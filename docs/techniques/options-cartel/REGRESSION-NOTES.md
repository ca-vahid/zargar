# Full-backend verification notes — 2026-09-07

Run: `scripts/test-codex.ps1 -q`, output in `.cache/cartel-full-backend.log`.
Only zargar_test_codex on loopback 5433 is used. No simultaneous test run or
frontend build was started. Backend code stayed unchanged during this run.

## Stale transaction intervention

Progress paused at 70%. PostgreSQL showed backend 94890 waiting to drop
`technique_armed`, blocked by backend 94887, idle in transaction for more than
four minutes after a read of armed/paused plans. Both connections were in
zargar_test_codex; the test Python process was still live.

The read query matches `PlanRunner.restore`. Inspection found that the shared
TechniqueService launches its restore coroutine as an untracked startup task;
its stop method does not await that task. This is a plausible lifecycle cause,
not yet proven by a dedicated reproducer. Cartel's own repository uses a
different active-status query.

Backend 94887 was terminated only after an SQL guard rechecked its database,
idle transaction age, query, and exact blocking relationship to the waiting
DROP. No runtime connection, other agent database, or Python process was stopped.
The full run continued using the same process. Its eventual result must disclose
this intervention and cannot be called an uninterrupted clean full-suite pass.

## Final result

The same run finished with **1,024 passed, 2 failed, 5 warnings in 1,478.92
seconds**. Both assertion failures match the prior documented baseline:

- `test_daily_loss.py::test_traded_portfolio_still_halts` expects a global halt,
  while the current default halt scope is portfolio.
- `test_platform_phase3.py::test_every_journaled_kind_has_a_contract` reports the
  missing `TechniqueLossHalt` event contract.

The older chart-PNG endpoint failure did not recur. Four warnings concern short
test HMAC keys; one warns of a non-checked-in asyncpg connection during a technique
arming test. This supports investigating shared test/service cleanup, but does
not by itself prove the precise source of the stale transaction.

No additional assertion failures were observed. This is not an all-green or
uninterrupted full-suite result, and it does not validate broker rollout or
calibrated strategy performance. The test process is terminal; the disposable
test database is no longer reserved by this run.

## Baseline assertion follow-up

The missing TechniqueLossHalt contract is now registered against the actual
existing runner payload. The stale daily-loss test now verifies both portfolio
and global settings, including unaffected unrelated books under portfolio scope.
No production halt policy, threshold or technique rule changed. The complete
daily-loss and platform-phase3 selection passed **18 tests in 31.62 seconds**;
scoped Ruff passed. This addresses the two observed assertion failures, but a
new full-suite run has not yet verified the combined tree without intervention.
The startup-task/connection cleanup issue remains separate.

## Lifecycle reproducer and correction

`test_technique_lifecycle.py` held an armed-plan read transaction in the startup
restore task, then called TechniqueService.stop. It failed on the previous code:
shutdown returned before the transaction was released. The test explicitly
cleaned up its held task so it did not contaminate subsequent tests.

The service now retains startup task handles and cancels/awaits its research,
sheet, restore and orphan-sweep tasks before stopping the armer and closing
clients. No trading rules or thresholds changed. The reproducer now passes and
acquires an exclusive table lock after shutdown. The lifecycle, technique API
and technique arming selection passed **46 tests in 143.81 seconds**, without
database intervention. A new full-suite run is still needed to verify the entire
combined tree; the historical full-run intervention is not erased by this fix.

## Fresh combined-tree rerun

A new sequential `scripts/test-codex.ps1 -q` run completed, recorded in
`.cache/cartel-full-backend-final.log`. Backend code and frontend build assets
were held unchanged during it. Only isolated preview read/research actions and
mobile rendering checks use zargar_dev_codex; tests remain in zargar_test_codex.
The result was **1,037 passed, 4 warnings in 1,136.55 seconds**, with no database
intervention. No matching pytest process remains. All four warnings concern
short HMAC keys deliberately supplied by auth tests; the prior connection-cleanup
warning did not recur. This is a passing full-backend run of the combined tree.
It does not establish source-example calibration, real-broker execution, or the
completion of the other method/data/operational requirements.

## Saved capitalization evidence acceptance

After the 1,037-test full run, capitalization capture and per-symbol scan evidence
were added. Focused suites passed (79 tests for candidate/screen/collection/API;
41 for fundamentals/scan tasks/recovery/API after scan integration). These do not
replace a full regression on the latest tree. Frontend typecheck/build passed.

Browser acceptance in the isolated sim preview captured MU as
`f5141529146b4fb8ba216a8442d0fc78`, with observation time
2026-09-07T15:08:52.587Z and provider price time 2026-09-04T20:00:01Z.
Candidate analysis passed capitalization while leaving missing industry rank
unknown. A fresh page explicitly selected the saved capture; scan
`e14a1f669188432dbb94b3ebad503647` persisted that same ID for MU and completed
watch-only with child analysis `81a97953abbf4538975702d9317dd5b1`.
No plan was armed and no order was submitted. Automated industry mapping,
universe collection, full regression and filled-trade acceptance remain open.

## Membership browser acceptance and current regression

The membership desk control was verified in Chrome against the isolated sim
preview. MU capture `b8c3192a13d443ec93a364e5c216269d` observed at
2026-09-07T15:14:13.938Z confirmed NASDAQ:MU in Semiconductors and disabled manual
industry editing. Scan `418cb0ebef7e4b6f81ea934b6c573f7d` persisted this membership
ID together with capitalization capture `f5141529146b4fb8ba216a8442d0fc78`; child
analysis `13615623a5fe4fd0836a23171a5525f5` completed watch-only. No performance
ranks were inferred from membership. No arm or order action was taken.

A new full sequential backend run is now using
`.cache/cartel-full-backend-evidence.log`; do not treat it as passed until its
terminal result is recorded. Code and frontend assets are held unchanged during
this run. The earlier 1,037-test result predates the evidence integrations.

Read-only collection investigation: the raw HTTP industry overview returned 100
rows, whereas the fully loaded browser previously displayed 129. It exposed
Overview columns, without explicit 1W/1M values or a source-data timestamp.
Therefore raw overview HTML is not a complete performance snapshot and must not
be fed to rank eligibility as one.

Mobile follow-up: ten Desk/History route-device combinations passed using the
saved membership/capitalization scan. The iPhone SE History screenshot was
visually reviewed; the scan summary, missing-rank notice and Review MU button
fit the viewport. This does not cover the expanded membership form on mobile.
The backend regression remains live; a read-only test-database check observed
fresh table creation with no waiting lock at the observation time.

Complete real-source import acceptance: Chrome selected TradingView Performance,
clicked Load More and read 129 unique industry rows with both percentage cells
present. The application import saved `2020893c45514751b8d4af4e69d5cc08` at
2026-09-07T15:18Z. Source data time remained null; all 129 rows correctly retained
unknown rank eligibility. The Semiconductors row preserved 1W 1.65 and 1M 2.28.
The full record is in `.cache/options-cartel/industry-complete-browser-capture.json`,
with input hash `20ae7409714d37614fca4fdca49e34ba180b9fc24a01872d75657808825d0650`.
This proves complete import/rendering, not automated capture or freshness.
The separate full backend regression has logged progress through 13% and remains
active; no final total is available yet.

## Current evidence-integration full regression completed

`scripts/test-codex.ps1 -q` completed with exit code 0:
**1,073 passed, 4 warnings in 1,319.05 seconds (21:59)**.
Log: `.cache/cartel-full-backend-evidence.log`. No database intervention or
process restart was needed. The four warnings concern deliberately short HMAC
keys in auth test fixtures. Code and built frontend assets stayed unchanged.

Afterward, a joined API/SimExecutor option-campaign acceptance test was added and
passed individually (4.63 seconds). It checks entry, target trim, manager/runner
restore, duplicate target suppression, stop exit, exact order quantities, P&L and
API convergence to zero open positions. An early fixture used a stale option quote;
its timestamp was corrected. An immediate API assertion raced asynchronous fill
projections and was replaced with a bounded wait for their actual closed state.
Neither required a production-code change. Related focused regression is running.

The related runtime/controller/position-adapter suite completed with exit code 0:
**39 passed in 89.22 seconds**. This includes the new joined option campaign.
Scoped Ruff also passed. The 1,073-test full result precedes this test-only addition.

Saved membership selector follow-up: matching verified captures can now be
selected after reopening the page. The expanded evidence form loaded MU capture
`b8c3192a13d443ec93a364e5c216269d` across all five mobile profiles with zero audit
failures. The iPhone SE screenshot was visually reviewed. This was a UI-only
change; it does not replace the separate full-backend and joined-campaign results.

Batch capitalization UI acceptance: captured MU, HOOD and invalid ZZQNOTREAL.
The two valid captures were selected separately; the invalid symbol displayed a
provider error. Subsequent scan `ecc4547befdb4bf19d2559e64c631131` persisted MU
capture `cc0b8d38a479429f9e4f39aa6a0c4d1f` and HOOD capture
`86be99c30ad44916a9d6539d19abb8c8`, returning two watch-only rows and one data error.
All five Desk mobile profiles passed. No arm/order action was taken.

Option valuation UI acceptance: a synthetic underlying replay generated by the
existing evaluator was saved as `0c08d0ce4d794860a53f748eea1bc680`, without orders,
portfolio changes or another engine startup. Chrome imported explicitly synthetic
USD quotes and saved valuation `08a9c1b3dd844aac8c686055f96ea5cf`: four contracts
at ask 1.20, one exit at bid 1.80 and three at bid 1.40, with 0.50 per-contract
fees. The displayed net result was 116.00, fees 4.00 and return on debit 24.07%.
This is deterministic UI acceptance evidence, not a claim about actual returns.
Expanded input and result views passed ten mobile route/device checks. The
result screenshot was visually checked on iPhone SE. Build passed; backend
valuation/replay tests previously passed 17 cases.

Quote recorder integration: 19 recorder/runtime tests passed, followed by six
focused checks including the runtime quote-watch hook. The hook captured the
selected option quote and created no order. Scoped lint and frontend build passed.
The new table was provisioned only in zargar_dev_codex after empty execution-state
checks. Chrome saved/refreshed the disabled recording setting; the expanded panel
passed all five mobile profiles and the iPhone SE screenshot was inspected.
Recording remains off in the preview. These changes postdate the 1,073-test full
regression and need inclusion in the next combined verification checkpoint.

Stored-quote valuation integration: 21 observation/valuation tests passed. The
loader preserves observation IDs, scopes data to the replay's own plan/contract,
and records incomplete results for empty windows. New unusable observations
block fallback to prior favorable quotes. Browser verification saved incomplete
valuation `e921046e0d7745a39ef0b7c1d7959ba9` from the existing missing-data replay,
without inventing returns. The updated quote controls passed all five mobile
profiles. Build and scoped lint passed. Recording remains disabled in the preview.

Saved evidence detail views now render capitalization amounts, provider versus
observation timestamps, industry suggestions, verified membership and source
links. Capture records are labeled Captured at rather than Market data as of.
Opening a history row does not silently select it for a scan. Both fundamentals
and membership views passed the five-device audit (ten combinations total); the
fundamentals view was visually inspected on iPhone SE. These are UI-only changes.

## Quote pipeline full regression completed

The current sequential `scripts/test-codex.ps1 -q` run completed with exit code 0:
**1,096 passed, 4 warnings in 1,253.93 seconds (20:53)**.
Log: `.cache/cartel-full-backend-quotes.log`. No process restart or database
intervention was needed. The four warnings concern short HMAC keys in auth
fixtures. Code and built frontend assets were held unchanged throughout the run.
This includes quote observations/recording, stored premium valuation and the
joined option campaign. It does not prove the remaining research, data-provider,
full simulation, operational or deployment requirements.

Final wrap-up verification: the descriptive industry-rank change passed 25
industry/API tests. The isolated preview showed Semiconductors at captured weekly
rank 26 in the 129-industry snapshot while eligibility remained unknown and the
provider timestamp remained null. All five mobile profiles passed. The production
build passed, and release notes preserve the previous 0.7.1 entry beneath the new
0.7.2 Options Cartel entry. Recording is off; pre-refresh checks confirmed zero
orders, open positions, active arms and running scans. Local env/cache/dependency
paths are ignored and excluded from the staged release checkpoint.
