# Current Cartel capabilities and limits

Reviewed September 16, 2026 against the integrated source tree. This is a capability
summary, not a statement that a particular build is running. Verify health/build,
served frontend and the deployment receipt for operational status.

| Area | Implemented | Remaining limits |
|---|---|---|
| Preparation | Broad discovery, daily benchmark freshness, industry context, ranked candidates, contract reserves, separate Practice/Live policies | Provider coverage can block or delay a run; partial results may still have valid arms |
| Accounts and permission | Dedicated Practice routing, explicit Live account/acknowledgements and live-auto permission, shared pre-trade guards | A saved plan or research observation is not order permission |
| History and recovery | Provider-keyed durable cache, incremental reads, 20-session minute baselines, bounded interrupted/partial recovery | Adjustment identity, corporate-action gaps and verified no-trade intervals need further evidence |
| Observation | Source-bearing minute tape, future-session-aware gap warnings, bounded context repair and prospective cutoffs | Zero missing timestamps does not imply exchange-quality candles; recovery does not recreate live observation |
| Entry and management | Closed-bar entries, final contract checks, write-ahead submission, partial-fill protection, durable exits and restoration | Small quantities cannot execute every percentage trim; Live acceptance is venue/configuration-specific |
| Actual daily results | Account/session order and execution ledger, fees, inventory reconciliation and quote coverage | Unknown historical marks/fill evidence stay unknown; FX translation is outside technique price P&L |
| Manual research | Underlying replay, paired entry variants and recorded-premium valuation | Selected-plan hindsight comparisons are not an unbiased universe walk-forward |
| Prospective research | Frozen bounded full pool, structural-R/leader ranking, primary direction plus optional structural-short proxy, target/exit/shares studies | Funding estimates reserve no capital; no portfolio-wide competition model or proved option expectancy |
| Research scheduling | Never-attempted due baselines first, then least-attempted/oldest-due retries; persisted across restart | Fair scheduling cannot create absent provider history; collection may remain incomplete |
| Ignition | Research stages and separately selectable long-side Practice pilot | Fixed engineering thresholds need calibration; richer catalyst/thesis modeling remains open |

## Distinct research paths

The older **Intraday market research** panel observes market-blocked long shortlists.
The broader **Profitability research** panel in Validation records the bounded pool
and economics comparisons, including a primary short pool when preparation chose
that direction. A zero additional bearish-proxy count can therefore coexist with
many short candidates. Both are non-executing; neither changes an arm's permission.

Definitions and user instructions: [profitability protocol](PROFITABILITY-RESEARCH.md),
[intraday decision](INTRADAY-RESEARCH-DECISION-2026-09-14.md),
[preparation guide](DAILY-PREPARATION.md), [replay and daily review](REPLAY.md).

## Current evidence gaps

- Full immutable provider revision history and exact reconstruction of every legacy decision input.
- Consistent source-qualified coverage for all observation-pool members, including illiquid names.
- Prospective net option outcomes, concentration/capital competition and a later holdout period.
- Source-example calibration and broker-specific Live acceptance; no automatic strategy graduation.

Historical checks and deployments stay in dated evidence records, including
[September 13 readiness](READINESS-2026-09-13.md) and
[September 15 research release](PROFITABILITY-RELEASE-2026-09-15.md).
Their test totals and balances are not current system-wide claims. See
[the current work plan](PLAN.md) for priorities.
