# 0007. Sandbox backends behind our interface, not the deepagents harness

Status: accepted. Date: 2026-10-30.

## Context
The local sandbox ([ADR 0006](0006-python-sandbox-allowlist.md)) is not a security boundary.
Stronger isolation is available from deepagents sandbox providers, which run commands in a remote
environment through an `execute` tool.

## Decision
Add a small `SandboxBackend` interface and select an implementation by setting. A provider can be
adapted behind it later. Do not adopt the deepagents agent harness.

## Reasons
- The harness lets the model choose commands to execute. Here rules choose the tool and the
  learner approves each run, so model-chosen commands would undo that design.
- Its planning and subagent features are not needed by the tutor graph.
- A backend behind our interface keeps the allowlist check, approval, and result contract unchanged.

## Consequences
Default behavior is unchanged and no dependency is added. No provider adapter exists yet, so
stronger isolation still needs outer containment or a future adapter.
