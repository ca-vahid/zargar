# EM profitability: historical sweep evidence, September 15, 2026

This review ranks strategy experiments using existing EM sweep records. It does not rerun the engine, change settings, place orders, or reopen the reliability work. Queries used a read-only PostgreSQL transaction setting and a 15-second statement timeout against `technique_sweeps` and `technique_walkforward`.

The most useful direction is to study **long bounces with a numeric resistance target**, preserve the already adopted gap-day wait, and avoid a blanket early-profit rule. The evidence supports research priorities, not an increase in trading risk or a promise of profitable option execution.

## Comparable cohorts and meaning of the numbers

- C baseline and its six variants each contain the same 117-symbol universe and 1,521 symbol-session rows: **13 actual trading sessions, August 25 through September 11**. Sweep request dates are August 24 through September 11 because a plan is built at the prior close. All seven carry `techniqueSource=d629e09984`.
- T14 baseline and three scratch variants contain 1,404 rows, 117 symbols, and **12 actual sessions, August 25 through September 10**, with `techniqueSource=0614c29c76`. Do not compare T14's raw total directly with C's extra session and different source version.
- Saved C threshold dictionaries differ from C baseline only by the displayed variant overrides. Symbol arrays are equal. `processVersion` and `sweepVersion` differ by variant; these hashes are not asserted to be Git commit SHAs.
- A fire is a hypothetical underlying-price trade. R is the modeled gain or loss divided by modeled underlying risk. The model uses bar-based target/stop execution, proportional trims, and a last-bar close for remaining exposure. It does not price an actual option contract, spread, commissions, integer contract ladder, portfolio capital constraint, or executable bid/ask depth.
- C baseline has 39 fires, of which 15 have `sim.resolved=true`; C3 has 33, of which 11 do. Every fire is marked `closedByEod=true`, but the remaining rows are last-close modeled values, not independently observed terminal fills. Accordingly all totals below are **gross underlying R proxies**, never realized dollars or net option expectancy.
- The chronological split is seven sessions through September 2 versus six from September 3 through September 11. It is a retrospective stability check, **not an untouched out-of-sample test**: the variants had already been selected using these dates.

## Existing variants: what earned its place

| Variant | Fires | Wins | Total R proxy | R/fire | Early total R | Late total R |
|---|---:|---:|---:|---:|---:|---:|
| C baseline | 39 | 16 | +6.2768 | +0.1609 | +7.8014 | -1.5246 |
| C3 gap wait at 0.5% | 33 | 16 | +11.3810 | +0.3449 | +10.0970 | +1.2840 |
| C3 plus gap continuation | 34 | 17 | +11.7136 | +0.3445 | +10.4296 | +1.2840 |
| C4 scratch at 0.75R, only far TP1 | 39 | 16 | +3.6959 | +0.0948 | +5.2205 | -1.5246 |
| C4 scratch at 1R, only far TP1 | 39 | 16 | +3.8209 | +0.0980 | +5.3455 | -1.5246 |
| C5 range-break expansion | 43 | 17 | +5.4729 | +0.1273 | +7.0464 | -1.5735 |
| C3 + continuation + C5 | 39 | 19 | +11.1184 | +0.2851 | +9.8833 | +1.2351 |

The C3 wait removes six losing fires totaling -5.1042R. All 33 retained fires have identical entry timestamps, entry prices, stops, and R outcomes to baseline. Removed outcomes: UBER bounce August 31 -1.0456R; CRWD bounce September 1 -1.25R; TSM breakdown September 3 -1.0157R; AMD breakdown September 3 -0.5299R; VRT bounce September 9 -1.25R; AXP breakdown September 9 -0.013R. The improvement occurs in both chronological blocks: +2.2956R early and +2.8086R late.

**This is already part of the method.** The runtime checkout's [TRADING-RULES](C:/Cursor/zargar/docs/techniques/enhanced-market/TRADING-RULES.md) records adoption on September 12: `technique.gap_day_pct=0.5` and `gap_day_wait_minutes=30`. The rule waits through the first 30 minutes when the symbol opens at least 0.5% away from its prior close. Its continuation add-on remains off; the historical extra +0.3326R is one trade, not an established source of additional profitable frequency.

## Ranked profitability ideas

### 1. Prioritize research on long support bounces with a numeric resistance target

Within the existing C3 cohort, bounces are the only family positive in both chronological blocks with a meaningful share of the fires:

| Family | Fires | Wins | Total R proxy | Early R | Late R | R without two best trades |
|---|---:|---:|---:|---:|---:|---:|
| Long bounce | 12 | 9 | +11.7453 | +6.7119 | +5.0334 | +3.3777 |
| Short resistance reject | 12 | 5 | +2.4528 | +3.8680 | -1.4152 | -5.2309 |
| Long breakout | 4 | 1 | -1.5621 | -0.2788 | -1.2833 | -1.3056 |
| Short breakdown | 5 | 1 | -1.2550 | -0.2041 | -1.0509 | -1.3367 |

Bounce observations cover eight symbols and eight sessions; they are not 12 independent market regimes. The two best bounces are both HOOD: +4.6493R on August 25 and +3.7183R on September 2. The family remains positive without them, although its apparent advantage is much smaller.

The target-basis split is informative but strongly confounded with setup family and direction:

| Family / direction | Saved first-target basis | Fires | Wins | Total R proxy | Early R | Late R |
|---|---|---:|---:|---:|---:|---:|
| Bounce / long | `next_resistance` | 10 | 8 | +11.6083 | +6.5749 | +5.0334 |
| Bounce / long | `pct_ladder` | 2 | 1 | +0.1370 | +0.1370 | no fires |
| Reject / short | `next_support` | 10 | 3 | +2.3222 | +3.8076 | -1.4854 |
| Reject / short | `pct_ladder` | 2 | 2 | +0.1306 | +0.0604 | +0.0702 |
| Breakout / long | `pct_ladder` | 4 | 1 | -1.5621 | -0.2788 | -1.2833 |
| Breakdown / short | `pct_ladder` | 5 | 1 | -1.2550 | -0.2041 | -1.0509 |

**Proposed comparison:** freeze the label "long bounce with saved `next_resistance` target" before reviewing subsequent outcomes. Report all its opportunities, executable shares/options, entries, missed fills, net results, and runner contribution beside the full baseline. Initially use it to prioritize study, not to switch other families off or increase size. Two percentage-target bounces provide almost no within-family comparison, so the table does not prove that numeric targets cause the advantage.

### 2. Measure the room left at the actual entry, rather than adding an upper target-distance gate

For each existing C3 fire, compute signed distance from its modeled actual entry to TP1, divided by the actual entry-to-stop distance. These are diagnostic bins chosen for this review:

| TP1 distance from actual entry | Fires | Wins | Total R proxy | Early R | Late R |
|---|---:|---:|---:|---:|---:|
| Greater than 0 but below 1R | 6 | 2 | -2.2558 | -0.1140 | -2.1418 |
| 1R to below 3R | 26 | 13 | +8.5130 | +5.0872 | +3.4258 |
| At least 3R | 1 | 1 | +5.1238 | +5.1238 | no fires |

No fired row in this cohort had TP1 already behind its modeled entry. The weaker signal here is **too little reward left after entry confirmation**, not evidence that distant targets should be banned. The below-1R sample is only six fires, five in the later block. It overlaps the losing breakout/breakdown families, so it cannot independently establish a causal entry rule.

**Proposed comparison:** record planned and executable-entry distances separately, plus setup family, source alignment, target basis, vehicle, spread, and actual quantity. Compare the unchanged baseline with a diagnostic candidate that labels limited remaining room; select no new blocking threshold yet. The next session cohort must include refused opportunities and later price paths, so a reduction in entries cannot masquerade as improved profitability.

### 3. Preserve the gap wait and the profitable runners; test giveback exits only on the matching cohort

The blanket T14 scratch variants sell half at the specified R and move the remainder's stop to entry. On their own matched 12-session cohort:

| Variant | Fires | Wins | Win rate | Total R proxy |
|---|---:|---:|---:|---:|
| T14 baseline | 37 | 14 | 37.8% | +3.9796 |
| Scratch at 0.5R | 37 | 22 | 59.5% | -0.0935 |
| Scratch at 0.75R | 37 | 21 | 56.8% | +1.2060 |
| Scratch at 1R | 37 | 16 | 43.2% | -4.0686 |

A higher win rate is not the objective when it clips the few large winners. C4's targeted variant also loses total R, but its relevance is much narrower than the headline suggests: **only one of 39 trades changes**. VST's August 26 reject falls from +5.1238R to +2.5429R or +2.6679R. Every other C4 trade has the same entry, stop, and R as baseline. This is not a representative test of the replanned, distant-target HOOD giveback problem.

**Proposed comparison:** retain the ladder on normal geometry. In the separately labeled cohort of actual replanned entries with distant first targets, compare a single predefined earlier-profit policy against the same entry, contract, original quantity, and remaining runner. Use the option's executable bid path and fees when available; otherwise keep the outcome unknown. Do not infer profitability from underlying MFE, a candle high, or a hypothetical trim that still lets the sold quantity ride the subsequent winner. C5's wider range-break entry net loss and C3 continuation's single added trade do not support loosening entries to create activity.

## Limits that matter to a profitability decision

The complete C3 book loses its positive total if its three best modeled trades are excluded: +11.3810R becomes -2.1104R. That concentration is consistent with a runner-dependent method and makes broad profit caps hazardous. It also means neither the total nor a favorable family split establishes a robust edge from 13 sessions.

The gross expectancy of +0.3449R/fire under C3 is an upper allowance for all trading friction under this model, not a forecast. Real costs vary with share price, option premium, spread, contract count, and stop distance. At-level entries may not fill at the modeled level; simultaneous signals may compete for cash. No actual capital allocation or net option comparison was reconstructed here. Some historical sessions have fewer than 390 minute bars. This review uses the persisted cohort rather than claiming a newly validated complete-market replay.

New-session measurement should retain the original full baseline, report net fill-based results separately from these R proxies, show at least the chronological blocks above, and publish the outcomes of the largest contributors. Today's results belong in that forward evidence even if they contradict the historical family ranking. Nothing here authorizes changing normal September 15 trading behavior.

## Reproducible source identifiers

| Label | Sweep ID |
|---|---|
| `evo-C-baseline` | `793512a5b553488ebc089068cc7061c3` |
| `evo-C3-gap0.5` | `e032e96d981447409f40624599ebe810` |
| `evo-C3-gap0.5-cont` | `4825a5f9970e42e0b8e535f97576ea31` |
| `evo-C4-far0.75` | `9b4e4e4a073a422480798f4d6bcac5e3` |
| `evo-C4-far1.0` | `83ecfa0b22934e1da4298f1360c890ce` |
| `evo-C5-range` | `db2961acad324915a0d5bf04e4a361e2` |
| `evo-C3C5` | `d159e97d93d94bae9c5bb39c124cee5a` |
| `evo-T14-baseline` | `b48db0763a1b40459a2cecd309f514ad` |
| `evo-T14-scratch0.5` | `de5cf24a456d496ca2cef329115063fa` |
| `evo-T14-scratch0.75` | `2e1b5600aca74e688683fd122dacbf15` |
| `evo-T14-scratch1.0` | `80711f4d88eb4f749e3725bcff302b79` |

Derivation: join sweeps to walkforward on `sweep_id`; expand `result.triggers`; select `status=fired`; sum `sim.rMultiple`; count wins where R > 0. For target geometry, join the saved `plan.triggers` on trigger ID within the same walkforward row. Pair variants on symbol, build session, and trigger ID, then compare fire time, fill, stop, and R. No raw database or source transcript was exported.

Active review folder: `C:/Cursor/zargar-codex`, branch `codex/zargar-development`. Only this derived Markdown report was added. No tests, strategy executions, paid model calls, runtime restarts, or setting changes were performed.
