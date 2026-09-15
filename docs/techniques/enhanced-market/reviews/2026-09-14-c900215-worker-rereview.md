# EM worker rereview: c900215

**Verdict: deployment hold remains.** The original six regressions and seven developer boundary cases pass, but three additional boundary cases reproduce incomplete WI-03/WI-04 handling. This is a focused continuation of the same acceptance contract.

Reviewed `c900215f30d853128a5b0a8f70ea2954da24d901`, independently confirmed as the remote desk branch tip. Fetched `origin/main` at `561a85980131f0d0ee34ffce8487c202feefbd7d` is an ancestor. Review checkout: `C:/Cursor/zargar-codex/.cache/em-worker-followup`, detached at that commit. Primary checkout remains `C:/Cursor/zargar-codex`, branch `codex/zargar-development`. No runtime changes, restart, repair, or backfill apply performed.

## Verified progress

- Original six reviewer cases are unchanged after newline normalization and pass.
- Those six plus `test_em_worker_ownership.py`: **13 passed in 37.61 seconds**.
- Three new cases: **3 failed in 13.07 seconds**, at intended assertions, with real PostgreSQL and the team's API rig. Planning and arming are mocked; these are observed calls, not actual orders.
- Both commands ran sequentially through `scripts/test-codex.ps1` against `zargar_test_codex`, with no competing pytest process found at each start. The team's broader totals were not independently rerun.
- Wrong-note lease rejection, replacement-media eligibility/cache identity, current-caption extraction, old extraction suppression during the model call, and persisted extraction reuse now pass the tested cases.

## WF-01 / WI-03 — P1: manual board check relabels an old extraction

**Path:** `C:/Cursor/zargar-codex/.cache/em-worker-followup/backend/zargar/api/routes_technique.py:313` calls `board_check(note_id)` without a revision. In `C:/Cursor/zargar-codex/.cache/em-worker-followup/backend/zargar/technique/ingest.py:646`, the method defaults to the current source revision while taking symbols from the existing legacy extraction. An edit retains that old extraction.

**Reproduction:** extract revision 1 for OLD; edit to revision 2 for NEW; call the same board method used by the manual route. `analyze` is called once for the old extraction. Test: `test_manual_board_cannot_relabel_old_extraction_as_current_revision`.

**Correction:** resolve the selected persisted extraction artifact and validate its revision/input identity against the requested current board before claiming or planning. Missing/stale extraction must be refused or explicitly re-extracted. Never use a caller's omitted revision as permission to label old output current. Apply this to every entry point, including the manual API. Preserve old artifacts as history.

**Acceptance:** adopt the reproduction unchanged and add a manual-route API case. No stale planning/arming, publication, or completion of the current revision's job.

## WF-02 / WI-03 — P1: expired lease reaches arming before rejection

**Path:** `ingest.py:310` checks source revision/deletion only. `ingest.py:707` calls `arm_plan` after that check. The final checkpoint validates the lease after the side effect.

**Reproduction:** let planning expire the board job's lease while leaving the source unchanged. `arm_plan` is called once; only the final checkpoint raises `StaleWorker`. Test: `test_expired_board_lease_cannot_arm_before_checkpoint_rejects`.

**Correction:** carry job ID, unique attempt owner, fence, expiry, revision and selected artifact through board processing. Validate ownership as well as source currency before planning, arming and publication, and enforce the authorization at the final arm mutation boundary across awaited work. A lost/expired/reassigned lease must stop side effects; rejecting a later checkpoint is insufficient. Engine work still uses the shared owner string `engine`; give concurrent attempts distinct identities and renew only the original claim.

**Acceptance:** retain the expiry case unchanged. Add reassignment/fence change during planning and an edit or lease loss during the awaited arm path; verify the actual arm mutation is refused. Do not flatten or disarm pre-existing positions as a cleanup workaround.

## WF-03 / WI-04 — P1: revision-only failure still writes without ownership

**Path:** `ingest.py:499` accepts only `revision_id`, tries to claim current work, then writes the note failed even if another owner prevents that claim. `_extract_and_check` uses this revision-only path for board errors.

**Reproduction:** another worker holds the current revision's live lease; call `_fail` with that revision ID. The note becomes failed despite the denied claim. Test: `test_revision_only_failure_cannot_mutate_another_owners_live_work`.

**Correction:** board failure handling must retain the original board job/attempt context. No fresh claim in a stale attempt's exception handler. No projection or job write without a still-valid original lease; a revision ID alone is not authority. Treat ownership conflicts as no-op/conflict outcomes.

**Acceptance:** retain the reproduction unchanged; test the full board exception path after another attempt takes over, including another attempt on the same source revision succeeding.

## Handoff

Adopt `worker-followup-regressions/test_codex_worker_followup_boundaries.py` unchanged into the development checkout's `backend/tests`. The file imports `tests.test_em_source_wiring`. From an isolated review checkout, run:

```powershell
./scripts/test-codex.ps1 tests/test_codex_worker_revision_ownership.py tests/test_em_worker_ownership.py tests/test_codex_worker_followup_boundaries.py -q --tb=short
```

Then run affected existing wiring/revision/API/runner groups in an exclusive sequential database window. Return the exact combined SHA, WF-01 through WF-03 closure table, additional boundary tests and results. Preserve the existing passing cases and keep the patch focused on ownership/provenance. The restart follow-up is not reopened by these worker defects. Source-backfill closure and the separate scoped FIX-01 money-repair decision remain unchanged.
