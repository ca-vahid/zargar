# 1. Corrected baseline: actual fills, and how far the pricing proxy can be trusted

Four kinds of number appear in this package and are never mixed:
**actual Practice fills** (this page, sections A to C), **real trade prints** (Alpaca option minute bars and ticks),
**simulated execution on real prints** (the replay), and **historical quotes** (none exist for options; nothing here uses one).

## A. Cash reconciliation (runtime database, read-only, close of 2026-09-18) — independently verifiable

`starting cash + signed fills x 100 - commissions = portfolios.cash`, to the cent, for all four books.

| Book | Start | Gross fills | Commissions | Computed | `portfolios.cash` | Difference |
|---|---|---|---|---|---|---|
| Team2 Practice (retired 2026-09-18) | 10,000.00 | -412.41 | 166.40 | 9,421.19 | 9,421.19 | 0.00 |
| Team2 Control | 10,000.00 | -180.70 | 145.60 | 9,673.70 | 9,673.70 | 0.00 |
| Team2 Sizing 0.5 | 10,000.00 | -106.41 | 85.28 | 9,808.31 | 9,808.31 | 0.00 |
| Team2 C1 Conjunction | 10,000.00 | -145.90 | 135.20 | 9,718.90 | 9,718.90 | 0.00 |

No open positions. Commissions are $1.04 per contract per side and are 39% of the four books' total loss ($532.48 of $1,377.90).

## B. Counting correctly

| Level | Count | What it is |
|---|---|---|
| Book fills | 22 | rows in `executions` |
| Market legs | 16 | one contract, side and second in the market; the 2026-09-18 IWM legs were filled in three books at once, the SPY legs in two |
| Market round trips | 8 | 09-08 x2, 09-16 x2, 09-17 x1, 09-18 x3 (the first package said seven: corrected) |
| Independent market opportunities (date x symbol) | 6 | 09-08 QQQ, 09-16 QQQ, 09-17 QQQ, 09-18 IWM, 09-18 SPY, 09-18 QQQ |
| Trading days with a fill | 4 | 09-08 is before cohort v2 (it started 2026-09-11); 09-16, 09-17 and 09-18 are cohort v2 |

Eight round trips on four days: one winner, seven non-winners (one flat before fees). This sample cannot estimate an expectancy.
The three experiment books share one trading day and mostly the same trades; **no comparison between Control, Sizing 0.5 and C1 is supported yet.**

| Date | Books | Contract | Qty (all books) | In ET | Price | Out ET | Price | Held |
|---|---|---|---|---|---|---|---|---|
| 09-08 | Practice | QQQ 714P | 14 | 10:02:08 | 0.655 | 10:04:00 | 0.61 | 2 min |
| 09-08 | Practice | QQQ 714P | 9 | 10:06:01 | 0.63 | 10:08:00 | 0.68 | 2 min |
| 09-16 | Practice | QQQ 716C | 23 | 10:00:19 | 0.51 | 10:03:00 | 0.3699 | 3 min |
| 09-16 | Practice | QQQ 715C | 18 | 10:08:03 | 0.61 | 10:12:03 | 0.5699 | 4 min |
| 09-17 | Practice | QQQ 717C | 16 | 13:10:03 | 0.69 | 13:10:20 | 0.69 | 17 s |
| 09-18 | Control, Sizing, C1 | IWM 283P | 40 + 24 + 40 | 10:12:03 | 0.49 | 10:20:03 | 0.4599 | 8 min |
| 09-18 | Control, Sizing | SPY 758P | 30 + 17 | 10:22:03 | 0.66 | 10:24:01 | 0.6399 | 2 min |
| 09-18 | C1 | QQQ 714P | 25 | 10:46:17 | 0.41 | 10:48:02 | 0.3998 | 2 min |

## C. Pricing-proxy validation against those fills (`harness/validate_proxy.py`, output `results/proxy_validation.json`)

The replay's execution proxy is "the open of the first option minute with a print at or after the decision time T" (T = the 2m
bar close that preceded the fill). 15 of the 16 market legs were bar-close decisions and all 15 have a print in the decision
minute (proxy lag 0). The sixteenth (09-17 exit, a quote-watch target sale 17 s after the entry) has no bar-close decision and is
not scored.

| Legs | n | Signed error (proxy - fill), mean | median | min | max | Absolute error, mean | max | Adverse to us, mean |
|---|---|---|---|---|---|---|---|---|
| All bar-close legs | 15 | +$0.0210 | +$0.0100 | -$0.040 | +$0.105 | $0.0277 | $0.105 | +$0.0116 |
| Entries (BUY) | 8 | +$0.0306 | +$0.0200 | -$0.010 | +$0.105 | $0.0331 | $0.105 | +$0.0306 (proxy pays MORE than we paid) |
| Exits (SELL) | 7 | +$0.0101 | +$0.0100 | -$0.040 | +$0.070 | $0.0215 | $0.070 | -$0.0101 (proxy sells HIGHER than we sold) |
| Cohort v2 legs only | 11 | +$0.0182 | +$0.0102 | -$0.040 | +$0.070 | $0.0273 | $0.070 | +$0.0072 |

Tick-level timing: the fills landed 0.4 to 19.6 s after T (one exit, 09-16 10:03:00, 60 s after). The nearest print before the fill
was 0.0 to 3.1 s earlier and within $0.01 of the fill on 11 of 16 legs (within $0.03 on 15); on 09-08 10:02 the tape printed 0.89 while we were filled at
0.655 (pre-v2 contract authority: the fill was priced on a delayed quote, a known and since-fixed defect).

What this supports and what it does not:

- The first package said "median error $0.00" and stopped. That hid an **average absolute error of about three cents per leg, five
  percent of a $0.56 premium**, with tails of seven to ten cents.
- The signed errors partly cancel over a round trip: the proxy is pessimistic on entries by about three cents and optimistic on exits
  by about one cent, a net pessimism near two cents per round trip, which is about 3.5% of the premium. **That bias estimate is the
  same size as the replay's measured mean loss per trade.** On this evidence the replay cannot distinguish "loses about 4% per trade"
  from "about break-even"; it can distinguish both from the +22% the pricing formula claimed.
- The sample is 15 legs from 6 opportunities on 4 days, all between 10:00 and 13:10 ET, all QQQ/IWM/SPY contracts near $0.40 to $0.70,
  all in September 2026. It says nothing about May to August, about thin late-day contracts, or about exits on fast target touches.
  **Historical execution fidelity is not established**; the replay is labelled "simulated execution on real prints" everywhere.
- Status: the cash reconciliation (A) can be checked independently with two SQL queries. The proxy table (C) is developer-reported;
  the script, its inputs (`harness/actual_fills.json`) and the cached ticks reproduce it.

## D. Marked equity and the experiment review levels (corrected interpretation)

The first package implied Control had passed an $800 review level without a pause. **That was wrong.** The experiment-specific
sampled review levels are: **Sizing 0.5: $800; C1: $1,000; Control: none** (Control keeps only the existing protections: the
per-entry budget check, the two-loss cap, the 10% technique day-loss pause and the 15% book breaker). The stored monitor record
(`techniques.team2.experiment_observation`) confirms it: `threshold` 800 for the sizing book, 1000 for C1, and no threshold on Control.

Three different series exist and must not be compared without reconciling them:

| Series | Cadence | Marking basis | 2026-09-18 extremes |
|---|---|---|---|
| `equity_points` (PositionKeeper) | every 30 s (measured: 84 points 10:10 to 10:52, max gap 30.5 s) | option marked at the MID when an ask exists; cash includes fees | Control high 10,498.40 (10:13:41, the 40 IWM puts marked 0.625), low 9,570.20; Sizing high 10,299.04, low 9,749.66; C1 high 10,498.40, low 9,682.90 |
| Experiment monitor (`experiment_watch`) | every 30 minutes | FRESH BID; cash includes fees; records missing marks | 16:00 record: Sizing drawdown 191.69 from a high-water mark of 10,000; C1 281.10 from 10,000 |
| Continuous extrema | not recorded anywhere | — | unknown |

- Peak-to-trough on the 30-second mid-marked series: Sizing $549, C1 $816, Control $928. Against their own levels: Sizing 549 < 800,
  C1 816 < 1,000. **No applicable experiment review level was reached on either basis.** Control's $928 is not comparable to any
  experiment level because it has none.
- The mid-marked high is not a bid-marked high: at the 10:13:41 point the 283 put was marked 0.625; a bid mark would be lower, so the
  monitor's basis would show a smaller peak and a smaller drawdown than the 30-second series.
- What remains true and was already documented in the sizing sheet: a review level sampled every 30 minutes can be exceeded between
  samples. On 2026-09-18 the whole intratrade swing (eight minutes) fell between two samples, so the monitor's high-water mark stayed
  at 10,000. That is the designed behaviour of a sampled trigger, not a missed pause.
