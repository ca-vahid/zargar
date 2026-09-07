# Options Cartel — full delivery plan

Current delivery status: [DELIVERY-STATUS.md](DELIVERY-STATUS.md), updated
2026-09-07. Screening, plans, execution controls, durable management, campaign
replays, comparisons and selected-symbol scans now have implementations.
Older milestone notes below describe their original verification point; their
pending statements are superseded by the current status document.

Latest completed full regression: 1,096 backend tests passed including the
industry/fundamentals/membership integrations, quote pipeline and joined option
campaign, recorded in `.cache/cartel-full-backend-quotes.log`.
See EXECUTION-ACCEPTANCE.md and REGRESSION-NOTES.md for verification scope.
All tests use only zargar_test_codex.
Operational rollout verification remains a separate unfinished requirement.
All requirements below remain in scope; the active goal is not complete until
source coverage, method fidelity, full app integration, and verification are proven.

## 1. Research and specification

- [x] Read all 21 full archive-index texts; cross-version deltas and unresolved
  execution interpretations recorded in SOURCE-REVIEW.md. Additional X/media/
  video coverage is still pending. September video S24 has since been reviewed.
- [x] Add explicit source-supported opening-gap retest option to the entry
  kernel; legacy plans remain unchanged by default. Two new tests pass.
- [x] Inspect four additional source images: June scanner, January volume
  matrix/cloud style, June-2025 TSLA retest. Material screenshot/text conflict
  recorded in SOURCE-REVIEW.md (ADR 2% vs 3%; liquidity volume uses 10-day average).
- [x] Separate `june_2026_image` profile in rule schema, collector and UI:
  ADR >2%, ten completed-session average volume >500K. Existing June text and
  saved snapshots retain prior semantics. Six new screen tests and one collector
  test cover profile defaults, volume spikes/quiet days, warm-up and legacy restore.
  Browser exercised the profile on MU; five-device Desk/Method audit passed.
  Exit schedules remain independent and default to the June text schedule for this profile.

- [x] Locate/read supplied September thread and June strategy text.
- [x] Establish independent method docs and source ledger.
- [x] Read May, June, September strategy texts, January volume and trade examples,
  December strategy; inspect all eleven main-thread images; locate public ledger.
- [ ] Read relevant discovered educational threads, related account posts,
  replies, charts and linked videos; record access gaps and coverage honestly.
- [ ] Build an example corpus with entry, stop, options contract, exits,
  timestamps and source provenance, including failures rather than winners only.
- [ ] Resolve METHOD/TRADING-RULES questions from evidence, or explicitly
  identify implementation decisions and parameters for user review.
- [ ] Create a rule-to-source-to-code-to-test traceability matrix.

## 2. Engine fit and deterministic method

- [x] Independent `CartelRules` with May/June/September profiles, source references,
  rule snapshots and separately labeled engineering definitions.
- [x] Explicit session-dated daily input contract; completed-day/week filtering,
  holiday/half-day handling and conflicting/missing-bar validation.
- [x] SPY/QQQ agreement, bullish/bearish screens, source-dated market capitalization
  and industry rank inputs, ADR/ATR/EMA metrics, volume-sorted screening shortlist.
  These are screening candidates, not a claim that setup analysis or arming is complete.
- [x] Reviewable `CartelPlan`/`EntryPolicy` and one pure `read_entry` for observation
  and replay: 5/15/30m complete-candle confirmation, bullish/put direction mirrors,
  breakout/retest modes, snapshot volume baselines, invalidation, causal day-low/high
  or breakout-bar/preplanned stops, never-chase and stable signal IDs.
  This accepts prepared levels; automatic setup detection and runtime routing remain pending.
- [x] Measured weekly/daily setup candidates for base, flag, pennant, wedge,
  inside day, EMA pullback and breakout/retest, with aligned benchmark relative
  strength, volume dry-up and explicit engineering parameters. Historical
  source-example validation is still pending; labels are not calibrated models.
- [x] `prepare_plan` composes fresh screen/context, selected reviewed setup,
  historical or sourced manual targets and complete same-time volume medians.
  Missing targets block preparation; missing baselines remain visible and block
  the entry kernel. This is pure composition, not API persistence or live arming.
- [x] Pure `ExitCampaign`/`ExitState` with explicit source profiles: target quarters,
  daily EMA exits, ATR extension, confirmed-fill breakeven, stable exit identities,
  whole-lot allocation and pending-exit suppression. September fractions require
  an explicit reviewer choice. **Not yet wired to PositionManager**; its true-daily
  data and confirmed-fill adapter still need integration and chaos tests.

- [ ] Implement own rule schema/snapshots, market regime, theme/sector ranking,
  universe filters, weekly/daily setup analysis and focus-list selection.
- [ ] Establish data provider/history contracts, sufficient warm-up, timezone,
  completed daily/weekly bars and point-in-time inputs (no lookahead).
- [ ] Implement causal trigger/stop logic and repeatable decision traces for
  all documented setup families, including manual source-plan review where needed.
- [ ] Implement replay/outcomes/variant sweeps using the same rules as live.
- [ ] Assess shared PositionManager capability gaps: multi-step daily EMA exits,
  3xATR extension trim, first-trim breakeven, exact contract rounding, and
  option-price versus underlying-price accounting. Reuse generic mechanics;
  preserve all existing technique behaviors.

## 3. Runtime and research services

- [x] Entry settlement helper requests cancellation for partial fills or explicit
  cancellation, waits for persisted order reports (not optimistic cancel returns),
  adopts terminal fills once, and retires unfilled terminal orders. Cancellation
  requests are persisted/rate-limited; failures and unconfirmed partial exposure
  are explicit. **Pending partial exposure is reported, not yet automatically
  protected by a runtime guard; live entry activation remains disabled.**

- [x] Idempotent terminal-entry adoption helper: validates reserved-order
  identity, terminal status, actual whole-unit fills/prices and unallocated
  portfolio holdings; serializes allocation and uses deterministic managed ids.
  Retries rebind existing positions and cannot resurrect closed ones. Adapter
  adoption is published in memory only after durable save; persistence/journal
  failures propagate on the opt-in path. Working partial entries and late-fill
  reconciliation still require the runtime orchestrator; no arming API is enabled yet.

- [x] Routine automatic contract-selection API with explicit reviewed DTE range/
  target, target absolute delta, ask/spread limits and optional open-interest
  minimum. Structural chain shortlist is refreshed before eligibility/ranking;
  missing/stale Greek and quote observations never qualify. Reports search bounds
  (six nearest expiries and configured refresh cap), candidates and reasons;
  result is journaled and places no orders. UI and final fire-time selection
  integration remain pending.

- [x] Routine option preflight enforces absolute delta >=0.25 from S15, correct
  call/put sign, and an independently timestamped delta observation. Lower
  reviewed exceptions require a reason; missing/stale Greeks still block them.
  Shared snapshots retain per-field Greek observation times so quote or
  gamma-only refreshes cannot refresh old delta metadata. No order is submitted.

- [x] Controlled daily-history restoration in the Cartel adapter: validates
  symbol, completion, contiguous warm-up and latest required session; rejects
  conflicting candles, future data and history rewind; preserves fills, stops,
  pending orders and unrelated attention. Missed closes are persisted rather
  than booked as hypothetical fills. Provider scheduling and automatic catch-up
  execution remain unfinished; this method currently restores data only.

- [x] Opt-in Cartel position-policy adapter registered through the service.
  PositionManager remains the only order router; adapter receives minute bars and
  confirmed exit fills. It persists true daily aggregation and campaign accounting,
  moves breakeven only after fills, resizes share stops, and guards duplicate/stale
  bars. Missing data suppresses indicator exits with attention warnings while
  protective/target exits remain available. Unknown adapters retain basic protection.
  **Entry routing/adoption orchestration and missing-history recovery are not complete.**

- [x] Transactional `ArmRepository` for persisted arming state, single-consumer
  signal claims and write-ahead attempt tags. Competing repository instances
  serialize through PostgreSQL row locks; creation locks the owned plan row.
  Recovery binds only an exact unique order match; unknown/mismatched outcomes
  remain attention-required and cannot be blindly resubmitted. Disarm retains
  pending exposure as closing. This repository is not yet a running execution
  service or a public arming API; permissions, live trigger callbacks, confirmed
  fill adoption and managed exits still need the runtime adapter.

- [x] Shared-RiskGate execution preflight API for a reviewed Cartel plan:
  explicit vehicle/OCC selection, directional calls/puts, no share shorting,
  horizon/expiry checks, fresh two-sided prices, budget/risk sizing with current
  FX, overnight acknowledgement, account/auto permissions and phone protection.
  It journals the report and never creates an order. Actual trigger-time routing,
  partial-fill adoption, technique day-loss handling and the runtime runner remain pending.

- [x] `/api/options-cartel/collect` collects symbol + SPY/QQQ daily history and
  intraday volume inputs through the shared provider, using a scoped HTTP client.
  It persists provider coverage/warnings and source-dated supplied metadata.
  Missing fundamental/industry rankings stay unknown; an automatic metadata/
  ranking provider and full-universe scan orchestration remain unfinished.

- [x] Authenticated `/api/options-cartel` research API with real PostgreSQL
  persistence for analysis, reviewed plan, entry replay, run history/detail and
  append-only reviews. Each read/write checks technique ownership. Snapshots
  retain supplied inputs, source labels, parameters, exit campaign and parent links.
  No broker, scheduler or runner is started by these routes.

- [x] Register TechniqueInfo, own namespaced settings and enable/pause controls.
- [ ] Wire service/runner lifecycle, subscriptions, scheduler jobs, restore,
  night scan, focus lists, saved plans and preflight.
- [ ] Arm alert/proposal/auto with portfolio, budget/risk, contract selection,
  expiry/horizon and overnight acknowledgement where required.
- [ ] Route every execution through OrderManager/RiskGate and adopt fills into
  durable position management without competing exit owners.
- [ ] Persist identity on all runs/plans/orders/positions/events; register
  versioned event contracts; ensure shared Armed/health/restart guards see plans.
- [ ] Prove pause and all halt scopes block entries while exits remain available;
  cover duplicate bars, slow/partial fills, disarm, restart, expiration and gaps.

## 4. Complete app experience

- [x] Registry-backed Options Cartel sidebar destination, lazy-loaded page and
  `/techniques/options-cartel/{desk,plans,history,method}` routing. Research UI
  connects collection, screen/context checks, measured candidates, reviewed-plan
  creation with entry/exit choices, saved history and append-only reviews.
  Source data and watch-only conditions are visible. This is not the complete
  execution UI: arming, managed-position controls, replay/sweep controls and
  richer chart evidence remain unfinished.
- [x] Browser verified live MU collection (missing fundamentals/industry evidence
  correctly watch-only), synthetic setup -> reviewed plan -> saved review, and
  phone layout. Pure/API tests plus registry regression checks pass.
- [x] Mobile audit: full default matrix initially found one Cartel tablet font
  issue; fixed. Expanded Cartel rerun found landscape links too small; fixed.
  Final focused Desk/Method audit passes on all five device profiles (10 combos).
  Log `.cache/cartel-mobile-final.log`; screenshots `frontend/.mobile-shots/`.
  Current build passes; existing bundle-size/mixed-import warnings remain.

- [ ] Own sidebar destination and routing, desktop/mobile layouts and settings.
- [ ] Method/source details, market/theme dashboard, scan/focus list, setup/chart
  evidence, plan details and editable reviewed inputs.
- [ ] Arming/preflight controls and clear reasons for watch-only/rejected setups.
- [ ] Armed/open/closed views, partial-exit history, live versus modeled results,
  alerts, reconciliation attention, pause/resume/disarm/exit actions.
- [ ] Run history, replay, sweeps, review/evolution evidence and method provenance.
- [ ] Empty/loading/error/stale-data states and restart-safe state refresh.

## 5. Verification and handoff

- [x] Running execution desk: 309 broad regression cases passed in 335.25 seconds
  (`.cache/cartel-runtime-regression.log`). Subsequent permission/lifecycle and
  shared-display fixes passed scoped runtime/controller/API checks, ending with
  20 tests in 37.62 seconds (`.cache/cartel-runtime-final-checks.log`). Production
  build passed. All 20 mobile route/device combinations passed, including an
  expanded options-arming form selected by `MOBILE_AUDIT_CARTEL_PLAN`.
  Logs: `.cache/cartel-runtime-final-build.log`, `.cache/cartel-runtime-mobile.log`.
  Browser verification found and fixed empty-trigger, nullable-distance and
  intraday-wording assumptions in the shared Armed presentation. Synthetic future
  auto/proposal plans were all disarmed; the preview retained zero orders,
  positions and active arms. No real-account execution was activated.

- [x] Prior-mark recovery: 290 Cartel/shared-position regression cases passed
  in 265.61 seconds; final quote-snapshot/clock follow-up passed 58 tests in
  107.89 seconds. Build and all 10 mobile route/device combinations passed.
  Logs: `.cache/cartel-marks-regression.log`, `.cache/cartel-marks-clock-tests.log`,
  `.cache/cartel-marks-build.log`, `.cache/cartel-marks-mobile.log`. A live read-only
  SPY probe confirmed the requested 2026-09-04 daily bar. The refreshed owned
  preview remained in Practice with zero orders, positions and armed plans.

- [x] Daily-loss reporting/guard: **289 passed in 291.79 seconds** across Cartel,
  shared positions and engine-flow suites. Final report-status API changes passed
  **19 loss/API tests in 28.26 seconds**. Production build passed; final mobile
  audit passed all 10 route/device combinations (Desk/Method on five profiles).
  Logs: `.cache/cartel-loss-regression.log`, `.cache/cartel-loss-api-final.log`,
  `.cache/cartel-loss-build.log`, `.cache/cartel-loss-mobile-final.log`.
  Browser verified refresh, exchange timezone, limit status and the Practice
  account picker. The preview stayed in Practice with zero orders/positions/arms.

- [x] Persisted-readiness regression: **267 passed in 225.48 seconds** (229
  Cartel cases plus 38 shared position cases), sequentially in `zargar_test_codex`.
  Log: `.cache/cartel-readiness-regression.log`. Covers readiness after restart,
  inherited entry tags, status/fill/price reconciliation, account/symbol isolation,
  protective exits while entry is blocked, and a blocker arising after preflight.
  Scoped Ruff and diff checks pass. No interactive runtime was changed.

- [x] Verified primary exits: **254 passed in 250.14 seconds** across Cartel
  and shared position suites, log `.cache/cartel-exit-final.log`. A subsequent
  asynchronous-trim fix passed **31 exit/adapter/controller tests in 64.83 seconds**,
  log `.cache/cartel-exit-followup.log`. The full real-sim lifecycle now includes
  confirmed venue-stop cancellation and a close under an engaged halt, with
  both holdings and the managed campaign reaching zero. Scoped Ruff and diff
  checks pass. No interactive runtime was restarted or activated by this work.

- [x] Entry-controller regression: **247 passed in 227.70 seconds** (209 Cartel
  cases plus 38 shared position chaos/policy cases), sequentially in
  `zargar_test_codex`. Log: `.cache/cartel-controller-final.log`. This includes
  real OrderManager/RiskGate/SimExecutor stock and option submissions, actual
  fills, managed handoff, approval gating and interrupted submission recovery.
  Scoped Ruff and diff checks pass. Public money-mode lifecycle and its remaining
  activation gates are not claimed complete by this result.

- [x] Residual recovery regression: **233 passed in 198.11 seconds** (all Cartel
  tests plus shared position chaos/policy suites), log `.cache/cartel-residual-regression.log`.
  Subsequent video-profile collection/screen/API checks: **45 passed in 10.14 seconds**,
  log `.cache/cartel-video-collection-tests.log`; screen/API/plan checks also passed
  45 cases before the collection-validator fix. Final production build and scoped
  Ruff passed. Browser verification collected a real MU history analysis with the
  video profile and displayed its relative-volume gate. Missing capitalization
  remained visibly unknown/watch-only. The isolated preview still had zero
  orders, managed positions and armed plans after verification.

- [x] Earlier Cartel + shared position regression: **225 passed in 194.03 seconds**
  (187 Cartel cases and 38 existing position chaos/policy cases), sequentially
  in `zargar_test_codex`. Log: `.cache/cartel-partial-final.log`. Includes working
  partial protection, cumulative growth, terminal handoff, a concurrent exit
  during quantity persistence, rollback/retry after a failed quantity save,
  and provisional stop-versus-profit behavior. Scoped Ruff and diff checks pass.
  This does not enable money modes or prove residual-fill/cancellation recovery.

- [x] Earlier complete Cartel suite after alert recovery changes: **183 passed
  in 114.16 seconds**, sequentially in `zargar_test_codex`. Log:
  `.cache/cartel-suite.log`. This supersedes earlier Cartel test counts below;
  it does not establish completion of money-mode integration, UI interaction
  checks, full source coverage, or the full repository suite.

- [x] Cancellation settlement + adoption: **13 passed in 24.30 seconds**.
  Optimistic cancellation, persisted acknowledgements, duplicate callbacks,
  partial-risk reporting and terminal adoption are covered. Interim protection
  of working partials remains an explicit uncompleted runtime requirement.

- [x] Terminal adoption + adapter checks: **19 passed in 27.32 seconds**.
  Includes eight adoption cases for races, terminal partials, missing holdings,
  late fills, closed-position retry and injected persistence failure. Earlier
  adoption/adapter/shared chaos run passed 37 cases before the last retry fix;
  default non-adapter behavior is preserved by the opt-in guards.

- [x] Contract selection + Cartel API: **22 passed in 12.79 seconds**.
  Covers eligibility/ranking, freshness, put direction, bounded provider search,
  ownership and selection journaling. No trade was submitted by this feature.

- [x] Daily recovery + position-adapter checks: **15 passed in 33.47 seconds**.
  Includes conflict/future/rewind rejection and preservation of executed state.
  No automatic catch-up trades were executed or claimed by these tests.

- [x] Position-adapter integration and existing position suites: **169 passed
  in 94.01 seconds** (131 Cartel cases plus 38 shared position chaos/policy cases).
  Includes one real OrderManager/RiskGate/sim fill-and-trim path and recorded-fill
  cases for partial fills, restored state, missing adapter/data and stop resizing.
  This does not establish complete entry-runner/automatic adoption or missing-data recovery.

- [x] `test_options_cartel_state.py`: 11 PostgreSQL cases for concurrent arming,
  duplicate callbacks, interrupted submission before/after order persistence,
  actual-vs-requested quantity, foreign/mismatched/duplicate orders, pause,
  retirement and stale signals. Tests insert synthetic order records to emulate
  crashes; they do not prove live OrderManager submission or position adoption.

- [x] Current complete Cartel suite: **119 passed in 49.59 seconds**, including
  11 execution-preflight cases and 6 API cases. This verifies preflight, not
  submitted orders, adoption, recovery or live exit management; those gates remain open.

- [x] First pure suite: `tests/test_options_cartel_screen.py` — 22 passed;
  own-module Ruff check passed. Covers historical causality, incomplete weeks,
  missing/stale/future metadata, strict source thresholds and directional context.
  This is not runtime or UI acceptance; the broader checks below remain required.
- [x] `test_options_cartel_entry.py` — 15 tests; together with screening,
  **37 passed**. Uses S06's HOOD price geometry with explicitly synthetic timestamps,
  not a claim of historical reproduction. Future bars, missing minutes, retests,
  invalidation, expired plans, old crossings and serialization are covered.
- [x] `test_options_cartel_setups.py` (13 cases) and
  `test_options_cartel_prepare.py` (8 cases): **58 Cartel tests passed in total**.
  Includes screen-to-plan-to-entry composition; no live account/order or UI claim.
- [x] `test_options_cartel_exits.py`: 18 cases; **76 pure Cartel tests total**.
  Source campaign variants, delayed/partial fill state, idempotence, small lots,
  protective-exit priority and actual daily-close boundaries are covered.
- [x] `test_options_cartel_api.py`: 4 real-Postgres/ASGI tests cover the complete
  research -> reviewed plan -> replay -> review/readback path, authentication,
  foreign-technique isolation, immutable parent runs and no order creation.
  Automated provider scanning, live arming and desktop/mobile UI remain pending.
- [x] Collection: 6 provider-boundary cases plus one added PostgreSQL API case.
  A read-only live SPY/QQQ probe returned 124 completed daily candles per index
  and 1,949 SPY minute bars (7-day request), ending 2026-09-04. Daily timestamp
  mapping was verified; missing metadata was explicitly reported. Local evidence:
  `.cache/options-cartel/live-collection-probe.json`. No engine was launched.

- [ ] Unit/source-example parity, integration, replay causality, persistence,
  isolated-method guards and execution chaos tests in `zargar_test_codex` only.
- [ ] Frontend build and actual browser desktop/mobile verification against an
  independent Codex runtime/database; no existing app restart.
- [ ] Compare baseline: three known pre-existing test failures (COLLABORATION.md).
- [ ] Audit every requirement above against actual files, test output, rendered UI
  and source coverage; update status and list any operational rollout gates.
- [ ] Record shared additions in PLATFORM-RULES and user-visible changes in all
  required version/changelog files. Keep live activation behind existing gates.

## Concrete integration findings to resolve next

### Running execution desk (2026-09-07)

`CartelRuntime` is now attached to the shared listener/Armed registry and uses the
entry controller for proposal and auto modes. It restores armed and managed state,
handles owned order updates, keeps partial-fill reconciliation independent of slow
submission I/O, applies the daily loss latch, and supports pause/resume/disarm/flatten.
Proposal approval identifies the current signal; caller disconnects cannot cancel
the order task. Resume and reviewed pre-submission configuration updates require a
fresh signal. Reserved attempts cannot be erased by signal-expiry handling.

The plan page exposes account/workspace selection, execution mode, share/option
vehicle, budget/risk/unit limits, reviewed contract input/search, overnight/live
acknowledgements and preflight. Active plans receive live updates and expose approval
and management controls. The shared Armed page receives real mode/size/levels and
Cartel-specific confirmation/swing-exit metadata. Its chart uses the underlying
entry reference separately from an option premium.

Core regression passed 309 cases (Cartel, shared positions and engine flow).
Follow-ups covered arming permission checks, DTO presentation and cancellation of
the approval HTTP caller. Browser checks armed only explicitly synthetic future
plans, verified auto/proposal modes and pause/resume, and disarmed every fixture.
No preview orders or positions were created. Exact final checks are recorded in §5.

Remaining full-goal work includes broader source/example validation, complete
replay/sweep and outcome UI, scheduled scan/recovery integration, daily-history
catch-up decisions, robust broker normalization and operational rollout evidence.
The new execution controls are not a claim of calibrated strategy performance or
verified live-broker deployment.

### Prior-mark recovery (2026-09-07)

The risk card now offers an authenticated recovery action when carried positions
lack a prior close. `marks.py` requests only those owned asset symbols from the
shared daily-history provider, checks the exact completed exchange session, and
inserts missing rows without overwriting existing data. Contract symbols remain
contract symbols; underlying prices cannot replace option marks. Provider gaps,
invalid existing rows and unsupported symbols remain explicit. Quote-source
compatibility is judged per symbol: simulated tape never acquires a real-history
benchmark, while a real OPRA contract is not misclassified by the stock-feed setting.

Risk reports now use a copied quote snapshot for their requested cutoff. Recovery
keeps that snapshot across provider I/O, and submission preflight receives the
controller's callable clock so asynchronous work does not freeze production time.
The recovery action is explicit and places no orders; money-mode startup/pre-open
integration still needs to invoke the recovery workflow where appropriate.

Verification: 290 Cartel/shared-position cases passed in 265.61 seconds before
the snapshot follow-up; 58 mark/loss/preflight/controller checks then passed in
107.89 seconds. Production build passed. A live read-only SPY request returned
the exact completed 2026-09-04 session. Existing data, simulated-source rejection,
per-symbol OPRA handling, provider failures, authenticated API access, concurrent
inserts and changing quotes during recovery are covered.

### Daily loss accounting and Desk report (2026-09-07)

`loss.py` computes daily trading P&L from owned executions, recorded commissions,
prior-close inventory and fresh current bids. It checks execution quantities and
weighted prices against order projections, and inventory against managed legs.
Options require their own prior close; an underlying close cannot substitute.
Missing/invalid marks, FX or accounting evidence make the result unavailable.
`GET /api/options-cartel/risk/{portfolio_id}` is authenticated and read-only; the
Desk's account picker uses the shared workspace filter and displays data gaps,
exchange time, the configured limit and existing halt state.

The optional `techniques.options_cartel.daily_loss_halt_pct` defaults to 0 (off),
consistent with the optional platform technique limit; auto still requires the
book loss halt. When enabled, preflight/submission checks latch an observed breach
for that ET day in the append-only journal, surviving restart and P&L recovery.
The threshold uses current book equity. This limit is an engineering control,
not a daily percentage stated by Sean. GET reporting itself does not latch it.

**Accounting scope:** this is price/recorded-fee P&L converted at current FX,
excluding FX translation P&L. Execution timestamps preserve the executor report's
time. Broker adapters may still report receipt time and provisional/absent fees;
venue-time and fee corrections need normalization before claiming audited live
broker-day results. Prior marks must exist in the shared daily-bar layer; missing
contract marks are not fabricated. Automated mark recovery and continuous runtime
monitoring remain part of money-mode integration.

Backend regression: 289 passed in 291.79 seconds (Cartel, shared positions and
engine flow), log `.cache/cartel-loss-regression.log`. After the final read-only
halt-status fields, 19 loss/API checks passed in 28.26 seconds. Production build
passed. Browser verified the empty Practice book at USD 0.00, refresh, exchange
timezone, and exclusion of the live-kind book from the Practice picker. The Live
confirmation was cancelled without changing routing.

### Persisted execution readiness (2026-09-06)

Preflight and the entry controller now read prior Cartel executions for the same
portfolio and underlying. Unknown/mismatched exits, unapplied quantities or
price corrections, pending cancellations/closes, unrestored positions and older
unsettled entries block new exposure. Closed records are still checked for working
orders. Healthy, reconciled resting stops remain allowed. The read does not
mutate a global halt or prevent existing positions from closing. Reports include
structured blockers and references; the controller rechecks before/after reservation.

Exit orders retain entry-lineage tags, so entry association now selects the owned
BUY order rather than treating its SELL descendants as duplicate submissions.
Share preflight risk uses the actual ask in the proposed limit, not an older
trigger price. The final underlying check follows the asynchronous readiness read.

Focused readiness/preflight/controller checks: 43 passed in 73.57 seconds. Includes
account/symbol isolation, restart, status versus fill reconciliation, same-quantity
price corrections, protective exits under an entry block, and a new blocker arising
after preflight. Broader regression results are recorded in §5 after completion.

Remaining activation work: per-technique loss accounting, public money-mode
runtime and UI, full daily-history catch-up, and source/replay/mobile acceptance.
Fill-price corrections currently block entry for accounting review; they are not
silently rewritten by this gate.

### Primary exit cancellation (2026-09-06)

Cartel's exit router now persists the requested remaining quantity and handles
the cancellation/replace cycle. A cancel() response alone never releases units:
the router verifies the persisted owned order and applies cumulative fills first.
Pending profit-taking and venue stops never reserve more than the held quantity.
A venue-stop fill closes the remaining campaign instead of installing another
profit-taking order. Stop/close retries are bounded and delayed; unknown outcomes
require reconciliation. A persisted close request resumes after restart.

The order-layer test double now persists its acknowledged reports in the disposable
database, so cancellation tests exercise the same evidence boundary as runtime.
The focused exit/adoption/residual/settlement and shared-position run passed 69
cases in 93.24 seconds; the broader and final follow-up results are in §5.

Remaining: connect public money-mode lifecycle and proposal/arming UI, implement
per-technique day-loss accounting, finish daily-history catch-up and broader
source/replay/UI acceptance. Unresolved-exit attention must also feed symbol
entry gating before activation. This closes a cancellation integration gap; it is
not a claim that the complete technique is ready to activate.

### Entry submission controller (2026-09-06)

`CartelEntryController` now connects a consumed signal and its saved execution
configuration to real OrderManager/RiskGate submission, followed by settlement
and actual-fill adoption. It checks the owned plan and exit/history inputs,
signal identity/age, RTH/horizon, live acknowledgements, halts, current underlying
geometry, chase distance and vehicle price. Share risk sizing uses the maximum
entry price and the signal's actual stop. Proposal mode requires approval of
that particular signal. The 120-second signal-age limit is an engineering
freshness guard, not a wait time quoted from Sean. A reservation is durable before routing; a pause or
price change detected afterward can abort before any order call. Duplicate
callbacks reconcile the existing attempt. Missing order acknowledgement is
attention-required, never permission to submit again.

The controller is not exposed through the alert-only public observer yet.
Runtime subscription/restoration, proposal UI and arming controls, primary
campaign cancellation/stop replacement, and per-technique day-loss accounting
remain integration gates. The controller enforces the enabled book loss halt
for auto; it does not claim that the remaining technique-specific accounting
or runtime lifecycle has been completed.

The focused controller/adoption/settlement run passed 27 cases in 47.99 seconds.
It drives actual stock and option orders through the real OrderManager and
SimExecutor against `zargar_test_codex`, verifies fills and managed adoption,
and covers duplicate calls, lost/unknown responses, proposal approval, stale
signals, chase/halts, and a pause during reservation. The option test found and
fixed adoption's acknowledgement lookup for the nested saved execution config.

### Residual fills and video review (2026-09-06)

Late entry fills during/after campaign closure now allocate separately identified
residual positions, using contiguous cumulative fill/cost ranges. They flatten
through the shared manager without reopening the original or cancelling its
in-flight exit. Persisted range discovery recovers an interrupted adoption/binding.
Residual exits reconcile exact persisted attempt tags; unknown outcomes remain
attention items rather than blind retries. Confirmed terminal exit reports apply
their actual fills before considering the remaining quantity. Missing restored
residuals, overlapping ranges and cumulative quantity regressions are rejected.

The user unlocked S24's TikTok video. [VIDEO-REVIEW.md](VIDEO-REVIEW.md) records the
caption/frame review and source-versus-platform differences. A separate video
screen profile adds relative volume >1, ADR >2% and average volume over ten
sessions, without altering saved profile behavior. It supplies no exit policy;
the plan form explicitly distinguishes the selected written exit profile.

**Still required:** connect the entry controller and money-mode APIs/UI; reconcile
primary campaign venue-stop replacement/cancellation against late reports;
automate durable event-delivery recovery and handle fill-price corrections.
Residual recovery is now implemented, but isolated synthetic tests are not live
activation evidence. No new entry orders were placed by this work.

### Working partial protection (2026-09-06)

`settle_entry` now calls `reconcile_entry_fills` before requesting or waiting on
cancellation. Confirmed units become a durable provisional managed position:
stops/expiry and manual exits remain active, while source profit-taking waits for
terminal settlement. Cumulative fill growth updates the same position and its
campaign quantities using incremental fill cost. Repeat callbacks reuse the
position and do not add the units twice. Entry retirement retains unresolved
provisional protection in the active state set.

Opt-in position adapters now serialize quantity changes, persistence, closed-bar
decisions, closes and order-fill callbacks with a per-position reentrant guard.
This permits the manager's immediate-fill callback to nest inside a close while
blocking an unrelated entry growth or exit callback from overwriting its state.
Other policies retain their existing execution path. Shared change is recorded
in PLATFORM-RULES.

**Still required before money modes:** reconcile residual fills when a provisional
position is already closing/closed; verify venue cancellation and stop replacement
against late reports; handle fill-price corrections, persistence/subscription
failures and restore continuously; connect the entry controller and APIs/UI.
The current reconciler explicitly rejects those residual/correction cases.
No interactive runtime has been updated or money mode enabled by this work.

### Alert observation recovery (2026-09-06)

The shared listener/Armed hub now includes Cartel alert-only plans, with own-page
arm/pause/resume/disarm controls. Proposal/auto requests still reject explicitly.
Resume and restart restore available current-session bars from this runtime's
database/cache, preserve persisted observations, and save an `observeAfter` cutoff.
The entry reader skips old crossings while retaining session extremes and
post-arming invalidations. Subscription/seed failures persist a paused plan and
surface attention in both detail and shared summary; resume retries recovery.
Observation and signal consumption now use one row-locked transaction, including
when journal delivery fails afterward. Journal delivery is still a separate
commit; a durable retry/outbox for that failure remains an audit-completeness gap.
Missing provider history is not fabricated or treated as complete warmup.

Tests exercise pause/restart with a missed crossing followed by a new crossing,
restored session-stop context, subscription failure/retry, no order creation,
and persisted consumption through an injected journal failure. The focused
observer/entry/state/API run passed **45 tests in 52.69 seconds** using only
`zargar_test_codex`. Scoped Ruff and the production frontend build passed
(existing mixed-import/chunk-size warnings). This is not money-mode acceptance
or verification of the currently running preview's code version.

Cartel now adopts confirmed fills and protects working partials through the
reconciler above; it does not use the requested quantities constructed by
`PositionManager.open` as evidence of holdings. The remaining entry must still
be monitored after protective exits begin: a late fill may arrive during or
after closure. That residual-exposure recovery is not implemented yet. Keep
the trigger/order association durable and recover it without blind resubmission.

The legacy `PositionManager.on_minute_bar` path obtains 5m bars for `timeframe=1d`;
it is unchanged for existing techniques. Cartel now explicitly opts into its
own daily/campaign adapter, avoiding that approximation. Still required: seed
the current session's pre-entry minutes at adoption, recover missing daily/minute
history after downtime, and process missed daily decisions against current
execution prices without inventing historical fills. Current adapter detects
these gaps and raises attention; detection alone is not complete recovery.

The research queue and missing options-selection details remain active. No
execution runner is enabled for Cartel yet. The registered research page is
available in the isolated Codex preview; it does not place orders.
