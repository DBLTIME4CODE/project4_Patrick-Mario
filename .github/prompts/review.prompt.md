---
description: "Code review — security + architecture review of recent changes or a specific file"
agent: "ensemble"
model: 'Claude Opus 4.6 (1M context)(Internal only)'
argument-hint: "File path or description of what to review"
---

Review the specified code. Triage this as **CODING** — dispatch all 6 specialists. Focus on:
- Security vulnerabilities or risky patterns
- Design issues, coupling, or SOLID violations
- Missing input validation or error handling

Present findings organized by severity (Critical → Low) with specific line references and recommended fixes.
