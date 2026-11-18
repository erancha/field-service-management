#!/usr/bin/env bash
#
# Run the test suites of Field Service Management.
#
#   ./scripts/test.sh                # backend + frontend (default)
#   ./scripts/test.sh all            # backend + frontend (explicit)
#   ./scripts/test.sh backend        # the backend in backend/ and the scripts  (alias: be)
#   ./scripts/test.sh frontend       # the role apps in frontend/  (alias: fe)
#   ./scripts/test.sh e2e            # the cross-process SSE sample stack in Docker
#
# Targets combine, so several may be given.
#
# The backend target runs: the scripts' syntax check (bash -n) and their shell tests under
# scripts/tests/, lint (ruff), typecheck (mypy), import-linter layer contracts, and pytest (unit,
# integration, API, contract and architecture tests), whose integration tests start an ephemeral
# Postgres and object store via Testcontainers, so Docker must be running. The frontend target
# runs lint (oxlint), component tests (vitest), then the typecheck (tsc) and production build
# (vite) that npm run build chains.
#
# The e2e target is opt-in and never part of the default: it builds and starts the
# samples/redis_event_bus_with_sse compose stack and asserts the cross-process SSE round trip. The
# test layers are described in docs/testing.md.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

usage() {
  echo "Usage: ./scripts/test.sh [all|backend|frontend|e2e] ... (aliases: be, fe)" >&2
  exit 2
}

RUN_BACKEND=false
RUN_FRONTEND=false
RUN_E2E=false
selected=false

for arg in "$@"; do
  case "$(printf '%s' "$arg" | tr '[:upper:]' '[:lower:]')" in
    -h|--help)   print_help; exit 0 ;;
    all)         RUN_BACKEND=true; RUN_FRONTEND=true ;;
    be|backend)  RUN_BACKEND=true ;;
    fe|frontend) RUN_FRONTEND=true ;;
    e2e)         RUN_E2E=true ;;
    *) usage ;;
  esac
  selected=true
done

if [ "$selected" = false ]; then
  RUN_BACKEND=true
  RUN_FRONTEND=true
fi

run_backend() {
  echo "==> Backend"
  echo "--> scripts (bash -n, shell tests)"
  for script in "$ROOT"/scripts/*.sh "$ROOT"/scripts/lib/*.sh "$ROOT"/scripts/tools/*.sh \
      "$ROOT"/scripts/tests/*.sh "$ROOT/.githooks/pre-commit"; do
    bash -n "$script"
  done
  for check in "$ROOT"/scripts/tests/test_*.sh; do bash "$check"; done
  ensure_backend_venv
  echo "--> lint (ruff)"
  ( cd "$BACKEND" && "$BACKEND_VENV/bin/ruff" check src tests )
  echo "--> typecheck (mypy)"
  ( cd "$BACKEND" && "$BACKEND_VENV/bin/mypy" )
  echo "--> import-linter (layer contracts)"
  ( cd "$BACKEND" && "$BACKEND_VENV/bin/lint-imports" )
  echo "--> pytest"
  ( cd "$BACKEND" && "$BACKEND_VENV/bin/pytest" )
}

run_frontend() {
  echo "==> Frontend"
  command -v npm >/dev/null 2>&1 \
    || { echo "npm not found; install Node.js 22 and retry." >&2; exit 1; }
  # npm ci installs the lockfile verbatim; npm install may re-resolve and mutate it. npm writes
  # node_modules/.package-lock.json on install, so a lockfile newer than it was edited since.
  if [ ! "$FRONTEND/node_modules/.package-lock.json" -nt "$FRONTEND/package-lock.json" ]; then
    ( cd "$FRONTEND" && npm ci --no-audit --no-fund )
  fi
  echo "--> lint (oxlint)"
  ( cd "$FRONTEND" && npm run --silent lint )
  echo "--> component tests (vitest)"
  ( cd "$FRONTEND" && npm run --silent test )
  echo "--> typecheck and build (tsc -b, vite build)"
  ( cd "$FRONTEND" && npm run --silent build )
}

run_e2e() {
  echo "==> E2E (samples/redis_event_bus_with_sse)"
  "$ROOT/samples/redis_event_bus_with_sse/test.sh"
}

if [ "$RUN_BACKEND" = true ]; then run_backend; fi
if [ "$RUN_FRONTEND" = true ]; then run_frontend; fi
if [ "$RUN_E2E" = true ]; then run_e2e; fi

echo "All requested tests passed."
