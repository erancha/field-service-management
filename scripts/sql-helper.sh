#!/usr/bin/env bash
#
# Run psql against the Field Service Management Postgres container (db service, fsm database).
#
#   ./scripts/sql-helper.sh                   open an interactive psql shell
#   ./scripts/sql-helper.sh [psql-args...]    forward args to psql, e.g. -c "SELECT 1"
#   ./scripts/sql-helper.sh -f <file>         run a host SQL file (streamed in via stdin)
#   --context <name>                          reach another Docker daemon's stack; must come first,
#                                             since every later argument is forwarded to psql
#   -h, --help                                show this help
#
# Examples:
#   ./scripts/sql-helper.sh -tA -c "SELECT count(*) FROM appointment;"
#   ./scripts/sql-helper.sh -f scripts/all-tables.sql   # row counts for every table
#   ./scripts/sql-helper.sh --context fsm-ec2 -tA -c "SELECT count(*) FROM users;"
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"

# Selects the Docker daemon holding the database. Empty means the caller's current context, so a bare
# invocation reaches the local stack; --context fsm-ec2 opens psql inside the deployed stack's
# container without publishing Postgres beyond the box's loopback interface.
DOCKER_CONTEXT_ARGS=()
if [[ "${1:-}" == "--context" ]]; then
  DOCKER_CONTEXT_ARGS=(--context "${2:?--context needs a context name}")
  shift 2
fi

# Pin compose's project directory to the repo root so the service name and project resolve the same
# regardless of the caller's working directory.
compose() { (cd "$ROOT_DIR" && docker "${DOCKER_CONTEXT_ARGS[@]}" compose -f "$COMPOSE_FILE" "$@"); }

require_docker() {
  docker "${DOCKER_CONTEXT_ARGS[@]}" info >/dev/null 2>&1 \
    || { echo "Docker is not reachable — start Docker (or the deployment box) and retry." >&2; exit 1; }
}

# Print this script's header comment block as --help text (single source of usage docs).
print_help() { awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}"; }

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  print_help
  exit 0
fi

# -f names a path on the host, not inside the container, so the file is streamed in via stdin
# rather than psql's own -f (which would resolve the path container-side).
SQL_FILE=""
if [[ "${1:-}" == "-f" || "${1:-}" == "--file" ]]; then
  SQL_FILE="${2:-}"
  if [[ -z "$SQL_FILE" || ! -f "$SQL_FILE" ]]; then
    echo "SQL file not found: ${SQL_FILE:-<none given>}" >&2
    exit 1
  fi
  shift 2
fi

require_docker

PSQL=(psql -U fsm -d fsm)
if [[ -n "$SQL_FILE" ]]; then
  compose exec -T db "${PSQL[@]}" "$@" < "$SQL_FILE"
else
  compose exec -T db "${PSQL[@]}" "$@"
fi
