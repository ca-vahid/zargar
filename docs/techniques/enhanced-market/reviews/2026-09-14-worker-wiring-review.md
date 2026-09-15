# EM worker wiring review — 2026-09-14

**Verdict: hold deployment of the worker wiring PR pending WI-01 through WI-05.** These findings do not reopen the previously verified deployment or source backfill. The restart follow-up addresses the reported HTTP 500 path; its checks are scoped separately below.

Reviewed commit: `9078bfddfaf53b87b431a9139f8fbed19e14e094` on `claude/zargar-stock-app-research-8mnqfh`, including `5254531` and `b8d1ab8`. Review checkout: `C:/Cursor/zargar-codex/.cache/em-worker-wiring-review` (detached). Primary folder remains `C:/Cursor/zargar-codex`, branch `codex/zargar-development`; other desks' work was preserved.

## Independent evidence

- Six new PostgreSQL/API regression cases fail at the intended assertions on the reviewed commit (16.51 seconds). No fixture/import failure. Tests use the team's real API/database rig with model and planning calls mocked; no engine startup, paid calls, or orders.
- Reproductions: `C:/Cursor/zargar-codex/docs/techniques/enhanced-market/reviews/worker-wiring-regressions/test_worker_revision_ownership.py`.
- Supplied wiring/revision/watermark checks: **18 passed in 130.91 seconds**, sequentially, after a process check found no competing Codex pytest process. Command: `./scripts/test-codex.ps1 tests/test_em_source_wiring.py tests/test_em_source_revisions.py tests/test_codex_source_watermark_pair.py -q --tb=short`. An earlier six-case wiring run passed but had another test client visible at its start and is not counted as exclusive evidence.
- Windows PowerShell 5.1 parser: zero parse errors; restart script contains zero non-ASCII bytes. No restart, deployment lease, or repair apply was performed.
- Reported broader-suite totals and the reported pre-existing arming failure were not independently rerun in this review. Six directly reproduced failures are sufficient to require another patch.

## Required corrections

### WI-01 — P1: a transcript lease can write a different note

**Evidence:** `test_transcript_job_cannot_write_a_different_note` leases note A, submits that job/fence with note B's ID, and receives HTTP 200 rather than 409. `store_transcript` locks the requested note but checkpoints the independently supplied job. The artifact and legacy projection can consequently belong to different notes.

**Files:** `C:/Cursor/zargar-codex/.cache/em-worker-wiring-review/backend/zargar/technique/ingest.py` (`pending`, `store_transcript`) and `backend/zargar/technique/source_revisions.py` in the same checkout (`claim_for_note`, `checkpoint`).

**Correction:** validate the complete lease context before any write: note, revision, stage, owner, fence, expiry, and revision-bound input identity. Capture the source snapshot and claim atomically. Return 409 with no artifact, checkpoint, or legacy mutation for a mismatched context. Use distinct claim identities for concurrent worker/task instances; a role-wide owner string must not grant simultaneous attempts the same fence.

**Acceptance:** retain the supplied wrong-note case unchanged. Add two worker instances competing for one job and verify only the actual claimant can renew or complete it.

### WI-02 — P1: an old transcript suppresses replacement-media work

**Evidence:** `test_changed_video_still_needs_its_own_transcription_after_old_worker_finishes` changes the broadcast URL while transcription is leased. Completing the old job leaves no pending work for the replacement revision. `store_revision` updates text/images without refreshing media identity, and old completion changes the latest note's transcription status.

**Files:** the same `ingest.py` (`store_revision`, `pending`, `store_transcript`, extraction input selection); worker cache behavior in `C:/Cursor/zargar-codex/.cache/em-worker-wiring-review/tools/em_ingest.py` must use the same input identity.

**Correction:** derive media and transcription requirements from each accepted revision. Archive a valid old worker's output under its original revision, but update the current projection only if it still corresponds to the current inputs. Replacement media must remain eligible. Reuse transcripts only for verified identical media inputs; retain current caption/context when composing extraction inputs.

**Acceptance:** retain the replacement-video case unchanged. Also cover unchanged media with edited caption, changed media cache identity, and duplicate completion. The team's existing changed-source case currently accepts a transcribed latest note despite a changed URL; revise that expectation to the input-identity contract rather than weakening this new test.

### WI-03 — P1: superseded or deleted extraction reaches current planning

**Evidence:** both variants of `test_old_extraction_does_not_drive_the_current_board_after_source_changes` deliver an edit or tombstone during the model call. The old result then calls `technique.analyze`. `board_check` claims the current job only after planning work; it can finish the newer revision using the old extraction. These tests demonstrate planning invocation, not an actual submitted order.

**Files:** the same `ingest.py` (`extract`, `_extract_and_check`, `board_check`).

**Correction:** carry the original revision and authorized processing context through extraction and board processing. Claim/validate before side effects. Before current-board publication or arming, require that the source is still current and not tombstoned. Old outputs may remain historical artifacts, but must not update the current board or complete another revision's job. Never acquire whatever job is current at the end to legitimize work already performed.

**Acceptance:** keep both edit/delete cases unchanged. Add source changes at the board/planning wait boundary and confirm no stale arm or newer-job completion. Deletion must still preserve history and leave existing positions and ownership untouched.

### WI-04 — P1: lease conflicts mutate another worker's state

**Evidence:** `test_stale_worker_conflict_cannot_mark_another_workers_note_failed` gives another worker the live lease. `_extract_and_check` cannot claim, makes no model call, but its broad exception handler invokes `_fail`, which marks the note failed anyway.

**Files:** the same `ingest.py` (`_extract_and_check`, `_fail`).

**Correction:** treat `StaleWorker` as an ownership conflict with no projection mutation. Failure handling must use the original job/revision/lease context and conditionally update only authorized work. Do not freshly claim the current revision in an old attempt's exception handler. Preserve retry limits for actual owned failures.

**Acceptance:** retain the live-other-owner case unchanged; add an old task failing after a newer revision has succeeded and verify the newer success remains intact.

### WI-05 — P2: idempotent artifact reuse diverges from the displayed extraction

**Evidence:** `test_repeated_extraction_projection_has_a_matching_immutable_artifact` returns different model answers for identical inputs/configuration. The output key reuses the first immutable artifact while the legacy projection receives the second answer. The displayed extraction has no matching persisted artifact.

**Files:** the same `ingest.py` (`extract`) and `source_revisions.py` (artifact reuse/checkpoint result).

**Correction:** when reusing an output key, use the persisted artifact as the projection and downstream input. If a deliberate reprocessing policy permits another result, give it an explicit processing/configuration identity and persist it before publication. Do not silently discard the new payload while displaying it.

**Acceptance:** retain the varying-answer case unchanged; verify downstream board input references the artifact actually selected.

## Restart and integration scope

The HTTP-response failure path now treats health 500 as a live unhealthy engine, preserving pause/inventory/readiness checks. The before-inventory artifact, restoration receipt fields, and pre-stop import probe are appropriate corrections. Static inspection and PowerShell parsing support this bounded assessment; successful unhealthy-engine recovery was not exercised by the reviewer. A timeout without an HTTP response still follows the engine-absent path and is outside this specific 500 fix. Bounded watchdog retries for unchanged deterministic failures remain with the watchdog owner.

At inspection, runtime health reported `0.7.77` / `0394b144fc244b24db75ab322da17a07a27291c3`; fetched main was `561a859`, which is not an ancestor of the reviewed `9078bfd`. Integrate the then-current main before final review, preserving later Tips/scheduler/shutdown and shared release changes. These are observations at review time, not a claim about future branch state. Do not downgrade the running checkout to the reviewed tree.

## Return packet requested

1. Patch WI-01 through WI-05 in a focused follow-up, with a closure table linking each case to its correction. Keep source candidates order-free; do not expand into scenario production or strategy tuning in this patch.
2. Adopt the attached six cases unchanged into `backend/tests/test_codex_worker_revision_ownership.py`; preserve the additional acceptance contracts above.
3. Run sequentially via `scripts/test-codex.ps1` against `zargar_test_codex` in an exclusive window, then the existing source/wiring/reviewer and affected runner groups. Record exact combined SHA, commands, failures, skips and any collisions separately.
4. Return the pushed SHA and updated response/design documents for rereview before deploying the worker change.

The FIX-01 five-record non-live money repair retains its prior scoped GO and remains a separate unapplied human step. This review neither runs it nor broadens its scope. Profitability and the original low-trade/exit-performance questions remain unproven by these infrastructure tests.
