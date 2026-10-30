---
paths:
  - "pyproject.toml"
  - "requirements*.txt"
---

# LangChain package policy

Source: PROJECT_SPEC.md Section 15.2.

- Core: `langchain` (v1), `langgraph`, `langchain-openai`, `langchain-qdrant`, `langchain[mcp]` (provides `langchain.mcp`, `MCPAdapter`; beta, bounded to `>=1.4,<1.5` with `mcp>=2.3,<3`).
- `langchain-community`: document loaders and integrations not in a provider package. Pin it.
- `langchain-classic`: do not add without an ADR in `docs/adr/`. It holds legacy chains, retrievers such as `ContextualCompressionRetriever`, the indexing API, hub, and `CacheBackedEmbeddings`. Reranking is a plain function, so none of it is needed.
- Before pinning, verify whether the Upstash cache and chat-history integrations live in `langchain-community` or a separate package.
- Verify package and class names against current docs (Context7) before coding. Pin every LangChain package in the lockfile. Upgrades go through the eval gate.
- OpenAI model IDs come from config, never hard-coded. The spec lists placeholders only.
