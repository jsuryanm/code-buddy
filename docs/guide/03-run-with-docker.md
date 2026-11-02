# Run CodeBuddy locally with Docker

This page shows how to run CodeBuddy on your own computer with Docker, step by step. You do not
need Docker to use CodeBuddy: the normal way is `uv` (see [setup.md](../setup.md)). Docker is
useful when you want to run it the same way a server does, or try the image before you deploy it
to AWS ([aws-free-tier.md](../aws-free-tier.md)).

> **Not tested yet.** The Docker files were written and checked offline only. Nobody has built
> the image or run these commands yet, because the development computer had no Docker. Expect
> small problems on your first run. The box [What was not tested](#what-was-not-tested) lists
> them.

## Contents

1. [What Docker and Compose are](#what-docker-and-compose-are)
2. [Install Docker (Windows with WSL)](#install-docker-windows-with-wsl)
3. [The services](#the-services)
4. [Three ways to run it](#three-ways-to-run-it)
5. [First run, step by step](#first-run-step-by-step)
6. [Add your documents (ingestion)](#add-your-documents-ingestion)
7. [Where logs and data live](#where-logs-and-data-live)
8. [Stop, restart, reset](#stop-restart-reset)
9. [Common errors](#common-errors)
10. [What was not tested](#what-was-not-tested)

Words in `<ANGLE_BRACKETS>` are placeholders: replace them, brackets included, with your own
value. Run every command from the repository root (the folder that contains
`docker-compose.yml`).

| Placeholder | What to put there | Example |
|---|---|---|
| `<FILE>` | A document to ingest, inside `data/raw` | `data/raw/notes.md` |
| `<TITLE>` | The name the tutor cites | `"My notes"` |
| `<SERVICE>` | One service name from the table below | `api` |

---

## What Docker and Compose are

**Docker** packs an app and everything it needs (Python, libraries, settings) into one bundle
called an **image**. A running copy of an image is a **container**; it behaves the same on any
computer. **Docker Compose** starts several containers together, as described in one file, here
[`docker-compose.yml`](../../docker-compose.yml).

The image is described by the [`Dockerfile`](../../Dockerfile). One image holds the API, the
Streamlit UI and the ingestion tool. The [`.dockerignore`](../../.dockerignore) file keeps your
`.env`, logs, data, tests and docs out of the image.

## Install Docker (Windows with WSL)

If you work in WSL (Linux inside Windows), the easiest way is Docker Desktop for Windows:

1. Install Docker Desktop from <https://www.docker.com/products/docker-desktop/> and start it.
2. In Docker Desktop, open **Settings > Resources > WSL integration**.
3. Turn on the switch for your Linux distribution (for example Ubuntu), then **Apply & restart**.
4. Close and reopen your WSL terminal.

Check that it worked:

```bash
docker version
```

What you should see: two sections, **Client** and **Server**. If only Client appears, or you see
"Cannot connect to the Docker daemon", Docker Desktop is not running or the WSL integration is
off for your distribution.

Then check Compose:

```bash
docker compose version
```

What you should see: `Docker Compose version v2.24.0` or newer. Older versions do not understand
the optional `.env` setting in `docker-compose.yml`.

On Linux without Windows, install Docker Engine and the Compose plugin from Docker's
documentation instead.

## The services

A **service** is one container in the Compose file. CodeBuddy's Compose file has five:

| Service | Starts with | What it does | Address on your computer |
|---|---|---|---|
| `qdrant` | `docker compose up` | The local vector database that stores your documents for search. Its data is kept in the volume `qdrant-data` | not published |
| `api` | `docker compose up` | The tutor itself. Waits until `qdrant` is healthy | <http://localhost:8000> |
| `ui` | `docker compose up` | The Streamlit tutor page. Talks to the API at `http://api:8000` | <http://localhost:8501> |
| `api-demo` | named on the command line | A keyless demo API with scripted replies. No OpenAI, no Qdrant. Takes the name `api` so the UI finds it | <http://localhost:8000> |
| `ingest` | `--profile ingest run` | Loads documents into the index, then exits | none |

A **volume** is a storage area that Docker keeps between runs. A **profile** marks a service that
only starts when you ask for it.

Ports are bound to `127.0.0.1`, so only your own computer can open them. Each service has a
memory limit (`mem_limit`): 1 GiB for `qdrant`, 2 GiB for `api` and `ingest`, 512 MiB for `ui`,
1 GiB for `api-demo`.

## Three ways to run it

| Way | Needs keys? | Command | Good for |
|---|---|---|---|
| A. Keyless demo | No | `docker compose up --build api-demo ui` | Seeing the UI work |
| B. Local, with local Qdrant | OpenAI key and model ids | `docker compose up --build -d` | Real tutoring, all on your computer |
| C. Local, with Qdrant Cloud | OpenAI key, model ids, Qdrant Cloud | `docker compose up --build -d --no-deps api ui` | Same index as the AWS server |

### A. Keyless demo

```bash
docker compose up --build api-demo ui
```

This runs in the foreground: the logs of both containers scroll in your terminal. Open
<http://localhost:8501>. The replies are scripted, but the hint ladder, the leak guard and the
permission prompt before your code runs are real. Press Ctrl+C to stop.

Do not start the demo together with `api`: both want port 8000.

### B. Local, with the local Qdrant

This is the normal setup. Follow [First run](#first-run-step-by-step) below.

### C. Local, with Qdrant Cloud

Put your cluster in `.env`:

```dotenv
QDRANT_CLUSTER_ENDPOINT=<your cluster URL>
QDRANT_API_KEY=<your cluster API key>
QDRANT_COLLECTION_NAME=cb          # optional, the collection prefix; cb is the default
```

Then start only the API and the UI (`--no-deps` skips the local `qdrant`):

```bash
docker compose up --build -d --no-deps api ui
```

Compose passes `QDRANT_CLUSTER_ENDPOINT` to the API as `CODEBUDDY_QDRANT_URL`. Without it, the
API uses the local `qdrant` service.

---

## First run, step by step

### Step 1: Create your `.env`

`.env` holds your keys. It is never put into the image and never committed to Git. Copy the
settings template:

```bash
cp .env.example .env
```

If your copy of the repository has the template as `env.example` instead, copy that one. Then
open `.env` in an editor and fill in at least:

```dotenv
OPENAI_API_KEY=sk-...
CODEBUDDY_MODEL_FAST=<model id>
CODEBUDDY_MODEL_STANDARD=<model id>
CODEBUDDY_MODEL_HEAVY=<model id>
```

Every setting is explained in [configuration.md](../configuration.md).

If it fails: without `.env`, the containers still start (the file is optional), but the API has
no model keys and gives degraded answers. Only the demo (way A) works without it.

### Step 2: Make the logs folder writable

The app inside the container runs as a normal user (user id 10001), not as you. It writes its
log files into the `logs` folder of the repository. Let it write there:

```bash
mkdir -p logs && chmod a+rwx logs
```

If you skip this, the app still runs, but writes no log files (it logs one warning and uses the
terminal instead).

### Step 3: Build and start

```bash
docker compose up --build -d
```

`--build` builds the image from the `Dockerfile` first. `-d` runs the containers in the
background.

What you should see: the first build takes several minutes (it downloads Python packages and a
small search model). Then Compose prints one line per container as it is created, started, and,
for `qdrant`, healthy. You get your prompt back when all are started.

Check the containers:

```bash
docker compose ps
```

What you should see: `qdrant`, `api` and `ui`, each with a status that says `Up`, and
`(healthy)` once the health checks pass (this can take up to a minute).

### Step 4: Check the API

```bash
curl localhost:8000/healthz
```

What you should see: one line of JSON that starts with `{"status":"ok"`. Look for
`"models_configured":true` (your model ids are set) and `"qdrant":"server"` (it uses a Qdrant
server: the local one, or your cluster in way C).

### Step 5: Open the tutor

Open <http://localhost:8501>. Paste some buggy Python and ask a question.

The local index starts empty, so the tutor has no documents to cite until you ingest some (next
section).

If anything fails: see [Common errors](#common-errors), and read the logs:

```bash
docker compose logs --tail 100 api
```

---

## Add your documents (ingestion)

**Ingestion** loads documents into the search index so the tutor can cite them. The `ingest`
service runs once and exits. Put your files in `data/raw` in the repository; Compose shows that
folder to the container read-only.

```bash
docker compose --profile ingest run --rm ingest <FILE> --corpus fundamentals --title <TITLE>
```

For example, with a sample file that is already inside the image:

```bash
docker compose --profile ingest run --rm ingest data/sample/python_basics.md \
  --corpus fundamentals --title "Python basics"
```

The arguments after `ingest` are those of `python -m codebuddy.rag.ingest` (see
[rag-and-ingestion.md](../rag-and-ingestion.md)). `--rm` removes the finished container. Ingestion
needs `OPENAI_API_KEY` in `.env`, because it uses OpenAI to make embeddings (a small cost).

What you should see: log lines naming the target (`server host=...`) and the collection, then one
line per file with its number of chunks.

**For Qdrant Cloud (way C)**, add `--no-deps` so the local `qdrant` is not started:

```bash
docker compose --profile ingest run --rm --no-deps ingest <FILE> --corpus fundamentals
```

Each target keeps its own record of ingested files (in `/app/data/index/manifest.json` in the
`app-data` volume): the local Qdrant and each cluster or collection prefix are tracked
separately, so ingesting the same file into the cloud after the local one works without any
extra flag. `--force` is only for re-ingesting a file on purpose when it has not changed.

**PDF files** need an extra part (Docling, which pulls in PyTorch, several GB). Build it into the
image first, ingest, then rebuild without it for everyday use:

```bash
docker compose build --build-arg EXTRAS="--extra ui --extra trace --extra pdf" ingest
docker compose --profile ingest run --rm -e CUDA_VISIBLE_DEVICES= ingest data/raw/thinkpython.pdf \
  --corpus fundamentals --title "Think Python"
docker compose build ingest
```

`-e CUDA_VISIBLE_DEVICES=` avoids a crash of the PDF converter on WSL when it looks for a
graphics card. Markdown, text and HTML work without the extra.

---

## Where logs and data live

| What | Where | Kept after `down`? |
|---|---|---|
| App log files | `logs/YYYY-MM-DD/` in the repository, for example `api_HH-MM-SS.log` and `.errors.log` | Yes (a normal folder). Files older than 5 days are deleted at start |
| Container output | `docker compose logs <SERVICE>` | No, removed with the container |
| Your documents' index (local Qdrant) | Volume `qdrant-data` | Yes |
| Checkpoints and the ingestion record | Volume `app-data` (`/app/data` in the container) | Yes |
| Your keys | `.env` in the repository | Yes, never in the image |

The log files hold metadata only, never learner text, code or replies (see
[observability.md](../observability.md)).

To follow a container's output live:

```bash
docker compose logs -f api      # Ctrl+C stops following, not the container
```

---

## Stop, restart, reset

Stop the containers (your data and index stay in the volumes):

```bash
docker compose down
```

Start again later (add `--build` after you changed code):

```bash
docker compose up -d
```

If `docker compose ps` still lists `api-demo` after `down`, stop it with
`docker compose --profile demo down`.

> **Deletes data.** The next command deletes the volumes too: your local index, checkpoints and
> the ingestion record. You must ingest your documents again afterwards. Documents in Qdrant
> Cloud are not affected.

```bash
docker compose down -v
```

---

## Common errors

| Symptom | Likely cause | Fix |
|---|---|---|
| `docker: command not found` or "Cannot connect to the Docker daemon" (WSL) | Docker Desktop is not running, or WSL integration is off | Start Docker Desktop; turn on Settings > Resources > WSL integration for your distribution; reopen the terminal |
| "port is already allocated" for 8000 or 8501 | Something else uses the port: a local `uvicorn` or `streamlit`, or `api` and `api-demo` together | Stop the other program, or stop one of the two APIs |
| Compose complains about `env_file` or `required` | Compose older than 2.24 | Update Docker Desktop, then check `docker compose version` |
| `/healthz` shows `"models_configured":false`, or replies are degraded | No `.env`, or the model ids are missing | Create and fill `.env`, then `docker compose up -d` again |
| API waits forever, or "dependency failed to start" | `qdrant` is not healthy | `docker compose ps` and `docker compose logs qdrant` |
| Qdrant unreachable with Qdrant Cloud | Wrong endpoint or key in `.env` | Check `QDRANT_CLUSTER_ENDPOINT` and `QDRANT_API_KEY`; the `api` log names the host it tried |
| Tutor cites nothing | Nothing ingested yet, or the ingest went to another target | Run the ingestion step; check that its log names the same host as the API |
| Ingestion says the file was skipped | It was already ingested into this same target and has not changed | Nothing to do, or add `--force` to ingest it again on purpose |
| Container killed, exit code 137 | Out of memory | Give Docker Desktop more memory (Settings > Resources), or raise that service's `mem_limit` |
| No files in `logs/` | The container user cannot write there | `chmod a+rwx logs`, then restart |
| UI says "Can't reach the tutor" | The API container is down or still starting | `docker compose ps`, then `docker compose logs api` |
| Build fails | A package download failed, or a real build error | Read the first error in the build output; run the build again to rule out a network hiccup |

More help: [deployment.md](../deployment.md) (the reference version of this page) and the
troubleshooting section of [setup.md](../setup.md).

---

## What was not tested

> Nothing on this page has been run. The development computer had no Docker, so the image was
> never built. Only offline checks ran: the YAML files parse, and
> `tests/unit/test_deploy_files.py` checks the Dockerfile and the Compose file.
>
> Not tested, in particular:
>
> - building the image, including the `uv` cache mounts;
> - the step that downloads the BM25 search model into the image (it is allowed to fail; the
>   container then downloads it on first use);
> - the `qdrant` health check (it assumes the Qdrant image has `bash`);
> - the optional `.env` (`required: false`, needs Compose 2.24 or newer);
> - the demo taking the name `api` on the network;
> - the Streamlit health check;
> - write permissions on the `logs` folder for user 10001;
> - the whole flow with live OpenAI, Qdrant, Groq, Upstash or Langfuse.
