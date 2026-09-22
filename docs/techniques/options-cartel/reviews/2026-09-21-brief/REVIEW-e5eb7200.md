# PR246 re-review — e5eb7200

Exact reviewed head: e5eb720012382cc9f791452d26e0e8d9183a17af.
Isolated checkout: C:/Cursor/zargar-codex/.cache/cartel-pr246-r2.
Reviewer branch: codex/review-cartel-246-r2. Production source was not modified;
only this report and two targeted acceptance probes were added by the reviewer.
No runtime, settings, arms, deployment or activation changed.

## Verdict

**Changes requested, narrowed to two remaining code boundaries under R1 and R6.**
Do not merge/deploy the combined release yet. The original seven probes pass and
the new end-to-end fixture is useful, but neither proves the two cases below.
R2, R3, R4, R5 and R7 are closed within the reviewed scope. R1/R6's original
failures are corrected, with the remaining lifecycle/as-of issues described here.

Independent verification:
- **83 passed:** retained seven probes, end-to-end fixture, short/long preparation,
  cadence, attribution and contracts suites.
- Production frontend/release metadata **passed**, v0.8.29.
- **Two targeted boundary probes failed** reproducibly.
- Sequential scripts/test-codex.ps1 on zargar_test_codex only. No claim of an
  independent full339-test run; the separately confirmed base exit-fixture failure
  was not reclassified as a new regression.

## R1 follow-up — P1: restoring a control does not restore its data subscription

Locations: observer.py::_register_control_stored (221-233), runtime.py::restore
(205-209), engine.py::_startup_symbols (325-340).

A retired/disarmed executing row with no order is skipped by the execution restore
loop. The second loop now correctly registers its control, but registration only
loads the plan and inserts into controls. It never ensures/subscribes the underlying
symbol. Engine startup subscribes watchlists, held instruments and the default
symbol, not arbitrary retired controls. If nothing else watches that symbol after
a real process restart, the registered control receives no new bars.

The new end-to-end test reuses the existing engine/feed and calls on_minute_bar
directly after restart, so it cannot reveal this missing upstream dependency.

Probe: test_restored_retired_control_restores_its_market_data_subscription.
The registry contains r1, but ensure_symbol('HOOD') is never awaited. This is the
remaining real-runtime boundary of the original requirement that controls retain
an independent subscription and lifetime, not a new trading feature request.

Required fix: establish canonical market-data subscription for every current-session
restored control, even when it has no active execution row, position or watchlist.
Use the normal engine ensure/watch path with bounded error handling; surface a
coverage failure without pretending observation continued. Preserve the restore
watermark and no-order boundary. Test a fresh feed/engine with no other watcher,
then deliver bars through the bus instead of invoking the control callback directly.

## R6 follow-up — P2: later mutable order totals leak into an as-of report

Locations: review_attribution.py::entry_ledger (158-160), session_review.py (121-124).

The fills ledger correctly excludes fills after the report cutoff. entry_ledger
then overrides that quantity with the current Order.filled_qty, and uses the
current order status. Selecting an order because it was created before the cutoff
does not make its latest cumulative totals/status historical evidence.

Probe: test_asof_partial_fills_do_not_use_later_order_cumulative_totals.
Two units fill before the cutoff, a third after it. summarize_fills correctly
returns entryFilledQty=2; attribution.entry reports3 from the later FILLED order
row. This can mislabel historical partial/working entries as fully filled.

Required fix: cumulative fills at cutoff must come from executions filtered to that
cutoff. Derive requested quantity and order disposition from time-qualified order
history/snapshots, or label disposition unknown when it cannot be reconstructed.
Do not use remaining holdings as cumulative entry fills. Cover a later fill,
a later cancellation/rejection, partial exits and report cutoffs across sessions.

## End-to-end fixture clock correction

At test_cartel_end_to_end.py:175, `_now = lambda: OPEN+17*MIN/1000` adds milliseconds
to seconds. PositionManager.now_ms multiplies this by1000. The intended expression
is `(OPEN+17*MIN)/1000`, as in the earlier clock assignments. Correct it and assert
the manager timestamp after restore. This is a test-fixture defect, not a third
identified production regression; it weakens the current restart-time validation.
A post-restore management tick should be checked in addition to position quantity.

## Unchanged release/activation limits

The non-15m research-panel exclusion and underlying-quote observation timestamp
issue remain explicit F4 activation limits. The volume grid stays off until the
finite comparison is performed. F5-F8/shares remain outside this package. No new
future-session waiting requirement is introduced by this review. A corrected
F1-F3 release can be assessed separately if the team chooses to split scope;
the current combined head is not yet accepted.

## Reproduction and handback

```powershell
./scripts/test-codex.ps1 tests/test_pr246_review_boundaries.py tests/test_cartel_end_to_end.py tests/test_cartel_cadence_preparation.py tests/test_cartel_cadence.py tests/test_cartel_review_attribution.py tests/test_options_cartel_contracts.py -q
./scripts/test-codex.ps1 tests/test_pr246_round2_boundaries.py -q --tb=short
```

Return one narrow correction with the two probes retained/adapted into meaningful
regressions, the fixed fixture clock, focused results and separate code/deployment/
activation verdicts. No redesign of the selector or strategy is requested here.
