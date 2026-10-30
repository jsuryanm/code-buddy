# Pedagogy policy (as implemented)

Source of truth in code: `src/codebuddy/pedagogy/` and `agent/code_analysis.py`. Design rationale
is in [../PROJECT_SPEC.md](../PROJECT_SPEC.md) Section 8.

The policy is ordinary code. The model words the reply but never chooses the hint level, never
decides when to reveal, and cannot emit corrected code at levels 0 to 3 (the guard stops it).

## Decision table

`decide_mode(intent, progress, signals, now, max_turns, max_seconds)` returns a `Decision`:

| Intent (from classifier) | Mode | Level | Notes |
|---|---|---|---|
| `show_answer` | `reveal` | 4 | Always honored, even on the first turn |
| `off_topic` | `redirect` | none | Two-sentence polite redirect on the fast tier |
| `concept_question` | `explain` | none | Direct explanation, no hint ladder; cacheable (L1) |
| `debug_help`, `problem_start` | `hint` | `min(hints_given, 3)` | Walks the ladder; never reaches 4 on its own |

Hint ladder:

| Level | Name in code | What the tutor does | Corrected code |
|---|---|---|---|
| 0 | `DIAGNOSE` | One question that makes the learner trace or predict | No |
| 1 | `LOCATE` | Narrows to the region or step, without naming the bug | No |
| 2 | `NAME_CONCEPT` | Names the concept at fault, uses the explanation template, one check question | No |
| 3 | `SCAFFOLD` | Pseudo-code plan or a worked example on a different problem | No (pseudo-code fences allowed) |
| 4 | `REVEAL` | Full solution, why it failed (max 120 words), transfer question | Yes |

At levels 0 and 1 the prompt (`EARLY_HINT_RULE` in `pedagogy/templates.py`) says the private analysis
and runtime facts are only for choosing the question. The model must never state the error type, its
cause, or the failing input; it asks the learner to run or trace a specific small input and say what
they observe. The guard cannot catch this in prose, so it is a prompt rule, and `PROMPT_VERSION`
was bumped to `p2` with it.

## When the answer is offered

`offer_answer` becomes true when any of these holds, and `can_show_answer` is then true too:

| Trigger | Condition |
|---|---|
| Hints without progress | `hints_given >= 3` (starting with the 4th turn) |
| Turn cap | `hints_given >= LADDER_MAX_TURNS` (default 4) |
| Time cap | seconds since the first hint on this problem `>= LADDER_MAX_SECONDS` (default 600) |
| Give-up phrase | "I give up", "this is stupid", "I'm stuck/frustrated/lost", "I don't get it/this", "this makes no sense" |
| Repeated submission | the same code (normalized) sent a third time in a row |

With the default settings the 3-hint trigger fires before the 4-turn cap, so the offer appears on
the fourth hint. Lower `LADDER_MAX_TURNS` below 3 to offer earlier.

An offer does not reveal anything. The hint at level 3 is still given, the prompt asks the model to
end by saying that "Show answer" is available, and the UI highlights the button. The learner
decides. Independently of any trigger, `can_show_answer` is true after the first hint, so the
button is enabled from then on.

Explicit requests are matched by `asks_for_answer()`, for example "show me the answer",
"give me the solution", "just tell me", "reveal the solution".

## How progress changes

`update_state` applies after each turn (`SessionProgress`, stored in the session cache):

| Event | Effect |
|---|---|
| Hint turn | `hints_given += 1`; `started_at` set on the first hint |
| Reveal | `reveals += 1`; `hints_given = 0`; `started_at = 0`; repeated submissions reset |
| Classifier says `problem_start` | Ladder restarts (`hints_given = 0`, `started_at = 0`) |
| Learner answers the run-my-code prompt | `run_permission` becomes `allow` or `deny` (if "remember" was chosen) |
| Every turn | Stage updated from the classifier; last 6 messages kept (500 chars each) |

Known gap: the tutor does not detect that a learner solved the problem. The ladder resets only on
a reveal, a classified new problem, session expiry (2 hours idle), or a new session. If a
learner finishes one problem and moves on without saying so, the next question may start at a
higher hint level. The UI's "New session" button is the manual reset.

## Leak guard rules (`pedagogy/guard.py`)

Enforced for `mode == hint` and level below 4. Violations raise `LeakDetected`:

- A fenced block opens with any language other than pseudo-code. At level 3, fences labeled
  `text`, `txt`, `plaintext`, `pseudo`, `pseudocode`, or unlabeled are allowed; at levels 0 to 2 no
  fence is allowed.
- A line is a block statement: starts with `for`, `while`, `if`, `elif`, `else`, `def`, `class`,
  `try`, `except`, `finally`, or `with` and ends in `:` or `)`.
- A line is `return x`, `import m`, or `from m import ...`.
- A line is an assignment (`x = 1`, `total += n`; `==` is not an assignment).

Inline code in backticks is always fine, and so is lowercase prose that merely starts with a
keyword ("for example, ..." does not end in `:`). What the guard cannot catch: a leak written in
prose ("change the plus one to nothing"), or code in an indented block without a fence or keyword.
That is why evals should also sample replies with an LLM judge (not built yet).

When the guard stops a reply, the text already shown stays, and `fallback_text()` appends a safe
question from the stage question bank (`pedagogy/templates.py`).

## Explanation template

Used at level 2 and for reveals. At most 120 words:

1. What happens, one sentence, using the learner's variable names.
2. Why, one sentence naming the concept.
3. Tiny trace, 3 to 5 lines of variable values on a small input.
4. One check question.

## Bug patterns (`agent/code_analysis.py`)

Static analysis on the learner's Python, never executed. Findings reach the model as "private
analysis" so it can choose a good question; they are not shown to the learner directly.

| Pattern id | Concept | Detected when |
|---|---|---|
| `off_by_one_range` | loop bounds | `for ... in range(len(x) + k)` |
| `uninitialized_accumulator` | variable initialization | `x += ...` where `x` was not assigned earlier in the scope |
| `mutating_while_iterating` | iteration and mutation | `for x in lst:` with `lst.remove/append/pop/insert` inside |
| `missing_base_case` | recursion | a function calls itself and contains no `if` |
| `shadowed_builtin` | names and scope | assigning to `list`, `sum`, `max`, `len`, and similar names |

A syntax error is reported as a finding with its line number. To add a pattern, add a
`BugPattern` entry to `PATTERNS`, a detector in `analyze()`, a case in `tests/unit/test_code_analysis.py`,
and a row in `eval/golden/cases.jsonl`.

## Tools and the policy

Running the learner's code is a separate, rule-based decision made after the mode is chosen, and
only in hint mode on code that parses. What the run found (error type and line, variable values)
reaches the model as private notes, and the leak guard still checks every reply. Details:
[tools-and-approvals.md](tools-and-approvals.md).

## Changing the policy

1. Edit `pedagogy/policy.py` (or `frustration.py`) and update `tests/unit/test_policy.py` first.
2. Run `uv run pytest -q` and `uv run python -m codebuddy.eval.run`.
3. If prompts changed, bump `CODEBUDDY_PROMPT_VERSION` so cached answers stop matching.
4. Update this page and, if the design changed, the spec.
