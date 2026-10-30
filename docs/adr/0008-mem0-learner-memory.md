# 0008. Learner memory on mem0, as private notes only

Status: accepted. Date: 2026-10-30.

## Context
The spec (Section 8.6) wants a learner model that lasts across sessions. The session cache keeps
only the last six messages for two hours. The tutor's promise is that the policy, not the model,
decides what the learner sees, so any long-term memory must not become a way around that.

## Decision
- Use mem0 (open source, `mem0ai>=2.2.1,<3`) with embedded Qdrant under `CODEBUDDY_MEMORY_PATH`,
  behind a small `LearnerMemory` protocol (`recall`, `remember`, `all`, `forget`). Tests use an
  in-memory fake.
- Map the three memory kinds to mem0 as follows:
  - Semantic: facts mem0 extracts from recent turns (a normal `add`).
  - Episodic: one line per reveal, built by our code and stored with `infer=False`.
  - Procedural: mem0's `procedural_memory` type, written after a reveal with
    `agent_id="codebuddy-tutor"` (mem0 ignores the type without an agent ID) and the learner's
    `user_id`, so one learner filter finds, lists, and deletes everything.
- Opt-in per learner, identified by a signed learner token, not an account.
- Recall runs as a graph node in parallel with classification and retrieval under a 0.6 s timeout.
  Writes run in the background on a reveal and every fourth hint.
- Memory reaches the model only as a delimited `<memory>` block of private notes. The policy
  functions never read it. Answer caches are bypassed for a learner with memory active.

## Alternatives not taken
- Our own Redis store: we would write extraction, deduplication, merging, and embedding search
  ourselves. mem0 already does these.
- Policy-driven memory (memory feeds `decide_mode()`, for example to skip hints for a "mastered"
  concept): it makes pedagogy depend on a model-written, unverified profile, which breaks "pedagogy
  is code, not prompt" and the anti-frustration guarantees.
- Concept-mastery scores as in spec 8.6: needs solved detection we do not have.

## Consequences
- Writes cost OpenAI calls (extraction and embeddings) and personal data is stored on the server
  and sent to OpenAI. The opt-in, the list view, and Forget me exist for this reason.
- The tutor can personalize questions but cannot change the ladder or reveal earlier.
- mem0 plans to remove procedural memory in a breaking release, so the dependency is capped below 3.
- A learner token in the URL is a bearer secret; there are no accounts, no retention schedule, and
  no solved detection. Details in [../memory.md](../memory.md).
- Only one process can open the embedded store; running several API workers needs a Qdrant server
  for memory too, which is not wired yet.
