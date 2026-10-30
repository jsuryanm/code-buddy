# 0005. Tools over MCP, rule-planned, with learner approval for execution

Status: accepted. Date: 2026-10-30.

## Context
The spec asks for MCP support, tool calling, and human in the loop. The tutor's core promise is
that the policy, not the model, controls what the learner sees, and running a stranger's code is
the one risky action.

## Decision
- Tools live in one module and are served over MCP (stdio) and callable in-process.
- Rules choose tools (`_plan_tools`), not the model. Tool output reaches the model as private notes.
- Tools carry a risk class. `execute` tools pause the graph with LangGraph `interrupt()` until the
  learner approves, once or for the session. Each turn gets its own checkpoint thread.
- Approvals are bound to the session that owns the paused turn, are single-use, and expire.

## Consequences
The model cannot call tools on its own, so it cannot be talked into running code. The cost is
less flexibility than a free tool-calling agent. A paused turn needs a durable checkpoint store
(SQLite now). The first debug turn in a session needs an extra round trip for the permission.
