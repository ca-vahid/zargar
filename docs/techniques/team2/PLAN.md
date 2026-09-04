# Team2 technique — desk plan (design + build phases)

*Opened 2026-09-03. This desk (the Team2 desk) owns the Team2 technique end to end: its docs,
its plan builder, its runner, its review loop and its evolution loop — separate from EM's,
sharing only the engine and the generic tools. Method spec: `METHOD.md`. Judgement log:
`TRADING-RULES.md`. Engine rules we inherit: `docs/BUILDING-A-TECHNIQUE.md`,
`docs/PLATFORM-RULES.md`. Checkboxes below are the build status; decisions are logged in §2.*

## 0. Desk charter

- **Goal**: every trading day, before the open, Team2 has its own session plans for SPY, QQQ
  and IWM armed (alert → proposal → auto, earned the same way EM earned it), a nightly
  outcome score, a review loop that explains every fire and every miss, and a variant sweep
  harness so the method can evolve on evidence.
- **Separation**: `techniques.team2.*` settings, `technique_id="team2"` on every run, order,
  position and journal event; its own UI page from the registry (never hard-coded in the
  nav); its own `TRADING-RULES.md`. Nothing in `zargar/technique/` (EM's package) is edited
  for Team2 — shared needs go to `marketstructure/` or `execution/` as technique-agnostic
  code, logged in `PLATFORM-RULES.md`.
- **Data policy**: everything we learn from the author stays under `notes/` verbatim, never
  re-fetched (`SOURCES.md`).

## 1. The trade, as the engine will see it

```
nightly (after close)   : PDH/PDL zones from today's RTH 15m bars  ->  4 bias scenarios  ->  plan skeleton per symbol
pre-open (09:25 ET)     : PMH/PML from 04:00-09:25 bars  ->  gap read vs PDH/PDL  ->  final plan (triggers + levels + targets)
session (2m closes)     : EMA regime (13/48/200, ext-hours warmed)  ->  15m close beyond level = CONFIRMED
                          -> 1st/2nd 2m pullback into EMA13 / level retest that HOLDS = FIRE
                          -> BUY option (Q1)  ->  stop = 2m close through EMA/level (1 candle)
                          -> trim at new high/low push, runner on EMA13 close, zone target, 16:05 flatten
nightly                 : outcome score (simulate_plan parity), review trace, scorecard, sweep rows
```

Plan = data (levels, zones, scenario table, trigger specs, targets, thresholds snapshot), the
same shape EM and Tip plans use, so replay / sweep / audit work unchanged.

## 2. Decisions (log every one with a date)

| # | Decision | Status | Notes |
|---|---|---|---|
| D1 | Technique id `team2`, label "Team2", page `team2`, settings prefix `techniques.team2.` | proposed 2026-09-03 | rename before registering if the user prefers |
| D2 | Universe fixed: SPY, QQQ, IWM (`techniques.team2.symbols`) | proposed | no scan; author never varies it |
| D3 | Contract (METHOD Q1) | **DECIDED 2026-09-03 (user): Team2 is a 0DTE technique; open the never-list for `team2` with its own gated path.** Rules differ per technique by design. Implementation: RiskGate gets a per-technique 0DTE policy (`techniques.<id>.zero_dte = {enabled, flatten_et, max_contracts, premium_cap}`) instead of hard-coded technique ids; Team2's path = entry-day expiry only, flatten at `techniques.team2.flatten_et` (default 15:45), premium-targeted strike (`target_premium` 0.60, floor 0.20), never after the flatten time. 1DTE stays a sweep VARIANT for comparison, not the default | **firm** |
| D2b | Images (96 MB) stay local, `*.jpg` gitignored; JSON metadata + INDEX.md are committed | firm (user) | |
| D4 | Sizing multipliers (Q2): trend-day outside both ranges 1.0 · inside prior range 0.5 · inside PM range 0 | proposed | sweep 0.25/0.5/0.75 for the middle bucket |
| D5 | Exit ladder (Q3): author trims at +50% and +100% premium (first cue = new high/low of day), runner exits on a 2m close through EMA13, outright exit at the next zone or "when it goes ITM" | proposed (fractions unknown → 1/3 · 1/3 · runner) | sweep fractions; premium-path simulation required (F1) |
| D6 | Entry window (Q4): author has NO time gate (P2); ours: first fire ≥ 09:45 (first 15m close), last fire 15:30, flatten 16:05; pre-10:00 fires tagged `early` and post-14:00 tagged `late` for the sweep | proposed | the 09:30–09:45 candle is the first confirmable 15m bar |
| D13 | Premium hard stop: `techniques.team2.premium_stop_pct = 25` (author: ~20% on 0DTE, P1) as the cap under the candle rule; the existing runner premium-stop watch does this | proposed | sweep 20/25/35 |
| D14 | Daily risk discipline (P7): after a winning trade the next trade's $ risk ≤ half the day's realised P&L; never size up intraday | proposed | fits `size_multiplier` + per-arm loss halt |
| D7 | Tolerance for "touch" (Q5): PDH/PDL use their own zone; PMH/PML lines ±0.25×ATR(2m,14) | proposed | |
| D8 | EMA continuity (Q6): EMA state carries across sessions incl. 04:00–09:30 and 16:00–20:00 bars, exactly like a TradingView 2m chart with extended hours on | proposed | verify against one screenshot from the author |
| D9 | Pullback count (Q7): the first two EMA13 touches after confirmation; a third is watch-only | proposed | |
| D10 | Bias invalidation (Q8): a 15m close back through the zone in the other direction flips the scenario; the plan re-plans, never re-fires the old side | proposed | |
| D11 | No overnight holds — session technique like EM; flatten at 16:05 | firm | |
| D12 | Shorts are puts only (platform never-list) | firm | |

## 3. Build phases

### P0 — Data the method needs (engine, technique-agnostic)
- [x] **Feasibility probed 2026-09-03**: Yahoo v8 chart with `includePrePost=true` returns 1m bars
      04:00 → 19:59 ET for SPY / QQQ / IWM (≈ 940 bars/day; ≈ 260–330 pre-market bars) in both the `1d`
      and `5d` ranges, so PMH/PML and extended-hours EMA warm-up need no new vendor. Same-day check:
      SPY PMH 767.78 / PML 763.59, matching the "766 was a major level" chatter on the author's feed.
      Yahoo 1m depth stays ≈ 20 days (8 days/request) — the bars table must persist them nightly.
- [x] **Extended-hours bars**: fetch 04:00–20:00 ET 1m bars for the Team2 universe (Yahoo `includePrePost`, **← built 2026-09-03: `history.fetch_window(session="ext")`, nightly `research.ext_bars` job 20:10 ET**
      Alpaca full tape) into the bars table with a `session` tag (pre / rth / post); EM's detectors keep
      reading RTH-only through the existing helpers (`_rth_only` stays default). PLATFORM-RULES entry.
- [x] **Aggregation**: 1m → 2m / 5m / 15m closed bars (pure function in `marketstructure`), ET-aligned **← built 2026-09-03: `marketstructure/aggregate.py`**
      (2m bars start at :30, :32 …; 15m at :30, :45 …).
- [x] **EMA series** helper (`marketstructure/indicators.py`: `ema_series`, stack order, fan width = **← built 2026-09-03: `marketstructure/indicators.py`**
      (EMA13−EMA200)/ATR) — pure, picklable.
- [x] **PDH/PDL zones** (`marketstructure/levels.py`: `prior_day_zones(bars15m)` → wick → next body) and **← built 2026-09-03: `marketstructure/dailylevels.py`**
      **PMH/PML** (`premarket_range(bars1m, date)`), both parameterised by a `MarketRules` value.
- [x] Tests: aggregation alignment, EMA vs a reference implementation, zone construction on a **← built 2026-09-03: `tests/test_marketstructure_extended.py` (synthetic fixtures)**
      fixture week (IWM Nov-2022 example from the author's thread if bars are still fetchable, else a synthetic).

### P1 — Team2 market read (pure, replayable)
- [x] `Team2Rules(MarketRules)`: zone rule, PM tolerance, EMA periods, fan thresholds, confirm timeframe, **← built 2026-09-03: `techniques/team2/rules.py`**
      pullback count, stop timeframe, entry window — `rules()` snapshot goes into every plan run.
- [x] Regime reader: per 2m close → `{stack: bull|bear|mixed, fan: chop|trend, above200: bool}`. **← built 2026-09-03: `techniques/team2/regime.py`**
- [x] Scenario reader: per 15m close vs PDH/PDL zones → scenario 1–4 / none, with the flip rule (D10). **← built 2026-09-03: `techniques/team2/scenario.py`**
- [x] **Trigger kinds** in `TriggerTracker` (shared code, direction-aware, mirrored for shorts): **← built 2026-09-03: implemented as the pure `techniques/team2/session.py` walk (EMA13 pullback, level retest, scenario/PM-break setups) instead of inside `TriggerTracker`, whose 1m volume/gap machinery does not fit; parity = the same function live and in replay**
      `confirmed_break_pullback` (15m close beyond level → observed → 2m EMA13/level touch that holds →
      fired), `level_retest` (break then retest of the level itself), `zone_bounce` / `zone_reject`
      (range-day scenarios, gated by regime). Existing kinds untouched.
- [x] `simulate_plan` parity for the new kinds (exit on 2m close through EMA13 / level, trim at new high). **← built 2026-09-03: `session.simulate_session` is the single evaluator; the `now_ms` truncation test asserts prefix equality**
- [x] Tests: the four scenarios on synthetic days; a confirmed break with a failed pullback; the 15m **← built 2026-09-03: `tests/test_team2_session.py`**
      sweep-then-close case; long/short mirror equality.

### P2 — Plans, outcomes, walk-forward (research surface)
- [x] `techniques/team2/plan.py`: `build_session_plan(symbol, date, *, reference_price=None)` — nightly **← built 2026-09-03: `build_skeleton` + `complete_plan`**
      skeleton (PDH/PDL zones, targets = last pivots outside the range, scenario table) + pre-open
      completion (PMH/PML, gap read, sizing bucket, final triggers).
- [x] Runs minted with `technique="team2"`, `result.trace` (one `vp.note` per decision), `config` **← built 2026-09-03: `Team2Service.mint_plan_run` (config.thresholds snapshot, result.plan + trace)**
      (rules snapshot, prompt/code versions), bars snapshot for replay.
- [x] Outcome scoring through the shared `outcome.simulate_plan` path (same evaluator live and replay). **← built 2026-09-03: Team2 scores in PREMIUM terms via `session.simulate_session` (E8); the shared R-based scorer does not apply**
- [x] Walk-forward sweep: `technique_review sweep --technique team2 --start A --end B [--set k=v]` over **← built 2026-09-03: `Team2Service.sweep` + `POST /api/team2/sweep` + `tools/team2_sweep.py` (variants via `overrides`)**
      SPY/QQQ/IWM; `sweep-compare`. First run: 60 sessions, report per scenario × entry kind × window.
- [ ] Decide D3–D10 from the sweep, log in `TRADING-RULES.md`.

### P3 — Runner + UI (alert mode first)
- [x] `TechniqueInfo(id="team2")` registered; `techniques/team2/runner.py::Team2Runner(PlanRunner)` with the **← built 2026-09-03: `techniques/base.py`, `techniques/team2/runner.py` (hooks + bar-loop override), attached in the lifespan**
      hooks (`rules`, `load_plan`, `analyze_fire`, `pick_contract`, `entry_limit_cap`, `size_multiplier`
      = D4 buckets, `preopen_due/preopen_check` = the 09:25 completion, `plan_horizon` = 1 session).
      Attach registers `engine.plan_runners["team2"]` **and** `engine.techniques["team2"]`.
- [x] Scheduler: `team2_plan_nightly` (17:00 ET) and the 09:25 pre-open completion; journaled. **← built 2026-09-03: registered in `attach_team2_runner`; `Team2Service.nightly_plans` / `preopen_complete`**
- [x] Settings in `settings_service.DEFAULTS` under `techniques.team2.*` (symbols, mode, windows, **← built 2026-09-03**
      contract policy, size buckets, exit ladder, fan thresholds) — UI-editable.
- [x] UI: `pages/Team2Page.tsx` from the registry (tabs: Plans · Armed · History · Validation), phone **← built 2026-09-03: Plans · Armed · History · Validation; nav + route + tabs registered**
      "Now" summary via the shared armed hub. Underline tabs, one-line rows, everything links to its run.
- [ ] Journal contracts for any new event kind (`events_contract.py`), PLATFORM-RULES §4 note.
- [x] Tests: sim-broker rig arms a Team2 plan, fires on a synthetic confirmed break + pullback, exits **← built 2026-09-03: `tests/test_team2_runner.py` (alert-mode fire, pre-open completion, audit, expiry, replay parity, sweep)**
      on the EMA close; restart mid-session restores; kill switch honoured; pause stops new fires only.

### P4 — Review loop (the desk's own)
- [ ] `technique_review` CLI works for `--technique team2` (dump / score / review / diff / replay /
      counterfactual) — generic where it already is, Team2 prompt + rubric where it is not.
- [ ] A `/team2-review` skill mirroring `/technique-review`: replay what the pipeline saw, why each
      step happened, what price did, classify root cause (data / rule / threshold / expression /
      execution), plan the fix. Findings land in `TRADING-RULES.md`.
- [ ] Nightly soak line in the morning desk report (`zargar/desk.py`) for Team2: plans built, fires,
      misses, needs-attention.

### P5 — Arming for money (proposal → auto → practice soak)
- [ ] Proposal mode on the practice portfolio for ≥ 10 sessions; execution scorecard; F-findings.
- [ ] Auto mode gated exactly like EM: loss halt per arm, `allow_live_auto`, per-arm ack, RiskGate
      caps per technique/tag, phone exit-only.
- [ ] Alpaca-paper pass, then the practice soak calendar (PRE-LIVE-PROFILE limits).

### P6 — Evolution (the loop that keeps it honest)
- [ ] Variant sweeps (`--set`) as the only way a threshold changes; `TRADING-RULES.md` change log with
      the sweep id for every change.
- [ ] Ingestion of the author's new X threads/recaps into `notes/x/` (manual capture recipe in
      README; automate later if the feed keeps teaching) — never routes through Tip's intake.
- [ ] Shadow-instance sibling runs for rule variants once the harness exists (reuse EM's evolution
      harness if it is technique-agnostic by then; otherwise keep it in the sweep).

## 3b. Enrich the engine, do not fork it — the engine work list (decided 2026-09-03)

**Why not a new engine.** Everything money-related the method needs already exists and is
battle-tested: `RiskGate`, `OrderManager`, `PlanRunner` (arm/fire/critic/exits/loss halt/quote
stop/**premium stop**/failed-exit watchdog/audit/restart recovery), risk-based sizing, the
options pick + reprice path, journal contracts, walk-forward + outcome scoring, the Armed hub and
the phone view. A second engine would re-implement the parts that took the longest to make
safe. What the method needs that the engine lacks is DATA and READS, which are exactly the
technique-agnostic layers (`marketstructure/`, bars, RiskGate policy) the platform rules say to
extend. Every item below is a shared-engine diff, kept small, `rt()`-resolved, and logged in
`PLATFORM-RULES.md`; nothing in EM's `zargar/technique/` changes.

| # | Engine gap | Where | Change | Why Team2 needs it |
|---|---|---|---|---|
| E1 | **Extended-hours bars** | `marketstructure/history.py` (`_rth_only`, Yahoo `includePrePost=false`), `brokers/yahoo.py` (already supports the flag), bars table (`models.py:163`) | `fetch(…, session="rth"|"ext")`; persist 04:00–20:00 1m bars for `techniques.team2.symbols` nightly + intraday; RTH-only stays the default so EM detectors are untouched | PMH/PML (L2), EMA warm-up with ext hours (E1/Q6) |
| E2 | **Timeframe aggregation** 1m → 2m/5m/15m, ET-aligned | new `marketstructure/aggregate.py` (pure) | closed-bar aggregation with session boundaries; 15m bars start :30/:45 | C1 15m close, T1 2m entries, C5 5m flags |
| E3 | **EMA series + stack/fan read** | new `marketstructure/indicators.py` (pure; `guards.ema()` is single-value) | `ema_series`, `ema_stack(13,48,200)`, `fan_width`, carry-over state across sessions | E1–E5 |
| E4 | **Prior-day zones + PM range** | `marketstructure/levels.py` | `prior_day_zones(bars15m)` (wick → next candle body), `premarket_range(bars1m)` | L1.2, L2.1 |
| E5 | **Trigger kinds** `confirmed_break_pullback`, `level_retest`, `zone_bounce/reject` | `marketstructure/tracker.py` (+ `outcome.simulate_plan` parity) | 15m-close confirmation state → 2m pullback that holds → fire; direction-aware mirrors; no gap rules | T1, T2, L4 |
| E6 | **Per-technique 0DTE policy in RiskGate** | `risk.py:445-471` (hard-coded `enhanced_market` / tip lotto) | `techniques.<id>.zero_dte.*` policy table; Team2 path: entry-day expiry, flatten time, contract/premium caps; manual `risk.allow_0dte` unchanged | D3 |
| E7 | **Premium-targeted strike** | `technique/options.py::select_contract` (just-OTM) → add a `target_premium` mode in the shared picker | first OTM strike whose ask ≤ target, floor 0.20, spread/delta warnings kept | V1/F5 |
| E8 | **Premium-path outcome simulation for 0DTE** | `execution/simulate.py` (`premiumPathSimulated: false`), `technique/outcome.py` | Black–Scholes intraday re-pricing (bs_price/implied_vol exist in `technique/options.py`) of the picked contract along the underlying path, with theta to expiry; stamp `premiumPathSimulated: true` | F1: scoring in R of the underlying misrepresents a $0.50 0DTE |
| E9 | **Premium-% exit ladder** | `execution/policies.py` / `exits.py` (ladders are price-based today) | ladder rungs in premium % (+50/+100) with price-event cues (new HOD/LOD), plus the existing 13-EMA-close trail and a price target rung; premium hard stop −25% (already `premium_stop_pct`) | X1–X3, D5, D13 |
| E10 | **Session-aware sizing buckets** | `PlanRunner.size_multiplier` hook (exists) + a `daily_risk_after_win` knob | full/small/none by location; shrink after a win | V6, D4, D14 |
| E11 | **Pre-open completion of a plan** | `PlanRunner.preopen_check` / `build_replacement_plan` hooks (exist) | at 09:25 add PMH/PML, gap read, sizing bucket, final triggers | §1 flow |
| E12 | **Registry + UI page** | `techniques/base.py`, `frontend` nav from `GET /api/techniques` | `TechniqueInfo(id="team2")`, `Team2Page` (Plans · Armed · History · Validation) | D1 |

Sequence: **E1→E4** first (pure data + reads, fully testable offline), then **E5 + E8** (the
tracker and the scorer must ship together for parity), then the walk-forward sweep (P2) to
decide D4–D14, then **E6/E7/E9/E10/E11/E12** (money path, alert mode) — P3 onwards.

## 3c. Completeness review before the build (2026-09-03)

Audited the plan against (a) every rule in `METHOD.md`, (b) what EM and Tips needed before they
could arm nightly (`BUILDING-A-TECHNIQUE.md`, `WALKFORWARD-PLAN.md` §9, `POST-SOAK-BUILD-PLAN.md`,
`PRE-LIVE-PROFILE.md`), and (c) 0DTE execution realism. Items below were MISSING or under-specified
and are now part of the plan; each carries the phase it belongs to.

**A. Method rules not yet mapped to a build item**
- [x] A1 (P2) **Day-type classifier** at 09:25: gap day (open outside PDH–PDL → PM range is the first **← built 2026-09-03: `scenario.classify_day`**
      read, L2.4), inside day (open inside → PM-range break decides, L2.5), normal. Drives which
      triggers the plan arms first.
- [x] A2 (P1) **Target discovery** (L3.1): last pivot high above PDH / last pivot low below PDL from **← built 2026-09-03: `levels.targets_beyond` (the running HOD/LOD target: not yet)**
      the 15m history (`find_pivots` exists); intraday HOD/LOD as the running target until it breaks
      (image 1961977216818163982). Range-day targets = opposite side of yesterday's range.
- [x] A3 (P1) **Zone + EMA agreement gate** (B9): no entry unless price is beyond the zone AND on the **← built 2026-09-03: stack must agree; flip only on a 15m close**
      right side of the EMA stack; bias flip only on a 15m close through the zone the other way (D10).
- [x] A4 (P1) **Range-day extra confirmation** (B3): scenarios 2/3 require one of PM-level break, **← built 2026-09-03: PM level on the trade's side**
      EMA cross, or a 5m flag before a fire; scenarios 1/4 do not.
- [ ] A5 (P1) **5m flag detector** (C2/C5) — a counter-trend channel after an impulse; `detect_wedge`
      is the nearest existing primitive. Flag BREAK is an entry cue of its own (V0).
- [x] A6 (P1) **Pullback-quality gate** (F4): the pullback into the EMA must be an even drift (≤ N 2m **← built 2026-09-03: body ≤ k×avg body**
      bars, bodies ≤ k×avg body), not a single engulfing candle; replayable with the gate off.
- [ ] A7 (P1) **Trend-continuation read** (B8): a PDL break in an existing downtrend is continuation
      (no dip-buying until a higher high); tag plans with `continuation|reversal`.
- [x] A8 (P3) **Re-entry policy** (T5/V5): after a stop the same trigger re-arms for up to **← built 2026-09-03: `max_reentries` per setup**
      `max_reentries` (default 2) while the scenario holds; PlanRunner's re-arming exists — wire the
      cap and journal each re-arm.
- [x] A9 (P3) **Third-touch rule** (P6/D9): touches beyond the second are watch-only; journal them as **← built 2026-09-03: `late_touch` events**
      `late_touch` so the sweep can measure what they would have paid.
- [ ] A10 (P3, optional) **Scale-in** to an average ("loaded up with .50 average", V0): reuse Tip's
      scale-in ladder machinery; off by default.
- [ ] A11 (P1) **Intraday zones** (L3.4): early-session S/R inside the larger zones, used later in
      the day — lower priority, behind a knob.
- [x] A12 (P3) **Concurrency**: SPY/QQQ/IWM fire together on index moves; `max_concurrent_positions` **← built 2026-09-03: one position at a time inside the read**
      (default 1) and correlated-exposure cap per technique.

**B. Data and backtest realism (the sweep is only as honest as this)**
- [x] B1 (P0, DO FIRST) **Start persisting extended-hours 1m bars for the three symbols tonight.** **← built 2026-09-03: `research.ext_bars` job; the bank starts the first night the app runs this build**
      Yahoo keeps ≈ 20 sessions of 1m; a 60-session sweep is impossible unless we bank bars from
      now. Nightly job + backfill of the 20 days available.
- [x] B2 (P0) **Historical option premiums do not exist for us** → E8's Black–Scholes premium path **← built 2026-09-03: `premium.PremiumModel`; `^VIX`/`^VIX1D`/`^VIX9D` daily job**
      needs an IV input: nightly per-contract IV from `option_chain_snapshots` (exists, CBOE) as the
      day's base, intraday scaled by a VIX proxy. **Fetch `^VIX` (and `^VIX1D` for 0DTE) daily bars
      from Yahoo** — trivial, not built (`grep ^VIX` → nothing).
- [x] B3 (P2) **Calibrate the premium model on the author's 9 documented trades** (METHOD §7b: entry **← built 2026-09-03: `test_premium_model_calibrates_to_the_authors_trades` — 4 trades with full data, model 12–45% optimistic (F8); the remaining 5 lack an entry premium**
      time/price/premium and exit time/premium are known for several) — the model must reproduce
      +122% on SPY 711c 10:10→10:46, +166% on QQQ 472p, etc., within tolerance before any sweep
      result is believed. This is the acceptance test for E8.
- [x] B4 (P0) **Fees in the simulator**: `options.fee_per_contract` 0.99 USD + `sim.reg_fee_per_contract` **← built 2026-09-03: `fee_per_contract` 1.04 + one tick slippage each way**
      0.05 → ≈ $1.04/contract/side = **≈ 2% of a $0.50 contract each way**; slippage model = pay the
      ask, sell the bid, plus one tick. Both must be in the premium-path scorer.
- [x] B5 (P0) **Session calendar**: holidays and **early-close days (13:00)** are not modelled **← built 2026-09-03: `marketstructure/market_calendar.py`; `sessions.session_bounds` / `next_session_date` honour it**
      (`sessions.py`); PDH/PDL and the flatten time must respect them. Add an ET market calendar.
- [x] B6 (P0) **Bar integrity checks** for extended hours: pre-market 1m bars are sparse/gappy (a **← built 2026-09-03: wall-clock buckets in `aggregate.py`**
      missing minute must not shift the 2m/15m grid); define aggregation on wall-clock buckets.
- [x] B7 (P2) **Include-invalid replay** for every new gate (15m close, EMA agreement, pullback **← built 2026-09-03: as sweep variants (`overrides`), not a plan-side `valid` flag**
      quality, range-day confirmation, third touch) so each gate's value is measurable.

**C. 0DTE execution realism**
- [ ] C1 (P3) **Live option quotes**: CBOE is 15-min delayed — unusable for a $0.50 0DTE contract.
      Alpaca OPRA real-time quotes exist (`options/service.py`, `options.quotes_source=alpaca`); Team2
      MUST refuse to fire without a fresh OPRA quote (staleness ≤ 5 s) — journal `quote_stale` skips.
- [ ] C2 (P3) **Fill path latency**: SnapTrade orders + polled fills (~1/s) against 2-minute candles.
      Measure entry→fill latency in the execution scorecard from day one; never-chase cap = the
      author's own rule (entry at the level, `entry_limit_cap` = ask + 1 tick).
- [ ] C3 (P3) **Flatten discipline**: all Team2 positions closed by `flatten_et` (15:45) — market
      order retry path exists (failed-exit watchdog); expiry settlement handling exists (2026-09-02)
      but must never be needed.
- [ ] C4 (P3) **Contract selection at fire time** needs the live chain (strikes/asks) within seconds:
      cache the day's 0DTE chain at 09:25 and re-price the candidate strikes with OPRA at fire.
- [ ] C5 (P5) **Venue check**: Webull CA (SnapTrade) 0DTE index-ETF options — confirmed tradable
      (`snaptrade_options_check` 2026-08-21) but the practice soak must measure fill quality; Alpaca
      paper (day-TIF) is the paper venue.

**D. Risk and safety (what the never-list opening must NOT weaken)**
- [x] D-1 (P3) **Per-technique 0DTE policy** (E6) with: entry-day expiry only, `flatten_et`, no new **← built 2026-09-03: `risk.py` + `techniques.team2.zero_dte`**
      entries after `last_entry_et` (15:30), per-order and per-day contract caps, premium cap per
      trade, daily loss halt per technique, kill switch honoured. Manual `risk.allow_0dte` unchanged.
- [ ] D-2 (P3) **Existing per-order caps** (`risk.max_option_contracts` 10, `risk.max_option_premium_notional`
      $1,000, 5% of equity) sit BELOW the author's full size (~48 contracts / $2.6k): Team2 starts
      inside the platform caps (practice) — raising them is a PRE-LIVE-PROFILE decision, not a default.
- [x] D-3 (P3) **Daily risk discipline** (D14) as a runner rule: after a win, next-trade risk ≤ half **← built 2026-09-03: `max_losses_per_day`, shrink-after-win inside the read**
      the day's realised P&L; after N losses (`max_losses_per_day`, default 2) stop for the day.
- [x] D-4 (P3) **Event days**: macro calendar (FOMC/CPI/NFP) — the author trades through but names **← built 2026-09-03: placeholder `research/macro_calendar.py` (`engine.macro`, manual list) → plan flag `eventDay`; the read skips entries when `avoid_event_days` is on (`skip_event_day` event)**
      them as chop; knob `avoid_event_days` (default off in practice, on for live until proven).
      Needs a macro calendar source (not built; EventCalendar is earnings-only).
- [ ] D-5 (P3) **Mobile exit-only + phone_entry_blocked** apply unchanged; HALT visible.

**E. Operations — "arm items every night"**
- [x] E-1 (P3) Nightly job 17:00 ET: PDH/PDL zones + scenario table + targets → plan skeleton per **← built 2026-09-03: skeleton + 09:25 completion; restore inherits PlanRunner**
      symbol, journaled; morning 09:25 completion (PMH/PML, day type, sizing bucket, final triggers);
      restore/boot-roll after a restart (runner core does this — verify with a restart test).
- [ ] E-2 (P3) Alert mode first (Telegram/push/toast through `PlanRunner._alert`), then proposal,
      then auto — the same earned ladder as EM; `needsAttention` surfaced on the Armed page.
- [x] E-3 (P3) Morning desk report line (`zargar/desk.py` 08:25) and nightly soak line for Team2. **← 2026-09-03: the report aggregates `engine.plan_runners` (armed/paused/inTrade per technique), so Team2 is counted; a Team2-specific line (sheet + last read) is still to add**
- [x] E-4 (P3) Armed "Now" phone summary via the shared armed hub (register in `engine.plan_runners`). **← 2026-09-04: `Team2Runner._snapshot` gives the Armed page pseudo-triggers (the zones being watched, then the live setups) and a summary in the method's words; a "How Team2 works" section sits on the Team2 page**
- [ ] E-5 (P4) Nightly outcome scoring + scorecard per scenario × entry kind × time bucket.

**F. Review and evolution loop (the desk's own)**
- [x] F-1 (P2) Every plan run carries `result.trace` with a `vp.note` per decision (day type, zone **← built 2026-09-03: `session.events` (one prose reason per decision) + the plan sheet**
      math, scenario, EMA read, confirmation, pullback quality, contract pick with the chain rows seen,
      premium at fire) and `config` (rules snapshot, code/prompt versions, bars asset id).
- [ ] F-2 (P4) `technique_review` generic over `--technique team2` (dump/score/review/diff/replay/
      counterfactual); `/team2-review` skill; findings → `TRADING-RULES.md`.
- [ ] F-3 (P4) Bug-missed trades → counterfactual ledger, never a synthetic fill (platform invariant).
- [ ] F-4 (P6) **Ongoing source capture**: the author posts recaps daily; a weekly manual pass with the
      capture recipe (README) + `fetch_tweet_media.py`; automate later only via ToS-clean means (the
      public status pages / syndication endpoint), never a self-bot. New rules → METHOD version bump.
- [ ] F-5 (P6) Variant sweeps are the only path to a threshold change; each change cites its sweep id.

**G. UI and settings**
- [x] G-1 (P3) Settings "Team2 technique" panel (like Tips): **← built 2026-09-03 (`SettingsPage.tsx`)** — symbols, mode, zero_dte policy, target
      premium, size buckets, exit ladder, fan thresholds, windows, max reentries, concurrency.
- [x] G-2 (P3) `Team2Page` from the registry: Plans (tonight's skeleton + 09:25 completion, the **← built 2026-09-03: phone layout + `mobile-audit` still to run**
      one-level/one-direction/one-target line per symbol, V9), Armed, History (runs, outcomes),
      Validation (sweep, calibration vs the author's trades). Underline tabs, one-line rows, links
      to the run/journal; phone layout via `mobile.css` only; `npm run mobile-audit` gate.
- [ ] G-3 (P3) Changelog entry + version bump (four places) on every user-visible step.

**H. Process**
- [x] H-1 Parallel-session safety: own test DB on :5433 (`ZARGAR_TEST_DATABASE_URL=…/zargar_test_team2`). **← built 2026-09-03: `zargar_test_team2` on :5433**
- [ ] H-2 Check `git log` for the other team's merges each session before touching shared files;
      PLATFORM-RULES entry for every shared-engine diff (E1–E12).
- [x] H-3 Docs touched when built: `CLAUDE.md` pointer, `ARCHITECTURE.md` (ext-hours bars, aggregation), **← built 2026-09-03: PLATFORM-RULES entry written; ARCHITECTURE / BUILDING-A-TECHNIQUE / CLAUDE.md updated**
      `PLATFORM-RULES.md` (0DTE policy table, new trigger kinds), `BUILDING-A-TECHNIQUE.md` (new
      primitives available to all techniques).

## 4. Testing bar (from BUILDING-A-TECHNIQUE §6, made concrete)

- Live tracker ≡ replay (`simulate_plan`) on every fixture; rules snapshot in every plan run.
- Every gate replayable with the gate off (`include_invalid`) so its value is measurable.
- `tests/test_platform_phase0.py` / `_phase3.py` / `test_platform_separation.py` untouched and green.
- No real money until P5's soak; no overnight ever (D11).

## 5. Open items

- Whether the desk gets its own morning push line before P4 (cheap; do with P3).
- Whether to persist the author's chart images (vision reads) for the Q1/Q2 answers if the
  transcripts do not settle them.
