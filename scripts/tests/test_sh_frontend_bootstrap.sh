#!/usr/bin/env bash
#
# Behavioral tests for the frontend bootstrap path of scripts/test.sh:
#   1. A clean install (no node_modules) must use `npm ci`, so the lockfile is honored verbatim.
#   2. When npm is absent, the script must fail and name Node.js instead of passing silently.
#
#   ./scripts/tests/test_sh_frontend_bootstrap.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASH_BIN="$(command -v bash)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "FAIL: $1" >&2; exit 1; }

# A copy of test.sh with the scripts it sources, in a repo whose frontend/ has no node_modules.
REPO="$TMP/repo"
mkdir -p "$REPO/scripts/lib" "$REPO/frontend" "$TMP/stubs"
cp "$ROOT/scripts/test.sh" "$ROOT/scripts/common.sh" "$REPO/scripts/"
cp "$ROOT/scripts/lib/settings-guard.sh" "$ROOT/scripts/lib/ec2.sh" "$REPO/scripts/lib/"
touch "$REPO/frontend/package-lock.json"

# --- 1. Clean install uses `npm ci` -------------------------------------------------------------
# A stub npm lets the whole frontend run succeed while every invocation is recorded.
NPM_LOG="$TMP/npm-calls.log"
printf '#!/usr/bin/env bash\necho "$@" >> "%s"\nexit 0\n' "$NPM_LOG" > "$TMP/stubs/npm"
chmod +x "$TMP/stubs/npm"

PATH="$TMP/stubs:$PATH" "$BASH_BIN" "$REPO/scripts/test.sh" frontend >/dev/null \
  || fail "test.sh frontend errored with a stubbed npm"
first_call="$(head -n 1 "$NPM_LOG")"
case "$first_call" in
  ci\ *|ci) echo "ok: clean install runs 'npm ci' ($first_call)" ;;
  *) fail "clean install ran 'npm $first_call' instead of 'npm ci'" ;;
esac

# --- 2. Missing npm fails loudly -----------------------------------------------------------------
# A PATH holding only the non-builtin commands test.sh needs before the npm check guarantees npm
# is absent.
mkdir -p "$TMP/thin-bin"
for tool in dirname tr; do ln -s "$(command -v "$tool")" "$TMP/thin-bin/$tool"; done

if out="$(PATH="$TMP/thin-bin" "$BASH_BIN" "$REPO/scripts/test.sh" frontend 2>&1)"; then
  fail "test.sh frontend exited 0 without npm"
fi
case "$out" in
  *"npm not found"*) echo "ok: missing npm exits nonzero and names it" ;;
  *) fail "expected the missing-npm message, got: $out" ;;
esac

echo "All test.sh frontend bootstrap tests passed."
