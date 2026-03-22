---
description: "Run the full multi-agent ensemble on a coding task — 6 specialists + judge synthesis"
agent: "ensemble"
model: 'Claude Opus 4.6 (1M context)(Internal only)'
argument-hint: "Describe the coding task you want the ensemble to solve"
---

Run the ensemble workflow on this task. The orchestrator will triage, dispatch to the appropriate specialists, have the judge synthesize via two-phase analysis (analyze → commit → code), run the dual QC gate (verifier + security re-review), run the Phase 4b Codex blind review (non-blocking, parallel), and present the final solution for your review before applying any changes.
