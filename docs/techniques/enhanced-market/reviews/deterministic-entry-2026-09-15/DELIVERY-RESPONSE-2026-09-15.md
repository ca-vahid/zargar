# EM deterministic entry - delivery response and handoff package (2026-09-15)

**Delivered as one integrated commit on `claude/technique-review-trade-plan-fbb9ba`: `758ccfb8e0a456d1df534f9e91a35e16f47cb352`** (the EM
delivery commit `26c83bb` merged with `origin/main` `079472e`, version 0.7.92; the FIX-03 / F127 sizing hunk resolved
exactly as the running checkout resolved it: the risk-budget floor kept with the expiry-scoped 0DTE clamp). Delivery A
and Delivery B are both in it. Nothing is deployed; the settings defaults below become live only with the next
normally verified combined release. No runtime setting, arm, order or position was changed while building this.

## 1. What changed (Delivery A - deterministic main mode)

| Component | Change |
|---|---|
| `execution/planrunner.py` | Generic hooks `fire_review_policy(ap)` (default `legacy` - Tips/Team2/Cartel unchanged), `fire_decision(ap, tid, tr, trade, attempt_id=)` (default None), `fire_evidence_mode(ap)` (default `off`), `fire_policy_view(ap)`. `_fire_rest` resolves the policy ONCE per fire attempt after the (model-free) `analyze_fire`: `deterministic` -> the technique's decision, journaled as `TechniqueEntryDecision`, refusal/deferral is its own disposition (`refused` status, `decisionDisposition` refused/deferred; never `critic_killed`, never an advisory downgrade, no kill counter, cooldown, re-arm or pause), `allow` -> the UNCHANGED `_enter` chain; `legacy` -> the old reviewer branch untouched; any other value -> `policy_error` refusal (no model fallback). `Trade` carries `decision`, `decisionDisposition`, `timing` (barTs, barCloseTs, receivedTs, decidedTs, decisionMs, quoteReadyTs, admissionTs, submitTs) and `signalBar`; restore preserves them; `TechniquePlanTriggerFired` / `TechniquePlanOrderIntent` carry `decision`, `fireDecisionMode`, `timing`. Armed snapshots and preflight expose `effectiveFireDecisionMode`, `decisionVersion`, `fireEvidenceMode`, `legacyUseCritic`, `criticEffective`. |
| `technique/entry_decision.py` (new, pure) | `EntrySnapshot` / `EntryPolicy` / `evaluate_entry` -> `EntryDecision` (`deterministic-entry-v1`): decisionId (attempt-scoped), rule/threshold hash, plan identity, trigger family, confirmation variant, signal bar start/close, source/received time, verdict allow/refuse/defer, stable reason codes, per-check outcome + authority (`entry_required` / `diagnostic`), input hash. `snapshot_from_tracker` freezes the ACTUAL `TriggerTracker` transition (its `fired` note: rel / rangeBreak / loose / confirmedAfter, the break candidate note) - a kind label never manufactures confirmation. `policy_from_thresholds` snapshots only the keys the rules read. |
| `technique/arming.py` | EM overrides: `fire_review_policy` from `techniques.enhanced_market.fire_decision_mode` (`deterministic` default; `legacy`, `legacy_blocking`, `critic` -> legacy; else `invalid:<value>`), `fire_evidence_mode`, `fire_decision` (snapshot + pure evaluation, no I/O). `review_fire` / the critic are never invoked on the deterministic path; `record_fire` persists the unmutated deterministic analysis; the chat note states the live decision. |
| `settings_service.py` | `techniques.enhanced_market.fire_decision_mode = deterministic`, `fire_evidence_mode = off`, `fire_evidence_max_calls = 40`, `fire_evidence_timeout_seconds = 60`. Deliberately NO `execution.*` default (other desks unchanged). `critic_mode` / `useCritic` retained as legacy fields. |
| `events.py`, `research/events_contract.py` | `TechniqueEntryDecision` v1 (runId, symbol, trigger, decisionId, decisionMode, decisionVersion, verdict, reasonCodes, inputHash, checks) and `TechniqueEntryEvidence` v1 (…, reviewOutcome, authority). |
| `technique/service.py` | `arm_options` returns `fireDecisionMode`, `decisionVersion`, `fireEvidenceMode`, `premarketLlmAvailable`; `arm_preflight` attaches the effective policy. |
| `tools/em_fire_policy_migration.py` (new, read-only) | Migration preview: every active EM arm with stored `useCritic`, old effective policy, NEW effective policy, critic-only kills/failures/cooldowns/paused state, consumed triggers. Rewrites nothing. |
| `tools/em_profitability.py` | Rows carry `policyVersion` / `decisionId` / `fireDecisionMode` / `timing` / `quoteRefresh`; report adds the execution-policy cohort table (attempts, fills, refused, open, net, refresh attempted/ok). |
| Frontend | `types.ts` (effective policy + decision fields); `ArmDialog.tsx` (EM in deterministic mode shows "live entry decision: deterministic (deterministic-entry-v1) · later AI review: off/after close" instead of the AI double-check; other desks keep the checkbox); `ArmedTab.tsx` (`refused` status label, live decision line per trade, policy badge per plan); `SettingsPage.tsx` (EM live entry authority group: decision mode + later review; the legacy AI toggle relabelled as legacy-mode / other desks). Build + check-release green (0.7.92). |
| Docs | TRADING-RULES (deterministic main mode, **momentum-family model veto retired**, rule map v1, not-encoded judgments), PLATFORM-RULES (hook + invariant), ARCHITECTURE, CLAUDE.md; reviewer plan + rule map + notes adopted under this folder. |

## 2. Delivery B - optional frozen evidence (default off)

`technique/entry_evidence.py`: `frozen_input(decision_payload, saved_trigger)` (excludes fills/outcomes by construction,
hash-stable), `isolated_analysis` (a fresh `TechniqueAnalysis` from the frozen trigger, never the execution object),
`run_evidence` (one bounded critic call on the copy; timed_out / failed / unavailable / invalid / completed are evidence
outcomes), `EvidenceResult.to_record` (`authority = evidence_only`, disagreement category, timings, key
`(decisionId, inputHash, policyVersion, promptHash, model)`). `tools/em_entry_evidence.py`: after-close command gated by
`fire_evidence_mode = after_close` (`--force` still evidence only), one call at a time, per-call timeout, paid-call
budget, chart/facts rendered only from stored bars at or before the signal-bar close, appends `TechniqueEntryEvidence`;
`report` shows coverage before anything else. The modules import no order / arm / pause / settings-write / engine
capability (asserted by test).

## 3. Migration preview (read-only, runtime database, 2026-09-15 evening)

Effective mode `deterministic` (`deterministic-entry-v1`), evidence `off`. 41 active EM arms for 2026-09-16, all with
stored `useCritic=true` under the old `critic:momentum_only` policy -> new effective `deterministic` at their next fire
attempt; **0** with critic-only state (kills / failures / refire cooldowns), **0** critic-only paused, no consumed
triggers. Nothing needs releasing; nothing was rewritten. The mode is resolved per fire attempt, so restored and
batch-created arms obey the same policy. Legacy rollback = `PATCH /api/settings {"techniques.enhanced_market.fire_decision_mode": "legacy"}`
(journaled `SettingChanged`); it changes only the next fire attempts, never re-fires a consumed trigger.

## 4. Latency evidence

- Pure decision `evaluate_entry` over 2,000 fixture attempts: p50 0.026 ms, p95 0.035 ms, p99 0.131 ms, max 0.60 ms;
  model calls on the entry path: 0 (test `test_local_decision_latency_is_millisecond_scale` pins p99 < 50 ms).
- Runner boundary in the integration rig (fire -> decision -> entry seam): `decisionMs` < 1000 asserted with a
  never-resolving model client that is never touched; the reviewer branch is not awaited.
- What it replaces: Sep 15 recorded 15 critic traces of 14.13-21.99 s (mean 17.57 s) on the entry path.
- Still on the path and measured separately (timing stamps on the intent): the bounded provider quote refresh
  (<= 2.5 s, EM), contract pick, sizing/admission, RiskGate, venue acknowledgement. Not a promised sub-second broker
  transaction.

## 5. Acceptance matrix -> tests

| Case | Test |
|---|---|
| Valid bounce/reject, model unavailable / hanging sentinel never touched | `test_em_deterministic_entry_integration.py::test_deterministic_fire_never_touches_the_model_and_reaches_the_entry_chain`, `::test_restored_legacy_use_critic_arm_and_missing_llm_key_still_decide_deterministically` |
| Breakout/breakdown/wedge only after the actual configured branch; kind label cannot confirm | `test_em_deterministic_entry.py::test_breakout_needs_its_actual_followthrough_branch_and_a_kind_label_cannot_confirm`, `::test_breakdown_short_mirror_and_wedge_break_reuse_the_break_path` |
| Range-break / loose continuation record bypassed checks honestly | `::test_range_break_and_loose_continuation_record_bypassed_checks_honestly` |
| Incomplete confirmation / invalidated / exhausted / not-current refuse; advisory legacy cannot override | `::test_bounce_at_the_level_allows_without_a_reclaim_candle_and_a_stop_close_refuses`, `::test_exhausted_level_plan_not_current_and_bad_geometry_refuse`, integration `::test_deterministic_refusal_is_not_critic_killed_and_advisory_policy_cannot_downgrade_it` |
| Legacy veto mode retained when explicitly selected | integration `::test_legacy_mode_keeps_the_old_reviewer_branch_with_its_veto` |
| Invalid policy refuses with a policy error, no model fallback | integration `::test_invalid_policy_refuses_with_a_policy_error_and_never_falls_back_to_the_model` |
| Late negative/positive critic result cannot change the decision | integration `::test_generic_desks_default_to_legacy_and_a_late_model_opinion_cannot_mutate_the_decision`, `test_em_fire_evidence.py::test_isolated_analysis_is_a_fresh_object_built_from_the_frozen_trigger` |
| Repeated model failures in evidence mode = evidence errors only | `test_em_fire_evidence.py::test_hanging_failing_absent_and_skipped_models_are_evidence_outcomes_only` |
| Missing required deterministic input = explicit unknown-required (defer); unknown optional = diagnostic | `test_em_deterministic_entry.py::test_reject_short_mirrors_direction_and_volume_below_floor_refuses`, `::test_not_encoded_judgments_are_diagnostic_and_provenance_never_refuses` |
| Price/spread/budget change during quote fetch; final guard after earlier risk check | existing `test_em_entry_quote_refresh.py`, `test_codex_em_final_dispatch_quote.py`, `test_codex_em_final_dispatch_budget.py`, `test_em_shares_position_cap.py` (unchanged chain) |
| Disarm/expiry/quiescence/pending order/concurrent trigger; restart with held position | existing `test_technique_arming.py` (solo), `test_em_source_wiring.py`, `test_codex_fc01_source_loss.py` |
| Other desks unaffected | integration `::test_generic_desks_default_to_legacy_...`, `test_platform_separation.py`, `test_tip_runner.py`, `test_team2_gate_pick.py`, `test_team2_sizing_cap.py`, `test_codex_team2_f127_expiry.py` |
| Snapshot replay identical | `test_em_deterministic_entry.py::test_replay_is_deterministic_and_the_input_hash_binds_policy` |
| Evidence has no trading capability | `test_em_fire_evidence.py::test_evidence_modules_import_no_trading_capability` |
| Premarket/source review independent | `test_em_review_preopen.py`, `test_em_source_wiring.py` (unchanged) |

## 6. Verification on the integrated tree `758ccfb8e0a456d1df534f9e91a35e16f47cb352`

- Frontend `npm run build`: check-release "Release 0.7.92 ... agree", built.
- Pure EM / measurement / contract / sizing / F127 group: **106 passed**, plus `test_platform_phase3.py` **13 passed**
  when run on a private database (its `test_daily_bars_snapshot_persists_1d_rows` failed once on the shared
  `zargar_test` database while another session used it - a collision, not a regression).
- DB-backed dispatch / FC-01 / wiring / API / pre-open / separation / Team2 pick / Tip runner group: PENDING - running at the time of this handoff (exclusive private database, sequential); result appended in the next commit.
- Arming solo: PENDING - runs solo after the DB group; result appended in the next commit.
- Known unrelated failures on main (unchanged): `test_auto_options_one_contract_lifecycle` (sim option fills need the
  OPRA identity), `test_restore_reattaches_an_open_trade` (load-sensitive; passes alone).

## 7. Release / activation handoff

1. Final review of `758ccfb8e0a456d1df534f9e91a35e16f47cb352`. Then the normal combined-release protocol at a safe boundary (after the close,
   readiness safe, no open EM trades): deploy.ps1 for lease/handoff, `Start-ScheduledTask ZargarRestart` for the
   restart (this desk's shell is elevated), verify arms/positions/helpers afterwards.
2. On first boot with this build the 41 Sep 16 arms fire under `deterministic` automatically (per-attempt resolution).
   Rollback at any time: `fire_decision_mode = legacy` (journaled). `fire_evidence_mode = after_close` is a separate,
   optional opt-in; the after-close command needs an API key and is never a condition for trading.
3. Each close: `em_profitability report --date <session>` shows the execution-policy cohort table; the deterministic
   cohort's additional admissions (momentum families no longer vetoed) and their outcomes are retained, not filtered.

## 8. Unresolved trading-policy decisions (none blocking)

- The momentum-family model veto is retired by design (disclosed in TRADING-RULES). Any qualitative filter (reclaim
  confirmation, higher-timeframe context, opposing shelf, chop) is a separately versioned rule with its own evidence.
- `defer` (unknown required evidence) consumes the fired trigger like a refusal; no re-fire is attempted (conservative).
  If a re-arm-on-defer policy is wanted, it is a separate explicit change.
