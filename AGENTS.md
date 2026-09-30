# Development workflow

After every code change, run the project checks in this order:

1. Apply formatting and lint fixes with `task ruff`.
2. Run static type checking with `task mypy` and fix any reported issues.
3. Run the test suite with `task tests`.

Do not use more than four test workers. Prefer the default single-worker run unless
parallel execution is needed; when it is, cap it at four workers to avoid exhausting
the development machine.

# Code structure

Do not extract one-off logic into helper methods, utility functions, or utility
modules merely to apply DRY. Keep it inline at its only call site. Extract such
logic only with explicit user approval.

# Git workflow

After a task is fully implemented and verified, review the working tree and
stage only files that belong to that task. Commit the changes with the exact
message `Task <number> — <title>` and push them with a normal fast-forward push.

Keep different task numbers in separate commits whenever practical. When one
task changes both the client and server, use the same task number and title in
both repositories. Fetch and inspect the remote state before pushing. Never use
`git pull` blindly in a dirty working tree, and never force push unless the user
explicitly requests it after reviewing the reason.
