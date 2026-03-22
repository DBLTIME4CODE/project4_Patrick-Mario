# Review Checklist

## Functional Review
- [ ] Acceptance criteria are fully met
- [ ] No obvious regressions
- [ ] Edge cases considered

## Technical Review
- [ ] Code is readable and maintainable
- [ ] Tests are meaningful (not only happy path)
- [ ] Error handling is appropriate
- [ ] No hardcoded secrets or sensitive data

## Quality Gates
- [ ] `ruff check .` passes
- [ ] `mypy src` passes
- [ ] `pytest -q` passes

## Final Decision
- [ ] Approve
- [ ] Request changes

## Reviewer Notes
<notes>
