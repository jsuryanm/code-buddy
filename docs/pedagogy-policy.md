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
| any but `problem_start`, when `signals.fixed` | `confirm` | none | The learner fixed the bug (see below); offers a quiz |
| `off_topic` | `redirect` | none | Two-sentence polite redirect on the fast tier |
| `concept_question` | `explain` | none | Direct explanation, no hint ladder; cacheable (L1) |
| `debug_help`, `problem_start` | `hint` | `min(hints_given, 3)` | Walks the ladder; never reaches 4 on its own |

Hint ladder:

| Level | Name in code | What the tutor does | Corrected code |
|---|---|---|---|
| 0 | `DIAGNOSE` | Says where the problem is (line or step) and what causes it, in plain words, then one question toward the fix (max 60 words) | No |
| 1 | `LOCATE` | Narrows to the specific step or value that goes wrong and why, with a nudge on what to change as an idea (max 60 words) | No |
| 2 | `NAME_CONCEPT` | Names the concept at fault, uses the explanation template, one check question (max 90 words) | No |
| 3 | `SCAFFOLD` | Pseudo-code plan or a worked example on a different problem (max 110 words plus the pseudo-code) | No (pseudo-code fences allowed) |
| 4 | `REVEAL` | Full solution, why it failed (max 120 words), transfer question | Yes |

At levels 0 and 1 the prompt (`EARLY_HINT_RULE` in `pedagogy/templates.py`) asks the model to say
briefly where the problem is (the line or step, using the learner's own names) and what causes it,
in plain words. For a runtime error it may name the error in plain words with a short gloss ("an
IndexError, which means the list has no item at that position"). Then it asks one question that
pushes the learner toward the fix. It never writes the corrected code or the exact fix; the guard
stops corrected code on the stream, and a fix written in prose is a prompt rule only. Level 1 goes
one step further than level 0: the specific step or value, why it goes wrong there, and a nudge on
what to change as an idea. Level 2 names the concept with a short trace (explanation template),
level 3 gives a pseudo-code plan. `PROMPT_VERSION` was bumped to `p4` with this rule.

## Plain, short replies

Every learner-facing prompt carries `STYLE_RULE` (`pedagogy/templates.py`): short sentences, plain
everyday words, the learner's own variable names and line numbers, a technical term explained in a
few everyday words the first time, no lists of terms, no filler. Each hint level ends with exactly
one question. Word limits: levels 0 and 1 at most 60 words, level 2 at most 90, level 3 at most 110
plus the pseudo-code, explanations at most 120, reveals keep a 120-word "why" plus the code,
redirects stay at two sentences.

Word limits in a prompt are a request, not a guarantee, so the code adds a backstop: each model
call gets `max_completion_tokens` for its mode (hint 250, explain 320, reveal 900, redirect 90;
settings `MAX_TOKENS_*`). The cap is passed per call, by mode and not by tier, and
`RunnableWithFallbacks` hands the same kwargs to every fallback tier, so a fallback keeps it. A
reply that hits the cap is cut off mid-sentence; the caps are set well above the word limits so
this only happens when the model ignores them. `PROMPT_VERSION` became `p3` with this change (plus
the classifier prompt that now sees recent history) and is now `p4` (the early-hint rule above).

## When the answer is offered

`offer_answer` becomes true when any of these holds, and `can_show_answer` is then true too:

| Trigger | Condition |
|---|---|
| Hints without progress | `hints_given >= 2` (after 2 hints, so from the 3rd hint on) |
| Turn cap | `hints_given >= LADDER_MAX_TURNS` (default 3) |
| Time cap | seconds since the first hint on this problem `>= LADDER_MAX_SECONDS` (default 600) |
| Give-up phrase | "I give up", "this is stupid", "I'm stuck/frustrated/lost", "I don't get it/this", "this makes no sense" |
| Repeated submission | the same code (normalized) sent a third time in a row |

With the default settings the 2-hint trigger fires before the 3-turn cap, so the offer appears with
the third hint (level 2). Lower `LADDER_MAX_TURNS` below 2 to offer earlier. This keeps the learner
out of a long hint loop.

An offer does not reveal anything. The hint at its level is still given, the prompt asks the model to
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
| Fix confirmed | `hints_given = 0`; `started_at = 0`; repeated submissions reset; `quiz_offer` set to the fixed pattern |
| Code sent that parses (not a quiz answer) | `last_patterns` becomes its bug patterns, the yardstick for the next fix |
| Classifier says `problem_start` | Ladder restarts (`hints_given = 0`, `started_at = 0`) |
| Learner answers the run-my-code prompt | `run_permission` becomes `allow` or `deny` (if "remember" was chosen) |
| Every turn | Stage updated from the classifier; last 6 messages kept (500 chars each) |

## Fix detection

`fixed_it(progress, features, code_changed, runtime)` in `pedagogy/policy.py` decides from the
code alone whether the learner fixed their bug. It is true when the last code they sent had bug
patterns (`progress.last_patterns`), this code is different (its normalized hash changed), it
parses, none of those patterns remain, and a trace that ran this turn did not fail. A message
such as "I fixed it" or "it works now" with the same code is not enough. A syntax error in between
does not lose the yardstick: code that fails to parse leaves `last_patterns` as it was.

Tools run after the policy, so in the current graph no trace has run yet when `fixed_it` is
called; the runtime check covers a runtime result when one is present and is tested on its own.

A fix sets `Signals.fixed` (not a frustration signal), and `decide_mode` returns `confirm` after
the explicit-reveal check. A turn classified as `problem_start` is a new problem, not a fix. The
`confirm` prompt (`CONFIRM_RULE`) asks for at most 60 plain words: say what the change fixed using
the learner's own code, ask them to say in one sentence why it works, and mention that a quiz is
available. It writes no new code; the model gets a private note naming the fixed symptom. The
reply runs on the standard tier with the hint token cap, and the leak guard is off because the
learner's own fixed code is not a leak. The ladder resets, which closes the old gap where a solved
problem left the next question at a high hint level. `meta` carries `offer_quiz: true` and
`quiz_concept`, the concept name (for example "loop bounds"), never the pattern id.

## Quiz after a fix

`POST /v1/quiz` starts a set of five questions on the bug pattern just fixed
(`progress.quiz_offer`); 404 when there is nothing to quiz on. The questions come from a
hand-written bank in `pedagogy/quiz.py`, not from the model: five snippets per pattern, in rising
difficulty (two easy, two medium, one hard). Easy is a short, obvious version; medium hides the
bug in a slightly longer function; hard puts it in a nested loop or a helper. Each entry stores its
`solution`. A test asserts every snippet parses and `analyze()` finds exactly its pattern, and
every solution parses with no pattern. Starting a quiz makes no model call, resets the ladder, and
clears `last_patterns` so quiz code never counts as a fix of the learner's own bug.

`progress.quiz` holds `{"pattern", "index" (0 to 4), "score", "results", "tries"}`. While it is
set, each turn is graded by `advance()` before the normal policy:

| Turn | Result |
|---|---|
| Code unchanged from the question (ignoring blank lines and trailing spaces) | Not graded: a short nudge from code, "Edit the code in the box to fix the bug, then send it."; no try counted |
| Code that parses with the pattern gone | "Correct.", score + 1, and the next question in the same reply (no extra button) |
| First wrong try (pattern still there, or a syntax error) | One hint from the model: the normal level-0 hint prompt, leak guard on |
| Second wrong try, "skip", or an explicit request for the answer | The stored solution, written by code; the question is marked wrong and the next one follows |
| "stop quiz" (also "skip/end/quit the quiz") | The quiz ends with the score so far |
| A message without code | Not a quiz answer: the tutor replies as usual and the quiz waits |
| Answer to question 5 | A summary, "4 of 5"; if any were wrong, one sentence naming the difficulties to review. The quiz is cleared |

Showing a quiz solution is a reveal from code, from the bank's stored `solution`, so the guard is
not involved. A quiz answer skips the classifier and retrieval (it goes from `check_cache` straight
to `policy`). There is no ladder inside a quiz: quiz turns never change `hints_given`, run no tools,
skip the answer cache, and write nothing to learner memory. Show answer is hidden while a quiz
runs. `meta` carries `quiz: {"index", "total", "difficulty", "score"}` while one is active, and
`quiz_code`, the snippet of a new question, so the UI can put it into the code box.

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

Used at level 2 (at most 90 words) and for reveals (at most 120 words):

1. What happens, one sentence, using the learner's variable names.
2. Why, one sentence naming the concept.
3. Tiny trace, 2 to 3 lines of variable values on a small input.
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

A syntax error is reported as a finding with its line number. To add a pattern, add a `BugPattern`
entry to `PATTERNS`, a detector in `analyze()`, a case in `tests/unit/test_code_analysis.py`, and a
row in `eval/golden/cases.jsonl`.

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
