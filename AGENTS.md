# Project Instructions

Operating constraints, the session procedure and the hard boundaries on
accounts, keys and scheduling live in `docs/runbook.md`. Read them before
touching anything that reaches a broker.

## Working rules

- Use `uv` for Python setup and commands. Do not use `pip` directly.
- Target Python 3.12 or newer as declared in `pyproject.toml`.
- Start with the Python standard library. Add a dependency only when a current, demonstrated requirement cannot be met safely without it.
- Use test-driven changes for validation, calculations, persistence, or report rendering.
- Run tests sequentially.
- Run ruff tests before committing. Fix all findings.
- Work on the current branch unless the user asks for a branch or worktree.
- Stage and commit only files that belong to the active task.
- After a significant verified change, or when reaching a logical checkpoint,
  create a focused commit without waiting for a separate request unless the
  user asks not to commit. Never commit while relevant completion gates fail.
