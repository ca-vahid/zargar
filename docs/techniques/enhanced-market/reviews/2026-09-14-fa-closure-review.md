# FA closure review at b542ec0

**Decisions:** start the scoped first Delivery B PR; the reviewed v3 five-record reconciliation set is technically accepted for the default non-live guarded path; hold deployment of the combined trading change for one remaining final-quote validation failure. Resolve the newly observed upstream documentation conflict before integration.

Reviewed head: `b542ec0812ced40595b2bf1a875af21f088dd8cc`, including `ae6d315` and guard-scoping/Tip forwarding fix `1afc713`. Isolated checkout: `C:/Cursor/zargar-codex/.cache/em-delivery-a-final`. Primary workspace and branch remain `C:/Cursor/zargar-codex` / `codex/zargar-development`; existing work was preserved.

## Verified results and accepted corrections

Independently ran the prior reviewer group and all twelve real-database/dispatch/promotion cases together: **67 passed in 16.09 seconds**. All eight adopted files match the original text after newline normalization; the promotion file has only the declared package-relative sibling import adjustment.

The separately reported **82** Tip/arming passes and **98** broader passes were not rerun here. Their disclosure of the two temporary wider-suite regressions is useful; both fixes were inspected rather than assuming a green aggregate count explains them.

Accepted within the demonstrated scope:

- Final day-budget enforcement now survives the last awaited OrderManager transition. The synchronous guard is forwarded through the generic retry path, collar retry and Tip override. Restricting this particular day-budget predicate to option entries preserves the existing F33 scope; it is not a new claim that shares have an equivalent pre-entry budget control.
- The actual PostgreSQL repair path locks the plan row and commits its state and all correction Event rows in one transaction. Real rollback, retry, grouped-update and ownership tests pass. Publication happens after commit.
- Ledger prices and entry/exit commissions now drive the reproduced corrections. The wrong-technique refusal and corrupted-projection cases pass.
- The demonstrated 3R/4R saved-definition promotion cases pass. Missing source-data/timeframe/process provenance remains a separately limited measurement claim, discussed below.
- Build identity is captured at import rather than lazily on the first health call. Full SHA and tracked-file dirty status resolve the earlier checkout-movement objection. Deployment-provided metadata and untracked-file limits should remain disclosed.
- Earlier multiplier, target-rung, critic restoration/disposition and forward-quote-order cases remain green.

All tests ran sequentially through `scripts/test-codex.ps1`, using only `zargar_test_codex` at loopback port 5433. The dispatch tests use real OrderManager/RiskGate/persistence with a recording executor, not a broker connection. The review did not deploy, apply a live manifest, alter a watcher or start another trading engine.

## Remaining deployment blocker: current NBBO is not checked at final dispatch

**FC-01 — P1, within the existing FA-01 scope.** `backend/zargar/execution/planrunner.py::_entry_guard` checks `contract["warnings"]` at its final synchronous boundary. This is the captured contract dictionary from the earlier refresh; it does not read the current quote cache and recompute the applicable quote-quality verdict.

The single new [regression](delivery-a-final-regressions/test_em_final_dispatch_quote.py) reuses the already validated actual OrderManager fixture:

1. Initial NBBO is **bid 2.95 / ask 3.00**, a roughly 1.68% spread. One contract has $150 modeled premium-stop risk against $160 remaining daily allowance.
2. The actual RiskGate passes. OrderManager awaits and completes its `SUBMITTED` transition.
3. During that awaited boundary, a new OPRA observation replaces the quote-cache entry with **bid 2.50 / ask 3.00**. The ask, quantity and day allowance are unchanged. The current spread is roughly **18.18%**, above EM's 10% policy.
4. The captured contract still has no wide-spread warning. The final guard permits the executor call.

**Result: 1 failed in 2.44 seconds**, at the zero-executor assertion. The test verifies that RiskGate passed, the submitted transition was reached and the current cache actually contains the wide spread. This is a current-market-data variant of the same final-dispatch requirement, not a change in strategy thresholds or a claimed live financial loss.

**Required patch:** have the final synchronous guard read the latest cached quote for the actual order symbol and apply the applicable technique's pure validation policy, including current spread and valid/fresh source evidence. Do not derive current eligibility solely from the earlier mutable warning list. Keep method-specific policy behind the appropriate hook rather than reintroducing an EM import into the generic runner. Preserve the already working current-budget check and retry forwarding.

The guard must return or refuse without I/O and without mutating quantity/limit after the persisted Order has been constructed. If current evidence requires a new price, quantity or asynchronous refresh, reject/defer the current attempt and create a separately validated attempt as appropriate. Preserve reduce-only protective exits.

**Closure:** the existing 67-case group stays green and this new case ends in a known `REJECTED_RISK`/`beforeSubmitRejected` record with no executor call. Include the unchanged narrow-spread allow control and the existing budget timing cases. No additional broad strategy work is required to close FC-01.

## v3 reconciliation decision

**Scoped GO for `FIX-01-manifest-dryrun-v3-2026-09-14.json` on the default non-live path**, using the reviewed real-AsyncSession implementation and its apply-time lock/hash check. This approval is for those explicit five records, not arbitrary legacy manifests or `--include-live`.

Read-only evidence at this review's verification snapshot:

- All three affected plans are disarmed.
- USO and SWKS contribute four unfilled entries whose orders are `REJECTED_RISK`, with zero filled quantity and matching symbol, portfolio and EM ownership.
- HPQ has the three correctly owned executions: buy 100 at 34.77; sell 30 at 34.803; sell 70 at 34.6531. Fees are zero. Gross/net realized P&L for this specific record is **−7.193**.
- Zero correction events were observed; application is not claimed.
- Current state hashes match the reviewed v3 manifest:

| Plan | Hash |
|---|---|
| USO | `9d03592cf2f6e804` |
| SWKS | `6d45be2ad1d79b75` |
| HPQ | `ef17f95f1725c722` |

An initial external verification appeared to disagree because Windows pipe text was decoded with the wrong encoding. Explicit UTF-8 verification matched all three hashes. That false alarm was withdrawn; there is no stale-manifest finding on this evidence.

At application time, retain the normal guarded checks. If a row or ownership changes, stop/refuse and regenerate a reviewed manifest; do not bypass the comparison. Apply only the explicit v3 set, do not re-arm plans, do not modify cash/execution history, and return the correction receipts plus fresh persisted trade/aggregate reads. This repair operation is separate from trading-code deployment.

Still outside this scoped acceptance: live-owner/quiescence synchronization, manifests omitting ownership fields, generic halt conclusions beyond the labeled diagnostic, and proof of every repaired value solely from a replay receipt/multiplier. The current v3 items are explicitly owned and their ledger values were checked; do not generalize that to unrestricted tool input.

## Test-harness compatibility cleanup

The response discloses production branches that detect a minimal fake session and use projection arithmetic/separate journaling only to keep five old direct-function tests green. I prefer removing that alternate production behavior and migrating those five cases to equivalent real-session coverage.

Preserve the old files as historical reproductions and supply a coverage map. The actual PostgreSQL grouped round trip/retry covers tracked persistence, aggregates, multiple items and list replay; the actual transaction-failure cases cover receipt/state coupling. Retain their assertions and add any missing equivalent case. A changed test count with documented stronger coverage is acceptable; maintaining a count is not a reason to maintain a different repair algorithm for mocks.

This cleanup does not reverse the real-AsyncSession acceptance of the specific v3 records. It prevents future reliance on fake-session greens as production-path evidence.

## Delivery B: proceed

**GO to start the first scoped PR now**: the three tables, backfill dry-run tool, `resume_unfinished()` with fencing and the order-free boundary. The design now marks the old schema/backfill section superseded and records both first-PR implementation contracts:

1. Explicit source edit/event ordering and safe merging of partial/out-of-order deliveries.
2. Atomic source/job and artifact/checkpoint transitions, or deterministic idempotent recovery with stable output keys.

Keep this PR diagnostic/schema-only: no extraction-policy changes, Practice book creation, candidate orders or strategy activation. Demonstrate the migration/backfill and crash/recovery cases in the isolated test environment. The earlier branch-consumption, pending-order and quiescence requirements remain before future activation; they do not require more research before this PR begins.

Keep quantity-dependent R:R reporting and the wider FIX-02 exit integration cases explicitly open. Promotion now preserves the tested saved thresholds, but full reproduction with nondefault structural timeframes, saved bars/data snapshots and unknown process versions remains limited. Record that scope in FIX-10/measurement work rather than calling every kind of replay identity complete.

## Upstream and runtime observations

The remote desk tip was verified as `b542ec0` on `refs/heads/claude/zargar-stock-app-research-8mnqfh`; use that published ref or the exact SHA for subsequent retrieval. Since the team's snapshot, `origin/main` has advanced to `5188956`, adding Tips test/documentation work. Relative to the common ancestor, that change touches `backend/tests/test_tip_geometry_wiring.py`, `docs/PLATFORM-RULES.md` and two Tips documents.

A read-only `git merge-tree --write-tree b542ec0 origin/main` preview reports a content conflict in **`docs/PLATFORM-RULES.md`**. No branch or working file was merged by this review. The team should reconcile that file while preserving both desks' entries and include the current Tips fixture update; the old “no conflict work” status is no longer current.

The initial health request timed out. A later read returned **v0.7.72 without the new build field**. This does not attest deployment of the reviewed EM head. Do not infer that the corrected EM release is running from the version alone. After the quote fix and normal integration/readiness checks, return the actual launch-bound build identity, effective settings and restoration evidence.

## Reviewer return packet

Return the narrow FC-01 quote-cache guard patch and its passing regression, the merged upstream documentation resolution, and the scoped Delivery B first PR. If the separately approved v3 correction is applied, return its receipts and readback rather than a deployment claim. Keep `--include-live` unused.

New-case command after copying the supplied file to `backend/tests/test_codex_em_final_dispatch_quote.py`:

```powershell
./scripts/test-codex.ps1 tests/test_codex_em_final_dispatch_quote.py -q --tb=short
```

It imports `dispatch_rig` from the already adopted `tests/test_codex_em_final_dispatch_budget.py`. Both use the isolated repository fixture, no `Engine.start()`, and no network/real executor.

No full-suite or profitability sign-off is implied. The verdict closes demonstrated corrections, permits the bounded repair and next diagnostic work, and retains one specific deployment blocker.
