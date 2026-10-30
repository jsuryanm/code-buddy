# 0006. Allowlist-based Python sandbox, not a security boundary

Status: accepted. Date: 2026-10-30.

## Context
Tracing learner code gives the tutor facts (the real error and line, variable values) that make
hints better. Docker was unavailable in development, and a proper microVM service is out of scope
for the first release.

## Decision
Run only beginner Python through an AST allowlist, restricted builtins, resource limits, an empty
environment, a throwaway directory, a timeout, and `unshare -rn` for no network where possible.
Document it as defense in depth and require a container with no network for public deployments.

## Consequences
Useful and testable today, with real protection against accidents and casual abuse. Not safe
against a determined attacker, so the approval prompt stays and production needs outer isolation.
Classes, file access, and most imports are unavailable, which matches the fundamentals scope.
