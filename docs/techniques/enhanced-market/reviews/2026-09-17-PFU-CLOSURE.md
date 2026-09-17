# EM closure - September 17 preparation follow-up review (PFU-01..PFU-04)

Review: `C:/Cursor/zargar-codex/docs/techniques/enhanced-market/reviews/2026-09-17-PREPARATION-FOLLOWUP-REVIEW.md`
(reviewed code c74df44, records cd3aa95). **Code SHA (the PFU changes): `47275c3f8ff02c857b46b431e71b3300ec0eea67`. Integrated SHA based on the CURRENT runtime:
`e048f5afaf5a0c23b22630e5713f80bea0be074a`** on `claude/technique-review-trade-plan-fbb9ba` - version **0.8.03** (the Team2 desk took 0.8.02 with PR #193
while this closure was being written and deployed it at 19:57 PT; the EM block was renumbered, nobody's shipped block
rewritten). Ancestors of `e048f5afaf5a0c23b22630e5713f80bea0be074a`: the running checkout `ed88f25` (= v0.8.02 build ed88f254, live since 19:57 PT) and
`origin/main` fbe3fd6. Frontend build + check-release "Release 0.8.03 ... agree" on that tree. Nothing was deployed; the runtime is v0.8.01 build 3f5675d and keeps baseline Practice
trading, the deterministic entry and observation-only collection unchanged.

## Per finding

| ID | Change | Acceptance (focused) | Status |
|---|---|---|---|
| PFU-01 watchdog | Pure classification module `scripts/watchdog-classify.ps1`; `scripts/watchdog.ps1` policy: 2-of-3 probes (12 s), `live-unhealthy` refuses ordinary recovery (exit 2) and escalates once per stall marker (Telegram + log with the human next step, `ZargarRestartOverride`), `absent` takes the existing DOWN path, `-ProbeOnly` read-only; identity bound to the pid the engine stamps in `logs/engine.pid` (engine.start), venv path as fallback with the identity logged; marker cleared on ANY successful probe; persistence is time-based (180-600 s), stale markers reset. | `scripts/tests/watchdog-classify.tests.ps1` 8/8: first-probe recovery clears an old marker; unrelated stalls do not chain; rapid invocations do not persist; live process + old log = absent; unbound process (0) = absent even with a fresh log; read-only changes no state. Parse-checked; `-ProbeOnly` run against the live engine (healthy, no marker written). | BUILT on the branch; NOT merged to the shared protocol; owner (Tips desk) agrees with direction, integration waits for the user; not deployed. |
| PFU-02 P-04 | `sacrificedWinners` -> `underlyingTp1FirstRefused` (descriptive); waiting-policy claim withdrawn; new PAIRED comparison `confirmation_pair`: first completed close beyond the level within 10 bars, entry at the next bar OPEN, unchanged gates (stop side, room, frozen R2 >= 3.0 at the exit rung), underlying TP1 vs stop; outcomes distinct (`no_confirmation`, `refused_*`, `unknown (...)`, `tp1_first`, `stop_first`, `unresolved`); option dollars unknown; baseline winners and losers both kept. | `tests/test_em_profitability_p04_p05.py`: budget-refused TP1 touch is not a sacrificed winner; delayed entry with no room / low R2 refused separately; no same-close fill (no next bar = unknown); bar gaps unknown; paired summary keeps 1 winner + 1 loser and marks option dollars unknown; the summary's baseline block is not clobbered (regression found in the real report and fixed). | BUILT, collecting (order-free, in the daily report); descriptive until >= 30 paired rows. |
| PFU-03 P-05 | Labels from `marketstructure.sessions.session_window` on tz-aware fire times (`sessions-v1`), runner label kept as a diagnostic; `EVENT_CALENDAR` with label, ET time, source, retrospective flag; `pre_event`/`post_event`/`unknown_calendar`. | 10:45 ET = midday not afternoon; 13:59 pre / 14:00 post around FOMC; a date without an entry = `unknown_calendar`; render says "never a trading-window rule". | BUILT, collecting; descriptive. |
| PFU-04 cooldown | `CboeClient(cooldown_s=)` + `cooldown_s` used for both cooldown sites; `OptionsService.provider()` reads `options.cboe_cooldown_seconds` on every call (live-editable); wording: background cooldown with bounded retry, no capacity reservation, freshness/risk refusals preserved. | `tests/test_em_cboe_cooldown_setting.py`: non-default 5 s reaches the client and follows a later edit to 7.5 s; a 429 starts a 5 s cooldown, not 20 s. | BUILT; not deployed. |

## Results on the integrated tree (`47275c3f8ff02c857b46b431e71b3300ec0eea67`)

- Import smoke ok (0.8.02). EM reviewer set + follow-ups + API + separation + options freshness: **101 passed, 5 skipped**;
  profitability/cohort suites after the baseline-block fix: 11 passed; `test_technique_api` + loop watch after the pid
  stamp: see the status report. Arming solo on the merged tree: reported separately (load-sensitive, foreground).
- Frontend build + check-release: "Release 0.8.02 ... agree" (EM block renumbered from the superseded 0.7.99 draft;
  nobody's shipped block rewritten).
- Reports regenerated with the corrected tables: `research/profitability/2026-09-15.md`, `2026-09-16.md`.

## Built / merged / deployed / collecting / evaluated

- BUILT: all four findings, on the EM branch.
- MERGED: into the EM branch only (main + runtime 3f5675d merged IN; nothing merged OUT to main yet - a PR follows the
  user's word).
- DEPLOYED: **v0.8.03 build `d3091ae468a52ba410b93a76772688d86537ecc3` at 20:25 PT 2026-09-16 on the user's "do it all"** (readiness safe,
  market closed, 0 open trades; `deploy.ps1` under the lease -> `ZargarRestart` task; receipt phase `verified`, expected/healthy 0.8.03;
  restoration by hand: 72 armed before and after by id - enhanced_market 58, options_cartel 1, team2 3, tip 10 - 0 missing, 0 new;
  resting orders 26 -> 26; open trades 0 -> 0). On the new build: 58 EM arms effective `deterministic`, evidence off; settings intact;
  `/api/health.local.delivery` now reports `eventLoopLagMs` 15.4, `loopStalls` 0; `logs/engine.pid` stamped (65008); one engine pair,
  gateway and ingest alive, intake live. The watchdog classification is LIVE by construction (the scheduled task reads
  `scripts/watchdog.ps1` from the checkout): acceptance 8/8 and `-ProbeOnly` = healthy from the runtime checkout. The user decided
  this after the owner coordination; the Tips desk's pre-open note carries the evidence. No restart for research labels; the dirty build string
  is the runtime checkout's untracked EM research artifacts, which are committed on the EM branch.
- DEPLOYED (2): v0.8.04 build 66e85f6 at 20:56 PT - the two stall causes the watch named (queued logging, off-loop provider JSON) and the healthy-tick marker clearing; restoration 72/72 by id, DB pool alive, 0 stalls after start. TRADING-RULES 2026-09-16 20:29-20:56.
- DEPLOYED (3): v0.8.04 build 662a8e6 at 21:04 PT - chain normalisation + enrichment index off the loop (stall #2 on 66e85f6, 4.8 s); restoration 72/72. FINAL live runtime tonight: 662a8e6.
- COLLECTING: P-02 (observer ON), P-04b paired, P-05 labels - order-free, in the daily report.
- EVALUATED: P-02 one comparable row (CRWV 09-16 +$61.03 vs production), five unknown for lack of covered observations;
  P-04b two sessions: 12 of 13 variants refused or unconfirmed, 1 stopped; P-03 friction 6-10% on filled options.
  None of it is a verdict; thresholds unchanged.

## Tomorrow (2026-09-17)

- 58 EM arms verified against the current runtime (ids, book EM Practice, session 2026-09-17, effective deterministic,
  evidence off); helpers alive; observation settings on; pre-open re-plan at 09:25 ET. Attending owner for the 06:20 PT
  review: this session (session-local cron) - it must stay open, or the user assigns another.
- Overnight affordability/spread/expiry counts are preparation diagnostics only; the pick judges the CURRENT quote with
  the existing gates; fresh refusal reasons will be reported separately from the overnight estimates.
- Research load: the Cartel research sweep on the live engine (80-180 runs/min on 09-16) belongs to that desk / the
  platform owner; off-loop rendering does not solve CPU/RAM contention.
