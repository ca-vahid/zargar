# Options Cartel — current guide

Updated 2026-09-16. Technique id: `options_cartel`. Deployment evidence is separate from source status.
Sean Trades (`@SRxTrades`) is the source author; the app's numerical interpretations and Practice experiments are identified separately.

The desk supports daily preparation, automatic Practice execution, separately permissioned Live execution, durable position management, actual daily accounting and non-executing research. The current guides describe code behavior; app-wide versions and dated deployment notes do not by themselves prove what process is running. No profitable strategy or exact author replication has been established.

## Start here

1. Read [Automatic daily preparation](DAILY-PREPARATION.md) for account routing, settings, preparation, recovery and arming.
2. Read [Post-ignition workflow](IGNITION.md) before selecting the optional Practice pilot. Its research watchlist does not itself trade.
3. Use [Current capabilities and limits](DELIVERY-STATUS.md) to distinguish shipped behavior from open validation work.
4. Open Plans for preparation, Armed for actual monitored campaigns, History/Validation for research and Method for source documentation. Records have dedicated `/techniques/options-cartel/run/<runId>` URLs.

Practice uses the configured Options Cartel Practice book. Live has separate settings and permissions. Preparation builds plans and may arm them; entry orders still require the engine's closed-bar, data, quote, cash/risk and execution checks. An armed plan is not a filled position. Held positions retain their protective management when preparation is stopped or a new plan expires.

## Reading status correctly

- **Armed** means waiting for a valid entry, not purchased. Before its first session, a plan names that future date and owes no prior-day observation minutes.
- **Waiting for benchmark** means the provider has not supplied the required completed SPY/QQQ session. It is not a bearish or bullish judgment.
- **Daily review** reports actual orders, executions and fees. **Validation → Profitability research** reports hypothetical comparisons and missing evidence.
- A **short** setup expresses downside through the reviewed option contract, normally a put; it is not permission to short shares. The separately tagged bearish research proxy never arms itself.

## Documentation map

| Purpose | Documents |
|---|---|
| Operating instructions | [Preparation](DAILY-PREPARATION.md), [record details](RECORD-PAGE.md), [selected-symbol scans](SCANNING.md), [replays/comparisons](REPLAY.md) |
| Method and policy | [Method](METHOD.md), [ignition](IGNITION.md), [trading decisions](TRADING-RULES.md), [traceability](TRACEABILITY.md) |
| Source evidence | [Source ledger](SOURCES.md), [source-version review](SOURCE-REVIEW.md), [video evidence](VIDEO-REVIEW.md), [examples](EXAMPLES.md), [public ledger audit](LEDGER-REVIEW.md), [industry evidence](INDUSTRY-DATA.md) |
| Developer work | [Work status/backlog](PLAN.md), [release handoff](RELEASE-HANDOFF.md), [September 12 release scope](RELIABILITY-RELEASE-2026-09-12.md) |
| Historical evidence | [September 12 deployment](DEPLOYMENT-2026-09-12.md), [weekend review](WEEKEND-REVIEW-2026-09-12.md), [original proposal](IMPLEMENTATION-PLAN-2026-09-12.md), [archived milestones](archive/PLAN-PRE-2026-09-13.md) |
| Proposal under review | [2026-09-17 Lane A package](reviews/2026-09-17-proposal/README.md): reconstructed bottlenecks (APA, QS, TTWO, PWR, APTV), gate map, rule matrix, proposal; read-only tool `zargar.tools.cartel_evidence` |
| Documentation changes | [Change record](DOCUMENTATION-CHANGES.md) |

The in-app Method library bundles selected Markdown chapters. A frontend rebuild is needed to display updated text. Git documentation updates do not themselves restart the app or change account settings.

## Collaboration and evidence boundaries

Follow root [AGENTS.md](../../../AGENTS.md) and [COLLABORATION.md](../../COLLABORATION.md). Preserve Claude worktrees and the shared runtime. Codex tests use only `zargar_test_codex`, sequentially. Never start a second engine against a runtime or test database. Keep other techniques' knowledge/rules separate.

No full public-feed coverage, exact author replication, broker-verified author return or profitable strategy has been established. Test success verifies the tested mechanics; source examples and replay R are not realized option P&L. Active plans, balances, versions and provider availability must be checked live when needed.

- [Intraday market research: accepted decision and limits](INTRADAY-RESEARCH-DECISION-2026-09-14.md)
  records the user-approved observation-only experiment. It does not change trading permission.

- [September 15 profitability review](PROFITABILITY-REVIEW-2026-09-15.md): cash-day accounting, 63 research cases, candidate/target selection and a prioritized prospective experiment queue. No execution settings changed.

- [Profitability research](PROFITABILITY-RESEARCH.md): prospective candidate/ranking,
  bearish, campaign-target and exit comparisons in Practice; operating instructions
  and promotion criteria. Actual trades remain in Daily review.

Current completion: [September 18 diagnostics and provider reconstruction](DIAGNOSTICS-2026-09-18.md).

Data repair: [Verified provider intervals](VERIFIED-INTERVALS.md).
