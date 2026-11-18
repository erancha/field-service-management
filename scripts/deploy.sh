#!/usr/bin/env bash
#
# Deploy Field Service Management: build the images and start Postgres, Redis, the object store,
# the role replicas, the calendar worker and the nginx edge in Docker Compose, then return once
# every role answers through the edge.
#
#   ./scripts/deploy.sh          on this machine's Docker
#   ./scripts/deploy.sh --ec2    on an EC2 instance, as three stacks, one per role, each behind
#                                a CloudFront distribution
#   -h, --help                   show this help
#
# Before the roles start, a one-shot container (the migrate service) brings the Postgres tables up
# to the current schema with Alembic, then exits. Sign-in needs the Google client and the
# generated session secret, so the script checks them first, with the database, token and store
# keys, and names every one that is blank with its settings file. Every run starts with
# ./scripts/init-env.sh, which creates a missing settings file and keeps the existing ones, so a
# first run creates them all and then stops on the settings left to fill in. Stop or inspect the
# stack with ./scripts/docker-helper.sh (--stop / --logs / --ps), which takes --ec2 too.
#
# On this machine the edge publishes the three role apps on every interface: the technician app
# at localhost:EDGE_TECHNICIAN_HOST_PORT, the customer app at EDGE_CUSTOMER_HOST_PORT and the back
# office at EDGE_BACKOFFICE_HOST_PORT (8001, 8002 and 8003 as shipped; localhost at each port is
# what Google sign-in is registered for). Postgres, Redis and the object store are published on
# the loopback interface at DB_HOST_PORT, REDIS_HOST_PORT and OBJECT_STORE_HOST_PORT.
#
# --ec2 also needs the access key pair and region in scripts/lib/aws-config.sh, and deploys to
# the account its credentials belong to. With EC2_HOST_STACK of params.sh blank the technician's
# stack is the instance's host and the other two are its guests; set to another Docker Compose
# repo's host stack, all three are guests on that stack's instance, deployed first from its repo.
# This script creates or updates one CloudFormation stack of scripts/template-ec2.yaml per role
# (the git branch selects them: field-service-management-tech, -app and -admin on main, each with
# -fb on any other branch, on the host's -fb instance):
# the role's edge port in the instance's security group and a CloudFront distribution whose https
# address is the role's only way in. It then builds the images here for ARM, loads them into the
# instance's Docker daemon over SSH, and runs Compose against that daemon once for the whole
# stack. The settings files stay on this machine; each container's own settings, secrets
# included, reach the instance as part of the container's configuration, which Docker keeps on
# the instance's encrypted disk. Register the printed addresses with Google once
# (docs/sign-in.md).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

TARGET=local
case "${1:-}" in
  -h|--help) print_help; exit 0 ;;
  --ec2)     TARGET=ec2 ;;
  "")        ;;
  *)         print_help >&2; exit 2 ;;
esac

"$SCRIPT_DIR/init-env.sh"
load_settings
collect_missing_settings secrets.sh POSTGRES_PASSWORD DATABASE_URL SESSION_SECRET FSM_TOKEN_KEY \
  MINIO_SECRET_KEY GOOGLE_CLIENT_SECRET
collect_missing_settings params.sh GOOGLE_CLIENT_ID
require_collected_settings
require_docker

# Waits for each role's /health through the edge at <base of the role>, given as role=base pairs.
wait_for_roles() {  # logs-hint role=base...
  local hint="$1" pair
  shift
  for pair in "$@"; do
    wait_for_http "${pair#*=}/health" \
      || { echo "the ${pair%%=*} role did not answer on ${pair#*=}; see $hint" >&2; exit 1; }
    echo "  ${pair%%=*} -> ${pair#*=}"
  done
}

deploy_local() {
  local role
  local -a pairs=()
  for role in "${ROLES[@]}"; do pairs+=("$role=http://localhost:$(role_port "$role")"); done
  echo "Building and starting the data services, the role replicas, the worker and the edge..."
  compose up -d --build
  wait_for_roles "./scripts/docker-helper.sh --logs" "${pairs[@]}"
  echo "Open each address in your browser and sign in with Google" \
       "(the API docs at /docs, health at /health and /ready)."
  echo "  stop it or tail logs:  ./scripts/docker-helper.sh --stop | --logs"
}

deploy_ec2() {
  local role url
  local -a pairs=()
  refuse_stack_name
  load_aws_config
  for role in "${ROLES[@]}"; do
    select_ec2_role "$role"
    deploy_ec2_stack
    resolve_ec2_host
    record_role_url "$role"
    pairs+=("$role=$EC2_URL")
  done
  COMPOSE_FILES+=("$EC2_COMPOSE_FILE")

  echo "Building the images for linux/arm64 on this machine..."
  compose build
  prepare_ec2_host
  echo "Loading the images into the instance's Docker daemon..."
  # shellcheck disable=SC2046  # one image name per word, none with spaces
  docker save $(ec2_built_images) | gzip | ssh_ec2 "$EC2_HOST_USER@$EC2_HOST" 'gunzip | docker load'

  open_ec2_docker
  echo "Starting the data services, the role replicas, the worker and the edge on the instance..."
  compose up -d --no-build --remove-orphans
  # A deploy leaves the previous build's layers behind; the instance's disk is small.
  docker image prune -f >/dev/null
  wait_for_roles "./scripts/docker-helper.sh --ec2 --logs" "${pairs[@]}"
  echo "Register these redirect URIs with the Google OAuth client once (docs/sign-in.md):"
  for role in "${ROLES[@]}"; do
    url="EC2_${role^^}_URL"
    echo "  ${!url}/auth/google/callback"
  done
  echo "  $EC2_TECHNICIAN_URL/calendar/connect/callback"
  echo "  stop it or tail logs:  ./scripts/docker-helper.sh --ec2 --stop | --logs"
}

"deploy_$TARGET"
