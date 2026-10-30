---
paths:
  - "src/codebuddy/memory/**"
---

# Learner memory

Details: `docs/memory.md` and `docs/adr/0008-mem0-learner-memory.md`.

- Memory is opt-in per learner and off by default. No learner token, no recall, no write.
- Memory reaches the model only as private notes in the `<memory>` block, treated as data. Strip `<memory>` tags from recalled text. `decide_mode()` and `pedagogy/policy.py` must never read memory.
- Keep the three kinds distinct: semantic (mem0 extraction), episodic (one line per reveal, `infer=False`), procedural (needs `agent_id`; also pass `user_id` so the learner filter finds and deletes it).
- mem0 2.2.x: `search` and `get_all` take ids in `filters=` and `top_k=`; only `delete_all` takes `user_id`. All mem0 calls go through `asyncio.to_thread`. Keep `MEM0_TELEMETRY=False` set before mem0 is imported.
- Recall runs in parallel under a timeout and fails open; writes run in the background and never block a turn.
- A learner with memory active bypasses the answer caches (L1, L2). Never cache a reply that used memory or session history.
- Identity is a signed learner token checked in the API before any store access. Never accept a raw client-chosen ID, and never log tokens or the secret.
- Any new `LearnerMemory` implementation needs a test against `InMemoryLearnerMemory`'s behavior (isolation per learner, forget count).
