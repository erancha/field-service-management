#!/usr/bin/env bash
#
# Create the gitignored settings files under scripts/lib/ (secrets.sh, params.sh and
# aws-config.sh) from their .example.sh files, with the generated values. An existing file is
# kept unless --force.
#
#   ./scripts/init-env.sh             # create each file that is missing
#   ./scripts/init-env.sh --force     # replace every file, hand-filled keys included
#
# In secrets.sh the database password is 32 hex characters and the session secret 64, the token
# key a Fernet key (32 random bytes, URL-safe base64) and the photo store's secret key 40 hex
# characters, all from openssl, and the database URL is written from the ports and database names
# of scripts/lib/stack-params.sh. GOOGLE_CLIENT_SECRET of secrets.sh and GOOGLE_CLIENT_ID of
# params.sh stay blank for you to fill in (docs/sign-in.md), with ADMIN_EMAILS and the optional
# keys. Each file is readable by its owner only. If a written value fails its check, the files
# stay as they were. Then run ./scripts/deploy.sh.
#
# Replacing secrets.sh with --force writes a new FSM_TOKEN_KEY, which makes every stored calendar
# connection unreadable, and a new POSTGRES_PASSWORD, which an existing database volume does not
# accept (docker-helper.sh --stop --volumes starts it over).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --force)   FORCE=1 ;;
    -h|--help) print_help; exit 0 ;;
    *) echo "Usage: ./scripts/init-env.sh [--force]" >&2; exit 2 ;;
  esac
  shift
done

# shellcheck source=lib/stack-params.sh
source "$STACK_PARAMS_FILE"

# Each new file is built and verified beside its target and renamed over it only when both are
# complete, so a failure leaves no partial file. mktemp creates a draft readable by the owner
# only, as the files hold secrets.
drafts=()
trap 'rm -f "${drafts[@]}"' EXIT
draft_of() {  # target; prints the draft's path, or nothing when the target is kept
  local target="$1" draft
  if [ -f "$target" ] && [ "$FORCE" -eq 0 ]; then
    echo "${target#"$ROOT"/} already exists; left as it is (--force overwrites it)." >&2
    return
  fi
  draft="$(mktemp "$target.XXXXXX")"
  cat "${target%.sh}.example.sh" > "$draft"
  printf '%s' "$draft"
}

secrets_draft="$(draft_of "$SECRETS_FILE")"
[ -z "$secrets_draft" ] || drafts+=("$secrets_draft")
params_draft="$(draft_of "$PARAMS_FILE")"
[ -z "$params_draft" ] || drafts+=("$params_draft")
# Only deploy.sh --ec2 reads it, so it may stay unfilled on a machine that deploys locally.
aws_draft="$(draft_of "$AWS_CONFIG_FILE")"
[ -z "$aws_draft" ] || drafts+=("$aws_draft")

if [ -n "$secrets_draft" ]; then
  db_password="$(openssl rand -hex 16)"
  database_url="postgresql+psycopg://$POSTGRES_USER:$db_password"
  database_url+="@127.0.0.1:$DB_HOST_PORT/$POSTGRES_DB"
  session_secret="$(openssl rand -hex 32)"
  # The URL-safe base64 alphabet has - and _ where openssl's has + and /; none of the generated
  # values holds the | that delimits the substitutions below.
  token_key="$(openssl rand -base64 32 | tr '+/' '-_')"
  store_secret="$(openssl rand -hex 20)"
  sed -i "s|^export POSTGRES_PASSWORD=.*|export POSTGRES_PASSWORD=\"$db_password\"|;
          s|^export DATABASE_URL=.*|export DATABASE_URL=\"$database_url\"|;
          s|^export SESSION_SECRET=.*|export SESSION_SECRET=\"$session_secret\"|;
          s|^export FSM_TOKEN_KEY=.*|export FSM_TOKEN_KEY=\"$token_key\"|;
          s|^export MINIO_SECRET_KEY=.*|export MINIO_SECRET_KEY=\"$store_secret\"|" \
    "$secrets_draft"
  for key in POSTGRES_PASSWORD DATABASE_URL SESSION_SECRET FSM_TOKEN_KEY MINIO_SECRET_KEY; do
    # The draft is sourced in a subshell, so a key the example lacks reads as unset here.
    ( unset "$key"
      # shellcheck source=/dev/null
      source "$secrets_draft"
      [ -n "${!key:-}" ] ) \
      || { echo "$key has no value in the new ${SECRETS_FILE#"$ROOT"/}" >&2; exit 1; }
  done
fi

[ -z "$secrets_draft" ] || mv "$secrets_draft" "$SECRETS_FILE"
[ -z "$params_draft" ] || mv "$params_draft" "$PARAMS_FILE"
[ -z "$aws_draft" ] || mv "$aws_draft" "$AWS_CONFIG_FILE"
[ -z "$secrets_draft" ] \
  || echo "Created scripts/lib/secrets.sh with generated database, session, token and store keys."
[ -z "$params_draft" ] || echo "Created scripts/lib/params.sh."
[ -z "$aws_draft" ] || echo "Created scripts/lib/aws-config.sh (needed for deploy.sh --ec2 only)."
# The reminder is for a file this run created; a kept file was filled in before.
if [ -n "$secrets_draft$params_draft" ]; then
  echo "Fill in the settings left blank (docs/sign-in.md for the Google client);" \
       "./scripts/deploy.sh names each one it still needs."
fi
