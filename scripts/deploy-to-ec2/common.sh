# Cross-cutting helpers: logging, fatal exits, the AWS query wrapper, and the preconditions every
# command shares (tooling, credentials, domain).
#
# Sourced by start.sh — not executable on its own.

log() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
die() { echo "$*" >&2; exit 1; }

# An AWS text query over an empty result set prints "None"; callers want an empty string for absent,
# so every existence check reads as a plain emptiness test rather than a comparison against "None".
aws_value() { local v; v="$(aws "$@")"; [ "$v" = "None" ] && v=""; printf '%s' "$v"; }

require_tools() {
  local tool
  for tool in aws docker ssh curl jq; do
    command -v "$tool" >/dev/null 2>&1 || die "Required tool not found: $tool"
  done
  docker compose version >/dev/null 2>&1 || die "The docker compose plugin is required (it runs the build from here)."
}

load_aws_credentials() {
  local config="${FSM_AWS_CONFIG:-$ROOT_DIR/scripts/aws-config.sh}"
  if [ -f "$config" ]; then
    # shellcheck disable=SC1090  # operator-local credentials file, path resolved at runtime
    source "$config"
  fi
  if [ -z "${AWS_ACCESS_KEY_ID:-}" ] || [ -z "${AWS_SECRET_ACCESS_KEY:-}" ]; then
    die "No AWS credentials. Point FSM_AWS_CONFIG at your aws-config.sh, place one at
scripts/aws-config.sh (gitignored), or export AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY."
  fi
  [ -n "${AWS_DEFAULT_REGION:-}" ] || die "AWS_DEFAULT_REGION is not set (the credentials file normally sets it)."
}

# The overlay compose file interpolates FSM_DOMAIN, so it must be exported for every remote compose
# call, not merely set.
require_domain() {
  [ -n "${FSM_DOMAIN:-}" ] || die "FSM_DOMAIN is not set — e.g. FSM_DOMAIN=example.com $0
The roles are served at tech./app./admin. of that domain, which must have a Route 53 hosted zone."
  export FSM_DOMAIN
}
