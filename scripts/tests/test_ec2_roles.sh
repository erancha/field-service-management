#!/usr/bin/env bash
# Verifies how scripts/common.sh points lib/ec2.sh at each role's stack: on main each role deploys
# EC2_STACK-<suffix> at its edge port on the loan-simulator instance, on any other branch the same
# names with -fb on the loan-simulator-fb instance, and an exported STACK_NAME is refused, since it
# would name one stack for all three.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

mkdir -p "$WORK/scripts/lib"
cp "$SCRIPTS_DIR/common.sh" "$WORK/scripts/"
cp "$SCRIPTS_DIR"/lib/{settings-guard.sh,ec2.sh,stack-params.sh} "$WORK/scripts/lib/"
git -C "$WORK" init -q -b main

# Prints role=stack@host:port for every role, as deploy.sh --ec2 selects them.
selections() {
  ( unset STACK_NAME
    source "$WORK/scripts/common.sh"
    source "$STACK_PARAMS_FILE"
    for role in "${ROLES[@]}"; do
      select_ec2_role "$role"
      printf '%s=%s@%s:%s\n' "$role" "$STACK_NAME" "$HOST_STACK_NAME" "$EC2_ORIGIN_PORT"
    done )
}

expected_main="technician=field-service-management-tech@loan-simulator:8001
customer=field-service-management-app@loan-simulator:8002
backoffice=field-service-management-admin@loan-simulator:8003"
[[ "$(selections)" == "$expected_main" ]] || fail "main selects: $(selections)"

git -C "$WORK" checkout -q -b feature
expected_branch="technician=field-service-management-tech-fb@loan-simulator-fb:8001
customer=field-service-management-app-fb@loan-simulator-fb:8002
backoffice=field-service-management-admin-fb@loan-simulator-fb:8003"
[[ "$(selections)" == "$expected_branch" ]] || fail "a feature branch selects: $(selections)"

if out="$( (export STACK_NAME=other
            source "$WORK/scripts/common.sh"
            source "$STACK_PARAMS_FILE"
            refuse_stack_name) 2>&1)"; then
  fail "an exported STACK_NAME was accepted"
fi
grep -q "STACK_NAME is exported" <<<"$out" || fail "the refusal does not name STACK_NAME: $out"

echo "test_ec2_roles: all checks passed"
