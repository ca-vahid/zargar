# 8. The S1 collector: default-off, order-free package

Delivered for review. **Not enabled, not deployed.** Turning it on needs (a) this code reviewed and deployed through the coordinated
restart, and (b) `techniques.team2.selection_study` set to `collect`. Neither is part of this package. Registration: `s1-r2`
(`07-selection-study-spec.md`).

## What it is

| Piece | Where | What it does |
|---|---|---|
| Pure module | `backend/zargar/techniques/team2/selection_study.py` | opportunity identity, the six causal features, the record opened at the start, observation validity on the quote's own clock, abandonment, after-cost return, cross-book collapse, coverage by bucket. No I/O, no settings, no imports from the execution layer |
| Switch | `techniques.team2.selection_study` = `off` (default) \\| `collect`, in `settings_service.DEFAULTS` | UI-editable and journaled like every knob. It is NOT an experiment override: `EXPERIMENT_ROLES` still whitelists only `sizing -> size_full` and `c1 -> no_trade_zone` |
| Runner wiring | `Team2Runner._study_on / _study_open / _study_tick / _study_observe / _study_pending / _study_of`; one call at the END of `_diag_candidates`, one at the end of `_diag_tick`; `state_extras` / `restore_extras` carry `selectionStudy` | runs only inside the existing shadow-diagnostics path, after every decision of the fire has been taken. Reads the attempt record, the bars already held, and one forced quote refresh per due observation. Journals `TechniquePlanDiagnostic` rows of kind `selection_study_open` and `selection_study_close` |
| Tests | `backend/tests/test_team2_selection_study.py` (12) | below |

It depends on the shadow diagnostics being on (`techniques.team2.diagnostics`, already true), because it reuses their examined-quote
binding. With `selection_study=off` no study code runs beyond one settings read, nothing is stored and nothing is journaled.

## Why it cannot affect trading

- Every hook returns `None`; no decision path reads a value from it.
- It is called after the candidates were examined and the pick was made, inside the diagnostics' own `try`, and wraps itself in another.
- It never writes to a trade, a plan's state machine, an order, a position, a portfolio or a setting
  (`test_the_collector_has_no_path_to_an_order_a_position_or_a_decision` checks the source of the module and of every `_study_*` method).
- Its only side effects are: a dict in the runner's memory, that dict inside the plan's persisted extras, journal rows, and at most
  one forced quote refresh per due observation (two per opportunity, at most 12 opportunities followed at once).

## The four review amendments, and the test that pins each

| Amendment | Implementation | Test |
|---|---|---|
| 1. Book-independent opportunity identity | `opportunity_id(date, symbol, setupId, signalTs)`: the contact bar's close time, never a per-book contact number. `collapse()` keeps one record per identity across books (Control, else Sizing, else C1) and flags `c1Only` | `test_identity_ignores_per_book_contact_numbers` (the 2026-09-18 shape: C1's #1 at 10:14, Control's #1 at 10:22, C1's #3 at 10:22) |
| 2. Positive improvement required; one feature goes forward | specification only (analysis rules, page 7): `d > 0` with the lower interval bound above zero, plus the frozen choice order | no code: the analysis is run once, at the end, from the frozen rules |
| 3. Timing defined | `t_q0` = the entry quote's SOURCE time; delay `t_q0 - T_signal` must be within 0 to 90 s; every clock starts at `t_q0`; an observation counts only when its own source time lies in `[due, due + 90 s]` and it passes `quote_check` | `test_the_entry_quote_delay_is_measured_from_the_signal_and_bounded`, `test_an_observation_counts_only_inside_its_window_on_the_quotes_own_clock`, `test_late_in_the_day_and_capacity_are_recorded_not_dropped` |
| 4. Observations recorded when they begin | `selection_study_open` is journaled at once; `selection_study_close` when the last observation resolves; `collapse()` reports an open record without a close as `incomplete`; `coverage()` keeps valid, late, capacity, incomplete and every unknown reason in the denominator; an observation overdue after a restart is recorded, never quoted or back-filled | `test_off_records_nothing_and_on_never_mutates_its_inputs`, `test_incomplete_and_abandoned_observations_stay_in_the_coverage_denominator`, `test_an_overdue_observation_after_a_restart_is_unknown_never_backfilled` |

Replay side of amendment 3: the research harness now flags entries executed a minute or more after their decision and repeats every
arm comparison without them. One such entry exists in 26 replay files (arm H4); no verdict moves (page 5).

Other acceptance tests: `test_the_collector_ships_off_and_is_not_an_experiment_override`,
`test_features_read_nothing_at_or_after_the_contact_bar` (bars after T, and the contact bar itself, cannot change a feature),
`test_feature_values_and_unknowns`, `test_winsorised_primary_and_cost_arithmetic`.

## Acceptance checklist for this package

1. `pytest backend/tests/test_team2_selection_study.py` : 12 passed (own database `zargar_test_team2`; the tests use no database rows).
2. Default parity: with the switch off, the Team2 and reviewer suites behave as before (result in the PR description).
3. `git diff main --stat -- backend` shows only: `selection_study.py` (new), `runner.py` (the `_study_*` block, two one-line calls, two
   persistence lines, two imports), `settings_service.py` (one default), the new test, and the two research knobs already in this PR.
4. No change to `session.py` in this pass, to any rule, sizing, protection, experiment book or product pricing. No version bump: nothing user-visible ships while the switch is off.
5. Depends on PR #224 for the `TechniquePlanDiagnostic` event contract (open). The collector adds no new event type.

## Known limits of the collector (stated, not hidden)

- F-f needs the fire's target; on the shadow path (a fire refused before the picker) the target is not on the attempt record, so
  `room` is `unknown` there. Reported per bucket; no guess is made.
- F-b can only tell today's pre-market levels from the previous session's. Older levels need C2 key levels, which stay off.
- The `actionable underlying price` is the spot the picker used for the ladder walk, the runner's fresh underlying price.
- A plan that is disarmed or removed leaves its open records unclosed. That is intended: they stay visible as `incomplete`.
- The analysis script (collapse, Holm, clustered bootstrap over journal rows) is NOT in this package. It is written once, before
  the data are looked at, against the frozen rules on page 7, and is reviewed separately.
