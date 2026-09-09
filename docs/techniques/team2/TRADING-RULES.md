# Team2 technique — judgement log

*The METHOD (`METHOD.md`) is what the author says; this file is what WE have learned about it —
findings, open questions with decision thresholds, theories, and the change log of every rule or
parameter change, each dated and citing its run / scorecard / sweep. Engine-level lessons go to
`docs/PLATFORM-RULES.md` instead. Opened 2026-09-03; nothing has run yet.*

## Rules under observation

| Rule | Current value | Question | Decides it | Status |
|---|---|---|---|---|
| Q1 contract | **0DTE, strike by premium ≈ $0.50–0.60 (decided, D3)** | Would 1DTE survive as a variant? Does the $0.50 strike beat the first-OTM strike? | sweep with the premium-path scorer (E8): 0DTE-$0.50 vs 0DTE-first-OTM vs 1DTE | decided 2026-09-03; variants open |
| Q2 size buckets | 1.0 / 0.5 / 0 | Is the middle bucket worth trading at all? | sweep expectancy per bucket, ≥ 60 sessions | open |
| Q3 exit ladder | 50% at new-high push, runner on EMA13 close | Does the runner add R after costs? | sweep 30/50/70 + no-runner | open |
| Q4 entry window | 09:45–15:30 | Are post-noon fires net positive with 0–1 DTE decay? | per-window expectancy | open |
| Q5 PM tolerance | ±0.25 ATR(2m) | Retest hit-rate vs false touches | touch-count audit on replay rows | open |
| C1 15m close | required | How many valid fires does the 15m rule cost vs how many fakeouts it saves? | replay with the gate off (`include_invalid`) | open |
| D9 pullback count | first two | Third touches: return or noise? | sweep 1/2/3 | open |

## Findings

- **F1 (2026-09-03, images)** The author's vehicle is **0DTE, 1–2 strikes OTM, $0.20–$0.60 premium**
  in every recap found (5 trades, 2024–2026; METHOD §7b). Consequence: the method's stated
  win rates are on lottery-priced contracts where a one-candle stop is −20–40% and a trend day
  is +400%; our outcome scoring must simulate the PREMIUM path (theta + gamma on 0DTE), not the
  underlying's R — `simulate_position` stamps `premiumPathSimulated: false`, which is not good
  enough here. Open: 0DTE is on the platform never-list for non-EM techniques (user decision).
- **F2 (2026-09-03, images)** The sizing guide is three buckets keyed to the 15m map (full beyond
  the PDH/PDL zones, small between the prior-day zone and the PM level, none inside the PM range).
- **F3 (2026-09-03, images)** Exits are quoted in premium %: +50% / +100% trims, "sold when it went
  ITM", runners on the 13 EMA. The first trim's cue is the new high/low of day, i.e. a PRICE event —
  so the ladder can be expressed as price-triggered with premium-% telemetry.
- **F5 (2026-09-03, images)** Strike is chosen by PREMIUM, not distance: entry asks cluster at
  $0.50–0.60 (SPY/QQQ) and $0.20 (IWM) while OTM distance ranges 0.3–1.8%. Expression policy
  candidate: `strike = first OTM strike with ask ≤ techniques.team2.target_premium` (default 0.60),
  with a floor so we never buy the $0.05 lottery. A full-size position ≈ $2.6k premium (~48
  contracts) in one recap — our `budget_per_trade` scale, not a per-contract count.
- **F6 (2026-09-03, images)** "Sell at target" is literal: the pre-planned next level is an
  outright exit on touch, after earlier trims — the exit ladder ends with a price target, not only
  the EMA trail.
- **F7 (2026-09-03, podcast 2023)** Hard premium stop ≈ **−20%** on 0DTE ("the sweet spot"), on top
  of the candle rule; no time-of-day gate (pre-10:00 flagged riskier); 2–5 trades/day; the FIRST
  13 EMA pullback after the break is "where most of my money is made", the third is the trap.
  Daily risk discipline: shrink $ risk after a win so one loss cannot erase the day.
- **F4 (2026-09-03, video 2022)** "We buy pullbacks, we don't buy breakouts." An extended entry
  (large engulfing candle into the EMA) is explicitly the bad entry; the good one is an even,
  flag-like drift into the EMA. Candidate gate: pullback slope / body-size filter on the 2m bars.

- **F10 (2026-09-04, second image pass)** Three entry mechanics the text never spelled out: (a) **break & base** —
  the entry is the tight base just beyond the level, no EMA dip needed (T7); (b) the **200 EMA flush** as the
  range-day trigger, with the pre-market level as the final target (T8); (c) the **48 EMA** as a valid second dip
  (E5 was already in the text; the IWM 3-entry image shows entry 2 on the 48 after entry 1 on the 13 failed).
  All three are in `session.py` now (`entry_kind` ema/ema48/level/base/ema200) with the stop on the line each
  leaned on. **Trim-and-add** (X5) and averaging into a base (X6) are recorded, not built (A10).
- **F11 (2026-09-04)** The "new high/low of day" trim cue (X1) is now selectable (`trim_cue=new_extreme`) next to the
  premium-% cue so the sweep can compare the two; and `pullback_max_bars` finally does something: a dip that sits on
  the wrong side of the EMA13 for longer than N bars is called a consolidation (`pullback_stalled`).

- **F12 (2026-09-04, market watch)** A plan run's `config.thresholds` were frozen when the plan was
  MINTED (17:00 the night before), but the live runner always reads `rules_from_settings`. The three
  plans armed for 2026-09-04 carry `entry_at: "ema"` — the value before the second review (abe9baa)
  changed the default to `"both"` — and are missing the nine knobs added since (`allow_ema48_entries`,
  `allow_ema200_flush`, `base_bars`, `base_tol_atr`, `trim_cue`, `hod_target`, `hod_target_min_atr`,
  `add_on_retest`, `max_adds`). Consequence: `POST /api/team2/runs/{id}/replay` runs a DIFFERENT method
  than the desk did, so the replay-parity check reports phantom mismatches and any review of the run
  understates what was traded. No trading impact — the live path was always on the current rules.
  Fixed by `Team2Service.stamp_run()` (below); today's three runs were minted before the fix, so
  their replays stay divergent for 2026-09-04 only.
- **F13 (2026-09-04, market watch)** The COMPLETED plan (PMH/PML, `dayType`, `openPrice`,
  `sizingAtOpen`) only ever lived in the armer's memory and in `technique_armed.state` — it was never
  written back to `technique_runs.result.plan`. `replay()` therefore re-derived it with
  `complete_plan(plan, today)` against whatever bars existed at replay time. Before 09:30 that
  reproduces the live read; **after the open it does not** — `complete_plan` prefers the 09:30 RTH
  open over the 09:25 pre-market last price (`openSource` flips `premarket_last` → `rth_open`), and
  the pre-market range gains its last five minutes. Both feed `classify_day` and `sizing_bucket`, so
  a mid-day replay can show a different day type and a different sizing bucket than the desk traded.
  This is the more consequential half of F12: it silently rewrites the day's premise. Fixed the same way.
- **F14 (2026-09-04, market watch)** Team2's never-chase cap (`Team2Runner.entry_limit_cap` = the
  contract's `ask + tick`, T6/C2) can never bind. The shared fire chain re-prices the picked contract
  on the live NBBO (`OptionsService.reprice` mutates the dict in place) and *then* asks the hook for
  the cap, so both the limit and the cap are computed from the SAME repriced ask: `cap = limit + 0.01`
  by construction, and the `entry_capped` branch is unreachable for this technique. Practically the
  entry still cannot be filled above the current ask, so nothing is over-paid at the moment of the
  order — but the method's actual intent (don't pay up for a contract that has already run past the
  $0.20–$0.60 band, F1/F5) is unenforced: a strike picked at $0.55 on the ~15-min delayed CBOE chain
  can be re-priced to $1.20 on OPRA and still be bought, at half the contracts. Behaviour change →
  proposed, not built (see the run log 09:32 ET).
- **F15 (2026-09-04, market watch — BUILT 13:30 ET, see change log)** Gap days trade the PM range in the book (L2.4: "on gap days the
  PM range is the first thing watched for direction — a 15m close outside it, then the first 13 EMA
  dip"), but two pieces of code disagree with that on a gap day: (a) `sizing_bucket` tests
  `price > pdh.top` BEFORE the pre-market no-trade zone, so on a gap-up day every price above the PDH
  zone is "full" size even when it sits inside the pre-market range (V6 calls that range chop); and
  (b) the `pm_break_up` / `pm_break_down` setups in `session.py` are guarded by
  `close <= zones["pdh"].top` / `close >= zones["pdl"].bottom`, which is the L2.5 *inside-day* case —
  so on a gap day the PM level never becomes a setup at all. Live example: QQQ 2026-09-04 opened at
  719.35, gap-up over the 718.60–718.91 PDH zone but INSIDE the 717.13–722.06 pre-market range; the
  armed plan's only triggers are the PDH/PDL breaks, and a 15m close over 718.91 would arm full-size
  13-EMA entries in the middle of the pre-market range. The downside case is the sharper one: a
  gap-day reversal through PML 717.13 has no setup until PDL 709.69, ten points lower. Behaviour
  change → proposed, not built.
  **Confirmed live at 10:02 ET** and sharper than first written. QQQ fired scenario 1 touch #1 at spot
  721.44 — inside PM 717.13–722.06, 0.62 under the PMH — with `bucket=full`. The same engine, the same
  minute, skipped IWM's two identical EMA13 touches (294.94 at 09:46, 294.64 at 09:56) with
  `skip_no_trade_zone` "entry sits inside the pre-market range (V6/B5)". The only discriminator is the
  day type. And it is not a gap-day ambiguity at all — it is a **missing rung**: V6 states a five-step
  ladder ("above the PDH zone = Full · PDH zone→PMH = **Small** · PMH→PML = No trade · PML→PDL zone =
  Small · below the PDL zone = Full"), and `scenario.sizing_bucket` implements only three, returning
  "full" for anything above `pdh.top` and never producing "small" for the PDH-top→PMH band. Whenever
  PMH > PDH top (every gap-up day, and plenty of normal ones) the ladder's second rung is unreachable.
  The literal V6 reading for QQQ at 721.44 is **small**, not full. Fix would be to walk the five rungs
  in price order; still a sizing (money) change → the user's call, but no longer a judgement about what
  the author meant.
- **F16 (2026-09-04, market watch, operational)** The Practice portfolio Team2 is armed to
  (`ff3c29d4`, sim) tripped its daily-loss halt at **09:38 ET** (`KillSwitchEngaged`, auto, "Practice
  at -9.13%, halt at -8.0%") — eight minutes into the session, from other techniques' positions;
  Team2 has no trade and no position today. No impact while Team2 is in `alert` mode, but the kill
  switch is global: if the mode is moved to proposal/auto today, entries are refused (exits only), so
  a day's worth of Team2 practice signals would silently produce no fills. Release is the user's call.
- **F17 (2026-09-04, market watch — FIXED)** F16 turned out to have a *reading* cost too, not just a
  money one: `Team2Runner._fire_from_event` checked the kill switch **before** the mode, so while the
  shared Practice halt was engaged the desk stopped recording its own read of the tape. QQQ's first fire
  of the day (10:02 ET, scenario 1 touch #1, EMA13 720.84 held on a 721.44 close, model call 723 ≈ $0.47)
  was logged as `halt_skip` and produced no `fired` row — while `POST /runs/{id}/replay` over the same
  bars *did* show the fire, so live-vs-replay parity broke as a side effect. Alert mode places nothing
  (`_fire_rest` only sets `trade.status = "alert"`), and the caps immediately below the halt check —
  plus `_add_from_event`'s `would_add` — are already gated to money modes with the comment "money modes
  only; alert/proposal keep recording every read". The halt check was the odd one out. Fixed: the halt
  gate now applies to proposal/auto only; an alert-mode fire during a halt is recorded with
  `haltedAtFire: true` so the audit still says the money path would have refused it.

- **F18 (2026-09-04, market watch)** A **refused** pullback burns the D9 budget. `session.py` does
  `s.touches += 1` (l.425) *before* every skip check, so a touch rejected for sitting in the pre-market
  no-trade zone (`skip_no_trade_zone`, V6/B5) or for being an engulfing lunge (`skip_engulfing`, A6/F4)
  still counts as one of the "first two pullbacks". Live case today: IWM confirmed scenario 3 (bounce
  PDL) on the 09:30–09:45 15m close at 294.79, then the 09:46 (294.94) and 09:56 (294.64) touches were
  correctly refused for the PM range 293.24–295.92 — and every touch since (10:00, 10:32, 10:34, 10:38 =
  #3–#6) is `late_touch`, watch-only. IWM is locked out of its own valid setup for the rest of the day
  without ever having taken a trade; if it now closes above the PMH 295.92 (it printed 295.91 at 10:20)
  the first clean full-size EMA13 pullback is unreachable. The book's rationale for D9 is structural —
  P6: the third bounce is "where the first-dip buyers are stopping out" — which presumes the first two
  dips were *bought*. A skip for location or candle shape means no one bought. **Built the same hour by the
  desk (commit 67c5986):** the no-trade-zone and range-confirmation skips happen before the touch is counted;
  engulfing bars still count (they were pullbacks, just bad bars) — sweep that half separately. Deployed 11:50 ET.

- **F19 (2026-09-04, market watch — shared engine; FIXED by the desk the same day, PLATFORM-RULES 2026-09-04)** `Quote.day_high` /
  `day_low` / `volume` from the Alpaca stream are **since process start**, not session-to-date.
  `brokers/alpaca.py` seeds `{"day_high": 0.0, "day_low": 0.0, "volume": 0}` per process (l.188) and
  only accumulates from live prints (l.212); the Yahoo session context is a `or` fallback (l.253), so
  one tick permanently discards the true session high/low. After today's 10:36 restart the API reported
  SPY dayHigh 771.29 against a real session high of 772.87 (bars), QQQ 719.65 against 721.86, and SPY
  volume 317k at 10:33. **No Team2 impact** — the method's HOD/LOD target (X3b) is computed from the
  bar series in `session.py`, and today's QQQ HOD target 721.86 matches the DB bars exactly; the only
  consumer of `dayHigh` is the frontend quote card. **Proposed:** `max(st["day_high"], ctx.day_high)` /
  `min(...)` instead of `or`, and take session volume from the Yahoo context rather than the tick sum.

- **F20 (2026-09-04, market watch — BUILT 13:30 ET, see change log)** The **PM break-and-retest setups (L2.6 / L2.7) can never take their
  own entry.** `session.py` anchors `pm_break_up` on the PMH and `pm_break_down` on the PML
  (l.251 / l.257), so a level retest resolves `entry_spot = s.anchor = pmh|pml`; `scenario.sizing_bucket`
  then asks `pml <= price <= pmh` **inclusively** and returns `"none"`, and the entry is refused as
  `skip_no_trade_zone`. The book's own words are the opposite: **L2.7** "mark PML, wait for a break ...
  enter puts on the **retest/rejection of PML**, stop just above PML"; **L2.6** is the mirror for the PMH.
  V6/V7's no-trade zone is about sitting *inside* the range, not about the edge you just broke and came
  back to. EMA13/EMA48 entries on the same setup are refused too until the EMA itself has drifted outside
  the range, by which time the retest is long gone — so the setup is effectively dead, not merely rare.
  **Live case today, and it was the trade of the day:** SPY closed the 10:15–10:30 15m candle at 770.30,
  below the PM low 770.50 → `pm_break` fired, target = PDL zone top **769.26**. At 10:44 SPY retested
  770.50 exactly and the desk refused it (`bucket: none`, touch #1). SPY then ran to a session low of
  **769.05** — through the target — and sat at 769.30 at 11:05. Zero trades taken; the read shows
  `trades: 0, setups: 1`. **Not built — sizing is a money rule.** Proposal: exempt a `pm_break_*` setup's
  retest of its own anchor from the V6 gate and size it **small** (V6's PDH-zone→PMH / PML→PDL-zone rung,
  which is exactly where a PM-level retest sits). Same ten lines as [F15]'s five-rung ladder — decide
  them together.

- **F21 (2026-09-04, market watch — log hygiene, no code)** The ET timestamps in the last two *desk*
  entries of `notes/market-watch.md` are ~1h35m ahead of real ET, which makes the run log unusable as a
  chronology. Checks: commit `d778f48` (F19) is authored 07:51:24 -0700 = **10:51 ET** but logged as
  "deployed 12:28 ET"; commit `67c5986`/`489fa81` (F18) at 07:41 PDT = **10:41 ET** is logged as
  "deployed 11:50 ET"; the three plans' `armedAt` after that restart is `07:55:23-07:00` = **10:55 ET**.
  The app's own clock is correct (bars, quotes and `regime.ts` all agree with wall-clock ET), so this is
  a writing error in the log, not a runtime timezone slip. Stamp future sections from the app
  (`regime.ts`) or from `TZ=America/New_York date`, not by hand.

- **F22 (2026-09-04, market watch — FIXED, commit pending)** **The desk's first real order was refused
  by a bug that reads *cash* where it says *equity*.** SPY's `pm_break_down` setup fired at 11:08 ET
  (touch #1, EMA13 769.81 held, close 769.70, bear stack), the contract picker did its job — real OPRA
  quote, `SPY260904P00768000`, bid 0.38 / ask 0.39, spread 2.6%, vol 63,663, delta −0.244, size `small`
  ×0.5 → 26 contracts ≈ $1,014 premium — and the trade was then dropped with
  `contract skipped (premium ≈$1,014 is over 50% of the account's $-267 equity)`. The Practice book's
  equity is **$8,618.40**; **−$266.58 is its cash**, which is negative only because other techniques'
  RKLB calls and ZURA shares are holding the book fully invested. Root cause is one line in the shared
  `execution/planrunner.py` premium pre-check (l.2305): `pf = positions.portfolio(pid)` returns the
  *cached portfolio row* — name / kind / cash / baseCurrency, and **no `equity` key at all** (equity is
  the async `positions.equity(pid)`) — so `float(pf.get("equity") or pf.get("cash") or 0.0)` always
  fell through to cash. The check exists only to *mirror* the RiskGate so the shares fallback can kick
  in before an order is rejected; the authoritative gate (`risk.py` l.263/304) uses
  `await positions.equity(...)` and would have **passed** this order ($1,014 < 50% of $8,618). So the
  pre-check was strictly stricter than the gate it mirrors, and silently so. **Fixed** by awaiting the
  real equity. The model trade would have lost (−12.23%, stopped 11:14 on the 2m close back through the
  EMA13) — the finding is the mechanism, not the P&L. Shared-engine change, logged in `PLATFORM-RULES.md`.
  Two related mismatches are **left alone and proposed only**: (a) the same pre-check has no shadow-book
  exemption, while the RiskGate skips %-of-equity caps for `kind == "shadow"` (2026-09-01 precedent) —
  a shadow book with negative cash is currently blocked from every option entry on this path; (b) nothing
  on this path checks buying power, so a book with real equity but no cash can now be sized into an
  order it could not fund at a real broker. Neither bites Team2 on a sim book.

- **F20 reinforced (2026-09-04 12:00–12:14 ET)** IWM reproduced F20 within the same session: the 11:45–12:00
  15m candle closed above the PM high 295.92 → `pm_break` up, calls to the PDH zone; the 12:14 retest at
  **exactly 295.92** was refused `skip_no_trade_zone`. That is three PM-break setups today (SPY 10:44,
  IWM 12:14, and SPY's own EMA13 touch only entered once the EMA had drifted *below* the range) against
  zero entries taken at the anchor. F20 is not a rare edge — on a range day it is the whole setup class.
  Still **not built**; sizing is a money rule.

  **Further evidence (12:38 ET, same IWM setup).** `pm_break_up@12:00` has now had **four** EMA13 touches
  refused in 34 minutes — 12:14 at 295.92, 12:24 at 295.89, 12:32 and 12:34 at 295.88 — every one of them
  "inside the pre-market range" for the simple reason that the setup's own anchor **is** the PM high and
  price is pulling back to it, which is exactly what L2.7 says to buy. Seven refusals across two symbols
  in one session, still zero entries. IWM has been within 0.05% of 295.92 for over half an hour, so this
  setup will keep generating refusals for as long as the chop lasts.

- **F23 (2026-09-04 12:25 ET, FIXED)** The two "this is not a tradeable location" skips —
  `skip_no_trade_zone` (V6/B5) and `skip_range_confirmation` (B3/A4) — were re-stated on **every** 2m close
  for as long as the condition held. IWM printed 37 identical `skip_no_trade_zone` rows between 09:46 and
  12:14 (SPY and QQQ add more), each one both a read event and a `TechniquePlanTriggerSkipped` row in the
  append-only `events` table, which cannot be pruned later. The signal is one bit ("price is parked in the
  no-trade zone"), so the noise buries the events that matter — F20's refusals, the fires, the exits.
  **Fixed** in `techniques/team2/session.py`: a `note_once` helper keyed on the setup, the same shape as
  the existing `pullback_stalled` dedupe (`s._stalled`); the flag clears the moment a real touch gets past
  the gate, so a later refusal is said again. No decision changes — the gates, counts and the D9 allowance
  are untouched, and replay parity is preserved because both paths run the same code. Regression test:
  `test_no_trade_zone_skip_is_said_once_per_setup` (5 rows → 1 on the fixture).


- **F24 (2026-09-04 12:40 ET, FIXED)** The Armed/Team2 "Now" line reported the D9 touch allowance of the
  WRONG setup. `runner.py` took `max(touches)` over every live setup, while `session.py` enters only the
  **newest live setup in the current bias direction**. SPY at 12:22 ET therefore read "scenario 3 (bounce
  PDL) → calls · touches 1" when scenario_3@11:00 had used none of its two — the 1 belonged to
  pm_break_down@10:30, a spent SHORT setup the bias had already left behind. The touch count is the one
  number a person watching the desk uses to judge whether a setup can still be traded, so reading it high
  makes a live setup look half-spent. **Fixed** by mirroring `session.py`'s selection (newest live setup
  in the bias direction, falling back to the old max when none matches). Display only — no gate, count or
  entry changes. Verified against today's three live reads: SPY 1 → 0, QQQ and IWM unchanged.

- **F25 (2026-09-04 13:00 ET, FIXED 15:00 ET — one clock, see change log)** Read events are stamped with the OPEN time of
  the 2m bar that produced them, while trades and exits are stamped with that bar's CLOSE (`end_ts`).
  Within one read the same entry therefore carries two clocks: IWM's fire event says **12:14** while its
  own trade record says `entryTs` **12:16**, and the fill price (295.96) is the close of the 12:14–12:15
  bar — knowable only at 12:16. Exits are the mirror image and read correctly: the exit stamped **12:28**
  quotes close 295.87, which is the close of the **12:26–12:27** bar (the DB's 12:28 bucket closes at
  295.84), so anyone eyeballing the read against the tape mis-maps every exit by one bar. 15m events skew
  further: IWM's `pm_break` says 12:00 but the 15m bar 12:00–12:14 only closes at 12:15 (the journal row
  for QQQ's 12:30 scenario flip was written at 12:46 ET — the runner emitted it when the bar closed).
  **There is NO look-ahead**: `session.py` consumes a 15m bar only once `bar.ts + confirm_tf <= end_ts`
  (line 239), which is why IWM's 12:00 PM break was first actionable on the 2m bar ending 12:16 — verified
  against the DB tape. So this is a reporting defect, not a rule defect. Fix = one convention (stamp every
  read event at the producing bar's close, like the trades already are). Left for the user because event
  `ts` values reach the append-only journal, the sweep rows and ~40 tests; a blanket shift also re-emits
  today's already-journaled events once on the next deploy.
- **F20/F15 first-day evidence (2026-09-04 13:00 ET)** With both rules live, today's model day flips from
  **3 trades / 3 losses (−12.23%, −14.35%, −10.33%)** to **3 trades / 1 win / 2 losses, pnlPctSum
  +30.91**: SPY takes the 10:44 PM-low retest (put 768, small) for **+62.3%** — trim a third at +53%
  (11:00), the rest at the planned target 769.26 (11:04, +66.9%) — then gives −12.23% back on the 11:08
  EMA13 touch; IWM takes the 12:14 PMH retest (call 296, small) for −19.17% on the 12:28 one-candle stop;
  QQQ takes **nothing** (both of its earlier entries sat inside the PM range — F15 refusing them removed
  −14.35% and −10.33%). One day is not a verdict, but the two rules moved the day 68 points of premium
  and the winner is exactly the L2.6/L2.7 entry F20 was built to allow. Judge them from the walk-forward.
- **F26 (2026-09-04 13:40 ET, FIXED — the two silent entry gates)** `simulate_session` stopped taking
  entries with a bare `continue` in two places: past `last_entry_min` (15:30, D6) and once
  `losses_today >= max_losses_per_day` (D-3). Neither wrote a read event, so a session that goes quiet
  after 15:30 — or a symbol that has spent its loss budget — is indistinguishable in the read, the
  Armed timeline and the journal from a session with no setup at all. That is exactly the discipline
  a watcher is supposed to be able to verify, and today it was invisible: the desk's 15:30 cutoff would
  have passed with no row anywhere. Fixed the same way F23 fixed the skip spam — say it **once** per
  session, not per 2m close: `skip_last_entry` names the cutoff and the flatten time it hands over to,
  `skip_loss_cap` names the count and the cap. Purely additive to the read; it changes no entry, exit or
  size. Both are journaled (`TechniquePlanTriggerSkipped`) and iconed in the Armed timeline. Every full
  session now carries exactly one `skip_last_entry` at 15:30 — that row IS the discipline record.
- **F27 (2026-09-04 13:40 ET, FIXED 15:00 ET — wired, shipped at 0)** `rules.py:37` declares
  `zone_tol_atr: float = 0.0` ("PDH/PDL zones are their own tolerance, L1.2") and it is published in
  `GET /api/team2/status.thresholds`, but **nothing in the codebase reads it** — the only hits are the
  dataclass line and its own `.pyc`. `ScenarioTracker.on_close` flips the desk's bias on a bare
  `bar.close > pdh.top` / `< pdl.bottom` with no buffer and no decisiveness test. Evidence from today's
  QQQ tape (15m bars re-derived from the runtime DB): the **12:30** bar closed **718.94** against a zone
  top of **718.91** — a **0.025** margin, 0.086 × the 0.289 ATR, on a bar whose body was only 0.55 of its
  range (below the `decisive_body_ratio` 0.6 the rules already define for breaks). That flipped the desk
  from "reject PDH → puts" to "break PDH → calls", minted `scenario_1@12:30`, and the **13:00** close
  (718.13) flipped it straight back and invalidated it 30 minutes later. Four bias flips on QQQ today
  (09:30 / 10:30 / 12:30 / 13:00) around a 0.31-wide zone, **zero** trades. It cost nothing today because
  every QQQ entry was refused by F15 anyway, but on a day where QQQ is outside its PM range the desk would
  have been buying calls into a rejection. Proposal: wire `zone_tol_atr` for real (`close > top + tol·ATR`)
  and/or require `decisive_body_ratio` on a flip, shipped at **0.0 / off** so behaviour is unchanged until
  the walk-forward picks the value. Threshold change — user's call, not the watch's.
- **F28 (2026-09-04 13:40 ET, FIXED 15:00 ET — `TechniquePlanRead`)** `runner.py` journals
  the informational read events `scenario`, `pm_break` and `late_touch` under
  `ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED`, alongside the genuine `skip_*` rows. The bias flip and the PM break
  are the two **structural** events of the method — the ones that arm the L2.6/L2.7 setups — and the
  append-only journal records them as trigger skips. It also poisons the counts: IWM's audit shows "40
  skipped" today, which includes its `pm_break` and both `scenario` rows, so any review tool or morning
  report that keys off skip volume reads the desk as far more refused than it was. Fix = a new additive
  event constant (`TechniquePlanRead` or similar) in `zargar/events.py`. Not built here: `events.py` is
  shared vocabulary, the journal is append-only so the fix splits today's history, and EM's review CLI
  would want a look. Proposed.
- **F29 (2026-09-04 13:40 ET, DECIDED + BUILT 15:00 ET — desk-wide, `losses_desk_wide`)** `max_losses_per_day` is counted
  **per symbol** (`session.py` runs one symbol, `losses_today` is local to it) while
  `max_concurrent_positions` is deliberately counted **across all three plans** (A12,
  `open_positions_across_plans`). So the code already treats SPY/QQQ/IWM as one desk for risk *taken* but
  as three independent desks for losses *absorbed*. Today the desk is at **2 model losses** (SPY −12.23,
  IWM −19.17) and still has a budget of 2 more in each of the three symbols — up to 6 losers in a session
  the author would have walked away from after 2. Casey trades one book; §Z-rules read as one daily stop,
  not one per ticker. Question for the user: should `max_losses_per_day` be desk-wide like A12? Cheap to
  build (the runner already has `open_positions_across_plans`), but it is a money rule.

- **F30 (2026-09-04 14:15 ET, FIXED 15:00 ET — mid basis + 3-tick floor for Team2)**
  The desk's **first real Team2 order** (BUY 30 QQQ260904P00716000 @ **$0.34**, 13:48 ET, Practice sim)
  was closed 10 minutes later by the live premium stop: *"bid 0.24 is 29% below the 0.34 paid (limit
  25%)"* — filled 0.24, realized **−$300** plus $62.40 commission = **−$362.40**. Two things about that:
  (1) the method's own stop never triggered — the 2m close never went through 717.4513; QQQ's worst 2m
  close in the trade was 717.22 against a 717.13 entry. (2) The **model** ran the *same* 25% rule
  (`session.py:294`, `techniques.team2.premium_stop_pct`) and did not fire until **14:12**, 14 minutes
  later, because the model measures **mark → mark** while the live guard measures **bid → ask-paid**.
  On a $0.34 contract the 0.01 bid/ask spread is **~3%**, so the live stop starts an eighth of its budget
  in the hole before the underlying moves at all, and one tick is 3% of a 25% budget. Both stops sold the
  bottom: at **14:13 the same contract bid 0.335 / ask 0.345** — back to what was paid — with QQQ at
  717.08, still on the short's side of the 717.13 entry. Proposal: measure the live premium stop
  **mid-vs-mid** (or bid-vs-bid-at-entry) so it means what the author's ~20% means and matches the model,
  and/or floor the stop in ticks for cheap contracts. **Threshold + money rule — the user's call.**
  Related: the 2026-09-04 sizing row already flags that 25% of a $2,000 ticket is ~6% of the practice book.

  **Sharpened at 14:20 ET:** there are in fact **three** premium series answering the same 25% question and
  they disagree. The runner's guard (real **bid** vs ask paid) fired at 13:58; the **live read** still had
  the position open at 14:20 (in money modes it marks on the real premium, which had recovered to 0.335);
  the **replay** closed it at 14:12 on the synthetic mark-to-mark model. Same rule, same contract, three
  answers — that, not the 25% number, is the thing to settle first.

- **F31 (2026-09-04 14:15 ET, FIXED)** While the book was flat, the Armed/phone headline still read
  *"in trade pm_break_down@13:30: put 716, **1.00 left**, model peak +12%"*. The model holds until ITS
  stop; the desk's real contract had been gone since 13:58 (F30). The `· contract N% live` suffix only
  appears when an open trade exists, so the one case that matters — the contract closed underneath the
  model — was silent. `runner.py` now appends **"· book flat — the desk's contract is already closed
  (stop)"** when a filled trade for that setup is closed, so alert mode (which mints trades but never
  fills) stays silent. Same class of divergence at the 15:45 flatten and after a failed-exit retry.

- **F32 (2026-09-04 14:45 ET, FIXED 15:00 ET — halts net of fees)** The per-plan
  halt (`planrunner._maybe_loss_halt`) sums `trade.realized_pnl`, which is `(fill − avg_fill) × qty ×
  100` — **gross**. QQQ's two round trips today cost **$99.84** in commissions (executions table:
  30 contracts 31.20 + 31.20, 18 contracts 18.72 + 18.72) against a gross −$354.18, so the book lost
  **−$454.02** while the halt was still reading **−$354**. Concretely: after the first trade the book
  was down **−$362.40**, already past the plan's **−$341.38** limit, but the halt saw −$300 and let a
  second entry through. On a $0.30–0.60 0DTE contract the round-trip fee is **6–12% of premium**, so
  the halt understates the real day loss by that much at exactly the moment it is meant to bind.
  Proposal: mark the halt (and the per-technique `daily_loss_halt_pct`) off the book's own realised
  P&L, or subtract `fee_per_contract × qty × legs`. **Shared engine + money rule — the user's call.**

- **F33 (2026-09-04 14:45 ET, FIXED 15:00 ET — `skip_loss_budget` before routing)**
  `Team2Runner._on_bar` runs `_act` (which can fire, size and route an order) and only then calls
  `_maybe_loss_halt`. Live case: at **14:16** the QQQ plan had **$41** of gross loss budget left
  (−$300 realised against −$341.38) and opened **18 × QQQ260904P00717000 @ $0.59 = $1,062**. One
  minute later the bid was 0.56, the halt fired on "realised −300.00 + open −54.00", and the plan
  was disarmed and flattened at 0.5599 — a full round trip (**$37.44** of commission plus the spread)
  bought nothing. The trade could not have been held: its own worst case was 25× the remaining budget.
  Proposal: before routing an entry in auto, refuse when `premium_at_risk` (or the trade's own stop
  loss) exceeds the remaining daily budget — same shape as the existing `max_open_trades` and A12
  caps, with its own `skip_loss_budget` read event. **Shared engine + money rule — the user's call.**

- **F34 (2026-09-04 14:50 ET, FIXED — deploy queued)** Nothing keeps the desk's symbols on the feed
  once their plan is gone. QQQ disarmed at 14:17; the 14:33 restart re-armed only SPY and IWM, so
  nothing called `ensure_symbol("QQQ")` and **QQQ's 1m bars stopped at 14:28** while SPY and IWM kept
  banking. The day's replay of the disarmed plan is therefore truncated at the disarm — for a
  technique whose review loop is the point, the "would the method have made it back after the loss
  cap?" question becomes unanswerable for exactly the plan that most needs it. `attach_team2_runner`
  now `ensure_symbol`s every `techniques.team2.symbols` entry at boot, armed or not (best-effort;
  three index ETFs).

- **F35 (2026-09-04 14:50 ET, FIXED — deploy queued)** A plan that disarms mid-session vanishes from
  the desk with no reason given: `/api/team2/status` drops it from `armed`, and the Team2 **Plans**
  tab renders a bare *"not armed"*. Today that made "why is QQQ gone?" a journal-archaeology question
  even though the `technique_armed` row already stores `status: disarmed` and the full
  `stopReason`. `Team2Service.runs()` now joins that row and returns `status`/`stopReason`; the page
  shows *"disarmed — loss halt: realised −300.00 + open −54.00 marked at bid crossed −341.38"*.

- **F36 (2026-09-04 14:50 ET, FIXED 15:00 ET — closest-to-target in both paths)** On
  QQQ's 14:14 fire the read says *"buy put **716** ≈ **$0.26**"* while the live order was **717 P at
  $0.59** — a different strike at **2.3× the premium**, so that trade's model P&L (−19% on 0.26) and
  book P&L (−$91.62 on 0.59) are not comparable at all. Cause: both aim at `target_premium` 0.60 but
  from different prices. `PremiumModel.pick_strike` walks OTM until its **flat-IV BS mark ≤ 0.60**; at
  spot 717.03 its 717 mark was just over 0.60 (σ 0.1669 model vs 0.1335 OPRA), so it stepped to 716.
  The live picker saw the real ask **0.59 ≤ 0.60** and stopped at 717. A knife-edge on one cent
  decides the strike, the premium and the size. Same family as F30 (three premium series, one rule).
  Note the first QQQ fire an hour earlier agreed (716 model $0.33 / live $0.36) — the divergence
  appears only when the ATM contract prices within a cent of the target. Proposal: pick the strike
  whose premium is **closest** to the target in both paths, and stamp the read's contract with the
  live one once a money-mode fill exists so the scorecard compares like with like.


- **F37 (2026-09-04 15:10 ET, FIXED 15:35 ET — the book counts once a plan routed; alert plans use the model; the gate is money-modes only)**
  F29 shipped at 15:00 and is binding **right now**: `losses_across_plans()` sums, per armed plan,
  `max(model losers, real closed losers)`. At 15:10 SPY carries **1 model loser** (11:10, −12.23%) and
  IWM **1** (12:16, −19.17%), so the desk reads **2 of 2** and every remaining entry today is refused —
  including SPY's `scenario_3` at **769.26**, which price is sitting **0.11 %** away from. Neither of
  those two "losses" cost a cent: the live runner **refused both fires at the time** as
  `skip_no_trade_zone` (the audit has the rows at 14:46 and 16:16 UTC) because F20/F15 had not been
  deployed yet — they exist only because the read is recomputed by *today's newest* code. So a rule
  meant to stop a desk that is bleeding is being tripped by a hindsight simulation of trades the desk
  declined. The `max(model, real)` choice is right for **alert** mode (the model is the only record
  there); in **auto** on a plan that has traded for real, the book is the record and the model is
  commentary. Proposal: count `real` for any plan whose mode is auto/proposal once that plan has
  routed an order, `model` only for alert-mode plans (or plans that never routed), and say which
  basis was used in the skip line. **Money rule — the user's call.** Same family as F30/F36: the
  model and the book are two premium/P&L series and a *risk gate* now depends on which one you read.

- **F38 (2026-09-04 15:10 ET, FIXED 15:35 ET — a per-day tally keeps a disarmed plan's losers and is re-seeded from the persisted rows at boot)**
  `losses_across_plans()` iterates `self._armed.values()`, so QQQ's **two real losing round trips**
  (−$300 and −$54 gross, −$454.02 with fees) stopped counting toward the desk the moment its own loss
  halt **disarmed** it at 14:17. The cap therefore *loosens* precisely after the worst outcome a plan
  can have. It does not bite today only because SPY+IWM already reach 2 on model losers (F37); on a
  day where QQQ takes both of the desk's losses and halts out, SPY and IWM would each start again from
  a budget of 2. Fix is small — keep a per-day tally, or iterate today's plans rather than the armed
  map — but it changes what the desk is allowed to trade. **Money rule — the user's call.**
  (Related, cosmetic: the F29 gate in `runner.py:379` is **not** mode-guarded, unlike the
  `max_open_skip` and `max_concurrent_skip` gates immediately around it, so in alert mode it also
  stops minting the paper trade. Harmless while the desk is in auto; worth aligning with the
  "money modes only; alert/proposal keep recording every read" convention two lines above it.)

- **F39 (2026-09-04 15:10 ET, FIXED 15:35 ET — an unmeasurable equity refuses with its own reason)**
  `planrunner.py:2396` reads `elif est > 0 and pct_cap and eq and est > eq * pct_cap / 100.0`. With
  `eq` **negative** the right-hand side is negative, so *every* option entry is blocked under a message
  that claims a percentage cap; with `eq` exactly **0** the whole clause is falsy and the cap is skipped
  — the gate fails open. Neither is "the premium is too large"; both are "we cannot measure the
  account". Seen today only as the pre-F22 symptom (SPY's 11:10 fire was refused against *"the account's
  $-267 equity"*, which was the Practice book's **cash**, −5,020.52 + the 4,299.92 SOFI buy + the 454.02
  QQQ round trips, before F22 switched the check to `positions.equity()`); with the fix live the same
  book reads **$8,401** and the gate passed at 13:48. Still worth closing: `eq <= 0` should refuse with
  its own reason, not silently through one branch and always through the other. **Shared engine
  (`zargar/execution/planrunner.py`) — proposal, not built here.**

- **F40 (2026-09-04 15:40 ET, FIXED 17:45 ET — a disarmed plan keeps listening until its flatten settles; shared engine, PLATFORM-RULES)**
  `PlanRunner.disarm()` submits the flatten (`_exit(..., "disarm", force_market=True)`), then
  immediately does `self._armed.pop(run_id)` and persists. The fill arrives ~2 s later on the orders
  topic and `on_order_update` starts with `ap = self._armed.get(run_id)` → `None` → **return**. The
  trade record is frozen at the write-ahead intent forever. Proven on today's QQQ plan: order
  `c4f557e6…` is **FILLED 18 @ 0.5599** in `orders`/`executions` (14:17:02 ET, commission $18.72), the
  book is flat, yet the persisted plan still reads `status: "open"`, `remaining: 18`,
  `realizedPnl: 0.0`, exit `{kind: "disarm", status: "SUBMITTED", filledQty: 0.0, price: null}`.
  Three consequences, all live today: (1) **F38's boot seed counted 1 real loser, not 2** — the log
  says *"loss tally seeded with 1 loser(s)"* — because the seed keys on `status == "closed"`, so the
  desk-wide cap loosens by one after exactly the event F38 was built to survive; (2) the plan's own
  P&L understates the day by the flatten's **−$54.18** gross (−$91.62 net) — anything scoring the day
  from plan state, not the book, is wrong; (3) the record claims an 18-lot 0DTE put held past
  expiry. Not a restore hazard (disarmed plans are not restored), and no money moved that shouldn't
  have — the book is correct throughout; this is the plan's *record* of it. Recommended shape: in
  `disarm()`, await the flatten's terminal status (short timeout) before popping from `_armed`, or
  keep the plan in a `_closing` map that `on_order_update` also consults, and persist again when it
  settles; F38's seed should additionally count a trade whose exit orders filled at a loss even if the
  record says open. **Shared engine (`zargar/execution/planrunner.py`) — proposal, not built here**
  (it changes the disarm path for EM and Tip too).


- **F41 (2026-09-04 16:05 ET, FIXED — one armed plan per symbol per session; `force` is the manual override)**
  `team2_plan_nightly` is registered with the scheduler's default `weekdays_only=True`, which checks
  `now.weekday() >= 5` and nothing else — so it also fires on a **weekday market holiday**.
  `nightly_plans()` then sees `is_trading_day(today) == False` and targets `next_trading_day(today)`,
  which is the *same* date Friday's run already planned. Neither `mint_plan_run()` (it always inserts a
  new `TechniqueRun`) nor `PlanRunner.arm()` (it dedupes on `run_id` only) refuses the repeat, so the
  session would have opened with **two armed plans per symbol**: two full-size entries per setup, two
  contributions to the desk-wide loss cap, two records of the same day. Next occurrence was
  **Monday 2026-09-07 (Labor Day) 17:00 ET → 2026-09-08**, with the desk in AUTO and no watch run
  between the mint (17:00 ET) and the Tuesday open. Same defect on a second "Plan now" press.
  Fix: `nightly_plans()` skips a symbol that already has an armed plan for `for_date` and reports it
  under `skipped` (the toast prints it); `force=True` — exposed on `POST /api/team2/plan-now` — is the
  manual rebuild. Nothing is disarmed and no sizing changed: it only refuses to duplicate.
  Test: `tests/test_team2_runner.py::test_nightly_plans_never_arms_a_second_plan_for_the_same_session`.

- **F42 (2026-09-04 16:05 ET, FIXED — the pre-open leaves a session that has not started alone)**
  Same holiday root: `team2_preopen` (09:25 ET) also fires on a weekday holiday, and
  `preopen_complete()` walked **every** armed plan regardless of its `plan_for`. `complete_plan()`
  over a date with no bars writes `pmh: None`, `pml: None`, `complete: False` back onto the plan and
  keeps the stale `dayType`/`sizingAtOpen`, then `stamp_run()` persists that onto the run — i.e. a
  holiday morning would blank the plan built for the next trading day, and the real 09:25 read would
  be the second one written. Fix: skip any plan whose `plan_for` is later than today's ET date;
  past-dated plans still complete (tests, replays, a manual catch-up).
  Test: `tests/test_team2_runner.py::test_preopen_never_completes_a_plan_whose_session_has_not_started`.

- **F43 (2026-09-04 16:05 ET, FIXED 17:45 ET — Team2 scores its own day: read vs book, skips, net of fees; also on the disarm path)**
  `_end_session()` writes the execution scorecard from `PlanRunner._score_execution()`, which iterates
  `ap.trackers` — EM's declared `TriggerTracker`s. **Team2 has no trackers**: its entries come out of
  the session walk, so the scorecard is structurally empty. Today both surviving plans journalled
  `TechniquePlanScored {rows: [], matched: 0, actualFires: 0, theoreticalFires: 0, realizedPnl: 0}` at
  16:00 ET on a day the read took 4 model trades and the book lost **−$454.02** — a record that says
  "nothing happened". Worse for a plan that disarms early: QQQ (the only symbol that traded real money)
  never reached `_end_session()` at all, so it has **no scorecard row**, and its persisted
  `realizedPnl` is −300.00 because of F40. Proposed shape (Team2-local, `runner.py`): override the
  scorecard with the day's own comparison — `_last_sim` model trades (setup, entry ts, premium, pnl %)
  against the real fills from `ap.trades`/the book, plus the skips that stopped a model trade from being
  taken (`skip_loss_cap_desk`, `skip_no_trade_zone`, `skip_last_entry`, `skip_no_contract`); and write
  it on the loss-halt disarm path too, not only at the close. Wants the F30/F36 answer first (which
  premium series is authoritative for "what the model made"), so it is the user's call.
  **Not built here** — it is new reporting, not a defect fix.

- **F44 (2026-09-04 16:05 ET, FIXED 17:45 ET — expired contracts are dropped from the tracked batch on every refresh)**
  `OptionsService._tracked` only ever grows: `track()` adds, nothing prunes. The 2 s OPRA poll therefore
  keeps requesting contracts that expired days ago — today's batch of **55** symbols still carried
  `MU260902P00945000`, `GOOGL260902C00340000`, `META260902C00590000`, `TSLA260902P00355000` (expired
  2026-09-02) and, after this close, both of the desk's `QQQ260904` puts. Harmless today, but a 0DTE
  desk adds several dead symbols **every session**, and the batch is a single URL: it grows without
  bound until the process restarts, wasting the paid quote budget and eventually risking that a
  provider-side symbol cap clips the contracts the desk is actually trading. Proposed: drop a symbol
  from `_tracked` when its expiry is past (and when nothing holds or watches it), on the same pass.
  **`zargar/options/service.py` — shared engine, proposal, not built here.**

- **F45 (2026-09-04 16:30 ET, FIXED 17:45 ET — paced, 429s retried with backoff, failures counted; the nightly chain sweep was
  rate-limited out of half the universe)** `research/snapshots.py::_run` walks every optionable
  universe symbol back-to-back with **no throttle, no retry and no backoff**, and CBOE's free endpoint
  refuses it. Today's 16:30 job attempted **150** underlyings in ~3 minutes and took **185 HTTP 429s**;
  once the refusals start they return instantly, so the loop rips through the remainder of the
  universe in seconds and loses all of them. The damage is dated and measurable in
  `option_chain_snapshots`: **145–146** distinct underlyings persisted on 2026-08-27/28 versus
  **73–78** on every session since 2026-08-31 (77 today). That table is Flow's single writer and its
  nightly 16:45 scan reads it, so roughly half the universe has had no Vol/OI read for five sessions,
  and the overnight-OI confirmation for the names that *are* saved is comparing against gaps. It also
  collides with `OptionsService.refresh_tracked`, which shares the same CBOE client and logged 114
  `enrich skipped … CBOE HTTP 429` lines in the same window. **No Team2 impact** — Team2 picks its
  contract from OPRA, not from these snapshots — but it is the largest live data defect the desk can
  see. Proposed: pace the sweep (a small per-request delay or a semaphore of 1–2), retry a 429 once
  after a backoff, and journal the per-symbol failure count so a half-empty night is visible instead
  of silent. **`zargar/research/snapshots.py` — shared engine, proposal, not built here.**


- **F47 (2026-09-08 09:15 ET, EXPERIMENTAL — sweep variant only, user decision 2026-09-08 evening after the Codex
  review: "as written it is wrong" — a target too close should mean skip or degrade size, not a farther target
  invented for it; nothing promotes without the twenty-session review; the planned target has no minimum-room floor)**
  `levels.targets_beyond` sets a break trade's outright exit to the **most recent 15m pivot** beyond
  the zone within the 10-session lookback, with **no check that the pivot leaves enough room to be
  worth trading**. `session.py` then exits the *whole* remaining position the moment that level is
  touched (`rules.target_exit`, X3/V11), so a target sitting just past the break level closes the
  trade before the +50 % / +100 % trims can ever engage. The engine already knows the test — the X3b
  HOD/LOD substitute must clear `hod_target_min_atr` (1.0) × ATR before it may replace the plan
  target — but that floor is applied **only to the substitute**, never to the plan target itself.
  Live today (2026-09-08), measured against Friday's average 2m bar range as the ATR proxy
  (SPY 0.254 / QQQ 0.375 / IWM 0.152): SPY's targets leave 1.16 up (4.6 ATR) and 1.55 down (6.1 ATR),
  IWM's 0.40 up (2.6 ATR) — all sane — but **QQQ's break-below target is 716.34 against a PDL zone
  bottom of 716.56: 0.22 of room, 0.59 ATR, 0.03 % of spot.** If QQQ breaks its PDL zone today the
  auto desk buys puts and then exits in full ~0.22 under the break, for a few percent of premium,
  instead of running the method's trim ladder. Proposed: apply the same `hod_target_min_atr` floor
  when `targets_beyond` picks the plan target — a pivot that does not clear it is skipped for the
  next one out, and the target falls back to `None` ("open", ride the EMA) when nothing qualifies.
  **Threshold/rule change on a money path — proposal only, not built by the watch job.**
- **F48 (2026-09-08 09:40 ET, FIXED — `a53f866`)** `POST /api/team2/runs/{id}/replay` declared
  `body: ReplayBody` as a **required** model, so the plain parity replay the watch job runs (no
  overrides) came back **422 Unprocessable Content**. `overrides` is the body's only field and it is
  optional, so the body is now optional too. Operator/CLI surface only — the UI never calls this route,
  and nothing on a money path changed. Deploy queued for the next watch run (the fix landed inside the
  09:30–10:30 prime-open window and a restart there costs live read state for no benefit).
- **F49 (2026-09-08 09:40 ET, FIXED 2026-09-08 evening — `Team2Runner._finalize_open`: the first regular bar re-runs
  `complete_plan`, keeps the 09:25 estimate as `plan.preopenSnapshot`, journals `open_finalized` and re-stamps the run;
  `test_team2_integrity.py::test_day_type_is_finalized_on_the_real_open…`; the day's premise is read 5 minutes before the
  open)** `plan.openPrice` — and with it `dayType` (A1) and `sizingAtOpen` (V6) — is set by
  `complete_plan`, which prefers the **09:30 RTH open** but falls back to the **last pre-market close**
  when no RTH bar exists yet. The 09:25 pre-open job always runs before the open, so the fallback is
  what fires **every single session**, and nothing ever re-completes the plan once the real open
  prints: `Team2Service.preopen_complete` and `Team2Runner._preopen_check` are the only callers, and
  `replay()` re-derives only when `complete` is False (F13 deliberately stamped the completed plan so
  replay reproduces the live premise — that fix locked the approximation in). `sizingAtOpen` is only a
  label (live sizing recomputes `sizing_bucket(entry_spot, …)` per touch), but **`dayType` gates
  money**: `session.py:268` lifts the inside-day guard on `pm_break_up` / `pm_break_down` only when the
  day type is `gap_up`/`gap_down` (F15/L2.4), so a mis-typed day changes which setups exist at all.
  Live today: the stamped opens are the 09:25 prints SPY 769.28 / QQQ 721.18 / IWM 295.59, while the
  real 09:30 bar opens were **SPY 769.06 / QQQ 720.91 / IWM 295.34** — a 0.22–0.27 gap. All three still
  classify `normal`, but **SPY's real open sat 0.06 above its PDL zone bottom of 769.00**: an open
  seven cents lower would have been a `gap_down` day, and the stamped pre-market print would still have
  said `normal`. Proposed: re-complete the plan on the first RTH bar of the session (upgrading
  `openPrice`/`openSource`/`dayType`, and re-stamping so replay parity is preserved), leaving the 09:25
  completion as the pre-open estimate it is. **Money-path behaviour change — proposal only, not built
  by the watch job.**

- **F50 (2026-09-08 10:10 ET, FIXED 2026-09-08 evening — the plan target is now an UNDERLYING condition on the ~2 s quote
  watch (`PlanRunner.target_breach` hook, Team2 implements long `last ≥ target` / short `last ≤ target`): the first FRESH
  print through it sells the remaining size as a reduce-only LIMIT at the contract's fresh bid, never a premium limit;
  duplicates are impossible while an exit is pending (`pending_exit_qty`), a stale print never sells, a resting limit is
  re-priced by `_reprice_stuck_exits` and the failed-exit watchdog; the model labels its own exits
  `fillAssumption: target_touch_intrabar`. Semantics in PLATFORM-RULES 2026-09-08. `test_target_sells_once_on_a_fresh_print…`;
  the target exit WAS decided a bar late and the
  book pays for it. First live money evidence.)** The plan target is judged on the CLOSED 2m bar
  (`session.py` X3/V11: "target touched → sell the whole position"), and the live runner then routes
  that exit **at the bar close** — so the desk sells wherever price is when the bar ends, while the
  model books the exit **at the target price**. QQQ today, both legs of the same setup, entry on the
  716.90 retest with the plan target 716.34 (F47's thin 0.65-ATR target):
  · trade #1 fired 10:02, filled 14 × **$0.655**; the 10:02–10:04 bar wicked to 715.87 (target touched,
  the put was worth ≈$0.85 there) and closed 716.86 — the exit routed at 10:04:00 and filled **$0.61**
  → **−$63**, while the model scored the same trade **+32.7 %** at mark 0.7263.
  · trade #2 fired 10:06, filled 9 × **$0.63**, same target, exit at 10:08:00 filled **$0.68**
  → **+$45**, model **+32.9 %**.
  Model day: 2 trades, 2 wins, **+65.6 %**. Book day: **−$18** realised gross (**−$65.84** after
  **$47.84** of commissions — 23 contracts × 2 legs × $1.04; the $58 in the first draft of this note
  was an estimate, the 16:00 scorecard has the exact figures), i.e. the read and the book disagree in *sign* on the desk's first two trades. The gap
  is not the model's premium series — it is **when the sell is sent**: on a target that sits inside one
  bar's range, price is routinely back through the level by the close. The engine already runs an
  exit-only ~2 s quote watch (stop + premium stop + failed-exit retry), so the target could be armed
  the same way. Proposed, in order of preference: (a) rest a **SELL limit at the target premium** from
  the moment the entry fills — the method's own "sell into the spike" — or (b) put the plan-target
  touch on the quote-watch loop and exit on the print instead of the close. Either makes the book
  match what the read claims. **Money-path behaviour change — proposal only, not built by the watch
  job.** Note this compounds F47: a target one bar wide guarantees the timing loss shows up on every
  trade.
- **F51 (2026-09-08 10:10 ET, FIXED 2026-09-08 evening — `Team2Runner._session_sigma`: the read's IV is captured ONCE per
  plan at the first 2m read from today's 0DTE ATM chain IV (call+put `mid_iv` averaged at the strike nearest spot,
  `source: chain_atm`, flagged `chainDelayed` because CBOE is ~15 min behind) else the VIX proxy (`vix_proxy`), stamped as
  `plan.sigma {value, source, lockedAt, strike, spot, capturedAt}` on the plan AND the run row, journaled `sigma_locked`;
  `replay()` uses the stamped value. `techniques.team2.sigma_source` default `vix1d → chain`. A later IV can never rewrite
  an earlier signal — it may only inform the next session (Codex: point-in-time provenance). Tests: `test_iv_is_locked…`,
  `test_the_locked_iv_comes_from_todays_atm_chain…`, `…falls_back_to_the_vix_proxy…`; the read's IV proxy WAS half the traded 0DTE IV)**
  The session read prices every model trade with `PremiumModel(sigma=…)` fed by the IV proxy
  `^VIX1D → ^VIX×1.3 → 0.20` (`runner.py::_sigma`, B2). Today's sigma is **0.1203** while the contract
  the desk actually bought, `QQQ260908P00714000`, quoted **IV 0.236** on OPRA — a factor of two. Two
  measurable consequences on today's tape: the model priced its 716-strike put (nearer the money) at
  **$0.5216** while the desk paid **$0.655** for the 714 strike (further out, so the real 716 strike
  was worth ≈$0.9), and the model's premium moved **+33 %** for a 0.56 spot move where the real
  contract moves ≈half that per point (a low IV inflates the percentage sensitivity of a near-dated
  OTM contract). The live money path is unaffected — trims and the premium stop are judged on the
  contract's own fresh bid (F8) and sizing on the live NBBO (F14) — but every number the *read*
  produces is affected: the +50 %/+100 % trim forecasts, `pnlPct`, the walk-forward sweep and any
  scorecard row still carried on the `session-read` basis. Proposed: seed sigma per symbol from the
  0DTE chain the picker already fetches (the ATM IV of the expiry) and fall back to the VIX1D proxy
  only when no chain is available; stamp the source next to `premiumPathSimulated`. **Calibration
  change to the model — proposal only, not built by the watch job.**
- **F52 (2026-09-08 10:10 ET, FIXED — see change log)** Team2's `TechniquePlanRead` journal kind
  (F28: scenario / pm_break / pm_retest / late_touch) was **not registered** in the shared event
  contract, so every structural read event logged
  `WARNING event contract: unregistered Technique event kind: TechniquePlanRead` (6 today, first at
  09:46 ET — every session since Team2 started reading). The guard test
  `test_every_journaled_kind_has_a_contract` never caught it because it scans only `zargar/technique/`
  and `zargar/execution/`, not the per-technique packages under `zargar/techniques/`. Registered the
  kind and widened the test's scan to `zargar/techniques/**` (the only unregistered kind it finds is
  this one). Advisory logging only — no trade or shape changed.

- **F53 (2026-09-08 10:40 ET, FIXED — see change log)** The Armed page's and the phone's one-line plan
  summary said `waiting for the 1st/2nd 2m pullback into the EMA13 (touches 0)` for a setup the regime
  **cannot fire**. `session.py:407` (E3/B9, stack must agree) and `:410` (E4, no braided EMAs) skip
  silently and deliberately — they are re-judged on every 2m bar, so minting an event would flood the
  read — but nothing else surfaced them, so a blocked trigger looked identical to one the next EMA13
  touch would take. Live today: QQQ's 15m close at 10:30 flipped the bias to **scenario 3 (bounce PDL)
  → calls** while the EMA stack was still **bear** (ema13 717.34 < ema48 718.22 < ema200 718.90, spot
  717.6). No touch of the EMA13 could have fired that plan; the line implied one would. The summary's
  waiting branch now appends `— no entry until the stack must turn bull (E3/B9/E4)` (and
  `, or a 200 EMA flush (T8)` on a range day, where T8 is the documented exception). Descriptive only:
  the gate itself is unchanged and still lives in `session.py`. Guarded by an invariant in
  `tests/test_team2_runner.py` that walks the session's snapshots and asserts the clause is present
  exactly when the regime disagrees.
- **F54 (2026-09-08 10:40 ET, observation — evidence for F27's open thresholds, NOT fixed)** QQQ's PDL
  zone today is **716.56–717.03 — 0.47 wide against a 2m ATR of 0.72**, i.e. the whole zone is 0.65 ATR.
  With `zone_tol_atr` and `flip_body_ratio` both shipping at **0**, the bias flipped twice in two 15m
  bars: **10:15 close 716.505 flipped scenario 2 → 4 on a 0.055 margin (0.08 ATR)**, then **10:30 close
  717.76 flipped 4 → 3** (1.0 ATR, decisive). The first flip is noise by any measure and it minted
  `scenario_4@10:00`, which promptly died on `skip_no_trade_zone`; the second reversed the desk's
  direction outright. Both flips are *correct* against the rules as written — this is the exact failure
  F27 anticipated ("QQQ 2026-09-04 12:30 flipped on a 0.025 margin, 0.55 body, and flipped back 30 min
  later"), now with a second independent day of evidence and a zone-width measurement to go with it.
  Suggests the tolerance wants to scale with zone width, not just ATR. **Threshold work — for the
  walk-forward and the user, not the watch job.**

- **F55 (2026-09-08 10:55 ET, FIXED — see change log)** The Team2 page rendered plan timestamps in the
  **browser's** timezone while every other line on the same page is ET. Friday's nightly built today's
  plans at **17:34 ET**; the Plans table's WHEN column showed **"Sep 4, 2:34 PM"** on this PT machine —
  directly beneath a status line reading `plans 17:00 ET, pre-open 09:25`, so the plan appeared to have
  been built three hours *before* the plan job that built it. Every other technique surface already
  pins ET (`NowView`, `ArmedDayPanel`, `ValidationTab`, `PlanCard`, `StockChart`); `Team2Page.tsx:109`
  was the only one that did not. Now formatted with `timeZone: "America/New_York"` and suffixed `ET`.
  Display only — no data, rule or plan changed. (The WHEN column is the run's `createdAt`; `armedAt` is
  not carried on the runs list, only on the snapshot. That is accurate for a column headed "when", so
  it was left alone.)


- **F56 (2026-09-08 11:10 ET, EXPERIMENTAL — split per the Codex review into (a) edge-reversal at small size and (b) the
  six-ATR bypass; BOTH sweep variants only, neither promotes without the twenty-session review (user 2026-09-08 evening);
  a wide pre-market range makes V6's no-trade zone
  swallow the whole session, so no scenario setup can ever fire)** `sizing_bucket` (`scenario.py:36`)
  returns **`none`** for any entry price inside the PM range — F15's deliberate widening on 2026-09-04,
  which stopped the desk buying the middle of a gap day's pre-market range. The gate is applied to the
  **pullback's entry price**, i.e. roughly spot, so when the PM range is wide it is not a zone the
  price passes through — it *is* the day. Today, on a plain `normal` day:

  | | PM range | width | vs 2m ATR | today's 1m closes inside it |
  |---|---|---|---|---|
  | QQQ | 716.90–723.72 | 6.82 | **12.4×** | 78/97 (80%) |
  | SPY | 766.73–770.48 | 3.75 | **9.4×** | 74/97 (76%) |
  | IWM | 293.80–295.91 | 2.11 | **9.0×** | **97/97 (100%)** |

  QQQ's PDH zone (721.82–721.86) *and* PDL zone top (717.03) both lie **inside** its own PM range, so
  scenario 2 and scenario 3 are anchored on lines the sizing ladder refuses. The result is visible in
  the read: QQQ logged `skip_no_trade_zone` at **10:16** (entry 716.99) and again at **11:00** (entry
  718.26); SPY at **10:00** (entry 767.82) and will repeat while it holds this range; IWM has never
  left its PM range at all. **Every fire the desk took today came from the one carve-out that already
  exists** — F20's PM-level retest exemption (`session.py:478`), which re-buckets a `pm_break` retest
  *on* the anchor as `small`. Without F20 the desk would have taken zero trades in a session with four
  scenario setups and eight EMA13 touches.

  The V6 ladder has three rungs — `full` beyond the prior-day zones, `small` between a prior-day zone
  and the PM level, `none` inside the PM range — but when the PM range **contains** yesterday's zones
  the middle rung is geometrically empty and everything collapses to `none`. **Proposed** (same shape
  as F20, Team2-local, one function): when the entry sits within the touch tolerance of a **prior-day
  zone edge**, bucket it `small` rather than `none` — a tested structural line is not the middle of
  the chop, whichever side of the overnight range it happens to fall on. Optionally gate the whole
  rule on PM width (e.g. skip the `none` bucket entirely once the PM range exceeds ~6× ATR, where it
  has stopped describing chop and is just describing the day). **Threshold/rule work — the user's
  call and the walk-forward's to size; not built by the watch job.** Note this is the mirror image of
  F15: F15 was a real loss inside a *gap* day's PM range; F56 is the cost of the same rule on a
  *normal* day whose PM range is wide.

  **Follow-up measurement (run 23, 12:05 ET — the refusal rate, not just the anecdote).** Rebuilt the
  session's 2m bars from the `bars` table (09:30–12:03 ET, 78 bars per symbol) and counted how many of
  them **straddle a session-seeded EMA13** (bar low ≤ EMA13 ≤ bar high) — a deliberately generous
  proxy for "a pullback into the 13 happened here" — then how many of those sat inside the PM range:

  | | 2m EMA13 straddles | of which inside PM | 2m closes inside PM |
  |---|---|---|---|
  | SPY | 33 | 31 (**94%**) | 68/78 (87%) |
  | QQQ | 28 | 26 (**93%**) | 68/78 (87%) |
  | IWM | 41 | **41 (100%)** | 78/78 (100%) |
  | **all three** | **102** | **98 (94%)** | |

  So on this day the `none` bucket is not filtering the odd bad location — it is refusing **19 of every
  20 candidate pullbacks**, and on IWM every single one. Caveat on the number: the straddle test is a
  geometric proxy, not the technique's own touch test (which additionally requires a live setup, the
  right direction and the touch tolerance), so 102 is an **upper bound on candidates**, not a count of
  gate firings — the read mints one `skip_no_trade_zone` per setup by design (F23). It measures the
  *geometry* the gate is applied to, which is exactly what the proposal above is about. Strengthens
  the case for the width-scaled rung; still the user's call.

- **F57 (2026-09-08 11:40 ET, FIXED — the "not a tradeable location" gates were invisible on the one
  line the desk actually reads).** The waiting headline said *"waiting for the 1st/2nd 2m pullback into
  the EMA13 (touches 0)"* on all three symbols while every pullback was being refused at the door.
  `session.py` DOES mint the refusal (`skip_no_trade_zone` V6/B5, `skip_range_confirmation` B3/A4) —
  but only into the read, and only **once per setup** (F23, so it does not bury the read), and the
  count it holds down is `touches`, which by design is **not incremented** by a refused dip (F18). The
  three together mean the page can sit at "touches 0" for hours with a single 10:00 event, five
  scrolls down, as the only trace. Today it bit every symbol: SPY 10:00, QQQ 10:16 + 11:00, IWM 11:26
  — the IWM one landing *the moment* its stack turned bull and F53's regime clause cleared, so the
  line went from "blocked by the regime" straight to a clean-looking "waiting" that could never fire.
  **Fix:** the setup's current refusal (`_skipped`, cleared by a real touch) is now serialized on the
  read and appended to the headline — *"· the last pullback sat inside the pre-market range — no-trade
  zone (V6/B5)"*. Same family as F53 and purely descriptive: **no gate, threshold, size or money path
  is touched**; the gates stay in `session.py`. Guarded both ends — `tests/test_team2_session.py`
  pins the read exposing the refusal on the fixture that reaches the gate, and
  `tests/test_team2_runner.py` asserts the clause appears exactly when the picked setup is refused.
  (F56 remains the open *rule* question — whether the gate should be this wide on a day whose PM
  range is 9–12x ATR. F57 only stops it being silent.)

- **F58 (2026-09-08 12:35 ET, NOT fixed — proposal; V6's ladder is only defined when the PM range is
  NESTED inside yesterday's zones, and the code resolves every other geometry as `none`).** Chasing
  F56 I first tested the cheaper hypothesis — that the pre-market window is wrong — and it is **not**:
  the sheets' PM ranges reproduce the 04:00–09:30 ET 1m tape to the cent (SPY 766.73–770.48, QQQ
  716.90–723.72, IWM 293.80–295.91), which is exactly METHOD **L2.1**. The window is faithful; the
  problem is the *ladder*. **V6** reads, top to bottom: above the PDH zone = Full · PDH zone→PMH =
  Small · PMH→PML = No trade · PML→PDL zone = Small · below the PDL zone = Full. For those five bands
  to be ordered at all, the picture must have `PDL zone < PML < PMH < PDH zone` — the PM range nested
  *inside* yesterday's range. `sizing_bucket` (`scenario.py:36`) does not test for that: it checks
  `pml <= price <= pmh` **first and unconditionally**, so whenever a PM edge crosses a prior-day zone
  the overlapping bands are all resolved in favour of `none` — including the band V6 calls **Full**.
  None of today's three symbols is nested: QQQ PMH 723.72 is *above* its PDH zone top 721.86, SPY PML
  766.73 is *below* its PDL zone bottom 769.00, IWM PML 293.80 sits inside its PDL zone 293.56–294.59.
  **SPY 10:00 is the clean demonstration**: entry 767.82 is below the PDL zone bottom 769.00, in the
  direction of the confirmed scenario-4 bias — V6 puts that band at **Full size** and the function's
  own `price < pdl.bottom` rung would return `full` — but the PM check pre-empts it and returns
  `none`. QQQ 11:00 (718.26, mid prior-day range) and IWM 11:26 (295.32, ditto) are defensible `none`s
  under B7; QQQ 10:16 (716.99, inside the PDL zone) is genuinely undefined. So of the four refusals
  today, **one contradicts V6 outright and one is undefined** — this is a precedence question, not
  only the width question F56 raises. Proposed (user's call, NOT built): make the `none` rung apply
  only where the ladder is defined — i.e. clamp the no-trade band to `max(pml, pdl.top)`…
  `min(pmh, pdh.bottom)` — so beyond a prior-day zone V6's Full/Small rungs win, and F15's gap-day
  protection (which was a price in the *middle* of a PM range, inside yesterday's range) is untouched.
  Cross-refs F56 (width) and F15 (why the rung was widened).

  **Follow-up (2026-09-08 13:15 ET, run 25) — what the four refusals actually did on today's tape,
  and what the proposed clamp would and would not have changed.** Measured on the banked 1m bars from
  each refusal's own minute to 13:05 ET, taking the entry price the gate refused and the plan target
  the setup carried. **Spot only** — no premium path, no trims, no stop: this says where price went,
  not what the book would have made (F50 shows the exit *timing* is what turns a model win into a book
  loss, and F51 that the model's sigma is half the traded IV). MFE/MAE are in points.
  | refusal | dir | entry → target (room) | outcome | MFE | MAE |
  |---|---|---|---|---|---|
  | SPY 10:00 | short | 767.82 → 767.45 (0.37) | **target hit in the same minute** | 1.83 later | **0.00** before the target |
  | QQQ 10:16 | short | 716.99 → 716.34 (0.65) | never reached it | 0.54 (83 %) | **3.94 against** |
  | QQQ 11:00 | long | 718.26 → 721.82 (3.56) | not yet | 2.67 (75 %) | **0.00** |
  | IWM 11:26 | long | 295.32 → 295.955 (0.63) | not yet | 0.62 (**98 %**) | 0.12 |
  Three of the four went the setup's way and one went hard against it — and the split does **not**
  line up with F58's precedence argument the way the geometry alone suggested. Working the proposed
  clamp (`max(pml, pdl.top)`…`min(pmh, pdh.bottom)`) through today's four:
  · **SPY 10:00 would be allowed** — 767.82 is below the PDL zone, so the band no longer covers it.
  That is the case V6 explicitly calls Full size, and it hit its target with **zero** adverse
  excursion: the clamp buys the desk its one clean trade of the day. ✓
  · **QQQ 10:16 would ALSO be allowed** — 716.99 sits inside the PDL zone 716.56–717.03, so it falls
  *below* the clamped band bottom of 717.03 and is no longer refused. That is the −3.94 loser. ✗ The
  "genuinely undefined" case is exactly the one the clamp resolves in the wrong direction, so a clamp
  shipped as written is **not free**: it takes the winner and the loser together. If the clamp is
  adopted, the inside-a-prior-day-zone band needs its own answer rather than falling through.
  · **QQQ 11:00 and IWM 11:26 would still be refused** — both sit inside the clamped band — even
  though they are the two that ran 75 % and 98 % of the way to target. So the clamp does **not**
  address most of what F56 measures; it is a precedence fix, and the width question stays open on its
  own evidence (run 23: 94 % of candidate pullbacks refused desk-wide).
  Caveats: one session, four cases, spot basis, and the two open cases could still reverse before the
  close. This is evidence for the user's decision on F56/F58, not a calibration.


- **F59 (2026-09-08 13:40 ET, PARTLY fixed — the reporting half is deployed; the gate itself is a
  proposal for the user)** **A real, liquid contract existed and the desk refused the trade on a
  synthetic price that missed the floor by one tenth of a cent.** IWM's PM high finally broke at 13:30
  (15m bucket 13:15–13:30 closed 295.97 > PMH 295.91 — verified against the banked 1m tape, and the
  2m bar ending 13:30 ran 295.87–295.97 so the F20 retest of 295.91 is real). The read minted
  `pm_break` → `pm_retest` → and then **`skip_no_contract`: "no strike prices between $0.20 and
  $0.60 (V1)"**. That statement is about the **model**, not the chain:
  · `session.py` picks the strike with `PremiumModel.pick_strike`, Black–Scholes at the day's sigma.
  Today's sigma is **0.1203**. At spot 295.91, 13:30, 2.5 h to the 16:00 expiry, the model marks the
  IWM **296 call at $0.199** — **$0.001 under the `premium_floor` of $0.20**. `pick_strike` breaks out
  of its walk the moment a mark falls under the floor, so it collected **zero** candidates and returned
  `None`. The 297 call models $0.009.
  · The **real** 0DTE chain at the same moment (CBOE, spot 295.87): **IWM 296C bid 0.24 / ask 0.25**,
  **volume 70,329**, OI 2,635, IV 0.1346, delta 0.43 — squarely inside the band, and the most heavily
  traded call on the sheet. The live picker would have bought it. Replay reproduces the refusal
  byte-identically, so this is deterministic, not a glitch.
  · **The model is the gatekeeper for whether the real chain is ever consulted.** The runner only asks
  the venue for a contract after the read emits `fire`; a `skip_no_contract` ends the touch inside
  `session.py`. So a cent of model error is a veto over a real trade. This is the same root as
  **F51** (model sigma 0.1203 vs the traded IV 0.236 on QQQ's actual fill) but with a much sharper
  consequence: F51 mis-*prices* a trade the desk still takes, F59 *cancels* it.
  · **Why IWM is the symbol it bit.** `runner._sigma(symbol)` **ignores its `symbol` argument** — it
  caches per symbol but returns one index-wide number, `^VIX1D` (fallback `^VIX`×1.3, then 0.20), for
  SPY, QQQ **and IWM** alike. VIX1D is an S&P 500 measure; the Russell is the more volatile index, and
  today the real IWM 296C printed IV 0.1346 against the model's 0.1203 — ~11 % low, which is all it
  took at a hard floor. Compounding it: IWM's $1 strikes at 295.9 with 2.5 h left step **0.95 (295,
  ITM) → 0.25 (296) → 0.04 (297)**, so the $0.20–$0.60 band spans *at most one strike* on this symbol
  late in the session. The model has to be right to the cent or it whiffs entirely.
  · Cost today: the setup's target was 295.955 (PDH zone bottom) and spot printed 296.03 in the very
  bar of the refusal, so the trade was an immediate spot winner — but in **premium** terms the 296C
  was ~0.25 at 13:30 and ~0.245 at 13:36 with spot 296.00, i.e. roughly flat, no +50 % trim. So the
  honest reading is *a real trade was cancelled for a bad reason*, not *a large P&L was lost*. The
  setup keeps **touch 1 of 2**, so one more retest is available today — and the model will refuse it
  harder, since decay only pushes the 296 mark further under the floor and 297 is worthless.
  **Fixed this run (reporting only, no gate changed):** the refusal now says whose price it is
  ("no strike **MODELS** between $0.20 and $0.60 (V1) — modelled premium at sigma 0.1203, not the live
  chain") and is recorded on the setup with `note_once` so it reaches the Armed page and the phone.
  `skip_no_contract` was **already** in the runner's headline list from F57, but `session.py` used
  `note` rather than `note_once`, so the setup's `_skipped` stayed `None` and the clause could never
  fire — IWM's headline read *"waiting for the 1st/2nd 2m pullback into the EMA13 (touches 1) · EMA
  stack bull, trend"* with no hint that the pullback had been turned away. Same defect class as F53
  and F57: a silent gate.
  **Follow-up after the 13:44 redeploy — it cost the whole setup, not one touch.** The re-simulated
  read shows the retest was refused **twice** (13:30 and 13:40, both `skip_no_contract` with the new
  honest wording), and the 13:42 touch was `late_touch` — beyond `pullback_max_touches` = 2, watch
  only. So `pm_break_up@13:15` ends the day **touches 3, entries 0**: the model burned both tradable
  touches of the only PM break the desk got today, and no further entry is possible on it. Residual
  (noted, not changed): the headline clause still does not show here, because `session.py` clears
  `_skipped` on *every* real touch (line 488) before the late-touch branch, so touch #3 wiped the
  refusal touch #2 had recorded and the summary reads a bare "touches 3". That is F57's intended
  "a real touch clears it" semantics; whether an exhausted setup should keep saying *why* it never
  entered is a wording question for the user, not a defect.
  **Proposed, NOT built (user's call — this is the money path):** (a) let the **live chain** decide
  when the runner is live — have the read emit the fire with a `needs_contract` flag and let the
  existing live picker (which already applies `chase_cap_mult`) accept or refuse against the real ask,
  so the model prices the *simulation* but never vetoes a *trade*; or, much cheaper, (b) make
  `_sigma` actually per-symbol (`sigma_source: "chain"` already exists as a setting value and is
  unimplemented in `_sigma`) — reading the day's ATM IV off the 0DTE chain would have marked the 296C
  at ~0.22 and taken the trade; or (c) widen `premium_floor` for $1-strike underlyings. (a) is the
  structural answer; (b) is the one-symbol fix. Cross-refs **F51** (same sigma error, milder effect)
  and the open F30-family question of which premium series is authoritative.

- **F60 (2026-09-08 14:10 ET, FIXED — the headline promised a pullback the setup could no longer
  take).** With IWM's `pm_break_up@13:15` exhausted (touches 1 and 2 both refused by F59's model
  price, touch 3+ `late_touch`), the Armed + phone line still read *"scenario 3 (bounce PDL) → calls ·
  **waiting for the 1st/2nd 2m pullback into the EMA13 (touches 8)**"*. Two things were wrong in one
  sentence: the desk was not waiting for anything tradeable on that setup — every further touch is
  watch-only under D9/P6 — and the touch count belongs to `pm_break_up@13:15` while the scenario label
  comes from `bias` (scenario 3, confirmed 09:45): per **F24** the count is taken from the newest live
  setup in the bias direction, which today is not the setup the label names. Fixed (reporting only,
  `47b0460`): once `touches >= pullback_max_touches` the line reads *"pm_break_up@13:15: its first 2
  pullbacks are spent (touches 8) — further touches are watch-only (D9/P6)"*, naming the setup the
  count belongs to. The same commit puts the 09:25 pre-open result (`pmh`, `pml`, `complete`) on the
  snapshot's `team2` block, so completion can be checked without parsing the sheet string. No gate,
  threshold, size or money path changed; Team2 tests 57 passed, and `test_team2_runner.py` now asserts
  both wordings (the E3/B9/E4 and no-trade-zone clauses are judged on either).

- **F61 (2026-09-08 14:10 ET, FIXED 2026-09-08 evening — `Setup.touches` (the D9 allowance) is incremented only by a PRICED
  pullback: a fire or an engulfing skip; `skip_no_contract` and the location/regime skips count as `opportunities` but do
  not spend; the read exposes `pullbacks ≥ opportunities ≥ touches ≥ attempts`. `test_a_plumbing_refusal_does_not_spend…`;
  a plumbing refusal WAS spending the method's D9
  allowance).** `session.py` increments `s.touches` **before** it asks the premium model for a
  strike, so a `skip_no_contract` — a refusal that says nothing about the tape — consumes one of the
  two pullbacks D9/P6 allows. This is the exact inverse of the principle **F18** already established:
  a dip that is "not a tradeable location" (`skip_no_trade_zone`, `skip_range_confirmation`) returns
  *before* the increment and does **not** spend the allowance. Today's cost is concrete: IWM's
  `pm_break_up@13:15` spent touch #1 (13:30) and touch #2 (13:40) on the model's $0.199 mark for a
  296 call that was really 0.24/0.25 with 70,329 contracts traded (F59), and from 13:42 the setup was
  permanently watch-only — 9 touches, 0 entries, on the only PM break the desk got today. Proposal:
  move the `pick_strike` failure branch above `s.touches += 1`, i.e. treat "we could not price a
  contract" like F18's non-locations, not like a pullback the desk passed on. Note it is only a
  partial remedy for F59 — it preserves the allowance but still takes no trade — and it does change
  which touches can enter, so it is the user's call, not the watch's. `skip_engulfing` should keep
  consuming (that *was* a pullback, just a bad bar).

- **F62 (2026-09-08 14:10 ET, FIXED 2026-09-08 evening — a pullback is an EPISODE: after a counted contact the setup is
  `_departed=False` until a 2m close at least `pullback_reset_atr` (0.5) × ATR off the EMA13 on the trade's side; contacts
  before that are one `same_pullback` note, not new pullbacks. Chosen from the method's "pullback = leaves and returns"
  reading and the Codex caution NOT to tune it to today's two entries: on the synthetic drift day it is 4 episodes vs 16
  bar-contacts (`test_a_drift_on_the_ema_is_one_pullback_not_many`); today's IWM 13:42–13:54 would have been one. Knob
  `techniques.team2.pullback_reset_atr` (0 = the old every-bar behaviour); a touch HAD no reset, so a drift on the EMA13
  counts as many pullbacks).** `touched_ema` is judged bar by bar with no requirement that price ever
  *leave* the EMA13 band between touches, so a sideways drift sitting on the EMA prints a fresh touch
  every 2 minutes. IWM 13:42–13:54: six consecutive 2m closes oscillating 295.86–296.04 around an
  EMA13 of 295.86–295.93 minted touches #3 through #8 of the same setup. The method's words are
  "**the first or second pullback**" — a pullback is an event (price extends away from the 13, then
  returns), not a state. A6/`pullback_max_bars` guards only the opposite case (price closed on the
  *wrong* side of the EMA for too long = consolidation). Proposal: require a reset before counting a
  new touch — e.g. one 2m close at least k×ATR clear of the EMA13 on the trade's side, or N bars off
  the band. **Caution, from today's own tape:** QQQ's two winners were touch #1 at 10:02 and touch #2
  at 10:06, four minutes apart on the same retest of 716.90 (+65.6 % model P&L combined); a reset rule
  set too wide would have refused the second one. Any reset threshold must be judged by the sweep
  against those two entries before it is shipped. Interacts with **F61** (both decide what "spends"
  the D9 allowance) and with **F60** (which only reports the spend honestly).

- **F63 (2026-09-08 14:40 ET, MITIGATED 2026-09-08 evening — the cause was found and removed: the 14:24:01 stop is the
  Claude desktop package update ("Relaunch to update", 1.49585) stopping `CoworkVMService`; the engine was a child of that
  process tree (third such stop). It now runs under the Task Scheduler (`scripts/install-watchdog.ps1`: `ZargarWatchdog`
  every 3 min + at logon starts it when :8420 is silent, `ZargarRestart` on demand is the deploy path) — recovery ≤ 3 min
  instead of "whenever someone notices". The fire-during-downtime gap itself is unchanged: a bar the engine never saw
  is still not traded (by design — never a synthetic fill) and the catch-up read journals it `haltedAtFire`-style as before;
  a fire that happens while the app is DOWN is
  neither traded nor recorded).** The app died at 14:24 ET with no traceback and no shutdown line and
  was restarted at 14:33 (9 minutes dark; the third such unexplained mid-session stop, see the
  2026-09-04 pattern). Nothing was lost today — the only events in the gap were `late_touch` and one
  `skip_no_trade_zone` — but the restore path means a *fire* in that window would have been silently
  swallowed. `PlanRunner.arm(restored=True)` replays every banked bar of the day with `journal=False`;
  `_fire_rest` maps `not journal` to `trade.status = "alert"` (planrunner.py:2271), and the block that
  follows drops replay-minted `alert` trades the live record never had (`phantom_dropped`, added for
  EM's GOLD 2026-08-25 case). Meanwhile `Team2Runner._act`'s `_seen` cursor has already advanced past
  that event, so the next live bar will not reconsider it. Net: no order, no trade row, no journal —
  the fire exists only in the pure re-simulation the read shows. Team2 is more exposed than EM here
  because its whole read is re-simulated each bar rather than carried in an incremental tracker.
  Proposal (shared `zargar/execution/planrunner.py`, so **not** built by the watch): during a restore,
  distinguish "the replay minted a trade the live plan contradicted" (drop it — the GOLD case) from
  "the replay minted a trade in a window where no live plan existed" (the process was down), and for
  the latter either fire it when it is still inside the entry window and the level is still valid, or
  record it to the counterfactual ledger so a bug-missed trade is at least measured. Until then, a
  restart is a silent trade filter and outage minutes should be treated as unmonitored, not as
  "nothing happened".

- **F64 (2026-09-08 14:40 ET, NOT fixed — cosmetic; a mid-session restart journals the catch-up
  window twice).** The 14:33 boot restored every Team2 plan **twice** — `team2 runner restored 3
  armed plan(s)` at 11:33:34 and again at 11:33:48 PDT, the second following EM's `re-armed 45
  plan(s) after restart` pass — and the three events the outage had left unprocessed were journaled
  once per pass: IWM bars 14:26 and 14:30 (`late_touch`) and 14:32 (`skip_no_trade_zone`) each have
  two `events` rows (ids 29750/29794, 29754/29800, 29755/29803). Steady-state operation is
  single-stream (the 14:34 bar journaled once) and the read itself is unaffected — replay parity was
  exact on all three symbols — so no decision was doubled. It matters only for anything that *counts*
  journal rows: skip tallies, touch counts and F28-style audits over `TechniquePlanRead` /
  `TechniquePlanTriggerSkipped` will over-count on any day with a mid-session restart, and this desk
  restarts to deploy most runs. Shared restore code, so proposal only: either seed the runner's
  `_seen` cursor from the persisted event log on restore, or make the catch-up journal idempotent on
  (runId, event, bar ts).


- **F65 (2026-09-08 15:05 ET, NOT fixed — proposal; a FAILED pm-range break never dies, and the level
  can never be re-armed).** `session.py` marks `scenario_*` setups dead on a bias flip (D10, line 259)
  but a `pm_break_up` / `pm_break_down` setup has **no death condition at all** — `s.dead` is never set
  for them anywhere in the file. Today's IWM: the 13:30 15m close above the pre-market high 295.91
  armed `pm_break_up@13:15`; price never made the PDH zone, fell back inside the pre-market range and
  by 15:05 sits at 295.45, ~0.46 below the broken level, with the read's own events twice saying so
  (`skip_no_trade_zone` 13:58 "entry 295.76 sits inside the pre-market range", again 14:32 at 295.84).
  The method already calls that dead: **L2.6** makes "a 2m close under PMH" the stop for the
  break-retest trade, and F20's own note says "deeper back inside the range the break has failed and
  no entry is taken". Two consequences. (1) Reporting: the failed setup stays *live*, so under F24 it
  owns the Armed/phone headline — IWM's line all afternoon has been about a setup that died at 13:58.
  (2) Money path, the real one: `pm_up_done` / `pm_dn_done` (line 198) are day-scoped, so **only one
  PM-high break setup can ever exist per day**. IWM's is exhausted at 14 touches (F62's no-reset
  counting did that in twelve minutes), so a *second, genuine* 15m close above 295.91 into the close
  could not create a fresh setup and could not be traded — the level is spent for the day on the
  strength of one failed break. The shared engine already has the concept Team2 is missing:
  `TriggerTracker` retires a level after `max_false_breaks` (=2, `marketstructure/tracker.py:338`),
  and that threshold is already in Team2's rules payload — unused by `session.py`. Proposal: kill a
  `pm_break_*` setup on the first 2m close back inside the pre-market range beyond tolerance (L2.6's
  own stop), and clear the corresponding `pm_*_done` flag so a later confirmed 15m close beyond the
  level arms a fresh setup, capped by `max_false_breaks`. Changes which setups can fire → **user's
  call**, not built by the watch. Judge the cap on the sweep: a fast wick back inside must not kill a
  break that is merely retesting (that retest is F20's small-size L2.6 entry), so the death test wants
  the *close*, not the low.

- **F66 (2026-09-08 15:33 ET, FIXED same run — reporting; the headline kept promising a pullback entry
  after the 15:30 cutoff).** At 15:33, three minutes past the last-entry time, all three Armed rows
  still read "waiting for the 1st/2nd 2m pullback into the EMA13 (touches 0) … no entry until the
  stack turns bull … the last pullback sat inside the pre-market range" — a sentence about a trade
  that could not be taken for the rest of the day. `session.py` knew: it had minted `skip_last_entry`
  on the 15:32 close on all three symbols (F26), and the trigger rows already carried
  `windowOpenNow: false`. Only the one line the Armed page and the phone show was still speaking as
  if the next EMA13 touch were live — the same class as F53 (silent stack gate), F57 (silent
  no-trade-zone refusal) and F60 (spent allowance): a gate that stops the desk in silence. Fixed in
  `runner.py`'s snapshot: past the cutoff the state line becomes "past 15:30 — no new entries today,
  flat by 15:45 (D6/C3)", and after the flatten "the desk is flat for the day (C3)"; the "no entry
  until…" and "no-trade zone" clauses are dropped with it, since they answer a question the clock has
  already closed. An open position keeps its own line and gains " · sold at 15:45 whatever the read
  says (C3/D-1)" — on the phone at 15:40 that is the fact that matters. Read from the session's own
  `skip_last_entry` event, not the wall clock, so a replay of the day says exactly the same thing.
  **Reporting only — no rule, threshold, gate, size or money path changed.**

- **F67 (2026-09-08 16:20 ET, PARTLY fixed — the desk's own History tab now carries the day's grade;
  the shared Armed > History half is a proposal).** After the 16:00 disarm the Team2 day was
  **invisible and, where visible, wrong**. Two separate defects, both post-close:
  (1) **The shared Armed > History list never showed today's Team2 plans at all.** It is ordered by
  `created_at` and capped (`technique/service.py::armed_history`, default 50 rows), and Team2's plans
  are always built the *previous* session — today's were built Friday 2026-09-04 17:34 ET — so 50
  plans built Sep 7–8 by EM and tips pushed all three off the window. The page's own day header read
  *"2026-09-08 · 42 plan(s) · 10 fired · 0.00 realized"* with no SPY/QQQ/IWM row in it. Ordering by
  `plan_for` alone does not fix it (Sep 8 has 45 rows; within a day Team2's are still the oldest by
  build time) — it wants a bigger window or a `planFor` filter. **EM's `zargar/technique/` → proposal,
  not built by the watch.**
  (2) **The Realized column is gross.** It renders `state.realizedPnl`, which is
  `(fill − avg_fill) × qty × 100` summed over the plan's trades — for QQQ today **−$18.00**, while the
  Team2 Practice book actually went **10,000.00 → 9,934.16 = −$65.84**: $47.84 of commissions
  (23 contracts × 2 legs × $1.04) on two round trips whose gross difference was $18. The net number
  already exists on the same row (`state.scorecard.realizedPnl`, F43), and F32 made the *halts* net
  for exactly this reason — the record the desk grades itself by is the one place still reading gross.
  A shared-UI one-liner (prefer `scorecard.realizedPnl` when present) → **proposal**.
  **Fixed the Team2-owned half:** `Team2Service.runs()` now returns a `result` block per plan (fires,
  matched vs what the read wanted, the model's % sum, the book's **net** and gross, and the skip
  tally), and the Team2 page's History tab renders it as a "How it went" column — *"2 trade(s) ·
  −65.84 book · read +65.6%"* for QQQ, *"no trade · 6 refused"* for IWM, with the commissions and the
  per-skip breakdown in the tooltip. That is the F37 divergence readable at a glance on the desk's own
  page, for any past session. **Reporting only — no rule, threshold, gate, size or money path
  changed.**

- **F68 (2026-09-08 16:45 ET, FIXED same run — reporting; the day's own grade counted its state notes
  as refusals).** F67's new "How it went" column shipped counting *every* `skip_*` row in the
  scorecard as a setup the method turned down. Three of them are not: `skip_last_entry`,
  `skip_event_day` and `skip_loss_cap` are minted **once per session** by `session.py` to say what
  state the day is in (F26 added them precisely so a day that goes quiet after 15:30 does not look
  like a day with no setups). So today's closed rows read **SPY "no trade · 2 refused"** where exactly
  one setup was refused (the 10:00 no-trade-zone, plus the 15:32 cutoff note) and **IWM "6 refused"**
  against five real refusals (2 × no contract, 3 × no-trade-zone). A desk grading its own day would
  over-count how often the method said no — on the very number the F62/F65 discussion about refusal
  rates turns on. Exactly F28's principle one layer up: *skip counts must mean skips*. Fixed in
  `techniques/team2/service.py`: `DAY_NOTES` names the three once-a-session rows, the result block
  gains **`refused`** (the tally a human should read) and **`notes`** (which day states applied); the
  raw `skips` map is unchanged, so nothing is lost and older rows without `refused` still render from
  the raw sum. The History column now reads *"no trade · 1 refused"* / *"5 refused"* with *"day: last
  entry"* in the tooltip. **Reporting only — no rule, threshold, gate, size or money path changed.**
  57 Team2 tests pass (F68 assertions in `test_team2_runner.py`).

- **F69 (2026-09-08 16:45 ET, FIXED 2026-09-08 evening — shared `main.py`: rotation 50 MB × 10, `httpx` logger at WARNING
  (its per-poll INFO line was 99 % of the file; F45's CBOE 429 storm still surfaces as WARNING/ERROR), a startup line with
  pid/parent/argv and an atexit/SIGTERM/SIGBREAK goodbye line so the next unexplained stop leaves evidence;
  the app log KEPT ~50 minutes of history,
  so a post-mortem past lunchtime is impossible).** Measured this run: of **5,430** lines written in
  **13.5 minutes**, **5,378 (99.0 %)** are `INFO httpx HTTP Request` lines from the polling loops
  (4,316 Yahoo 1m, 635 Alpaca/OPRA, 406 CBOE). The app's own content is ~52 lines in the same 13.5
  minutes. `main.py:20` rotates at `maxBytes=5_000_000, backupCount=3`, so the entire retained window
  is **~50 minutes** — which is why this watch has repeatedly found the 09:25 pre-open lines already
  rotated away (runs at market-watch.md:93, :232, :1622), and why a post-close review cannot read what
  the 09:30 open logged. Two independent options, neither built here because both are shared:
  (a) **`backupCount` 3 → 20** (~5 hours of history, ~100 MB of disk) — loses no information at all,
  one number; (b) `logging.getLogger("httpx").setLevel(WARNING)` — a ~100× shrink, but it deletes the
  request trace that diagnosed **F45**'s CBOE 429 storm, so (a) is the recommendation and (b) only
  alongside it. `backend/zargar/main.py` — shared engine, **user's call**.

- **F70 (2026-09-09 09:00 ET, PROPOSED — shared feed, not built here).** `Quote.prev_close` is **one
  session stale during pre-market**, so every day-change on the desk reads against the wrong base
  between the close and the next 09:30 open. Measured this run at 09:03 ET: `/api/quotes` returned
  SPY `prevClose 770.19` / `regPrice 765.96`, but 770.19 is the **2026-09-04** close (the `bars` 1d
  table confirms it) and 765.96 is 2026-09-08's — the actual prior close. CBOE agrees with the tape:
  `/api/options/SPY/expiries` reports `prevClose 765.96`. Cause: `brokers/yahoo.py:287` takes
  `chartPreviousClose` from the v8 chart meta, and before the open Yahoo's 1d chart is still
  **yesterday's** session, whose "previous close" is the session before that. SPY therefore shows
  about **-0.86 %** pre-market where the truth is **-0.29 %** (QQQ and IWM the same way). Once the
  09:30 bar prints, Yahoo's chart rolls to today and the value self-corrects, which is why this has
  never been caught in-session. **Team2's own numbers are unaffected** — the gap rule and `dayType`
  come from the plan's `lastClose` and the 1m bars (today: SPY `lastClose 765.99`, `openPrice 763.70`
  → `gap_down`, correct), and `techniques/team2/` never reads `quote.prev_close`. Fix would be one
  clause in the shared Yahoo poll (when `session != "regular"` and the chart day is not today, prefer
  `regularMarketPrice` as the day-change basis) — `backend/zargar/brokers/yahoo.py`, shared engine,
  **user's call**.

- **F71 (2026-09-09 09:30 ET, FIXED same run — reporting; a level price had already broken through
  still read as a percentage "away" from it, with the sign inverted).** The Team2 plan panel's "Now:"
  line renders each pseudo-trigger as `${label} ${sign}${distancePct}% away`, and `distancePct` is
  `(level − price) / price` — direction-blind (`techniques/team2/runner.py:941`, the same formula the
  shared `PlanRunner` uses). On a **short** row that sign is backwards: price *below* the level, i.e.
  the level **already broken**, yields a **positive** number. Measured live at 09:36 ET on a morning
  when two of three symbols gapped straight through their PDL: SPY at 763.64 with its PDL zone bottom
  at **765.14** — 1.50 (0.20 %) *through* the level, waiting only on the 09:45 15m close — read
  **"+0.20 % away"**, while QQQ at 716.92 with its PDL bottom at **715.57**, which genuinely had 1.35
  still to fall, read **"−0.19 % away"**. The broken level looked *further off* than the unbroken one.
  Descriptive only — no rule, gate, size or money path reads `distancePct`; the trigger itself is
  correct (`ArmedTab`/`ArmedPage`/`DashboardPage` sort on `Math.abs`, so ordering was never wrong).
  **Fixed** in the Team2 branch of `frontend/src/components/technique/ArmedDayPanel.tsx` with a
  direction-aware `team2Distance()`: a break row whose price is already through says *"price is
  already through, waiting on the 15m close"*, one that is not says *"X.XX % away"*, and a setup row
  says *"X.XX % from the level"* (magnitude only — the sign carried no meaning there either).
  **The signed field is unchanged**, so the shared Armed page and the phone's Now view keep rendering
  it as "level X % above/below" / "needs to rise/fall X %", which is factually right for any
  direction. v0.7.23.
  - **Shared half, NOT fixed (proposal).** `execution/planrunner.py:318` and `:789` compute the same
    direction-blind number for EM's real triggers, and `ArmedPage`'s `DistanceCell` turns it into
    *"needs to rise 0.20 %"*. For a **breakdown/breakout** trigger whose price is already through the
    level, "needs to rise" is wrong in the same way — the trigger is satisfied on price and waiting
    on its confirmation. Shared engine + EM surface → **user's call**.

- **F72 (2026-09-09 09:46 ET — GUARD BUILT 10:15 ET, v0.7.24; the strategy question stays OPEN).**
  On a gap-down morning the planned target can already be **behind price when the scenario arms**,
  and a *first* entry would then exit on its very next 2m bar. Measured at 09:46 ET, minutes after
  the 09:45 15m close armed all three symbols short: **SPY** `scenario_4 break PDL`, anchor 765.14,
  **target 764.75** — with SPY trading **763.7**, already 1.05 *below* its own target. **IWM**
  `scenario_4`, anchor 294.26, **target 293.56**, with IWM at **293.2**. (QQQ's `scenario_2 reject
  PDH` target 716.50 is still ahead of price at 717.3, so it is unaffected.) The targets come from
  the plan's next prior-day level (`target_lookback_sessions=10`); a gap that opens *through* the
  zone consumes the room before the confirmation even arrives.
  - **Why a first entry cannot dodge it.** `techniques.team2.hod_target` is **`reentry`**, so the
    X3b running-LOD retarget in `session.py:556` is gated on `hod_target == "always" or s.entries >= 1
    or trades` — all false for the day's first entry, which therefore keeps `s.target`. The exit
    check at `session.py:313` is `hit = b2.low <= p.target` for a short, which is **already true**,
    so the position closes on the first 2m close after it opens.
  - **And it books the wrong sign.** For a short, a target *above* the entry is a loss: the model
    would sell the put at spot 764.75 against an entry near 763.8 — a real modelled loss recorded
    under a `would_exit`/`exit` labelled "target reached". So the day's grade would read a stop-out
    as a target hit.
  - **Not yet reached today** only because both setups are still gated on the EMA stack ("no entry
    until the stack turns bear, E3/B9/E4") with `touches 0`. If the stack turns bear this session,
    SPY and IWM can hit this.
  - **BUILT 2026-09-09 10:15 ET (v0.7.24) — the safety guard only, not the strategy.** A trade with
    no room is refused rather than taken: `scenario.target_is_ahead()` is one predicate (strictly
    above for a long, strictly below for a short; `None` and an unjudgeable spot stay allowed;
    **equality is refused**), and it is applied at both money-path entrances.
    **(1) The read** (`session.py`) refuses the ENTRY with `skip_target_behind`. The target
    resolution was hoisted above the strike pick, so the refusal costs no `pick_strike` call and —
    like the other structural refusals (F18) — **does not spend the D9 pullback allowance**; only a
    priced fire does (F61). **(2) The runner** (`runner.py`) falls back to the SETUP's target when a
    fire carries none, which could put the stale level back on a live trade; it is now **dropped**
    (`target_dropped`). That is what closes the **quote-watch** exposure — `target_breach` runs on
    the ~2s watch (planrunner 2b), so a wrong-side target would have sold the whole position on the
    FIRST live print, before any 2m bar closed. No target is safe (candle stop, premium stop, trims
    and the 15:45 flatten still manage the trade); a wrong one is not. Surfaced per the F57/F59
    lesson: journalled as a trigger skip, stated in the Armed/phone headline, given timeline icons.
    **Existing-position protection is unchanged** — an open position keeps its target exit, premium
    stop, candle stop, trims and flatten, pinned by tests. 28 new tests in
    `tests/test_team2_target_guard.py`, every case mirrored long/short; 94 Team2 tests pass.
    **Deliberately NOT done:** the EMA-stack gate is not relied on (it was only incidentally holding
    this off), and `hod_target` was **not** switched globally.
  - **Live status 2026-09-09 10:20 ET: deployed, not yet exercised by the tape.** SPY's target
    (764.75 at 763.8) and IWM's (293.56 at 292.8) are still behind price, so both would be refused,
    but no qualifying pullback has reached the guard yet — IWM's are being turned away earlier by the
    no-trade zone (V6/B5) and SPY/QQQ have not produced one with a bear stack. QQQ is unaffected
    (target 716.50 below price 718.75 — correctly ahead for a short), which is the selectivity check.
  - **STILL OPEN — the strategy decision (the guard only stops the bad trade; it does not recover a
    good one).** Three replacement options, none built:
    **(a) Refuse and move on** — what the guard does today, made permanent policy: no room means no
    trade on that setup for the session. Safest, zero new knobs; the cost is that a genuine gap-down
    trend day produces *no* Team2 trade at all, which is the F72 morning itself.
    **(b) `hod_target=always`** — one settings change, so the running LOD/HOD retargets first entries
    too, with the existing `hod_target_min_atr=1.0` room test as the guard. Recovers the trade and
    reuses machinery already proven on re-entries; the cost is that every first entry now targets an
    intraday extreme instead of a planned level, which is a real change to how the method exits and
    should be swept before it is trusted.
    **(c) Re-derive the target at arming** from the next prior-day level *below current price*
    (rather than below the zone). Keeps targets structural and planned; the cost is new code in the
    level sheet and the risk of reaching for a level far away on a big gap. **User's call.**

- **F73 (2026-09-09 10:40 ET, FIXED and deployed, v0.7.25 — F71's fix shipped as dead code).**
  F71 (v0.7.23, yesterday's 09:45 run) added a direction-aware `team2Distance()` to `ArmedDayPanel`
  so a break row already through its level would read *"price is already through, waiting on the 15m
  close"* instead of a sign-inverted percentage. It never fired once. The branch is gated on
  `t.kind === "break PDH" || t.kind === "break PDL"` — the human labels from `SCENARIO_LABEL` — but
  the pseudo-trigger the API serves carries `Setup.kind`, which is `scenario_1..4` /
  `pm_break_up` / `pm_break_down` (`session.py:37`). Measured live at 10:38 ET on the served bundle:
  SPY's trigger came back `{"kind": "scenario_4", "direction": "short", "distancePct": 0.211}` —
  already 1.61 through its PDL — and the panel rendered the generic fallback *"— 0.24% from the
  level"*, exactly the wording F71 was written to replace. Fixed by matching the kinds the desk
  actually emits (`TEAM2_BREAK_KINDS`); the `through` test itself was correct and is untouched.
  **Reporting only — no rule, threshold, gate, size or money path changed.** The lesson is the
  reusable one: F71 was verified at the *data* level (both signs measured off the API) and in the
  bundle, but never on screen, and the on-screen check is the only one that would have caught a
  predicate that never matches. Verified on screen this time.

- **F74 (2026-09-09 10:35 ET, NOT fixed — proposal; a reclaimed scenario anchor keeps a live short,
  and only the EMA-touch entries are missing the side test).** D10 deliberately makes the bias
  sticky: `ScenarioTracker.on_close` flips a scenario 2/3 only on a 15m close through the *far* side
  of the range (`scenario.py:146-149`). QQQ today shows what that costs. The 09:30 15m bar closed
  716.96 under the PDH zone bottom 717.47 and set `scenario_2 reject PDH → puts`. Every 15m bar
  since has closed **above** that level — 718.86, 718.95, 718.29, 717.89 — and QQQ has held above it
  for 45 minutes, but a flip needs a close above 721.89 (or below 715.57), so the short setup is
  still live, still owns the Armed headline, and `bias.history` still has exactly one entry. The
  gap is narrower than it first looks, and that is the useful part: the level-retest entry **is**
  side-gated (T2, `session.py`: a short needs `b2.close < s.anchor`), and so is "break & base" (T7).
  It is the **EMA13 / EMA48 touch entries (T1/E5) that carry no anchor-side test at all** — they ask
  only for a touch and the stack. So on a day where the stack turns bear while price sits inside the
  4.42-point band between the reclaimed anchor and the flip level, the desk would buy puts with the
  rejection it is trading on 1–3 points *below* price. **F72's new guard does not catch it**: QQQ's
  target 716.50 is genuinely below spot, so it reads as room. Nothing was at risk today — QQQ is
  double-gated by a bull stack (strength 3) and by the pre-market no-trade zone (V6/B5; PM
  713.50–720.67 means an entry needs price above 720.67, by which point the anchor is 3.2 below) —
  which is also why this has not shown up before. Sibling of **F65** (a failed `pm_break_*` setup
  that never dies): both are "the setup outlived its premise". Options: (a) require the EMA-touch
  entries to sit on the trade's side of `s.anchor`, the same test T2 already applies; (b) kill a
  scenario setup after N 15m closes back through its anchor (the `max_false_breaks=2` already in the
  rules payload and still unused by `session.py`, per F65); (c) leave it — D10's stickiness is the
  method's own choice and the other gates cover it. **A rule change either way, so: user's call.**

## Theories to test

- T1 The 15m-close confirmation is the load-bearing rule (added by the author only in 2026 after
  years without it); expect it to cut fires by ~40% and raise win rate materially.
- T2 Range-day scenarios (reject PDH / bounce PDL) will underperform trend-day scenarios enough that
  the desk should start with scenarios 1 and 4 only.
- T3 "Ext hours on" EMAs matter mostly for the first 30 minutes (the 200 EMA otherwise has no
  history at 09:30); after ~11:00 RTH-only EMAs converge.

## Change log

- **2026-09-09 (market watch, run 35, 10:40 ET — v0.7.25)** — **F73 fixed** (reporting only): F71's "price is already through" wording was keyed to the labels `break PDH`/`break PDL` while the served pseudo-trigger carries `Setup.kind` (`scenario_4`, `pm_break_down`, …), so the branch never matched a single live row and every Team2 break setup fell back to a bare percentage; break rows now match on the kinds the desk emits, verified on screen. **F74 logged as a proposal** (rule change, user's call): a scenario 2/3 anchor reclaimed by later 15m closes keeps its setup live, and the EMA13/EMA48 touch entries — unlike T2 and T7 — have no anchor-side test. **F72's guard fired live for the first time** (IWM 10:32, `skip_target_behind`, target 293.56 above a 292.58 short entry) and replayed identically. Tests: 94 Team2 tests pass; frontend build green. No rule, threshold, gate, size or money path changed.
- **2026-09-08 (evening, after the Codex review — v0.7.13, one deploy; stamped 0.7.12 at first, renumbered because the Cartel desk's PR 13 took 0.7.12 on origin/main the same evening)** — **Hosting:** the 14:24 outage was the Claude
  desktop package update stopping its VM service with the engine inside its process tree; the engine now runs under the
  Windows Task Scheduler (`ZargarWatchdog` / `ZargarRestart`, `scripts/watchdog.ps1`), the log keeps days (F69), and the
  process announces start/stop. **Read integrity:** acted-on read events are recognised by FINGERPRINT (ts · event ·
  setup · touch · why) instead of list position, so an input moving under the recomputed read can neither re-fire nor
  skip an event (`read_rewritten` said once); the read's IV is locked per session from the 0DTE ATM chain and stamped
  (F51); the day premise is finalized on the 09:30 bar with the 09:25 estimate kept (F49). **Execution:** the plan target
  is an underlying condition on the quote watch, sold reduce-only at the fresh bid (F50). **Read:** pullbacks are episodes
  (`pullback_reset_atr` 0.5, F62) and only priced pullbacks spend the D9 allowance (F61). **Kept experimental:** F47, F56a/b
  (sweep variants only). **Governance:** twenty banked Practice sessions trigger a REVIEW, never a promotion (PLAN §3d).
  Tests: `tests/test_team2_integrity.py` (9) + the Team2/halt/exit/arming suites. Threshold changed: `pullback_reset_atr`
  0 → 0.5 (new), `sigma_source` vix1d → chain. No size, gate or money-path knob changed; Practice continues at
  $2,000 / 6 % / 10 % technique pause / 15 % book breaker.
- **2026-09-08 (market watch, run 32, post-close)** — **F68 fixed** (reporting only): the History tab's "How it went" column now counts only setups the method actually refused. `skip_last_entry`, `skip_event_day` and `skip_loss_cap` are once-a-session state notes (F26), and counting them as refusals made SPY read "2 refused" for one real refusal and IWM "6" for five; they now ride in the tooltip as day states. **F69 logged as a proposal** (shared, user's call): 99.0 % of the app log is `httpx` INFO chatter, so 5 MB × 3 rotation retains only ~50 minutes and a post-close review cannot read the open. Tests: 57 Team2 tests pass. No rule, threshold, gate, size or money path changed.

- **2026-09-08 (market watch, run 24)** — no code change. **F58 logged as a proposal**: V6's sizing ladder is only ordered when the PM range is nested inside the prior-day zones, and `sizing_bucket` resolves every other geometry to `none` — SPY's 10:00 refusal contradicts V6's own Full-size band. Also verified (negative result) that the PM window is exactly METHOD L2.1's 04:00–09:30 ET, so F56/F58 are rule questions, not a data defect. No rule, threshold, gate, size or money path changed.
- **2026-09-08 (market watch, run 25)** — no code change. Measured, on today's banked 1m tape, what each of the four no-trade-zone refusals actually did (spot basis) and worked F58's proposed clamp through them: it would have **allowed SPY 10:00** (target hit in the same minute, zero adverse excursion) but **also QQQ 10:16** (3.94 points against, target never reached), and would still refuse QQQ 11:00 and IWM 11:26 — the two that ran 75 % and 98 % of the way to target. So the clamp is a precedence fix that takes a winner and a loser together, and does not address the width F56 measures. Logged as a follow-up under F58. Also verified the desk-wide loss tally against the persisted rows (1 of 2, book basis): re-entries carry `#N` trigger ids so they group as separate positions, only X5 `+add` legs share one. No rule, threshold, gate, size or money path changed.

- **2026-09-08 (market watch, run 27)** — **F60 fixed** (`47b0460`, reporting only): once a setup has spent its two-pullback D9 allowance the Armed + phone headline says so and names the setup the touch count belongs to, instead of reading "waiting for the 1st/2nd 2m pullback into the EMA13 (touches 8)" on a setup that can no longer enter today; the snapshot's `team2` block also carries the 09:25 `pmh`/`pml`/`complete`. **F61 and F62 logged as proposals** (both money-path, user's call): a `skip_no_contract` refusal spends the D9 allowance although F18 already exempts "not a tradeable location" refusals, and a touch has no reset, so a drift sitting on the EMA13 counts as a fresh pullback every 2 minutes (IWM printed touches #3–#8 in twelve minutes). No rule, threshold, gate, size or money path changed.
- **2026-09-08 (market watch, run 31, post-close)** — **F67 logged; its Team2-owned half fixed** (reporting only): the desk's History tab now shows each plan's day result — trades, the book's NET p&l (after commissions) and the read's model % side by side, refusals in the tooltip — because after the 16:00 disarm the day was invisible in the shared Armed > History (ordered by build time and capped at 50 rows; Team2's plans are built the session before) and its Realized column reads GROSS (QQQ showed −18.00 against the book's −65.84). The two shared-side fixes are proposals for the user. Also deployed run 30's queued **F66** commit `ce8c543`. Tests: 57 Team2 tests pass. No rule, threshold, gate, size or money path changed.
- **2026-09-08 (market watch, run 30)** — **F66 fixed** (reporting only): past the 15:30 last-entry cutoff the Armed + phone headline says so instead of promising "waiting for the 1st/2nd 2m pullback into the EMA13", and an open position's line names the 15:45 flatten. Driven by the read's own `skip_last_entry` event so replays agree. Tests: 57 Team2 tests pass (new F66 assertions in `test_team2_runner.py`). No rule, threshold, gate, size or money path changed.
- **2026-09-08 (market watch, runs 28–29)** — no code change. **F63/F64** logged after a 9-minute unexplained outage (14:24→14:33 ET; a fire during downtime would be neither traded nor recorded, and the catch-up window journals twice), **F65** logged at 15:05: a failed pm-range break is never invalidated and `pm_up_done`/`pm_dn_done` are day-scoped, so one failed break spends the level for the session. All three are proposals for the user — no rule, threshold, gate, size or money path changed.
- **2026-09-08 (market watch, run 26)** — **F59 logged; its reporting half fixed.** IWM's 13:30 PM-break retest was refused `skip_no_contract` because the *modelled* 296 call marked $0.199 against the $0.20 floor, while the real 296C was bid 0.24 / ask 0.25 on 70,329 contracts — the premium model is a veto over a live trade, and `_sigma` returns one index-wide VIX1D for SPY, QQQ and IWM alike. Deployed (reporting only): the refusal now names the modelled premium and its sigma, and is recorded with `note_once` so it reaches the Armed + phone headline — `skip_no_contract` was already in F57's headline list but `_skipped` was never set, so the clause could never fire. **No rule, threshold, gate, size or money path changed**; letting the live chain (or a per-symbol sigma) decide is written up under F59 as a proposal for the user.
- **2026-09-08 (market watch, run 22)** — **F57 fixed**: the setup's current no-trade-zone / range-confirmation refusal is serialized on the read and stated on the Armed + phone headline, instead of the page reading "touches 0" while every pullback was refused. Reporting only — no rule, threshold, gate, size or money path changed.
- **2026-09-08 (market watch, run 19)** — `TechniquePlanRead` registered in the shared event contract and the contract test widened to scan `zargar/techniques/**` (F52). No rule, threshold or money path changed.
- **2026-09-08 (market watch, run 20)** — the plan summary's waiting line now names the silent E3/B9 stack gate and E4 chop gate when they block the setup (F53). Wording only; no rule, threshold, gate or money path changed. F54 logged as observation. Team2 page timestamps pinned to ET (F55) — display only.
- **2026-09-08 (market watch, run 21)** — F53's follow-up wording deployed (`f89e173`); no code change this run. F56 logged as a proposal (V6's no-trade zone swallows a wide pre-market day). No rule, threshold, gate or money path changed.

| Date | Change | Evidence | By |
|---|---|---|---|
| 2026-09-04 | **F41 + F42 fixed** (post-close): the nightly never mints/arms a second plan for a session that already has one (`skipped`, with `force` on plan-now as the manual rebuild), and the 09:25 completion leaves a plan whose session has not started alone. Both are the same root cause — the two Team2 jobs are weekday-gated, not trading-day-gated, so **Labor Day 2026-09-07** would have double-armed 2026-09-08 and blanked its plans that morning. No sizing, entry or exit rule changed | market watch 16:05 ET; `next_trading_day(2026-09-04) == next_trading_day(2026-09-07) == 2026-09-08` | Team2 desk |
| 2026-09-03 | Method codified v0.1 from 49 public posts; desk opened | `SOURCES.md` | Team2 desk |
| 2026-09-03 | D3 decided by the user: Team2 is a 0DTE technique; RiskGate gets a per-technique 0DTE policy (E6) instead of the hard-coded EM/tip ids. Engine is ENRICHED, not forked (PLAN §3b, E1–E12) | METHOD §7b/§7c, images INDEX | Team2 desk |
| 2026-09-03 | Completeness review before the build (PLAN §3c, groups A–H): added day-type classifier, target discovery, zone+EMA gate, range-day confirmation, 5m flag detector, pullback-quality gate, re-entry cap, concurrency cap; bank ext-hours bars from tonight, ^VIX/^VIX1D fetch, fee+slippage in the premium scorer, calibration vs the author's 9 documented trades, market calendar (half days); OPRA-only fires, flatten discipline; per-technique 0DTE policy caps; nightly arming ops; review/evolution loop; settings panel + page | audit of METHOD vs PLAN | Team2 desk |
| 2026-09-03 | **Build v0.1 landed** (PLAN P0–P3 partial, 43 checkboxes): shared primitives + Team2 package + runner (alert mode) + page + sweep. Build-time judgement calls, each a rule the sweep must vindicate: (1) entry mechanics live in ONE pure session walk (`session.py`) instead of `TriggerTracker` — parity by construction; (2) trims are decided on the MODEL premium (BS on the VIX proxy) live too — the execution scorecard must compare against the real premium before proposal mode; (3) the "new high/low of day" trim cue is expressed as +50%/+100% premium (author's own numbers), price cue not yet modelled; (4) range-day confirmation = price beyond the PM level on the trade's side; (5) the event-day gate is a plan flag from the manual macro list, off by default | tests: 35 Team2 + 14 primitives green; shared suites 239 green | Team2 desk |
| 2026-09-04 | **F12/F13 fixed**: `Team2Service.stamp_run()` writes the completed plan and the rules the session actually runs under back onto the plan run at the 09:25 pre-open, before any entry. Replay now reproduces the live session instead of re-deriving PMH/PML and the day type from later bars; historical runs stay frozen as they were | market watch 09:00 ET; `tests/test_team2_runner.py` asserts the stamp (fails without it) | Team2 desk |

- **F8 (2026-09-03, calibration)** Flat-IV Black–Scholes on the author's four fully documented trades
  (entry premium, entry/exit spot read off his charts): SPY 711c +137% model vs +122% reported; QQQ 472p
  +211% vs +166%; IWM 201p +187% vs +157%; SPY 648c +114% vs +100%. The model is **consistently 12–45%
  optimistic** (chart-read spots, exits taken before the extreme, real spread on the way out). Until the
  execution scorecard measures our own fills, read sweep gains with a ~0.8 haircut; losses (−20/−30% stops)
  are premium-defined and unaffected. Test: `test_premium_model_calibrates_to_the_authors_trades`.
- **F9 (2026-09-04, first live plan)** The very first plan the desk built for SPY (from the banked 15m bars of
  2026-09-03) put the PDH zone at 773.76–774.03 with "room up to 775.30". The author's own 2026-09-03 recap
  annotated the high at 774.03 and his pre-market plan said "room up to 775.29" (notes/x/images INDEX,
  `2095599035113693522-1.jpg`). Zone construction (L1.2) and target discovery (L3.1) reproduce his sheet to the cent.
| 2026-09-04 | **F17 fixed**: the kill switch no longer suppresses Team2's alert-mode read. `_fire_from_event`'s halt gate now applies to proposal/auto only (alert places nothing); an alert fire during a halt carries `haltedAtFire: true`. Restores live-vs-replay parity while the shared Practice portfolio is halted | market watch 10:00 ET; QQQ 10:02 fire lost to `halt_skip`; `tests/test_team2_runner.py::test_alert_mode_still_reads_the_tape_while_halted` fails without the fix | Team2 desk |
| 2026-09-04 | **Post-close audit (two fresh-eyes reviews, 26 backend + 26 UI items) — F46 batch, all built:** (1) Team2 runs the stale-exit re-price every RTH minute and flattens the BOOK on the clock at `flatten_min` and again on the way out of the session, whatever the read holds (a resting trim limit used to clamp the flatten and the shared close is 16:05, after 0DTE expiry); (2) `pick_contract` re-prices on the live NBBO before sizing/caps (was sized on the delayed ask); (3) the technique day-loss halt keeps a retired plan's net P&L (`_retired_pnl`, seeded at boot); (4) the premium stop and the halt marks trust only FRESH real-time option quotes; (5) an X5 add is judged with its base position, not as a second loser; (6) `isAdd`/`targetKind` survive a restart; (7) trim/exit read events name their setup and the runner routes by it; (9) a budget change re-derives the plan loss halt; (10) the double-arm guard reads the persisted rows; (11) replay prices the past with THAT day's IV; (12) defaults now express the shipped sizing (`zero_dte` 40 / $2,000; `maxContracts` follows the policy); (13) a trade's quote-watch stop is the line the entry leaned on minus one ATR, not spot ± ATR; (16) `_seen` advances per event; (19/20) D10's flip knob wired, F27's tolerance symmetric; (21) `execution.premium_stop_basis/min_ticks/fee_per_contract` defaults exist; (22) the entry window is judged on the bar CLOSE (the first eligible dip after the 09:45 close was refused); (23) `pnlPctPerUnit` beside the weighted %; (25) Alpaca never seeds the day range from Yahoo's 09:30 poll. Open on purpose: (8) `_seen` not persisted (rare), (17/18) `runner_exit`/`stop_candles`/`flag_tf_min` informational — no 5m flag detector yet, (24) `shrink_after_win` per symbol, (26) sizing computed twice per entry. UI: the phone timeline sees the desk-stopping events, the loss-limit tile shows the technique brake, book halts on the phone strip, Team2's Armed tab shows account/P&L/stop reason/bar age, chart bands from the settings, no chart rebuild per read event, touch-safe tooltip, Settings has a Risk & clock group + live-auto toggle, thresholds read-only on Plans, Team2 wording on the Armed page, phone CSS no longer hides Team2's status line | reviews 2026-09-04 post-close | Team2 desk |
| 2026-09-04 | **F40, F43, F44, F45 closed** (post-close sweep): a disarmed plan with a flatten in flight stays in a `_closing` map until every exit settles (its fill lands, the record closes, F38's seed also reads pre-fix rows by their exit fills); Team2 overrides the execution scorecard — the session read's model trades matched against the book's fills, unmatched rows named, skips counted, P&L net of fees — and writes it on the loss-halt disarm too; expired contracts leave the OPRA batch; the nightly chain sweep paces itself (`research.chain_snapshots.delay_s` 0.75, `retries` 2 with 3s/6s backoff) and warns when > 20% of the universe failed | post-close 2026-09-04 | Team2 desk |
| 2026-09-07 | **Team2 trades its own book from 2026-09-08: `Team2 Practice` ($10,000)** — the shared Practice book is archived (platform change by another desk, PLATFORM-RULES invariant 15: a technique's orders land only in its own book; `techniques.team2.default_portfolio` set). Consequences for the ladder: the 10% technique pause and the 15% book breaker are now percentages of Team2's OWN $10k, so the per-plan halt re-derived to $1,200 (6% x 2), the desk-wide loss tally and the retired-P&L tally already key on the book id; `risk.sim_require_cash` is on — a $2,000 entry must fit the cash on hand. Every 2026-09-04 figure in this file (equity $8.5k, −$454 day) refers to the archived book | other desk's notice 2026-09-07 | Team2 desk |
| 2026-09-04 | **F37–F39 closed** (run 13): the desk-wide loss cap counts the BOOK for any money-mode plan that routed an order and the model only for alert plans (never the larger of the two); the gate applies in money modes only and says which record it used; a disarmed plan's losers stay in the day's tally and are re-seeded from the persisted rows after a restart; zero/negative equity refuses an option entry with its own reason instead of failing open at 0 / closed below it | run 13 | Team2 desk |
| 2026-09-04 | **F25–F36 closed (user 2026-09-04 14:50 ET: "implement all the fixes")** — F25 one clock: every read event stamped at its bar's CLOSE (setup ids keep the open in their name); F27 `zone_tol_atr` wired + `flip_body_ratio`, both shipped at 0 (unchanged until the walk-forward); F28 structural reads journal as `TechniquePlanRead`, not skips; F29 `losses_desk_wide=True` — `max_losses_per_day` counts SPY+QQQ+IWM together (`skip_loss_cap_desk`); F30 `premium_stop_basis=mid` + `premium_stop_min_ticks=3` for Team2 (EM keeps bid, 0); F32 both loss halts net of commissions; F33 an entry whose premium-stop risk exceeds the remaining daily budget is refused before routing (`skip_loss_budget`); F36 `premium_pick=closest` — model and live pick the strike CLOSEST to the target in [floor, 1.5x]. F34/F35 (watch job) deployed with them | this session's QQQ trades | Team2 desk |
| 2026-09-04 | Halt scopes (platform, built by the desk): the daily-loss breaker now halts only the losing BOOK (`risk.daily_loss_halt_scope=portfolio`), and Team2 has its own `techniques.team2.daily_loss_halt_pct` = 10 — after losing 10% of the book in a day (≈ two full-size stops) its plans PAUSE for the day while the other techniques carry on. `risk.daily_loss_halt_pct` stays at the 12 set this morning for practice; re-tighten before real money | PLATFORM-RULES 2026-09-04 | Team2 desk |
| 2026-09-04 | **F15 + F20 built** (user 2026-09-04 13:20 ET: "can we fix these all?"). F15: `sizing_bucket` judges the PM no-trade zone BEFORE "beyond yesterday's zone" (a gap-day PM range beyond the PDH/PDL zone is still chop), and on gap days a 15m close beyond the PM level arms `pm_break_*` even outside yesterday's range (L2.4). F20: a `pm_break_*` setup's touch within the tolerance of its own anchor, close on the trade's side, is sized SMALL (the V6 rung) instead of refused — the L2.6/L2.7 retest entry; deeper inside the range V6 stands. `pm_retest` event names it. Watch the sweep: both change which trades are taken | TRADING-RULES F15/F20 evidence (SPY 10:44 → 769.05, IWM 12:14–12:34, QQQ 10:02) | Team2 desk |
| 2026-09-04 | F18: dips skipped because the range day had not cleared its PM level (B3/A4) or because they sat in the pre-market no-trade zone (V6/B5) no longer consume the two-pullback allowance (D9). Live case: IWM scenario 3 showed "touches 5, entries 0" by 11:20 ET — every dip was in the no-trade band, and the setup was spent before it ever became tradeable. Engulfing bars still count (they were pullbacks, just bad bars) | live 2026-09-04 IWM | Team2 desk |
| 2026-09-04 | Sizing: `budget_per_trade` 500 -> **2000** and `risk_pct` 6% (user); `zero_dte.max_contracts` 10 -> 40 and `premium_cap` 1000 -> 2000 so the RiskGate policy admits the size. At $0.60 that is ~33 contracts; the 25% premium stop puts ~$500 (≈6% of the $8.5k practice book) at risk per trade — well above the author's own daily-risk rule (§7c) for a book this size; revisit before real money | user decision 2026-09-04 10:50 ET | Team2 desk |
| 2026-09-04 | F14 closed: `chase_cap_mult` = 1.5 — the live entry limit never exceeds target_premium x 1.5 ($0.90 at the $0.60 target); an ask that ran rests at the cap and cancels unfilled. Same day: Team2 moved from alert to AUTO on the Practice (sim) book by the user ("change the alert mode to real mode"); `risk.daily_loss_halt_pct` raised 8 -> 12 for the Practice book so the other techniques' -9.13% morning did not keep the global kill switch engaged (the halt is global, not per book — platform gap, PLATFORM-RULES) | market-watch run 2 (F14), user decision 2026-09-04 10:30 ET | Team2 desk |
| 2026-09-04 | Posture pass: X5 trim-and-add (`add_on_retest`, one add), X3b running HOD/LOD target for re-entries (`hod_target=reentry`), trims judged on the LIVE premium in money modes (deferred/no-op vs the model), small positions hold whole to +100%. Default ON for the sweep to judge; the synthetic add day shows an add can cut a winner (+124% → +70%) — decide `add_on_retest` from the walk-forward, not from the image | `tests/test_team2_posture.py`; images 2081050843768660321 (trim-and-add), IWM three-trade day (HOD target) | Team2 desk |
| 2026-09-04 | Second review: T7 base, T8 200-EMA flush, EMA48 entries, new-extreme trim cue, stalled-pullback rule, cross-plan concurrency cap (A12) in the runner; 8 more images read (INDEX) | images 1979379272990277934, 1961977219590574391-2/3, 1908549478438887528, 2081050843768660321, 1964745974393557113/76528400559, 2013059662812463256 | Team2 desk |
| 2026-09-04 | **F26 fixed**: the 15:30 last-entry cutoff (D6) and the daily loss cap (D-3) each emit a one-time read event (`skip_last_entry` / `skip_loss_cap`) instead of stopping entries in silence. Reporting only — no entry, exit or size changes; journaled and iconed in the Armed timeline | market watch 13:35 ET; `tests/test_team2_session.py::test_entry_cutoff_and_loss_cap_say_why_the_read_went_quiet` | Team2 desk |
| 2026-09-04 | **F31 fixed**: the Armed/phone headline no longer claims "in trade" after the desk's real contract has been closed underneath the still-holding model read (premium stop, flatten, failed-exit retry). Reporting only | market watch 14:00 ET; QQQ 13:58 premium stop vs the model holding to 14:12 | Team2 desk |
| 2026-09-04 | **F34 + F35 fixed** (deploy queued for after the 15:45 flatten): the desk's three symbols stay on the feed whether or not a plan is armed on them (a disarmed plan's tape stopped banking at the next restart), and a plan that is no longer armed reports its `status`/`stopReason` on `/api/team2/runs` and in the Plans tab instead of a bare "not armed". Reporting + data continuity only — no entry, exit or size changes | market watch 14:50 ET; QQQ disarmed 14:17, bars stopped 14:28 | Team2 desk |
