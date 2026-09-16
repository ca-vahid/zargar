# EM profitability cohorts review: ba2eccb

**Research definitions accepted for prospective comparison. Scoped integration GO with both experiments disabled; the report remains provisional until the profitability-measurement corrections below.** No new production reliability work, strategy activation, order, setting change or restart is requested by this review.

Reviewed commit: `ba2eccb33fc1259775f6869e1623c8283ed83a59`, verified on remote `origin/claude/technique-review-trade-plan-fbb9ba`. The other desk remote `origin/claude/zargar-stock-app-research-8mnqfh` still pointed to an earlier commit at inspection. A release owner must integrate the actual reviewed commit, not assume similarly named branches contain it. Isolated review checkout: `C:/Cursor/zargar-codex/.cache/em-profitability-review`, detached; primary remains `C:/Cursor/zargar-codex`, branch `codex/zargar-development`.

## What the initial report establishes

The reporter's `build` and `summarize` functions were executed read-only against the local database, with connection-enforced `default_transaction_read_only=on` and a 15-second statement timeout. The CLI writer was not invoked and no raw database export was saved. Cutoff: **September 15, 13:20 ET**.

| Measure | Independently reproduced |
|---|---|
| Baseline and P-01 fills | Five each; every fill is in `long_bounce_next_resistance`. No removed trades. |
| Closed positions | Four, net **-$141.22**: NFLX -$60.32, CVNA -$74.16, IREN +$2.84, CRWV -$9.58. |
| Open position | One ORCL call; $296 paid premium + $1.04 entry fee. Unmarked in this report. |
| Cohort-eligible fires without a position | Four: INTU/WDC `tp1_first`; AMAT/SMCI `stop_first` in the underlying-only proxy. These are not four proven missed winners. |
| P-02 | Four eligible positions, all unknown without observation evidence. |
| Friction examples | CVNA 10.12%, IREN 6.22%, matching the prior review's static snapshot calculation. |
| Economics-table coverage | Eight rows reported out of fifteen filled/refused fire rows; seven are omitted because friction is unknown. |

Thus **P-01 has no measured selection advantage today**: its trade set equals the baseline. That is useful forward evidence and should remain in the series. P-02 has no measured improvement yet. The quoted -$73.26 day figure is not the realized-only figure above; show a separate timestamped unrealized/mark component if using an equity-based day total. The team cited a later cutoff, so these numbers are not asserted to be same-time contradictions.

The two thresholds newly chosen here (2R eligibility and 8% friction marker) are declared research conventions, not established optimums. September 14/15 remain development examples; use subsequent sessions to evaluate the frozen definitions.

## Independent checks

`tests/test_em_profitability.py` plus `tests/test_em_forward_measurement.py`: **15 passed in 0.48s**. Five new focused cases: **5 failed in 0.31s**, all at intended assertions. They use pure functions, the actual observer capture method and an in-memory database double; no test connects to production, starts an engine or places an order. Commands ran sequentially through `scripts/test-codex.ps1`. Broader team suites and an unspecified combined v0.7.87 target were not independently validated.

## PF-01 — P2: connect the actual P-02 observation contract to its reducer

`backend/zargar/execution/planrunner.py` emits `disposition=observed`, `modeled.scorable`, `modeled.coveredQty`, a nested contract/modeled bid and `observedAt`. `backend/zargar/tools/em_profitability.py:130` instead accepts only `disposition=covered`, a top-level `bid`, and sorts by `observedTs`. A valid record from the actual capture method consequently remains unknown in the reducer. The current successful unit test hand-builds the consumer's expected shape and misses this mismatch.

Additionally, recording an unscorable first touch consumes that candidate rung. A valid bid/depth arriving later is no longer captured, although the frozen policy calls for the **first covered** observation. The second reproduction records a no-quote touch and then supplies a valid quoted opportunity 500ms later; the capture returns no candidate.

**Correction:** consume the actual payload and validate its coverage, candidate version, original entry/trade identity, same contract, eligible time and available quantity. Keep the first unscorable evidence but allow a later first covered opportunity for this policy. Do not change the first-raw-observation semantics of a separate experiment silently. Bind observations using entry/trade instance as well as run/trigger; `build` currently collects all shadows by trigger alone.

**Acceptance:** the actual capture payload drives the compared result, while wrong trade/contract, insufficient coverage, pending/stop-first, and wrong-time evidence stay unknown. First unscorable then valid covered evidence must be handled exactly as the frozen definition says.

## PF-02 — P2: conserve actual fees in the paired exit comparison

The baseline uses actual execution fees, while `productionPerContract` and the alternative substitute the day's median fee for both sides. This can create a difference unrelated to exit prices.

**Reproduction:** two contracts bought at $1 and sold at $2, with $2 actual total entry fees and $4 actual total exit fees, produce baseline **$194**. At an identical alternative price and exit fee, the report produces **$192** and a false -$2 change because it recharges historical entry fees and reprices the retained contract's fee allocation.

**Correction:** preserve actual entry fees and actual fees/results on the retained contracts. Apply a declared modeled exit fee only to the hypothetical sale. Allocate actual fees consistently with lots/fills, and keep any missing allocation unknown. When price and exit cost are unchanged, the pair must produce zero difference. Winner opportunity cost must use the same fee basis as the pair.

This is profitability accounting, not a request to rewrite the production ledger. The current realized baseline figure reproduced correctly for today's book.

## PF-03 — P2: complete contract economics without excluding unknowns or puts

The P-03 table filters out rows when friction cannot be calculated. Today's three oversized share intents and several contract/budget refusals consequently disappear from that table. Keep them with explicit unknown values and reasons, rather than changing the research denominator.

The tool defines `affordable_qty` but never calls it while building/rendering the report; no affordable-quantity field appears in the reproduced output. Wire the declared budget calculation using evidence available at the intent, or mark it unknown. Label it risk-budget quantity if other cash/exposure constraints are not included; do not imply complete admission feasibility.

`payoff_to_tp1` also rejects every negative delta. Negative put delta is normal, not missing data: delta -0.5 times a -$5 underlying move on one standard contract gives a +$250 first-order premium proxy. Use signed delta and signed movement, with missing/zero/invalid inputs kept unknown. Avoid an absolute-value calculation that would turn an adverse movement into profit. This remains a local sensitivity approximation, not a forecast of realized option payoff. [OIC technical explanation](https://www.optionseducation.org/referencelibrary/faq/technical-information).

Two tests reproduce omission of an unscorable refused WDC intent and refusal to calculate a valid put-direction proxy. Current RKLB and DVN rows demonstrate why puts must not automatically lose the payoff comparison against calls.

## P-01 metric labeling to correct in the same report change

`roomAtActualEntryR` currently receives `tr.entry`, the intended underlying plan entry. It is neither an observed underlying price at dispatch nor the option's fill price. Label the available value as planned room, and report actual-entry room unknown unless the corresponding underlying observation is available. Do not plug an option premium into underlying geometry.

The source-alignment field is deliberately only a symbol/direction match to the source ledger. Present it as such; it does not establish agreement on level, timeframe, conditions or holding period. Preserve source availability when interpreting the stratum. No redesign of the source pipeline is requested here.

## Release and next step

The new observer and P-02 knobs are default-off in the reviewed source. Normal baseline trading remains independent. This code may be integrated in a normally verified after-close release **with both knobs off**, retaining the existing release checks and reporting the exact combined SHA/receipt. This review does not attest an unspecified v0.7.87 combined build, start a restart, or approve experiment activation.

Before activating collection or using P-02/P-03 to choose a trading change, return PF-01 through PF-03 and the metric-label correction with the five supplied cases passing. Preserve the 15 existing checks. Keep the scheduled daily report useful now by labeling these sections provisional and retaining all unknowns; do not infer a strategy improvement from the current all-baseline P-01 cohort.

Tests and the short P-02 note are in `reviews/profitability-cohort-regressions`. Copy `test_p02_real_payload_and_fee_conservation.py` and `test_codex_profitability_report_scope.py` to the development checkout's `backend/tests` and run them with the existing profit/observer files through the isolated test script. Nothing in this packet requests new infrastructure or changes to the day's real trades.
