# Handback 2: response to REVIEW-ff67f695 (R1-R7 + end-to-end fixture)

Prepared 2026-09-21 (late evening ET) by the implementation desk. One corrected commit on
`claude/cartel-brief-0921` on top of ff67f695 (PR #246); the reviewer's seven probes
(`backend/tests/test_pr246_review_boundaries.py`, from codex/review-cartel-pr246 e52f64a9) are
adopted verbatim into the branch as retained regressions. Runtime, settings, arms and positions
were not touched. Nothing is deployed or activated.

## R1-R7: fix and retained test

| Finding | Fix | Where | Retained tests |
|---|---|---|---|
| R1 P1 matched control stops when the executing cadence acts | The control has its OWN registry (`CartelObserver.controls`), its own tape (`state.control.minutes`), watermark (`state.control.observeAfter`) and session lifetime. `_observe_controls` runs after the executing loop for every registered control of the symbol, regardless of the row's status/phase (signalled, submitting, managed, disarmed, expired); it stops only when the plan's last session has closed plus two minutes, or when the technique is disabled (the entry pause does not stop it). Corrections merge into the control tape and advance its watermark (context only). Restart: `runtime.restore` re-registers controls for every stored row with a control block, flooring the watermark at the restore clock (no replay); `_register_control` also runs from `_remember` (arm/restore). A control block saved onto an already-tracked row is discovered lazily. Control signals are journaled (`control_signal`) and never consumable (`consume_locked` id shape). | `observer.py` (`controls`, `_register_control`, `_register_control_stored`, `_observe_controls`), `runtime.py::restore` | probe `test_matched_control_keeps_observing_after_executing_signal`; `test_cartel_end_to_end.py` (control observed through signalled -> managed -> restart), `test_cartel_cadence.py` (ids never consumable, watermark, repaired evidence) |
| R2 P1 saved Live 5m settings fail validation | Unlabelled policies derive: 15m -> `breakout_15m_v1` (identical behaviour), any other timeframe -> `legacy_timeframe` (the pre-existing read; valid in every workspace; no control, no pilot). Only the EXPLICIT `breakout_5m_v1` label opts into the Practice-only experiment. The "must carry a label" rule is removed. | `automatic_plans.py::PreparationPolicy` | probe `test_existing_live_5m_policy_is_not_reinterpreted_as_new_experiment`; `test_cartel_cadence.py::test_saved_policy_without_label_...` (Live/Practice saved 5m dictionaries) |
| R3 P1 long-only pilot changed executable short plans | `automatic_review` keeps a bearish executable plan on the incumbent 15-minute cadence with label `breakout_15m_v1` under the pilot; `control_block` builds a control only for long plans. A real short-regime preparation (mirrored history, falling SPY/QQQ) arms a 15m put plan without a control under BOTH policy states; a long-regime preparation under the pilot arms a 5m plan with a 26-slot control baseline independent of its 78-slot 5m baseline. | `automatic_plans.py::automatic_review`, `preparation.py::control_block` | probe `test_long_only_cadence_pilot_does_not_change_short_execution`; `test_cartel_cadence_preparation.py` (3 tests through `run_preparation` and arming); `test_cartel_cadence.py::test_bearish_executable_plan_keeps_the_15m_cadence_under_the_5m_pilot` |
| R4 P2 expiry/chain requests escape the deadline | `_bounded()` wraps expiry discovery, every chain request and every refresh in the same remaining-deadline/per-call ceiling; nothing starts after the deadline; a stalled or failed request is recorded as incomplete work (never an empty result); the deadline is rechecked before returning: a result that lands after it is recorded but not selected (`expiredSelection`, `searchStatus=expired`). Cancellation propagates unchanged. Legacy path unchanged. | `contracts.py::_bounded`, `_select_diverse` | probe `test_expiration_discovery_consuming_deadline_prevents_further_requests`; `test_options_cartel_contracts.py`: stalled expiry discovery, stalled chain request, already-expired request, result after deadline, refresh timeout consuming the deadline |
| R5 P2 partial candle reported as completed close | `price_touch` judges a bucket only when it ended by the cutoff and EVERY minute is an exchange bar or a verified non-emission interval (the canonical `read_entry` rule); otherwise the bucket is listed in `incompleteBuckets` and the close is unknown. A touch followed by an incomplete window yields `wickOnly=None` ("unknown, not wick-only"); a no-touch verdict names unknown windows. Sampled bars, missing minutes and repaired evidence are all "unknown". | `review_attribution.py::price_touch` | probe `test_incomplete_bucket_cannot_be_reported_as_completed_close`; `test_cartel_review_attribution.py::test_price_touch_completeness_rules` (missing last minute, sampled bar, verified interval, unended bucket) |
| R6 P2 partial-fill classification used fields the producer never supplies | `summarize_fills` now returns `entryFilledQty` (cumulative BUY fills), `entryFilledQtyToday` and `exitFilledQty` beside `remainingQty`; `entry_ledger()` derives requested/filled/status from ORDER rows (`qty`, `filled_qty`, `status`) that `session_review` passes as `entry_orders`, never from holdings; `actual_outcome` returns no_order / submitted / unfilled / partially_filled / held / closed and the report carries `attribution.entry`. | `review_ledger.py`, `review_attribution.py::entry_ledger/actual_outcome`, `session_review.py` | probe `test_partial_fill_classification_consumes_the_real_ledger_shape`; `test_cartel_review_attribution.py::test_actual_outcomes_follow_recorded_fills` (partial entry, cancelled remainder with partial exit, unfilled, working); `test_cartel_end_to_end.py` (real ledger: 1+1 fills, trim, report) |
| R7 P2 later refusals asserted independent | `remainsIfFirstRemoved` is `True` only for a different rule in the SAME window on the same inputs; a later window/stage is `None` with `independence: unknown` and its reason spelled out. ULTA's two same-window blockers stay established. | `review_attribution.py::attribute` | probe `test_later_refusal_is_not_proved_independent_of_first_entry_refusal`; `test_cartel_review_attribution.py` (NTNX later window unknown, ULTA same window established) |

## End-to-end fixture

`backend/tests/test_cartel_end_to_end.py::test_plan_to_report_with_diverse_search_partial_fills_exit_restart_and_control`:
frozen plan armed through the runtime with `diverse_liquidity_v1` + `executable_cost_v1` and a
matched control -> exchange-sourced tape -> complete closed-bar 5m confirmation -> saved contract
refreshed first and refused on spread -> bounded search across both expiries selects the eligible
alternative (`searchComplete=true`, economics estimated) -> second preflight -> ONE order through
the shared OrderManager/RiskGate (2 contracts, $400 <= $500 budget) -> partial fill (1) protected,
cumulative fill (1) -> adoption -> the 15m control keeps observing while the arm is `managed` ->
first-target trim of one contract at the bid -> restart (new PositionManager + CartelRuntime): position
restored, control re-registered with a floored watermark, one more control read -> exactly one BUY and
one SELL fill -> session report from the actual ledger: `actualOutcome=held`, `entry` 2/2 FILLED,
selection coverage `eligible_expression_found`, funnel all true, fees from the execution rows, cadence
comparison (executing 1 plan / 1 signal / 1 order / 1 fill; control 0 orders, no P&L). Every quote and
Greek is SYNTHETIC and labelled. Fixture plumbing, stated in the test: order/position creation stamps
are aligned to the rig's synthetic session clock so the report's cutoff sees them.

## Verification (isolated `zargar_test_cartel`)

- Reviewer probes: 7/7 pass. Attribution 9, cadence 15, contracts 49, end-to-end 1, regime
  preparation 3.
- Focused packet (probes, attribution, opportunity, contracts, reselection, research quotes, execution,
  automatic plans, controller, contract integrity, lab observer, eod improvements, sep16 follow-through,
  lab protocol, preparation, coverage, workspaces, baseline windows, prepare, entry, observer, runtime,
  execution review, intraday + profitability research, method lab + review, API, review quality, restart
  recovery): 339 passed, 1 failed (the pre-existing reduce-only exit test below). Frontend `npm run build` green at 0.8.29.
- Known pre-existing failure (also on base, confirmed by the reviewer):
  `test_reduce_only_exit_bypasses_an_entry_final_guard` after 16:00 ET.

## Verdicts (separate)

- Code: corrected; ready for re-review.
- Deployment: not performed.
- Practice activation: not performed. The proposed staging in HANDBACK.md is a suggestion, not a
  prerequisite for delivering reviewed code.

## Still open (unchanged scope, not new defects)

- Non-15m plans are still excluded from the intraday and profitability research panels ("Research v1");
  before F4 activation this exclusion must be lifted or replaced by equivalent evidence.
- The underlying-quote timestamp/observation mismatch seen in the September 21 shadow evidence is not
  addressed; it will be investigated with receipt-time evidence, never by admitting future quotes.
- The volume grid stays off; no cross-session comparison was run.
- F5-F8 and shares integration remain outside this package.
