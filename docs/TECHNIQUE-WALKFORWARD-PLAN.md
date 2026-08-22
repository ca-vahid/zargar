# Session Plans & Walk-Forward Validation — design

**Status:** **built 2026-08-22** (phase 1 *and* phase 2) on branch
`claude/technique-walkforward` — see §14 for the as-built map. First draft 2026-08-22
(developer session); rewritten after a full read of the book, the code and the review loop
that landed in `2e6d58a` (`docs/TECHNIQUE-REVIEW-PLAN.md`). Decisions taken with the user
are in §11. Tests: `backend/tests/test_technique_walkforward.py`.
**Companions:** [`TECHNIQUE-ENHANCEDMARKET.md`](TECHNIQUE-ENHANCEDMARKET.md) (rule spec),
[`TECHNIQUE-PIPELINE-PLAN.md`](TECHNIQUE-PIPELINE-PLAN.md) (what is built),
[`TECHNIQUE-REVIEW-PLAN.md`](TECHNIQUE-REVIEW-PLAN.md) (trace / outcomes / reviews / replay).

---

## 1. The question that produced this document

> "When I run analysis for a previous session, say 8/20, do I see the possible runs for
> 8/21 — for the next session? Old analysis should show possibilities for the next
> business day. This is to confirm if our assumptions are correct. Is that what we're
> doing?"

**No — and it should.** Investigating the question also surfaced rules in the book that
the spec never codified (one contradicts a default we shipped), plus two detector gaps
that would distort any validation run. All of it is described here, with page numbers.

---

## 2. What the tool does today (verified, not assumed)

Running an analysis with Period = 8/20 pins `as_of` to that session's close and filters
every bar to `ts <= as_of`. Verified by execution:

```
as-of instant:            2026-08-20 16:00 local
sessions in window:       08-11 … 08-20        (8 sessions of 5m bars)
last bar the model sees:  2026-08-20 15:55 ET  (final bar of the session)
facts.lastClose:          311.34               (8/20's closing price)
facts.session.today:      8/20  open 317.45  HOD 320.28  LOD 310.65
facts.session.prev:       8/19  HOD 319.28   LOD 309.60  close 316.88

emitted candidate:  support_bounce, entry 310.35, basis "at_level", R:R 0.65
```

The history handling is correct (no look-ahead). The **framing** is not:
`basis: "at_level"` means "enter now, at this price" — but *now* is 16:00 on a closed
market. The tool answers a question that cannot be acted on, and never checks what
happened next. Since `2e6d58a` the outcome loop does score what price did after a
backdated run, but it scores a *fill* the book would never have taken at that moment.

### The four time framings

| # | Framing | Question it answers | Status |
|---|---|---|---|
| 1 | **Intraday, live** | "It is 10:47 and price is at support — take it?" | ✅ built, but ignores the book's schedule (§3.2) |
| 2 | **Intraday, replayed** | "At 10:47 on 8/20 the rules fired — did it work by 11:30?" | ✅ built (Backtest tab + per-run outcomes), same schedule blind spot |
| 3 | **Close of N → plan for N+1** | "These are Monday's levels; here is what to watch" | ❌ **missing** |
| 4 | **Did plan N predict session N+1?** | "Are our assumptions correct?" | ❌ **missing** |
| 5 | **Plan N armed live on N+1** | "Price just touched the planned level inside a prime window — act" | ❌ missing (phase 2, §9) |

Framings 3 and 4 are the body of this document; 5 is the follow-on.

---

## 3. What the book actually says (full re-read, 123 pp.)

`TECHNIQUE-ENHANCEDMARKET.md` §0 classified pp. 111–123 as *"Partial — One-Contract Rule
only"*. **That was wrong.** The "Actionable Next Steps" section contains hard rules, and
several earlier pages speak directly to the plan-then-verify workflow.

### 3.1 The author's own routine is close-of-day → next session

- "Prepare Your Own Watchlist: **Before the session begins**, prepare your own watchlist of
  stocks or options to track." (p. 116)
- His free 9:00 AM stream: "potential trading opportunities for the day ahead, including
  **key levels**, market sentiment and economic news." (p. 115)
- "Always be aware of **previous day's support/resistance levels**. They often play a
  significant role in the next day's price action." (p. 71) — the worked SPY example
  carries 498.75 from the prior session and calls HOD/LOD-anchored trends "the strongest".
- "**Set alerts above and below key levels** to stay informed." (p. 117) — the plan *is* a
  set of alerts.
- "At the end of each trading day, **remove all your drawings**… Start fresh the next day
  by **redrawing your levels** and patterns." (p. 120) — plans are rebuilt every session;
  only prior-day HOD/LOD are explicitly carried (T1.3a/b).

### 3.2 Trading schedule (pp. 114–115) — NOT codified. New rules R6.1–R6.4.

| Rule | Window (ET) | Verdict | Book's reasoning |
|---|---|---|---|
| **R6.1** | 09:30–10:30 | **Prime** | "highest volatility and volume… institutional orders… reacting to overnight news". Momentum, breakouts, early reversals. |
| **R6.2** | 14:45–16:00 | **Prime** | "surge in activity as traders adjust or close positions". End-of-day momentum, continuation, last-minute breakouts (the p. 71 SPY example is a last-hour breakout on volume). |
| **R6.3** | 10:30–14:45 | **Avoid** | "lower volume, choppy price action, and a lack of clear direction". Risks: theta decay, false breakouts, whipsaws. |
| **R6.4** | pre-market & after-hours | **Avoid** | "lack the volume necessary for reliable options trading". Risks: slippage, wide spreads, erratic swings. |

> "Trading more does not equal making more. Focus on quality trades during
> high-probability times." (p. 115)

**What we violate today:** the pipeline emits setups at 12:30 without a word; the scan
loop runs every 30 min across the whole session (`service._scan_loop`, `_in_rth` = 09:30–
16:00); the Backtest harness steps a cursor across the whole day and scores every fill.
**The backtest's current numbers therefore do not measure the book's method.**

### 3.3 Timeframe preference (p. 114) — contradicts our default

> "Focus on 30-Minute and 1-Hour Timeframes… My personal win rate is significantly
> higher on these timeframes (**78%**) compared to lower time frames (**58%**)."

The only quantified performance claim in the book. We shipped `technique.default_tf = 1m`,
the UI offers only 1m/5m/15m, and `history.py` has **no 30m interval at all**.

**Reading it correctly:** the author identifies levels and patterns on 30m/1h charts and
then trades intraday options (0DTE / current-week, pp. 22–23) inside one-hour prime
windows. 09:30–10:30 is *one* 1h bar. So the 30m/1h preference is about **where
structure is read**, not about entering on hourly closes. The design below separates a
**structure timeframe** (30m/1h) from a **trigger timeframe** (1m/5m) — §11 decision.

### 3.4 Already aligned — after-hours data (p. 114)

"Disable After-Hours Data: After-hours trading volume is often low, which can create
misleading signals." `history.py` sends `includePrePost=false`. Record as **R6.5** so
nobody "fixes" it.

### 3.5 Stops are chart-based, never a fixed percentage (pp. 73, 117) — detector gap

- "I use **the level below support** as my mental stop-loss guide… long at $100, support
  $98 → mental SL ~$97.50; I wait to see how price reacts at support." (p. 73)
- "**Avoid** the common advice of using a stop loss based on a **fixed percentage**. This
  method is especially flawed… set your stop losses based on the chart." (p. 117)

Read carefully, the book's bounce stop is a *zone just under the level* ("$98 support →
watch ~$97.50", i.e. ~0.5 %), and the "fixed percentage" it rejects is a stop set on the
entry/premium with no regard to the chart (options swing 15–20 %). `build_bounce_setup`
was already level-anchored (`level − max(2·tol, 0.5 %)`); what it lacked was
**volatility awareness** and a tunable. *As built:* `setups.bounce_stop` = level − max(2·tol,
`technique.bounce_stop_pct` (0.5 %), 0.25 × ATR), cited as **T4.3d**; the breakout / wedge
stops keep their level / wedge-low references.

### 3.6 Other rules that bear on plans (cited for completeness)

- **Volume floor is time-of-day relative** (p. 63) — already implemented (`volume.py`);
  in a plan it becomes a *trigger-time* condition, not a build-time one.
- **No daily profit target; "day trading doesn't mean trading every day"** (p. 117) — a
  plan with **no** triggers is a valid, expected output.
- **"Aim for 2+ confluences per trade"** (p. 67) — a cheap trigger-quality score: level
  source priority (T1.3a > b > c > d), touch count, higher-TF agreement, volume posture.
- **Backtesting** (pp. 72–73): ≥ 100 trades, test across conditions, account for slippage,
  don't cherry-pick; review over 6–12 months (p. 98). Walk-forward must be cheap.
- **"Buying the dip": sharp sell-off into support with little consolidation = faster
  recovery** (p. 67) — a plan note, not a gate.
- The author's own numbers: ~60 % win rate at 2.5:1 (p. 6); "good R/R is 1:3 or higher"
  (p. 62). R2's ≥ 3.0 gate is a parameter the sweep should scan, not a law.

---

## 4. Gaps (corrected list)

| # | Gap | Where | Severity |
|---|---|---|---|
| G1 | As-of-close runs emit *fills* instead of *plans*; no next-session check | `service.analyze`, UI "Period" | **core** |
| G2 | Trading schedule R6 absent: pipeline, scan loop, backtest all time-blind | `rulebook.py`, `backtest.py`, `service._scan_loop` | **high** — backtest numbers invalid |
| G3 | No 30m; default/primary TF is the one the book reports as worse; structure vs trigger TF not separated | `history.py`, `analysis.py`, settings, UI | **high** |
| G4 | Bounce stop is a flat 0.5 % with no volatility awareness or tunable (book: chart-anchored zone just under the level, never a fixed % of entry/premium) | `setups.build_bounce_setup` | medium — fixed (`bounce_stop`, T4.3d) |
| G5 | No level-quality measurement independent of trades | — | high (it is the fast signal) |
| G6 | Overnight gap handling undefined | — | medium (book silent; our extrapolation) |
| G7 | UI "Period" as-of is 16:00 **local**, not ET (`dateToAsOfMs`) | `TechniquePage.tsx` | low now (user is west of ET), fragile |
| G8 | Volume baseline / sessions keyed by UTC date (`levels.session_key`, `volume._session`) | — | none for US RTH (13:30–20:00 UTC same date); would break for overnight markets — note only |
| G9 | Plan output has no home in the review loop (trace, outcomes, reviews, replay) | `models.py`, `outcome.py` | medium — must be designed in, not bolted on |
| G10 | Spec §0 mis-scopes pp. 111–123; no R6 section; Q11–Q13 missing | `TECHNIQUE-ENHANCEDMARKET.md` | doc |

---

## 5. What a Session Plan is

A **Session Plan** is the output of running the technique as-of a session boundary (the
close of N, or any time before the open of N+1 — same bars). It is *not* a trade. It is
the map plus conditional triggers plus the conditions that void them.

```
SessionPlan
  planFor            2026-08-21                  session this plan is for
  builtFrom          2026-08-20 16:00 ET         as-of instant (last bar consumed)
  symbol
  structureTfs       ["1h", "30m"]               where levels/patterns were read (R: p.114)
  triggerTf          "1m" | "5m"                 where triggers are evaluated
  levels[]           price, kind, touches, sources (T1.3a prior HOD/LOD, b, c, d), tfs, age
  context            trend per tf (T3.5), volume posture (T2), wedge geometry (T3.1), prevClose
  triggers[]         conditional setups — §5.1
  invalidations[]    plan-wide void conditions — §5.2
  gapPolicy          the Q11–Q13 numbers in force
  provenance         config snapshot (processVersion etc., same as runs)
```

### 5.1 A trigger is conditional, never a fill

```
TODAY (wrong for a closed market)
  entry 310.35   basis: at_level        ← "fill me now"

PROPOSED — bounce trigger
  WATCH  support 310.35 (prior-day LOD ×3, T1.3a)
  IF     price trades into 310.35 ± tol                     (T4.1 — at the level)
  AND    time is inside 09:30–10:30 or 14:45–16:00 ET       (R6.1 / R6.2)
  AND    volume at the touch ≥ 50 % of time-of-day baseline  (R3.1, T2.9)
  THEN   long at 310.35, stop 309.20 (next support below, T4.3a), targets [...], R:R 3.2
  NOTE   hammer / long lower wick at the touch raises confidence (T3.4b) — it is NOT a
         gate: T4.2 says do not wait for visual confirmation on a bounce.
  VOID   if the session opens below the stop; if gap > gapVoidR × risk

PROPOSED — breakout / wedge trigger
  WATCH  resistance 317.80 (×2) / wedge upper line at open
  IF     a bar CLOSES above the level
  AND    inside a prime window (R6)
  AND    volume on the break ≥ 1.5× baseline (T3.3a/T2.5) AND candle decisive (T3.3b)
  AND    follow-through: 2 of next 3 bars hold above (T3.3c/f)                 ← confirmation REQUIRED
  THEN   long at the break close, stop below wedge low / broken level, target measured move (T3.1e/f)
  VOID   if the session opens above the level (gapped past; T4.1 forbids chasing)
```

Every clause maps to an existing rule id. The change is that the conditions are *stated
and then tested* instead of silently assumed true at the analysis instant.

### 5.2 Invalidations and overnight gaps (book is silent — our extrapolation)

The author is flat overnight and never discusses gaps. Recorded as spec Q11–Q13,
flagged as ours, every number a setting:

| Case | Rule | Record as |
|---|---|---|
| Opens **beyond the entry** (gapped past a bounce level / above a breakout level) | trigger not taken — T4.1 forbids chasing | `gapped_past` |
| Opens **beyond the stop** | trigger void | `gapped_through` |
| `|open − prevClose| > technique.plan.gap_void_r × risk` (default 1.0) | whole plan void; geometry no longer exists | `gap_void` |
| Level gapped through and never retested | not scored as a trade; scored for **level flip** (support → resistance, T1.3b) | `flipped` / `not_flipped` |

Because gap handling is our invention, the sweep reports results **with and without** the
gap rules so their effect is measured rather than assumed.

### 5.3 Timeframe model (decision — §11)

| Role | Timeframes | Why |
|---|---|---|
| **Structure** (levels, trend, wedge, prior HOD/LOD) | 1h + 30m | p. 114; deep history (30m 60 d, 1h 2 y) |
| **Trigger** (touch, close-through, volume at the bar, window) | 1m (default) or 5m | intraday execution; prime windows are 60–75 min |
| **Volume baseline** | trigger tf, time-of-day profile from prior sessions | T2.9 |

The plan reports per-structure-tf results so the 78/58 claim is testable: the same
sessions swept with structure on 5m/15m vs 30m/1h.

---

## 6. Walk-forward validation

### 6.1 The loop

```
for each session N in [start … end]:
    plan  = build_session_plan(symbol, as_of = close of N, structure_tfs, trigger_tf)   # deterministic, free
    next  = bars of session N+1 at trigger_tf                                           # no look-ahead
    res   = replay_plan(plan, next)                                                     # bar by bar
aggregate(res) by symbol, setup type, window, structure tf, level source, touches, R:R gate
```

`replay_plan` walks N+1 in order and records, per trigger:

1. **Open behaviour** — gap vs prev close and vs plan risk; `gapped_past` / `gapped_through` / `gap_void`.
2. **Trigger** — did the condition fire? at what time? inside which R6 window?
3. **Fill & sequence** — `outcome.simulate_plan` from the trigger bar (entry window, stop
   wins a straddling bar, 30/40/15 trims, runner to horizon) — *the same scorer as live
   outcomes and the backtester*, so numbers are comparable everywhere.
4. **Outcome** — R multiple, MFE/MAE, bars held, resolved-by-close.
5. **Counterfactuals** — the same trigger *without* the R6 gate and *without* the gap rules
   (so each rule's value is measured, §6.4).

### 6.2 Two metric families, deliberately separated

**(a) Level quality — independent of any trade.** For every plan level: did N+1 *respect*
it? `respected` = price entered the ±tol band and reversed ≥ `respect_mult × tol`
(default 3) without a *close* beyond the band; `broken` = closed beyond; `flipped` =
broken then respected from the other side; `untested` = never came within band.
Bucketed by source (T1.3a/b/c/d), touch count, structure tf, age. Needs no entry rules,
no R:R gate, no trades — and gives a usable signal within days.

**(b) Trigger / setup quality — the full rule stack.** Trigger rate, fill rate, win rate,
avg R, expectancy, per setup type, per window (prime-open / prime-close / mid-day), per
structure tf, per R:R gate value. Needs the 50–100-trade sample.

If levels are respected 70 % of the time but setups lose, the entry/exit rules are at
fault, not the detection — and vice versa. One combined number would be un-actionable.

### 6.3 Cost

Plan building is **deterministic by default** — the detectors already produce levels,
volume posture, trend, wedges and candidates. A 60-session × 9-symbol sweep is free and
takes minutes. `--with-vision` runs the 4-pass model on a sample (≈$0.20/run) to answer a
separate question: *does the model's judgement beat the deterministic triggers?*

### 6.4 Pass criteria — what "assumptions are correct" looks like

| Claim under test | Metric | Passing looks like |
|---|---|---|
| Prior-day HOD/LOD are the strongest levels (T1.3a) | respect rate by source | T1.3a > T1.3b > T1.3c/d |
| ≥ 2 touches makes a level real; 3+ stronger (T1.2) | respect rate by touch bucket | monotonic in touches |
| Prior-day levels carry into the next day (T1.3b, p. 71) | respect + flip rate of carried levels | materially above chance |
| Volume confirms breakouts (T3.3a/T2.5) | win rate, confirmed vs unconfirmed breaks | confirmed ≫ unconfirmed |
| Fakeout tests add value (T3.3d–f) | outcome of rejected breaks | rejected breaks lose on average |
| Enter at the level, don't chase (T4.1/T4.2) | avg R by entry distance from level | at-level ≫ chased |
| R:R ≥ 3 is the right gate (R2) | expectancy across gate ∈ {2, 2.5, 3, 4} | 3 is not dominated |
| Prime windows beat mid-day (R6.1–R6.3) | win rate / expectancy by window | prime > mid-day |
| 30m/1h structure beats lower tfs (p. 114, 78 vs 58) | win rate by structure tf | replicates the direction, if not his numbers |
| Gap rules help (Q11–Q13, ours) | expectancy with vs without | with ≥ without, else drop them |

The 78/58 row deserves the most scepticism — one trader's self-report on an unstated
sample — and it is exactly what the harness exists to check.

---

## 7. Integration with the review loop (must be designed in)

Everything in `docs/TECHNIQUE-REVIEW-PLAN.md` applies to plans:

| Piece | How plans use it |
|---|---|
| `technique_runs` | a plan is a run with `mode="plan"`; `result.plan` holds the SessionPlan; `result.trace` records why each level/trigger was kept or dropped (stage `plan`); `config` carries structure/trigger tfs and gap policy |
| `technique_outcomes` | one row per trigger, `plan_source="trigger:<i>"`; `status` pending until N+1 is complete; `path` + `levelRespect` summary stored on a `plan_source="levels"` row |
| `technique_reviews`, `/technique-review` skill, bundle | unchanged — a plan is reviewable ("why was this level not in the plan?", "trigger fired at 11:10 — correctly skipped by R6.3?") |
| replay | `replay_run` on a plan rebuilds it from the bars snapshot with threshold overrides and re-scores against the same N+1 bars |
| **sweep table** (new) | `technique_walkforward` — one row per (sweep, symbol, session): plan summary, level-respect counts, trigger results, counterfactuals; aggregates computed on read. Bulk rows stay light; any session can be **promoted** to a full plan run for deep review |

---

## 8. What changes in code (phase 1 — plans + walk-forward)

| Area | Change |
|---|---|
| `rulebook.py` | R6.1–R6.5 texts; `session_window(ts_ms) → prime_open \| prime_close \| midday \| extended`; `Thresholds` gains `respect_mult`, `gap_void_r`, `plan_entry_window_bars` |
| `history.py` | add **30m** (`1800 s`, 59-day span/lookback); `fetch_session(symbol, tf, date)` helper |
| `analysis.py` | `AnalysisRequest` gains `structure_tfs`, `trigger_tf`; FACTS gain `sessionWindow` of as-of and `gap` (open vs prevClose) when the as-of is intraday; `compute_facts` keeps working for live runs |
| `setups.py` | **bounce stop = next support below** (buffer = max(tol, 0.25 ATR)); fallback ATR-based; surface `stopReference="next_support"`; `confluences` count per setup (p. 67) |
| `plans.py` *(new)* | `build_session_plan(symbol, as_of, *, structure_tfs, trigger_tf, thresholds) → SessionPlan`; `plan_to_dict`; trigger builders for bounce / breakout / wedge from the existing detectors; invalidations + gap policy |
| `walkforward.py` *(new)* | `replay_plan(plan, next_bars)`, `level_respect(levels, bars)`, `run_sweep(symbols, start, end, …)` with counterfactuals and aggregation; uses `outcome.simulate_plan` |
| `backtest.py` | gate fills by `session_window` (setting, default on); report by window; keep the old behaviour behind `--all-hours` so the before/after is visible |
| `service.py` | `analyze()` → `mode="plan"` when the as-of is at/after a session close (or `plan=True`); scan loop runs in prime windows only (setting) and labels mid-day runs; `score_run` understands plan triggers; `sweep()` + `promote()` |
| `vision.py` / `schemas.py` | R6 in the rulebook → prompt; `--with-vision` plan prompt emits *triggers* (watch / if / then / void), never fills; `TechniqueAnalysis` gets `session_window` + `plan_mode` fields (flat) |
| `models.py` | `technique_walkforward` (sweep rows); no new columns on runs needed beyond `mode` values |
| Settings | `technique.structure_tfs` = `["1h","30m"]`; `technique.trigger_tf` = `1m`; `technique.default_tf` **stays the trigger/primary tf (1m)** for live runs — structure is the new knob, so live behaviour is unchanged (UI copy cites p. 114); `technique.bounce_stop_pct` = 0.5; `technique.enforce_session_windows` = on; `technique.scan.windows` = `["prime_open","prime_close"]`; `technique.plan.gap_void_r` = 1.0; `technique.plan.respect_mult` = 3; `technique.plan.entry_window_bars` = 12; `technique.plan.with_vision` = off; `technique.walkforward.symbols` = SPY, QQQ, AAPL, MSFT, NVDA, TSLA, AMD, META, AMZN; `technique.arm.enabled` / `technique.arm.use_critic` / `technique.arm.auto_symbols` |
| API | `POST /api/technique/plan {symbol, asOf?, structureTfs?, triggerTf?}`; `POST /api/technique/walkforward {symbols, start, end, …}`; `GET /api/technique/walkforward/{sweepId}` (+ aggregates); `POST /…/{sweepId}/promote {symbol, session}` |
| CLI | `technique_review plan <sym> [--as-of]`, `sweep …`, `sweep-report <id>` — same tool the skill drives |
| UI | **Plan card** (levels with provenance, triggers as WATCH/IF/THEN/VOID, window badges; no fill price); **Validation tab** (sweep runner, level-respect and setup tables, per-window/per-tf breakdowns, claim pass/fail grid from §6.4); session-window badge on every run; "Period" as-of fixed to **16:00 ET**; 30m/1h offered; Advanced explainer carries the p. 114 citation |
| Spec | §9 corrections below |
| Tests | no-look-ahead regression (plan built at close N must not change when N+1 bars are present); window classifier; bounce stop = next support; gap cases; level-respect scorer on synthetic sessions; sweep on synthetic data; plan-as-run round trip through outcomes/bundle |

### 8.1 Migration notes

- Changing `default_tf` semantics (structure vs trigger) is a settings-default change;
  explicit user choices are preserved; the Advanced explainer shows why.
- Existing backdated runs keep their current (fill-based) outcomes; new plan runs get
  trigger-based ones. The history table shows `mode` so the two aren't mixed.

---

## 9. Phase 2 — arm the plan for live trading (framing 5)

The book's "set alerts above and below key levels" (p. 117), done by the machine:

1. At (or before) the open, the day's plan is **armed**: its triggers become live
   watchers on the quote/bar bus.
2. A trigger fires only inside R6 prime windows; mid-day touches are logged as
   `observed_midday` (data for §6.4), not acted on.
3. On fire: the deterministic checks run on the live bar; optionally the vision critic
   (PASS 4) reviews the live chart before a setup is emitted; the setup then follows the
   existing practice-proposal → approval → RiskGate path. **No new order path.**
4. Every fire / skip / void is journaled against the plan run, so the evening review is
   plan-vs-reality, not memory.

Built after phase-1 results show the triggers are worth arming. Designed now so the plan
schema needs no change later (`triggers[].armedAt`, `firedAt`, `skippedReason`).

---

## 10. Honest limitations

- **Yahoo depth**: 1m ≈ 20 d (8 d/request), 5m/15m/30m ≈ 60 d, 1h ≈ 2 y. A 100-trade
  sample on 1m triggers is unreachable from free data; 5m triggers reach ~60 sessions.
  The structure timeframes the book prefers are exactly where we have depth.
- **No look-ahead is enforced by filtering `ts <= as_of`**; the plan builder must keep
  it — regression test required.
- **Fills are assumed at the level**; real fills slip (p. 72). Results are optimistic.
- **This validates the codification, not the book.** Rule-id citations exist so the two
  can be told apart; a poor result may mean our reading is wrong.
- **Regime & survivorship**: a few weeks of one regime proves little (p. 72, p. 98).
- **Gap rules, level-respect definition and the trigger/structure split are ours**; each
  is reported with its counterfactual so it can be dropped if it doesn't earn its place.

---

## 11. Decisions taken (2026-08-22, with the user)

| Question | Decision |
|---|---|
| Timeframes | **Structure on 30m/1h, triggers on 1m (default) / 5m**; per-structure-tf reporting so p. 114 is testable; add 30m to history |
| Symbol universe | **Book's universe** — SPY, QQQ, AAPL, MSFT, NVDA, TSLA, AMD, META, AMZN; holdings addable per sweep |
| End goal | **Validate first (phase 1), then arm plans for live triggers (phase 2)** |
| Where this lives | main checkout `docs/`; implementation on a fresh branch off main |
| Plan horizon | **One session, rebuilt daily** (p. 120), prior-day HOD/LOD carried (T1.3a/b); level `age` recorded |
| Which sessions to plan | **Every close** — "no trigger" is data (trigger-rate metric) |
| Prime-window enforcement | **Detect everywhere, gate at trigger, report both** — measures R6 instead of assuming it |
| Bounce trigger gate | **No candle requirement** (T4.2); hammer/wick = confidence only |
| Gap handling | our extrapolation; `gap_void_r` default 1.0, all gap rules reported with counterfactual |
| Model in plan mode | **Deterministic default, vision opt-in**; "model vs rules" is its own measured question |
| Storage | plans are runs (`mode="plan"`) + `technique_outcomes` rows; bulk sweep in `technique_walkforward`; any session promotable to a full run |

---

## 12. Corrections to the rule spec (`TECHNIQUE-ENHANCEDMARKET.md`)

- §0 scope: pp. 111–123 → **KEEP** (schedule, timeframe preference, watchlist prep,
  alerts, clean-chart daily rebuild, one-contract rule).
- New **§R6** — R6.1–R6.4 windows, R6.5 after-hours data; cite pp. 114–115.
- T4.3 note: stop = **level below support**, fixed-% explicitly rejected (pp. 73, 117).
- New note under T-modules: author's 30m/1h preference and 78 %/58 % (p. 114) —
  single-trader self-report, to be tested; structure vs trigger tf split is ours.
- T1.3b strengthened with p. 120 (levels redrawn daily) and p. 117 (alerts at levels).
- §10 gap table: **Q11–Q13** gap handling, **Q14** level-respect definition, **Q15**
  structure/trigger timeframe split — all marked as our extrapolation.
- §11 status table is stale (everything shows ☐) — refresh.

---

## 14. As built (2026-08-22)

| Piece | Where |
|---|---|
| R6 windows, `session_window` / `session_bounds` / `next_session_date`, new rules T1.6 / T4.3d / T4.6 / R6.1–R6.5, thresholds `bounce_stop_pct`, `stop_buffer_atr`, `respect_mult`, `gap_void_r`, `plan_entry_window_bars` | `backend/zargar/technique/rulebook.py` |
| 30m interval, `fetch_session(symbol, tf, date)` | `technique/history.py` |
| `bounce_stop` (ATR-aware, T4.3d), `confluences` (T4.6) | `technique/setups.py` |
| `sessionWindow`, `gap`, `atr` in FACTS and the prompt; `AnalysisRequest.structure_tfs` / `trigger_tf` | `technique/analysis.py` |
| SessionPlan / Trigger / Condition, `build_session_plan`, `analysis_from_trigger`, `plan_summary_text` | `technique/plans.py` |
| `TriggerTracker` (shared by replay and live), `level_respect`, `replay_plan` (+ counterfactuals), `run_symbol`, `aggregate` (+ claims grid) | `technique/walkforward.py` |
| Backtest R6 gating (`prime_windows_only`, `byWindow`) | `technique/backtest.py` |
| `mode="plan"` (auto when the as-of is outside the session, or `plan=True`), plan trace (stage `plan`), R6 watch-only (stage `window`), `_score_plan_run` (per-trigger + `levels` outcome rows), sweeps (`start_sweep` / `get_sweep` / `promote`), scan windows, arming wiring | `technique/service.py` |
| `PlanArmer` (arm / disarm / arm_today / auto-arm, bus-driven bar loop, critic on fire, setup + proposal via the existing path, journal + chat notes) | `technique/arming.py` |
| `VisionPipeline.run_critic`; `session_window` / `plan_mode` fields; R6 + plan-mode prompt text | `technique/vision.py`, `technique/schemas.py` |
| `technique_sweeps`, `technique_walkforward` tables; events `TechniqueSweepStarted/Completed`, `TechniquePlanArmed/Disarmed`, `TechniquePlanTriggerFired/Skipped` | `models.py`, `events.py` |
| API: `POST /api/technique/plan`, `POST/GET /api/technique/walkforward[/{id}]`, `POST …/{id}/promote`, `GET /api/technique/armed`, `POST/DELETE /runs/{id}/arm`, `POST /api/technique/arm-today`; `analyze` body `plan` / `withVision`; backtest `primeWindowsOnly` | `api/routes_technique.py` |
| CLI: `plan`, `sweep`, `sweeps`, `sweep-report`, `promote`, `arm`, `disarm`, `arm-today`, `armed` | `tools/technique_review.py` |
| UI: PlanCard (levels + WATCH/IF/THEN/VOID triggers + session scorecard + arm), Validation tab (sweep runner, claims grid, level/trigger tables, promote), Armed-plans rail, R6 window badges, Period as-of = 16:00 ET, 30m/1h offered, backtest prime-window toggle | `frontend/src/components/technique/PlanCard.tsx`, `ValidationTab.tsx`, `RunResult.tsx`, `TechniquePage.tsx` |
| Tests (15): windows, ATR stop, plan shape, no look-ahead, tracker gap/window/volume/breakout paths, level respect, replay + counterfactuals, sweep + aggregate, plan run end-to-end (trace, scoring, bundle, replay), R6 watch-only, sweep service + promote + CLI, arming fire/expire, scan windows | `backend/tests/test_technique_walkforward.py` |

## 13. Open items (not blocking)

- Whether the walk-forward sweep should also run the **image-only** path on a sample
  (the user sometimes pastes screenshots) — probably not; no bars to score.
- Short side stays out (Q10); the book's chart-inversion tip (p. 120) suggests the
  author does trade puts — revisit after the long-side numbers exist.
- FOMC / economic-calendar no-trade days (R3.4) need a calendar source before the sweep
  can exclude them; until then they are flagged, not filtered.
