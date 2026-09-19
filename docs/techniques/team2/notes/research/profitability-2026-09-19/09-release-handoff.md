# 9. Selection study S1: release handoff (registration `s1-r4`)

> **DEPLOYED AND ACTIVATED on 2026-09-19** on the user's authorisation: see `10-deployment-and-activation-receipt.md`.
>
> **ACCEPTED by the review team (2026-09-19)**, with the documented limitations, for this acceptance scope: no further development
> and no historical rerun. The package is ready for a SEPARATE merge and deployment approval, with the collector kept OFF.
> ACTIVATION stays a separate decision, taken only after the deployed build, the plan restoration and the registration have been
> verified (section 5). Once activated, monitor counts, coverage and collector health ONLY until the frozen endpoint (section 6).
> Trading books, risk settings and C2 stay unchanged throughout.

**Verdict: READY WITH STATED LIMITATIONS** (after the release-review corrections of 2026-09-19: the operator CLI's event-loop
ownership, journal-order precedence before canonical hashing, an immutable first finalization, and artifact integrity, where the
saved manifest and report are hashed before any comparison). The code is complete and passes its acceptance packet and the required suites on the
combined release tree. The collector is OFF; nothing may start until the review team accepts this package and the owner separately
approves deployment and activation. There is no code blocker. The remaining items are approvals and the limitations below.

## 1. Commit and dependencies

| Item | Status |
|---|---|
| Release tree | branch `claude/trading-technique-research-56296a` (PR #223): the head commit that contains this file |
| Release-review corrections | R1 CLI event loop, R2 first-close precedence, R3 immutable finalization: all three fixed here; the reviewers' three probes are adopted verbatim and pass |
| PR #224 (`TechniquePlanDiagnostic` event contract) | **merged INTO this tree** (commit `024a4749`); the targeted contract check passes here. PR #224 itself is still open on GitHub and can be closed as superseded once #223 merges, or merged first: either order gives the same tree |
| `main` | merged into the tree before testing (main at `d815ccaf`, PR #234) |
| Runtime | v0.8.23 build `b6e272…` (EM desk). The tree reports 0.8.22 because the EM desk's 0.8.23 has not reached `main`; the deploy step merges main again, as for every desk |
| Nothing enabled | `techniques.team2.selection_study` default `off`; no setting, book, rule, risk, product pricing or C2 window changed |

## 2. Registration and lifecycle (full text: `07-selection-study-spec.md`)

| | |
|---|---|
| Study / registration | `s1-r4`, registration hash `13b2bcc18bbbf5fa` (`python -m zargar.tools.team2_selection_study registration` prints the whole record) |
| Analysis | `selection_study_analysis.py`, sha256 `4022fccf7e06d9102d0c3048e0951be35a7a34541fcb46574b04ff4ac9f1aa48`, part of the registration |
| Identity | `date|SYMBOL|setupId|signalTs`, the contact bar's close; first opening owns; other books journal `duplicateOf` openings with no slot |
| Quote evidence | finite bid > 0 and ask > 0, ask >= bid, source exactly `opra`, source time never after collection, at most 30 s old, both ends |
| Timing | entry quote within 90 s after the signal; clocks from the entry quote's source time; 10 and 30 minutes; window 90 s; due after 15:45 = late |
| Outcome and costs | R30 after $1.04 per contract per side, winsorised at +200%; secondary (R10, R30 one tick worse) descriptive only |
| Capacity | 12 unique opportunities across the desk |
| Analysis rule | date-clustered bootstrap (10,000, seed 20260919); Holm over all six (unjudgeable at p = 1); pass = Holm p < 0.05 AND d > 0 with lower bound > 0 AND favoured mean > 0 AND sign kept without the 3 best sessions; per side >= 60 valid, >= 20 sessions, coverage >= 80%, gap <= 15 points; one feature forward by the frozen tie-break |
| States | prepared -> collecting -> stopped_insufficient_coverage or ready_for_final_analysis -> finalized |
| Sessions | counted / excluded (early close, restart 09:30-15:45 ET, 3-minute bar gap) / partial / disabled; ONLY counted sessions advance the count and enter the sample; zero-opportunity sessions count |
| Endpoint | close of the 60th counted session or of the 2026-12-18 session, whichever first, in ET on the NYSE calendar |
| Early stop | coverage < 60% at the close of the 15th or any later counted session: stopped, no final analysis |

## 3. Tests: commands and results

All results below were run by me on the combined tree in an isolated worktree, database `zargar_test_team2`, sequentially.
**None of the r4 results has been run by anyone else yet.** Earlier and separate: the review team independently ran the r3 packet
(12 supplied tests passed, their 3 probes failed at the held head; the probes pass since r3).

```
cd backend
export PYTHONPATH=<worktree>/backend ZARGAR_TEST_DATABASE_URL=postgresql+asyncpg://zargar:zargar@127.0.0.1:5433/zargar_test_team2
python -m pytest tests/test_team2_selection_study.py tests/test_team2_selection_analysis.py tests/test_team2_selection_lifecycle.py \
    tests/test_team2_selection_e2e.py tests/test_codex_team2_collector_boundaries.py -q -W "error:coroutine:RuntimeWarning"
python -m pytest "tests/test_platform_phase3.py::test_every_journaled_kind_has_a_contract" -q
python -m pytest tests/test_team2_*.py tests/test_codex_team2_*.py tests/test_marketstructure_extended.py tests/test_platform_phase3.py -q
python -m zargar.tools.team2_selection_study demo
```

| Run | Result |
|---|---|
| Selection packet (collector 41, analysis 16, lifecycle 15, end-to-end 3, release 8, review probes 3+3), unawaited coroutines as errors | **89 passed** in 64 s |
| Full Team2 + reviewer suites + `test_platform_phase3.py` (includes the event-contract check) | **486 passed** in 3 min 55 s |
| `import zargar.api.app` | ok |
| Not run | the platform chaos suite and other desks' suites: this package changes no shared execution code |

What the new cases cover (requested list):

| Case | Test |
|---|---|
| zero-opportunity session accounting | `test_zero_opportunity_sessions_count_and_the_first_eligible_session_is_the_first_full_one` |
| 59 sessions + an opening on the 60th morning | `test_59_counted_sessions_and_an_opening_on_the_60th_morning_do_not_unlock_the_analysis` |
| before / at the exact deadline, ET | `test_the_deadline_is_the_close_of_the_2026_12_18_session_in_et` |
| objective exclusions, partial and disabled | `test_objective_exclusions_partial_and_disabled_sessions_never_advance_the_count` (restart inside/after the cut-off/before the open; 3-minute vs 2-minute bar gap; early close; mid-session activation; off for part / all of a day) |
| pending observations at the endpoint; post-endpoint records | `test_pending_observations_at_the_endpoint_and_post_endpoint_records_stay_out_of_the_sample` |
| repeated finalization, identical identities | `test_repeated_finalisation_is_identical_order_independent_and_verifiable` (shuffled input, later clock, tamper detected) |
| known positive / negative / insufficient datasets through the final path | `test_known_datasets_through_lifecycle_and_final_analysis` |
| poor-coverage early stop, coverage-only view | `test_the_poor_coverage_early_stop_is_applied_from_the_15th_session` |
| end to end: activation -> collection -> restart -> completion -> final report | `test_activation_collection_restart_completion_and_final_report` (real journal, real `state_extras` / `restore_extras`, real reconciliation, the tool's own loader on the test database; mid-session restart excludes that day; a stale-state restart after the close is committed does not duplicate it; recorded and verified) |
| journal-write failure; restart before an opening / after a closing commit | `test_a_lost_journal_write_is_visible_and_the_opportunity_stays_in_the_denominator` (lost opening -> recovered from the close; lost close -> `incomplete`; health survives restart) |
| unawaited coroutine | `test_the_synchronous_hooks_create_no_coroutine_without_a_running_loop`; the packet runs with coroutine warnings as errors |
| on/off runner comparison, provider calls, sizing, intents | `test_the_actual_runner_takes_identical_decisions_and_order_intents_with_the_collector_on_and_off` (awaits the whole fire chain) |
| **the real CLI**: status, wrong confirmation, activate, duplicate activation, `final` before the endpoint | `test_the_real_cli_status_activate_and_duplicate_activation_on_the_test_database` (subprocesses; exit codes, durable row counts, and no `Event loop is closed`, `never awaited` or traceback in stderr) |
| **the real CLI**: seal, repeated `final --record`, later rows, a later bar backfill, refusing to overwrite | `test_the_real_cli_seals_the_first_final_and_later_rows_or_backfills_never_change_it` |
| **journal-order precedence**: conflicting later closes (worse AND better), shuffled transport | `test_the_first_journaled_close_wins_under_any_transport_order_and_price_never_decides` |
| **multiple candidate openings** (a restart re-opening) | `test_the_first_journaled_opening_owns_and_a_later_opening_cannot_take_over` |
| **the seal**: later duplicate, rows after the endpoint, a reclassifying backfill, a second conflicting final row, a tampered seal | `test_the_seal_is_the_first_recorded_final_and_later_data_only_shows_as_drift` |
| **artifact integrity**: unchanged, edited report, edited manifest, edited and re-hashed, missing payloads, missing declared hash, tampered seal | `test_artifact_integrity_hashes_the_saved_payloads` |
| **artifact integrity through the real CLI**: verify after sealing, after each kind of edit, with payloads removed, with a corrupt file, and with later drift on a valid artifact | `test_the_real_cli_verify_fails_on_an_edited_or_missing_payload_but_not_on_drift` |
| the read-only tool never switches collection off | `test_status_tells_the_operator_to_switch_off_and_never_claims_to_do_it` |

## 4. Deterministic example (`python -m zargar.tools.team2_selection_study demo`)

Synthetic, no database: activation after the close of 2026-09-30, collector on; a restart on 2026-10-08 at 11:07, a QQQ outage on
2026-10-14, collector off on 2026-10-19, the 2026-11-27 early close; zero-opportunity sessions; four opportunities on other days, one
examined by two books; some 30-minute quotes missing. Output (identical on every run):

| Field | Value |
|---|---|
| state | `ready_for_final_analysis` |
| first eligible session | 2026-10-01 |
| counted / excluded / disabled | 52 / 3 / 1 |
| endpoint | deadline: close of the 2026-12-18 session (60 counted sessions were not reached) |
| selected records / rows outside the window | 176 / 99 (`session not counted`) |
| manifest sha256 | `bf518f290f1e27cc03e331112ee55f308bece64ece7b7e62b1837f112614c32e` |
| result sha256 | `77d51538f8fca1ad4dc96ee8f4b1d05b7c2a4cfdc687a0b54ff6896baca75eaa` |
| reproduced by a second run | yes |
| verdicts | flag, wait, first15, room: insufficient evidence; levelOrigin, scenario4: fail; study outcome `none` |

## 5. Deployment, activation and rollback (each step needs the owner's explicit approval)

Deployment (the collector stays off):
1. Review team accepts this package. Merge PR #223 into `main` (it contains PR #224).
2. Coordinated restart through the usual door: merge `main` into the running checkout, `python -c "import zargar.api.app"`,
   `node scripts/check-release.mjs`, `/api/ops/restart-check` must say safe, then `Start-ScheduledTask -TaskName ZargarRestart`.
   Never `start.ps1` / `Stop-Process` from an assistant shell.
3. Verify: `/api/health` build = the merged commit; `techniques.team2.selection_study` = `off`; `... team2_selection_study status`
   says `prepared`; Team2 plans restored equal by id.

Activation (a separate approval; outside market hours, after the close):
1. `python -m zargar.tools.team2_selection_study activate --build <the running build sha> --confirm 13b2bcc18bbbf5fa`
   (one journal row; refused if this registration is already activated).
2. `PATCH /api/settings` `techniques.team2.selection_study` = `collect` (journaled as `SettingChanged`).
3. `status` should report `collecting` with `firstEligibleSession` = the next trading day.

Finalising (after the endpoint, when `status` says `ready_for_final_analysis`):
1. `python -m zargar.tools.team2_selection_study final --out <dir> --record` writes `<dir>/final.json` and seals the result with ONE
   journal row. Every later `final` returns that sealed artifact and reports drift; a second `--record` is refused.
2. `python -m zargar.tools.team2_selection_study verify --out <dir>` hashes the saved manifest and report, compares them with
   their declared hashes and with the seal, and reports any drift. It exits 2 if the artifact was edited, re-hashed, truncated or lost
   its payloads; drift alone on a valid artifact exits 0.
3. Switch `techniques.team2.selection_study` back to `off`.

Every command reads its database from `ZARGAR_DATABASE_URL` (else `backend/.env`, i.e. the RUNTIME database). The CLI tests always
set it to the desk's test database, and a scoped `conftest` fixture enforces that for those modules.

Rollback:
- Stop collecting: `PATCH` the setting back to `off`. Open records are closed on the next quote-watch tick with `collector switched
  off`; the lifecycle marks later sessions `disabled` (not counted). Nothing is deleted. Trading is unaffected either way.
- Code rollback: with the setting `off` the collector is inert, so a code rollback is an ordinary release revert through the same
  coordinated restart. Journaled study rows stay; a later registration never mixes with them.
- Abandon the study: leave the setting off and record the decision; the rows remain as a documented, stopped registration.

## 6. Coverage-only monitoring (the ONLY view before the endpoint)

`python -m zargar.tools.team2_selection_study status`, from `backend/`, daily after the close. Look at:

- `state`, `countedSessions` / 60, `deadline`, `statusCounts` and `nonCounted` (every excluded, partial or disabled session with its
  reason). Unexpected `excluded` days mean restarts or bar gaps; unexpected `disabled` days mean the setting was switched off.
- `opportunitiesInCountedSessions`, `validOutcomes`, `coveragePct`, and `byFeature` coverage (counts and unknown reasons only).
  Coverage under 60% from the 15th counted session on stops the study by itself.
- `collectorHealth` must stay all zeros: any `journalWriteFailures`, `noEventLoop`, `quoteReadErrors`, `tickErrors`, `openErrors` or
  `snapshotErrors` is an operational incident to report apart from method performance.
- `recoveredOpenings` and `ignoredCloses` should be rare; each is a journal write that failed or a duplicate close that was ignored.
- Never run `final` before the state is `ready_for_final_analysis`; it refuses anyway.

## 7. Limitations that remain (accepted as stated, not blockers)

1. If the plan that owns an opportunity disappears, the opportunity ends `incomplete` even if another book still watches it. No hand-over.
2. After a restart, a restored observation of a contract that is no longer tracked will usually end `unknown`. It stays in the denominator.
3. Passive reads depend on the option service's refresh cadence (about 5 s) and the NBBO source time being within 30 s: a quiet contract
   can miss its window and is recorded `unknown`.
4. Restart detection uses Team2 `TechniquePlanRestored` rows. A restart while no Team2 plan is armed is not seen, but then nothing is being
   collected either.
5. The outage rule reads the runtime `bars` table; if bar persistence itself fails the day is excluded (conservative, never inflating the count).
6. The end-to-end and CLI tests drive the real runner for two sessions and journal the other sessions' rows synthetically; the lifecycle,
   loader, CLI and final path are the real ones. They were exercised on the test database, never against the runtime database.
8. Before the first seal, session eligibility is recomputed from the current records, so a bar backfill in that window can change a
   session's classification. The seal at the endpoint freezes it; afterwards later data only shows as drift.
7. Power: only differences of roughly 35 to 40 points of R30 can pass; `insufficient evidence` is a likely and valid outcome.

## 8. Backlog (optional, does not reopen acceptance)

- Hand an orphaned opportunity to another book that examined it.
- A dashboard card for `status`.
- Close PR #224 as superseded after #223 merges.
