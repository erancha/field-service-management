#!/usr/bin/env bash
#
# Run all available tests for the Field Service Management repo.
#
#   ./scripts/test.sh            # backend + frontend
#   ./scripts/test.sh backend    # backend only  (alias: be)
#   ./scripts/test.sh frontend   # frontend only (alias: fe)
#
# Backend: import-linter boundary contracts + pytest (unit, integration, API, contract,
# architecture). Integration tests start ephemeral PostgreSQL via testcontainers, so Docker must be
# running. Frontend: typecheck (tsc), lint (oxlint), unit/component tests (vitest), and a
# production build (vite).
# The test taxonomy is documented in docs/testing.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv"

# Print this script's header comment block as --help text (single source of usage docs).
print_help() { awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}"; }

TARGET="all"
for arg in "$@"; do
  case "$(printf '%s' "$arg" | tr '[:upper:]' '[:lower:]')" in
    be*|back*)  TARGET="backend" ;;
    fe*|front*) TARGET="frontend" ;;
    -h|--help)  print_help; exit 0 ;;
    *) echo "Usage: ./scripts/test.sh [backend|frontend]   (first letters suffice: be | fe)" >&2; exit 2 ;;
  esac
done

run_backend() {
  echo "==> Backend"
  [ -d "$VENV" ] || python3 -m venv "$VENV"
  "$VENV/bin/python" -c "import fsm" 2>/dev/null \
    || ( cd "$BACKEND" && "$VENV/bin/pip" install --quiet --disable-pip-version-check -e ".[dev]" )
  echo "--> import-linter (architecture boundary contracts)"
  ( cd "$BACKEND" && "$VENV/bin/lint-imports" )
  echo "--> pytest (unit + integration + API + contract)"
  ( cd "$BACKEND" && "$VENV/bin/pytest" )
}

run_frontend() {
  echo "==> Frontend"
  if ! command -v npm >/dev/null 2>&1; then
    echo "npm not found — skipping frontend checks."
    return 0
  fi
  [ -d "$FRONTEND/node_modules" ] || ( cd "$FRONTEND" && npm install --no-audit --no-fund )
  echo "--> typecheck (tsc --noEmit)"
  ( cd "$FRONTEND" && npx tsc --noEmit )
  echo "--> lint (oxlint)"
  ( cd "$FRONTEND" && npm run --silent lint )
  echo "--> unit/component tests (vitest)"
  ( cd "$FRONTEND" && npm run --silent test )
  echo "--> build (vite)"
  ( cd "$FRONTEND" && npm run --silent build )
}

case "$TARGET" in
  backend)  run_backend ;;
  frontend) run_frontend ;;
  all)      run_backend; run_frontend ;;
esac

echo "All requested tests passed."
