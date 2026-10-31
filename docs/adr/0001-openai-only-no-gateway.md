# 0001. OpenAI only, no LLM gateway

Status: accepted. Date: 2026-10-29.

## Context
The spec first proposed an LLM gateway (LiteLLM) for key management, fallback routing, and
small-versus-heavy task routing across providers.

## Decision
Use OpenAI as the only provider through `langchain-openai`. No gateway service.

- Task routing: three tiers (fast, standard, heavy) with model IDs from environment variables.
- Fallback: `generate` chains heavy to standard to fast on an error or an empty reply, then a
  degraded reply. (Originally `.with_fallbacks()`, replaced because an empty reply is not an
  exception, so it never triggered the fallback.)
- Keys: secret manager or `.env`; one OpenAI project per environment with a budget set in OpenAI.
- Per-user budgets, if needed, are Redis counters in the app.

## Consequences
One vendor, SDK, and bill, and no extra hop in the latency path. A full OpenAI outage is survived
only by the degraded mode (course material, no generation). Adding a second provider later means
changing `llm.py`, because chat models share LangChain's interface. A gateway can still be added
if multi-provider routing becomes necessary.
