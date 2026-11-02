# Deploy CodeBuddy on the AWS free tier

This guide puts CodeBuddy on the internet, on one small AWS server, step by step. It assumes you
have never run a server, used Docker on a server, or used AWS before. Every new word is
explained the first time it appears, and there is a [glossary](#glossary) at the end.

> **Read this first: nothing in this guide has been deployed yet.**
> The files in [`deploy/aws/`](../deploy/aws/) were written and checked offline only. No one has
> run them against a real AWS account. Expect to fix small things on your first deploy. The box
> [What was tested and what was not](#what-was-tested-and-what-was-not) lists the risky points.

## Contents

1. [What you will end up with](#what-you-will-end-up-with)
2. [Why one server, and the limits](#why-one-server-and-the-limits)
3. [Before you start](#before-you-start)
4. [Step by step](#step-by-step)
   - [Step 1: Get the image onto GitHub](#step-1-get-the-image-onto-github)
   - [Step 2: Put your documents into Qdrant Cloud](#step-2-put-your-documents-into-qdrant-cloud)
   - [Step 3: Store your secrets in Parameter Store](#step-3-store-your-secrets-in-parameter-store)
   - [Step 4: Make the site password](#step-4-make-the-site-password)
   - [Step 5: Find your VPC and subnet](#step-5-find-your-vpc-and-subnet)
   - [Step 6: Deploy](#step-6-deploy)
   - [Step 7: Open the site](#step-7-open-the-site)
   - [Step 8: Set a budget alert](#step-8-set-a-budget-alert)
   - [Step 9: Check health and read logs](#step-9-check-health-and-read-logs)
   - [Step 10: Update after a change](#step-10-update-after-a-change)
   - [Step 11: Pause, stop, or delete everything](#step-11-pause-stop-or-delete-everything)
   - [Step 12: Before the free plan ends](#step-12-before-the-free-plan-ends)
5. [How it is secured](#how-it-is-secured)
6. [Cost guide](#cost-guide)
7. [Troubleshooting](#troubleshooting)
8. [What was tested and what was not](#what-was-tested-and-what-was-not)
9. [Glossary](#glossary)

### How to read the commands

Commands are in grey boxes. Copy them into a terminal (on Windows, use your WSL terminal).

Words in `<ANGLE_BRACKETS>` are placeholders. Replace the whole thing, brackets included, with
your own value. The placeholders used in this guide:

| Placeholder | What to put there | Example |
|---|---|---|
| `<PROFILE>` | The name of your AWS CLI login (profile) | `codebuddy` |
| `<REGION>` | The AWS region you deploy to | `us-east-1` |
| `<INSTANCE_ID>` | Your server's id, printed by `deploy.sh` | `i-0abc123def4567890` |
| `<VPC_ID>` | Your network's id (step 5) | `vpc-0abc1234` |
| `<SUBNET_ID>` | Your subnet's id (step 5) | `subnet-0abc1234` |
| `<QDRANT_URL>` | Your Qdrant Cloud cluster address | `https://xyz.cloud.qdrant.io` |
| `<QDRANT_KEY>` | Your Qdrant Cloud API key | (secret) |
| `<YOUR_EMAIL>` | Where AWS sends budget alerts | `you@example.com` |
| `<GITHUB_USER>` | Your GitHub user name | `jsuryanm` |

Unless a step says otherwise, run the commands from the `deploy/aws` folder of the repository:

```bash
cd ~/code-buddy/deploy/aws    # adjust if your copy of the repository is somewhere else
```

---

## What you will end up with

At the end you have a web address like `https://3-120-45-67.sslip.io`. Opening it asks for a
user name and password. After you log in, you see the CodeBuddy tutor, the same Streamlit page
you run on your own computer.

Here is what happens when you open that address:

```text
 Your browser
     |
     |  HTTPS (port 443), user name + password
     v
+------------------------------------------------------------+
|  ONE small AWS server (EC2, t3.small, Amazon Linux 2023)   |
|                                                            |
|   caddy  -->  ui (Streamlit, port 8501)  -->  api (8000)   |
|   HTTPS +                                    private,      |
|   password                                   not public    |
+------------------------------------------------------------+
                                                   |
               +-------------------+---------------+--------------+
               v                   v               v              v
            OpenAI           Qdrant Cloud       Upstash       Langfuse
        (models, paid)      (your documents)   (caches)    (traces, optional)
```

What each piece is, and what it costs:

| Piece | What it does | Where it runs | Cost |
|---|---|---|---|
| Caddy | Gets an HTTPS certificate, asks for the password, passes visitors on to the UI | On the server | Free software |
| UI (Streamlit) | The tutor web page | On the server | Free software |
| API | The tutor itself: policy, retrieval, model calls | On the server, private | Free software |
| The server (EC2) | One small virtual computer | AWS | Uses free-plan credits |
| Disk (EBS) | The server's 20 GiB hard drive | AWS | Uses credits, also while stopped |
| Public IP address | The server's fixed internet address | AWS | About $0.005 an hour, also while stopped |
| OpenAI | Writes the tutor's replies, makes embeddings | OpenAI | **Real money, per use. Your main cost** |
| Qdrant Cloud | Stores your documents for search | Qdrant | Free cluster tier available |
| Upstash | Caches, rate limits, sessions (optional, recommended) | Upstash | Free tier available |
| Langfuse | Traces for debugging (optional) | Langfuse | Free tier available |
| Groq | Voice to text (optional) | Groq | Free tier available |
| GitHub Container Registry | Stores the app's image | GitHub | Free for public images |

The free tiers of Qdrant, Upstash, Langfuse and Groq are those services' own offers. Check their
websites for current limits; this guide does not track them.

**Docker** is a tool that packs an app and everything it needs into one bundle, called an
**image**. A running copy of an image is a **container**. **Docker Compose** starts several
containers together from one file. On the server, Compose runs three containers: `caddy`, `ui`
and `api`. The file that describes them is
[`deploy/aws/docker-compose.aws.yml`](../deploy/aws/docker-compose.aws.yml).

The whole server is described in one file,
[`deploy/aws/template.yaml`](../deploy/aws/template.yaml). AWS reads it and creates everything
in one go. This is called **CloudFormation**, and the group of things it creates is a **stack**.
Deleting the stack deletes everything it created.

## Why one server, and the limits

### Why one server

A big company would put a **load balancer** in front of several servers, and use managed
database services. Each of those bills by the hour, whether anyone uses the site or not. A load
balancer alone costs roughly as much as the server again.

CodeBuddy does not need them:

- It has no database of its own to manage. Your documents live in Qdrant Cloud, caches in
  Upstash, traces in Langfuse. Those are already outside AWS.
- Caddy, a small free program on the server, gets HTTPS certificates for free. You do not need
  AWS's certificate service or a load balancer for that.
- One user (you, or a few people you trust) does not need several servers.

So the design is: one server, one fixed address, nothing billed per request. The reasons are
written down in [ADR 0010](adr/0010-aws-free-tier-single-instance.md).

### The limits

- **One server, no backup server.** If it reboots or is replaced, the site is down for a few
  minutes.
- **No autoscaling.** If many people use it at once, it gets slow. It does not add servers.
- **The free plan is time-limited.** AWS accounts created on or after 15 July 2025 get the
  credit-based free plan. It lasts 6 months. After that **the account closes unless you upgrade
  it** to a paid plan. See [step 12](#step-12-before-the-free-plan-ends).
- **Stopping the server does not stop all charges.** A stopped server still bills its disk and
  its public IP address. Only deleting the stack stops everything
  ([step 11](#step-11-pause-stop-or-delete-everything)).
- **The public IP address costs about $0.005 an hour** (about $3.60 a month), also while the
  server is stopped. Whether the new free plan covers this is **not confirmed**. Assume it uses
  your credits.
- **One shared password.** There are no user accounts. Everyone who knows the password is the
  same user.

---

## Before you start

Work through this checklist once. Each item says how to check that it worked.

### Accounts and keys

**1. An AWS account.** Sign up at <https://aws.amazon.com/>. During sign-up you choose a plan.

- Accounts created on or after 15 July 2025 get the **free plan**: credits for 6 months. This
  template is built for it. The eligible server sizes include `t3.micro` and `t3.small`.
- Older accounts have the **legacy free tier**: 750 hours a month of `t2.micro` or `t3.micro`
  for 12 months. On a legacy account, deploy with `INSTANCE_TYPE=t3.micro` (step 6), or a
  `t3.small` bills at the normal rate.

How to check: sign in to the AWS console, open **Billing and Cost Management**, and look at the
Free Tier and Credits pages. The exact page names can change; this guide could not check them.

Do not use the account's root login (the e-mail you signed up with) for daily work. Create a
user in **IAM Identity Center** with administrator access and use that. AWS's own sign-up guide
walks you through it.

**2. An OpenAI API key and model ids.** Create a key at <https://platform.openai.com/>. The app
needs three model ids, one for each tier: fast, standard and heavy. You choose them. For
example, this project has been run with `gpt-4o-mini` for fast and standard and `gpt-5-mini`
for heavy. Use whatever your OpenAI account offers.

Set a monthly spending limit in the OpenAI dashboard. OpenAI is the part that costs real money.

How to check: the key starts with `sk-`, and you can see it in the OpenAI dashboard.

**3. A Qdrant Cloud cluster.** Sign up at <https://cloud.qdrant.io/> and create a cluster (a free
one is fine). Write down its **endpoint** (the URL) and create an **API key**.

How to check: the cluster shows as running in the Qdrant Cloud console.

**4. An Upstash Redis database (optional, recommended).** Sign up at <https://upstash.com/>,
create a Redis database, and copy its **REST URL** and **REST token**. Without it, caches and
rate limits live only inside the server's memory and reset on every restart.

**5. A Langfuse project (optional).** Sign up at <https://cloud.langfuse.com/>, create a project
and copy its public key, secret key and base URL. Traces contain metadata only, never learner
text (see [observability.md](observability.md)).

**6. A Groq API key (optional).** Only needed for voice input. Get one at
<https://console.groq.com/>.

**7. The GitHub repository.** The code lives at <https://github.com/jsuryanm/code-buddy>. You
need to be able to push to its `main` branch, because that is what builds the image (step 1).

### Tools on your computer

You need the AWS command line tool and one plugin. **You do not need Docker on your computer**
for the deploy: the image is built by GitHub, and the server runs it.

**AWS CLI v2.** This is the `aws` command. Install it (Linux and WSL, x86_64):

```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
```

What you should see when you check it:

```bash
aws --version
```

```text
aws-cli/2.x.x Python/3.x.x Linux/... 
```

The first number must be `2`. For macOS or Windows, follow AWS's page "Installing or updating
the latest version of the AWS CLI".

**Log the AWS CLI in.** Pick one of these two ways.

With IAM Identity Center (recommended, no long-lived keys on your computer):

```bash
aws configure sso --profile <PROFILE>
aws sso login --profile <PROFILE>       # repeat this when the login expires
```

Or with an access key for an IAM user:

```bash
aws configure --profile <PROFILE>
```

It asks for the access key id, the secret access key, the default region (for example
`us-east-1`) and the output format (press Enter).

**Tell every terminal which login and region to use.** The scripts read these two variables. Run
this in each new terminal before you use the scripts:

```bash
export AWS_PROFILE=<PROFILE>
export AWS_REGION=<REGION>
```

How to check it worked:

```bash
aws sts get-caller-identity
```

What you should see: a small JSON block with your `Account` number and an `Arn`. If you see
"Unable to locate credentials" or "token has expired", log in again.

**Session Manager plugin.** This lets you open a terminal on the server without SSH. Install it
on Ubuntu or WSL:

```bash
curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o "session-manager-plugin.deb"
sudo dpkg -i session-manager-plugin.deb
```

How to check it worked:

```bash
session-manager-plugin
```

What you should see: a message that says the plugin was installed successfully. For other
systems, search AWS's documentation for "Install the Session Manager plugin for the AWS CLI".

**uv and Python.** You already use them to run the app locally. Step 2 uses them for ingestion,
and step 4 uses them to make the password hash.

---

## Step by step

> **Tip:** do [step 8 (budget alert)](#step-8-set-a-budget-alert) before step 6. It takes one
> minute and warns you by e-mail before costs grow.

### Step 1: Get the image onto GitHub

**What it does.** The server does not build the app. It downloads a ready-made image from
GitHub Container Registry (GHCR), GitHub's place for images. The workflow
[`.github/workflows/docker-publish.yml`](../.github/workflows/docker-publish.yml) builds the
image from the [`Dockerfile`](../Dockerfile) every time something is pushed to `main`.

**The image name.** The workflow names the image after the repository: `ghcr.io/` plus the
repository path in lower case. The repository is `github.com/jsuryanm/code-buddy`, so the image
is:

```text
ghcr.io/jsuryanm/code-buddy:latest
```

That is also the default `IMAGE_URI` in `deploy.sh`. Each build gets two tags: `latest` and the
short commit id (for example `ghcr.io/jsuryanm/code-buddy:3f2a1bc`). If you fork the repository
under another GitHub user, the image is `ghcr.io/<GITHUB_USER>/code-buddy:latest`, and you must
set `IMAGE_URI` to that in step 6.

**1a. Push to `main`.** Merge your work into `main` and push it:

```bash
git push origin main
```

The workflow also has a **Run workflow** button (in the Actions tab, under "Publish image"), but
GitHub only shows it once the workflow file is on `main`.

**1b. Watch the build.** On GitHub, open the repository, then the **Actions** tab, then the run
called **Publish image**. Or, with the GitHub CLI:

```bash
gh run list --workflow docker-publish.yml
```

What you should see: a green tick after several minutes. The first build is the slowest.

If it fails: open the run and read the red step. A failure in "build-push-action" is usually a
Docker build error; the same error would appear in a local `docker build`. A permission error on
push means the workflow could not write packages: check that the repository's Actions settings
allow the `GITHUB_TOKEN` to write packages.

**1c. Make the image public (once).** A new package on GHCR is **private**. The server downloads
it without a password, so it must be public:

1. On GitHub, open your profile, then **Packages**, then **code-buddy**.
2. Open **Package settings**.
3. Under **Change visibility**, choose **Public** and confirm.

The image holds the code and no secrets (the [`.dockerignore`](../.dockerignore) keeps `.env`,
data and logs out). Public means anyone can download the code in the image.

**To keep it private instead**, create a classic personal access token on GitHub with only the
`read:packages` scope, and store it in step 3 as `GHCR_USER` (your GitHub user name) and
`GHCR_TOKEN` (the token). The server then logs in to GHCR before it downloads.

How to check: the package page shows the tags `latest` and a short commit id, and says Public.

### Step 2: Put your documents into Qdrant Cloud

**What it does.** The tutor answers from your documents (for example Think Python). They must be
in a search index. On your computer the index lives in the folder `data/index`. **That folder is
not copied to the server**, and the image does not contain it. The server reads your documents
from Qdrant Cloud instead, so you load them there once, from your own computer. This is called
**ingestion**. The server never ingests.

Run this from the repository root (not `deploy/aws`):

```bash
cd ~/code-buddy
uv sync --extra pdf      # PDF support; downloads PyTorch, several GB, only needed once
```

Then ingest. The two variables point ingestion at your cluster instead of the local folder:

```bash
QDRANT_CLUSTER_ENDPOINT=<QDRANT_URL> QDRANT_API_KEY=<QDRANT_KEY> CUDA_VISIBLE_DEVICES= \
  uv run python -m codebuddy.rag.ingest data/raw/thinkpython.pdf \
  --corpus fundamentals --title "Think Python"
```

What each part means:

- `QDRANT_CLUSTER_ENDPOINT` and `QDRANT_API_KEY`: your cluster. You can put them in your local
  `.env` instead of typing them.
- `CUDA_VISIBLE_DEVICES=` (empty): avoids a crash of the PDF converter on WSL when it looks for
  a graphics card.
- `--corpus fundamentals`: the learner-facing collection.
- Ingesting the same file locally first does not matter: each target (the local folder, and each
  cluster and collection prefix) keeps its own record of ingested files in
  `data/index/manifest.json`, so the cluster still gets the file. (`--force` is only for
  re-ingesting an unchanged file on purpose.)
- `OPENAI_API_KEY` must be set (in your `.env` is fine). Ingestion uses OpenAI to make
  embeddings, which costs a little money.

What you should see: log lines that name the target as `server host=...` (your cluster, not
`embedded path=data/index`), then one line per file with the number of chunks. The 240-page
book took several minutes on a laptop CPU.

If it fails:

- "cannot reach" or an authentication error: check the endpoint URL and the API key.
- The log says `embedded path=data/index`: the cluster variables were not picked up. Check the
  spelling.
- It says the file was skipped: it was already ingested into this same cluster and has not changed. Add `--force` only if you want it again.

**Collection names.** Collections are named `<prefix>_<corpus>_<version>`, for example
`cb_fundamentals_v1`. The prefix comes from `QDRANT_COLLECTION_NAME` (default `cb`). If you set
a prefix here, store the same value on the server in step 3.

More about ingestion: [rag-and-ingestion.md](rag-and-ingestion.md).

### Step 3: Store your secrets in Parameter Store

**What it does.** Your keys must reach the server, but they must never be in Git or in the
template. AWS **Systems Manager Parameter Store** is a safe box for small values. Each key is
stored encrypted (as a **SecureString**) under the path `/code-buddy`. The server, and only the
server, is allowed to read that path. The standard tier is free.

The script [`put-secrets.sh`](../deploy/aws/scripts/put-secrets.sh) asks for each value. Typing
is hidden. Press Enter to skip a name.

```bash
cd ~/code-buddy/deploy/aws
scripts/put-secrets.sh
```

Or take the values from your local `.env` file (only the names below are read; values are
never printed):

```bash
scripts/put-secrets.sh --from-env-file ../../.env
```

To set or change only some names:

```bash
scripts/put-secrets.sh --only CODEBUDDY_API_KEYS --only QDRANT_COLLECTION_NAME
```

The names, in the order the script asks for them:

| Name | Needed? | What it is |
|---|---|---|
| `OPENAI_API_KEY` | **Required** | Your OpenAI key |
| `CODEBUDDY_MODEL_FAST` | **Required** | Model id for the fast tier |
| `CODEBUDDY_MODEL_STANDARD` | **Required** | Model id for the standard tier |
| `CODEBUDDY_MODEL_HEAVY` | **Required** | Model id for the heavy tier |
| `CODEBUDDY_API_KEYS` | **Required** | A long random string. The UI uses it to talk to the API. Make one with `openssl rand -hex 32` |
| `CODEBUDDY_MEMORY_SECRET` | Skip | Learner memory is turned off on this deployment |
| `GROQ_API_KEY` | Optional | Voice input |
| `UPSTASH_REDIS_REST_URL` | Recommended | Upstash REST URL |
| `UPSTASH_REDIS_REST_TOKEN` | Recommended | Upstash REST token |
| `QDRANT_CLUSTER_ENDPOINT` | Recommended | Your Qdrant Cloud URL. Without it the server has no documents |
| `QDRANT_API_KEY` | Recommended | Your Qdrant Cloud key |
| `QDRANT_COLLECTION_NAME` | Optional | Collection prefix; only if you used one other than `cb` in step 2 |
| `LANGFUSE_PUBLIC_KEY` | Optional | Langfuse traces |
| `LANGFUSE_SECRET_KEY` | Optional | Langfuse traces |
| `LANGFUSE_BASE_URL` | Optional | For example `https://cloud.langfuse.com` |
| `GHCR_USER` | Only for a private image | Your GitHub user name (step 1c) |
| `GHCR_TOKEN` | Only for a private image | A token with `read:packages` (step 1c) |

The site password hash, `BASIC_AUTH_HASH`, has its own script (step 4).

Values must not contain a single quote (`'`) or a line break. The server refuses them.

What you should see: one `stored /code-buddy/<NAME>` line per value and `skipped <NAME>` for the
ones you left empty.

If it fails:

- "AccessDenied": your AWS login may not create parameters. Use an administrator login.
- "Unable to locate credentials" or the wrong region: run the two `export` lines from
  [Before you start](#tools-on-your-computer) again.

How to check (names only, no values):

```bash
aws ssm get-parameters-by-path --path /code-buddy --query 'Parameters[].Name' --output text
```

### Step 4: Make the site password

**What it does.** Streamlit has no login. Without a password, anyone who finds the address could
use the tutor, and every question would spend your OpenAI money. So Caddy asks for a user name
and password before it lets anyone in. This is called **basic auth**.

The user name is `tutor` (change it with `BASIC_AUTH_USER` in step 6). The script
[`make-basic-auth.sh`](../deploy/aws/scripts/make-basic-auth.sh) asks for the password, turns it
into a **bcrypt hash** (a scrambled form that cannot be turned back into the password), and
stores only the hash as `/code-buddy/BASIC_AUTH_HASH`.

```bash
scripts/make-basic-auth.sh
```

It asks twice, hidden. The password must have at least 12 characters. Write it in a password
manager: it is not stored anywhere in readable form.

What you should see:

```text
stored /code-buddy/BASIC_AUTH_HASH (run update.sh if the server is already up)
```

If it fails:

- "need uv, python3 with bcrypt (pip install bcrypt), or docker": install uv, which you already
  use for the project.
- "passwords differ" or "use at least 12 characters": run it again.

To change the password later, run the script again and then `scripts/update.sh` (step 10).

### Step 5: Find your VPC and subnet

**What it does.** A **VPC** is your private network inside AWS. A **subnet** is a slice of it in
one data centre. Every new AWS account has a **default VPC** with public subnets in each region,
and `deploy.sh` finds them by itself. **You can skip this step** unless `deploy.sh` says "no
default VPC" or you want a specific subnet.

To see your default VPC:

```bash
aws ec2 describe-vpcs --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text
```

What you should see: an id like `vpc-0abc1234`. `None` means there is no default VPC.

To list its default subnets (the ones `deploy.sh` picks from):

```bash
aws ec2 describe-subnets --filters Name=vpc-id,Values=<VPC_ID> Name=default-for-az,Values=true \
  --query 'Subnets[].[SubnetId,AvailabilityZone]' --output table
```

What you should see: a table of subnet ids and zones such as `us-east-1a`. `deploy.sh` takes
the one whose zone comes first alphabetically.

To use your own choice, set both before step 6:

```bash
export VPC_ID=<VPC_ID>
export SUBNET_ID=<SUBNET_ID>
```

The subnet must be **public** (it must have a route to the internet). Any subnet of the default
VPC is public.

If there is no default VPC: you can recreate one in the VPC console ("Create default VPC"), or
create a VPC with a public subnet yourself. The second is outside the scope of this guide.

### Step 6: Deploy

> **Costs money (or credits) from here on.** The server, its disk and its public IP address bill
> until you delete the stack with `destroy.sh` (step 11). Stopping the server is not enough.

**What it does.** The script [`deploy.sh`](../deploy/aws/scripts/deploy.sh) checks that the
required secrets exist, shows what it will create, asks you to type `yes`, then asks
CloudFormation to build the stack from [`template.yaml`](../deploy/aws/template.yaml).

The stack contains:

- a **security group** (a firewall) that lets in only ports 80 (HTTP) and 443 (HTTPS). No SSH;
- an **IAM role** and **instance profile**: the server's permission to use Session Manager and
  to read the `/code-buddy` secrets, nothing else;
- an **Elastic IP**: a fixed public address that stays the same even if the server is replaced;
- the **EC2 instance** (the server): Amazon Linux 2023, `t3.small`, an encrypted 20 GiB disk.

When the server starts for the first time, a start-up script (the template's **UserData**)
installs Docker and Compose, creates 2 GiB of swap (disk used as extra memory), writes the
Compose file and the Caddyfile to `/opt/codebuddy`, reads your secrets into
`/opt/codebuddy/.env`, downloads the image and starts the containers.

Run it with the defaults:

```bash
scripts/deploy.sh
```

Settings are environment variables. You only need them to change a default:

| Variable | Default | Meaning |
|---|---|---|
| `STACK_NAME` | `code-buddy` | Name of the stack |
| `INSTANCE_TYPE` | `t3.small` | `t3.small` (2 GiB memory) or `t3.micro` (1 GiB, slower) |
| `VOLUME_SIZE` | `20` | Disk size in GiB, 8 to 30 |
| `IMAGE_URI` | `ghcr.io/jsuryanm/code-buddy:latest` | The image from step 1 |
| `SSM_PREFIX` | `/code-buddy` | Where the secrets are |
| `DOMAIN_NAME` | empty | Your own domain; empty means `<ip-with-dashes>.sslip.io` |
| `BASIC_AUTH_USER` | `tutor` | The site's user name |
| `ALLOWED_CIDR` | `0.0.0.0/0` | Who may connect. Narrowing it breaks automatic certificates |
| `VPC_ID`, `SUBNET_ID` | default VPC and subnet | From step 5 |

For example, a smaller server on a legacy free-tier account:

```bash
INSTANCE_TYPE=t3.micro scripts/deploy.sh
```

What you should see first:

```text
About to create or update stack 'code-buddy' in us-east-1:
  instance t3.small, 20 GiB gp3 disk, Elastic IP (public IPv4, $0.005/h)
  vpc vpc-..., subnet subnet-..., image ghcr.io/jsuryanm/code-buddy:latest
These bill (or use free-plan credits) until you run scripts/destroy.sh.
Type 'yes' to continue:
```

Type `yes` and press Enter. Anything else cancels. CloudFormation then works for a few minutes.
When it is done, the script prints a table of **outputs**:

| Output | What it is |
|---|---|
| `Url` | The site address |
| `InstanceId` | The server's id (your `<INSTANCE_ID>`) |
| `PublicIp` | The fixed IP address |
| `ConnectCommand` | The command that opens a terminal on the server |
| `BootstrapLogCommand` | The command that shows the first-boot log |
| `DeleteCommand` | The command that deletes the stack |

The last line says: "First boot takes about 5 minutes." The stack is finished when the server
exists, not when the app is ready. The app needs those extra minutes.

Watch the first boot with the `BootstrapLogCommand` from the table. It looks like this:

```bash
aws ssm start-session --region <REGION> --target <INSTANCE_ID> \
  --document-name AWS-StartInteractiveCommand \
  --parameters command="sudo tail -n 100 -f /var/log/codebuddy-bootstrap.log"
```

What you should see: lines starting with `[codebuddy ...]`, ending with
`BOOTSTRAP DONE: https://...`. Press Ctrl+C to stop watching. If the session cannot start yet,
wait a minute: the server needs time to register with Session Manager.

If it fails:

- "missing SSM parameters under /code-buddy: ...": do steps 3 and 4.
- "no default VPC": see step 5.
- The stack fails or rolls back: see [Troubleshooting](#troubleshooting), first row.
- The bootstrap log shows `CODEBUDDY BOOTSTRAP FAILED (exit ...) at line ...`: the line above it
  says what went wrong. See [Troubleshooting](#troubleshooting).

**Running it again.** `deploy.sh` also updates an existing stack. If AWS has published a newer
Amazon Linux image since the last deploy, CloudFormation **replaces the server** with a new
one. The address stays the same (the Elastic IP is kept), but sessions stored on the old server
are lost and Caddy fetches a new certificate.

### Step 7: Open the site

**What it does.** You visit the `Url` from step 6.

**The address.** Without your own domain, the address is your IP address with dashes, followed
by `.sslip.io`, for example `https://3-120-45-67.sslip.io`. **sslip.io** is a free public
service that turns any such name back into the IP address inside it. That gives you a real
hostname, which a certificate needs, without buying a domain.

To use your own domain instead: create an `A` record for it that points at the `PublicIp`
output, then deploy again with `DOMAIN_NAME=<your domain> scripts/deploy.sh`.

**The first visit.**

1. Wait until the bootstrap log says `BOOTSTRAP DONE` (step 6).
2. Open the `Url`. For the first minute you may get a security or connection error: Caddy is
   still getting the certificate from **Let's Encrypt**, a free certificate authority. Wait a
   minute and reload.
3. Your browser asks for a user name and password. Enter `tutor` (or your `BASIC_AUTH_USER`)
   and the password from step 4.
4. The CodeBuddy tutor appears.

What you should see: the padlock in the address bar, and the tutor page.

A quick check from your computer, without a browser:

```bash
scripts/status.sh --no-remote
```

The line `site: https://... -> HTTP 401` means Caddy is up and asking for the password. That is
the expected answer for a request without a password.

If it fails: see "Certificate not issued", "502 from Caddy", "UI says it can't reach the tutor"
and "Login loop" in [Troubleshooting](#troubleshooting).

### Step 8: Set a budget alert

**What it does.** An **AWS Budget** e-mails you when spending passes a limit. The script
[`budget.sh`](../deploy/aws/scripts/budget.sh) creates a monthly budget (default 5 US dollars)
that e-mails you when actual spend passes 80% of it, and when AWS forecasts that the month will
go over 100%. The first two budgets in an account are free.

```bash
scripts/budget.sh --email <YOUR_EMAIL> --amount 5
```

What you should see:

```text
budget 'code-buddy-monthly' created: 5 USD a month, alerts to you@example.com
```

**About credits.** The budget leaves credits out. It tracks what your resources would cost
before free-plan credits. If it counted credits, the spend would show as 0 and the alert would
never fire. How the new free plan's credits show up in AWS Budgets is **not confirmed**: open the
Budgets page in the console after a day and check that it shows spending.

If it fails:

- "DuplicateRecordException": a budget with that name exists. Use `--name <another name>`.
- "AccessDenied": use an administrator login.

This alert is for AWS only. OpenAI has its own limits: set one in the OpenAI dashboard.

### Step 9: Check health and read logs

**The quick way, from your computer:**

```bash
scripts/status.sh
```

It prints, in order: the stack status (`CREATE_COMPLETE` or `UPDATE_COMPLETE` is good), the
server's id, size and state (`running`), the site's HTTP code (`401` is good), and then, from
the server: the containers, the API's health check, memory and disk.

In the API health check (a JSON block), look for:

- `"status":"ok"`;
- `"models_configured":true` (the three model ids are set);
- `"qdrant":"server"` (it uses Qdrant Cloud; `embedded` means the Qdrant secrets are missing);
- `"auth_required":true` (the API demands `CODEBUDDY_API_KEYS`).

**Open a terminal on the server.** Session Manager gives you a shell in your own terminal,
without SSH and without opening any port. Use the `ConnectCommand` output:

```bash
aws ssm start-session --region <REGION> --target <INSTANCE_ID>
```

What you should see: a prompt like `sh-5.2$`. You are logged in as `ssm-user`. Use `sudo` for
Docker commands. Type `exit` to leave.

Useful commands on the server:

```bash
cd /opt/codebuddy
sudo docker compose ps                     # the three containers and their state
sudo /usr/local/bin/codebuddy-status       # containers, API /healthz, memory, disk
sudo docker compose logs --tail 100 api    # last 100 lines of the API container
sudo docker compose logs --tail 100 ui
sudo docker compose logs --tail 100 caddy  # certificates and proxy errors
sudo docker logs codebuddy-api-1           # the same API log, by container name
```

The helpers `codebuddy-status` and `codebuddy-update` live in `/usr/local/bin`. This guide
writes the full path because `sudo` may not search that folder on Amazon Linux (not checked).

`docker compose ps` should show `api`, `ui` and `caddy` as running (`api` and `ui` also as
`healthy`).

**Where the files are on the server:**

| Path | What it is |
|---|---|
| `/opt/codebuddy/docker-compose.yml` | What runs (a copy of `docker-compose.aws.yml`) |
| `/opt/codebuddy/Caddyfile` | Caddy's settings |
| `/opt/codebuddy/.env` | Your secrets, written from Parameter Store. Readable by root only. Do not edit; it is rewritten on every update |
| `/opt/codebuddy/site.env` | Non-secret settings: image, address, user name, region |
| `/opt/codebuddy/logs/YYYY-MM-DD/` | The app's own log files, for example `api_HH-MM-SS.log`, `ui_HH-MM-SS.log`, and `.errors.log` files. Kept 5 days |
| `/var/log/codebuddy-bootstrap.log` | The first-boot log |
| `/var/log/cloud-init-output.log` | The same, plus everything else that ran at first boot |

To read today's API log:

```bash
sudo ls /opt/codebuddy/logs/$(date -u +%F)/
sudo tail -n 50 /opt/codebuddy/logs/$(date -u +%F)/api_*.log
```

The app's logs hold metadata only: timings, modes, counts and hashed ids. They never contain
learner text, code or replies (see [observability.md](observability.md)). Container logs are
capped at 3 files of 10 MB per container.

### Step 10: Update after a change

**What it does.** After you push new code to `main`, GitHub builds a new `latest` image (step 1).
The server does not notice by itself. The script
[`update.sh`](../deploy/aws/scripts/update.sh) tells the server to re-read the secrets from
Parameter Store, download the newest image, and restart the containers that changed.

Use it after:

- a new image was published (wait for the green tick in GitHub Actions first);
- you changed a secret (step 3) or the password (step 4).

```bash
scripts/update.sh
```

What you should see: `updating i-...`, then the output of `docker compose ps` from the server,
then `status: Success`. The site is unavailable for a few seconds while containers restart. The
script waits up to about 10 minutes.

If it fails: the output shows the server's error. "missing SSM parameters" means a required
secret was deleted. A pull error means the image is private or the name is wrong (see
[Troubleshooting](#troubleshooting)).

The same by hand, on the server:

```bash
aws ssm start-session --region <REGION> --target <INSTANCE_ID>
sudo /usr/local/bin/codebuddy-update
```

**Changing settings that live in the template** (instance size, disk size, domain, user name,
image name): run `deploy.sh` again with the new environment variables. Some of these changes
replace the server (see "Running it again" in step 6).

**Changing the Compose file or the Caddyfile.** The template carries a copy of both. After you
edit [`docker-compose.aws.yml`](../deploy/aws/docker-compose.aws.yml) or
[`Caddyfile`](../deploy/aws/Caddyfile), copy them into the template and deploy:

```bash
cd ~/code-buddy
uv run python deploy/aws/sync_template.py
cd deploy/aws && scripts/deploy.sh
```

A unit test fails while the copies differ. A UserData change replaces the server.

### Step 11: Pause, stop, or delete everything

**Stopping the server (pause).** This stops the hourly charge for the server itself, but **the
disk and the public IP address keep billing**:

```bash
aws ec2 stop-instances --instance-ids <INSTANCE_ID>
aws ec2 start-instances --instance-ids <INSTANCE_ID>    # to start it again
```

The address stays the same. The containers are set to restart on their own when Docker starts
again (`restart: unless-stopped`); this was not tested.

**Deleting everything.**

> **Deletes data.** This deletes the server and its disk: chat sessions stored on it and the
> certificate are gone. Your documents in Qdrant Cloud, Upstash and Langfuse are outside AWS
> and stay. Your secrets in Parameter Store stay too, unless you add `--delete-secrets`.

```bash
scripts/destroy.sh
```

It asks you to type the stack name (`code-buddy`) to confirm, then waits until the stack is
gone. What you should see at the end:

```text
stack code-buddy deleted
```

To also delete every secret under `/code-buddy`:

```bash
scripts/destroy.sh --delete-secrets
```

The budget from step 8 is not part of the stack and stays. Delete it in the Budgets console if
you no longer want it.

**Confirm that nothing still bills.** Check these in the AWS console, in the region you used:

1. **CloudFormation**: the stack `code-buddy` is gone (or shows `DELETE_COMPLETE`).
2. **EC2 > Instances**: no running or stopped instance named `code-buddy`. (A terminated one
   disappears from the list after a while and does not bill.)
3. **EC2 > Elastic IPs**: no address left. An unattached Elastic IP still bills.
4. **EC2 > Volumes**: no volume left from the server.
5. **Billing and Cost Management > Bills**: over the next day or two, the charges for EC2 and
   VPC (public IPv4) stop growing.

Or from the terminal:

```bash
aws cloudformation describe-stacks --stack-name code-buddy   # should say "does not exist"
aws ec2 describe-addresses --query 'Addresses[].PublicIp'    # should print []
aws ec2 describe-volumes --query 'Volumes[].VolumeId'        # should not list the server's disk
```

If the stack deletion fails: open the stack in the CloudFormation console, look at the Events
tab for the red line, fix it (for example delete a resource by hand), and run `destroy.sh` again.

### Step 12: Before the free plan ends

The free plan lasts 6 months from sign-up. After that, AWS closes the account unless you upgrade
it, and everything in it goes away. Mark the date in your calendar. Around month 5, pick one:

1. **Upgrade the account** to a paid plan in **Billing and Cost Management**. The same stack keeps
   running and bills at normal prices: a `t3.small`, a 20 GiB disk and one public IP address. The
   [cost guide](#cost-guide) has rough numbers. Keep the budget alert.
2. **Delete the stack** with `destroy.sh` (step 11) and stop using AWS.
3. **Move elsewhere.** The image runs anywhere Docker runs. Copy
   [`docker-compose.aws.yml`](../deploy/aws/docker-compose.aws.yml) and the
   [`Caddyfile`](../deploy/aws/Caddyfile) to another server, write the `.env` by hand with the
   same names as in step 3 (plus `IMAGE_URI`, `SITE_ADDRESS`, `BASIC_AUTH_USER`,
   `BASIC_AUTH_HASH` and `CODEBUDDY_API_KEY`, the first of your `CODEBUDDY_API_KEYS`), and run
   `docker compose up -d`. This path has not been tried.

Your documents, caches and traces live in Qdrant Cloud, Upstash and Langfuse, not in AWS, so they
survive whatever you choose. Keep a copy of your secrets outside AWS (your local `.env` or a
password manager): Parameter Store goes away with the account.

If your credits run out before 6 months, AWS's free-plan rules decide what happens next. Check
the free plan page in the Billing console; this guide could not confirm the details.

---

## How it is secured

In plain words, here is what protects the site and your money.

**No SSH.** SSH is the usual way to log in to a server, through port 22 and a key file. This
server has no key and port 22 is closed. You get a terminal through **Session Manager**, which
goes through your AWS login instead. Nothing to leak, no port to attack.

**Only two ports are open.** The firewall (security group) allows only 80 and 443. Port 80 is
needed for Let's Encrypt to check that you own the address, and to redirect visitors to HTTPS.

**HTTPS everywhere, automatically.** Caddy gets and renews the certificate on its own and sends
security headers (for example `Strict-Transport-Security`, which tells browsers to always use
HTTPS).

**A password in front of everything.** Caddy's basic auth covers the whole site. This matters
because Streamlit has no login: without it, anyone who found the address could use the tutor on
your OpenAI bill. Only a bcrypt hash of the password is stored.

**The API is private.** Only Caddy has public ports. The API listens on the private network
between the containers, and the UI must present a key from `CODEBUDDY_API_KEYS` to use it.

**Secrets are in Parameter Store, not in files in Git.** They are encrypted. The server's role
may read only the `/code-buddy` path, and may decrypt only through Parameter Store. On the
server they are written to `/opt/codebuddy/.env`, readable by root only. The template, the
UserData and the repository contain no secrets.

**IMDSv2 only.** Every EC2 server has a metadata service that can hand out its temporary AWS
credentials. The template requires the safer version (IMDSv2) and blocks containers from
reaching it, so a bug in the app cannot steal the server's AWS permissions.

**Encrypted disk.** The server's disk is encrypted by AWS.

**Logs hold metadata only.** No learner text, code, replies or raw ids (see
[observability.md](observability.md)). Langfuse traces follow the same rule.

**What is NOT protected:**

- **One shared password.** Anyone with it is "you". There are no accounts and no way to lock out
  one person except changing the password for everyone.
- **No web application firewall (WAF)** and no protection against floods of requests.
- **No rate limit at the edge.** Caddy does not limit requests. The app has its own rate limits
  (stronger with Upstash), but a person with the password can still run up OpenAI costs.
  The OpenAI spending limit is your last line of defence.
- **The sandbox that runs learner code is not a security boundary** (see
  [security.md](security.md)). Code runs only after approval, but it runs on your server.
- **One server.** No backups are needed for state (it lives outside AWS), but there is no
  standby if the server breaks.

---

## Cost guide

> **Prices change.** The dollar figures below are approximate on-demand prices for the US East
> (N. Virginia) region at the time of writing. Check the AWS and OpenAI pricing pages before you
> rely on them.

| Item | Free? | Approximate cost | What to watch |
|---|---|---|---|
| EC2 `t3.small` | Uses free-plan credits | About $0.02 an hour, about $15 a month | Runs 24 hours a day until deleted |
| EC2 `t3.micro` | Uses free-plan credits | About $0.01 an hour, about $7.50 a month | Slower; may run out of memory |
| EBS disk, 20 GiB gp3 | Uses free-plan credits | About $1.60 a month | Bills while stopped |
| Public IPv4 address | Coverage by the free plan unconfirmed | $0.005 an hour, about $3.60 a month | Bills while stopped and while unattached |
| Data out to the internet | A free monthly amount exists | Small for one user | Large downloads |
| Parameter Store, standard tier | Free | $0 | |
| Session Manager | Free | $0 | |
| CloudFormation | Free | $0 | |
| AWS Budgets (first two) | Free | $0 | |
| GHCR, public image | Free | $0 | |
| Qdrant Cloud, Upstash, Langfuse, Groq | Their free tiers | $0 within limits | Their usage pages |
| **OpenAI** | **No** | **Per token; see below** | **Your real cost** |

### How to read the Free Tier page

In the AWS console, open **Billing and Cost Management**. The **Free Tier** page lists services
and how much of their free amount you have used this month. The **Credits** page shows how many
free-plan credits are left and when they expire. **Bills** shows charges by service: look for
"Elastic Compute Cloud" and "Virtual Private Cloud" (the public IP address). Page names may differ
slightly from these; this guide could not check them against a live account.

### Estimating OpenAI spend

Every tutor turn sends a prompt to OpenAI and gets a reply. You pay per **token** (roughly 4
characters of English). A rough monthly estimate:

```text
monthly cost = turns per month
             x (input tokens per turn  x input price per token
              + output tokens per turn x output price per token)
```

Look up current prices at <https://openai.com/api/pricing/>. Prices are listed per million
tokens: divide by 1,000,000 to get the price per token. To learn your real tokens per turn, use
the tutor for a while and read the Usage page in the OpenAI dashboard. Ingestion (step 2) also
costs a little, for embeddings, once per document.

Reasoning models (some heavy-tier choices) also bill for hidden "reasoning" tokens, so they cost
more per turn than the visible reply suggests.

Why OpenAI is the real cost: the AWS part is a fixed, small amount covered by credits for 6
months. OpenAI grows with every question, and a shared password can be shared further. Set a
monthly limit in the OpenAI dashboard.

---

## Troubleshooting

To look closer at any problem, open a terminal on the server (step 9) and read the bootstrap log
and the container logs.

| Symptom | Likely cause | Fix |
|---|---|---|
| Stack fails to create (`ROLLBACK_COMPLETE`) | Wrong region, a server type your account may not launch, no permission to create IAM roles, or a bad parameter | Open the stack in the CloudFormation console, Events tab: the first red line names the reason. Delete the failed stack (`scripts/destroy.sh`), fix, deploy again |
| Stack is done but the site never answers | First boot still running, or the bootstrap failed | Watch the bootstrap log (step 6). Look for `CODEBUDDY BOOTSTRAP FAILED` and the line before it. Also read `/var/log/cloud-init-output.log` |
| Bootstrap fails while installing Docker or Compose | `dnf install docker` or the Compose download from GitHub failed (both untested) | Read the error in the bootstrap log. A checksum error means the downloaded file did not match the pinned one. Delete the stack and deploy again; if it repeats, report it |
| Certificate not issued (browser security error after several minutes) | Ports 80 or 443 blocked, `ALLOWED_CIDR` narrowed, the address does not point at the server, or a Let's Encrypt rate limit | `sudo docker compose logs caddy` on the server. Keep `ALLOWED_CIDR` at `0.0.0.0/0`. With your own domain, check its `A` record. Rate limits clear after some time; do not delete and recreate the stack in a loop |
| 502 from Caddy | The UI container is not running yet, restarting, or crashed | `sudo docker compose ps` and `sudo docker compose logs ui`. Wait a minute after a restart. If it keeps crashing, see "Out of memory" |
| UI says "Can't reach the tutor" | The API container is down, still starting, or `CODEBUDDY_API_KEYS` does not match | `sudo docker compose logs api`. Run `sudo /usr/local/bin/codebuddy-status` to see `/healthz`. After changing secrets, run `scripts/update.sh` |
| Login loop (the password box keeps coming back) | Wrong user name or password, or the hash was changed but the server not updated | User name is `tutor` unless you set `BASIC_AUTH_USER`. Run `scripts/make-basic-auth.sh` again, then `scripts/update.sh` |
| Out of memory (containers restart, exit code 137, very slow) | `t3.micro` has 1 GiB; the containers are limited to 800 MiB (api), 500 MiB (ui) and 96 MiB (caddy) | `free -m` on the server. Use `t3.small` (`INSTANCE_TYPE=t3.small scripts/deploy.sh`) |
| Disk full | Old images or logs | `df -h /` on the server. `sudo docker image prune -f` removes unused images (`update.sh` does this too). Or deploy with a larger `VOLUME_SIZE` (up to 30; this replaces the server) |
| Image pull denied | The GHCR package is still private, or `IMAGE_URI` has the wrong owner | Make the package public (step 1c), or store `GHCR_USER` and `GHCR_TOKEN`. Check that `IMAGE_URI` matches the package page. Then `scripts/update.sh` |
| "missing SSM parameters" | A required secret was never stored, or is under another prefix or region | Run step 3 and step 4 in the same region as the stack. Check with the `get-parameters-by-path` command from step 3 |
| "values must not contain quotes or newlines" | A secret has a `'` or a line break | Store a clean value with `scripts/put-secrets.sh --only <NAME>`, then `scripts/update.sh` |
| Session Manager session cannot start | Plugin not installed, wrong region or profile, the server is still booting, or the server cannot reach AWS | Check `session-manager-plugin` and the two `export` lines. Wait 2 to 3 minutes after creation. In the console, Systems Manager > Fleet Manager should list the server |
| Qdrant unreachable, or `/healthz` shows `"qdrant":"embedded"` | Qdrant secrets missing or wrong, or the cluster is paused | Check `QDRANT_CLUSTER_ENDPOINT` and `QDRANT_API_KEY` in Parameter Store, then `scripts/update.sh`. Check the cluster in the Qdrant Cloud console. Free clusters may be paused after a period without use |
| Tutor gives no sources | Documents were never ingested into the cluster, or the collection prefix differs | Run step 2. Make `QDRANT_COLLECTION_NAME` the same on your computer and on the server |
| OpenAI errors (authentication, quota, unknown model) | Wrong key, no credit on the OpenAI account, or a model id your account cannot use | `sudo docker compose logs api`. Fix the key or model ids with `scripts/put-secrets.sh --only <NAME>`, then `scripts/update.sh` |
| High AWS bill | A forgotten stack, a stopped server (disk and IP still bill), an unattached Elastic IP, or a deploy in a second region | Billing console > Bills, by service and region. Delete what you do not need (step 11) |
| High OpenAI bill | Many turns, a heavy reasoning model, or the password was shared | OpenAI Usage page. Change the password (step 4 and step 10). Pick cheaper model ids. Lower the OpenAI limit |

---

## What was tested and what was not

> **Nothing in this guide was deployed or run by its author.** No AWS call, no Docker command
> and no image build was made while writing it. The development computer had no Docker, and
> deploying was out of scope.
>
> **Checked offline only:**
>
> - `template.yaml` passes `cfn-lint` (the CloudFormation checker) with no findings.
> - All scripts in `deploy/aws/scripts/` pass `shellcheck`, and `--help` runs without touching
>   AWS. The start-up script inside the template and its helpers were shellchecked too.
> - Unit tests (`tests/unit/test_aws_deploy_files.py`, `tests/unit/test_deploy_files.py`) check
>   the template's structure, that UserData stays under the 16 KB limit, that the copies of the
>   Compose file and the Caddyfile inside the template match the real files, and the Dockerfile.
> - The GitHub workflow was written, not run.
>
> **Watch these on your first deploy:**
>
> - The Compose plugin download from GitHub on Amazon Linux 2023, and its pinned checksum.
> - `dnf install -y docker` on Amazon Linux 2023, and the Amazon Linux image lookup.
> - Caddy: basic auth with the hash from the environment, WebSockets for Streamlit, HTTP/1 and
>   HTTP/2 only.
> - Let's Encrypt certificates for an `sslip.io` name, and how its rate limits apply.
> - The Elastic IP attaching in time (the start-up script waits up to 5 minutes; Caddy retries).
> - GHCR: the package being private after the first build, and the image owner name.
> - Memory on `t3.micro` (1 GiB plus 2 GiB swap) for the API and the UI.
> - Compose keeping the `$` signs in the bcrypt hash literally.
> - How free-plan credits show up in AWS Budgets, and whether the plan covers the public IP.
> - Containers coming back by themselves after a stop and start.

---

## Glossary

> - **EC2** (Elastic Compute Cloud): AWS's virtual servers. One server is an **instance**.
> - **Instance type**: the size of a server. `t3.small` has 2 vCPUs and 2 GiB memory; `t3.micro`
>   has 2 vCPUs and 1 GiB.
> - **EBS** (Elastic Block Store): the server's disk. **gp3** is a general-purpose disk type.
> - **AMI** (Amazon Machine Image): the operating system the server starts from. Here, Amazon
>   Linux 2023.
> - **Region**: a group of AWS data centres in one area, for example `us-east-1`.
> - **VPC** (Virtual Private Cloud): your private network inside AWS.
> - **Subnet**: a part of a VPC in one data centre. A **public** subnet can reach the internet.
> - **Security group**: a firewall around a server. It says which ports are open, to whom.
> - **IAM** (Identity and Access Management): who may do what in your AWS account.
> - **IAM role**: a set of permissions that a machine (not a person) can use.
> - **Instance profile**: the thing that attaches an IAM role to a server.
> - **Elastic IP**: a fixed public IP address you keep until you release it.
> - **IMDSv2**: the safer version of the service that tells a server about itself, including its
>   temporary credentials.
> - **SSM** (Systems Manager): AWS's tools for managing servers. **Session Manager** gives you a
>   terminal on a server without SSH. **Run Command** runs a command on it (`update.sh` and
>   `status.sh` use it).
> - **Parameter Store**: part of SSM that stores small values. A **SecureString** is stored
>   encrypted.
> - **CloudFormation**: AWS reads a template file and creates everything in it. The things it
>   created together are a **stack**. Deleting the stack deletes them.
> - **UserData**: a script a server runs on its first boot.
> - **GHCR** (GitHub Container Registry): GitHub's storage for Docker images, at `ghcr.io`.
> - **Image** and **container**: an image is a packed app; a container is a running copy of it.
> - **Docker Compose**: starts several containers together from one file.
> - **Caddy**: a small web server that gets HTTPS certificates by itself.
> - **Reverse proxy**: a server that receives visitors' requests and passes them on to another
>   program (here, Caddy passes them to Streamlit).
> - **TLS**: the encryption behind HTTPS. A **certificate** proves the site is who it says it is.
> - **Let's Encrypt**: a free certificate authority that Caddy uses.
> - **sslip.io**: a free service that turns names like `3-120-45-67.sslip.io` into the IP
>   address inside them.
> - **Basic auth**: the browser's built-in user name and password box.
> - **bcrypt hash**: a one-way scrambled form of a password.
> - **Swap**: disk space the server uses as slow extra memory.
