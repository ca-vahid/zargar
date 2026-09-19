# 8. The S1 collector and the frozen analysis: default-off, order-free, passive

> Superseded for release purposes by `09-release-handoff.md` (registration `s1-r4`: lifecycle, endpoint, frozen final sample,
> end-to-end tests). The collector design below is ACCEPTED and unchanged; r4 adds the registration hash to every row, a
> health counter, no coroutine without a running loop, and recovery of an opening from its close.

**The collector stays OFF.** Not enabled, not deployed, no setting changed. Turning it on needs (a) this code accepted and deployed
through the coordinated restart, (b) PR #224 (the `TechniquePlanDiagnostic` event contract) merged, and (c)
`techniques.team2.selection_study` set to `collect`. None of those is part of this package. Registration: `s1-r3`
(`07-selection-study-spec.md`). This document replaces the first collector package, which the review team held for four groups of
defects; all four are corrected here in one pass.

## What it is

| Piece | Where | What it does |
|---|---|---|
| Pure module | `backend/zargar/techniques/team2/selection_study.py` | identity, strict quote evidence, the six features, the point-in-time snapshot, the opening record with its `openHash`, passive observation, abandonment, after-cost return, cross-book collapse, coverage |
| Frozen analysis | `backend/zargar/techniques/team2/selection_study_analysis.py`, sha256 `ad4b02111a79494ffdc1b71c5ff04e68e88f6c20c611851269814bb79adcb772` (pinned by a test) | population, date-clustered bootstrap, Holm, the four-part pass rule, the per-side minimums, the single-feature choice |
| Read-only tool | `backend/zargar/tools/team2_selection_study.py` | default view = COVERAGE ONLY (counts and coverage, never an outcome); `--final` runs the frozen analysis and is REFUSED before the stop rule (60 sessions or 2026-12-18) |
| Switch | `techniques.team2.selection_study` = `off` (default) \\| `collect` | UI-editable and journaled; NOT an experiment override (`EXPERIMENT_ROLES` still holds only `sizing` and `c1`) |
| Runner hooks | `Team2Runner._study_*` | all SYNCHRONOUS, all return `None`; see "Where it runs" |
| Tests | `tests/test_team2_selection_study.py` (41), `tests/test_codex_team2_collector_boundaries.py` (3, the review team's probes, adopted verbatim), `tests/test_team2_selection_analysis.py` (13) | below |

## Where it runs (corrected statement)

The first package said the hook "runs after every fire decision". That was wrong. Accurately:

- `_study_snapshot` runs **at the signal**, synchronously: in `_diag_signal` at the fire, and at the top of `_diag_shadow` for a fire
  refused before the picker, in both cases BEFORE any awaited contract work.
- `_study_open` runs at the end of `_diag_candidates`, which is **inside `pick_contract`, before the later entry gates, sizing and
  submission**. It reads the attempt record and the examined candidate row, builds a record and journals it (fire-and-forget, like
  every diagnostics row). It returns `None`; `pick_contract`'s result does not depend on it.
- `_study_tick` runs at the end of `_diag_tick` on the two-second quote watch. It is synchronous, awaits nothing and starts no task.

## The four corrections, and the tests that pin them

### R1. Quote validity is the study's own rule, at both ends

`quote_evidence()`: bid > 0 and ask > 0, both finite, ask >= bid, the quote's own `source` exactly `"opra"`, a positive source
timestamp that is **not after** its collection time (no clock tolerance) and at most 30 s before it. The entry is re-validated from
the BOUND FIELDS of the chosen candidate row; the diagnostics' `priceKnown` flag (which accepts ask-only rows) is ignored. A follow-up
quote is judged by the same function. The runner copies `Quote.source` as it is: nothing is inferred or synthesised.

Tests: `test_study_quote_evidence_refuses_every_weak_quote` (16 cases: missing or zero bid, zero or non-finite ask, crossed, missing /
empty / `chain` / `derived:` source, missing or zero source time, no collection time, future-dated, stale),
`..._accepts_the_valid_controls`, `test_entry_is_revalidated_from_the_bound_fields_never_from_the_diagnostics_flag` (including the REAL
producer `diagnostics.candidate_rows`), `test_follow_up_validity_on_the_quotes_own_clock_with_no_future_tolerance` (valid controls and
ten refusals), `test_the_runner_never_synthesises_provenance_for_a_follow_up_quote`; the review team's
`test_entry_rechecks_required_bid_in_real_candidate_output` and `test_future_source_time_is_not_study_evidence`.

### R2. Lifecycle, capacity and the immutable opening

- **Capacity unit = the UNIQUE opportunity** (one contract), at most 12 across the desk. When a second or third book examines an
  opportunity another book already follows, its opening is journaled with `duplicateOf` (the follower's run, book and `openHash`),
  carries no schedule and uses no slot. The follower is the FIRST book to open it; `collapse()` takes the follower's record and lists
  every book that examined it (`c1Only` when only C1 did).
- **Everything that was opened is closed**, deterministically, by `_study_tick`, which keeps running while records remain even when
  the switch is off: `plan removed before the observation`, `collector switched off`, `session ended` (after 15:45 ET plus the
  window), or a resolved observation. Closing journals ONE `selection_study_close` and removes the record from memory; the id is
  remembered so a later revision cannot reopen it.
- **A close is bound to its opening.** Every record carries `openHash` (study, identity, book, trigger, features, entry quote, recorded
  time, due times). `collapse()` accepts only a close carrying the follower's `openHash`, takes the FIRST one, and counts later or
  foreign closes as `ignoredCloses`; entry and features always come from the OPENING row.
- **Restart.** Records restored through the real `restore_extras` hook wait for `_study_reconcile`, which runs inside the existing
  restart journal read (`load_contract_verdicts`) and drops every record whose close is already in the journal. The wait is bounded
  (60 s): if the journal cannot be read the record proceeds, and a duplicate close would be ignored by `collapse()` anyway.

Tests: `test_three_books_on_one_opportunity_use_one_slot_and_one_observation`, `test_twelve_unique_opportunities_fill_capacity_...`,
`test_a_removed_plan_is_closed_frees_its_slot_and_stays_in_the_denominator` (disarm before the 10-minute and before the 30-minute
observation), `test_end_of_session_switch_off_and_a_later_session_all_release_capacity`, `test_a_revision_never_reopens_and_a_close_is_journaled_once`,
`test_a_close_is_bound_to_the_immutable_opening_and_later_or_foreign_closes_are_ignored`,
`test_restore_through_the_real_persistence_hooks_reconciles_journaled_closes` (real `state_extras` / `restore_extras`, a journaled close,
a bounded wait), `test_incomplete_observations_stay_in_the_coverage_denominator`; the review team's
`test_removed_plan_cannot_hold_capacity_forever`.

### R3. Features are point-in-time evidence

`snapshot()` is taken synchronously when the signal is created and stores the features together with the hash of the exact bar values
used. `_study_open` only COPIES that capture; it never recomputes, and the first capture stands. Without a capture the six features
are `unknown` ("not captured at the signal"). The room feature no longer uses the picker's spot: `_study_actionable` reads the
underlying's last print by its own `last_ts`, else the midpoint by `quote_ts` / `source_ts`, within `stale_seconds`, refuses zero and
future times, and otherwise the feature is `unknown`. It does NOT call `_fresh_underlying`, because that helper writes the runner's own
decision evidence; the collector writes nothing of the runner's. Contract selection and trading policy are untouched.

Tests: `test_features_read_nothing_at_or_after_the_contact_bar`, `test_feature_values_and_unknowns`,
`test_the_room_price_is_bound_to_its_own_field_time_or_is_unknown` (stale last with a fresh midpoint, fresh last, no source evidence,
future print, and the runner's `_last_actionable` left untouched),
`test_features_are_frozen_at_the_signal_and_survive_a_correction_during_the_awaited_pick` (an earlier bar is corrected and the quote
moves during the pick: the opened record equals the capture; a second capture does not replace the first; no capture gives unknown).

### R4. Operational isolation, shown through the actual runner

- **The collector is passive.** It makes no provider request and never calls `refresh_now`, `reprice`, `track` or any untrack: the
  option service's own enrich loop already refreshes every tracked contract about every five seconds, and the chosen contract is
  tracked by the picker's walk. An observation is a synchronous read of `engine.quotes`. The first package's forced refresh (which
  refreshes the WHOLE tracked set through a shared service) is gone, and with it every task, timeout and `inflight` state. A contract
  that is no longer tracked, or a cache that raises, yields `unknown` when the window ends; the slot is freed.
- **Real on/off comparison** (`test_the_actual_runner_takes_identical_decisions_and_order_intents_with_the_collector_on_and_off`): the real
  chain `_fire_from_event` -> gates -> `pick_contract` -> sizing -> the real `OrderIntent` at the placement boundary, on a controlled
  clock, run twice. Compared equal: the order intent (book, contract, side, quantity, type, limit, time in force), the trade's status,
  reason, quantity and limit, every provider call and every forced refresh made by the entry path, the journal's non-study rows, the
  persisted keys, and the diagnostics attempt record apart from the study capture. With the collector on, 33 minutes of ticks add zero
  provider calls and zero forced refreshes and produce one open and one close with valid observations.
- `test_a_failing_quote_cache_is_recorded_and_never_raises_or_holds_a_slot`: the option quote cache raises on every read; trading goes
  ahead, both observations close as `no valid quote inside the window`, nothing raises.
- `test_every_study_hook_is_synchronous_and_the_observation_path_awaits_nothing`: a structural check kept only as a tripwire, not as
  the proof.

## The frozen analysis

`selection_study_analysis.analyse()` implements page 7's rules exactly and is hash-pinned
(`test_the_analysis_file_is_frozen`): a change to that file fails the suite and is a new registration. Tests cover: a clearly better
bucket passes and exactly one feature goes forward; **a significantly WORSE favoured bucket cannot pass even with a positive mean**; a
better but still losing bucket fails; an effect carried by three sessions fails; each per-side minimum and the coverage gap give
`insufficient evidence`; `c1Only`, excluded sessions and rows of an earlier registration are set apart and counted; Holm's adjusted
values; the frozen tie-break; and the tool showing coverage only until the stop rule.

## Suite results (2026-09-19, worktree on the PR head, own database `zargar_test_team2`)

| Run | Result |
|---|---|
| Collector, review-team probes and analysis (`test_team2_selection_study.py`, `test_codex_team2_collector_boundaries.py`, `test_team2_selection_analysis.py`) | 57 passed |
| Full Team2 suite: `tests/test_team2_*.py tests/test_codex_team2_*.py tests/test_marketstructure_extended.py` | **441 passed** in 3 min 57 s |
| `python -c "import zargar.api.app"` | ok |
| Not run here | the platform chaos suite and `test_platform_phase3.py` (its contract test fails on main until PR #224 merges; this package does not touch shared execution code) |

## Known limits (stated, not hidden)

- F-f needs the fire's target; on the shadow path the planned target from the read's event is used, and `unknown` when it has none.
- F-b tells today's pre-market levels from the previous session's only; older levels need C2 key levels, which stay off.
- If the follower's plan is removed, the opportunity is `incomplete` even when another book is still armed: no hand-over is attempted.
- After a restart the option service's tracked set is rebuilt from positions, so a restored observation of an untracked contract will
  usually end `unknown`. It stays in the denominator.
- Passive reads depend on the enrich loop's cadence (default 5 s) and on the NBBO's own source time being within 30 s: a quiet contract
  can miss its window and is recorded `unknown`.
