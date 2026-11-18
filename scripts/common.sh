#!/usr/bin/env bash
# Shared helpers for the field-service-management scripts: repo paths, help text, the settings
# files under scripts/lib/, the three roles and their EC2 stacks, compose access, and backend venv
# provisioning.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
BACKEND_VENV="$BACKEND/.venv"
FRONTEND="$ROOT/frontend"
# The stack's settings: stack-params.sh is committed; params.sh (this deployment's own settings)
# and secrets.sh are gitignored and created by init-env.sh from their .example.sh files.
STACK_PARAMS_FILE="$ROOT/scripts/lib/stack-params.sh"
PARAMS_FILE="$ROOT/scripts/lib/params.sh"
SECRETS_FILE="$ROOT/scripts/lib/secrets.sh"
# The deploying user's AWS credentials and region, read only for the EC2 target.
AWS_CONFIG_FILE="$ROOT/scripts/lib/aws-config.sh"
# The Compose files of the target: docker-compose.yml alone on this machine; use_ec2 of
# lib/ec2.sh adds the instance's override.
COMPOSE_FILES=("$ROOT/docker-compose.yml")
# Print the calling script's header comment block as --help text (single source of usage docs).
print_help() { awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"; }

# shellcheck source=lib/settings-guard.sh
source "$ROOT/scripts/lib/settings-guard.sh"
# shellcheck source=lib/ec2.sh
source "$ROOT/scripts/lib/ec2.sh"

# The three role apps the edge serves, each on a port of its own. On EC2 each role has its own
# stack, EC2_STACK-<suffix>, and so its own CloudFront distribution and https origin, since a role
# is told apart by its origin.
ROLES=(technician customer backoffice)
declare -A ROLE_STACK_SUFFIX=([technician]=tech [customer]=app [backoffice]=admin)

# Prints the edge port of <role>, EDGE_<ROLE>_HOST_PORT of stack-params.sh; requires load_settings.
role_port() {  # role
  local key="EDGE_${1^^}_HOST_PORT"
  printf '%s' "${!key:?set $key in stack-params.sh}"
}

# Exports every setting of the three files into this shell, which is where docker compose takes
# the ${...} values and each service's keys from. Stops when a gitignored file is missing, when
# git tracks it, or when a tracked file holds one of its secrets or addresses.
load_settings() {
  # shellcheck source=lib/stack-params.sh
  source "$STACK_PARAMS_FILE"
  source_checked_file "$PARAMS_FILE" assert_addresses_untracked
  source_checked_file "$SECRETS_FILE" assert_secrets_untracked
}

# Adds each listed setting that is blank or still its example's <placeholder> to
# MISSING_SETTINGS, with the file under scripts/lib/ that sets it, so one run names them all.
MISSING_SETTINGS=()
collect_missing_settings() {  # file key...
  local file="$1" key
  shift
  for key in "$@"; do
    [[ -n "${!key:-}" && "${!key}" != "<"*">" ]] || MISSING_SETTINGS+=("$key ($file)")
  done
}

# Stops when collect_missing_settings found any, listing every one of them.
require_collected_settings() {
  [ "${#MISSING_SETTINGS[@]}" -eq 0 ] && return
  echo "Fill in these settings under scripts/lib/, then run the script again:" >&2
  printf '  %s\n' "${MISSING_SETTINGS[@]}" >&2
  exit 1
}

require_docker() {
  docker info >/dev/null 2>&1 \
    || { echo "Docker is not reachable; start it and retry." >&2; exit 1; }
}

# An exported STACK_NAME names one stack, and this repo deploys one per role, so it is refused
# rather than applied to all three.
refuse_stack_name() {
  [[ -z "${STACK_NAME:-}" ]] ||
    die "STACK_NAME is exported, but this repo has a stack per role" \
        "($EC2_STACK-tech, -app and -admin); unset it and retry"
}

# Points lib/ec2.sh at the stack of <role>: STACK_NAME is EC2_STACK-<suffix>, with ec2.sh's -fb
# rule off main, and EC2_ORIGIN_PORT is the role's edge port. With EC2_HOST_STACK blank the first
# role's stack is the host and the others are its guests, so deploy it first and delete it last.
# Requires load_settings.
select_ec2_role() {  # role
  local base="$EC2_STACK"
  local EC2_STACK="$base-${ROLE_STACK_SUFFIX[$1]}"
  if [[ -z "$EC2_HOST_STACK" && "$1" != "${ROLES[0]}" ]]; then
    local EC2_HOST_STACK="$base-${ROLE_STACK_SUFFIX[${ROLES[0]}]}"
  fi
  STACK_NAME=""
  HOST_STACK_NAME=""
  resolve_ec2_stack
  EC2_ORIGIN_PORT="$(role_port "$1")"
}

# Sets EC2_<ROLE>_URL, the CloudFront address of <role>'s stack, from EC2_URL, which
# resolve_ec2_host has just set for that stack.
record_role_url() {  # role
  printf -v "EC2_${1^^}_URL" '%s' "$EC2_URL"
}

# Selects the EC2 target for the rest of the script, as use_ec2 of lib/ec2.sh does for a repo of
# one stack: each role's CloudFront address first, then the instance, which every role's stack
# names as its host.
use_ec2_roles() {
  local role
  refuse_stack_name
  load_aws_config
  for role in "${ROLES[@]}"; do
    select_ec2_role "$role"
    resolve_ec2_host
    record_role_url "$role"
  done
  use_ec2
}

# Compose reads the ${...} values and the keys each service lists in its environment from this
# shell, so the settings are loaded first. On the EC2 target docker-compose.ec2.yml builds each
# role's callbacks, and the worker's photo links, from the role's CloudFront address.
compose() {
  load_settings
  if [[ " ${COMPOSE_FILES[*]} " == *" $EC2_COMPOSE_FILE "* ]]; then
    export EC2_TECHNICIAN_URL EC2_CUSTOMER_URL EC2_BACKOFFICE_URL
  fi
  local file
  local -a files=()
  for file in "${COMPOSE_FILES[@]}"; do files+=(-f "$file"); done
  (cd "$ROOT" && docker compose "${files[@]}" "$@")
}

# Waits up to about a minute until the URL answers 2xx: the edge answers 502 while no replica of
# the role is up, which is no answer from the role.
wait_for_http() {  # url
  curl -fs --retry 60 --retry-all-errors --retry-delay 1 --max-time 2 -o /dev/null "$1"
}

# The venv holds the runtime dependencies at the exact pins the image installs (requirements.txt
# as a constraint), so the suite runs on what ships; the dev tools float within pyproject.toml. It
# is current only when installed from both files as they stand now: the stamp is a copy taken
# after the last successful install, so editing either forces a reinstall. The import and
# executable probe still catches a venv broken with the stamp intact.
ensure_backend_venv() {
  [ -d "$BACKEND_VENV" ] || python3 -m venv "$BACKEND_VENV"
  local stamp="$BACKEND_VENV/.dependencies.stamp"
  if ! cat "$BACKEND/pyproject.toml" "$BACKEND/requirements.txt" | cmp -s - "$stamp" \
     || ! { "$BACKEND_VENV/bin/python" -c "import fsm" 2>/dev/null \
            && [ -x "$BACKEND_VENV/bin/uvicorn" ] && [ -x "$BACKEND_VENV/bin/pytest" ]; }; then
    echo "Installing backend dependencies into backend/.venv..."
    ( cd "$BACKEND" && "$BACKEND_VENV/bin/pip" install --quiet --disable-pip-version-check \
        --constraint requirements.txt -e ".[dev]" )
    cat "$BACKEND/pyproject.toml" "$BACKEND/requirements.txt" > "$stamp"
  fi
}
