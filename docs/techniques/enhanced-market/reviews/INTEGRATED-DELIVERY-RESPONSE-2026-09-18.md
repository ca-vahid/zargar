# EM integrated delivery - consolidated closure (2026-09-18)

Answers `EM-INTEGRATED-DEVELOPMENT-PLAN-2026-09-18.md` as ONE delivery: workstreams A-E are implemented, wired, tested and
reported on one merged candidate. Owner: EM desk. Nothing was deployed, no strategy was activated, no setting of the running
app was changed, no paid model call was made, and the runtime database was only read.

| Item | Value |
|---|---|
| Tested candidate | **`0f0949b42854817ffa58d175f2ffaaa18ff26911`** on `claude/technique-review-trade-plan-fbb9ba`, version **0.8.21** (quartet + lockfile agree; `npm run build` and `check-release` green) |
| Contains | runtime head `f4ce6ad8` (= origin/main `c40f1fd0`, v0.8.20) merged cleanly; frozen baseline at the start of work: `7f8e9e1` (v0.8.19) |
| Live at the time of writing | v0.8.19 build `491d6ff` when this work began; the runtime checkout has since moved to `f4ce6ad8` (another desk). This delivery is NOT deployed |
| Docs-only receipt | any commit after the tested SHA touches `docs/` only (exact diff: `git diff 0f0949b42854817ffa58d175f2ffaaa18ff26911..HEAD --stat`) |
| Paid model calls | 0. Runtime DB: read-only transactions only. Test DBs: `zargar_test_em` (private); reviewer files on `zargar_test_codex` (see Tests) |

## 1. What now exists (plain statement)

1. **What an author actually said is preserved** (`source-scenarios-v1`): author, revision, evidence spans with transcript offsets, direction, condition, level, underlying targets apart from option strikes, horizon, avoid / no-chase, and a usable time that is the completion of the last needed input - never the message timestamp. A ticker the evidence does not support is `unresolved`; an extracted ticker whose passage names another ticker is `conflict`. Both are held. Corrections are a new append-only artifact usable only from their own time.
2. **One preparation eligibility owner** (`em-prep-policy-v1`): `baseline` (default, unchanged) and `deterministic` (rules + grade floor, zero model calls). Batch, ingestion and the pre-open re-plan route through it under the proposed policy; one candidate key arms once. An absent review is recorded as absent.
3. **Every source idea is explained**: the source-to-plan table lists every trigger of every matched plan, the policy record and the gate events. Ticker-only and opposite-direction coincidences are never "aligned".
4. **Fresh setups after an early invalidation** (`requalification-v1`) and **source-conditioned continuation** (`source-continuation-v1`) are order-free candidates with their own trackers; the baseline tracker is never reset.
5. **First-sale R at the final quantity** (`first-sale-v1`) is recorded on every EM entry and can refuse an entry only under `enforce`.
6. **Realized, displayed and covered-executable profit are separate numbers** (`book-snapshot-v1`): recorder, reducer, report and UI are built; the recorder is OFF.
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
through it). Retrospective, four sessions, 28 entries: `enforce` would have refused **one** (SBUX, -84.10). Report:
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
| Causal-input cache / resume | `causal_input_key`, `plan_batch`, table `technique_prep_decisions` | `test_hashes_are_deterministic...`, `test_resume_reuses...`, Postgres ledger case (a preview writes nothing) |
| Lazy charts in deterministic paths, on-demand kept | `service.analyze` `render_charts` | `test_lazy_charts_in_every_deterministic_preparation_path...` |
| Model cost tracking, dated table, four kinds apart | `technique/model_costs.py`, `vision.py` request ledger, `llm.pricing_table` | `test_costs_are_never_invented...`, `test_the_pipeline_keeps_a_request_ledger` |
| Comparison command | `tools/em_prep_compare.py` | `test_em_prep_compare.py` (4); report `research/prep-compare/2026-09-15_2026-09-18.md` |
| Frozen prospective definitions + horizon | `research/PROSPECTIVE-DEFINITIONS-2026-09-18.md` | - |

### C - source continuation and requalification

| Requirement | Where | Evidence |
|---|---|---|
| Two separately identified order-free variants consuming A and B | `technique/source_candidate_policy.py`, `technique/requalification.py` | `test_em_source_candidates.py` (11) |
| Fresh structure by the existing causal pivot detector; rebound alone insufficient; pivots unusable before confirmation | `fresh_structure` (`find_pivots`, window 3) | `test_no_reset_fresh_confirmed_structure...` |
| Same windows and source expiry; NVDA 15:55 not captured | `source_expiry_ts`, production `TriggerTracker` | `test_the_source_horizon_is_not_extended...`, afternoon-break case expires |
| One child per branch per session; unique parent / child ids | `child_id`, `existing_children` | `test_r2_target_provenance_the_stop_cap_and_the_one_child_limit` |
| Causal entry timing; no same-close fill; gates at eligibility and at pricing | own tracker, `upto_ts`, `pricing_gates` (unknown without a contemporaneous quote) | `test_the_evaluator_is_causal...`; late-born candidate never sees earlier bars |
| MU volume and AMD 2.97R stay named; cost / benefit diagnostics | `namedBaselineOutcome`, `exclusion_diagnostic` | AMD / SPCX refusals; report section 3 |
| Producer, persistence / resume, replay + forward evaluator, table, UI dispositions | `evaluate_session`, `source_candidates_runtime.py` (loop OFF), table `technique_source_candidates`, panel Candidates | `test_the_forward_candidate_pass_is_off_by_default_order_free_and_restart_idempotent` |
| Never arms through any path | origin `scenario:*` (existing runner boundary) | `test_every_candidate_is_order_free...`; no `technique_armed` row after a pass |

### D - first-sale economics and quote integrity

| Requirement | Where | Evidence |
|---|---|---|
| SBUX explained and regressed | section 2 | `test_em_first_sale.py` (18) |
| One versioned record for diagnostics and research | `first-sale-v1`, event `TechniqueFirstSale`, route `/api/technique/em/first-sale`, panel First sale | producer test freezes live inputs without inventing the underlier |
| Vehicle comparison, order-free; BMNR / DRAM fixtures | `compare_vehicles`; near-money rows of the chain already fetched (`near_money_rows`, no extra request) | DRAM-shaped fixture test; historical limit stated in the report |
| Sim cap stays opening-only and OFF; quote provenance kept | unchanged (`test_em_sim_option_spread.py` still green) | - |
| ORCL producer audit, no cash rewrite | read-only | both fills `source: opra`, no transform; the 0.76/1.12 entry book is the doubt |
| DRAM / SKHY bounded timelines; held-position fix only where a defect is established | TRADING-RULES 2026-09-18 evening | DRAM: no EM defect, unchanged. SKHY: one bounded re-pick, OFF, no-chase guarded |

### E - ED-04 executable-profit capture (implemented, not designed)

| Requirement | Where | Evidence |
|---|---|---|
| EM-only record + bounded async recorder, default OFF, new namespaced knob | `technique/profit_capture.py`, `profit_capture_runtime.py`, knob `book_snapshot_observe` | `test_em_profit_capture.py` (23) |
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
| Requalification | met | `test_em_source_candidates.py` |
| Economics | met | `test_em_first_sale.py` |
| Portfolio capture | met | `test_em_profit_capture.py` |
| Paired exits | met | existing `test_em_runner_protection.py` (13, unchanged) + the new consumer case |
| Comparison | met | `test_em_prep_compare.py` + the reconciled report |

## 5. Tests on the candidate

Environment: Windows 11 host, Python 3.13, venv `C:/Cursor/zargar/backend/.venv`, Postgres on 127.0.0.1:5433, run from the worktree
`backend/`, sequentially, one pytest process at a time, 2026-09-18 evening PT (market closed), about 4 GB free RAM. All runs below
are on the exact candidate `0f0949b` unless marked.

| Run | Command (abridged) | Result |
|---|---|---|
| New suites | `pytest tests/test_em_first_sale.py test_em_profit_capture.py test_em_source_scenarios.py test_em_preparation_policy.py test_em_prep_compare.py test_em_source_candidates.py test_em_integrated_api.py` | 18 + 23 + 15 + 17 + 4 + 11 + 4 = **92 passed** |
| Affected batch (private DB `zargar_test_em`) | every `test_em_*`, `test_codex_em_*`, `test_codex_worker_*` (minus the four reviewer-database files), `test_technique_{api,ingest,ingest_flow,lifecycle,options,setups,walkforward,review,universe,detection,arm_expired}`, `test_platform_{separation,phase0,phase3}`, `test_options_{service,occ,greeks_freshness}`, `test_armed_summary` | **483 passed, 5 skipped, 3 failed** in 11 min 51 s |
| Arming, solo | `pytest tests/test_technique_arming.py` | **30 passed, 1 failed** (`test_auto_options_one_contract_lifecycle`, the known baseline failure) in 8 min 46 s |
| Reviewer-database files (`zargar_test_codex`, zero other connections verified first) | `test_codex_em_final_dispatch_budget.py`, `test_codex_em_source_backfill.py`, `test_codex_em_source_ordering.py`, `test_em_reconcile_real_session.py` | **15 passed, 3 failed** |
| Frontend | `npm run build` (typecheck + production build + `check-release`) on `68c2c43`; no frontend file changed afterwards | green, "Release 0.8.21 ... agree" |
| Import smoke | `python -c "import zargar.api.app"` | ok, 0.8.21 |

**The failures are baseline failures, shown by evidence, not assumed.** Each was rerun on the UNMODIFIED base commit `f4ce6ad8` (the
runtime head this candidate merges) in a scratch worktree and fails identically there:

| Test | On the candidate | On base `f4ce6ad8` | Reading |
|---|---|---|---|
| `test_codex_em_final_dispatch_quote::test_em_dispatch_rechecks_current_nbbo...` | fails (`risk_passed == []`) | fails identically | the option entry never reaches the RiskGate in this rig after the close; not touched by this delivery |
| `test_codex_em_final_dispatch_budget::test_em_day_budget_is_valid_at_actual_dispatch[unchanged / reprice / submitted]` | 3 fail, same symptom | 3 fail identically | same cause |
| `test_options_service::test_option_order_practice_roundtrip` | timeout | timeout identically | same family (Practice option fill outside an eligible session) |
| `test_platform_phase3::test_every_journaled_kind_has_a_contract` | fails on `TechniquePlanDiagnostic` | fails identically | a Team2 event without a contract. This delivery's own new event `TechniqueFirstSale` HAS a contract and validates |
| `test_technique_arming::test_auto_options_one_contract_lifecycle` | fails | known baseline failure since 2026-09-16 | unchanged |

They are reported, not waved away: the option-dispatch family deserves its owners' look (it may be session-clock dependent - it was run
on a Friday evening). No timeout was called harmless without the base rerun.

Prior-tree results, kept separate: the same affected batch on the intermediate candidate `68c2c43` gave the same 483 passed / 5 skipped /
3 failed. Between `68c2c43` and `0f0949b` four backend files changed (event contract, candidate evaluator context, diagnostics).

Not run: the full 352-file repository suite (other desks' suites were not touched by this delivery and the host cannot run them in
parallel); `scripts/test-codex.ps1` itself (the same files were run sequentially with the same database after verifying it was idle);
`npm run mobile-audit` (see section 10).

## 6. Reports (September 15-18; all retrospective, read-only, zero model calls)

| Report | Path | Reproduce |
|---|---|---|
| Source-to-plan, candidates, exclusions, corrections layer | `research/source-scenarios/2026-09-18.md` (+ `.json`), corrections `research/source-corrections-2026-09-18.json` | `python -m zargar.tools.em_source_scenarios report --date 2026-09-18 --corrections <file>` |
| Preparation comparison | `research/prep-compare/2026-09-15_2026-09-18.md` | `python -m zargar.tools.em_prep_compare --dates 2026-09-15,2026-09-16,2026-09-17,2026-09-18` |
| Executable profit | `research/profit-capture/2026-09-15..18.md` | `python -m zargar.tools.em_profit_capture report --date <d>` |
| First-sale R | `research/first-sale/2026-09-15_2026-09-18.md` | `python -m zargar.tools.em_first_sale report --dates ...` |
| Per-session profitability (existing tool, 09-15 and 09-18 added) | `research/profitability/` | `python -m zargar.tools.em_profitability report --date <d>` |

What they say, without spin:
- **Actual baseline**: -220.30 / -147.55 / +222.65 / -299.33 = **-444.52** after commissions, excluding model cost. ORCL 09-17 stays flagged as disputed; the ledger is not rewritten.
- **Proxy comparison under one shared book**: model-selected +7.68 / -0.93 / +0.85 / -3.52 R; deterministic +7.90 / -1.76 / -0.40 / -2.78 R; frozen exception -1.93 / -0.93 / -3.75 / -2.18 R. Independent sums overstate all three; the daily-loss halt binds the wider deterministic set hardest. These are underlying replays: no option evidence exists for plans that were not traded, so none of it is dollars.
- **Model cost**: about 4M input and 1.5M output tokens per evening (102-112 reads). Dollar cost is UNKNOWN because no dated price row is configured; none was invented.
- **Executable profit for the four sessions is UNKNOWN**: the recorder did not exist. The reports say so and reconstruct nothing from marks.
- **Conditional-review mismatch**: real, but never the sole veto on 09-18 - nothing is rescued.
- **Source fidelity on 09-18**: none of the five EM positions was a highlighted author idea; of the author's ideas, the aligned AMD and SPCX-long triggers were rejected by R2 (2.97R, 2.56R) and the armed SPCX trigger was the opposite short.

## 7. Migrations, schema and defaults

Additive only (`db.create_all` creates missing tables; no column is dropped or renamed; no historical row is rewritten; no money write).

| Table | Written by | When |
|---|---|---|
| `technique_book_snapshots` | ED-04 recorder | only with `book_snapshot_observe` on |
| `technique_prep_decisions` | `prep_decide(persist=True)` | only under the deterministic policy (ingestion / re-plan) or an explicit batch call; previews never write |
| `technique_source_candidates` | forward candidate pass | only with `source_candidates_observe` on |
| `technique_source_artifacts` kind `scenarios` (existing table) | board check | only with `source_scenarios_observe` on |

Dry run: the four report commands above ran against the runtime database inside `set transaction read only`; the profit-capture report confirms the new table is absent there (`Recorder table present: False`) and degrades to UNKNOWN.

### Collection manifest (every knob; default = effective after a deploy unless someone changes it)

| Knob | Default | Status | Effect when changed |
|---|---|---|---|
| `techniques.enhanced_market.preparation_policy` | `baseline` | built, merged, not deployed | `deterministic`: rules select, zero model calls, ingestion and re-plan routed through the owner |
| `techniques.enhanced_market.prep_grade_floor` | `B` | built | grade floor of deterministic eligibility |
| `techniques.enhanced_market.conditional_review_fix` | `report` | built | `apply`: a trigger whose only model objections are "not yet triggered" is eligible if the rules pass |
| `techniques.enhanced_market.prep_audit_quota_pct` | `0.0` | built | share of candidates sampled for an evidence-only audit (paid) |
| `techniques.enhanced_market.source_scenarios_observe` | `False` | built | board check builds and stores the scenarios artifact |
| `techniques.enhanced_market.source_candidates_observe` | `False` | built | one-minute order-free candidate pass during the session |
| `techniques.enhanced_market.first_sale_rr_gate` | **`observe`** | built | journals `TechniqueFirstSale` per entry; `enforce` refuses; `off` silences. **The one new collector that is ON by default** |
| `techniques.enhanced_market.pick_retry_after_429_s` | `0.0` | built | one bounded option re-pick after a provider 429 |
| `techniques.enhanced_market.book_snapshot_observe` | `False` | built | ED-04 recorder |
| `techniques.enhanced_market.book_snapshot_seconds` | `30.0` | built | recorder cadence |
| `llm.pricing_table` | `[]` | built | dated price rows; empty = cost unknown |
| Already on by user decision, unchanged | `shadow_exit_observe`, `shadow_p02_candidate` = True; `fire_decision_mode` = deterministic | live | P-02 / P-06 collection continues as before |

New collector behind an already-on knob: none. The near-money vehicle rows ride the first-sale record (same knob).
Evaluated status: nothing is evaluated yet; the validation sample starts per `PROSPECTIVE-DEFINITIONS-2026-09-18.md`.

## 8. Rollout, readiness and rollback checklist (next coordinated market-closed window)

1. Re-read `origin/main` and the runtime head; the candidate must CONTAIN the runtime commit (fast-forward only, never reset). On a version collision renumber THIS block to the next free number and rebuild.
2. `python -c "import zargar.api.app"`, `npm run build`, `npm run check-release` on the final SHA.
3. `GET /api/ops/restart-check` must be safe: no open positions, no working entries, no pending exits, no in-flight orders, no preparation batch, no other desk mid-work. Never restart to hurry this delivery.
4. Save the before-inventory (`/api/ops/state` armed ids by technique, resting orders, helper windows).
5. Deploy only through `scripts/deploy.ps1 -TargetCommit <full sha> -Expect 0.8.21` under the deployment lease, then the `ZargarRestart` task. Never Stop-Process, never `start.ps1` from an assistant shell.
6. Verify: `/api/health` version and launch-bound build; armed ids equal by id per technique; resting orders equal; Discord gateway and EM ingestion helpers up; the three new tables exist and are EMPTY; `GET /api/technique/em/manifest` shows every default above; one `TechniqueFirstSale` event appears with the first EM entry and no entry is refused by it; protective paths untouched (quote watch logs as before).
7. After the deploy only: record the SKHY miss in the counterfactual ledger (`technique_review counterfactual <run> --trigger r2 --reason "CBOE 429 outlasted the pick back-off"`); never a synthetic fill in a book.
8. **Rollback without losing evidence** (journaled `PATCH /api/settings`, no restart): `first_sale_rr_gate=off`; every `*_observe` knob `False`; `preparation_policy=baseline`; `conditional_review_fix=report`; `pick_retry_after_429_s=0`. Rows already written stay; positions are managed exactly as before because none of these paths owns an exit. Code rollback = deploy the previous build through the same protocol.

## 9. Activation recommendation (four separate decisions; none taken here)

| Decision | Recommendation | Trade-off |
|---|---|---|
| `first_sale_rr_gate = enforce` | **Yes, first.** It enforces a rule already documented; in four sessions it would have refused one entry of 28 (SBUX, a loss) | It will refuse break-family entries whose confirming close has eaten the reward; some of those would have won. Observe for a week first if a smaller step is preferred |
| ED-04 recorder ON | **Yes, second** - it is evidence, not policy, and nothing can be learned about giveback without it | about one row per 30 s while a position is open plus event rows; drops are visible; no fetch, no model |
| Source scenarios + candidates ON | Yes after the recorder: order-free, bounded (one settings read when off; one pass a minute when on) | engine reads of bars / plans once a minute in the session; watch the first day |
| `preparation_policy = deterministic` | **Not yet.** The proxy comparison does not show it is better; it doubles the candidate count and meets the loss halt more often. Decide after the declared horizon with after-cost dollars, and with a price row so the model's cost is known | saves roughly 4M input + 1.5M output tokens an evening; loses the model's substantive objections (provenance, manufactured targets) that rules do not yet encode |
| `conditional_review_fix = apply` | Low value now (rescued nothing on 09-18); leave on `report` and read the count weekly | - |
| `pick_retry_after_429_s` | Optional, small (suggest 4); only after the Tips / platform owners have seen the diff | one extra provider request per rate-limited entry |

## 10. Material deviations and limits (reported once)

1. `first_sale_rr_gate` ships as `observe`, not `enforce`: the instruction to preserve baseline Practice trading outranks enforcing on merge. The rule, the refusal path and the regression are complete.
2. The conditional-review fix is report-only under baseline and the model prompt is unchanged, for the same reason.
3. Scenario artifacts are not yet stored for past notes: storing is the ingestion path behind its OFF knob; the 09-18 table is built on the fly, read-only. The reviewed MU correction is a file, applied as a separate later-usable layer.
4. Historical vehicle comparison is limited to the picked contract: no intraday alternative rows were ever stored. Forward capture now rides the first-sale record at zero extra requests.
5. DRAM: no change (no EM-side defect established). Shared-simulator treatment of an unchanged standing quote is left to its owners.
6. Shared-layer owners could not be consulted tonight. Every shared diff is inert by default (three base hooks that do nothing, a request ledger, three additive tables, one route registration). They should review `execution/planrunner.py`, `technique/vision.py`, `models.py`, `api/app.py`, `technique/options.py` before the deploy.
7. The author's live replay / ledger remains inaccessible; his result stays unknown. Nothing was bought, messaged or subscribed.
8. `npm run mobile-audit` was not run: the new panel lives on the Validation tab, which phones replace with the desktop-only notice.
9. Open defects outside this plan, unchanged: the `max_open_trades` skip still lacks a reason text; stray host process pid 135928; provenance of six ingest-auto-armed plans (EvaPanda vs author) is now answerable per row from the source table.
