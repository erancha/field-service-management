#!/usr/bin/env bash
#
# Run all available tests for the Field Service Management repo.
#
#   ./scripts/test.sh                        # backend + frontend (default)
#   ./scripts/test.sh all                    # backend + frontend (explicit)
#   ./scripts/test.sh backend                # backend only  (alias: be)
#   ./scripts/test.sh frontend               # frontend, full (alias: fe)
#   ./scripts/test.sh frontend=unit          # frontend fast path only (alias: fe=u)
#   ./scripts/test.sh backend frontend=unit  # combine targets: full backend + fast frontend
#   ./scripts/test.sh e2e                    # cross-process SSE sample stack (docker compose)
#
# Each argument is a target with an optional =mode. Targets combine, so several may be given.
#
# Backend: lint (ruff), typecheck (mypy), import-linter boundary contracts, and pytest (unit,
# integration, API, contract, architecture). Integration tests start ephemeral PostgreSQL via
# testcontainers, so Docker must be running. Frontend: typecheck (tsc), lint (oxlint),
# unit/component tests (vitest), and a production build (vite).
# The =unit mode is a frontend inner-loop shortcut that keeps the typecheck but skips oxlint and the
# vite build; run the full frontend target before committing. It applies to the frontend only. The
# e2e target is opt-in and never part of the default: it builds and starts the
# samples/redis_event_bus_with_sse compose stack and asserts the cross-process SSE round trip. The
# test taxonomy is documented in docs/testing.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv"

# Print this script's header comment block as --help text (single source of usage docs).
print_help() { awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}"; }

usage() {
  echo "Usage: ./scripts/test.sh [all|backend|frontend[=unit]|e2e] ...   (first letters suffice: be | fe | u)" >&2
  exit 2
}

RUN_BACKEND=false
RUN_FRONTEND=false
RUN_E2E=false
FRONTEND_MODE="full"
selected=false

for arg in "$@"; do
  raw="$(printf '%s' "$arg" | tr '[:upper:]' '[:lower:]')"
  name="${raw%%=*}"
  mode="${raw#*=}"
  [ "$mode" = "$raw" ] && mode=""   # no '=' present → no mode attached

  case "$name" in
    -h|--help)  print_help; exit 0 ;;
    all)        RUN_BACKEND=true; RUN_FRONTEND=true; fe_arg=true ;;
    be*|back*)  RUN_BACKEND=true; fe_arg=false ;;
    fe*|front*) RUN_FRONTEND=true; fe_arg=true ;;
    e*)         RUN_E2E=true; fe_arg=false ;;
    *) usage ;;
  esac
  selected=true

  if [ -n "$mode" ]; then
    [ "$fe_arg" = true ] || { echo "=$mode applies to the frontend only (got: $arg)" >&2; exit 2; }
    case "$mode" in
      u*|unit) FRONTEND_MODE="unit" ;;
      full)    FRONTEND_MODE="full" ;;
      *) usage ;;
    esac
  fi
done

# No target arguments runs everything, matching the documented default.
if [ "$selected" = false ]; then
  RUN_BACKEND=true
  RUN_FRONTEND=true
fi

run_backend() {
  echo "==> Backend"
  [ -d "$VENV" ] || python3 -m venv "$VENV"
  # The venv is current only when it was installed from pyproject.toml as it stands now: the stamp
  # is a copy taken after the last successful install, so editing the dependency list forces a
  # reinstall instead of leaving the venv without the new package until an import fails mid-suite.
  # The import/executable probe still catches a venv that is broken with the stamp intact.
  DEPS_STAMP="$VENV/.pyproject.stamp"
  if ! cmp -s "$BACKEND/pyproject.toml" "$DEPS_STAMP" \
     || ! { "$VENV/bin/python" -c "import fsm" 2>/dev/null && [ -x "$VENV/bin/ruff" ] && [ -x "$VENV/bin/mypy" ]; }; then
    ( cd "$BACKEND" && "$VENV/bin/pip" install --quiet --disable-pip-version-check -e ".[dev]" )
    cp "$BACKEND/pyproject.toml" "$DEPS_STAMP"
  fi
  echo "--> lint (ruff)"
  ( cd "$BACKEND" && "$VENV/bin/ruff" check src tests )
  echo "--> typecheck (mypy)"
  ( cd "$BACKEND" && "$VENV/bin/mypy" )
  echo "--> import-linter (architecture boundary contracts)"
  ( cd "$BACKEND" && "$VENV/bin/lint-imports" )
  echo "--> pytest (unit + integration + API + contract)"
  ( cd "$BACKEND" && "$VENV/bin/pytest" )
}

run_frontend() {
  echo "==> Frontend"
  if ! command -v npm >/dev/null 2>&1; then
    # Skipping is a dev convenience only; under CI a missing npm must fail, not pass silently.
    if [ -n "${CI:-}" ]; then
      echo "npm not found and CI is set — frontend checks cannot run." >&2
      return 1
    fi
    echo "npm not found — skipping frontend checks."
    return 0
  fi
  # npm ci installs the lockfile verbatim; npm install may re-resolve and mutate it.
  [ -d "$FRONTEND/node_modules" ] || ( cd "$FRONTEND" && npm ci --no-audit --no-fund )
  echo "--> typecheck (tsc --noEmit)"
  ( cd "$FRONTEND" && npx tsc --noEmit )
  if [ "$FRONTEND_MODE" != unit ]; then
    echo "--> lint (oxlint)"
    ( cd "$FRONTEND" && npm run --silent lint )
  fi
  echo "--> unit/component tests (vitest)"
  ( cd "$FRONTEND" && npm run --silent test )
  if [ "$FRONTEND_MODE" != unit ]; then
    echo "--> build (vite)"
    ( cd "$FRONTEND" && npm run --silent build )
  fi
}

run_e2e() {
  echo "==> E2E (samples/redis_event_bus_with_sse)"
  "$ROOT/samples/redis_event_bus_with_sse/test.sh"
}

if [ "$RUN_BACKEND" = true ]; then run_backend; fi
if [ "$RUN_FRONTEND" = true ]; then run_frontend; fi
if [ "$RUN_E2E" = true ]; then run_e2e; fi

echo "All requested tests passed."
