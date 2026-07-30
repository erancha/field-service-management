# One function per command start.sh dispatches to, each composed from the other modules. Anything
# reusable belongs in those; this file is the sequence, not the mechanism.
#
# Sourced by start.sh — not executable on its own.

print_endpoints() {
  cat <<EOF

The app is live:
  technician   https://tech.$FSM_DOMAIN
  customer     https://app.$FSM_DOMAIN
  back office  https://admin.$FSM_DOMAIN

Register these redirect URIs on the Google OAuth client (Google Auth Platform > Clients), or
sign-in fails with redirect_uri_mismatch:
  https://tech.$FSM_DOMAIN/auth/google/callback
  https://app.$FSM_DOMAIN/auth/google/callback
  https://admin.$FSM_DOMAIN/auth/google/callback
  https://tech.$FSM_DOMAIN/calendar/connect/callback

Everyone who signs in must be listed under Audience > Test users while the consent screen is in
Testing mode, and ADMIN_EMAILS in backend/.env governs who reaches the back office.
EOF
}

do_deploy() {
  require_domain
  [ -f "$ROOT_DIR/backend/.env" ] || die "Missing backend/.env — run ./scripts/init-env.sh first.
Compose reads it here and passes the values to the box, so it is required at deploy time."

  ensure_box
  wait_for_docker

  log "Building on the box and starting the stack (the first build takes several minutes)"
  compose_remote up -d --build
  ensure_certificate
  compose_remote ps
  log "Deploy complete — $INSTANCE_ID at $PUBLIC_IP"
  print_endpoints
}

do_status() {
  local instance state
  read -r instance state <<<"$(find_instance)"
  if [ -z "$instance" ]; then
    echo "No instance tagged Name=$INSTANCE_NAME exists. Run the script with no arguments to create one."
    return 0
  fi
  aws ec2 describe-instances --instance-ids "$instance" \
      --query 'Reservations[0].Instances[0].{Instance:InstanceId,State:State.Name,Type:InstanceType,IP:PublicIpAddress,Launched:LaunchTime}' \
      --output table
  if [ "$state" != "running" ]; then
    echo "Instance is $state — the site is down. Start it with --start."
    return 0
  fi
  require_domain
  connect_box
  compose_remote ps
}

do_db_tunnel() {
  connect_box
  echo "Postgres on the box is forwarded to localhost:15432 (user fsm, database fsm)."
  echo "Ctrl-C closes the tunnel."
  ssh -N -L "15432:127.0.0.1:5432" "$CONTEXT_NAME"
}

do_stop() {
  local instance state
  read -r instance state <<<"$(find_instance)"
  [ -n "$instance" ] || die "No instance tagged Name=$INSTANCE_NAME to stop."
  log "Stopping $instance — the disk and all stack data survive; compute billing ends"
  aws ec2 stop-instances --instance-ids "$instance" >/dev/null
  aws ec2 wait instance-stopped --instance-ids "$instance"
  ssh -O exit "$CONTEXT_NAME" 2>/dev/null || true
  log "Stopped. The site is offline until --start; the Elastic IP is held, so DNS stays valid."
}

do_start() {
  require_domain
  ensure_box
  wait_for_docker
  compose_remote ps
  log "Running at $PUBLIC_IP"
  print_endpoints
}

do_terminate() {
  local instance state reply
  read -r instance state <<<"$(find_instance)"
  [ -n "$instance" ] || die "No instance tagged Name=$INSTANCE_NAME to terminate."

  echo "This destroys instance $instance and its encrypted EBS volume."
  echo "Everything in the stack's Postgres volume — appointments, users, the knowledge base — is lost,"
  echo "along with the issued certificates."
  printf "Type 'terminate' to confirm: "
  read -r reply
  [ "$reply" = "terminate" ] || die "Aborted."

  aws ec2 terminate-instances --instance-ids "$instance" >/dev/null
  aws ec2 wait instance-terminated --instance-ids "$instance"

  ssh -O exit "$CONTEXT_NAME" 2>/dev/null || true
  docker context rm "$CONTEXT_NAME" >/dev/null 2>&1 || true
  rm -f "$KNOWN_HOSTS"
  remove_ssh_config
  log "Terminated. The key pair, security group, and Elastic IP remain for a future launch —
release the address (aws ec2 release-address) if this deployment is gone for good, since an
unattached Elastic IP is billed while idle."
}
