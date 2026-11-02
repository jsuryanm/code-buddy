#!/usr/bin/env bash
# Store CodeBuddy's secrets in SSM Parameter Store as SecureString. Values are typed hidden
# (read -s) or read from your own env file, and never printed, logged or passed on a command
# line: each one goes to the AWS CLI through a private temporary JSON file that is deleted.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: put-secrets.sh [--prefix /code-buddy] [--from-env-file PATH] [--only NAME]...

Writes SecureString parameters <prefix>/<NAME> (standard tier, free). Interactive by default:
press Enter to skip a name and keep its current value. With --from-env-file, takes the known
names from a KEY=VALUE file (for example your local .env) and prints only the names stored.
The basic-auth hash has its own script: make-basic-auth.sh.

Region and credentials: the usual AWS_REGION / AWS_PROFILE environment variables.
Required for the app: OPENAI_API_KEY, CODEBUDDY_MODEL_FAST/STANDARD/HEAVY, CODEBUDDY_API_KEYS
(any long random string, e.g. from: openssl rand -hex 32).
EOF
}

NAMES=(OPENAI_API_KEY CODEBUDDY_MODEL_FAST CODEBUDDY_MODEL_STANDARD CODEBUDDY_MODEL_HEAVY
  CODEBUDDY_API_KEYS CODEBUDDY_MEMORY_SECRET GROQ_API_KEY UPSTASH_REDIS_REST_URL
  UPSTASH_REDIS_REST_TOKEN QDRANT_CLUSTER_ENDPOINT QDRANT_API_KEY QDRANT_COLLECTION_NAME
  LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY LANGFUSE_BASE_URL GHCR_USER GHCR_TOKEN)

prefix=/code-buddy
env_file=""
only=()
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) prefix="${2:?--prefix needs a value}"; shift 2 ;;
    --from-env-file) env_file="${2:?--from-env-file needs a path}"; shift 2 ;;
    --only) only+=("${2:?--only needs a name}"); shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
prefix="${prefix%/}"
[ ${#only[@]} -gt 0 ] && NAMES=("${only[@]}")

workdir=$(mktemp -d)
chmod 700 "$workdir"
trap 'rm -rf "$workdir"' EXIT

put() { # put NAME VALUE: value travels through the environment into a 0600 file, never argv
  local name="$1" json="$workdir/p.json"
  NAME="$prefix/$name" VALUE="$2" python3 - "$json" <<'PY'
import json, os, sys
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump({"Name": os.environ["NAME"], "Value": os.environ["VALUE"],
               "Type": "SecureString", "Overwrite": True}, f)
PY
  aws ssm put-parameter --cli-input-json "file://$json" > /dev/null
  rm -f "$json"
  echo "stored $prefix/$name"
}

if [ -n "$env_file" ]; then
  [ -r "$env_file" ] || { echo "cannot read $env_file" >&2; exit 1; }
  # Parse KEY=VALUE lines (optional quotes, comments) without echoing anything.
  while IFS= read -r -d '' name && IFS= read -r -d '' value; do
    for known in "${NAMES[@]}"; do
      if [ "$name" = "$known" ] && [ -n "$value" ]; then put "$name" "$value"; fi
    done
  done < <(python3 - "$env_file" <<'PY'
import sys
for line in open(sys.argv[1]):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.removeprefix("export ").split("=", 1)
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    sys.stdout.write(key.strip() + "\0" + value + "\0")
PY
  )
  exit 0
fi

echo "Storing secrets under $prefix (region: ${AWS_REGION:-${AWS_DEFAULT_REGION:-from your profile}})."
echo "Typing is hidden. Press Enter to skip a name."
for name in "${NAMES[@]}"; do
  value=""
  read -r -s -p "$name: " value
  echo
  if [ -n "$value" ]; then put "$name" "$value"; else echo "skipped $name"; fi
done
unset value
