# EM deterministic entry - response to the final review at 758ccfb (DE-01..DE-05)

Corrected integrated delivery: **`8e641e9e7fd86f5b29beef339ad25401cd4c1a86`** on `claude/technique-review-trade-plan-fbb9ba` (the DE fixes on top of
758ccfb / fc6a295, merged with `origin/main` at `cd4c1c6`). The four reviewer files were adopted UNCHANGED
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

## Notes for the final review

- No new trading filter was introduced to satisfy parity; DR-01/DR-02/DR-03 were closed by removing the added gates and
  by freezing the tracker's actual rules. `defer` on unknown required evidence remains conservative (consumes the trigger).
- The evidence command's `evaluated` count includes `unavailable` / `invalid` rows (each gets a record); coverage is
  reported separately (`withCompletedEvidence`).
- Older `TechniqueEntryDecision` records without a snapshot (none exist yet - the mode is not deployed) would be
  `unavailable` for evidence, by design.
