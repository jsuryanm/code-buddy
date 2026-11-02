# 0010. AWS free tier: one EC2 instance, Caddy, SSM parameters, a GHCR image

Status: accepted. Authored and checked offline (cfn-lint, shellcheck, unit tests); never
deployed. Date: 2026-11-02.

## Context
The tutor needs a first public deployment that a beginner can run on a new AWS account. Accounts
created on or after 2025-07-15 get the credit-based free plan: credits for 6 months, then the
account closes unless it is upgraded; eligible instance types include t3.micro, t3.small and
t4g.*. The app is one image that runs the API and the Streamlit UI. Vector search (Qdrant
Cloud), caches (Upstash), traces (Langfuse cloud) and models (OpenAI, Groq) are already managed
services outside AWS. Streamlit has no login, and every visitor spends the owner's OpenAI credit.

## Decision
- **One EC2 instance** (`deploy/aws/template.yaml`, CloudFormation): Amazon Linux 2023 from the
  SSM public parameter, t3.small by default (t3.micro allowed), encrypted gp3 root volume,
  IMDSv2 required with hop limit 1, no SSH key, security group open on TCP 80 and 443 only,
  access through SSM Session Manager. An Elastic IP gives a stable address.
- **Docker Compose on the instance** (`docker-compose.aws.yml`): `api`, `ui` and `caddy`, with
  per-service memory limits for 2 GiB, a 2 GiB swap file, capped json-file logs, and learner
  memory off. Only Caddy publishes ports.
- **Caddy** terminates HTTPS with automatic Let's Encrypt certificates for `DomainName` or, by
  default, `<ip-with-dashes>.sslip.io`, so no domain purchase is needed. It enforces HTTP basic
  auth on the whole site and proxies only the UI. The API stays on the private compose network;
  the UI calls it with a key from `CODEBUDDY_API_KEYS`.
- **Secrets in SSM Parameter Store** (SecureString under a prefix, default `/code-buddy`), never
  in the template, its parameters, UserData or Git. The instance role may read only that path,
  and decrypt only through SSM. A boot script writes `/opt/codebuddy/.env` (mode 600); running
  `codebuddy-update` refreshes it and pulls the image.
- **Prebuilt image on GitHub Container Registry**, built for linux/amd64 by
  `.github/workflows/docker-publish.yml` on every push to main. The instance never builds.
- The compose file and the Caddyfile are embedded in UserData (under the 16 KB limit), so the
  instance needs nothing from Git; `sync_template.py` copies them in and a test keeps them equal.

## Alternatives not taken
- **ECS on Fargate**: no free compute, and a public service wants an ALB or a public IP per task.
- **App Runner**: not in the free plan, and its scaling costs are hard to cap for a learner demo.
- **Lightsail**: simple, but a separate product with its own bundles and networking; plain EC2
  is the offer whose free-plan eligibility was confirmed for this account.
- **ALB + ACM certificates**: an ALB bills hourly (roughly the cost of the instance again);
  Caddy gets free certificates on the instance.
- **Terraform**: one more tool to install and state to keep; CloudFormation needs only the AWS
  CLI and deletes cleanly as one stack.
- **Building on the instance**: slow and memory-hungry on 1 to 2 GiB.

## Consequences
- Time limit: the free plan ends after 6 months and the account closes unless upgraded. After an
  upgrade the same stack bills normally (about a t3.small, 20 GiB gp3 and one public IPv4).
- Public IPv4 costs $0.005 per hour, also while stopped; whether the free plan covers it is
  UNCONFIRMED (assume it uses credits). A stopped instance still bills its disk and the Elastic
  IP; `scripts/destroy.sh` deletes everything the stack created.
- A single point of failure with no autoscaling: a reboot or replacement means minutes of
  downtime. The instance is stateless (state lives in the external services), so replacing it
  is safe; Caddy then requests a new certificate (Let's Encrypt rate limits apply).
- A newer AMI on a later `deploy.sh` replaces the instance.
- Basic auth is one shared password, not accounts. The API is reachable only through the UI.
- Ingestion runs from the developer's machine against Qdrant Cloud, not on the server.
- Unverified until a real run: the compose plugin download, Caddy behaviour and certificate
  issuance on sslip.io, the GHCR pull, and memory headroom on t3.micro.
