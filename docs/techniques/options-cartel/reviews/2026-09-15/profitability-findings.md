# Cartel profitability review — Tuesday, September 15, 2026

## What the account earned

The dedicated Options Cartel Practice book (`0b48ed48de2f4030b49942b52858356d`, USD) finished Tuesday flat, with **no Tuesday orders, fills, fees or P&L**. Cash remains **$9,938.87** against $10,000 starting cash. The complete book execution query still contains only Monday's APA round trip:

| Period | Closed campaigns | Gross realized | Fees | Net realized | Open quantity |
|---|---:|---:|---:|---:|---:|
| Tuesday Sep 15 | 0 | $0.00 | $0.00 | $0.00 | 0 |
| Cumulative through Tuesday | 1 | -$59.05 | $2.08 | **-$61.13** | 0 |

Cumulative book return is **-0.6113%**. Monday's one APA call was bought at $3.30 and sold at $2.7095; each execution carried $1.04 commission. Its position row is zero. There is no remaining APA marked exposure to add to Tuesday's result.

Source: read-only runtime database observation beginning **2026-09-15 20:47:49 UTC**. Audit code: `b691afc219a34e1b12b40871d6774836c4a8a2ec`. No implementation, runtime setting changes, engine launches, broker calls or database tests were performed.

## Did abstention miss money or avoid losses?

**For the five selected names, the baseline evidence favors Tuesday's abstention.** Ignoring only the market-permission block, the saved 15-minute rules identify one qualifying stock signal: BOX. It had almost no favorable movement after the next-minute modeled entry and ended below it. That is one avoided exposure to an unfavorable stock path, **not a proved dollar saving or a realized option loss**. This does not establish that the five-name ranking found the day's best opportunities; omitted candidates need the same causal evaluation. No profitable option trade is established as missed by this sub-review.

This is narrower than saying the market filter avoided five losing trades. PPC and EL never reached their planned long triggers; their entry rules already kept them out. NTNX touched its first target but never produced a qualifying baseline entry. ARE rose, but its stored context did not qualify and a favorable daily candle cannot establish an executable option opportunity.

Preparation `b026e513a1714235ad78b417803f5f8e` had **nine research candidates** and selected the five below. This review covers those five, not all nine or the whole market. The targets/invalidations were fixed from completed history before Tuesday's open. All five were `ma_pullback` setups. The saved market policy was already **moderate**, not strict: Monday's QQQ close $709.18 was below its $710.97494 50 EMA, while SPY was above its 50 but below its 8/21. The existing moderate gate therefore blocked longs.

## The five saved setups versus Tuesday's stock tape

Prices below are underlying-stock observations, not fills or option returns. Monday-close returns show the day's gap and session together; open-to-close returns are a different, hypothetical holding interval.

| Symbol | Long trigger | Pre-entry invalidation | First target | Tuesday open / high / close | Close vs Monday | Open to close | Baseline interpretation |
|---|---:|---:|---:|---|---:|---:|---|
| BOX | 35.1800 | 34.3100 | 36.0500 | 34.4500 / 35.3200 / 34.8150 | -0.13% | +1.06% | One qualifying noon signal; subsequent entry-to-close path negative |
| NTNX | 68.1250 | 66.4200 | 68.8000 | 66.5500 / 68.9100 / 68.0100 | +0.47% | +2.19% | Target touched, but the crossing's volume was insufficient; no qualifying baseline signal |
| ARE | 52.7100 | 51.2100 | 53.2900 | 51.6700 / 53.2800 / 52.9300 | +1.87% | +2.44% | Stronger stock day; first target was not reached; saved context coverage blocked certification |
| PPC | 31.2400 | 30.2400 | 31.6200 | 30.2050 / 30.2050 / 29.8700 | -1.26% | -1.11% | Opened below invalidation and never approached the trigger |
| EL | 99.1000 | 96.4200 | 99.8200 | 97.6000 / 97.9900 / 96.2450 | -2.01% | -1.39% | Never reached trigger; trusted 15-minute close invalidated at 12:15 ET |

For context, SPY closed -0.455% and QQQ -0.647% versus Monday. Three shortlist stocks rose from Tuesday's open, but only two rose versus Monday's close. This demonstrates why selecting a favorable start price after the fact is not a strategy result.

### BOX: a valid stock confirmation with no follow-through

The saved watch-context plan (`33438da2baf2c716f008f276df3fd578`) and original 15-minute baseline produce the following conditional result when the market block is ignored for research:

| Measurement | Result |
|---|---:|
| Confirmation | 12:00 ET |
| Confirmation close | $35.2300 |
| Confirmation volume / baseline | 96,323 / 59,078 = **1.63044x** |
| Directional close location | **0.78571** versus required 0.70 |
| Causal session-extreme stop | $34.4500, known at confirmation |
| Next-minute modeled entry | **$35.2400** |
| Post-entry maximum high | $35.2450, only **+0.0063 initial underlying R** |
| Post-entry minimum low | $34.6800, **-0.7089 R** |
| Last regular-session close | $34.8150, **-1.2060% / -0.5380 R** from modeled entry |
| First target / initial stop touched after entry | Neither |

The full-day high $35.32 occurred **before** this modeled entry. Counting that earlier high as a post-entry gain would materially exaggerate the opportunity. The -0.538 R is an underlying endpoint mark, not a closed trade or option P&L. The original multi-day exit policy could continue holding; no fictitious EOD liquidation has been added.

### NTNX: a target touch does not prove a missed qualified entry

At 11:00 ET, the 15-minute close crossed $68.125 at $68.1399. Its volume was 38,529 against a 57,225 baseline: **0.67329x**, below both the configured 1.5x threshold and a 1.0x alternative. Earlier untrusted minutes also prevent a verified session-extreme stop in the stored tape. The next minute opened $68.09, already back below the trigger. Later trading above $68.80 therefore cannot be assigned as profit on an assumed baseline entry.

### ARE and PPC: distinguish missing qualification from price direction

Latest pre-open watch context `597605028732d07403b1b56b503d6d9a` contains saved plans/baselines for BOX, NTNX and EL. It records ARE/PPC baseline coverage as **25/26 and 24/26**, insufficient under the actual first-hour coverage requirement. Their original analysis records contain no baseline minutes, but the separate history cache does contain the earlier inputs; absence from an analysis record is not archive absence.

ARE's first observed 15-minute price crossing at 11:45 ET closed $52.755, but the next minute opened $52.70, below its $52.71 trigger. The crossing bucket also includes untrusted sampled bars. Later 12:45 and 15:45 price crossings are not retroactively interchangeable with a valid first entry. ARE's $53.28 high remained approximately one cent below the $53.29 first target. PPC's entire session stayed below its trigger, independently of any baseline reconstruction.

## What the bounded parameter comparison actually says

The parent review's saved `.cache/entry-sweep-results.json` contains **35 cases: seven variants × five names**. This sub-review independently reproduced the fixed 15-minute base using saved watch-context plans and did not run a second optimization grid.

| Single change from baseline | Signals in this selected set | Profitability interpretation |
|---|---|---|
| Baseline: 15m, 1.5x volume, session stop | BOX only | Unfavorable entry-to-close underlying mark |
| 5m confirmation | BOX only, earlier at 09:40 | About -0.513 underlying R at close; earlier entry did not unlock a profitable observed path |
| Volume 1.0x | BOX only | Lowering volume added no useful opportunity here |
| Volume 2.0x | None | Avoided BOX in this sample, but zero trades on one day does not establish superior expectancy |
| 30m confirmation | None | Same opportunity-cost question; no optimization verdict |
| Retest entry | None | A useful prospective challenger, not proven best by this day |
| Breakout-bar stop | BOX; $35.01 stop touched at 14:48 ET | Tighter stop changes dollars at risk and holding duration; -1R on this smaller denominator is not directly comparable with the baseline's -0.538R endpoint |

The 5-minute reconstruction had sufficient baseline coverage for all five, yet still produced only BOX. ARE was constrained by target room (a recorded candidate offers about 0.182R versus 0.25 required) and session evidence; PPC invalidated. NTNX failed volume even at 1.0x. Today does not support the simple thesis that more permissive entries would have produced more profitable trades.

## Ranked profitability experiments

These are proposals for frozen, prospective comparisons, not settings to activate based on one day.

1. **Evaluate all nine candidates before optimizing the top-five ranking.** The parent review's separate post-close Alpaca historical fetch found DT +4.548% and GH +5.040% open-to-close, versus BILL +1.896% and OCUL -5.288%; DT/GH had 390/388 minute observations and BILL/OCUL 344/367. These are freshly retrieved historical stock paths, not as-observed entry decisions, option returns or proof of valid missed Cartel trades. They are a concrete reason to compare the omitted four with the selected five using the same pre-existing triggers, causal confirmation, targets, stops, contract costs and whole-lot exits. BOX's first-place structural-target-R rank is not expected return. Start with full-denominator research and a fixed leadership/liquidity/economic-room ranking challenger; do not simply add trades or hindsight-select DT/GH.
2. **Test trade follow-through and failed-break loss containment.** BOX passed volume/close tests but delivered essentially zero post-entry upside. Compare the present entry/exit policy against one explicit challenger, such as requiring a separate successful retest or exiting a confirmed failed breakout before the distant session stop. Keep market regime, budget, contract-selection rule and all other parameters fixed. Measure net option return, frequency of early exits before eventual winners, capital tied up, and loss tails. Do not simultaneously optimize retest, volume, stop distance and timing.
3. **Measure option-level opportunity before increasing activity.** At prospective signals, record a fixed eligible contract, ask entry/bid exit evidence, fees, spread, DTE, delta and whole-contract quantity—even for a non-executing comparison lane. Compare achievable first-target/runner proceeds with premium and transaction costs. A stock target of roughly 0.7–1.2% is not automatically attractive for a call buyer, and a $500 budget may fund only one contract with a different exit schedule. Do not increase risk just to obtain more trim units. Option prices also depend on time and implied volatility, so stock gains cannot be translated directly into call profits. [OCC/OIC option-price explanation](https://www.optionseducation.org/referencelibrary/faq/option-price-behavior).
4. **Compare selective leadership exceptions with the current moderate regime rule.** ARE and NTNX outperformed weak indices, which is a reason to study selective exceptions, not remove the market gate broadly. Require an independently specified intraday leadership/volume/price condition, use the same candidate denominator, and retain all no-entry and failed-qualification outcomes. Today's only baseline-qualified long in the top five had a poor subsequent stock path; evaluate the omitted candidates before judging the ranking or regime filter across all nine. One day's stock winners must not become hindsight picks, and seven trial variants must not be presented as seven independent confirmations.

For promotion, evaluate paired prospective opportunity sets across sessions, keep equal or explicitly matched capital/risk, include fees and no-fill outcomes, and separate realized P&L from open marks. Twenty sessions is an operational review checkpoint, not an automatic profitability claim. A result driven by one ticker/day, missing quotes, or a changed risk denominator is not sufficient evidence to raise allocation.

## Evidence and reproducibility

- Saved preparation: `b026e513a1714235ad78b417803f5f8e`; source cutoff 2026-09-15 04:03:01.861 UTC; resumed record created before the regular-session open.
- Latest watch context: `597605028732d07403b1b56b503d6d9a`, created 13:27:14.296 UTC, before the 13:30 open.
- Analysis IDs: BOX `a2b1dd78f40c4d149e8902096096235c`; NTNX `326d7201629547a78e300d7fed432428`; ARE `d9ac8a0af2d04d5fb419ec151c3f4c38`; PPC `36244f95b720463fa9c6c15170159491`; EL `cfb44f8cefd54cf5816675ae2cbefbf7`.
- `.cache/base_stock_study.py` performs a bounded read-only extraction and the pure `read_entry` calculation; `.cache/base-stock-inputs.json` contains only these five names' session minutes, saved watch context, shortlist and prior closes; `.cache/base-stock-results.json` retains results and price-event chronology.
- Each name has 390 stored session minutes. Exchange/sampled counts are BOX 381/9, NTNX 371/19, ARE 350/40, PPC 344/46, EL 378/12. Source flags were preserved; unsupported prices were not relabeled to manufacture valid entries.
- Scope limit: underlying analysis and hypothetical rule comparisons only. No selected exact-contract option execution/valuation was reconstructed for Tuesday; no monetary avoided-loss or missed-option-profit estimate is made.
