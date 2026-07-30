# How this machine reaches the box: the managed SSH config block, the Docker context that rides on
# it, and the two entry points other modules call to get a usable connection.
#
# ensure_box changes the deployment into a known state; connect_box only attaches to a running one.
# Keeping them apart is what stops a read-only command from allocating addresses or rewriting DNS.
#
# Sourced by start.sh — not executable on its own.

# Docker's ssh:// transport shells out to plain ssh with no way to pass an identity file, so the
# connection details have to live in the SSH config. ControlMaster matters for more than speed here:
# compose opens a connection per operation, and without a shared one a build would renegotiate SSH
# dozens of times.
write_ssh_config() {
  local tmp
  mkdir -p "$HOME/.ssh"
  touch "$SSH_CONFIG"
  tmp="$(mktemp)"
  awk -v b="$SSH_BEGIN" -v e="$SSH_END" '
    $0 == b { skip = 1 } skip && $0 == e { skip = 0; next } !skip { print }
  ' "$SSH_CONFIG" > "$tmp"

  cat >> "$tmp" <<EOF
$SSH_BEGIN
Host $CONTEXT_NAME
    HostName $PUBLIC_IP
    User $OS_USER
    IdentityFile $KEY_FILE
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
    UserKnownHostsFile $KNOWN_HOSTS
    ControlMaster auto
    ControlPath $HOME/.ssh/cm-$CONTEXT_NAME-%r@%h:%p
    ControlPersist 10m
    ServerAliveInterval 30
$SSH_END
EOF
  mv "$tmp" "$SSH_CONFIG"
  chmod 600 "$SSH_CONFIG"
  # A control socket from an earlier run may still point at a previous address.
  ssh -O exit "$CONTEXT_NAME" 2>/dev/null || true
}

# Removes the managed block, leaving anything the operator wrote around it intact.
remove_ssh_config() {
  local tmp
  [ -f "$SSH_CONFIG" ] || return 0
  tmp="$(mktemp)"
  awk -v b="$SSH_BEGIN" -v e="$SSH_END" '
    $0 == b { skip = 1 } skip && $0 == e { skip = 0; next } !skip { print }
  ' "$SSH_CONFIG" > "$tmp"
  mv "$tmp" "$SSH_CONFIG"
  chmod 600 "$SSH_CONFIG"
}

ensure_context() {
  if docker context ls --format '{{.Name}}' | grep -qx "$CONTEXT_NAME"; then
    docker context update "$CONTEXT_NAME" --docker "host=ssh://$CONTEXT_NAME" >/dev/null
  else
    docker context create "$CONTEXT_NAME" --docker "host=ssh://$CONTEXT_NAME" \
        --description "Field Service Management deployment box" >/dev/null
  fi
}

# cloud-init installs Docker after sshd is already accepting, and the ec2-user docker group
# membership only applies to sessions opened after usermod ran — so each attempt reconnects.
wait_for_docker() {
  local attempt
  log "Waiting for the Docker engine on the box"
  for attempt in $(seq 1 60); do
    if ssh -o BatchMode=yes -o ConnectTimeout=10 "$CONTEXT_NAME" 'docker info' >/dev/null 2>&1; then
      log "Docker engine ready"
      return 0
    fi
    sleep 5
  done
  die "Docker did not become ready on $PUBLIC_IP within 5 minutes.
Check cloud-init: ssh $CONTEXT_NAME 'sudo tail -50 /var/log/cloud-init-output.log'"
}

# Brings the box, its address, DNS, and the local wiring to a known state. Used by the commands that
# are meant to change the deployment.
ensure_box() {
  ensure_instance
  ensure_elastic_ip
  ensure_dns
  write_ssh_config
  ensure_context
}

# Points the local wiring at a box that is already running, touching no AWS resource. Commands that
# only read the deployment use this: reporting status or opening a tunnel has no business allocating
# an address or rewriting DNS as a side effect.
connect_box() {
  local state
  read -r INSTANCE_ID state <<<"$(find_instance)"
  [ -n "${INSTANCE_ID:-}" ] || die "No instance tagged Name=$INSTANCE_NAME exists."
  [ "$state" = "running" ] || die "Instance $INSTANCE_ID is $state, not running — start it with --start."

  PUBLIC_IP="$(aws_value ec2 describe-instances --instance-ids "$INSTANCE_ID" \
      --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)"
  [ -n "$PUBLIC_IP" ] || die "Instance $INSTANCE_ID has no public address."

  write_ssh_config
  ensure_context
}

# Every remote compose call goes through here: --context is always explicit, so the operator's
# default Docker context is never switched and local runs keep using the local daemon.
compose_remote() {
  (cd "$ROOT_DIR" && docker --context "$CONTEXT_NAME" compose "${COMPOSE_FILES[@]}" "$@")
}
