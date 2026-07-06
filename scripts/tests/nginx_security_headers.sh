#!/usr/bin/env bash
#
# Behavioral test for the SPA security headers in nginx/snippets/spa.conf: every SPA response —
# index.html, hashed assets, and deep-link fallbacks — must carry X-Content-Type-Options,
# X-Frame-Options, and a Content-Security-Policy that denies framing. The caching headers those
# location blocks already set must survive alongside (nginx drops inherited add_header directives
# in any location that declares its own, so coexistence is exactly what can regress).
#
# Runs the real nginx image with the repo config mounted; requires Docker.
#
#   ./scripts/tests/nginx_security_headers.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NGINX_IMAGE="nginx:1.27-alpine"

TMP="$(mktemp -d)"
CONTAINER=""
cleanup() {
  [ -n "$CONTAINER" ] && docker rm -f "$CONTAINER" >/dev/null 2>&1
  rm -rf "$TMP"
}
trap cleanup EXIT

fail() { echo "FAIL: $1" >&2; exit 1; }

# Minimal SPA payload standing in for the built frontend.
mkdir -p "$TMP/html/assets"
echo '<!doctype html><title>t</title>' > "$TMP/html/index.html"
echo 'console.log(1)' > "$TMP/html/assets/app-test.js"

# The upstream blocks resolve technician/customer/backoffice at startup; point them at loopback so
# nginx boots without the backend stack. Static serving never touches them.
CONTAINER="$(docker run -d \
  -v "$ROOT/nginx/default.conf":/etc/nginx/conf.d/default.conf:ro \
  -v "$ROOT/nginx/snippets":/etc/nginx/snippets:ro \
  -v "$TMP/html":/usr/share/nginx/html:ro \
  --add-host technician:127.0.0.1 \
  --add-host customer:127.0.0.1 \
  --add-host backoffice:127.0.0.1 \
  -p 127.0.0.1:0:8001 \
  "$NGINX_IMAGE")"

PORT="$(docker port "$CONTAINER" 8001/tcp | head -n 1 | sed 's/.*://')"

for _ in $(seq 1 50); do
  curl -sf -o /dev/null "http://127.0.0.1:$PORT/index.html" && break
  docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true \
    || { docker logs "$CONTAINER" >&2 || true; fail "nginx container exited during startup"; }
  sleep 0.2
done

assert_header() {
  local path="$1" header="$2" want="$3" headers
  headers="$(curl -sf -D - -o /dev/null "http://127.0.0.1:$PORT$path")" \
    || fail "GET $path did not return success"
  echo "$headers" | grep -i "^$header:" | grep -qF "$want" \
    || fail "GET $path: header '$header' missing or lacks '$want'; got: $(echo "$headers" | grep -i "^$header:" || echo '<absent>')"
}

# index.html, a hashed asset, and a deep link (client-routed path served via the SPA fallback).
for path in /index.html /assets/app-test.js /appointments; do
  assert_header "$path" "X-Content-Type-Options" "nosniff"
  assert_header "$path" "X-Frame-Options" "DENY"
  assert_header "$path" "Content-Security-Policy" "frame-ancestors 'none'"
  assert_header "$path" "Content-Security-Policy" "default-src 'self'"
  echo "ok: $path carries the security header set"
done

# The caching contract must coexist with the security headers in the same location blocks.
assert_header "/index.html" "Cache-Control" "no-cache"
assert_header "/assets/app-test.js" "Cache-Control" "immutable"
echo "ok: caching headers coexist with security headers"

echo "All nginx security header tests passed."
