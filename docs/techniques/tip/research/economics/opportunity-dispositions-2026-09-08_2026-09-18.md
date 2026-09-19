# Tips opportunity dispositions (opportunity-dispositions-v1) - ideas since 2026-09-08

Every ACTIONABLE idea (passed verification, or reached a proposal, plan or fill) has ONE disposition. An AVOIDABLE miss is one the desk caused by processing (failed analysis, expired approval, stale quote at submission, our own cancel) - a judgement, a risk boundary, or a level that never came is not.

| source | ideas | takes | filled | declined | risk-infeasible | late | analysis failed | approval expired | order unfilled | pending | avoidable |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| MK-alpha-trades | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 🌟｜ab | 22 | 10 | 6 | 10 | 2 | 0 | 2 | 0 | 2 | 0 | 2 |
| 🌟｜common-stock | 4 | 4 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 🌟｜eva | 83 | 1 | 1 | 82 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 🌟｜florida-man | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 🌟｜jon-and-kian | 9 | 4 | 2 | 5 | 1 | 0 | 0 | 0 | 1 | 0 | 0 |
| 🌟｜muggzone-options | 54 | 11 | 7 | 40 | 3 | 0 | 3 | 0 | 1 | 0 | 4 |
| 🌟｜neal | 3 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 🌟｜tt | 12 | 3 | 1 | 8 | 0 | 1 | 1 | 0 | 1 | 0 | 1 |
| **all** | 189 | 34 | 22 | 149 | 6 | 1 | 6 | 0 | 5 | 0 | 7 |

## Avoidable misses (7)

| signal at (UTC) | source | symbol | verdict | disposition | reason | evidence |
|---|---|---|---|---|---|---|
| 09-08 14:59 | 🌟｜muggzone-options |  | - | analysis_failed | no JSON object in analyst reply | run e70322e5 orders - |
| 09-08 15:05 | 🌟｜ab | APLD | - | analysis_failed | interrupted (restart/cancel) — reconciled at boot | run 54b5178a orders - |
| 09-08 16:40 | 🌟｜muggzone-options | ORCL260925C00200000 | - | analysis_failed | no JSON object in analyst reply | run dd912e72 orders - |
| 09-09 16:03 | 🌟｜tt | MU260918C01180000 | - | analysis_failed | no JSON object in analyst reply | run 89bb48a6 orders - |
| 09-10 14:52 | 🌟｜muggzone-options | AAPL260914C00330000 | take | order_unfilled:quote_age | quote age 10.5s (max 10s) | run 5bb50326 orders e1eb3304 |
| 09-11 17:27 | 🌟｜muggzone-options | RKLB260925C00070000 | - | analysis_failed | no JSON object in analyst reply | run abd015d4 orders - |
| 09-17 14:26 | 🌟｜ab | AMZN261120C00300000 | - | analysis_failed | appraisal failed | run 1e02b525 orders - |

Order-unfilled ideas that were NOT avoidable: 4 (2 armed plans whose level never came, 1 refused by a risk-gate price check).

An avoidable miss is an OPPORTUNITY, not a forgone profit: no outcome is assigned to a trade that never happened.

