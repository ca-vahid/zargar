# Options Cartel — current guide

Updated 2026-09-13 against integrated main. Technique id: `options_cartel`.
Sean Trades (`@SRxTrades`) is the source author; the app's numerical interpretations and Practice experiments are identified separately.

The desk is implemented. The [September 13 correctness release](READINESS-2026-09-13.md) adds final-entry contract checks, target integrity, pending invalidation protection, explicit legacy-arm review and quantity-correct Practice research. Other desks can advance the app-wide version independently. Use the release handoff and live health for deployment state.

## Start here

1. Read [Automatic daily preparation](DAILY-PREPARATION.md) for account routing, settings, preparation, recovery and arming.
2. Read [Post-ignition workflow](IGNITION.md) before selecting the optional Practice pilot. Its research watchlist does not itself trade.
3. Use [Current capabilities and limits](DELIVERY-STATUS.md) to distinguish shipped behavior from open validation work.
4. Open Plans for preparation, Armed for actual monitored campaigns, History/Validation for research and Method for source documentation. Records have dedicated `/techniques/options-cartel/run/<runId>` URLs.

Practice uses the configured Options Cartel Practice book. Live has separate settings and permissions. Preparation builds plans and may arm them; entry orders still require the engine's closed-bar, data, quote, cash/risk and execution checks. An armed plan is not a filled position. Held positions retain their protective management when preparation is stopped or a new plan expires.

## Documentation map

| Purpose | Documents |
|---|---|
| Operating instructions | [Preparation](DAILY-PREPARATION.md), [record details](RECORD-PAGE.md), [selected-symbol scans](SCANNING.md), [replays/comparisons](REPLAY.md) |
| Method and policy | [Method](METHOD.md), [ignition](IGNITION.md), [trading decisions](TRADING-RULES.md), [traceability](TRACEABILITY.md) |
| Source evidence | [Source ledger](SOURCES.md), [source-version review](SOURCE-REVIEW.md), [video evidence](VIDEO-REVIEW.md), [examples](EXAMPLES.md), [public ledger audit](LEDGER-REVIEW.md), [industry evidence](INDUSTRY-DATA.md) |
| Developer work | [Work status/backlog](PLAN.md), [release handoff](RELEASE-HANDOFF.md), [September 12 release scope](RELIABILITY-RELEASE-2026-09-12.md) |
| Historical evidence | [September 12 deployment](DEPLOYMENT-2026-09-12.md), [weekend review](WEEKEND-REVIEW-2026-09-12.md), [original proposal](IMPLEMENTATION-PLAN-2026-09-12.md), [archived milestones](archive/PLAN-PRE-2026-09-13.md) |
| Documentation changes | [Change record](DOCUMENTATION-CHANGES.md) |

The in-app Method library bundles selected Markdown chapters. A frontend rebuild is needed to display updated text. Git documentation updates do not themselves restart the app or change account settings.

## Collaboration and evidence boundaries

Follow root [AGENTS.md](../../../AGENTS.md) and [COLLABORATION.md](../../COLLABORATION.md). Preserve Claude worktrees and the shared runtime. Codex tests use only `zargar_test_codex`, sequentially. Never start a second engine against a runtime or test database. Keep other techniques' knowledge/rules separate.

No full public-feed coverage, exact author replication, broker-verified author return or profitable strategy has been established. Test success verifies the tested mechanics; source examples and replay R are not realized option P&L. Active plans, balances, versions and provider availability must be checked live when needed.

- [Intraday market research: accepted decision and limits](INTRADAY-RESEARCH-DECISION-2026-09-14.md)
  records the user-approved observation-only experiment. It does not change trading permission.
