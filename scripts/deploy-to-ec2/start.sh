#!/usr/bin/env bash
#
# Launch (or reuse) the Field Service Management EC2 box and serve the app publicly from it over
# HTTPS, driven from this machine through a remote Docker context.
#
#   ./scripts/deploy-to-ec2/start.sh [command]
#
#     (none)             launch or reuse the box, point DNS at it, build, start, issue certificates
#     --check-domain     is FSM_DOMAIN free, what does it cost, what else is available
#     --register-domain  buy FSM_DOMAIN through Route 53 (charges the AWS account)
#     --status           instance state and the stack's containers
#     --db-tunnel        forward the box's Postgres to localhost:15432 for a GUI client
#     --stop             stop the INSTANCE — compute billing ends, the disk survives
#     --start            start a stopped instance and bring the stack back
#     --terminate        destroy the instance and its disk (all stack data is lost)
#     -h, --help
#
# This file is the entry point only: it parses the command, loads the modules beside it, and
# dispatches. The work lives in those modules, each owning one concern:
#   config.sh        tunables and every derived name, path, and tag
#   common.sh        logging, fatal exits, the AWS query wrapper, shared preconditions
#   domain.sh        finding and buying the domain
#   instance.sh      key pair, security group, launching the box, its Elastic IP
#   dns.sh           Route 53 records and the wait for them to resolve
#   connection.sh    SSH config, Docker context, and the remote compose wrapper
#   certificates.sh  first certificate issuance (the certbot service renews)
#   commands.sh      one function per command above, composed from the modules
#
# REQUIRED before the first run
#   FSM_DOMAIN       the domain, e.g. example.com. The roles are served at tech.$FSM_DOMAIN
#                    (technician), app.$FSM_DOMAIN (customer), and admin.$FSM_DOMAIN (back office).
#                    A Route 53 hosted zone for it must exist and be delegated — --register-domain
#                    does both, as does registering through the Route 53 console.
#   FSM_ACME_EMAIL   contact address Let's Encrypt uses for expiry warnings.
#   For --register-domain only: registrant details in scripts/domain-contact.json (gitignored),
#   copied from domain-contact.example.json. Override the path with FSM_DOMAIN_CONTACT.
#
#   Register the four callbacks the deploy prints on the Google OAuth client before signing in.
#   Google requires https for a public redirect URI, which is why the edge terminates TLS rather
#   than serving the roles over plain http.
#
# Operate the deployed stack with the existing helpers by naming the context, so this script needs
# no logs or psql commands of its own:
#   ./scripts/docker-helper.sh --context fsm-ec2 --logs -e backoffice
#   ./scripts/docker-helper.sh --context fsm-ec2 --stop        # stops the STACK, leaves the box up
#   ./scripts/sql-helper.sh    --context fsm-ec2 -c "SELECT count(*) FROM appointment;"
#
# HOW IT WORKS
#   Compose is a client-side plugin, so `docker --context fsm-ec2 compose up --build` sends the build
#   context to the box's Docker daemon and builds there — natively arm64 on Graviton, with no
#   registry and no cross-compilation — and no copy of the repo is left on the box. Compose also
#   reads backend/.env here and passes the values as container environment, so secrets are never
#   written to the box's disk.
#
#   An Elastic IP is attached so the DNS records stay valid across a stop/start. While the instance
#   runs it costs exactly what the auto-assigned public address would; the difference is that a
#   restart does not silently strand the domain on a dead address.
#
#   nginx serves the three role hostnames on 443 and answers the ACME challenge on 80. Certificates
#   live in a Docker volume, are issued once by this script, and are renewed by the certbot service.
#   Postgres and Redis stay bound to the box's loopback interface — use --db-tunnel to reach them.
#
# LOCAL RUNS ARE UNAFFECTED
#   Every remote command passes --context explicitly. The default context is never switched and
#   DOCKER_HOST is never exported, so ./scripts/start.sh and ./scripts/test.sh (testcontainers) keep
#   talking to the local Docker daemon.
#
# AWS CREDENTIALS come from FSM_AWS_CONFIG, else scripts/aws-config.sh (gitignored), else whatever is
# already exported in the environment.
#
# TUNING (environment overrides)
#   FSM_EC2_INSTANCE_TYPE  default t4g.medium — 4 GB ARM. t4g.small halves the cost and still runs
#                          the stack (~1 GB resident); the 2 GB swap covers its SPA build.
#   FSM_EC2_NAME           default fsm — the Name tag on the instance and its Elastic IP
#   FSM_EC2_CONTEXT        default fsm-ec2 — Docker context name and SSH host alias
#   FSM_EC2_DISK_GB        default 30
#   FSM_ACME_STAGING       set to 1 to issue from Let's Encrypt's staging CA while working out DNS
#                          or firewall problems. Staging certificates are untrusted by browsers but
#                          do not consume the production rate limit, which locks out five failed
#                          issuances per hour.
set -euo pipefail

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$MODULE_DIR/../.." && pwd)"

for module in config common domain instance dns connection certificates commands; do
  # shellcheck source=/dev/null  # sibling modules, resolved relative to this file at runtime
  source "$MODULE_DIR/$module.sh"
done

# set -e fires ERR before the script aborts; recording where pinpoints the failing step in a run
# that spans several minutes of AWS calls.
trap 'log "ERROR: failed near line $LINENO (exit $?)"' ERR

# Print this script's header comment block as --help text (single source of usage docs).
print_help() { awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}"; }

mode="${1:---deploy}"
case "$mode" in
  -h|--help) print_help; exit 0 ;;
esac

require_tools
load_aws_credentials

case "$mode" in
  --deploy)          do_deploy ;;
  --check-domain)    do_check_domain ;;
  --register-domain) do_register_domain ;;
  --status)          do_status ;;
  --db-tunnel)       do_db_tunnel ;;
  --stop)            do_stop ;;
  --start)           do_start ;;
  --terminate)       do_terminate ;;
  *) die "Unknown command: $mode
(expected --check-domain | --register-domain | --status | --db-tunnel | --stop | --start | --terminate; see -h)" ;;
esac
