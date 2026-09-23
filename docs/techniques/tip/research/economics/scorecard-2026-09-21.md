# Tips economic scorecard (tips-scorecard-v4) - 2026-09-21 .. 2026-09-21

Tips Practice book only in the trading columns; shadow research books are listed apart and never summed. Realized = FIFO lots after ALLOCATED fees (the census engine; fees counted once, inside realized). Model cost = list-price ESTIMATE from `llm.rates` - not an invoice.

**Accounting day, not the market close:** a session runs 04:00 ET to 04:00 ET (the desk's day anchor). Its MARK is the last persisted equity point inside that window - the actual timestamp is printed; it is normally hours after 16:00 ET and includes any after-hours quote drift. Model runs are assigned to the same window (`tip_llm_cost` uses the calendar day instead, so its daily totals differ by the 00:00-04:00 ET runs).

**Primary metric = marked change after model cost.** Realized after model cost is printed beside it; they differ whenever open positions are marked.

Interval baseline: 8,964.46 = the 2026-09-20 accounting-day mark (09-21 03:59).

| session | mark at (ET) | mark equity | MARKED change | method realized net | fees in it | questioned net | repairs | realized total | model cost (priced) | unpriced runs | partial runs | **MARKED after model cost (primary)** | realized after model cost |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-09-21 | 09-22 00:44 | 8,966.61 | +2.15 | +2.79 | 0.00 | +0.00 | +0.00 | +2.79 | 122.50 | 0 | 0 | **-120.35** | -119.71 |
| **cumulative** | 09-22 00:44 | 8,966.61 | **+2.15** | **+2.79** | 0.00 | +0.00 | +0.00 | +2.79 | **122.50** | 0 | 0 | **-120.35** | -119.71 |

Open positions at the last mark: market value minus cost +2,128.48 (lots still open: 6); this is why marked and realized differ.

## Reconciliation

- **Cash from executions vs persisted cash** at every session close: largest difference $0.00 (reconciles).
- **Equity identity:** not printed - this report starts after the book's inception, so lots opened before the interval are outside the ledger window. Run from the book's first session for the full identity.
- **Questioned fill** 2026-09-17 MRNA260918C00165000 (evidence-quality): kept on the ledger, graded apart - docs/techniques/tip/reviews/2026-09-17-mrna-quote-audit.md.
- **Questioned fill** 2026-09-14 APLD261016C00030000 (execution-realism): kept on the ledger, graded apart - docs/techniques/tip/reviews/2026-09-14-eod-response.md (EOD-05); Yahoo 1m prints APLD261016C00030000 2026-09-14.
- Unallocated sells not explained by a repair: 1 (see the census exceptions).

## Model operating cost by stage (cumulative, list-price estimate)

| stage | runs/requests | input tokens | output tokens | priced $ | stamped | run-record | rollup (partial) | unpriced runs | unpriced input | partial runs | unknown calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| intake-review | 134 | 17,171,780 | 272,967 | 92.68 | 134 | 0 | 0 | 0 | 0 | 0 | 0 |
| appraise | 25 | 3,701,489 | 72,658 | 20.32 | 25 | 0 | 0 | 0 | 0 | 0 | 0 |
| extraction | 160 | 921,154 | 89,224 | 6.84 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| retro | 5 | 430,735 | 12,688 | 2.47 | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| digest | 2 | 23,097 | 2,774 | 0.18 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |

Attribution basis: `stamped` = usage.model recorded by the loop; `run-record` = the run's own model field written by the loop that called the provider (journaled changes to techniques.tip.analyst_model in the record: 0); `rollup (partial)` = nightly stage counters for extraction/transcription, which have no run record and lose in-memory counts across restarts - a LOWER BOUND. Digest and rule-audit are desk overhead (no source).

## Priced model cost by source (appraise + retro + intake reviews)

| source | priced $ |
|---|---:|
| 🌟｜muggzone-options | 58.56 |
| 🌟｜ab | 22.30 |
| 🌟｜tt | 14.70 |
| 🌟｜eva | 8.00 |
| 🌟｜common-stock | 4.97 |
| 🌟｜neal | 4.64 |
| 🌟｜giul-heatseeker | 1.34 |
| 🌟｜jon-and-kian | 0.97 |

## Opportunity dispositions (every actionable idea has one; `tip_outcomes --dispositions` lists them)

27 actionable ideas, 8 analyst TAKES: filled 6, declined 19, risk_infeasible 2.

**Avoidable misses (the desk's own processing): 0** - none. An avoidable miss is an opportunity, never a forgone profit: no outcome is assigned to a trade that did not happen.

## Target exits: touch -> decision -> order -> fill (S21-03)

| symbol | rung | qty | target | first touch | decided | sent as | filled | fill | shortfall/unit | shortfall $ |
|---|---|---:|---:|---|---|---|---|---:|---:|---:|
| VKTX | TP1 30.6000 reached | 17.0 | 30.6 | 15:26 | 15:30:00 | MKT | 15:30:01 | 29.904 | 0.696 | 11.83 |

The manager decides on the CLOSED bar's high/low and sells at the bid it sees then; the shortfall is arithmetic between the touched target and the realised fill - it is not evidence that a resting limit at the target would have filled. The card's payoff scenarios assume an exit AT the target (stated on every card since S21-01).

## Friction and exposure of open positions (S21-04; a diagnostic of an immediate round trip, not a forecast)

| symbol | qty | debit | entry fees | exit fees est. | spread at quote (role) | all-in $ | all-in % | hold cap | same-underlying other lots (cost) |
|---|---:|---:|---:|---:|---|---:|---:|---|---|
| ACHR270115C00007000 | 3 | 144.0 | 3.12 | 3.12 | 3.0 (decision) | 9.24 | 6.4 | 25 | 1 ($70.00) |
| SBLK | 62 | 1978.42 | 0.0 | 0.0 | 1.24 (decision) | 1.24 | 0.1 | 15 | 0 ($0.00) |
| NFLX260925C00074000 | 1 | 62.0 | 1.04 | 1.04 | 2.0 (decision) | 4.08 | 6.6 | 3 | 0 ($0.00) |
| PL | 59 | 999.46 | 0.0 | 0.0 | 0.59 (decision) | 0.59 | 0.1 | 15 | 0 ($0.00) |
| IONQ | 28 | 1140.44 | 0.0 | 0.0 | 0.56 (decision) | 0.56 | 0.0 | 15 | 0 ($0.00) |
| CORZ261218C00025000 | 1 | 100.0 | 1.04 | 1.04 | 2.0 (decision) | 4.08 | 4.1 | 30 | 0 ($0.00) |
| ACHR260925C00005500 | 5 | 70.0 | 5.2 | 5.2 | 5.0 (decision) | 15.4 | 22.0 | 4 | 1 ($144.00) |
| VKTX | 50 | 1487.0 | 0.0 | 0.0 | 2.0 (decision) | 2.0 | 0.1 | 10 | 0 ($0.00) |

No friction threshold is applied; this is what the book pays to get in and out at the quoted market. Unknown inputs stay '?' (never estimated).

## Source x setup x entry style - FILLED Practice ideas (method results; questioned apart)

| source | setup | entry | filled ideas | completed | partial | net realized | fees | wins (avg) | losses (avg) | max drawdown | open at cost | questioned net |
|---|---|---|---:|---:|---:|---:|---:|---|---|---:|---:|---:|
| 🌟｜muggzone-options | 0-4dte | proposal-now | 1 | 0 | 0 | +0.00 | 0.00 | 0 | 0 | +0.00 | 62.00 | +0.00 |
| 🌟｜neal | shares | proposal-now | 2 | 0 | 0 | +0.00 | 0.00 | 0 | 0 | +0.00 | 2,139.90 | +0.00 |
| 🌟｜ab | 0-4dte | proposal-now | 1 | 0 | 0 | +0.00 | 0.00 | 0 | 0 | +0.00 | 70.00 | +0.00 |
| 🌟｜jon-and-kian | 30+dte | proposal-now | 1 | 0 | 0 | +0.00 | 0.00 | 0 | 0 | +0.00 | 100.00 | +0.00 |
| 🌟｜common-stock | shares | proposal-now | 1 | 0 | 1 | +2.79 | 0.00 | 0 | 0 | +0.00 | 981.42 | +0.00 |

No cohort above has enough completed ideas to claim an edge; the table ranks where money went, not what will work. Open exposure is at cost and is not credited to any cohort.

## Shadow research books (never summed with Practice; quarantined books excluded from any judgement)

| book | kind | quarantined | realized net (FIFO, research) | matched sells | open lots | unallocated sells |
|---|---|---|---:|---:|---:|---:|
| Shadow: 🌟｜ab | immediate |  | +0.00 | 0 | 2 | 0 |
| Shadow: 🌟｜ab (armed) | armed | YES | +0.00 | 0 | 1 | 1 |
| Shadow: 🌟｜common-stock | immediate |  | +0.00 | 0 | 1 | 0 |
| Shadow: 🌟｜common-stock (armed) | armed |  | +0.00 | 0 | 0 | 1 |
| Shadow: 🌟｜eva | immediate |  | +0.00 | 0 | 8 | 0 |
| Shadow: 🌟｜eva (armed) | armed | YES | +0.00 | 0 | 0 | 0 |
| Shadow: 🌟｜florida-man | immediate |  | +0.00 | 0 | 0 | 0 |
| Shadow: 🌟｜florida-man (armed) | armed |  | +0.00 | 0 | 0 | 0 |
| Shadow: flow-scan | immediate |  | +0.00 | 0 | 0 | 0 |
| Shadow: flow-scan (armed) | armed |  | +0.00 | 0 | 0 | 0 |
| Shadow: 🌟｜giul-heatseeker | immediate |  | +0.00 | 0 | 1 | 0 |
| Shadow: 🌟｜jon-and-kian | immediate |  | +0.00 | 0 | 1 | 0 |
| Shadow: 🌟｜jon-and-kian (armed) | armed |  | +0.00 | 0 | 0 | 0 |
| Shadow: MK-alpha-trades | immediate |  | +0.00 | 0 | 0 | 0 |
| Shadow: 🌟｜muggzone-options | immediate |  | +0.00 | 0 | 9 | 1 |
| Shadow: 🌟｜muggzone-options (armed) | armed |  | +0.00 | 0 | 0 | 0 |
| Shadow: 🌟｜neal | immediate |  | +0.00 | 0 | 2 | 0 |
| Shadow: 🌟｜neal (armed) | armed |  | +0.00 | 0 | 0 | 0 |
| Shadow: 🌟｜tt | immediate |  | +0.00 | 0 | 1 | 0 |
| Shadow: 🌟｜tt (armed) | armed |  | +0.00 | 0 | 0 | 0 |

Shadow books buy at tip time or at the level with research sizing and no fees model parity; their cash is not a portfolio. They inform source comparison only.

