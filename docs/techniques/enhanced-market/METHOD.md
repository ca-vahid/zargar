# Technique: EnhancedMarket (Day Trading 101)

Codification of the trading method in `docs/Day Trading 101 - From Beginer to Expert.pdf`
(Zachary Cohen / "EnhancedMarket", TradeProElite, 2024, 123 pp.) into rules a
machine can evaluate.

This document is the **specification** for the technique pipeline. Each rule is
numbered (`T1.1`, `R2`, …) so pipeline code, prompts, and journal events can cite
the exact rule that fired. Page numbers refer to PDF pages.

---

## 0. Scope — what we take and what we drop

| Book section | Pages | Verdict |
|---|---|---|
| Introduction / author bio | 4–11 | **Drop** — biography |
| Ch 1: Starting Your Trading Journey (brokerages, cash vs margin, enabling options, how much to start, paper trading, years 1–3) | 12–20 | **Drop** — we have accounts, a mock ladder, and a risk gate already |
| Ch 2: Mastering Options Trading (contracts, strike, expiry, Greeks, IV, OI, bid/ask) | 21–32 | **Partial** — terminology dropped; the author's *personal selection rules* (§6) are kept |
| **Ch 3: Technical Analysis Essentials** | **33–60** | **KEEP — this is the engine** |
| **Ch 4: Risk Management Strategies** | **61–66** | **KEEP — sizing, no-trade gates** |
| **Ch 5: Developing Your Trading Edge** | **67–82** | **KEEP — entry, TP/SL, averaging** |
| Ch 6: The Trader's Mindset | 83–110 | **Drop** — psychology, not executable |
| Conclusion / Actionable Next Steps / community | 111–123 | **KEEP** (corrected 2026-08-22) — trading schedule (§R6), 30m/1h timeframe preference, disable after-hours data, pre-session watchlist + alerts at levels, redraw levels daily, chart-based stops, the One-Contract Rule (R5) |

The author states his entire method rests on **two** things (p. 32):

> Support and Resistance levels — Flag patterns (particularly falling wedges and flags)

Everything else in Ch 3–5 is confirmation, filtering, or trade management around
those two primitives. No indicators, no oscillators, no moving averages.

---

## 1. The method in one paragraph

Find horizontal price levels that the market has repeatedly respected (support /
resistance). Wait for price to either **(a)** return to a support level after a
compression pattern (falling wedge / bull flag), or **(b)** break decisively
through a level. Use **volume** as the sole confirmation instrument: volume must
dry up during compression and spike on the breakout. Enter *at the level*, not
after visual confirmation. Stop goes just beyond the level that invalidates the
idea. Targets are the measured height of the pattern, taken in scaled tranches
with a runner. Express the trade as a slightly-OTM weekly or 0DTE option. Risk
per trade is small enough that the position can breathe.

---

## 2. Module T1 — Support & Resistance levels

**Source: pp. 33–35, 40–41, 70.**

### T1.1 Definitions
- **Support**: price level where downward movement stalls on increased buying.
- **Resistance**: price level where upward movement pauses on increased selling.

### T1.2 What makes a level real
A level's strength is the count and quality of its **touches**. The book's charts
annotate levels that were touched **2–3 times** ("Support 1/2 … tested twice,
showing its significance"; resistance "touches or comes close … three distinct
instances", pp. 33–34).

> **Rule T1.2** — A level requires **≥ 2 touches**. 3+ touches = strong. Each
> touch reinforces significance.

### T1.3 Level sources, in priority order
1. **Prior-day High of Day (HOD) / Low of Day (LOD)** — the book calls trends
   formed at the day's absolute extreme "the strongest… like the highest
   watermark left by a flood" (p. 70).
2. **Previous day's support/resistance** — "Always be aware of previous day's
   support/resistance levels. They often play a significant role in the next
   day's price action" (p. 70). The worked SPY example uses a support at
   `498.75` carried over from the prior session.
3. **Intraday swing highs/lows** with ≥ 2 touches.
4. **Round numbers** — `$50`, `$100`, `$1000` act as levels "simply because many
   traders place their orders at these psychologically significant prices" (p. 40).

### T1.4 Psychology (informs confidence, not detection)
Memory/anchoring, round numbers, pain-and-regret (breakeven selling at old
highs), fear/greed, institutional order placement, confluence, herd mentality
(pp. 40–41). Used to *explain* a level in the rationale field, not to find it.

### T1.6 Pre-session routine: levels are prepared, alerted, and redrawn daily
**Source: pp. 115–117, 120 (added 2026-08-22).** "Before the session begins, prepare your own
watchlist" (p. 116); the author's own pre-market stream is "key levels… for the day ahead"
(p. 115); "set alerts above and below key levels" (p. 117); "at the end of each trading
day, remove all your drawings… start fresh the next day by redrawing your levels" (p. 120).
Together with T1.3a/b (prior-day levels carry into the next day, p. 71) this is the
close-of-N → plan-for-N+1 workflow: a **Session Plan** of levels + conditional triggers,
rebuilt every session (`technique/plans.py`, `docs/techniques/enhanced-market/WALKFORWARD-PLAN.md`).

### T1.5 Trendline drawing rules
**Source: p. 68.** These are hard constraints on any sloped line the model draws:
- Not steeper than **45°**.
- Consistent anchoring: **either wick-to-wick or body-to-body**, never mixed.
- **Minimum 3 touch points** for validity.
- Only the "most obvious and valuable" lines — keep the chart clean.
- Strongest trends form from **daily highs/lows**.

---

## 3. Module T2 — Volume analysis

**Source: pp. 35–41, 51, 58–59.** Volume is the only confirmation tool in the
method. "Volume is the fuel that drives price movement. Without volume, price
doesn't move" (p. 59).

| Rule | Pattern | Meaning |
|---|---|---|
| T2.1 | Rising price **+** rising volume | Trend confirmed, likely to continue |
| T2.2 | Rising price **+** falling volume | Bearish divergence — trend losing steam |
| T2.3 | Falling price **+** falling volume | Selling pressure weakening — bounce likely |
| T2.4 | Volume spike after prolonged trend | Possible climax / reversal |
| T2.5 | Breakout **+** volume surge | Genuine breakout |
| T2.6 | Breakout **+** low volume | **Fakeout warning** |
| T2.7 | Large volume, small price move | Institutional accumulation/distribution |
| T2.8 | Low volume during consolidation | "Calm before the storm" — indecision preceding a move |

> **Rule T2.9 (measurement basis)** — "Compare current volume to the average
> volume" (p. 41, p. 59), and specifically "compare current volume to the average
> volume **at that time of day**" (p. 63). Volume judgements are relative to a
> time-of-day baseline, never absolute.

---

## 4. Module T3 — Patterns

### T3.1 Falling wedge (the primary pattern)
**Source: pp. 41–47.** Bullish. Works as a reversal in a downtrend *or* a
continuation in an uptrend.

**Identification (all must hold):**
1. A series of **lower highs and lower lows**.
2. Two trendlines — upper on the highs, lower on the lows — **converging**; the
   upper line's downward slope is **steeper** than the lower line's.
3. **Volume decreasing** as the wedge forms.

**Trading it:**
- **Entry**: on a decisive break **above the upper trendline**, confirmed by a
  volume spike. "It's important not to jump in too early" (p. 46).
- **Stop**: just **below the lowest point of the wedge** — the most recent low
  before the breakout.
- **Target**: measure the **height of the wedge at its widest point** (the
  distance between the trendlines at the *start* of the pattern) and project that
  distance **upward from the breakout point** (p. 46).

**Modifiers (p. 47):** longer-forming wedges → more powerful breakouts; the
pattern is timeframe-agnostic but a wedge on a higher timeframe signals a more
significant reversal.

### T3.2 Consolidation / flag patterns
**Source: pp. 47–48.** Value: they give a tight, clear stop level ("low-risk
entry points"), have a high success rate when traded correctly, and a strong
break from one "often leads to significant moves".

### T3.3 Breakout vs Fakeout
**Source: pp. 54–58.** This is the highest-value discriminator in the book.

**A true breakout needs all three:**
1. **Volume confirmation** — volume tapers as price approaches the level ("a
   coiled spring compressing"), then **surges** on the break.
2. **Decisive price action** — a **large candle closing clearly beyond** the
   level, with **minimal wicks**. Merely touching or slightly exceeding the level
   does not count.
3. **Follow-through momentum** — the next few candles continue in the breakout
   direction. Lack of follow-through is a warning.

**A fakeout shows:**
1. **Lack of volume** — the single most reliable tell.
2. **Quick reversal** — long wicks; price pierces the level then snaps back to
   close within or beyond the prior range.
3. **Failure to hold** — price cannot maintain its new position above resistance
   / below support. Produces bull traps and bear traps.

> **Rule T3.3.4 (multi-timeframe)** — "A breakout on a lower timeframe might be a
> fakeout on a higher timeframe" (p. 59). Breakout calls must be cross-checked on
> a higher timeframe.

### T3.4 Candlesticks & momentum
**Source: pp. 49–54, 67.**

- **Close position** — close near the high = buyers in control; close near the
  low = sellers in control.
- **Wicks are rejection**. Long **upper** wick = bearish; long **lower** wick =
  bullish. "The longer the wick, the stronger the signal" (p. 67).
- **Named patterns**: doji (indecision), hammer / hanging man (reversal warning),
  engulfing (strong reversal).
- **Candle size & frequency** — in a strong trend, candles of the dominant colour
  are *more frequent and larger*. Green growing while red shrinks = building
  bullish momentum, and vice versa.
- **Context overrides the pattern** — "a bullish candle in a downtrend might just
  be a brief pause, not a reversal" (p. 54).

### T3.5 Trend structure
**Source: pp. 52–53.** Trend direction is read **without trendlines**:
- **Uptrend** = series of **higher lows and higher highs**.
- **Downtrend** = series of **lower highs and lower lows**.
- Confirm on multiple timeframes.

---

## 5. Module T4 — Entry, stop, and target arithmetic

### T4.1 The entry principle
**Source: pp. 74–75.** "Buy at support and sell at resistance."

The book's own worked example of why late entry is fatal:

| | Optimal | Suboptimal |
|---|---|---|
| Support / Resistance | $100 / $105 | $100 / $105 |
| Entry | $100 | $103 |
| Stop | just below $100 | still just below $100 |
| Reward | $5 | $2 |
| Risk | small | 3× larger |

Second worked example (SPY, p. 75): support $437, resistance $438 — entering at
$437 risks ~$0.25 to make ~$1.00; entering late risks $0.75 to make $0.50.

> **Rule T4.1** — Entry is placed **at the level**, and the R:R is computed from
> the level, not from the current price. If price has already travelled away from
> the level such that R:R falls below threshold (§R3), the setup is **expired**,
> not chased.

### T4.2 The "visual confirmation" trap
**Source: p. 75.** Waiting to see the trade prove itself before entering is
explicitly named as a mistake — "like waiting for a train to start moving before
jumping on". Once entry/stop/target are defined, execute without hesitation.

⚠ **Tension to resolve.** T4.2 (enter at the level, don't wait) directly conflicts
with T3.1/T3.3 (wait for the breakout candle **and** volume confirmation). The
book never reconciles these. Reading the examples, the resolution appears to be:
- **Support-bounce entries** (buy the dip into support) → enter *at* the level, no confirmation wait.
- **Breakout entries** (through resistance / out of a wedge) → *require* volume + decisive-candle confirmation.

The pipeline treats these as **two distinct setup types** (§8).
**DECIDED (2026-08-21):** confirmed by the user — Setup A and Setup B are
modelled separately, with confirmation required only for Setup B.

### T4.3 Stop-loss
**Source: pp. 72–73.**
- The author uses **mental stops only**, on the grounds that hard stops get
  hunted by liquidity grabs.
- Stop reference = **the level below support**, not a candle close or exact
  price. Worked example: long at $100 with support at $98 → mental stop zone
  ~$97.50.
- On a touch of that zone he does **not** auto-exit; he watches the reaction at
  support — bouncing back above with strong volume = hold; struggling to reclaim
  = exit.
- **Exception (p. 79):** when averaging down, a **hard stop is mandatory** — "a
  mental stop-loss isn't enough".
- Falling-wedge stop (p. 46) = just below the **lowest point of the wedge**.

> **Implementation note.** A mental stop is a *monitoring rule*, not an order. In
> our system this maps to a **stop-watch alert + re-evaluation trigger**, with a
> hard protective stop placed further out as a disaster backstop. This is a
> deliberate divergence from the book and must be flagged in the UI.

> **Rule T4.3d (added 2026-08-22)** — the stop is **chart-based, just below the level
> that invalidates the idea, never a fixed percentage** of price or premium: "avoid the
> common advice of using a stop loss based on a fixed percentage… set your stop losses
> based on the chart" (p. 117). The book's own bounce example ($98 support → watch
> ~$97.50, p. 73) is a zone just under the level; `setups.bounce_stop` uses the larger of
> that 0.5 %, two touch tolerances and 0.25 ATR (`technique.bounce_stop_pct`).

### T4.4 Take-profit ladder
**Source: p. 73.** The author's own worked structure, long at $100:

| Tranche | Level | Action |
|---|---|---|
| TP1 | $102 | trim **30 %** |
| TP2 | $104 | trim **40 %** |
| TP3 | $106 | trim **15 %** |
| Runner | — | final **15 %** on a trailing mental stop |

Note the ladder is evenly spaced (+2, +4, +6 from a $100 entry ⇒ **2 %, 4 %,
6 %**), with a 30/40/15/15 split. For pattern trades the TP anchor is instead the
**measured wedge height** (T3.1).

> **Rule T4.4** — Never exit on P&L. "It's also essential not to sell a position
> based on your Profit and Loss (PnL) statement… I focus solely on the chart and
> the technicals" (p. 46).

### T4.6 Confluence
**Source: p. 67.** "Aim for 2+ confluences (agreeing factors) per trade… conflicting
signals = potential to avoid the trade." `setups.confluences` counts them (prior-day
extreme, 3+ touches, volume posture, higher-timeframe agreement, rejection candle) and
fires **T4.6** when ≥ 2; plans carry the list per trigger.

### T4.5 Averaging down
**Source: pp. 77–78.** Permitted only under **all** of:
1. A **logical catalyst** for recovery. The book's test: SPY dropping on a rate
   *hike* = do not average; SPY dropping despite a rate *cut* = illogical
   reaction, valid opportunity.
2. **With the trend** — never against it.
3. **Only at established support levels** — "If you buy at support level 1 and it
   fails, wait for support level 2 before adding more."
4. **Predefined** before entry: whether averaging is allowed, exactly where, and
   how much additional capital.
5. **Hard stop-loss set.**

Worked example: 100 sh @ $100 → +50 @ $95 → +25 @ $90, hard stop $85, average
cost $96.43.

---

## 6. Module T5 — Options expression

**Source: pp. 22–23, 29.** The author trades the setup *through options*, not
shares.

> **T5.1 Strike** — "I always trade options that are **just OTM**." Rationale:
> lower premium, more leverage, buy-low-sell-high before expiry.

> **T5.2 Expiry** — "I primarily focus on trading **weekly** options. The furthest
> expiration I typically consider is **Friday of the current week**." When
> available he prefers **0DTE**, with **smaller position sizes** to compensate.
> Day traders generally use **0–3 DTE**.

> **T5.3 IV** — Do not buy when IV is "super high" — IV crush can lose money even
> when direction is correct. Avoid buying premium into earnings/events.

> **T5.4 Liquidity** — Avoid illiquid options with wide bid-ask spreads, inflated
> premiums, or poor Greeks (high theta, low delta) — see R4.

**Status in Zargar (DECIDED 2026-08-21):** wire a real options chain provider —
**Tradier** (`/v1/markets/options/chains?greeks=true`), which returns bid/ask,
volume, open interest, and full greeks + IV (bid_iv/mid_iv/ask_iv, sourced from
ORATS). That makes T5.1–T5.4 genuinely checkable rather than advisory. Setups
still emit **underlying** entry/stop/targets as the primary numbers, with a
concrete selected contract alongside. **Execution remains practice-only** — no
venue we hold trades options today.

---

## 7. Module R — Risk & no-trade gates

### R1 Position sizing
- p. 45: never risk more than **5 %** of the account on a single trade.
- p. 60: a common rule is **1–2 %** of portfolio per trade.
- p. 72: because he uses wide mental stops, he sizes **smaller** — "I might risk
  **0.5 %** of my account instead of 1 %."
- p. 60: **"full-porting"** (whole account on one trade) is forbidden.

> These three numbers are inconsistent. Treat **5 % as the hard ceiling**,
> **0.5–1 % as the working default** for wide-stop trades. Our existing
> `risk.max_position_pct` (10 %) is *looser* than the book — the technique needs
> its own tighter cap.

### R2 Win rate / R:R
- Professional win rates ~**50–55 %** (p. 61).
- Target **R:R ≥ 1:3** (p. 62).
- Worked math: 10 trades, 50 % win rate, 1:3 → 5 × −$10 + 5 × +$30 = **+$100**.

> **Rule R2** — Reject any setup whose computed R:R at the intended entry is
> **< 3.0**.

### R3 No-trade conditions
**Source: pp. 62–65.** The pipeline must be able to return *"no setup"* and say
why:
1. **Low volume** — volume significantly below average, low volatility. Explicit
   threshold given: **volume below 50 % of daily average**.
2. **Poor price action** — choppy, directionless; no clear trend or pattern;
   frequent false breakouts. Explicit threshold: **more than two false breakouts
   in the first hour of trading**.
3. **Unfavourable contract conditions** — inflated premiums, high theta/low
   delta, wide bid-ask.
4. **Calendar** — bank holidays, **FOMC** days, major economic releases (NFP,
   GDP). "The big players aren't in the game."
5. **Mental state** — not machine-evaluable; surfaced as a manual toggle.

### R4 Pre-trade checklist
**Source: p. 65.** Every setup emission runs: market volume check → price action
assessment → (mental state evaluation).

### R5 One-Contract Rule
**Source: pp. 117–119.** For the first 3–6 months, **one contract per trade
regardless of account size**. Maps to a hard quantity cap while the technique is
being validated.

### R6 Trading schedule (added 2026-08-22)
**Source: pp. 114–115.** "Understanding when to trade is just as important as knowing
how to trade."

| Rule | Window (ET) | Verdict | Book's reasoning |
|---|---|---|---|
| **R6.1** | 09:30–10:30 | Prime | highest volume/volatility, institutional orders, overnight news; momentum, breakouts, early reversals |
| **R6.2** | 14:45–16:00 | Prime | closing surge; end-of-day momentum, continuation, last-minute breakouts (the p. 71 SPY example) |
| **R6.3** | 10:30–14:45 | **Avoid** | "lower volume, choppy price action, lack of clear direction"; theta decay, false breakouts, whipsaws |
| **R6.4** | pre-market / after-hours | **Avoid** | thin volume, wide spreads, erratic swings |
| **R6.5** | — | data | "Disable after-hours data" (p. 114) — `history.py` fetches regular-session bars only |

> "Trading more does not equal making more. Focus on quality trades during
> high-probability times." (p. 115)

Implementation: `rulebook.session_window(ts)`; FACTS carry `sessionWindow`; a setup
found outside the prime windows is **watch only** (`technique.enforce_session_windows`);
scheduled scans run in `technique.scan.windows`; the backtester takes setups in prime
windows only by default; plan triggers require a prime window; armed plans log mid-day
touches as observed but do not fire.

### Timeframe preference (p. 114)
"Focus on 30-Minute and 1-Hour Timeframes… My personal win rate is significantly higher
on these timeframes (**78 %**) compared to lower time frames (**58 %**)." A single-trader
self-report on an unstated sample — **to be tested, not assumed**. Our reading: structure
(levels, patterns) is read on 30m/1h (`technique.structure_tfs`), the entry/trigger
decision on 1m/5m (`technique.trigger_tf`) inside the R6
windows; the walk-forward reports per structure timeframe (spec Q15).

---

## 8. The two setup types (derived)

Everything above composes into exactly two tradeable setups. This taxonomy is
*our* synthesis; the book presents these interleaved.

### Setup A — Support Bounce ("buy the dip")
| Field | Rule |
|---|---|
| Precondition | Established support (T1.2, ≥2 touches), price declining into it |
| Preferred context | Sharp sell-off into support with **little consolidation on the way down** — fewer overhead levels means a faster recovery (p. 67) |
| Confirmation | Long **lower wick** / hammer at the level (T3.4); falling volume into the level (T2.3) |
| Entry | **At the support level** (T4.1), no confirmation wait (T4.2) |
| Stop | Mental, just below support (T4.3) |
| Targets | Next resistance; ladder 30/40/15/15 (T4.4) |
| Invalidation | Decisive close below support on volume |

### Setup B — Breakout / Falling-wedge break
| Field | Rule |
|---|---|
| Precondition | Falling wedge (T3.1) **or** consolidation at resistance (T3.2) |
| Confirmation | **Required** — volume surge + large candle closing clearly beyond the level with minimal wicks + follow-through (T3.3) |
| Entry | On the confirmed break of the upper trendline / resistance |
| Stop | Below the wedge's lowest point (T3.1) |
| Targets | **Measured wedge height projected from the breakout point** (T3.1), then ladder |
| Invalidation | Fakeout signature: no volume, quick reversal, failure to hold (T3.3) |
| Cross-check | Must not be a fakeout on the higher timeframe (T3.3.4) |

---

## 9. What the pipeline must emit

The contract for a single analysis run. All prices are in the **underlying**.

```
symbol, asOf, timeframe(s) analysed
verdict:            setup | no_setup
setupType:          support_bounce | breakout | falling_wedge
direction:          long | short
levels:             [{ price, kind: support|resistance, touches, source, timeframe }]
pattern:            { kind, upperTrendline, lowerTrendline, widestHeight, formingBars } | null
entry:              { price, basis: "at_level"|"on_break", requiresConfirmation: bool }
stop:               { price, kind: mental|hard, reference: "below_support"|"wedge_low" }
targets:            [{ price, trimPct, basis: "measured_move"|"next_resistance"|"pct_ladder" }]
runnerPct
riskReward:         computed, must be >= 3.0
volumeAssessment:   { relativeToTimeOfDayAvg, trend, breakoutSpike, verdict }
confidence:         0-1
rulesFired:         ["T1.2","T3.1","T2.5","T4.1", …]   ← every rule cited by id
noTradeReasons:     ["R3.1 volume below 50% of average", …]
optionsExpression:  { strikeGuidance: "just OTM", expiry: "current-week Friday"|"0DTE", warnings: [...] } | null
rationale:          prose, referencing the rules
```

Two hard requirements carried over from the existing signal pipeline:

1. **Grounding.** Every level and price the model reports must be **verified
   against the actual OHLCV bars** in code — a claimed support at $98 must
   correspond to real lows near $98 with the claimed touch count. The vision
   model proposes; deterministic code disposes. Same discipline as
   `signals/extraction.py::ground_signal`.
2. **Journaling.** Every run appends to the `events` journal with the full
   `rulesFired` list, so a setup can always be explained after the fact.

---

## 10. Where the book is silent (decisions we must make)

These are genuine gaps — the book gives no number, so the pipeline needs a
configurable default and the numbers below are *our* proposals, not the author's.

| # | Gap | Proposed default |
|---|---|---|
| Q1 | Level **tolerance** — how close is a "touch"? | 0.15 % of price, or 0.25 × ATR |
| Q2 | **Timeframes** to analyse | 1m + 5m primary, 15m/1h for higher-TF cross-check |
| Q3 | **Lookback** window for level detection | Current session + prior 2 sessions |
| Q4 | "Volume spike" magnitude | ≥ 1.5 × the time-of-day baseline |
| Q5 | "Volume dry-up" magnitude | ≤ 0.7 × baseline, falling across the pattern |
| Q6 | "Large candle, minimal wicks" | body ≥ 60 % of range, ≥ 1.5 × recent avg body |
| Q7 | "Follow-through" | 2 of the next 3 candles continue, no close back through the level |
| Q8 | Wedge minimum length | ≥ 8 bars, ≥ 2 touches per trendline (T1.5 wants 3) |
| Q9 | Max distance from level still tradeable | R:R ≥ 3 test (T4.1) governs |
| Q10 | Short side | The book is **almost entirely long-biased** (falling wedge, buy support). Mirror rules for shorts are our extrapolation — long-only for v1; **lifted 2026-08-26** (`technique.long_only` off): `reject` = short at resistance (p. 74 "sell at resistance"), `breakdown` = confirmed close through support (T3.3 mirrored), puts only |
| Q11 | **Overnight gap past a planned level** (book silent: the author is flat overnight) | trigger not taken — T4.1 forbids chasing (`gapped_past`) |
| Q12 | **Open beyond the planned stop** | trigger void (`gapped_through`) |
| Q13 | **Gap magnitude** | \|open − prev close\| > `technique.plan.gap_void_r` (1.0) × risk voids the plan; reported with and without |
| Q14 | **"Level respected"** (for level-quality scoring) | price enters ±2×tol and reverses ≥ `technique.plan.respect_mult` (3) × tol without a close beyond; `broken` / `flipped` / `untested` otherwise |
| Q15 | **Structure vs trigger timeframe** | structure on 30m/1h, triggers on 1m/5m (p. 114 read as *where structure is read*) — ours; per-tf results keep it testable |

### Decisions taken 2026-08-21

| Question | Decision |
|---|---|
| Entry-rule conflict (T4.2) | **Two setup types** — bounce enters at the level, breakout requires confirmation |
| Options | **Wire Tradier chain data now**; setups select a real contract. Execution stays practice-only |
| Backtest history | **Free Yahoo tiers** — 1m ≈ last 20 days (8 days/request), 5m 60 days, 1h 2 years. Verified empirically 2026-08-21. Plus chart-image upload for any period |
| Trigger | **On-demand + scheduled scans**, and a **conversational review surface** over every run (see `PIPELINE-PLAN.md` §5) |
| Direction | **Long-only for v1** |

---

## 11. Implementation status (refreshed 2026-08-22)

| Module | Spec | Built |
|---|---|---|
| T1 Support/Resistance (+ T1.6 pre-session levels) | ✅ | ✅ `levels.py`, `plans.py` |
| T2 Volume | ✅ | ✅ `volume.py` |
| T3 Patterns (wedge, breakout/fakeout, candles, trend) | ✅ | ✅ `structure.py`, `setups.py`, `candles.py` |
| T4 Entry/Stop/Targets (+ T4.3d chart stop, T4.6 confluence) | ✅ | ✅ `setups.py` |
| T5 Options expression | ✅ | ✅ CBOE chain (`options.py`) |
| R Risk & no-trade gates (+ R6 schedule) | ✅ | ✅ `rulebook.py`, `service.py`, `backtest.py` |
| Pipeline + grounding | ✅ | ✅ `vision.py`, `grounding.py` |
| Review loop (trace, provenance, outcomes, reviews, replay) | — | ✅ `docs/techniques/enhanced-market/REVIEW-PLAN.md` |
| Session plans + walk-forward + live arming | — | ✅ `docs/techniques/enhanced-market/WALKFORWARD-PLAN.md` |
| UI panel | ✅ | ✅ Analyse / Chat / History / Backtest / Validation |
| Backtest harness | ✅ | ✅ (R6-gated by default) |
| Auto-execution | — | ☐ (deliberately deferred — armed triggers become practice proposals) |
