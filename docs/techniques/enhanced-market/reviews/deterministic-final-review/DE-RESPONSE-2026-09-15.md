# EM deterministic entry - response to the final review at 758ccfb (DE-01..DE-05)

Corrected integrated delivery: **`8e641e9e7fd86f5b29beef339ad25401cd4c1a86`** on `claude/technique-review-trade-plan-fbb9ba` (the DE fixes on top of
758ccfb / fc6a295, merged with `origin/main` at `cd4c1c6`). **Accepted by the corrected review (`deterministic-corrected-review/CORRECTED-REVIEW-8e641e9.md`);
the CR-01/CR-02 follow-ups are closed below in the release tree `ab9238c`** (= 8e641e9 + CR fixes 89765c0 + `origin/main` e8c03ee (0.7.94) + the runtime
checkout's local merge 1ee9a91; version 0.7.95). The four reviewer files were adopted UNCHANGED
(`tests/test_codex_deterministic_rule_parity.py`, `tests/test_codex_deterministic_record_owner.py`,
`tests/test_em_evidence_boundary_regressions.py`, `tests/test_policy_migration_reporting.py`; packet copied to this
folder). The 20 prior cases and the `fc6a295` arming cases are preserved. Nothing is deployed; the current runtime
(0.7.91 build a4d241b, legacy critic) and the Sep 16 preparation are untouched.

## Closure table

| ID | Finding | Fix | Regression |
|---|---|---|---|
| DE-01 (DR-01) | A second confirmation-bar window gate refused a valid 10:29 candidate confirmed at 10:32. | The tracker's own gate is the window authority (touch bar for bounce/reject, CANDIDATE bar for break families); the decision records `candidateWindow` + `firedWindow` and adds no second gate (`window` passes iff the tracker fired). An ineligible candidate is still refused by the tracker itself (never fires). | `test_confirmed_break_keeps_tracker_candidate_window_semantics` |
| DE-01 (DR-02) | Saved entry replaced by the fill proxy, then all targets required ahead of it. | `EntrySnapshot.entry` = the SAVED entry, `observed_entry` = the tracker fill proxy, separate fields; saved geometry validated against the saved entry only. Invalid saved geometry still refuses (`geometry_invalid`); current-price feasibility, chase and quantity-dependent R2 stay with the unchanged downstream checks. | `test_saved_geometry_does_not_become_invalid_when_break_close_passes_tp1`, `test_exhausted_level_plan_not_current_and_bad_geometry_refuse` |
| DE-01 (DR-03) | Policy built from a fresh settings read, not the rules that fired the tracker; confirmation inputs missing from the hash. | `fire_decision` builds the policy from `tr.thresholds` and `tr.enforce_windows` (the tracker's own rule object); the threshold snapshot/hash now includes `decisive_body_ratio`, `decisive_size_mult`, `max_breakout_wick_ratio`, `range_break_bars`, `range_break_max_range_mult`. | `test_fire_snapshot_uses_the_rules_that_actually_fired_the_tracker`, `test_replay_is_deterministic_and_the_input_hash_binds_policy` |
| DE-02 (record owner) | A deterministic refusal persisted the pre-gate analysis as verdict `setup`. | `record_fire` applies the EXECUTED decision before persisting: verdict `no_setup`, confidence 0, reason codes on the rationale / no-trade reasons. | `test_persisted_setup_uses_the_executed_deterministic_refusal` |
| DE-02 (attribution) | The report joined the first same-trigger fire/intent to the latest trade; refused attempts vanished. | Attempt census from the immutable `TechniquePlanTriggerFired` events (policy version, decisionId, disposition per attempt); a trade row binds its fire/intent by decisionId (deterministic) or by its own firing-bar time window (legacy), never the first same-trigger event; `byPolicy.attempts` counts the census, fills/refusals bind to their attempt. | `test_fill_policy_belongs_to_its_attempt_after_legacy_refire` |
| DE-03 | `SettingsService.load()` in the preview (and the evidence command) can migrate aliases and commit. | New non-mutating `ReadOnlySettings` projection + `read_only_settings(session)` in `settings_service.py` (same DEFAULTS / alias / technique-override / trading-mode-alias resolution as `get`, in memory only); preview and evidence `_open` use it inside `set transaction read only`; no Journal in the preview; mode names normalised by the ONE `normalize_fire_mode` (runner, preview, UI: strip/lower, `legacy_blocking` / `critic` / `llm` -> legacy, else `invalid:<raw>`). | `test_preview_does_not_migrate_stored_settings` |
| DE-04 | The command imported a non-existent mapped type and aborted; bad rows raised outside the row boundary. | No bar-table query at all (frozen bars come from the decision record); every row runs inside its own error boundary (`invalid` / `unavailable` outcomes, batch continues); `validate_frozen` + `isolated_analysis` inside `run_evidence`'s boundary. | `test_after_close_cli_processes_a_real_eligible_row_without_import_abort`, `test_missing_required_snapshot_becomes_invalid_evidence_not_batch_abort` |
| DE-05 | Summary-only decision record; inputs reconstructed later from mutable rows; shallow frozen copies; key ignored the evidence hash; prompt hash was a label; usage lost. | The decision record now carries its full `snapshot` (the `EntrySnapshot` as serialised), its `policy` (effective rules) and `frozenBars` (last 240 completed 1m bars at or before the signal close, captured from the in-memory bar cache at decision time - raw data only, no render, no model) with `frozenBarsHash`. `frozen_input` deep-copies and prefers the decision's snapshot (`frozenSource = decision_snapshot`); a supplied trigger is labelled `retrospective:supplied_trigger`; the command marks decisions without a snapshot / frozen bars `unavailable` and never rebuilds from current rows. `evidence_key` includes `evidenceInputHash`; `promptHash` = hash of the actual system prompt + critic pass source + verdict schema + model/effort (`prompt_identity`); usage read from `passRecord.usage`; `modelStartedAt` stamped at the model call; CLI `--timeout` always honoured (min with the setting); one provider attempt per row; `report` bounded to the session day with later reviews joined by decision id; only `completed` evidence blocks a retry; a still-open session is refused even with `--force`; signal-bar close derived from the plan's trigger timeframe. | `test_frozen_evidence_is_detached_from_mutable_plan_and_decision`, `test_evidence_identity_changes_when_the_review_input_changes`, `test_successful_real_critic_return_preserves_usage`, `test_em_fire_evidence.py` (4) |
| UI | "critic on" derived from stored `useCritic` beside the deterministic badge; invalid mode mislabelled. | Header and badge use the effective policy; invalid mode renders a policy error in the armed card and the arm dialog; the legacy checkbox appears only for legacy / older servers. Build + check-release green. | frontend build |

## Verification (corrected tree)

- Reviewer reproductions + prior cases (`test_codex_deterministic_rule_parity`, `test_codex_deterministic_record_owner`,
  `test_em_evidence_boundary_regressions`, `test_policy_migration_reporting`, `test_em_deterministic_entry`,
  `test_em_deterministic_entry_integration`, `test_em_fire_evidence`): **31 passed**.
- Pure EM / measurement / profitability / entry quality / exits / platform contracts (private DB) / EM review execution /
  sizing / F127 / Team2 sizing: **118 passed** (together with the 31 reviewer/prior cases in one run; private database `zargar_test_em2`).
- DB-backed dispatch / FC-01 / wiring / API / pre-open / evidence / separation / Team2 pick / Tip runner: **103 passed in 4:49** (private database `zargar_test_em`, sequential).
- Arming solo (incl. the explicit-legacy cases and the real-rig deterministic case from fc6a295): **30 passed + 1 failed** = only the known baseline `test_auto_options_one_contract_lifecycle`; the load-sensitive restore case passed in this full-file solo run.
- Frontend: `npm run build` green, check-release "Release 0.7.93 ... agree".
- Migration preview (read-only, runtime database, after the DE-03 fix): effective mode `deterministic` (`deterministic-entry-v1`), evidence `off`; effective settings `techniques.enhanced_market.fire_decision_mode=deterministic`, `fire_evidence_mode=off`, `critic_mode=momentum_only`; 41 active EM arms for 2026-09-16, all `useCritic=true` -> new effective `deterministic`, 0 with critic-only state, 0 critic-only paused; no setting written, no arm rewritten (the projection never commits).
- Known baseline failures on main, unchanged: `test_auto_options_one_contract_lifecycle` (sim option fills need the OPRA
  identity); `test_restore_reattaches_an_open_trade` is load-sensitive and passes alone.

## CR-01 / CR-02 closure (corrected review at 8e641e9; fixed in 89765c0, release tree ab9238c)

| ID | Finding | Fix | Regression |
|---|---|---|---|
| CR-01 (evidence only) | The after-close command trusted the record's declared `inputHash` / `frozenBarsHash` and rendered facts under current default thresholds. | `entry_evidence.verify_identity` runs BEFORE any rendering or model call: the snapshot + policy must reproduce `inputHash` (`entry_decision.recompute_input_hash`, the same `snapshot_hash`), the frozen bars must reproduce `frozenBarsHash` (`entry_decision.frozen_bars_hash`, the ONE canonical function the runner now also uses) and `frozenBarsCount`, and no frozen bar may close after `signalBarClose`; any mismatch is an `invalid` outcome with the reason named and no model request. Derived facts are computed under the FROZEN policy thresholds (`frozen_thresholds`: captured values over defaults for unrecorded keys) and the record discloses `evidenceAnalysisPolicy` + `identityVerified`. | reviewer `test_em_evidence_completed_path.py` (2: good path completed with usage / image / hash equality; corrupted bars -> invalid, zero model requests); `test_em_cr_identity_and_census.py::test_identity_verifies_from_the_captured_material_and_every_tamper_is_named`, `::test_derived_facts_use_the_frozen_policy_values_and_disclose_it` |
| CR-02 (report only) | Refused / deferred attempts were counted only through trade rows; a refused attempt with no row vanished, the census dedupe key lacked the run id. | The attempt census is built per run from ALL `TechniquePlanTriggerFired` events before the trade-row loop (a refused attempt has no row), keyed once per (runId, trigger, decisionId) - or (runId, trigger, bar) for legacy attempts without a decision id; `byPolicy.refused` counts census dispositions in {vetoed, refused, deferred, policy_error, critic_unavailable, failure-budget-paused} once per attempt, a row bound to a counted attempt is never counted again, a refused row without a census attempt still counts once, and an unknown disposition is counted as an attempt but never classified. | reviewer `test_codex_policy_refusal_census.py` (1); `test_em_cr_identity_and_census.py::test_refusals_are_counted_once_per_full_attempt_identity_across_runs` (two runs, same trigger id, duplicate delivery, unknown disposition) |
| Regression found while running the broader group | `test_em_review_da_reconcile.py::test_exhausted_critic_failure_budget_has_explicit_persisted_disposition` (a reviewer rig without the policy hook) failed with `AttributeError: fire_review_policy` since 163e4a6. | `_fire_rest` resolves the policy through `getattr(self, "fire_review_policy", None)`; a runner without the hook is legacy (the base hook's own default). No test changed. | that reviewer case (unchanged) |

Results on the release tree `ab9238c` (both private databases, sequential, foreground):

- Reviewer reproductions + prior + EM measurement / profitability / entry quality / review execution / final dispatch / separation / API / pre-open
  (26 files incl. the two new reviewer files and my 3 CR cases): **119 passed, 5 skipped** (`zargar_test_em2`).
- DB-backed dispatch / FC-01 / wiring / API / pre-open / evidence / separation / Team2 pick / Tip runner (the recorded 10-file group): **103 passed in 4:33** (`zargar_test_em`, on 89765c0 before the two merges; the merges touched no EM runtime code - the same API/pre-open/separation/dispatch files re-ran green in the 119 above).
- Arming solo: **30 passed + 1 failed** = only the known baseline `test_auto_options_one_contract_lifecycle` (load-sensitive restore case passed) - run three times (89765c0, 7096732, ab9238c), same result each time.
- Frontend: `npm run build` green, check-release "Release 0.7.95 ... agree" (0.7.94 was taken by the Team2 desk during the merge; this release renumbered to the next free number, nobody's block rewritten).
- Migration preview (read-only, runtime database, 21:58 PT before the deploy): effective mode `deterministic` (`deterministic-entry-v1`), evidence `off`;
  41 active EM arms for 2026-09-16, all `useCritic=true` -> effective `deterministic`, 0 critic-only state, 0 critic-only paused; nothing written.

## Release 0.7.95 - deployed 2026-09-15 22:04 PT (after the close, no open positions)

- **Deployed SHA `414a86cc4a05cbb0dce017299cd7ddcd4840c3ca`** (`ab9238c` + this closure record) - `/api/health` version `0.7.95`, build `414a86cc…` (launch-bound).
- Protocol: readiness `/api/ops/restart-check` safe (market closed, 0 open trades) -> `scripts/deploy.ps1 -TargetCommit 414a86c… -Expect 0.7.95`
  under the deployment lease (before-inventory `logs/restart-inventory-20260915-220229.json`, health contract check, the elevated-shell start refused
  as designed) -> `ZargarRestart` scheduled task (restart.ps1, consumed the pending handoff) -> healthy at 22:04:12 PT (dark ~90 s).
  Receipt `logs/deployment-receipt.json`: phase `verified`, target 414a86c…, expectedVersion 0.7.95, healthyVersion 0.7.95, runtime clean, restoration
  `skipped-no-baseline` -> verified by hand below.
- **Restored-arm verification (by id, before-inventory vs `/api/ops/state` after restore):** 56 armed before, 56 after, 0 missing, 0 new -
  enhanced_market 41, options_cartel 5, team2 3, tip 7; resting orders 22 -> 22; open trades 0 -> 0; 51 `TechniquePlanRestored` events.
- **Effective deterministic mode:** all 41 EM armed snapshots report `effectiveFireDecisionMode=deterministic`, `fireEvidenceMode=off`,
  `criticEffective=false`; effective settings `techniques.enhanced_market.fire_decision_mode=deterministic`, `fire_evidence_mode=off`,
  `fire_evidence_max_calls=40`, `critic_mode=momentum_only` (legacy path only), `shadow_exit_observe=True`, `shadow_p02_candidate=True`
  (the user's 14:06 PT observation decision, unchanged), `trading.mode=practice`. The 10 Tips/Team2 arms read `legacy` from the base hook
  default and the 5 Cartel arms carry no policy view - untouched, out of scope.
- **After-close LLM evidence is OFF** (`fire_evidence_mode=off`); zero model calls since the restart (0 technique runs, 0 `TechniqueEntryEvidence`,
  0 `TechniqueEntryDecision` records exist yet - the first ones will be written by tomorrow's fires).
- Helpers after the restart: Discord gateway connected (intake liveness `live`), `em-ingest` worker window up, watchdog task Ready.
- Not deployed / not run: the FIX-01 v4 money repair (human step), the after-close evidence command (stays off until a person turns it on).

## Notes for the final review

- No new trading filter was introduced to satisfy parity; DR-01/DR-02/DR-03 were closed by removing the added gates and
  by freezing the tracker's actual rules. `defer` on unknown required evidence remains conservative (consumes the trigger).
- The evidence command's `evaluated` count includes `unavailable` / `invalid` rows (each gets a record); coverage is
  reported separately (`withCompletedEvidence`).
- Older `TechniqueEntryDecision` records without a snapshot (none exist yet - the mode is not deployed) would be
  `unavailable` for evidence, by design.
