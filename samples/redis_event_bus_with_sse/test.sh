#!/usr/bin/env bash
#
# End-to-end test of this sample: hold an SSE stream through the frontend proxy (which pins it to
# backend-1), post a message through the same proxy (pinned to backend-2), and pass only when the
# message comes back on the stream and the trace logs show the publish and the delivery in two
# different processes.
#
#   ./test.sh        # up (built if needed) -> round trip -> down, when this run started the stack
#
# A stack already running is reused and left running afterwards. On success the script prints the
# delivery-trace log lines it asserted on, since a stack it started is gone by the time it returns.
set -euo pipefail

# Print this script's header comment block as --help text (single source of usage docs).
# Runs before the cd below, while the invocation path in BASH_SOURCE still resolves.
print_help() { awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}"; }

case "${1:-}" in
  -h|--help) print_help; exit 0 ;;
  "") ;;
  *) print_help; exit 2 ;;
esac

cd "$(dirname "${BASH_SOURCE[0]}")"

PAGE_URL="http://localhost:8010"

if [ -z "$(docker compose ps -q)" ]; then
  # This run owns the stack's lifecycle, so it tears the stack down on every exit path.
  trap 'docker compose down' EXIT
fi
docker compose up -d --build --wait

# --wait above covers the backends via their compose healthchecks; the dev server declares none,
# so poll the page itself.
for _ in $(seq 1 30); do
  curl -sf -o /dev/null "$PAGE_URL" && break
  sleep 1
done
curl -sf -o /dev/null "$PAGE_URL" || { echo "FAIL: frontend never came up at $PAGE_URL" >&2; exit 1; }

MESSAGE="e2e-$(date +%s)-$$"
CAPTURE="$(mktemp)"
SINCE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

curl -sN --max-time 20 "$PAGE_URL/api/events" > "$CAPTURE" &
SSE_PID=$!
# Redis pub/sub has no replay: the subscription must be open before the publish, and the stream
# only registers it once backend-1 accepts the connection.
sleep 2

curl -sf -X POST "$PAGE_URL/api/publish" -H 'Content-Type: application/json' \
  -d "{\"message\": \"$MESSAGE\"}" > /dev/null

for _ in $(seq 1 20); do
  grep -q "$MESSAGE" "$CAPTURE" && break
  sleep 0.5
done
kill "$SSE_PID" 2>/dev/null || true

grep -q "$MESSAGE" "$CAPTURE" || {
  echo "FAIL: posted message never arrived on the SSE stream" >&2
  docker compose logs --since "$SINCE" backend-1 backend-2 >&2
  exit 1
}

# The capture proves delivery; these two lines prove it crossed processes — the publish logged by
# backend-2, the SSE delivery logged by backend-1.
docker compose logs --since "$SINCE" backend-2 | grep -q "Published 'sample.message'" || {
  echo "FAIL: backend-2 never logged the publish" >&2; exit 1; }
docker compose logs --since "$SINCE" backend-1 | grep -q "Delivering 'sample.message'" || {
  echo "FAIL: backend-1 never logged the SSE delivery" >&2; exit 1; }

# Timestamp order across the two backends, same sort key as the repo's --logs --sorted mode: the
# timestamp opens the text after the service-name column.
echo "--- delivery trace ---"
docker compose logs --since "$SINCE" backend-1 backend-2 \
  | grep -E "SSE stream '|Published 'sample.message'|Received 'sample.message'|Delivering 'sample.message'" \
  | sort -t'|' -k2 -s
echo "PASS: the posted message crossed processes through Redis and returned over SSE."
