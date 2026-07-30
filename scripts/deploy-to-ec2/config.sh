# Every tunable and derived name for the deployment, sourced first so the rest of the modules only
# read these. Operators override the FSM_* variables; everything below them is derived and should not
# need editing.
#
# Sourced by start.sh — not executable on its own.

# Compose files for every remote call: the repo's local-development definition, then the overlay
# beside these modules that turns it into the public deployment. The base file leads deliberately —
# compose takes the project directory from the first file, so the build contexts declared in it
# resolve against the repo root rather than this directory.
COMPOSE_FILES=(-f "$ROOT_DIR/docker-compose.yml" -f "$MODULE_DIR/docker-compose.ec2.yml")

INSTANCE_TYPE="${FSM_EC2_INSTANCE_TYPE:-t4g.medium}"
INSTANCE_NAME="${FSM_EC2_NAME:-fsm}"
CONTEXT_NAME="${FSM_EC2_CONTEXT:-fsm-ec2}"
DISK_GB="${FSM_EC2_DISK_GB:-30}"

OS_USER="ec2-user"
SG_NAME="${INSTANCE_NAME}-ec2-sg"
KEY_NAME="${INSTANCE_NAME}-ec2"
KEY_FILE="$HOME/.ssh/${KEY_NAME}.pem"
# Host keys live outside the operator's main known_hosts: AWS recycles public addresses, and a
# recycled one would otherwise trip the host-key-changed warning on an unrelated future connection.
KNOWN_HOSTS="$HOME/.ssh/known_hosts.${CONTEXT_NAME}"
SSH_CONFIG="$HOME/.ssh/config"
SSH_BEGIN="# >>> ${CONTEXT_NAME} (managed by scripts/deploy-to-ec2/start.sh) >>>"
SSH_END="# <<< ${CONTEXT_NAME} <<<"

# Ingress rules carrying these descriptions are the script's to reconcile; any other rule an operator
# adds to the group by hand is left untouched. SSH is pinned to one address and follows it as the
# operator's network changes; the web ports are open to everyone, which is the point of the deployment.
SSH_RULE_DESC="fsm deploy script — operator IP"
WEB_RULE_DESC="fsm deploy script — public web"

# Public AWS parameter holding the id of whatever Amazon Linux 2023 arm64 image Amazon currently
# publishes; it is read at launch, so a box created today gets the current image.
AMI_SSM_PARAM="/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"

# Subdomain per role, in the order technician, customer, back office. This one list drives the DNS
# records, the certificate's names, and the URLs printed after a deploy.
ROLE_HOSTS=(tech app admin)

# Endings --check-domain probes alongside the requested one. The same second-level name is tried
# against each rather than calling list-domain-suggestions, which returns an empty list often enough
# to be useless as the only answer.
CHEAP_TLDS=(com click link fyi eu me.uk)
