# Rule and implementation traceability

The original milestone table below records 2026-09-06 implementation stages.
For current completion boundaries use [DELIVERY-STATUS.md](DELIVERY-STATUS.md).
Later integrations supersede the original table's pending statements as follows.

| Added integration | Code | Evidence/limits |
|---|---|---|
| Alert/proposal/auto and fresh-signal approval | `runtime.py`, `controller.py`, `observer.py` | Runtime/controller/observer tests and isolated future-plan UI checks; broker rollout still pending. |
| Working partials and late fills | `settlement.py`, `adoption.py`, `residuals.py` | Settlement/adoption/residual tests; durable position identity and no blind resubmission. |
| Managed campaign exits | `position_adapter.py`, `exit_router.py` | Actual-fill allocation, cancel/replace, stop sizing and restart tests; missed daily-close catch-up remains open. |
| Account-scoped daily risk and prior marks | `loss.py`, `marks.py` | Loss/marks tests; source-compatible recovery and persistent session latch. |
| Campaign replay | `replay.py`, `replay_service.py` | Replay/API tests and browser missing-data case; underlying-price simulation, not premium returns. |
| Entry-rule comparisons | `sweeps.py` | Sweep/API tests, immutable snapshots and paired complete-case statistics; selected-plan experiments, not universe walk-forward. |
| Multi-symbol scanning | `scans.py` | API partial-failure tests and browser MU/HOOD provider scan; industry/universe collection and scheduling still pending. |
| Related-account example attribution | `EXAMPLES.md` S25/S26 | All HIMS attachments inspected; distinct member contracts cannot be merged into Sean's campaign. |
| Ascending triangle | S18; `setups.py`, `plans.py` | Distinct bullish candidate, repeated ceiling touches/rising support/contraction, context rejection and plan round-trip tests. Numeric thresholds remain engineering choices. |

| Requirement | Source | Current code | Evidence / remaining work |
|---|---|---|---|
| Independent identity/rules | User; platform separation | `options_cartel/rules.py` | No EM/Tip/Team2 knowledge imports; registration not yet done |
| Market EMA context | S02, S04, S06 | `screen.market_regime` | Both indices, missing/stale inputs, bearish and disagreement tests |
| June stock thresholds | S02 | `CartelRules.for_profile`, `screen_listing` | Strict price/cap/volume/ADR thresholds; completed-day volume is our explicit interpretation |
| Historical May screen | S04 | `CartelRules.for_profile` | ADR and EMA differences preserved rather than silently blended |
| June scanner image | S02 image HL2QABMWYAAXbHO.png | `june_2026_image`, `volume_basis`/`volume_period` | Mean of ten complete sessions; ADR >2%; quiet-day/spike/missing-window tests; legacy snapshots retain last-session basis. Browser selection and device audit passed. |
| Weekly/monthly industry ranks | S01 | `ListingFacts`, `screen_listing` | Top-ten agreement, unknown/stale/future/wrong-direction tests; provider not yet integrated |
| Small volume-sorted focus list | S02 | `focus_list` | Stable order/cap/unknown rejection tests; setup-qualified final list still pending |
| Completed daily and weekly inputs | Platform parity; M4 causality | `data.completed_daily`, `complete_weeks` | Future bars do not change past read; half-day/holiday/missing session tests |
| ADR/ATR definitions | Engineering D6 below | `screen_listing` | Lookbacks snapshotted; not falsely attributed to Sean |
| Setup geometry and relative strength | S01/S02/S05 + D9 | `setups.analyze_setups` | Seven measured candidate families; aligned-date relative strength; weekly/daily context and 13 synthetic tests. Source-example validation pending. |
| Reviewed plan composition | S01/S02 + D10 | `prepare.prepare_plan` | Screen-to-setup-to-plan-to-entry tested; sourced targets, source-dated volume medians; persistence/runtime pending |
| Entry/initial stop | S01/S02/S03 + D7/D8 | `plans.CartelPlan`, `entry.read_entry` | 15 tests: causal confirmation/extremes, configurable source variants, missing data, retests and stable replay IDs. Prepared levels only; no execution adapter yet. |
| Daily EMA/extension exits | S01/S02/S04 + D11 | `exits.ExitCampaign`, `position_adapter.CartelPositionAdapter` | Pure policy plus real-manager tests: daily aggregation, actual fills, restart state, pending exits, missing-data warnings and a real simulated trim. Entry adoption orchestration and missing-history recovery still pending. |
| Shares/puts/options expression | S06/S15 + D12/D16 | `execution.preflight`, `contracts.select_contract` | Reviewed routine selection and risk preflight APIs; 15 selector tests plus API ownership/journal check. Live submission integration remains unfinished. |
| Research persistence and API | User goal / platform provenance | `service.CartelService`, `api/routes_options_cartel.py` | 4 PostgreSQL API tests: owned records, immutable snapshots, parent links, journal events, authentication and no orders. Not live arming. |
| Market-history collection | Shared provider + causal input contract | `collect.collect_inputs`, `/api/options-cartel/collect` | 6 boundary tests and persisted collection API test; live SPY/QQQ daily/minute probe. Metadata remains a separate explicit input, not fabricated or inferred from future data. |
| Expression/risk preflight | Platform invariants + D12 | `execution.preflight`, `/runs/{id}/preflight` | 11 real-RiskGate cases plus journaled API denial; no orders. Actual submission/adoption/recovery remains unfinished. |
| Routine delta selection | S15 + D15 | `execution.preflight`, OptionsService per-field observation times | Missing/stale/future/low/wrong-sign delta rejected; negative put delta and explicit reviewed exceptions tested. Automatic contract selection/submission still pending. |
| Durable arming/attempt ownership | Write-ahead and restore invariants | `state.ArmRepository` | 11 PostgreSQL concurrency/crash-state cases; exact order association, no blind retry. Runtime listener and fill adoption still pending. |
| Terminal entry adoption | Actual fills precede managed exposure | `adoption.adopt_confirmed_entry` | Eight PostgreSQL cases; deterministic identity, reserved-order matching, actual holdings, save failure/retry and no closed-position resurrection. Working-partial protection and live entry orchestration remain pending. |
| Cancel/terminal settlement | No blind resubmission; reports are authoritative | `settlement.settle_entry` | Five PostgreSQL cases: optimistic cancellation, confirmed partial adoption, failure, unfilled terminal state and working-order preservation. Pending-partial protection is still required. |
| Recover missing daily data | Persisted execution beats replay | `position_adapter.recover_daily` | Four PostgreSQL cases; preserves actual fills, rejects conflicts/future/rewind, records missed closes. Acquisition scheduling and catch-up decisions remain pending. |

## D6 — first explicit engineering definitions

- ADR: arithmetic mean of `(daily high - daily low) / daily low * 100`, 20
  completed sessions by default. Source gives the threshold, not this lookback.
- ATR: Wilder smoothing, 14-session default; reference prior close for gaps.
- Market agreement: both SPY and QQQ must agree; unknown/mixed cannot pass.
- Ranking and market-cap snapshots: require a source and observation timestamp;
  seven-calendar-day freshness default, reject future snapshots during replay.
- September profile retains June's numerical screen where September specifies
  qualitative context but no replacement. This choice is disclosed in every snapshot.
- Bearish industry ranks must explicitly be supplied as downside rankings;
  bullish strength rankings cannot silently become bearish selection evidence.
- Daily provider adapters must supply exchange session dates; no assumption that
  a UTC-midnight provider timestamp is the ET trading date.

These are parameterized engineering definitions subject to source refinement
and validation. They are not calibration results or claimed author rules.

## D9/D10 — setup and preparation definitions (2026-09-06)

`SetupParameters` explicitly contains the initial uncalibrated measurements:
10-session base, 8 complete weekly candles, 20-session benchmark-relative return,
15% daily base range, 50% weekly range, 15% proximity to weekly directional extreme,
0.8 consolidation/prior-volume ratio, 5% impulse, 0.10%/bar line slope tolerance,
and 0.5% touch tolerance. Directional measurements are mirrored for bearish puts.
Slope/inside-day/EMA-touch/retest labels describe measured geometry, not an
independently verified classifier matching every source example.

Historical three-bar-confirmed pivots supply candidate resistance/support targets.
At new extremes no Fibonacci projection or arbitrary R target is invented;
the reviewer must supply levels and their source/rationale. A review cannot
override failed market/context checks through `prepare_plan`.

Volume baseline: median of complete same-time 5/15/30m buckets from up to 20
already-closed sessions, requiring five samples per bucket. Missing minutes do
not count as zero volume; half-day afternoon buckets naturally have fewer samples.
Current unfinished sessions never enter the baseline. Sample counts, dates and
the engineering definition accompany the prepared plan for future persistence.
