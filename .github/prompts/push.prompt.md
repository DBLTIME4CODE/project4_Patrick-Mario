---
description: "Quick git commit and push — stages changed files, commits with a summary, and pushes to origin"
model: 'Claude Opus 4.6 (1M context)(Internal only)'
argument-hint: "Optional: commit message (auto-generated if omitted)"
---

Run the project validation suite first, then commit and push:

1. Run `pytest -q` on any changed test files to verify nothing is broken
2. Run `git status` to see what's changed
3. Run `git diff --stat` to summarize the changes
4. Stage ONLY the modified/new files shown in git status (not untracked files unless they're clearly part of the current work)
5. Generate a clear, conventional-commits-style commit message summarizing what changed (or use the user's message if provided)
6. Commit and push to `origin master`

Show the commit hash and confirm success.
