# Route 53 records for the three role hostnames, and the wait that confirms the world can see them.
#
# Sourced by start.sh — not executable on its own.

# The hosted zone must already exist and be delegated. Creating one here would look like success
# while the domain's registrar still pointed elsewhere, and certificate issuance would then fail for
# reasons far from this step.
ensure_dns() {
  local zone_id batch change_id host
  zone_id="$(aws_value route53 list-hosted-zones-by-name --dns-name "$FSM_DOMAIN." \
      --query "HostedZones[?Name=='$FSM_DOMAIN.'].Id | [0]" --output text)"
  [ -n "$zone_id" ] || die "No Route 53 hosted zone for $FSM_DOMAIN.
Register the domain through Route 53 (which creates and delegates the zone automatically), or
create the zone and point your registrar's name servers at it, then re-run."

  batch="$(mktemp)"
  {
    printf '{"Comment":"fsm deploy","Changes":['
    for host in "${ROLE_HOSTS[@]}"; do
      [ "$host" = "${ROLE_HOSTS[0]}" ] || printf ','
      printf '{"Action":"UPSERT","ResourceRecordSet":{"Name":"%s.%s","Type":"A","TTL":60,"ResourceRecords":[{"Value":"%s"}]}}' \
          "$host" "$FSM_DOMAIN" "$PUBLIC_IP"
    done
    printf ']}'
  } > "$batch"

  log "Pointing tech/app/admin.$FSM_DOMAIN at $PUBLIC_IP"
  change_id="$(aws route53 change-resource-record-sets --hosted-zone-id "$zone_id" \
      --change-batch "file://$batch" --query 'ChangeInfo.Id' --output text)"
  rm -f "$batch"
  aws route53 wait resource-record-sets-changed --id "$change_id"
}

# Route 53 reporting a change as INSYNC means its own name servers agree, not that this machine's
# resolver has stopped serving a cached answer — and certbot fails hard on a name that still points
# somewhere else.
wait_for_dns() {
  local attempt resolved host="tech.$FSM_DOMAIN"
  log "Waiting for $host to resolve to $PUBLIC_IP"
  for attempt in $(seq 1 60); do
    resolved="$(getent hosts "$host" | awk '{print $1}' | head -1)"
    if [ "$resolved" = "$PUBLIC_IP" ]; then
      log "DNS resolves correctly"
      return 0
    fi
    sleep 10
  done
  die "$host still resolves to '${resolved:-nothing}' rather than $PUBLIC_IP after 10 minutes.
Check the zone's delegation at the registrar before retrying; certificate issuance would fail."
}
