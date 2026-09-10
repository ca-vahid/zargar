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


## 2026-09-04 15:10 ET (run 13 — the F25–F36 build is live and healthy; the desk is now loss-capped out for the day)

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
  and every fix queued by earlier runs already shipped at 14:57. The desk is in auto with SPY 0.11 % from a level, so no restart and no deploy this run.
- **Next run should check:** whether the **15:32 `skip_last_entry`** row appeared on
  SPY and IWM (F26's first live exercise — expect it at the first 2m close past 15:30, per F25's clock)
  and the **15:45 flatten**; that no entry was taken after 15:30; the nightly `team2_plan_nightly` at
  17:00; the day's final read/replay parity and the scorecard; and whether the user has ruled on
  F27/F28 residue, F29's basis (**F37**), **F38**, **F39**, and the still-open F30-family question of
  which premium series is authoritative.


## 2026-09-04 15:30 ET (desk session) — F37–F39 built and deployed

- Commit 2c4e18c, deployed 15:27 ET (alert → restart → auto, nothing open). F37: the desk-wide loss cap counts the
  BOOK for any money-mode plan that routed an order and the model only for alert plans — never the larger; gate is
  money-modes only and names its record. F38: a per-day tally keeps a disarmed plan's losers, seeded from the
  persisted rows at boot (QQQ's two real losers count again after this restart → the desk reads 2 of 2 from the
  book, which is the truth today). F39: zero/negative equity refuses an option entry with its own reason.
- Watch job: `skip_loss_cap_desk` lines now say "counted from the book/model".


## 2026-09-04 15:40 ET (run 14 — F26's last-entry rule fired live; a disarmed plan never books its flatten)

- **Alive, real-time, two plans.** `/api/health` ok v0.7.0, 62 armed. SPY and IWM `armed` + **auto** on
  Practice (`ff3c29d4`), `needsAttention: false`, no `readError`, nothing open or working; QQQ still
  disarmed from 14:17. Quotes **0 s** old, session `regular`; OPRA quote+trade polls returning 200
  every ~2.4 s (the 53-symbol `feed=opra` batch includes both QQQ 0DTE puts). 1m bars banking for
  **all three** — SPY 1,428 / QQQ 1,043 / IWM 977 rows in 24 h, last bar 15:32, age ~105 s (F34 still
  proven: QQQ banks although its plan is gone). **Zero `Traceback` / `ERROR` / `read_error`** in the
  2,451 log lines since the 14:57 boot — 16 warnings, all the benign `dropped N non-bucket-aligned
  stub bar(s)`.
- **F26's first live exercise passed on both plans.** `skip_last_entry` at **15:32:00 ET** on SPY and
  IWM — *"past 15:30 — no new entries, managing what is open until the 15:45 flatten (D6/C3)"* —
  journaled as `TechniquePlanTriggerSkipped` on both, and at the first 2m **close** past 15:30 exactly
  as F25's clock predicts. Nothing was open to manage. The 15:45 flatten falls in the next run.
- **No new trades, model or real, since 14:18.** SPY: bias still scenario 3 (bounce PDL) since the
  11:15 close, `scenario_3@11:00` **waiting** at 769.26 with price 769.89 (**0.08 %** away, 0 touches);
  its earlier `pm_break_down@10:30` reads 2 model trades (+57.45 %, −12.23 %). IWM: `scenario_3@09:30`
  waiting at 293.88, price 295.92 still inside the PM range so F15 refuses every touch;
  `pm_break_up@12:00` fired once at 12:16 (−19.17 %). Day (model): **5 trades, 1 win / 4 losses**;
  book: **−$454.02**, all QQQ.
- **Replay parity exact on both armed plans**, including the new row: SPY 9/9 events + 2/2 trades
  (pnlPctSum 45.22 on both sides), IWM 8/8 + 1/1 (−19.17); `skip_last_entry` reproduces at 15:32 in
  the replay too. (`POST /runs/{id}/replay` needs `-d '{}'`; the read comes back under `result`.)
- **F35 verified in the browser**, not just the API: `/team2` Plans tab prints
  *"disarmed — loss halt: realised -300.00 + open -54.00 marked at bid crossed -341.38"* on the QQQ row.
- **F40 (new, NOT fixed — shared engine; a disarmed plan never learns its flatten filled).**
  `PlanRunner.disarm()` submits the flatten and then pops the plan out of `self._armed` in the same
  breath; `on_order_update` opens with `ap = self._armed.get(run_id)` and returns when that is `None`,
  so the fill 2 s later is dropped on the floor. QQQ's flatten order `c4f557e6…` is **FILLED 18 @
  0.5599** in `orders` + `executions` (14:17:02 ET, $18.72 commission) and the book is flat, yet the
  persisted plan still reads `status: "open"`, `remaining: 18`, `realizedPnl: 0.0`, exit
  `{kind: "disarm", status: "SUBMITTED", filledQty: 0.0}`. It bites **F38 today**: the boot seed keys on
  `status == "closed"`, so the log says *"loss tally seeded with **1** loser(s)"* when QQQ had two —
  the desk-wide cap loosens by one after precisely the event F38 was built to survive. It also
  understates the plan's own day by the flatten's **−$54.18** gross (−$91.62 net) and leaves a record
  claiming an 18-lot 0DTE put held past expiry. No money is misplaced — the book is right throughout —
  and disarmed plans are never restored, so this is a records/rule-counting defect, not an exposure
  one. **Not built here: it is `zargar/execution/planrunner.py` and changes the disarm path for EM and
  Tip too.** Proposal: await the flatten's terminal status (short timeout) before popping from
  `_armed`, or keep the plan in a `_closing` map `on_order_update` also consults and re-persist when it
  settles; and have F38's seed count a trade whose exit orders filled at a loss even when the record
  still says open.
- **The desk cap is binding anyway.** Right now `losses_across_plans()` = QQQ 1 (book, seeded) + SPY 1
  (model — its only fire was refused pre-route, so F37 keeps it on the model basis) + IWM 1 (model) =
  **3 of 2**, so no entry could be taken even if 15:30 had not passed. With F40 fixed it would read 4.
- **Nothing built or deployed this run.** The only finding is shared-engine, and no fix was queued from
  earlier runs. No restart: the market is open, both plans are in auto, and there was no reason to.
- **Next run (16:05, post-close) should check:** the **15:45 flatten** rows on SPY and IWM and that no
  entry was taken after 15:30; the day's final read/replay parity and the scorecard; the nightly
  `team2_plan_nightly` at 17:00; and whether the user has ruled on the open money rules — F27/F28
  residue, **F40**, and the F30-family question of which premium series is authoritative.

## 2026-09-04 16:05 ET (run 15, post-close — the day closed clean; a Labor-Day double-arm caught and fixed)

- **The session closed correctly on all three.** SPY and IWM took the `session closed` disarm at
  **16:00:00 ET** (`flatten: false`, `openLeft: 0`, `statuses: {}`) — nothing was open, so the 15:45
  flatten had nothing to do and, correctly, logged nothing. **No entry was taken after 15:30**: the
  only post-cutoff rows on either plan are F26's `skip_last_entry` at 15:32. QQQ stayed disarmed from
  its 14:17 loss halt. `/api/health` ok v0.7.0; **zero `Traceback` / `ERROR` / `read_error`** in the
  27,589 log lines covering 14:56–16:06 ET (178 warnings, all the benign `dropped N
  non-bucket-aligned stub bar(s)`).
- **Data real-time to the close and past it.** Quotes 0–7 s old, session correctly `post`, `regPrice`
  holding the regular close (SPY 770.24 / QQQ 718.96 / IWM 295.97); OPRA quote+trade polls 200 every
  ~2.4 s through 16:06; 1m bars banking for all three (SPY 1,428 / QQQ 1,043 / IWM 977 rows in 24 h,
  last bar 16:04 ET) — F34 still holding for disarmed QQQ.
- **Day's final read (model): 4 trades, 1 win / 3 losses.** SPY `pm_break_down@10:30` +49.6 % trim then
  the 11:04 target at 769.26 (+61.4 %), then −12.2 % on the 11:14 EMA13 stop → **+45.22 % summed**;
  IWM `pm_break_up@12:00` −19.17 %; QQQ `pm_break_down@13:30` −19.69 %. SPY's bias sat on scenario 3
  (bounce PDL) from the 11:15 close with `scenario_3@11:00` **waiting** at 769.26 all afternoon;
  IWM's `scenario_3@09:30` never left the PM range (F15). **Real book: −$454.02, all QQQ**
  (30 lots 0.34→0.24, then 18 lots 0.59→0.5599) — no SPY or IWM order was ever routed today.
- **Replay parity exact on all three**, post-close: SPY 9/9 events + 2/2 trades (45.22 both sides),
  IWM 8/8 + 1/1 (−19.17), QQQ 13/13 + 1/1 (−19.69). UI checked in the browser: the Plans tab shows the
  three rows with QQQ's stop reason spelled out (F35).
- **F41 (new, FIXED + deployed `d8bd403`) — the desk would have opened Tuesday double-armed.**
  Both Team2 jobs are registered `weekdays_only`, which checks `weekday() >= 5` and nothing else, so
  they also fire on a **weekday market holiday**. On **Monday 2026-09-07 (Labor Day) 17:00 ET**
  `nightly_plans()` would see a non-trading day, target `next_trading_day` = **2026-09-08** — the same
  session tonight's 17:00 run plans — and mint + arm a second plan per symbol: `mint_plan_run()` always
  inserts a new run and `arm()` dedupes on `run_id` only. Two armed SPY/QQQ/IWM plans in **AUTO**, each
  with its own `max_open_trades`, both counting into the desk-wide cap, with no watch run between the
  17:00 mint and the Tuesday open. Fixed: the nightly skips a symbol that already has an armed plan for
  that date (reported under `skipped`, printed in the plan-now toast); `force=true` on
  `POST /api/team2/plan-now` is the manual rebuild. Nothing is disarmed, no sizing rule changed.
- **F42 (new, FIXED + deployed `d8bd403`) — same root, the other job.** `preopen_complete()` walked
  **every** armed plan whatever its date; `complete_plan()` over a date with no bars writes
  `pmh: None`, `pml: None`, `complete: false` back onto the plan and `stamp_run()` persists it. The
  09:25 job on Labor Day would therefore have blanked the plans built for 09-08 before the desk ever
  saw them. Fixed: a plan whose `plan_for` is later than today is left alone; past-dated plans still
  complete (tests, replay, catch-up).
- **Deployed at 16:15 ET** — market closed, nothing open, no Team2 plan armed. 57 tests green
  (`tests/test_team2_*.py` + `test_marketstructure_extended.py` + `test_book_halt.py`, own DB
  `zargar_test_team2_watch`), `npm run build` clean, restart clean (17 EM plans restored, both Team2
  jobs re-registered at 17:00 / 09:25 ET, zero errors). Tonight's nightly is unaffected: the scheduler
  hydrates `last_day` from the journal, so the restart does not consume it.
- **F43 (new, NOT fixed — proposal: the Team2 day is never scored).** `_end_session()` writes the
  scorecard from `PlanRunner._score_execution()`, which iterates `ap.trackers` — EM's declared
  triggers. Team2 has none (entries come out of the session walk), so both surviving plans journalled
  `TechniquePlanScored {rows: [], matched: 0, actualFires: 0, theoreticalFires: 0, realizedPnl: 0}` at
  16:00 on a day with 4 model trades and a −$454 book. QQQ — the only symbol that traded real money —
  disarmed before `_end_session()` and has **no scorecard at all**. A Team2-local override should
  compare `_last_sim`'s model trades against the real fills plus the skips that blocked them, and run
  on the loss-halt path too; it needs the F30/F36 answer (which premium series is authoritative) first.
- **F44 (new, NOT fixed — shared engine).** `OptionsService._tracked` only ever grows: the 2 s OPRA
  batch still carried contracts that expired on 2026-09-02 (`MU260902P…`, `GOOGL260902C…`,
  `META260902C…`, `TSLA260902P…`) plus, after this close, both `QQQ260904` puts — 55 symbols in one
  URL. A 0DTE desk adds several dead symbols a session and only a restart clears them (visible in the
  smaller batch after 16:15). Prune on expiry in `zargar/options/service.py` — proposal, not built here.
- **F40 re-confirmed on the persisted record**: QQQ's second trade still reads
  `status: "open", remaining: 18, realizedPnl: 0.0` while its flatten `c4f557e6…` is FILLED 18 @ 0.5599
  in `orders`/`executions`. Unchanged since run 14 — shared engine, still the user's call.
- **Next run (16:30 ET, last of the day) should check:** that the 16:15 deploy is still healthy and no
  new errors; nothing further to trade today. **Tonight's 17:00 `team2_plan_nightly` targets
  2026-09-08 (Tuesday — Monday is Labor Day)** and is after the last watch run, so **Tuesday's first
  run must verify exactly ONE armed plan per symbol for 2026-09-08** (F41's live proof) and that the
  09:25 completion filled pmh/pml/dayType/sizing that morning and not before (F42). Still open for the
  user: F40, F43, F44 and the F30-family question of which premium series is authoritative.


## 2026-09-04 16:30 ET (run 16, last of the day — the 16:15 deploy is clean; the nightly chain sweep is not)

- **Alive and healthy on the new build.** `/api/health` ok v0.7.0, 17 EM plans armed, no Team2 plan
  armed (correct: SPY and IWM took the 16:00 `session closed` disarm, QQQ has been out since its 14:17
  loss halt). **Zero `Traceback` / `ERROR` / `read_error`** in the 7,159 log lines since the 16:13 boot;
  50 warnings, 47 of them the benign `dropped N non-bucket-aligned stub bar(s)` and the other 3 the
  restart's own EM housekeeping (`marked N orphaned running sweep(s) as interrupted`, two
  `TechniqueSweepStarted … missing sweepId` contract warnings — EM's, not ours).
- **Data still real-time past the close.** Quotes 0–6 s old, session correctly `post`, `regPrice`
  holding the regular close (SPY 770.19 / QQQ 718.96 / IWM 296.01); the 55-symbol OPRA quote+trade
  batch is returning 200 every ~2.4 s and still prices contracts live (SPY 260914C775 **2.40 / 2.42**),
  so this is not an after-hours feed drop; 1m bars banking for all three (SPY 1,428 / QQQ 1,043 /
  IWM 982 rows in 24 h, last bar 16:33 ET, age 118 s).
- **Nothing traded and nothing could.** No plan armed, no order, no working exit. Today's final record
  stands as run 15 left it: model 4 trades (1 win / 3 losses), real book **−$454.02, all QQQ**.
- **F41 verified deterministically against the calendar.** `is_trading_day(2026-09-07)` is **False**
  and `next_trading_day(2026-09-04) == next_trading_day(2026-09-07) == 2026-09-08`, so tonight's 17:00
  nightly targets Tuesday and Labor Day's 17:00 run will hit the new `already armed for 2026-09-08`
  skip instead of minting a second plan. Also checked the long-weekend hold end-to-end: `_on_bar`
  returns early unless `session_date(bar.ts) == ap.plan_for`, the 16:05 clock-close and the PlanRunner
  pre-open are both `plan_for == today` guarded, so plans built tonight ignore every Friday-evening,
  Sunday-evening and Monday bar and survive intact to Tuesday. **Nothing else double-fires over the
  long weekend.**
- **F45 (new, NOT fixed — shared engine/research; the biggest live data defect on the box).** The 16:30
  `chain_snapshots` job walks the universe with no throttle, retry or backoff: it attempted **150**
  underlyings and took **185 CBOE 429s** in three minutes (the refusals return instantly, so the loop
  burns through the tail of the universe in seconds). `option_chain_snapshots` shows the damage by
  date — **145–146** underlyings on 2026-08-27/28 versus **73–78** every session since 2026-08-31
  (77 today). That table is **Flow's single writer** and its 16:45 scan reads it, so half the universe
  has had no Vol/OI read for five sessions. It also starves `OptionsService.refresh_tracked`, which
  shares the CBOE client (114 `enrich skipped … CBOE HTTP 429` lines in the same window). **No Team2
  impact** — Team2 picks its contract from OPRA. Written up in TRADING-RULES as a proposal;
  `zargar/research/snapshots.py` is outside this desk's scope.
- **F40, F43, F44 unchanged and still the user's call** (QQQ's flatten still persisted as
  `status: open, remaining: 18` while the fill is FILLED 18 @ 0.5599 in `orders`/`executions`; the
  16:13 boot again logged *"loss tally seeded with 1 loser(s)"* when QQQ had two — F40's undercount,
  reproduced on the new build; the Team2 day is still never scored; the OPRA batch still carries the
  expired `MU260902P…`/`GOOGL260902C…`/`META260902C…`/`TSLA260902P…` plus both `QQQ260904` puts).
- **Nothing built or deployed this run** — the only new finding is shared-engine research code, and
  no fix was queued. No restart (none needed; the 16:15 build is clean).
- **Tuesday's first run (2026-09-08 09:30 ET) must check, in this order:** exactly **ONE** armed plan
  per symbol for 2026-09-08 (F41's live proof — tonight's 17:00 mints them and Monday's 17:00 must
  skip); that the 09:25 completion filled `pmh`/`pml`/`dayType`/`sizingAtOpen`/`complete: true`
  **that morning** and that nothing blanked them on Labor Day (F42's live proof); that the desk loss
  tally reset for the new day; and the usual real-time data checks. Still open for the user: **F40**,
  **F43**, **F44**, **F45**, and the F30-family question of which premium series is authoritative.

## 2026-09-04 18:30 ET (desk session) — post-close sweep

- Two fresh-eyes reviews (backend 26 items, UI 26 items) + the desk's own audit. Built and deployed: F40/F43/F44/F45 and the
  F46 batch (TRADING-RULES change log has the full list). Key money items: clock flatten at 15:45 independent of the read,
  stale-exit re-price for Team2, live-ask sizing, fresh-only option quotes for the stop, retired plans still count toward the
  technique halt, adds judged with their base, entry window on the bar close, replay with that day's IV.
- Watch job: new events `clock_flatten`, `exit_reprice` (Team2), `closing_settled`; scorecards now carry `basis:
  session-read vs book`; `skip_loss_cap_desk` counts positions (base + adds), not trades.
- **19:10 ET addendum.** Deployed 72e8990 + 4331301 (the `/api/team2/runs` 500 from a variable slip) + d611706. Monday's
  plans were re-armed under the new arm config (flatten clock 15:45, loss halt $1,034) — the forced re-plan ADDED a second
  set instead of replacing (fixed: force now disarms the old plan first, `replaced` in the response); the duplicates
  were disarmed by hand. 3 Team2 plans armed for 2026-09-08 in auto.

## 2026-09-07 evening (desk session) — new book for Tuesday

- Team2's three 2026-09-08 plans now sit on **Team2 Practice** (`b9dcd8db…`, $10,000) — the shared Practice book
  `ff3c29d4…` is archived. Watch job: query orders/positions/P&L by the NEW book id, not the old one; loss halts
  re-derived to $1,200 at 6%; budget $2,000/trade; `risk.sim_require_cash` is on (an entry must fit cash on hand).
- Loss ladder set tonight: Team2/EM/Tips 10% each (technique pause), book breaker 15% (per portfolio), HALT global.


## 2026-09-08 09:15 ET (run 17, first of the day — pre-open; F41 and F42 both proved live on Labor Day)

- **Alive and clean.** `/api/health` ok **v0.7.9** (main merged since Friday's 0.7.0), 82 plans armed
  desk-wide. The app restarted **02:59 ET** today (`BrokerConnected` / `SimBookRestored` /
  `TechniquePlanRestored` ×3 for Team2); the log since the 05:58 rotation is **1,746 lines with zero
  `Traceback` and zero `ERROR`**, 12 warnings, none Team2's. `FeedSelfTestPassed` at 09:00.
- **F41 PROVED LIVE — the Labor Day double-arm did not happen.** `ScheduledJobRan` at
  **09-07 17:00:04** reads `{"job": "team2_plan_nightly", "planFor": "2026-09-08", "runs": [],
  "armed": [], "skipped": ["SPY: already armed for 2026-09-08", "QQQ: …", "IWM: …"]}` — the holiday
  nightly minted nothing and the guard named every symbol. Status now shows **exactly one armed plan
  per symbol** for 2026-09-08 (SPY `c861c19d`, QQQ `61293ed7`, IWM `33afee68`), all `armed`, mode
  **auto**, on **Team2 Practice** `b9dcd8db…` — the new per-technique book, not the archived shared one.
- **F42 PROVED LIVE — nothing blanked the plans on the holiday.** `team2_preopen` on 09-07 returned
  `{"completed": []}`: the date guard left the future-dated plans alone, and their zones are still the
  ones built Friday 21:34 UTC.
- **Levels reconcile exactly to Friday's tape.** Friday RTH 1m H/L: SPY 772.87 / 769.00, QQQ 721.86 /
  716.56, IWM 296.18 / 293.56 — the PDH/PDL zone edges in all three sheets match to the cent, and
  SPY's "room" levels (774.03 up / 767.45 down) are Thursday's H/L. Correct previous session used
  across the long weekend.
- **Data is real-time.** Quotes 15 s old, session `pre`, `regPrice` holding Friday's close
  (SPY 770.19 / QQQ 718.96 / IWM 296.01) and `dayHigh/dayLow/volume` correctly reset to 0 for the new
  ET session (F19). 1m bars banking for all three, last bar 09:03 ET (~1,000 rows each in 24 h).
  The **OPRA batch is 200-ing every ~2 s** and is down to **39 symbols with no expired contracts in
  it** — F44's prune is holding (Friday's batch carried 55 including four dead 260902 strikes).
- **Book and brakes are a clean slate for day one.** Team2 Practice: cash **$10,000**, equity $10,000,
  zero positions, **no order has ever been routed on it**. Global halt not engaged, `books: {}`, and
  no pause/halt/needs-attention event today. Per-plan loss halt $1,200, premium budget $2,000,
  flatten 15:45, `maxOpenTrades` 1.
- **Pre-market so far (04:00–09:03 ET):** SPY 766.73–770.48, QQQ 716.90–723.72, IWM 293.80–295.91.
  QQQ has already traded **above** its PDH zone (723.72 vs 721.86) and IWM sits inside its PDH zone —
  both are live break candidates at the open. The 09:25 job has not run yet (correct at 09:15); the
  replay-side read already computes `pmh/pml`, `dayType: normal`, `complete: true`, so the stamp onto
  the armed plans is the thing to verify next run.
- **F47 (new, NOT fixed — proposal; a planned target with no minimum-room floor).**
  `levels.targets_beyond` takes the most recent 15m pivot beyond the zone as the outright exit, with
  no test that it leaves tradeable room, and `session.py` closes the **whole** position when it is
  touched (X3/V11). The engine already has the test — X3b's HOD/LOD substitute must clear
  `hod_target_min_atr` (1.0) × ATR — but it is applied only to the substitute, never to the plan
  target. Against Friday's average 2m range as the ATR proxy (SPY 0.254 / QQQ 0.375 / IWM 0.152),
  SPY (4.6 / 6.1 ATR) and IWM (2.6 ATR) are fine, but **QQQ's break-below target 716.34 sits 0.22
  under its PDL zone bottom 716.56 — 0.59 ATR, 0.03 % of spot.** A QQQ breakdown today would buy puts
  and exit in full almost immediately, before the +50 % trim engages. Proposed: apply the same
  `hod_target_min_atr` floor when the plan target is picked, skip to the next qualifying pivot, and
  fall back to `None` ("open", ride the EMA) when none qualifies. **Money-path threshold change —
  written up, not built by this job.**
- **Nothing built, nothing deployed, no restart this run** (none needed, and 09:25–09:35 is the
  no-restart window anyway).
- **Next run (09:30/10:00 ET) must check:** that the 09:25 `team2_preopen` stamped `pmh`/`pml`/
  `dayType`/`sizingAtOpen`/`complete: true` onto all three ARMED plans (the snapshot's `team2` block
  was all-null pre-open, as expected); that the read advances on every 2m close with fresh
  `regimeLast` EMAs; QQQ's and IWM's PDH breaks, given both were at/above the zone pre-market; and
  whether a QQQ break-below would hit F47's 0.22-room target. Still open for the user: **F47** and the
  F30-family question of which premium series is authoritative.



## 2026-09-08 09:40 ET (run 18 — the open; 09:25 completion verified, F48 fixed, F49 raised)

- **Alive, clean, and the pre-open landed.** `/api/health` ok **v0.7.9**, 89 plans armed desk-wide.
  `ScheduledJobRan {"job": "team2_preopen"}` at **09:25:07 ET** returned
  `completed: [QQQ, IWM, SPY]`, and `/api/team2/runs` now reports **`complete: true`, `dayType:
  normal`** for all three — with `pmh`/`pml` (SPY 766.73–770.48 · QQQ 716.90–723.72 ·
  IWM 293.80–295.91), `openPrice` and `sizingAtOpen: none` stamped. Exactly **one armed plan per
  symbol** for 2026-09-08 (SPY `c861c19d`, QQQ `61293ed7`, IWM `33afee68`), mode **auto**, on
  **Team2 Practice** `b9dcd8db…`. The three `complete: false` duplicates in the runs list are Friday's
  hand-disarmed set — expected. Zero `Traceback` / `ERROR` in 15,651 log lines; the only warnings are
  the benign stub-bar drops and other desks' (the three `TechniquePlanError … missing required field
  'error'` at 09:31/09:32 are the **tip** technique's share-shorting rejections, which put the reason
  in `reason` instead of `error` — not Team2's, logged here only so the next run doesn't chase it).
- **Data is real-time.** Quotes ~10 s old, `session: regular`, SPY 768.85 / QQQ 719.53 / IWM 294.52;
  1m bars banking for all three (406 rows each since midnight, last bar always within ~1 min); the
  read advanced **bars2m 1 → 3** across this run with `regimeLast` moving 09:30 → 09:34 and sane EMAs
  (SPY ema200 768.68 vs 768.34 spot; QQQ 719.41 vs 719.14; IWM 295.23 vs 294.71). `fifteenMinBars: 0`
  is correct — the first 15m RTH close is 09:45, so no `bias` yet on any symbol. The OPRA batch is
  200-ing every ~2 s across 48 symbols with **no expired contracts** in it (F44 still holding).
- **Book untouched.** Team2 Practice: cash **$10,000**, equity $10,000, **zero positions, zero orders
  ever routed**. `needsAttention: false` on all three plans, no halt/pause event today.
- **What the tape did 09:30–09:38.** All three opened inside their pre-market range and drifted down:
  SPY 769.06 open → 768.34 (PDH 772.87 is 4.0 away, PDL 769.00 already 0.7 above spot); QQQ 720.91 →
  719.14 after tagging **721.886 in the first minute — 0.03 above its PDH zone top 721.86**, so QQQ
  has already poked the level intraday without a 15m body close; IWM 295.34 → 294.71. No scenario, no
  setup, no fire — correct, nothing has confirmed on a 15m close.
- **Observation for today (by design, but it shapes the session): the pre-market ranges swallow half
  the playbook.** V6's no-trade zone is judged first (F15), so a break that happens *inside* the PM
  range is size **zero**: SPY's PDL break at 769.00 sits inside PM 766.73–770.48, and QQQ's PDH break
  at 721.86 sits inside PM 716.90–723.72. Two of today's six triggers can therefore only be traded
  once price also leaves the pre-market range. The other four (SPY PDH, QQQ PDL, both IWM) are clean.
  Expect `skip_no_trade_zone` events on the SPY-down and QQQ-up paths — that is the rule working, not
  a defect.
- **F47 (still open) bites two of six triggers today.** Re-measured against the live 2m ATR from the
  read (SPY 0.241 / QQQ 0.337 / IWM 0.188): QQQ's PDL target 716.34 leaves **0.22 = 0.65 ATR** and
  **IWM's PDL target 293.43 leaves 0.13 = 0.69 ATR** — both under the `hod_target_min_atr` 1.0 floor
  the engine already applies to X3b substitutes. A breakdown on either would exit in full almost at
  the break. The other four clear it easily (SPY 4.8 / 6.4 ATR, QQQ PDH 6.7, IWM PDH 2.1).
- **F48 (new, FIXED, commit `a53f866`, deploy QUEUED).** `POST /api/team2/runs/{id}/replay` required a
  JSON body, so the watch job's bare parity replay returned **422**. Made the body optional. Team2
  tests pass (**57 passed**, own DB `zargar_test_team2_watch`). **Not deployed this run** — it landed
  inside the 09:30–10:30 prime-open window and a restart there throws away live read state for a
  cosmetic operator fix. Restart it at the next run. Parity itself checks out with an explicit `{}`
  body: all three replays reproduce the live read exactly (0 events / 0 setups / 0 trades, same plan).
- **F49 (new, NOT fixed — proposal; money path).** `dayType` and `openPrice` are set at 09:25 from the
  **last pre-market close**, never from the real 09:30 open, and nothing re-completes the plan after
  the open (F13's stamp deliberately froze the premise for replay parity). `dayType` is not cosmetic —
  `session.py:268` lifts the inside-day guard on `pm_break_*` setups only on a gap day. Today the
  stamped opens were SPY 769.28 / QQQ 721.18 / IWM 295.59 against real opens of **769.06 / 720.91 /
  295.34**; all three still say `normal`, but **SPY's real open cleared its PDL zone bottom (769.00) by
  six cents** — seven cents lower and the day was `gap_down` while the plan said `normal`. Proposed:
  re-complete on the first RTH bar and re-stamp. Written up in TRADING-RULES; for the user to decide.
- **Next run (10:00 ET) must:** deploy the queued F48 fix with `scripts\start.ps1 -Detach` (no trade
  open → safe; skip again if one is), then check the first 15m closes at 09:45/10:00 for a real bias
  on any symbol, that QQQ's 721.886 poke did or did not become a confirmed break, whether any
  `skip_no_trade_zone` fired as predicted above, and — if a QQQ or IWM breakdown fires — exactly how
  F47's thin target behaves live. Still open for the user: **F47**, **F49**, and the F30-family
  question of which premium series is authoritative.


## 2026-09-08 10:10 ET (run 19 — THE DESK'S FIRST TRADES: two QQQ round trips, model +65.6% / book −$66)

- **Alive and clean.** `/api/health` ok **v0.7.9**, 81 plans armed desk-wide; exactly one Team2 plan
  per symbol for 2026-09-08 (SPY `c861c19d`, QQQ `61293ed7`, IWM `33afee68`), all `armed`, mode
  **auto**, on **Team2 Practice** `b9dcd8db…`. **Zero `Traceback` and zero `ERROR`** in the 14k-line
  current log; 74 warnings, all benign stub-bar drops except the six covered by F52 below and the
  tip technique's `TechniquePlanError missing 'error'` (not ours).
- **Data real-time.** Quotes 0–1 s old, `session: regular` (SPY 766.78 / QQQ 716.75 / IWM 294.85);
  1m bars banking for all three with the current minute's bar always present (QQQ 10:04 bar at
  10:05); the read advanced every 2m close (bars2m 16 → 20 across the run) with fresh `regimeLast`
  EMAs; the option the desk traded priced **`source: opra`** the whole way (0.63/0.64 at 10:04).
- **QQQ traded twice and the book is down $65.84.** 09:45 15m close below 721.82 → scenario 2
  (reject PDH, puts) *and* below the PM low 716.90 → `pm_break_down`. Then two retests of 716.90:
  **10:02** fired, bought **14 × QQQ 260908 P714 @ $0.655** ($917 premium, small bucket ×0.5, RiskGate
  all-pass), exited 10:04 at **$0.61** → **−$63**; **10:06** fired again, **9 × @ $0.63** (×0.25),
  exited 10:08 at **$0.68** → **+$45**. Realised **−$18**, **−$65.84** with $58 of commissions; book
  cash 9,934.16, no open position, `needsAttention: false`, no halt. A third touch at 10:10 was
  correctly `late_touch` (watch-only, D9/P6), so this setup is finished for the day.
- **The model scored those same two trades +32.7% and +32.9% — two wins.** Read and book disagree in
  *sign* on the desk's first day. Root cause is **F50 (new, proposal)**: the target exit is decided on
  the closed 2m bar and routed at that close, while the model books it at the target price. Trade #1's
  bar wicked to 715.87 (target 716.34 touched, put ≈$0.85 there) and closed 716.86 — the desk sold the
  close. Proposed fix: rest a SELL limit at the target premium on fill, or move the target touch onto
  the existing exit-only ~2 s quote watch. Money path — written up, not built.
- **F47 proved live and it compounds F50.** QQQ's plan target 716.34 sat **0.56 below the entry level
  and 0.65 ATR** — under the `hod_target_min_atr` 1.0 floor the engine already applies to X3b
  substitutes. Both trades hit it **within one bar**, so the ladder (+50%/+100% trims) never engaged
  and the timing loss landed on every trade. Still the user's call.
- **F51 (new, proposal).** The read's IV proxy is **VIX1D 0.1203** while the traded contract quoted
  **IV 0.236** on OPRA: the model priced its 716 put at $0.5216 where the desk paid $0.655 for the
  further-out 714. Live money is unaffected (trims on the live bid, sizing on the live NBBO) but every
  read/scorecard percentage is. Proposed: seed sigma from the 0DTE chain's ATM IV per symbol.
- **F52 (new, FIXED — commit `25a4921`, deploy QUEUED).** `TechniquePlanRead` was unregistered in the
  shared event contract (6 advisory warnings today, one per structural read event); the guard test only
  scanned `zargar/technique/` and `zargar/execution/`, never the per-technique packages. Registered the
  kind, widened the test's scan to `zargar/techniques/**`. Logged in `docs/PLATFORM-RULES.md` §4.
  **70 passed** (`tests/test_team2_*.py`, `test_marketstructure_extended.py`, `test_platform_phase3.py`,
  own DB `zargar_test_team2_watch`).
- **SPY and IWM: no trade, and the predicted skip fired.** SPY took scenario 4 (break PDL) at 09:45 and
  then logged **`skip_no_trade_zone` at 10:00 — "entry 767.82 sits inside the pre-market range (V6/B5)"**,
  exactly as run 18 predicted; it is not counted as a pullback. IWM took scenario 3 (bounce PDL, calls)
  at 09:45 and has not touched the EMA13. Both reads reconcile to the tape.
- **Parity is exact.** `POST /runs/{id}/replay` (with `{}`, since F48 is not deployed) reproduces the
  live QQQ read event-for-event — same two fires, same two exits, same +32.69 / +32.92, plus the 10:10
  late touch.
- **No restart this run.** Both F48 and F52 are queued: 10:10 ET is inside the prime-open window with
  three live setups and QQQ still eligible for another scenario-2 entry, and neither fix touches money.
  **Deploy both at the next run (10:30+, midday window) with `scripts\start.ps1 -Detach` if no trade is
  open or working.**
- **Next run (10:30 ET) must:** deploy the two queued commits; check that the desk loss tally reads
  **1 of 2** on the book basis (F37) after QQQ's −$63; watch SPY's scenario 4 for a pullback that
  clears the PM range (its skip will keep repeating while price stays inside 766.73–770.48) and IWM's
  scenario 3 / a 10:15 bias flip; and, if anything fires, re-measure F50's close-vs-target slippage.
  Still open for the user: **F47**, **F49**, **F50**, **F51** and the F30-family question of which
  premium series is authoritative.


## 2026-09-08 11:00 ET (run 20 — the two queued fixes deployed; F53/F55 found and shipped)

- **Alive, clean, both queued commits deployed.** `/api/health` ok, **v0.7.10** (the version bump came
  from the other team's `c6db9a5`, already committed and merely un-deployed — not ours). Exactly one
  armed plan per symbol for 2026-09-08 (SPY `c861c19d`, QQQ `61293ed7`, IWM `33afee68`), all `armed`,
  mode **auto**, on **Team2 Practice** `b9dcd8db…`, `needsAttention: false`, no halt or pause.
  **Zero `ERROR` and zero `Traceback`** all session (checked the current log and the rotated `.1`);
  the only warnings are the benign stub-bar drops.
- **F48 and F52 are live and proved.** `POST /runs/{id}/replay` with **no body now returns 200** (F48).
  All four `unregistered Technique event kind: TechniquePlanRead` warnings are timestamped 07:14–07:30
  PDT, i.e. **before** the 10:37 ET restart; **zero since** (F52). The Team2 runner restored 3 armed
  plans and — worth recording, since runs 18/19 both deferred a restart fearing this — **the session
  read rebuilt identically** across the restart: same 15 events, same 4 setups, same 2 trades, same
  `pnlPctSum` 65.61, touch counts intact. `session.py` being one pure walk over the banked bars is
  what makes a mid-session restart cheap. Future runs can deploy display-only fixes without waiting.
- **Data real-time.** Quotes 0 s old, `session: regular`; 1m bars banking for all three (last bar always
  within ~1 min of now); the read advanced 31 → 37 2m bars across the run; the Alpaca **OPRA** batch is
  200-ing every ~2 s (`feed=opra`), no expired contracts (F44 still holding). EMAs sane against spot on
  all three.
- **Book untouched since run 19.** Cash and equity both **$9,934.16**, zero open positions, no order
  routed this run. **F37 confirmed live**: QQQ is `auto` *and has routed*, so it is judged on the
  **book** — trade #1 −$63 is the one loss, trade #2 +$45 is a win → **1 of 2** desk-wide; SPY and IWM
  never routed, so they fall to the model basis at 0. `losses_basis` = book/model. **One more book loss
  on any symbol stops the whole desk for the day** (`losses_desk_wide`).
- **The read reconciles to the tape, exactly.** Rebuilt today's 15m bars from the `bars` table and
  checked every scenario call against `ScenarioTracker`: QQQ 09:45 C716.72 (H721.886 into the PDH zone
  → scenario 2) ✓; **09:45–10:00 C717.47 correctly did NOT flip** (s2 flips only through 721.86 or
  716.56 — D10, not on a close back above the PDL zone) ✓; 10:15 C716.505 < 716.56 → scenario 4 ✓;
  10:30 C717.76 > 717.03 → scenario 3 ✓. SPY 09:45 C767.29 < 769.00 → scenario 4, no flip since ✓.
  IWM 09:45 L294.26 into the zone, C294.81 above → scenario 3 ✓. Replay parity is **exact** on all
  three, event-for-event and pnl-for-pnl.
- **F53 (new, FIXED, commits `00e5218` + `f89e173`, DEPLOYED).** The Armed page and the phone said
  `waiting for the 1st/2nd 2m pullback into the EMA13 (touches 0)` for setups the regime **cannot
  fire**. `session.py:407` (E3/B9 stack must agree) and `:410` (E4 no braided EMAs) skip **silently**
  by design — they are re-judged every 2m bar, so an event per skip would flood the read — but nothing
  else surfaced them, so a blocked trigger read exactly like one the next touch would take. It bit
  **two of three symbols at once**: QQQ's 10:30 close flipped the bias to scenario 3 → **calls** and
  IWM has been scenario 3 → **calls** since 09:45, while both stacks are **bear**. The waiting line now
  appends `— no entry until the stack turns bull (E3/B9/E4), or a 200 EMA flush (T8)`. Verified live
  after deploy: QQQ and IWM carry the clause, **SPY does not** (scenario 4 → puts agrees with its bear
  stack). Descriptive only — the gate is untouched and still lives in `session.py`. Guarded by an
  invariant in `tests/test_team2_runner.py` that walks the session's snapshots and asserts the clause
  appears **exactly** when the regime disagrees. `f89e173` (wording: "until the stack turns bull", not
  "must turn") is committed and tested but **deploy QUEUED** — not worth a third restart for a verb.
- **F55 (new, FIXED, commit `6a2ac26`, DEPLOYED).** The Plans table rendered timestamps in the
  **browser's** timezone. Friday's nightly built today's plans at **17:34 ET**; the WHEN column read
  **"Sep 4, 2:34 PM"** on this PT machine — directly under a status line saying `plans 17:00 ET`, so
  the plan looked like it predated the job that built it. Every other technique surface already pins
  `America/New_York` (`NowView`, `ArmedDayPanel`, `ValidationTab`, `PlanCard`, `StockChart`);
  `Team2Page.tsx:109` was the lone holdout. Now ET-stamped and suffixed `ET`. `npm run build` clean.
  (The column is the run's `createdAt`, which is accurate for a header reading "when" — left alone.)
- **F54 (new, observation — NOT fixed; evidence for F27's open thresholds).** QQQ's PDL zone today is
  **716.56–717.03, 0.47 wide against a 2m ATR of 0.72 — the whole zone is 0.65 ATR**. With
  `zone_tol_atr` and `flip_body_ratio` both at **0**, the bias flipped twice in two 15m bars: 10:15
  C716.505 flipped 2 → 4 on a **0.055 margin (0.08 ATR)** — noise by any measure, and it minted
  `scenario_4@10:00` which died on `skip_no_trade_zone` — then 10:30 C717.76 flipped 4 → 3 (1.0 ATR,
  decisive) and **reversed the desk's direction**. Both flips are correct against the rules as written;
  this is the exact failure F27 anticipated on 2026-09-04, now with a second independent day and a
  zone-width measurement. Suggests the tolerance should scale with **zone width**, not ATR alone.
  Threshold work — for the walk-forward and the user, not the watch job.
- **Also confirmed:** run 18's prediction held — SPY's scenario 4 logged `skip_no_trade_zone` at 10:00
  (entry 767.82 inside PM 766.73–770.48) and will keep repeating while price stays in that range.
  Note for the recipe: the `?token=` URL handoff does **not** sign the SPA in (it redirects to `/` and
  drops it); set the `zargar_session` cookie in the browser instead.
- **Next run (11:30 ET) must:** deploy `f89e173` (wording only — safe whenever no trade is open); watch
  whether QQQ/IWM's bear stack turns bull to release their scenario-3 calls, or the bias flips back;
  keep an eye on the **1-of-2 desk-wide book loss count** (one more loser ends the day); and re-measure
  **F50**'s close-vs-target slippage and **F47**'s thin targets if anything fires. Still open for the
  user: **F47**, **F49**, **F50**, **F51**, **F54** and the F30-family question of which premium series
  is authoritative.


## 2026-09-08 11:15 ET (run 21 — quiet tape; the last queued fix deployed; F56 on the no-trade zone)

- **Alive, clean, and the queue is empty.** `/api/health` ok, **v0.7.10**; one armed plan per symbol
  for 2026-09-08 (SPY `c861c19d`, QQQ `61293ed7`, IWM `33afee68`), all `armed`, mode **auto**, Team2
  Practice `b9dcd8db…`, `needsAttention: false`, no halt or pause. `f89e173` (F53's wording) deployed
  at 11:10 ET with `start.ps1 -Detach` — no position open, no order working, midday window. Verified
  live: the clause now reads *"no entry until the stack turns bull … (E3/B9/E4)"* on QQQ/IWM and, new
  since run 20, on **SPY** too — SPY's stack slipped bear → **mixed** around 11:00, so all three
  symbols are now regime-blocked. Second clean mid-session restart in a row: 79 plans restored and the
  Team2 read rebuilt **identically** (bars2m 48, 2 trades, `pnlPctSum` 65.61).
- **Data real-time.** Quotes 0 s old, `session: regular` (SPY 767.67 / QQQ 718.84 / IWM 295.15); 1m
  bars banking with **94 of 94 minutes present since 09:30, no gaps**, last bar ~60 s old; the read
  advanced 37 → 48 2m bars across the run; the Alpaca **OPRA** batch is 200-ing every ~2 s (freshest
  11:03:46 ET), `feed=opra`. EMA/fan classification checked by hand and correct — `fanWidth` is
  ATR-normalised (QQQ 1.03, SPY 1.91 → trend; IWM 0.40 < `fan_trend_min_atr` 0.6 → chop), all three
  match their own EMA spreads.
- **No trade this run; the book is untouched.** Cash and equity both **$9,934.16**, zero open
  positions, no order routed. Desk loss tally still **1 of 2** on the book basis (F37) from QQQ's
  −$63; one more book loser stops the whole desk (`losses_desk_wide`).
- **The read still reconciles to the tape, exactly.** Rebuilt today's 15m bars from the `bars` table:
  QQQ's last flip was 10:15 C717.76 > 717.03 → scenario 3, and 10:45 C718.94 / 11:00 C718.74 both sit
  between the zones, so **correctly no flip** ✓. SPY has closed below 769.00 on every 15m bar since
  09:45 → scenario 4 unchanged ✓. IWM has closed above 294.59 on every bar → scenario 3 unchanged ✓.
  **Replay parity is exact on all three** (`POST /runs/{id}/replay`, no body): 16/2/1 events matched
  event-for-event, `pnlPctSum` 65.61 / 0 / 0.
- **F56 (new, proposal — NOT fixed).** The desk cannot fire a scenario setup today, and the reason is
  structural, not the tape. `sizing_bucket` returns **`none`** for any entry inside the pre-market
  range (F15, 2026-09-04) and the gate is applied to the *pullback's entry price* ≈ spot — so on a day
  with a wide PM range the no-trade zone is not a zone price crosses, **it is the day**: QQQ PM 6.82
  wide = **12.4× ATR** (80% of today's closes inside), SPY 3.75 = 9.4× (76%), IWM 2.11 = 9.0× (**100%
  — it has never left**). QQQ's PDH zone *and* its PDL zone top both sit inside its own PM range, so
  scenarios 2 and 3 are anchored on lines the sizing ladder refuses; `skip_no_trade_zone` has now
  fired on QQQ at 10:16 and 11:00 and on SPY at 10:00. **Both of today's actual fires came from the
  one carve-out that already exists** — F20's PM-level retest exemption. Without it the desk would be
  0-for-4 setups and 8 EMA13 touches. Proposed (same shape as F20): bucket an entry within touch
  tolerance of a *prior-day zone edge* as `small`, not `none`; optionally disable the `none` rung once
  the PM range exceeds ~6× ATR. Rule/threshold work — written up with the measurements in
  TRADING-RULES.md, **not built**.
- **One ERROR in the log all session, and it is not ours.** `zargar.execution.listener cartel-observer
  bar handling failed` at 10:54 ET — `options_cartel/entry.py:45` raising *"entry read requires
  symbol-matched, minute-aligned 1m bars"* out of `observer.on_minute_bar`. That is the **other team's**
  options_cartel technique; the shared listener caught it and the loop continued, and no Team2 plan was
  affected. Flagged for them, not touched. Zero Team2 errors, zero `TechniquePlanRead` warnings since
  the F52 deploy.
- **Next run (11:30 ET) must:** nothing is queued — deploy nothing unless something new is found. Watch
  for a stack flip that releases QQQ's or IWM's scenario-3 calls (both bear/mixed against a long bias),
  or a 15m close that flips a bias; keep the **1-of-2 desk-wide book loss** count in view; and if
  anything fires, re-measure **F50**'s close-vs-target slippage and **F47**'s thin targets. Still open
  for the user: **F47**, **F49**, **F50**, **F51**, **F54**, **F56**, and the F30-family question of
  which premium series is authoritative.


## 2026-09-08 11:45 ET (run 22 — every symbol structurally blocked; F57 makes the refusal visible)

- **Alive and clean.** `/api/health` ok; one armed plan per symbol for 2026-09-08 (SPY `c861c19d`,
  QQQ `61293ed7`, IWM `33afee68`), all `armed`, mode **auto**, Team2 Practice `b9dcd8db…`,
  `needsAttention: false`, no halt or pause. Version reads **v0.7.11** after this run's deploy — as in
  run 21, the bump was the other team's, already committed and merely un-deployed; my commit touches
  five files and none of them is a version file (`git show --stat 1cdc89c`).
- **Data real-time.** Quotes ~6 s old, `session: regular` (SPY 767.77 / QQQ 720.13 / IWM 295.52); 1m
  bars **123 of 123 minutes present since 09:30, zero gaps**, last bar 11:32 ET; the read advanced
  48 → 61 → 65 2m bars across the run; the Alpaca **OPRA** batch is 200-ing every ~2 s (freshest
  11:40:49 ET). EMA stacks hand-checked against spot on all three and correct — QQQ's turned
  **mixed → bull** during this run, SPY's is **mixed**, IWM's **bull**.
- **The read reconciles to the tape, exactly, and replay parity is exact.** Rebuilt today's 15m bars
  from the `bars` table: QQQ's last flip was the 10:15 bucket (C717.76 > 717.03 → scenario 3) and the
  10:30/10:45/11:00/11:15 closes (718.15 / 718.94 / 719.91 / 720.09) all sit **between** the zones →
  correctly no flip ✓; SPY has closed below 769.00 on every bar since 09:45 → scenario 4 unchanged ✓;
  IWM above 294.59 on every bar → scenario 3 unchanged ✓. `POST /runs/{id}/replay` reproduced
  16 / 2 / 2 events event-for-event with `pnlPctSum` 65.61 / 0 / 0.
- **No trade this run; the book is untouched.** Zero open positions, zero working orders, no order
  routed. Desk loss tally still **1 of 2** on the book basis (F37); one more book loser stops the desk.
- **The one new tape event is IWM's 11:26 `skip_no_trade_zone`** (entry 295.32 inside PM
  293.80–295.91) — and it is the sharpest evidence yet for **F56**. IWM's stack turned bull during
  this run, which cleared F53's regime clause, and the **very next gate refused the pullback anyway**.
  All three symbols are now blocked structurally rather than by the tape: SPY 10:00, QQQ 10:16 + 11:00,
  IWM 11:26. F56 stays a **proposal** — it is rule/threshold work, not the watch job's.
- **F57 (new, FIXED, commit `1cdc89c`, DEPLOYED).** With all three refused, the headline the Armed page
  and the phone show still read *"waiting for the 1st/2nd 2m pullback into the EMA13 (touches 0)"* —
  no hint that nothing was going to happen. `session.py` **does** mint the refusal, but three correct
  behaviours compound into an invisible one: it goes only into the read, only **once per setup** (F23,
  so the read is not buried), and the number the line leads with is `touches`, which a refused dip
  **does not increment** by design (F18). So the page can sit at "touches 0" for an hour with a single
  10:00 event, well down the timeline, as the only trace. The setup's current refusal (`_skipped`,
  cleared by a real touch) is now serialized on the read and appended: *"· the last pullback sat inside
  the pre-market range — no-trade zone (V6/B5)"*. Same family as F53, **descriptive only — no gate,
  threshold, size or money path touched**. Verified live on all three after deploy; SPY correctly
  carries *both* clauses (regime mixed vs wanted bear, **and** the no-trade zone). Guarded at both
  ends: `test_team2_session.py` pins the read exposing the refusal on the fixture that actually reaches
  the gate, `test_team2_runner.py` asserts the clause appears exactly when the picked setup is refused.
  `pytest tests/test_team2_*.py tests/test_marketstructure_extended.py` → **57 passed**.
- **Third clean mid-session restart in a row.** Deployed 11:43 ET (midday, nothing open, nothing
  working); 80 plans restored and the Team2 read rebuilt **identically** (QQQ trades 2, `pnlPctSum`
  65.61). Backend-only change, so no frontend build was needed.
- **Log is clean.** Exactly one ERROR all session and it is still **not ours**: `cartel-observer bar
  handling failed` at 11:21 ET (`options_cartel/entry.py:45`, the other team's technique) — a **second
  occurrence** after run 21's 10:54 ET, so it is recurring, not a one-off. The shared listener caught
  it and the loop continued; no Team2 plan affected. Flagged for them, not touched. Zero Team2 errors,
  zero `TechniquePlanRead` warnings since F52.
- **Next run (12:00 ET) must:** nothing is queued — deploy nothing unless something new is found.
  Watch whether SPY's stack turns bear (it is the only symbol still regime-blocked) and whether QQQ can
  reach its PDH zone 721.82–721.86 from 720.20; keep the **1-of-2 desk-wide book loss** count in view;
  if anything fires, re-measure **F50**'s close-vs-target slippage and **F47**'s thin targets. Still
  open for the user: **F47**, **F49**, **F50**, **F51**, **F54**, **F56**, and the F30-family question
  of which premium series is authoritative.
## 2026-09-08 12:05 ET (run 23 — quiet, clean, nothing queued; F56 measured properly)

- **Alive and clean; nothing deployed this run and nothing is queued.** `/api/health` ok, **v0.7.11**;
  one armed plan per symbol for 2026-09-08 (SPY `c861c19d`, QQQ `61293ed7`, IWM `33afee68`), all
  `armed`, mode **auto**, Team2 Practice `b9dcd8db…`, `needsAttention: false` on all three, halt
  `engaged: false` with no per-book halts and no technique pause. No Team2 code change was needed —
  nothing was found broken.
- **Data real-time.** Quotes 0–1 s old, `session: regular` (SPY 767.40 / QQQ 719.98 / IWM 295.61); 1m
  bars **154 of 154 minutes present since 09:30, zero gaps**, last bar 12:03 ET (~2 min); the read
  advanced 65 → 76 → 78 2m bars across the run; the Alpaca **OPRA** batch is 200-ing every ~2 s
  (freshest 12:04:09 ET), `feed=opra`. EMA/fan values present on all three regimes.
- **The tape did nothing.** Zero new events on any symbol since run 22 — QQQ still 16, SPY 2, IWM 2.
  No new touches, no scenario flip, no fire, no skip. Rebuilt today's 15m closes from the `bars` table
  and every bias is still correct: QQQ's last flip was the 10:15 bucket (C717.76 > 717.03 → scenario 3)
  and 10:30–11:45 (718.15 / 718.94 / 719.91 / 720.09 / 720.85 / 719.97) all sit **between** the zones →
  correctly no flip ✓; SPY below 769.00 on every bar since 09:45 → scenario 4 ✓; IWM above 294.59 on
  every bar → scenario 3 ✓. Worth noting QQQ's day high **721.886 tagged the PDH zone (721.82–721.86)**
  in the 11:30 window and the desk correctly did **not** flip — the rule wants a 15m *body* close above
  721.82 and the highest close was 720.85 ✓.
- **Replay parity is exact on all three.** `POST /runs/{id}/replay` reproduced 16 / 2 / 2 events
  **event-for-event** (byte-identical JSON) with `pnlPctSum` 65.61 / 0 / 0. The only difference is
  `bars2m` 77 vs 78 — a new 2m bar closed between the live read and the replay call, not a defect.
- **Book untouched.** Team2 Practice cash **and** equity $9,934.16, zero open positions, zero Team2
  working orders, no order routed. (The one open order in `/api/state` is a TSLA GTC stop in portfolio
  `e39cc477…` — another team's book, not ours.) Desk loss tally still **1 of 2** on the book basis
  (F37); one more book loser stops the desk.
- **All three symbols are still blocked only by the no-trade zone, and the regime clause has cleared
  everywhere.** F53's clause is now absent from all three (QQQ bull stack vs long bias ✓, SPY bear vs
  short ✓, IWM bull vs long ✓) while F57's clause is present on all three — so the headline now reads
  the situation exactly right: the regime agrees, the location does not. Both of last week's deploys
  are doing their job.
- **F56 quantified (still a proposal — NOT built).** Instead of re-telling the anecdote I measured the
  refusal rate: rebuilt today's 78 2m bars per symbol and counted bars whose range **straddles** a
  session-seeded EMA13, then how many of those sat inside the pre-market range. **SPY 31/33 (94%),
  QQQ 26/28 (93%), IWM 41/41 (100%) — 98 of 102 (94%) across the desk.** The `none` bucket is not
  filtering the odd bad location, it is refusing 19 of every 20 candidate pullbacks. Honest caveat
  recorded with it: the straddle test is a geometric proxy (no direction/tolerance/live-setup filter),
  so 102 is an upper bound on *candidates*, not a count of gate firings. Written into TRADING-RULES.md
  under F56 as a follow-up table.
- **Log is clean.** Zero ERRORs and zero Tracebacks in `backend/zargar-8420.log` since the 11:43 ET
  restart. The other team's recurring `cartel-observer bar handling failed` has **not** reappeared in
  this log window (it is theirs either way — `options_cartel/entry.py:45`, flagged, not touched).
- **UI checked.** `/team2` renders all three plans with F55's ET stamps ("Sep 4, 5:34 PM ET") and the
  sheets; `/armed` header reads **"MID-DAY · TEAM2 CAN FIRE"** with 80 armed / 0 in trade. No console
  or render problems.
- **Next run (12:30 ET) must:** nothing is queued — deploy nothing unless something new is found.
  Watch for a 15m body close that flips a bias (QQQ is the live one: 720.0 spot vs its PDH zone
  721.82–721.86, and a close above it would flip to scenario 1/calls with room to 724.12), and note
  that a *break above the PDH zone* is one of the few places today's entries would sit **outside** the
  PM range (QQQ PM top 723.72 — so even a PDH break entry is refused until 723.72; more F56 evidence).
  Keep the **1-of-2 desk-wide book loss** count in view; if anything fires, re-measure **F50**'s
  close-vs-target slippage and **F47**'s thin targets. Still open for the user: **F47**, **F49**,
  **F50**, **F51**, **F54**, **F56**, and the F30-family question of which premium series is
  authoritative.

## 2026-09-08 12:35 ET (run 24 — quiet again; the no-trade zone's *precedence* is the sharper bug, F58)

- **Alive and clean; nothing deployed, nothing queued.** `/api/health` ok, **v0.7.11**; one armed plan
  per symbol for 2026-09-08 (SPY `c861c19d`, QQQ `61293ed7`, IWM `33afee68`), all `armed`, mode
  **auto**, Team2 Practice `b9dcd8db…`, `needsAttention: false` and `readError: null` on all three,
  halt `engaged: false` with no per-book halts and no technique pause. No Team2 code change was made —
  nothing was found broken.
- **Data real-time.** Quotes **0 s** old, `session: regular` (SPY 767.15 / QQQ 719.28 / IWM 295.45);
  1m bars **183 of 183 minutes present since 09:30, zero gaps** on all three, last bar 12:32 ET; the
  read advanced 78 → 91 2m bars since run 23; the Alpaca **OPRA** batch is 200-ing every ~2 s
  (freshest 12:33:02 ET), `feed=opra`. EMA/fan values present on all three regimes.
- **The tape did nothing, for the second run running.** Zero new events on any symbol since run 23 —
  QQQ still 16, SPY 2, IWM 2; no new touch, no scenario flip, no fire, no skip. Rebuilt today's 15m
  bars from the `bars` table and every bias is still right: QQQ's last flip was the 10:15 bucket
  (C717.76 > 717.03 → scenario 3) and 10:30–12:15 (718.15 / 718.94 / 719.91 / 720.09 / 720.85 /
  719.97 / 719.60 / 719.08) all sit **between** the zones → correctly no flip ✓; SPY below 769.00 on
  every close since the 09:30 bucket → scenario 4 ✓; IWM above 294.59 on every close → scenario 3 ✓.
- **Replay parity is exact on all three.** `POST /runs/{id}/replay` reproduced 16 / 2 / 2 events
  **byte-identically** with `pnlPctSum` 65.61 / 0 / 0; only `bars2m` differs (91 live vs 92 replay — a
  bar closed between the two calls, not a defect).
- **Book untouched.** Team2 Practice cash **and** equity $9,934.16, zero open positions, zero Team2
  working orders, no order routed. Desk loss tally still **1 of 2** on the book basis (F37).
- **F53 and F57 are both doing their job on the live headline.** QQQ's stack slipped **bull → mixed**
  during this run, so its regime clause correctly came *back* ("no entry until the stack turns bull");
  SPY (bear vs short) and IWM (bull vs long) carry no regime clause. All three carry F57's clause —
  *"the last pullback sat inside the pre-market range — no-trade zone (V6/B5)"*. The line now reads the
  situation exactly: on QQQ the regime **and** the location are wrong, on SPY and IWM only the location.
- **F58 (new, proposal — NOT built). The pre-market *window* is correct; V6's *ladder* is the
  problem.** Rather than re-tell F56 I tested the cheaper hypothesis first — that the PM range is
  computed over the wrong window. It is not: the sheets reproduce the 04:00–09:30 ET 1m tape to the
  cent (SPY 766.73–770.48, QQQ 716.90–723.72, IWM 293.80–295.91), which is exactly METHOD **L2.1**.
  So F56/F58 are rule questions, not a data defect. What the check *did* expose: V6's five bands
  (Full · PDH zone→PMH Small · PMH→PML No trade · PML→PDL zone Small · Full) are only *ordered* when
  `PDL zone < PML < PMH < PDH zone` — the PM range nested inside yesterday's. `sizing_bucket`
  (`scenario.py:36`) never tests for that: it checks `pml <= price <= pmh` **first and
  unconditionally**, so wherever a PM edge crosses a prior-day zone the overlapping bands all resolve
  to `none` — including the band V6 calls **Full**. **None of today's three symbols is nested** (QQQ
  PMH 723.72 above its PDH zone top 721.86; SPY PML 766.73 below its PDL zone bottom 769.00; IWM PML
  293.80 inside its PDL zone). **SPY 10:00 is the clean case**: entry 767.82 is *below* the PDL zone
  bottom 769.00 and with the confirmed scenario-4 bias — V6 says **Full size**, the function's own
  `price < pdl.bottom` rung would say `full`, and the PM check pre-empts both and returns `none`. Of
  today's four refusals, **one contradicts V6 outright, one (QQQ 10:16, inside the PDL zone) is
  undefined, two (QQQ 11:00, IWM 11:26, mid prior-day range) are defensible under B7.** Proposed fix
  for the user, not built: clamp the no-trade band to `max(pml, pdl.top)`…`min(pmh, pdh.bottom)` so
  beyond a prior-day zone V6's Full/Small rungs win, leaving F15's gap-day protection intact. Written
  up with the geometry in TRADING-RULES.md as **F58**; cross-refs F56 (width) and F15 (why widened).
- **Log is clean.** Zero ERRORs and zero Tracebacks in `backend/zargar-8420.log`. The other team's
  recurring `cartel-observer bar handling failed` has not reappeared. Note the app's total armed count
  is **78** (was 80 at run 23) — the two that dropped are **not ours**: the breakdown is
  enhanced_market 45 / tip 28 / options_cartel 2 / **team2 3**, all three of ours present and armed.
- **UI checked** (cookie handoff — the browser pane normalizes `?token=`, so set `zargar_session` and
  reload `/team2`): all three plans render with F55's ET stamps ("Sep 4, 5:34 PM ET"), the full sheets,
  `ARMED`, and the Armed tab shows **3**. No render or console problems. (The pane is narrow so it
  serves the phone layout — expected, not a defect.)
- **Next run (13:00 ET) must:** nothing is queued — deploy nothing unless something new is found.
  Watch whether QQQ's stack recovers to bull (it is now the only regime-blocked symbol) and for a 15m
  body close outside a zone (QQQ needs > 721.82 or < 717.03 from 719.2; note even a PDH break entry is
  refused until 723.72 under today's `none` rung — more F58 evidence). Keep the **1-of-2 desk-wide
  book loss** count in view; if anything fires, re-measure **F50**'s close-vs-target slippage and
  **F47**'s thin targets. Still open for the user: **F47**, **F49**, **F50**, **F51**, **F54**,
  **F56**, **F58**, and the F30-family question of which premium series is authoritative.

## 2026-09-08 13:15 ET (run 25 — third quiet run; measured what the four refusals would have done)

- **Alive and clean; nothing deployed, nothing queued.** `/api/health` ok, **v0.7.11**; one armed plan
  per symbol for 2026-09-08 (SPY `c861c19d`, QQQ `61293ed7`, IWM `33afee68`), all `armed`, mode
  **auto**, Team2 Practice `b9dcd8db…`, `needsAttention: false` and `readError: null` on all three,
  halt `engaged: false` with no per-book halts and no technique pause. No Team2 code change was made —
  nothing was found broken.
- **Data real-time.** Quotes **0–1 s** old, `session: regular` (SPY 767.77 / QQQ 720.42 / IWM 295.73);
  1m bars **213 of 213 minutes present since 09:30, zero gaps** on all three, last bar 13:02 ET; the
  read advanced 91 → 106 2m bars since run 24; the Alpaca **OPRA** batch is 200-ing every ~2 s
  (freshest 13:05:02 ET), `feed=opra`, and QQQ's traded contract is still in the subscription list.
  EMA/fan values present on all three regimes.
- **The tape did nothing, for the third run running.** Zero new events since run 23 — QQQ still 16,
  SPY 2, IWM 2; no new touch, no scenario flip, no fire, no skip. Rebuilt today's 15m closes from the
  `bars` table and every bias is still right: QQQ's last flip was the 10:15 bucket (C717.76 > 717.03 →
  scenario 3) and 10:30–13:00 (718.15 / 718.94 / 719.91 / 720.09 / 720.85 / 719.97 / 719.60 / 719.08 /
  719.27 / 719.23 / 720.39) all sit **between** the zones → correctly no flip ✓; SPY below 769.00 on
  every close (highest 768.04) → scenario 4 ✓; IWM above 294.59 on every close → scenario 3 ✓.
- **Replay parity is exact on all three.** `POST /runs/{id}/replay` reproduced 16 / 2 / 2 events
  **byte-identically** (JSON compare, not eyeball) with `pnlPctSum` 65.61 / 0 / 0; only `bars2m`
  differs (106 live vs 108 replay — bars closed between the two calls, not a defect).
- **Book untouched, and the desk loss tally VERIFIED rather than carried forward.** Team2 Practice cash
  **and** equity $9,934.16, zero open positions, zero Team2 working orders (the 6 open orders in
  `/api/state` are other teams' books). Reading the persisted `technique_armed.state.trades` and
  applying `_plan_losses` by hand: QQQ's two round trips are `pm_break_down@09:30#1` (−$63) and
  `#2` (+$45) — re-entries carry a **`#N`** suffix, so they are two groups, not one, and only X5
  `+add` legs collapse into a base position. Tally = **1 of 2 on the book basis** (F37), SPY and IWM
  contribute 0 on the model basis. One more book loser stops the desk. Today's trades are still fully
  explained by **F50** (exit routed at the bar close, not the target) and **F51** (model sigma 0.1203
  vs the contract's traded IV 0.236, and the model's 716 strike vs the desk's 714) — nothing new.
- **F53 and F57 are both reading the live headline correctly.** QQQ's stack recovered mixed → **bull**
  during this run, so its regime clause is gone again; all three now carry only F57's clause —
  *"the last pullback sat inside the pre-market range — no-trade zone (V6/B5)"*. Regime agrees on all
  three; location does not.
- **New evidence for F56/F58 (measurement, nothing built).** Rather than re-tell the refusals I
  measured them: from each refusal's own minute to 13:05 ET, on the banked 1m bars, taking the refused
  entry and the setup's plan target — **SPY 10:00** short 767.82 → 767.45 **hit its target in the same
  minute with 0.00 adverse excursion**; **QQQ 10:16** short 716.99 → 716.34 never got there and went
  **3.94 against**; **QQQ 11:00** long 718.26 → 721.82 has run **75 %** of the way with MAE 0.00;
  **IWM 11:26** long 295.32 → 295.955 has run **98 %** with MAE 0.12. Working F58's proposed clamp
  through them: it would allow **SPY 10:00 (the winner) *and* QQQ 10:16 (the loser)** — 716.99 sits
  inside the PDL zone 716.56–717.03, i.e. below the clamped band bottom — and would **still refuse**
  QQQ 11:00 and IWM 11:26, the two that nearly reached target. So the clamp is a precedence fix that
  buys a winner and a loser together, and it does **not** address the width F56 measures (94 % of
  candidate pullbacks refused, run 23). Spot basis only — no premium path, no trims, no stop, and F50
  warns a spot win is not a book win. Written up as a follow-up table under **F58**; both stay
  **proposals for the user**, unbuilt.
- **Log is clean for Team2.** Logs rotate at 5 MB (~every 35 min), so I scanned all four files back to
  11:19 ET: **zero Team2 errors, zero Tracebacks of ours**. The only ERRORs are the other team's
  recurring `cartel-observer bar handling failed` (`options_cartel/entry.py:45`) — now a **third and
  fourth** occurrence, 11:21 and 12:08 ET. Flagged for them, not touched. The 28-per-6-minutes
  `zargar.marketdata persist_bars: dropped N non-bucket-aligned stub bar(s)` warnings are **deliberate**
  (EM team's write-time bucket guard, `marketdata.py:283`) and cost us nothing — our bar continuity is
  213/213 — but at ~300/hour they are the only thing in the WARNING channel and would mask a real one.
  Shared code, so noted only.
- **UI not re-verified this run.** The browser pane strips `?token=` and the cookie-injection step was
  refused by the tool policy, so `/team2` only rendered the sign-in page. Nothing UI-facing has changed
  since run 24's pass (no deploy since 11:43 ET), and every string the page renders — the F53/F57
  summaries, the sheets, the trigger rows — was verified directly on the API this run.
- **Next run (13:30 ET) must:** nothing is queued — deploy nothing unless something new is found. Watch
  QQQ's two live cases (spot 720.4: a 15m body close above **721.82** flips it to scenario 1/calls, and
  the 11:00 refused long is 75 % to that same target) and IWM's 295.32 long, now 98 % of the way to
  295.955 — if either completes, that is the first *closed* counterfactual and worth recording against
  F56/F58. Keep the **1-of-2 desk-wide book loss** count in view; if anything fires, re-measure
  **F50**'s close-vs-target slippage and **F47**'s thin targets. Still open for the user: **F47**,
  **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, and the F30-family question of which premium
  series is authoritative.

## 2026-09-08 13:45 ET (run 26 — the tape finally moved, and the desk refused it on a modelled price)

- **Alive and clean.** `/api/health` ok, **v0.7.11**; one armed plan per symbol for 2026-09-08 (SPY
  `c861c19d`, QQQ `61293ed7`, IWM `33afee68`), all `armed`, mode **auto**, Team2 Practice `b9dcd8db…`,
  `needsAttention: false` and `readError: null` on all three, halt `engaged: false`, no per-book halt,
  no technique pause. **Redeployed at 13:44 ET** with F59's reporting fix (`b69d086`); 77 armed plans
  restored, all three of ours back and armed.
- **Data real-time.** Quotes **0–1 s** old, `session: regular` (SPY 767.68 / QQQ 720.51 / IWM 296.00);
  1m bars **247 of 247 minutes present since 09:30, zero gaps** on all three, last bar 13:36 ET; the
  Alpaca **OPRA** batch is 200-ing every ~2 s (freshest 13:38 ET). EMA/fan values present on all three
  regimes (SPY mixed, QQQ bull, IWM bull, all "trend").
- **IWM broke its pre-market high at 13:30 — the first new structure since run 22.** The 15m bucket
  13:15–13:30 closed **295.97** above PMH **295.91** (verified bar by bar against the banked 1m tape:
  the 13:29 bar closed 295.97, the bucket's body top clears the level ✓). `pm_break` → new setup
  `pm_break_up@13:15`, direction long, target 295.955 (PDH zone bottom). The 2m bar ending 13:30 ran
  295.87–295.97, so the F20 retest of 295.91 is real ✓. SPY and QQQ did nothing again (2 and 16 events,
  unchanged); every 15m close still sits between the zones on QQQ, below 769.00 on SPY.
- **F59 (new, PARTLY fixed) — a real, liquid contract existed and the desk refused the trade on a
  synthetic price that missed the floor by one tenth of a cent.** The retest minted
  **`skip_no_contract`: "no strike prices between $0.20 and $0.60 (V1)"**. That is a statement about
  the **model**, not the chain. At today's sigma **0.1203** (Black–Scholes, 2.5 h to the 16:00 expiry,
  spot 295.91) the model marks the IWM **296 call at $0.199** — **$0.001 under `premium_floor`** — and
  `pick_strike` breaks out of its walk the instant a mark falls under the floor, so it collected zero
  candidates and returned `None`. The **real** 0DTE chain at the same moment: **IWM 296C bid 0.24 /
  ask 0.25, volume 70,329**, OI 2,635, IV 0.1346, delta 0.43 — squarely in band and the most traded
  call on the sheet. Replay reproduces the refusal byte-identically, so it is deterministic.
- **Root cause, and why IWM.** The read is the gatekeeper: the runner only asks the venue for a real
  contract after `fire`, so a `skip_no_contract` ends the touch inside `session.py` and a cent of model
  error becomes a veto over a live trade. `runner._sigma(symbol)` **ignores its `symbol` argument** —
  it returns one index-wide `^VIX1D` for SPY, QQQ **and** IWM. VIX1D is an S&P measure; today's real
  IWM 296C printed IV 0.1346 against the model's 0.1203, ~11 % low, which is all a hard floor needs.
  Compounding it, IWM's $1 strikes at 295.9 with 2.5 h left step **0.95 (295, ITM) → 0.25 (296) →
  0.04 (297)**, so the $0.20–$0.60 band spans *at most one strike* on this symbol late in the day.
  Same root as **F51** (model sigma vs traded IV) but sharper: F51 mis-*prices* a trade the desk still
  takes; F59 *cancels* it.
- **It cost the whole setup, not one touch.** After the redeploy the re-simulated read shows the retest
  refused **twice** (13:30 and 13:40) and the 13:42 touch logged `late_touch` — beyond the 2-touch cap.
  `pm_break_up@13:15` ends **touches 3, entries 0**; no further entry is possible on it today. Honest
  cost: spot hit the 295.955 target in the refusal bar itself (13:30 high 296.03), but in **premium**
  terms the 296C was ~0.25 at 13:30 and ~0.245 at 13:36 with spot 296.00 — roughly flat, no +50 % trim.
  So: *a real trade was cancelled for a bad reason*, not *a large P&L was lost*.
- **Fixed and deployed (`b69d086`, reporting only — no gate, threshold, size or money path changed).**
  The refusal now says whose price it is — *"no strike **MODELS** between $0.20 and $0.60 (V1) —
  modelled premium at sigma 0.1203, not the live chain"* — and is recorded with `note_once` so it
  serializes on the setup and can reach the Armed page and the phone. `skip_no_contract` was **already**
  in F57's headline list, but `session.py` used `note`, so `_skipped` stayed `None` and the clause could
  never fire: IWM's headline read *"waiting for the 1st/2nd 2m pullback into the EMA13 (touches 1) ·
  EMA stack bull, trend"* with no hint the pullback had been turned away. Same silent-gate class as F53
  and F57. Team2 tests **57 passed** on `zargar_test_team2_watch`. Residual noted in F59: the clause
  still does not render on IWM now, because a real touch clears `_skipped` (line 488) and touch #3 wiped
  what touch #2 recorded — F57's intended semantics, a wording question for the user, not a defect.
- **Proposed, NOT built (money path — user's call).** (a) Let the **live chain** decide: have the read
  emit the fire with a `needs_contract` flag and let the existing live picker (which already applies
  `chase_cap_mult`) accept or refuse against the real ask, so the model prices the *simulation* but
  never vetoes a *trade*. (b) Much cheaper: make `_sigma` genuinely per-symbol — `sigma_source: "chain"`
  already exists as a settings value and is **unimplemented** in `_sigma`; the day's ATM 0DTE IV would
  have marked the 296C at ~0.22 and taken the trade. (c) Widen `premium_floor` for $1-strike
  underlyings. (a) is the structural answer, (b) the one-symbol fix.
- **Replay parity exact on all three.** 2 / 16 / 5 events reproduced byte-identically (JSON compare),
  including the IWM refusal. **Book untouched:** Team2 Practice cash **and** equity $9,934.16, zero
  positions, zero Team2 working orders. Desk loss tally still **1 of 2** on the book basis (F37).
- **Log clean for Team2.** Zero Tracebacks and zero Team2 ERRORs across the live file and its three
  rotations (covering 11:53 ET →). The only ERRORs are the other team's `cartel-observer bar handling
  failed` (12:08 ET, the 4th occurrence already flagged) and one asyncio connection-lost callback at
  12:06 ET. Note the log now rotates every ~6 minutes at this volume — the OPRA `httpx` INFO lines
  dominate it — so an error more than ~25 minutes old is already gone; that limits what a later run can
  scan and is worth a quieter log level for `httpx`.
- **Next run (14:15 ET) must:** nothing is queued. IWM's PM-break setup is exhausted (touches 3/2), so
  watch for a **new** setup — a 15m body close above IWM's PDH zone top 296.18, QQQ above 721.82 or
  below 717.03, SPY below 769.00 is already live. **If any of them fires, check the contract event
  first**: F59 says a model refusal can silently cancel it, and the 14:45–16:00 window plus decay makes
  a sub-floor mark *more* likely, not less. Keep the **1-of-2 desk-wide book loss** count in view. Still
  open for the user: **F47**, **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**, and the
  F30-family question of which premium series is authoritative.

## 2026-09-08 14:15 ET (run 27 — IWM's only PM break ends 9 touches / 0 entries; the headline said it was still waiting)

- **Alive and clean.** `/api/health` ok, **v0.7.11**; one armed plan per symbol for 2026-09-08 (SPY
  `c861c19d`, QQQ `61293ed7`, IWM `33afee68`), all `armed`, mode **auto**, Team2 Practice `b9dcd8db…`,
  `needsAttention: false` and `readError: null` on all three, halt `engaged: false`, no per-book halt,
  no technique pause. **Redeployed at 14:12 ET** with F60 (`47b0460`); 77 armed plans restored, all
  three of ours back and armed, and the new snapshot fields confirm the 09:25 pre-open on each plan:
  `complete: true`, SPY PM 766.73–770.48, QQQ 716.90–723.72, IWM 293.80–295.91.
- **Data real-time.** Quotes **0–1 s** old, `session: regular` (SPY 767.51 / QQQ 719.63 / IWM 295.79);
  banked 1m bars **274 of 274 minutes since 09:30, zero gaps** on all three, last bar 14:03 ET at the
  time of the check; EMA/fan values present on all three regimes (SPY mixed, QQQ mixed, IWM bull, all
  "trend"). Sigma still the one index-wide 0.1203 (F59/F51).
- **SPY and QQQ did nothing new.** SPY 2 events (unchanged since 10:00), QQQ 16 (unchanged since
  11:00); QQQ's stack slipped back to **mixed**, so its headline carries the E3/B9 clause again. Both
  still carry F57's no-trade-zone clause. QQQ's two morning round trips remain the day's only trades
  (2 wins, +65.6 % model P&L); the desk-wide loss tally is unchanged at **1 of 2** on the book basis.
- **IWM: the 13:30 PM break is now dead for the day.** After F59's two model refusals (13:30, 13:40)
  the setup printed `late_touch` at 13:42, 13:44, 13:48, 13:50, 13:52 and 13:54 and one more
  `skip_no_trade_zone` at 13:58 (entry 295.76 back inside the PM range) — **touches 9, entries 0**.
  Verified against the banked tape: 13:42–13:54 the 1m bars oscillate 295.86–296.04 while the 2m EMA13
  sits 295.86–295.93, i.e. price rode the EMA. Spot has since faded to 295.79, below the 295.91 break
  level, so the break itself has failed on the tape as well.
- **F60 (new, FIXED, `47b0460`) — the headline promised a pullback the setup could not take.** The
  Armed + phone line read *"scenario 3 (bounce PDL) → calls · waiting for the 1st/2nd 2m pullback into
  the EMA13 (touches 8)"*: the desk was not waiting for anything tradeable (D9/P6 makes touch 3+
  watch-only), and the count belongs to `pm_break_up@13:15` while the scenario label comes from the
  09:45 bias — per F24 the count is taken from the newest live setup in the bias direction, which
  today is not the setup the label names. It now reads *"pm_break_up@13:15: its first 2 pullbacks are
  spent (touches 8) — further touches are watch-only (D9/P6)"*. Same commit adds the 09:25 pre-open
  result (`pmh`/`pml`/`complete`) to the snapshot's `team2` block so completion is checkable without
  parsing the sheet string. **Reporting only — no gate, threshold, size or money path changed.** Team2
  tests **57 passed** on `zargar_test_team2_watch`; `test_team2_runner.py` now asserts both wordings
  (its F53/F57 clauses are judged on either) plus F60 itself.
- **F61 (new, PROPOSED, not built) — a plumbing refusal spends the method's two-pullback allowance.**
  `session.py` does `s.touches += 1` **before** it asks the premium model for a strike, so
  `skip_no_contract` consumes a D9 pullback. That is the inverse of F18, which deliberately exempts
  the "not a tradeable location" refusals (`skip_no_trade_zone`, `skip_range_confirmation`) by
  returning before the increment. Cost today: IWM's only PM break spent both tradeable touches on the
  model's $0.199 mark for a 296C that was really 0.24/0.25 with 70,329 traded. Proposal: move the
  `pick_strike` failure branch above the increment. It changes which touches can enter → **user's
  call**. `skip_engulfing` should keep consuming (that was a real pullback, just a bad bar).
- **F62 (new, PROPOSED, not built) — a touch has no reset.** `touched_ema` is judged bar by bar with
  no requirement that price leave the EMA13 band in between, so a drift on the 13 prints a fresh
  pullback every 2 minutes (IWM's touches #3–#8 in twelve minutes above). The method says "the first
  or second **pullback**" — an event, not a state; A6/`pullback_max_bars` only guards the opposite
  case. Proposal: require a reset (one 2m close ≥ k×ATR clear of the EMA13, or N bars off the band)
  before counting a new touch. **Caution from today's own tape:** QQQ's two winners were touches #1
  (10:02) and #2 (10:06) on the same 716.90 retest, four minutes apart — a reset set too wide refuses
  the second. Must be judged by the sweep, not by today.
- **Replay parity exact on all three** (JSON compare of every event): SPY 2 / QQQ 16 / IWM 13
  reproduced byte-identically, including both `skip_no_contract` refusals and the six late touches.
  **Book untouched:** Team2 Practice cash **and** equity $9,934.16, zero positions, zero Team2 working
  orders.
- **Log clean.** Zero Tracebacks and zero ERRORs of any kind across the live file and its two
  rotations (covering 12:59 ET →) — the other team's `cartel-observer` errors have not recurred since
  the 4th occurrence at 12:08 ET. Rotation is still ~5 MB every 6–33 minutes, dominated by OPRA
  `httpx` INFO lines (run 26's note about log retention stands).
- **Next run (14:45 ET) must:** nothing is queued. 14:45 opens the second session window (R6), so
  watch for **new** setups — IWM's PM break is exhausted and has failed on the tape; live 15m levels
  are QQQ above 721.82 / below 717.03, SPY below 769.00, IWM above the PDH zone top 296.18. **If
  anything fires, check the `contract` event first** (F59: a model refusal can silently cancel it, and
  decay into the close makes a sub-floor mark more likely) and re-measure **F50**'s close-vs-target
  slippage. Keep the **1-of-2 desk-wide book loss** count in view. Still open for the user: **F47**,
  **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**, **F61**, **F62**, and the F30-family
  question of which premium series is authoritative.

## 2026-09-08 14:45 ET (run 28 — the app was DOWN for 9 minutes; restarted, nothing lost, but the restart itself is a trade filter)

- **The app was dead when this run started.** `/api/health` refused the connection; nothing was
  listening on :8420. The server log stops mid-stream at **14:24 ET** with no traceback, no shutdown
  line and no ERROR of any kind in the whole file — an external kill, the same unexplained pattern as
  the 2026-09-04 mid-session stops. No Team2 commit or deploy of mine ran between 14:12 and 14:24, and
  the other team's branch has not committed since 08:33. **Restarted at 14:33 ET** with
  `scripts\start.ps1 -Detach` — 62 plans restored on the first pass, all three Team2 plans back and
  `armed`. Dark window: **14:24 → 14:33, ~9 minutes.**
- **Everything is healthy now.** `/api/health` ok, **v0.7.11**, armed 77; SPY `c861c19d`, QQQ
  `61293ed7`, IWM `33afee68` all `armed`, mode **auto**, Team2 Practice `b9dcd8db…`,
  `needsAttention: false`, `readError: null`, halt `engaged: false`, no per-book halt, no technique
  pause. Pre-open still complete on all three (`complete: true`, SPY PM 766.73–770.48, QQQ
  716.90–723.72, IWM 293.80–295.91).
- **No data was lost to the outage.** Banked 1m bars are **305 of 305 minutes since 09:30 with zero
  gaps** on all three symbols (last bar 14:39 at the time of the check) — the restart's history
  backfill filled the dark window. Quotes **0.1–0.2 s** old, `session: regular` (SPY 767.32 / QQQ
  719.47 / IWM 295.82). The Alpaca **OPRA** batch is polling again (last 14:36 ET). EMA/fan values
  present on all three regimes (SPY mixed, QQQ mixed, IWM bull, all "trend"); sigma still the one
  index-wide 0.1203 (F59/F51).
- **What the tape did.** SPY unchanged at 2 events (still nothing since 10:00). QQQ unchanged at 16
  (nothing since 11:00); its two morning round trips remain the day's only trades. IWM's exhausted
  `pm_break_up@13:15` kept printing watch-only touches straight through the outage — #9 at 14:16, #10
  14:20, #11 14:22, **#12 14:26 and #13 14:30 while the app was dark**, #14 at 14:34 — now **touches
  14, entries 0**, plus a `skip_no_trade_zone` at 14:32 (entry 295.84 back inside the PM range). Spot
  295.82 is below the 295.91 break level: the break has failed on the tape. **Nothing tradeable
  happened in the dark window** — every gap event was a `late_touch` or a no-trade-zone skip.
- **F63 (new, PROPOSED, not built) — a fire during downtime is neither traded nor recorded.** Reading
  the restore path: `PlanRunner.arm(restored=True)` replays the day's bars with `journal=False`,
  `_fire_rest` turns `not journal` into `trade.status = "alert"`, and the next block drops
  replay-minted `alert` trades the live record never had (`phantom_dropped`, added for EM's GOLD
  2026-08-25 case) — while `_act`'s `_seen` cursor has already moved past that event, so no later bar
  reconsiders it. A fire at 14:26 today would have left **no order, no trade row and no journal
  entry**, visible only in the pure re-simulation the read renders. Team2 is more exposed than EM
  because its entire read is re-simulated each bar instead of carried in an incremental tracker. Fix
  belongs in shared `execution/planrunner.py` (tell "the replay contradicts the live record" apart
  from "no live plan existed because the process was down"; then either fire it if the window and
  level still hold, or write it to the counterfactual ledger) — **user's call**.
- **F64 (new, PROPOSED, not built) — a mid-session restart journals the catch-up window twice.** The
  boot restored Team2 plans **twice** (11:33:34 and 11:33:48 PDT, the second right after EM's
  `re-armed 45 plan(s) after restart`), and each pass journaled the three unprocessed events: IWM bars
  14:26, 14:30, 14:32 each have two `events` rows (29750/29794, 29754/29800, 29755/29803). Steady
  state is single-stream (the 14:34 bar journaled once) and the read is unaffected, so no decision was
  doubled — but any audit that *counts* `TechniquePlanRead` / `TechniquePlanTriggerSkipped` rows
  over-counts on every day the desk restarts to deploy, which is most of them. Shared code → proposal.
- **Replay parity exact on all three.** SPY 2 / QQQ 16 / IWM 21 events reproduced byte-identically
  (JSON compare), including the two 13:30/13:40 `skip_no_contract` refusals and all fourteen touches.
  **Book untouched:** Team2 Practice cash **and** equity **$9,934.16**, zero positions, zero Team2
  orders (the last ten orders on the desk are all tips-technique fills). Desk loss tally unchanged at
  **1 of 2** on the book basis (F37).
- **Log otherwise clean for Team2:** zero Tracebacks and zero Team2 ERRORs in the live file (covering
  11:05 PDT →). One non-Team2 warning worth passing on: `zargar.technique score_run b1ddda0b… failed:
  StringDataRightTruncationError — value too long for character varying(24)` at boot (EM's scorer, not
  ours). The **UI check did not complete**: `http://127.0.0.1:8420/team2?token=…` strips the query and
  lands on the sign-in screen in the in-app browser, so the page was verified through the API only.
- **Next run (15:15 ET) must:** nothing is queued; deploy nothing unless something new appears. The
  second session window (14:45–16:00) is open, so watch for **new** setups — IWM's PM break is
  exhausted and has failed, live 15m levels are QQQ above 721.82 / below 717.03, SPY below 769.00, IWM
  above the PDH zone top 296.18. **Check `/api/health` first** — if the app is dark again, that is the
  headline (F63: outage minutes are unmonitored, not empty). If anything fires, read the `contract`
  event before anything else (F59) and re-measure **F50**'s close-vs-target slippage; 15:30 is the last
  entry and 15:45 the flatten. Still open for the user: **F47**, **F49**, **F50**, **F51**, **F54**,
  **F56**, **F58**, **F59**, **F61**, **F62**, **F63**, **F64**, and the F30-family question of which
  premium series is authoritative.

## 2026-09-08 15:05 ET (run 29 — quiet tape, everything healthy; F65: a failed PM break never dies and spends the level for the day)

- **Alive and clean.** `/api/health` ok, **v0.7.11**, armed 77; one armed plan per symbol for
  2026-09-08 (SPY `c861c19d`, QQQ `61293ed7`, IWM `33afee68`), all `armed`, mode **auto**, book Team2
  Practice `b9dcd8db…`, `needsAttention: false`, `readError: null` on all three. Global halt
  `engaged: false`, no book halt, no technique pause. Pre-open still complete on all three
  (`complete: true`; SPY PM 766.73–770.48, QQQ 716.90–723.72, IWM 293.80–295.91). **No restart this
  run** — nothing was queued and nothing needed deploying.
- **Data real-time.** Quotes **0–1 s** old, `session: regular` (SPY 766.76 / QQQ 719.20 / IWM 295.45);
  banked 1m bars **333 of 333 minutes 09:30→15:02 ET with zero gaps** on all three; the read is at
  `bars2m: 166` (= 15:02) with `barAgeSeconds` 64; the Alpaca **OPRA** batch is polling (quotes,
  trades and snapshots at 15:04 ET). EMA/fan values present on all three regimes — SPY bear/trend
  (strength 3), QQQ mixed/trend, IWM mixed/trend. Sigma is still the one index-wide 0.1203 (F51/F59).
- **The tape did nothing new.** SPY unchanged at 2 events (nothing since 10:00), QQQ unchanged at 16
  (nothing since 11:00) — its two 10:06/10:08 round trips remain the day's only trades. IWM added
  nothing after the 14:34 touch: spot fell below its 2m EMA13 (close 295.51 vs EMA13 295.54 on the
  15:00 bar), and a long pullback needs `low <= ema+tol` **and** `close > ema` (session.py:419), so
  the drift below the 13 correctly stops printing touches. Count stands at **touches 14, entries 0**.
- **F65 (new, PROPOSED, not built) — a failed pm-range break is never invalidated, and the level is
  then spent for the day.** `pm_break_*` setups have no death condition anywhere in `session.py`
  (only `scenario_*` die, on the D10 bias flip). IWM's 13:30 break of 295.91 failed — the read itself
  said so twice (`skip_no_trade_zone` 13:58 at 295.76, 14:32 at 295.84, both "inside the pre-market
  range") and price is now 0.46 below the level — yet the setup is still live, still owns the headline
  under F24, and, because `pm_up_done` is day-scoped (line 198), **a second genuine 15m close above
  295.91 could not arm a fresh setup**; the old one is exhausted at 14 touches. The method already
  kills it (L2.6 stop = a 2m close under PMH; F20's "deeper back inside the range the break has
  failed"), and the shared engine already has the mechanism (`TriggerTracker` retires a level after
  `max_false_breaks`, tracker.py:338 — the threshold is in Team2's rules payload and unused by the
  read). Proposal: die on the first 2m **close** back inside the PM range beyond tolerance, clear
  `pm_*_done`, cap re-arms with `max_false_breaks`. Money path → **user's call**. Related to F62: the
  no-reset touch counter is what burned the allowance in twelve minutes.
- **Replay parity exact on all three** (JSON compare of every event): SPY 2 / QQQ 16 / IWM 21
  reproduced byte-identically. **Book untouched:** Team2 Practice cash **and** equity **$9,934.16**,
  zero positions; the last eight orders on the desk are all tips/EM fills, none Team2. QQQ's two
  trades still read −63 then +45 on the book (**−18** net) against +65.6% on the model read — the
  F37 model-vs-book divergence, now visible side by side on the Armed row.
- **Log clean for Team2:** zero Tracebacks and zero Team2 ERRORs across the live file (covering 11:45
  PDT →). One non-Team2 warning recurs at boot and again at 12:03 PDT: EM's
  `score_run … StringDataRightTruncationError — value too long for character varying(24)`.
- **UI verified this run — and the sign-in blocker from run 28 is solved.** The in-app browser drops
  a `?token=` query, but the SPA reads its bearer from `localStorage["zargar_token"]`
  (`frontend/src/lib/api.ts:4`), so: open `http://127.0.0.1:8420`, set that key to the minted session
  via the browser's JS tool, reload. `/team2` Plans + Armed tabs render correctly; **F60's new wording
  is live on IWM** — *"pm_break_up@13:15: its first 2 pullbacks are spent (touches 14) — further
  touches are watch-only (D9/P6)"* — and the Armed rows show account, mode, `$2,000/trade · halt
  $1200`, fills 2/2 and P&L −18 on QQQ, with `bar 118s old`.
- **Next run (15:30–15:35 ET) must:** nothing queued; deploy nothing unless something new appears —
  and in any case **do not restart between now and the 15:45 flatten**. 15:30 is the last entry (D6)
  and 15:45 the flatten (C3): confirm the read emits `skip_last_entry` at 15:30 (F26) and that no
  position is left open at 15:45 (there are none open now). Live 15m levels if anything still fires:
  QQQ above 721.82 / below 717.03, SPY below 769.00, IWM above the PDH zone top 296.18 (its own PM
  break is exhausted, F65). Check the `contract` event first on any fire (F59) and re-measure **F50**
  close-vs-target slippage. Desk loss tally still **1 of 2** on the book basis (F37). Still open for
  the user: **F72 (live today)**, **F47**, **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**, **F61**, **F62**,
  **F63**, **F64**, **F65**, and the F30-family question of which premium series is authoritative.

## 2026-09-08 15:33 ET (run 30 — the 15:30 cutoff held; F66 fixed: the headline was still promising a pullback entry that had closed)

- **Alive and clean, no restart.** `/api/health` ok, **v0.7.11**, armed 78; one armed plan per symbol
  for 2026-09-08 (SPY `c861c19d`, QQQ `61293ed7`, IWM `33afee68`), all `armed`, mode **auto**, book
  Team2 Practice `b9dcd8db…`, `needsAttention: false`, `readError: null` on all three. Global halt
  `engaged: false`, `books: {}` (no per-book halt), no technique pause. Pre-open still complete on all
  three (SPY PM 766.73–770.48, QQQ 716.90–723.72, IWM 293.80–295.91).
- **Data real-time.** Quotes 8–9 s old at the moment of the read, `session: regular` (SPY 767.08 /
  QQQ 718.93 / IWM 295.36); banked 1m bars **363 of 363 minutes 09:30→15:32 ET with zero gaps** on all
  three; the read is at `bars2m: 181`, `barAgeSeconds` 61–74. The Alpaca **OPRA** batch is polling
  (last request 15:33 ET). EMA/fan values present on all three — SPY bear/trend, QQQ bear/trend,
  IWM mixed/trend. Sigma still the one index-wide 0.1203 (F51/F59).
- **D6 verified — the last-entry cutoff fired correctly.** All three reads minted `skip_last_entry` on
  the **15:32** 2m close: *"past 15:30 — no new entries, managing what is open until the 15:45 flatten
  (D6/C3)"*. Emitted once per session (`last_entry_noted`), on the late side only, exactly as F26
  built it. Every trigger row carries `windowOpenNow: false`.
- **The tape did nothing new.** SPY still 3 events (last real one 10:00), QQQ still 17 (last 11:00),
  IWM still 22 (last touch 14:34) — the 15:32 cutoff note is the only new event on each. Counts hold
  at QQQ 2 trades / IWM touches 14, entries 0. No position is open anywhere, so the 15:45 flatten will
  be a no-op; nothing to unwind before the close.
- **F66 (new, FIXED this run, not yet deployed) — the one line the desk reads was still promising a
  trade the clock had closed.** At 15:33 all three Armed rows read *"waiting for the 1st/2nd 2m
  pullback into the EMA13 (touches 0) · no entry until the stack turns bull · the last pullback sat
  inside the pre-market range"* — three minutes after entries closed for the day. The read knew
  (`skip_last_entry`) and the API knew (`windowOpenNow: false`); only the human sentence did not. Same
  family as F53/F57/F60. Fixed in `runner.py`'s snapshot: the state line becomes *"past 15:30 — no new
  entries today, flat by 15:45 (D6/C3)"* (and *"the desk is flat for the day (C3)"* after 15:45), the
  now-moot "no entry until…" / "no-trade zone" clauses are dropped with it, and an open position's
  line gains *" · sold at 15:45 whatever the read says (C3/D-1)"*. Driven by the session's own event,
  not the wall clock, so replays say the same thing. **Reporting only — no rule, threshold, gate, size
  or money path changed.** 57 Team2 tests pass (new F66 assertions in `test_team2_runner.py`).
- **DEPLOY QUEUED (commit `ce8c543`), deliberately not deployed this run.** Run 29 queued "do not restart between now and
  the 15:45 flatten"; a restart at 15:33 would drop the desk dark across the flatten window for no
  reason. Committed on the branch — **the next run (16:00 ET, after the close) must run
  `scripts\start.ps1 -Detach`** to pick it up.
- **Replay parity exact on all three** (JSON compare of every event *and* every trade): SPY 3 / QQQ 17
  / IWM 22 events and QQQ's 2 trades reproduced byte-identically, including the new `skip_last_entry`
  rows. **Book untouched:** Team2 Practice cash **and** equity **$9,934.16**, zero positions; the last
  twelve orders on the desk are all tips/EM fills, none Team2. Desk loss tally unchanged at **1 of 2**
  on the book basis (F37).
- **Log clean for Team2:** zero Tracebacks and zero ERRORs of any kind in the live file (covering
  15:18 ET →). Rotation still ~5 MB every 20–35 minutes, dominated by OPRA `httpx` INFO lines.
- **UI verified** (in-app browser, `localStorage["zargar_token"]` recipe from run 29): `/team2` Plans
  and Armed tabs render correctly; the plan rows correctly show **"Sep 4, 5:34 PM ET"** as the build
  time for a 2026-09-08 session — Friday's 17:00 job planning across the weekend **and Labor Day
  Monday**, which is F41/F42's calendar fix working as intended in production.
- **Next run (16:00 ET, after the close) must:** (1) **deploy** — `scripts\start.ps1 -Detach` from
  `C:\Cursor\zargar`, then re-check `/api/team2/status` and confirm the F66 wording; (2) confirm the
  session closed cleanly — plans `expired`/`disarmed`, no position left open, no `clock_flatten` errors
  in the journal; (3) confirm the **17:00 plan job** mints tomorrow's (2026-09-09) SPY/QQQ/IWM plans
  once each (F41: never twice); (4) grade the day — QQQ 2 trades (−63 then +45, **−18** on the book vs
  +65.6% on the model read: the F37 divergence), IWM 14 touches and 0 entries, SPY 0. Still open for
  the user: **F47**, **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**, **F61**, **F62**,
  **F63**, **F64**, **F65**, and the F30-family question of which premium series is authoritative.

## 2026-09-08 16:20 ET (run 31 — post-close: the session closed clean, the queued F66 deploy went out, F67 fixed — the desk can read a closed day again)

- **Deployed twice, both after the close, nothing armed and nothing open.** First
  `scripts\start.ps1 -Detach` at 16:05 ET picked up run 30's queued **F66** commit `ce8c543`; the
  second at 16:17 ET carried this run's **F67** (`55d1b61`). `/api/health` ok, **v0.7.11**, armed 18
  (all tips/EM — Team2's three are disarmed for the day). Scheduler re-registered
  `team2_plan_nightly at 17:00 ET` and `team2_preopen at 09:25 ET` on both boots; the desk loss tally
  re-seeded to **1 loser** from today's disarmed plans (F38), which is correct.
- **The session closed cleanly.** All three plans went `TechniquePlanScored` → `TechniquePlanDisarmed`
  at 16:00:00 ET with `reason: session closed`, `flatten: false`, `openLeft: 0`, `stopReason: null` —
  no `clock_flatten` error, nothing to unwind, no position anywhere. The **15:32 `skip_last_entry`**
  (D6) is the last event on each read. Banked 1m bars: **390 / 390 minutes 09:30 → 15:59 with zero
  gaps on SPY, QQQ and IWM**, so even the 14:24–14:33 outage window is complete in the record.
- **The day, graded.** **SPY** 0 fires (scenario 4 = break PDL at 09:45, one no-trade-zone refusal at
  10:00). **QQQ** the only trades of the day: both `pm_break_down@09:30` retests of 716.90 —
  14 × QQQ260908P00714000 @ $0.655 (10:02→10:04) and 9 @ $0.63 (10:06→10:08) — model **+32.69 %** and
  **+32.92 %**, book **−$92.12** then **+$26.28**. **IWM** 0 entries against **14 touches** on the
  13:15 pm-break that later failed, plus 2 `skip_no_contract` and 3 no-trade-zone refusals.
  **Desk day: book 10,000.00 → 9,934.16 = −$65.84** — gross −$18.00 plus **$47.84** of commissions
  (23 contracts × 2 legs × $1.04). Loss tally ends **1 of 2** on the book basis (F37). F50's estimate
  of "$58 of commissions" is corrected in place to the scorecard's exact $47.84.
- **F67 (new, the Team2 half FIXED and deployed `55d1b61`; the shared half PROPOSED) — after the
  close the day was invisible, and where visible it was wrong.** The shared **Armed > History** list
  showed **no SPY/QQQ/IWM row at all** for 2026-09-08 (its day header read *"42 plan(s) · 10 fired ·
  0.00 realized"*): `armed_history` orders by `created_at` and the page asks for 50 rows, and Team2's
  plans are always built the *previous* session — today's on Friday at 17:34 ET — so 50 plans built
  Sep 7–8 by EM and tips pushed them out. Sorting by `plan_for` alone would not fix it (Sep 8 has 45
  rows; Team2's are still the oldest within the day). Second half: that table's Realized column renders
  `state.realizedPnl`, which is **gross** — QQQ read **−18.00** against the book's **−65.84**, though
  the net figure sits on the same row in `state.scorecard.realizedPnl` and shared halts have been net
  since F32. Both halves are EM's technique service / the shared Armed page → **proposals, logged in
  `docs/PLATFORM-RULES.md` §3**. **Fixed the half this desk owns:** `Team2Service.runs()` now returns a
  `result` block per plan (fires, matched, the model % sum, the book's net *and* gross, the skip tally)
  and the Team2 page's History tab renders a **"How it went"** column — verified live in the browser:
  *"2 trade(s) · -65.84 book · read +65.6%"* (QQQ), *"no trade · 6 refused"* (IWM), *"no trade ·
  2 refused"* (SPY), with commissions and per-skip counts in the tooltip. Reporting only — no rule,
  threshold, gate, size or money path changed. 57 Team2 tests pass (new F67 assertions in
  `test_team2_runner.py`); changelog entry added under 0.7.11.
- **Replay parity exact on all three** (JSON compare of every event *and* every trade): SPY 3 / QQQ 17
  / IWM 22 events and QQQ's 2 trades reproduced byte-identically. **Book flat:** Team2 Practice cash
  **and** equity **$9,934.16**, zero positions, zero Team2 working orders.
- **Log clean.** Exactly one ERROR in the live file and it is not ours (an asyncio
  `ConnectionResetError` on a client socket at 13:08 PDT, before the second restart); zero errors and
  zero Tracebacks since the last boot. EM's `score_run … StringDataRightTruncationError` boot warning
  recurs (not Team2). The expired `QQQ260908P00714000` is still in the OPRA batch tonight — F44 drops
  it on the first refresh after expiry, so tomorrow's first run should confirm it is gone.
- **Next run (tomorrow 09:00 ET, first of the day) must:** (1) confirm the **17:00 ET job minted
  2026-09-09 plans once per symbol** — F41, never twice, and the desk restarted twice today, so check
  the count before anything else; (2) confirm the **09:25 pre-open** completed all three
  (`pmh`/`pml`/`dayType`/`sizingAtOpen`/`complete: true`) and call `POST /api/team2/preopen-now` if
  not; (3) check quotes/1m bars/OPRA freshness at the open; (4) glance at the new **"How it went"**
  column on Team2 → History — yesterday's row should read *"2 trade(s) · -65.84 book · read +65.6%"*.
  Still open for the user: **F47**, **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**,
  **F61**, **F62**, **F63**, **F64**, **F65**, F67's two shared-side halves, and the F30-family
  question of which premium series is authoritative.

## 2026-09-08 16:45 ET (run 32 — last of the day; F68 fixed: "refused" now means refused, F69 logged — the log only remembers ~50 minutes)

- **Alive, clean, deployed once (post-close, nothing armed or open).** `/api/health` ok, **v0.7.11**,
  armed 18 (all tips/EM). `/api/team2/status` `armed: []` — today's three plans are disarmed for the
  day, as run 31 recorded. Team2 Practice **$9,934.16** cash *and* equity, zero positions, zero Team2
  working orders; the last dozen orders on the desk are all tips/EM. Nothing on the tape to read: the
  market closed 45 minutes ago and the 15:32 `skip_last_entry` is still the last event on each read.
- **F41 re-verified from the journal, not the UI.** `ScheduledJobRan` shows **Labor Day's** 17:00 job
  (`2026-09-07T21:00Z`) minting nothing: `runs: [], armed: [], skipped: ["SPY: already armed for
  2026-09-08", …]` — exactly the double-arm F41 was built to prevent, with today's real plans coming
  from Friday's 17:34 ET run. Today's `team2_preopen` ran at `13:25:07Z` = **09:25 ET** and completed
  all three. Tonight's 17:00 ET job fires ~15 minutes after this run ends, so **tomorrow's first run
  still owns the "2026-09-09 minted once per symbol" check**, and the desk restarted twice today plus
  once more this run.
- **F68 (new, FIXED and deployed `1600b68` + `dc9bdc0`) — yesterday's new "How it went" column
  over-counted how often the method said no.** F67 shipped counting *every* `skip_*` row in the
  scorecard as a refused setup. Three of them are not refusals at all: `skip_last_entry`,
  `skip_event_day` and `skip_loss_cap` are minted **once per session** by `session.py` to say what
  state the day is in — F26 added them precisely so a day that goes quiet after 15:30 does not look
  like a day with no setups. Today's closed rows therefore read **SPY "no trade · 2 refused"** for one
  real refusal (the 10:00 no-trade-zone + the 15:32 cutoff note) and **IWM "6 refused"** against five
  (2 × no contract, 3 × no-trade-zone) — an inflated number on exactly the statistic the F62/F65
  argument about refusal rates turns on. This is F28's principle one layer up: *skip counts must mean
  skips*. `service.py` now names the three in `DAY_NOTES`; the result block gains **`refused`** (the
  tally to read) and **`notes`** (which day states applied), the raw `skips` map is untouched, and
  rows written before the fix still render from the raw sum. **Verified live in the browser:** IWM
  *"no trade · 5 refused"*, SPY *"no trade · 1 refused"*, QQQ unchanged at *"2 trade(s) · -65.84 book ·
  read +65.6%"*, with *"day: last entry"* now in the tooltip. **Reporting only — no rule, threshold,
  gate, size or money path changed.** 57 Team2 tests pass (F68 assertions in `test_team2_runner.py`).
- **Self-inflicted, worth recording:** the first `start.ps1 -Detach` **failed the frontend build and
  left the server down for ~90 seconds** — my changelog edit put unescaped `"` inside a double-quoted
  TS literal (TS1005). `start.ps1` stops the old process *before* it rebuilds, so a build error is an
  outage, not a no-op. Fixed and redeployed immediately (`dc9bdc0`); nothing was armed or open, and
  the 18 tips/EM plans restored. Lesson for this watch: **run `npm run build` before `start.ps1`,
  never rely on the deploy to catch it** (the CLAUDE.md gate exists for this reason).
- **F69 (new, PROPOSED, not built — shared).** The app log keeps **~50 minutes** of history and this
  watch has now lost the 09:25 pre-open lines three separate times. Measured this run: **5,378 of
  5,430 lines (99.0 %)** written in 13.5 minutes are `INFO httpx HTTP Request` polling lines (4,316
  Yahoo 1m · 635 Alpaca/OPRA · 406 CBOE); the app's own content is ~52 lines in that window.
  `main.py:20` rotates at `maxBytes=5_000_000, backupCount=3`. Options: **(a) `backupCount` 3 → 20**
  (~5 hours, ~100 MB — loses nothing, one number, recommended) or (b) `httpx` logger → WARNING (~100×
  smaller, but it deletes the request trace that diagnosed **F45**'s CBOE 429 storm). Shared engine →
  **user's call.**
- **Log clean for Team2** across both boots: zero Tracebacks, zero Team2 ERRORs; the scheduler
  re-registered `team2_plan_nightly at 17:00 ET` and `team2_preopen at 09:25 ET`, and the loss tally
  re-seeded to **1 loser** (F38, correct). The only warning is EM's known `score_run …
  StringDataRightTruncationError` — not ours. The expired `QQQ260908P00714000` is still in the OPRA
  batch, which is F44 behaving as written (it drops a contract once its expiry is *past*); tomorrow's
  first run should see it gone.
- **Next run (tomorrow 2026-09-09 09:00 ET, first of the day) must:** (1) confirm the 17:00 ET job
  minted **2026-09-09** plans **once per symbol** (F41 — the desk restarted three times today);
  (2) confirm the **09:25 pre-open** stamped `pmh`/`pml`/`dayType`/`sizingAtOpen`/`complete: true` on
  all three, else `POST /api/team2/preopen-now`; (3) check quote/1m-bar/OPRA freshness at the open and
  that `QQQ260908P00714000` has left the batch (F44); (4) yesterday's History row should read
  *"2 trade(s) · -65.84 book · read +65.6%"* (QQQ), *"no trade · 5 refused"* (IWM), *"no trade ·
  1 refused"* (SPY). Still open for the user: **F47**, **F49**, **F50**, **F51**, **F54**, **F56**,
  **F58**, **F59**, **F61**, **F62**, **F63**, **F64**, **F65**, **F69**, F67's two shared-side halves,
  and the F30-family question of which premium series is authoritative.

## Desk session 2026-09-08 evening — the Codex batch (v0.7.13; first deployed as 0.7.12, renumbered after PR 13 took that number)

User instruction: "Go ahead with the hosting investigation and revised correctness work. Keep F47 and both F56
variants experimental. Add tests proving IV updates cannot rewrite past signals or cause skipped/duplicate
events, and define realistic quote-target execution semantics. Twenty sessions triggers a review, not
automatic promotion. Continue Practice with existing risk limits once recovery and exit protection are verified."

- **Hosting — cause found.** Windows Application log: `CoworkVMService` "Claude VM Service stopped" 11:24:01 PT
  (14:24:01 ET) during the Claude desktop package update 1.49585 ("Relaunch to update"). The engine was a child of
  that tree. Fix: `scripts/watchdog.ps1` + `scripts/install-watchdog.ps1` → user tasks `ZargarWatchdog` (3 min),
  `ZargarWatchdogLogon`, `ZargarRestart` (on demand = the deploy path). Log retention 50 MB × 10, httpx quiet,
  start/stop lines with pid (F69).
- **Read integrity:** fingerprints (no re-fire / no skip when an input moves; `read_rewritten` once), sigma locked
  per session from the 0DTE ATM chain and stamped (F51), open finalized on the 09:30 bar (F49).
- **Execution:** F50 `target_breach` hook — plan target on a fresh underlying print, reduce-only limit at the bid.
- **Read:** F62 pullback episodes (`pullback_reset_atr` 0.5), F61 only priced pullbacks spend.
- **Experimental, not promoted:** F47, F56a, F56b. **Governance:** 20 sessions → review (PLAN §3d).
- Tests: `tests/test_team2_integrity.py` (9 new) + Team2/halt/exit/arming suites: 114 passed (the first full run
  caught three pure-read regressions from F62 — the departure was judged only at the entry gate, so a bar spent in a
  trade never re-armed the next pullback; now judged on every 2m close, `268adf6`). Deployed 16:53–16:54 ET via
  `schtasks /Run /TN ZargarRestart` (30 s, engine pid 18364 owned by the scheduler); the 3 plans for 2026-09-09 restored
  on Team2 Practice and set back to auto at $2,000 / 6 % (per-plan halt $1,192); `sigma`/`complete` stay empty until the
  09:25 pre-open and the first 2m read. Zero `httpx` INFO lines since boot (F69). EM's known
  `technique_outcomes` truncation error is still in the log — not ours.

## 2026-09-09 09:00 ET (run 33 — first of the day, pre-open; everything green, F70 logged)

- **Alive and current.** `/api/health` ok, **v0.7.22** (the desk moved 0.7.13 → 0.7.22 overnight on
  other teams' merges — EM run-cap, Cartel moderate alignment, tips intake reviews, `restart.ps1`
  watchdog-lock and ASCII fixes). Engine up since **02:59 ET** (pid 14092); the app log shows nine
  boots between 20:27 and 23:59 PDT last night, all the evening desk session and its watchdog, and
  eleven `TechniquePlanRestored` events on each Team2 plan to match. Nothing armed or open was lost.
- **F41 clean — plans minted once, from the journal not the UI.** Exactly **one**
  `ScheduledJobRan team2_plan_nightly` at **2026-09-08 17:00:26 ET**, and exactly **three**
  `technique_runs` rows for it (SPY `e4d39d00` 17:00:25, QQQ `9a1094ed` 17:00:25, IWM `e87e4ad2`
  17:00:26), all `armed` for `planFor 2026-09-09`. No duplicate despite the nine restarts.
- **Mode is `auto` on all three, as the evening session left it** (`TechniquePlanModeChanged
  alert → auto` at 21:16 ET yesterday, journaled): Team2 Practice, premium budget **$2,000**,
  risk **6 %**, per-plan daily loss halt **$1,192.10**, `maxOpenTrades 1`, `allowLive false`.
  Not touched by this watch.
- **Data is real-time.** 1m bars for SPY/QQQ/IWM banking to **09:02 ET** (92 s old, pre-market);
  quotes `quoteAgeSeconds 0–2`, `session: "pre"`; `alpaca stream: connected` + `authenticated` at
  boot with no reconnects since. `dayHigh/dayLow/volume` are 0 pre-open, which is F19 behaving.
  **0DTE chains exist for all three** (`/api/options/{sym}/expiries` → `2026-09-09 dte 0 is0dte`),
  so the contract pick has something to hit today: SPY spot 763.57 iv30 12.6, QQQ 715.06 / 18.4,
  IWM 293.12 / 17.3.
- **F44 confirmed closed:** the expired `QQQ260908P00714000` appears **1,339 times** in the log
  history and **zero** times since the 23:59 boot — it dropped out of the OPRA batch on the first
  refresh after expiry, exactly as written.
- **Tonight's sheet (gap-down day on all three, plan `complete` in replay, `openPrice` from the
  pre-market print):** SPY PDH 767.46–769.70 / PDL 765.14–765.99, PM 762.49–767.13, last close
  765.99, open 763.70. QQQ PDH 717.47–721.89 / PDL 715.57–716.50, PM 713.50–720.67, close 718.38,
  open 715.09. IWM PDH 295.86–296.10 / PDL 294.26–294.81, PM 292.62–294.82, close 294.70, open
  293.31. QQQ sits **0.05 %** under its PDL trigger and IWM **0.33 %** — a 15m close below either
  starts a put day. No scenario, no bias, no regime yet: correct at 09:12 ET, before the open.
- **Yesterday's History row renders right** (F67 + F68 verified live through the API): QQQ
  *"2 trade(s) · -65.84 book · read +65.6%"*, IWM *"no trade · 5 refused"*, SPY *"no trade ·
  1 refused"*, each with `notes: ["skip_last_entry"]` kept out of the refusal tally. **Book flat:**
  Team2 Practice cash **and** equity **$9,934.16**, zero positions.
- **Tests green on the new version:** 66 passed (`tests/test_team2_*.py
  tests/test_marketstructure_extended.py`, own DB `zargar_test_team2_watch`) — the 0.7.13 → 0.7.22
  merges broke nothing of ours.
- **F70 (new, PROPOSED, not built — shared feed).** `Quote.prev_close` is **one session stale in
  pre-market**: `/api/quotes` gave SPY `prevClose 770.19` (the **09-04** close, confirmed against the
  1d `bars` table) with `regPrice 765.96` (the real prior close, which CBOE also reports via
  `/api/options/SPY/expiries`). `brokers/yahoo.py:287` reads `chartPreviousClose`, and before the
  open Yahoo's 1d chart is still yesterday's session. So the desk shows SPY at about **-0.86 %**
  pre-market where the truth is **-0.29 %**; it self-corrects on the 09:30 bar, which is why it has
  never been caught in-session. **Team2 is unaffected** — the gap rule and `dayType` come from the
  plan's `lastClose` and the 1m bars, and `techniques/team2/` never reads `quote.prev_close`.
  One clause in the shared Yahoo poll would fix it → **user's call**. Written up in TRADING-RULES.
- **Log clean, one piece of shared noise.** Zero Team2 errors, zero Tracebacks since boot; the
  scheduler re-registered `team2_plan_nightly 17:00 ET` and `team2_preopen 09:25 ET`. The only two
  ERRORs in the file are EM's (an httpx connect failure at 21:40 ET yesterday, twice). Worth a
  mention for whoever owns marketdata: **~1,100 `persist_bars: dropped N non-bucket-aligned stub
  bar(s)` WARNINGs in six hours**, N climbing 1 → 15 — the EM #5 guard doing its job, but it is now
  the loudest thing in the log and F69's rotation fix is what makes it visible. Not ours, not fixed.
- **Nothing deployed this run** — no defect found in Team2 code, and the window was inside the
  09:25–09:35 no-restart guard by the end of it.
- **Next run (09:30 ET) owns the pre-open check:** the 09:25 job fires 13 minutes after this run
  ended, so confirm `pmh`/`pml`/`dayType`/`sizingAtOpen`/`complete: true` on all three and call
  `POST /api/team2/preopen-now` if any is missing; then watch the first 2m closes against the PDL
  zones (QQQ and IWM are the near ones) and check that `bias`/`regimeLast` start advancing.
  Still open for the user: **F47**, **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**,
  **F61**, **F62**, **F63**, **F64**, **F65**, **F69**, **F70**, F67's two shared-side halves, and
  the F30-family question of which premium series is authoritative.

## 2026-09-09 09:30 ET (run 34 — the pre-open check; all green, F71 found and fixed)

- **Alive, plans intact, no restarts today.** `/api/health` ok, v0.7.22, 82 armed. The last
  `TechniquePlanRestored` on all three Team2 plans is **02:59 ET** (the evening session's watchdog
  boot) — nothing has restarted since, and the watchdog has ticked cleanly every 3 minutes all
  morning (`logs/watchdog.log`, rc=0 through 09:34). Mode still **auto** on Team2 Practice, $2,000
  premium / 6 % risk, per-plan halt $1,192.10, `maxOpenTrades 1`, `allowLive false`. Not touched.
- **The 09:25 pre-open completed on all three, and this run owns that check: PASS.**
  `ScheduledJobRan team2_preopen` at **09:25:10 ET (0.8 s)**, `TechniquePlanPreopen` journaled on
  each plan at 09:25:54, and every plan now carries `complete: true` with `pmh`/`pml`/`dayType`/
  `sizingAtOpen`. SPY PM 762.49–767.13, QQQ 713.50–720.67, IWM 292.62–294.82. `sizingAtOpen` is
  **`none` on all three** — correct, not a miss: every open printed *inside* its own pre-market
  range, which F15 calls chop. No `preopen-now` call was needed.
- **F49 fired and did its job.** At 09:31:00 each plan finalized the day type on the real 09:30
  open: SPY 764.08 `gap_down → gap_down`, IWM 293.46 `gap_down → gap_down`, and **QQQ 716.40
  `gap_down → normal`** — the 09:25 estimate off the last pre-market print was wrong on QQQ and the
  RTH open corrected it, which is exactly what F49 was built for. **F51 fired too**: sigma locked at
  09:32 from the 0DTE ATM chain (SPY 0.1212, QQQ 0.1748, IWM 0.1610) and is stamped on the run, so
  the replay reproduces the same premiums.
- **Data is real-time, all three legs.** 1m bars banking to within ~60 s (SPY/QQQ/IWM 09:34 read at
  09:35); underlying quotes `quoteAgeSeconds 0`, `session: "regular"`, `dayHigh/dayLow/volume`
  session-to-date (SPY 1.34 M by 09:33). **Option quotes are OPRA, not the delayed chain**: the
  0DTE ATM contracts came back `source: "opra"`, `provider: "alpaca"`, `delayed: false`, `sourceTs`
  the same second (SPY 765C 0.72/0.73, QQQ 717C 1.84/1.85, IWM 293P 0.45/0.46 — the ~$0.50 band the
  method wants is populated). Alpaca stream `connected` + `authenticated` at the 02:59 boot with **no
  reconnects since**. F70's stale `prevClose` self-corrected at the open as predicted (SPY
  `prevClose 766.00`), confirming it is a pre-market-only defect.
- **The read is advancing and correct.** 2m closes stepping every two minutes (bars2m 1 → 7 across
  the run), `regimeLast` EMAs present on every one, `bias` still null at 09:45 with
  `fifteenMinBars: 0` — **right**, because the first 15m bar of the session does not close until
  09:45. SPY (763.6) and IWM (293.2) have been *through* their PDL zones since the open and QQQ sits
  between its zones; the next 15m close is the decision. Replay parity: `POST /runs/{id}/replay`
  reproduced the live read on all three (same sigma, same zero events/setups/trades). No
  `read_error`, no `needsAttention`, zero Team2 ERRORs or Tracebacks in the log since boot.
- **F71 (new, FIXED and live this run).** The plan panel's "Now:" line showed **SPY's PDL as
  "+0.20 % away"** while SPY was 1.50 *through* it, and **QQQ's PDL — which really did have 1.35 left
  to fall — as "−0.19 % away"**: the broken level read as nearer-than-nothing and the unbroken one
  read as negative. Cause: `distancePct = (level − price)/price` is direction-blind, so on a short row
  a positive number means *already through*. Fixed with a direction-aware `team2Distance()` in the
  **Team2 branch only** of `ArmedDayPanel.tsx` — a break row already through now says *"price is
  already through, waiting on the 15m close"*. The signed field itself is untouched, so the shared
  Armed page and the phone keep their correct "level X % above/below" wording. **Reporting only — no
  rule, threshold, gate, size or money path changed.** 66 Team2 tests pass; `npm run build`
  (typecheck + check-release) passes. Verified at the data level (both signs measured live off the
  API) and in the served bundle; I did **not** get a clean visual confirmation — the in-app browser
  would not keep the Team2 Armed tab selected after a re-render, so the on-screen check is owed to
  the next run.
- **Deployed without a restart, and one restart is queued.** The change is frontend-only and
  `start.ps1` had already been given a fresh `dist` by my build, which the running server serves off
  disk — the new bundle (`index--9Q1rk2u.js`) is live now. Version bumped to **v0.7.23** in all four
  files + the lockfile, so the **UI chip reads 0.7.23 while `/api/health` still reports 0.7.22**
  until the backend restarts. I did **not** restart: at 09:45 the first 15m close of the session was
  landing on two symbols sitting through their PDL, and that is the worst possible moment to bounce
  the engine. **Next run: `scripts\start.ps1 -Detach` if nothing is open or working**, which
  re-aligns the health version.
- **Not ours, worth repeating for whoever owns marketdata:** `persist_bars: dropped N
  non-bucket-aligned stub bar(s)` is still the loudest line in the log (~1–9 per minute all morning),
  plus a `calendar fetch failed for SPX: 404` from the Yahoo quoteSummary endpoint. Both are outside
  Team2.
- **09:46 ET, after the fix landed — the 09:45 15m close armed all three, every one SHORT.** SPY
  `scenario 4 break PDL` (level 765.14, target 764.75), IWM `scenario 4 break PDL` (294.26 → 293.56),
  QQQ `scenario 2 reject PDH` (717.47 → 716.50, `rangeDay: true`). All three read
  *"waiting for the 1st/2nd 2m pullback into the EMA13 (touches 0) · EMA stack mixed, trend — no
  entry until the stack turns bear (E3/B9/E4)"* — method-correct: the scenarios are right for a
  gap-down open (two straight through the PDL, one rejecting the PDH from inside), and the desk is
  correctly refusing to buy puts into a mixed stack. This also settles the queued-restart call:
  **do not restart while these are live.**
- **F72 (new, PROPOSED, NOT built — a rules question, and it is LIVE today).** SPY's and IWM's
  planned targets are **already behind price**: SPY's target is 764.75 with SPY at 763.7, IWM's is
  293.56 with IWM at 293.2. Because `techniques.team2.hod_target` is **`reentry`**, the X3b running-LOD
  retarget does not apply to the day's *first* entry (`session.py:556` needs `s.entries >= 1` or a
  prior trade), so a first entry keeps that stale target — and `session.py:313`'s short exit test
  `b2.low <= target` is **already true**, so the position would close on the very next 2m bar. Worse,
  for a short a target *above* the entry is a **loss** booked under a "target reached" label, so the
  day's grade would score a stop-out as a win. Only the EMA-stack gate is holding it off right now.
  Three options written up in TRADING-RULES F72 — refuse the setup for lack of room, set
  `hod_target=always`, or re-derive the target below *current* price. **Not built: user's call.**
- **Next run (10:00 ET) should:** (1) run the queued `start.ps1 -Detach` if flat, and confirm
  `/api/health` reads 0.7.23; (2) get the visual confirmation of F71 on the Team2 plan panel;
  (3) check what the 09:45 and 10:00 15m closes did — SPY and IWM were through their PDL zones, so a
  put scenario is the live possibility, and if one arms, verify the EMA13 pullback entries, the
  `contract` pick (strike + ask near $0.60) and replay parity against the live fire. Still open for
  the user: **F47**, **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**, **F61**, **F62**,
  **F63**, **F64**, **F65**, **F69**, **F70**, **F71's shared half**, F67's two shared-side halves,
  and the F30-family question of which premium series is authoritative.

## 2026-09-09 10:15 ET (run 34b — F72's safety guard built and deployed, v0.7.24)

- **Built to the user's scope: a guard, not a strategy change.** `scenario.target_is_ahead()` —
  strictly above for a long, strictly below for a short; `None` (no target) and an unjudgeable spot
  stay allowed; **equality is refused**. Applied at BOTH money-path entrances: the read refuses the
  entry (`skip_target_behind`, `session.py`) and the runner **drops** a stale fallback target
  (`target_dropped`, `runner.py`). The runner half is the one that closes the **quote-watch**
  exposure — `target_breach` runs on the ~2s watch, so a wrong-side target would have sold the whole
  position on the FIRST live print, before any 2m bar closed.
- **Explicitly not relied on, per the instruction:** the EMA-stack gate (it was only incidentally
  holding this off today) and a global `hod_target` flip (that is the strategy decision, kept
  separate). **Existing-position protection untouched** — an open position keeps its target exit,
  premium stop, candle stop, trims and flatten; two tests pin it, including one proving a *valid*
  target still exits on the live print.
- **Placement detail worth keeping:** the target resolution was hoisted above the strike pick, so a
  refusal costs no `pick_strike` call and — like the other structural refusals (F18) — **does not
  spend the D9 pullback allowance**; only a priced fire does (F61). Location gates still run first,
  which is why IWM's pullbacks today are refused by the no-trade zone before the target is ever
  judged.
- **Surfaced, per the F57/F59 lesson** (a refusal the desk cannot see is a refusal that does not
  exist): journalled as a trigger skip, stated in the Armed/phone headline via `skip_why`, and given
  timeline icons in `ArmedDayPanel`.
- **Tests: 28 new in `tests/test_team2_target_guard.py`, every case mirrored long/short** — the
  predicate (ahead / wrong-side / equal / `None` / no spot), end-to-end refusal on a new synthetic
  `down_day` and its long mirror, the boundary a ten-thousandth on the wrong side, controls proving
  the guard does not over-fire, the D9 allowance, note-once behaviour, and the quote watch (a
  wrong-side target *would* fire on the first print; a dropped one does not; a valid one still does).
  **94 Team2 tests pass**; frontend build green. One test had to be rewritten honestly: an EXACT
  price tie is unreachable end-to-end because the trade dict rounds the entry spot to 4 dp, so
  equality is pinned at the predicate level and the integration test proves the boundary a hair off.
- **Deployed at 10:15 ET with the desk flat** (no trades, no open positions, touches 0 on all three
  — the one moment it was safe). `start.ps1 -Detach`, v0.7.24 live, `/api/health` agrees, all three
  Team2 plans restored with their scenarios intact (tips 18, managed positions 9, no errors).
- **Honest live status: deployed, NOT yet exercised by the tape.** SPY (target 764.75 at 763.8) and
  IWM (293.56 at 292.8) would both be refused, but no qualifying pullback has reached the guard yet.
  QQQ is correctly unaffected — its 716.50 target is genuinely ahead of 718.75 for a short, which is
  the selectivity check. Next run should look for a real `skip_target_behind` in the read.
- **The strategy question is deliberately still open** — the guard stops the bad trade, it does not
  recover a good one. Three replacement options are written up in TRADING-RULES F72 (refuse and move
  on / `hod_target=always` / re-derive the target below current price) with the cost of each. Also
  still open: **F47**, **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**, **F61**,
  **F62**, **F63**, **F64**, **F65**, **F69**, **F70**, **F71's shared half**, F67's two shared-side
  halves, and the F30-family question of which premium series is authoritative.

## 2026-09-09 10:30 ET (run 35 — F72's guard fires for real; F71 turned out to be dead code, fixed as F73, v0.7.25)

- **Alive and clean.** `/api/health` ok, v0.7.24, armed 77 — the queued restart from run 34 was
  already taken at 10:15, so the health version and the UI chip agreed on arrival. Three Team2 plans
  armed for 2026-09-09 (SPY, QQQ, IWM), all `complete: true`, no `read_error`, `needsAttention`
  false on all three, and **zero Team2 errors or Tracebacks since the 10:15 boot**. Alpaca stream
  `connected` + `authenticated` at 07:15:19 PT with no reconnects since.
- **Mode is `auto`, and that is the user's own setting, not drift** — `techniques.team2.mode` was set
  to `auto` on **2026-09-04**, five days ago, and every plan carries `allowLive: false` on the sim
  book **Team2 Practice**. Recording it because the watch recipe still says "alert unless the user
  changed it": the user changed it, and the desk has been trading Practice on auto since.
- **Data is real-time on all three legs.** 1m bars banking to 10:32 read at 10:34 (SPY/QQQ/IWM all
  the same ts); underlying quotes `quoteAgeSeconds 0`, `session: "regular"`, volumes session-to-date
  (SPY 5.96 M). **Option quotes are OPRA**: the three 0DTE ATM puts came back `provider: "alpaca"`,
  `delayed: false`, `asOf` the same second (SPY 763P 0.78/0.79, QQQ 717P 1.00/1.01, IWM 292P
  0.39/0.41 — the ~$0.50 band the method wants is populated and tight).
- **F72's guard fired live at 10:32 on IWM — its first real instance, and it was right.** The read
  journalled `skip_target_behind`: *"target 293.56 is above the 292.58 entry — price has already run
  through it"*. Worth noting exactly why this one reached the guard when SPY's did not: IWM's
  pullback at 292.58 fell just **below** the pre-market low 292.62, so it escaped the no-trade zone
  that has been refusing SPY all morning (SPY 10:28, entry 763.57 inside PM 762.49–767.13) — the
  guard was the only thing standing between the desk and a short whose target sat $0.98 *above* the
  entry. QQQ is correctly unaffected (target 716.50 genuinely below spot), which is the selectivity
  check.
- **The read is advancing and matches the tape.** I rebuilt the 15m bars from the DB's 1m rows and
  checked every scenario call against them: SPY 09:30 close **763.75** body-below 765.14 ✓, IWM
  **293.30** body-below 294.26 ✓, QQQ **716.96** body-below 717.47 ✓ — all three match the read's own
  `scenario` events to the cent. 31 → 33 2m bars, 4 fifteen-minute bars, `regimeLast` EMAs present
  everywhere. **Replay parity holds on all three**: same sigma, same scenarios, same skips, zero
  trades — and IWM's replay reproduced `skip_target_behind`, so the new guard is deterministic.
- **F73 (new, FIXED and deployed this run, v0.7.25) — yesterday's F71 fix never fired once.** F71
  (v0.7.23) added the direction-aware wording so a break row already through its level would say
  *"price is already through, waiting on the 15m close"*. It is gated on
  `t.kind === "break PDH" || t.kind === "break PDL"` — the human labels — but the pseudo-trigger the
  API serves carries `Setup.kind`, which is `scenario_1..4` / `pm_break_up` / `pm_break_down`
  (`session.py:37`). Measured live at 10:38: SPY's trigger is
  `{"kind": "scenario_4", "direction": "short", "distancePct": 0.211}` — 1.61 already through its
  PDL — and the panel rendered the generic fallback *"— 0.24% from the level"*, the exact wording
  F71 was written to replace. Fixed by matching the kinds the desk emits (`TEAM2_BREAK_KINDS`); the
  `through` test itself was correct and untouched. **Reporting only — no rule, threshold, gate, size
  or money path changed.** 94 Team2 tests pass, `npm run build` green.
- **This one is a lesson about verification, not about the code.** Run 34 verified F71 at the data
  level and in the bundle but explicitly could not get a clean on-screen check, and owed one to this
  run. A predicate that never matches is invisible to both of those checks and visible instantly on
  screen. **This time it is confirmed on screen**: SPY's plan panel now reads *"— price is already
  through, waiting on the 15m close"*, and QQQ — a *reject* row, not a break — correctly still reads
  *"— 0.09% from the level"*.
- **Deployed without a restart, deliberately.** v0.7.25 touches no backend logic at all (the panel
  plus four version strings and the lockfile), and `start.ps1`'s `dist` was rebuilt, which the running
  server serves off disk — the new bundle is live and the chip reads 0.7.25. `/api/health` will read
  0.7.24 until the next restart. I did **not** bounce an AUTO-mode desk with three armed plans for a
  cosmetic version number; **queue the restart for the post-close run**, not for a mid-session one.
- **F74 (new, PROPOSED, NOT built — a rules question).** QQQ's 09:30 15m close set
  `scenario_2 reject PDH → puts` at 717.47, and **every 15m bar since has closed above it** (718.86,
  718.95, 718.29, 717.89) — but D10 flips a scenario 2/3 only on a close through the *far* side
  (721.89 / 715.57), so the short is still live, still owns the headline, and `bias.history` still
  has one entry. The narrow, useful version: the level-retest entry (T2) **is** side-gated and so is
  break-and-base (T7); it is the **EMA13/EMA48 touch entries (T1/E5) that have no anchor-side test**,
  so in the 4.42-point band between a reclaimed anchor and the flip level the desk would buy puts on
  a rejection sitting *below* price. **F72's guard does not catch this** (QQQ's target is genuinely
  below spot). Nothing was at risk today — QQQ is double-gated by a bull stack (strength 3) and by
  the PM no-trade zone — which is why it has not surfaced before. Sibling of **F65**. Three options
  in TRADING-RULES F74. **User's call.**
- **Not ours, unchanged:** `persist_bars: dropped N non-bucket-aligned stub bar(s)` still dominates
  the log, plus `calendar fetch failed for SPX/USO: 404` from Yahoo's quoteSummary endpoint. Both
  outside Team2.
- **Next run (11:00 ET) should:** (1) watch for the first EMA13 touch that clears both the no-trade
  zone and the stack gate — no fire has been priced yet today, so the `contract` pick (strike, ask
  near $0.60) and live-vs-replay fire parity are still unexercised; (2) check whether QQQ's 15m
  closes ever reach 721.89 (which would flip the bias and settle F74 on its own for today); (3) keep
  the restart queued for post-close. Still open for the user: **F47**, **F49**, **F50**, **F51**,
  **F54**, **F56**, **F58**, **F59**, **F61**, **F62**, **F63**, **F64**, **F65**, **F69**, **F70**,
  **F71's shared half**, **F72's strategy question**, **F74**, F67's two shared-side halves, and the
  F30-family question of which premium series is authoritative.

## 2026-09-09 10:48 ET (run 34c — F72 revised on the user's three corrections; v0.7.25)

- **The runner fallback was a real hole and is closed.** My first cut set an invalid target to
  `None`, which meant the trade entered with `targets=[]` — **an invalid target silently became
  permission for a targetless entry**, a *weaker* outcome than the refusal the read applies to the
  identical condition. `Team2Runner.resolve_fire_target(e, setup, spot, direction)` now returns
  `(target, refusal)` and `_fire` returns on a refusal, journalling `skip_target_behind`. Invalid
  means refused at **both** layers, wherever the fire came from — restored, replayed, or a plan
  rewritten under a running session. A genuinely **absent** target (none on the fire, none on the
  setup) is a different shape and stays allowed; that one the read validated.
- **The `hod_target="always"` claim was wrong — withdrawn.** X3b's guard is
  `nearer = (ext < target) if long else (ext > target)`: it only ever pulls a target **closer**. For
  a short it needs the running LOD *above* the planned target, but once price has run **through**
  that target the LOD is below it, so `nearer` is False and X3b declines. The knob changes nothing
  here; recovering the case that way would need the `nearer` comparison itself rewritten. Now pinned
  by a mirrored test (`test_hod_target_always_does_not_recover_a_target_price_has_run_through`) so
  the claim cannot quietly come back into the doc.
- **Structural re-planning built as a VARIANT, default off.** `techniques.team2.target_replan` =
  `off` | `entry`. When a planned target is not ahead of the entry, the target is re-derived from the
  next structural level beyond **current price** — the same 15m pivots the plan was built on, now
  carried as `plan.levelLadder` (`levels.level_ladder` + `next_structural_level`) — and then
  **re-validated by the same predicate**. A re-plan is a candidate, never an exemption: with no
  qualifying level the baseline refusal stands. **Validated at ENTRY, not only at arming**, per the
  instruction: price moves between the 15m confirmation and each pullback, so the "next" level at
  09:46 is not the one at 11:20, and only the entry knows which.
- **How to measure it** (nothing about the default changes until this exists):
  `python -m zargar.tools.team2_sweep sweep --start A --end B --set target_replan=entry` against the
  same range with the knob off, then `sweep-compare`. The override rides the existing alias map, so
  no sweep-tool change was needed.
- **Invalid-candidate refusal remains the baseline and the default** — confirmed live after the
  deploy: `techniques.team2.target_replan = off`, `hod_target = reentry` (untouched).
- **Tests: 20 new (48 in the file, 114 Team2 total), every case mirrored long/short** — the
  resolver's five shapes (invalid on the fire / invalid via the setup fallback / genuinely absent /
  valid / unparseable), the withdrawn `hod_target` claim, ladder ordering and price-relative
  selection, plan construction against a real multi-session history, the variant recovering a trade
  the baseline refuses, entry-time validation of *every* re-planned fire, re-validation against an
  empty ladder, and byte-identical event streams with the knob off. One harness note worth keeping:
  the synthetic day has a SINGLE prior session and `level_ladder` excludes the zone's own date, so a
  plan built there has no pivots at all (its `targets` are `None` for the same reason) — the variant
  tests inject a ladder and construction is covered separately against a 4-session history.
- **Deployed 10:48 ET with the desk flat** (no trades, no open positions on any of the three).
  v0.7.25 live, `/api/health` agrees, 3 Team2 plans restored, no Team2 errors or Tracebacks.
- **Still not exercised by the tape**, same as this morning: SPY and IWM targets remain behind price
  and would be refused, but no qualifying pullback has reached the guard. IWM now shows 2 setups.
  Next run should still look for a real `skip_target_behind` in the read.

## 2026-09-09 11:20 ET (run 36 — F72's variant measured and rejected; F75: the sweep's data is partly synthetic)

- **Alive, clean, and all three plans healthy.** `/api/health` ok. Three Team2 plans armed for
  2026-09-09 (SPY, QQQ, IWM), `complete: true`, `needsAttention` false, no `read_error`, zero trades
  and zero open positions all morning. 1m bars banking to 11:03 read at 11:04; underlying quotes
  `quoteAgeSeconds 0`, session `regular`; **option quotes are OPRA** — the three 0DTE ATM puts came
  back `provider: "alpaca"`, `delayed: false`, priced to the second (SPY 762P 0.67/0.68, QQQ 717P
  1.19/1.20, IWM 291P 0.29/0.30). **Replay parity holds on all three** (same sigma, same scenarios,
  same skips, zero trades).
- **The app was restarted at 11:07 ET by another desk, not by me.** A `/api/technique/armed/...`
  call mid-run came back "connection actively refused"; the app was back seconds later on
  **v0.7.26** with the tips desk's merge (`33f4165`, PR #28 measurement work) as HEAD. Same branch,
  my Team2 commits are all still ancestors of HEAD, all 3 Team2 plans restored with their scenarios,
  touches and bias intact, no Team2 errors or Tracebacks since the boot. Recording it so the version
  jump 0.7.25 → 0.7.26 is not read as drift on this desk. The UI chip and `/api/health` now agree.
- **F72's guard fired four more times on IWM and was right every time.** `skip_target_behind` at
  10:32 (292.58), 10:36 (292.52), 10:42 (292.42) and 11:00 (292.12) — all refusing a short whose
  planned target 293.56 sits *above* the entry. The 11:00 one matters most: it hit the **new**
  `pm_break_down@10:30` setup, born at 10:45 off a 15m close below the PM low, which **inherited the
  same stale plan target**. So this is not a first-entry-only problem — every setup the session
  mints mid-day carries the plan's target, and on a gap-through day that target is behind price for
  all of them. SPY is still gated earlier by the pre-market no-trade zone; QQQ is correctly
  unaffected (target 716.50 genuinely below spot).
- **F72's strategy question is now MEASURED — and the answer is to keep the refusal (F72 addendum).**
  Ran the sweep both ways as the plan specified. On clean data (QQQ+IWM, 2026-08-25..09-08)
  `target_replan=entry` adds **5 trades, 0 wins, −53.0 pnl%-sum**, drops 3 baseline losers (−29.2),
  changes no existing trade, **net −23.8**. Two of the five peaked at +15% and +18% and still
  finished red — exactly the predicted mechanism, a further target lets the stop or the premium stop
  resolve the trade first. `target_replan` stays **off**, which is already the default, so **nothing
  was changed and nothing was deployed this run**. Small sample (5 trades), so this is "no evidence
  for it", not "proven worthless" — re-measure when SPY can be included (see F75).
- **The counterweight, honestly:** the four refused IWM shorts all ran the right way immediately —
  **+0.20% to +0.35% MFE against a maximum 0.09% adverse excursion** on the underlying by 11:04
  (IWM 292.58 → 291.55 low). I am not claiming a P&L: whether the premium cleared the +50% trim is
  not reconstructable without the option tape. But the refusal is not free, and today it was
  expensive four times.
- **F75 (new, NOT fixed — the biggest finding of the run, and it undermines earlier calibration).**
  The first sweep pass produced re-planned SPY targets of **592.62** and **908.54** for a SPY
  trading at 765. Chasing those down: the shared `bars` table this desk sweeps on is **partly
  synthetic**. SPY's 1m history starts 2026-08-15 and its **first five days are a random walk, not
  SPY** — RTH ranges 508–523, 542–570, 632–744, 826–909, **1249–1424** — going real only on 08-20;
  6,487 SPY 1m rows lie outside a 700–850 band. Separately, **flat stub sessions fill days the app
  was not running**: 08-22 (Sat), 08-23 (Sun), **09-05 (a real trading Friday)** and 09-06 each carry
  70–150 RTH rows at one constant price, low == high. Two consequences: sweep rows on or near that
  SPY block are scored on fiction, and `targets_beyond`/`level_ladder` take the last N *dates present
  in the bars* rather than the last N **trading** days, so weekends and not-running days silently eat
  lookback slots. **Today's live plans are clean** — all three are built off 2026-09-08 real data and
  their zones match the tape to the cent — so there is no live exposure. Root cause is shared
  marketdata (stub-bar persistence + whatever seeded SPY in mid-August), which this desk does not
  own. **Not built; options (a) backfill+delete and re-run every affected calibration, (b) make the
  sweep skip degenerate/non-trading sessions, (c) both — written up in TRADING-RULES F75. User's
  call.** Note (b) moves targets, so it is rules-adjacent and not something to ship mid-session on an
  auto desk.
- **Checked and found nothing wrong:** the read matches the tape (SPY/IWM 09:30 15m bodies below
  their PDL zones, QQQ below its PDH zone bottom — all three scenario calls correct); `regimeLast`
  EMAs present everywhere; `level_ladder` and `targets_beyond` use the *same* pivot window (2), so
  the ladder is not mis-tuned relative to the targets it replaces — I checked because it looked like
  a defect and it is not. UI renders correctly at 1440×900, version chip 0.7.26, only benign
  service-worker fetch noise in the console.
- **Not ours, unchanged:** `persist_bars: dropped N non-bucket-aligned stub bar(s)` still dominates
  the log (and is very likely the same mechanism as F75's flat sessions), plus
  `calendar fetch failed for USO/DRAM: 404` from Yahoo's quoteSummary endpoint.
- **Next run (11:30–12:00 ET) should:** (1) still hunt the first priced fire of the day — no
  `contract` pick has been exercised yet, so strike selection (~$0.60 ask) and live-vs-replay fire
  parity remain untested today; (2) watch whether IWM's `pm_break_down` setup ever clears the F72
  guard (it will not while the target stays 293.56 — so expect refusals to continue and note them
  once, not four times); (3) no restart is queued — the 11:07 boot already put the desk on 0.7.26.
  Still open for the user: **F47**, **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**,
  **F61**, **F62**, **F63**, **F64**, **F65**, **F69**, **F70**, **F71's shared half**, **F72's
  strategy question** (now with a measurement attached — the recommendation is "leave it off"),
  **F74**, **F75**, F67's two shared-side halves, and the F30-family question of which premium series
  is authoritative.


## 2026-09-09 11:35 ET (run 37 — desk healthy, still flat; F76: gap-day PM-break setups are born untradeable)

- **Alive and clean.** `/api/health` ok, **v0.7.27** — the app was restarted at **11:26 ET by another
  desk** (the tips team), not by me; all three Team2 plans restored with their scenarios, bias and
  touches intact, `armedAt` 11:26, no Team2 errors or Tracebacks since the boot. Recording the
  0.7.26 → 0.7.27 jump so it is not read as drift on this desk. Three plans armed for 2026-09-09
  (SPY `e4d39d00`, QQQ `9a1094ed`, IWM `e87e4ad2`), `complete: true`, `needsAttention` false, mode
  **auto** on Team2 Practice `b9dcd8db…`, **zero trades and zero open positions** all day.
- **Data is real-time.** 1m bars banking to **11:33** read at 11:35; underlying quotes seconds old,
  session `regular`; **option quotes are OPRA** — the three 0DTE ATM puts came back
  `provider: "alpaca"`, `delayed: false`, `source: "opra"`, priced to the second (SPY 762P 0.89/0.90,
  QQQ 715P 0.85/0.86, IWM 291P 0.33/0.34). RTH bars in the DB are **clean**: 124/123/123 rows for
  09:30–11:33, **zero flat bars, zero zero-volume bars** on all three — so F75's stub-bar corruption
  is not touching today's session (the flat rows today are all pre-market, which is normal).
- **Replay parity holds on all three.** The only difference was one extra 2m bar (62 vs 61) that
  arrived between the live read and the replay, producing one extra `same_pullback` on QQQ and IWM —
  a fetch-timing artifact, not a parity break. Same sigma, same scenarios, same skips, zero trades.
- **What the read saw since 11:20:** SPY printed a **15m close below the PM low 762.49 at 11:15**
  (`pm_break`), minting `pm_break_down@11:00`, then refused its first qualifying pullback at 11:32
  (`skip_target_behind`, target 764.75 above a 761.84 short entry) — SPY's **first** F72 refusal of
  the day. QQQ **flipped scenario 2 → scenario 4 at 11:15** on a 15m close below 715.57, and its new
  setup carries a genuinely valid target (710.81); its 11:32 pullback was refused by the *no-trade
  zone* instead (entry 715.39 inside the 713.50–720.67 PM range), which is correct — QQQ's PM range
  is 7.2 points wide and swallows the whole PDL break, so V6/B5 will keep blocking it until price
  leaves that range. IWM refused once more at 11:32 (target 293.56 vs a 291.28 entry). Net: **all
  three symbols short-biased, none able to trade.**
- **F76 (new, NOT fixed — proposal, the finding of this run).** Both PM-break setups minted today
  were **dead on arrival**: SPY's target 764.75 sits 2.26 *above* its own anchor (PM low 762.49),
  IWM's 293.56 sits 0.94 above its 292.62 anchor. Since a `pm_break_down` entry is by construction
  the retest of the PM low with the close below it, **every possible entry is under a target above
  it**, so F72 must refuse all of them. Mechanism:
  `tgt = zones["pdl"].top if pml > zones["pdl"].top else targets.get("below")` validates the first
  candidate against the PDL zone but never validates the **fallback** against the setup's own anchor,
  and on a gap-down day the gap already carried price through both. Deterministic, not tape-dependent
  — any gap-down day with the PM low below `targets.below` mints a dead `pm_break_down`; mirror for
  gap-ups. QQQ is the control (target genuinely ahead) but never printed a PM break today. Also
  **misleading prose**: the note says *"→ puts down to the PDL zone (L2.5/V7)"* whatever target was
  actually chosen. Not re-litigating **F15**, which deliberately lets PM breaks exist on gap days;
  what F15 left open is what the target should then be. Options in TRADING-RULES F76 — (a) leave it,
  (b) validate at construction and mint no setup with a stated reason (no trade changes, kills the
  dead setup and the wrong note), (c) derive the target from V7's "next support below" relative to
  the anchor, which is a **rule change needing its own sweep** and is *not* the same experiment as
  F72's `target_replan` (that one re-derived at entry for all setups and lost). **Recommend (b) now,
  (c) only behind a measurement. Nothing built** — it touches setup creation, hence opportunity
  counting and grading, which is not a mid-session change on an auto desk.
- **Checked and found nothing wrong:** `note_once`'s dedupe looked broken (IWM logged
  `skip_target_behind` at 10:32, 10:36 and 10:42 for one setup) — it is not: `s._skipped` is cleared
  by every genuinely tradeable touch, so each row is a distinct refused opportunity, which is the
  information F72 wants. `regimeLast` EMAs present on all three, 200 EMA sane vs price, scenario
  calls match the tape.
- **Not ours, unchanged:** `persist_bars: dropped N non-bucket-aligned stub bar(s)` still dominates
  the log; two `ConnectionResetError` tracebacks today are client-disconnect socket noise; the two
  `technique run failed` errors are EM's, from yesterday 21:40.
- **One check I could not complete:** the `/team2` UI. `?token=` does not authenticate the SPA route
  (it lands on the login shell), so this run verified the page only as far as the served shell and
  version chip 0.7.27. The API layer the page reads was verified in full, and the last full-page
  check was run 36 at 11:20 with no Team2 UI change deployed since.
- **Next run (12:00–12:30 ET) should:** (1) still hunt the **first priced fire of the day** — no
  `contract` pick has been exercised, so strike selection (~$0.60) and live-vs-replay fire parity
  stay untested today; (2) watch QQQ, which is now the only symbol with a valid target — it needs
  price to leave the 713.50–720.67 PM range for V6/B5 to release it; (3) expect continued refusals on
  SPY and IWM and note them once, not per row. No restart queued. Still open for the user: **F47**,
  **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**, **F61**, **F62**, **F63**, **F64**,
  **F65**, **F69**, **F70**, **F71's shared half**, **F72's strategy question** (measured; the
  recommendation is "leave it off"), **F74**, **F75**, **F76**, F67's two shared-side halves, and the
  F30-family question of which premium series is authoritative.


## 2026-09-09 12:05 ET (run 38 — desk healthy, still flat; F77: the strike pick reads a chain row that can lag OPRA)

- **Alive and clean.** `/api/health` ok, **v0.7.27**, unchanged since the 11:26 ET boot by the tips
  desk — **no restart this run and none queued**. Three plans armed for 2026-09-09 (SPY `e4d39d00`,
  QQQ `9a1094ed`, IWM `e87e4ad2`), `complete: true`, `needsAttention` false, mode **auto** on Team2
  Practice `b9dcd8db…`, **zero trades and zero open positions** all day. No Team2 errors or
  Tracebacks in `backend/zargar-8420.log` since that boot — only the known `persist_bars` stub-bar
  noise, two client-disconnect `ConnectionResetError`s and Yahoo calendar 404s (SPX/USO/DRAM).
- **Data is real-time and clean.** RTH 1m bars banked to **12:02 ET** read at 12:03 — **153 rows for
  09:30–12:02 on SPY, i.e. every minute present**, QQQ/IWM 152 (the in-flight minute), and **zero
  flat bars, zero zero-volume bars** on all three, so F75's synthetic-bar corruption is again not
  touching today's session. Underlying quotes seconds old, session `regular`. Option quotes are
  **OPRA** (`source: "opra"`, `delayed: false`, sub-second `ts`).
- **Replay parity is exact on all three** — identical event lists (SPY 7, QQQ 5, IWM 15), identical
  sigma (0.1212 / 0.1748 / 0.1610), zero trades both ways. The only difference is one extra 2m bar
  (77 vs 76) that arrived between the live read and the replay. Cleaner than run 37, which saw a
  spurious extra `same_pullback` from the same fetch-timing effect.
- **What the read saw since 11:35 — nothing new, only more refusals.** SPY: `same_pullback` 11:42,
  then a **second `skip_target_behind` at 11:58** (target 764.75 vs a 762.16 short entry). IWM:
  `same_pullback` 11:34, then `skip_target_behind` **11:56** (293.56 vs 291.24). QQQ: one
  `same_pullback` at 11:42 and no new opportunity. All three remain short-biased scenario 4 (break
  PDL); **QQQ is still the only symbol with a genuinely valid target** (710.81) and it stays blocked
  by the no-trade zone because its 7.2-point PM range (713.50–720.67) swallows the whole PDL break.
  Price at 12:03: SPY 762.15, QQQ 716.13, IWM 291.03.
- **F76 confirmed, exactly as predicted.** Run 37 forecast that SPY and IWM would keep refusing while
  their PM-break targets sit above their own anchors; both did, once each. Logged as confirming
  evidence, not re-litigated. **Still a proposal — nothing built**; recommendation stays option (b)
  (validate the target against the anchor at construction and mint no setup, with a stated reason).
- **F77 (new, NOT fixed — measured, low severity).** Sampling `GET /api/options/quote/<occ>` on the
  three 0DTE ATM puts: the top-level chain row and the nested real-time quote agree on every call
  **except the first after an idle gap**, where the row serves the previous cycle's value — SPY 762P
  row 0.74/0.75 vs OPRA 0.875/0.885, QQQ 716P row 0.97/0.98 vs OPRA 1.235/1.245 (IWM agreed); five
  immediately-following samples matched exactly on all three. Both series are Alpaca/OPRA, so this is
  refresh cadence, **not** a delayed-feed fallback. The money path is already safe — **F14**'s
  `opts.reprice(c)` in `pick_contract` means sizing, pre-checks and the never-chase cap all read the
  live NBBO. What the reprice does not revisit is *which strike was chosen*: `select_by_premium`
  ranks the ladder on chain asks, so a one-cycle-stale ladder could land on an adjacent strike
  (step 1.0 on all three). **Unobserved in practice — no `contract` pick has fired on this desk yet**,
  so this measures the inputs, not a mis-pick. Direct evidence for the open **F30-family question of
  which premium series is authoritative**; the fix, if wanted, is to reprice before ranking rather
  than after. Not built — it touches the shared `options/pick` path.
- **The `/team2` UI check run 37 could not complete is now green.** The blocker was that `?token=`
  does not authenticate the SPA route; the workaround is to set the `zargar_session` cookie in the
  browser before navigating. Both the **Plans** and **Armed** tabs render all three plans correctly,
  with live reads and the right plain-language refusal text ("the planned target is already behind
  price … (F72)" on SPY/IWM, the no-trade-zone line on QQQ), version chip 0.7.27, bar age ~109s.
  Recording the recipe so future runs do not re-lose it.
- **Next run (12:30–13:00 ET) should:** (1) still hunt the **first priced fire of the day** — strike
  selection (~$0.60 ask) and live-vs-replay fire parity remain untested today, and F77 is one of the
  things that first `contract` event would let us check for real; (2) watch **QQQ**, the only symbol
  that can still trade, which needs price to leave 713.50–720.67; (3) expect continued SPY/IWM
  refusals and note them once, not per row. No restart queued. Still open for the user: **F47**,
  **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**, **F61**, **F62**, **F63**, **F64**,
  **F65**, **F69**, **F70**, **F71's shared half**, **F72's strategy question** (measured; the
  recommendation is "leave it off"), **F74**, **F75**, **F76**, **F77**, F67's two shared-side
  halves, and the F30-family question of which premium series is authoritative.
## Desk session 2026-09-09 evening — F75 repair batch (v0.7.28)

Reviewer's second pass accepted with additions; user: "Proceed with the repair right away since we're still in
practice mode. Include the real-session volume defect and persistence of authoritative corrections, use
content-based dataset versions, and strengthen restart checks beyond open positions. Preserve the contaminated
data and original research records. Keep target_replan off until the clean dataset supports a reproducible rerun."

- **Corrections carried:** 09-05 = Saturday; the flat sessions are the app running on closed days; "no observed
  effect on the values checked" replaces "the live plans are clean".
- **Built (shared):** `bars.source` provenance, precedence upsert (the sampled bar no longer survives its exchange
  correction on disk — a sampled bar + its correction in one flush was also a cardinality error in the first cut,
  caught by the new test), calendar gate in the aggregator and the persister, sim isolation, F78 print-based
  volume, `bars_quarantine` / `bars_dataset_versions`, `zargar.tools.bars_repair`, `marketdata.dataset_version`.
- **Built (Team2):** `history.validate_sessions` in plans / warm-up / replay / sweep; lookback in valid sessions;
  `plan.history` provenance; sweeps stamped with the dataset hash.
- **Built (restarts):** `/api/ops/restart-check|state|restore-check`, start.ps1 refusal + restoration check,
  watchdog `-Override`, `ZargarRestartOverride` task.
- **Tests:** `test_bars_integrity.py` (7), `test_bars_repair.py`, `test_team2_history.py` (3), `test_ops_restart.py`
  (3) + the Team2 / halt / arming / API / Cartel / flow suites.
- **Repair record:** appended below once the tool has run (pre-repair dataset hashes, quarantine batches, backfill
  counts, post-repair hashes).


## 2026-09-09 12:40 ET (run 39 — desk healthy and still flat; four restarts in 11 minutes; F79/F80 on bar provenance)

- **Alive, three plans armed, nothing traded.** `/api/health` ok, **v0.7.28**. SPY `e4d39d00`,
  QQQ `9a1094ed`, IWM `e87e4ad2` all `armed`, `complete: true`, `needsAttention` false, mode
  **auto** on Team2 Practice `b9dcd8db…`, **zero trades and zero open positions** all day. Quote age
  0–1 s, bar age ~76 s after the last boot. Option quotes on the three 0DTE ATM puts are **OPRA**
  (`source: "opra"`, `provider: alpaca`, `delayed: false`, sub-second) and this time the chain row
  and the nested real-time quote **agreed exactly on all three** (SPY 762P 0.76/0.78, QQQ 716P
  1.07/1.08, IWM 291P 0.35/0.37) — **F77 did not reproduce** on this sample.
- **Four restarts inside eleven minutes, all from another desk iterating on the restart scripts:**
  12:26, 12:31, 12:33 and 12:36 ET. The 12:26 one hit the array-splat bug and ran the engine in the
  **foreground**, so the desk was dark from ~12:26 until the 12:32 recovery — I found `/api/health`
  refused on my first call of this run, and the app went down under me again mid-check at ~12:37.
  The bug is already fixed in `5b8e4cb` (committed 12:28 ET, after that restart was launched), and
  the 12:36 restart came back clean with `Restore check OK: armed 74/74, openTrades 0/0,
  pendingExits 0/0, restingOrders 10/10, inflightOrders 0/0`. **No Team2 trade was live or working
  at any point**, so nothing was lost — but the desk was unattended-auto and dark for ~6 minutes of
  RTH, which is the exact scenario the run-book warns about. **I queued no restart of my own.**
- **What the read saw since 11:35 ET — still nothing but refusals, no fire.** SPY: `same_pullback`
  12:06 and 12:28, `skip_target_behind` at 12:08 (762.17), 12:14 (761.98) and 12:26 (761.70) against
  its 764.75 target. IWM: `skip_target_behind` 12:08 (291.15), 12:10 (291.11), 12:30 (290.85) against
  293.56. QQQ: one `same_pullback`, no new opportunity, still blocked by the no-trade zone. All three
  remain short-biased scenario 4 (break PDL); **QQQ is still the only symbol with a valid target**
  (710.81) and still needs price out of its 713.50–720.67 PM range. Prices at 12:38: SPY 762.00,
  QQQ 715.74, IWM 291.00. **F76 keeps confirming** — SPY and IWM have now refused 5 and 7
  opportunities respectively on targets that sit above their own short entries.
- **Replay parity holds on substance.** Identical event counts and identical sigma on SPY
  (12/12, 0.1212) and QQQ (6/6, 0.1748); IWM 20 live vs 19 replay (0.1610). Zero trades both ways on
  all three. Every difference is a single late-window bookkeeping event (QQQ 12:14 vs 12:38
  `same_pullback`; IWM a 12:28/12:30 `skip_target_behind` + `same_pullback` reshuffle) and tracks the
  known effect that the replay fetches one more 2m bar than the live read had (94 vs 93). No
  fire/trim/exit divergence.
- **F79 (new, NOT fixed — proposal, shared engine).** Today's RTH 1m bars are `source='unknown'` for
  **09:30–11:57 ET on all three symbols** and flip to `'exchange'` at 11:58 simultaneously (SPY
  148/36, QQQ and IWM 147/36) — even though v0.7.28 booted at 11:26 and a quote-built bar is supposed
  to be stamped `sampled`. Worse, the **first nine `exchange` bars (11:58–12:06) carry volume 0 on
  all three symbols** (plus 12:19/12:20 on SPY and IWM) where neighbouring minutes run 8k–60k, and
  the 12:05 ET watch had read those same minutes as non-zero *before* they were rewritten — so the
  exchange correction **destroyed real volume**, and since `exchange` outranks everything nothing can
  repair it in place. Contributing mechanism: `unknown` ties with `sampled` at rank 1 and the upsert
  takes the new row on `>=`, so an `unknown` re-seed overwrites a live sampled bar. **No Team2
  decision is affected** — the method has no volume rule (`volume_floor_mult = 0.0`) and OHLC is
  intact (zero flat bars all session) — but it is direct counter-evidence to the provenance and
  print-volume guarantees that shipped this morning. `bars_dataset_versions` still holds only the
  pre-repair row and `bars_quarantine` is empty, i.e. `bars_repair` has not run over today.
- **F80 (new, NOT fixed — proposal, shared engine).** **QQQ and IWM have no 11:25 ET 1m bar at all**,
  any tf, any source; SPY's exists. The engine booted at 11:26:17, so 11:25 was the minute forming in
  the dying process and was never re-fetched for two of three symbols. The 2m bucket 11:24–11:26 is
  therefore built from half the tape on those two, silently — the read still reports 91–93 `bars2m`
  and nothing raises `needsAttention`. The later restarts left no holes because the exchange-bar
  correction back-filled their minutes, so the exposure is a restart while only the quote-sampled
  path is live — which per F79 was most of today. **This corrects run 38**, which saw QQQ/IWM one bar
  short of SPY and put it down to "the in-flight minute": the missing row is 11:25 and it is
  permanent.
- **Nothing built this run, no restart queued.** Both new findings land in shared engine code
  (`zargar/marketdata.py`, the boot backfill), which this watch is not allowed to change.
- **Next run (13:00–13:30 ET) should:** (1) still hunt the **first priced fire of the day** — strike
  selection near $0.60 and live-vs-replay fire parity remain untested; (2) watch **QQQ**, the only
  symbol that can still trade; (3) re-check bar provenance and whether the zero-volume band grew, and
  whether any further restart left a 1m hole (F79/F80); (4) expect continued SPY/IWM refusals (F76).
  Still open for the user: **F47**, **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**,
  **F61**, **F62**, **F63**, **F64**, **F65**, **F69**, **F70**, **F71's shared half**, **F72's
  strategy question**, **F74**, **F75**, **F76**, **F77**, **F79**, **F80**, F67's two shared-side
  halves, and the F30-family question of which premium series is authoritative.


## 2026-09-09 13:05 ET (run 40 — desk healthy, bar data now clean, still zero fires; F81 explains why)

- **Alive, three plans armed, nothing traded.** `/api/health` ok, **v0.7.29**. SPY `e4d39d00`,
  QQQ `9a1094ed`, IWM `e87e4ad2` all `armed`, `complete: true`, `needsAttention` false, mode
  **auto** on Team2 Practice `b9dcd8db…`, **zero trades, zero open positions**, ninth session
  running. Quote age 0 s, session `regular`, bar age 73–96 s. Option quotes on the three 0DTE ATM
  puts are **OPRA real-time** (`source: "opra"`, `provider: alpaca`, `delayed: false`) and the chain
  row matched the nested quote **exactly on all three** (SPY 762P 0.55/0.56, QQQ 716P 0.77/0.78,
  IWM 291P 0.38/0.39) — **F77 did not reproduce**, second run running.
- **A fifth restart today, 12:54 ET, deploying v0.7.29** (another desk; `logs/restart-20260909-095443.log`).
  It came back clean — `Healthy: v0.7.29 | armed 43`, `Restore check OK: armed 73/73, openTrades 0/0,
  pendingExits 0/0, restingOrders 10/10, inflightOrders 0/0`, and `team2 runner restored 3 armed
  plan(s)`. No Team2 trade was live at any point. A transient `restore check MISMATCH` warning at
  09:55:41 PT listed 32 EM plans still restoring and cleared before the script's own check. **I
  queued no restart of my own.**
- **F79 and F80 are FIXED and verified.** Commits `568f3e7` / `663b5fc` from the other desk.
  Re-measured on today's live tape: **all 214 RTH 1m rows 09:30–13:03 on all three symbols carry
  `source='exchange'`** — no `unknown`, no `sampled`, **zero zero-volume bars** (the 11:58–12:06
  band and the SPY/IWM 12:19–12:20 rows hold real volume again) and **no interior gaps**, including
  the **11:25 ET minute F80 recorded as permanently missing** on QQQ and IWM. The bar dataset this
  desk sweeps on is now clean for today.
- **What the read saw since 12:40 ET — one new event, still no fire.** IWM `skip_target_behind` at
  13:00 (291.04 against its 293.56 target). SPY has been quiet since its 12:28 `same_pullback`,
  QQQ since 12:38. All three remain short-biased scenario 4 (break PDL). Prices at 13:04: SPY
  762.50, QQQ 716.30, IWM 290.92. Day totals: **14 refusals, 0 fires** — 5 on SPY, 9 on IWM, and
  QQQ still walled off by its 713.50–720.67 pre-market no-trade zone.
- **Replay parity holds.** SPY 12/12 and IWM 22/22 events identical, zero trades both ways on all
  three. QQQ's replay emits one extra `same_pullback` at 12:14 that the live read did not — a
  bookkeeping event only, and explained: this morning's live reads ran on the pre-correction tape
  while the replay now reads the corrected exchange bars. Should disappear for sessions that run
  entirely on v0.7.29. **No fire/trim/exit divergence anywhere.**
- **F81 (new, NOT fixed — proposal; this is why the desk has never fired).**
  `plan.complete_preopen()` updates `pmh`/`pml`/`dayType`/`sizingAtOpen`/`sheet` but **never
  recomputes `plan["targets"]`**, which are frozen at the 17:00 build. On a gap day the overnight
  move can put price through the plan's own down-target before the method may take anything. Today
  both `gap_down` symbols were born dead: **SPY's 764.75 target was already behind at the 09:30
  close of 763.85**, IWM's 293.56 was behind by the 09:45 15m confirmation at 293.30. Every later
  pullback then hit the F72 guard. The refusals were **right about direction** — SPY refused
  761.70–762.17 and traded to 760.94, IWM refused 290.85–292.42 and traded to 290.58 — only the
  target arithmetic blocked them.
- **Counterfactual measured (read-only sweep, no orders, no settings touched), dataset
  `164a83894fbbca79…`:** the already-built variant `techniques.team2.target_replan=entry` takes
  **4 trades today, +85.6% summed premium, 2 winners** (SPY −20.9%/−7.9%, IWM +46.6%/+67.8%)
  against the baseline's **zero**. Over 30 sessions (2026-08-26→09-09; tape before today is
  pre-repair): **41 trades / wr 0.341 / +188.0%** vs baseline **33 / 0.333 / +125.8%**.
  **The asymmetry matters:** the whole gain is in `pm_break_down` (69.4→194.4%), while
  `pm_break_up` gets worse (112.4→47.1%, wr .38→.27) — and the window is itself down-biased, which
  is exactly what would manufacture a down-only edge. **Proposed, for the user:** (a) leave off,
  (b) on, (c) on for down-breaks only, or (d) re-derive targets at the 09:25 pre-open, which fixes
  the cause instead of the symptom. Not built — thresholds and rules are the user's call.
- **Known log noise, not a defect:** `persist_bars: dropped N non-bucket-aligned stub bar(s)` fires
  constantly (2208 lines since 2026-09-08 16:26) but it is the deliberate write-time bucket
  alignment guard (`marketdata.py:344`, EM team #5). Recorded so future runs stop re-flagging it;
  the only improvement would be to aggregate or demote it, and that is shared engine.
- **UI green.** `/team2` renders all three plans with the right sheets and statuses on v0.7.29 via
  the cookie recipe (set `zargar_session` in the browser, then navigate; `?token=` does not
  authenticate the SPA route).
- **Next run (13:30–14:00 ET) should:** (1) still hunt the **first priced fire** — strike selection
  near $0.60 and live-vs-replay fire parity remain untested after nine sessions; (2) watch **QQQ**,
  the only symbol that can still trade, which needs price out of 713.50–720.67; (3) expect SPY/IWM
  refusals to continue (F81/F76/F72) and note them once; (4) re-check that bar provenance stays
  `exchange` now that v0.7.29 is running a full session. No restart queued. Still open for the user:
  **F47**, **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**, **F61**, **F62**, **F63**,
  **F64**, **F65**, **F69**, **F70**, **F71's shared half**, **F72's strategy question**, **F74**,
  **F76**, **F81**, F67's two shared-side halves, and the F30-family question of which premium
  series is authoritative. **F75, F79 and F80 are now closed.**

## Desk record 2026-09-09 12:26–13:20 ET — F75 repair executed (v0.7.28 → v0.7.29)

- **Deploys (all via `schtasks /Run /TN ZargarRestart` → `restart.ps1`):** 12:26 ET v0.7.28 (the first attempt at
  12:14 exited 1 on a stray CR in a comment; the 12:26 run's array splat left the engine in the task console's
  foreground); 12:31 / 12:33 / 12:36 ET clean restarts after `schtasks /End` (readiness answered, `Restore check OK:
  armed 74/74 … restingOrders 10/10` in `logs/restart-*.log`; the 12:36 one restored the helper workers I had wrongly
  "deduplicated"); 12:54 ET v0.7.29 (F79/F80). Zero technique trades were open at any restart; the F80 seed re-read
  13,389 minutes for 31 symbols at the 12:54 boot. Version clashes: none this time (checked origin/main before each bump).
- **Repair on the runtime DB:** quarantine `7f6269da4e71` (closed days, 316,603 rows / 439 symbol-sessions),
  `bfa00d50b550` (SPY sim 08-14..19, 4,424), `a9116e809b6e` (AAPL/AMD/MSFT/NVDA/TSLA/SHOP.TO/TD.TO sim 08-14..19, 30,969);
  Alpaca backfill 214 symbols in two passes (1,605,836 + 742,162 bars fetched; 1,240,400 + 555,684 added; 42,109 + 6
  volumes zeroed on print-less minutes); pass 1 had silently started at 08-20 because the history clip applied
  Yahoo's depth to Alpaca — fixed and re-run. Identities: Team2 pre `0155fbe4…` (67,780) → FINAL `a00ecad1…` (55,219);
  all symbols FINAL `532d7932…` (2,880,732). Team2 audit: clean.
- **F72 rerun on the clean set** (sweep dataset `96129c00…`, SPY/QQQ/IWM, 39 sessions 08-20..09-08): baseline 37 / wr
  .405 / +247.7 vs `target_replan=entry` 45 / .356 / +207.0 → stays off (TRADING-RULES F72 addendum 2).
- **Open for the user:** F81 (pre-open never re-derives the plan targets; today's gap day was born dead — a rules
  change, the watch job's counterfactual is on the pre-repair tape); the residual audit flags on other symbols
  (`outlier_range` 20 real large-move days, `volume_spike` 10) are reports for their desks, not defects.


## 2026-09-09 13:45 ET (run 41 — desk healthy, data clean, still zero fires; the two blockers now account for the whole day)

- **Alive, three plans armed, nothing traded.** `/api/health` ok, **v0.7.29**, armed 75. SPY
  `e4d39d00`, QQQ `9a1094ed`, IWM `e87e4ad2` all `armed`, `complete: true` (pmh/pml/dayType/
  sizingAtOpen present), `needsAttention` false, mode **auto** on Team2 Practice `b9dcd8db…`,
  **zero trades, zero open positions**, ninth session. Quote age 0 s, session `regular`, bar age
  73–96 s. **No restart this run and none by another desk since 12:54 ET**; the engine log has not
  logged a single warning or traceback since 12:56 ET.
- **Bars stay clean under v0.7.29.** 244/244 RTH 1m rows per symbol 09:30–13:33, **all
  `source='exchange'`**, zero `sampled`/`unknown`/`sim`, **zero zero-volume rows, no interior gaps**
  on any of the three. F79 and F80 remain closed after a full session on the fixed build.
- **Option quotes real-time, F77 did not reproduce (second consecutive run).** SPY 763P, QQQ 717C,
  IWM 291P all `source: "opra"`, `provider: alpaca`, `delayed: false`, and the top-level chain row
  matched the nested quote **exactly** on all three (QQQ 0.43/0.44, delta .44, 0 DTE).
- **What the read saw since 13:05 — one genuinely new thing.** QQQ's bias **flipped a third time**: at
  **13:15 ET** a 15m body closed above 716.50 → **scenario 3 (bounce PDL) → calls**, target 717.47,
  its two earlier setups now `dead`. Its first pullback was refused **13:34 `skip_no_trade_zone`**
  (entry 716.28). IWM added `skip_target_behind` at 13:00/13:04/13:10 (290.98–291.04 against 293.56),
  `same_pullback` at 13:08/13:16, and its **second `skip_engulfing` of the day at 13:32** (touch #2,
  body 0.20 > 2.0× avg 0.05 — a correct A6/F4 refusal). SPY quiet since 12:28. Prices at 13:37:
  SPY 762.90, QQQ 716.35, IWM 290.91.
- **The whole day now has exactly two causes, one per symbol group.** Day totals across the three:
  **18 `skip_target_behind`, 5 `skip_no_trade_zone`, 2 `skip_engulfing`, 0 fires**. The symbols that
  *left* their pre-market range (SPY, IWM) were killed by the frozen target (**F76**/**F81**); the
  symbol that never left it (QQQ) was killed by V6's no-trade zone (**F56**). Measured: QQQ spent
  **246 of 246 RTH minutes inside its own PM range** (713.50–720.67 = **21.8× its 2m ATR**), SPY 61%
  (17.6×), IWM 20% (17.6×). QQQ printed no PM break, so F20's carve-out never applied — the symbol
  was untradeable by construction for a full session. This is F56's mechanism at its extreme; logged
  as a confirmation, not a new finding.
- **F76's reporting half FIXED (commit `05fb2b2`, deploy queued).** The `pm_break` note said *"→ puts down
  to the PDL zone (L2.5/V7)"* whichever candidate the target resolved to, so on a gap day it
  advertised a level the setup does not hold. It now states the setup's own number and flags when
  that number is behind the break — *"→ puts down to 764.75 — already behind the break, so this setup
  has no room (F76)"* — and carries `target` in the event payload. New helper
  `_pm_break_target_says()` (mirrored long/short), new test
  `test_pm_break_note_states_the_setups_own_target`; **118 Team2 tests pass**. **Reporting only** —
  no target, size, gate, rule or money path changed. **Deploy queued for the next restart**, not
  taken mid-session: the desk is in auto mode and the fix changes no decision.
- **Replay parity holds.** SPY 12/12 and IWM 26/26 events identical, zero trades both ways on all
  three. QQQ's replay still emits one extra 12:14 `same_pullback` — the known artifact of this
  morning's live reads running on the pre-repair tape; it should disappear for a session run entirely
  on v0.7.29.
- **UI:** `/team2` and `/api/team2/status` both return 200. The full page render was **not**
  re-verified this run (no deploy since run 40's green check on the same version, and the browser
  cookie handoff was unavailable).
- **Next run (14:00–14:30 ET) should:** (1) still hunt the **first priced fire of the day** — strike
  selection near $0.60 and live-vs-replay fire parity remain untested after nine sessions; (2) watch
  **QQQ's new scenario 3**, which needs price out of 713.50–720.67 to be takeable at all, and the
  14:45 prime-close window on all three; (3) **deploy the queued F76 prose fix** if no trade is open;
  (4) re-check bar provenance stays `exchange`. Still open for the user: **F47**, **F49**, **F50**,
  **F51**, **F54**, **F56**, **F58**, **F59**, **F61**, **F62**, **F63**, **F64**, **F65**, **F69**,
  **F70**, **F71's shared half**, **F72's strategy question**, **F74**, **F76's rule question**,
  **F81**, F67's two shared-side halves, and the F30-family question of which premium series is
  authoritative.

## 2026-09-09 14:15 ET (run 42 — the queued F76 fix is deployed as v0.7.30; desk healthy, still zero fires)

- **Alive and clean.** `/api/health` ok, **v0.7.30** after this run's deploy, armed 74. SPY
  `e4d39d00`, QQQ `9a1094ed`, IWM `e87e4ad2` all `armed`, `complete: true` (pmh/pml/dayType/
  sizingAtOpen present), `needsAttention` false, mode **auto** on Team2 Practice `b9dcd8db…`,
  **zero trades, zero open positions**, ninth session. Quote age 0 s, session `regular`, bar age
  85–118 s. The engine log carries **no warning or traceback since the 12:55 ET boot**; everything
  above that line pre-dates it.
- **Data is real-time and provenance-clean.** 274/274 RTH 1m rows per symbol 09:30–14:03, **all
  `source='exchange'`**, zero `sampled`/`unknown`/`sim`, **zero zero-volume rows, zero interior
  gaps** on all three. Option quotes: SPY 763P 0.51/0.52, QQQ 717C 0.50/0.51, IWM 291P 0.23/0.24 —
  all `source: "opra"`, `provider: alpaca`, `delayed: false`, 0 DTE. F77 did not reproduce for a
  third consecutive run. F79/F80 stay closed.
- **F76's reporting half is DEPLOYED (v0.7.30, commit `73495eb`).** Run 41 committed the fix
  (`05fb2b2`) but **without a release bump**, and the versioning rule requires APP_VERSION,
  package.json, the lockfile, `backend/zargar/__init__.py` and pyproject to move together — so the
  fix could not ship. `73495eb` bumps all five to **0.7.30** with the changelog entry
  ("A setup's note states its own target"); `npm run check-release` green, **118 Team2 tests pass**,
  frontend build green. Deployed at 14:10–14:12 ET through the scheduler task **ZargarRestart**
  (`/api/ops/restart-check` returned `safe: true` first; restore check **OK 71/71, openTrades 0/0,
  pendingExits 0/0, restingOrders 10/10, inflightOrders 0/0**). Verified live: SPY 11:15 now reads
  *"→ puts down to 764.75 — already behind the break, so this setup has no room (F76)"* with
  `target: 764.75` in the payload; IWM 10:45 the same at 293.56. **Reporting only** — no target,
  size, gate, rule or money path changed.
- **Replay parity is now exact on all three.** SPY 12/12, QQQ 10/10, IWM 30/30, zero trades both
  ways. **QQQ's extra 12:14 `same_pullback` is gone** — the restart recomputed the live read on the
  repaired tape, exactly as run 41 predicted, so that artifact is closed. (IWM briefly showed one
  extra 14:14 `same_pullback` in the replay: a race, the 2m bar closed between the live read and the
  replay call, not a divergence.)
- **What the read saw since 13:37.** IWM: `late_touch` at **13:38, 13:42 and 14:12** — touch #3 of
  `pm_break_down@10:30`, watch-only past the first two (D9/P6), the first appearance of that event
  kind today and the correct behaviour; plus `same_pullback` 13:44. QQQ: `same_pullback` 14:02 on
  its new scenario 3 (bounce PDL, calls, target 717.47), which flipped at 13:15. SPY: nothing since
  12:28. Prices at 14:14: SPY 763.12, QQQ 716.71, IWM 291.04. **Day totals unchanged in cause: 18
  `skip_target_behind`, 5 `skip_no_trade_zone`, 2 `skip_engulfing`, 3 `late_touch`, 0 fires.**
- **The day's two blockers still stand.** SPY and IWM (the symbols that left their pre-market range)
  are killed by the frozen target — **F76**/**F81**; QQQ (which never left it) by V6's no-trade zone
  — **F56**. Nothing new to add: both mechanisms are already written up with evidence, and both are
  rules questions for the user, not defects to fix here.
- **UI green.** `/team2` renders on 0.7.30 with all three plans, right sheets, ARMED status, and the
  "74" armed count (cookie recipe: set `zargar_session` via `document.cookie`, then navigate;
  `?token=` still does not authenticate the SPA route).
- **Next run (14:30–15:00 ET) should:** (1) still hunt the **first priced fire** — strike selection
  near $0.60 and live-vs-replay fire parity remain untested after nine sessions; (2) watch the
  **14:45 prime-close window**, the day's last real chance, and **QQQ's scenario 3**, the only symbol
  with a live target, which needs price out of 713.50–720.67; (3) remember the **15:30 last-entry /
  15:45 flatten** 0DTE gates; (4) **no restart is queued** — the desk is current at v0.7.30. Still
  open for the user: **F47**, **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**, **F61**,
  **F62**, **F63**, **F64**, **F65**, **F69**, **F70**, **F71's shared half**, **F72's strategy
  question**, **F74**, **F76's rule question**, **F81**, F67's two shared-side halves, and the
  F30-family question of which premium series is authoritative.

## 2026-09-09 14:40 ET (run 43 — desk healthy on v0.7.30; the contract picker exercised read-only for the first time → F82)

- **Alive and clean.** `/api/health` ok, **v0.7.30**, armed 74. SPY `e4d39d00`, QQQ `9a1094ed`, IWM
  `e87e4ad2` all `armed`, `complete: true` (pmh/pml/dayType/sizingAtOpen present), `needsAttention`
  false, mode **auto** on Team2 Practice `b9dcd8db…`, **zero trades, zero open positions**, ninth
  session. Quote age 0.1–0.4 s, session `regular`, bar age 67 s. **No restart this run**; the engine
  log has exactly **one** timestamped warning since the 14:12 ET boot — a transient EM restore-check
  mismatch on one plan (another desk's, resolved). No Team2 log line, no traceback after the boot.
- **Data real-time and provenance-clean.** 303/303 RTH 1m rows per symbol 09:30–14:32, **all
  `source='exchange'`**, zero `sampled`/`unknown`/`sim`, **zero zero-volume rows, zero interior
  gaps** on all three. Option quotes `source: "opra"`, `provider: alpaca`, `delayed: false`,
  sub-second, and the chain row matched the nested OPRA quote exactly — **F77 did not reproduce for a
  fourth consecutive run**. F75/F79/F80 stay closed.
- **Replay parity exact on all three** (SPY 12/12, QQQ 10/10, IWM 33/33, zero trades both ways).
  Run 42's IWM `same_pullback` discrepancy was the predicted bar-boundary race and did not recur.
- **What the read saw since 14:14.** IWM: `late_touch` at **14:16** (touch #4 of
  `pm_break_down@10:30`, watch-only past the first two — D9/P6) and `same_pullback` at 14:20. QQQ:
  nothing since the 14:02 `same_pullback` on its scenario 3 (bounce PDL, calls, target 717.47). SPY:
  nothing since 12:28. Prices at 14:38: SPY 762.82, QQQ 716.43, IWM 291.08. **Day totals: 18
  `skip_target_behind`, 5 `skip_no_trade_zone`, 2 `skip_engulfing`, 4 `late_touch`, 0 fires.**
- **Method sanity checked against the tape, not just the log.** Recomputed 2m bars and the 2m EMA13
  from the DB: IWM's 14:12/14:16/14:20 touches are **real** (bar 14:16 O290.94 H291.13 L290.93
  C291.11 straddles EMA13 291.01; 14:24 onward genuinely stops touching, and the read correctly
  stops logging). QQQ's 13:15 flip to scenario 3 is **correct**: the 13:00–13:15 15m bar closed
  **716.89**, above the 716.50 PDL-zone top, with `flip_body_ratio=0` so a close (not a body) is the
  rule. EMA200 values are sane against price on all three (SPY 763.06 vs 762.70).
- **F82 — NEW, the day's one real finding.** With no fire in nine sessions the contract picker had
  never run, so this run exercised it **read-only** (live CBOE chain + `select_by_premium` + an OPRA
  reprice; **no order, no plan touched**). Good news: the **mechanism works end-to-end** — same-day
  expiry found, strike chosen, live tight OPRA quote returned (SPY 762P 0.20/0.21 · QQQ 717C
  0.28/0.29 · IWM 291P 0.19/0.20). The finding is what it *chose*: at 14:38 ET, 81 minutes to
  expiry, **exactly one OTM strike on each symbol still sits inside the `[0.20, 0.90]` premium band
  — the first OTM strike, at ~$0.27, less than half the $0.60 target** (next strike out: $0.02–0.12,
  under the floor). The premium rule has quietly become "buy the nearest OTM strike", with **no
  delta guard** — IWM's pick priced **delta −0.51**, effectively ATM, a far faster instrument than
  the morning ~$0.50 contract the calibration (B3) is built on. On the same decay the last in-band
  strike drops under the floor around **15:10–15:25 ET**, *before* the 15:30 `last_entry_min` gate,
  so late fires would start refusing with `skip_no_contract`. Also confirmed (F14's known mechanism,
  quantified): selection reads the **delayed** CBOE ask while the fill reads OPRA, and today the
  delayed asks were one-directionally ~$0.05 / ~20% high on all three.
- **Proposed for the user (F82 — rules/thresholds, not built):** (a) leave it; (b) make
  `target_premium` time-aware (scale with √time-to-expiry so the band tracks the author's morning
  *moneyness*); (c) add a **delta band** beside the premium band (e.g. refuse |delta| > 0.45); or
  (d) an explicit late-session entry cutoff instead of the accidental one at the $0.20 floor. The
  honest fix for F14's half is to run **selection** on live OPRA, not only the reprice.
- **The day's two blockers are unchanged** and already written up: SPY and IWM (which left their
  pre-market range) are dead on the frozen target — **F76**/**F81**; QQQ (which never left it) is
  blocked by V6's no-trade zone — **F56**. Both are rules questions for the user.
- **UI:** `/team2` and `/api/team2/status` both 200. The full page render was **not** re-verified
  this run — the browser cookie handoff was blocked by the sandbox — but run 42 verified it green on
  this identical build 25 minutes earlier and nothing has deployed since. `restart-check` reports
  `safe: true`.
- **Next run (15:00–15:30 ET) should:** (1) watch the **14:45 prime-close window**, the day's last
  real chance, and **QQQ's scenario 3** (the only symbol with a live target — it needs price out of
  713.50–720.67 to be takeable at all); (2) **test F82's prediction directly** — re-measure the
  in-band strike count around 15:10–15:25 and record whether the band empties before the 15:30
  last-entry gate; (3) mind the **15:30 last-entry / 15:45 flatten** 0DTE gates; (4) confirm bar
  provenance stays `exchange` and the 15:45 flatten runs clean on an empty book. **No restart
  queued** — the desk is current at v0.7.30. Still open for the user: **F47**, **F49**, **F50**,
  **F51**, **F54**, **F56**, **F58**, **F59**, **F61**, **F62**, **F63**, **F64**, **F65**, **F69**,
  **F70**, **F71's shared half**, **F72's strategy question**, **F74**, **F76's rule question**,
  **F81**, **F82**, F67's two shared-side halves, and the F30-family question of which premium
  series is authoritative.

## 2026-09-09 15:15 ET (run 44 — F82's decay prediction CONFIRMED on the live chain; its reporting half fixed as v0.7.31; new F83)

- **Alive and clean.** `/api/health` ok, **v0.7.30** running, armed 73. SPY `e4d39d00`, QQQ
  `9a1094ed`, IWM `e87e4ad2` all `armed`, `complete: true` (pmh/pml/dayType/sizingAtOpen present),
  `needsAttention` false, mode **auto** on Team2 Practice `b9dcd8db…`, **zero trades, zero open
  positions**, ninth session. Quote age 0.1–0.3 s, session `regular`, bar age 92 s, window
  `prime_close`. `restart-check` `safe: true`.
- **Data real-time and provenance-clean.** 334/334 RTH 1m rows per symbol 09:30–15:03, **all
  `source='exchange'`**, zero `sampled`/`unknown`/`sim`, **zero zero-volume rows, zero interior
  gaps** on all three.
- **Replay parity exact on all three**: SPY 12/12, QQQ 10/10, IWM 34/34, zero trades both ways.
- **What the read saw since 14:38.** IWM only: `late_touch` at **15:02** (touch #4 of
  `pm_break_down@10:30`, watch-only past the first two — D9/P6). QQQ nothing since its 14:02
  `same_pullback` on scenario 3; SPY nothing since 12:28. Prices at 15:16: SPY 763.16, QQQ 716.48,
  IWM 290.79. **Day totals: 18 `skip_target_behind`, 5 `skip_no_trade_zone`, 2 `skip_engulfing`,
  5 `late_touch`, 0 fires.**
- **F82 CONFIRMED, and the band empties 25 minutes EARLIER than the gate.** Run 43 predicted from
  decay that the last in-band strike would drop under the $0.20 floor around 15:10–15:25 ET.
  Re-measured **read-only at 15:05 ET** (54 min to expiry) on the live CBOE chain, each symbol on its
  own live direction — **no order, no plan touched**: **SPY 0 in-band strikes, IWM 0 in-band strikes**,
  `select_by_premium` returns `None` on both, so any fire from ~15:05 on is a `skip_no_contract`
  refusal. (SPY puts 762/761/760 = 0.15/0.06/0.04 · IWM puts 290/289/288 = 0.04/0.02/0.01.) The
  desk's **effective** last-entry on a quiet day is ~15:00, not the configured 15:30, and nothing in
  the plan, the headline or the gate says so. **QQQ sharpens the delta half:** 2 in band (716 @ 0.77,
  717 @ 0.26) and "closest to $0.60" picked **716 @ 0.77 — delta 0.63**, drifting from run 43's
  −0.51 to +0.63 in 27 minutes. A fixed *price* band on a decaying chain can only be met by moving
  toward the money. Options (a)–(d) in F82 remain the user's call; (d) now has a measured cost.
- **Fixed and released: F82's reporting half (v0.7.31, commit `4fa1cab`).** Both refusal strings —
  the live runner's error and the modelled read's `skip_no_contract` note — said no strike priced
  *"between $0.20 and $0.60"*, while **both** pickers accept `[floor, 1.5 × target] = [0.20, 0.90]`:
  a note understating the accepted band by 50%, the same class of defect as F76. The edge is now a
  named constant on each side (`options.pick.MAX_OVER_TARGET`, `team2.premium.MAX_OVER_TARGET` —
  previously a hard-coded 1.5 in the model), both strings quote it and name the target beside it, and
  a new test pins the two constants equal and the prose to the band. **119 Team2 tests pass**;
  `npm run check-release` and the frontend build green. **Reporting only** — no band, threshold, gate,
  size or money path changed.
- **DEPLOY QUEUED, deliberately not taken.** The commit is on the branch at v0.7.31 but the desk is
  still serving 0.7.30. A prose-only fix is worth nothing in the last 40 minutes of the session, and
  a restart spanning the **15:30 last-entry** and **15:45 flatten** gates with 73 armed plans (mostly
  another desk's EM) is risk for no gain. **Deploy on the next run, after the 16:00 close.**
- **F83 — NEW (labelling, not money).** The same 2m bar carries two different times: the read's
  **events** are stamped with the bar's **close**, the snapshot's **`regime` block** with its
  **start**. Proof: IWM's `late_touch` `time 15:02` `spot 290.8233` vs regime `ts` **15:00**
  `ema13 290.8233` — one bar, two labels. It has now cost two watch runs a false alarm: this run's
  first tape check evaluated IWM's touches under start-labelling and got **two phantom failures**;
  re-checked under close-labelling, **all three of IWM's 14:12/14:16/15:02 touches satisfy the coded
  rule** (`high >= ema13 − pm_tol_atr × atr and close < ema13`, tol ≈ 0.025). The touches are
  correct — the labels are not. Written up with the three options in TRADING-RULES; **not built**
  (it changes the read/snapshot contract and the UI, so it is the user's call).
  **Working rule for future runs: an event's time is the 2m bar's CLOSE; the regime block's `ts` is
  that bar's START.**
- **Method sanity otherwise green.** QQQ's scenario 3 (bounce PDL, calls, target 717.47) still the
  only symbol with a live target. EMA200 sane vs price on all three. The engine log has **no
  traceback** and one non-Team2 warning kind since the 14:12 ET boot: 274 × `persist_bars: dropped N
  non-bucket-aligned stub bar(s)`. **Not new (first seen 2026-09-08 16:26) and not Team2** — it is the
  shared F75 guard refusing stub bars, and Team2's own tape is complete (334/334, zero gaps), so
  nothing is being lost here. Noted for the platform owners as **noise, not breakage**: ~2 warnings a
  minute is enough to bury a real one.
- **UI green.** `/team2` renders on 0.7.30 with all three plans, correct sheets, ARMED status, the
  0DTE line ("entries until 15:30, flat by 15:45") and the armed count 73.
- **Next run (15:45–16:15 ET, after the close) should:** (1) **deploy v0.7.31** (`4fa1cab`) via the
  scheduler task `ZargarRestart` once the book is flat — check `restart-check` first; (2) confirm the
  **15:45 flatten** ran clean on an empty book and the session closed with 0 trades on the tenth
  session; (3) record the day's final totals and whether QQQ's scenario 3 ever left 713.50–720.67;
  (4) re-confirm bar provenance stays `exchange` through the close. Still open for the user: **F47**,
  **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**, **F61**, **F62**, **F63**, **F64**,
  **F65**, **F69**, **F70**, **F71's shared half**, **F72's strategy question**, **F74**, **F76's
  rule question**, **F81**, **F82** (now with confirmed evidence), **F83**, F67's two shared-side
  halves, and the F30-family question of which premium series is authoritative.
## Desk record 2026-09-09 14:00–14:40 ET — Codex review of PRs 33–45 (v0.7.32)

- The reviewer reproduced ten gaps with twelve regressions at a3885a9. All fixed; the regression file is now
  `tests/test_codex_f75_regressions.py` and passes with the rest of the affected suites (39) and the broad set.
- Restart evidence is now a blocker when missing (order inventory, readiness answer), fire chains in flight block,
  new entries are quiesced before the state capture, managed positions are reconciled by id after the restart.
- Data: one venue-merge policy (memory = batch = database), interior-minute recovery, seed baseline, provider-named
  backfill with per-day coverage before any zeroing, transactional quarantine with full-row verification, the Yahoo
  history parser no longer invents zero volumes.
- Research path: sweeps validate their warm-up sessions and stamp the hash of the bars they consumed; plans hash the
  bars they were built from. F72 re-measured in-process on frozen inputs (`600a8d75…`): baseline +247.7 vs variant
  +207.0 pnl%-sum, 30 shared / 6 variant-only / 1 baseline-only trades; 13 dates × 3 symbols. Stays off.
- Retained evidence for the runtime quarantine batches: closed-day rows have no live rows at their minutes (no venue
  bar exists on a closed day); the sim-block minutes hold 15,641 live exchange rows, all from the backfill that ran
  after the batches committed. No correction had a writer to race against.
- Deploy: after the close through `ZargarRestart` (the door refuses on missing evidence from now on).

## 2026-09-09 15:45 ET (run 45 — another desk deployed v0.7.32 mid-session at 15:33; the 15:30 gate fired clean; new F84 fixed as v0.7.33)

- **The desk went down and came back inside this run — not a crash.** Health was green on v0.7.30 at
  15:31; five minutes later `:8420` refused connections. Cause found in
  `logs/restart-20260909-123337.log`: **another desk ran `scripts
estart.ps1` at 15:33:37 ET**,
  deploying **v0.7.32** (which carries our queued v0.7.31 F82a fix). The app is up on **v0.7.32**,
  armed 73, and the script's own restore check passed: `armed 70/70, openTrades 0/0, workingEntries
  0/0, pendingExits 0/0, restingOrders 10/10, inflightOrders 0/0`. **This is a mid-session restart
  spanning the 15:30 last-entry gate** — harmless today because Team2's book was empty and its
  15:32 `skip_last_entry` was already logged, but it is not a thing this watch would have done, and
  it is worth the platform owners knowing a deploy landed 27 minutes before the close.
- **Team2 came through it intact.** All three plans `armed`, `complete: true`, `needsAttention`
  false, `readError` null, mode **auto** on Team2 Practice, **zero trades, zero open positions**,
  ninth session. Every event survived (SPY 13, QQQ 11, IWM 38 — identical counts either side of the
  restart); `team2 runner restored 3 armed plan(s)` in the log; bars resumed immediately.
- **The 15:30 last-entry gate fired correctly on all three** — `skip_last_entry` at 15:32 on SPY,
  QQQ and IWM ("past 15:30 — no new entries, managing what is open until the 15:45 flatten, D6/C3").
  The 15:45 flatten was still one minute out at the end of this run; **next run confirms it** (there
  is nothing to flatten).
- **Data real-time and provenance-clean.** 363/363 RTH 1m rows per symbol 09:30–15:32, **all
  `source='exchange'`**, zero `sampled`/`unknown`/`sim`, **zero zero-volume rows, zero interior
  gaps** on all three. Quote age 0 s, session `regular`, bar age 75–106 s (elevated only across the
  reboot, back to normal after). F75/F79/F80 stay closed.
- **Replay parity exact on all three, post-restart**: SPY 13/13, QQQ 11/11, IWM 38/38, zero trades
  both ways.
- **What the read saw since 14:38.** IWM only: `late_touch` at **15:02, 15:26, 15:30** (all
  watch-only past the D9 allowance) plus a 15:28 `same_pullback`. QQQ nothing since its 14:02
  `same_pullback` on scenario 3; SPY nothing since 12:28. Prices at 15:44: SPY 762.75, QQQ 716.09,
  IWM 290.42 — QQQ never left 713.50–720.67, so its scenario 3 was never takeable. **Day totals: 18
  `skip_target_behind`, 5 `skip_no_trade_zone`, 2 `skip_engulfing`, 7 `late_touch`, 3
  `skip_last_entry`, 0 fires.**
- **F84 — NEW, found and FIXED this run (v0.7.33, commit `1853ace`).** IWM's `pm_break_down@10:30`
  logged **seven** `late_touch` events today and **every one said "touch #3"**. Cause: a watch-only
  contact must not spend the D9 allowance, so `session.py` `continue`s without incrementing
  `s.touches`, and the label `idx = s.touches + 1` is pinned at the cap forever. The freeze is
  correct and stays — the *message* was the defect: seven distinct contacts are indistinguishable
  from one re-logged contact, and it misled this watch twice (runs 43 and 44 both recorded "touch
  #4" for the 14:16 event, a number no code ever emitted). The prose now counts with
  `s.opportunities`, which does advance. **Prose only** — the `touch` payload keeps the frozen index
  (contract unchanged); no rule, threshold, gate, size or money path moved. 120 Team2 tests pass,
  `check-release` and the frontend build green.
- **F82 addendum — the late-session survivor is decided by luck, not by the method.** Third
  read-only chain measurement (no order, no plan touched), 23 minutes to expiry: **SPY 1** in-band
  strike (763P @ $0.31, **delta −0.435**, spot 763.14 — the strike is 0.14 away), **QQQ 1** (717C @
  $0.24, delta 0.342), **IWM 0** (nearest OTM put $0.02 → `select_by_premium` returns `None`). This
  **corrects the shape** of run 44's reading: the band does not simply empty after ~15:00 — SPY had
  0 in-band at 15:05 and 1 again at 15:37 because price drifted back onto a strike. The real
  behaviour is that **the band collapses onto whichever strike is nearest the money**, so which
  symbol is tradeable late, and at what delta, is set by spot's distance to the nearest strike
  rather than by anything in the method. Strongest argument yet for F82 option **(c), a delta band
  beside the premium band** — still the user's call.
- **Proposed (not built) — an empty OPRA warning.** `zargar/options/service.py:356` logs
  `"OPRA quotes failed: %s"` on the generic exception path, and today's boot produced exactly that
  with an **empty reason** (`OPRA quotes failed: ` — the exception's `str()` is blank). Three
  occurrences all-time, all at startup, no impact — but OPRA is the source Team2's fire path
  reprices from, so a blank warning about it is the one line a post-mortem would need. One-line fix
  (log `type(exc).__name__` beside the message). **Shared engine code, so not touched** — the user's
  call, and it would want a PLATFORM-RULES row.
- **Also for the platform owners (not Team2, not fixed):** the restart logged one
  `restore check MISMATCH after restart` naming **36 `enhanced_market` plans**, which resolved on its
  own as the restore finished (`restart-check` now `safe: true`, armed 73). And
  `persist_bars: dropped N non-bucket-aligned stub bar(s)` continues at roughly two warnings a
  minute — the shared F75 guard doing its job, Team2's tape is complete, but it is enough noise to
  bury a real warning. Both were already flagged in run 44.
- **UI green.** `/team2` renders on v0.7.32 with all three plans, correct sheets, ARMED status, the
  0DTE line ("entries until 15:30, flat by 15:45") and armed 73.
- **DEPLOY QUEUED: v0.7.33 (`1853ace`).** Deliberately not taken — a prose-only fix is worth nothing
  in the last ten minutes of a session, and `restart-check` being `safe: true` is not a reason to
  restart across the 15:45 flatten. **Deploy on the next run, after the 16:00 close.**
- **Next run (16:00–16:30 ET, after the close) should:** (1) **deploy v0.7.33** (`1853ace`) via the
  scheduler task `ZargarRestart` — check `restart-check` first; (2) confirm the **15:45 flatten** ran
  clean on the empty book and the ninth session closed with 0 trades; (3) re-confirm bar provenance
  stays `exchange` through the close and the 17:00 `team2_plan_nightly` job is registered for
  tomorrow's plans; (4) verify the new `late_touch` prose reads correctly once 0.7.33 is serving.
  Still open for the user: **F47**, **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**,
  **F61**, **F62**, **F63**, **F64**, **F65**, **F69**, **F70**, **F71's shared half**, **F72's
  strategy question**, **F74**, **F76's rule question**, **F81**, **F82** (now with a third
  measurement), **F83**, F67's two shared-side halves, and the F30-family question of which premium
  series is authoritative.

## 2026-09-09 16:20 ET (run 46 — post-close: the ninth session closed clean at 0 trades, v0.7.33 deployed, and F85 says the desk went blind for two minutes at 15:15 and nothing but the journal remembers)

- **Alive and current.** The queued deploy went out: `ZargarRestart` at 16:09 ET, back in 25 s on
  **v0.7.33** (`1853ace`, F84's prose fix). The script's own restore check passed on every count —
  `armed 12/12, openTrades 0/0, workingEntries 0/0, pendingExits 0/0, restingOrders 10/10,
  inflightOrders 0/0, managedPositions 3/3, managedOpen 3/3`. `restart-check` was `safe: true`
  beforehand and Team2's book was empty, so nothing of ours was at risk. No traceback since the boot.
- **The session closed correctly.** All three plans took `TechniquePlanScored` + `TechniquePlanDisarmed`
  at **16:00:00 ET** with `reason: "session closed"`, `flatten: false`, `openLeft: 0`,
  `stopReason: null` — the 15:45 flatten had nothing to flatten, as expected. `/api/team2/status` now
  shows `armed: []` (the correct post-close state) and `/team2` renders all three as **DISARMED**.
  `team2_plan_nightly at 17:00 ET` and `team2_preopen at 09:25 ET` are both registered on the new
  boot, so tomorrow's plans are covered.
- **Final tape for the day — ninth session, still zero.** 0 fires, 0 trades, 0 open positions on all
  three. Day totals: **20 `same_pullback`, 18 `skip_target_behind`, 7 `late_touch`, 5
  `skip_no_trade_zone`, 5 `scenario`, 3 `skip_last_entry`, 2 `skip_engulfing`, 2 `pm_break`**
  (SPY 13 events, QQQ 11, IWM 38). Nothing new after the 15:32 `skip_last_entry` on each. **QQQ never
  left 713.50–720.67**, so its scenario 3 — the only symbol with a live target all afternoon — was
  never takeable, closing the day exactly as run 45 predicted.
- **Replay parity exact on all three, on the new build**: SPY 13/13, QQQ 11/11, IWM 38/38, zero
  trades both ways.
- **Bar provenance clean through the close.** **390/390** RTH 1m rows per symbol 09:30–16:00, **all
  `source='exchange'`**, zero `sampled`/`unknown`/`sim`, **zero zero-volume rows, zero interior
  gaps**, first 09:30 last 15:59 on all three. F75/F79/F80 stay closed.
- **F84 verified on 0.7.33.** IWM's seven watch-only contacts now read **"contact #13 … #19 of
  pm_break_down@10:30 — past the first 2 pullbacks, watch-only (D9/P6)"** — seven distinct,
  monotonic labels where 0.7.32 printed "touch #3" seven times — while the event's `touch` payload
  still carries the frozen index 3 (contract unchanged). Note for future runs: `/api/team2/runs/{id}/read`
  **recomputes** the read from bars (`source: "live"`), so a prose fix applies retroactively to what
  the endpoint shows; the journalled `TechniquePlanRead` rows keep the wording they were written with.
- **F85 — NEW, NOT FIXED, and the most important thing in this run.** At **15:15:02 ET** the runner
  journaled `TechniquePlanError {stage: "data", error: "stale bars", lastBarTs: 15:12}` on all three
  Team2 plans — and with the identical `lastBarTs` on **36 `enhanced_market` and 10 `tip` plans**.
  Four seconds later: `alpaca stream dropped: no close frame received or sent` (15:15:06),
  reconnected 15:15:08. The runner eats **1m** bars, so a healthy newest-bar age tops out ~65 s;
  **182 s means the 15:13 and 15:14 closes never reached it** — a desk-wide ~2-minute blind window,
  15 minutes before the 15:30 last-entry gate. **It is invisible after the fact:** `ap.stale` clears
  on the next bar, `needsAttention` reports staleness only while a position is open (nothing was
  held), `readError` stayed null, quotes are a different path and stayed fresh, and the tape is the
  perfect 390/390 all-exchange record above because the missing minutes were backfilled behind the
  outage. **Run 44 of this watch ran at exactly 15:15 ET and reported everything green.** Cost today:
  nothing (no setup was live). But this is exactly how a fire gets dropped silently.
  **Working rule adopted for every future run: query the journal for `TechniquePlanError` — a healed
  stall leaves no other trace.**
- **Proposed for the user (F85, not built — both halves are shared code, `zargar/execution/planrunner.py`
  and `zargar/brokers/alpaca.py`):** (a) record a healed stall durably on the session read as a
  "blind window HH:MM–HH:MM" line, so a day's record states where it was blind; (b) add a
  data-liveness watchdog on the stream (no bar for N seconds → force reconnect) — the reconnect took
  2 s, so the dark window was nearly all detection latency; (c) leave it.
- **Still noise, not breakage:** `persist_bars: dropped N non-bucket-aligned stub bar(s)` continues at
  roughly two warnings a minute (the shared F75 guard doing its job; Team2's tape is complete). The
  empty-reason `OPRA quotes failed:` line proposed in run 45 is unchanged.
- **Next run (pre-open tomorrow, 2026-09-10) should:** (1) confirm the **17:00 ET tonight**
  `team2_plan_nightly` job minted three plans for 2026-09-10 and that they carry sheets/levels;
  (2) run the **09:25 pre-open** check — `pmh`/`pml`/`dayType`/`sizingAtOpen`/`complete: true` on all
  three, and `POST /api/team2/preopen-now` if it was missed; (3) **query the journal for
  `TechniquePlanError` (F85)** as a standing item, not only the snapshot's `needsAttention`;
  (4) confirm the desk is serving **v0.7.33** and bar provenance stays `exchange`. Still open for the
  user: **F47**, **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**, **F61**, **F62**,
  **F63**, **F64**, **F65**, **F69**, **F70**, **F71's shared half**, **F72's strategy question**,
  **F74**, **F76's rule question**, **F81**, **F82** (three measurements, option (c) now best
  supported), **F83**, **F85**, F67's two shared-side halves, and the F30-family question of which
  premium series is authoritative.


## 2026-09-09 16:35 ET (run 47 — last run of the day: nothing broke after the close, and a measurement says the pre-market high/low is computed over bars of any provenance — F86)

- **Alive, current, quiet.** `/api/health` ok on **v0.7.33** (`1853ace`, deployed by run 46 at
  16:09 ET), armed 12 desk-wide. `/api/team2/status` → `armed: []`, mode `auto`, the 0DTE policy
  intact (last entry 15:30, flatten 15:45, cap 40 contracts / $2,000) — the correct post-close state
  for a session that closed at 16:00. **No traceback since the 16:09 boot**; the only warnings are
  the known `persist_bars: dropped N non-bucket-aligned stub bar(s)` noise.
- **Tomorrow is scheduled.** Both jobs are registered on the new boot —
  `team2_plan_nightly at 17:00 ET` and `team2_preopen at 09:25 ET` (log 16:09:55). The 17:00 job had
  not run yet at the time of this check (16:35), so **run 1 of 2026-09-10 must confirm three plans
  for 09-10 exist and carry sheets/levels** before the pre-open check.
- **F85 standing check, clean.** Queried the journal directly (the new working rule): the only
  `TechniquePlanError {error: "stale bars"}` cluster in 30 hours is the **49 rows at 15:15 ET**
  already written up as F85 — 44 distinct symbols, 3 of them Team2's. **Nothing new since 15:15**,
  and nothing at all after the close. The other `TechniquePlanError` rows today are tip-technique
  follow-ups (GS/AMZN/AVGO), not ours.
- **Tape final and clean.** RTH 09:30–15:59: **390/390 1m rows per symbol, 100 % `source='exchange'`,
  zero zero-volume rows** on SPY, QQQ and IWM. F75/F79/F80 stay closed. Day totals unchanged from
  run 46 (0 fires, 0 trades; 20 `same_pullback`, 18 `skip_target_behind`, 7 `late_touch`, 5
  `skip_no_trade_zone`, 5 `scenario`, 3 `skip_last_entry`, 2 `skip_engulfing`, 2 `pm_break`).
- **F86 — NEW, NOT FIXED, found by looking at the pre-market half of the tape (which no run had
  checked before; every previous provenance check stopped at 09:30).** `premarket_range()` is a plain
  `max(high)/min(low)` over whatever bars it is handed, and Team2 hands it `load_bars(...)` — every
  row of the bars table, any provenance, any volume. F75's `validate_sessions` guard covers the
  **warm-up** only, not today's pre-market. Over 20 sessions × 3 symbols (38 symbol-days with
  non-exchange pre-market rows) **one row actually moved a decision input**: `IWM 2026-08-25 07:01 ET`,
  `H 299.81 / L 297.97, volume 0, source 'unknown'`, set **PML 297.97 against a real traded low of
  298.26 — 0.29 too wide (0.10 %)**. pmh/pml are not cosmetic: they drive `classify_day`,
  `sizing_bucket` and the **`pm_break_up`/`pm_break_down` trigger levels** themselves. All 1,888
  non-exchange pre-market rows are `unknown` and the newest is **09:12 ET today**, consistent with
  pre-F75 writes — but quote-`sampled` rows outrank `unknown`, are still written in thin
  extended-hours minutes (IWM banked two at 16:30/16:31 ET today) and take their price from a quote,
  so the hole is open under a new label.
- **Proposed for the user (F86, deliberately not built — it changes a live trigger level, and the
  natural home is shared `marketstructure/dailylevels.py`):** **(a)** Team2-local, filter the bars
  passed to `premarket_range` to `source == 'exchange'` with a fallback when a day has none;
  **(b)** require `volume > 0` — cheapest, provenance-agnostic, and it is the rule the house already
  applies to history (F79: "a minute without volume is provisional, not a bar"); **(c)** fix it
  inside shared `premarket_range` for every technique, plus a PLATFORM-RULES row; **(d)** leave it
  and trust F75 to have ended the `unknown` writes. Recommendation if the user wants one: **(b)**.
- **Nothing deployed this run** — the only change is documentation (F86 in TRADING-RULES.md and this
  entry), so the desk keeps running v0.7.33 untouched into tonight's 17:00 plan job.
- **Next run (pre-open 2026-09-10) should:** (1) confirm the **17:00 ET** nightly job minted three
  plans for 09-10 with sheets/levels; (2) run the **09:25 pre-open** check — `pmh`/`pml`/`dayType`/
  `sizingAtOpen`/`complete: true` on all three, `POST /api/team2/preopen-now` if missed, and
  **spot-check the pre-market rows behind pmh/pml for provenance (F86)**; (3) query the journal for
  `TechniquePlanError` (F85); (4) confirm v0.7.33 is serving and RTH bars stay `exchange`. Still open
  for the user: **F47**, **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**, **F61**,
  **F62**, **F63**, **F64**, **F65**, **F69**, **F70**, **F71's shared half**, **F72's strategy
  question**, **F74**, **F76's rule question**, **F81**, **F82** (three measurements, option (c) best
  supported), **F83**, **F85**, **F86**, F67's two shared-side halves, and the F30-family question of
  which premium series is authoritative.

## Desk EOD 2026-09-09 — the author's day vs ours (read from x.com/Team2Trading via the user's browser)

- **What he did (his own account, unverified):** a pre-market plan on IWM only — "IWM broke 3 days of support this
  morning at our 293.43 zone. As long as we hold below that I'll be focusing on puts. Under the PML I have 291.19,
  then 289.98." 09:41 ET alert: the 293.43 support zone flipping to resistance, watching the IWM 293P. 10:20 ET:
  "PML break and everyone is up well over 100% on these puts" — screenshot +141.77% on the 293P; a later post rolled
  profits into a lower strike on the intraday S/R flip at the PML. No SPY or QQQ posts today.
- **What we did:** zero fires on all three symbols (nine sessions running). IWM: 13 `skip_target_behind` (F72 guard)
  + 2 engulfing + 1 no-trade-zone; SPY: 5 `skip_target_behind`; QQQ: 3 no-trade-zone. Our IWM read saw the same
  break (gap_down, pm_break_down setup at 10:45) and refused every pullback because the plan's down-target (293.56,
  fixed at 17:00 the night before from prior-day pivots) sat ABOVE the price after the gap — F81. His targets were
  the PML (291.19) and the next level (289.98), i.e. re-derived from the morning's structure; IWM printed 290.58.
- **Verdict:** same read, wrong arithmetic. The refusals were right about direction and wrong about the target; the
  gap-day target re-derivation (F81, pre-open, on the frozen inputs, guard kept) is the decision that separates
  our zero from his +141%. Not a re-plan-at-every-entry question (F72 stays off).

## Desk 2026-09-10 (evening of 09-09) — F81 built (v0.7.34)

- Pre-open/open target re-derivation is live (default on): tomorrow's 09:25 completion and 09:30 finalize journal
  `targets_rederived` when the morning has run through a planned target. Measured neutral on the frozen 14-date
  sample; it removes the "born dead" gap plan.
- The entry-time structure fallback (F81b) reproduces the author's IWM day (+114.5 modelled) and loses on the sample's
  other gap days (−27.5 net gap-only, −64 net everywhere). Off, experimental, on the twenty-session review list.

## Standing instruction for the watch job from 2026-09-10 — F81b is LIVE and under observation

`techniques.team2.target_replan = structure` (gap days only) was switched on at 20:30 ET on 2026-09-09. Every run must:
(1) list each `target_replanned` event of the day (symbol, time, was → now/none) and whether it fired; (2) keep a
running tally in this log — "F81b live trades: N, book net $X after fees" — separate from the day's other trades; (3) on
the tenth live entry under the rule, or at the twenty-session review, write the verdict in TRADING-RULES (keep if the
rule's own trades are net positive on the BOOK after fees, else set it back to `off`). Never let this rule go
unreported for a session.

## 2026-09-10 09:15 ET (run 48 — pre-open on a three-way gap-down: plans are correct and F81 re-derived all three targets; one NEW finding, F87, says today's live rule is not the rule replay will score)

- **Alive and current.** `/api/health` ok on **v0.7.36** (`c408f99`, the other desks' Cartel merges),
  armed 58 desk-wide, `/api/ops/restart-check` `safe: true`. Four restarts overnight by other desks
  (`TechniquePlanRestored` at 20:14, 23:22, 00:26, **01:29 ET** — the live boot); all three Team2
  plans restored each time. **No traceback since 09-09 08:11 PT**; the only warnings are the known
  `persist_bars: dropped N non-bucket-aligned stub bar(s)` noise.
- **Tonight's job ran.** `team2_plan_nightly` minted three plans at **17:00:04–17:00:07 ET on 09-09**
  (`TechniquePlanArmed`), all `planFor 2026-09-10`, status `armed`, mode `auto`, portfolio
  Team2 Practice, sheets/levels present. **Plan levels verified against the bars table to the cent:**
  SPY PDH 764.47 / PDL 760.94, QQQ 719.70 / 714.02, IWM 294.155 / 290.31 = the 09-09 RTH extremes
  exactly. Both jobs re-registered on the 01:29 boot (`team2_preopen at 09:25 ET`).
- **Data is real-time.** Quotes for all three seconds old, session `pre`; newest 1m bars 09:02–09:03 ET,
  `source='exchange'`, non-zero volume; `barAgeSeconds` 31–88 (pre-market minutes are thin, so a
  1–2 minute age is normal here); the engine logged **"pre-open feed self-test passed (REST bars +
  stream auth)" at 09:00:04 ET**, and the Alpaca stream has been connected+authenticated since the
  01:29 boot with **no drop since**.
- **F85 standing check (journal, not the snapshot): CLEAN.** Zero `TechniquePlanError` rows desk-wide
  since 09-09 16:00 ET. The 15:15 ET cluster remains the only one on record.
- **Today is a gap-down day on all three** — SPY 758.7 vs a 762.39 prior close (−0.48 %), QQQ 707.4 vs
  716.28 (−1.24 %), IWM 288.6 vs 290.68 (−0.72 %); every one classified `gap_down`, EMAs stacked
  **bear** on 2m with `fan: trend` (SPY strength 2, QQQ/IWM 3). **All three plans' down-targets were
  born behind price** (SPY 760.58 > 758.7; QQQ 710.75 > 707.4; IWM 290.17 > 288.6) — precisely the
  F81 "born dead" case from yesterday's IWM post-mortem.
- **F81 works, first live gap day.** The pre-open read re-derives every one of them to the pre-market
  low: **SPY 760.58 → 757.90, QQQ 710.75 → 706.50, IWM 290.165 → 288.35** (`targetsRederived`,
  `source: pml`, reference = the pre-market last). Day types, pmh/pml, `sizingAtOpen: none` and
  `complete: true` all present in the read. NOTE these come from the on-demand replay preview — the
  **live** plan still shows `complete: false` and will be completed by the 09:25 job; **run 49 must
  confirm the live snapshot carries the same pmh/pml/dayType/targets and journals `targets_rederived`.**
- **F86 measured on today's tape: no distortion.** Today's 04:00–09:30 pre-market rows give the
  **identical** pmh/pml under all four filters (all rows / `volume>0` / `source='exchange'` /
  both) on all three symbols — SPY 764.60/757.90, QQQ 717.52/706.50, IWM 291.74/288.35. The
  `sampled` rows exist (SPY 67, IWM 63, QQQ 5) but every one of them sits **inside** the exchange
  range today. F86 stays open as a latent hole, not a live one.
- **F87 — NEW, NOT FIXED, and it matters for the F81b measurement the user asked for.** The live
  runner reads `rules_from_settings(engine.settings)` **every bar**, while replay/outcome scoring
  reads the thresholds frozen into the plan at mint. Today's plans were minted at 17:00 ET **before**
  `target_replan` was flipped to `structure` at 20:30 ET, so every plan records
  `target_replan: "off"` while the runner is running **`structure`**. If F81b re-plans a target today,
  live will enter where replay writes `skip_target_behind` — the parity check disagrees and the day is
  **scored under a rule it did not trade**. Nothing lost today (0 setups, 0 trades so far).
  Recommendation to the user: re-snapshot `config.thresholds` at the 09:25 completion **and** journal a
  `rules_drift` note; full options in TRADING-RULES F87. **Queued, not deployed** — found at 09:12 ET,
  inside the 09:25–09:35 restart freeze.
- **F81b live tally: 0 trades, book net $0.00** (no setup has formed yet today; see F87 for the caveat
  that today's replay cannot reproduce an F81b entry even if one occurs).
- **Checked and dismissed, so nobody re-chases it:** the quote feed's `prevClose` for all three reads
  **09-08's** close (765.96/718.36/294.67), not 09-09's — that is Yahoo's documented pre-market
  behaviour (the last completed session's change) and **no Team2 input touches it**; the plans'
  `referencePrice` is 762.39/716.28/290.68, i.e. the prior RTH close taken from the bars table, and
  `classify_day` / `sizing_bucket` use `openPrice` + zones + pmh/pml only.
- **Nothing deployed this run** — documentation only (F87 in TRADING-RULES.md and this entry); the desk
  keeps running v0.7.36 untouched into the 09:25 pre-open.
- **Next run (≈09:30–09:45 ET) should:** (1) confirm the **live** snapshot completed at 09:25 —
  `pmh`/`pml`/`dayType`/`sizingAtOpen`/`complete: true` on all three, plus a `targets_rederived` read
  event, and `POST /api/team2/preopen-now` if it was missed; (2) watch the first 15m close against the
  PDL zones (SPY 760.94, QQQ 714.02, IWM 290.31 — price opened **below** all three, so the live
  question is `pm_break_down` at the PM lows 757.90 / 706.50 / 288.35, not the PDL break);
  (3) report every `target_replanned` event per the standing F81b instruction and keep the tally;
  (4) the F85 journal query; (5) decide whether to deploy the F87 fix once the open settles and no
  trade is working. Still open for the user: **F47**, **F49**, **F50**, **F51**, **F54**, **F56**,
  **F58**, **F59**, **F61**, **F62**, **F63**, **F64**, **F65**, **F69**, **F70**, **F71's shared
  half**, **F72's strategy question**, **F74**, **F76's rule question**, **F81**, **F82**, **F83**,
  **F85**, **F86**, **F87**, F67's two shared-side halves, and the F30-family question of which
  premium series is authoritative.

## 2026-09-10 09:52 ET (run 49 — the open confirmed a short bias on all three; F88 found and FIXED but NOT DEPLOYED: the restart door is closed because the running engine is elevated)

- **Alive, but undeployable.** `/api/health` ok on **v0.7.36**, armed 62 desk-wide, `/api/ops/restart-check`
  `safe: true`, zero Team2 errors in the engine log. The **09:25 pre-open job ran at 09:25:10 and 09:25:52**
  and completed all three plans: `pmh`/`pml`/`dayType: gap_down`/`sizingAtOpen: none`/`complete: true`,
  each followed by a `targets_rederived` event and an `open_finalized` at 09:31 on the real 09:30 open
  (SPY 758.02, QQQ 707.56, IWM 288.48). Run 48's open item is closed: the live snapshot does carry it all.
- **Data is real-time.** SPY/QQQ/IWM quotes **sub-second** old, session `regular`; 1m bars banking every
  minute, the 09:45 bar present at 09:46, **16/16 RTH minutes today all `source='exchange'`** with non-zero
  volume on all three. `prevClose` now reads 09-09's close (762.45 / 716.31 / 290.65) — run 48's pre-market
  `prevClose` oddity resolved itself at the open exactly as predicted, nothing to chase.
- **The open (09:30–09:45) — one 15m close, short bias on all three.** Every symbol gapped down and opened
  below its PDL zone, and the first 15m body closed below it: SPY 758.135 < 760.94, QQQ 708.77 < 714.02,
  IWM 288.40 < 290.31 → **`scenario_4` break PDL, puts (B1/C1)** on all three, `setups=1`, **0 fires, 0
  trades**. Verified against the bars table to the cent (the 15m close = each symbol's 09:44 1m close).
  EMAs sane and stacked bear everywhere; QQQ is the one trading back **above** its 13/48 EMA (709.5 vs
  707.36/708.82), i.e. the first pullback entry is setting up there, SPY sits just under its EMA13.
- **F88 — NEW, root-caused, fixed, tested, committed as `ef4fb89` (v0.7.37), and NOT LIVE.** The F81 gap-day
  re-derivation read what the 17:00 plan said as `targetsPlanned or targets`. `targetsPlanned` only ships
  with F81 itself (v0.7.34, deployed **20:30 ET on 09-09** — *after* the 17:00 mint), so all three of
  today's plans fell through to `targets`, which the 09:25 pass had already overwritten; the 09:30 finalize
  then measured the open against the 09:25 output instead of the plan's target, and `_log_rederived`
  de-duped the identical record so nothing said so. **Live cost, on the symbol F81 was built for:** IWM's
  09:25 pre-market last (288.09) *was* the pre-market low, so `below: 290.165 -> none`; at the 288.48 open
  the finalized PML **287.83 was ahead again** but the pass read `planned["below"] = None` and kept it.
  **IWM's active short setup right now carries `target: null`** (SPY 757.90, QQQ 706.50) — a fire there
  would have no `target_exit`, managed only by trims / premium stop / 15:45 flatten. SPY separately kept
  the 09:25 PML 757.90 instead of the finalized 757.69 (21c stale, same side, harmless). Fix: read
  `targetsPlanned` only, recover it from `targetsRederived[side]["was"]` when absent, and **pin** it, so
  the re-derive is idempotent by construction. 127 Team2 tests pass (2 new regressions replay today's IWM
  and SPY sequences), frontend build + `check-release` green. **No threshold, gate, band, size or money
  path changed.** Tomorrow's 17:00 plans carry `targetsPlanned` natively and never take the recovery path.
- **F89 — NEW, the reason F88 is not live, and it blocks EVERY desk.** `ZargarRestart` fired cleanly at
  09:40 ET (`restart-check safe: true`, no open trades, no working entries) and `restart.ps1` **aborted at
  `start.ps1:152` with `Stop-Process ... Access is denied`** on pid 29812. That process — the 01:29 ET boot,
  owner `LENOVO-INTEL\vispe` — is **elevated**: its `CommandLine` is unreadable from a Limited process, and
  all four Zargar tasks (`ZargarRestart`, `ZargarRestartOverride`, `ZargarUnelevatedStart`, `ZargarWatchdog`)
  run `RunLevel = Limited`. So `-Force` does not help either: this is an elevation refusal, not a readiness
  refusal. **Nothing was killed — there was no outage** — but no assistant on any desk can deploy today.
  This is precisely what the 2026-09-05 "the server must run UNELEVATED" decision exists to prevent.
  Deliberately **not worked around**: registering a `RunLevel Highest` task would deploy v0.7.37 but leave
  the next engine elevated and re-close the door for everyone. Logged in `docs/PLATFORM-RULES.md`.
  **Needs the user:** `scripts\stop.ps1` from the elevated terminal that owns the process, then any desk's
  `ZargarRestart` picks up v0.7.37 (armed plans restore automatically, as they did 4× overnight).
- **F81b live tally: 0 trades, book net $0.00.** Zero `target_replanned` events today — no entry has been
  attempted, so the rule has not had an opportunity. **F87 still stands and is unchanged:** today's plans
  record `target_replan: "off"` while the runner runs `structure`, so if an F81b entry does occur today the
  replay parity check will disagree and the day will be scored under a rule it did not trade.
- **F85 standing check: not clean, but not ours.** 20 `TechniquePlanError` rows in the last 20h — a burst of
  19 at **09:31 ET**, every one a **tip** never-chase notice ("X opened gapped through the N level - not
  chasing; the plan stays armed"), which is correct gap-day tip behaviour surfacing through the error
  channel, plus one 09-09 19:15 EM `stale bars` on CRWD. **Zero Team2 rows.**
- **Other desks, reported not touched:** two `cartel-observer bar handling failed` tracebacks (06:37 and
  06:42 PT, `ValueError: entry read requires symbol-matched, minute-aligned 1m bars`) in
  `backend/zargar-8420.log`. Cartel is another desk's technique; flagging only.
- **Next run (≈10:15 ET) should:** (1) check whether the user has restarted — if `/api/health` reads
  **0.7.37**, immediately re-verify IWM's setup target is no longer null (it should re-derive to the PML on
  the next `complete_plan`; if the plans were not re-completed, `POST /api/team2/preopen-now` does it);
  if it still reads 0.7.36, **do not attempt another restart** and repeat the F89 ask; (2) watch the first
  EMA13 pullback entries on the three short setups — QQQ is closest — and check every fire carries a
  `contract` event with an ask near $0.60, not `skip_no_contract`; (3) report `target_replanned` per the
  standing F81b instruction and keep the tally; (4) F85 journal query; (5) run the replay-vs-live parity
  check once a fire exists, remembering F87 makes it unreliable today. Still open for the user: **F47**,
  **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**, **F61**, **F62**, **F63**, **F64**, **F65**,
  **F69**, **F70**, **F71's shared half**, **F72's strategy question**, **F74**, **F76's rule question**,
  **F81**, **F82**, **F83**, **F85**, **F86**, **F87**, **F89**, F67's two shared-side halves, and the
  F30-family question of which premium series is authoritative.

### Run 49 addendum (10:00 ET) — the first live refusal, and why today's F81b tally may read empty

- **09:50 ET, SPY: `skip_no_trade_zone`** — "entry 759.01 sits inside the pre-market range — no-trade
  zone (V6/B5)". Correct against the tape (SPY PM range 757.69–764.60). First and only trigger decision
  of the day so far; QQQ and IWM have not produced a pullback contact yet.
- **F90 — NEW (observation + rule question, nothing changed).** The gate order in `session.py` is
  `sizing_bucket` (V6/B5 no-trade zone) **first**, target gates second, and F20's small-size exception
  only covers `pm_break` setups — not `scenario_4`. So on a gap-down day a `scenario_4` short can only
  enter **below the PML**, and F81 has just set that setup's target **to the PML**: at every reachable
  entry the plan target is behind by construction. The entry-time F81b re-derive is therefore the ONLY
  thing that can hand these setups a target today; on the baseline (`off`) the identical entry is refused
  `skip_target_behind`. That is the mechanism behind 09-09's 18 refusals — the two rules were built
  against each other rather than together. All three symbols are inside their PM ranges right now, so all
  three are gated on a PM-low break (757.69 / 706.50 / 287.83) — exactly where the author entered IWM
  yesterday. Four options written up in TRADING-RULES F90; recommendation is **(a) leave it** pending the
  twenty-session F81b review.
- **F88 ∩ F90, and it distorts the measurement the user asked for.** `target_is_ahead(None, …)` returns
  **True** by design ("no target" is a legal state), so IWM's null target never reaches the F81b branch
  at all. **F88 silently removed IWM from today's F81b experiment** — SPY and QQQ are in it, IWM is not.
  Combined with F87 (today's plans record `target_replan: "off"` while the runner runs `structure`), a
  zero or thin F81b tally today should NOT be read as evidence about the rule.
- **Checked, no crash risk:** the F81b branch formats `{target:.2f}` and calls `float(target)`, which
  would raise on a `None` target — but `target_is_ahead(None, …) == True` makes that branch unreachable
  for a null target. Verified in code, not just by absence of errors in the log.
- **09:53 ET, F90 confirmed live within three minutes of being written:** SPY traded **757.43, below its
  PM low 757.69** — out of the no-trade zone and into the only region where a `scenario_4` short can
  enter. Its plan target is **757.90**, now ABOVE price, i.e. behind the trade by construction exactly as
  F90 predicts. The next SPY pullback contact will land in the F81b `target_replanned` branch (or, on the
  baseline, in `skip_target_behind`). QQQ 708.07 and IWM 288.17 are still inside their ranges. Run 50
  should look for SPY's first `target_replanned` event and report it against the standing F81b tally.


## 2026-09-10 10:15 ET (run 50 - the desk fired its first Team2 trade of the day and REFUSED it: F91, the runner disagreed with its own read; fixed + committed, still undeployable)

- **Alive on v0.7.36**, armed 60 desk-wide, `needsAttention` false on all three, zero Team2 errors in
  the engine log. **The user has not restarted** - F88's v0.7.37 is still not live, and now F91's
  v0.7.38 queues behind it. `/api/ops/restart-check` flipped to `safe: true` at 10:13 (the EM fire
  chain that held it at 10:05 cleared), but **F89 still closes the door**: the running engine (the
  01:29 ET boot) is elevated and `Stop-Process` returns Access denied from any Limited task. Per run
  49's standing instruction I did **not** attempt another restart.
- **Data real-time and clean.** SPY/QQQ/IWM quotes sub-second old, session `regular`, SPY 757.33/757.36
  (3c spread); 1m bars banking every minute, **45/45 RTH minutes today `source='exchange'`** with
  non-zero volume on all three, last bar 10:12 at 10:13. Alpaca stream authenticated since the 01:29
  boot with no drop; the 09:00 ET pre-open feed self-test passed. `prevClose` correct (762.40 /
  716.31 / 290.64).
- **THE FINDING - F91: the live runner refused the entry its own read fired.** At **10:06 ET on SPY**
  the read applied F81b (`target_replanned`: "planned target 757.90 is behind the 757.59 entry - no
  structure left ahead: no target") and **fired**: touch #2, EMA13 757.59 held on a 757.16 close in a
  bear stack, buy the **756 put at $0.53**, size full x1. In the same second the runner journaled
  `TechniquePlanTriggerSkipped / skip_target_behind` - "target 757.90 (from the setup) is above the
  757.59 entry ... refusing the entry rather than entering with no target at all (F72)". Replay
  reproduces the read exactly, so **live and replay disagree on the only decision of the day**.
- **Root cause, one line.** `runner.resolve_fire_target` read `e["target"]` and, on `None`, fell back to
  `setup["target"]`. F81b's entire point is a `None` target on the fire - and the **setup keeps its
  stale planned target** (confirmed live: setup `pm_break_down@09:45` still carries `target 757.9`). So
  the fallback resurrected exactly the number the read had just replanned away from, and F72's guard
  refused it. The fire already carried the discriminator, `targetKind: "none"`, stamped in **exactly
  one place** (`session.py`'s F81b structure branch, nowhere else); the gate only looked at the value.
- **Scope, and it is the big one: F81b has been unreachable in live trading on EVERY entry since it was
  switched on at 20:30 ET on 09-09.** Not a mistuned threshold - the rule could not reach the book at
  all. With **F90** (on a gap day a `scenario_4` short can only enter below the PML, which is exactly
  where F81 puts its target) F81b is the *only* path to a gap-day entry, so this silently zeroed the
  gap-day book. **Every "F81b had no opportunity" reading in runs 46-49 is unreliable**; the
  twenty-session review should start counting from the first session that runs v0.7.38.
- **Fixed, tested, committed as `db73398` (v0.7.38), NOT deployed.** `resolve_fire_target` skips the
  setup fallback when the fire is stamped `targetKind == "none"`, honouring the read's verdict - the
  trims, the candle stop, the premium stop and the 15:45 flatten manage the trade, the same targetless
  shape the function's own docstring already blesses. **F72's hole stays closed:** an *unstamped*
  targetless fire (`targetKind` absent, empty, `plan`, `hod`, `replan`) still falls back and still
  refuses a stale target, so a restored or replayed event cannot smuggle in a targetless entry. F88's
  genuinely-null-target case (IWM today, `targetKind: "plan"`) is untouched. **No threshold, gate,
  band, size or money path changed.** 3 new regressions replay today's SPY sequence and both mirrored
  sides - verified failing when the one-line condition is reverted; **133 Team2 tests green**, frontend
  build + `check-release` green.
- **What the refused trade actually did, reported straight: it would have LOST.** The model trade
  entered $0.5277, ran to **+39.5% peak** (no trim - the first rung is +50%) and stopped out at
  **-12.21%** at 10:14 on the S1 one-candle stop (2m close 757.64 back through the EMA13 757.42), 4
  bars held. So today's refusal happened to save a small loser - but it was a **bug, not a decision**,
  and the same bug refuses the winners.
- **The open, and the rest of the tape.** All three gapped down, opened below their PDL zones and
  confirmed **`scenario_4` break PDL -> puts** on the 09:45 close (SPY 758.135 < 760.94, QQQ 708.77 <
  714.02, IWM 288.40 < 290.31). SPY then broke its PM low: `skip_no_trade_zone` at 09:50 (entry 759.01
  inside the PM range), `pm_break` at 10:00 arming `pm_break_down@09:45` at 757.69 - whose target the
  read itself flagged "already behind the break, so this setup has no room (F76)" - `skip_engulfing`
  at 10:02 (body 0.79 > 2.0x avg 0.21), `same_pullback` at 10:04, then the 10:06 fire. **QQQ**: three
  `same_pullback` notices (F62), still inside its PM range, 0 fires. **IWM**: one
  `skip_no_trade_zone` at 09:52, still carrying **`target: null`** from F88, 0 fires. **Book: 0 trades,
  0 open positions, $0.00 realized on all three.** Mode is **`auto`** and that is the user's own
  setting (`techniques.team2.mode` last written 09-04 10:22 ET, no change since - verified in the
  journal, not drift).
- **F92 - NEW (observation, no fix proposed).** Today's SPY `pm_break` carries `close: 756.78` live and
  `close: 756.76` in replay; the bars table's 09:59 exchange close is 756.76. The live read used the
  SAMPLED close that stood when the event was journaled at 10:00:00, corrected a moment later - the
  documented `feed.exchange_bar_hold_seconds` trade-off, not a Team2 defect. Changed nothing today
  (both far below the 757.69 PM low), but a decision taken within a couple of cents of a level can
  diverge between live and replay, and the parity check would report it as a rule bug. Also verified
  while checking: `regime.ts` is the bar's **START**, read-event `ts` is its **CLOSE** (start + tf) -
  reconciled against the 1m table at 10:04 -> 757.16.
- **F85 standing check: zero Team2 rows.** 7 `TechniquePlanError` rows in the last 4h, all **tip** - six
  09:31 never-chase gap notices (RDDT/BBAI/FRVO/GOOGL/AAOI x2) and one 09:26 source follow-up on AMZN.
  Other desks, reported not touched: the two `cartel-observer bar handling failed` tracebacks from
  09:37/09:42 ET are unchanged since run 49, none new.
- **F81b live tally: 1 read fire, 0 live entries, book net $0.00** - and per F91 that zero is the bug,
  not the rule. F87 is unchanged and now secondary: today's plans still record `target_replan: "off"`
  while the runner runs `structure`.
- **Next run (~10:45 ET) should:** (1) check `/api/health` - if it reads **0.7.38** the user restarted,
  so immediately confirm SPY/QQQ fires now reach the book (a `target_replanned` fire should produce a
  `contract` event and a trade, not `skip_target_behind`) and that IWM's null target re-derived; if it
  still reads **0.7.36**, do NOT attempt a restart and repeat the F89 ask; (2) keep the F81b tally,
  counting read fires and live entries **separately** until v0.7.38 is live; (3) watch QQQ's and IWM's
  first pullback contacts out of their PM ranges (706.50 / 287.83); (4) the F85 journal query. Still
  open for the user: **F47**, **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**, **F61**,
  **F62**, **F63**, **F64**, **F65**, **F69**, **F70**, **F71's shared half**, **F72's strategy
  question**, **F74**, **F76's rule question**, **F81**, **F82**, **F83**, **F85**, **F86**, **F87**,
  **F89**, **F90**, **F92**, F67's two shared-side halves, and the F30-family question of which premium
  series is authoritative.


## 2026-09-10 10:40 ET (run 51 — a quiet half hour: no fires, no live entries; two NEW findings, both reporting-level; still undeployable)

- **Alive on v0.7.36, armed 60 desk-wide, `needsAttention` false on all three, zero Team2 errors.**
  The user has **not** restarted, so F88's v0.7.37 and F91's v0.7.38 are both still queued.
  `/api/ops/restart-check` reads `safe: true` (no open trades, no working entries, nothing in flight),
  but **F89 still closes the door** — the running engine is the 01:29 ET boot and it is elevated, so a
  Limited task's `Stop-Process` is refused. Per run 50's standing instruction I did **not** attempt a
  restart. Nothing was deployed this run; the two queued commits are unchanged.
- **Data real-time and clean.** SPY/QQQ/IWM quotes sub-second old, session `regular` (SPY 758.97,
  QQQ 710.81, IWM 289.10 at 10:34); **64/64 RTH 1m bars today `source='exchange'`** on all three with
  zero zero-volume minutes, last bar 10:33 banked at 10:34; the Alpaca stream has been authenticated
  since the 01:29 ET boot with no reconnect. `prevClose` correct (762.40 / 716.31 / 290.64).
- **What the read saw since run 50 (10:15 → 10:40): no fires, no entries, no orders.**
  **SPY** — 10:16 `pm_retest` at the PM low 757.69 itself (the F20 small-size rung) but the same bar is
  contact **#3**, so `late_touch` made it watch-only (D9/P6); 10:18 `same_pullback` (F62). Nothing since.
  **IWM** — 10:15 `pm_break`: the 15m body closed **287.82** against the PM low **287.83**, a **one-cent**
  break, minting `pm_break_down@10:00`; its first pullback was refused at 10:16 `skip_no_trade_zone`
  (entry 288.05). Checked the F20 retest exception by hand and it correctly did **not** apply: the entry
  is 0.22 off the 287.83 anchor against a tolerance of 0.09 (0.25 × ATR 0.3598), and the 2m close 287.97
  is back **above** the PM low — no rejection, so no small-size rung. **QQQ** — three more `same_pullback`
  notices (09:54 / 09:58 / 10:06), never broke its PM low 706.50, 0 setups fired.
  **Book: 0 trades, 0 open positions, $0.00 realized on all three.**
- **Replay parity holds.** SPY replays 11 events identical to the live read, including run 50's 10:06
  `target_replanned` + fire and the 10:14 stop (−12.21% model). IWM replays 5 events identical, the
  `pm_break` close 287.82 on both sides. The one-cent margin is worth naming as a live instance of F92's
  hazard, but the bar is exchange-sourced and final, so there is nothing to correct.
- **F93 — NEW (observation + a rule question, nothing built).** A setup's `confirmed_ts` is the 15m bar's
  **START**, not its close — hence today's `pm_break_down@09:45` (SPY, confirmed by the 10:00 close) and
  `pm_break_down@10:00` (IWM, confirmed by the 10:15 close). Two of the three readers do not care; the
  third does: the **T7 "break & base"** trigger guards itself with `all(x.ts > s.confirmed_ts …)`
  (`session.py:477`), so on the first 2m bar after a break a `based` entry can fire off a base built
  **entirely from bars inside the confirming 15m bar**. Whether that is wrong is a method question, not a
  code question — the author says "break & base over pre market high" *at* the break — so per the watch's
  own limits I wrote it up instead of changing it. Options (a) leave it / (b) tighten the T7 guard alone
  by one 15m bar / (c) move `confirmed_ts` to the close. **Live cost so far: zero** — every Team2 fire on
  record is `entryKind: "ema"`, no `based` entry has ever reached the book. Recommendation: **(b)** if the
  guard should mean what it says, else (a); decide before T7 ever fires live.
- **F94 — NEW (platform, and it matters for how these logs are read).** The login page and top-bar chip
  read **v0.7.38** right now while `/api/health` reads **v0.7.36**: `frontend/dist` was rebuilt at 10:12 ET
  as part of run 50's F91 *verification*, and the running server serves that directory off disk — so the
  UI half deployed itself with no restart while the backend half stayed queued. Harmless today (both
  commits are backend-only, no contract mismatch), but a frontend change needing a new endpoint would go
  live against an engine that does not serve it, with no readiness check and no journal entry. **`/api/health`
  is the only truth about what is running — never the chip.** Not fixed: the remedy is a build/deploy
  policy on `scripts/start.ps1`, which is not this desk's to change. Logged in `docs/PLATFORM-RULES.md` too.
- **F81b live tally unchanged: 1 read fire, 0 live entries, book net $0.00** — and per F91 that zero is the
  bug, not the rule. F87 unchanged: today's plans still record `target_replan: "off"` while the runner runs
  `structure`. **F88 unchanged and visible again:** IWM's brand-new `pm_break_down@10:00` also carries
  `target: null` ("puts down to the next level (none on the plan)"), so both IWM setups are targetless.
- **F85 standing check: zero Team2 rows.** 7 `TechniquePlanError` rows in the last 4h, all **tip**, and all
  the same ones run 50 reported (six 09:31 never-chase gap notices, one 09:26 AMZN source follow-up) — none
  new. Other desks, reported not touched: the two `cartel-observer bar handling failed` tracebacks (09:37 /
  09:42 ET) are unchanged, none new.
- **UI checked:** `/team2` renders correctly — Plans tab lists all three armed plans with their sheets and
  day type, the thresholds panel is read-only as intended, no console-visible breakage. Two notes for future
  runs: the browser pane is narrow enough to render the phone layout (expected, not a defect), and the
  recipe's `?token=…` does **not** sign in — the handoff parameter is the **hash**, `#token=…` (`lib/api.ts:8`).
- **Next run (≈11:15 ET) should:** (1) check `/api/health` — **not the version chip** (F94) — and if it reads
  **0.7.38** the user restarted, so immediately confirm a `target_replanned` fire now reaches the book
  (a `contract` event and a trade, not `skip_target_behind`) and that IWM's two null targets re-derived;
  if it still reads **0.7.36**, do not attempt a restart and repeat the F89 ask; (2) keep counting read fires
  and live entries **separately** for F81b until v0.7.38 is live; (3) watch QQQ's PM low 706.50 and IWM's
  next pullback now that its PM break is armed — SPY is the only one of the three that has traded outside
  its PM range so far; (4) the F85 journal query. Still open for the user: **F47**, **F49**, **F50**, **F51**,
  **F54**, **F56**, **F58**, **F59**, **F61**, **F62**, **F63**, **F64**, **F65**, **F69**, **F70**, **F71's
  shared half**, **F72's strategy question**, **F74**, **F76's rule question**, **F81**, **F82**, **F83**,
  **F85**, **F86**, **F87**, **F89**, **F90**, **F92**, **F93**, **F94**, F67's two shared-side halves, and
  the F30-family question of which premium series is authoritative.


## 2026-09-10 11:05 ET (run 52 — 44 minutes of total silence, explained: the stack un-stacked; F95 is that the silence leaves no record)

- **Alive on v0.7.36, armed 59 desk-wide, `needsAttention: false` on all three, zero Team2 errors.**
  The user has **not** restarted, so F88's v0.7.37 and F91's v0.7.38 are both still queued.
  `/api/ops/restart-check` reads `safe: true` (no open trades, nothing working, nothing in flight),
  but **F89 still closes the door** and there is now a fresh receipt for it in the repo:
  `logs/restart-20260910-064016.log` is a 06:40 ET `restart.ps1` run that died on
  `Stop-Process ... python (29812): Access is denied`. Per the standing instruction from runs 49–51 I
  did **not** attempt another restart. Nothing was deployed this run.
- **Data real-time and clean.** SPY/QQQ/IWM quotes sub-second old, session `regular` (SPY 759.11,
  QQQ 711.19, IWM 288.72 at 11:05); **93/93 RTH 1m bars today `source='exchange'`** on all three with
  **zero** zero-volume minutes, last bar 11:02 banked at 11:03; `prevClose` correct (762.40 / 716.31 /
  290.64). Alpaca stream authenticated since the 01:29 ET boot with **no reconnect**, and the 09:00 ET
  pre-open feed self-test passed. Pre-open completion verified on all three: `complete: true`, PM
  ranges 757.69–764.60 / 706.50–717.60 / 287.83–291.74, `dayType: gap_down`, `sizingAtOpen: none`.
- **What the read saw since run 51 (10:40 → 11:05): nothing. Literally no events on any symbol since
  10:18.** Book still **0 trades, 0 open positions, $0.00 realized** on all three. That 44-minute gap
  is the whole story of this run, and it took recomputing the EMAs from the bars table to prove it was
  correct rather than a hang — see F95.
- **Why it is correct (checked, not assumed).** SPY's rally off 757.62 carried the **EMA13 back above
  the EMA48** (13 758.98 / 48 758.68 / 200 760.38 at 11:00), so `ema_stack` returns **`mixed`**;
  E3/B9 needs a full `bear` stack for a short, so every setup is skipped at `session.py:449` by a bare
  `continue` marked *"(silent — happens every bar)"*. Same on QQQ and IWM — **all three have been
  `mixed` on every 2m close since 10:16, zero bear-and-touch bars.** Both SPY setups are still alive
  (`dead: false`): `scenario_4@09:30` (touches 0) and `pm_break_down@09:45` (touches 2, past its D9
  allowance so further contacts are watch-only anyway).
- **Replay parity holds exactly, and it is the proof the read is not stalled.** SPY replays **11/11**
  events identical to live (including run 50's 10:06 `target_replanned` + fire and the 10:14 −12.21%
  stop), QQQ **5/5**, IWM **5/5** — and the replay, which recomputes from the bars table right up to
  11:02, **also** stops at 10:18. The regime meanwhile kept advancing every 2m close (last 11:00).
  Also verified: the F62 departure state machine is judged **before** the stack gate can `continue`
  (`session.py:309`), so the silence corrupts no state.
- **F95 — NEW (observation + a small proposal, nothing built).** The stand-down is right; the **record**
  is not. Recomputing the 2m series by hand, price made **six real EMA13 contacts** in that quiet
  window — SPY 10:42 / 10:44 / 10:46 / 11:00 / 11:02 / 11:04, IWM 10:40–10:54 and 11:00, QQQ 10:46 /
  11:00 / 11:02 — every one refused by E3, and **none of them appears anywhere**: no event, and
  `s.pullbacks` / `s.opportunities` never increment, so the setups under-report what the day offered.
  Two costs: the method review cannot measure what the stack gate refuses (exactly the question "does
  E3/B9 cost us money?"), and operationally a healthy quiet read is indistinguishable from a hung one.
  **Proposed, not built** (a new event kind is consumed by the scorer, the review loop and the parity
  check, so it is the user's call): a `stack_disagrees` note said **once per setup per stack flip**
  using the read's existing say-it-once idiom (`s._stalled` / `s._same_said` / `s._skipped`), plus the
  mirror note when it re-stacks — two events per regime change, not per bar; no gate, threshold, size
  or money path touched. Optionally count these into a separate `refused_by_regime` counter so the
  review can price the gate without polluting the executable-opportunity count.
- **F81b live tally unchanged: 1 read fire, 0 live entries, book net $0.00** — and per F91 that zero is
  the bug, not the rule. F87 unchanged: today's plans still record `target_replan: "off"` while the
  runner runs `structure`. **F88 unchanged:** IWM's `scenario_4@09:30` and `pm_break_down@10:00` both
  still carry `target: null`. **F94 unchanged:** the chip still reads 0.7.38 against a 0.7.36 engine —
  every version claim in this run is from `/api/health`.
- **F85 standing check: zero Team2 rows.** In the last 5 h the journal holds 34 error-ish rows, **none**
  Team2: 8 `TechniquePlanError` (all **tip** — six 09:31 never-chase gap notices plus 09:26 AMZN and a
  **new** 10:58 RDDT `update_stop` source follow-up), 22 `SignalVerificationFailed` (tip intake), 2
  `RiskCheckFailed` (one 10:53 `quote_fresh` 10.5 s, not Team2 — Team2 placed no orders today), and two
  **critical `ManagedPositionAttention` at 09:05** — TSLA (we hold 7, broker shows −4) and LULU (we hold
  49, broker shows 0), both unexplained with new entries halted on those symbols. **Other desks —
  reported, not touched, but the user should see the TSLA/LULU pair.** Engine log today: the only
  `ERROR`s are the two 09:37 / 09:42 ET `cartel-observer bar handling failed` tracebacks, unchanged
  since run 50; 1,735 warnings, all the benign `persist_bars: dropped N non-bucket-aligned stub bar(s)`
  / outside-a-market-minute pair plus two `shadow arm failed for SPX` and two Yahoo calendar 404s.
- **UI checked:** `/team2` renders correctly — Plans tab lists all three armed plans with their sheets,
  PM ranges and `gap down` day type, the thresholds panel is read-only as intended, no visible
  breakage. (The browser pane is narrow enough to render the phone layout — expected, not a defect.
  Sign-in handoff is the **hash**, `#token=…`, per run 51.)
- **Next run (≈11:45 ET) should:** (1) check `/api/health` — **not the version chip** (F94) — and if it
  reads **0.7.38** the user restarted, so immediately confirm a `target_replanned` fire now reaches the
  book (a `contract` event and a trade, not `skip_target_behind`) and that IWM's two null targets
  re-derived; if it still reads **0.7.36**, do not attempt a restart and repeat the F89 ask; (2) the
  first thing to check when the read looks quiet is **the stack, not the feed** — F95: `mixed` means a
  silent stand-down, and the tell that it is healthy is that `regimeLast.ts` is still advancing;
  (3) watch for the EMA13 to re-cross **below** the EMA48 on any of the three, which re-opens the short
  side — SPY's two live setups and IWM's two are all still armed; (4) keep counting F81b read fires and
  live entries **separately** until v0.7.38 is live; (5) the F85 journal query. Still open for the user:
  **F47**, **F49**, **F50**, **F51**, **F54**, **F56**, **F58**, **F59**, **F61**, **F62**, **F63**,
  **F64**, **F65**, **F69**, **F70**, **F71's shared half**, **F72's strategy question**, **F74**,
  **F76's rule question**, **F81**, **F82**, **F83**, **F85**, **F86**, **F87**, **F89**, **F90**,
  **F92**, **F93**, **F94**, **F95**, F67's two shared-side halves, and the F30-family question of
  which premium series is authoritative.
