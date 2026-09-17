# Current rule and implementation traceability

Reviewed 2026-09-16. Source IDs resolve in [SOURCES.md](SOURCES.md). Module names below are relative to `backend/zargar/techniques/options_cartel/` unless noted. A code path/test verifies mechanics, not author fidelity or investment performance.

| Concern | Code | Contract / limits |
|---|---|---|
| Method profiles and market alignment | `rules.py`, `screen.py` | Source-versioned screens; Moderate is a named Practice experiment |
| Generic geometry | `setups.py`, `quality.py` | Bases, flags, pennants, wedges, inside days, MA pullbacks, retests, triangles; numeric geometry/ranking is engineering |
| S30 post-ignition sequence | `ignition.py`, `setups.py` | Persistent research stages; separate long-side pilot; thresholds documented in IGNITION.md |
| Research/plan snapshots | `service.py`, `prepare.py`, `plans.py` | Saved analysis/plan inputs, targets and policies; not a complete provider revision ledger |
| Universe/industry collection | `discovery.py`, `industry_feed.py`, `industry.py` | Publisher pagination and context; not inferred historical membership |
| Daily preparation and leases | `preparation.py`, `preparation_lease.py`, `preparation_scope.py` | Workspace/account checks, reserves, cancellation/recovery, first-session expiry |
| History/cache/baseline | `preparation_io.py`, `history_cache.py`, `prepare.py`; shared `marketstructure/history.py` | Provider-keyed cache, actual completed session, source-specific native opt-in, minimum baseline samples |
| Minute source and recovery | `data_quality.py`, `observer.py`, `observation_health.py`, `preparation_readiness.py` | Retain source class; upgrade inferior context, never replay missed entries; equal-quality revision ordering remains limited |
| Entry authority | `entry.py`, `controller.py`, `runtime.py`, `state.py` | Completed bars, source/quote/permissions/risk, atomic attempt ownership and account capacity |
| Fills and held positions | `settlement.py`, `adoption.py`, `residuals.py`, `position_adapter.py`, `exit_router.py`, `catchup.py` | Actual fills, provisional partial protection, missed-close adaptation, residual handling and restore |
| Contracts and risk | `automatic_plans.py`, `contracts.py`, `execution.py`, `loss.py`, `marks.py`, `accounts.py` | Planning vs executable quotes, explicit budgets/Greeks, dedicated book, loss and prior marks |
| Replays/comparisons | `replay.py`, `replay_service.py`, `sweeps.py`, `premium_replay.py`, `quote_observations.py` | Non-executing research; underlying and recorded-premium results remain distinct |
| Prospective research | `profitability_research.py`, `intraday_research.py` | Practice-only contexts/observations; full bounded pool; persisted fair retry order; no automatic unlock or orders |
| Economics and quote studies | `research_economics.py`, `research_quotes.py` | Frozen ranking/target/exit variants, integer units, observation-time causality, entry-time funding limits; absent evidence is unknown |
| Future-session warnings | `observation_health.py`, `observer.py`, `runtime.py` | A plan owes no minutes before its first session; genuine active-session gaps remain visible |
| Session review | `session_review.py`; `api/routes_options_cartel.py` | Account/session-scoped decisions and source counts; not estimated option P&L |
| UI | `frontend/src/pages/CartelPreparation.tsx`, `CartelIgnition.tsx`, `CartelPlanOverview.tsx`, `CartelSessionReview.tsx`, `CartelMethodLibrary.tsx` | Preparation, research, actual arms, quantity previews and method documentation |

Representative regression areas: `test_options_cartel_ignition_reliability.py`, `test_options_cartel_preparation_safety.py`, `test_options_cartel_preparation_coverage.py`, `test_options_cartel_baseline_windows.py`, `test_options_cartel_runtime.py`, `test_options_cartel_controller.py`, `test_options_cartel_sweeps.py`, and the dedicated adoption/settlement/exit tests. Use actual test files and current results, not historical counts, for a new change.

The original stage-by-stage matrix is [archived](archive/TRACEABILITY-PRE-2026-09-13.md). Statements there such as registration/provider/entry-adapter pending are historical and superseded.

## September 13 correction boundaries

- Final contract authority: execution.py, controller.py, OrderManager.before_submit; test_options_cartel_contract_integrity.py.
- Target causality and candidate anchors: setups.py/automatic_plans.py; test_options_cartel_target_boundaries.py.
- Pending invalidation and explicit unused-arm review: preparation.py, observer.py, execution_review.py, runtime.py; pending_integrity, execution_review, execution_review_integrity tests.
- Actual held-position capacity: preparation.occupied_plans; test_options_cartel_capacity_integrity.py.
- Provider identity: preparation_io.py; test_options_cartel_provider_identity.py.
- Quantity-dependent exits and evidence: exits.py, replay_service.py, quote_observations.py, premium_replay.py; test_options_cartel_monday_economics.py and existing exit/replay/quote suites.
- Advisory leader observations and preparation-policy cohorts: leader_context.py; test_options_cartel_leader_context.py. These grant no trading permission and are not profitability measurements.

Current research regression entry points: `test_options_cartel_profitability_research.py`,
`test_options_cartel_profitability_api.py`, `test_options_cartel_research_economics.py`,
`test_options_cartel_research_quotes.py`, `test_options_cartel_session_warning.py`.
These supplement the execution/replay suites rather than replacing them.

September 16 follow-through: `contract_reselection.py` owns the bounded Practice spread-only search; `session_review.py` reads dated preflight refusals; `profitability_research.py` prewarms future-session baselines and records non-executing entry-policy diagnostics. Regression coverage is in `test_options_cartel_contract_reselection.py` and `test_cartel_sep16_followthrough.py`.
