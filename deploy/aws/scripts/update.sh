#!/usr/bin/env bash
# Refresh the server's .env from SSM and pull the latest image, through SSM Run Command
# (no SSH). Run it after a new image is published or after changing a secret.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: update.sh

Runs /usr/local/bin/codebuddy-update on the server: re-reads SSM parameters into
/opt/codebuddy/.env, then docker compose pull && docker compose up -d.
Settings: STACK_NAME (code-buddy), AWS_REGION, AWS_PROFILE.
By hand instead:  aws ssm start-session --target <instance-id>,  then  sudo /usr/local/bin/codebuddy-update
EOF
}
case "${1:-}" in -h|--help) usage; exit 0 ;; "") ;; *) usage >&2; exit 2 ;; esac

STACK_NAME="${STACK_NAME:-code-buddy}"
instance=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue" --output text)
echo "updating $instance (stack $STACK_NAME)"

command_id=$(aws ssm send-command --instance-ids "$instance" \
  --document-name AWS-RunShellScript --comment "codebuddy-update" \
  --parameters 'commands=["/usr/local/bin/codebuddy-update"]' \
  --query 'Command.CommandId' --output text)

# The waiter gives up after about 100 s; image pulls can take longer, so keep polling.
for _ in $(seq 1 60); do
  status=$(aws ssm get-command-invocation --command-id "$command_id" --instance-id "$instance" \
    --query Status --output text 2> /dev/null || echo Pending)
  case "$status" in Pending|InProgress|Delayed) sleep 10 ;; *) break ;; esac
done

aws ssm get-command-invocation --command-id "$command_id" --instance-id "$instance" \
  --query '[StandardOutputContent,StandardErrorContent]' --output text
echo "status: $status"
[ "$status" = "Success" ]
