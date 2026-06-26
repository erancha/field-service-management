#!/usr/bin/env bash
#
# Create backend/.env from backend/.env.example and fill in the two locally-minted secrets
# (FSM_TOKEN_KEY and SESSION_SECRET), so sign-in and technician calendar connect work once Google
# credentials are added. Refuses to clobber an existing backend/.env unless --force is given.
#
#   ./scripts/init-env.sh           # create backend/.env (fails if it already exists)
#   ./scripts/init-env.sh --force   # overwrite an existing backend/.env
#
# Then edit backend/.env to add Google sign-in/calendar, holidays, or email — see its comments.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/backend/.env"
EXAMPLE="$ROOT/backend/.env.example"

# Print this script's header comment block as --help text (single source of usage docs).
print_help() { awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}"; }

FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force)   FORCE=1 ;;
    -h|--help) print_help; exit 0 ;;
    *) echo "Usage: ./scripts/init-env.sh [--force]" >&2; exit 2 ;;
  esac
done

if [ -f "$ENV_FILE" ] && [ "$FORCE" -eq 0 ]; then
  echo "backend/.env already exists — pass --force to overwrite it." >&2
  exit 1
fi

cp "$EXAMPLE" "$ENV_FILE"

# Fill the two locally-minted secrets now so the OAuth flows work without manual steps. Both secret
# alphabets (url-safe base64 / hex) never contain the '|' sed delimiter.
TOKEN_KEY="$("$ROOT/scripts/generate-secret.sh" token-key)"
SESSION_SECRET="$("$ROOT/scripts/generate-secret.sh" session-secret)"
tmp="$(mktemp)"
sed -e "s|^FSM_TOKEN_KEY=.*|FSM_TOKEN_KEY=${TOKEN_KEY}|" \
    -e "s|^SESSION_SECRET=.*|SESSION_SECRET=${SESSION_SECRET}|" "$ENV_FILE" > "$tmp"
mv "$tmp" "$ENV_FILE"

echo "Created backend/.env with freshly generated FSM_TOKEN_KEY and SESSION_SECRET."
echo "Edit backend/.env to add Google sign-in/calendar, holidays, or email (see its comments), then run ./scripts/start.sh."
