#!/usr/bin/env bash
#
# Behavioral tests for the frontend bootstrap path of scripts/test.sh:
#   1. A clean install (no node_modules) must use `npm ci`, so the lockfile is honored verbatim.
#   2. When npm is absent and CI is set, the script must fail instead of passing silently.
#   3. When npm is absent outside CI, the script keeps skipping frontend checks (dev convenience).
#
#   ./scripts/tests/test_sh_frontend_bootstrap.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_SH="$ROOT/scripts/test.sh"
BASH_BIN="$(command -v bash)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "FAIL: $1" >&2; exit 1; }

# --- 1. Clean install uses `npm ci` -------------------------------------------------------------
# Copy test.sh into a temp repo whose frontend/ has no node_modules, and stub npm/npx so the
# whole frontend run succeeds while every npm invocation is recorded.
mkdir -p "$TMP/repo/scripts" "$TMP/repo/frontend" "$TMP/stubs"
cp "$TEST_SH" "$TMP/repo/scripts/test.sh"
NPM_LOG="$TMP/npm-calls.log"
printf '#!/usr/bin/env bash\necho "$@" >> "%s"\nexit 0\n' "$NPM_LOG" > "$TMP/stubs/npm"
printf '#!/usr/bin/env bash\nexit 0\n' > "$TMP/stubs/npx"
chmod +x "$TMP/stubs/npm" "$TMP/stubs/npx"

PATH="$TMP/stubs:$PATH" "$BASH_BIN" "$TMP/repo/scripts/test.sh" frontend >/dev/null \
  || fail "test.sh frontend errored with stubbed npm/npx"
first_call="$(head -n 1 "$NPM_LOG")"
case "$first_call" in
  ci\ *|ci) echo "ok: clean install runs 'npm ci' ($first_call)" ;;
  *) fail "clean install ran 'npm $first_call' instead of 'npm ci'" ;;
esac

# --- 2. Missing npm under CI fails loudly --------------------------------------------------------
# A PATH holding only the non-builtin commands test.sh needs (dirname, tr) guarantees npm is absent.
mkdir -p "$TMP/thin-bin"
ln -s "$(command -v dirname)" "$TMP/thin-bin/dirname"
ln -s "$(command -v tr)" "$TMP/thin-bin/tr"
ln -s "$(command -v env)" "$TMP/thin-bin/env"

if PATH="$TMP/thin-bin" CI=true "$BASH_BIN" "$TEST_SH" frontend >/dev/null 2>&1; then
  fail "test.sh frontend exited 0 under CI without npm"
fi
echo "ok: missing npm under CI exits nonzero"

# --- 3. Missing npm outside CI still skips -------------------------------------------------------
out="$(PATH="$TMP/thin-bin" env -u CI "$BASH_BIN" "$TEST_SH" frontend)" \
  || fail "test.sh frontend failed outside CI without npm (should skip)"
case "$out" in
  *skipping*) echo "ok: missing npm outside CI skips frontend checks" ;;
  *) fail "expected a skip notice without npm outside CI, got: $out" ;;
esac

echo "All test.sh frontend bootstrap tests passed."
