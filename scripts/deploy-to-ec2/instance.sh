# The EC2 box itself: the key pair that reaches it, the security group that fronts it, launching or
# restarting it, and the reserved address its DNS records point at.
#
# Leaves INSTANCE_ID, SG_ID, SUBNET_ID, and PUBLIC_IP set for later modules.
#
# Sourced by start.sh — not executable on its own.

ensure_key_pair() {
  local in_aws
  in_aws="$(aws_value ec2 describe-key-pairs --filters "Name=key-name,Values=$KEY_NAME" \
      --query 'KeyPairs[0].KeyName' --output text)"

  if [ -n "$in_aws" ] && [ ! -f "$KEY_FILE" ]; then
    die "Key pair '$KEY_NAME' exists in AWS but its private half is missing at $KEY_FILE.
AWS cannot re-issue it. Restore the file, or delete the key pair
(aws ec2 delete-key-pair --key-name $KEY_NAME) and terminate any instance still using it."
  fi
  if [ -z "$in_aws" ] && [ -f "$KEY_FILE" ]; then
    die "$KEY_FILE exists locally but no '$KEY_NAME' key pair is registered in AWS.
Remove the stale file to have a fresh pair created."
  fi
  if [ -z "$in_aws" ]; then
    log "Creating key pair $KEY_NAME -> $KEY_FILE"
    mkdir -p "$HOME/.ssh"
    aws ec2 create-key-pair --key-name "$KEY_NAME" --key-type ed25519 \
        --query 'KeyMaterial' --output text > "$KEY_FILE"
    chmod 600 "$KEY_FILE"
  fi
}

# SSH follows the operator's current address, withdrawing the one it was opened to before — a home or
# office IP changes, and a stale /32 left behind would widen access over time. The web ports are
# opened to the internet once and left alone.
ensure_security_group() {
  local vpc_id my_ip desired rule_id rule_cidr port found=0

  vpc_id="$(aws_value ec2 describe-vpcs --filters "Name=isDefault,Values=true" \
      --query 'Vpcs[0].VpcId' --output text)"
  [ -n "$vpc_id" ] || die "No default VPC in $AWS_DEFAULT_REGION to launch into."

  SG_ID="$(aws_value ec2 describe-security-groups \
      --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$vpc_id" \
      --query 'SecurityGroups[0].GroupId' --output text)"
  if [ -z "$SG_ID" ]; then
    log "Creating security group $SG_NAME"
    SG_ID="$(aws ec2 create-security-group --group-name "$SG_NAME" --vpc-id "$vpc_id" \
        --description "Public web plus operator SSH for the Field Service Management deployment" \
        --query 'GroupId' --output text)"
  fi

  SUBNET_ID="$(aws_value ec2 describe-subnets \
      --filters "Name=vpc-id,Values=$vpc_id" "Name=map-public-ip-on-launch,Values=true" \
      --query 'Subnets[0].SubnetId' --output text)"
  [ -n "$SUBNET_ID" ] || die "No public subnet found in $vpc_id."

  my_ip="$(curl -fsS --max-time 15 https://checkip.amazonaws.com | tr -d '[:space:]')"
  [ -n "$my_ip" ] || die "Could not determine this machine's public IP."
  desired="$my_ip/32"

  while read -r rule_id rule_cidr; do
    [ -n "$rule_id" ] || continue
    if [ "$rule_cidr" = "$desired" ]; then
      found=1
    else
      log "Withdrawing SSH access from stale address $rule_cidr"
      aws ec2 revoke-security-group-ingress --group-id "$SG_ID" \
          --security-group-rule-ids "$rule_id" >/dev/null
    fi
  done < <(aws ec2 describe-security-group-rules \
      --filters "Name=group-id,Values=$SG_ID" \
      --query "SecurityGroupRules[?Description=='$SSH_RULE_DESC'].[SecurityGroupRuleId,CidrIpv4]" \
      --output text)

  if [ "$found" -eq 0 ]; then
    log "Opening SSH to $desired"
    aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
        --ip-permissions "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=$desired,Description='$SSH_RULE_DESC'}]" \
        >/dev/null
  fi

  # Port 80 carries the ACME challenge and the redirect to https, so it stays open alongside 443.
  for port in 80 443; do
    if [ -z "$(aws_value ec2 describe-security-group-rules \
        --filters "Name=group-id,Values=$SG_ID" \
        --query "SecurityGroupRules[?Description=='$WEB_RULE_DESC' && FromPort==\`$port\`].SecurityGroupRuleId | [0]" \
        --output text)" ]; then
      log "Opening port $port to the internet"
      aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
          --ip-permissions "IpProtocol=tcp,FromPort=$port,ToPort=$port,IpRanges=[{CidrIp=0.0.0.0/0,Description='$WEB_RULE_DESC'}]" \
          >/dev/null
    fi
  done
}

# Prints "<instance-id> <state>", or nothing when no instance carries the Name tag.
find_instance() {
  aws_value ec2 describe-instances \
      --filters "Name=tag:Name,Values=$INSTANCE_NAME" \
                "Name=instance-state-name,Values=pending,running,stopping,stopped" \
      --query 'Reservations[].Instances[] | [0].[InstanceId,State.Name]' --output text
}

launch_instance() {
  local ami user_data
  ami="$(aws ssm get-parameters --names "$AMI_SSM_PARAM" --query 'Parameters[0].Value' --output text)"
  [ -n "$ami" ] && [ "$ami" != "None" ] || die "Could not resolve the Amazon Linux 2023 arm64 AMI."

  user_data="$(mktemp)"
  # The box runs only the Docker engine: compose stays on this machine and drives it over SSH.
  # Swap covers the SPA build's peak (rolldown and lightningcss link natively, ~1-1.5 GB) so the
  # smaller instance types can build without the OOM killer reaching the running stack.
  cat > "$user_data" <<'CLOUDINIT'
#!/bin/bash
set -eux
dnf install -y docker
systemctl enable --now docker
usermod -aG docker ec2-user
if [ ! -f /swapfile ]; then
  dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
CLOUDINIT

  log "Launching $INSTANCE_TYPE from $ami"
  INSTANCE_ID="$(aws ec2 run-instances \
      --image-id "$ami" \
      --instance-type "$INSTANCE_TYPE" \
      --key-name "$KEY_NAME" \
      --security-group-ids "$SG_ID" \
      --subnet-id "$SUBNET_ID" \
      --associate-public-ip-address \
      --metadata-options "HttpTokens=required,HttpEndpoint=enabled" \
      --block-device-mappings "DeviceName=/dev/xvda,Ebs={VolumeSize=$DISK_GB,VolumeType=gp3,DeleteOnTermination=true,Encrypted=true}" \
      --instance-initiated-shutdown-behavior stop \
      --user-data "file://$user_data" \
      --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE_NAME}]" \
      --query 'Instances[0].InstanceId' --output text)"
  rm -f "$user_data"

  # A fresh instance may inherit a recently released address, so any host key remembered for it
  # belongs to a different machine.
  rm -f "$KNOWN_HOSTS"
  log "Launched $INSTANCE_ID — waiting for it to pass its status checks"
  aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"
  aws ec2 wait instance-status-ok --instance-ids "$INSTANCE_ID"
}

ensure_instance() {
  local state
  read -r INSTANCE_ID state <<<"$(find_instance)"

  ensure_key_pair
  ensure_security_group

  if [ -z "${INSTANCE_ID:-}" ]; then
    launch_instance
    return
  fi

  case "$state" in
    running) log "Reusing running instance $INSTANCE_ID" ;;
    stopped)
      log "Starting stopped instance $INSTANCE_ID"
      aws ec2 start-instances --instance-ids "$INSTANCE_ID" >/dev/null
      aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"
      aws ec2 wait instance-status-ok --instance-ids "$INSTANCE_ID"
      ;;
    pending|stopping)
      log "Instance $INSTANCE_ID is $state — waiting for it to settle"
      aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"
      aws ec2 wait instance-status-ok --instance-ids "$INSTANCE_ID"
      ;;
    *) die "Instance $INSTANCE_ID is in state '$state', which this script does not handle." ;;
  esac
}

# A published service cannot afford an address that changes under its DNS records, so the box keeps a
# reserved one. Attached to a running instance this is billed at the same rate as the auto-assigned
# address it replaces; only a stopped instance pays for it while idle.
ensure_elastic_ip() {
  local alloc_id attached_to
  alloc_id="$(aws_value ec2 describe-addresses --filters "Name=tag:Name,Values=$INSTANCE_NAME" \
      --query 'Addresses[0].AllocationId' --output text)"
  if [ -z "$alloc_id" ]; then
    log "Allocating an Elastic IP for $INSTANCE_NAME"
    alloc_id="$(aws ec2 allocate-address --domain vpc \
        --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$INSTANCE_NAME}]" \
        --query 'AllocationId' --output text)"
  fi

  attached_to="$(aws_value ec2 describe-addresses --allocation-ids "$alloc_id" \
      --query 'Addresses[0].InstanceId' --output text)"
  if [ "$attached_to" != "$INSTANCE_ID" ]; then
    log "Associating the Elastic IP with $INSTANCE_ID"
    aws ec2 associate-address --allocation-id "$alloc_id" --instance-id "$INSTANCE_ID" >/dev/null
  fi

  PUBLIC_IP="$(aws_value ec2 describe-addresses --allocation-ids "$alloc_id" \
      --query 'Addresses[0].PublicIp' --output text)"
  [ -n "$PUBLIC_IP" ] || die "Elastic IP $alloc_id has no public address."
}
