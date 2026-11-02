# Run it on your computer

This page takes you from nothing to a working tutor in two stages:

1. **The keyless demo.** No accounts, no keys, no cost. Scripted replies, but everything
   else is real. About 5 minutes.
2. **Real mode.** Real OpenAI models and your own documents. Needs an OpenAI account and
   costs a little money per question.

The reference page with every detail is [../setup.md](../setup.md).

## 1. What you need first

| Thing | Why | How to check |
|---|---|---|
| A terminal | You type commands into it | On Windows, use WSL (Windows Subsystem for Linux); the author develops on WSL |
| Git | To download the project | `git --version` prints a version |
| [uv](https://docs.astral.sh/uv/) | Installs Python 3.12 and every library for you | `uv --version` prints a version |
| A web browser | To use the tutor | |
| Internet on the first run | uv downloads libraries; the search engine downloads a small word-search model (`Qdrant/bm25`) once | |

You do **not** need to install Python yourself. The file `.python-version` says 3.12, and uv
fetches that version if you do not have it. Install uv by following its
[installation page](https://docs.astral.sh/uv/getting-started/installation/).

A **terminal** is a window where you type commands. In this guide a command is shown in a
grey box. Copy it, paste it into the terminal, and press Enter. Replace anything in
`<ANGLE_BRACKETS>` with your own value, without the brackets.

## 2. Install

### Step 1: get the code

```bash
git clone <REPOSITORY_URL> code-buddy
cd code-buddy
```

What you should see: a folder `code-buddy` with `README.md`, `src/` and `docs/` inside.

### Step 2: install the libraries

```bash
uv sync --extra ui
```

`uv sync` reads `pyproject.toml` (the project's list of libraries) and `uv.lock` (the exact
versions) and installs them into a private folder `.venv`. `--extra ui` adds the Streamlit
web page. Other extras, added the same way, are:

| Extra | Adds | When you need it |
|---|---|---|
| `ui` | Streamlit | Always, for the web page |
| `pdf` | Docling, to read PDFs | Only to ingest PDF files. Large: it pulls in PyTorch |
| `rerank` | sentence-transformers | Only for the optional cross-encoder reranker |
| `trace` | Langfuse | Only for tracing ([04](04-logs-tracing-and-evaluation.md#2-langfuse-tracing-a-timeline-of-each-turn)) |

What you should see: a list of installed packages and no error. The first run takes a few
minutes.

### Step 3: check the install (optional)

```bash
uv run pytest -q
uv run python -m codebuddy.eval.run
```

`uv run` runs a command inside the project's `.venv`. The first line runs the automatic
tests, offline. The second runs the offline evaluation.

What you should see: the tests end with a line like `N passed`, and the evaluation prints a
table of metrics and `PASS`.

## 3. Try the keyless demo

The demo server uses **scripted** replies instead of a real AI model, and a small sample
textbook (`data/sample/python_basics.md`) instead of Think Python. Everything around the
replies is real: the policy, the hint ladder, the leak guard, the permission prompt, and the
sandbox, which really runs your code. You need two terminals open in the `code-buddy`
folder.

### Step 1: start the API (terminal 1)

```bash
uv run uvicorn codebuddy.api.demo:app --port 8000
```

[Uvicorn](06-glossary.md#uvicorn) is the program that runs the API server. `--port 8000`
means it listens at `http://localhost:8000`. `localhost` means "this computer".

What you should see: a first line like

```text
starting the keyless demo API (app=demo version=0.1.0 ...) log=logs/<DATE>/demo_<TIME>.log
```

and then `Uvicorn running on http://127.0.0.1:8000`. Leave this terminal open.

### Step 2: start the UI (terminal 2)

```bash
uv run streamlit run src/codebuddy/ui/app.py
```

What you should see: `Local URL: http://localhost:8501`. Streamlit may open the browser for
you.

### Step 3: ask a question

1. Open http://localhost:8501.
2. Check the bottom of the sidebar says **Connected**. If it says "Can't reach the tutor",
   terminal 1 is not running.
3. Click **Your code** above the message box to open it, and paste:

   ```python
   nums = [1, 2, 3]
   total = 0
   for i in range(len(nums) + 1):
       total += nums[i]
   print(total)
   ```

4. Type `my sum crashes with an IndexError` in the message box and press Enter.

What you should see:

- A status box listing steps such as "Reading your code" and "Choosing how to help".
- A message from the tutor showing your code with **Run my code** and **Don't run it**.
  Click **Run my code**. The sandbox really runs it.
- A short reply that ends in a question, with the caption "Hint 1: think it through" and a
  collapsed **References** section that cites "Sample Python Basics".

### Step 4: climb the ladder

Send a follow-up question, such as `which line?`, without changing the code. The caption
goes "Hint 2: look here", then "Hint 3: the concept".

On that third send, **Show answer** already appears, highlighted, even though only 2 hints
came before. Why: you sent the same code a third time in a row, which the tutor counts as a
sign of being stuck, so it offers the answer early. If you change the code a little each
time instead, Show answer appears after the 4th hint. Click it to see the fixed code.

You can also type `show me the answer` at any time, even on the first turn.

### Step 5: fix the bug and try the quiz

1. Click **New chat** in the sidebar. (After a reveal the tutor forgets the old bug on
   purpose, so pasting the revealed answer is not praised as your own fix.)
2. Paste the buggy code again and send `my sum crashes`. Answer the permission prompt.
3. In **Your code**, change `range(len(nums) + 1)` to `range(len(nums))` and send
   `I changed the loop`.

What you should see: the caption "You fixed it", a reply asking why your change works, and
a **Try a quiz** button. Click it: a buggy snippet lands in the code box, and the caption
reads "Quiz 1 of 5 (easy)".

To stop, press `Ctrl+C` in each terminal.

## 4. Real mode: the `.env` file

Real mode needs secret keys. They live in a file called `.env` in the project folder. The
API, the ingestion command and the RAGAS runner read it when they start, so you never type
`export`.

> **Warning:** `.env` holds secrets. It is listed in `.gitignore`, so git never uploads it.
> Never paste its contents into a chat, an issue or a screenshot.

### Step 1: create `.env` from the template

The template is `.env.example`. It lists every variable with a comment.

```bash
cp .env.example .env
```

Then open `.env` in a text editor and fill in the values below.

### Step 2: the variables you must set

| Variable | What it is, in plain words |
|---|---|
| `OPENAI_API_KEY` | Your password for OpenAI's API. Create one on the OpenAI platform website. Every model call and every embedding is billed to it |
| `CODEBUDDY_MODEL_FAST` | The OpenAI model ID for the **fast** tier: a small, quick, cheap model. Classifies questions and writes redirects |
| `CODEBUDDY_MODEL_STANDARD` | The model ID for the **standard** tier: a mid-size model. Writes hints and explanations |
| `CODEBUDDY_MODEL_HEAVY` | The model ID for the **heavy** tier: the most capable model. Writes full answers |

The three model IDs have **no defaults on purpose**: model names change, and the project
never hard-codes them. Look up current IDs in OpenAI's model list. You may use the same ID
for two tiers. If one of them is empty, the API refuses to start with
`RuntimeError: Set model IDs in the environment`.

What the tiers mean in practice: most turns use the standard model, so its speed decides how
fast replies feel. The heavy model only runs when a learner asks for the full answer. If a
tier fails, the next lighter one takes over (see
[01, models and tiers](01-how-the-tutor-works.md#models-tiers-and-fallbacks)).

### Step 3: optional variables

| Variable | What it does | Leave it empty and... |
|---|---|---|
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | Address and password of an Upstash Redis database, a hosted cache. Set both | The cache lives inside the API process and is lost on restart, including every session |
| `GROQ_API_KEY` | Your Groq key, for voice input (Groq runs the Whisper speech-to-text model) | No microphone in the chat box |
| `CODEBUDDY_API_KEYS` | Comma-separated passwords the API demands from callers | Anyone who can reach the API can use it |
| `CODEBUDDY_API_KEY` | The one password the UI sends, matching one of the keys above | The UI sends no key |
| `CODEBUDDY_API_URL` | Where the UI finds the API | `http://localhost:8000` |
| `CODEBUDDY_RATE_LIMIT_PER_MINUTE` | Turns allowed per caller per minute | `30`; `0` turns the limit off |
| `CODEBUDDY_MEMORY_ENABLED`, `CODEBUDDY_MEMORY_SECRET` | Long-term learner memory, and the secret that signs learner tokens | Memory is off |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | Tracing to Langfuse ([04](04-logs-tracing-and-evaluation.md#2-langfuse-tracing-a-timeline-of-each-turn)) | No tracing |
| `CODEBUDDY_LOG_LEVEL` | How much the logs say: `INFO` or `DEBUG` | `INFO` |

`CODEBUDDY_API_KEY` and `CODEBUDDY_API_URL` are read by the UI from the environment. They
have no field on the page.

Every other setting, with its default, is in [../configuration.md](../configuration.md). Any
setting `X` in that page's tables is set as `CODEBUDDY_X` in `.env`.

Not tested live: OpenAI chat replies, Groq and Upstash were never run against the real
services by the author's tooling.

## 5. Start the real API and UI

You need a knowledge base first, or replies will cite nothing. Do
[section 6](#6-add-documents-ingestion) before your first real run, then come back.

Terminal 1:

```bash
uv run uvicorn codebuddy.api.app:app --port 8000
```

Terminal 2:

```bash
uv run streamlit run src/codebuddy/ui/app.py
```

Check the API is healthy in a third terminal:

```bash
curl localhost:8000/healthz
```

What you should see: a line of JSON such as

```text
{"status":"ok","cache":"memory","models_configured":true,"stt_configured":false,
 "tools":"mcp","sandbox_network_isolated":...,"qdrant":"embedded","memory_enabled":false,
 "auth_required":false,"tracing_enabled":false}
```

`"cache":"memory"` means Upstash is not set. `"tools":"mcp"` means the tool server started
(see [section 9](#9-the-mcp-tool-server)).

## 6. Add documents (ingestion)

**Ingestion** means reading documents, cutting them into chunks, turning each chunk into an
[embedding](06-glossary.md#embedding), and storing them in the knowledge base. It calls
OpenAI's embedding model, so `OPENAI_API_KEY` must be set.

> **Warning:** stop the API first. The default knowledge base is a folder on disk
> (`data/index/`) that only one program may open at a time.

### Step 1: put files in `data/raw/`

Supported: `.md`, `.markdown`, `.txt`, `.html`, `.htm`, and `.pdf`. The folder `data/raw/`
is ignored by git. Check the licence of every document first: Think Python is CC BY-NC 3.0
(non-commercial), and the PCDIT paper needs its authors' permission for learner-facing use.
See [../corpus-manifest.md](../corpus-manifest.md).

### Step 2: ingest a Markdown or text file

Markdown, text and HTML work without extras:

```bash
uv run python -m codebuddy.rag.ingest data/raw/<FILE>.md --corpus fundamentals \
    --title "<TITLE>" --licence "<LICENCE>"
```

A folder works too: every supported file below it is ingested.

### Step 3: ingest a PDF

PDFs need the `pdf` extra:

```bash
uv sync --extra ui --extra pdf
CUDA_VISIBLE_DEVICES= uv run python -m codebuddy.rag.ingest data/raw/<FILE>.pdf \
    --corpus fundamentals --title "<BOOK TITLE>" --licence "<LICENCE>"
```

The empty `CUDA_VISIBLE_DEVICES=` at the start hides any graphics card from the PDF reader.
On WSL, Docling's PyTorch crashes (a segfault) while looking for a GPU; this avoids it. On
a CPU the 240-page Think Python took several minutes.

The options:

| Option | Meaning | Default |
|---|---|---|
| `--corpus` | Which collection: `fundamentals` (learners see it) or `pedagogy` (learners never see it) | `fundamentals` |
| `--title` | Name shown in citations | the file name |
| `--licence` | Recorded with every chunk | `unverified` |
| `--force` | Ingest again on purpose even if the file has not changed (each target, local or cluster, keeps its own record) | off |

What you should see: log lines, then one line per file such as `data/raw/<FILE>.pdf: 338
chunks` (or `unchanged, skipped` when nothing changed), then a finish line. The list
of what was ingested is in `data/index/manifest.json`. With the author's two PDFs the index
holds 338 `fundamentals` chunks and 29 `pedagogy` chunks.

Running it again is safe: unchanged files are skipped, changed files replace their own
chunks.

## 7. Where the knowledge base lives

[Qdrant](06-glossary.md#qdrant) is the search database. It can run in three ways:

| Mode | What it is | How to choose it |
|---|---|---|
| Embedded (default) | Files in `data/index/`, opened by the program itself. No server. One program at a time | Set nothing |
| Server | A Qdrant server you run | `CODEBUDDY_QDRANT_URL=http://localhost:6333` |
| Qdrant Cloud | A server hosted by Qdrant | The three variables below |

For Qdrant Cloud, add to `.env`:

```dotenv
QDRANT_CLUSTER_ENDPOINT=https://<CLUSTER_ID>.<REGION>.cloud.qdrant.io:6333
QDRANT_API_KEY=<YOUR_QDRANT_KEY>
QDRANT_COLLECTION_NAME=cb
```

- `QDRANT_CLUSTER_ENDPOINT` is the address of your cluster, from the Qdrant Cloud console.
- `QDRANT_API_KEY` is its password. It is never written to logs or `/healthz`.
- `QDRANT_COLLECTION_NAME` is a **prefix**, not a full name. Collections are called
  `<PREFIX>_<CORPUS>_<INDEX_VERSION>`, for example `cb_fundamentals_v1`. Default `cb`.

Then run the ingestion command again: it now writes to the cloud. `/healthz` then shows
`"qdrant":"server"`, and the API's start log has `qdrant=server host=<HOST>`. Learner memory
always stays in local files (`data/memory/`), whichever mode you pick.

Not tested live: Qdrant server mode and Qdrant Cloud.

## 8. A tour of the UI

| Part | What it does |
|---|---|
| **Sidebar** | **New chat** starts a fresh problem. Earlier chats of this browser tab are listed below it; click one to switch. At the bottom: "Connected" or "Can't reach the tutor", and **Settings** |
| **Stage line** | Problem, Cases, Design, Implement, Test, with your current [PCDIT](06-glossary.md#pcdit) stage highlighted |
| **Step status** | While the tutor works, a box lists the steps. When the reply starts it folds into a summary such as "Worked for 1.4 s · 4 steps"; click it to see each step |
| **Caption** | Under each reply: "Hint 1: think it through" up to "Hint 4: a plan", "Explanation", "Full answer", "You fixed it", or "Quiz 2 of 5 (medium)". "instant" means it came from the cache |
| **References** | A collapsed list under each reply: the book title and the sections used, such as `[1] 2.10 Debugging` |
| **Show answer** | Under the latest reply after the 4th hint, or sooner on frustration or after 10 minutes. Highlighted when the tutor offers the answer |
| **Try a quiz** | Appears after you fix a bug. **Skip question** and **Stop quiz** appear during a quiz |
| **Run my code** | The permission prompt. **Run my code** or **Don't run it**, and "remember my choice for this chat" |
| **Your code** | A collapsed box above the message box. Each chat keeps its own code |
| **Voice** | A microphone in the message box when the server has `GROQ_API_KEY`. What it heard appears in an editable "Heard" box with **Send** and **Discard**, so you can fix it before sending |
| **Settings, memory** | Only when the server has memory on: **Remember me across sessions**, **Show what I remember**, **Forget me** |

Chats live as long as the browser tab. Closing the tab loses the list.

The microphone needs your browser's permission to use it. Browsers allow microphones on
`localhost`; on another address they usually require HTTPS.

## 9. The MCP tool server

The tools (static analysis, concrete-case suggestions, and code tracing) are served by a
small separate program that speaks [MCP](06-glossary.md#mcp), a standard way for AI apps to
call tools.

**You do not start it.** With `CODEBUDDY_MCP_ENABLED=true` (the default), the API starts it
by itself as a child process. `/healthz` then shows `"tools":"mcp"`.

You can run it by hand, but only to check that it starts:

```bash
uv run python -m codebuddy.mcp_server
```

What you should see: a start line on the screen, then nothing. It is waiting for an MCP client to
talk to it. Press `Ctrl+C` to stop it.

If the API cannot start it, the API log says "calling tools in-process", and the tools run
inside the API instead. Everything still works. To turn tools off completely (so learner
code is never run), set `CODEBUDDY_TOOLS_ENABLED=false`.

## 10. Turn on long-term memory (optional)

1. Make a secret:

   ```bash
   uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. Add to `.env`:

   ```dotenv
   CODEBUDDY_MEMORY_ENABLED=true
   CODEBUDDY_MEMORY_SECRET=<THE_SECRET_YOU_JUST_MADE>
   ```

3. Restart the API and check `curl localhost:8000/healthz` shows `"memory_enabled":true`.

Without the secret, learner tokens stop working after every restart. Memory calls OpenAI and
stores personal data in `data/memory/`. Read [../memory.md](../memory.md) first. Not tested
live.

Next: [04-logs-tracing-and-evaluation.md](04-logs-tracing-and-evaluation.md).
