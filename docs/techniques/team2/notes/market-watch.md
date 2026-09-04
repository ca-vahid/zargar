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
