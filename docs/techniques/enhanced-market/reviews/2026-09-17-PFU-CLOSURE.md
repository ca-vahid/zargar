# EM closure - September 17 preparation follow-up review (PFU-01..PFU-04) and its re-review

Reviews answered: `2026-09-17-PREPARATION-FOLLOWUP-REVIEW.md` (PFU-01..04, reviewed code c74df44) and
`2026-09-17-PFU-CLOSURE-REREVIEW.md` (re-review of e048f5a / d3091ae), both in the reviewer workspace
`C:/Cursor/zargar-codex/docs/techniques/enhanced-market/reviews/`.

## The one tested candidate

**Code SHA: `3d458d0d93f5ad54e208c21f3bdef73fd20bd4f0`** on `claude/technique-review-trade-plan-fbb9ba`, version **0.8.06**.
Ancestors: the running checkout `f331345` (= v0.8.05, the other desks' convergence) and `origin/main` 1a5b2b8. This
closure record is committed on top of it; the deployment section below names the build that went live. Every result
in "Results" was run on this tree; earlier trees are listed under "History" and are not claimed for it.

### Results on `3d458d0` (2026-09-16 21:20-21:35 PT, private test databases, foreground, one file at a time)

| Check | Result |
|---|---|
| Import smoke (`zargar.api.app`, `zargar.main`, options service, profitability tool) | ok, 0.8.06 |
| Watchdog: parse-check `scripts/watchdog.ps1` + `scripts/watchdog-classify.ps1` | 0 errors |
| Watchdog: `scripts/tests/watchdog-classify.tests.ps1` (pure classifier 9 cases + mocked CALLER decision 11 cases) | 20/20 |
| `-ProbeOnly` run from a checkout WITHOUT a `logs/` directory | stdout only, no directory created, no log or marker written |
| EM reviewer / deterministic / evidence / profitability / follow-up / separation suites (24 files) | 82 passed, 5 skipped |
| Arming solo (`test_technique_arming.py`) | 30 passed, 1 failed = the known baseline `test_auto_options_one_contract_lifecycle` |
| Frontend `npm run build` + check-release | "Release 0.8.06 ... agree", built |

Known, unrelated to these changes: `test_technique_api.py::test_chart_png_endpoint_on_sim_symbol` fails only after
other tests in its file (the shared Yahoo history httpx client reuses a closed loop); it passes alone.

## Per finding

| ID | Change on `3d458d0` | Acceptance | Status |
|---|---|---|---|
| PFU-01 / re-review 1 - watchdog | `scripts/watchdog-classify.ps1`: `Get-EngineClassification` -> healthy / **live-unhealthy** / **uncertain** / absent. A live process with a stale or missing log is LIVE (log inactivity never proves absence); a process-discovery failure (-1) is UNCERTAIN; only "discovery worked, zero bound processes" is absent. `Invoke-WatchdogDecision` is the CALLER decision as a pure function over injected actions (probe, sleep, liveness, marker read/set/clear, log, alert, now): `-Force` alone never bypasses an unavailable readiness (refuse, exit 2); only `-Override` proceeds and is logged as OVERRIDE; a healthy first probe clears the marker AND the alert companion; `-ProbeOnly` returns without any mutation. `scripts/watchdog.ps1` only supplies the real actions and maps the decision to exit codes / `$up`; it creates no `logs/` directory and writes no log line under `-ProbeOnly`. Identity: the pid the engine stamps in `logs/engine.pid` (alive + `zargar.main` command line), venv path only as a logged fallback; CIM errors return -1. | 20/20 mocked cases: live+stale log refuses and alerts once; the refusal names `ZargarRestartOverride`; `-Force` alone refuses; `-Force -Override` proceeds as OVERRIDE; first-probe recovery clears marker+alert; discovery failure refuses (never proceed-down); ProbeOnly mutates nothing in healthy / live-unhealthy / absent branches; absent proceeds down and clears the marker; late probe + `-Force` proceeds with readiness available. No real restart exercised. | BUILT and tested on the branch. Owner (Tips desk / start path) agreed with the direction and defers integration into the shared protocol to the user; the user decided "do it all" - see Deployment. |
| PFU-02 / re-review 2 - paired confirmation | `em_profitability.confirmation_pair` scans the underlying FROM THE ENTRY BAR (the reviewer's reproduction - entry 101, entry minute high 106, next close 98 - now reads `tp1_first`); an incomplete horizon is `pending (horizon incomplete: n of 10 bars observed)` unless the session's last bar closed it; the firing (touch) bar never qualifies as the confirming close (frozen, stated); the result is labelled `geometry_only_underlying_proxy` with `gatesNotEvaluated` = quote quality/freshness, premium sizing / quantity-dependent exit rung, never-chase cap, timing window, admission and daily-loss budgets; short mirror added. `underlyingTp1FirstRefused` stays descriptive. | `tests/test_em_confirmation_pair_rereview.py` (5) + `test_em_profitability_p04_p05.py` (6): reviewer reproduction; same-bar target+stop on the entry bar = unknown; short mirror incl. `refused_stop_side`; one observed bar with hours left = pending, the same bar as the session's last = `no_confirmation`, a full window = `no_confirmation`; firing bar beyond the level does not confirm; baseline block intact; option dollars unknown. | BUILT; reports regenerated (below). The earlier claim that "waiting for the close costs room faster than it saves stops" is WITHDRAWN; two retrospective sessions are exploratory. |
| PFU-03 - P-05 labels | Unchanged from the first closure (shared session clock on tz-aware fire times, pre/post/unknown event phase, `unknown_calendar` coverage). Accepted by the re-review at source level. | as before | BUILT |
| PFU-04 - cooldown | Unchanged from the first closure (`options.cboe_cooldown_seconds` wired, live-editable; wording "background cooldown with bounded retry"). Accepted. | as before | BUILT |
| re-review 3 - record consistency | This document rewritten around ONE tested candidate; runtime collection and offline report generation separated below; no placeholders. | - | DONE |

## Collection versus report generation (kept separate)

- **Runtime collection (production, automatic):** the engine journals `TechniqueEntryDecision` per deterministic attempt
  and `TechniqueExitShadow` observations when `techniques.enhanced_market.shadow_exit_observe=True` /
  `shadow_p02_candidate=True` (ON for EM Practice since 2026-09-15 14:06 PT, unchanged). Nothing in this closure changes
  what the runtime collects.
- **Offline report generation (a person runs it; NOT automatic in production):** `python -m zargar.tools.em_profitability
  report --date YYYY-MM-DD`, owner = the EM desk session, executed from the EM worktree
  `C:/Cursor/zargar/.claude/worktrees/technique-review-trade-plan-fbb9ba/backend` against the runtime database
  (read-only), tool version `profitability-cohorts-v1` + addendum `p04-p05-2026-09-17`, on code `0126164` (the
  re-review fix commit inside `3d458d0`). Outputs: `research/profitability/2026-09-15.md` / `.json` and
  `research/profitability/2026-09-16.md` / `.json`, written 2026-09-16 21:15 PT, committed on the branch. The P-04b and
  P-05 tables exist only in these offline files until a person regenerates them.
- **Runtime P-02 comparison vs offline P-04/P-05:** P-02 uses the runtime's own observations (collected live); P-04/P-05
  are computed offline from journal rows and bars. "Nothing deployed" for a report change is therefore compatible with
  regenerated files; a deploy changes the runtime collection or the code the offline tool runs, never the files.

### Regenerated paired results (exploratory, 2 retrospective sessions; not a verdict)

- 2026-09-15: 8 P-01 attempts -> `refused_r2` 6, `stop_first` 2 (IREN b1, AMAT b2, -1R each on the underlying proxy);
  baseline winners/losers kept 1/4; option dollars at the delayed entry unknown for 6 of 8.
- 2026-09-16: 6 P-01 attempts -> `refused_r2` 5, `no_confirmation` 1 (CRCL b1); baseline winners/losers kept 1/3.
- No `pending` rows: both sessions were complete at generation time.

## Deployment record

Earlier tonight (all on the user's "do it all"): v0.8.03 build d3091ae at 20:25 PT; v0.8.04 build 66e85f6 at 20:56 PT
(queued logging, off-loop provider JSON); v0.8.04 build 662a8e6 at 21:04 PT (off-loop chain normalisation). Each
through `deploy.ps1` under the lease + the `ZargarRestart` task, receipt verified, restoration 72/72 by id.

**This candidate - DEPLOYED 2026-09-16 21:26 PT as v0.8.06 build `152ebd4601f310ec3e7d2700b3d4f62d40007161`** (= code
`3d458d0` + this closure record; the user's standing "do it all"): readiness safe (market closed, 0 open trades);
`deploy.ps1` under the lease -> `ZargarRestart` task; receipt phase `verified`, expected/healthy 0.8.06; restoration by
hand against `logs/restart-inventory-20260916-212457.json`: 72 armed before and after by id (enhanced_market 58,
options_cartel 1, team2 3, tip 10), 0 missing, 0 new; resting orders 26 -> 26; open trades 0 -> 0. From the runtime
checkout after the swap: `scripts/tests/watchdog-classify.tests.ps1` 20/20, `watchdog.ps1 -ProbeOnly` = healthy
(stdout only). The corrected watchdog is therefore what the `ZargarWatchdog` task runs from now on.

## Follow-up after the re-review acceptance (2026-09-16 22:05 PT)

The reviewers accepted the blocker corrections and asked for one more horizon case: distinguish the REPORT cutoff from the
actual session close. Done on the branch after `e772c42` (0.8.09 block, next normal release, not deployed tonight):
`confirmation_pair(..., session_close_ms=None)` closes an incomplete horizon only when the last observed bar is the
session's last bar (`session_close_of` = 16:00 ET on the firing day); a 10:02 ET report with one observed bar is
`pending`. Case: `tests/test_em_confirmation_pair_rereview.py::test_intraday_report_cutoff_is_not_the_session_close`
(11 passed with the existing file). Watchdog refusals are monitored by the EM desk session's review tick (Telegram stays
unconfigured); research volume on the live engine is reported per tick and flagged during market hours.

## History (earlier trees, for the record only)

- `47275c3` / `e048f5a` / `d3091ae`: first PFU closure (reviewed by the re-review); its watchdog classifier treated a
  live process with a stale log as absent and the caller skipped readiness under `-Force` - both corrected above.
- `c74df44`: the execution follow-ups (stall watch, off-loop rendering, CBOE priority) reviewed by the first review.

## Scope kept

No repeat preparation batch (58 EM arms for 2026-09-17 unchanged, all effective deterministic, evidence off), no strategy
activation, no risk / chase / threshold change, the 8% friction marker stays a marker, observation collection unchanged.
The CRWV earlier-exit result remains a modeled observation.
