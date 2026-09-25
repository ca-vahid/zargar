# Options Cartel: current guide

Updated 2026-09-22 (release 0.8.33). Technique id: `options_cartel`. Source author: Sean Trades
(`@SRxTrades`); the app's numerical interpretations and Practice experiments are ours and are labelled as
such. No profitable strategy or exact author replication has been established.

## State of play (2026-09-22)

- **Book.** Since 2026-09-23 22:10 ET Practice runs on `Options Cartel Practice 10k` (`297d8b39…`, $10,000;
  $1,000 per plan, contracts up to $10, 10 focus slots). The $1m capital-experiment book (09-19..09-23, no
  trades) and the older $10k book are archived with their history.
- **Results.** Zero orders on 2026-09-21 and 2026-09-22. Across 24 automatic plan-days since 09-14, 11
  touched their trigger and none reached an order. One trade since 09-14 (APA, -$61.13). The binding
  problem is trade flow, not position management.
- **What changed in 0.8.29-0.8.33.** Versioned contract search (`diverse_liquidity_v1`, on in Practice),
  cost ranking (`executable_cost_v2` built, Practice runs `legacy` after v1 drifted to deep
  in-the-money contracts), causal daily-review attribution, the 5-minute entry pilot with a 15-minute
  matched control, gap-open retest, non-increasing dry-up rule, first-target arm gate, research panels
  under a 5m pilot and receipt-time lab quotes. New switches default to legacy behaviour; activation order
  is in the [2026-09-22 plan](reviews/2026-09-22-plan/PLAN.md).
- **2026-09-23.** Yahoo's daily series omitted 09-22, so preparation waited for the benchmark all day and
  nothing armed. Since 20:26 ET Practice reads the shared Alpaca-first daily path (`nativeDailyBatch=false`)
  and runs `executable_cost_v2`, `gap_policy=retest_v1` and `dry_up_rule=non_increasing_v1`; the arm gate and
  5m cadence stay off. Record: [plan section 7](reviews/2026-09-22-plan/PLAN.md).
- **2026-09-24 (0.8.50).** The $10k Practice book (`297d8b39…`) is the only Cartel book. Order-free research
  collectors (method lab, profitability, intraday, ignition) are off. An entry-grid replay over 98 candidate-days
  found no entry variant worth activating (65/98 never touched the trigger; the 5m pilot and lower volume
  multiples add losing signals), so the entry rule stays. Next levers are a minute-liquidity screen, wider
  candidate supply and the first-target arm gate: [2026-09-24 plan](reviews/2026-09-24-sharp-pencil/PLAN.md).
- **Known limits.** Untrusted confirmation windows are caused by no-trade minutes at the end of a
  bucket, before a non-emission proof can exist (design decision open). Sean's daily posts cannot be
  retrieved automatically (X returns 402). Shares fallback (brief F6) and historical data repair (F7)
  are not built.

## Start here

1. [Daily preparation](DAILY-PREPARATION.md): account routing, every setting and switch, preparation,
   recovery and arming.
2. [Current capabilities and limits](DELIVERY-STATUS.md): what is shipped versus open.
3. [2026-09-22 improvement plan](reviews/2026-09-22-plan/PLAN.md): funnel evidence, switches, activation
   order and rollback. The [September 21 brief](IMPLEMENTATION-BRIEF-2026-09-21.md) is the specification it
   implements (F1-F4 plus the plan items; F5-F8 partly open).
4. [2026-09-24 sharp-pencil plan](reviews/2026-09-24-sharp-pencil/PLAN.md): what was removed, the entry-grid
   verdict, the ordered Cartel plan and cross-desk LLM/knowledge findings.
5. [Trading decisions log](TRADING-RULES.md): every method decision with its date and evidence.

In the app: Plans for preparation, Armed for monitored campaigns, History/Validation for research,
Method for the bundled chapters. An armed plan is not a filled position; entries still pass closed-bar,
data, contract, quote, cash/risk and execution checks.

## Reading status correctly

- **Armed** means waiting for a valid entry. **Waiting for benchmark** means the provider has not
  supplied the completed SPY/QQQ session; it is not a market judgment.
- **Daily review** reports actual orders, executions and fees, and names the first known blocker per
  plan; incomplete windows stay unknown. **Validation -> Profitability research** is hypothetical.
- A **short** setup trades a put, never short shares. The bearish research proxy never arms itself.

## Documentation map

| Purpose | Documents |
|---|---|
| Operating | [Preparation](DAILY-PREPARATION.md), [record page](RECORD-PAGE.md), [scans](SCANNING.md), [replay](REPLAY.md), [dedicated book](DEDICATED-BOOK.md), [capital experiment](CAPITAL-EXPERIMENT-2026-09-19.md) |
| Method and policy | [Method](METHOD.md), [ignition](IGNITION.md), [trading decisions](TRADING-RULES.md), [traceability](TRACEABILITY.md), [execution acceptance](EXECUTION-ACCEPTANCE.md) |
| Research | [Profitability research](PROFITABILITY-RESEARCH.md), [method lab](METHOD-LAB.md) and its [source matrix](METHOD-LAB-SOURCE-MATRIX.md), [intraday decision](INTRADAY-RESEARCH-DECISION-2026-09-14.md), [Sept 15 review](PROFITABILITY-REVIEW-2026-09-15.md) |
| Data | [Verified provider intervals](VERIFIED-INTERVALS.md), [Sept 18 diagnostics](DIAGNOSTICS-2026-09-18.md), [preparation performance](PREPARATION-PERFORMANCE.md) |
| Source evidence | [Sources](SOURCES.md), [source versions](SOURCE-REVIEW.md), [videos](VIDEO-REVIEW.md), [examples](EXAMPLES.md), [public ledger](LEDGER-REVIEW.md), [industry data](INDUSTRY-DATA.md), [related sources](RELATED-SOURCES.md) |
| Development | [Work status](PLAN.md), [release handoff](RELEASE-HANDOFF.md), [regression notes](REGRESSION-NOTES.md), reviews in [reviews/](reviews/) |
| History | Dated deployment, readiness, weekend and one-off action records: [archive/2026-09/](archive/2026-09/README.md); pre-2026-09-13 records: [archive/](archive/) |
| Change record | [Documentation changes](DOCUMENTATION-CHANGES.md) |

## Collaboration and evidence boundaries

Follow root [AGENTS.md](../../../AGENTS.md) and [COLLABORATION.md](../../COLLABORATION.md). Each desk tests
on its own database (this desk: `zargar_test_cartel`; Codex: `zargar_test_codex`). Never start a second
engine against a runtime or test database. Test success verifies the tested mechanics; source examples
and replay R are not realized option P&L. Versions, balances and active plans must be checked live.
