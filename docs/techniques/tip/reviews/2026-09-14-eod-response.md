# Tips EOD review 2026-09-14 — development response (v0.7.73)

Review: `C:/Cursor/zargar-codex/docs/techniques/tip/reviews/2026-09-14-eod-review.md`
(published code reviewed `5188956`). All five reviewer regression files adopted verbatim into
`backend/tests/` (`test_tip_eod_20260914_{gates,delivery,knowledge,simulation,restart}.py`,
10 checks); own follow-ups in `test_tip_eod_20260914_followup.py` (3).

## Operational actions (live, journaled, no settings changed)

| Action | Evidence |
|---|---|
| The four obsolete `repeated_pre_entry_failure` incidents (`760309ca`, `df02e34a`, `2e87b5bf`, `4e93b293`) released through `POST /api/tip/incidents/{id}/resolve` at the examined revision | the release predicate found the enforced pre-entry successes after each incident (events 99536 MRNA 17:14:40 ET, 99718 AFRM 17:29:01 ET); 200 each, 0 open |
| The three retro-promoted rules (`e02fbae2`, `e7a30cb4`, `2c8ed73d`) quarantined via `POST /api/tip/notes/{id}/dispute` | journaled; evidence preserved; they render as PENDING REVIEW, are never superseded, and await a person |
| Research quarantine of the corrupted shadow books | `POST /api/portfolios/{id}/quarantine` on `ab` (armed) and `eva` (armed) after the deploy — see below |

## Findings → fixes

| Id | Fix | Acceptance |
|---|---|---|
| EOD-01 | Gateway: `_last_frame`/`_last_dispatch`/per-channel `_chan_last` watermarks, `gateway_status.json` every 30 s, idle watchdog (`--idle-seconds` 180: no frame → close → reconnect → READY gap recovery), `--log-file logs/discord-gateway.log` tee (rotated). App: `techniques/tip/intake_liveness.py` (`liveness()`, `GET /api/tip/intake/liveness`, `monitor_loop` journaling `TipIntakeStalled`/`TipIntakeRecovered` 04:00–20:00 ET). Desk sweep prints it. | `test_liveness_distinguishes_a_live_pipe_from_a_stuck_one`: unknown / live / stuck pipe / hung process / pending backlog |
| EOD-01 trace | Mirror receipts: 15 in the 12:30 bucket, none 13:00–16:59, 665 at 17:30. The gateway restarted with the app at 11:52 and again at 16:12 (team2's deploy); the 16:13 instance produced its first receipts at 17:13. Console-only logging left no record of the 12:35–16:12 silence — that is what the status file and file log fix. Root cause NOT proven (heartbeat ACKs may have flowed on a session that delivered no dispatches; the 16:13→17:13 latency is consistent with a 30-channel cursor backfill under rate limits). The next stall is now measured, journaled and self-healed. | — |
| EOD-02 | `RiskPlan.reviewClass` (evidence \| budget \| plan) set by `plan_risk`, journaled on `TipGeometryRepaired`, consumed by `record_pre_entry_failure(review_class=)`; text classifier checks the evidence vocabulary FIRST (`missing delta`, `s old`, `old (max`, `no live underlying`, …) and never treats `no risk estimate:` as intrinsic; the count query filters `Event.portfolio_id`. | gates: 3 checks |
| EOD-03 | `add_tip_note(staged=True)` → `needs_human` at birth, no family supersede, `TipRuleAudited proposed/pending-review` journal; `save_note(scope=rule)` stages whenever `knowledge_apply_enabled` is False; `_rules_text` renders needs_human rows as `PENDING REVIEW — proposed or disputed, NOT operative policy`. | knowledge: 1 check + `test_staged_model_rule_is_rendered_as_pending_not_policy` |
| EOD-04 | `Engine._quote_consumer`: bars on the critical path, sim fills on a bounded ordered queue (4000; oldest dropped and counted when saturated). `PositionManager._watch_once` → per-position `_watch_position` tasks, bounded pass wait (`execution.watch_pass_timeout_seconds` 5), a still-busy position is skipped by the next pass (its guard prevents duplicates). Not claimed as today's root cause; instrumentation of source→aggregation→publication→receipt latency is still open. | delivery: 2 checks |
| EOD-05 | `brokers/sim.option_session_open()`: OPT orders fill only 09:30–16:00 ET (13:00 early close) on a trading day; `SimExecutor(option_sessions=True)` default, `AppConfig.sim_option_sessions` (tests: False). The APLD 04:01 fill stays in the ledger, labelled an execution-realism defect in TRADING-RULES. | simulation: 1 check |
| EOD-06 | share plans record `quote.source/ageS/delayed/underlyingDelayed`; `_resolve_proof_meta` binds an execution by its OWNED order first (entry legs / exits), the symbol comparison only rejects unowned records. | gates: 2 checks |
| EOD-07 | `ops.restart_state` counts running `TipAnalystRun` rows created within 2 h (`tipRuns`), reports older running rows as `tipRunsStale`. Deployment-intent lease: NOT built (needs both desks' scripts) — convention recorded in PLATFORM-RULES. | restart: 1 check |
| EOD-04/07 (found while verifying) | `Scheduler`: jobs run as their own tasks (`_running`), a tick waits for the jobs it started (bounded `tick_timeout_s` 600), `stop()` cancels the loop and running jobs with a bounded wait (`stop_timeout_s` 10) and names a job that did not unwind. Found because after 20:00 ET every registered nightly job is due on a fresh engine's first tick and a slow job held `Engine.stop()` — the same mechanism would hold a production restart. | peek/API teardown 3/3; scheduler tests in flow_api/platform_phase3/knowledge_review |
| EOD-08 | `rule_audit._finish` sets `finished_at`. Per-run usage on retros/digests and bounded resumable audit judgments: NOT built tonight (deferred with the measurement plan). | — |
| EOD-09 | `Portfolio.quarantined` + `quarantine_note` (additive columns), `positions.set_quarantine`, `POST /api/portfolios/{id}/quarantine` (journaled `PortfolioQuarantine`); `source_trust` ignores a quarantined immediate book; `grade_lanes` skips quarantined lanes. | `test_quarantined_shadow_book_is_not_evidence` |

## Budget premise (corrected in TRADING-RULES)

The MSFT and TSLA takes HAD stops; their delta-linear unit risk ($96, $100) exceeded the ~$89
budget after structure widened the stop (MSFT 2.73 → 18.44 points). No budget change is
recommended; the research items (feasibility shown to the analyst before tool work,
`take-but-cannot-fit` separated from skips in the scorecard, stop-repair provenance) are queued.

## Deferred

Deployment-intent lease (EOD-07); per-call usage on retros/digests and the bounded audit
judgment (EOD-08); pipeline latency instrumentation (EOD-04); source→receipt→appraisal timing
report and contemporaneous-option-evidence research for the 26 late messages (EOD-01).

## Deployed

v0.7.77 = main `411bc2a` (PR #108, renumbered after main moved to 0.7.76), restarted through the
readiness gate at 21:34 ET on 2026-09-14 (task last run 33 min earlier, checkout head checked);
health 0.7.77 at 21:35:34 ET. Verified after restart: RKT/T/HIMS restored with their stops, 0 open
incidents, gates enforce/integrity, `gateway_status.json` + `logs/discord-gateway.log` written by
the restarted gateway, `/api/tip/intake/liveness` answering. Shadow books `ab` (armed) and `eva`
(armed) quarantined via `POST /api/portfolios/{id}/quarantine` (journaled `PortfolioQuarantine`).
Follow-up the same night: a PAST late delivery inside the 24 h look-back is a `warnings` entry,
never a current-stall verdict (it would have journaled a false `TipIntakeStalled` at 04:00 ET).

