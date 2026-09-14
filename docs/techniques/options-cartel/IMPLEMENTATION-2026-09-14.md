# September 14 EOD implementation — v0.7.73

Implementation branch: `codex/cartel-eod-improvements` in
`C:/Cursor/zargar-codex/.cache/cartel-eod-20260914`, based on main `5188956`.
This release implements the operational/code portions of the eight-package EOD plan.
It does not change account budgets, risk percentages, entry thresholds or saved campaigns.

| Package | Delivery |
|---|---|
| C14-01 | Partial results resume successful research and retry failures; three bounded attempts per evening/pre-open window, durable next retry, original cutoff and new baseline revision identity. |
| C14-02 | Held-only ownership uses validated config.runId or a conservative unlinked identity. |
| C14-03 | Stale/delayed/unknown option quote fills are refused; the protective order remains working; exact evidence commits alongside executions. |
| C14-04 | Cross-process OS deployment mutex, reviewed target/clean-tree/build checks, guarded restart and receipt; Cartel added to restart inventory. |
| C14-05 | Source-callback/publication/consumer queue and handler timing plus event-loop lag; bounded async journal and authenticated status. Upstream exchange transit is not independently measurable. |
| C14-06 | Session/account read model reconciles FIFO lots/fees and campaign outcomes, carried positions, exclusions, durable attempts and historical accounts. UI clears old scope and discards stale responses. |
| C14-07 | Durable quote coverage distinguishes worker counters from archive evidence; held contracts are recorded even after an arm retires. Exact execution evidence supplements sampled quotes. |
| C14-08 | Provider identity is retained and incompatible prefixes are discarded; docs updated; FISV independently checked; prospective policy cohorts remain separate. |

## FISV source investigation

Read-only requests on September 14 verified:

- Yahoo daily history returns November 10, 11, 13 and 14, 2025, omitting November 12.
- Alpaca SIP raw provider-day history returns November 12 with close **64.38**;
  adjacent returned closes are November 11 **64.26** and November 13 **64.53**.
- Nasdaq technical notice DTN2025-32 confirms the FI-to-FISV transition on November 11.

The sources differ in session-volume/adjustment conventions. This release does not splice
Alpaca's one bar into Yahoo history, flip the native-daily setting, or invent a missing
session. That remains an explicit dataset-validation decision. The precise remaining
exclusion is visible; retries are bounded. No runtime histories or credentials were copied.

## Validation record

- Initial targeted preparation/pending/scan and pure quote regression: **10 passed**.
- Capacity/provider/adoption/recovery/quote observation checks: **36 passed**.
- EOD/API/engine/shared exit batch: **44 passed**, one new fixture failed before its portfolio
  was flushed; corrected the fixture's FK ordering without changing any accounting assertion.
- Corrected EOD/provider/preparation coverage/workspaces/recovery: **34 passed**.
- Expanded stale/future/crossed/delayed/source/receipt regression, exact evidence transaction,
  pending/preparation/ops/simulator/risk checks: **54 passed**.
- Windows PowerShell parsing, competing-process lock refusal and nested-owner restart lease:
  passed without touching the runtime or running restart.
- Production build and release metadata check passed. Four real-built-UI/synthetic-data
  desktop/phone light/dark cases passed: accounting, links, exclusions, scope reset,
  archive coverage and no trading writes. Screenshots inspected.

Groups overlap and later release validation is appended below. No full-platform suite or
profitability claim is implied. All database tests use zargar_test_codex, sequentially.

## Operating the release

Open Options Cartel → Plans → **Daily review · trades, costs and missed opportunities**.
Choose the session and account, then Load daily review. Closed campaigns and filled orders
are separate counts; net realized includes entry/exit commissions for the lots closed.
Open holdings require a source-qualified cutoff mark. Unknown legacy fill evidence remains
unknown. Expand exclusions, attempts and quote coverage for diagnostic details.

Preparation keeps its normal schedules. Compatible partial work recovers outside regular
hours; the morning window gets a fresh retry allowance even if evening retries exhausted.
Changed session/policy or invalidation does not reuse stale trade permission. Manual Resume
is available after reviewing exhausted errors. Do not arm alert-only duplicates.

For deployments, acquire `scripts/deployment-lock.ps1` before changing the runtime checkout.
`scripts/deploy.ps1 -TargetCommit <reviewed-full-commit> -Expect <version>` performs clean-tree,
fast-forward, build, source-identity and guarded restart checks under that owner. It must be
run from the authorized runtime checkout, never the isolated Codex test environment. A held
swing position is inventoried; pending execution and working guards remain in force.

Deployment and live validation are recorded separately after completion.


### Follow-up regression corrections

The broader 83-check run found an invalid telemetry-name argument added to the Cartel
runtime constructor; that edit was removed (CartelObserver already names the consumer).
Subsequent lifecycle checks required their historical simulated clock and explicit OPRA
source times to match their existing quote timestamps. Fixtures were updated to provide
valid evidence; stale/delayed rejection assertions remain strict. The new preparation fixture
now selects its Practice account explicitly rather than assuming only one simulated book.

For elevated task handoff, the deployment owner may leave a short-lived pending manifest
with the exact commit, version and artifact hash. Other builders refuse that pending handoff;
the restart task validates it under the OS mutex before touching the runtime. A verified
same-commit restart in the preceding five minutes is skipped unless explicitly forced.


The corrected runtime/EOD/source-evidence/telemetry/deployment/ops batch passed **41 tests**.
The final built UI passed the same four desktop/phone light/dark cases after the last UI
changes. A new real-DB quote-coverage fixture needed its referenced plan inserted first;
its FK setup was corrected without changing coverage/account-isolation assertions.

Final focused validation: **14 passed**, including the scheduled partial-resume path,
pre-open retry allowance, FIFO/fee attribution, real-DB quote coverage, timestamp-tied
attempt pagination, telemetry and Windows deployment ownership. The earlier provider/coverage
follow-up also passed **11 checks**. These groups overlap; no counts are summed as unique tests.
