#!/usr/bin/env bash
# Verifies require_ec2_host_stack of lib/ec2.sh against a stand-in aws command: a guest stops with
# a message naming EC2_HOST_STACK, the account and the region when the host stack is missing or
# unreadable, and when it is itself a guest, and with AWS's error when the credentials are
# refused; it passes when the host stack owns an instance.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

# The stand-in answers by FAKE_HOST: refused credentials, or a host stack missing, denied, guest
# or host.
mkdir "$WORK/bin"
cat > "$WORK/bin/aws" <<'AWS'
#!/usr/bin/env bash
case "$*" in
  "sts get-caller-identity"*)
    [[ "$FAKE_HOST" != refused ]] || { echo "An error occurred (InvalidClientTokenId)" >&2; exit 254; }
    echo 111122223333 ;;
  "cloudformation describe-stacks"*)
    case "$FAKE_HOST" in
      missing) echo "An error occurred (ValidationError): Stack with id h does not exist" >&2
               exit 254 ;;
      denied) echo "An error occurred (AccessDenied): not authorized" >&2; exit 254 ;;
      guest) echo None ;;
      host) echo i-0123 ;;
    esac ;;
  *) echo "unexpected aws call: $*" >&2; exit 99 ;;
esac
AWS
chmod +x "$WORK/bin/aws"

# Runs require_ec2_host_stack with the stand-in answering <mode>; prints its output.
check() {  # mode
  ( export PATH="$WORK/bin:$PATH" FAKE_HOST="$1" HOST_STACK_NAME=h AWS_DEFAULT_REGION=eu-north-1
    ROOT="$WORK"
    source "$SCRIPTS_DIR/lib/settings-guard.sh"
    source "$SCRIPTS_DIR/lib/ec2.sh"
    require_ec2_host_stack ) 2>&1
}

for mode in missing denied guest; do
  if out="$(check "$mode")"; then fail "a $mode host stack was accepted"; fi
  for word in EC2_HOST_STACK 111122223333 eu-north-1; do
    grep -q "$word" <<<"$out" || fail "the $mode refusal does not name $word: $out"
  done
done
grep -q "does not exist" <<<"$(check missing || true)" || fail "the refusal hides AWS's own error"
grep -q "is itself a guest" <<<"$(check guest || true)" || fail "a guest host is not named as one"
out="$(check refused || true)"
grep -q "credentials of aws-config.sh are refused" <<<"$out" || fail "refused credentials: $out"
check host >/dev/null || fail "a host stack that owns an instance was refused: $(check host)"

echo "test_ec2_host_stack: all checks passed"
