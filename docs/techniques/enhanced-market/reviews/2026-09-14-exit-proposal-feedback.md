# EM exit proposal: measurement accepted, conclusions need correction

Reviewed the exit sections of `STRATEGY-PROPOSAL-2026-09-14.md` at **b7d8a574635aa0d6d2d6a4be0538dc06462c43e6**, against `2026-09-14-trade-exit-reassessment.md`. This is a bounded research review. It does not reopen the accepted worker release, authorize an exit-policy change, or request additional infrastructure beyond the observations needed for the proposed comparison.

**Verdict:** proceed with an order-free, exit-only forward comparison of the current policy and fresh-observation target detection. Correct the historical illustrations below first. Keep target-distance analysis descriptive until it has a frozen rule and independent validation; do not introduce a new arm-time refusal now.

## EP-01: HPQ supports the experiment, but its $3.10 result is conditional

Proposal lines 69 and 75-78 mix two execution mechanisms: a resting share limit and a fresh-observation exit submitted after the target is observed. They are not the same experiment. A bar high of 35.19 establishes a stored trade-price excursion above the 35.1462 target; it does not establish the bid, queue position, executable size, or the observation available to the engine before that bar completed.

The arithmetic is correct **under the stated hypothetical fill**:

`-$7.193 + 30 * ($35.1462 - $34.803) = +$3.103`.

That assumes all 30 shares fill at exactly the unrounded target, the remaining 70 exit at the actual price, and commissions are unchanged. A real resting limit needs a valid price increment and may fill partly or not at all. A quote-triggered submission needs a later executable quote and submission latency; it cannot inherit the resting-limit fill.

**Correction:** label $3.10 an arithmetic illustration of an assumed share fill, not a demonstrated outcome of fresh-observation execution. Replace "one observed beneficiary, no observed loser" with "one clear completed-bar delay case; the net benefit of earlier execution is unmeasured." For HOOD and INTC, unchanged target prices do not mean unchanged results; earlier option bids could produce better or worse proceeds. The existing missing-bid disclosure is appropriate but should apply to the headline too.

## EP-02: the structural comparison is not internally defined yet

Proposal lines 82-94 say the first saved opposing level at least 1R away replaces TP1. HPQ's selected level is farther away than its existing TP1, yet the table says no change because the old TP1 was closer. Under the written replacement rule, its reached TP1 trim would disappear. The table is only consistent with an unstated **earlier-only** rule that retains the original target if no qualifying closer level exists.

The policy also specifies full exit at the structural level for one contract, but does not unambiguously say what happens to two contracts, which currently exit at TP2. Replacing TP1 alone cannot answer the two-contract HOOD September 10 question.

HOOD September 14's structural touch is reported in the **09:35 entry minute**, while the actual entry occurred at **09:35:21.621**. Minute OHLC cannot establish whether the touch came before the fill. The following minute's $3.95 print is not a bid available at the structural trigger. Therefore "roughly neutral" is not established; the historical effect is **unscorable from the stated evidence**.

**Correction:** either defer this comparison explicitly, or define earlier-only selection, no-eligible-level fallback, and one/two/three-plus quantity handling before recalculating. Report missing event ordering and bids as unknown. Do not generalize this limited saved-level rule into "structural exits cannot help HOOD" or "only fixed-R/premium exits could help": the earlier review identified contemporary critic support levels, but those would require an independently specified eligibility and provenance rule before inclusion. They must not be inserted just to rescue this loss.

## EP-03: target distance is a useful diagnostic, not an approved new gate

Proposal lines 98-100 and 119 suggest choosing N from sweeps. Using more historical rows does not by itself avoid fitting past outcomes. Existing sweep versions changed, and underlying R simulations do not establish option net profitability or faithful availability of source inputs.

**Correction:** first record the distance to the actual quantity-dependent full-exit rung, with intended and final entry basis separated. An arm-time quantity can differ from the final filled quantity. Record the denominator, stop, target rung, vehicle, final quantity, session, source availability and policy/sweep version. For a future threshold proposal, freeze the calibration dates, untouched chronological validation dates and selection criterion before selecting N. Include every eligible setup, nonfill and rejected candidate; report trades removed, losses avoided and gains sacrificed. A distance gate could further reduce the already scarce trades, so frequency is an outcome, not just R per retained trade.

No N is accepted here. A diagnostic flag must not reject an arm, change a target, alter size, or relax the existing minimum-R requirement.

## Exact first forward comparison

1. **Scope and identity.** Observe all actual EM Practice admissions in the registered forward cohort. Copy each actual instrument, entry fill/time, quantity, direction, plan revision, targets, stop and flatten policy into a research row. Give the experiment a fixed version. Keep shares and options separate in summaries. Never create orders, amend live plans, consume cash/risk budget, or arm source scenarios from this observer.
2. **Control.** Retain the current production behavior and recorded fills as the accounting baseline. Also record when its target evaluator first had an eligible observation; observed fill P&L and modeled shadow proceeds are different evidence classes.
3. **Execution variant.** Change only when the same targets are evaluated: first qualifying fresh underlying observation after entry. Freeze the underlying price field, source, maximum age, duplicate handling and stop-versus-target precedence before the first observation. Preserve quantity-aware rungs, stop logic and session cap. A resting share limit would be a separate variant and is outside this first comparison.
4. **Observation record.** At both control and variant decision times, save source and received timestamps, observation ID, underlying decision price, instrument bid/ask and displayed sizes, quote source/age, policy version and reason. Record detection, actual submission and actual fill times separately. Use only quotes already available at the decision time; never a later bar high or a later-arriving quote backdated to the trigger.
5. **Cost and liquidity.** For sell-to-close, a contemporaneous bid is a modeled liquidation opportunity, not a proven fill. Freeze a latency/slippage convention and include the instrument multiplier and commissions. Do not count the entire quantity as executable if displayed size is insufficient; show the covered quantity and unresolved remainder. Missing/stale quotes remain unscorable, with the next eligible observation recorded separately rather than credited at the earlier target price.
6. **No hindsight selection.** Include every covered admission, including existing winners, no-target trades, partial exits and missing-data rows. Do not require HOOD/INTC to remain winners by selecting the rule after seeing their outcomes. Report any gains sacrificed. Keep observing each shadow position until its own terminal event or the same session cap, even if the production position already closed.
7. **Daily output.** One timeline per admission plus paired detection delay, quote coverage, modeled net difference where scorable, worst loss, observed bid-based favorable movement/giveback, holding time and coverage exclusions. Publish counts and missing data alongside aggregates. A first diagnostic review can occur after the next ten sessions; that review date is not automatic permission to activate a rule or proof of an edge.

These are documentation and measurement corrections. The immediate useful work is collecting the first prospective paired observations, not another broad implementation cycle.

## Sources and review limits

- Proposal at reviewed commit: `docs/techniques/enhanced-market/reviews/STRATEGY-PROPOSAL-2026-09-14.md`, exit sections lines 63-121.
- Prior ledger and evidence audit: `C:/Cursor/zargar-codex/docs/techniques/enhanced-market/reviews/2026-09-14-trade-exit-reassessment.md`.
- Governing historical change record: `docs/techniques/enhanced-market/TRADING-RULES.md` at the reviewed commit, section 5; historical stop, target-rung and sweep-definition changes are explicit there.
- Checks here: read-only Git/document review and decimal arithmetic. No runtime database query, model call, test suite, deployment, setting change, monetary repair, or source backfill was performed by this review.
- Active documentation folder: `C:/Cursor/zargar-codex`; branch `codex/zargar-development`. Other work and all runtime checkouts were preserved.
