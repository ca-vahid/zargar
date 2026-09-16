# EM measurement follow-up: ef98903

**Scoped GO to integrate/deploy with the observer disabled. Keep observation activation and performance conclusions on hold for the three measurement corrections below.** The protective-exit blocking issue is fixed in the inspected code and passing reproduction. Existing baseline preparation and the accepted v0.7.83 release remain unaffected.

Reviewed commit: `ef98903716264e67ed28962bcfb64c2622e778fe`. Isolated checkout: `C:/Cursor/zargar-codex/.cache/em-measurement-closure`, detached. Primary folder/branch remain `C:/Cursor/zargar-codex`, `codex/zargar-development`. No runtime, settings, orders, preparation process or watcher was changed by the reviewer.

## Checks and progress

- All **15 existing focused cases pass**, including the unchanged eight reviewer reproductions. Both original reviewer files match after newline normalization.
- Two added capture cases fail at intended assertions in the same run: **15 passed, 2 failed in 0.67s**. One added source-confirmation-gap case separately fails in **0.21s**.
- All are pure tests: no engine start, database use, network or orders. Runs used `scripts/test-codex.ps1` sequentially. The first attempt was deferred when another task had pytest running; no concurrent database test run was started and no other process was stopped.
- The team's wider 47-pass group, known fixture issue and restore reruns remain reported results, not independently rerun here.
- Live health still showed v0.7.83 / `b7d8a574635aa0d6d2d6a4be0538dc06462c43e6`. At 01:22 ET September 15, the inspected preparation window had 84 completed and 12 running EM analysis records, with no EM arms yet. This is a progress snapshot, not the batch's final reviewed-row count. Existing watcher should report completion; do not launch another batch or interrupt this one.

The useful corrections are present: quote watch captures/enqueues without awaiting research I/O, settings default off, original filled quantity determines the small-position policy, missing depth stays unresolved, failures remain retryable, source availability and exact opening/next-entry minutes are checked, and option gates are explicitly not evaluated. Narrowing the implementation to raw capture rather than a complete shadow P&L lifecycle is accepted.

## MF-01 — P2: final ladder trim still differs from production

At `backend/zargar/execution/planrunner.py:518`, `_production_exit_qty` returns the full uncommitted remainder whenever the selected index is the last target. Production `plan_exit` does not always do this: its 30/40/15 ladder can leave a runner after TP3.

**Direct comparison:** original 100 shares, 30 remaining after earlier trims, `trims_done=2`. Actual `plan_exit` proposes **15 shares** at TP3, while the observer proposes **30**. The new test calls both implementations and compares their quantities.

**Correction:** preserve the actual last-rung quantity/runner rule instead of treating the last stored target as automatic full liquidation. Derive or share the production decision without mutating production state. Also label the remaining runner/flatten policy accurately in target-distance diagnostics. No target or real exit behavior is to change.

Test: `test_last_rung_preserves_the_production_runner_remainder`.

## MF-02 — P2: records captured while an append is pending can be duplicated

`_shadow_capture` checks the acknowledged seen set. Two quote passes before the background append succeeds therefore both capture the same trade/version/rung. `_shadow_record` does not recheck that key and writes both records. The new regression captures twice before recording, then drains both and observes **two durable-append calls instead of one**.

**Correction:** distinguish pending from acknowledged identity and validate idempotency at the writer. A queued duplicate must not append again after the first succeeds. Retry failures using the original record and timing. If claiming durable uniqueness across restart, enforce or recover that identity from durable evidence rather than the process-local set alone. Keep the bounded recorder and non-blocking protection boundary intact.

Test: `test_observations_captured_before_first_write_do_not_duplicate_the_rung`.

## MF-03 — P2: missing pre-entry minutes can change the first eligible confirmation

`backend/zargar/tools/em_source_candidates.py:139-178` iterates stored eligible bars without requiring continuity through the first confirmation/retest. It now catches incomplete opening ranges, missing next-entry minutes and gaps after entry, but not this earlier missing interval.

**Reproduction:** 09:30–09:34 opening range complete; source available before open; 09:35–09:59 absent; 10:00 closes above the level and 10:01 reaches the target. The evaluator returns a target result around 4.14R with a 10:01 entry, although an earlier confirmation, no-chase event or stop sequence is unknown.

**Correction:** check required continuity from the first eligible observation through confirmation and any retest, and classify missing relevant intervals as unknown. The same evidence rule applies to a claimed never-confirmed result when unseen eligible minutes could contain confirmation. This does not require bars before source eligibility except those required to construct the opening range.

Test: `test_missing_eligible_confirmation_minutes_cannot_be_replaced_by_later_entry`.

## Handoff

Adopt the three cases in `measurement-regressions/test_codex_em_capture_followup.py` and `measurement-regressions/test_source_confirmation_gap.py`; the capture file imports the team's `tests.test_em_forward_measurement` helpers. Correct the measurement only, preserve the fifteen passing cases, and return the focused results before activating collection. No further worker/release infrastructure expansion is requested. Baseline review-and-arm continues independently.

The disabled observer can travel with the next normally verified combined release after preparation completes. This is not an instruction to restart now, activate it, or make a new trading rule. Keep source-candidate path results separate from actual option admission and profitability.
