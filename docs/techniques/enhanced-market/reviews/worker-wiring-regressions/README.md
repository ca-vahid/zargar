# Worker wiring regression handoff

Reviewed branch: `claude/zargar-stock-app-research-8mnqfh`, commit `9078bfddfaf53b87b431a9139f8fbed19e14e094`.

Read the accompanying `2026-09-14-worker-wiring-review.md` for WI-01 through WI-05 and additional acceptance cases. The six attached cases failed at their intended assertions on that commit. They import the team's `tests.test_em_source_wiring` PostgreSQL/API rig and require that module.

Copy `test_worker_revision_ownership.py` into the development checkout's `backend/tests/test_codex_worker_revision_ownership.py`. From the review checkout, the reviewer ran:

```powershell
Set-Location C:/Cursor/zargar-codex/.cache/em-worker-wiring-review
./scripts/test-codex.ps1 tests/test_codex_worker_revision_ownership.py -q --tb=short
```

Use only `zargar_test_codex` and an exclusive sequential test window. Do not run against runtime or another desk's database. Do not start an engine. Keep the cases unchanged; correct the implementation, then add the review's further boundary coverage. Return the combined SHA, closure table, and exact test outcomes before deployment review.
