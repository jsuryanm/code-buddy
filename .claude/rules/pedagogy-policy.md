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
| L0 | Where and why: the line or step (learner's names) and the cause in plain words, then one question toward the fix | No |
| L1 | Narrow down: the specific step or value, why it goes wrong, a nudge on what to change (as an idea) | No |
| L2 | Name the concept, with retrieved explanation | No |
| L3 | Partial scaffold or analogous worked example | No (analogous problem only) |
| L4 | Full solution, why the bug happened, transfer question | Yes |

- Never skip past L0 on a first turn unless the learner explicitly asks for the answer.
- Ask one question at a time.

## Escalation

- "Show answer" is enabled after the 4th hint (sooner when an offer trigger fires) and needs no justification. An explicit request always reveals, even on the first turn.
- Offer L4 proactively after 5 hints (turn cap 6, `LADDER_MAX_TURNS`) or 10 minutes on one problem (configurable). Hints 4 to 6 stay at L3.
- Frustration signals that trigger the offer: repeated identical submissions, 5 or more hints without progress, phrases like "I give up" or "just tell me", rapid short messages.
- A reveal always ends with a transfer question on a slightly different case.

## Error-explanation template (max 120 words)

1. What happens, one sentence, using the learner's variable names.
2. Why, one sentence naming the concept.
3. Tiny trace, 3 to 5 lines of variable values on a small input.
4. One check question.

## Answer-leak guard

Rule-based check plus a small LLM judge blocks corrected code at L0 to L3. On a hit, regenerate with a stricter instruction, or fall back to a retrieved concept-only explanation.

## Fix detection and quiz

- A fix is judged from the code only: patterns gone, code changed, parses, same functions and at least 60% of the statements. The reply is `confirm`; the ladder resets; a quiz is offered and stays offered until it starts, a new problem, or new buggy code. The learner's "why it works" reply with the same code gets a short acknowledgement, not a hint.
- Quiz: five hand-written questions per pattern (2 easy, 2 medium, 1 hard), graded by code. One guarded L0 hint per question, then the stored solution. Unchanged code gets a nudge, different code is not graded; neither costs a try. No ladder, tools, caching, or memory writes inside a quiz.
