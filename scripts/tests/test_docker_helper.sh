#!/usr/bin/env bash
# Verifies docker-helper.sh refuses what it does not support before touching a settings file, AWS
# or Docker: an unknown command, an unknown --stop or --logs option, a --logs option without its
# value, and any argument after --ps or --delete-stack.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail() { echo "FAIL: $*" >&2; exit 1; }

refused() {  # expected-text args...
  local expected="$1" out
  shift
  out="$(bash "$SCRIPTS_DIR/docker-helper.sh" "$@" 2>&1)" && fail "accepted: $*"
  grep -qF -- "$expected" <<<"$out" || fail "'$*' refused without naming the cause: $out"
}

refused "Unknown --stop option 'extra'" --stop extra
refused "Unknown --stop option 'extra'" --stop --volumes extra
refused "Unknown --logs option '--bogus'" --logs --bogus
refused "--grep needs a pattern" --logs --grep
refused "--since needs a duration" --logs -e --since
refused "takes no arguments (got: extra)" --ps extra
refused "takes no arguments (got: extra)" --ec2 --delete-stack extra
refused "Unknown command: --bogus" --bogus
grep -q -- '--stop \[--volumes\]' "$SCRIPTS_DIR/docker-helper.sh" ||
  fail "usage does not offer --volumes"

echo "test_docker_helper: all checks passed"
