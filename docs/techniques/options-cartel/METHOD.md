# The Options Cartel method — research draft

Version: research-0, 2026-09-06. Not yet an executable specification.
Author statements are paraphrased; performance claims are not verified evidence.
Source identifiers resolve in SOURCES.md. No thresholds borrowed from Team2 or EM.

## M1. Market and theme selection

S01 describes momentum swing trading through a top-down selection process:
market condition, theme, sector, leading stock, then setup. The advancing stage
of the four-stage market cycle is preferred. Failed breakouts and choppy markets
are reasons to remain in cash; aggressiveness increases when follow-through returns.

S02 makes the trend gauge more concrete: SPY/QQQ relative to the 8, 21, and
50 EMAs. Above these averages supports larger long exposure; below them calls
for reduced size or abstention. The author does not specify an exact numeric
size multiplier or how to resolve disagreement between the two indices.

S01 selects industries in the top ten of both weekly and monthly performance
rankings on TradingView. This is theme selection, not an options-flow signal.
The ranking universe and historical point-in-time membership need recording.

## M2. Universe and focus list

S02's stock screen: price above $3, market capitalization above $300 million,
volume above 500,000, ADR above 3%, and price above the 21/50 EMAs. Sort by
descending volume and narrow to four or five promising stocks in leading sectors.
ADR lookback and the exact volume measurement window are not stated in the text.

S01's weekly context favors substantial bases, proximity to highs, limited
overhead supply, relative strength, and healthy trends. Inspect the daily chart
for the actual consolidation. Named winning stocks are examples, not a permanent
universe. No survivorship-biased backtest may use today's leaders as past selections.

## M3. Setup and volume sequence

Both sources prefer contraction before expansion: a strong advance on increased
volume, quieter consolidation, and returning volume when price leaves the base.
S01 includes flags, wedges, inside days, bases, moving-average pullbacks, and
breakout/retests. Tightness and clear risk matter more than the pattern label.
Numerical definitions of tightness, relative strength, volume expansion/dry-up,
base duration, proximity to highs, and acceptable resistance remain unresolved.

## M4. Entry and initial risk

Plan the trigger, invalidation, exposure, and profit-taking before entry.
S02 uses repeatedly rejected resistance as the breakout trigger and seeks
volume confirmation. Its text allows 5m/15m confirmation; S01 describes
weekly → daily → hourly → 30m/15m entry analysis.

S02 places the initial stop at the low of the daily breakout candle. This must
be implemented causally: a completed day's final low is not available at an
intraday entry. Whether to freeze the low-so-far, wait for the daily close, or
use a separately documented intraday rule needs explicit resolution.

The earlier focus-list thread S03 describes a 5-minute close above resistance
and the breakout candle's low as its stop. This is a material historical
difference, not permission to silently select whichever backtests better.

## M5. Profit-taking and holding

S01: trim 25% at the first meaningful target/resistance during strength, then
raise the stop to entry. Trim an extension measured as three ATRs above the
8 EMA. Sell portions after daily closes under the 8/21/50 EMAs to retain
exposure while momentum persists. Exact later fractions, ATR period, extension
repeat behavior, and same-bar priority are not specified.

S02: take 25% portions at resistance (Fibonacci levels for all-time-high cases),
move the stop to entry after the first trim, and after the second trim use daily
closes below the 8 EMA and then 21 EMA for the final 25% portions. Exact Fibonacci
anchors and extension ratios are not specified. S01's later 50 EMA mention
must remain visible as method evolution rather than an invented fifth quarter.

The author's description of a stop-at-entry trade as risk-free does not remove
overnight gaps, slippage, fees, option decay, or differences between underlying
and contract prices. Store underlying stop geometry separately from option P&L.

## M6. Options expression — research still required

These threads refer to options and publish example contracts, but the inspected
text does not establish a universal DTE range, strike/delta rule, premium cap,
spread threshold, earnings policy, or max holding period. Do not substitute
Team2's 0DTE selection or EM's just-OTM weekly policy. Source examples, images,
and videos are still to be inspected for these rules.

S06 adds important exceptions to the bullish swing examples: a bearish MSTR
300 put (March 28 2025 expiry) follows a bear-flag breakdown with weak market
and Bitcoin context. Sean says short-dated/weeklies and 0DTE are unusual for
him, rather than the method's default. A RGTI share trade illustrates choosing
equity when high ADR and IV make option premiums unattractive. The implementation
must support bearish puts and a deliberate shares/options decision, not only calls.

S06's HOOD example reports an underlying trigger of $48.80, initial stop $48.32,
first target $55, Jun 20 2025 $50 calls at $2.49, another trim at $63, and
remaining exposure trailed by the 8 EMA. It reports closing/rolling on June 6
as expiry approached. Entry date and complete partial-fill quantities are absent
from the text, so this is not sufficient to infer a universal DTE or realized return.

## M8. Versioned variants (do not blend silently)

| Source | Scan/trend differences | Exit differences |
|---|---|---|
| S08, Dec 2025 | ADR >2%, 21/50 below price; weak indices may support downside trades | Three quarter-position trims at targets, then 8 EMA runner |
| S04, May 2026 | ADR >2%, positive change, 8/21 below price; focus list 5–10 | First quarter at resistance; subsequent quarters on daily 8/21/50 EMA breaks |
| S02, Jun 2026 | ADR >3%, 21/50 below price; focus list 4–5 | Two strength trims, then daily 8/21 EMA quarters |
| S02 scanner image | ADR >2%, **10-day average** volume >500K, 21/50 below price | Image only defines screen; exit choice remains sourced from thread text |
| S01, Sep 2026 | Weekly/monthly top-ten industry agreement, weekly-to-daily context | First quarter at resistance; 3xATR-from-8-EMA extension trim; daily 8/21/50 portions |

S05 (volume thread) adds breakout candle quality: range expansion, close near
the high, and expanding volume. It describes a volume moving-average cloud but
does not give its lookback in the inspected text. Volume is supporting context,
not a standalone buy signal. Use comparable completed periods and avoid treating
an unfinished daily volume total as a completed-day observation.

## M9. Main-thread image review

All eleven S01 images were visually inspected. The DRAM/SMCI/SNDK charts
illustrate contracting pennants/flags into EMAs, with preceding higher volume
and quieter consolidation; OSCR illustrates a flat-top daily base. CRCL is a
weekly descending base/trendline example. MU shows the renewed breakout volume.
The larger MU management chart annotates entry over a flat-top base, stop at the
day's low, a first strength trim/stop-to-entry, a second extension trim, and final
daily close below the 21 EMA. The exit infographic explicitly includes the
3xATR extension and daily 8/21/50 EMA portions, but still does not allocate every
later fraction. Chart drawings illustrate geometry; do not treat their plotted
levels as a complete, timestamped execution record.

## M10. Public ledger limitations

S07 links a public workbook whose Sean tab mixes swings, day trades, scalps,
lottos, hedges and rolls from 2021 onward. Historical records must be classified
before they are used as evidence for the September 2026 swing method.
The displayed return can reflect the highest trim rather than weighted realized
P&L: row 4 (CCJ) shows entry 2.10, highest trim 2.68, final exit 1.80 and 27.62%.
That percentage matches the peak trim, despite the remaining position exiting
below entry; quantities are not given. Never aggregate this column as an audited
strategy return or use it directly for practice-to-live graduation.

## M7. Operating routine and evidence

Nightly: assess market, rank themes, find leaders, inspect weekly/daily structure,
mark levels, prepare alerts, and maintain a short focus list. Wait for a planned
trigger rather than forcing trades every day. Positions may last weeks.
Research outcomes, hypothetical fills, and actual portfolio executions must
remain distinct. Capture source, rule version, inputs, decisions, and market
timestamps so every scan/entry/exit can be reviewed and replayed.

## M11. Expanded source review

All 21 texts in the discovered archive have now been read. See
[SOURCE-REVIEW.md](SOURCE-REVIEW.md) for dated scanner changes, explicit bearish
rules, gap-retest handling, option delta guidance, 1% risk guidance, the older
weak-follow-through 50% first trim, and unresolved reward/risk basis. These
findings refine the method without silently changing existing saved plans.

## M12. September video cross-check

S24 confirms the daily-trend process, EMA8/21/50 context, individual leaders,
base breakouts, 5m/15m execution and day-low stop. Its scanner explicitly uses
relative volume >1, ADR >2% and 10-day average volume >500K. This is now a
separate `september_2026_video` screen profile. See [VIDEO-REVIEW.md](VIDEO-REVIEW.md)
for timestamped evidence, the strict price-boundary choice and the distinction
between the video's entry-at-break description and Zargar's closed-bar gate.
The clip supplies no replacement exit allocation or option-selection policy.
