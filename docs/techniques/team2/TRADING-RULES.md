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

- **F25 (2026-09-04 13:00 ET, NOT fixed — read labelling)** Read events are stamped with the OPEN time of
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


## Theories to test

- T1 The 15m-close confirmation is the load-bearing rule (added by the author only in 2026 after
  years without it); expect it to cut fires by ~40% and raise win rate materially.
- T2 Range-day scenarios (reject PDH / bounce PDL) will underperform trend-day scenarios enough that
  the desk should start with scenarios 1 and 4 only.
- T3 "Ext hours on" EMAs matter mostly for the first 30 minutes (the 200 EMA otherwise has no
  history at 09:30); after ~11:00 RTH-only EMAs converge.

## Change log

| Date | Change | Evidence | By |
|---|---|---|---|
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
| 2026-09-04 | **F15 + F20 built** (user 2026-09-04 13:20 ET: "can we fix these all?"). F15: `sizing_bucket` judges the PM no-trade zone BEFORE "beyond yesterday's zone" (a gap-day PM range beyond the PDH/PDL zone is still chop), and on gap days a 15m close beyond the PM level arms `pm_break_*` even outside yesterday's range (L2.4). F20: a `pm_break_*` setup's touch within the tolerance of its own anchor, close on the trade's side, is sized SMALL (the V6 rung) instead of refused — the L2.6/L2.7 retest entry; deeper inside the range V6 stands. `pm_retest` event names it. Watch the sweep: both change which trades are taken | TRADING-RULES F15/F20 evidence (SPY 10:44 → 769.05, IWM 12:14–12:34, QQQ 10:02) | Team2 desk |
| 2026-09-04 | F18: dips skipped because the range day had not cleared its PM level (B3/A4) or because they sat in the pre-market no-trade zone (V6/B5) no longer consume the two-pullback allowance (D9). Live case: IWM scenario 3 showed "touches 5, entries 0" by 11:20 ET — every dip was in the no-trade band, and the setup was spent before it ever became tradeable. Engulfing bars still count (they were pullbacks, just bad bars) | live 2026-09-04 IWM | Team2 desk |
| 2026-09-04 | Sizing: `budget_per_trade` 500 -> **2000** and `risk_pct` 6% (user); `zero_dte.max_contracts` 10 -> 40 and `premium_cap` 1000 -> 2000 so the RiskGate policy admits the size. At $0.60 that is ~33 contracts; the 25% premium stop puts ~$500 (≈6% of the $8.5k practice book) at risk per trade — well above the author's own daily-risk rule (§7c) for a book this size; revisit before real money | user decision 2026-09-04 10:50 ET | Team2 desk |
| 2026-09-04 | F14 closed: `chase_cap_mult` = 1.5 — the live entry limit never exceeds target_premium x 1.5 ($0.90 at the $0.60 target); an ask that ran rests at the cap and cancels unfilled. Same day: Team2 moved from alert to AUTO on the Practice (sim) book by the user ("change the alert mode to real mode"); `risk.daily_loss_halt_pct` raised 8 -> 12 for the Practice book so the other techniques' -9.13% morning did not keep the global kill switch engaged (the halt is global, not per book — platform gap, PLATFORM-RULES) | market-watch run 2 (F14), user decision 2026-09-04 10:30 ET | Team2 desk |
| 2026-09-04 | Posture pass: X5 trim-and-add (`add_on_retest`, one add), X3b running HOD/LOD target for re-entries (`hod_target=reentry`), trims judged on the LIVE premium in money modes (deferred/no-op vs the model), small positions hold whole to +100%. Default ON for the sweep to judge; the synthetic add day shows an add can cut a winner (+124% → +70%) — decide `add_on_retest` from the walk-forward, not from the image | `tests/test_team2_posture.py`; images 2081050843768660321 (trim-and-add), IWM three-trade day (HOD target) | Team2 desk |
| 2026-09-04 | Second review: T7 base, T8 200-EMA flush, EMA48 entries, new-extreme trim cue, stalled-pullback rule, cross-plan concurrency cap (A12) in the runner; 8 more images read (INDEX) | images 1979379272990277934, 1961977219590574391-2/3, 1908549478438887528, 2081050843768660321, 1964745974393557113/76528400559, 2013059662812463256 | Team2 desk |
