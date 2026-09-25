# Sharp-pencil review and plan - 2026-09-24

Requested by the user after EM's worst session: review the whole approach (trading, LLM use, knowledge base, intake,
operations), remove what is not earning its keep, and plan for maximum opportunity and profit. Built from three read-only
studies written the same evening:

- `docs/research/2026-09-24-PROFIT-MAP.md` - every book, every technique, every Tips source, FIFO from fills.
- `docs/research/2026-09-24-LLM-KNOWLEDGE-INTAKE-REVIEW.md` - models, cost per stage, knowledge base, intake funnel.
- `docs/research/2026-09-24-OPS-AUDIT.md` - scheduled tasks, memory, database, logs, data providers, leftovers.

Everything below is SIMULATED money unless it says live. **No live book has ever had an order or a fill through the app.**

## 1. The bottom line

1. **Nothing the app executes makes money yet.** Every Practice book is net negative: -8,560.33 across 130 closed trades,
   and no technique reaches a profit factor of 1.0.

   | Technique | Closed trades | Net after fees | Reading |
   |---|---:|---:|---|
   | Team2 | 32 | -4,435.30 | the largest leak; commissions 1,605.76 = 36% of it (about $50 a trade) |
   | Tips (Practice) | 33 | -2,510.66 | options -2,730.26 (26 trades); shares +219.60 (7) |
   | EM | 61 | -1,545.67 | profit factor 0.50 and falling; no edge in 9 sessions |
   | Options Cartel | 1 | -61.13 | not enough to judge |

2. **The only big profits are in Tips research books, and they come from two lucky expiries.** The "immediate" shadow books
   (buy at tip time, hold to expiry) show eva +122k, tt +41k, muggzone +40k. But META (09-21) and MU (09-04) alone
   produced +255k, every other expiry together lost -61k, and without its top 3 trades eva is -69k (median trade -1,515).
   The research books also have no cash limit. They are a hint, not a strategy.

3. **The clearest real lead is how Tips EXITS, not what it picks.** Tips Practice lost -880.06 on 10 positions held
   overnight and sold within 10 minutes of the next open (1 winner); its other 19 trades netted -31.63. The research books
   made their money by holding.

4. **LLM spend is under control now.** It is down about 80%, from $100-115 a weekday to $21.45 on 09-24 (Opus 5.5 at medium,
   caching, skipping non-actionable messages). EM makes zero automatic model calls. What is left is mostly waste inside each
   Tips review: the knowledge block is ~96% of every review's input and the message itself under 2%.

5. **Operations are close to the edge.** 0.6 GB of RAM free, the database pool ran dry for two minutes at 11:28 ET (the daily
   loss monitor failed in that window), 167 engine stalls today, CBOE polled all night (417 rate limits), and the free CBOE
   endpoint is still the only source of option chains.

## 2. Decided and done on 2026-09-22..24

| What | State |
|---|---|
| EM fully deterministic (no model on any automatic path) | live 0.8.37; paid review off |
| EM stop rule (20 sessions) + preregistered tests | running; 3 of 20 |
| Shares fallback | **OFF** (test decided: -0.52R vs options +0.05R); effective from the 09-25 evening arming |
| EM Experimental book | **RETIRED** 09-24: paused (`em-experiment-retired`), experiment disabled; history kept. It lost -1,035.75 on 17 trades (12% winners) and its bundle showed no value |
| Hourly/daily history from Alpaca; BRK.B on the stream | live 0.8.38 |
| Outcome scoring un-stuck | live 0.8.40 |
| CBOE opening-burst fixes; share sizing at the gate's price | live 0.8.47 |
| Tips cost package (caching, Opus 5.5, skip non-actionable, batch) | live 0.8.39..0.8.43 |
| Cleanup (EM-owned) | 14 one-off scripts/logs archived, EM backup tick removed, 2 worktrees, 9 merged branches, 2 test DBs |

## 3. The plan

Owners: **EM** = this desk (also carries shared-platform fixes), **Tips**, **Team2**, **Cartel**, **User** = your decision.
Order is by money at stake per unit of effort.

### P0 - protect what runs (this week, after the close)

| # | Action | Why | Owner |
|---|---|---|---|
| 0.1 | No test suites or research tools on the host during market hours; close idle agent sessions from 09-22 | 0.6 GB free; the engine is not the memory user (252 MB) | all desks |
| 0.2 | Split the database pool: money paths (loss monitor, journal, orders) get their own reserved connections; cap concurrent research jobs | the pool ran dry at 11:28 ET and the daily loss monitor failed | EM (platform) |
| 0.3 | Gate the options enrichment loop to market hours (plus a pre-open warm-up) | ~1,700 overnight skips, CBOE cooldown already hot at 06:00 PT | EM (platform) |
| 0.4 | Reuse one HTTP client in the 4 functions that create one per call | top cause of the 167 stalls | Cartel (3), Tips (1) |
| 0.5 | Research/replay tools stop writing `technique_runs` on the runtime DB | Cartel wrote ~17,000 runs (~1 GB) in three days; the table is 4.7 GB | Cartel |
| 0.6 | An Alpaca option-chain provider behind CBOE (the paid feed already serves OPRA quotes) | CBOE is a free, no-guarantee single point of failure for every option entry | EM (platform), User approves |

### P1 - where profit can actually come from

| # | Action | Evidence | Owner |
|---|---|---|---|
| 1.1 | **Preregister a Tips exit test: hold vs the next-open sale.** Same entries, exit policy compared (hold to the analyst's target / hold cap vs sell at the next open). The hold study (`holdstudy-v2`) already samples the data | the next-open sales lost -880.06 on 10 trades; the other 19 trades were flat | Tips |
| 1.2 | **Team2 costs before signals:** measure commission and spread per trade against the gross edge; test fewer, larger-conviction entries or cheaper contracts | $50 a trade in commissions = 36% of Team2's -4,435 | Team2 |
| 1.3 | **Tips sources: judge only on capped, realistic books.** Put a cash limit on the research books and report each source excluding its top 3 trades | eva is +122k with its top 3 and -69k without | Tips |
| 1.4 | **EM: no more development.** Let the stop rule run (17 sessions, $0 real cost); apply only the preregistered decisions as each test fills | profit factor 0.50 over 61 trades | EM |
| 1.5 | **Live money stays off** until one technique shows a positive, capped Practice record over its own preregistered sample | nothing is profitable in Practice yet | User |

### P2 - LLM, knowledge base and intake

| # | Action | Evidence | Owner |
|---|---|---|---|
| 2.1 | **Fix the note-scope bug** (`techniques/tip/analyst.py` `save_note`, ~line 979: a full scope like `source:<name>` is stored as `general`), then move the 135 misfiled notes back through the audited batch path | every review is handed other rooms' chatter; sources lose their own notes | Tips |
| 2.2 | **Serve notes by relevance, not only recency** | muggzone has 477 notes and a run sees the newest 4; 360 source notes never reached a run | Tips |
| 2.3 | **Settle the 29 pending rules in one sitting** (11 are refinements of one "adoption geometry" rule; 3 pairs pull against each other) and stop injecting unused rules | the rulebook is 55% of every review's input; none of the 37 rules has a recorded use | Tips + User |
| 2.4 | **Enforce the relevance gate and per-source review budgets** | 87% of paid reviews only saved notes; the gate would have skipped 78 reviews with no missed position management | Tips (decision) |
| 2.5 | **Cache the extraction system prompt (1-hour lifetime)** | extraction input has no caching; about $2 a day | Tips |
| 2.6 | Expected result of 2.1-2.5 | about $13-15 a weekday, from $21 | - |

### P3 - remove the leftovers (owners confirm, then delete)

| Item | Scale | Owner |
|---|---|---|
| Codex review worktrees older than 09-18 | 125 full checkouts | Codex reviewer |
| Abandoned worktrees: six `agent-*` kfin, `options-trading-research`, `settings-page-audit`, `day-trading-technique-pipeline` (one dirty file to check) | 9 | Tips / platform |
| Branches already merged into main | 210 local / 200 remote | each desk |
| Finished test databases (`_team2_v255`, `_kfin_a..f`, `_hubfix*`, `_hold142`, `_team2_f129`) | ~300 MB | owning desk |
| Log rotation (broken since 09-08) + the `persist_bars` noise line (80% of warnings) | 16 MB and growing | EM (platform) |
| Event-contract warnings (`TechniquePlanError.error`, `TechniqueSweepStarted.sweepId`) and the Yahoo `SPX` calendar 404 | noise that hides real warnings | EM / platform |

## 4. What not to do

- Do not retune any technique from its last few days. Every open question has a fixed sample; acting early is how a
  method gets fitted to last week.
- Do not read the Tips research books' six-figure totals as a strategy: two expiries made them, and they have no cash limit.
- Do not turn on live trading, or raise Practice risk limits, until P1.5 is met.
- Do not run heavy work on the host while the market is open.
