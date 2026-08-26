# EnhancedMarket method review — book vs. app, 2026-08-26

**Why this exists.** Three live practice sessions in (08-24 → 08-26), the user asked for a
ground-up review: what the book actually prescribes, whether the app does *that*, where the
book itself is thin or dated, and where our blind spots are. Sources: a full re-read of all
123 pages; `TECHNIQUE-ENHANCEDMARKET.md` (spec), `TRADING-RULES.md` (judgement log),
`TECHNIQUE-WALKFORWARD-PLAN.md`; four code audits (levels/patterns/setups, volume/options/risk
gates + prompts, live fire→exit path + data feed) with every headline claim re-verified by hand;
and a read-only evidence pull from the runtime DB (`events`, `technique_armed`, `technique_runs`,
`technique_outcomes`, `orders`, `settings`). Companion to the judgement log — findings that
change a rule should be logged there with a date.

---

## 0. TL;DR

1. **The edge is untested, not disproven.** 51 plans armed, 12 fires, 11 critic kills, **0 orders,
   0 trades** in three sessions. Theoretical +1.9R identified on 08-25, 0 captured. Every lost R
   traces to plumbing (gap rule, data, spread guard, critic), not to the method.
2. **Today's fleet was not gapped out — it was restarted out.** 22 of 23 "voided at the open"
   decisions on 08-26 were evaluated on the **09:50 bar** (bar ts 13:50 UTC), the first bar the
   trackers saw after the 09:50 restart. The gap rule compares *that* bar's open to yesterday's
   close, and after 20 minutes of trading most names are >1R away. On 08-25 all 10 gap decisions
   were correctly made on the 09:30 bar. This inflates the "gap_void is too strict" evidence in
   `TRADING-RULES.md` §1.1 — most of today's samples are invalid.
3. **36 of 37 auto plans are armed with NO loss halt.** Equity was unavailable at arm time
   (evening bulk-arm), the derivation is skipped with a `log.warning` only — no journal event,
   no alert, no UI badge.
4. **The live trading path runs on quote-sampled bars, not exchange bars.** The exchange-bar
   correction (`ingest_exchange_bar`) can only land after the sampled bar for that minute was
   already published, and the armer's `bar.ts <= last_bar_ts` dedupe drops it. Charts, the
   critic's FACTS and the end-of-day scorecard see corrected bars; triggers and the volume gate
   do not. With Alpaca up the sampled volume is a real trade-size sum; on the Yahoo fallback it
   is noise.
5. **Two structural mis-codifications of the book:** (a) touch counting uses an identical
   band-overlap test for support and resistance (docstring says the extreme must reach the band)
   — every touch count, `min_touches`, "3+ touches" confluence and +12 grade points rest on it;
   (b) plain breakouts get a stop of `level − 0.5 %` and a `+2/4/6 %` ladder → **R:R ≈ 12 by
   construction**, so the R2 ≥ 3 gate cannot fail and the critic has been killing exactly those
   ("12:1 is an artifact of a percentage ladder", T; "193.29 stop is a percentage stop", PM).
6. **The universe drifted off the book.** The author trades mega caps / SPY where "wide spreads
   are rarely an issue" and "OI is always enough". Our 50-name fleet includes T ($26, 3-cent chop
   box, 13-cent stop), CHPT ($6), SOUN, CLF, GOLD, NCLH, CCL. Half the friction we are fighting
   (spread skips, stub-tick fakeouts, gap voids on tiny risk denominators) is the universe.
7. **What the book leaves undefined we had to invent — ~25 numbers and a dozen rules** (gaps,
   grades, zone merging, stop buffers, 0.40/0.75/1.00 ladder spacing, chop guard, veto/refire,
   tolerance). That is fine, but "doing exactly what the book says" is not a reachable target;
   the reachable one is "every deviation named, measured, and reversible". Several are not yet
   measured (grade weights, ladder spacing, tolerance), and a few are unnamed (§3).

---

## 1. The book, distilled

### 1.1 What the method is (pp. 32–60, 67–79, 114–120)

Two primitives, one confirmation instrument, a fixed trade shape:

| Element | The book's rule | Page |
|---|---|---|
| Structure | Horizontal S/R with 2–3+ touches; prior-day levels carry over; HOD/LOD-anchored lines "strongest"; round numbers | 33–35, 40–41, 70–71 |
| Patterns | Falling wedge (converging, upper steeper, volume drying up) and flags/consolidations | 41–48 |
| Confirmation | Volume, only. Taper into the level, surge on the break. "The only essential indicator you need is volume" | 35–41, 55–59, 119 |
| Entry A | Buy **at** support, no visual confirmation ("don't wait for the train to move") | 74–75 |
| Entry B | Buy the break only with volume + decisive candle + follow-through; else it's a fakeout | 46, 55–58 |
| Stop | Mental, the *level below support*, watch the reaction; hard stop when averaging; never a fixed % of price/premium; chart-based | 72–73, 78, 117 |
| Targets | TP1/2/3 trims 30/40/15 %, runner 15 % on a trailing mental stop; wedge target = measured height | 46, 73 |
| Instrument | Just-OTM call/put, weekly (≤ this Friday), 0DTE when available at smaller size; buy at the ask on breakouts; never look at Greeks; avoid buying high IV / into events | 22–25, 31 |
| Sizing | 0.5–1 % of account per trade (5 % hard ceiling); **one contract for the first 3–6 months** | 45, 60, 73, 117–119 |
| No-trade | Volume < 50 % of average; > 2 false breakouts in the first hour; bad contract conditions; holidays/FOMC/NFP/GDP; bad head | 62–64 |
| Schedule | 09:30–10:30 and 14:45–16:00 ET; avoid mid-day, pre/after-hours; disable after-hours data | 113–115 |
| Timeframes | "Focus on 30-minute and 1-hour" — 78 % vs 58 % win rate (self-reported) | 114 |
| Process | Journal everything, redraw levels daily, alerts at levels, ≥ 100 trades before trusting a number, evaluate over 6–12 months, one setup at a time, no daily $ target | 11, 72, 98, 117, 120 |
| The author's own stats | ~60 % win rate at 2.5:1 (p. 6) — **this**, not 78 %, is the realistic bar |

### 1.2 Where the book contradicts itself or stays discretionary (why "exactly as the book" is unreachable)

| Tension | Where | How we resolved it | Status |
|---|---|---|---|
| "Enter falling wedges slightly early to get IV on your side" (p. 25) vs "it's important not to jump in too early — wait for volume confirmation" (p. 46) | 25 / 46 | Wait for confirmation (Setup B) | decided 2026-08-21 |
| Risk per trade: 5 % (p. 45) vs 1–2 % (p. 60) vs 0.5 % (p. 73) | — | 0.5 % working, 5 % ceiling | decided |
| Mental stops only (p. 72) vs "use stop-loss and take-profit orders to remove emotion" (p. 107) vs hard stop mandatory when averaging (p. 78) | — | Closed-bar stop on the **low** + 0.25R quote breach + 50 % premium stop | ours; stricter than the book — the "watch the reaction at support" rule is *not* modelled (§3, T4.3) |
| "Aim for the midpoint" vs "I buy at the ask on breakouts" (p. 31) | — | LMT at the delayed CBOE ask | ours |
| Trend read "without trendlines" (p. 52) vs trendline rules ≥ 3 touches, ≤ 45° (p. 68) | — | 2 pivots = trend; wedge lines 2 touches; slope proxy 1 %/bar | ours, looser than T1.5 |
| 30m/1h focus (p. 114) vs 1m/5m execution examples throughout | — | Structure on 30m/1h, triggers on 1m | ours (Q15); the 5m trigger alternative is untested |

### 1.3 Where the book is dated or thin (2024 text, 2026 market)

- **No numbers anywhere** except 50 % volume floor, R:R ≥ 3, 30/40/15/15, 0.5–1 %/5 %, the two
  windows. Tolerance, spike size, decisive-candle, follow-through, wedge length, gap policy,
  0DTE size, "just OTM" distance, IV "super high" — all ours (spec Q1–Q15 plus §3 below).
- **Long-only in practice.** Every worked example is a bounce or an upside break. The author's
  own chart-inversion tip (p. 120) says he knows the bias exists. Half the opportunity set
  (resistance rejections, rising-wedge breakdowns → puts) is out of scope by our Q10 decision.
- **The 78/58 timeframe claim** is a single-trader self-report; it may also mean his *entries*
  are on 30m/1h bars, not that structure is read there. Untested either way.
- **0DTE.** In 2024 he says "when available". By 2026 single-stock weeklies make every Friday a
  0DTE day and index products every day; the book has no rule for what "smaller size" means when
  the size is already one contract.
- **Mid-day chop (R6.3)** is asserted, not measured. Our experiment (n=4 mid-day fires, all
  chop-fakeouts) leans the book's way so far.
- **Mega-cap assumption.** "With these major players there's always enough liquidity"; spread
  discipline, OI and stub-tick fakeouts are hand-waved because his universe makes them moot.
- **Silent on everything an unattended machine needs:** overnight gaps, holidays/earnings,
  partial fills, delayed option quotes, repeated touches of one level, restarts, what to do when
  the feed stalls. All invented here; most unmeasured.
- **Pattern language is loose.** "Flags" are named as the second primitive but never defined
  beyond the falling wedge; we ship no flag/consolidation detector at all.

---

## 2. What three live sessions showed (read-only DB pull, 2026-08-26 14:14 ET)

| | 08-24 | 08-25 | 08-26 (partial) |
|---|---|---|---|
| Plans that ran (auto, options, 1 contract) | 1 (WDAY) | 10 | 37 |
| Best grade A / B / C | 0/1/0 | 10/0/0 | 6/17/14 |
| Analyst `no_setup` armed anyway | 0 | 1 | 15 (C-cohort experiment) |
| Triggers | 1 | 22 | 45 |
| Voided at open (`gap_void` / `gapped_past`) | 0 | 7 / 1 (all on the 09:30 bar) | 21 / 2 (**22 on the 09:50 bar**, post-restart) |
| Fires (events / distinct triggers) | 0 | 3 / 2 | 9 / 2 |
| Critic kills | — | 2 (ZS b1 data-outage kill; SNOW b2 "fabricated targets" — both later judged wrong and fixed) | 9 (PM k1 ×3 chase into a 5-touch shelf; T k1 ×6 mid-day 3-cent box) — all judged right |
| Survived critic → order | — | SNOW b2 15:02 → **skipped, 16.5 % spread** | 0 |
| Orders / fills / trades | 0 | 0 | 0 |
| Theoretical ΣR (scorecard) vs captured | 0 / 0 | **+1.89R / 0** | not scored |
| "stale bars" errors | 4 | 100 (09:34–12:24, Yahoo 429 day) | 29 (one gap at 10:17 across 27 symbols) |
| Restarts | 6 | 4 | 5 |

Other facts: the only technique order ever sent (MRNA, 08-22) was `REJECTED_RISK` on the $1 000
caps, since raised to $2 500 / 25 % / $5 000 for the practice experiment (**global settings —
re-tighten before real money**). `dailyLossLimit` is 0 on 36/37 plans today. Settings drift
today: `critic_kills_per_day` 3→10, `refire_cooldown` 10→5, `midday_trading` on, `arm.mode`
auto. Broker sync mismatches on both SnapTrade accounts (WS Personal −52.8 % computed vs broker)
are unrelated to the technique but mean equity-based sizing on those accounts is unreliable.

**Reading:** the machine keeps refusing bad trades (WDAY no-volume breaks, PM chase, T chop) —
the discipline half works. The capture half has never executed once. And a third of today's
evidence (the 09:50 voids) is an artifact.

---

## 3. Fit audit — book rule → what the code does → verdict

Severity: **H** = changes outcomes or safety now; **M** = distorts validation / occasional loss;
**L** = hygiene. "Path" = A (analysis/`setups.py`), P (plans/`plans.py` + tracker), X (execution).

### T1 Levels

| # | Book | Code | Verdict | Sev |
|---|---|---|---|---|
| 1.1 | A touch = price reaches the level | `levels._count_touches` uses the same band-overlap test for support and resistance (`low ≤ p+tol and high ≥ p−tol`); a bar that blows straight through counts as a touch. Docstring describes the intended extreme-must-reach test | **Bug.** Inflates touches → `min_touches`, "3+ touches" confluence, +12/+6 grade points, level ranking | H |
| 1.2 | Prior-day S/R carries into the next day (T1.3b) | Only prior-day **HOD/LOD** are seeded; T1.3b exists as a rule id and a comment only | Missing source | M |
| 1.3 | HOD/LOD "strongest" | Seeded extremes are subject to the same ≥ 2-touch gate and dropped if not re-touched; a HOD on a round number is relabelled T1.3d (dict overwrite) and loses its priority | Partial | M |
| 1.4 | The level is the price | Cluster price = arithmetic mean of members, so "prior-day HOD 320.28" can be reported as 320.19 | Cosmetic drift; matters for gapped_past (`open ≤ entry`) | L |
| 1.5 | — | Five tolerance formulas in circulation (0.15 %/0.25 ATR detection; 0.30 % merge; 0.15 %-of-last-close triggers; 0.30 % respect; 0.3 %/0.35 range grounding) | Inconsistent; the tracker's "touch" is not the detector's "touch" | M |
| 1.6 | Structure on 30m/1h | `structure_tfs` honoured in plans; but `arming.py`, `backtest.py`, `tools.py`, `routes_technique.py` call `compute_facts(context_tfs=())` — the **fire-time critic judges on 1m alone**, no higher timeframe | Critic blind to structure | M |
| 1.7 | Lookback = current + 2 sessions (Q3) | `lookback_sessions` is plumbed and consumed nowhere; detection uses the whole fetched window (1m = 5 sessions) | Dead setting | L |

### T2 Volume

| # | Book | Code | Verdict | Sev |
|---|---|---|---|---|
| 2.1 | Volume < 50 % of the time-of-day average = no trade (R3.1) | Evaluated in **four** places with **two** formulas: FACTS/setups/grounding (numerator = last non-zero bar of the window, baseline excludes today, *unmeasurable → blocks*) vs the tracker (numerator = the trigger bar, baseline **includes the plan-build session**, falls back to a 20-bar rolling mean, *unmeasurable → fires*). Not evaluated at plan time at all | The exact divergence flagged in TRADING-RULES 1.4 ("tracker passed 0.2× bars"). Opposite fail-open/fail-closed conventions | H |
| 2.2 | Real volume | Live triggers run on quote-sampled 1m bars; the exchange-bar correction never reaches the armer (§0.4). Fine-ish on Alpaca (trade-size sums), garbage on Yahoo fallback | The gate the book calls "the only indicator" is fed the least reliable series in the system | H |
| 2.3 | Volume tapers **into** the level, then surges (T3.3a) | Only the surge half is tested; no "coiled spring" taper check anywhere | Half the rule | M |
| 2.4 | Breakout volume is the break bar's | Analysis path measures volume at the **last** bar and applies it to a break up to 12 bars old | Wrong bar (A only; the tracker is correct) | M |
| 2.5 | — | `volume_floor_mult` is not settings-exposed; profile buckets are UTC (60-min skew across a DST change) | Hygiene | L |

### T3 Patterns

| # | Book | Code | Verdict | Sev |
|---|---|---|---|---|
| 3.1 | Wedge target = height at the widest point | `widest_height` = the fitted-line gap extrapolated to **window bar 0** (80-bar window), not the pattern's first pivot | Measured move, R:R and grade inflated whenever the wedge starts mid-window | M |
| 3.2 | Wedge needs declining volume ("all must hold") | `detect_wedge` records it; only the plan path gates on it; `build_breakout_setup` ignores it | Partial | L |
| 3.3 | Flags / consolidations are the second primitive | No flag, triangle or consolidation detector; only the falling wedge and horizontal breaks | Missing primitive | M |
| 3.4 | A lower-tf break may be a fakeout on the higher tf (T3.3.4) | No higher-tf breakout classification; `plans._higher_tf_agrees` is a trend-direction proxy; `confluences(higher_tf_agrees=)` has no caller | Missing | M |
| 3.5 | Decisive candle, follow-through 2-of-3 | Tracker: ✓ (`is_decisive` 60 % body, 1.5× avg, ≤ 25 % wick; 3-bar hold + 2 continues). Analysis path: a break on the last bar passes with zero follow-through (`or not after`) | Tracker faithful; A path lenient | L |
| 3.6 | Trend = HH/HL, confirm on multiple tfs | Two pivots suffice; tfs never reconciled | Loose | L |
| 3.7 | Context overrides the candle (T3.4d) | Bounce confidence +0.1 for a hammer regardless of trend; T3.4a/c/d rule ids never fire from code | Cosmetic | L |

### T4 Entry / stop / targets

| # | Book | Code | Verdict | Sev |
|---|---|---|---|---|
| 4.1 | Stop is chart-based, never a fixed % (T4.3d) | Bounce: zone floor / invalidation low − buffer ✓ (fixed 08-23). **Breakout: `level − 0.5 %`** in `setups.py`; in the plan path `zone_low − buffer` collapses to the same 0.5 % whenever the zone is a single level (T k1: 25.87 → 25.7407 exactly). Wedge: `wedge_low − 0.1 %` | Fixed-percentage stop in costume, for breakouts — the MARA finding again | H |
| 4.2 | R:R ≥ 3 (R2) | With the 0.5 % stop and the `+2/4/6 %` blue-sky ladder, R:R ≈ 12 for every plain breakout; R2 cannot fail; grade capped at B is the only brake | Gate is unfalsifiable for breakouts (TRADING-RULES 1.5) | H |
| 4.3 | R:R to the target | Computed to **TP3** (100 % of the way) — but a < 3-contract position exits **in full at TP2** (75 %). A "3.0" plan is a 2.25 trade as executed | Gate and execution disagree | H |
| 4.4 | Ladder 2/4/6 % = evenly spaced | Anchored ladders use 0.40 / 0.75 / 1.00 of the distance — front-loaded; ours, unmeasured | Named now; test | L |
| 4.5 | Enter **at** the level | Tracker fires when `low ≤ entry + 0.15 %` and books the fill **at entry** — a price that may never have traded; live options buy at the ask regardless | Replay optimistic; live unaffected | M |
| 4.6 | Mental stop: watch the reaction at the level, exit if it can't reclaim | Closed-bar `low ≤ stop` (a wick suffices) + quote 0.25R breach + 50 % premium stop | Stricter and wick-sensitive; the book's "reaction" rule is unmodelled. Candidate experiment: stop on **close** below + quote breach only | M |
| 4.7 | Runner on a trailing stop | No trailing logic; runner leaves via flatten/stop/halt only | Irrelevant at 1 contract; matters later | L |
| 4.8 | Averaging down (T4.5) | Not implemented — deliberate | ✓ | — |
| 4.9 | 2+ confluences, conflicting signals = stand aside (T4.6) | Counted, never gates; two different lists in A and P paths | Note only | L |

### T5 Options

| # | Book | Code | Verdict | Sev |
|---|---|---|---|---|
| 5.1 | Just OTM | Nearest strike strictly beyond spot, capped at TP2 ✓. No distance sanity: on a $6 stock the next strike can be 8 % away; on a $975 one 0.5 % | Faithful; add an ATR-distance check | L |
| 5.2 | Weekly ≤ Friday; 0DTE when available at smaller size | 0DTE **preferred** whenever listed (unless after 15:15); "smaller size" halves risk-sized contracts but with the default fixed 1 contract there is nothing to halve | Every Friday is a full-size 0DTE day | M |
| 5.3 | Don't buy high IV / into events | Absolute IV ≥ 0.60 warning, gate **off** by default; **no earnings or macro calendar exists** (R3.4 is prompt text only) | Blind to earnings — on a 50-name fleet this *will* bite | H |
| 5.4 | Avoid wide spreads / thin contracts / high theta | Spread > 10 % blocks ✓ (SNOW 16.5 % blocked +1.89R); OI/volume/delta warn only; theta never compared | Spread rule right; universe wrong | M |
| 5.5 | — | Contract bid/ask are **CBOE ~15-min delayed**; entry LMT at that ask; `set_overlay` never advances `Quote.ts` and OCC symbols pass `is_us_equity` so the Hybrid feed swallows the option's Yahoo quote → the premium stop goes blind after 180 s (alert only after ~5 min) | Not live-money grade | H |
| 5.6 | — | `_pick_contract` runs **after** the critic; the "Contract to buy (T5)" context block is always empty | Critic never sees the contract | M |
| 5.7 | — | Fees (`options.fee_per_contract`) never applied to P&L; pre-flight estimates premium as 2 % of spot without a chain | Hygiene | L |

### R Risk & no-trade gates

| # | Book | Code | Verdict | Sev |
|---|---|---|---|---|
| R1 | Risk 0.5–1 %, ceiling 5 % | Enforced on **shares** sizing and on `riskPct`. For options the position is 1 contract and the real risk is the premium (up to $2 500 = 25 % of the $10k practice account under the raised caps) bounded only by the 50 % premium stop. "R" is underlying-defined, P&L premium-defined (known softness) | R1 is not enforced on the instrument we actually trade | H |
| R2 | R:R ≥ 3 | See 4.2/4.3 | | H |
| R3.1 | Volume floor | See 2.1/2.2 | | H |
| R3.2 | > 2 false breakouts in the first hour = no trade | Only a chop proxy (`sideways` + stop < 2 ATR). **No false-breakout counter.** T fired 6× and PM 3× into the same level; only the (paid, slow) critic stopped it | Cheap deterministic gate missing; the critic is doing R3.2's job | H |
| R3.4 | Holidays, FOMC, NFP, GDP | Not implemented | Missing | H (live) |
| R5 | One contract | ✓ default 1 | ✓ | — |
| R6 | Prime windows only | ✓ with the mid-day experiment (live armer only, tagged, critic informed) — well designed | ✓ | — |
| — | — | `max_open_trades` is per plan and auto-only; **no fleet-wide cap**: 37 auto plans could open 37 positions | Missing for live | H (live) |
| — | — | Loss halt: `dailyLossLimit` 0 = off; auto derives 2× risk only if equity is available, else **arms silently with none** (36/37 today) | Silent safety failure | H |
| — | — | `technique.arm.stale_seconds` flags and alerts but **never gates a fire** ("not firing until data resumes" is not true) | Misleading | M |

### X Execution & data (beyond the rules)

| # | Finding | Sev |
|---|---|---|
| X1 | **Gap decisions on the wrong bar after a restart** (§0.2): `TriggerTracker` runs the open-gap test on the first bar it sees; seeding uses in-memory `engine.bars` only, which is empty after a restart | H |
| X2 | Critic has **no timeout** and runs inside the serial `_bar_loop` → a slow/hung LLM stalls every plan's closed-bar exits (quote-stop loop keeps running); on error it fails **open** | H (live) |
| X3 | Exits evaluate on **any** bar of the day including extended hours (Yahoo `includePrePost=true`, Alpaca full tape); a reduce-only order skips `market_hours` and goes to a closed market | M |
| X4 | Failed-exit watchdog gives up after 5×30 s and parks the position with one alert; a restored `working` entry never times out (`fire_bar_index=None`) | M |
| X5 | 15 restarts in 3 days; each re-seeds and can contradict live history (`replay_divergence` ×7, `phantom_dropped` ×2). Restore is now defensive, but restart frequency itself is a risk while positions are open | M |
| X6 | Scorecard grades live behaviour against **corrected** bars the live path never saw, so "model would have fired but the live plan did not" will over-report on volume-gated triggers; no capture-rate roll-up exists (theoretical R vs realized **$**, different units) | M |
| X7 | 133 "stale bars" errors in 3 days; 08-26 10:17 hit 27 symbols at once. Data reliability remains the #1 operational risk | H |

---

## 4. Blind spots neither the book nor the code covers

1. **Earnings / event awareness.** Nothing in the pipeline knows a name reports tonight. The
   book's IV-crush warning and R3.4 both assume the trader checks; the machine doesn't.
2. **Universe selection is a rule, not a list.** The book's universe is implicit (mega caps);
   ours is a 50-name theme list. Needed: price floor, ATR-in-cents floor (a 13-cent stop on T
   is untradeable), option spread ceiling measured *at arm time*, average 1m volume floor.
3. **Risk per trade for options** needs a definition: `min(premium, premium_stop % × premium)`
   per contract, enforced against `max_risk_pct`, or skip the contract.
4. **Attempt budget per level per session** (R3.2 made mechanical): after N failed break
   candidates or M touches without follow-through the level is done for the day.
5. **Short side.** Puts on resistance rejection / rising-wedge break are the mirror the author
   himself hints at; long-only halves the sample the book says we need (≥ 100 trades).
6. **5m triggers.** The T chop-box fires would not exist on 5m bars with the same gates; the
   book's own preference points at slower bars. Untested.
7. **Real-time option quotes.** CBOE-delayed is fine for chain selection, not for a live premium
   stop or an entry LMT. Alpaca's options data (OPRA) or IBKR once active.
8. **Capture-rate telemetry** (TRADING-RULES backlog #1): identified R vs captured R by friction
   reason, weekly. Without it every review is a manual DB dig like this one.
9. **Position-level "why did we not trade" ledger**: today the reasons live across
   `TriggerSkipped`, `critic_killed`, `contract_skipped`, `stale`, `gap_void` — one query,
   one table, one chart.

---

## 5. Recommendations (ranked)

### A. Fix now — deterministic, cheap, changes outcomes
1. **Gap test only on the true session open**: if the first bar seen is not the 09:30 bar,
   fetch the session's first 1m bar from history (or DB) before deciding; otherwise mark
   `gap_unknown` and let the trigger run. Re-score today's 22 voids as a counterfactual.
2. **Loss halt cannot be silently absent**: if equity is unavailable, either refuse to arm in
   auto mode or fall back to a fixed dollar default, and journal + alert either way.
3. **Touch counting** per the docstring (extreme reaches the band). Re-run a sweep before/after
   to see how many grades move.
4. **Breakout stop = below the most recent swing low before the break** (the wedge rule
   generalised), buffered like the bounce stop; never `level − 0.5 %`. Blue-sky ladder: TP1 from
   ATR or refuse to grade (`R:R n/a`), not "12.0".
5. **R:R for the R2 gate = to the exit we will actually take** (TP2 for < 3 contracts).
6. **One `relative_volume` for everything** (trigger bar numerator, prior-sessions-only
   time-of-day baseline, one fail-open/closed policy — propose fail-closed for entries, journaled
   as `volume_unknown`), and expose `volume_floor_mult`.
7. **Exchange bars for the trading path**: evaluate triggers on the exchange bar for minute M
   when Alpaca is up (hold the sampled bar for ≤ 5 s, replace it with the exchange bar, else fall
   back), so the volume gate and the scorecard see the same series.
8. **Critic hygiene**: pick the contract *before* the critic; hard `asyncio.wait_for` timeout
   (e.g. 20 s) with fail-**closed** in auto mode; run it off the bar loop so exits never wait.
9. **Option quote freshness**: `set_overlay` stamps `ts`; exclude OCC symbols from the Alpaca
   equity subscription; premium stop alert at 60 s not 5 min.
10. **False-breakout counter** (R3.2): per level per session, N failed candidates → level done.

### B. Before any real-money arming
- Fleet-wide open-position and premium-at-risk caps; R1 on premium; re-tighten the raised
  `risk.*` caps; earnings/FOMC/holiday calendar (a static macro list + an earnings feed);
  extended-hours exit policy (RTH bars only for stops, or explicit after-hours rule); watchdog
  escalation instead of parking; restart discipline while positions are open; real-time option
  quotes; fees in P&L; `stale` as a real fire gate.

### C. Method-fit work (measurable, book-driven)
- Volume taper into the level; T1.3b carry-over; flag/consolidation detector; higher-tf fakeout
  check; wedge height at the pattern start; prior-day extremes exempt from the touch gate.

### D. Decisions to make with the data we have / can get quickly
- **Universe**: back toward the book (price ≥ $20–30, tight option spreads, real 1m volume) —
  or keep the wide list *for validation only* and arm a curated core.
- **gap_void_r**: 08-25's 8 voids are valid samples; today's 22 are not. Decide after the
  counterfactual on the valid set (the threshold in TRADING-RULES 1.1 stands).
- **0DTE policy**: Friday weeklies at 1 contract = full-size 0DTE. Options: skip 0DTE on
  single names, or next-week expiry on Fridays, or allow only in the open window.
- **Stop on close vs low**: A/B in the sweep (cheap) before touching live.
- **Trigger tf 5m vs 1m**: same.
- **C-grade / analyst-✗ arming**: T is the first datapoint (6 garbage fires). Keep the cohort
  for the count, but consider alert-mode only for C's.

### E. Telemetry
- Capture-rate roll-up, "why not traded" ledger, premium-R alongside underlying-R.

---

## 6. Questions for the discussion

1. Universe: do we go back to the book's mega-cap set for arming, and keep the 50 for sweeps?
2. Options risk: define R1 on premium (skip if premium > x % of equity) — what x?
3. 0DTE on Fridays with one contract — skip, next-week, or open-window only?
4. Stop semantics: keep the wick stop, or move to close-below + quote breach (book-closer)?
5. Order of work: A1–A2 (restart-gap + silent no-halt) are same-day fixes; A3–A10 are a
   focused pass; B is the live-money gate. Agree on A first?
6. Short side: schedule it after the long-side sample, or start mirroring now to double the
   sample rate?
