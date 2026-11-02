#!/usr/bin/env bash
# Show the stack, the instance, the public site and (through SSM) the containers and /healthz.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: status.sh [--no-remote]

Prints the stack status and outputs, the instance state, the HTTP status of the public URL
(401 means Caddy and basic auth are up), then runs codebuddy-status on the server through
SSM Run Command (containers, API /healthz, memory, disk). --no-remote skips that last part.
Settings: STACK_NAME (code-buddy), AWS_REGION, AWS_PROFILE.
EOF
}
remote=true
case "${1:-}" in
  --no-remote) remote=false ;;
  -h|--help) usage; exit 0 ;;
  "") ;;
  *) usage >&2; exit 2 ;;
esac

STACK_NAME="${STACK_NAME:-code-buddy}"
output() {
  aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query 'Stacks[0].StackStatus' --output text
instance=$(output InstanceId)
url=$(output Url)
aws ec2 describe-instances --instance-ids "$instance" \
  --query 'Reservations[0].Instances[0].[InstanceId,InstanceType,State.Name]' --output text
echo "site: $url -> HTTP $(curl -s -o /dev/null -m 10 -w '%{http_code}' "$url" || true)"

if $remote; then
  command_id=$(aws ssm send-command --instance-ids "$instance" \
    --document-name AWS-RunShellScript --comment "codebuddy-status" \
    --parameters 'commands=["/usr/local/bin/codebuddy-status"]' \
    --query 'Command.CommandId' --output text)
  aws ssm wait command-executed --command-id "$command_id" --instance-id "$instance" || true
  aws ssm get-command-invocation --command-id "$command_id" --instance-id "$instance" \
    --query '[Status,StandardOutputContent,StandardErrorContent]' --output text
fi
