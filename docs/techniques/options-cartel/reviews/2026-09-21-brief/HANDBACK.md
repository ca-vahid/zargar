# Handback: September 21 brief, first release (F1, F2, F3, F4)

Prepared 2026-09-21 (evening ET) by the implementation desk for the reviewer. Code
only: nothing in this handback changes trading settings, armed plans, positions or the
running application. Activation of any new policy is a separate, journaled settings change
after the reviewer's code verdict.

## 1. Branch, commit, reconciliation

- Branch `claude/cartel-brief-0921`, based on `origin/main` 7eb89303 (PR #245). Commit hash: see the PR.
  Release metadata bumped to 0.8.29 (next free number after main's 0.8.28 at commit time).
- Runtime observed at the start of the work: v0.8.28 build 7ee5ad2a; the Cartel Practice book
  `e7b246c9e30d4dde93f4d91844cbc982` had six arms for 2026-09-21 and no positions or orders.
- Effective settings re-read read-only from the runtime database before implementation
  (`techniques.options_cartel.preparation`, updated 2026-09-19 17:25): budget 25,000; risk 10%;
  max contracts 10; focus 20; contract policy 21-90 DTE / target 45 / delta 0.25-0.5 / ask 250 /
  spread 20% / OI 100 / refresh 6; entry 15m breakout, 1.5x, 0.70 close, session-extreme stop;
  market alignment moderate; coverage `opening_and_broad`; exits `whole_contracts_v2`.
  The saved policy has no `selectionVersion`, `rankingVersion` or `entryCadence` keys, so it
  validates to `legacy` / `legacy` / `breakout_15m_v1` under this branch: **behaviour unchanged until
  a settings change**.

Changed paths (backend `zargar/techniques/options_cartel/` unless noted):

| Package | Code | Tests |
|---|---|---|
| F2 | `contracts.py` (versions, `SelectionRequest`, `diverse_liquidity_v1`, `allocate_refresh`, `call_selector`), `contract_reselection.py`, `research_quotes.py`, `method_lab_observer.py` | `tests/test_options_cartel_contracts.py` (+22), `_contract_reselection.py` (+2), `_research_quotes.py` (+1) |
| F3 | `contracts.py` (`SelectionEconomics`, `contract_economics`, `executable_cost_v1`), `automatic_plans.py::planning_contract`, `execution.py::preflight` (`expression.economics`, `stockGeometry`) | `tests/test_options_cartel_contracts.py` (+8), `_execution.py` (+1), `_automatic_plans.py` (+1) |
| F1 | `review_attribution.py` (new), `session_review.py`, `frontend/src/pages/CartelSessionReview.tsx` | `tests/test_cartel_review_attribution.py` (new, 8) |
| F4 | `cadence.py` (new), `automatic_plans.py::PreparationPolicy`, `plans.py::cadence_version`, `service.py::PlanInput`, `prepare.py`, `preparation.py::control_block`, `observer.py`, `session_review.py`, `intraday_research.py` / `profitability_research.py` (opening-slot count), `frontend/src/pages/CartelPreparation.tsx` | `tests/test_cartel_cadence.py` (new, 13) |

Policy versions introduced (all snapshotted on the arm's saved `contract_policy` or plan):
`selection_version` = `legacy` | `diverse_liquidity_v1`; `ranking_version` = `legacy` |
`executable_cost_v1`; `refresh_batches` (1-3, diverse only); `entry_cadence` = `breakout_15m_v1` |
`breakout_5m_v1` | `legacy_timeframe`; `volume_experiment.version` = `off` | `grid_v1` (replay only);
`CartelPlan.cadence_version`; arm config `cadence` (control block, `cartel-cadence-control-v1`).

## 2. Evidence table

| Finding (brief section 3) | Code | Test | Outcome | Unresolved limit |
|---|---|---|---|---|
| NTNX selection: two expiries / 47 candidates, six November rows (OI 0-26) consumed the budget, October never refreshed | `contracts.py::_select_legacy` (unchanged) vs `_select_diverse` | `test_legacy_sampler_reproduces_ntnx_november_starvation`, `test_diverse_refresh_gives_the_reviewed_october_contract_first_consideration_and_represents_both_expiries` | Legacy reproduces the starvation; diverse refreshes the reviewed October contract first, records the 24 November rows as known OI failures without refresh, and reports `searchComplete=false` with 17 unrefreshed October rows | October delta/OI in the fixture are SYNTHETIC (the record has none); the real case is not proven eligible |
| NTNX October book 9.80/11.30, sizes 401/74 | `contract_economics` | `test_ntnx_october_book_economics_are_reported_not_labelled_as_profit` | 14.218% of mid, $150 crossing per contract, $2.08 round-trip fees, friction 13.46% of debit, 10 affordable and covered | No outcome claim; the -$150 endpoint comparison stays an illustration |
| ULTA option 10.00/14.80 | `rank_candidates` + economics | `test_ulta_book_stays_ineligible_under_the_saved_spread_rule_regardless_of_capital` | Ineligible at $500, $25k and $1m caps; 38.71% spread, $480 crossing | Delta SYNTHETIC |
| NTNX production 15m 0.929x / 1.162x vs lab 5m 2.511x | `entry.py` (unchanged), `cadence.py::read_control` | `test_ntnx_5m_confirms_at_2_511x_while_15m_refuses_at_0_929x_on_the_same_tape`, `test_independent_baselines_are_built_per_timeframe_from_the_same_minutes`, `test_control_read_records_the_15m_refusal_beside_the_executing_5m_signal_without_an_executable_id` | Reproduced from one synthetic tape with independent 5m and 15m baselines | Synthetic minute prints; only the bucket sums and closes match the record |
| ULTA 5m 09:55 0.962x, 15m 10:00 0.420x + 0.064R | `entry.py`, `review_attribution.py` | `test_ulta_5m_still_fails_unchanged_volume_and_now_wick_never_becomes_a_candle`, `test_ulta_lists_both_independent_1000_blockers_and_keeps_target_passed_windows_separate` | 5m still refuses at unchanged volume; both 10:00 blockers are listed as independent | None |
| NOW 09:31 wick | `review_attribution.py::price_touch` | `test_now_wick_is_not_an_eligible_missed_entry` | `wickOnly=true`, no candle closed beyond the trigger; category stays `no_trigger` | None |
| BBY/CNH/NVT no touch | `price_touch` | `test_no_level_touch_names_the_distance` | Explanation names the session high and the distance | None |
| NTNX `data_limited` masking the 10:30 refusal | `review_attribution.py::attribute`, `category_from` | `test_ntnx_volume_refusal_and_later_data_warning_are_separate`, `test_an_unknown_earlier_window_stays_unknown_and_a_repair_cannot_authorise` | First known blocker = 10:30 volume; 13:00 window listed separately; an earlier unknown window stays unknown | None |
| Reselection scope | `contract_reselection.py` | `test_reselection_passes_the_saved_contract_deadline_and_cash_basis_to_the_search`, `test_reselection_snapshots_the_saved_selection_version` + existing 5 | Deadline = signal + 120 s, never extended; version snapshotted | None |

Also covered (F2 acceptance list): now-invalid preferred contract (no grandfathering), identity
rejection (wrong underlying/right/expiry/garbage/plan id), missing OI = unknown not zero, refresh
timeout bounded by the deadline (real `asyncio.wait_for`), stale-after-refresh judged at the end,
deterministic ties (`allocate_refresh`), cancellation propagates, chain failure of one expiry leaves the
search incomplete, second batch only with an explicit deadline, saved policies without version keys stay
legacy, Live/other-desk seams unchanged (`call_selector` keeps 3-argument test doubles working).

## 3. September 21 reproductions and prior sessions

Reproductions are in the tests above. A frozen comparison across prior sessions requires the
arm tapes and quote records of those sessions; this branch adds the machinery (per-arm matched
control, cost tuple with `legacySelected`, funnel attribution) but the cross-session run was not
executed in this handback. `docs/techniques/options-cartel/reviews/2026-09-17-proposal/` holds the
earlier reconstructions (APA, QS, TTWO, PWR, APTV) on the legacy selector. Cost assumptions in every
estimate: buy at the ask, exit at the bid, displayed size consumed once, $0.99 + $0.05 per contract per
side from the Practice simulator settings, cash cap = min(cash, budget, equity x risk%).

## 4. Verdicts (separate)

- **Code acceptance:** ready for review. Focused packet on the isolated `zargar_test_cartel` database:
  contracts 45 passed; reselection 7; research quotes 5; execution suite incl. economics; automatic plans 5;
  attribution 8 + opportunity 3; cadence 13; controller / lab observer / contract integrity / eod
  improvements / lab protocol / preparation / coverage / baseline windows / entry / observer / runtime /
  execution review / research / method lab / API: see the PR description for the final counts.
  One pre-existing time-of-day failure: `test_reduce_only_exit_bypasses_an_entry_final_guard` fails
  after 16:00 ET on unchanged main code (sim option fills need an eligible session in that rig); not
  caused by this branch and not masked.
- **Deployment:** not deployed. Guarded procedure only (`/api/ops/restart-check` + `ZargarRestart`),
  outside prime hours and active preparations, after merge.
- **Practice activation:** not activated. Proposed order after deployment: (1) settings PATCH adding
  `contractPolicy.selectionVersion=diverse_liquidity_v1` and `rankingVersion=executable_cost_v1`
  (new plans only; saved arms keep legacy); (2) only after (1) has run at least one session,
  `entryCadence=breakout_5m_v1` with `entry.timeframeMinutes=5` (new plans only; existing arms keep
  their cadence; the 15m matched control is recorded automatically). Rollback: PATCH back to
  `legacy`/`breakout_15m_v1`; existing arms, positions, records and policy ids are untouched;
  protective exits are outside this change.

Settings before/after for activation: before = the 2026-09-19 policy quoted in section 1; after =
the same policy plus the three keys above. Existing arms and positions are preserved by construction
(policy version is snapshotted per arm; `arm_with_capacity` refuses to arm under a changed policy).

## 5. Guarded deploy

Not performed. Checklist for whoever deploys: merge, `python -c "import zargar.api.app"`,
`npm run check-release`, restart-check, `ZargarRestart`, then verify `/api/health` build,
restored arms/managed positions/orders and other desks' fingerprints.

## 6. User-visible explanations

- Daily review row: actual outcome, first known blocker (time, stage, rule, measurement),
  other independent blockers (same window flagged), incomplete windows (count, "before the first known
  blocker" when applicable, never cleared), contract search coverage (not attempted / incomplete /
  exhausted / eligible expression found, with the selection version), cadence line with the matched
  control's confirmations, and the top-level cadence comparison (executing plans/confirmations/orders/
  fills/net vs. control confirmations, no P&L).
- Preflight `expression.economics` and `stockGeometry`: spread in units / $ per contract / total,
  fees, debit, friction % of debit, displayed-size coverage, full-debit exposure, beside the stock
  target/stop R.
- Selection reports: `selectionVersion`, `byExpiry`, `batches`, `allocation`, `preferredContract`,
  `searchStatus`/`incompleteReasons`, `legacySelected`/`selectionChangedFromLegacy`, `rankKey`.
- Preparation settings: "Entry cadence (versioned)" selector (Practice only for 5m) tied to the
  confirmation timeframe.

## 7. Rollback

Settings PATCH back to the legacy versions stops new plans from using the new selection, ranking
or cadence. Records, policy ids, control observations and losses are retained; unknown outcomes stay
unknown. No code rollback is needed for that; a code rollback (revert the merge) also leaves every
saved arm valid because every new field has a legacy default.

## Known limits of this delivery

- The 5m cadence executes only for long Practice plans by the existing pipeline (bearish plans are
  the research proxy and never arm); the control is recorded per arm, not for plans that never armed.
- The end-to-end fixture required by section 13 (frozen plan -> confirmation -> diverse search ->
  preflight -> simulated order -> partial fills -> exits -> restart -> report) is covered by separate
  existing suites plus the new pieces; one single fixture spanning all stages is still to be written.
- The volume grid (`grid_v1`) is a replay-only declaration feeding `sweeps.py` variants; no replay run
  was executed.
- Intraday and profitability research still refuse non-15m plans ("Research v1 ..."); their opening-
  hour slot count now follows the plan timeframe, but a 5m Practice plan would be excluded from those
  observation panels until that limitation is lifted.
- The lab's underlying quote check (`underlying_quote_unavailable` when the SIP quote timestamp is
  later than the observation time) was observed in the September 21 shadow evidence and is not
  addressed here.
