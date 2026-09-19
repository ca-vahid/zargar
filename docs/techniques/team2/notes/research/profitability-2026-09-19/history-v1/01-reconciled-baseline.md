# 1. Reconciled baseline: ACTUAL results only (runtime database, read-only, as of 2026-09-18 close)

Nothing on this page is replayed or modelled. Source: `executions`, `orders`, `portfolios`, `equity_points`.

## Cash reconciliation (starting cash + signed fills x 100 - commissions = `portfolios.cash`)

| Book | Start | Gross fills | Commissions | Computed cash | `portfolios.cash` | Difference |
|---|---|---|---|---|---|---|
| Team2 Practice (retired 2026-09-18, history kept) | 10,000.00 | -412.41 | 166.40 | 9,421.19 | 9,421.19 | 0.00 |
| Team2 Control | 10,000.00 | -180.70 | 145.60 | 9,673.70 | 9,673.70 | 0.00 |
| Team2 Sizing 0.5 | 10,000.00 | -106.41 | 85.28 | 9,808.31 | 9,808.31 | 0.00 |
| Team2 C1 Conjunction | 10,000.00 | -145.90 | 135.20 | 9,718.90 | 9,718.90 | 0.00 |

No open positions in any book. Commissions are $1.04 per contract per side ($0.99 + $0.05 regulatory).
**Commissions are 39% of the total loss across the four books ($532.48 of $1,377.90).**

## Every round trip

| Date | Book(s) | Contract | Qty | In (ET) | Price | Out (ET) | Price | Held | Exit | Gross | Fees | Net |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 09-08 | Practice | QQQ 714P | 14 | 10:02:08 | 0.655 | 10:04:00 | 0.61 | 2 min | stop | -63.00 | 29.12 | -92.12 |
| 09-08 | Practice | QQQ 714P | 9 | 10:06:01 | 0.63 | 10:08:00 | 0.68 | 2 min | target | +45.00 | 18.72 | +26.28 |
| 09-16 | Practice | QQQ 716C | 23 | 10:00:19 | 0.51 | 10:03:00 | 0.37 | 3 min | stop | -322.23 | 47.84 | -370.07 |
| 09-16 | Practice | QQQ 715C | 18 | 10:08:03 | 0.61 | 10:12:03 | 0.57 | 4 min | stop | -72.18 | 37.44 | -109.62 |
| 09-17 | Practice | QQQ 717C | 16 | 13:10:03 | 0.69 | 13:10:20 | 0.69 | 17 s | target == broken level (fixed in PR #204) | 0.00 | 33.28 | -33.28 |
| 09-18 | Control / C1 | IWM 283P | 40 | 10:12:03 | 0.49 | 10:20:03 | 0.46 | 8 min | stop | -120.40 | 83.20 | -203.60 |
| 09-18 | Sizing 0.5 | IWM 283P | 24 | 10:12:03 | 0.49 | 10:20:03 | 0.46 | 8 min | stop | -72.24 | 49.92 | -122.16 |
| 09-18 | Control | SPY 758P | 30 | 10:22:03 | 0.66 | 10:24:01 | 0.64 | 2 min | stop | -60.30 | 62.40 | -122.70 |
| 09-18 | Sizing 0.5 | SPY 758P | 17 | 10:22:03 | 0.66 | 10:24:01 | 0.64 | 2 min | stop | -34.17 | 35.36 | -69.53 |
| 09-18 | C1 | QQQ 714P | 25 | 10:46:17 | 0.41 | 10:48:02 | 0.40 | 2 min | stop | -25.50 | 52.00 | -77.50 |

Seven distinct market round trips (five in cohort v2, from 2026-09-11). One winner, six losers. Longest hold eight minutes.
On 2026-09-18 Control and Sizing took the SPY put and C1 did not (why C1 passed on it is not traced here); C1 later took a
QQQ put that Control and Sizing, already at two losses, were refused by the desk loss cap. The three books are not three independent samples: they are one day.

## Equity, drawdown, exposure (marked to market, `equity_points`)

| Book | High | Low | Last | Peak-to-trough | Time in the market |
|---|---|---|---|---|---|
| Team2 Practice | 10,398.44 | 9,421.19 | 9,421.19 | 977.25 | about 11 minutes over 5 round trips |
| Team2 Control | 10,498.40 | 9,570.20 | 9,673.70 | 928.20 | 10 minutes |
| Team2 Sizing 0.5 | 10,299.04 | 9,749.66 | 9,808.31 | 549.38 | 10 minutes |
| Team2 C1 Conjunction | 10,498.40 | 9,682.90 | 9,718.90 | 815.50 | 10 minutes |

Control's high of $10,498 is the IWM put marked up about $500 inside the trade on 2026-09-18 before it came back through the stop.
The experiment review level is -$800 from a high-water mark that is SAMPLED every 30 minutes. The sampler's stored record
(`techniques.team2.experiment_observation`, Sizing row read here) shows a high-water mark of $10,000.00: the eight-minute
intratrade peak fell between samples, so the review level did not fire. On continuous marks Control's peak-to-trough was $928,
beyond $800. This is the documented behaviour of a sampled trigger, not a defect, and it is an operational observation, not a
method result: a review level that depends on 30-minute samples cannot see an eight-minute trade.

## Coverage gaps and comparisons that are NOT supported

- One trading day for the three experiment books. No comparison between Control, Sizing and C1 is supported yet. The only valid
  statement is arithmetic: the half-size book lost less on the same two trades.
- Sessions 2026-09-09 to 09-15 produced no fills on Practice (refusals: no-trade zone, contract quotes, the 09-14/15 corrective batch).
  Cohort v2 therefore holds five round trips in six sessions.
- 2026-09-08 is before cohort v2 (different contract authority) and is listed for completeness only.
- Actual fills versus the real-print replay on the same dates agree on contract, minute and direction for the 09-16 and 09-18 trades
  (`harness/validate_proxy.py`, package README). That is the only bridge between this page and the replay, and it is a validation of
  the replay's pricing, not a result.
