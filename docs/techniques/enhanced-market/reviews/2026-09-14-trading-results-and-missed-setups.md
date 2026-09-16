# EM: actual trades, missed setups, and the next strategy review

Review date: September 14, 2026, after the close. Times below are New York time. Read-only evidence refreshed around 23:36 ET. This returns the main review to trading decisions while the development team handles the separate worker reliability findings.

**Main conclusion:** September 14 was profitable in the dedicated EM Practice book, but the sample is too small to establish an edge. The most useful next comparison is the author's specific morning continuation scenario versus the independent level-bounce/rejection plans we actually generate. Exit timing is a second, separately measurable question. Buying more often is not the objective.

## Actual completed positions

Dedicated simulated portfolio: `045d8c35b3f149628ea001ae90a58edb`, EM Practice. Ledger-based results include recorded fees; do not substitute the unrepaired HPQ plan projection or combine older portfolios.

| Session | Position | Entry premium/share price | Exit premium/share price | Net P&L |
|---|---|---:|---:|---:|
| Sep 10 | 2 HOOD Sep 11 $114 puts | $1.73 | $1.399 | -$70.36 |
| Sep 14 | 100 HPQ shares | $34.77 | 30 at $34.803; 70 at $34.6531 | -$7.193 |
| Sep 14 | 1 HOOD Sep 18 $115 put | $3.45 | $3.90 | +$42.92 |
| Sep 14 | 2 INTC Sep 14 $96 calls | $1.00 | $2.15 | +$225.84 |
| Sep 14 | 1 MSFT Sep 18 $507.50 put | $5.45 | $6.50 | +$102.92 |

September 14 net: **+$364.487**, or **+$364.49**. Dedicated account total: **+$294.127**, with cash **$10,294.127** and no remaining open quantity in these positions. Five positions, three profitable and two losing, cannot establish repeatability. INTC contributes most of September 14's net gain. These are Practice executions, not live-broker performance.

This closes the earlier intraday snapshot, which did not yet include MSFT's final exit. It also corrects the impression that every recent trade lost. It does not dismiss the observed giveback problem.

## What happened to September 14's entries

There were **85 persisted arm records for 58 symbols**, including replacements. These are neither 85 independent opportunities nor 85 intended orders. The final session has **14 trigger-attempt records across 11 symbols**:

| Final disposition | Attempts | Symbols and evidence |
|---|---:|---|
| Filled and closed | 4 | HPQ, INTC, HOOD, MSFT |
| Share-fallback risk rejection | 4 | SWKS twice, USO twice; 100-share requests exceeded position/exposure caps |
| Option spread refusal | 3 | COIN 42.3%, OKLO 12.1%, FCX 25.5% |
| Remaining-loss-budget refusal | 2 | BE twice; modeled risk about $710/$497 versus about $397 remaining allowance |
| Stale quote refusal | 1 | DRAM; quote age 10.2 seconds versus 10-second limit |

Four fills out of fourteen attempts is the observed funnel, not an estimate of missed profits. In particular, USO's 100 shares required roughly $15,700–$15,900 of notional in a roughly $10,000 book. The relevant sizing question is whether an affordable quantity could pass all checks, not whether to remove the checks. No complete executable counterfactual for these ten refusals has been established.

The journal also contains 103 skip events across 100 run/trigger pairs in the inspected EM filter. Leading reasons are gap void (33), invalidation (26), gapped past (21), and gapped through (12). These occur earlier in the pipeline and overlap plan replacement/attempt history. They must not be added to fourteen as a count of independent missed trades, and some reflect the already identified old pre-open defect.

## Why the low-trade explanation changed over time

For this dedicated account, saved trade-attempt states show:

| Session | Recorded attempts | Main result |
|---|---:|---|
| Sep 8 | 9 | 9 critic-killed |
| Sep 9 | 9 | 8 critic-killed, 1 spread refusal |
| Sep 10 | 6 | 1 fill, 5 spread refusals |
| Sep 11 | 3 | 3 spread refusals |
| Sep 14 | 14 | 4 fills; ten downstream refusals described above |

These are different policy periods and recorded attempts, not a controlled experiment. On September 14, thirteen completed critic opinions were negative but advisory; MSFT continued after a 25-second timeout. The thirteen completed opinions took 14.13–20.27 seconds, averaging 17.14 seconds. Removing a veto that was already advisory would not have admitted the ten downstream refusals. The delay is measurable; its effect on fills and profit still needs matched evidence.

## The author's four morning names

The existing board marks ticker coverage. A source-faithful review needs direction, entry event, level, source time, horizon and invalidation. Full-day exchange-tagged one-minute underlying bars were checked for these four names; this is chart-event evidence, not executable option P&L.

| Source idea | September 14 evidence | Review classification |
|---|---|---|
| MSFT long over 498.97 toward 505+ | Price crossed the level and later reached the target area. Our linked valid morning plan was a short rejection at 509.56. | Genuine representation mismatch and an underlying opportunity to investigate; not a proven missed winning option trade. |
| AAPL long over 336.22 | Regular-session high was 335.50. | Source trigger never reached. Correct no-trigger day for that stated condition. |
| MRNA long over 149.73 | Regular-session high was 147.3399. | Source trigger never reached. Correct no-trigger day; swing horizon must remain separate. |
| META long continuation | Narrative lacks a fully specified numeric break/stop/target; our linked valid plan was short-only. | Direction mismatch. Insufficient source geometry to score an eligible trade or a missed profit. |

MSFT illustrates why “it reached the target” is not enough. The exact caption was posted before the open, at approximately 09:20:51. The 09:30 bar traded above 498.97 but closed at 498.03; by 09:34 price had fallen to 495.3416. The first completed one-minute close above the level was the 09:48 bar at 499.99, usable only after 09:49 plus feed/processing delay. Price subsequently revisited below the level before first touching 505 in the 11:36 bar. Immediate-break, completed-close and retest entries therefore have materially different paths. The source does not supply a numeric stop; no source-grounded R multiple, win label or option profit can be assigned yet.

The later MSFT put is a separate short trade at about 12:50, after the morning 505 objective had already been reached. It must not be labeled a failed implementation of a morning long solely because its direction differs. The earlier board coverage claim was the mismatch.

Historical note timestamps indicate morning video extraction/checking before the open. Backfilled immutable artifacts retain unknown availability and must not be upgraded into precise historical timing proof. The three short chart captions were stored but unprocessed in the inspected legacy note state.

## What the exit evidence supports

- **HPQ:** the first target was touched inside the 09:36 bar, but the runner waited for the completed bar and submitted at about 09:37. The 30-share trim captured only $0.99, then the remainder stopped out. This supports an experiment on exit timing at unchanged targets. The bar high is not proof a resting order would have filled there.
- **HOOD on Sep 10:** the planned underlying entry/stop were 115.09/115.6655. TP1 at 111.3716 was 6.46 initial risk units away; the two-contract policy waited to exit fully at TP2, 108.118, about 12.12 risk units away. Price moved favorably to 113.50 without reaching either target. The option had a post-entry exchange-tagged bar high of $2.33 versus its $1.73 entry before exiting at $1.399. This is a distant-target/no-early-trim question, distinct from HPQ's delayed response to a touched target. The bar high is not a historical executable bid, and a universal profit percentage remains unproven.
- **INTC and HOOD on Sep 14:** both completed profitable TP2 exits. Any earlier-exit policy must count the profit it gives up on winners as well as losses it might avoid.
- **MSFT:** the final put exit was profitable at the session flatten. The underlying low while held, 504.70, remained above the short plan's first target at 502.8106, so this was not a failure to execute an already reached target. Mixed sampled/exchange option-bar provenance prevents treating the highest sampled print as guaranteed realizable profit.

## Focused recommendations

1. **Complete a manual source-to-opportunity ledger now.** Start with all four September 14 source names, including the two untriggered ideas. Record source availability, direction, conditions, first eligible observation, system proposal and the reason they differ. Keep exact source instructions distinct from our chosen stop, confirmation and contract policy. This review can proceed without waiting for a candidate-production feature.
2. **Define one continuation experiment.** Use MSFT to expose the choices, not to optimize them after seeing its path. Specify immediate/completed-close/retest timing, a defensible as-of structural stop, source target/horizon, no-chase rule and affordable contract selection. Then freeze one chosen candidate definition before observing a new cohort. Preserve the independent baseline. Source-only ideas stay order-free until separately reviewed.
3. **Compare exits with entries held fixed.** Use identical entry time, contract, quantity and budget for every baseline/variant. First test timely execution at unchanged targets; separately test an explicit structural partial/full-exit policy compatible with one or two contracts. Include all five observed positions and all eligible subsequent positions, costs, slippage, unavailable quotes and adverse outcomes. Do not combine a new entry rule, larger size and earlier exits into one unexplained variant.
4. **Measure advisory critic delay separately.** Compare the actual delayed path with a predefined asynchronous-advisory candidate using as-of executable quotes while retaining final admission safeguards. No improvement claim where those quotes are absent. Do not make a larger model or relaxed spread gate the default response to scarce entries.

The next daily review should answer four concrete questions: which source scenarios became eligible; which our baseline represented; what blocked each actual entry; and how actual exits compared with the predefined alternative on available executable evidence. A short forward cohort is useful for diagnosing these mechanisms, not by itself enough for a profitability promotion.

## Evidence and scope

Read-only PostgreSQL tables: `technique_method_notes`, `technique_armed`, `technique_runs`, `events`, `orders`, `executions`, `bars`, and portfolio records. No stored EM counterfactual rows were found for sessions since September 10 in the inspected table. Detailed companion reviews: `2026-09-14-source-opportunity-reassessment.md` and `2026-09-14-trade-exit-reassessment.md` in this folder. Earlier evidence and proposed Delivery C/D research remain in `2026-09-14-comprehensive-review.md` and `DEV-TEAM-HANDOFF-2026-09-14.md`; they do not substitute for final-session reads.

No strategy settings, risk limits, orders, deployment or data repairs were changed. Review work remained in `C:/Cursor/zargar-codex`, branch `codex/zargar-development`. Worker reliability findings remain in their existing separate review packet. The unresolved trading questions are executable counterfactual prices, missing author geometry, and a sufficiently broad forward sample—not another expansion of the worker PR.
