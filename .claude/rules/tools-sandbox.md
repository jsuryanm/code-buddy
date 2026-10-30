---
paths:
  - "src/codebuddy/sandbox/**"
  - "src/codebuddy/tools/**"
  - "src/codebuddy/mcp_server/**"
---

# Tools, sandbox, and approvals

Details: `docs/tools-and-approvals.md` and `docs/security.md`.

- A tool needs an entry in `tools/policy.TOOL_RISK`. Only `read` tools may run without the learner's permission. `execute` tools pause the graph (`approve_run`); `write_shared` never auto-runs.
- Tools are planned by `TutorNodes._plan_tools()` from the intent and mode. Do not let the model pick tools.
- Tool output reaches the model only as private notes; the leak guard still checks the reply.
- Sandbox changes need a test in `tests/unit/test_sandbox.py` for each new allowed capability and for the refusal of its dangerous neighbors. Keep the allowlist small (beginner fundamentals only).
- Never relax the sandbox to make a learner's code run; tell the learner what is not supported instead.
- New tools go in `tools/functions.py` and `TOOLS`, in `mcp_server/server.py`, and get a test through the real MCP stdio server (see `tests/unit/test_tools.py`).
