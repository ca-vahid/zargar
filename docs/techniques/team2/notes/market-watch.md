# Team2 market-hours watch log

Appended by the scheduled task `team2-market-watch` (every 30 min, 09:00-16:30 ET, weekdays). One dated section per run; findings mirror into TRADING-RULES.md. First scheduled day: 2026-09-04 (SPY/QQQ/IWM armed in alert mode, commit 15ffa19 deployed).

## 2026-09-04 09:02–09:14 ET (run 1 — pre-open)

- **Alive.** `/api/health` ok, v0.7.0, 46 armed plans. No errors or tracebacks in `backend/zargar-8420.log`.
- **Plans.** All three armed for 2026-09-04 in `alert` mode on Practice (sim): SPY `161ac009`
  (PDH 773.76–774.03 → 775.30 / PDL 767.45–769.26 → 764.59), QQQ `04986940` (718.60–718.91 → 724.12 /
  709.69–712.88 → 707.85), IWM `d8795fa9` (295.07–296.18 → 296.58 / 293.43–293.88 → 292.86). No fires,
  no events, `needsAttention` false — correct, the session had not opened.
- **Data is real-time.** Engine logged `pre-open feed self-test passed (REST bars + stream auth)` at
  09:00 ET; Alpaca OPRA option quotes/trades polling returns 200 continuously; SPY/QQQ/IWM quotes
  `quoteAgeSeconds 0`, session `pre`; 1m bars banking to the DB with the latest bucket 82 s old.
- **Pre-open not yet due** (09:25) — `dayType`/`sizingAtOpen`/`pmh`/`pml` null on the armed snapshots is
  expected at 09:02, not a defect. Note the `/read` endpoint *looks* complete because `replay()`
  completes the plan in memory for display; that is what exposed F13 below.
- **F12 (new).** Plan runs freeze `config.thresholds` at mint time (17:00 the night before) while the
  live runner always reads `rules_from_settings`. Today's three runs carry `entry_at: "ema"` (pre-abe9baa)
  and are missing the nine knobs added since — so `replay()` runs a different method than the desk does
  and the parity check reports phantom mismatches. No trading impact.
- **F13 (new, the consequential half).** The completed plan (PMH/PML, day type, open price, sizing) never
  reached `technique_runs.result.plan` — only the armer's memory. `replay()` re-derived it from whatever
  bars existed at replay time, and after 09:30 `complete_plan` prefers the RTH open over the 09:25
  pre-market last price (`openSource` flips), which feeds `classify_day`/`sizing_bucket` and can show a
  different day type and sizing bucket than the desk actually traded.
- **Fix deployed: `70f7f8b`.** `Team2Service.stamp_run()` writes the completed plan and the live rules
  back onto the run at the 09:25 pre-open, before any entry; historical runs stay frozen. Team2 suite
  44 passed (own DB `zargar_test_team2_watch` on :5433); the new assertion in
  `tests/test_team2_runner.py` was verified to FAIL without the fix. Redeployed at 09:11 ET (outside the
  09:25–09:35 blackout, no trade open): 46 armed plans restored, Team2's 3 restored, `team2_preopen at
  09:25 ET` re-registered.
- **Next run should check:** that the 09:25 pre-open populated `pmh`/`pml`/`dayType`/`sizingAtOpen` with
  `complete: true`, that the stamp landed on the run rows (`config.thresholds.entry_at == "both"`), and
  that `POST /runs/{id}/replay` now reproduces the live events.
- **Proposed (not built — shared engine).** The same drift exists for every technique on `PlanRunner`:
  `_persist` writes `technique_armed` only, so no technique's run row carries the rules its session
  actually ran under. Worth lifting `stamp_run` into `PlanRunner` (or `arm()`) so EM and tips get the same
  replay fidelity. Touches `zargar/execution/planrunner.py` — user's call.
- **Noted, not Team2.** `zargar.marketdata persist_bars: dropped N non-bucket-aligned stub bar(s)` fires
  every ~20 s across the pre-market. Harmless-looking but it is constant log noise on a shared path; left
  alone (outside Team2 scope).

## 2026-09-04 09:32–09:41 ET (run 2 — the open)

- **Alive and real-time.** `/api/health` ok, v0.7.0, 67 armed plans (all techniques). Alpaca stream
  `connected` + `authenticated` at 09:11 ET, OPRA option quote/trade/snapshot polling all HTTP 200,
  SPY/QQQ/IWM quotes `quoteAgeSeconds 0` session `regular`, 1m bars banking every minute (09:38 bar
  71 s old at read time), 2m read advancing on every close (5 bars by 09:40). No tracebacks; the only
  WARNING in the log is `fire review failed: timed out after 25s` at 09:31 — the LLM critic on another
  technique's plan (Team2 runs `useCritic: false`), not ours.
- **The 09:25 pre-open ran** (`scheduled job team2_preopen ran (0.8s)`, `TechniquePlanPreopen` journaled
  for all three at 09:25:36, `replan: false`, gaps SPY −0.14% / QQQ +0.23% / IWM −0.39%). Plans are
  complete: SPY PM 770.50–774.24 normal, QQQ PM 717.13–722.06 **gap up**, IWM PM 293.24–295.92 normal.
- **F13 fix verified end-to-end.** `technique_runs.result.plan` now carries pmh/pml/dayType/
  sizingAtOpen/`complete: true` with `openSource: premarket_last` preserved, and `config.thresholds.
  entry_at == "both"` on all three rows (F12). `POST /runs/{id}/replay` returns exactly that stamped
  plan instead of re-deriving it — day type and sizing no longer drift after the open. Replay parity
  is trivially clean so far (live 0 events / 0 trades, replay 0 events / 0 trades).
- **Tape sanity: nothing should have fired, nothing did.** Opens SPY 772.01, QQQ 719.345, IWM 293.70;
  day types recomputed by hand from the opens match (`QQQ open > PDH top 718.91` → gap up; IWM's open
  sits inside the PDL zone → normal). First 15m close is 09:45, so `fifteenMinBars: 0`, `bias: null`
  and "no scenario yet" are correct; `first_entry_min=585` (09:45) bars entries anyway. Regime EMAs
  are present and sane (SPY 2m close 772.51 vs ema13 771.92 / ema48 772.23 / ema200 773.03).
- **UI `/team2` is fine** (Plans tab lists all three with their sheets and day types; header reads
  "alert mode · plans 17:00 ET, pre-open 09:25 · 0DTE: entries until 15:30, flat by 15:45"). Note for
  future runs: the sign-in handoff is `#token=…` (hash), not `?token=…` as this task file says, and a
  hash-only navigation does not re-run the bootstrap — load the URL, then reload once.
- **F16 — the Practice book is halted.** `KillSwitchEngaged` (auto) at **09:38 ET**: "daily loss limit:
  Practice at -9.13% (halt at -8.0%)" on `ff3c29d4`, the same portfolio Team2 is armed to. Team2 has no
  trade and no position today and is in alert mode, so no impact now — but if the mode were moved to
  proposal/auto today, every entry would be refused (exits only). Not touched: releasing it is the
  user's call.
- **F14 — Team2's never-chase cap is unreachable.** The fire chain re-prices the picked contract on the
  live NBBO (`OptionsService.reprice`, mutates in place) and only then calls `entry_limit_cap`, which
  returns that same ask + one tick — `cap` is always ≥ `limit`, so `entry_capped` can never fire. The
  order still can't beat the current ask, but the method's real intent (never pay past the $0.20–$0.60
  band, F1/F5) is unenforced: a $0.55 pick on the ~15-min delayed CBOE chain can be bought at $1.20 on
  OPRA. **Proposed** (behaviour change, not built): anchor the cap to the method's premium band, e.g.
  `min(ask + tick, target_premium × (1 + slack))`, or re-validate the repriced ask against
  `[premium_floor, target_premium]` and log `skip_premium_ran` instead of entering. Needs the user's
  call on which of the two, and on the slack.
- **F15 — gap days don't use the PM range the way the book does.** L2.4 says a gap day takes its
  direction from a 15m close *outside the pre-market range*, then the first 13-EMA dip. In code,
  (a) `sizing_bucket` returns "full" for anything beyond the PDH/PDL zone *before* it checks the
  pre-market no-trade zone, and (b) the `pm_break_up/down` setups are gated to closes inside yesterday's
  range (the L2.5 inside-day case), so a gap day gets no PM setup at all. Today's QQQ is the live case:
  gap-up open 719.35 above the PDH zone but inside PM 717.13–722.06 — a 15m close over 718.91 arms
  full-size 13-EMA entries in the middle of the pre-market range, and a reversal through PML 717.13 has
  no setup until PDL 709.69, ten points lower. **Proposed**, not built: on `dayType in (gap_up,
  gap_down)` let the PM levels be the scenario levels (drop the `<= pdh.top` guard) and test the PM
  no-trade zone before the "full" branch. Watch QQQ at the 09:45/10:00 closes for what it actually does.
- **Proposed (shared, minor).** Log rotation is 5 MB × 3 files, and the per-symbol Yahoo 1m polling
  writes an `httpx HTTP Request` INFO line per symbol per cycle — during market hours the whole
  retained window is **~15 minutes**, which is why the 09:25 pre-open lines had already rotated out by
  09:35. Dropping `httpx` to WARNING (or excluding it from the file handler) would give the watch job
  a usable day of history. Not touched (shared logging config).
- **Next run should check:** the 09:45 and 10:00 15m closes — did QQQ take scenario 1 (break PDH) and
  did any 13-EMA entry get skipped or sized "full" inside the PM range (F15 evidence); whether SPY/IWM
  produced a scenario; that a fire (if any) carries a `contract` event with a strike and an ask near
  $0.60 and `priced: opra`; and replay parity once there are real events.

## 2026-09-04 10:02–10:22 ET (run 3 — first hour)

- **Alive and real-time.** `/api/health` ok, v0.7.0, 66 armed plans. Zero tracebacks all day; the only
  non-httpx WARNING remains `persist_bars: dropped N non-bucket-aligned stub bar(s)` (shared path,
  logged run 2, still untouched). Alpaca stream `connected` + `authenticated`, OPRA option
  quote/trade polling HTTP 200 every ~2 s, SPY/QQQ/IWM quotes 8 s old session `regular`, 1m bars
  banking through 10:15. The 09:25 pre-open work from run 2 is intact after the redeploy.
- **What the read saw.** SPY: still no scenario (772.5 → 772.0, never near PDH 774.03 or PDL 767.45) —
  correct. IWM: scenario 3 (bounce PDL) confirmed on the 09:30–09:45 15m close at 294.79, then **two
  EMA13 touches correctly refused** — `skip_no_trade_zone` at 09:46 (294.94) and 09:56 (294.64), both
  inside PM 293.24–295.92 (V6/B5) — and a third at 10:00 flagged `late_touch` (D9/P6). QQQ: scenario 1
  (break PDH) at 720.04, then the day's first fires — touch #1 at **10:02** (EMA13 720.84 held, close
  721.44, model call 723 ≈ $0.47), stopped on the 10:08 2m close through the EMA13 at 720.75
  (`would_exit`, model −14.4%), then touch #2 at the **EMA48** 720.13 (close 720.30, model call 722 ≈
  $0.54, target the running HOD 721.86 — X3b). I hand-checked the 2m tape and the EMA13 series against
  the DB bars: the touches, the stack/fan gates and the 15m confirmations all read correctly.
- **F17 (new, FIXED — `4a540d6`).** The kill switch was silencing the desk. `_fire_from_event` tested
  the halt **before** the mode, so with Practice halted since 09:38 (F16) QQQ's 10:02 fire was logged
  `halt_skip` and no `fired` row was written — and `POST /runs/{id}/replay` over the same bars *did*
  show the fire, so **live-vs-replay parity broke** as a side effect. Alert mode places nothing
  (`_fire_rest` only sets `trade.status = "alert"`), and the caps immediately below the halt check plus
  `_add_from_event`'s `would_add` are already gated to money modes with the comment "money modes only;
  alert/proposal keep recording every read" — the halt check was the odd one out. Now gated to
  proposal/auto; an alert fire during a halt carries `haltedAtFire: true` so the audit still says the
  money path would have refused it. Team2 suite **45 passed** (own DB `zargar_test_team2_watch` on
  :5433); the new `test_alert_mode_still_reads_the_tape_while_halted` was verified to FAIL without the
  fix (`['armed','preopen','scenario','halt_skip','halt_skip','disarmed']`). Redeployed 10:19 ET —
  outside the 09:25–09:35 blackout, no Team2 trade open (`trades=0` on all three) — 66 plans restored,
  and QQQ's two fires now appear in the event log.
- **Restore artifact, no action.** The restore re-derived both QQQ fires from banked bars and then
  dropped the trade objects (`phantom_dropped: replay-minted alert trade removed (live plan never fired
  it)`) — correct in general (don't invent trades the live desk never had), but here the live desk
  *had* reached the conditions and only the pre-fix `halt_skip` stopped it. Net: today's QQQ fires live
  in the events log and in `last_read` (which is what the Team2 page and grading use) but not in the
  Armed page's `trades` list. One-off; from here the live path writes them itself.
- **F15 confirmed live, and it is smaller than "a gap-day question".** QQQ fired at 721.44 — inside
  PM 717.13–722.06, 0.62 under the PMH — with `bucket=full`, while the same engine in the same hour
  refused IWM's two identical touches for sitting inside *its* PM range. The discriminator is only the
  day type. Checking METHOD V6: it is a **five-rung ladder** ("above the PDH zone = Full · PDH
  zone→PMH = **Small** · PMH→PML = No trade · PML→PDL zone = Small · below the PDL zone = Full") and
  `scenario.sizing_bucket` implements three — it returns "full" for anything above `pdh.top` and can
  never produce "small" for the PDH-top→PMH band, which is unreachable whenever PMH > PDH top (every
  gap-up day and plenty of normal ones). The literal V6 reading for QQQ at 721.44 is **small**.
  **Proposed, not built** — sizing is a money decision: walk the five rungs in price order in
  `sizing_bucket`. One word from the user and it is a ten-line change plus a test.
- **Proposed (new).** Alert mode never picks a contract — `_fire_rest` gates `pick_contract` to
  proposal/auto — so the desk's fires carry only the **modeled** premium (BS on the VIX proxy: $0.47,
  $0.54) and today's OPRA poll list contains no SPY/QQQ/IWM 0DTE contract. That is exactly the number
  F8 says is 12–45% optimistic and exactly what F14 (never-chase) needs to be judged on. Picking the
  contract in alert mode too would give a real NBBO ask per fire at the cost of one OPRA call — no
  order, no money — and would let the desk answer "is a ~$0.50 strike actually there at that moment?"
  before proposal mode is ever switched on. Worth deciding before the next practice day.
- **F16 still open.** Practice remains halted (`-9.13%`, engaged 09:38, other techniques' positions).
  Release is the user's call; Team2 holds nothing.
- **Next run should check:** whether QQQ's touch #2 reached the HOD target 721.86 or stopped on the
  EMA48; whether SPY finally gets a scenario (it needs 774.03 or 767.45 — two-plus points away all
  morning); that `fired` rows now appear live without a restart (the F17 fix on the live path, not just
  on restore); IWM's touch count past the `late_touch` cap; and replay parity on the new events.

## 2026-09-04 10:36 ET (desk session, not the watch job) — Team2 moved to AUTO on Practice

- User decision ("change the alert mode to real mode"): all three plans switched alert → **auto** in place
  (`POST /api/technique/armed/{id}/mode`), `techniques.team2.mode=auto` for tonight's plans. Practice = the
  sim book `ff3c29d4`; live accounts untouched (`allow_live_auto` stays off, trading.mode practice).
- F14 closed first (commit 1a2fd1d, deployed 10:31 ET): `chase_cap_mult=1.5` → entry limit ≤ $0.90 at the $0.60 target.
- The global kill switch was released (`POST /api/resume`) after raising `risk.daily_loss_halt_pct` 8 → 12, because
  the Practice book sat at −9.13% from the other techniques and the check re-engages while below the limit
  (PLATFORM-RULES gap: global switch, per-book check). Not re-engaged 20 s later.
- Restart at 10:31 was done in ALERT mode on purpose so the replayed read could not buy QQQ's already-open model
  position; QQQ's second model trade (722c, EMA48 entry) had closed (`would_exit`) before the switch. No live
  position inherited. QQQ's scenario-1 setup has used both touches (D9) — no further entries there today.
- **Watch job: from now on check real orders/fills** (`GET /api/orders?portfolio=ff3c29d4…`, the plan's `trades` in
  the armed snapshot, `contract`/`entry_capped`/`position_open`/`live_trim` audit events) and do NOT restart while a
  Team2 trade is open or working.

## 2026-09-04 11:12 ET (desk session) — sizing $500 → $2,000 per trade

- User: budget_per_trade 2000. Applied to settings AND in place on today's three plans (`POST …/mode` now takes
  `premiumBudget`/`riskPct`, commit cce380f + 1c99f99). Team2 `risk_pct` 6 with its own `max_risk_pct` 6
  (the shared R1 cap is 5), `zero_dte.max_contracts` 40, `premium_cap` 2000. At $0.60 that is ~33 contracts and
  ~$500 (≈6% of the practice book) at risk per trade under the 25% premium stop.
- Deployed 11:08 ET via alert → restart → auto (no Team2 trade was open). Plans back in AUTO 11:11 ET.

## 2026-09-04 10:32-10:45 ET (run 4 - first auto session)

- **Alive, real-time, no Team2 orders.** `/api/health` ok v0.7.0, 66 armed. Mode is **auto** on the
  Practice sim book (`ff3c29d4`) since the 10:36 desk decision; the global kill switch is **released**
  (`halt.engaged: false`, `risk.daily_loss_halt_pct` now 12.0), Practice equity 8,655.32 / todayPct
  -0.17%. Alpaca stream `connected` + `authenticated` (10:36:13), OPRA quote+trade polls HTTP 200 every
  ~2 s, SPY/QQQ/IWM quotes 0 s old session `regular`, 1m bars banking through 10:33 (64 bars since the
  open, all three). **Zero Team2 orders placed today** (`/api/orders` has nothing on SPY/QQQ/IWM and no
  `source: team2` row) - correct, because both of QQQ's touches were used before the switch and IWM/SPY
  have produced no tradable touch.
- **The app restarted at 10:36:18 ET mid-run** (another session's deploy - four restarts today: 10:14,
  10:20, 10:22, 10:27, 10:36). All 3 Team2 plans restored, `needsAttention: false`, no attention reasons.
  My health/replay calls hit the 30 s gap and returned connection-refused; nothing was lost.
- **Verified: a restart in AUTO mode cannot buy a replayed fire.** The restore seed loop calls
  `_on_bar(..., journal=False)` (planrunner l.978) and `_fire_rest` reads
  `if cfg.mode == "alert" or not journal:` - a seeded fire is always stamped `alert`, never routed to
  `_enter`, and the phantom-drop then removes it. The desk's 10:31 "restart in alert mode on purpose"
  precaution was not actually required; restarts are safe in auto. (The remaining artifact is
  cosmetic and already logged: today's QQQ fires live in `last_read` and the event log but not in the
  Armed page's `trades` list.)
- **What the read saw since run 3.** QQQ: nothing new - both scenario-1 touches were spent by 10:18
  (#1 EMA13 720.84 -> stop on the 10:08 2m close 720.75, -14.35%; #2 EMA48 720.13 -> stop on the 10:18
  close 720.11, -10.33%; day -24.68% on two model trades), price back to 719.26 and the EMA stack has
  gone `mixed`/chop. IWM: no trade, four more `late_touch` events (10:00, 10:32, 10:34, 10:38 = touches
  #3-#6) - see F18. SPY: still no scenario at all (770.94, needs 774.03 or 767.45), `setups: 0`, correct.
- **Replay parity is exact on all three.** `POST /runs/{id}/replay` reproduces the live read
  bar-for-bar: QQQ 2 trades / same entries 720.84 & 720.13 / same strikes 723 & 722 / same -14.35% and
  -10.33%; IWM the same scenario + 2 skips + late touches; SPY 0/0. Every plan is `complete: true` with
  pmh/pml/dayType/sizingAtOpen stamped (QQQ 722.06/717.13 gap_up/full, IWM 295.92/293.24 normal/none,
  SPY 774.24/770.50 normal/none) - F12/F13 still holding after four restarts.
- **F18 (new, logged, NOT built).** A refused pullback burns the D9 "first two touches" budget:
  `session.py` increments `s.touches` before every skip gate, so IWM's two `skip_no_trade_zone`
  refusals (09:46, 09:56 - both correct per V6/B5, inside PM 293.24-295.92) exhausted the setup, and
  IWM is now watch-only for the rest of the day on a scenario it never traded. P6's rationale for D9 is
  that the third bounce is where the *first-dip buyers* stop out - which presumes the first two dips
  were bought. Proposal: move the increment below `skip_no_trade_zone`/`skip_engulfing`. Money decision,
  user's call.
- **F19 (new, shared engine, propose only).** `Quote.day_high`/`day_low`/`volume` from the Alpaca
  stream are since-process-start, not session-to-date (`brokers/alpaca.py` l.188/212/253 - the Yahoo
  context is an `or` fallback that one tick discards). Post-restart the API reported SPY dayHigh 771.29
  vs a real 772.87 and QQQ 719.65 vs 721.86. **No Team2 impact** - the X3b HOD target comes from the bar
  series (QQQ's 721.86 matches the DB exactly); only the frontend quote card reads it. Not touched.
- **Still open, unchanged.** F14 closed (chase_cap_mult 1.5 is live in `thresholds`). F15 (five-rung
  V6 sizing ladder collapsed to three) still proposed - QQQ traded `full` inside its PM range again
  today. F16 is resolved operationally (halt released). The alert-mode "no contract picked" proposal is
  moot while the desk is in auto (`pick_contract` runs on the money path) but returns the moment the
  user goes back to alert. Log rotation still gives only ~20 minutes of history during market hours.
- **Next run should check:** whether the desk places its **first real order** - a `contract` event with
  a strike and an OPRA ask, `entry_capped` if the cap bites at 1.5x, then `position_open`/`live_trim`
  in the audit; whether SPY finally confirms a scenario; whether IWM breaks 295.92 and gets locked out
  by F18; the 15:30 last-entry and 15:45 flatten discipline if anything is open.

## 2026-09-04 12:30 ET (desk session) — F18 + F19 deployed, QQQ flipped to puts

- F18 (refused dips no longer burn the D9 allowance) deployed 11:50 ET: IWM's setup went from "touches 5" to
  "touches 0" — tradeable again. F19 (quote day high/low/volume session-to-date, seeded from Yahoo, regular-session
  prints only, reset per session) deployed 12:28 ET, commit d778f48, PLATFORM-RULES + CLAUDE.md updated.
- Both deploys: alert → restart → auto with `premiumBudget 2000 / riskPct 6`; no Team2 trade was open either time.
- Read at 12:28 ET: QQQ **scenario 2 (reject PDH) → puts**, touches 0; SPY still no scenario; IWM scenario 3 → calls,
  touches 0. All three AUTO.

## 2026-09-04 13:05 ET (desk session) — Armed page speaks Team2

- The Armed day panel showed EM's prime/mid-day bands and "1m bar with a volume surge" prose on Team2 plans (user
  asked where the Team2 items are). Fixed (commit 5b3a8da + merge aa1a061, UI only, dist rebuilt, no restart): Now line
  = the read's summary, bands = entries all session / no new entries 15:30 / flat 15:45, read events have icons,
  session banner says Team2 fires all session; Team2 page › Armed tab shows the read per symbol + contract live %.
