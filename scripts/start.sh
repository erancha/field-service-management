#!/usr/bin/env bash
#
# Single entry point for running the Field Service Management app. Either mode reaches the roles at
# the same URLs — http://localhost:8001 (technician) / :8002 (customer) / :8003 (backoffice) — and
# each completes Google sign-in with the same registered localhost callbacks. Docker is the default (a
# closer-to-production stack); --host runs the roles as local uvicorn processes for fast boot and
# debugger attach. They differ only in packaging, not capability.
#
#   ./scripts/start.sh                       # all roles via docker compose, nginx on :8001/:8002/:8003 (default)
#   ./scripts/start.sh technician            # one role (alias: tec) -> http://localhost:8001
#   ./scripts/start.sh --host                # all roles as local uvicorn processes, same ports
#   ./scripts/start.sh technician --host     # one role on the host  -> http://localhost:8001
#
# The first 3 letters of a role are enough (tec / cus / bac); with no role, all roles run. Docker mode
# builds the backend image and brings the role(s) up as internal compose services (alongside db,
# redis, minio, and a one-shot migration) behind an nginx edge that serves the SPA and publishes one
# localhost port per role. Host mode provisions a virtualenv, starts PostgreSQL + Redis + MinIO via
# Docker, applies migrations, builds the frontend, and runs uvicorn per role directly on those ports.
#
# Bring the stack down or tail logs with scripts/docker-helper.sh (--stop / --logs / --ps).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
VENV="$BACKEND/.venv"
COMPOSE="$ROOT/docker-compose.yml"

usage() {
  echo "Usage: ./scripts/start.sh [technician|customer|backoffice|all] [--host]   (default: all roles, docker; aliases tec|cus|bo)" >&2
  exit 2
}

# Print this script's header comment block as --help text (single source of usage docs).
print_help() { awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}"; }

port_for() { case "$1" in technician) echo 8001 ;; customer) echo 8002 ;; backoffice) echo 8003 ;; esac; }

# Selected roles, in invocation order and without duplicates.
ROLES=()
add_role() {
  local candidate="$1" existing
  if [ ${#ROLES[@]} -gt 0 ]; then
    for existing in "${ROLES[@]}"; do [ "$existing" = "$candidate" ] && return 0; done
  fi
  ROLES+=("$candidate")
}

DOCKER=1
for arg in "$@"; do
  case "$(printf '%s' "$arg" | tr '[:upper:]' '[:lower:]')" in
    tec*)           add_role technician ;;
    cus*)           add_role customer ;;
    bac*|bo)        add_role backoffice ;;
    all)            add_role technician; add_role customer; add_role backoffice ;;
    --docker)       DOCKER=1 ;;
    --host|--local) DOCKER=0 ;;
    -h|--help)      print_help; exit 0 ;;
    *)              usage ;;
  esac
done
[ ${#ROLES[@]} -gt 0 ] || { add_role technician; add_role customer; add_role backoffice; }

# backend/.env is required by either run path (host mode sources it; docker compose loads it via
# env_file). It is not created here — run the init helper once first.
if [ ! -f "$BACKEND/.env" ]; then
  echo "backend/.env not found — create it first:  ./scripts/init-env.sh" >&2
  exit 1
fi

# Probe a role through the nginx edge on its published localhost port — the backends themselves are
# internal to the compose network. --retry-all-errors also retries the 502s nginx returns while the
# backend is still warming up.
wait_for_edge() {  # port
  curl -fs --retry 60 --retry-all-errors --retry-delay 1 -o /dev/null "http://localhost:$1/health"
}

if [ "$DOCKER" -eq 1 ]; then
  echo "Deploying [${ROLES[*]}] to Docker (db + migrations + ${ROLES[*]} + nginx edge)..."
  # nginx fronts all roles, so it pulls all backends up via depends_on regardless of selection.
  docker compose -f "$COMPOSE" up -d --build nginx "${ROLES[@]}"
  for role in "${ROLES[@]}"; do
    port="$(port_for "$role")"
    wait_for_edge "$port"
    echo "  FSM ($role) -> http://localhost:$port"
  done
  echo "  nginx serves each role on its own localhost port (SPA at /, plus /docs /health /ready)."
  echo "  stop the stack or tail logs:  ./scripts/docker-helper.sh --stop | --logs"
  exit 0
fi

# --- host mode: provision (idempotent, shared by every role) ---
command -v npm >/dev/null 2>&1 || { echo "npm not found — install Node.js + npm and retry." >&2; exit 1; }
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/python" -c "import fsm" 2>/dev/null \
  || ( cd "$BACKEND" && "$VENV/bin/pip" install --quiet --disable-pip-version-check -e ".[dev]" )
set -a; . "$BACKEND/.env"; set +a

# Cross-process SSE needs a shared broker: each role runs as its own uvicorn, so the in-memory bus
# cannot reach across them. Point every role process at the published Redis unless .env overrides it.
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"

docker compose -f "$COMPOSE" up -d db redis minio

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

# The backoffice process additionally runs the background calendar workers — draining the outbox to
# Google (outbound projection) and polling Google for technician-side edits (inbound sync). Exactly
# one process may run them so a single owner drains the shared outbox and Google is polled once;
# backoffice is that owner, so the projection only runs when this role is part of the launch.
echo "Starting [${ROLES[*]}]  (/: React app, docs: /docs, health: /health, ready: /ready)"
for role in "${ROLES[@]}"; do
  port="$(port_for "$role")"
  echo "  FSM ($role) -> http://localhost:$port"
  role_env=(FSM_ROLE="$role")
  # Backoffice owns the calendar workers; the dispatcher writes photo links into events, so the
  # role that enables it also supplies the technician edge's address the links must land on.
  [ "$role" = backoffice ] && role_env+=(
    FSM_DISPATCH_ENABLED=true FSM_SYNC_ENABLED=true
    TECHNICIAN_APP_URL="${TECHNICIAN_APP_URL:-http://localhost:8001}"
  )
  ( cd "$BACKEND" && exec env "${role_env[@]}" "$VENV/bin/uvicorn" fsm.platform.app:create_app --factory --port "$port" ) &
  pids+=($!)
done
wait
