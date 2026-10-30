---
name: spec-update
description: Apply a design decision change to PROJECT_SPEC.md and keep the spec, CLAUDE.md, and rules consistent.
disable-model-invocation: true
argument-hint: "[decision change, e.g. swap reranker]"
---

Apply this design change to the project documents: $ARGUMENTS

1. Find every affected section in `PROJECT_SPEC.md`: prose, tables, Mermaid diagrams, roadmap, risks, open questions.
2. Edit them so the change is stated once and consistently. Replace outdated content instead of leaving both versions.
3. Grep the spec for terms the change made obsolete.
4. Update Section 22 (traceability) and the open questions if the change adds or resolves one.
5. Bump the Status version and rewrite the Changes row at the top of the spec.
6. Check `CLAUDE.md` (keep it under about 400 words) and `.claude/rules/*.md` for statements that are now wrong. Fix them.
7. Run the `spec-reviewer` agent and fix what it reports.
8. Summarize what changed in a few lines.
