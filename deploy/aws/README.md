# CodeBuddy on the AWS free tier (quick reference)

One EC2 instance (t3.small default, t3.micro allowed) runs the prebuilt image from ghcr.io:
API + Streamlit UI behind Caddy (HTTPS, basic auth). Secrets live in SSM Parameter Store.
Qdrant Cloud, Upstash, Langfuse, OpenAI and Groq stay external. Authored and checked offline
only (cfn-lint, shellcheck, unit tests); **never deployed**. The full beginner guide is
[`docs/aws-free-tier.md`](../../docs/aws-free-tier.md).

Needs: AWS CLI v2 logged in (`AWS_PROFILE`, `AWS_REGION`), the Session Manager plugin, and the
image published by `.github/workflows/docker-publish.yml` and made public once.

```bash
cd deploy/aws
scripts/budget.sh --email you@example.com --amount 5   # alert before anything bills
scripts/put-secrets.sh                                  # or: --from-env-file ../../.env
scripts/make-basic-auth.sh                              # site password -> BASIC_AUTH_HASH
scripts/deploy.sh                                       # asks 'yes', prints Url and commands
scripts/status.sh                                       # stack, instance, site (401 = up), /healthz
scripts/update.sh                                       # after a new image or a secret change
scripts/destroy.sh                                      # deletes everything; stops the charges
```

Settings for `deploy.sh` are environment variables (`INSTANCE_TYPE`, `DOMAIN_NAME`,
`IMAGE_URI`, `BASIC_AUTH_USER`, ...; see `scripts/deploy.sh --help`). Ingest documents from
your own machine into Qdrant Cloud; the server does not ingest.

| File | What it is |
|---|---|
| `template.yaml` | CloudFormation: security group (80, 443 only), role, instance profile, Elastic IP, instance |
| `docker-compose.aws.yml`, `Caddyfile` | What runs on the server, also embedded in the template's UserData |
| `sync_template.py` | Copies those two files into `template.yaml` after you edit them (a test checks) |
| `scripts/` | The commands above |

On the server (`aws ssm start-session --target <InstanceId>`): files in `/opt/codebuddy`,
`sudo /usr/local/bin/codebuddy-update`, `sudo /usr/local/bin/codebuddy-status` (use the full path: `sudo` does not search `/usr/local/bin`), boot log `/var/log/codebuddy-bootstrap.log`.

Costs: public IPv4 $0.005/h (free-plan coverage unconfirmed), a stopped instance still bills
its disk and the Elastic IP, and the free plan ends after 6 months (the account closes unless
upgraded). `destroy.sh` removes everything the stack created.
