---
description: "Run project validation — ruff, mypy, pytest — and report results"
agent: "pragmatist"
model: 'Claude Opus 4.6 (1M context)(Internal only)'
argument-hint: "Optional: specific file or module to validate"
---

Run the project validation suite and report results:
1. `ruff check .` — lint errors
2. `mypy src` — type errors
3. `pytest -q` — test failures

For any failures, explain what's wrong and suggest the fix. If everything passes, confirm it cleanly.
