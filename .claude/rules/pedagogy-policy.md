---
paths:
  - "prompts/**"
  - "docs/pedagogy-policy.md"
  - "**/pedagogy*/**"
---

# Pedagogy policy

Detail behind the CLAUDE.md rule "pedagogy is code, not prompt". Source: PROJECT_SPEC.md Section 8.

## Hint ladder

| Level | Content | Corrected code allowed |
|---|---|---|
| L0 | Diagnostic question (trace or predict) | No |
| L1 | Locate the region | No |
| L2 | Name the concept, with retrieved explanation | No |
| L3 | Partial scaffold or analogous worked example | No (analogous problem only) |
| L4 | Full solution, why the bug happened, transfer question | Yes |

- Never skip past L0 on a first turn unless the learner explicitly asks for the answer.
- Ask one question at a time.

## Escalation

- "Show answer" is visible after the first hint and needs no justification.
- Offer L4 proactively after 4 tutor turns or 10 minutes on one problem (configurable).
- Frustration signals that trigger the offer: repeated identical submissions, 3 or more hints without progress, phrases like "I give up" or "just tell me", rapid short messages.
- A reveal always ends with a transfer question on a slightly different case.

## Error-explanation template (max 120 words)

1. What happens, one sentence, using the learner's variable names.
2. Why, one sentence naming the concept.
3. Tiny trace, 3 to 5 lines of variable values on a small input.
4. One check question.

## Answer-leak guard

Rule-based check plus a small LLM judge blocks corrected code at L0 to L3. On a hit, regenerate with a stricter instruction, or fall back to a retrieved concept-only explanation.
