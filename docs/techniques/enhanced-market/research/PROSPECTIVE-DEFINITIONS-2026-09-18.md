# EM prospective definitions - frozen 2026-09-18 (integrated delivery)

Frozen BEFORE any validation data is collected. September 15-18 are exploratory fixtures: they shaped these
definitions and therefore can never validate them. Nothing here is a live rule; every item is order-free or
observation-only until a separate activation decision. A definition is changed only by a NEW dated file with a new
version string - never by editing this one, and never after looking at the validation sample it governs.

## Evaluation horizon (declared now)

| Item | Value |
|---|---|
| Validation sample starts | the first regular session after the release carrying these versions is deployed AND the relevant knob is on |
| Minimum horizon | 20 regular sessions, or 60 baseline fills, whichever is LATER (a review, never a promotion) |
| Excluded sessions | none silently. A session with a recorder outage, a host stall or a data gap is listed with its reason and its coverage |
| Primary measure | after-cost dollars of the EM Practice book (execution ledger), with drawdown; model cost reported beside it, never netted silently |
| Secondary measures | proxy R under `capacity-v1`; coverage and unknown counts for every comparison |
| Stop rule | none tied to results: the sample is not stopped early because it looks good or bad; safety halts are the existing loss halts |
| Disputed evidence | reported separately (ORCL 2026-09-17 stays flagged); never overwritten |

## Frozen versions

| Version | What it fixes | Where |
|---|---|---|
| `em-prep-policy-v1` | deterministic eligibility = valid geometry + stop present + targets available + grade floor B; the model review is ABSENT, not an approval or a veto | `technique/preparation_policy.py` |
| `conditional-review-v1` | clause classifier (`not_yet_triggered`, `session_timing`, `substantive`); a reason that opens with a trigger id reaches that trigger only; plan-level reasons reach all | same |
| frozen exception features | reward to risk at TP3 at least 3.0, level touches at least 2, anchored targets (frozen in `em_prep_ablation`, 2026-09-18) | `tools/em_prep_ablation.py` |
| `capacity-v1` | 10 slots (100% gross / 10% per symbol), new entries stop at -1.5R realized (3% halt / 2% risk), one open position per plan | `tools/em_prep_compare.py` |
| `source-scenarios-v1` / `source-plan-match-v1` | evidence-verified ticker, strike is not a target, level-vs-strike conflict, branches, usable time, region tolerance 0.5% | `technique/source_scenarios.py` |
| `source-continuation-v1` | app geometry only from an `aligned` saved trigger; morning idea expires 11:30 ET, `0dte` at the close, `swing` not evaluated intraday | `technique/source_candidate_policy.py` |
| `requalification-v1` | fresh pivot pair strictly after the invalidation, pivot window 3, production stop buffer and 3% stop cap, author targets only, R2 unchanged, one child per branch per session | `technique/requalification.py` |
| `first-sale-v1` | R measured at the rung where the FINAL quantity exits; verdict on the runner's entry; unknown never refuses | `technique/first_sale.py` |
| `book-snapshot-v1` / `profit-capture-reducer-v1` | quote age at most 10 s, basket skew at most 5 s, covered side only, displayed size caps quantity, pending quantity reserved | `technique/profit_capture.py` |
| `model-costs-v1` | four separate cost kinds; no price without a dated row | `technique/model_costs.py` |

## Fixed research strata (no combinations beyond these)

Reported descriptively per session once forward data exists. Winners a stratum would remove stay in the table.

1. **Trend-aligned long bounce**: long `bounce` whose saved 1h trend fact is `uptrend` at plan time, against all other long bounces.
2. **Second lower-level bounce after a same-symbol loss**: a long bounce on a lower saved level fired after the same symbol stopped out earlier in the session (PANW b2 then b3 on 2026-09-18 is the motivating fixture), against first bounces.
3. **Contract payoff after spread and fees at the real first sale**: `first-sale-v1` payoff proxy net of spread and fees, by exit rung, against the realized result.

These are hypotheses, not gates. No threshold is tuned to the four fixture sessions, and no further combination is added
without a new dated definitions file.

## What is NOT claimed

- No equivalence or profitability claim follows from replan agreement or from underlying replay R.
- A deterministic selection that matches or beats the model on proxy R in four sessions is not evidence that removing the model improves after-cost dollars.
- The author's trading result is unknown; platform P&L is not his result.
