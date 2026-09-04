# Technique: Team2 (Casey / @Team2Trading) — "levels + EMA trend" index day trading

*Codified 2026-09-03 from the author's public X feed (every source is saved verbatim under
`notes/x/`; the index is `SOURCES.md`). Status: **research draft, v0.1** — nothing here is
built yet. Each rule is numbered (`L1`, `B2`, `E3`, …) so plan code, prompts and journal
events can cite the exact rule that fired, the same way EM's `METHOD.md` does. Cite the note
file in brackets after a rule when it matters which post said it.*

---

## 0. Provenance, scope and what is NOT public

- **Author**: Casey (@Team2Trading, earlier @cs_tradess), founder of the Team2Trading Discord
  (Whop, ~4k members, $119/mo). Trades **SPY / QQQ / IWM options** intraday, alerts entries
  and exits in the Discord, posts recaps + education threads on X. States repeatedly that
  "my entire system is taught right here on X for free" [2026-09-03 recent posts].
- **Sources captured**: 30+ posts/threads, Nov 2022 → Sep 2026 (mega threads Feb 2023,
  Mar/Apr/May/Aug/Oct 2025, Jan/Mar/Jul 2026). The method is extremely repetitive across
  them — good: the rules below are stated the same way many times. Where the wording
  changed over time (§8) the newest statement wins.
- **Not public (member-only or never stated)**: which option contract (strike / expiry), how
  position size is computed, exact trim percentages, and the trading window. The author twice
  promised a "part 2" covering "exp dates, strike prices, position sizes, trimming" [2025-08-09
  mega thread; 2025-10-18 mega thread v2] — no such thread was found. See §10 open questions.
- **Track record**: self-reported, unaudited (§9). A third-party tracker dispute was live on
  the feed the day of capture. Treat every win-rate claim as marketing until our own
  walk-forward says otherwise.
- **What we take**: the level definitions, bias scenarios, EMA regime read, confirmation
  rules, entry, stop, exit and sizing *principles*. **What we drop**: chart-reading prose
  ("study this chart"), mindset, promo.

## 1. The method in one paragraph

Before the open, mark four prices on SPY/QQQ/IWM: the previous regular session's high and
low (PDH/PDL, drawn as small zones on the 15-minute chart) and the pre-market high and low
(PMH/PML, 04:00–09:30 ET). The day's directional bias comes from how price treats the
PDH/PDL zones (break PDH → calls, reject PDH → puts, bounce PDL → calls, break PDL → puts);
trades outside yesterday's range are "trend" trades and get full size, trades inside it are
"range" trades and get caution, and the inside of the pre-market range is avoided. Put the
13 / 48 / 200 EMA on the 2-minute chart with extended hours on: stacked 13 > 48 > 200 with
price above all three is a bullish trend (calls only), the mirror is bearish (puts only), and
braided/flat EMAs mean chop (no trade). A level break counts only when a **15-minute candle
body closes** beyond it; then enter on the **first or second 2-minute pullback into the 13
EMA** (or the retest of the level itself), in the direction of the EMA trend, ideally as a
bull/bear flag. Risk **one 2-minute candle**: the stop is a 2-minute close back through the
EMA/level. First target is the push to a new high/low (trim), runners ride the 13 EMA and
exit when a 2-minute candle closes through it, or at the next zone. One or two trades a day.

---

## 2. Module L — Levels

### L1 Previous Day High / Low (primary)
- **L1.1** PDH / PDL = highest / lowest price of the **previous regular session (RTH)**
  [2025-06-21 thread: "(RTH)"; 2025-05-17: "yesterday's trading session"].
- **L1.2** Each is drawn as a **zone on the 15-minute chart: from the high-of-day (low-of-day)
  wick to the body of the following 15m candle** [2025-03-28, 2025-04-03, 2025-05-17,
  2025-08-09, 2025-10-18, 2022-11-05]. So the zone's width = |wick extreme − next candle's
  body edge|; it is asymmetric and data-defined, not a fixed %.
- **L1.3** These zones are "the main areas of support & resistance I watch each day" and the
  source of the daily bias (§3). Reactions to them happen "nearly every day".
- **L1.4** A broken PDH that holds on the retest has *flipped to support* (and vice versa)
  [2025-04-03: "PDH flipped to support on the retest = Bullish"].

### L2 Pre-Market High / Low (secondary)
- **L2.1** PMH / PML = highest / lowest price traded **04:00–09:30 ET** [many; 2025-11-15,
  2026-01-18, 2024-05-04].
- **L2.2** Drawn as **lines (dotted), not zones** [2025-06-21].
- **L2.3** Role: "secondary range to watch — mainly used on inside days, or as confirmation
  levels if they fall outside the previous day's range" [2026-03-08]. Also usable "for
  entries, targets, and avoiding chop" [2025-05-17].
- **L2.4** On **gap days** the PM range is the *first* thing watched for direction: a 15m close
  outside it, then the first 13 EMA dip [2025-09-29].
- **L2.5** On **inside days** (open inside PDH–PDL) direction comes from which PM level breaks
  first: break PMH → longs up to PDH resistance; break PML → puts down to PDL support. That
  one move is "usually the only clean move to catch on inside days" [2024-05-24].
- **L2.6** The **all-time-high variant**: mark PMH, wait for a 15m close above it, buy calls on
  the 2m retest of PMH, stop = 2m close under PMH [2026-04-17].
- **L2.7** The **PML break & retest** (puts): mark PML, wait for a break "if the market is
  looking weak", enter puts on the retest/rejection of PML, stop just above PML [2024-05-04].

### L3 Targets — the next zone
- **L3.1** The first target beyond PDH is "the last strong rejection we had above the PDH";
  beyond PDL, "the last strong bounce we had below the PDL" — i.e. the most recent pivot
  outside yesterday's range [2025-08-09].
- **L3.2** Range-day targets: after a PDH rejection target PDL; after a PDL bounce target PDH
  [2025-09-27, 2025-10-18].
- **L3.3** Original (2022–23) formulation, still consistent: number the zones 1..5 outward;
  when zone N breaks, aim for zone N+1; "large gaps between resistance levels create smooth
  price action" [2023-02-18].
- **L3.4** Intraday S/D zones: areas where price found support/resistance early in the day,
  traded the same way later in the day when inside the larger zones [2023-02-18].

### L4 Three ways to play any zone
- **L4.1** Bounce/rejection, breakout, or **retest** ("my personal favorite are the retest buys")
  [2022-11-05]. The 2024–26 material makes the retest / pullback the standard entry (§6).

## 3. Module B — Bias (the four scenarios)

- **B1** Read the reaction to the PDH/PDL zones: **1 break PDH → calls; 2 reject PDH → puts;
  3 bounce PDL → calls; 4 break PDL → puts** [2025-03-28 … 2026-03-08, stated identically ≥ 8
  times].
- **B2** Scenarios 1 and 4 are **trend days**: "most bullish / most bearish", keep the focus
  one way "as long as we hold" beyond the zone; lean into EMA dips and flags [2025-09-27].
- **B3** Scenarios 2 and 3 are **range days**: trade "a bit more cautiously", require extra
  confirmation (EMA cross, PM level break, flag) [2025-09-27]; "balanced days between PDH and
  PDL can be a bit more choppy" [2025-06-21].
- **B4** Combined read: price above **both** PDH and PMH → favor calls; below **both** PDL and
  PML → favor puts [2025-07-27].
- **B5** Inside **both** ranges (PDH–PDL and PMH–PML) = RISK OFF; outside both = RISK ON
  [2025-06-21]. "I typically try to avoid taking trades inside of the pre market high / low
  range" [2025-08-09]; newer traders should avoid it completely [2025-03-28].
- **B6** No shorting strength: "Never try to short stocks that are breaking resistance levels"
  [2023-09]. Bull flags are never shorted, bear flags never bought [2025-10-11].
- **B7** Full ladder [2025-01-25]: above PDH = bullish; above PDH **and** PMH = "mega bullish";
  below PDL = bearish; below PDL and PML = "mega bearish"; between PDH and PDL = range (chop);
  between PMH and PML = tight range ("mega chop").
- **B8** Trend continuation vs reversal [2025-01-11]: break of PDL = lower low = the downtrend
  is resuming, do not buy the dip until a higher high confirms; break of PDH = higher high =
  reversal. Mirror for uptrends.
- **B9** Zone and EMA must agree before entry: "going long only off a zone bounce can get
  rejected by the EMA resistance; going short only off the EMA rejection can bounce at the
  zone — wait for price to be beyond the zone **and** the EMAs" [2025-03-11].

## 4. Module E — EMA trend system (2-minute chart)

- **E1** Indicators: **13, 48, 200 EMA on the 2-minute chart, extended hours ON**
  [2026-02-08, 2025-06-15, 2025-04-05]. Higher timeframes for a wider outlook only.
- **E2** Bullish trend = 13 above 48 above 200 (price above all three is strongest); bearish
  = 200 above 48 above 13. Strength ladder: above 200 = bullish; above 200+48 = more bullish;
  above 200+48+13 = "mega bullish" (mirror for bearish) [2025-03-28, 2025-08-09, 2025-10-18].
- **E3** Direction filter: **calls only in a bullish EMA trend, puts only in a bearish one**;
  price over the 200 for long pullback entries, under it for shorts [2023-02-18, 2026-02-08].
- **E4** The "EMA fan": EMAs **tightly stacked / braided / flat = chop = no-trade**; EMAs
  spacing out and aligning = momentum arriving = pullbacks are respected [2025-10-04,
  2026-02-08, 2023-02-18]. "Range = consolidation = chop; range break = momentum = trend";
  the no-momentum areas "are typically the areas before one of my levels has broke"
  [2025-05-17].
- **E5** Lines of defense: **13 EMA** = first pullback in a strong trend and "the first dip I'm
  looking to buy after a major support/resistance break"; **48 EMA** = second line, watched
  after a few 13 taps / when momentum is weaker; **200 EMA** = "line in the sand" for trend
  [2025-04-27, 2025-06-15].
- **E6** The EMAs are also the exit tool: "using the 13 EMA to ride out my winners … exiting
  the trade on the break" [2023-02-18]; "13 EMA break as a visual trailing stop on runners"
  [2025-05-03].
- **E7** EMA trend must **align with the level bias**; "mostly trade when there is confluence
  between them" [2026-03-08].

## 5. Module C — Confirmation

- **C1 15-minute close rule (2026 wording)**: a key level counts as broken only when a
  **15-minute candle body closes** beyond it. "A majority of intraday liquidity sweeps occur on
  the 15 minute chart." Don't chase the break; confirm on the 15, then buy dips on the 2 (or
  5) [2026-03-01, 2026-01-18, 2025-11-15, 2026-07-25]. The 15m chart is kept up at all times
  and "confirms direction; the lower timeframes find the entry" [2025-08-31].
- **C2 Flags**: bull flags only above PDH / in a bullish EMA trend; bear flags only below PDL
  / in a bearish EMA trend. Continuation patterns, never traded as reversals [2025-04-05,
  2025-10-11]. A flag "in a bullish EMA trend after a 15m PM-range break = A+ setup"
  [2025-09-29].
- **C3** Other confirmation, all optional: candlestick patterns (hammers), trend lines,
  relative weakness/strength vs the index (2022 single-name era) [2026-04-18, 2022-11-05].
- **C5 Timeframe division of labour** [2025-09-07]: **15 minute = levels & zones; 5 minute =
  flags / trend lines; 2 minute = EMA trends & entries.** Flags are therefore judged on 5m
  bars, not 2m.
- **C4 The A+ checklist** (stated verbatim many times): *Above PDH ✅ Bullish EMA trend ✅ Bull
  flagging ✅* — "multiple confirmations for upside, 0 confirmations for downside"
  [2025-06-21]. Mirror for puts. Range-day variants substitute "rejects PDH / EMA trend flips
  bearish" or "bounces PDL / bullish EMA trend".

## 6. Module T — Entry

- **T1** Sequence (2026 canonical): **identify level → 15m close confirms the break → enter on
  the 2m chart on the first or second pullback into the EMAs (13 first)** [2026-01-18,
  2025-11-15, 2026-07-25: "15 minute candle close above PMH followed by a 2 minute dip back
  into the 13 EMA for my entry. This is my A+ setup for calls"].
- **T2** Alternative entry = **retest of the broken level itself** ("break & retest"), often
  the same price as the 13 EMA dip. Alert format: "Top watch • Break under 201.84 and we are
  going to focus on puts today" → entry alert when price retests 201.84 → stop above 201.84
  [2024-07-09].
- **T3** Entry is *at* the EMA/level, not on a fresh high; "the best entries are pullbacks to
  the EMAs, key levels, or both" [2025-05-03]. Ride the flow "break or reject a level → pullback
  to the EMAs → new high/low" [2025-08-09].
- **T4** Pullback entries are only valid while the EMA trend shows momentum (E4); 2025
  wording lets the level break itself supply the momentum ("when the level breaks it brings
  in enough one sided momentum to start buying the 13 EMA dips") [2025-11-15].
- **T6** Enter **as close to the stop as possible** — "whether it's an EMA pullback or a key level
  break & retest, taking your entry as close to that as possible keeps losses small"
  [2025-09-07]. For the engine: the entry limit sits at the EMA/level, never at market after
  the bounce is visible.
- **T7 Break & base** (images 2025-08-26/27 QQQ, 2026-09-03 SPY "BREAK & BASE"): after the 15m close beyond the
  level, price may not dip to the EMA at all — it BASES just beyond the level for a few 2m bars ("that break &
  base over pre market high is so nice… I've been loading up these cheap 574c"). The base itself is the entry;
  the stop is the level.
- **T8 The 200 EMA flush** (image 2025-10-17 SPY scenario 2): on a range day (PDH rejected after a 15m sweep) his
  trigger for puts was "the break of 200 EMA support" — the entry alert came on the 2m candle close below the 200
  EMA after a bearish 13/48 cross, and the PRE-MARKET LOW was "my final target on the rest of these puts". So a
  range-day scenario fires on the 200-EMA flush, not on a pullback; targets = the PM level, then the PDL zone.
- **T5** Re-entry is part of the method: the author stops out and re-enters the same idea
  ("stopped out of both these entries … before hitting the trade that ran 10x")
  [2026-09-03]; "multiple opportunities to enter a trend" [2025-05-03].

## 7. Module S / X / Z — Stop, exits, sizing

### S Stop — "Risk 1, win multiple"
- **S1** Stop = the level or EMA used for entry **not holding**, measured on a **2-minute
  candle close** ("Stop loss is a 2 minute candle close under that PMH level" [2026-04-17];
  "I stop out if the 13 EMA does not hold" [2025-05-17]).
- **S2** Size of the risk = **one candle** ("capping your loss to 1 candle"; "risk a candle or
  2 beyond that level before I cut" [2025-08-31]). Example claim: "1 candle risk, 10+ candle
  reward" [2025-04-24].
- **S3** Losses are cut immediately; "do not bag hold your losers" [2025-08-09].

### X Exits
- **X1** First target = **the push to a new high / low** after the pullback entry ("base hit";
  "sell on push to new highs/lows") — a trim, not a full exit [2025-05-03, 2025-08-09].
- **X2** Runners: hold with the **13 EMA as a trailing stop; exit on the 2m close through it**
  [2023-02-18, 2025-05-03]. Scale out along the way [2023-02-18].
- **X3** Zone targets: next zone / most recent pivot (L3); a range trade targets the opposite
  side of yesterday's range (L3.2). Be "cautious of a rejection/reversal" at the target zone.
- **X5 Trim heavy, then add on the retest** (image 2025-10-17): "I like to get a bunch trimmed on that first push
  so I can free up some room for possible adds if I like the retest later… re-upped a full position and these
  671p are ITM and up 100%". The first push is trimmed HEAVILY; the freed size is re-added on the next 13 EMA
  retest in the same direction — a scale-out/scale-back-in rhythm, not one static ladder.
- **X6 Stop for a level entry = the level** (image 2025-08-26 QQQ): ".31 average now — testing that pre market
  high again; if that breaks I'm out. For now those are the dips I'm looking to buy" — for a retest/base entry the
  invalidation is the level, and he averages in (.31 average) across the dips while it holds.
- **X4** Recap arithmetic seen: "first trim at 90%, then fully out at 130%" (premium % gain,
  one recap); "100% play … called it a day by 11am" [2025-10-18]. No systematic trim ladder
  is public (Q3).

### Z Sizing and cadence
- **Z1** Size by *location*: **full size only outside yesterday's range in an aligned EMA trend**
  ("Below PDL in a bearish EMA trend = full size on puts"); **moderate size** for a PM
  break-and-retest inside yesterday's range; **risk off** inside both ranges [2025-08-31,
  2025-06-21, 2025-08-09]. The author published a sizing "guide" image — not captured (Q2).
- **Z1b** "I prefer to size down for scenarios 2 & 3 (range day) and size up for scenarios 1 & 4
  (expansion day)" [2025-03-15] — the sizing rule in its cleanest form.
- **Z2** **1 or 2 high-quality trades a day** ("I average 1–3") [2025-05-03, 2025-04-03,
  2025-01-30]; "less is more"; no scalping every candle.
- **Z2b** Timeframes: "I take all my entries on the 2 minute timeframe. 5, 10, 15 minute for
  added confirmations. Stop losses are always a break of one of my EMAs or the key level I'm
  entering near." This thread "covered 1 of about 4 setups I trade" [2025-01-30].
- **Z2c** Loss size in premium terms: "4 losses that ranged between −20% and −40% depending on
  how quickly I exit upon my stop level breaking" vs wins of +35% to +210% [2025-03-15].
- **Z2d** Chained targets: after a break, "wait for price to break & retest my first target +
  13 EMA and take puts down to the second target" — the next zone becomes the next entry
  [2025-03-11].
- **Z3** Win rate is kept high by small candle-defined losses, not by wide stops; a 50% day can
  still be net positive because wins run multiple candles [2025-08-31].

## 7b. Module V — Expression: what the IMAGES say (read 2026-09-03, `notes/x/images/`)

The text never states the contract; the alert screenshots inside his recap images do. Every
example found so far is the same shape:

| Date | Underlying / level | Alert | Contract | Entry premium | Exit |
|---|---|---|---|---|---|
| 2026-09-03 | SPY, 768.00 zone break → retest ("break & base") | "I'm taking SPY 770c" ~11:00 | **SPY 770 C exp 03 Sep 26 (W) = 0DTE**, ~$2 OTM (0.3%) | n/a | "selling for over 500%" at 11:19 (+536.99%); two earlier 771c/770c entries stopped out from +25% / +26% |
| 2026-09-01 | IWM, PDL break | — | IWM 292 P exp 01 Sep 26 (W) = 0DTE, ~ATM | n/a | +474% "that's enough for me, I'm selling mine" 12:34 |
| 2026-04-17 | SPY, PMH 708.79 break (15m close) → retest | "I'm taking SPY 711c @ .60" ~10:10 | SPY 711 C exp 17 Apr 26 = 0DTE, ~$2 OTM | **$0.60** | "711c pushing ITM and up over 120%. I'm selling" 10:46 (+122%) |
| 2025-08 (thread 08-31) | SPY, PDH 647.37 break + bull flag, **13:24 entry** | "I'm taking some SPY calls here… 648c @ .54" | SPY 648 C 0DTE, ~$1 OTM | **$0.54** | "scaled out at 50% and 100%"; runners sold 14:33 at 100% |
| 2024-07-09 | IWM, PDL 201.84 break → retest | "I'm adding IWM 201p @ .20" ~09:45 | IWM 201 P exp 09 Jul 24 (W) = 0DTE, ~$1 OTM | **$0.20** | "new low of day… everyone should be up 100%, lock in some gains"; +157% "down to runners" 10:32 |
| 2025-08 (bear-flag post 08-07) | SPY ~633.4, bear flag at PDH in a bearish EMA stack, 10:36 | "if we hold the 13ema and break this flag I'll be looking at 631p" → "all loaded up with .50 average" | SPY 631 P 0DTE, ~$2.5 OTM | **$0.50 avg** (scaled in) | continuation to 631.13 |
| 2024-10 (weekly recap image) | 10 alerts / 7 W / 3 L (70%) | — | — | — | wins +80…+330% "scaling out of all of them"; losers "typical stop outs under the EMA, about −20/30%" |
| 2025-03-10 | QQQ ~480.3, PDL 480.53 break (10:05 "watching puts on the retest of 480.53") | "I'm taking QQQ 472p @ .55" 10:15 at the 13 EMA retest | QQQ 472 P 10 Mar 25 (W) = 0DTE, **$8.5 OTM (1.8%)** | **$0.55** | +166% at 10:57, "locked in over $4K" (**+$4,389.61 ⇒ ≈ $2.6k premium ≈ 48 contracts**); "scaled out on the way down and sold into strength when extended from the 13 EMA" |
| 2025-04-02 | QQQ ~473.6 support hold, bull flags, 13/48 EMA pullback ~11:55 | "I'm taking QQQ 480c" | QQQ 480 C 02 Apr 25 (W) = 0DTE, **$6.4 OTM (1.35%)** | n/a | "target hitting here… sold the rest for 350%" 13:14 (+361%) |
| 2025-10-17 | QQQ, plan "hold 595.50 zone → calls up to 603.19, then 608.31"; PDL bounce then PMH 599.52 break | "looking at the 606c if we get this 15 minute candle close above pre market high" → "I'm taking QQQ 606c" on the PMH + 13 EMA retest ~10:04 | QQQ 606 C 17 Oct 25 = 0DTE, **$6.5 OTM (1.1%)** | n/a | "selling here at my target" 603.19 at 10:16 (+118%) — "called it a day by 11am" |

- **V1 (revised)**: the OTM distance is NOT constant (SPY 0.3%, IWM 0.5%, QQQ 1.1–1.8%) but the
  **entry premium is: ≈ $0.50–0.60 on SPY/QQQ, $0.20 on IWM** (5 of 6 priced examples). The
  working rule is therefore **"0DTE, the OTM strike whose ask is ≈ $0.50"** — a premium-targeted
  strike, cheap enough that a one-candle stop costs 20–40% and a level-to-level move pays 100–500%.
- **V12 Far-OTM in high-IV regimes** (image 2025-04-04, the tariff crash): "SPY 505p" with SPY ≈ 522 — $17 (3.3%)
  out of the money, +424%. With IV that high the ~$0.50 contract simply sits far away; the premium-targeted rule
  (V1) reproduces this automatically, a fixed-distance rule would not.
- **V10 Position size evidence**: ≈ $2.6k premium / ~48 contracts on a "full size" QQQ trade
  (2025-03-10); "$5k–$10k weeks" claimed. A full-size loss at −30% ≈ $800.
- **V11 "Sell at target"**: the pre-planned next level (603.19) is an outright exit for the rest
  of the position, taken the moment price touches it (X3 confirmed); trims happen earlier.

- **V0 Entry cue variants seen in alerts**: (a) retest of the broken level, (b) 13 EMA dip, (c)
  **flag break** after the pullback ("watch the flag break for entry on puts") — the flag break
  is the trigger when the pullback is a visible 5m flag; scaling in ("loaded up with .50
  average") happens across the flag.

- **V1 Contract = same-day expiry (0DTE), first or second strike out of the money in the trade
  direction, bought for roughly $0.20–$0.60.** The strike sits just beyond the broken level /
  the entry price; "sold when it went ITM" is a recurring exit cue.
- **V2 Exits are quoted in premium %**: trims at +50% and +100%, "new high/low of day" is the
  cue for the first trim, runners to the 13 EMA break or the next zone; +400–500% exits happen
  on trend days and are taken outright ("that's enough for me").
- **V3 Losses in premium terms** run −20% to −40% (§Z2c) — with a $0.20–$0.60 entry that is a
  one-candle move in the underlying, consistent with S1/S2.
- **V4 Afternoon entries exist** (13:24 PDH break-and-flag, sold 14:33) — Q4 is not "morning only".
- **V5 Re-entry after a stop is normal**: 2026-09-03 he stopped two 770/771c entries (each up
  ~25% first) and re-entered 770c on the third test of 768.
- **V6 Sizing guide (image, 2025-08-31 + 2025-09-07)** on the 15m chart: **above the PDH zone =
  Full size · PDH zone→PMH = Small size · PMH→PML = No trade zone · PML→PDL zone = Small size ·
  below the PDL zone = Full size.** Q2 is answered qualitatively: three buckets.
- **V7 Direction guide (image, 2025-08-31)**: above PMH → calls to the PDH zone; above PDH → calls
  to the next resistance (last pivot above); inside PMH–PML → NO TRADE; below PML → puts to the
  PDL zone; below PDL → puts to the next support. The zones in the pictures are ~0.1% of price
  wide (SPY 624.03→~623.3; 617.87→~618.7), i.e. the literal wick→next-body rule.
- **V8 Stop picture (image, 2025-09-07)**: the red box is exactly one 2m candle closing through
  the 13 EMA after entry at the EMA; the green box is the multi-candle run. Confirms S1/S2.
- **V9 Pre-market game plan format** (Discord 08:45): "Main watch for upside is going to be our
  768.00 zone. Break above that and I'll be focusing on calls as we start to get some room up to
  775.29" — one level, one direction, one target. This is what the nightly plan should emit.

Video 1 (2022-10-17, `notes/video/`) adds: "we buy pullbacks, we don't buy breakouts"; entries
only on pullbacks to the EMA, never on extended candles; an even, channel-like flag into the EMA
is the good pullback, a big engulfing candle into the EMA "is less likely to work"; a 200 EMA
rejection at the open is the first sign of weakness; stop "right above the previous day's low
level"; trim along the way and ride the 13 EMA. (In 2022 the levels were the prior day's high/low
and the *overnight* high/low; the 15m close rule did not exist yet.)

## 7c. From the 2023 podcast (Trading Camp Pod #68, `notes/video/2023-03-27-…md`)

The only long-form interview found. In his own words (auto-transcript, lightly cleaned):

- **P1 Hard stop on the premium**: "I'm running hard stops on pretty much all of them, usually
  around the **20% max loss** mark… usually 20% on a zero day, that's about the sweet spot. If it
  goes below that you pretty much have to accept that you timed it wrong." (2023; the 2025–26
  wording is the 2m close through the EMA/level — the two coexist: the candle rule is the
  *reason*, the premium % is the *hard cap*. Zargar already has a premium stop.)
- **P2 No no-trade time**: "I don't have any specific times a day that I won't trade. It gets
  slow during lunchtime… if there's momentum during lunchtime I'm going to trade it. Before 10
  a.m. Eastern you can get faked out — there's that big trend change at 10 a.m. — so a trade
  before then is a little riskier, but if the setup's there I'll still take it." → Q4: no window;
  pre-10:00 is a caution flag, not a gate.
- **P3 Duration**: "a couple of two-minute candles… the long ones can run up to an hour or two
  if we're getting a nice trend." "I'm a scalper."
- **P4 Cadence**: "I'll usually get about two or three opportunities a day, sometimes even five…
  I'm looking to take five or less." Rules against overtrading = "waiting for a break of a level,
  then a pullback to the EMAs; if we're chopping between the two levels there's no trade."
- **P5 Timeframes**: 15m for the zones; "the five and the ten and maybe the 15 to find the bigger
  bull and bear flags and consolidation patterns… with zero days you can know where the market
  is heading and still lose — you can't be holding through half an hour of chop."
- **P6 The first pullback**: "once we break that high, more often than not the stock pulls back to
  the 13 EMA and bounces. That's my entry spot, that's where most of my money is made — the first
  pullback to the 13 EMA after the breakout." The third bounce "right by the resistance zone" is
  where the first-dip buyers are stopping out — do not take it (supports D9: first two touches).
- **P7 Risk in dollars, scaled by the day's P&L**: after a $500 win "there's no reason to risk
  750 bucks on the next trade… instead I'll risk 200, so even if I lose I'm still up 300." Risk
  per trade quoted in the $200–$1,000 range for that account size (2023). → a *daily* sizing rule:
  never let one loss erase the day; shrink risk after a win, never expand it.
- **P8 Precision**: (host, agreed) "you need a precise entry on a zero day… more or less 50 cents
  on SPY or QQQ is your buffer" — consistent with the one-candle stop.
- **P9 2023 vocabulary**: "supply and demand zones" = the PDH/PDL zones; targets = the zones
  "above and below"; "when you interrupt the EMA your stop can be really tight".

## 8. Version drift (what changed 2022 → 2026)

| Element | 2022–2023 | 2025 | 2026 |
|---|---|---|---|
| Levels | "Supply/demand zones" numbered 1..5, single names too (AAPL, TSLA…) | PDH/PDL zones + PMH/PML lines; 4 scenarios | same, PM range role clarified (inside days / confirmation) |
| Confirmation of a break | breakout itself, EMA momentum | EMA fan + flags | **+ 15-minute candle body close** (new, heavily emphasised) |
| Entry | pullback to 13/48 EMA after the break | 13 EMA pullback, "risk 1 win multiple" | 15m close → **first/second 2m pullback into EMAs** or level retest |
| Stop | "clear risk level" | 1 candle beyond EMA/level | 2m **close** beyond level/EMA |
| Universe | SPY QQQ IWM + names | SPY QQQ IWM | SPY QQQ IWM |

## 9. Self-reported performance (unaudited, for calibration only)

| Claim | Period | Source |
|---|---|---|
| 127 trades, 75.59% win rate | 2023 YTD to Feb 18 | 2023-02-18 |
| 31 trades, 26 W / 5 L (84%), account +140% | March 2025 | 2025-03-28 |
| 32 trades, 84%+ hit rate | ~Sep 10 – Oct 10 2025 | 2025-10-11 |
| "+78% profit" through choppy 2nd half of Aug 2025 | Aug 2025 | 2025-08-31 |
| 40 trades, 80%+ win rate | ~Jun–Jul 2026 | 2026-07-25 |
| two 500% plays in a week; one SPY trade 10x | week of 2026-08-31 | 2026-09-03 |

Individual recaps quote +100% to +400% per trade on the option premium. That return profile
on SPY implies **very short-dated, near-the-money contracts** (0–1 DTE) — an inference, not a
statement (Q1). An alert-tracking service (Alertsify) publicly disputed the record on
2026-09-03; the author disputed the tracker. Nothing here is verifiable from our side; the
Zargar way is to shadow-trade the codified rules and let the scorecard speak.

## 10. Open questions (decide before building; each has a way to answer it)

| # | Question | Why it matters | How to answer |
|---|---|---|---|
| Q1 | **Which contract?** | **ANSWERED 2026-09-03 from images (§7b): 0DTE, 1–2 strikes OTM, $0.20–$0.60.** Remaining decision: 0DTE is on the platform never-list for non-EM techniques — the user must open it for `team2` (gated like EM's) or we run the 1DTE variant; sweep BOTH | user decision + sweep |
| Q2 | **Sizing guide** | **ANSWERED (V6): three buckets — full / small / none.** Multiplier for "small" unknown | default 0.5; sweep 0.25/0.5 |
| Q3 | **Trim ladder** | **PARTLY ANSWERED (V2): trims at +50% and +100% premium, first trim cued by the new high/low of day, runner to the 13 EMA break; fractions not stated** | default 1/3 · 1/3 · runner; sweep |
| Q4 | **Trading window** | **ANSWERED (P2): no no-trade time; pre-10:00 is "riskier" but taken if the setup is there; lunch traded when there is momentum.** Examples span 09:45 → 14:33 | Sweep entry-time buckets anyway (our theta cost is real); first 15m close is 09:45 |
| Q5 | **Zone tolerance** for "retest" and "bounce" — how close is a touch | tracker parameters | Use the L1.2 zone width itself for PDH/PDL; PMH/PML lines need a tolerance (start 0.05% SPY ≈ ATR-scaled) |
| Q6 | **EMA warm-up with extended hours** — 200 EMA on 2m = 400 minutes of bars incl. pre-market | needs 04:00 bars every day, and overnight continuity (does the EMA carry across sessions? "ext hours on" implies yes) | Fetch pre/post bars; carry EMA state across days; verify against a TradingView screenshot |
| Q7 | **How many pullbacks** — "first or second" then stop looking? | avoids late chasing | Default: first two 13-EMA touches after the 15m close; sweep |
| Q8 | **What invalidates the bias** — a 15m close back inside the zone? | re-plan logic | Default: bias flips only on a new scenario (B1) confirmed by a 15m close |

## 11. Fit with the Zargar engine (first look — details belong in a PLAN.md)

What exists and can be reused as-is: `marketstructure` levels/ATR/candles/flags-ish
structure, `TriggerTracker` + `simulate_plan` walk-forward, `PlanRunner` (arm/fire/critic/
exits/loss halt/quote-stop/premium-stop), risk-based sizing, `option_pick`, per-technique
settings resolver, journal contracts, the Armed page.

Gaps this method forces (engine work, technique-agnostic where possible):

1. **Pre-market bars.** PMH/PML and the "ext hours on" EMAs need 04:00–09:30 ET 1m bars.
   Yahoo's chart endpoint supports `includePrePost`; today `history.py` fetches RTH only and
   `_rth_only` clips Alpaca. Needs a session-aware bars layer (RTH vs extended) without
   breaking EM's detectors, which assume RTH.
2. **2-minute and 15-minute aggregation** from 1m (trivial), plus an **EMA series** helper in
   `marketstructure` (only `guards.ema()` exists, single value).
3. **New trigger kinds**: `confirmed_break_pullback` (15m body close beyond level → armed →
   2m pullback touches EMA13/level and holds → fire) and `break_retest`. Existing kinds are
   bounce/breakout/reject/breakdown on 1m bars.
4. **Regime state per symbol**: EMA stack + fan width (chop vs trend) as a gate, recomputed
   per 2m close.
5. **0DTE** is on the platform never-list for non-EM techniques (`docs/BUILDING-A-TECHNIQUE.md`
   §4). If Q1 resolves to 0DTE this is a user decision + gated RiskGate change; otherwise
   express as 1DTE/nearest weekly ATM.
6. **Universe** is three ETFs — no scan needed; a fixed list under `techniques.team2.symbols`.
7. **Schedule**: no R6 windows; the author trades from the open through midday. Session-close
   flatten at 16:05 applies (intraday only, no overnight).

Everything else (alert/proposal/auto modes, per-arm loss halt, audit trail, walk-forward
sweep with `--set` variants, outcome scoring) is inherited.
