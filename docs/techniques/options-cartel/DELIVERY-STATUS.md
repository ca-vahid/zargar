# Current Cartel capabilities and limits

Reviewed 2026-09-13 against integrated main. Functional milestones v0.7.51–0.7.52 are deployed; the app-wide version can be newer. Use live health, Armed and account reports for current state. [September 12 deployment](DEPLOYMENT-2026-09-12.md) is a dated verification record.

| Area | Shipped | Remaining limits |
|---|---|---|
| Independent desk | Plans, Armed, History, Validation, Method, Settings; dedicated record URLs | No claim of exact author replication |
| Preparation | Broad discovery, industry context, ranking, plans, contract reserves, separate Practice/Live policy | Provider errors and incomplete searches can still produce no arms |
| Ownership and recovery | Renewable lease, explicit cancellation, eligible auto-resume, benchmark barrier, session-aware automatic expiry | Resume still reconstructs saved analyses; not every proposed checkpoint optimization shipped |
| Data quality | Source-bearing Cartel minutes, controller checks, source upgrades and prospective-only recovery | No full immutable candle-revision/decision-input ledger; same-quality revisions are not automatically preferred |
| History | Durable cache, incremental daily reads, 20-trading-session baseline requests | Corporate-action/ticker-gap resolution and verified no-trade semantics are not automatic |
| Native batch source | Opt-in multi-symbol collection with bounded pagination | Off by default; dataset equivalence, access and performance need validation |
| Ignition | Persistent research list and selectable long-side Practice pilot | Fixed versioned thresholds, no automatic calibration/promotion; research stage is not trading authority |
| Execution | Closed-bar controller, account/quote/risk gates, write-ahead attempts, partial-fill adoption, protective management and restore | Live availability depends on actual broker/configuration; no general Live acceptance claim |
| Readiness/capacity | Baseline gates, guarded capacity, preserved existing campaigns, terminal pending invalidation | Explicit strategy changes still require new plans; no arbitrary declared-window editor |
| Exits/risk | Whole-unit allocations, fill-driven transitions, daily loss reporting, distinct premium/underlying risk | Small positions cannot reproduce every percentage trim; no earned-risk-escalation model |
| Research | Underlying campaign replay, paired sweeps, recorded option-quote valuation, session decision report | No unbiased universe walk-forward or demonstrated profitable option expectancy |

## Verification evidence

The September 12 initial full Cartel run had 473 passes and seven failures. All seven were corrected and checked in a passing 92-test affected run; later 54-, 30-, 27- and 16-test groups covered additional boundaries/integration (overlapping groups). Production builds and four desktop/phone Practice/Live audits passed. This is not a claim that the final entire platform suite was rerun or that returns are profitable. Earlier 1,096-test counts belong to their older checkpoints.

## Open work

- Immutable data revisions with provider/feed/adjustment identity and reconstruction of exact decision inputs.
- Corporate actions, ticker history and verified no-trade interval handling across sources.
- Measured cold/warm/resume performance, including native-source equivalence/entitlement checks.
- Source-example calibration, full prospective option-fill evaluation and strategy graduation evidence.
- Richer catalyst/theme and thesis lifecycle modelling beyond the implemented detector/stages.
- Full receiver/broker-specific acceptance wherever Live execution is intended.

See [PLAN.md](PLAN.md) for ownership and change gates. No old plan is automatically promoted, no Live permission is inferred from a deployment, and no no-trade day proves a strategy defective or successful.
