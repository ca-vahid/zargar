# Sean / Options Cartel profitability research — September 15, 2026

Research-only review against checkout `b691afc` in `C:/Cursor/zargar-codex/.cache/cartel-profitability-20260915`. No strategy/settings changes, implementation, external messages or trading actions were performed. The parent review supplies today's no-long-trade premise; this subreview did not independently reconstruct today's account ledger.

## Main conclusion

**Today's authored evidence supports patience, not a requirement to make the system trade.** Sean explicitly described cash and doing little as retail advantages in the poor environment on September 15. His other September 15 post emphasizes waiting for setups, following stops and avoiding FOMO. A no-long-trade day is therefore compatible with the method. It does not, by itself, prove either that our gate is optimal or that profitable opportunities were missed.

The worthwhile research questions are whether a small, predefined exception cohort beats remaining in cash; whether a properly separated bearish profile works in genuinely bearish regimes; whether group/leader selection predicts follow-through better than ranking by chart target distance; and whether market-dependent exits and vehicle selection improve net results. These questions need contemporaneous options evidence and controlled comparisons, not a larger trade count.

## Primary-source evidence checked in this session

Search-engine queries for both accounts and September 15 did not expose reliable dated results. Direct Chrome access to the original X profiles succeeded. The following posts were then opened and their text/date checked. Times below are the browser's displayed Pacific local times. This is bounded public-profile/post coverage: it is not an export of all posts, replies, deleted content, videos, private-room alerts or fills. Image attachments in this pass were not decoded into execution records.

| Date / displayed time | Original source | Evidence and practical interpretation |
|---|---|---|
| Sep 15, 2026, 13:00 PT | [Cash is a position](https://x.com/SRxTrades/status/2099951391816999321) | Sean describes the environment as poor and says retail can benefit from doing little or nothing. Direct support for retaining a cash benchmark; no numerical market threshold or proof of an actual cash-only account day. |
| Sep 15, 2026, 10:00 PT | [Discipline and risk-taking](https://x.com/SRxTrades/status/2099906095279989015) | Waiting days for a setup, staying in cash when nothing is there, following stops and avoiding FOMO are explicit. This is process guidance, not a signal or a daily P&L statement. |
| Sep 14, 2026, 16:30 PT | [Adapt holding and strength trims to follow-through](https://x.com/SRxTrades/status/2099641849212293453) | Clean trends and working breakouts warrant more time; choppy markets whose moves are sold into warrant quicker strength realization while retaining some exposure. No mandatory holding-day cutoff, new numerical target or fully allocated exit schedule is supplied. |
| Sep 14, 2026, 11:30 PT | [Selective leader examples during the morning decline](https://x.com/SRxTrades/status/2099566349320438117) | Sean reports SPCX after a VWAP reclaim, INTC through leveraged shares after a 15m pivot, an addition to existing BMNR, and cybersecurity strength. These are different entry/vehicle/position contexts from a fresh standard Cartel option breakout. They motivate research about leaders and expression; they are not interchangeable benchmark fills. |
| Sep 13, 2026, 14:00 PT | [Full momentum framework](https://x.com/SRxTrades/status/2099241717983486243) | Market → theme → leader → setup → price/volume trigger → predefined risk. EMA context is graded, group participation matters, and recurring leaders may matter more than pattern appearance. Targets are prior highs/supply/weekly levels/extensions; stops depend on structure, commonly day low. Exact algorithmic weights, sizing fractions and thresholds remain unspecified. |
| Mar 30, 2025 | [Original bearish-market rule](https://x.com/SRxTrades/status/1906420174246510756) | Expanded original post explicitly supports downside trading when SPY/QQQ are below 8/21/50 EMAs. It does not say every mixed or choppy session should automatically become a short day. |
| Mar 30, 2025, 11:56 PT | [Original bearish scanner text](https://x.com/SRxTrades/status/1906420180030513310) | Text specifies price >$3, capitalization >$300M, volume >500K, relative volume >1, negative change and price below 8/21/50 EMAs. The previously documented screenshot disagreement on EMA periods must remain versioned; this proposal uses the text variant explicitly. |
| Mar 30, 2025 | [Weak-sector/weak-stock QCOM example](https://x.com/SRxTrades/status/1906420190608556506) | A distribution base and relative weakness inside a weak semiconductor group illustrate the bearish hierarchy. This example does not establish a universal option strike, DTE, entry fill or weighted return. |

The Options Cartel profile's newest visible non-pinned post was still its [September 8 DRAM swing claim](https://x.com/TheOptionCartel/status/2097414673662718231), alongside the pinned public-trades spreadsheet link. No September 15 account ledger or new dated performance post appeared in that inspected profile slice. That is a retrieval boundary, not proof that none exists. Promotional percentages do not establish quantities, weighted exits, fees, remaining exposure or a complete daily account return. We do not use them as profitability labels.

## Comparison with current implementation

- `screen.py:75–100` classifies each fresh benchmark as above every selected EMA, below every selected EMA, or mixed. Moderate permits longs only when one benchmark is above 8/21/50 and both exceed 50. This is a disclosed engineering permission rule; it is narrower and more binary than Sean's qualitative EMA ladder.
- `preparation.py:342–352` permits executable direction only when regime is long or short. Mixed/unknown becomes blocked research in the configured research direction, ordinarily long. The code already supports genuine bearish regimes; an absence of short candidates on a mixed day is not proof that bearish execution is missing.
- `quality.py:8–20` ranks by structural first-target R, then directional relative strength and daily volume. This ratio describes geometry. It is not a probability that the target will be reached, an estimate of option expectancy, or a substitute for strong theme participation.
- `leader_context.py` stores industry/group strength, participation and leaders as advisory evidence. The actual executable ranking does not put those group observations first. Industry is also an incomplete proxy for themes such as cybersecurity, crypto or nuclear.
- `automatic_plans.py` uses independent engineered contract preferences and the saved dollar budget. The author's September 14 examples include a VWAP reclaim, a 15m pivot, leveraged shares and adding to an existing position. Copying those examples into our breakout/call cohort would change several variables simultaneously.
- Existing source-version exits and whole-contract rounding are fixed by campaign. One option contract cannot realize a fractional strength trim. The September 14 APA loss, first target never reached, did not test the new two-/three-contract exit ladder; the repository's dated EOD audit already records that limitation.

Do not reinterpret today's zero new longs as zero opportunity, nor as evidence that a particular relaxed rule would have made money. Both assertions require a correctly timed alternate opportunity set and executable vehicle outcomes.

## Five testable experiments

All experiments below are **proposed offline/prospective research**, not permission to alter Practice or Live. Numerical challenger definitions are ours and must be frozen before observing their evaluation period. Run one challenger at a time against the unchanged baseline; do not combine winning settings after seeing outcomes.

### E1 — Graded market permission versus the cash benchmark

**Hypothesis:** A narrowly defined reduced-debit long cohort during cooling-but-intact index trends may add net expectancy without the drawdown of unrestricted weak-market longs.

**Control:** Existing strict/Moderate market gate and existing no-entry outcomes.

**Single challenger:** On sessions rejected as mixed, allow research-only candidates when both benchmarks remain above their 50 EMA and at least one is above its 21 EMA, using **one quarter of the existing per-trade debit budget**. Keep the same candidate pool, target/stop geometry, execution timeframe, confirmation, contracts, entry cutoff and exit policy. No extension to missing/stale benchmark data or benchmarks below 50. If the reduced budget funds no permitted whole contract, record no trade; do not pick a lower-quality cheap contract to force inclusion. The one-quarter amount and exact combination are experimental, not an authored number.

**Measure:** Incremental net P&L relative to cash on the added cohort, net return per maximum debit, drawdown, stop-out rate, gaps, quote availability and the proportion of otherwise qualifying setups that remain unaffordable. Retain distinct strata for below-8/above-21 and below-21/above-50 states rather than pooling away regime differences.

**Acceptance:** After the preregistered sample-size/stopping rule, incremental net expectancy must be positive after fees and conservative spread/slippage, its session-block uncertainty interval must support improvement, and the predeclared drawdown budget must be respected. Repeat in an untouched later period. If evidence remains weak, the baseline remains cash. More signals alone fails this experiment.

**Source basis:** September 13 graded EMA context; September 15 explicitly validates cash when conditions are poor. Neither source authorizes arbitrary weak-market risk.

### E2 — A dated bearish profile, not “no longs means buy puts”

**Hypothesis:** Sean's explicit weak-stock/weak-group filters can improve downside follow-through compared with the generic directional mirror, during genuinely bearish benchmark regimes.

**Control:** Existing short-direction general profile when its present benchmark gate allows shorts.

**Single challenger:** Version the March 30 **text** screen: negative change, relative volume >1 and price below stock 8/21/50 EMAs, with the authored liquidity/capitalization screen. Retain the existing strict below-8/21/50 benchmark requirement, completed breakdown entry, session-high stop, measured support targets and current put affordability/delta/spread/DTE constraints. Do not silently substitute the different scanner-image EMA variant. Mixed days can gather bearish research but remain non-executing under this test.

**Measure:** All eligible weak-stock candidates, breakdowns, data/contract exclusions, exact put quantity and option bid-path outcomes. Compare net expectancy/drawdown against both the baseline short cohort and cash. Report results by bearish regime and group, including rallies that stop puts out.

**Acceptance:** Demonstrate positive cost-adjusted incremental expectancy in an out-of-sample bearish cohort with sufficient executable quote coverage. A falling underlying or an attractive retrospective put high is not a pass. If no qualifying bearish sessions occur, the result is untested—not a reason to widen the gate.

**Source basis:** Original March 30 framework/scanner. No September 15 authored post observed here instructs indiscriminate bearish exposure.

### E3 — Leader/group-first ranking versus target-R-first ranking

**Hypothesis:** Among already eligible setups, strong groups and their leaders predict profitable continuation better than the largest nominal distance to the first target.

**Control:** Present structural-target-R → individual RS → volume order, with the same focus count and capacity rules.

**Single challenger:** Rank the same eligible pool first by the existing as-of group median directional RS (only groups with at least three observations), then individual directional RS, then existing target R and volume. Missing group evidence remains explicitly unranked. This uses current measurable proxies rather than pretending to infer institutional ownership from volume. Freeze mappings and membership snapshots; record recurring leader membership as evidence without silently increasing holding life or reserving extra slots.

**Measure:** Net realized plus separately reported executable bid-marked campaign outcomes under identical contracts/quantities/exit policies; target-before-stop rate; MFE/MAE; time to follow-through; overlap and replacement of the two top-five lists; group concentration; data/contract exclusion rates. Segment confirmed-pivot targets from Fibonacci fallback geometry. Preserve the nearest real supply/support in both arms.

**Acceptance:** The leader-first ordering must improve cost-adjusted outcomes across an untouched subsequent period without simply concentrating in one exceptional winner or changing the selection denominator. Run leave-one-group and leave-largest-winner diagnostics. If ranking does not improve expectancy, retain the existing order and keep group context advisory. This experiment does not grant access through a failed market, data or geometry gate.

**Source basis:** September 13 explicitly places theme and stock leadership above pattern perfection; September 14 provides dated examples of semiconductor, crypto and cybersecurity attention. Those names are examples, not permanent screening membership.

### E4 — Faster strength realization in weak follow-through, using feasible quantities

**Hypothesis:** In a predeclared weak-follow-through regime, realizing a larger portion at the same first resistance target may reduce give-back enough to improve net outcomes despite smaller participation in later trends.

**Control:** Current campaign's source-version allocation.

**Single challenger:** For campaigns with **at least four actually funded contracts**, sell approximately half at the same first target instead of approximately one quarter; allocate the remainder across existing later rungs in their existing relative proportions, with the complete integer allocation snapshotted before entry. Keep targets, entry, initial stop and final EMA policy unchanged. Require the first trim's actual fill before stop-to-entry. Freeze the weak-regime definition from information available before the trade—for example the same EMA state used in E1—rather than deciding after price reverses.

One-, two- and three-contract positions are not silently included in this comparison: one cannot trim, and the existing v2 two-/three-contract schedule is already a separate experiment. If the present budget rarely funds four contracts, this trial accumulates slowly; that is not permission to increase budget.

**Measure:** Weighted realized returns, runner contribution, gain given back after first target, stop-at-entry exits, transaction costs and maximum drawdown. Record unchanged opportunity counts and compare on the exact same entry cohort.

**Acceptance:** Improvement must survive fees, actual integer allocations and a later holdout; report the cost of forfeited large winners. A higher win rate with worse net expectancy fails. No post-hoc shortening of losers or fictional fractional option sales.

**Source basis:** September 14 explicitly contrasts faster strength trimming in chop with longer holding in clean trends. It supplies no universal percentage; the half-allocation challenger is a separately labeled engineering choice consistent with earlier dated source variants, not a new September 14 universal rule.

### E5 — Plain shares as an expression alternative when no suitable option fits

**Hypothesis:** Some valid directional long setups are better expressed through affordable ordinary shares than through an unsuitable cheap option or complete omission.

**Control:** Current option-selection result, including no trade when no permitted contract exists.

**Single challenger:** For otherwise eligible long setups rejected solely because no suitable option fits the existing premium budget/contract constraints, model ordinary unlevered shares at the same timed underlying signal, within the same maximum cash-debit cap and current share risk rules. Retain the same underlying invalidation and reviewed targets; snapshot feasible whole-share exit quantities. Do not loosen option delta/DTE/spread/OI or introduce leverage. Equal cash debit is explicitly not equal leverage or equal expected stop loss, so report both debit-normalized and stop-risk-normalized results.

**Measure:** Incremental net dollars relative to skipping, return per maximum cash debit, drawdown/gap risk, transaction costs, actual funded quantity and performance relative to any permitted option available at the same time. Include all blocked names and missing evidence, not only stocks subsequently highlighted as winners.

**Acceptance:** A prospective paired evaluation must show positive incremental net expectancy and acceptable downside after costs. Ordinary shares must be fundable under the existing budget without moving stops or increasing exposure. No historical close-price fill substitution and no 2× ETF substitution. If contemporaneous prices or source identity are absent, leave the outcome unknown.

**Source basis:** The author's September 14 post demonstrates that expression choice is part of his discretionary practice, but its leveraged-share example is not permission to add leveraged instruments. Earlier source review also records a shares-versus-expensive-options choice; current universal option preferences remain engineering assumptions.

## Measurement rules for every experiment

1. Register the hypothesis, exact policy/version, dates, denominator, stop rule and acceptance criteria before collecting the evaluation period. The existing 20-session research checkpoint is a collection review, not statistical proof or graduation.
2. Retain every discovered/eligible/excluded/pending/no-fill opportunity, with decision-time source/availability timestamps, provider identity and code/config versions. Missing data is a separate category, not a loss, win or zero-return fill.
3. Use the exact option/share expression, funded whole quantity, bid/ask, fees and slippage. Separate realized P&L, open bid marks and hypothetical outcomes. Underlying target R cannot stand in for option return.
4. Treat overlapping names and same-day/group trades as correlated observations; estimate uncertainty by session/group blocks rather than pretending every candle is independent. Report concentration and results without the largest winner.
5. Price both control and challenger under the same causal data/fill assumptions. Obtain sufficient future evidence; no source promotional percentage, highest trim, chart maximum, later screenshot or anecdote can fill missing observations.
6. Maintain current execution protections throughout research: no stale benchmark permission, no retrospective entries, no fabricated volume, no new permissions, no automatic risk escalation or Live promotion. Changes require a separately reviewed implementation and evidence.

## Recommended research order

Start with **E3**, because existing advisory group/leader observations can support a direct ranking comparison without first expanding market permissions. Collect **E2** whenever a genuinely bearish regime occurs. Study **E5** where contract constraints are the actual exclusion reason. Evaluate **E4** only when quantity and first-target events make it testable. Treat **E1** as the most direct challenge to today's abstention and require the strongest evidence before any permission change.

Today's authored cash guidance is a useful guard against optimizing for activity. The objective is improved net expectancy with controlled downside, and a correct decision to do nothing remains an admissible outcome.
