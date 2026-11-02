#!/usr/bin/env bash
# Create a monthly AWS cost budget that emails you at 80% of actual spend and at 100% of
# forecast spend. Do this before deploy.sh.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: budget.sh --email you@example.com [--amount 5] [--name code-buddy-monthly]

Creates a monthly COST budget in USD. Credits are excluded (IncludeCredit=false), so the
alert tracks what the resources would cost before free-plan credits; with credits included
the spend shows as 0 and nothing would ever fire. UNCONFIRMED: how the new free plan's
credits appear in AWS Budgets; check the budget page after a day.
The first two budgets in an account are free. Credentials: AWS_PROFILE as usual.
EOF
}

email=""
amount=5
name=code-buddy-monthly
while [ $# -gt 0 ]; do
  case "$1" in
    --email) email="${2:?--email needs a value}"; shift 2 ;;
    --amount) amount="${2:?--amount needs a value}"; shift 2 ;;
    --name) name="${2:?--name needs a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[ -n "$email" ] || { usage >&2; exit 2; }
[[ "$amount" =~ ^[0-9]+(\.[0-9]+)?$ ]] || { echo "amount must be a number" >&2; exit 2; }

account=$(aws sts get-caller-identity --query Account --output text)
budget=$(printf '{"BudgetName":"%s","BudgetType":"COST","TimeUnit":"MONTHLY",
  "BudgetLimit":{"Amount":"%s","Unit":"USD"},
  "CostTypes":{"IncludeCredit":false,"IncludeRefund":false}}' "$name" "$amount")
notifications=$(printf '[
  {"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN",
    "Threshold":80,"ThresholdType":"PERCENTAGE"},
   "Subscribers":[{"SubscriptionType":"EMAIL","Address":"%s"}]},
  {"Notification":{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN",
    "Threshold":100,"ThresholdType":"PERCENTAGE"},
   "Subscribers":[{"SubscriptionType":"EMAIL","Address":"%s"}]}]' "$email" "$email")

aws budgets create-budget --account-id "$account" --budget "$budget" \
  --notifications-with-subscribers "$notifications"
echo "budget '$name' created: $amount USD a month, alerts to $email"
