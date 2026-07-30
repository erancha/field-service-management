# First issuance of the TLS certificate covering the three role hostnames. Renewal is not here — the
# certbot service in docker-compose.ec2.yml owns that, so it keeps working with no one at a terminal.
#
# Sourced by start.sh — not executable on its own.

# certbot writes a renewal profile only after a real certificate is issued, which is what
# distinguishes an issued lineage from the self-signed placeholder the nginx entrypoint mints at the
# same path so the edge can start at all.
ensure_certificate() {
  local host
  local -a args

  if compose_remote exec -T nginx test -f /etc/letsencrypt/renewal/fsm.conf 2>/dev/null; then
    log "Certificate already issued — the certbot service handles renewal"
    return 0
  fi

  [ -n "${FSM_ACME_EMAIL:-}" ] || die "FSM_ACME_EMAIL is not set — Let's Encrypt needs a contact address
for expiry warnings, e.g. FSM_ACME_EMAIL=you@example.com $0"

  wait_for_dns

  args=(certonly --webroot -w /var/www/certbot --cert-name fsm
        --email "$FSM_ACME_EMAIL" --agree-tos --no-eff-email --non-interactive)
  for host in "${ROLE_HOSTS[@]}"; do
    args+=(-d "$host.$FSM_DOMAIN")
  done
  if [ "${FSM_ACME_STAGING:-0}" = "1" ]; then
    log "Issuing from the Let's Encrypt STAGING CA — browsers will not trust the result"
    args+=(--staging)
  fi

  log "Requesting a certificate for tech/app/admin.$FSM_DOMAIN"
  compose_remote run --rm --entrypoint certbot certbot "${args[@]}"
  # nginx is holding the placeholder in memory until told to re-read it.
  compose_remote exec -T nginx nginx -s reload
  log "Certificate installed"
}
