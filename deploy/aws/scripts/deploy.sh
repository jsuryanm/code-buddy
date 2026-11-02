#!/usr/bin/env bash
# Create or update the CodeBuddy stack (deploy/aws/template.yaml) and print its outputs.
# Asks before creating anything billable.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: deploy.sh [--yes]

Settings (environment variables, all optional):
  STACK_NAME        code-buddy
  INSTANCE_TYPE     t3.small (or t3.micro)
  VOLUME_SIZE       20 (GiB, 8 to 30)
  IMAGE_URI         ghcr.io/jsuryanm/code-buddy:latest
  SSM_PREFIX        /code-buddy
  DOMAIN_NAME       empty: use <ip-with-dashes>.sslip.io
  BASIC_AUTH_USER   tutor
  ALLOWED_CIDR      0.0.0.0/0
  VPC_ID, SUBNET_ID default VPC and its first default subnet
  AWS_REGION, AWS_PROFILE  the usual AWS CLI variables

Costs: the instance, its disk and the public IPv4 address bill (credits on the free plan)
until you run destroy.sh. Stopping the instance still bills the disk and the IP.
EOF
}

yes=false
case "${1:-}" in
  --yes) yes=true ;;
  -h|--help) usage; exit 0 ;;
  "") ;;
  *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
esac

here="$(cd "$(dirname "$0")/.." && pwd)"
STACK_NAME="${STACK_NAME:-code-buddy}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.small}"
VOLUME_SIZE="${VOLUME_SIZE:-20}"
IMAGE_URI="${IMAGE_URI:-ghcr.io/jsuryanm/code-buddy:latest}"
SSM_PREFIX="${SSM_PREFIX:-/code-buddy}"
DOMAIN_NAME="${DOMAIN_NAME:-}"
BASIC_AUTH_USER="${BASIC_AUTH_USER:-tutor}"
ALLOWED_CIDR="${ALLOWED_CIDR:-0.0.0.0/0}"

VPC_ID="${VPC_ID:-$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text)}"
[ "$VPC_ID" != "None" ] || { echo "no default VPC: set VPC_ID and SUBNET_ID" >&2; exit 1; }
SUBNET_ID="${SUBNET_ID:-$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=$VPC_ID" Name=default-for-az,Values=true \
  --query 'sort_by(Subnets,&AvailabilityZone)[0].SubnetId' --output text)}"
[ "$SUBNET_ID" != "None" ] || { echo "no default subnet: set SUBNET_ID" >&2; exit 1; }

# The server refuses to start without these; check names only (values are not fetched).
present=$(aws ssm get-parameters-by-path --path "$SSM_PREFIX" \
  --query 'Parameters[].Name' --output text | tr '\t' '\n')
missing=()
for name in OPENAI_API_KEY CODEBUDDY_MODEL_FAST CODEBUDDY_MODEL_STANDARD CODEBUDDY_MODEL_HEAVY \
  CODEBUDDY_API_KEYS BASIC_AUTH_HASH; do
  grep -qx "${SSM_PREFIX%/}/$name" <<< "$present" || missing+=("$name")
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "missing SSM parameters under $SSM_PREFIX: ${missing[*]}" >&2
  echo "run scripts/put-secrets.sh and scripts/make-basic-auth.sh first" >&2
  exit 1
fi

cat <<EOF
About to create or update stack '$STACK_NAME' in ${AWS_REGION:-${AWS_DEFAULT_REGION:-your default region}}:
  instance $INSTANCE_TYPE, ${VOLUME_SIZE} GiB gp3 disk, Elastic IP (public IPv4, \$0.005/h)
  vpc $VPC_ID, subnet $SUBNET_ID, image $IMAGE_URI
These bill (or use free-plan credits) until you run scripts/destroy.sh.
EOF
if ! $yes; then
  read -r -p "Type 'yes' to continue: " answer
  [ "$answer" = "yes" ] || { echo "cancelled"; exit 1; }
fi

aws cloudformation deploy \
  --stack-name "$STACK_NAME" \
  --template-file "$here/template.yaml" \
  --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset \
  --parameter-overrides \
    "VpcId=$VPC_ID" "SubnetId=$SUBNET_ID" "InstanceType=$INSTANCE_TYPE" \
    "VolumeSizeGiB=$VOLUME_SIZE" "ImageUri=$IMAGE_URI" "SsmPrefix=$SSM_PREFIX" \
    "DomainName=$DOMAIN_NAME" "BasicAuthUser=$BASIC_AUTH_USER" "AllowedCidr=$ALLOWED_CIDR"

aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table
echo "First boot takes about 5 minutes. Follow it with the BootstrapLogCommand above."
