#!/bin/sh
#
# Chooses the edge configuration at container start, before nginx is executed.
#
# FSM_DOMAIN unset — a local run — leaves the per-port localhost edge that the image ships in
# conf.d/default.conf. Set, it renders the per-hostname TLS edge over that file.
#
# Numbered 18 so it runs after the image's own entrypoint scripts prepare listen directives and
# resolvers, and before nginx starts.
set -e

[ -n "${FSM_DOMAIN:-}" ] || exit 0

envsubst '${FSM_DOMAIN}' < /etc/nginx/fsm/public.conf.template > /etc/nginx/conf.d/default.conf

# nginx refuses to start when ssl_certificate names a missing file, yet the real certificate cannot
# be issued until nginx is already answering the ACME challenge on port 80. A self-signed placeholder
# breaks that circle: the edge starts, certbot completes the challenge and overwrites this material,
# and a reload picks up the trusted certificate. It is deliberately short-lived — if one is ever
# served to a browser, that means issuance failed and the loud warning is the correct signal.
CERT_DIR=/etc/letsencrypt/live/fsm
if [ ! -f "$CERT_DIR/fullchain.pem" ]; then
    echo "18-fsm-edge-mode.sh: no certificate yet — generating a placeholder so nginx can start"
    mkdir -p "$CERT_DIR"
    openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
        -subj "/CN=tech.${FSM_DOMAIN}" \
        -keyout "$CERT_DIR/privkey.pem" \
        -out "$CERT_DIR/fullchain.pem" >/dev/null 2>&1
fi
