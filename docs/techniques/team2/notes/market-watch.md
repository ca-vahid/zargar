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

## 2026-09-04 11:05 ET (run 5 — first full auto session, clock-verified)

- **Alive, real-time, nothing broken.** `/api/health` ok v0.7.0, 66 armed. All three plans `armed` +
  **auto** on the Practice sim book (`ff3c29d4`), `needsAttention: false`, no attention reasons,
  `complete: true` with pmh/pml/dayType/sizingAtOpen stamped (QQQ 717.13–722.06 gap_up/full,
  SPY 770.50–774.24 normal/none, IWM 293.24–295.92 normal/none). Alpaca stream `connected` +
  `authenticated` 10:55:20 ET after the 10:55 restart; SPY/QQQ/IWM quotes 0 s old, session `regular`;
  1m bars banking in the runtime DB through **11:06 ET** (97 bars each = every bar since 09:30);
  `barAgeSeconds` 72 on all three, `stale: false`. No errors, no `Traceback`, no `read_error` in
  `backend/zargar-8420.log`.
- **Zero Team2 orders today.** `/api/orders` has no SPY/QQQ/IWM row and no `source: team2` row; the
  audit shows only `TechniquePlanArmed` / `TechniquePlanModeChanged` / `TechniquePlanTriggerSkipped`.
  Correct — no setup has produced a *sizable* touch since the desk went auto at 10:55 ET.
- **What the read saw since run 4.** QQQ: the 10:30 15m close at 718.07 flipped the bias to
  **scenario 2 (reject PDH) → puts**, which killed scenario 1 (`deadReason: bias flipped to reject PDH
  (D10)`) after its two losing model trades (−14.35%, −10.33%); scenario 2 is waiting, touches 0, price
  717.37 vs the 718.60 anchor. IWM: scenario 3 alive with **touches 0** — F18 is working, thirteen
  `skip_no_trade_zone` refusals (09:46 → 11:02, all inside PM 293.24–295.92) no longer burn the D9
  allowance. SPY: broke its PM low at 10:30 and produced its first setup of the day — see F20.
- **Replay parity exact on all three.** `POST /runs/{id}/replay` reproduces the live event stream
  bar-for-bar and trade-for-trade (QQQ 6/6 events, same entries 720.8368 & 720.1343, same strikes
  723/722, same −14.35% / −10.33%; SPY 2/2; IWM 14 vs 15 — the replay had simply seen one more 2m
  close, 11:04, than the live read). No drift after five restarts today.
- **F20 (new, NOT built — the trade of the day was refused).** `pm_break_up`/`pm_break_down` (rules
  L2.6/L2.7) anchor on the PM level itself, and `sizing_bucket` tests `pml <= price <= pmh`
  **inclusively**, so a retest of the level the setup is built on is always `bucket: none`. SPY today:
  15m close 770.30 below the PM low 770.50 at 10:30 → setup with target 769.26; 10:44 retest at exactly
  770.50 → `skip_no_trade_zone`; SPY then ran to 769.05, **through the target**, and the desk took
  nothing. The book says the opposite in as many words (L2.7 "enter puts on the retest/rejection of
  PML"). Sizing is a money rule, so proposed only: exempt a pm_break setup's retest of its own anchor
  and size it **small** — the V6 rung a PM-level retest actually sits on. Bundle the decision with F15
  (the five-rung V6 ladder collapsed to three); it is the same ten lines of `sizing_bucket`.
- **F21 (new, log hygiene).** The last two *desk* entries above are stamped ~1h35m ahead of real ET —
  "12:28 ET" for commit `d778f48` authored 10:51 ET, "11:50 ET" for F18's 10:41 ET commit. The app's
  clock is fine (bars/quotes/`regime.ts` all agree with wall-clock ET); it is a writing error. Stamp
  future sections from `regime.ts` or `TZ=America/New_York date`.
- **Minor, proposed only.** `skip_no_trade_zone` prints on **every** 2m close while the condition holds
  (IWM: 13 identical events in 76 minutes, and it will keep going all day). Dedupe it the way
  `pullback_stalled` already does (`s._stalled`) — emit once, re-emit only when the bucket or setup
  changes. Cosmetic; not worth a restart mid-session with auto armed.
- **Unchanged.** F14 closed (`chase_cap_mult` 1.5 live). F15 still open. F16 resolved operationally
  (kill switch released, `risk.daily_loss_halt_pct` 12). The QQQ restore artifact is unchanged and
  still cosmetic: today's two QQQ fires live in `last_read` and the event log but not in the Armed
  page's `trades` list. Log rotates on restart, so only ~15 min of history survives a deploy.
- **No restart this run** — nothing needed one, and five restarts have already happened today.
- **Next run should check:** whether QQQ's scenario-2 put setup gets its first EMA13 touch below
  718.60 and whether that becomes the desk's **first real order** (`contract` event with a strike and
  an OPRA ask, `entry_capped` if the 1.5x cap bites, then `position_open`/`live_trim`); whether IWM
  closes above 295.92 and finally has a sizable dip; whether SPY confirms a full scenario (774.03 /
  767.45) now that the PM-break path is a dead end; and the 15:30 last-entry / 15:45 flatten discipline.

## 2026-09-04 12:20 ET (run 6 — the desk's first real order, and the bug that ate it)

- **Alive, real-time, plans healthy.** `/api/health` ok v0.7.0, 64 armed. All three plans `armed` +
  **auto** on the Practice sim book (`ff3c29d4`), `needsAttention: false`, `complete: true` with
  pmh/pml/dayType/sizingAtOpen stamped (QQQ 717.13–722.06 gap_up/full, SPY 770.50–774.24 normal/none,
  IWM 293.24–295.92 normal/none). SPY/QQQ/IWM quotes 0 s old, session `regular`; 1m bars banking
  (`barAgeSeconds` 87–114, `stale: false`, 683 bars seen on SPY); OPRA quote/trade/snapshot polls
  HTTP 200 every ~2 s; **no `Traceback`, no `ERROR`, no `read_error`** anywhere in `zargar-8420.log`.
  F19 confirmed working live — SPY `dayHigh` 772.87 / QQQ 721.86 now match the bar series exactly.

- **F22 — the headline. The desk's FIRST real order fired correctly and was then refused by a bug.**
  SPY's `pm_break_down` setup fired at **11:08 ET** (touch #1, EMA13 769.81 held, close 769.70, bear
  stack) and the contract picker did everything right: real OPRA quote `SPY260904P00768000`, bid 0.38 /
  ask 0.39, spread 2.6%, volume 63,663, OI 7,342, delta −0.244, IV 14.6%, size `small` ×0.5 → 26
  contracts ≈ **$1,014** premium. The trade was then dropped with
  `contract skipped (premium ≈$1,014 is over 50% of the account's $-267 equity)`. **The Practice book's
  equity is $8,618.40; −$266.58 is its CASH** — negative only because other techniques' RKLB calls and
  ZURA shares have it fully invested. One line in the shared `execution/planrunner.py` premium
  pre-check read the cached portfolio row (`positions.portfolio()`), which has **no `equity` key at
  all**, so `pf.get("equity") or pf.get("cash")` always fell through to cash. That made the pre-check
  strictly stricter than the RiskGate it exists to mirror — `risk.py` awaits `positions.equity()` and
  would have **passed** this order. Every remaining fire today would have been refused the same way.
- **Fixed and deployed: commit `c9021d3`, restart 12:18 ET.** Await the real equity; no behaviour added,
  the RiskGate stays the authority. Tests green on the job's own DB (`zargar_test_team2_watch`): 47
  Team2 + primitives, plus 50 shared `test_technique_arming.py` + `test_riskgate.py`. Logged in
  `PLATFORM-RULES.md` (shared engine) and `TRADING-RULES.md` (F22). All three plans restored `armed` +
  auto, `needsAttention: false`. No Team2 position was open and no order working at restart time.
- **Two related mismatches deliberately NOT built** (in F22, for the user): (a) this pre-check has no
  `kind == "shadow"` exemption although the RiskGate has had one since 2026-09-01 — shadow books with
  negative cash are blocked from every option entry on this path; (b) nothing on this path checks
  **buying power**, so a fully-invested book can now be sized into an order it could not fund at a real
  broker. Neither bites Team2 on a sim book, but (b) is the one to decide before real money.

- **What the read saw since run 5.** SPY: `pm_break` down 10:30 (15m close 770.30 below PM low 770.50) →
  the 10:44 retest at exactly 770.50 refused (F20), then the 11:08 fire above and the 11:14 model exit
  (2m close 769.87 back through the EMA13 769.79, **−12.23%**); 11:00 15m close above 769.26 flipped it
  to scenario 3 (bounce PDL) → calls; SPY is back at 770.91. QQQ: nothing — scenario 2 (reject PDH) →
  puts still waiting, touches 0, 718.48 vs the 718.60 anchor, stack gone `mixed`. IWM: **`pm_break` up
  at 12:00** (15m close above PM high 295.92 → calls to the PDH zone), touches 0, now 296.05.
- **Day so far: 3 model trades, 3 losses (−12.23%, −14.35%, −10.33%), 0 real orders placed.** The only
  SPY/QQQ/IWM row in `/api/orders` is `SPY260914C00775000` (Sep-14 expiry, `source: auto`) — another
  technique's, not Team2's.

- **F20 reinforced — it is now three refusals in one session.** IWM's 12:14 retest of its own PM high
  **at exactly 295.92** was refused `skip_no_trade_zone`, the same shape as SPY's 10:44. `sizing_bucket`
  tests `pml <= price <= pmh` inclusively, so a `pm_break_*` setup can never enter at the level it is
  built on — and L2.6/L2.7 say to enter precisely there. On a range day that is the whole setup class,
  not an edge case. Still **not built** (sizing is a money rule); decide it together with F15.

- **Replay parity exact on all three.** SPY 5/5 events + 1/1 trade (−12.23%), QQQ 6/6 + 2/2 (same entries
  720.8368 / 720.1343, same strikes 723 / 722, same −14.35% / −10.33%), IWM 0 trades. The apparent
  "replay ran to 12:14 while live stopped at 11:32" was only the ~40 minutes that elapsed between the two
  fetches — no drift, no future bars. Six restarts today and the stamped plans still hold (F12/F13).

- **Unchanged.** F14 closed. F15 open. F16 resolved operationally. F21 respected — this section is
  stamped from the app clock. The `skip_no_trade_zone` spam is now 20+ identical IWM events (dedupe it
  the way `pullback_stalled` does — cosmetic, still not worth its own restart). The QQQ restore artifact
  (today's two fires live in `last_read` and the event log but not in the Armed page's `trades` list) is
  unchanged and still cosmetic.
- **Next run should check:** whether a fire now actually reaches the book — `contract` → `entry_capped`
  (if the 1.5× chase cap bites) → `position_open` → `live_trim` in the audit, and a real row in
  `/api/orders` with `source: team2`; whether IWM's pm_break-up gets an EMA13 touch outside the PM range
  (the only way it can enter while F20 stands); QQQ's scenario-2 put touch below 718.60; and the 15:30
  last-entry / 15:45 flatten discipline on anything open.

## 2026-09-04 12:33 ET (run 7 — quiet tape, two read-quality fixes committed but NOT deployed)

- **Alive, real-time, nothing broken.** `/api/health` ok v0.7.0, 64 armed. All three plans `armed` + **auto**
  on the Practice sim book (`ff3c29d4`), `needsAttention: false`, `complete: true` with pmh/pml/dayType/
  sizingAtOpen stamped (QQQ 717.13–722.06 gap_up/full, SPY 770.50–774.24 normal/none, IWM 293.24–295.92
  normal/none). The app restarted at **12:19 ET** (run 6's F22 deploy): Alpaca stream `connected` +
  `authenticated` 12:19:21, all three plans restored. SPY/QQQ/IWM quotes 0 s old, session `regular`;
  1m bars banking in the runtime DB through **12:24 ET** (SPY 1,428 / QQQ 1,076 / IWM 976 rows in 24 h),
  `barAgeSeconds` 89–106, `stale: false`; OPRA quote+trade polls HTTP 200 every ~2 s. The only `ERROR` in
  `zargar-8420.log` is a benign Windows socket reset (`WinError 10054`) on an outbound HTTP connection at
  12:10, pre-restart. No `read_error`, no Traceback.
- **F22 confirmed fixed in the wild.** After the restart the SPY plan's seeded fire re-priced cleanly — the
  `contract_quality` refusal is gone and the 11:08 trade now appears in the Armed page's `trades` list with
  its real strike (768 P, entry mark 0.5039). No order followed, which is correct: a restore-seeded fire is
  stamped `alert` (run 4's finding) and the audit shows only `TechniquePlanArmed`. **Still zero Team2 orders
  today** — `/api/orders` on the Practice book has no SPY/QQQ/IWM row and no `source: team2` row.
- **What the read saw since run 6 (13 minutes): nothing new but skip spam.** SPY flipped to scenario 3
  (bounce PDL) → calls at 11:00, price 770.94, touches 0. QQQ scenario 2 (reject PDH) → puts, touches 0,
  718.54 against the 718.60 anchor, stack `mixed`. IWM `pm_break_up@12:00` → calls, touches 0, 296.06 just
  above the 295.92 anchor; its 12:14 retest was the F20 refusal already logged. Day still stands at
  **3 model trades, 3 losses (−12.23%, −14.35%, −10.33%), 0 real orders.**
- **Replay parity exact on all three.** SPY 4/4 events + 1/1 trade (769.8082 / 768 P / −12.23), QQQ 6/6 + 2/2
  (720.8368 / 723 C / −14.35 and 720.1343 / 722 C / −10.33), IWM 2/2 + 0 trades. Note for the next run:
  `POST /runs/{id}/replay` **requires a JSON body** — send `-d '{}'` or it 422s on a missing body.
- **F23 (new, FIXED, committed `bbce064`, NOT yet deployed).** `skip_no_trade_zone` (V6/B5) and
  `skip_range_confirmation` (B3/A4) were re-stated on every 2m close for as long as the condition held —
  IWM printed **37** identical rows between 09:46 and 12:14, each one both a read event and an
  append-only `TechniquePlanTriggerSkipped` journal row that can never be pruned. `note_once()` now dedupes
  per setup (same shape as the existing `pullback_stalled` flag); a real touch past the gate clears it, so a
  later refusal is said again. No gate, count or D9-allowance change; replay parity holds because live and
  replay run the same code. Regression test `test_no_trade_zone_skip_is_said_once_per_setup` (5 rows → 1 on
  the fixture). 48 Team2 + primitives tests green on `zargar_test_team2_watch`.
- **F24 (new, FIXED, committed `c929c77`, NOT yet deployed).** The Armed/Team2 "Now" line read the D9 touch
  allowance off the wrong setup: `runner.py` took `max(touches)` over all live setups, while `session.py`
  enters only the **newest live setup in the bias direction**. SPY read "scenario 3 (bounce PDL) → calls ·
  touches 1" while that setup had used none of its two — the 1 belonged to `pm_break_down@10:30`, a spent
  SHORT setup. Fixed by mirroring `session.py`'s selection. Verified against all three live reads:
  SPY 1 → 0, QQQ and IWM unchanged.
- **Deploy deliberately QUEUED, not done.** Both fixes are display/journal quality with zero effect on
  entries. The desk is in AUTO with two waiting setups (IWM 0.05% above its `pm_break_up` anchor, QQQ 0.01%
  from its scenario-2 anchor), and a fire landing inside a ~30 s restart window is seeded back as `alert`
  and never routed to `_enter` — i.e. the one thing the desk has waited all day for would be swallowed. Not
  worth trading that for cosmetics. **Deploy at the next restart another session makes, or after the 15:45
  flatten.** (Seven restarts today already.)
- **Unchanged.** F14 closed. **F15 and F20 still open and still the two that matter** — F20 has now refused
  three PM-break retests in one session (SPY 10:44, SPY's own anchor, IWM 12:14), and on a range day that is
  the entire setup class; decide it together with F15's collapsed V6 ladder, it is the same ten lines of
  `sizing_bucket`. F16 resolved operationally. F21 respected (this section is stamped from the app clock).
- **Observation, not built.** A setup whose target price has already been exceeded stays alive and keeps
  being evaluated (IWM `scenario_3@09:30`, target 295.07, price 296.06). Harmless today because
  `session.py` only ever enters the *newest* same-direction setup, so it is shadowed by `pm_break_up@12:00`
  — but it would matter for a stale setup that is still the newest. Worth a `dead_reason: "target reached"`
  if the user wants it; method question, so proposed only.
- **Next run should check:** whether QQQ or IWM finally produces a *sizable* touch and the desk places its
  **first real order** (`contract` → `entry_capped` → `position_open` → `live_trim` in the audit and a
  `source: team2` row in `/api/orders`); whether F23/F24 got deployed by someone's restart (`git log` vs the
  running build); and the 15:30 last-entry / 15:45 flatten discipline on anything open.

## 2026-09-04 12:38 ET (run 8 — quiet, healthy; F20 refused four more IWM touches)

- **Alive and real-time, nothing broken.** `/api/health` ok v0.7.0, 63 armed. All three plans `armed` +
  **auto** on the Practice sim book (`ff3c29d4`), `needsAttention: false`, pmh/pml/dayType/sizingAtOpen
  stamped (QQQ 717.13–722.06 gap_up/full, SPY 770.50–774.24 normal/none, IWM 293.24–295.92 normal/none).
  Quotes 0 s old, session `regular` (SPY 770.79/770.80, QQQ 718.92/718.93, IWM 295.82/295.83); 1m bars
  banking in the runtime DB through **12:36 ET** at 12:37:42 (SPY 1,428 / QQQ 1,076 / IWM 976 rows in 24 h),
  `barAgeSeconds` 77, `stale: false`; OPRA `options/quotes/latest` + `trades/latest` polls HTTP 200 every
  ~2 s. **No `Traceback`, no `ERROR`, no `read_error`** since the pre-restart 12:10 socket reset.
- **Only 5 minutes of new tape since run 7**, and the session read advanced through 12:34 as expected.
  SPY: scenario 3 (bounce PDL) → calls, touches 0, 770.86 vs the 769.26 anchor, stack `mixed`. QQQ:
  scenario 2 (reject PDH) → puts, touches 0, 719.00 vs 718.60, stack `mixed`. IWM: `pm_break_up@12:00` →
  calls, touches 0, 295.92 sitting exactly on its anchor. Day unchanged: **3 model trades, 3 losses
  (−12.23%, −14.35%, −10.33%), 0 real orders.** `/api/orders` still has no SPY/QQQ/IWM 0DTE row and no
  `source: team2` row (the SPY 260914C00775000 fill is another technique's).
- **Replay parity exact on all three** (`POST /runs/{id}/replay` with `-d '{}'`): SPY 5/5 events + 1/1 trade
  (768 P, −12.23), QQQ 6/6 + 2/2 (723 C −14.35, 722 C −10.33), IWM 40/40 + 0 trades. No drift.
- **F20 is now the finding of the day — four more refusals on one setup.** IWM's `pm_break_up@12:00` has had
  **four** EMA13 touches refused `skip_no_trade_zone` in 34 minutes: 12:14 at 295.92, 12:24 at 295.89,
  12:32 and 12:34 at 295.88. All "inside the pre-market range" for the one structural reason F20 names —
  the setup's anchor **is** the PM high, so a pullback to it is by definition inside the range, and that
  pullback is exactly what L2.7 tells the desk to buy. Seven refusals across two symbols today, zero
  entries. IWM has held within 0.05% of 295.92 for over half an hour, so it will keep refusing while the
  chop lasts. Evidence appended to `TRADING-RULES.md` under F20. **Still not built** — sizing is a money
  rule; decide it with F15 (the collapsed V6 ladder), same ten lines of `sizing_bucket`.
- **F22's refusal record on the SPY trade is historical, not a regression.** The armed snapshot still shows
  the 11:08 fire as `skipped … $-267 equity`; that is the write-ahead record persisted at 11:08, restored
  through the 12:19 restart. The fix landed at 12:18; no fire has been priced since, so the fix has still
  not been exercised live.
- **F23 + F24 remain committed (`bbce064`, `c929c77`) but NOT deployed** — the running build is the 12:19
  one. The spam confirms it: IWM's `skip_no_trade_zone` count went 37 → 38 (34 on `scenario_3@09:30`,
  4 on `pm_break_up@12:00`). Deploy decision unchanged from run 7 and for the same reason: the desk is in
  AUTO with a setup taking a touch every few minutes, and a fire landing inside a ~30 s restart window is
  seeded back as `alert` and never routed to `_enter`. **Deploy after the 15:45 flatten, or on the next
  restart another session makes.**
- **Minor, not Team2, no action.** 24 Yahoo `v8/chart` 404s in the last 400 log lines are other techniques'
  dated option symbols, and `calendar fetch failed for SPY/SPX` (Yahoo `quoteSummary` 404) leaves the macro
  block empty — harmless here since `avoid_event_days` is false.
- **Next run should check:** whether any of the three finally takes a touch that is *outside* the PM range
  and places the desk's **first real order** (`contract` → `entry_capped` → `position_open` → `live_trim`
  in the audit plus a `source: team2` row in `/api/orders`, which is also the first live exercise of the
  F22 fix); whether F23/F24 got deployed by someone's restart (`git log` vs the running build); and the
  15:30 last-entry / 15:45 flatten discipline.


## 2026-09-04 13:45 ET (desk session) — F15 + F20 built and deployed, F23/F24 deployed with them

- User: "can we fix these all?" → F15 and F20 built (commit 10fb660): PM no-trade zone judged before "beyond
  yesterday's zone"; gap days arm `pm_break_*` at the PM levels; a `pm_break_*` setup's touch within tolerance of its
  own anchor (close on the trade's side) is sized SMALL and named `pm_retest` instead of refused. Tests: 36 Team2 green.
- Deployed 13:42 ET (alert → restart → auto, no Team2 trade open; the process that was running had started 12:56 ET,
  before F23/F24 too, so those are live now as well). Replay of today under the new rules: SPY takes the 10:44 PM-low
  retest (put 768 ≈ $0.39, small) and the 11:08 EMA13 touch; IWM takes the 12:14 PMH retest (call 296 ≈ $0.38, small);
  QQQ's 10:02 full-size entry inside the PM range is now refused (F15). Restore-seeded fires are alert-stamped — no
  retroactive orders.
- Watch job: `pm_retest` is a new read event; count it with the fires. Decide F15/F20 permanently from the walk-forward
  (both change which trades are taken).

## 2026-09-04 13:05 ET (run 9 — F15/F20 verified live on the tape; the day's model P&L flipped)

- **Alive, real-time, all three plans healthy.** `/api/health` ok v0.7.0, 63 armed. SPY/QQQ/IWM all
  `armed` + **auto** on the Practice sim book (`ff3c29d4`), `needsAttention: false`, pre-open complete
  (QQQ 717.13–722.06 gap_up/full, SPY 770.50–774.24 normal/none, IWM 293.24–295.92 normal/none).
  Quotes 0 s old, session `regular`; option quotes real-time OPRA (`provider: alpaca`, `delayed: false`,
  `source: opra` — IWM 296 C bid 0.14/ask 0.15 at 13:04); 1m bars banking in the runtime DB through
  **13:03 ET**, `barAgeSeconds` 103, `stale: false`; OPRA quote+trade polls HTTP 200 every ~2.4 s.
  **Zero `Traceback`, `ERROR` or `read_error`** in `zargar-8420.log` (42 warnings, all the benign
  `dropped N non-bucket-aligned stub bar(s)` + one FX 1:1 line). Running build = the 12:58 ET restart,
  so **F15, F20, F23 and F24 are all live** (the desk session deployed them; its log header is
  stamped 13:42/13:45 ET for a 12:58 ET restart — F21 again).
- **F23/F24 confirmed in the wild.** Since 12:58 the IWM audit has **no** new `skip_no_trade_zone` rows
  (it had 8 in the 30 minutes before, and 38 for the day) — `note_once` is doing its job. SPY's "Now"
  line reads "scenario 3 (bounce PDL) → calls · touches 0", the newest long setup's own count, not the
  spent short setup's 1.
- **F15/F20 verified against the DB tape, and they changed the day.** Today's model read is now
  **3 trades / 1 win / 2 losses, pnlPctSum +30.91** where run 8 saw 3 straight losses (−36.91):
  · SPY `pm_break_down@10:30` (15m close 770.30 < PM low 770.50 ✓) → **`pm_retest` 10:44** (2m bar
    high 770.49 within tolerance of 770.50, close 770.37 on the short's side ✓) → put 768 ≈ $0.39
    small → trim ⅓ at +53% (bar closing 11:00, 769.45 ✓) → rest at the planned target **769.26**
    (bar 11:02–11:03 traded to 769.05 ✓) = **+62.3%**; then touch #2 at the EMA13 11:08 (close
    769.70 vs EMA13 769.81 ✓) stopped −12.23% (2m close 769.87 back through it ✓).
  · IWM `pm_break_up@12:00` (15m close 295.97 > PM high 295.92 ✓) → **`pm_retest` 12:14** (close
    295.96 above the anchor ✓) → call 296 ≈ $0.38 small → −19.17% on the 12:26–12:27 close 295.87
    back through the level ✓. Its 12:32/12:34 retests are correctly refused: close 295.88/295.89 is
    below the anchor's tolerance band (295.893), i.e. not on the trade's side.
  · QQQ takes **nothing** — F15 refuses both of the entries it took this morning (10:02 at 720.84,
    11:06 at 717.97, both inside the 717.13–722.06 PM range), which removed −14.35% and −10.33%.
  Every 15m close, 2m close, EMA13 level and target touch quoted above was re-derived from the
  runtime DB's 1m bars and matches. Evidence appended to `TRADING-RULES.md`.
- **Replay parity exact on all three** (`POST /runs/{id}/replay` needs `-d '{}'`): SPY 8/8 events +
  2/2 trades, IWM 7/7 + 1/1, QQQ 5/5 + 0/0, identical strikes and P&L; the only diff is `bars2m`
  106→108, the 4 minutes that elapsed between the two fetches.
- **Still zero real orders.** All three of today's fires happened before the code that would take
  them existed, and restore-seeded fires are alert-stamped, so nothing routed to `_enter`. SPY's
  snapshot still carries the historical F22 refusal record (`$-267 equity`) from 11:08 — a
  write-ahead record, not a regression; the F22 fix has **still not been exercised live**.
- **F25 (new, NOT fixed — read labelling).** Entry-side read events are stamped with the 2m bar's
  OPEN, trades/exits with its CLOSE: IWM's fire says 12:14 while its own `entryTs` says 12:16, and the
  exit stamped 12:28 quotes the 12:26–12:27 bar's close (295.87; the 12:28 bucket closes 295.84). 15m
  events skew 15 min the same way. **No look-ahead** — `session.py:239` only consumes a 15m bar once
  its close time ≤ `end_ts`, which is why IWM's 12:00 PM break was first actionable on the bar ending
  12:16 (verified on the tape). Reporting defect only; the fix shifts event `ts` values that reach the
  append-only journal, sweep rows and ~40 tests, so it is **proposed, not built**.
- **Fixed and deployed with no restart:** the Armed/Team2 timeline had no icon for the new `pm_retest`
  event (nor `skip_reentries` / `skip_no_contract` / `skip_event_day`) — today's two PM-retest entries,
  the whole point of F20, rendered as anonymous "·" noise. Added to `EVENT_ICON` in
  `ArmedDayPanel.tsx` (`pm_retest` = ▲). `npm run build` clean; the server serves `dist` from disk, so
  the new bundle (`index-D2T0jFO4.js`, HTTP 200) is live **without touching the process**.
- **No restart queued.** Nothing pending needs one. Next code deploy should still wait for a moment
  with no setup taking touches (the desk is in AUTO and a fire inside a ~30 s restart window is seeded
  back as `alert`).
- **Next run should check:** whether a *fresh* fire finally reaches the book — `contract` →
  `entry_capped` → `position_open` → `live_trim` in the audit plus a `source: team2` row in
  `/api/orders`, which is also the first live exercise of the F22 equity fix; SPY's scenario 3 (769.26)
  and QQQ's scenario 1 (718.91, flipped on a 0.03 margin at 12:30) waiting for their first EMA13 touch;
  and the 15:30 last-entry / 15:45 flatten discipline.
- **Log-reading note for future runs:** `backend/zargar-8420.log` timestamps are **machine-local PT
  (ET − 3 h)** — 10:05 in the log is 13:05 ET. Earlier runs quoted log times as ET.

## 2026-09-04 13:50 ET (run 10 — quiet tape; F26 fixed and DEPLOYED, F27/F28/F29 raised)

- **Alive, real-time, all three healthy.** `/api/health` ok v0.7.0, 63 armed. SPY/QQQ/IWM all `armed` +
  **auto** on Practice (`ff3c29d4`), `needsAttention: false`, pre-open complete (SPY PM 770.50–774.24
  normal/none, QQQ 717.13–722.06 gap_up/full, IWM 293.24–295.92 normal/none). Quotes **0 s** old, session
  `regular`; option quotes real-time **OPRA** (`IWM260904C00296000` bid 0.09/ask 0.10, `src: opra`); 1m bars
  banking in the runtime DB through **13:33 ET** at check time (SPY 1,428 / QQQ 1,069 / IWM 976 rows in
  24 h), `barAgeSeconds` 71–103, `stale: false`. **Zero `Traceback`/`ERROR`/`read_error`** in
  `zargar-8420.log` apart from one `ConnectionResetError` at 13:32 ET which is this run's own HTTP client
  closing. **Practice equity is $8,989** (cash −4,566 against three open non-Team2 positions) — the F22
  premium pre-check would now pass a $1,014 Team2 ticket at 11% of equity.
- **Almost no new tape since run 9 (13:05).** One new event across the desk: QQQ's **13:00** 15m close
  **718.13** flipped the bias back to scenario 2 (reject PDH) → puts. Day unchanged: **3 model
  trades, 1 win / 2 losses, pnlPctSum +30.91** (SPY +62.31 then −12.23, IWM −19.17, QQQ 0).
  **Still zero real orders** — `/api/orders` has no `source: team2` row and nothing dated 2026-09-04.
  All three symbols are currently *inside or under* their PM ranges, so F15 refuses every entry: SPY
  769.35 (below its range, but its long setup needs a rally back into it), QQQ 716.71 and IWM 295.32
  (both inside). The F22 fix has **still not been exercised live**.
- **F23 confirmed holding.** IWM's read carries **2** `skip_no_trade_zone` rows for the day (one per
  setup) where run 8 counted 38. QQQ 2. The audit's IWM "40 skipped" total is all pre-12:58 rows.
- **Replay parity exact on all three**, before and after the restart: SPY 8/8 events, QQQ 6/6, IWM 7/7,
  identical P&L. No drift.
- **F26 (FIXED + DEPLOYED, commit `b86acda`).** `simulate_session` stopped taking entries with a bare
  `continue` in two places — past the **15:30 last-entry cutoff** (D6) and once `losses_today >=
  max_losses_per_day` (D-3). Neither wrote a read event, so today's 15:30 cutoff — the exact discipline
  this watch is asked to verify — would have passed with **no row in the read, the Armed timeline or the
  journal**, indistinguishable from a session with no setup. Now said **once** per session (the F23
  pattern): `skip_last_entry` names the cutoff and the flatten time it hands to, `skip_loss_cap` names the
  count and the cap. Additive only — no entry, exit or size changes; journaled and iconed (⛔).
  51 Team2 tests green, `npm run build` clean.
- **Deployed at 13:47 ET** via `start.ps1 -Detach`: nothing open or working on any plan and all three
  symbols refusing entries at the time, so the ~30 s restart window carried no fire risk. All 63 plans
  restored, all three back to `auto`, day P&L identical, parity re-verified after. The **frontend** change
  went out with no restart (server serves `dist` from disk; `index-Cs0_Vig7.js` HTTP 200). Note this
  restart also carries F23/F24/F15/F20 forward — they were already live from the 12:58 build.
- **F27 (NOT fixed — proposal).** `zone_tol_atr` is declared in `rules.py:37`, published in
  `/api/team2/status.thresholds`, and **read by nothing** — `ScenarioTracker.on_close` flips the desk's
  bias on a bare `bar.close > pdh.top` with no buffer and no decisiveness test. Evidence from today's QQQ
  15m bars re-derived off the runtime DB: the **12:30** bar closed **718.94** vs a zone top of **718.91** —
  a **0.025** margin, **0.086 × ATR**, body only 0.55 of range (under the `decisive_body_ratio` 0.6 the
  rules already define for breaks). It flipped the desk to calls, minted `scenario_1@12:30`, and the 13:00
  close flipped it straight back and invalidated it 30 minutes later. **Four** bias flips on QQQ today
  around a 0.31-wide zone, zero trades. Free today only because F15 was refusing QQQ anyway. Proposal: wire
  the knob (`close > top + tol·ATR`) and/or require a decisive body on a flip, shipped at 0.0/off so nothing
  changes until the walk-forward picks the value. **Threshold change — user's call.**
- **F28 (NOT fixed — proposal).** `runner.py` journals `scenario`, `pm_break` and `late_touch` under
  `ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED`. The bias flip and the PM break are the method's two *structural*
  events — the ones that arm the L2.6/L2.7 setups — and the append-only journal files them as trigger
  skips, which also inflates every skip count a review tool or morning report would read. Fix = an additive
  event constant in `zargar/events.py`; not built because that is shared vocabulary, the journal is
  append-only (the fix splits today's history) and EM's review CLI wants a look.
- **F29 (NOT fixed — open method question).** `max_losses_per_day` is counted **per symbol**, while
  `max_concurrent_positions` is deliberately counted **across all three plans** (A12). The code treats
  SPY/QQQ/IWM as one desk for risk *taken* and three desks for losses *absorbed*: today's 2 model losses
  leave a budget of 2 more in *each* symbol — up to 6 losers in a session the author would have left after
  2. Casey trades one book. Should the loss cap be desk-wide like A12? Cheap to build
  (`open_positions_across_plans` already exists), but it is a money rule.
- **Also seen, no action.** All three plans were flipped auto→alert→auto in an 11-second window at
  **13:16:41–13:16:52 ET** with no re-arm in between — a manual mode toggle from another session/UI, not a
  restart (a restart re-arms). Harmless here, but a fire inside such a window is alert-only. 15 mode changes
  per plan so far today.
- **Next run should check:** the **15:30 cutoff row** — every plan's read should now carry exactly one
  `skip_last_entry` at 15:30 (this is F26's first live exercise), then the 15:45 flatten; whether any symbol
  finally breaks clear of its PM range and places the desk's **first real order** (`contract` →
  `entry_capped` → `position_open` in the audit plus a `source: team2` row in `/api/orders`, also the first
  live exercise of the F22 equity fix); and whether the user has ruled on F27/F28/F29.


## 2026-09-04 14:15 ET (run 11 — THE DESK'S FIRST REAL ORDER; engine died at 14:01 and came back by itself)

- **The first Team2 money order ever placed.** QQQ `pm_break_down@13:30` → `pm_retest` **13:46** → auto
  **BUY 30 QQQ260904P00716000 @ $0.34** (limit 0.36) at **13:48:01 ET**, Practice sim book `ff3c29d4`.
  Closed **13:58:43** by the live premium stop (*"bid 0.24 is 29% below the 0.34 paid, limit 25%"*),
  filled 0.24 → realized **−$300** + $62.40 commission = **−$362.40**. Full chain in the audit:
  `TriggerFired → OrderIntent(qty 30) → SUBMITTED → PositionOpened(avgFill 0.34) → PlanError(premium stop)
  → PlanExit → OrderIntentCreated → RiskCheckPassed → OrderSubmitted → OrderAccepted → OrderFill →
  PositionClosed`, and two `source: technique` rows in `/api/orders`. **The F22 equity pre-check passed
  live for the first time** (a $1,020 ticket against ~$8,989 practice equity).
  *Note for future runs: order `source` is `technique`, not `team2` (the column is 12 chars) — earlier
  run logs told the next run to grep for `source: team2`, which will never match.*
- **Verified on the DB tape.** 13:30 15m bar closes **716.805** < PM low 717.13 ✓ → `pm_break`. The
  13:46–13:47 2m bar highs **717.1299** (the anchor 717.132, within tolerance) and closes **716.95**, on
  the short's side ✓ → `pm_retest` + fire, F20 working exactly as designed. The underlying stop (717.4513,
  a 2m close through the level) never triggered: the worst 2m close in the trade was 717.22.
- **F30 (new, NOT fixed — proposal).** The live premium stop measures **bid → ask-paid**; the model runs
  the *same* 25% rule mark-to-mark and did not fire until **14:12**, 14 min later. On a $0.34 contract the
  0.01 spread is ~3%, so the live guard spends an eighth of its budget before the underlying moves.
  Both sold the bottom: at 14:13 the same contract was **bid 0.335 / ask 0.345**, back to what was paid,
  with QQQ 717.08 still on the short's side of the 717.13 entry. Proposal: mid-vs-mid (or
  bid-vs-bid-at-entry) and/or a tick floor for cheap contracts. **Money rule — the user's call.**

  **Sharpened at 14:20 ET:** there are in fact **three** premium series answering the same 25% question and
  they disagree. The runner's guard (real **bid** vs ask paid) fired at 13:58; the **live read** still had
  the position open at 14:20 (in money modes it marks on the real premium, which had recovered to 0.335);
  the **replay** closed it at 14:12 on the synthetic mark-to-mark model. Same rule, same contract, three
  answers — that, not the 25% number, is the thing to settle first.
- **F31 (FIXED, committed — deploy QUEUED).** With the book flat, the Armed/phone headline still read
  "in trade … **1.00 left**". `runner.py` now appends "· book flat — the desk's contract is already closed
  (stop)" when a *filled* trade for that setup is closed (alert mode mints trades but never fills, so it
  stays silent). 51 Team2 tests green. **Not deployed this run:** SPY sits 0.02% from its `scenario_3`
  entry at 769.26 and the desk is in AUTO — a ~30 s restart window would alert-stamp that fire for a
  cosmetic label. Next run should deploy it when nothing is taking touches.
- **The engine died at 14:01:05 ET and restarted itself at 14:02:19.** No traceback, no shutdown line —
  the Windows Application log shows **"Claude VM Service stopped" at 11:01:05 PT / "starting" at 11:01:06**,
  the same second the log went silent. The `ZargarUnelevatedStart` scheduled task
  (`start.ps1 -Detach`) ran at 11:01:54 PT and brought it back: engine up 14:02:19, **all 63 plans
  restored**, 3 Team2 plans back in `auto`, `team2_plan_nightly` 17:00 and `team2_preopen` 09:25
  re-registered. **No money was left unmanaged** — the QQQ position had closed at 13:58, three minutes
  before. Worth the user knowing: the trading engine is currently collateral damage of a Claude desktop
  service restart, and the ~75 s hole would have been a naked 0DTE position had it landed a few minutes
  earlier. Not a Team2 defect; not fixed here.
- **Everything else healthy.** `/api/health` ok v0.7.0, 63 armed; all three plans `armed` + auto,
  `needsAttention: false`. Quotes **0–0.2 s** old, session `regular`; the option quote is real-time
  **OPRA** (`QQQ260904P00716000` bid 0.335/ask 0.345, `src: opra`); Alpaca stream connected; 1m bars
  banking through **14:07 ET** (SPY 1,428 / QQQ 1,069 / IWM 977 rows in 24 h), age 81 s.
  **Zero `Traceback`/`ERROR`/`read_error`** since the restart (40 warnings, all the benign
  `dropped N non-bucket-aligned stub bar(s)` plus the known SPX calendar 404).
- **Day so far: 3 closed model trades, 1 win / 2 losses.** SPY `pm_break_down@10:30` +62.31 then −12.23
  (net +50.08), IWM `pm_break_up@12:00` −19.17, QQQ `pm_break_down@13:30` −29.54 (model) / −$362 (book).
  QQQ's bias flipped a 4th and 5th time (12:30 scenario 1, 13:00 scenario 2) — more F27 evidence.
- **Replay parity exact on SPY (8/8 events, 2/2 trades) and IWM (7/7, 1/1).** QQQ shows the expected
  one-bar drift: the replay ran to 14:12 and reproduced the model's own premium-stop exit the live read
  had not reached yet (9 vs 10 events). Note for future runs: `POST /runs/{id}/replay` returns the read
  under **`result`**, not at the top level.
- **Next run should check:** the **15:30 `skip_last_entry` row** on each plan (F26's first live exercise)
  and the 15:45 flatten; whether the queued F31 deploy went out; whether SPY takes its `scenario_3`
  EMA13 touch at 769.26 and IWM its own; and whether the user has ruled on F27/F28/F29/F30.

## 2026-09-04 14:35 ET (desk session) — halt scopes deployed

- Platform gap closed (commit 29bdb45, merged b52b0c9, deployed 14:31 ET via alert → restart → auto): the daily-loss
  breaker halts only the losing BOOK (`risk.daily_loss_halt_scope=portfolio`), a technique can pause itself on a book
  (`techniques.<id>.daily_loss_halt_pct`; Team2 = 10), the HALT button stays global. RiskGate check `book_halt`,
  `POST /api/portfolios/{pid}/resume`, Armed summary `bookHalts`, kill-switch tile shows a halted book. PLATFORM-RULES
  has the three scopes. `risk.daily_loss_halt_pct` is still 12 for practice (raised this morning) — with per-book
  scope there is no longer a reason for it; the user may put it back to 8.
- After the restart only SPY and IWM are armed for Team2 (62 plans restored) — QQQ's plan is no longer armed; see the
  desk's note below / the plan's journal.
- **14:33 ET addendum.** QQQ's plan was disarmed at 14:17 by its own per-plan loss halt: two real round trips
  (30 × 716p 0.34→0.24 = −$300; 18 × 717p 0.59→0.56 = −$54, flattened on the disarm, all filled, book flat) crossed
  a $341 limit — the limit derived at 2% risk this morning, never re-derived when risk went to 6% in place. Fixed
  (commit db1f315): a risk % change in auto re-derives the dollar loss halt; SPY/IWM now carry $997 (6% × 2).
  Deployed 14:31 with the halt scopes. QQQ stays disarmed for today (its own day is over, by the plan's rule).

## 2026-09-04 14:45 ET (run 12 — QQQ is out for the day on its own loss halt; the halt math is $100 short)

- **Alive and real-time, but only TWO plans.** `/api/health` ok v0.7.0, 62 armed. SPY and IWM `armed` +
  **auto** on Practice (`ff3c29d4`), `needsAttention: false`, nothing open or working; **QQQ is
  disarmed** (see below). Quotes 0 s old, session `regular`; the 14:16 order intent proves the option
  side is real-time **OPRA** (`priced: "opra"`, bid 0.58/ask 0.59), and the log shows OPRA
  quote+trade polls returning 200 every ~2.4 s. 1m bars banking through **14:44 ET** for SPY (1,428
  rows/24 h) and IWM (977), age 73–118 s, `stale: false`. **Zero `Traceback`, `ERROR` or `read_error`**
  in the 4,586 log lines since the 14:33 restart — 43 warnings, all the benign
  `dropped N non-bucket-aligned stub bar(s)`.
- **The engine restarted twice more** (14:30 and 14:33 ET, both `start.ps1` deploys by the desk
  session — halt scopes `29bdb45` and the loss-limit recompute `db1f315`). Both restored cleanly.
  Confirmed live: SPY and IWM now carry **`dailyLossLimit` $997.08** (6 % × 2), not the stale $341.38
  they were restored with at 14:30 — `db1f315` is working.
- **QQQ took a SECOND real order and then disarmed itself.** `pm_break_down@13:30` touch #2 fired at
  **14:16**: **BUY 18 QQQ260904P00717000 @ $0.59** (limit 0.59, $1,062). At **14:17** the per-plan loss
  halt fired — *"realised −300.00 + open −54.00 marked at bid crossed −341.38"* — and the plan was
  **disarmed and flattened** at 0.5599. Correct behaviour by the rule as written; QQQ's day is over.
  Full chain in the audit, four `source: technique` executions in the DB. Day's book damage on Team2:
  **−$454.02** (gross −$354.18 + **$99.84** commission).
- **F32 (new, NOT fixed — the loss halt does not count commissions).** The halt sums
  `trade.realized_pnl`, which is gross. After the FIRST QQQ round trip the book was already down
  **−$362.40**, past the plan's −$341.38 limit, but the halt read **−$300** and let the second entry
  through. On a $0.30–0.60 0DTE contract the round-trip fee is 6–12 % of premium — the halt understates
  the day exactly where it is meant to bind. **Shared engine + money rule — the user's call.**
- **F33 (new, NOT fixed — the halt is checked after the entry, never before it).** `_on_bar` runs
  `_act` (which fires, sizes and routes) and only then `_maybe_loss_halt`. So at 14:16 the plan opened a
  **$1,062** ticket with **$41** of gross budget left; one minute of spread was enough to trip the halt
  and force an immediate flatten that bought nothing but **$37.44** of commission. Proposal: refuse an
  auto entry whose premium-at-risk exceeds the remaining daily budget, with a `skip_loss_budget` read
  event — same shape as `max_open_trades` / A12. **Shared engine + money rule — the user's call.**
- **F36 (new, NOT fixed — the read and the book bought different contracts).** On that same 14:14 fire
  the read says *"buy put **716** ≈ **$0.26**"* while the order was **717 P at $0.59** — 2.3× the
  premium, so the model's −19 % and the book's −$91.62 are not comparable. Both aim at
  `target_premium` 0.60: the model's flat-IV BS mark for 717 was a hair over 0.60 (σ 0.1669 vs OPRA's
  0.1335) so it stepped OTM; the live picker saw the real ask 0.59 ≤ 0.60 and stopped. One cent decides
  the strike, the premium and the size. Same family as F30. The 13:46 fire agreed (716, $0.33 model /
  $0.36 live) — the split only appears when the ATM contract prices within a cent of the target.
- **F26's first live exercise passed.** QQQ's read carries `skip_loss_cap` at **14:18**: *"2 losing
  trades today (max 2) — done taking entries in this symbol for the session (D-3)"*. Exactly the row
  that did not exist before this morning. (The 15:30 `skip_last_entry` row is still ahead of us.)
- **F34 + F35 (FIXED, committed `40954d6`, deploy QUEUED).** F34: nothing kept the desk's symbols on
  the feed once a plan was gone — QQQ's 1m bars **stopped at 14:28** because the 14:33 restart re-armed
  only SPY and IWM, so the day's replay of the disarmed plan is truncated at the disarm (confirmed: its
  replay reads 147 2m bars and stops). `attach_team2_runner` now `ensure_symbol`s every
  `techniques.team2.symbols` entry at boot, armed or not. F35: a disarmed plan vanished from the Plans
  tab as a bare *"not armed"* though `technique_armed` already stores `status: disarmed` + the full
  `stopReason`; `Team2Service.runs()` now returns both and the page prints the reason. Reporting and
  data continuity only — no entry, exit or size changes. 51 Team2 tests green, `npm run build` clean
  (the frontend half is already live, dist is served from disk).
- **Deploy queued for the 16:05 run (post-close).** SPY sits 0.10 % from its `scenario_3` entry
  (769.26) and IWM 0.12 % from its `pm_break_up` anchor (295.92) with the desk in AUTO — neither fix is
  worth alert-stamping a fire for, and 15:30–15:45 must stay untouched (last entry + flatten).
- **Replay parity exact on all three**, including the disarmed QQQ: SPY 8/8 events + 2/2 trades,
  IWM 7/7 + 1/1, QQQ 14/14 + 2/2, identical P&L (only `bars2m` 155 vs 156 = the minute between fetches).
- **Day so far (model): 5 trades, 1 win / 4 losses.** SPY `pm_break_down@10:30` +62.31 then −12.23
  (net +50.08), IWM `pm_break_up@12:00` −19.17, QQQ two at −48.56 combined. Book: −$454.02, all QQQ.
- **UI not visually checked this run** — the in-app browser drops `?token=` on the SPA redirect and
  lands on the sign-in page; the page change was gated on typecheck + build instead.
- **Next run should check:** the **15:30 `skip_last_entry` row** on SPY and IWM and the **15:45
  flatten**; whether SPY takes its `scenario_3` EMA13 touch at 769.26 or IWM clears 295.92 (it is
  inside its PM range, so F15 refuses every entry until it does); that the queued `40954d6` deploy goes
  out after 15:45; and whether the user has ruled on F27/F28/F29/F30/F32/F33/F36.

## 2026-09-04 15:00 ET (desk session) — F25–F36 built and deployed

- User: "implement all the fixes and then restart the engine". Commit bd2a39a (+ F34/F35 from the watch job) deployed
  14:57 ET via alert → restart → auto (no Team2 trade open). Closed: F25 one clock (read events at the bar CLOSE;
  the first 2m close past 15:30 now reads 15:32), F27 `zone_tol_atr` + `flip_body_ratio` wired at 0, F28
  `TechniquePlanRead` journal kind, F29 desk-wide loss cap (`losses_desk_wide`, `skip_loss_cap_desk`), F30
  `premium_stop_basis=mid` + `premium_stop_min_ticks=3`, F32 halts net of fees, F33 `skip_loss_budget` before
  routing, F36 `premium_pick=closest` in both paths. 107 tests green. PLATFORM-RULES logs the shared knobs.
- Watch job: expect `TechniquePlanRead` rows instead of skip rows for scenario/pm_break/late_touch/pm_retest; skip
  counts drop accordingly. Both plans carry a $997 loss halt at 6% risk.


## 2026-09-04 15:30 ET (run 13 — the F25–F36 build is live and healthy; the desk is now loss-capped out for the day)

- **Alive, real-time, two plans.** `/api/health` ok v0.7.0, 62 armed. SPY and IWM `armed` + **auto** on
  Practice (`ff3c29d4`), `needsAttention: false`, no `readError`, nothing open or working. Quotes **0–1 s**
  old, session `regular`; the Alpaca stream logged *connected* + *authenticated* at 14:56:30 ET and the
  OPRA quote/trade polls return 200 continuously. **Zero `Traceback` / `ERROR` / `read_error`** in the
  2,730 log lines since the 14:57 restart — 22 warnings, all the benign `dropped N non-bucket-aligned
  stub bar(s)`. Reads current: `regimeLast` at 15:00, bar age 62–82 s.
- **Every queued deploy is out and verified live.** `bd2a39a` (F25–F36) + `40954d6` (F34/F35) + F31 went
  out at 14:57. Confirmed on the running process: `losses_desk_wide=true`, `premium_pick=closest`,
  `premium_stop_basis=mid`, `premium_stop_min_ticks=3`, `zone_tol_atr=0.0`, `flip_body_ratio=0.0` all
  present in `/api/team2/status.thresholds` and settings; both plans carry `dailyLossLimit` **$997.08**.
  **F34 proven:** QQQ's 1m bars are banking again (**1,043** rows/24 h, last 15:03) although its plan is
  disarmed — before the fix they stopped at 14:28. **F35 proven, including in the UI:** the Plans tab
  prints *"disarmed — loss halt: realised -300.00 + open -54.00 marked at bid crossed -341.38"* on the
  QQQ row instead of a bare "not armed". **F25 proven:** read events now carry the bar's **close** —
  today's SPY break reads `10:45 pm_break` where run 12 saw `13:30` for the same shape on QQQ.
- **No new trades, model or real, since 14:18.** SPY: `pm_break_down@10:30` fired twice in the model
  (10:46 +57.45 % to target, 11:10 −12.23 % on the EMA13 stop), bias flipped to **scenario 3 (bounce PDL)**
  at the 11:15 close and has not moved since; `scenario_3@11:00` is **waiting** at 769.26, price 770.12,
  **0.11 %** away, 0 touches. IWM: `pm_break_up@12:00` fired once (12:16, −19.17 % on the one-candle
  stop), `scenario_3@09:30` waiting at 293.88; price 295.56 sits inside the PM range so F15 refuses
  every touch. Day (model): **5 trades, 1 win / 4 losses**; book: **−$454.02**, all QQQ.
- **Replay parity exact on all three.** SPY 8/8 events + 2/2 trades (pnlPctSum 45.22 both sides),
  IWM 7/7 + 1/1 (−19.17), QQQ 11 events + 1 trade off the restored tape. *Note for future runs:*
  `POST /runs/{id}/replay` needs a JSON body (`-d '{}'`), else FastAPI 422s.
- **Parity against the LIVE audit is only valid within one deploy generation.** SPY's model fire at
  10:46 and IWM's at 12:16 have **no** `TechniquePlanTriggerFired` row — the live runner logged
  `skip_no_trade_zone` at those minutes, because F20 (the PM-level retest entry) and F15 were not
  deployed until 12:58. Today's read is recomputed by the newest code and therefore trades a day the
  desk did not live. Do not read "model fired, audit didn't" as a defect on 2026-09-04 before 12:58.
- **F37 (new, NOT fixed — proposal; binding right now).** F29's desk-wide loss cap counts
  `max(model losers, real losers)` per armed plan. SPY 1 + IWM 1 = **2 of 2**, so **the desk is refusing
  every remaining entry today** — including SPY's `scenario_3` 0.11 % away — on the strength of two
  simulated losses the live runner **explicitly declined at the time** (the `skip_no_trade_zone` rows
  above). A rule for a desk that is bleeding is being tripped by hindsight. Proposal: in auto/proposal,
  count the **book** once a plan has routed an order; keep the model basis for alert-mode plans; name the
  basis in the skip line. **Money rule — the user's call.**
- **F38 (new, NOT fixed — proposal).** `losses_across_plans()` iterates `self._armed`, so QQQ's two
  **real** losers left the desk count the instant its own loss halt disarmed it at 14:17. The cap
  loosens right after the worst thing a plan can do. Harmless today (F37 already holds the desk at 2),
  but on a day QQQ eats both desk losses and halts out, SPY and IWM would each restart with a budget
  of 2. Also noted: the F29 gate is not mode-guarded, unlike the two gates around it.
- **F39 (new, NOT fixed — shared engine, latent).** `planrunner.py:2396`: with equity **negative**
  every option entry is blocked under a bogus "over N% of equity" message; with equity exactly **0**
  the cap is skipped entirely. Today this only appeared as the pre-F22 symptom — SPY's 11:10 fire was
  refused against *"the account's $-267 equity"*, which was the Practice book's **cash**, not its
  equity. With F22 live the same book reads **$8,401** and the 13:48 QQQ ticket passed. Still worth an
  explicit `eq <= 0` refusal. **`zargar/execution/planrunner.py` — proposal, not built here.**
- **Nothing built or deployed this run.** All three findings are money rules or shared-engine changes,
  and it is 15:30 — the last-entry cutoff — with the desk in auto. No restart.
- **Next run (16:05, post-close) should check:** whether the **15:32 `skip_last_entry`** row appeared on
  SPY and IWM (F26's first live exercise — expect it at the first 2m close past 15:30, per F25's clock)
  and the **15:45 flatten**; that no entry was taken after 15:30; the nightly `team2_plan_nightly` at
  17:00; the day's final read/replay parity and the scorecard; and whether the user has ruled on
  F27/F28 residue, F29's basis (**F37**), **F38**, **F39**, and the still-open F30-family question of
  which premium series is authoritative.

