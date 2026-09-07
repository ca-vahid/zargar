# Options Cartel execution acceptance gaps

Updated 2026-09-07: the full regression passed 1,096 tests, including the joined
option campaign below. Its earlier focused runtime/controller/adapter run passed
39 tests in 89.22 seconds. These checks do not establish browser or broker rollout acceptance.

## Existing integration evidence

- `test_options_cartel_runtime.py::test_public_auto_arm_bus_signal_fill_and_flatten`
  enters through the public arm API, publishes synthetic minute bars on the bus,
  uses the real OrderManager/RiskGate/SimExecutor, observes a filled share position
  in API detail, and flattens it through the API. It starts from a seeded plan and
  uses a controlled historical exchange clock; it is not browser acceptance.
- `test_options_cartel_controller.py::test_option_submission_preserves_contract_units_debit_and_overnight_ack`
  submits and adopts a simulated option fill, checking contract quantity, the 100x
  multiplier, actual premium and overnight acknowledgment. The option snapshot and
  market clock are test fixtures. It ends at adoption rather than campaign closure.
- `test_options_cartel_position_adapter.py::test_real_order_manager_sim_trim_is_reduce_only_and_fill_confirmed`
  verifies a real simulated share entry/trim, remaining holdings and realized P&L.
  Its prepared managed position is not the result of a complete option arm flow.
- Adapter/router/catch-up suites independently exercise restart accounting,
  pending-exit budgets, current-quote recovery and duplicate suppression.

## Joined acceptance case

Implemented in `test_options_cartel_runtime.py::test_option_campaign_api_entry_target_restore_and_stop`.
It enters through the arm API, uses real simulated fills for four contracts,
trims one at the source target, restores the manager/runner with three remaining,
repeats the old target bar without another trim, then closes the remainder at the
underlying stop. It verifies one BUY and two SELL orders, zero final holdings,
the 100x multiplier and $55 simulated realized P&L. API closure is awaited because
order and position projections update asynchronously. No production code was
changed for this acceptance case.

Use only zargar_test_codex and the existing deterministic simulation fixtures.
Start with a reviewed saved Cartel plan and arm an option through the public API.
Publish a qualifying closed-bar signal; require exactly one BUY intent and actual
fill adoption. Advance underlying and option quotes to a source profit target;
require a reduce-only exit, actual filled quantity, correct remaining contracts
and breakeven only after confirmation. Stop and restore the runner/manager, then
exercise the remaining campaign exit. Assert no repeated entry/trim, zero final
holdings, consistent API detail and realized P&L including the option multiplier.
Do not replace this with a test that directly assigns the desired final state.

The browser acceptance remains separate: select expression/contract controls,
arm in Practice, observe approval/working/managed/closed states and inspect saved
history. The current browser checks exercised research, imports, alerts and
controls, not a filled option campaign. Do not bypass real runtime session gates
or introduce orders into another worktree's runtime to obtain this evidence.

Broader requirements still include source-example calibration, premium-aware
replay, full universe/date walk-forward, venue normalization and operational soak.
