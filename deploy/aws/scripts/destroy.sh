#!/usr/bin/env bash
# Delete the CodeBuddy stack: the instance, its disk, the Elastic IP, the role and the
# security group. This stops every charge the stack causes. Asks first.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: destroy.sh [--delete-secrets]

Deletes the CloudFormation stack and waits until it is gone. SSM parameters are kept (the
standard tier is free) unless --delete-secrets is given. Data in Qdrant Cloud, Upstash and
Langfuse is outside AWS and untouched.
Settings: STACK_NAME (code-buddy), SSM_PREFIX (/code-buddy), AWS_REGION, AWS_PROFILE.
EOF
}
delete_secrets=false
case "${1:-}" in
  --delete-secrets) delete_secrets=true ;;
  -h|--help) usage; exit 0 ;;
  "") ;;
  *) usage >&2; exit 2 ;;
esac

STACK_NAME="${STACK_NAME:-code-buddy}"
SSM_PREFIX="${SSM_PREFIX:-/code-buddy}"

echo "This deletes stack '$STACK_NAME' and everything in it (the server's disk too)."
$delete_secrets && echo "It also deletes every SSM parameter under $SSM_PREFIX."
read -r -p "Type the stack name to confirm: " answer
[ "$answer" = "$STACK_NAME" ] || { echo "cancelled"; exit 1; }

aws cloudformation delete-stack --stack-name "$STACK_NAME"
echo "deleting... (a few minutes)"
aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"
echo "stack $STACK_NAME deleted"

if $delete_secrets; then
  names=$(aws ssm get-parameters-by-path --path "$SSM_PREFIX" \
    --query 'Parameters[].Name' --output text)
  for name in $names; do
    aws ssm delete-parameter --name "$name"
    echo "deleted $name"
  done
fi
