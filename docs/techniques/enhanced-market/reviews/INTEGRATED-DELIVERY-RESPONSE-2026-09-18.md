# EM integrated delivery - consolidated closure, REVISION 2 (2026-09-19)

> SUPERSEDED where they conflict by `FINAL-COMPLETION-RESPONSE-2026-09-19.md` (final candidate `2d7f51bb`, 0.8.23): the revision-2 review found two more defects (R2-01, R2-02) in the candidate this document describes. Kept as the record of revisions 1 and 2.

Answers `EM-INTEGRATED-DEVELOPMENT-PLAN-2026-09-18.md` (the contract) and `2026-09-18-INTEGRATED-CANDIDATE-REVIEW.md` (IR-01..IR-05, the
outstanding acceptance requirements) as ONE corrected candidate. Owner: EM desk. Revision 1 of this document described candidate `0f0949b`;
the reviewers reproduced real defects in it. Sections 0a to 0c are new and govern; sections 1 to 10 are revision 1, corrected in place where
they were wrong (every correction is marked "rev 2"). Nothing was deployed, no strategy was activated, no setting of the running app was
changed, no paid model call was made, no historical money row was rewritten, and the runtime database was only read (now under a
session-level read-only guarantee that was probed: a write is refused with `ReadOnlySQLTransactionError`).

| Item | Value |
|---|---|
| Final tested candidate | **`9ea7572e97b6016cc7d4bbb5ceb40a785bbc8a6f`** on `claude/technique-review-trade-plan-fbb9ba`, version **0.8.21** (quartet + lockfile agree) |
| Contains | runtime head `f4ce6ad83b3f6c44aa356659fecc53c47e7f64ab` = origin/main `c40f1fd0` (v0.8.20), re-read 2026-09-19 after the last code commit: the branch is 0 commits behind both. No version collision (main and runtime are 0.8.20) |
| Live at the time of writing | v0.8.20 build `f4ce6ad8` (`/api/health` ok, 19 plans armed). This candidate is NOT deployed |
| Commits since revision 1 | `1cb0a9f1` first-sale-v2 (IR-01/IR-04), `f9371f28` book-snapshot-v2 (IR-02/IR-03), `7002426d` candidate-pricing-v1 + cache identity (IR-05), `d0e6f948` owner findings + controlled clock, `9ea7572e` owner re-check finding + definitions + reports |
| Docs-only receipt | any commit after `9ea7572e` touches `docs/` only (`git diff 9ea7572e..HEAD --stat`) |
| Paid model calls | 0. Test DBs: `zargar_test_em` (private); reviewer files on `zargar_test_codex` after verifying zero connections |

## 0a. Closure matrix - one row per review requirement

Every test named here is in the candidate and passed on `9ea7572e` (section 5). "Rig" = the real `PlanArmer` on the sim engine with a real
`OrderManager` and RiskGate, not a pure-function call.

### IR-01 - first-sale admission (`first-sale-v2`: `technique/first_sale.py`, `technique/arming.py`, `execution/planrunner.py`)

| Requirement | What the candidate does | Proof (`tests/test_em_first_sale.py`) |
|---|---|---|
| The current executable price owns admission, not the saved entry | admission entry = the WORSE of the runner entry and the validated bound (long: ask, short: bid; shares also their own limit). The reviewers' case (entry 100, underlier 102, stop 99, TP2 103) now FAILS at 0.333R | `test_reviewer_reproduction_the_current_executable_price_owns_admission_not_the_saved_entry` |
| Validated evidence, never an unvalidated last price | named source + venue quote time within `risk.stale_quote_seconds` + symbol identity + not halted; a print is the bound only when no fresh two-sided quote exists; a receipt time is never evidence; a source is never invented | `test_a_print_is_the_bound_only_when_no_fresh_two_sided_quote_exists_and_a_receipt_time_is_never_evidence`, `test_em_producer_uses_validated_venue_evidence_the_frozen_pin_and_never_invents_a_source` |
| Unrounded comparison | `r_raw` is compared; rounding is display only. 2.9996 is below 3 | `test_the_comparison_is_unrounded_2_9996_is_below_3` |
| Enforce fails closed; observe non-authoritative; invalid mode never silently off | `decide()` dispositions: `passed`, `refused`, `deferred_missing_evidence`, `deferred_error`, `policy_error`, `observed_*`. An invalid setting REFUSES entries | `test_modes_an_invalid_value_is_never_silently_off_and_errors_fail_closed_under_enforce`, `test_observe_is_never_authoritative_and_enforce_fails_closed_on_fail_unknown_and_error`, rig: `test_an_invalid_setting_refuses_entries_instead_of_silently_disabling_the_gate` |
| Final-dispatch recheck after waits and retries | `first_sale_final` is the first call inside the final entry guard; it re-decides on the final price, quantity and fresh evidence and raises the same `entry gate:` rejection shape as FC-01 | rig: `test_a_price_that_moves_between_the_check_and_the_dispatch_is_refused_at_the_final_guard`; `test_shares_are_bounded_by_their_own_limit_and_a_changed_quantity_changes_the_gate` |
| Gate target vs first production sale; multi-contract rule unchanged | both reported on every record (1 and 2 contracts: the TP2 full exit is both; 3+ contracts and shares: gate TP3, first sale the TP1 ladder rung). The 3+ rule was NOT changed while fixing SBUX | `test_gate_target_and_first_production_sale_are_reported_apart_for_one_two_three_contracts_and_shares` |
| Frozen policy pin | `technique.rr_gate_target` comes from the plan's run config (cached, 2 s bound); unresolved = unknown, never a fresh legacy-key read | `test_the_frozen_pin_comes_from_the_run_config_bounded_and_cached`, `test_puts_are_signed_a_wrong_side_target_fails_and_the_pin_must_be_frozen` |
| Protective exits unaffected | the check is entry-only; exits never reach either hook | `test_the_check_is_entry_only_is_rechecked_in_the_final_guard_and_never_awaits_research_persistence` |
| SBUX | one contract, TP2 exit: 1.316R, fails the 3R rule | `test_sbux_one_contract_is_1_316r_at_tp2_and_fails_the_3r_rule` |
| Baseline kept until activation | default `off`: the entry reaches the venue and nothing is recorded; other desks run no first-sale code | rig: `test_default_off_reaches_the_venue_and_records_nothing`; `test_base_runner_is_off_and_other_desks_run_no_first_sale_code` |

### IR-02 - executable-profit coverage (`book-snapshot-v2`: `technique/profit_capture.py`)

| Requirement | What the candidate does | Proof (`tests/test_em_profit_capture.py`) |
|---|---|---|
| Unknown provenance stays unknown | `quote_problems`: identity, `source_unknown`, admissible sources only (the Yahoo and sim feed identities are inadmissible), venue quote time, regular session, halted, finite two-sided prices, known size AND size unit. The runtime never writes an invented `feed` source | `test_reviewer_reproduction_1_an_unknown_source_is_never_scorable`, `test_anything_short_of_validated_venue_evidence_is_unknown_and_never_makes_a_peak` |
| Depth spent once per contract/side across the whole book | one allocation per (symbol, side), pending exit reservations first, positions in deterministic order; two 2-lots against bidSize 2 leave the basket unscorable | `test_reviewer_reproduction_2_displayed_depth_is_spent_once_across_the_book`, `test_pending_quantities_are_conserved_and_a_skewed_or_share_basket_needs_the_same_proof` |
| Partial, stale or unsynchronized baskets never make a peak | a basket with any unscorable leg, skew above 5 s or a quote older than 10 s is unscorable; the reducer takes peaks from scorable books only | the two tests above, `test_reducer_peaks_attribution_from_executions_gaps_duplicates_and_full_reconciliation` |
| A midpoint is not executable value | long exits at the bid; spread is never deducted twice | `test_a_midpoint_spike_is_not_executable_value_and_spread_is_never_deducted_twice` |

### IR-03 - durable profit accounting (`profit_capture.py::build_ledger`, `profit_capture_runtime.py`)

| Requirement | What the candidate does | Proof |
|---|---|---|
| Session totals recovered from executions across restart and disarm | `SessionLedger` reads the session's executions incrementally on the recorder task (never on a protective path); totals do not depend on in-memory trades | `test_restart_disarm_prior_session_and_duplicate_writes_through_the_real_collector_and_storage` (the real collector + Postgres) |
| Prior-session results excluded | the ledger window is the session; a sell with no session buy is a ledger error, and a ledger in error is unscorable | `test_the_ledger_is_executions_only_excludes_prior_sessions_and_keeps_per_trade_attribution`, `test_a_ledger_that_is_pending_wrong_or_inconsistent_with_the_held_quantity_is_never_scorable` |
| Closed-trade attribution retained | FIFO round trips keyed by the entry order id; `closedTrades` ride every final ledger and the reducer attributes from them | the reducer test above |
| Fees, cash and final net reconcile | reducer v2 reconciles net, fees, the sum of closed trades, and cash minus ledger flow; a transfer is identified and not counted as P&L | the reducer test + the Postgres case (includes a transfer) |
| Idempotent recorder retries; a restart is a distinct identity | `captureId` = hash of observer instance, sequence and capture time; the write is idempotent on it; a new observer instance is a new identity and the reducer reports `recorder_restart` gaps and ignores duplicates | `test_retries_keep_the_same_capture_id_and_a_failed_finalize_is_written_unscorable`, the Postgres case |

### IR-04 - no diagnostic delay on the entry path

| Requirement | What the candidate does | Proof |
|---|---|---|
| New collectors default OFF | `first_sale_rr_gate = off` (revision 1 shipped `observe`), `book_snapshot_observe`, `source_scenarios_observe`, `source_candidates_observe`, `source_candidates_chain_fetch` all off | `test_em_default_is_off_and_an_invalid_setting_is_invalid_not_off`, `tests/test_em_integrated_api.py::test_manifest_shows_every_new_knob_at_its_safe_default` |
| Research persistence bounded and nonblocking, including the first-sale journal path | `technique/research_recorder.py::BoundedRecorder`: `put_nowait` into a bounded queue, bounded retries, a timeout per write, visible drops. `_first_sale_check` awaits no research write | rig: `test_observe_with_a_blocked_research_writer_never_delays_or_refuses_the_entry`; `test_snap_is_synchronous_the_ledger_is_attached_off_path_and_saturation_is_visible`, `test_the_runner_calls_are_sync_never_awaited_and_bracket_the_exit_before_the_order` |
| Refusal evidence is not lost | an enforced refusal is journaled on the established `_refuse_entry` order path with a `detail` payload | rig: `test_enforce_defers_without_validated_underlier_evidence_and_journals_the_refusal` |
| Every new active code path disclosed | section 7, "Code that runs by default (rev 2)" | - |

### IR-05 - forward candidate feasibility and causal identities

| Requirement | What the candidate does | Proof |
|---|---|---|
| Supplied contemporaneous evidence produces evaluated results | `candidate-pricing-v1`: contract, quote, spread (10%), sizing, budget and executable-price no-chase (the `first-sale-v2` admission); overall feasible / infeasible / unknown | `tests/test_em_source_candidates.py::test_complete_contemporaneous_evidence_produces_evaluated_gates_and_the_identical_case_without_it_stays_unknown`, `test_supplied_evidence_is_really_judged_wide_spread_run_away_budget_and_stale_inputs` |
| Missing evidence stays unknown; never back-filled | evidence must be within 3 minutes of the trigger; the pricing is decided once and frozen | `tests/test_em_integrated_api.py::test_forward_pricing_evidence_is_gathered_once_at_the_trigger_frozen_and_never_backfilled` |
| Candidates stay order-free; the research fetch is separately configured | origin `scenario:*` never arms; the chain read is behind its own OFF knob at background provider priority | `test_the_pricing_stage_cannot_arm_or_order_and_the_research_fetch_is_separately_configured`, `test_every_candidate_is_order_free_by_origin_and_has_one_id_per_branch_and_session` |
| Prep cache identity; no cached approval survives a conflicting input | the key carries bars, as-of, thresholds, dataset, policy + review version, grade floor, mode, origin, analyst verdict and reasons, source revision ids, scenario and correction ids, holds | `tests/test_em_preparation_policy.py::test_no_cached_approval_survives_a_new_hold_a_correction_a_new_review_or_a_policy_change` (a Postgres boundary case, not a hash-stability test) |
| Author, direction and scenario fidelity; zero-model path; honest comparison | unchanged from revision 1 and retested: `tests/test_em_source_scenarios.py`, `test_em_preparation_policy.py`, `test_em_prep_compare.py` | section 5 |

### The dispatch tests (verification requirement)

The reviewers asked for the cause, not an after-hours guess. Revision 1 guessed, and the guess was WRONG. Cause: `PlanArmer.size_multiplier`
read the wall-clock weekday. On a Friday the 0.5 multiplier sized a contract with 150 dollars of risk to zero against a 100 dollar budget, so
the entry never reached the RiskGate. Fix: the weekday comes from the test-pinnable `zargar.clock` (production = real time), and
`tests/conftest.py` pins a controlled Wednesday session clock (`2026-09-16T10:00:00-04:00`) for the modules `test_codex_em_final_dispatch_*`
only. The reviewer files are unchanged. The unchanged cases were run under a pinned clock before and after the fix. All four dispatch cases
now pass (section 5).

## 0b. Shared-file owner reviews (obtained before handback; reviews only, neither is a deploy go)

**Tips / platform desk** (owner of `execution/planrunner.py`, `models.py`, `api/app.py`, `settings_service.py`, `technique/vision.py` shared
surface). First review of the exported shared diff at `7002426d`: no objection to the hook placement, the fill call sites or the additive
tables, routes and defaults, with ONE standing condition: an attached observer's `snap` stays O(1) capture + `put_nowait`, no I/O, no locks
(kept by test). Two findings, both applied in `d0e6f948`: one model price source (`llm.rates`; my duplicate `llm.pricing_table` was removed)
and a failed retried model request is marked `failed`. Re-check of `d0e6f948`: items 1, 3, 4 VERIFIED; item 2 FINDING (unwrap the settings
envelope like their cost tool, make the read-only guarantee real, keep `_meta` out of `pricedModels`). Re-check of `9ea7572e`, quoted:
"Owner re-check of item (2) at 9ea7572e...: VERIFIED. This is a review only, not a deploy go. ... The owner review items are now all closed:
(1), (2), (3) and (4) verified, the snap condition kept by test, and the Team2 contract gap with the Team2 desk."

**Team2 desk** (the other `PlanRunner` subclass owner). Review of `f4ce6ad8..7002426d` (`planrunner.py` is unchanged since), quoted: "NO
OBJECTION for Team2Runner. This is a code-review verdict only, not a go to deploy." They checked name collisions (none), the entry path (with
the base policy `off` the check is one hook call that returns before any await; the final guard reaches their predicate as before), the exit
and fill paths (`_book_snap` is a synchronous dict lookup that cannot delay a reduce-only exit), and ran 367 Team2 cases green on that tree.
Two non-blocking notes, both recorded in PLATFORM-RULES: a desk that overrides `first_sale_policy` with code that raises will refuse entries
(fail-closed, never exits); the duplicate `entry_guard_predicate` definition predates this work. They confirmed the missing
`TechniquePlanDiagnostic` contract is their defect and fixed it in PR #224 (open, not merged, not in this candidate).

## 0c. What revision 1 claimed that is withdrawn

- "Enforce would have refused one of 28 entries (SBUX, a loss)" is withdrawn as a back-test. It read the SAVED geometry. Under
  `first-sale-v2` admission needs the validated executable underlier at the time, which was never captured: all 28 historical rows are
  `unknown` and `enforce` would have DEFERRED every one. SBUX remains a true statement about plan geometry (1.316R at its real exit rung).
- "Every shared diff is inert by default" was false for EM (the awaited journal write under default `observe`). It is now true of the first-sale
  path by default, and the residual default-active code is listed exactly in section 7.
- "The dispatch family may be session-clock dependent (after hours)" was a wrong hypothesis; see the dispatch paragraph above.
- "Dollar cost of the model is unknown because no price row is configured": the platform's one price card `llm.rates` prices claude-opus-5,
  so the comparison now reports an ESTIMATE of about 56 to 65 US dollars per evening at the current card (not an invoice; the card carries no
  effective date). Invoice-verified cost remains unknown.

## 1. What now exists (plain statement)

1. **What an author actually said is preserved** (`source-scenarios-v1`): author, revision, evidence spans with transcript offsets, direction, condition, level, underlying targets apart from option strikes, horizon, avoid / no-chase, and a usable time that is the completion of the last needed input - never the message timestamp. A ticker the evidence does not support is `unresolved`; an extracted ticker whose passage names another ticker is `conflict`. Both are held. Corrections are a new append-only artifact usable only from their own time.
2. **One preparation eligibility owner** (`em-prep-policy-v1`): `baseline` (default, unchanged) and `deterministic` (rules + grade floor, zero model calls). Batch, ingestion and the pre-open re-plan route through it under the proposed policy; one candidate key arms once. An absent review is recorded as absent.
3. **Every source idea is explained**: the source-to-plan table lists every trigger of every matched plan, the policy record and the gate events. Ticker-only and opposite-direction coincidences are never "aligned".
4. **Fresh setups after an early invalidation** (`requalification-v1`) and **source-conditioned continuation** (`source-continuation-v1`) are order-free candidates with their own trackers; the baseline tracker is never reset.
5. **First-sale R at the final quantity** (rev 2: `first-sale-v2`, default OFF): under `observe` it is recorded per EM entry through a bounded recorder and is never authoritative; under `enforce` the validated executable underlying bound owns admission, missing evidence defers, and the decision is re-made at final dispatch (section 0a, IR-01).
6. **Realized, displayed and covered-executable profit are separate numbers** (rev 2: `book-snapshot-v2`): recorder, execution-backed session ledger, reducer, report and UI are built; the recorder is OFF (section 0a, IR-02 / IR-03).
7. **Alternative lifecycles are compared after a shared book** (`prep-compare-v1`, `capacity-v1`), labelled proxy-only wherever no executable evidence exists.

## 2. SBUX event 165135 - exact explanation

Run `8a79a643`, trigger d1 (breakdown, put). Saved plan: entry 96.0907, stop 97.681, targets 94.1689 / 92.2471 / 90.3253,
R:R **3.63 measured to TP3**. Why TP3: `technique.rr_gate_target=auto` resolves to TP3 whenever `technique.arm.contracts=0`
(risk-based sizing: the quantity is unknown at plan time), and the saved config carries `rr_gate_target: 2`. At the fire the
deterministic entry decision 165121 allowed the setup (it checks geometry sides, not R). The runner's entry for a break family
is the confirming close: 95.335. The sizer bought **one** contract. A position of fewer than three contracts leaves whole at
`single_contract_exit` = TP2, so the position's real reward was (95.335 - 92.2471) / (97.681 - 95.335) = **1.316R** against a 3.0
minimum. No fire-time R check existed (the `R2` comments at the order boundary are the 2026-09-14 review item for the TIME
gate, not reward to risk). Verdict: **a violation of the documented rule** "R2 is measured where the position exits" - it was
measured once, with the wrong quantity assumption, and never again. It is an underlying rule and remains one; the missing
observed underlier is `unknown` in the record, never the intended geometry relabelled.

Fix + regression: `technique/first_sale.py`, runner hook `_first_sale_check` (after sizing, before the intent; base = off),
EM producer `PlanArmer.first_sale_record`; `tests/test_em_first_sale.py` (SBUX 1.316R vs 3.0; one / two / three contracts and
shares; repricing changes the inputs; puts signed; unknowns never refuse; 2.99R fails - 3R not weakened; exits never pass
through it). **Rev 2 correction:** the sentence that stood here ("`enforce` would have refused one of 28") is WITHDRAWN as a back-test. It judged the saved geometry; v2 admission needs the validated executable underlier, which history never captured, so all 28 rows are unknown and `enforce` would have deferred them. "Unknowns never refuse" is now true only under `observe`; under `enforce` an unknown DEFERS. Report:
`research/first-sale/2026-09-15_2026-09-18.md`.

## 3. Requirement-by-requirement closure

### A - faithful source scenarios, one decision owner

| Requirement | Where | Evidence |
|---|---|---|
| Scenario artifact on the immutable revision / artifact machinery; author vs app-derived fields with derivations | `technique/source_scenarios.py` (`build_scenarios`, `store_scenarios`, kind `scenarios`) | `test_em_source_scenarios.py` (15): identity, derivations, append-only Postgres case |
| Usable time = when inputs completed; late transcript unavailable earlier | `times.usableAt`, `usable_at()`, matcher `causal` | `test_a_late_transcript_is_unavailable_to_an_earlier_decision` |
| Alternatives as branches with a pair id | `pairId`, `branch` | `test_both_branches_are_represented...` (APP long/short; SPX above/fails) |
| Ambiguous ticker unresolved; MU->TSLA and MBGO fixtures; AVGO a hypothesis | evidence-verified ticker, topic zones | `test_mu_stays_mu...`, `test_ambiguous_mbgo...` on the REAL transcript |
| Strike is not a target; 1155 conflict flagged | `option_mentions`, `underlying_numbers`, `level_conflict` | `test_a_call_strike...`, `test_the_literal_1155...` |
| Edits / deletions create new revisions; corrections append-only | new input hash per revision; `apply_corrections` | `test_an_edited_revision...`, `test_corrections_are_append_only...` |
| Matcher: direction, family, region, targets, causal availability; full trigger set | `match_plan` (`source-plan-match-v1`) | SPCX long vs short reject; NVDA b1..d2 all listed; SPY overnight plan `causal False` |
| One authority owner; ingestion supersession exposed; no duplicate arms | `preparation_policy.select`, `prep_service`, `ingest.board_check` (`owner`, `supersedesModelVeto`, `validTriggers`, deterministic branch) | `test_one_owner_one_arm...`, `test_the_ingestion_path_keeps_its_baseline_branch...` |
| UI / report table; fixtures for both notes | `EmReviewPanel.tsx` Source -> plan; `tools/em_source_scenarios.py`; `tests/fixtures/em_source_notes_2026_09_18.json` | `research/source-scenarios/2026-09-18.md`; `test_em_integrated_api.py` |

### B - deterministic preparation with selective model evidence

| Requirement | Where | Evidence |
|---|---|---|
| Versioned policy distinct from `fire_decision_mode`; baseline default; effective policy on preflight / board / arm snapshots | `preparation_policy.effective`, `PlanArmer._em_policy_extras`, board `policy` | `test_defaults_are_baseline...`, `test_the_effective_policy_rides...` |
| Deterministic mode: zero model calls; absent review is neither approval nor veto | `decide()` (pure; no model, no I/O) | `test_deterministic_mode_needs_no_model...` |
| Conditional-plan review fix, per-trigger reasons, no auto-approval | `classify_clause`, `review_semantics`, `conditionalFix` | four tests incl. the REAL 09-18 reviews: nothing rescued, objections kept |
| Audit sampler, default zero | `audit_sampled` (stable hash, quota) | `test_audit_sampler_is_stable_and_zero_by_default` |
| Causal-input cache / resume (rev 2: identity also carries origin, analyst evidence, scenario / correction ids, holds, policy + review version) | `causal_input_key`, `prep_service.input_key_for`, `plan_batch`, table `technique_prep_decisions` | `test_hashes_are_deterministic...`, `test_resume_reuses...`, Postgres ledger case (a preview writes nothing) |
| Lazy charts in deterministic paths, on-demand kept | `service.analyze` `render_charts` | `test_lazy_charts_in_every_deterministic_preparation_path...` |
| Model cost tracking, four kinds apart | `technique/model_costs.py`, `vision.py` request ledger, the platform's one price card `llm.rates` (rev 2; owner finding) | `test_costs_are_never_invented...`, `test_the_pipeline_keeps_a_request_ledger` |
| Comparison command | `tools/em_prep_compare.py` | `test_em_prep_compare.py` (4); report `research/prep-compare/2026-09-15_2026-09-18.md` |
| Frozen prospective definitions + horizon | `research/PROSPECTIVE-DEFINITIONS-2026-09-19.md` (supersedes the 09-18 file before any data was collected) | - |

### C - source continuation and requalification

| Requirement | Where | Evidence |
|---|---|---|
| Two separately identified order-free variants consuming A and B | `technique/source_candidate_policy.py`, `technique/requalification.py` | `test_em_source_candidates.py` (rev 2: 14, incl. three pricing-stage cases) |
| Fresh structure by the existing causal pivot detector; rebound alone insufficient; pivots unusable before confirmation | `fresh_structure` (`find_pivots`, window 3) | `test_no_reset_fresh_confirmed_structure...` |
| Same windows and source expiry; NVDA 15:55 not captured | `source_expiry_ts`, production `TriggerTracker` | `test_the_source_horizon_is_not_extended...`, afternoon-break case expires |
| One child per branch per session; unique parent / child ids | `child_id`, `existing_children` | `test_r2_target_provenance_the_stop_cap_and_the_one_child_limit` |
| Causal entry timing; no same-close fill; gates at eligibility and at pricing | own tracker, `upto_ts`, `pricing_gates` (rev 2: `candidate-pricing-v1` - EVALUATED on contemporaneous evidence, unknown without it) | `test_the_evaluator_is_causal...`; late-born candidate never sees earlier bars |
| MU volume and AMD 2.97R stay named; cost / benefit diagnostics | `namedBaselineOutcome`, `exclusion_diagnostic` | AMD / SPCX refusals; report section 3 |
| Producer, persistence / resume, replay + forward evaluator, table, UI dispositions | `evaluate_session`, `source_candidates_runtime.py` (loop OFF), table `technique_source_candidates`, panel Candidates | `test_the_forward_candidate_pass_is_off_by_default_order_free_and_restart_idempotent` |
| Never arms through any path | origin `scenario:*` (existing runner boundary) | `test_every_candidate_is_order_free...`; no `technique_armed` row after a pass |

### D - first-sale economics and quote integrity

| Requirement | Where | Evidence |
|---|---|---|
| SBUX explained and regressed | section 2 | `test_em_first_sale.py` (rev 2: 23 functions incl. six real dispatch-rig cases) |
| One versioned record for diagnostics and research | `first-sale-v2` (rev 2), event `TechniqueFirstSale`, route `/api/technique/em/first-sale`, panel First sale | producer test freezes live inputs without inventing the underlier |
| Vehicle comparison, order-free; BMNR / DRAM fixtures | `compare_vehicles`; near-money rows of the chain already fetched (`near_money_rows`, no extra request) | DRAM-shaped fixture test; historical limit stated in the report |
| Sim cap stays opening-only and OFF; quote provenance kept | unchanged (`test_em_sim_option_spread.py` still green) | - |
| ORCL producer audit, no cash rewrite | read-only | both fills `source: opra`, no transform; the 0.76/1.12 entry book is the doubt |
| DRAM / SKHY bounded timelines; held-position fix only where a defect is established | TRADING-RULES 2026-09-18 evening | DRAM: no EM defect, unchanged. SKHY: one bounded re-pick, OFF, no-chase guarded |

### E - ED-04 executable-profit capture (implemented, not designed)

| Requirement | Where | Evidence |
|---|---|---|
| EM-only record + bounded async recorder, default OFF, new namespaced knob | `technique/profit_capture.py`, `profit_capture_runtime.py`, knob `book_snapshot_observe` | `test_em_profit_capture.py` (rev 2: 16 functions incl. both reviewer reproductions and the real collector + Postgres case) |
| Cadence + before / after target, stop, protection, fill | runner `_book_snap` call sites | `test_the_runner_calls_are_sync_never_awaited...` |
| Identity, realized, fees, cash, marks with basis, quantities incl. pending, quote provenance, covered estimate, scorable + skew | `capture_position`, `capture_book` | midpoint spike vs executable; stale / delayed / derived / unknown size -> unknown; skewed basket unscorable; pending conserved; shares need depth too |
| Drops visible; never awaited; bounded memory / retries | `ProfitCaptureObserver` | saturation, failed-write retry with original timing, restore marker, flat-book rule |
| Reducer + report + UI; reconcile to execution cash; unexplained difference = error | `reduce_session`, `tools/em_profit_capture.py`, panel Profit capture | peaks, giveback, coverage gaps, reconciliation error case |
| P-02 kept; P-06 consumer integration | `summarize_paired` (strict identity and time), existing P-06 reducer untouched | sacrificed winner retained, actual fees reconcile; wrong instance / pre-signal / post-close -> no context |
| No new profit lock or blanket exit | none added | - |

## 4. Acceptance matrix (plan section 9)

| Area | Status | Tests |
|---|---|---|
| Source identity | met | `test_em_source_scenarios.py` |
| Source fidelity | met | same + `test_em_source_candidates.py` |
| Conditional planning | met | `test_em_preparation_policy.py` |
| Deterministic prep | met | same (hashes, resume, cache invalidation, explicit no-review, other desks untouched, lazy charts) |
| Authority | met | same + API test (no arm from a candidate pass) |
| Requalification and forward feasibility | met on rev 2 (IR-05) | `test_em_source_candidates.py`, `test_em_integrated_api.py` |
| Economics | met on rev 2 (IR-01, IR-04) | `test_em_first_sale.py` |
| Portfolio capture | met on rev 2 (IR-02, IR-03) | `test_em_profit_capture.py` |
| Paired exits | met | existing `test_em_runner_protection.py` (13, unchanged) + the new consumer case |
| Comparison | met | `test_em_prep_compare.py` + the reconciled report |

## 5. Tests on the candidate (rev 2: every run below is on the exact SHA `9ea7572e`)

Environment: Windows 11 host, Python 3.13, venv `C:/Cursor/zargar/backend/.venv`, Postgres on 127.0.0.1:5433, run from the worktree
`backend/`, sequentially, one pytest process at a time, 2026-09-18 evening PT (market closed), about 5 GB free RAM. Each output file starts
with `git rev-parse HEAD` = `9ea7572e97b6016cc7d4bbb5ceb40a785bbc8a6f`.

| Run | Files | Result |
|---|---|---|
| EM + reviewer EM + reviewer worker suites (private DB `zargar_test_em`) | every `tests/test_em_*.py`, `test_codex_em_*.py`, `test_codex_worker_*.py` except the two that refuse any database but the reviewers' | **306 passed, 5 skipped, 0 failed** (3 min 22 s). The 5 skips are the pre-existing `HISTORICAL` marks in `test_em_review_da_reconcile.py` |
| of which the new and changed suites | `test_em_first_sale.py` 23, `test_em_profit_capture.py` 16, `test_em_source_candidates.py` 14, `test_em_integrated_api.py` 5, `test_em_preparation_policy.py` + `test_em_prep_compare.py` + `test_em_source_scenarios.py` | all passed (counts are test functions; several are parametrised) |
| Technique / platform / options batch (private DB) | `test_technique_{api,ingest,ingest_flow,lifecycle,options,setups,walkforward,review,universe,detection,arm_expired}`, `test_platform_{separation,phase0,phase3}`, `test_options_{service,occ,greeks_freshness}`, `test_armed_summary` | **215 passed, 2 failed** (10 min 59 s); both failures are baseline, table below |
| Arming, solo | `tests/test_technique_arming.py` | **30 passed, 1 failed** (8 min 56 s): `test_auto_options_one_contract_lifecycle`, the known baseline failure |
| Reviewer-database files (`zargar_test_codex`; zero connections verified immediately before) | `test_codex_em_final_dispatch_budget.py`, `test_codex_em_final_dispatch_quote.py`, `test_codex_em_source_backfill.py`, `test_codex_em_source_ordering.py`, `test_em_reconcile_real_session.py`, `test_reconcile_postgres_atomicity.py` | **26 passed, 0 failed** (24 s). The four dispatch cases that failed in revision 1 pass under the controlled session clock |
| Other desk, their own run | Team2 desk: `tests/test_team2_*.py` + `tests/test_codex_team2_*.py` on a worktree detached at `7002426d` (`planrunner.py` identical to the final SHA) | 367 passed (their report, their database) |
| Frontend | `npm run build` (typecheck + production build + `check-release`) on `9ea7572e` | green |
| Import smoke | `python -c "import zargar.api.app"` | ok, 0.8.21 |

Reviewer regressions: every adopted reviewer file is byte-for-byte unchanged; none was weakened, skipped or deselected.

**Genuine baseline failures (3), kept apart from this delivery.** Each fails identically on the unmodified base `f4ce6ad8`:

| Test | Evidence it is baseline | Owner / status |
|---|---|---|
| `test_platform_phase3::test_every_journaled_kind_has_a_contract` | fails on `TechniquePlanDiagnostic`; reproduced on origin/main by the Team2 desk, who own the event | fixed by their PR #224 (open, not merged). This delivery's own event `TechniqueFirstSale` has a contract and validates |
| `test_options_service::test_option_order_practice_roundtrip` | times out on base `f4ce6ad8` in a scratch worktree, with AND without a pinned session clock, so it is not the weekday cause fixed here | platform options; not touched by this delivery; cause not established by me |
| `test_technique_arming::test_auto_options_one_contract_lifecycle` | known baseline failure since 2026-09-16, unchanged | EM backlog, outside this plan |

An identical failure on main does not show the affected path works. What this candidate shows for the EM order path is the opposite kind of
evidence: the real dispatch rig cases in `test_em_first_sale.py` and the reviewers' four dispatch cases reach the RiskGate and the venue and pass.

Not run: the full 358-file repository suite (other desks' suites; the host cannot run them in parallel and the review asked for no
indiscriminate campaign); `scripts/test-codex.ps1` itself (the same files were run with the same database after verifying it was idle);
`npm run mobile-audit` (section 10).

## 6. Reports (September 15-18; all retrospective, read-only, zero model calls; all regenerated on the final code)

| Report | Path | Reproduce |
|---|---|---|
| Source-to-plan, candidates (now with the executable-pricing column), exclusions, corrections layer | `research/source-scenarios/2026-09-18.md` (+ `.json`), corrections `research/source-corrections-2026-09-18.json` | `python -m zargar.tools.em_source_scenarios report --date 2026-09-18 --corrections <file>` |
| Preparation comparison | `research/prep-compare/2026-09-15_2026-09-18.md` | `python -m zargar.tools.em_prep_compare --dates 2026-09-15,2026-09-16,2026-09-17,2026-09-18` |
| Executable profit | `research/profit-capture/2026-09-15..18.md` | `python -m zargar.tools.em_profit_capture report --date <d>` |
| First-sale R (`first-sale-v2`) | `research/first-sale/2026-09-15_2026-09-18.md` | `python -m zargar.tools.em_first_sale report --dates ...` |
| Per-session profitability (existing tool) | `research/profitability/` | `python -m zargar.tools.em_profitability report --date <d>` |

What they say, with the unknowns kept:
- **Actual baseline**: -220.30 / -147.55 / +222.65 / -299.33 = **-444.52** after commissions, excluding model cost. ORCL 09-17 stays flagged as disputed; the ledger is not rewritten.
- **Proxy comparison under one shared book**: model-selected +7.68 / -0.93 / +0.85 / -3.52 R; deterministic +7.90 / -1.76 / -0.40 / -2.78 R; frozen exception -1.93 / -0.93 / -3.75 / -2.18 R. Underlying replays only: no option evidence exists for plans that were not traded, so none of it is dollars. The deterministic path made ZERO model calls; the comparison does not show it is better.
- **Model cost** (rev 2): about 4M input and 1.5M output tokens per evening. ESTIMATED at the current `llm.rates` card: about 65.0 / 59.5 / 64.5 / 56.3 US dollars per evening. The card carries no effective date, so this is an estimate and not an invoice. Invoice-verified cost: UNKNOWN. Requests without a completion: counted, cost UNKNOWN.
- **First sale** (rev 2): validated executable underlier at admission was never captured, so v2 admission is UNKNOWN for all 28 historical entries. By saved geometry, one entry (SBUX) was below 3R at its real exit rung. No back-tested refusal count is claimed.
- **Executable profit for the four sessions is UNKNOWN**: the recorder did not exist. The reports reconstruct nothing from marks.
- **Forward candidate pricing for the four sessions is UNKNOWN**: no contemporaneous contract evidence was captured for candidates; every pricing gate reads unknown.
- **Conditional-review mismatch**: real, but never the sole veto on 09-18; nothing is rescued.
- **Source fidelity on 09-18**: none of the five EM positions was a highlighted author idea; the aligned AMD and SPCX-long triggers were rejected by R2 (2.97R, 2.56R) and the armed SPCX trigger was the opposite short. The author's own result is unknown.

## 7. Migrations, schema, defaults and the code that runs by default

Additive only (`db.create_all` creates missing tables; no column is dropped or renamed; no historical row is rewritten; no money write).

| Table | Written by | When |
|---|---|---|
| `technique_book_snapshots` (primary key = the capture id, so a retried insert is idempotent) | ED-04 recorder | only with `book_snapshot_observe` on |
| `technique_prep_decisions` | `prep_decide(persist=True)` | only under the deterministic policy or an explicit batch call; previews never write |
| `technique_source_candidates` | forward candidate pass | only with `source_candidates_observe` on |
| `technique_source_artifacts` kind `scenarios` (existing table) | board check | only with `source_scenarios_observe` on |

Restore and idempotence checks: `test_the_forward_candidate_pass_is_off_by_default_order_free_and_restart_idempotent` (a second pass after a
restart writes no second row and never re-prices); the ED-04 Postgres case (restart = new observer identity, `recorder_restart` gap reported,
a duplicate write acknowledged once); `create_all` run twice on the test databases by the fixtures. Dry run on the runtime: all four report
tools ran against the runtime database with `default_transaction_read_only = on`; the profit-capture report confirms the new table is absent
there and degrades to UNKNOWN.

### Collection manifest (every knob; default = effective after a deploy unless someone changes it)

| Knob | Default | Effect when changed |
|---|---|---|
| `techniques.enhanced_market.first_sale_rr_gate` | **`off`** (rev 2; was `observe`) | `observe`: records `TechniqueFirstSale` per entry through the bounded recorder, never authoritative. `enforce`: refuses / defers, rechecked at final dispatch. Any other value refuses entries |
| `techniques.enhanced_market.book_snapshot_observe` / `book_snapshot_seconds` | `False` / `30.0` | ED-04 recorder and its cadence |
| `techniques.enhanced_market.source_scenarios_observe` | `False` | board check builds and stores the scenarios artifact; ingestion runs the supersession query |
| `techniques.enhanced_market.source_candidates_observe` | `False` | one-minute order-free candidate pass during the session |
| `techniques.enhanced_market.source_candidates_chain_fetch` | `False` (new in rev 2) | lets the candidate pass read an option chain at background provider priority when the cache has none |
| `techniques.enhanced_market.preparation_policy` | `baseline` | `deterministic`: rules select, zero model calls |
| `techniques.enhanced_market.prep_grade_floor` / `conditional_review_fix` / `prep_audit_quota_pct` | `B` / `report` / `0.0` | as in revision 1 |
| `techniques.enhanced_market.pick_retry_after_429_s` | `0.0` | one bounded option re-pick after a provider 429 |
| `llm.rates` | unchanged platform setting | the ONE model price card (rev 2: my duplicate `llm.pricing_table` was removed before it ever shipped) |
| Already on by user decision, untouched | `shadow_exit_observe`, `shadow_p02_candidate` = True; `fire_decision_mode` = deterministic | P-02 / P-06 collection continues exactly as before |

### Code that runs by default (rev 2: the accurate list, with every new collector OFF)

1. `PlanRunner._first_sale_check`: one call of the runner's `first_sale_policy()` per entry. Base runners return the constant `off`. EM reads one setting from the in-memory settings cache. With `off` it returns before any await. No record, no write.
2. `first_sale_final` inside the final entry guard: one call, returns None unless the mode is `enforce` or invalid.
3. `PlanRunner._book_snap` at the fill, exit and quote-watch sites: a synchronous attribute check that returns when no observer is attached. EM attaches its observer object at start, and the observer's `snap` reads one setting and returns when the knob is off. Never awaited; exceptions are swallowed.
4. The candidates loop task: wakes once a minute, reads one setting, sleeps. No engine read while off.
5. `technique/vision.py` request ledger: each model pass appends a small `modelRequests` row to the run result it already writes (status started / completed / failed, attempts, usage). Active by default on paid analysis runs; adds no request and no await.
6. `PlanArmer.size_multiplier` reads the weekday from `zargar.clock.now_ms()` instead of the wall clock. Identical in production; pinnable in tests.
7. `technique/ingest.py` passes source ids into the preparation owner; the supersession query runs only with `source_scenarios_observe` on.
8. `option_pick(near_money=...)` is passed only when the first-sale mode is observe or enforce; with `off` the pick is called as before.
9. `_refuse_entry` gained an optional `detail` keyword. `tests/conftest.py` gained one autouse fixture that acts only for modules named `test_codex_em_final_dispatch_*`.
10. API: one read-only router (`/api/technique/em/*`) and the Validation-tab review panel. They query on demand only.

## 8. Rollout, readiness and rollback packet (next coordinated market-closed window; nothing here was executed)

1. Re-read `origin/main` and the runtime head; the candidate must CONTAIN the runtime commit (fast-forward only, never reset or downgrade). On a version collision renumber THIS block to the next free number, rebuild, rerun `check-release`. If Team2's PR #224 has merged, merge main first: the two contract lines sit in different hunks.
2. `python -c "import zargar.api.app"`, `npm run build`, `npm run check-release` on the final SHA.
3. `GET /api/ops/restart-check` must be safe: no open positions, no working entries, no pending exits, no in-flight orders, no preparation batch, no other desk mid-work. Not during regular hours. Never restart to hurry this delivery.
4. Save the before-inventory (armed ids by technique, resting orders, helper windows).
5. Deploy only through `scripts/deploy.ps1 -TargetCommit <full sha> -Expect 0.8.21` from `C:/Cursor/zargar` under the deployment lease. Never Stop-Process, never `start.ps1` from an assistant shell. The deploy is a user decision; two peer reviews are not a go.
6. Verify: `/api/health` version and launch-bound build; armed ids equal by id per technique; resting orders equal; Discord gateway and EM ingestion helpers up (exactly one of each); the three new tables exist and are EMPTY; `GET /api/technique/em/manifest` shows every default above, `first_sale_rr_gate = off`; the first EM entry of the next session is NOT accompanied by a `TechniqueFirstSale` event; P-02 shadow-exit events continue.
7. After the deploy only: record the SKHY miss in the counterfactual ledger; never a synthetic fill in a book. The FIX-01 v4 money repair stays a separate human step.
8. **Rollback without losing evidence** (journaled `PATCH /api/settings`, no restart). It touches ONLY the switches this delivery added, each back to its shipped default, and only those that were changed: `techniques.enhanced_market.book_snapshot_observe=False`, `first_sale_rr_gate=off`, `source_scenarios_observe=False`, `source_candidates_observe=False`, `source_candidates_chain_fetch=False`, `preparation_policy=baseline`, `conditional_review_fix=report`, `prep_audit_quota_pct=0`, `pick_retry_after_429_s=0` (`book_snapshot_seconds` and `prep_grade_floor` are inert while their feature is off). **Never part of a rollback, left exactly as they are:** the established P-02 / P-06 collection `shadow_exit_observe=True` and `shadow_p02_candidate=True`, `fire_decision_mode=deterministic`, `fire_evidence_mode`, `ingest.auto_arm`, every risk limit and every other desk's setting. Rows already written stay. No path here owns an exit, so positions are managed exactly as before. Code rollback = deploy the previous build through the same protocol; the additive tables can stay. (corrected 2026-09-19: the earlier wording "every `*_observe` knob" wrongly swept in the established P-02 / P-06 switches)

## 9. Recommendations (separate decisions; none taken here)

Deployment and each activation are separate. Order follows the review: measurement first, enforcement last.

| Step | Recommendation | Why / trade-off |
|---|---|---|
| 1. Deploy the candidate with everything OFF | Yes, in a safe market-closed window | behaviour-neutral by the list in section 7; it is the precondition for any evidence |
| 2. ED-04 recorder ON (`book_snapshot_observe`) | **First activation.** Measurement, not policy | nothing can be learned about executable giveback without it. Cost: about one row per 30 s while a position is open plus event rows; no fetch, no model; drops are visible. Read the first session's coverage and unscorable reasons before trusting any peak |
| 3. `first_sale_rr_gate = observe` | **Second**, after a clean recorder day | it starts capturing the validated executable underlier at admission, which is exactly the evidence history lacks. Non-authoritative; the bounded recorder cannot delay an entry. Review unknown rates and dispositions after at least 10 sessions |
| 4. Source scenarios + candidates ON | Third; order-free | one pass a minute in the session; keep `source_candidates_chain_fetch` off until the cached-evidence hit rate is known |
| 5. `first_sale_rr_gate = enforce` | **Not now, and not on the strength of one avoided loser.** | the historical sample cannot evaluate v2 admission at all (28 of 28 unknown). Enforcing the documented 3R invariant may be justified once the observe sample shows how often evidence is missing (each missing case would DEFER an entry) and what the refused entries did afterwards, winners included |
| 6. `preparation_policy = deterministic` | **Not yet** | the proxy comparison does not show it is better; it meets the loss halt more often. It would save an estimated 56 to 65 dollars an evening. Decide after the declared horizon on after-cost dollars |
| 7. `conditional_review_fix = apply`, `pick_retry_after_429_s` | leave at defaults | the first rescued nothing on 09-18; the second is optional and small |

## 10. Remaining scope, deviations and limits (reported once)

1. Nothing in this delivery is evaluated yet. The validation sample starts per `research/PROSPECTIVE-DEFINITIONS-2026-09-19.md` (which supersedes the 09-18 file before any data was collected; the 09-18 file is kept unchanged with a pointer).
2. The conditional-review fix is report-only under baseline and the model prompt is unchanged, to preserve baseline preparation.
3. Scenario artifacts are not stored for past notes: storing is the ingestion path behind its OFF knob; the 09-18 table is built on the fly, read-only. The reviewed MU correction is a file, applied as a separate later-usable layer.
4. Historical vehicle comparison is limited to the picked contract: no intraday alternative rows were ever stored. Forward capture rides the first-sale record at zero extra requests once that knob is on.
5. Admissible quote sources for executable scoring are `opra` and `ibkr`. A feed that cannot name a venue source yields unknown, by design; if the Practice feed cannot supply one during the session, ED-04 coverage will be low and will say so.
6. DRAM: no change (no EM-side defect established). The shared simulator's treatment of an unchanged standing quote is left to its owners.
7. The author's live replay / ledger remains inaccessible; his result stays unknown. Nothing was bought, messaged or subscribed.
8. `npm run mobile-audit` was not run: the panel lives on the Validation tab, which phones replace with the desktop-only notice.
9. Open defects outside this plan, unchanged: the three baseline test failures in section 5; the `max_open_trades` skip still lacks a reason text; the duplicate `entry_guard_predicate` definition in `planrunner.py` (pre-existing).
