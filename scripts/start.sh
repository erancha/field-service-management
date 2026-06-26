#!/usr/bin/env bash
#
# Single entry point for running the Field Service Management app.
#
#   ./scripts/start.sh                       # both roles on the host (technician + customer)
#   ./scripts/start.sh technician            # one role on the host  (alias: tec)  -> http://localhost:8001
#   ./scripts/start.sh customer              # one role on the host  (alias: cus)  -> http://localhost:8002
#   ./scripts/start.sh both                  # both roles, stated explicitly       (alias: all)
#   ./scripts/start.sh --docker              # build + run both roles via docker compose (both = default)
#   ./scripts/start.sh technician --docker   # build + run one role via docker compose
#
# The first 3 letters of a role are enough (tec / cus); with no role, both run. Host mode
# provisions a virtualenv, starts PostgreSQL via Docker, applies migrations, builds the frontend,
# and runs uvicorn per role. --docker instead builds the backend image and brings the role(s) up as
# internal compose services (alongside db + a one-shot migration) behind an nginx edge that serves
# the SPA and is the only published port (80); reach the roles at technician/customer.localhost.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
VENV="$BACKEND/.venv"
COMPOSE="$ROOT/docker-compose.yml"

usage() {
  echo "Usage: ./scripts/start.sh [technician|customer|both] [--docker]   (default: both; aliases tec|cus|all)" >&2
  exit 2
}

# Print this script's header comment block as --help text (single source of usage docs).
print_help() { awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}"; }

port_for() { case "$1" in technician) echo 8001 ;; customer) echo 8002 ;; esac; }

# Selected roles, in invocation order and without duplicates.
ROLES=()
add_role() {
  local candidate="$1" existing
  if [ ${#ROLES[@]} -gt 0 ]; then
    for existing in "${ROLES[@]}"; do [ "$existing" = "$candidate" ] && return 0; done
  fi
  ROLES+=("$candidate")
}

DOCKER=0
for arg in "$@"; do
  case "$(printf '%s' "$arg" | tr '[:upper:]' '[:lower:]')" in
    tec*)      add_role technician ;;
    cus*)      add_role customer ;;
    both|all)  add_role technician; add_role customer ;;
    --docker)  DOCKER=1 ;;
    -h|--help) print_help; exit 0 ;;
    *)         usage ;;
  esac
done
[ ${#ROLES[@]} -gt 0 ] || { add_role technician; add_role customer; }

# backend/.env is required by both run paths (host mode sources it; docker compose loads it via
# env_file). It is not created here — run the init helper once first.
if [ ! -f "$BACKEND/.env" ]; then
  echo "backend/.env not found — create it first:  ./scripts/init-env.sh" >&2
  exit 1
fi

# Probe a role's backend through the nginx edge by Host header — the backends are internal to the
# compose network and not published on the host. --retry-all-errors also retries the 502s nginx
# returns while the backend is still warming up.
wait_for_edge() {  # role
  curl -fs --retry 60 --retry-all-errors --retry-delay 1 -o /dev/null \
    -H "Host: $1.localhost" "http://localhost/health"
}

if [ "$DOCKER" -eq 1 ]; then
  echo "Deploying [${ROLES[*]}] to Docker (db + migrations + ${ROLES[*]} + nginx edge)..."
  # nginx fronts both roles, so it pulls both backends up via depends_on regardless of selection.
  docker compose -f "$COMPOSE" up -d --build nginx "${ROLES[@]}"
  for role in "${ROLES[@]}"; do
    wait_for_edge "$role"
    echo "FSM ($role): http://$role.localhost  (via nginx :80)"
  done
  echo "  nginx edge on :80 is the only published entry — open http://technician.localhost /"
  echo "  http://customer.localhost   (per host: /  (SPA)   /docs   /health   /ready)"
  echo "  backends are internal to the compose network; reach them via the edge."
  exit 0
fi

# --- host mode: provision (idempotent, shared by every role) ---
command -v npm >/dev/null 2>&1 || { echo "npm not found — install Node.js + npm and retry." >&2; exit 1; }
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/python" -c "import fsm" 2>/dev/null \
  || ( cd "$BACKEND" && "$VENV/bin/pip" install --quiet --disable-pip-version-check -e ".[dev]" )
set -a; . "$BACKEND/.env"; set +a

docker compose -f "$COMPOSE" up -d db

printf 'Waiting for PostgreSQL'
for _ in $(seq 1 30); do
  if docker compose -f "$COMPOSE" exec -T db pg_isready -U fsm >/dev/null 2>&1; then
    echo " ready."; break
  fi
  printf '.'; sleep 1
done

( cd "$BACKEND" && "$VENV/bin/alembic" upgrade head )

# Build the React app and serve it from FastAPI at "/" (Node + npm required, checked above).
FRONTEND="$ROOT/frontend"
echo "Building frontend..."
( cd "$FRONTEND" && { [ -d node_modules ] || npm install --no-audit --no-fund; } && npm run build )
export FSM_FRONTEND_DIST="$FRONTEND/dist"

# Run one uvicorn per role as a background child and wait on all of them, so a single Ctrl-C
# (delivered to the whole process group) tears every role down together.
pids=()
cleanup() { [ ${#pids[@]} -gt 0 ] && kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup INT TERM EXIT

echo "Starting [${ROLES[*]}]  (/: React app, docs: /docs, health: /health, ready: /ready)"
for role in "${ROLES[@]}"; do
  port="$(port_for "$role")"
  echo "  FSM ($role) -> http://localhost:$port"
  ( cd "$BACKEND" && FSM_ROLE="$role" exec "$VENV/bin/uvicorn" fsm.platform.app:create_app --factory --reload --port "$port" ) &
  pids+=($!)
done
wait
