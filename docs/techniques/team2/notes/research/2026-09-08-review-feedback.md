# Independent feedback on the first-clean-day review

Received 2026-09-08. Session date was not explicitly supplied in the pasted report. Scope: review feedback only; no implementation or deployment authorized by this note.

## Evidence boundary

The daily figures, incidents and F47–F63 labels come from the user's pasted reviewer report. Those findings are not present in this local judgement log. The current local checkout remains HEAD `96b67a1`, branch `codex/zargar-development`; it is not established as the team's deployed version after its eleven reported fixes. Local code supports several described failure mechanisms, but the day's executions, quotes and logs have not been independently retrieved.

Method reference: [author study](../../AUTHOR-STUDY.md).

## Overall assessment

Useful diagnosis, but do not approve all seven changes as one overnight package. Prioritize hosting reliability, truthful scoring and signal/execution separation. The two-trade day does not justify optimizing thresholds to fit it. A 94% rejection rate is not itself a defect: count distinct eligible setups and examine whether the method should have traded them.

Reported gross arithmetic reconciles: 14 x 100 x (0.61 - 0.655) = -63; 9 x 100 x (0.68 - 0.63) = +45; gross -18, approximately -66 after costs. These are executed Practice trades, not verified live brokerage transactions. If all 46 contract-sides cost 1.04, fees would be 47.84 and net -65.84, consistent with the rounded account figure. This fee assumption still needs the actual ledger. Fees matter, but gross results were already negative.

The model's summed +65% is not a portfolio return. Obtain same-contract, same-quantity and same-time comparisons with identical fee treatment before interpreting the discrepancy.

## Proposal verdicts

### F50 — target execution: support the defect fix; revise the design

The local simulation credits an intrabar high/low target touch at the target underlying price; the runner processes events on closed 2m bars. This can create optimistic simulation and late live exits. It does not establish that every such trade loses or that the first trade could certainly fill at 0.85.

A resting option sell limit and an underlying-price target are different conditions. Option premiums depend on volatility, time and quotes as well as spot; a fixed premium limit may fill before the underlying target or remain unfilled after it. Preserve the intended target as an underlying condition and evaluate a fresh-quote, reduce-only exit path, or explicitly specify a distinct premium take-profit policy. Existing platform invariants allow sub-minute exits; no new sub-minute entry path is needed.

Before release: prove the exact contract's timestamped executable bid/size near the target, crossing detection, latency, partial fills, stop/trim/flatten races, and restart reconciliation. Maintain only the remaining exit quantity and prevent duplicate exits. Do not promise an exact fill on a print. Replay without intrabar option quotes must disclose ambiguous target/stop ordering and avoid idealized fill claims.

External reference: [OIC on bid/ask and limit-order execution](https://www.optionseducation.org/news/understanding-the-bid-and-ask-prices-for-options).

### F47 — minimum target room: support the question; reject skipping a real obstacle

Casey uses nearby support/resistance as destinations and reasons for caution. If the nearest valid level leaves insufficient room, the default research alternative is to skip/degrade the entry, not select a more distant target and assume passage through the nearer level. A new opportunity beyond it requires an appropriate break/confirmation.

One ATR is a candidate filter, not a published author constant or a guarantee of option profitability. Measure remaining room from the actual entry, compare with structural stop distance and executable option costs, and validate multiple sessions. The existing HOD-substitution threshold does not prove that the same threshold is correct for rejecting planned targets. A weak/spurious pivot could instead require a better pivot-quality definition; that is a separate hypothesis.

### F61 — plumbing refusal and allowance: support with separate counters

Preserve structural pullback ordinal separately from valid opportunities, routing attempts and fills. A market pullback still occurred even if data failed; an unavailable price should not be counted as an executed trade or silently exhaust an execution allowance. This avoids both phantom spending and unlimited attempts at late pullbacks.

The IWM example is a model/live-pricing disagreement, not necessarily missing data. The local `session.py` calls `model.pick_strike` before emitting a fire, so changing the failure counter alone does not remove model pricing as a live-entry prerequisite. A rejected model estimate should be distinguishable from a fresh executable chain genuinely failing the desk's premium policy. Any retry must recheck the current setup, price, risk and freshness; never buy an obsolete signal just because data recovered.

### F62 — distinct touch episodes: support; reject today's-trades calibration target

Define approach, contact/hold, departure and a fresh return using closed bars and a documented band. Consecutive bars drifting at an EMA should not automatically be distinct pullbacks. Include moving-EMA behavior, EMA13/48/level overlap, bias resets, re-entry and restart state in tests.

Do not tune the reset to ensure the two QQQ trades four minutes apart survive. They should both fire only if each independently satisfies the same definition. Evaluate other sessions, losers and non-events as well as today's desired examples. Casey's early-pullback preference is explicit; precise state-machine thresholds remain ours.

### F56 — no-trade-zone exceptions: experiment only, split into two proposals

An explicitly confirmed rejection/bounce at a prior-day edge is method-plausible; an edge touch alone is insufficient. Keep this separate from a blanket bypass when PM range exceeds six ATRs. The latter threshold is not established by the author's sources or a single day's refusal count. It also changes as current ATR contracts/expands unless its measurement time is pinned.

Wide PM range can reflect substantial uncertainty rather than safety. Compare edge-reversal and broad-bypass variants independently across different range orderings, sessions and regimes, with fixed risk. Report incremental executable trades and net outcomes. Retain PM levels as meaningful obstacles even if an exception is eventually adopted.

### F51 — market-derived IV: high priority, with point-in-time provenance

Support improved calibration and the separation of observed from modeled outcomes. Use the relevant symbol, expiry, strike/side, timestamp, quote quality and source. A delayed or stale chain is not automatically reliable because it exposes IV. One scalar cannot reproduce all strike-specific quotes or their intraday changes. Compare modeled prices with bid/mid/ask observations; do not equate lower IV with universally higher premiums or universally inflated returns.

Local runner `_act` consumes `simulate_session` events, including fires and modeled management events. Therefore a claim that model IV has no money-path impact is too broad unless the newer deployed code proves decoupling. Pricing/sizing orders on real quotes alone does not eliminate upstream model gating.

Snapshot inputs as known at the time. Do not seed old walk-forward sessions with today's or closing chain, or recompute earlier signals using later IV. Missing historical intraday chains limit the precision of historical premium scoring. Preserve the original baseline, label model limitations and do not retroactively overwrite live outcomes.

### F49 — actual-open classification: support with snapshot discipline

Keep the 09:25 plan provisional; finalize relevant opening context from the observed 09:30 open and complete PM range through 09:29. Record when those data became available, preserve the earlier snapshot, and use the same transition in replay. Missing/corrected opening data must produce an explicit state. Do not reconstruct earlier decisions with later bars or silently reclassify an already executed trade.

## Hosting and restart incidents

The reported nine-minute outage and recurring stops deserve immediate investigation and an operational owner. They undermine a claim that the entire day was operationally clean. First preserve timestamped application/host logs and identify the actual process exit/restart cause; do not assume the previous hosting cause without evidence.

F63 needs durable recording and an explicit stale/missed/recovered disposition, not blind execution of a signal from the restart interval. Before relying on unattended execution, verify restored positions, pending orders, remaining exit quantity, stops, flattening and duplicate prevention. An external supervisor/alert can help only after its restart/reconciliation behavior is safe and understood.

Eleven deployments split the day into code/config intervals even if no numeric money rules changed. Any change in event handling can still affect trades. Request the deployment timeline and align each trade/replay to its actual version. The 17:00 plan job is not a reason to rush an exit or signal-state change; record which plan version a later deployment applies to.

## Requested evidence and sequence

1. Preserve run IDs, actual contracts, fills/fees, underlying and option quote timestamps, decision traces, deployment times and host logs. Define the denominators behind four scenarios, eight touches, 14 IWM touches and 94% refusals.
2. Reconcile the two executed trades and rebuild an honest baseline. Verify whether 0.85 was an executable option bid or another model estimate.
3. Investigate hosting/restart safety; build F49 and F51 with immutable point-in-time inputs, and F61/F62 with independently justified episode/attempt semantics.
4. Fix F50 with an explicit underlying-target execution contract and conservative replay. Validate interactions with existing exits before deployment.
5. Keep F47 thresholds and both F56 variants out of automatic promotion until multi-session comparisons support them.

Recommendation to the user: support F49/F51/F61/F62 subject to these revisions and tests; support F50's objective but require a different or clearly specified design; do not deploy F47/F56 as written. No changes or team messages were sent by this review task.
