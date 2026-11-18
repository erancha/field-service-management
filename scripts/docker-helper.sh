#!/usr/bin/env bash
#
# Docker Compose helper for the stack: teardown, logs, status. Bringing it up is deploy.sh's job.
# With --ec2 as the first argument it acts on the stack's EC2 instance instead of this machine.
#
#   ./scripts/docker-helper.sh --stop [--volumes]
#       Stop and remove the stack's containers and network. The fsm_pgdata volume (the database)
#       and the fsm_objectstore volume (the customers' photos) are KEPT by default so they survive
#       a restart; --volumes (alias -v) also removes both for a clean start.
#   ./scripts/docker-helper.sh --logs [-e|--errors|-w|--warnings] [--grep <pattern>]
#                                     [--since <duration>] [--sorted] [service...]
#       Follow the stack's logs live (last 200 lines). -e filters to ERROR/EXCEPTION/FATAL lines,
#       -w adds WARN lines, --grep filters to a case-insensitive regular expression, and --since
#       limits the window (10m, 1h). A trailing service list (db redis objectstore migrate
#       technician customer backoffice worker nginx) narrows to those services. --sorted prints
#       the window once instead of following it, merged across services and ordered by the
#       timestamp each app line opens with: a live follow prints each container's lines as they
#       arrive, so lines logged microseconds apart by different replicas can print out of order.
#       Lines without a leading timestamp (nginx access lines, tracebacks) sort by their text, so
#       pair --sorted with --grep or a list of the backend services.
#   ./scripts/docker-helper.sh --ps
#       Show the containers' status.
#   ./scripts/docker-helper.sh --ec2 --delete-stack
#       Delete the git branch's three EC2 stacks, one per role: each one's port on loan-simulator's
#       instance and its CloudFront distribution, after asking to type each stack's name. The
#       containers and volumes stay on the instance; run --ec2 --stop [--volumes] first to remove
#       them.
#   -h, --help
#
# Examples:
#   # a live event across the roles, one line per delivery hop, each prefixed with its replica
#   # (published -> received -> delivering -> SSE stream open/close):
#   ./scripts/docker-helper.sh --logs --grep 'published|received|delivering|SSE stream' \
#     technician customer backoffice worker
#   # the same hops afterwards, in timestamp order:
#   ./scripts/docker-helper.sh --logs --sorted --since 10m \
#     --grep 'published|received|delivering|SSE stream' technician customer backoffice worker
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

do_stop() {  # [-v|--volumes], checked below before anything runs
  local -a down=(down --remove-orphans)
  [ $# -eq 0 ] || down+=(-v)
  compose "${down[@]}"
}

# The --logs options, read before any settings file, AWS or Docker is touched. The service list
# after them stays in LOG_SERVICES.
LOG_PATTERN=""
LOG_FOLLOW=true
LOG_SINCE=()
LOG_SERVICES=()
parse_logs_options() {
  while [ $# -gt 0 ]; do
    case "$1" in
      -e|--errors)   LOG_PATTERN='(error|exception|fatal)'; shift ;;
      -w|--warnings) LOG_PATTERN='(warn|warning|error|exception|fatal)'; shift ;;
      --grep)
        [ -n "${2:-}" ] || { echo "--grep needs a pattern" >&2; exit 1; }
        LOG_PATTERN="$2"; shift 2 ;;
      --since)
        [ -n "${2:-}" ] || { echo "--since needs a duration" >&2; exit 1; }
        LOG_SINCE=(--since "$2"); shift 2 ;;
      --sorted)      LOG_FOLLOW=false; shift ;;
      -*)            echo "Unknown --logs option '$1'" >&2; exit 1 ;;
      *)             LOG_SERVICES+=("$1"); shift ;;
    esac
  done
}

# The sort key is everything after the service-name column, which app lines open with their own
# ISO-8601 UTC timestamp: fixed width, so text order is time order.
do_logs() {
  local -a args=(logs --tail=200)
  if $LOG_FOLLOW; then args+=(-f); fi
  args+=("${LOG_SINCE[@]}" "${LOG_SERVICES[@]}")
  local -a filter=(cat) order=(cat)
  if [ -n "$LOG_PATTERN" ]; then filter=(grep -Eai "$LOG_PATTERN"); fi
  if ! $LOG_FOLLOW; then order=(sort -t'|' -k2 -s); fi
  compose "${args[@]}" | "${filter[@]}" | "${order[@]}"
}

TARGET=local
if [ "${1:-}" = --ec2 ]; then TARGET=ec2; shift; fi
mode="${1:-}"
case "$mode" in
  -h|--help) print_help; exit 0 ;;
  "")        print_help; exit 1 ;;
esac
shift

# The arguments are checked before any settings file, AWS or Docker is touched.
case "$mode" in
  --stop)
    for arg in "$@"; do
      case "$arg" in -v|--volumes) ;; *) echo "Unknown --stop option '$arg'" >&2; exit 1 ;; esac
    done ;;
  --ps|--delete-stack)
    [ $# -eq 0 ] || { echo "$mode takes no arguments (got: $*)" >&2; exit 1; } ;;
  --logs) parse_logs_options "$@" ;;
  *) echo "Unknown command: $mode (expected --stop | --logs | --ps | --delete-stack; see -h)" >&2
     exit 1 ;;
esac

load_settings
if [ "$mode" = --delete-stack ]; then
  [ "$TARGET" = ec2 ] || { echo "--delete-stack needs --ec2 before it" >&2; exit 2; }
  refuse_stack_name
  for role in "${ROLES[@]}"; do
    select_ec2_role "$role"
    delete_ec2_stack
  done
  exit 0
fi
if [ "$TARGET" = ec2 ]; then use_ec2_roles; fi
require_docker
case "$mode" in
  --stop) do_stop "$@" ;;
  --logs) do_logs ;;
  --ps)   compose ps ;;
esac
