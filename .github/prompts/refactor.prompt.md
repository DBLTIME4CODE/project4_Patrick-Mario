---
description: "Refactor code — improve structure, reduce complexity, clean up without changing behavior"
agent: "ensemble"
model: 'Claude Opus 4.6 (1M context)(Internal only)'
argument-hint: "File path or module to refactor, and what to improve"
---

Refactor the specified code. Triage this as **CODING** — dispatch all 6 specialists.

**Constraint: behavior-preserving.** All existing tests must still pass after refactoring. If no tests exist for the code being refactored, write them FIRST against current behavior, then refactor.

Focus on:
- Reducing complexity and improving readability
- Better separation of concerns
- Removing duplication
- Preserving all existing behavior

Present the refactored code with before/after summaries and confirm test coverage.
