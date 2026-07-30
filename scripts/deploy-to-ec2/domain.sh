# Finding and buying the domain. Registration is the only thing in this deployment that spends money
# irreversibly, so it lives behind its own command and a typed confirmation rather than happening as
# a step of a deploy.
#
# Sourced by start.sh — not executable on its own.

# Read-only companion to --register-domain: is this name free, what does it cost, and what does the
# same name cost under cheaper endings. Nothing here charges anything.
do_check_domain() {
  require_domain
  local base own tld availability price
  local -a tlds

  base="${FSM_DOMAIN%%.*}"
  own="${FSM_DOMAIN#*.}"
  # The requested ending leads, then the cheap ones it is not already among.
  tlds=("$own")
  for tld in "${CHEAP_TLDS[@]}"; do
    [ "$tld" = "$own" ] || tlds+=("$tld")
  done

  printf '%-26s %-12s %s\n' "DOMAIN" "AVAILABLE" "PRICE/YEAR"
  for tld in "${tlds[@]}"; do
    availability="$(aws route53domains check-domain-availability --region us-east-1 \
        --domain-name "$base.$tld" --query 'Availability' --output text)"
    price="$(aws route53domains list-prices --region us-east-1 --tld "$tld" \
        --query 'Prices[0].RegistrationPrice.Price' --output text)"
    printf '%-26s %-12s $%s\n' "$base.$tld" "$availability" "$price"
  done
  echo
  echo "Register one with:  FSM_DOMAIN=<domain> $0 --register-domain"
}

# Route 53 creates and delegates the hosted zone as part of registration, which is what the deploy
# then needs. route53domains is only served from us-east-1, whatever region the stack runs in.
do_register_domain() {
  require_domain
  local contact tld price availability operation status attempt reply

  contact="${FSM_DOMAIN_CONTACT:-$ROOT_DIR/scripts/domain-contact.json}"
  [ -f "$contact" ] || die "No registrant details at $contact.
Copy scripts/domain-contact.example.json there and fill it in — ICANN requires genuine contact
details, and the registrant email must be one you can read to complete verification."
  grep -q '"_comment"' "$contact" && die "$contact still contains the _comment key from the example.
Remove it — the AWS API rejects unknown fields."

  availability="$(aws route53domains check-domain-availability --region us-east-1 \
      --domain-name "$FSM_DOMAIN" --query 'Availability' --output text)"
  [ "$availability" = "AVAILABLE" ] \
    || die "$FSM_DOMAIN is $availability — pick another name."

  tld="${FSM_DOMAIN##*.}"
  price="$(aws route53domains list-prices --region us-east-1 --tld "$tld" \
      --query 'Prices[0].RegistrationPrice.Price' --output text)"

  cat <<EOF

Registering $FSM_DOMAIN for one year.
  Price now:        \$$price charged to this AWS account
  Auto-renew:       ON — \$$price again every year until you turn it off in the Route 53 console.
                    Left off, the domain would lapse and the site would go down with it.
  WHOIS privacy:    ON — the details in $contact are not published
  Registrant email: $(jq -r '.Email' "$contact")
                    A verification link goes here and MUST be clicked within 15 days,
                    or ICANN suspends the domain.
EOF
  printf "Type 'register' to confirm: "
  read -r reply
  [ "$reply" = "register" ] || die "Aborted — nothing was charged."

  operation="$(aws route53domains register-domain --region us-east-1 \
      --domain-name "$FSM_DOMAIN" \
      --duration-in-years 1 \
      --auto-renew \
      --admin-contact "file://$contact" \
      --registrant-contact "file://$contact" \
      --tech-contact "file://$contact" \
      --privacy-protect-admin-contact \
      --privacy-protect-registrant-contact \
      --privacy-protect-tech-contact \
      --query 'OperationId' --output text)"
  log "Registration submitted as operation $operation"

  # Registration is asynchronous at the registry, so the wait is bounded and a still-pending
  # operation is reported rather than treated as failure.
  for attempt in $(seq 1 60); do
    status="$(aws route53domains get-operation-detail --region us-east-1 \
        --operation-id "$operation" --query 'Status' --output text)"
    case "$status" in
      SUCCESSFUL)
        log "$FSM_DOMAIN registered — Route 53 has created and delegated its hosted zone"
        echo
        echo "Click the verification link in the email sent to $(jq -r '.Email' "$contact"),"
        echo "then deploy:  FSM_DOMAIN=$FSM_DOMAIN FSM_ACME_EMAIL=... $0"
        return 0
        ;;
      ERROR|FAILED)
        die "Registration $status. Details:
$(aws route53domains get-operation-detail --region us-east-1 --operation-id "$operation" --output json)"
        ;;
    esac
    sleep 30
  done

  log "Still $status after 30 minutes — registration can take hours to clear the registry."
  log "Check with: aws route53domains get-operation-detail --region us-east-1 --operation-id $operation"
}
