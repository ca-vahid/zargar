# a55bced review and release handoff

**The previous EM corrections are accepted on source inspection and the team's reported passing cases. Do not deploy `a55bced` directly over the running checkout yet: preserve the already-present Team2 F126 correction and obtain a clean integrated test run. No new trading-policy blocker was found in this patch.**

Reviewed source: `a55bced0958f3b19344ae22b9c5c079e15034a72`, isolated in `C:/Cursor/zargar-codex/.cache/em-delivery-b-followup`. Primary workspace remains `C:/Cursor/zargar-codex`, branch `codex/zargar-development`. The four newly adopted reviewer files are text-identical to the supplied originals after newline normalization.

## Acceptance by finding

| Finding | Review conclusion |
|---|---|
| FC-02 | Captured warnings no longer admit an option entry. Missing quote is refused; configured real-time sourcing rejects delayed chain evidence; the current entry age policy replaces the exit-mark age; missing timestamps are refused. These are the requested semantics. |
| B-01 | EM update envelopes now select EM delivery and preserve the receipt sequence. EM-only edits return before the Tips path. The previous routing and worker-sequence defects are corrected. |
| B-02 | The HTTP text field is optional; omitted/null update text preserves existing content, explicit empty string clears, and create normalization is separate. |
| B-03 | The original timestamp-tie, tombstone and identical-content watermark cases are addressed. One additional conservative-rejection edge remains below as P2 follow-up. |
| B-04 | Eligibility precedes the limit with skip-locked; checkpoint validates claim state, lease owner, unexpired lease and current fence. |
| B-05 | Manifest digest and complete source/artifact evidence are checked before work and rebuilt under the row lock in the same apply transaction. Refusal rolls back and the CLI exits 2. |

The approved design boundaries remain: order-free candidates; no new Practice book; source observations, artifacts and jobs have separate mutability; unknown historical availability stays unknown. Gateway deletion forwarding and actual transcription/extraction checkpoint wiring remain the next PR, as already disclosed.

## What I did and did not verify independently

The source diff and original test adoption were independently checked. The database-independent entry-quality checks passed. A separate pure watermark control passed and the new P2 case failed as described below: **9 passed / 1 failed** in that pure-function group, including eight existing entry-quality cases.

**I do not claim a clean independent 28-case database result.** Multiple attempted reruns were invalidated by another Codex task starting tests against the same `zargar_test_codex` database. The other branch creates an `execution_evidence` table that is not in this EM revision's metadata; subsequent fixture cleanup fails on its foreign key, and concurrent DDL also produced a deadlock. These are test-environment collisions, not evidence that the EM fixes failed.

Only this review's identified processes were candidates for stopping; no Cartel/Team2 process or runtime was stopped. Disposable-schema resets were restricted to `zargar_test_codex` and attempted only after verifying no other client at that instant. A new run subsequently started again, so no collision-affected run is counted as valid suite evidence. The last short attempt reached 12 passes and three fixture errors; it is not a clean 15-case result.

The team's **15/28/67/121** passing groups remain supplied evidence. Their five historical skips and three previously established gateway-mode failures must remain labeled separately. Do not report my interrupted attempts as additional green suites or new product regressions.

Before release, arrange one actual exclusive test window for the combined tree. A shared wrapper lock/reservation would avoid checking for idle processes and then racing a newly started review. A separate disposable EM database requires the user's explicit exception to the current AGENTS.md database restriction; none has been used by this review.

## Release integration: preserve Team2 F126

Current `origin/main` is included in `a55bced`, so the team's main-merge statement is correct. However, the running checkout's local branch at `b1da621` also contains **`260fbc089379d5ac03f119237a2be588b503d966`**, which is not an ancestor of `a55bced`.

That commit adds `"planFor": ap.plan_for` to `Team2Runner._score_execution` in `backend/zargar/techniques/team2/runner.py` and asserts it in `backend/tests/test_team2_close.py`. It fixes the close-event contract failure and accompanies the v0.7.72 release metadata. The observed health endpoint reports v0.7.72; it does not yet attest the reviewed EM build.

**Required release step:** preserve/merge the F126 implementation and regression, reconcile version/changelog metadata while retaining EM's launch-bound build identity, and return the exact combined commit. Do not replace the running checkout wholesale with the EM branch or regress the Team2 scorecard. This is an integration requirement, not another EM strategy change.

Run the reviewer groups and `test_team2_close.py` on that combined tree in an exclusive test window. Then use the established readiness/restart/restoration procedure and return the actual build SHA, effective settings and restoration evidence. This reviewer has not deployed anything.

## P2 follow-up: preserve a real timestamp/sequence pair

`source_revisions._advance_watermark` currently takes the maximum timestamp and maximum sequence independently. It can combine values from different accepted events.

Pure production-function reproduction:

1. Existing watermark: `(13:00, sequence 100)`.
2. A newer event arrives at `(13:05, sequence 5)`, for example after a gateway sequence reset. `_compare_order` correctly accepts it because its source time is newer.
3. `_advance_watermark` stores `(13:05, sequence 100)` rather than the accepted pair.
4. A subsequent `(13:05, sequence 6)` update is incorrectly called older and discarded.

This is a conservative source exclusion, not an unauthorized entry or overwrite of a newer source. It does not reopen the old trading-dispatch blocker. Carry it into the next source/worker wiring PR, preferably before relying on completeness across gateway restarts.

When accepting a newer event time, retain the sequence associated with that event, rather than carrying the maximum from an older event. Specify gateway connection/sequence-reset semantics and preserve receipt metadata. Keep the existing tombstone and same-content cases green.

The [pure regression and control](a55bced-regressions/test_source_watermark_pair.py) require no database or network. The original failing requirement has not been weakened; this is an explicitly scoped additional follow-up.

## Backfill and money-record decisions

**Source backfill:** the implementation now addresses the previously reported B-05 snapshot/locking failures on inspection. Generate a fresh dry-run manifest from the intended deployed schema/version and return its scope, digest and artifact counts before applying it. Keep legacy availability unknown, preserve original notes, retain the normal locked recheck, and report the resulting revision/artifact/job counts and refusal status. Do not reuse an older manifest with the prior weaker evidence definition.

**FIX-01 v4 money repair:** its prior five-record, default non-live scoped GO is unchanged. Use the approved manifest with normal current hash/ownership/ledger checks; no `--include-live`, automatic rearm, cash rewrite or execution-history mutation. The code review did not run the supplied apply command.

These are different operations. Acceptance of the monetary correction is not evidence that the source backfill or the new release has been applied.

## Next development work

Proceed with the scoped next PR for gateway deletions and wiring actual transcription/extraction workers through immutable artifacts and fenced checkpoints. Keep candidate orders and strategy activation off. Include:

- Source ordering and partial-update behavior through the actual gateway/API path, including the sequence-reset P2 above.
- Durable claim → output → checkpoint behavior, retries, crash recovery and stale-worker refusal in the real worker path.
- Correct linkage between source revision, media/transcript input and extraction output, with prospective availability timestamps.
- Tombstones/supersession that preserve history and keep existing managed positions under their original exit owner.

No additional X research or broad parameter retuning is requested for these implementation steps. Quantity-dependent R:R reporting, wider exit integration and later strategy measurement remain separately tracked work.

## Handoff summary

| Item | Decision |
|---|---|
| Previously reported FC-02/B-01–05 corrections | Accepted on code review and supplied tests, with independent database rerun limitation disclosed |
| Direct deployment of `a55bced` over current runtime checkout | Not yet; preserve F126 and validate the combined build |
| Source backfill code | Ready for a fresh reviewed dry run; no application performed |
| FIX-01 v4 explicit non-live correction | Prior scoped GO unchanged |
| Next worker/deletion wiring PR | Proceed, keeping research/order-free scope |
| Watermark sequence-reset edge | P2 follow-up; one pure failure plus passing control supplied |

No runtime state, production database data, trading settings or production source was changed by the reviewer. Review documentation and one pure regression file were added; the shared disposable test schema was reset during attempted isolated verification, with collisions and invalidated results disclosed above.
