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
