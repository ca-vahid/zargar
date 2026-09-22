# Intake review context cost by component (since 2026-09-21; 135 captured reviews; read-only)

Characters per component of the EXACT request each review received (tokens ~ chars/4, an estimate). The rulebook and shared notes are supplied on every call of a review, so a multi-turn review pays them per turn. Priced at the Opus 5 input list rate $5.00/MTok - an estimate, not an invoice.

| component | avg chars | share of header | est. tokens per review | est. $ per review (per turn) |
|---|---:|---:|---:|---:|
| head | 354 | 0% | 89 | $0.000 |
| message | 168 | 0% | 42 | $0.000 |
| outcomes | 70 | 0% | 18 | $0.000 |
| rules | 53,098 | 68% | 13,275 | $0.066 |
| notes | 21,698 | 28% | 5,424 | $0.027 |
| history | 2,417 | 3% | 604 | $0.003 |

System prompt + schema: 2,347 chars per call (also per turn). Recorded usage: 428 calls, 17,297,011 input tokens across the 135 reviews (mean 128,126 per review, 3.2 turns).

## By useful action (what the review actually did)

| action | reviews | avg rules chars | avg notes chars | avg input tokens (recorded) | management tools |
|---|---:|---:|---:|---:|---|
| note only | 124 | 53,085 | 21,673 | 124,880 | - |
| management | 8 | 53,353 | 21,510 | 177,418 | [('disarm_plan', 5), ('update_exit_plan', 5), ('close_position', 1)] |
| possible entry flagged | 3 | 52,996 | 23,215 | 130,858 | - |

## By source

| source | reviews | avg header chars | avg rules | avg notes | avg history | management | note only | nothing |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 🌟｜muggzone-options | 72 | 77,458 | 53,244 | 21,959 | 1,749 | 4 | 68 | 0 |
| 🌟｜ab | 25 | 78,459 | 53,096 | 21,695 | 3,087 | 4 | 20 | 0 |
| 🌟｜tt | 20 | 80,639 | 52,591 | 22,750 | 4,630 | 0 | 18 | 0 |
| 🌟｜eva | 7 | 77,538 | 53,192 | 19,918 | 3,192 | 0 | 7 | 0 |
| 🌟｜common-stock | 7 | 72,724 | 52,826 | 18,402 | 889 | 0 | 7 | 0 |
| 🌟｜neal | 4 | 75,170 | 53,353 | 20,619 | 499 | 0 | 4 | 0 |

Reading: the rulebook and the notes are the same text on every review of every source; a compact treatment (fewer / pinned rules, notes scoped to the tickers in the message) is the comparison to prepare on these captured cases - measured against the FULL context on identical inputs, keeping mixed / correction / protective cases, before anything is changed. No note is deleted and no route is changed by this report.
