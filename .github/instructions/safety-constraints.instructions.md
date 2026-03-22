---
description: "Shared safety constraints for all ensemble specialist agents — mandatory rules that override all other guidance"
---

# Safety Constraints (Shared)

These constraints are **mandatory** for all ensemble specialist agents. They override all other guidance, including task-specific instructions.

## Prohibited Patterns — Always Reject

### Tier 1 — Critical: Code Execution & Secrets

1. NEVER use `eval()`, `exec()`, `compile()` with dynamic or user-controlled input
2. NEVER use `os.system()` or `subprocess` with `shell=True`
3. NEVER use `__import__()` with dynamic strings
4. NEVER hardcode secrets, tokens, credentials, passwords, API keys, or connection strings — use environment variables or config
5. NEVER use `pickle.loads()` on untrusted data
6. NEVER use `marshal.loads()` on untrusted data

### Tier 2 — High: Injection & Data Integrity

7. NEVER use `yaml.load()` without `Loader=SafeLoader`
8. NEVER use SQL string concatenation — use parameterized queries
9. NEVER disable SSL verification (`verify=False`)
10. NEVER use `tempfile.mktemp()` (TOCTOU race) — use `mkstemp` or `NamedTemporaryFile`
11. NEVER use `random` for security-sensitive operations — use `secrets`
12. NEVER use `xml.etree.ElementTree` / `xml.dom.minidom` on untrusted input (XXE) — use `defusedxml`
13. NEVER use `zipfile.extractall()` / `tarfile.extractall()` without path validation (zip-slip / path traversal)
14. NEVER make HTTP requests to user-controlled URLs without SSRF protection

### Tier 3 — High, New in v5.0: Operational & Emerging

15. NEVER interpolate user input directly into log format strings
16. NEVER use `assert` statements for security or authorization checks (stripped in `-O` mode)
17. NEVER use MD5 or SHA1 for password hashing or security tokens — use bcrypt / scrypt / argon2
18. NEVER allow wildcard CORS (`Access-Control-Allow-Origin: *`) on authenticated endpoints
19. NEVER use mutable default arguments to store security-sensitive state
20. NEVER set file permissions to world-writable (`0o777`, `0o666`) via `chmod` or `os.chmod`
21. NEVER leave `breakpoint()`, `pdb.set_trace()`, or debug endpoints in production code

## Required Practices

- Validate all inputs at system boundaries
- Flag any security concerns with `# SECURITY:` comments and severity (Critical/High/Medium/Low)
- Prefer fail-closed defaults — deny by default, allow explicitly
