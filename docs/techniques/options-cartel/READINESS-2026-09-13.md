# September 13 correctness release and Practice protocol

This implements the corrections from [the final review](FINAL-REVIEW-2026-09-13.md). Runtime version, arming and deployment evidence belong to the release handoff, not this implementation description.

## Correctness

- Automatic preparation saves actual contract-selection limits into execution. Premium, delta, spread and current DTE are checked again before entry, including at final broker dispatch. Open interest remains selection-time evidence because its provider has no independent freshness timestamp. Protective exits do not inherit entry-only liquidity gates.
- Older automatic option arms without saved contract policy refuse entry. **Review entry contract limits** applies only to unused, waiting automatic Practice arms. It preserves the contract, targets and exit campaign, keeps/tightens debit limits and journals the review. Paused, changed, submitted, held or already-reviewed campaigns cannot be silently rewritten.
- Target discovery retains confirmed nearby directional pivots across each candidate's geometry, including the ignition candle. Review repairs omissions in saved analyses. Fibonacci fallback uses the candidate's boundary and cannot hide confirmed nearer supply/support. Existing plans remain immutable.
- Pending activation refreshes session readiness after contract selection. Original creation governs invalidation; a separate cutoff suppresses missed entries. A breakdown during a contract lookup cannot be erased by the later arming timestamp.
- Daily-analysis cache reuse requires provider/dataset identity in both directions. Native access denial explicitly switches datasets, including during multi-symbol collection. Ambiguous old provider labels are not compatible cache evidence.

## Whole-contract Practice exits

Settings → **Plan policy and exit allocations** exposes `whole_contracts_v2`. This is an engineering experiment; Live retains the original policy.

| Filled quantity | First target | Extension | EMA8 | EMA21 | EMA50 |
|---:|---:|---:|---:|---:|---:|
| 1 | 0 | 0 | 0 | 0 | 1 |
| 2 | 1 | 0 | 0 | 0 | 1 |
| 3 | 1 | 0 | 1 | 0 | 1 |
| 4 | 1 | 1 | 0 | 1 | 1 |
| 5 | 1 | 1 | 1 | 1 | 1 |

The first trim must actually fill before stop-to-entry and dependent management advance. One contract cannot scale out and retains its final EMA/protective/expiry exit. Four or more keep the original rounding. Existing campaign snapshots remain `legacy`; selecting the new setting affects new plans. A target touch is never a fictional fill. Do not increase budget or select poor contracts merely to fund more exit legs.

## Evidence collection

Enable **Option quote recording** in Cartel Settings. It consumes already-tracked selected contracts; it creates neither orders nor an independent data subscription. Identical source observations are deduplicated, first availability is retained and missing observations have gap records. Sampling stale data does not make it fresh. Stored premium valuation pages the campaign window instead of rejecting it at 40,000 samples.

Replay defaults to original confirmed filled quantity when known, otherwise a current fresh budget/equity estimate explicitly distinct from historical funding. If neither is available it models one hypothetical unit. Explicit overrides remain hypothetical. Premium valuation preserves that basis and cannot present a different contract as the funded vehicle. Recorded quote valuation still does not model resting-order queue/depth or actual broker fills.

Plans preserve advisory industry/leader observations and a preparation-policy cohort hash. Coverage includes evaluated names that failed setup checks and keeps missing histories separate. Industry membership is only a theme proxy. Groups with fewer than three strength observations are unranked. The evidence does not reorder the executable shortlist or grant permission. Retained campaigns belong to their original preparation cohort; the hash is not a snapshot of every shared runtime constraint.

Use twenty consecutive sessions as a collection checkpoint, not graduation. Preserve the full funnel, including rejected/no-fill opportunities. Compare one frozen challenger at a time using exact contracts/quantities, costs, separate realized and bid-marked P&L, a log of every experiment and an untouched subsequent period. Quantity-correct exits are the first proposed challenger. No automatic risk escalation or Live promotion is implemented.

## Source update

Sean's September 13 explanation reinforces market, theme, leader, setup, price/volume and predefined risk. The advisory evidence is a partial representation; industries do not capture every theme/catalyst. No new post validates the app's exact thresholds. [September 13 system description](https://x.com/SRxTrades/status/2099241717983486243).

## Next-session operation

1. Deploy; verify backend/UI versions and restored arms, positions and orders.
2. Enable recording and select the Practice whole-contract alternative if running that experiment. Retain risk, contract and entry thresholds.
3. Explicitly review legacy unused arms. Fresh preparation preserves existing campaigns and cannot replace their exits implicitly.
4. Prepare the intended session. Check horizon, source coverage, account, saved contract limits and actual Armed status. A partial run may contain valid arms plus exclusions.
5. At the open, verify exchange-bar and live option-quote delivery. Future signals, fills and returns cannot be certified on Sunday.

Acceptance covers target causality, final-dispatch quote changes, pending invalidation, migration races, integer exits, replay quantities and provider/quote identity. See the deployment handoff for checks actually run and unresolved conditions.
