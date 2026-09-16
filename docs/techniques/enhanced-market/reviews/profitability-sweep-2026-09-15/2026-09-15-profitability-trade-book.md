# EM profitability sweep: the actual Practice trade book

Evidence cutoff: **September 15, 2026, 11:52:46 ET (15:52:46 UTC)**. This is an intraday case study. All accounting below uses executions at or before that cutoff in the dedicated EM Practice portfolio `045d8c35b3f149628ea001ae90a58edb`; subsequent fills and current mutable position marks are excluded. No orders, settings, code, database rows or running processes were changed.

## What the money says

September 15 has five actual entries by the cutoff, three completed and two still open. All five are long calls entered for a **bounce**. Low trade frequency is not the main issue in this morning's filled cohort; the useful questions are which bounces deserve entry and whether attainable gains cover the option's transaction cost and exit distance.

| Session | Position | Actual entry | Actual exit | Fees allocated to completed position | Net realized P&L |
|---|---|---:|---:|---:|---:|
| Sep 10 | 2 HOOD Sep 11 114 puts | 1.730 | 1.399 | $4.16 | -$70.36 |
| Sep 14 | 100 HPQ shares | 34.770 | 30 at 34.803, 70 at 34.6531 | $0.00 | -$7.193 |
| Sep 14 | 2 INTC Sep 14 96 calls | 1.000 | 2.150 | $4.16 | +$225.84 |
| Sep 14 | 1 HOOD Sep 18 115 put | 3.450 | 3.900 | $2.08 | +$42.92 |
| Sep 14 | 1 MSFT Sep 18 507.5 put | 5.450 | 6.500 | $2.08 | +$102.92 |
| Sep 15 | 4 NFLX Sep 18 79 calls | 0.880 at 09:34:01 | 0.750 at 09:57:02 | $8.32 | -$60.32 |
| Sep 15 | 2 CVNA Sep 18 70 calls | 1.490 at 10:02:23 | 1.140 at 10:24:01 | $4.16 | -$74.16 |
| Sep 15 | 2 IREN Sep 18 42 calls | 1.460 at 10:07:18 | 1.495 at 10:42:01 | $4.16 | +$2.84 |

September 14 net remains **+$364.49**. September 15 realized net through the cutoff is **-$131.64**, comprising -$115.00 gross price P&L and $16.64 closed-position fees. All eight completed positions sum to **+$162.487**, with four winners and four losers. Their closed-position fees total $29.12.

The one INTC winner contributes $225.84, more than the entire completed-book gain. Excluding it leaves **-$63.353**. That is concentration evidence, not a reason to discard the winner: any proposed filter or earlier exit must include the profit it would forgo on INTC. This is much too small and policy-mixed a sample to infer a stable win rate or edge.

Completed long bounces total +$87.007 across five positions; completed short rejections total +$75.48 across three. The tiny, uneven cohorts do not justify switching direction or abandoning bounces.

## Open exposure is a separate line

| Position open at cutoff | Entry | Paid premium | Entry fees | Remaining quantity |
|---|---:|---:|---:|---:|
| ORCL Sep 18 142 call, entered 09:45:38 | 2.96 | $296 | $1.04 | 1 |
| CRWV Sep 18 82.5 call, entered 10:49:18 | 2.42 | $242 | $1.04 | 1 |

Open paid premium is **$538**, plus **$2.08** already paid entry fees. These are neither realized losses nor guaranteed recoverable values. The stored entry sizing uses a 50% premium-stop model, $148 plus $121 for these positions; paid premium is the separate amount exposed if the option loses its full value. No as-of executable bid with timestamp and displayed quantity was established for marking these open positions in this review, so the headline realized total excludes their unrealized result.

The ledger-implied cash balance at the cutoff is $9,622.407: $10,000 starting cash + $162.487 closed net - $538 open premium - $2.08 open entry fees. Cash is not account equity while these options remain open.

## Today's losses and givebacks are different cases

The following chart observations use complete exchange-tagged one-minute underlying bars strictly after the entry minute and before the exit minute, or through 11:51 for open positions. This avoids treating a pre-entry tick or the unfinished 11:52 bar as evidence. R here is **planned underlying price risk**, not actual option P&L or premium risk. Same-minute path ordering and historical executable option bids remain unknown.

| Position | Favorable underlying high in this conservative held window | Favorable move from intended entry | Production first sale | Interpretation |
|---|---:|---:|---|---|
| NFLX | 78.9400 | about 1.15 planned R | TP1 at 79.096, about 1.54 R, four-contract ladder | A bounce occurred but did not reach TP1; then the stop closed the position. |
| CVNA | 69.1505 | about 0.51 planned R | Two contracts wait for TP2 at 70.3071, about 3.87 R | Primarily an entry-quality/limited-follow-through case; there is no established meaningful option gain to protect. |
| IREN | 42.2950 | about 2.40 planned R | Two contracts wait for TP2 at 42.9076, about 5.20 R; even TP1 begins at 2.77 R | Useful favorable underlying movement never reached the first sale. The stop ultimately produced only $7 gross/$2.84 net. |
| ORCL, open | 144.0500 | about 3.60 planned R | One contract waits for TP2 at 144.25, about 3.84 R | Price passed TP1 at 142.738 while the small-position policy kept the full contract. This is an unresolved winner as of cutoff, not a completed giveback. |
| CRWV, open | 82.8012 | about 1.76 planned R | One contract waits for TP2 at 83.5307, about 3.53 R; TP1 starts about 1.89 R | No first target reached in this window; final economic outcome remains open. |

The exact option bars reinforce why the same story should not be applied to every position. NFLX's held-window exchange-tagged premium high was 1.12 against its 0.88 fill, a 27% trade-print excursion before a realized loss. IREN's equivalent high was 1.60 versus 1.46. Those observations justify measuring a predefined early-profit exit, but neither high is an executable bid or a promise of capture. CVNA's equivalent exchange high was only 1.33 against a 1.49 entry. Its sampled bars contain a 2.45 high, which must not be promoted into a missed-profit claim. No historical same-contract bid/ask path with quantity was reconstructed here.

## The trading costs can consume a modest bounce

Stored entry-contract snapshots identify OPRA as the source used for spread judgement. The table below is a **static economic illustration**: actual fill minus the stored contemporaneous bid, plus the known round-trip commission schedule for that quantity. It is not a second deduction from realized P&L, not a forecast, and not a verified historical liquidation fill. The snapshot does not establish displayed bid quantity at the exact fill instant.

| Position | Fill / stored bid | Position's price concession plus round-trip fees | As fraction of paid premium |
|---|---|---:|---:|
| NFLX, 4 contracts | 0.88 / 0.86 | $16.32 | 4.64% |
| ORCL, 1 contract | 2.96 / 2.86 | $12.08 | 4.08% |
| CVNA, 2 contracts | 1.49 / 1.36 | $30.16 | 10.12% |
| IREN, 2 contracts | 1.46 / 1.39 | $18.16 | 6.22% |
| CRWV, 1 contract | 2.42 / 2.35 | $9.08 | 3.75% |

CVNA illustrates why merely passing the maximum-spread rule does not make a contract attractive for a short bounce. Its captured spread was 9.12% of midpoint and a 10.12% paid-premium improvement from that bid would be needed just to cover the fill-to-bid difference and fees. IREN's $4.16 fees consumed **59.4% of its $7 gross gain**. These are reasons to compare contract expressions by net attainable payoff, not to loosen spread limits or enlarge quantities.

For the five fills, first recorded trigger handling to entry submission was approximately 16-23 seconds; NFLX then waited another 37.5 seconds to fill and ORCL another 16.8 seconds. This is a potential price-quality variable. It is not yet measured lost profit, and should remain a separate paired comparison rather than be combined with new entry and exit rules.

## Profitable hypotheses to test, in order

1. **Require observable evidence of a bounce before a new entry in one frozen comparison.** Compare the current touch/proximity behavior with a predefined completed-close reclaim after an actual level interaction, then a next available executable option price. NFLX's trigger bar closed at 78.40 below its 78.49 intended level, followed by another down close; CVNA's trigger bar low was 69.04, above its 68.9734 planned level. These are concrete differences between anticipating and observing a bounce. Keep position size, source universe, stop and exit policy fixed for this comparison; otherwise the explanation of any improvement becomes ambiguous. Count delayed fills, no-fills and forgone winners. Do not simply re-enable every negative critic verdict: all five current entries received negative advisory opinions, and earlier profitable trades were taken during the advisory period too.
2. **Compare one explicit small-position early-profit policy against unchanged entries.** IREN and ORCL make the target-distance problem tangible. For two contracts, one possible frozen comparison is an initial sale at a predefined attainable level followed by a retained runner; for one contract, the comparison must explicitly choose a whole-position exit. Do not choose the level from the observed high. Include INTC and HOOD September 14, where early exits may reduce profits, and HOOD September 10, where distant targets were a problem. This is a research proposal, not an instruction to change today's open positions.
3. **Rank option expressions by net payoff at the same structural target.** Compare the chosen near-dated contract with a small predeclared set of affordable liquid alternatives at the same entry observation. Preserve the dollar-risk budget and use timestamped bids, asks and sizes; keep unavailable Greek-based payoffs unknown. Evaluate total dollars after both sides' costs, along with the downside. CVNA's current cost burden is the motivating case, not evidence that a different contract would have won.

Use a forward cohort that includes every eligible case and its no-trade outcome. The September 14 and 15 examples help define the comparisons; they should not be reused as evidence that an optimized rule works. These recommendations concern trading selection and payoff capture. They do not reopen infrastructure work.

## Evidence and review scope

Read-only SQL inspected `executions`, linked `orders`, immutable opening/closing and target-distance `events`, entry fields in `technique_armed.state`, and `bars`. Execution cutoff was enforced explicitly at 15:52:46 UTC. Current state was used only to recover original entry geometry and references; realized and open quantities were reconstructed from timestamped fills. The prior five-position report, `2026-09-14-trading-results-and-missed-setups.md`, was cross-checked against those fills again. The HPQ figure uses share multiplier 1 and ledger evidence, not the unrepaired old plan projection.

Active review folder: `C:/Cursor/zargar-codex`, branch `codex/zargar-development`. This file contains derived review facts only. No raw database export, trading changes, test database work, paid model calls or deployment actions were performed.
