# 3. Pricing harness: what was wrong, the frozen conventions, the regressions, and what changed

Every replay number in this package is **simulated execution on real trade prints**. It is not a quote, not a fill and not a
forecast of fills. Code: `harness/realmodel.py` (v2). The v1 harness and its results are kept unchanged in `harness/v1/` and
`results/v1/`.

## Defects in the first harness (all confirmed by reading `harness/v1/realmodel.py`)

| # | Defect | Effect |
|---|---|---|
| 1 | **Future price in the selection.** The strike was chosen on the OPEN of the option minute that STARTS at the decision time, and up to two minutes later, while the entry kept the decision timestamp. The contract was picked with a price that did not exist when the read decided | look-ahead in contract choice |
| 2 | **Unavailable price became $0.00.** `mark()` returned 0.0 when no print was found, so a missing exit was a 100% loss and a missing management mark looked like a -100% premium stop | invented prices |
| 3 | **Target-touch VWAP presented as the fill.** One number, no statement that intraminute order is unknown | hidden assumption worth several points of mean return |
| 4 | **Unbounded price age.** Management marks carried the last print for up to five minutes; exits up to three | stale marks in stops and trims |
| 5 | **One execution model presented as correct.** Zero extra slippage was called the "central case" | false precision |

## Frozen conventions (v2)

T = the read's decision time, the close of a 2m bar.

| Operation | Price used | Permitted age / window | If unavailable |
|---|---|---|---|
| Contract SELECTION at T | close of the latest option minute that ENDED at or before T | at most 2 minutes old | the strike is not eligible; if none is, the entry is refused: `no_observed_contract_in_band` |
| Entry EXECUTION after T | open of the first option minute with a print in [T, T+2 min) | 2 minutes | refused: `no_execution_print` |
| Eligibility recheck at execution | the execution price must still be within [premium floor, target x 1.5 chase cap] (the live order is a limit at the cap) | — | refused: `refused_above_chase_cap` / `refused_below_floor` |
| Times carried | `observationTs`, `executionTs`, `observedPx`, `execPx`, `execLagMin` on every trade (`pricing` block) and every refusal (`pricingLog`) | — | — |
| MANAGEMENT mark at a 2m close (premium stop, trim cue, add) | close of the latest option minute INSIDE that 2m bar | 2 minutes | UNKNOWN (NaN): no premium-based decision on that bar; counted |
| DECISION EXIT (candle stop, premium stop, trim, flatten) at T | open of the first option minute with a print in [T, T+5 min) | 5 minutes | UNKNOWN: the trade is CENSORED and reported apart; never priced |
| TARGET exit (the read books it inside the 2m bar ending at T) | three scenarios, never one fill: `proxy` = VWAP of the option minute in which the underlying first touched; `bar_close` = a decision exit at T; `touch_high` = the HIGH of the touch minute | touch minute only | falls back to `bar_close` |

`bar_close` and `touch_high` are file-named `conservative` and `optimistic`; on this data `bar_close` is NOT the lowest of the
three (price often continues through a target), so the three are reported as scenarios, not as a bound in a fixed order.

## Regressions (`harness/test_pricing_boundaries.py`, synthetic prints, no network or database): 8 passed

| Boundary | Test |
|---|---|
| Future-price selection | `test_selection_never_uses_a_price_printed_after_the_decision`, `test_a_contract_seen_only_after_the_decision_is_not_eligible` |
| Stale marks | `test_a_stale_observation_is_not_carried_into_the_selection`, `test_a_stale_print_is_not_carried_into_a_stop_or_trim_mark` |
| Time-dependent eligibility | `test_time_dependent_eligibility_is_rechecked_at_the_execution_price` (chase cap, no print, one-minute lag carried explicitly) |
| Missing marks | `test_a_missing_management_mark_is_unknown_never_zero`, `test_an_exit_without_a_print_is_censored_not_priced` |
| Target-touch ambiguity | `test_target_touch_is_a_bounded_scenario_not_one_fill` |

Run: `PYTHONPATH=<worktree>/backend python -m pytest harness/test_pricing_boundaries.py -q -p no:cacheprovider -c /dev/null`.
The first selection test fails against `harness/v1/realmodel.py` by construction (v1 picks the 102 strike on the post-decision print).

## What changed after the correction (baseline, 2026-05-07 to 2026-09-18, no extra slippage, $1.04 fee, `proxy` target scenario)

| | v1 | v2 |
|---|---|---|
| Trades | 333 | 332 |
| Entries in both | 331 | 331 |
| Entries only in this version | 2 | 1 |
| Same entry, different strike chosen | — | 12 |
| Same entry, different entry price | — | 12 |
| Same entry, different result | — | 12 |
| Mean net return per trade | -3.76% | -3.71% |
| Mean on the 331 common entries | -3.68% | -3.60% |
| Entries executed in the decision minute | not recorded | 332 of 332 (no lagged execution) |
| Selection print age | not recorded | 1 minute for all 332 |
| Entries refused for pricing reasons | not distinguished | 13 no observed contract in band, 2 no execution print |
| Unknown management marks | silently priced | 1 |
| Censored trades (exit without a print) | silently priced | 0 |

The look-ahead was real but small on these contracts because SPY, QQQ and IWM 0DTE options near $0.60 print every minute. The
correction matters more for what it makes visible (times, refusals, unknowns) than for the mean. The larger effects are the target
scenario and the cost assumptions, shown on page 5.

## What had been examined before each registration (so no result is mistaken for confirmation)

| Registration (commit) | Already examined when it was frozen | Not yet examined |
|---|---|---|
| Round 1, H1 to H5 (5bc329e3) | Actual fills. The BASELINE on the whole window 05-07 to 09-18, including what later became TRAIN, HOLDOUT and the post-09-14 dates, with both pricing methods. Baseline subgroup tables (setup, symbol, hour, hold, exit) on the whole window. The fidelity audit | Any variant arm on any window |
| Round 2, E1 and E2 (038ab13f) | All of the above; round 1 arms on TRAIN; the author ledger, whose dates lie in HOLDOUT and after: the holdout is CONTAMINATED as a source of these two ideas, and was declared so | E1 and E2 on any window |
| Round 3, X1 and X2 (2db47a49) | All of the above; rounds 1 and 2 on TRAIN; the exit-free horizon table on TRAIN, which is what suggested brackets: TRAIN is therefore not independent evidence for X1/X2 either | X1 and X2 |
| This correction pass | Everything above, plus the v1 results of all nine arms on TRAIN. The v2 re-run of the nine arms is a RE-MEASUREMENT under corrected pricing, not a new test; no value, definition or criterion was changed | The holdout for any ARM: still never opened. C2 key levels on or after 2026-09-14: never run |

The baseline's holdout and post-09-14 figures are descriptive (they were seen before anything was registered). C2's sealed
validation window (2026-09-14 to 10-09) is untouched: `key_levels` stayed `off` in every run in this package.
