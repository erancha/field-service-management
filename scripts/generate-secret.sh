#!/usr/bin/env bash
#
# Print one freshly generated secret to stdout (nothing else, so it can be captured). Two kinds:
#   token-key       FSM_TOKEN_KEY  — a Fernet key that encrypts stored technician refresh tokens
#   session-secret  SESSION_SECRET — a random key that signs session cookies (OAuth login flow)
#
#   ./scripts/generate-secret.sh token-key
#   SESSION_SECRET=$(./scripts/generate-secret.sh session-secret)
#
# A Fernet key is 32 random bytes url-safe-base64 encoded (identical to Fernet.generate_key()); the
# session secret is 32 random bytes as hex. Both use the Python standard library only, so the Docker
# fallback needs no pip install. Uses a local Python when available, otherwise Docker.
set -euo pipefail

# Print this script's header comment block as --help text (single source of usage docs).
print_help() { awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}"; }

case "${1:-}" in
  token-key)      PYCODE='import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())' ;;
  session-secret) PYCODE='import secrets; print(secrets.token_hex(32))' ;;
  -h|--help)      print_help; exit 0 ;;
  *) echo "Usage: ./scripts/generate-secret.sh <token-key|session-secret>" >&2; exit 2 ;;
esac

if command -v python3 >/dev/null 2>&1; then
  python3 -c "$PYCODE"
elif command -v python >/dev/null 2>&1; then
  python -c "$PYCODE"
elif command -v docker >/dev/null 2>&1; then
  docker run --rm python:3.12-slim python -c "$PYCODE"
else
  echo "Need python3, python, or docker to generate a secret." >&2
  exit 1
fi
