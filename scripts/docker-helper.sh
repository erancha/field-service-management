#!/usr/bin/env bash
#
# Thin Docker Compose helper for the Field Service Management stack: teardown and scoped logs.
# Bringing the stack UP stays in start.sh (it also provisions the venv, builds the SPA, and applies
# migrations); this helper owns the compose operations start.sh does not.
#
#   ./scripts/docker-helper.sh --stop [--volumes] [--prune[=images|volumes|all]]
#       Stop and remove the stack's containers and network. Volumes are KEPT by default so the
#       Postgres data survives a restart; --volumes (alias -v) also removes them for a clean
#       database. --prune additionally clears this project's dangling images and/or volumes (bare
#       --prune = all), label-scoped to the FSM compose project so other stacks are never touched.
#       Pruning volumes is refused unless --volumes is also given, since it would delete the kept
#       Postgres volume.
#   ./scripts/docker-helper.sh --logs [-e|--errors|-w|--warnings] [--grep <pat>] [--since <dur>] [--sorted] [service...]
#       Follow logs live (last 200 lines). -e filters to ERROR/EXCEPTION/FATAL; -w widens that to
#       also include WARN; --grep <pat> filters to a case-insensitive regex; --since limits the
#       window (e.g. 10m, 1h). A trailing service list narrows to those services (technician
#       customer backoffice nginx db redis). --sorted dumps the window once instead of following,
#       merged across services and ordered by each line's own timestamp: the live follow prints
#       per-container pipes as they drain, so lines logged microseconds apart in different
#       replicas can print out of order. Sorting keys on the timestamp the app stamped, so it
#       reflects when each line was logged, not when Docker collected it. Lines whose message
#       does not start with a timestamp (nginx access logs, tracebacks) sort by their text —
#       pair --sorted with --grep or a service list that keeps timestamped app lines.
#   ./scripts/docker-helper.sh --ps
#       Show the stack's container status.
#   --context <name>
#       Operate the stack on another Docker daemon, given before the command — e.g.
#       `--context fsm-ec2 --logs -e backoffice` reaches the EC2 deployment (see
#       scripts/deploy-to-ec2/start.sh). Omitted, every command runs against the local daemon.
#   -h, --help
#
# --logs only: narrow to specific services by naming them last (--stop always takes the whole stack):
#   ./scripts/docker-helper.sh --logs -e backoffice   # follow errors from one service
#
# To skip a service, list the others. Combine with -e/-w to filter by severity too — e.g. warnings
# from everything except nginx, whose access logs otherwise flood a plain follow:
#   ./scripts/docker-helper.sh --logs -w $(docker compose -f docker-compose.yml config --services 2>/dev/null | grep -vx nginx)
#   ./scripts/docker-helper.sh --logs -w --since 1h $(docker compose -f docker-compose.yml config --services 2>/dev/null | grep -vx nginx)
#
# To follow a live event across the roles as one line per delivery hop, each prefixed with the replica
# that logged it (published -> received -> delivering -> SSE stream open/close):
#   ./scripts/docker-helper.sh --logs --grep 'published|received|delivering|SSE stream' technician customer backoffice worker
# Add --sorted (and optionally --since) to re-read those hops afterwards in true timestamp order:
#   ./scripts/docker-helper.sh --logs --sorted --since 10m --grep 'published|received|delivering|SSE stream' technician customer backoffice worker
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"

# Selects the Docker daemon for every call below. Empty means the caller's current context, so a bare
# invocation reaches the local stack. Passing --context here rather than switching the context
# globally leaves other shells, projects, and testcontainers pointed at the local daemon.
DOCKER_CONTEXT_ARGS=()
if [[ "${1:-}" == "--context" ]]; then
  DOCKER_CONTEXT_ARGS=(--context "${2:?--context needs a context name}")
  shift 2
fi

# Pin compose's project-directory to the repo root so relative build contexts and the default
# project name resolve the same regardless of the caller's working directory.
compose() { (cd "$ROOT_DIR" && docker "${DOCKER_CONTEXT_ARGS[@]}" compose -f "$COMPOSE_FILE" "$@"); }

# Compose's default project name: the repo dir basename, lowercased and stripped to the chars
# compose keeps. Used to label-scope prune so it only ever touches THIS stack's images/volumes.
compose_project() { basename "$ROOT_DIR" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-'; }

require_docker() {
  docker "${DOCKER_CONTEXT_ARGS[@]}" info >/dev/null 2>&1 \
    || { echo "Docker is not reachable — start Docker (or the deployment box) and retry." >&2; exit 1; }
}

# Print this script's header comment block as --help text (single source of usage docs).
print_help() { awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}"; }

do_stop() {
  local wipe=false prune=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -v|--volumes) wipe=true ;;
      --prune)      prune=all ;;
      --prune=*)    prune="${1#*=}" ;;
      *)            echo "Unknown --stop option '$1'" >&2; exit 1 ;;
    esac
    shift
  done

  case "$prune" in
    ""|images|volumes|all) ;;
    *) echo "--prune expects images|volumes|all (bare --prune = all)" >&2; exit 1 ;;
  esac
  if ! $wipe && [[ "$prune" == volumes || "$prune" == all ]]; then
    echo "--prune=$prune would delete the kept Postgres volume; pass --volumes too if that is intended." >&2
    exit 1
  fi

  if $wipe; then
    compose down -v --remove-orphans
  else
    compose down --remove-orphans
  fi

  local -a scope=(--filter "label=com.docker.compose.project=$(compose_project)")
  local -a d=(docker "${DOCKER_CONTEXT_ARGS[@]}")
  case "$prune" in
    images)  "${d[@]}" image  prune -f "${scope[@]}" ;;
    volumes) "${d[@]}" volume prune -f "${scope[@]}" ;;
    all)     "${d[@]}" image  prune -f "${scope[@]}"; "${d[@]}" volume prune -f "${scope[@]}" ;;
  esac
}

# Severity presets and --grep only choose what to match; the stream follows live unless --sorted
# turns it into a one-shot dump ordered by app timestamp. --since bounds the window. Remaining
# args name services to narrow to.
do_logs() {
  local pattern="" follow=true
  local -a since=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -e|--errors)   pattern='(error|exception|fatal)'; shift ;;
      -w|--warnings) pattern='(warn|warning|error|exception|fatal)'; shift ;;
      --grep)        pattern="${2:?--grep needs a pattern}"; shift 2 ;;
      --since)       since=(--since "${2:?--since needs a duration}"); shift 2 ;;
      --sorted)      follow=false; shift ;;
      *)             break ;;
    esac
  done

  local -a args=(logs --tail=200)
  $follow && args+=(-f)
  args+=("${since[@]}" "$@")

  # The sort key is everything after the service-name column, which app lines open with their own
  # ISO-8601 UTC timestamp — fixed-width, so plain lexicographic order is chronological order.
  if $follow && [[ -n "$pattern" ]]; then
    compose "${args[@]}" | grep -Eai "$pattern"
  elif $follow; then
    compose "${args[@]}"
  elif [[ -n "$pattern" ]]; then
    compose "${args[@]}" | grep -Eai "$pattern" | sort -t'|' -k2 -s
  else
    compose "${args[@]}" | sort -t'|' -k2 -s
  fi
}

mode="${1:-}"
case "$mode" in
  -h|--help) print_help; exit 0 ;;
  "")        print_help; exit 1 ;;
esac
shift

require_docker
case "$mode" in
  --stop) do_stop "$@" ;;
  --logs) do_logs "$@" ;;
  --ps)   compose ps "$@" ;;
  *) echo "Unknown command: $mode (expected --stop | --logs | --ps; see -h)" >&2; exit 1 ;;
esac
