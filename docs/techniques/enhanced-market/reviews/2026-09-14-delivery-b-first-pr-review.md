# FC-01 and Delivery B first-PR review

**Verdict: hold the combined deployment and do not apply the new source backfill. The approved FIX-01 five-record money-projection repair remains a separate scoped GO on its normal non-live path. The Delivery B design direction is still accepted, but this first implementation needs the concrete boundary fixes below before closure.**

Reviewed `f2fb378b1774f72b489ec73ef3a6ac1cbc36cc67`, including FC-01/harness cleanup `99a7748` and upstream merge `751f7c8`. Source review and tests used `C:/Cursor/zargar-codex/.cache/em-delivery-b-review`. Primary checkout remains `C:/Cursor/zargar-codex`, branch `codex/zargar-development`; no production files, runtime settings, watchers, orders or live database records were changed by this review.

## What passed and what remains unverified

- A clean, sequential rerun of the supplied dispatch/quote, reconciliation, promotion and Delivery B cases returned **23 passed in 52.41 seconds**: the 13 reviewer cases and ten first-PR source cases.
- The reported 121 wider passes and the full reported 28-pass ingest/gateway/separation result were not independently repeated in full.
- The three `test_discord_gateway_modes.py` failures are **pre-existing**. They fail with the same missing `_on_message` attribute on this head and on the unchanged main implementation. The relevant gateway/test files are identical between the original baseline and current main. Their channel-mode assertions do not run, so these failures should be ported to the envelope API by the owning desk, not called a green functional mode test.
- **Fifteen new boundary cases reproduce failures**, grouped below. They use real isolated PostgreSQL/API/OrderManager where needed and fake external HTTP/executor calls. They are not fifteen observed live incidents.
- The first broad review test attempt was aborted after another task started tests against the same disposable database. Only this review's identified test process was stopped. The 23-pass result above is the clean rerun; the interrupted attempt is not counted. Serialize EM/Tips/Team2 use of `zargar_test_codex`, even across different worktrees.
- One gateway test initially lacked a stub for the existing Tip edit HTTP call. The stub was added, then the test reached and failed its intended EM-routing assertion. That setup error is not counted as a product finding.

The old widened-NBBO test now passes. The pure quality hook, single-path repair implementation, additive tables, source-plus-job transaction, artifact-plus-checkpoint transaction, legacy unknown availability and ordinary scenario arm/restore refusal are useful, verified progress.

## FC-02 — P1: losing current quote evidence still permits entry

`backend/zargar/execution/entry_quality.py:25-27` explicitly falls back to captured contract warnings when the current quote is absent or delayed. A clean old warning list returns an allow decision.

The two new actual-dispatch cases first allow the real RiskGate to pass on a valid OPRA quote, then change the cache during the actual OrderManager `SUBMITTED` await:

1. Remove the current quote entirely.
2. Replace it with a chain quote whose source timestamp is 15 minutes old, even though its local receipt timestamp is fresh.

Both still call the recording executor. They should produce a known final risk refusal with zero executor calls. These cases isolate loss of current executable evidence; they do not change the ask, quantity or day budget.

**Correction:** for an option entry requiring current quote evidence, absence or a delayed replacement is a refusal/defer condition. Captured warning text may explain a research result, but it cannot substitute for current entry evidence after RiskGate's earlier observation is invalidated. Keep the synchronous final hook, current budget check, retry forwarding and reduce-only exemptions.

Also use the applicable **entry** freshness requirement. The new final hook reads `execution.premium_mark_max_age_seconds` (default 90), while RiskGate's entry quote age is `risk.stale_quote_seconds` (default 10). An exit-mark age must not silently weaken the final entry policy. Validate timestamps and quote values as executable evidence rather than treating missing age as fresh. The two reproduced blockers here are missing and delayed current quotes; the differing age limits are an additional code-confirmed policy mismatch to resolve in the same predicate.

**Tests:** [test_fc01_dispatch_source_loss.py](fc01-delivery-b-regressions/test_fc01_dispatch_source_loss.py), two failures. Retain the previous narrow/wide, budget timing and protective-exit controls. Update the new pure-function test that currently blesses the missing/chain fallback to the agreed entry contract; keeping an unsafe expectation green is not acceptance.

## B-01 — P1: the gateway's real update envelope never selects EM delivery

The new `_process_envelope` branch requires `kind == update` and `env.em`. However, `_enqueue` still sets `em = bool(em_entry) and kind == create` at `tools/discord_gateway.py:920`. An actual queued EM-channel edit therefore cannot enter the new forwarding branch.

The new test drives `_enqueue` and `_process_envelope`, not the obsolete `_on_message` helper. It proves that the update reaches the queue but `_em_forward` is never called. This is distinct from the three acknowledged pre-existing tests.

A second real-envelope test shows that `_em_forward` writes `gatewaySeq = self._seq` at worker time. Two receipts captured when the gateway sequence is 40 and 41 are both forwarded as 99 after more frames arrive. The ordering key is no longer the receipt's key.

**Correction:** mark applicable updates as EM deliveries in the persisted envelope and carry their original receipt sequence/ordering metadata through spool, retry and forwarding. Preserve independent destination acknowledgements. Route an EM-only channel to EM, and a shared channel to its explicitly configured destinations; do not assume the Tip update branch accounts for EM. Test the actual envelope-to-API path, including partial payloads and failure/retry, rather than testing `_em_forward` in isolation.

**Tests:** [test_em_edit_gateway_boundary.py](fc01-delivery-b-regressions/test_em_edit_gateway_boundary.py), two failures: zero EM forwarding, and `[99, 99]` instead of `[40, 41]`.

## B-02 — P1: API field defaults break partial-update semantics

`IngestMessageBody.text` is still `str = ""` in `api/routes_technique.py`, whereas the intended update contract uses absence/None to mean “keep the prior value.” The endpoint passes `model_dump()` to the revision service.

Actual FastAPI tests show:

- An images-only update omitting text turns the saved text into an empty string.
- An update with `text: null`—the gateway's representation of absent content—is rejected with HTTP 422.

**Correction:** preserve field presence through the HTTP DTO, gateway, service and ledger. For updates, omitted/null text means unchanged; explicit empty text means clear. Normalize create defaults separately. Apply the same distinction to images, embedded content and author/source metadata where relevant. Do not declare safe partial merge based only on a direct call to `record_delivery` that bypasses the actual request model.

**Tests:** the omitted and null parameterizations in [test_source_ordering_and_jobs.py](fc01-delivery-b-regressions/test_source_ordering_and_jobs.py).

## B-03 — P1: accepted ordering metadata can move backward

Three persisted-source cases fail:

1. Equal `editedAt` values do not use `gatewaySeq` as the tie-break when an edit timestamp is present. A lower sequence replaces the newer accepted value.
2. A deletion without an edit timestamp lowers the effective watermark to original publication time. A delayed older edit can then resurrect it.
3. A newer same-content delivery is classified as redelivery without retaining its newer ordering metadata. An older, different-content edit can subsequently be accepted.

**Correction:** implement one explicit comparison key with defined missing-time, sequence and connection/replay semantics. Preserve the latest accepted ordering observation independently from the immutable content revision. A newer identical state need not create another content revision, but its ordering receipt/watermark must not be lost. Tombstones retain sufficient ordering authority to reject earlier content; restoration must be an appropriately newer source event, not an accidental stale edit.

Keep `A → B → A` as three distinct accepted states when actually ordered that way. Unknown event order must be handled explicitly rather than invented from worker execution time.

**Tests:** equal-timestamp ordering, deletion watermark and same-content watermark cases in the source/jobs test file.

## B-04 — P1/P2: leased work can starve ready jobs; expired workers can checkpoint

`resume_unfinished` applies its row limit before excluding live leases/backoff rows. With limit one, the oldest leased job is repeatedly selected and skipped while a later eligible job is never claimed. The new ready-job test returns no work instead of the available second job.

`checkpoint` checks fence equality but not a current, unexpired lease. The new test lets a one-second lease expire before any replacement worker claims it; the original worker can still commit instead of receiving `FenceMismatch`. This contradicts the module's stated expired-worker policy.

**Correction:** select eligible jobs before applying the limit, using locking/skip-locked semantics as appropriate. Check a valid claimed/in-progress lease and the current fence under the checkpoint transaction. An unclaimed, expired or completed job must not accept a worker checkpoint merely because its integer token matches. Retain the already-correct artifact/checkpoint single-transaction behavior.

**Tests:** starvation and expired-lease cases in the source/jobs file. Add/retain positive renewal, fresh-owner, backoff and exactly-once output controls. This is within the promised recovery infrastructure, not a request to finish the deferred extraction worker.

## B-05 — P1: source-backfill apply does not enforce the reviewed snapshot

`tools/em_source_backfill.py` generates `planHash` but does not verify it. It compares only caption/image `contentHash` in an unlocked preflight, then later locks the note and copies its current contents and derived payloads.

The real PostgreSQL failures show:

- An invalid manifest digest is accepted and writes records.
- A changed transcript/extraction with an unchanged caption is copied under the reviewed manifest's old input hashes and stage/outcome assumptions.
- An edit after preflight but before row locking produces a new revision with current text/images and the old manifest content hash.

**Correction:** verify the manifest's own identity and bind every copied field/evidence value, including source identity/content, media reference, transcript/output hash, extraction hash and job disposition. Recheck the complete reviewed state under the note lock, inside the same transaction that creates revision/artifact/job records. Refuse changed evidence before inserting anything. Return an explicit refusal/error status from the CLI rather than reporting successful application when validation refused it.

The additive tables and one-transaction insert design are acceptable. Unknown legacy availability is correctly preserved; do not change it to `updated_at`. The problem is what the transaction is authorized to copy, not a need to rewrite original source rows.

**Tests:** [test_source_backfill_evidence_boundaries.py](fc01-delivery-b-regressions/test_source_backfill_evidence_boundaries.py), three failures, plus the independently written changed-artifact case in the source/jobs file. These overlap one requirement and are not four independent bugs. The existing successful apply/reapply case remains a positive control.

## Scope of Delivery B acceptance and the next PR

The design direction remains supported, and the first PR has a useful additive foundation. Do not close its two implementation contracts or deploy its active ingestion changes until B-01–05 are fixed.

The following disclosed limitations are **not added blockers to this scoped first PR**:

- Gateway deletion forwarding is still pending; direct API delete/tombstone semantics must nevertheless be correct now.
- Transcription and extraction still use legacy note columns. Wiring the actual workers through artifacts/checkpoints is the next PR; the current primitives must first preserve ordering and ownership correctly.
- No source-informed candidate producer or trading activation is built yet. The ordinary scenario-origin arm and restore refusal works for the implemented origin contract; no unproven retry bypass is alleged here. Preserve protective exits.

Keep the next wiring work separate from correcting the infrastructure. Its acceptance should use the real gateway/API/worker path and crash points, not only direct helper calls. Keep candidates order-free and retain the approved three-table/source-artifact-job separation.

## FIX-01 money-projection repair is a different operation

The cleaned `em_reconcile_fallback` has one production path; the test-only capability branches are removed. The real-session replacements preserve the old invariants, and the real PostgreSQL acceptance cases passed in the clean rerun.

The committed v4 money-repair manifest is identical to approved v3 in its items, hashes, corrected values, `falseHalts`, `liveRows` and `unresolved`; only `generatedAt` changes. Therefore the previous **scoped GO carries over to v4's five explicit non-live records**, using the normal row lock, current hash/ownership/ledger checks, without `--include-live` or automatic rearming. If current state has changed, the normal guard must refuse; do not force an old manifest through.

This is not approval to apply the separate **Delivery B source backfill**, which remains held under B-05. The provided manual money-repair command was not executed by this reviewer. Return correction receipts and persisted readback after the separately approved operation; it is not a deployment claim.

## Upstream, test scope and handoff

`origin/main` at `5188956` is included in the reviewed branch. Merge `751f7c8` retains the shared platform-rule sections; the earlier conflict is no longer an outstanding integration item on this head.

Record the three pre-existing gateway-mode test failures with their owning task and port them to the envelope interface without weakening their behavior assertions. They neither invalidate the scoped EM changes by themselves nor explain the new real-envelope EM-routing failure.

The first interrupted test run is excluded from evidence. The clean counts are 23 supplied checks passed; 15 newly written boundary cases failed across targeted runs; and the three legacy mode failures reproduced separately on both this head and unchanged main code. The reported larger groups remain team evidence. No full-suite or profitability sign-off is made.

Return two focused corrections: (1) final entry evidence must remain current through dispatch, including missing/delayed observations and the actual entry age policy; (2) B-01–05 source/gateway/recovery/backfill contracts. Keep the existing nominal controls and supplied new regressions. Update the status table to distinguish original fixes closed, first-PR boundaries open, and explicitly deferred next-PR wiring.

### Regression files and execution

- [Final source-loss dispatch](fc01-delivery-b-regressions/test_fc01_dispatch_source_loss.py): copy into `backend/tests/test_codex_fc01_source_loss.py`; imports the already adopted `dispatch_rig`.
- [Source ordering/API/jobs](fc01-delivery-b-regressions/test_source_ordering_and_jobs.py): standalone file with explicit disposable-database guard.
- [Source backfill](fc01-delivery-b-regressions/test_source_backfill_evidence_boundaries.py): copy into `backend/tests/test_codex_em_source_backfill.py` for the repository `fresh_db` fixture.
- [Actual gateway envelopes](fc01-delivery-b-regressions/test_em_edit_gateway_boundary.py): pure gateway/spool test, no database/network.

Run sequentially from the isolated checkout, with exclusive ownership of the disposable test database:

```powershell
./scripts/test-codex.ps1 tests/test_codex_fc01_source_loss.py -q --tb=short
./scripts/test-codex.ps1 C:/Cursor/zargar-codex/docs/techniques/enhanced-market/reviews/fc01-delivery-b-regressions/test_source_ordering_and_jobs.py -q --tb=short
./scripts/test-codex.ps1 tests/test_codex_em_source_backfill.py -q --tb=short
./scripts/test-codex.ps1 C:/Cursor/zargar-codex/docs/techniques/enhanced-market/reviews/fc01-delivery-b-regressions/test_em_edit_gateway_boundary.py -q --tb=short
```

All database writes belong to isolated synthetic test rows/tables in `zargar_test_codex`; no runtime source backfill or monetary correction was performed.
