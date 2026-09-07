# Shared Claude / Codex guidance

Both agents follow this file. Read `CLAUDE.md` for the existing architecture,
commands, testing conventions, and trading invariants; read
`docs/ARCHITECTURE.md` before non-trivial changes and `docs/PLATFORM-RULES.md`
before runtime changes. Keep shared collaboration rules here, not in duplicated
agent-specific copies. Historical desk assignments in CLAUDE.md are context;
the current user task determines scope.

## Worktrees and ownership

- GitHub's default branch is `main`; new work starts from `origin/main`.
- Codex works in `C:\Cursor\zargar-codex`, branch `codex/zargar-development`.
- Preserve `C:\Cursor\zargar` and all its `.claude/worktrees` checkouts,
  branches, dirty files, environments, and processes. Never prune, reset, clean,
  switch, or install dependencies in another agent's checkout.
- Inspect status, worktree list, and recent merges before edits. Keep shared
  engine changes small and record changes to shared rules in PLATFORM-RULES.
- Report the active folder, branch, checks, and unresolved blockers at handoff.
- If Git reports dubious ownership, use the per-command option
  `git -c safe.directory=C:/Cursor/zargar-codex ...`; do not trust all folders.

## Database and runtime isolation

- Existing runtime owns API `8420` and frontend dev port `5173`.
  Codex reserves API `8421` and frontend `5174`; check listeners before use.
- Never run a second engine against an existing runtime database, even with
  `broker=sim`: persisted settings, scheduled jobs, and positions still matter.
- Do not use `scripts/start.ps1`, `stop.ps1`, or generic setup scripts for Codex:
  they manage the shared runtime and helpers, including processes on `8420`.
- Codex tests use only `zargar_test_codex` on loopback port `5433` through
  `scripts/test-codex.ps1`. Tests drop/recreate tables. Do not run simultaneous
  test processes against the same database (including pytest-xdist).
- Never point tests at `zargar`, `zargar_test`, `zargar_test_team2`, or any
  other agent's database. Never run an interactive app against the test DB.
- Keep credentials local. Do not copy Claude's `.env`, runtime settings,
  database contents, broker keys, or ingestion credentials into this worktree.
- The Codex local `.env` reserves `zargar_dev_codex` for a future isolated sim
  runtime. It is deliberately not provisioned by test setup. Before launching
  one, provision that separate database, verify effective config and blank
  integration keys, and use `8421`. Changing a port alone is not isolation.

See `docs/COLLABORATION.md` for setup commands and verification status.
