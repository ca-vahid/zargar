# Current Cartel capabilities and limits

Updated 2026-09-15 for the profitability research release; deployment is recorded separately. The app-wide version can advance with other desks. Use live health, Armed and account reports for current state. Earlier deployment notes below are dated verification records.

The [September 13 corrections](READINESS-2026-09-13.md) add final-dispatch contract checks, target causality, pending invalidation protection, provider-compatible cache reuse, explicit legacy-arm review, a versioned Practice small-lot policy, quantity-correct replay, deduplicated quote/gap evidence and advisory leadership cohorts. See the release handoff for deployment and test evidence. Existing campaigns keep their snapshots; no profitability or Live acceptance claim follows from these corrections.

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
| Research | Underlying campaign replay, paired sweeps, recorded option-quote valuation, session decision report, prospective bounded candidate/ranking and exit studies | No unbiased universe walk-forward or demonstrated profitable option expectancy |

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


## EOD correction delivery — v0.7.74

Implemented: compatible partial-preparation recovery with bounded retries and immutable
baseline revisions; held-only identity handling; durable pending-attempt/expiry evidence;
actual provider metadata in history caches; exact simulated-fill evidence and freshness;
account-scoped EOD fill/fee/holdings review; durable quote coverage; deployment mutex and
Cartel inventory; asynchronous bar-publication/consumer/handler timing telemetry.

Limits: quote sampling cannot reconstruct unknown legacy fills. Publication/consumer timing
does not independently prove upstream venue receive latency. FISV remains a documented
provider-gap investigation: Yahoo omits November 12, 2025 while Alpaca raw provider-day
history contains it. Different volume/adjustment datasets are not spliced automatically.
Risk settings and saved campaigns were not migrated. Prospective cohort collection is still
required before changing strategy thresholds or claiming improved expectancy.

## Intraday research boundary

Implemented non-executing Practice observations of blocked-market shortlists. Frozen prior
completed daily EMAs are compared with completed 15-minute index candles. Hypothetical stock
confirmations have no contract, fill or profit claim and cannot be armed. See
[the accepted decision](INTRADAY-RESEARCH-DECISION-2026-09-14.md). Automatic reopening remains
unimplemented and unapproved; observations must be evaluated prospectively before proposing it.

## Profitability research release

Fresh Practice preparation freezes a separate bounded observation pool and both
structural-R and leader-first rankings. A separately identified structural-short
research cohort observes bearish conditions; it is not an exact reconstruction
of the author's March scanner. Selected contract observations and estimated
whole-unit affordability support target/campaign comparisons. Predefined
failed-break, time-cap and weak-environment exits use the same entry and initial
risk; the conditional shares comparison retains equal cash limits.

Validation has a dated research panel; Settings controls collection. The Method
library includes [the protocol](PROFITABILITY-RESEARCH.md). Old preparations are
not relabeled as prospectively observed. Stock paths remain proxies, and missing
quote/cost evidence cannot become option returns. No execution rule or automatic
Live permission is changed by these studies.
