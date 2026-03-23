# Copilot Instructions for This Repository

## Ensemble Pipeline Mandate (v10.0)
- **ALL coding tasks (code creation, modification, or deletion) MUST go through the full ensemble pipeline (ALL 6 specialists → judge → triple QC gate). No exceptions. No reduced dispatch.**
- The ensemble agent is PROHIBITED from writing code solo or skipping any specialist.
- Only non-coding responses (questions, explanations, config lookups) may skip the pipeline.
- This rule applies regardless of perceived task size or complexity.
- **Phase 4b (Codex blind review)** runs in parallel with the QC gate as a non-blocking, independent second opinion.

## Multi-Model Pipeline
- **Claude Opus 4.6** (1M context): 5 specialists + judge + verifier + security-reviewer (8 agents)
- **GPT-5.3 Codex** (400K context): codex-specialist (Phase 2) + codex-reviewer (Phase 4b, advisory)
- **Gemini 3.1 Pro** (173K context): gemini-verifier (Phase 4, blocking cross-model QC)
- Total: 12 agents across 3 model families

## Working Model
- Treat the user as Scrum Master/product validator.
- Prefer implementing complete vertical slices (code + tests + docs updates).
- Do not stop at analysis when implementation is requested.

## Engineering Standards
- Keep code under `src/myproject` and tests under `tests`.
- Add or update tests for every behavior change.
- Keep functions focused and avoid unnecessary abstractions.
- Use type hints for new/changed Python code.

## Validation Steps
Before considering a task done, run:
1. `ruff check .`
2. `mypy src`
3. `pytest -q`

## Communication Style
- Summarize what changed and why.
- Call out risks, assumptions, and open questions.
- Propose next steps only when useful.
