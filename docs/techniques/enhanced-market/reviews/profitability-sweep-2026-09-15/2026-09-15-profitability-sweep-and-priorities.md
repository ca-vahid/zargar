# EM profitability sweep and priorities

**Recommendation: preserve the current gap-day selectivity, prioritize study of long bounces with real chart targets, and test small-position profit capture separately. Do not loosen entry rules or apply a blanket early-profit rule to increase activity or win rate.** The profitable historical paths depend materially on retaining large winners.

This is a profitability review as requested, treating reliability work as settled for this task. It freshly analyzes the saved historical sweeps, actual EM Practice fills, and morning source scenarios. It does not launch another engine sweep, change settings, or place orders. Current-session accounting is frozen at **September 15, 2026, 11:52:46 ET**; later outcomes are excluded.

## What the money says now

| Evidence | Result | Meaning |
|---|---:|---|
| September 14 completed Practice positions | +$364.49 net | A profitable session, led by INTC. |
| September 15 completed positions by cutoff | -$131.64 net | NFLX -$60.32, CVNA -$74.16, IREN +$2.84. |
| All eight completed positions in dedicated EM Practice | +$162.487 net | Four profitable, four losing; too few and too policy-mixed to establish a stable edge. |
| Same completed book excluding INTC | -$63.353 | Any filter/early exit must count lost access to that $225.84 winner. |
| ORCL and CRWV still open at cutoff | $538 paid premium plus $2.08 entry fees | Unmarked open exposure, excluded from realized totals. |

All five September 15 fills were **long-bounce calls**. The morning is not primarily a lack-of-trades problem: fifteen attempts produced five fills by the cutoff. Ten stopped at quote, budget, exposure or spread checks. Today argues for better selection/payoff capture, not a purchase quota or more risk.

Completed long bounces have earned +$87.007 across five positions; short rejections +$75.48 across three. These tiny cohorts do not justify shutting off either direction. The day remains incomplete.

## Historical sweep: what helped and what did not

The main matched cohort has **117 symbols, 1,521 symbol-session rows and 13 trading sessions, August 25–September 11**. Variants share the symbol universe and technique-source identifier; their intended parameter differences are recorded. Numbers below are **gross underlying-price R proxies**, where 1R is the model's underlying entry-to-stop risk. They are not actual option returns, portfolio dollars or results after execution costs.

| Matched comparison | Fires | Total R proxy | Decision |
|---|---:|---:|---|
| Original C baseline | 39 | +6.28R | Comparison reference. |
| Gap-day wait at 0.5% | 33 | +11.38R | Preserve: removed six losing fires, helped both chronological blocks. **Already active**, not a new change to implement. |
| Gap wait plus continuation | 34 | +11.71R | Only one extra trade; insufficient evidence to add frequency. |
| Range-break expansion | 43 | +5.47R | More trades, less return than the original baseline. Do not add it merely to get purchases. |
| Far-target scratch at 0.75R | 39 | +3.70R | Lower total, but only one trade changed; limited relevance to today's givebacks. |

The active gap wait preserves all 33 retained entries/outcomes and excludes six losses totaling -5.10R. Runtime settings confirm a 0.5% threshold and 30-minute wait. Its improvement is +2.30R in the early block and +2.81R in the later block. The split is retrospective, not an untouched validation sample.

A separate matched 12-session, 37-fire T14 cohort tests selling half and moving the stop to entry:

| Exit policy | Win rate | Total R proxy |
|---|---:|---:|
| Baseline | 37.8% | +3.98R |
| Scratch at +0.5R | 59.5% | -0.09R |
| Scratch at +0.75R | 56.8% | +1.21R |
| Scratch at +1R | 43.2% | -4.07R |

**Higher win rate did not mean more money.** This argues against applying one early-profit rule to every trade. It does not settle the special case of a one/two-contract position whose first actual sale waits for an unusually distant target: the far-target C4 experiment changed just one VST winner, not a representative sample of those trades.

## Best research lead: setup quality and target credibility

Within the active-gap-rule historical cohort:

| Family | Fires | Wins | Total R proxy | Later-block R |
|---|---:|---:|---:|---:|
| Long bounce | 12 | 9 | +11.75R | +5.03R |
| Short rejection | 12 | 5 | +2.45R | -1.42R |
| Long breakout | 4 | 1 | -1.56R | -1.28R |
| Short breakdown | 5 | 1 | -1.26R | -1.05R |

Ten long bounces aimed at saved **next-resistance targets** produced eight wins and +11.61R, positive in both chronological blocks. But only two percentage-target bounces are available for comparison. This supports prioritizing that cohort for study; it does not prove numeric targets cause the advantage or that every current long bounce deserves entry. The full bounce family stays positive without its two best trades (+3.38R), while the complete 33-trade C3 book becomes negative if its three best trades are removed. Retaining runners matters.

Another useful diagnostic is room remaining at the actual modeled entry:

- TP1 less than 1R ahead: six fires, -2.26R total.
- TP1 from 1R to below 3R ahead: 26 fires, +8.51R total.
- TP1 at least 3R ahead: one fire, +5.12R.

These bins overlap setup families and were chosen for analysis. They do not justify either a new hard lower threshold or an upper target-distance ban. Record both **room to the next meaningful obstacle** and **distance to the first sale under the actual quantity policy**; those are different quantities.

## What actual trades reveal about profit capture

IREN moved about **2.40 planned underlying R** in favor, but its first target was 2.77R away and its two-contract full exit waited for TP2 at 5.20R. Its $7 gross profit became $2.84 after $4.16 fees. This is a useful small-position exit case, not proof a particular alternative would have filled.

NFLX had a favorable exchange-tagged option-price excursion before closing at a loss. CVNA did not show the same favorable exchange-price evidence, so it should not be treated as another identical giveback. HPQ's earlier session shows a different mechanism again: the target was touched within a bar, but the actual trim followed after price reversed.

The planned first-sale distances for today's other positions were roughly 1.54R for NFLX, 3.87R for CVNA, 3.84R for ORCL and 3.53R for CRWV. These are underlying geometry measurements, not option profit thresholds. ORCL and CRWV are still unresolved at the cutoff.

**Specific next comparison:** retain the normal ladder as baseline. In a separately tagged one/two-contract, distant-first-sale cohort, compare one predefined quantity-feasible partial/full-exit policy on identical entries, contracts and quantities. Track the remaining position honestly and count the profit forgone on large winners. Do not choose the winning threshold after looking at today's path. Keep more timely execution at unchanged targets as a separate comparison.

## The source ideas are useful controls, not automatic winners

META provides a concrete target/stop-fit example. The source's 665→670 objective was reached at 09:39. The frozen completed-close/whole-opening-range-stop proxy entered at 666.646 and offered only 0.321R to 670, so it failed the existing gate. Our baseline plan's first target was instead 681.972, followed by 695.344/708.716; none was reached by the cutoff. Its trigger had been invalidated at 09:33, so this is a comparison of plan geometry, not an executed baseline giveback.

The conclusion is not to turn a 0.32R opportunity into a trade by relaxing risk rules, nor to make it look attractive by placing distant percentage targets. It is to test a coherent entry, a stop justified by the structure available at that entry, and a credible objective together. A broad opening-range stop may not be the appropriate representation of a local continuation/retest setup; any alternative must be declared before its new-session results are examined.

MU is the essential counterexample: its frozen source candidate offered 3.47R, moved only 0.42R favorably and then closed through the stop for about -1.07 underlying R. MRNA, SNDK, ZS's short branch and AMZN's preferred 257 breakout had not triggered. ZS's long proxy remained unresolved and below the 3R eligibility requirement. Copying the author's names or levels does not establish an edge.

## Costs and capital: another profitability lever

CVNA entered at 1.49 with a captured bid of 1.36. A static immediate-return-to-that-bid illustration plus round-trip fees costs about **10.12% of entry premium**. That is a payoff hurdle, not an extra loss to subtract again from realized P&L. Quote availability and price changes matter; it is not a guaranteed executable bid. IREN shows the same economic issue at a smaller scale: fees consumed most of its small gross win.

For contract selection, compare expected attainable dollar payoff with spread, fees and feasible quantity, instead of judging the chart's R alone. Keep the existing liquidity/risk constraints. A nearby liquid strike or different allowed expiry is useful only if it preserves the intended exposure and improves the net payoff case—not simply because it permits a purchase.

Three September 15 share-fallback attempts in WDC, INTU and AMAT requested roughly $33,000–$41,000 positions in an approximately $10,000 book and were refused. The capital-allocation research question is whether a smaller feasible vehicle/quantity offers worthwhile net profit within existing caps. Those refusals are not measured lost profits, and this review does not turn them into reliability tickets or recommend higher exposure limits.

## Recommended priorities for the dev/reviewer team

| Priority | Work | Success measure |
|---|---|---|
| P-01 | Freeze and report the `long bounce + next_resistance` cohort alongside the full baseline; stratify by confirmation, actual-entry room, quantity and source alignment. | Better net results across subsequent sessions without hiding filtered winners, sparse trades or capital conflicts. Research prioritization first, no automatic family shutdown. |
| P-02 | Compare one quantity-feasible exit alternative only for distant-first-sale small positions; separately evaluate faster execution at unchanged targets. | Net realized/model-supported difference after costs, including lost runner profit, on identical entries/contracts/quantities. Unknown bid paths stay unknown. |
| P-03 | Record attainable objective, stop basis and contract friction together for source-continuation candidates and baseline plans. | Fewer economically unattractive proposals, with the full accepted/refused opportunity set and held-out outcomes retained. No invented distant targets or looser risk caps. |

Keep the active gap wait. Do not adopt broad scratch exits, range expansion, a blanket target-distance cap, or a wholesale return to critic veto solely from this sample. All five of today's filled trades had negative advisory critic opinions, but so did major September 14 winners; the useful next test is a defined setup-quality distinction, not an undifferentiated veto.

Daily reports should lead with net completed P&L, open exposure, winner concentration, target/exit capture and economic refusals. Evaluate the frozen candidates on new sessions and report all outcomes. These are hypotheses, not new live settings.

## Method and artifacts

The sweep freshly queried existing saved cohorts and computed matched-entry differences, chronological splits, family/target-basis partitions and concentration. It did not rerun market data acquisition or claim that historical underlying-bar simulations contain executable option prices. Their proportional trims and last-close residual marks differ from actual integer option execution. Eight completed Practice trades, thirteen historical sessions and retrospective subgroup selection justify a ranked experiment list, not a profitability promotion.

Selecting the best result among many tried variants can inflate apparent performance; record the tested variants and use genuinely new-session evidence for the next decision. This follows the primary research on selection bias and backtest overfitting. [Bailey and López de Prado, *The Deflated Sharpe Ratio*](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf).

Companion reports in this folder contain exact sweep IDs, run/source IDs, fill evidence and derivations:

- [Historical sweep](2026-09-15-profitability-historical-sweep.md).
- [Actual Practice trade book](2026-09-15-profitability-trade-book.md).
- [Morning source opportunities](2026-09-15-profitability-source-opportunities.md).

Workspace: `C:/Cursor/zargar-codex`, branch `codex/zargar-development`. Only derived review documentation was added. No trading, settings or runtime changes were made.
