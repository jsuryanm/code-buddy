#!/usr/bin/env bash
# Make the bcrypt hash for the site's basic auth and store it in SSM as <prefix>/BASIC_AUTH_HASH.
# The password is typed hidden and never printed; it reaches the hasher on stdin only.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: make-basic-auth.sh [--prefix /code-buddy] [--print]

Asks for the password twice (hidden), hashes it with bcrypt and stores the hash as the
SecureString parameter <prefix>/BASIC_AUTH_HASH. --print shows the hash instead of storing it.
The user name is the stack parameter BasicAuthUser (default: tutor).

Hasher: Python with the bcrypt package (through uv if installed), else the caddy Docker image.
Region and credentials: the usual AWS_REGION / AWS_PROFILE environment variables.
EOF
}

prefix=/code-buddy
print=false
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) prefix="${2:?--prefix needs a value}"; shift 2 ;;
    --print) print=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
prefix="${prefix%/}"

read -r -s -p "Password for the site: " pw1; echo
read -r -s -p "Again: " pw2; echo
[ "$pw1" = "$pw2" ] || { echo "passwords differ" >&2; exit 1; }
[ ${#pw1} -ge 12 ] || { echo "use at least 12 characters" >&2; exit 1; }
unset pw2

HASH_PY='import sys, bcrypt; sys.stdout.write(bcrypt.hashpw(sys.stdin.read().encode(), bcrypt.gensalt(12)).decode())'
if command -v uv > /dev/null; then
  hash=$(printf '%s' "$pw1" | uv run --quiet --no-project --with bcrypt python -c "$HASH_PY")
elif python3 -c 'import bcrypt' 2> /dev/null; then
  hash=$(printf '%s' "$pw1" | python3 -c "$HASH_PY")
elif command -v docker > /dev/null; then
  # caddy hash-password reads the password from stdin when it is not a terminal
  hash=$(printf '%s\n' "$pw1" | docker run --rm -i caddy:2.11-alpine caddy hash-password)
else
  echo "need uv, python3 with bcrypt (pip install bcrypt), or docker" >&2
  exit 1
fi
unset pw1
case "$hash" in
  \$2?\$*) ;;
  *) echo "hashing failed (no bcrypt hash produced)" >&2; exit 1 ;;
esac

if $print; then
  echo "$hash"
  exit 0
fi

workdir=$(mktemp -d)
chmod 700 "$workdir"
trap 'rm -rf "$workdir"' EXIT
NAME="$prefix/BASIC_AUTH_HASH" VALUE="$hash" python3 - "$workdir/p.json" <<'PY'
import json, os, sys
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump({"Name": os.environ["NAME"], "Value": os.environ["VALUE"],
               "Type": "SecureString", "Overwrite": True}, f)
PY
aws ssm put-parameter --cli-input-json "file://$workdir/p.json" > /dev/null
echo "stored $prefix/BASIC_AUTH_HASH (run update.sh if the server is already up)"
