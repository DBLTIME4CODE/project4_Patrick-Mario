---
description: "Run standalone quality check on code — verify consistency, correctness, test alignment"
agent: "verifier"
model: 'Claude Opus 4.6 (1M context)(Internal only)'
argument-hint: "File path or code to quality-check"
---

Run a standalone quality check on the specified code. Read the relevant files first, then verify:

1. **Syntax & imports** — all imports resolve, no circular dependencies
2. **API consistency** — function signatures match between definition and call sites
3. **Test alignment** — tests call the right functions with the right arguments and assert correct behavior
4. **Edge cases** — boundary conditions and error paths are handled
5. **Safety** — no dangerous patterns (eval, exec, shell=True, hardcoded secrets)

Report PASS or FAIL with specific issues and fixes for each problem found.
