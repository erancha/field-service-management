#!/usr/bin/env bash
# Verifies how scripts/common.sh points lib/ec2.sh at each role's stack: on main each role deploys
# EC2_STACK-<suffix> at its edge port, on any other branch the same names with -fb. As guests all
# three name the host stack of EC2_HOST_STACK; with EC2_HOST_STACK blank the technician's stack is
# the host and the other two its guests. An exported STACK_NAME is refused, since it would name one
# stack for all three.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

mkdir -p "$WORK/scripts/lib"
cp "$SCRIPTS_DIR/common.sh" "$WORK/scripts/"
cp "$SCRIPTS_DIR"/lib/{settings-guard.sh,ec2.sh,stack-params.sh} "$WORK/scripts/lib/"
git -C "$WORK" init -q -b main

# Prints role=stack@host:port for every role, as deploy.sh --ec2 selects them, with the host
# setting <host stack> (blank: host).
selections() {  # host stack
  ( unset STACK_NAME HOST_STACK_NAME
    source "$WORK/scripts/common.sh"
    source "$STACK_PARAMS_FILE"
    EC2_HOST_STACK="$1"
    for role in "${ROLES[@]}"; do
      select_ec2_role "$role"
      printf '%s=%s@%s:%s\n' "$role" "$STACK_NAME" "$HOST_STACK_NAME" "$EC2_ORIGIN_PORT"
    done )
}

expected_main="technician=field-service-management-tech@other:8001
customer=field-service-management-app@other:8002
backoffice=field-service-management-admin@other:8003"
[[ "$(selections other)" == "$expected_main" ]] || fail "main selects: $(selections other)"

expected_host="technician=field-service-management-tech@field-service-management-tech:8001
customer=field-service-management-app@field-service-management-tech:8002
backoffice=field-service-management-admin@field-service-management-tech:8003"
[[ "$(selections '')" == "$expected_host" ]] || fail "as a host main selects: $(selections '')"

git -C "$WORK" checkout -q -b feature
expected_branch="technician=field-service-management-tech-fb@other-fb:8001
customer=field-service-management-app-fb@other-fb:8002
backoffice=field-service-management-admin-fb@other-fb:8003"
[[ "$(selections other)" == "$expected_branch" ]] ||
  fail "a feature branch selects: $(selections other)"

if out="$( (export STACK_NAME=other
            source "$WORK/scripts/common.sh"
            source "$STACK_PARAMS_FILE"
            refuse_stack_name) 2>&1)"; then
  fail "an exported STACK_NAME was accepted"
fi
grep -q "STACK_NAME is exported" <<<"$out" || fail "the refusal does not name STACK_NAME: $out"

echo "test_ec2_roles: all checks passed"
