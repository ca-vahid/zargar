# EM integrated delivery - final-completion response (2026-09-19)

Answers `EM-FINAL-COMPLETION-GOAL-2026-09-18.md` (sections 1 to 8), which consolidates the integrated plan, the candidate review (IR-01..IR-05) and
the revision-2 review (R2-01, R2-02). ONE candidate, ONE packet. Owner: EM desk. This document governs; where it conflicts with
`INTEGRATED-DELIVERY-RESPONSE-2026-09-18.md` (revisions 1 and 2) this one is right. During this goal nothing was deployed, no trading policy was
activated, no preparation was re-run, no historical money row was rewritten, no paid model call was made, no other desk was interrupted, and the
runtime database was only read (session-level read-only, probed). All new collectors and candidate policies stay OFF.

## 0. The exact tree

| Item | Value |
|---|---|
| Final merged SHA | **`2d7f51bb7874c7ba5f769a2d3a81c2f2bb93b217`** on `claude/technique-review-trade-plan-fbb9ba`, version **0.8.23** (quartet + lockfile agree; `npm run build` + `check-release` green; `import zargar.api.app` ok) |
| Last CODE commit | `d723cad904c653bf94c128323ebaa1a7bef4be9b`. `git diff d723cad9..2d7f51bb --stat` touches only `docs/` (my reports and definitions, main's Cartel documents) and two TEST files: my `tests/test_technique_arming.py` helper fix and main's `tests/test_options_service.py` fix (PR #229). No application code differs |
| Ancestry | contains the reviewed candidate `9ea7572e` / receipt `a45872b0`; contains origin/main `f621d49f` (0 behind) and the runtime head `4801aa3061e95583dfcbc37b6a01c88f37188275` (0 behind; live v0.8.22, `/api/health` ok). The runtime commit is NOT an ancestor of main (it is a deployment integration branch), so both were merged. Fast-forward only from the runtime; never a reset |
| Version | main and the runtime took 0.8.21 and 0.8.22 (Cartel) while this work ran. MY block was renumbered to the next free number, **0.8.23**; the other desk's released blocks are verbatim; the runtime side's `build_sha` helper is kept |
| Commits of this goal | `bccfbe25` (sections 1 to 6), `5d46902c` + `07f54131` (runtime and main merges, renumber), `40c0bf00` (owner finding: transaction-scoped arm lock), `d723cad9` (owner nit: SQLSTATE), `f4fbc17f` (docs + main's docs), `2d7f51bb` and its parent (arming test helper fix + main's test fix), then docs |
| Docs-only receipt | any commit after `2d7f51bb` touches `docs/` only: `git diff 2d7f51bb..HEAD --stat` |

## 1. Closure table - fixed OR already correct, with the producer / caller tests

"Rig" = the real `PlanArmer` on the sim engine with a real `OrderManager` and RiskGate. "Postgres" = the real storage on a private test database.
Every test named here passed on `f4fbc17f`, whose application code is identical to the final SHA, or on the final SHA itself (section 3 says which).

### Section 1 - execution-backed accounting and attribution (`technique/profit_capture.py`, `profit_capture_runtime.py`)

| Requirement | Status | What and where | Proof (`tests/test_em_profit_capture.py` unless said) |
|---|---|---|---|
| Different entries in one contract never collapse; partial fills of one entry combine; exits and fees belong to the owning trade; unknown linkage is explicit | **FIXED (R2-01 reproduced)** | the trade instance is the ENTRY ORDER. `resolve_links` binds orders from the runner's journaled `TechniquePlanOrderResult` rows: an exit by its journaled `entryOrderId` (new additive key), an older event by the run + trigger journal sequence. `build_ledger` errors, and the ledger is `unreconciled` (unscorable), on an unlinked execution, a carry-in, an exit beyond its entry, a side / stage conflict or a symbol conflict. Nothing is attributed by symbol | `test_r2_01_two_entries_in_one_contract_stay_two_trades_with_their_own_exits_and_fees` (the reviewers' A/B case with different prices and fees, an interleaved trim, per-trade AND aggregate cash both asserted, per-trade held-quantity mismatch), `test_partial_fills_combine_refire_is_a_new_trade_and_unknown_linkage_is_never_guessed_from_the_symbol` (partial fills, refire of the same trigger, a cancelled entry, an unlinked exit, an over-sell) |
| Restart and disarm | already correct, re-proved on the new ledger | totals come from executions, never memory | `test_restart_disarm_prior_session_and_duplicate_writes_through_the_real_collector_and_storage` (Postgres) |
| Authoritative instrument / multiplier | **FIXED** | `instrument_of`: the ORDER's security type checked against `options.occ.contract_multiplier`. Missing or conflicting identity = error, cash flow unknown. The symbol-length heuristic is gone from the ledger AND from the report tools' `execution_net` | `test_the_money_multiplier_comes_from_instrument_identity_never_from_the_symbols_shape` (a 9-character share symbol the old rule priced x100; an adjusted root; STK with an OCC symbol) |
| Late executions with older timestamps; occurrence vs ingestion time | **FIXED** | the max-execution-time cursor is removed. `SessionLedger.read` re-reads the WHOLE bounded session of ONE book per capture (executions JOIN orders, plus the journal's `OrderFill` time = ingestion). `lateObserved` lists fills observed more than 60 s after they occurred | `test_a_late_arriving_older_fill_revises_with_provenance_and_the_earlier_capture_is_not_relabelled`; Postgres: `test_two_same_contract_entries_a_late_older_fill_and_an_unlinked_exit_through_the_real_reader_and_storage` |
| Capture-as-of vs later reconciliation | **FIXED** | each capture stores the identity of the executions it knew (`executionSet`, `readAt`). The reducer, given the final executions, marks a capture REVISED when a fill that occurred before it became known later; a revised capture cannot hold the executable peak; the stored capture is never rewritten | same two tests |
| Session boundaries, carry-ins, deposits and repairs, shortened sessions, DST | **FIXED** (calendar) / already correct (transfers) | `session_supported` uses the exchange calendar: a holiday or weekend is `unsupported_session` = unscorable. Quote eligibility ends at the calendar's close (13:00 on an early close). The window is zone-aware. A carry-in exit is an error. A transfer is declared and excluded, an undeclared cash move is a reconciliation error | `test_sessions_follow_the_exchange_calendar_holidays_early_closes_and_dst`; transfer: the Postgres restart test |
| Stable capture identity through ambiguous acknowledgements; storage uniqueness; restart identities; flat-endpoint reconciliation of per-trade totals, commissions, aggregate P&L and cash | already correct, extended | primary key = capture id; a new observer = a new identity | the Postgres restart test; `tests/test_em_integrated_api.py::test_enabled_capture_runs_queue_database_reducer_and_api_with_restart_full_queue_ambiguous_write_and_a_flat_end` |

### Section 2 - forward feasibility (`technique/source_candidate_policy.py`, `source_candidates_runtime.py`, `first_sale.py`)

| Requirement | Status | What and where | Proof (`tests/test_em_source_candidates.py` unless said) |
|---|---|---|---|
| Wrong underlying, expired contract, conflicting OCC / metadata fail; missing identity unknown; a matching quote symbol binds nothing | **FIXED (R2-02 reproduced)** | `contract_identity` parses the symbol with the production OCC parser: underlying must equal the candidate's, the right must match the direction, the expiry must not be past, the 0DTE cut-off applies, explicit metadata that conflicts fails, a non-standard symbol is unknown. On a failed contract nothing downstream is evaluated | `test_r2_02_a_contract_is_bound_to_its_candidate_by_identity_wrong_underlying_expired_and_conflicts_fail` (the reviewers' WRONG / 2026-01-01 case) |
| A genuine executable-price chase check, apart from R | **FIXED** | new gate `chase` (`candidate-chase-v1`): the validated executable QUOTE bound at most 0.25R beyond the entry in the trade's direction. The old gate is renamed `firstSaleR`. A print is not an executable quote: print-only = unknown | `test_r2_02_adequate_r_never_substitutes_for_a_chase_pass` (the reviewers' 100 / 105 case: R passes, chase FAILS; mirrored for puts) |
| Daily-loss allowance, slots, exposure, cash, reservations, quantity caps, first-sale policy; causal snapshot; missing = partial | **FIXED** | gate `portfolio` takes as evidence the PRODUCTION `RiskGate.evaluate` verdict on a dry intent for the sized quantity (no order row: `OrderManager.place` is never called), `engine.trading_halted`, the symbol's open-or-working count vs `max_open_trades`, and working entries' premium (budget is net of it). Snapshot must be within 10 s and for the same quantity. `feasible` only when EVERY gate passes; otherwise `unknown` + `completeness: partial` + the missing gates | `test_r2_02_portfolio_constraints_decide_feasibility_and_missing_constraints_are_partial_never_feasible` (exhausted day budget, full slot, exposure, halt, reservations, stale snapshot, other quantity, no constraints) |
| Production helpers, parity and declared differences | **FIXED** | OCC parser, quote validator, first-sale admission, the RiskGate itself. Every record carries `productionEquivalent: false` and `deliberateDifferences` (the chase bound is research: production EM has no general underlying chase cap; the portfolio gate is a risk-gate verdict, not an order preflight - the owner's wording) | `test_complete_contemporaneous_evidence_produces_evaluated_gates_and_the_identical_case_without_it_stays_unknown` |
| Quote provenance, raw / derived / delayed, venue times, freshness, identity, finite two-sided, depth units, session | already correct + calendar session | `quote_problems` | `test_supplied_evidence_is_really_judged_wide_spread_run_away_budget_and_stale_inputs`, `test_anything_short_of_validated_venue_evidence_is_unknown_and_never_makes_a_peak` |
| Evidence after a trigger is evidence for its own time; declared window; no back-fill, no quote shopping | already correct + `observedAfterTriggerMs` recorded | `attach_pricing` decides once | `tests/test_em_integrated_api.py::test_forward_pricing_evidence_is_gathered_once_at_the_trigger_frozen_and_never_backfilled` |
| Order-free through creation, persistence, API, reuse, replan, restore | already correct | origin `scenario:*` | `test_every_candidate_is_order_free_by_origin_and_has_one_id_per_branch_and_session`, `test_the_pricing_stage_cannot_arm_or_order_and_the_research_fetch_is_separately_configured`, API: `test_the_forward_candidate_pass_is_off_by_default_order_free_and_restart_idempotent` |

### Section 3 - source and candidate causality through the real pipeline

| Requirement | Status | What and where | Proof |
|---|---|---|---|
| Author, contributor, direction, condition, targets vs strikes; MU/TSLA, MBGO, SPCX opposite direction, 700C, 1155, full NVDA trigger set | already correct | `source_scenarios.py` | `tests/test_em_source_scenarios.py` (15, unchanged, green) |
| Authoritative revision AS OF the evaluation; older revisions not independently actionable; edit, identical update, correction, deletion, a worker still reading; history preserved; production positions untouched | **FIXED** | `authoritative_payloads`: per message the highest revision RECEIVED by the as-of time; only that revision's newest scenarios artifact counts; a tombstone has none; while a new revision has no artifact yet nothing older is actionable. `withdraw` turns only NON-terminal candidates of a superseded / deleted source into `source_withdrawn`; terminal rows are untouched; nothing else is written | `tests/test_em_integrated_api.py::test_the_authoritative_revision_is_chosen_as_of_the_evaluation_and_a_withdrawn_source_keeps_its_history` (real loader + storage: edit, replay as of BEFORE the edit, pending revision, tombstone, no armed row). Identical update = no revision at all: existing `test_em_source_revisions.py::test_revision_per_distinct_state_and_redelivery_is_a_receipt` |
| Holds and corrections carried from ingestion to the owner and to candidate creation | **FIXED** (caller) / already correct (pure) | ingestion now passes `source_hold` and the scenario ids INTO `prep_arm`; the candidate loader reads the stored scenario's hold | the same API test asserts the MU/TSLA hold arrives through the real loader; `tests/test_em_preparation_policy.py::test_two_concurrent_workers_...` asserts a hold supplied by the caller stops the arm |
| The plan / thresholds / profile available at the candidate's BIRTH | **FIXED** | `birth_plan`: the newest plan at the source's usable time, else the first built afterwards; plans after the evaluation time do not exist; EVERY plan keeps its own context (`contextByRun`) | `test_the_plan_at_birth_is_used_never_the_latest_plan_of_the_symbol`; API: `test_a_born_candidate_is_frozen_...` (a later re-plan with other thresholds is ignored even with nothing stored) |
| A pivot is knowable when its confirming bar CLOSES | **FIXED** | `confirmedCloseTs = bars[i + w].ts + 60 s`; eligibility = that close; the child is fed only bars that start at or after it; `invalidatedKnownAtTs` documents the parent's close semantics. Honest note: the old code fed the same bars; what was wrong was the recorded availability time, one minute early | `test_no_reset_fresh_confirmed_structure_is_required_and_pivots_are_unavailable_before_confirmation`, `test_a_requalified_candidate_never_sees_bars_from_before_its_own_confirmation` |
| Duplicate / out-of-order / missing minutes; shortened sessions; no baseline reset | **FIXED** | `bars_integrity`: irregular series = held; a missing minute inside the structure window holds the child; the 0DTE source expiry is the calendar's close; a non-session day is held | `test_irregular_bars_are_held_and_a_missing_minute_inside_the_structure_window_holds_the_child`, `test_a_shortened_session_and_a_holiday_use_the_exchange_calendar` |
| One child per branch / session, immutable geometry and identity; two ticks, restart, changed source, duplicate workers | **FIXED** | `definition_of` is frozen at the first persist; later passes resume from it; a terminal candidate keeps its disposition, trigger time, fill proxy and pricing (only the after-the-fact outcome proxy is re-scored; a differing replay is recorded, not applied); an offered re-interpretation is recorded `reinterpretationIgnored`; `branchKey` (note + symbol + direction + board position) survives a source edit; the insert race is idempotent | `test_one_child_per_branch_survives_a_source_edit_and_a_terminal_candidate_is_never_re_decided`; API: `test_a_born_candidate_is_frozen_two_ticks_a_restart_a_later_replan_and_duplicate_workers_change_nothing` |

### Section 4 - preparation ownership and economic comparison

| Requirement | Status | What and where | Proof (`tests/test_em_preparation_policy.py` unless said) |
|---|---|---|---|
| Batch, ingestion, manual arm and pre-open through the same owner; baseline unchanged; absent review is not an approval; conditional semantics apart | **FIXED** (manual / batch door) / already correct (rest) | `TechniqueService.arm_plan`, ONLY under `preparation_policy = deterministic`, routes every arm through `prep_arm`; an ineligible plan is refused; a human override is explicit and recorded (`prepOverride`). Baseline runs none of it | `test_manual_and_batch_arms_pass_the_same_owner_under_the_proposed_policy_and_baseline_runs_none_of_it`, `test_the_ingestion_path_keeps_its_baseline_branch_and_routes_the_proposed_policy_through_the_owner`, the four conditional-review tests |
| Identity includes effective geometry / reference price, bars, source state and holds, thresholds, policy, origin, analyst evidence | **FIXED** (geometry) / already correct (rest) | `input_key_for` adds a hash of the plan's reference price and every trigger's geometry and grade | `test_the_effective_plan_geometry_and_reference_price_are_part_of_the_decision_identity`, `test_no_cached_approval_survives_a_new_hold_a_correction_a_new_review_or_a_policy_change` |
| Two concurrent callers; restart after commit before acknowledgement; unique-key races | **FIXED** | `prep_arm`: a TRANSACTION-scoped Postgres advisory lock on the candidate key with a bounded wait, then a re-check of armed plans IN THE DATABASE, then the arm. The run id stays the arm identity. The decision insert race returns the winner's row | `test_two_concurrent_workers_arm_one_candidate_once_and_a_restart_after_the_commit_does_not_arm_again`, `test_a_cancelled_arm_never_leaves_the_candidate_locked_and_a_waiting_worker_is_bounded` (the owner's requested case) |
| Common causal coverage, chronological capital, proxies vs dollars, missing never a win; rejected winners and avoided losers kept | already correct | `tools/em_prep_compare.py` (`capacity-v1`, `modelRejected`) | `tests/test_em_prep_compare.py` (5) |
| Doubtful simulated fills quarantined in a sensitivity result without rewriting the ledger | **ADDED** | `baselineActualSensitivity`: 09-17 booked +222.65 vs -28.27 with the two disputed ORCL fills set aside; both shown | report line in `research/prep-compare/2026-09-15_2026-09-18.md` |
| Dated estimates apart from invoices, allocation and unknown; zero paid calls | already correct + route and panel | `model_costs.py`; new `GET /api/technique/em/model-cost` | `test_costs_are_never_invented_and_the_four_kinds_stay_apart`; API routes test |

### Section 5 - first-sale admission

| Requirement | Status | Proof (`tests/test_em_first_sale.py`) |
|---|---|---|
| Current-underlier evidence, conservative bound, final quantity, frozen settings, unrounded comparison, final-dispatch recheck | already correct (IR-01), retained | the 23 functions of revision 2, all green |
| Invalid mode, missing, malformed / non-finite, stale / derived / delayed evidence, policy exception, repricing; enforce defers, observe never controls, off records nothing | **EXTENDED**: derived / transformed / delayed flags are now refused as a bound | `test_malformed_nonfinite_derived_and_delayed_inputs_are_unknown_and_a_print_is_never_called_an_executable_quote` + the revision-2 mode and rig tests |
| No print fallback called an executable quote | **FIXED (labelled and validated apart)** | `underlier-print-fallback-v1`: `boundClass = venue_print_fallback`, its own fresh venue print time; the candidate stage does not accept it for the chase bound | same test |
| Gate target vs first production sale; larger-position policy unchanged | already correct | `test_gate_target_and_first_production_sale_are_reported_apart_for_one_two_three_contracts_and_shares` |
| Refusals durable even if research recording drops; exits outside the gate | **PROVED on the rig** | `test_a_refusal_keeps_its_durable_attribution_when_the_research_recorder_drops_everything`, `test_a_final_dispatch_refusal_is_durable_without_the_recorder_and_exits_never_meet_the_gate` |
| Simulator cap opening-only and OFF; closing intent, short cover, restored / unknown intent keep protections | already correct, untouched | `tests/test_em_sim_option_spread.py` (6): `test_cap_on_never_touches_a_protective_stop_a_flatten_or_a_reducing_exit` (includes `BUY_TO_CLOSE`), `test_unknown_intent_is_never_capped_and_existing_quote_checks_still_apply`, `test_default_off_keeps_the_old_behaviour_...` |

### Section 6 - recorder, reducer and UI together

| Requirement | Status | Proof |
|---|---|---|
| Strict provenance, single depth allocation incl. pending reservations; a partial or skewed basket makes no peak | already correct (IR-02) | the two reviewer reproductions and `test_pending_quantities_are_conserved_...` |
| Marked vs realized vs executable with a clear basis; missing cash / fees / marks never zero; no "complete" when a comparison is unavailable | **FIXED** | reconciliation status `partial_comparisons_unavailable` with the list; an unknown instrument makes the execution total unknown, not zero: `test_the_reducer_refuses_mixed_scope_sums_drops_across_instances_and_never_calls_a_partial_comparison_ok` |
| One book / session / policy scope; capture-id dedupe; mixed input rejected; restarts, gaps and drops across instances | **FIXED** | `error_mixed_scope`; `policyVariants`; drops are the SUM of each instance's maximum: same test |
| Attribution and paired P-02 / P-06 rows bound to verified identity, time and lifecycle; sacrificed winners; proxy vs dollars | **FIXED** | `identityVerified` needs a ledger-known instance inside its lifecycle; `comparisonClass`: `test_paired_exit_consumer_join_is_strict_on_trade_identity_and_time` |
| Enabled capture -> queue -> database -> reducer -> API / UI with restart, full queue, ambiguous write, flat terminal event | **PROVED end to end** | `tests/test_em_integrated_api.py::test_enabled_capture_runs_queue_database_reducer_and_api_with_restart_full_queue_ambiguous_write_and_a_flat_end` (real engine, real armer, real observer, Postgres, the real route) |
| Bounded and nonblocking on order / protection paths; OFF = no write, query, chain fetch or paid call | already correct | `test_snap_is_synchronous_...`, `test_the_runner_calls_are_sync_never_awaited_...`, `test_off_by_default_records_nothing_and_collects_nothing`, rig `test_default_off_reaches_the_venue_and_records_nothing`, the chain test's OFF assertion, the candidate pass OFF test |
| UI shows unknown coverage and model-cost estimates, separate peaks, no implied sale | **FIXED** | `EmReviewPanel.tsx`: pricing shows `partial` with the unknown gates and is green only when complete; realized shows "unknown" when instrument identity is unknown; the marked peak says "a mark, not a price anyone paid", the executable peak "hypothetical liquidation estimate - no sale occurred"; coverage shows recorder starts, drops and captures revised by late fills; reconciliation is green only on `ok`; the four model-cost kinds print "unknown" for a missing number (`num()`), never 0.00. Typecheck + production build green; the wire values are asserted None in the API routes test |

### Section 7 - integration, tests and release evidence

Sections 3 and 4 below. Reviewer files are byte-for-byte unchanged; none was weakened, skipped or deselected.

## 2. Limits and deviations (stated once)

1. The exit-to-entry link is journaled from this build on. Older events are linked by the run + trigger journal sequence, which is exact because the runner holds one trade per trigger at a time; an event with neither is `unlinked` and the capture is unscorable. No historical session has captures, so nothing historical depends on it.
2. The ingestion time of a fill is the `OrderFill` journal row's time. A fill whose journal row is missing has `observedAtMs` None: it is not called late, and it still counts in the ledger.
3. `candidate-chase-v1` is a RESEARCH bound. Production EM has no general underlying chase cap to be equivalent to; the record says so in every evaluation.
4. The portfolio gate is the risk-gate verdict, not a full order preflight (client / phone-entry stamps and the broker preview are not part of it) - the platform owner's wording, carried in the record.
5. Reservation premium of working entries uses the trade's quantity x limit x multiplier from runner memory at the snapshot; unreadable = unknown.
6. A missing minute OUTSIDE a requalification's structure window does not hold a continuation candidate (production tolerates such gaps); the count is recorded on every candidate.
7. Manual arm under the proposed policy refuses an ineligible plan unless the human passes an explicit recorded override. Under baseline (the default) the manual door is unchanged.
8. `npm run mobile-audit` was not run: the panel lives on the Validation tab, which phones replace with the desktop-only notice.
9. Not re-run: the full 358-file repository suite and other desks' suites (the goal asked for no broad repeat campaign). Team2 reported 367 of theirs green on the unchanged runner control flow.

## 3. Tests (sequential, one process at a time, private DB `zargar_test_em`; each output starts with its SHA)

The two large batches ran on `f4fbc17f`, whose application code is identical to the final SHA (the only later non-doc changes are the two test files named in section 0). Every file those two changes touch, the arming suite and the reviewer-database files were then run on the final SHA `2d7f51bb`.

| Run | Result |
|---|---|
| Every `tests/test_em_*.py`, `test_codex_em_*.py`, `test_codex_worker_*.py` (except the two that refuse any database but the reviewers') | on `f4fbc17f`: **330 passed, 5 skipped, 0 failed** (4 min 07 s). The 5 skips are the pre-existing `HISTORICAL` marks in `test_em_review_da_reconcile.py` |
| `test_technique_{api,ingest,ingest_flow,lifecycle,options,setups,walkforward,review,universe,detection,arm_expired}`, `test_platform_{separation,phase0,phase3}`, `test_options_{service,occ,greeks_freshness}`, `test_armed_summary` | on `f4fbc17f`: **215 passed, 2 failed** (6 min 15 s) - the contract test and the options round trip. On the final SHA `2d7f51bb`, `test_options_service.py` + `test_platform_phase3.py`: **24 passed, 1 failed** (the contract test only; the options round trip now passes) |
| `tests/test_technique_arming.py`, alone | on the final SHA `2d7f51bb`: **31 passed, 0 failed** (3 min 28 s) - the long-standing lifecycle failure is resolved (below) |
| Reviewer-database files on `zargar_test_codex` (zero connections verified first): both dispatch files, source backfill, source ordering, reconcile real session, reconcile atomicity | on the final SHA `2d7f51bb`: **26 passed, 0 failed** (38 s), including all four dispatch cases under the controlled session clock |
| Frontend `npm run build` (typecheck + build + `check-release` 0.8.23); `import zargar.api.app` | green; ok |

New or changed test functions of this goal: profit capture +7 (38), source candidates +7 (21), preparation +4 (22), first sale +3 (36 with parametrisation), integrated API +3 (8).

**The three failures of revision 2 - exact comparison, owner and status. ONE remains.**

| Test | Candidate vs base | Owner / status |
|---|---|---|
| `test_platform_phase3::test_every_journaled_kind_has_a_contract` | **STILL FAILS**, identically on origin/main (reproduced by the Team2 desk; reported red on main by the Tips desk): `TechniquePlanDiagnostic` has no contract. My event `TechniqueFirstSale` and the additive key on `TechniquePlanOrderResult` validate | Team2 desk. Fixed in their PR #224, open and NOT merged, so by the goal's rule not folded in. It turns green when that PR merges |
| `test_options_service::test_option_order_practice_roundtrip` | failed identically on base `f4ce6ad8` (with and without a pinned clock) and on this candidate. My reading by source inspection: a stale expectation - since `12491f2b` (2026-09-14) the simulator refuses to price a fill from a delayed / `chain` quote and needs an `opra` / `ibkr` identity. The owner then CONFIRMED it with a targeted diagnostic ("Delayed quotes cannot price simulated fills") and fixed the test on main (`f621d49f`, PR #229, test only). Folded in through the normal main merge | platform options owner (Tips desk). **RESOLVED by its owner**; passes on the final SHA. Not a product defect |
| `test_technique_arming::test_auto_options_one_contract_lifecycle` | failed since 2026-09-16 on every tree. Same cause, in an EM-owned test: its helper `_opt_quote` published an anonymous option quote, which the simulator has refused for fills since `12491f2b`. The helper now publishes a venue-identified quote (`source = opra`, `source_ts`), as production does. Test-only change; no application code | EM desk. **RESOLVED** in this candidate; the whole arming suite is green |

## 4. Shared-owner reviews of the FINAL diff (reviews only; neither is a deploy go)

**Tips / platform desk**, reviewed `9ea7572e..07f54131`, then re-checked `40c0bf00`: no objection to (1) the `entryOrderId` payload key, (2) the model-cost route, (4a) the bounded read of executions / orders / events on the recorder task, (4b) the direct `RiskGate.evaluate` call - they confirmed it mutates nothing that matters and asked for the label "risk-gate verdict" (applied). FINDING (5): my first lock was session-level on a pooled connection and unbounded; fixed with a transaction-scoped lock and `lock_timeout`, with the cancellation test they asked for. Quoted: "Owner re-check of item (5) at 40c0bf00...: VERIFIED ... With (1), (2), (4a) and (4b) already agreed, the owner review of the final shared diff is closed." Their non-blocking SQLSTATE nit is applied in `d723cad9`. Unresolved objections: none.

**Team2 desk**, reviewed `7002426d..07f54131` for `planrunner.py`, quoted: "NO OBJECTION to the extra entryOrderId key ... exactly that one payload key; no control flow, hook or await changed." Unresolved objections: none.

The shared diff of this goal: one payload key in `execution/planrunner.py`; one read-only route; `TechniqueService.arm_plan` gained a private keyword and the policy door (active only under the non-default policy). No new table, no new setting, no change to `models.py`, `orders.py`, `risk.py` or `tests/conftest.py`.

## 5. Reports (regenerated on the final code; retrospective, read-only, zero model calls)

| Report | Path | What it says, unknowns kept |
|---|---|---|
| First-sale R | `research/first-sale/2026-09-15_2026-09-18.md` | 28 entries. v2 admission is UNKNOWN for all 28: the validated executable underlier was never captured. No pass / fail count is claimed. By saved geometry one entry (SBUX) was below 3R at its real exit rung |
| Executable profit | `research/profit-capture/2026-09-15..18.md` | realized -220.30 / -147.55 / +222.65 / -299.33 (execution ledger, instrument identity from the orders). Executable and displayed peaks: UNKNOWN - the recorder did not exist |
| Preparation comparison | `research/prep-compare/2026-09-15_2026-09-18.md` | proxy R under one shared book; not dollars; deterministic path zero model calls; does not show the rules-only policy is better. Model cost ESTIMATE about 56 to 65 US dollars per evening at the current card (no effective date; not an invoice; never subtracted from trading results). Sensitivity class for the disputed 09-17 ORCL fills shown beside the booked number |
| Source to plan and candidates | `research/source-scenarios/2026-09-18.md` | forward pricing for the four sessions is UNKNOWN for every gate (no contemporaneous evidence was captured); the author's own result is unknown |

Causal manifests: each report's JSON carries its versions, generation time, inputs and coverage. Frozen definitions: `research/PROSPECTIVE-DEFINITIONS-2026-09-19-R2.md` (supersedes the two earlier files before any data was collected).

## 6. Migrations, restore and idempotence, defaults, per-feature status

Schema: additive only, unchanged from revision 2 - three tables (`technique_book_snapshots`, `technique_prep_decisions`, `technique_source_candidates`) and the existing artifacts table's kind `scenarios`. This goal added NO table and NO column. Dry run: all four report tools ran against the runtime database with `default_transaction_read_only = on`; the snapshot table is absent there and the report degrades to UNKNOWN.

Restart / restore / idempotence evidence: capture id primary key + ambiguous-write case (Postgres and API chain tests); new observer identity and `recorder_restart` gap; candidate persist race and two ticks / restart (API); prep decision race, arm race, restart after commit, cancelled arm (Postgres); forward pass restart idempotent (API).

| Setting | Default = effective after a deploy | Feature status |
|---|---|---|
| `techniques.enhanced_market.first_sale_rr_gate` | `off` | built, tested, OFF. `observe` records through the bounded recorder; `enforce` refuses / defers and rechecks at dispatch; any other value refuses entries |
| `techniques.enhanced_market.book_snapshot_observe` / `book_snapshot_seconds` | `False` / `30.0` | built, tested end to end, OFF |
| `techniques.enhanced_market.source_scenarios_observe` | `False` | built, OFF |
| `techniques.enhanced_market.source_candidates_observe` | `False` | built, OFF |
| `techniques.enhanced_market.source_candidates_chain_fetch` | `False` | built, OFF |
| `techniques.enhanced_market.preparation_policy` | `baseline` | `deterministic` built, OFF |
| `techniques.enhanced_market.prep_grade_floor` / `conditional_review_fix` / `prep_audit_quota_pct` | `B` / `report` / `0.0` | built |
| `techniques.enhanced_market.pick_retry_after_429_s` | `0.0` | built, OFF |
| `llm.rates` | platform setting, unchanged | read only |
| Established, untouched | `shadow_exit_observe`, `shadow_p02_candidate` = True; `fire_decision_mode` = deterministic; `ingest.auto_arm` as set | P-02 / P-06 collection and baseline trading continue unchanged |

Default-active bookkeeping with everything OFF (the accurate list): one call of the runner's `first_sale_policy()` per entry (a constant for other desks, one cached settings read for EM) and one `first_sale_final` call returning None in the entry guard; `_book_snap` = an attribute check plus, for EM, one cached settings read, never awaited; the candidates loop wakes once a minute, reads one setting and sleeps; the model request ledger rides the run result already written; `size_multiplier` reads the pinnable clock; ingestion passes source ids into the owner (the supersession query only with its knob on); `option_pick(near_money=...)` only with the first-sale mode on; the exit order-result event carries one more key; one read-only router and the Validation panel query on demand. `TechniqueService.arm_plan` reads the effective preparation policy once per arm (a few cached settings reads) and does nothing else under baseline. No research write, query, chain fetch or paid call happens with the knobs OFF (tests above).

## 7. Rollout and rollback packet (nothing here was executed)

1. Re-read `origin/main` and the runtime head. The candidate must CONTAIN the runtime commit (fast-forward only; never reset or downgrade). On a version collision renumber THIS block to the next free number, rebuild, rerun `check-release`. If Team2's PR #224 has merged, merge main first (different hunk of `events_contract.py`).
2. `python -c "import zargar.api.app"`, `npm run build`, `npm run check-release` on the final SHA.
3. `GET /api/ops/restart-check` must be safe: no open positions, no working entries, no pending exits, no in-flight orders, no preparation batch, no other desk mid-work. Not during regular hours. Never restart to hurry this delivery.
4. Save the before-inventory (armed ids by technique, resting orders, helper windows).
5. Deploy only through `scripts/deploy.ps1 -TargetCommit <full sha> -Expect 0.8.23` from `C:/Cursor/zargar` under the deployment lease. Never Stop-Process, never `start.ps1` from an assistant shell. The deploy is the user's decision; two peer reviews are not a go.
6. Verify: `/api/health` version and launch-bound build; armed ids equal by id per technique; resting orders equal; exactly one Discord gateway and one EM ingestion helper; the three tables exist and are EMPTY; `GET /api/technique/em/manifest` shows every default above; the first EM entry of the next session has NO `TechniqueFirstSale` event; P-02 shadow-exit events continue; the first EM exit's `TechniquePlanOrderResult` carries `entryOrderId`.
7. After the deploy only: record the SKHY miss in the counterfactual ledger. The FIX-01 v4 money repair stays a separate human step.
8. **Rollback without losing evidence** (journaled `PATCH /api/settings`, no restart). It touches ONLY the switches this delivery added, each back to its shipped default, and only those that were changed: `techniques.enhanced_market.book_snapshot_observe=False`, `first_sale_rr_gate=off`, `source_scenarios_observe=False`, `source_candidates_observe=False`, `source_candidates_chain_fetch=False`, `preparation_policy=baseline`, `conditional_review_fix=report`, `prep_audit_quota_pct=0`, `pick_retry_after_429_s=0` (`book_snapshot_seconds` and `prep_grade_floor` are inert while their feature is off). **Never part of a rollback, left exactly as they are:** the established P-02 / P-06 collection `shadow_exit_observe=True` and `shadow_p02_candidate=True`, `fire_decision_mode=deterministic`, `fire_evidence_mode`, `ingest.auto_arm`, every risk limit and every other desk's setting. Rows already written stay. No path here owns an exit, so positions are managed exactly as before. Code rollback = deploy the previous build through the same protocol; the additive tables can stay.

## 8. ONE deployment recommendation, distinct from activation

**Deployment:** deploy `2d7f51bb` (0.8.23) with every new switch OFF, in a safe market-closed window, by the protocol above. It is behaviour-neutral by the list in section 6 and is the precondition for any evidence. Owner of the deploy decision: the user.

**Activation (separate, later, one at a time; none requested now):**

| Order | Switch | What it changes | Monitoring and rollback owner |
|---|---|---|---|
| 1 | `book_snapshot_observe = true` | measurement only: about one row per 30 s while a position is open plus event rows; one bounded read per capture on the recorder task; no order path awaits it | EM desk: read the first session's coverage, unscorable reasons, drops and revisions before trusting any peak. Rollback: the knob |
| 2 | `first_sale_rr_gate = observe` | records the validated executable underlier at admission - the evidence history lacks; never authoritative | EM desk: unknown rate and dispositions after at least 10 sessions. Rollback: `off` |
| 3 | `source_scenarios_observe`, then `source_candidates_observe` | order-free: one pass a minute in the session; keep `source_candidates_chain_fetch` off until the cached-evidence hit rate is known | EM desk. Rollback: the knobs |
| later | `first_sale_rr_gate = enforce` | would defer every entry whose evidence is missing and refuse those below 3R at the executable bound | **not recommended now.** The 28 historical entries are all unknown, so they establish neither the benefit nor the harm; one avoided loser is not a reason. Decide on the observe sample, winners included |
| later | `preparation_policy = deterministic` | rules select, zero model calls, every arm through one owner | **not recommended now.** The proxy comparison does not show it is better; decide after the declared horizon on after-cost dollars |
