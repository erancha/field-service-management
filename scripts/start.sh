#!/usr/bin/env bash
#
# Single entry point for running the Field Service Management app.
#
#   ./scripts/start.sh technician            # run on the host  (alias: tec)  -> http://localhost:8001
#   ./scripts/start.sh customer              # run on the host  (alias: cus)  -> http://localhost:8002
#   ./scripts/start.sh technician --docker   # build + run as a container via docker compose
#   ./scripts/start.sh customer   --docker
#
# The first 3 letters of the role are enough (tec / cus). Host mode provisions a
# virtualenv, starts PostgreSQL via Docker, applies migrations, and runs uvicorn.
# --docker instead builds the backend image and brings the role up as a compose
# service (alongside db + a one-shot migration), publishing its port on the host.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
VENV="$BACKEND/.venv"
COMPOSE="$ROOT/docker-compose.yml"

usage() {
  echo "Usage: ./scripts/start.sh technician|customer [--docker]   (first 3 letters suffice: tec | cus)" >&2
  exit 2
}

# Print this script's header comment block as --help text (single source of usage docs).
print_help() { awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}"; }

ROLE=""
DOCKER=0
for arg in "$@"; do
  case "$(printf '%s' "$arg" | tr '[:upper:]' '[:lower:]')" in
    tec*)      ROLE=technician; PORT=8001 ;;
    cus*)      ROLE=customer;   PORT=8002 ;;
    --docker)  DOCKER=1 ;;
    -h|--help) print_help; exit 0 ;;
    *)         usage ;;
  esac
done
[ -n "$ROLE" ] || usage

# backend/.env is required by both run paths (host mode sources it; docker compose loads it via
# env_file). It is not created here — run the init helper once first.
if [ ! -f "$BACKEND/.env" ]; then
  echo "backend/.env not found — create it first:  ./scripts/init-env.sh" >&2
  exit 1
fi

wait_for_http() {
  curl -s --retry 60 --retry-connrefused --retry-delay 1 -o /dev/null "http://localhost:$PORT/health"
}

if [ "$DOCKER" -eq 1 ]; then
  echo "Deploying '$ROLE' to Docker (db + migrations + $ROLE)..."
  docker compose -f "$COMPOSE" up -d --build "$ROLE"
  wait_for_http
  echo "FSM ($ROLE) running in Docker at http://localhost:$PORT"
  echo "  landing: /   docs: /docs   health: /health   ready: /ready"
  exit 0
fi

# --- host mode: provision (idempotent) ---
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

echo "Starting FSM ($ROLE) on http://localhost:$PORT  (/: React app, docs: /docs, health: /health, ready: /ready)"
cd "$BACKEND"
FSM_ROLE="$ROLE" exec "$VENV/bin/uvicorn" fsm.platform.app:create_app --factory --reload --port "$PORT"
