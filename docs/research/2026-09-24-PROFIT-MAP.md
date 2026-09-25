# Profit map - where Zargar makes and loses money (2026-09-24)

Read-only study of the runtime database (queried 2026-09-24 evening ET; last equity point 2026-09-25 02:36 UTC).
No model calls, no writes. All money below is SIMULATED except the live books section.

## Method

- Round trips = flat-to-flat position episodes per (book, symbol), FIFO-matched from `executions` (2,154 fills, all
  joined to `orders`). Options (OCC symbols / `sec_type=OPT`) use multiplier 100. Net = FIFO gross minus every
  commission in the episode. Expiry settlements (`orders.source='settle'`, 119 fills, price = intrinsic) close
  episodes like any exit. 325 closed episodes; 200 positions still open are excluded from trade stats (they show up in
  equity).
- Technique = the opening order's `orders.technique` (`source='signal'` = a Tips proposal fill -> `tip`).
- Tips source = `orders.tags` `source:<name>` > `orders.signal_id`/`proposal_id -> signals.source_name`; shadow
  books use `portfolios.source_name`. 1 Tips Practice trade (GOOGL261016C00360000, -27.18) has no traceable source.
- "Last 30 days" = closed 2026-08-25..2026-09-24. The first fill in the whole DB is 2026-08-17, so the 30-day window
  equals all-time for every book except `Practice (archived 2026-09-07)` (3 manual trades on 08-17).
- Win = net > 0. PF = sum of wins / |sum of losses|. `*` = fewer than 20 trades - NOT conclusive.
- Sanity check: for every sim book with no open positions, closed-trip net equals `equity - starting_cash` to the cent
  (EM Practice -682.84, Team2 Control -1,664.78, ...), so the FIFO matcher agrees with the engine's books.

## LIVE books (real money) - read first

**No live book has ever had an order or fill routed through the app** (0 rows in `orders`/`executions` for any
`kind='live'` portfolio). Live equity is broker-synced, `starting_cash` is 0 on all six, and the equity series mixes
deposits with market moves, so **live trading P&L is unknown** from this data.

| live book | equity now $ | first equity point | holdings (broker-synced) |
|---|---:|---|---|
| Webull (Cash) | 21,164.94 | 67.31 on 2026-08-20 | SPCX 60, MSFT.TO 98, AAPL.TO 89 |
| Wealthsimple Trade (Personal) (id c7134b99) | 4,708.15 | 0.00 on 2026-08-20 | TQQQ 41.9874 |
| Wealthsimple Trade (Personal) (id 2b821772), WS Corporate, Webull (Margin), Live (IBKR) | 0.00 | - | none |

## Headline findings

1. **Every Practice (sim) book is net negative. Total closed-trip net across sim books: -8,560.33 on 130 trades.**
   By technique: team2 -4,435.30 (32 trades), tip -2,510.66 (33), enhanced_market -1,545.67 (61), options_cartel
   -61.13 (1), manual -7.57 (3). No technique reaches PF 1.0; best is EM Practice PF 0.64 (43 trades).
2. **The only large positive numbers are in the Tips SHADOW "immediate" books (eva +122,354.23, tt +41,238.64,
   muggzone-options +40,206.72) - and they are two events, not an edge yet.** They come almost entirely from options
   held to expiry: settlement-closed trades across all shadow books net +194,021.97, of which expiries
   2026-09-21 (META rallied 680 -> 741.25 that day; 12 trades, +159,710.11) and 2026-09-04 (MU closed 1,016.59;
   11 trades, +95,630.46) = +255,340.57. **Every other expiry date together = -61,318.60.** eva excluding its top 3
   trades = -69,430.61 (median trade -1,514.94); muggzone ex-top-3 = -19,357.95; tt ex-top-3 = -11,155.34.
   Also: tt immediate, muggzone immediate + armed, eva armed, ab armed and common-stock armed are QUARANTINED
   (unallocated sells / runaway legs - see notes), and shadow books have no cash constraint (eva cash -23,574.77),
   so equity-minus-start is not a return on $10k.
3. **The same sources in the ARMED lane (wait for the level) are flat to negative**: eva armed -93.18 (25 trades,
   PF 0.88, shares only), tt armed -67.78 (2), jon-and-kian armed -99.68 (4). Only muggzone armed is positive
   (+3,604.48 on 6 trades, one expiry settlement = +3,568.74).
4. **Tips Practice (-911.68, 29 trades) - the whole loss is the "hold overnight, sell at the next open" exit**:
   10 trades that closed within 10 minutes of the next session's open net -880.06 (1 winner); the other 19 trades net
   -31.63. Tips Practice shares +219.60 (7 trades, PF 1.86) vs options -2,730.26 (26 trades, incl. the archived
   Practice book).
5. **Team2 is the biggest executed leak; commissions are 36% of its net loss**: gross -2,829.54, commissions
   1,605.76, net -4,435.30 on 32 option trades (15.6% win). Commissions per trade average 50.18 vs 367.58 avg win.
   Sizing 0.5 (-415.87, PF 0.76) lost least; C1 Conjunction 0 wins in 5.
6. **EM**: EM Practice -682.84 (43, PF 0.64), EM Experimental -1,035.75 (17, 11.8% win). Options -1,243.72 (37
   trades, -11.1% on premium); shares fallback -301.95 (24 trades, PF 0.38) - consistent with the 2026-09-24 decision
   to turn the shares fallback off.

## Where the money is (ranked by net; sample size in brackets)

| # | where | net $ | trades | conclusive? | note |
|---|---|---:|---:|---|---|
| 1 | Shadow eva - immediate (options held to expiry) | +122,354.23 | 65 | n>=20 but 2 expiries = the result; ex-top-3 -69,430.61 | research book, no cash limit |
| 2 | Shadow tt - immediate | +41,238.64 | 13 | no (<20), QUARANTINED | MU 09-04 = 2 of the 3 wins |
| 3 | Shadow muggzone-options - immediate | +40,206.72 | 47 | n>=20 but ex-top-3 -19,357.95; QUARANTINED | MU/HOOD/MRVL expiries |
| 4 | Shadow muggzone-options - armed | +3,604.48 | 6 | no, QUARANTINED | one settlement +3,568.74 |
| 5 | Tips Practice - shares | +219.60 | 7 | no | VKTX +295.80, IONQ +85.85 |
| 6 | Tips Practice source common-stock | +106.57 | 5 | no | |
| 7 | Tips Practice source muggzone-options | +95.81 | 9 | no | |
| 8 | Shadow neal - armed / immediate | +83.85 / +7.18 | 2 / 3 | no | |
| 9 | Shadow florida-man armed, giul-heatseeker immediate | +18.22 / +4.64 | 1 / 1 | no | |

Nothing that actually executes in a Practice book is net positive at >= 20 trades.

## Where the money leaks (ranked by loss)

| # | where | net $ | trades | conclusive? | note |
|---|---|---:|---:|---|---|
| 1 | Shadow ab - immediate | -7,141.51 | 7 | no | 6 of 7 went to expiry, 1 win |
| 2 | Team2 (all books) | -4,435.30 | 32 | yes | commissions 1,605.76; gross -2,829.54 |
| 3 | Tips options in Practice (both books) | -2,730.26 | 26 | yes | -20.1% of premium deployed |
| 4 | Shadow common-stock - armed | -2,651.33 | 7 | no, QUARANTINED | shares |
| 5 | Shadow flow-scan - immediate | -2,386.05 | 1 | no | one expiry at zero |
| 6 | Practice (archived 2026-09-07) | -1,887.65 | 10 | no | BBAI -828.00, GOOGL -811.60 |
| 7 | Team2 Control | -1,664.78 | 9 | no | |
| 8 | Shadow jon-and-kian - immediate | -1,455.85 | 3 | no | 0 wins |
| 9 | Team2 C1 Conjunction | -1,321.82 | 5 | no | 0 wins |
| 10 | EM Experimental | -1,035.75 | 17 | no | 2 wins |
| 11 | Shadow ab - armed | -1,076.29 | 8 | no, QUARANTINED | |
| 12 | Tips Practice source ab | -1,026.53 | 9 | no | |
| 13 | Tips Practice: overnight -> exit at next open | -880.06 | 10 | no (but 9 of 10 lost) | the entire Tips Practice loss |
| 14 | Tips Practice source jon-and-kian | -806.37 | 4 | no | |
| 15 | EM Practice | -682.84 | 43 | yes | PF 0.64 |
| 16 | Team2 Practice (archived) | -578.81 | 5 | no | |
| 17 | Tips Practice source florida-man | -505.08 | 1 | no | CCXI, sold at next open |
| 18 | Team2 Sizing 0.5 | -415.87 | 11 | no | least-bad Team2 variant |
| 19 | EM shares fallback | -301.95 | 24 | yes | PF 0.38 |

## Where the opportunity is (hypotheses, not verdicts)

- **Tips exit policy, not tip selection, is the testable gap.** The immediate shadow books (buy at tip time, hold
  the stated contract to expiry) captured the two big moves; Tips Practice never held any contract to expiry
  (0 of 29 settle-closed) and lost almost exactly its overnight-then-sell-at-open trades. The shadow result is two
  events and quarantined books, so the honest next step is a preregistered study of the exit rule
  (hold-to-expiry vs the analyst ladder vs no forced sale at the open), date-clustered, not a rule change.
- **Team2 cost floor**: commissions alone are 36% of the Team2 loss; any Team2 variant must clear ~$50/trade of fees
  before it can be positive.
- **Shares > options on the Tips Practice side** so far (+219.60 vs -2,730.26), tiny samples.
- **No live evidence at all**: the app has never traded real money; the first live tip is still an open gate.

## Data caveats

- 6 shadow books are quarantined (`portfolios.quarantine_note`): tt immediate, muggzone immediate + armed
  (ADV-02 unallocated sells / negative lots), eva armed (TSLA record vs venue), ab armed (APLD runaway, 3,282 exits,
  equity -85,613.61), common-stock armed. My FIFO skips nothing, so their numbers inherit those defects.
- Shadow books size ~$2-8k per tip against $10k starting cash with no cash limit (cash goes negative), so returns
  on $10k are meaningless; use per-trade or return-on-premium (eva immediate +77.6% on 157,698.79 deployed).
- Settlement fills are recorded at intrinsic value at 07:00 UTC the day after expiry; verified against the
  underlying closes for META 09-21 (741.25), MU 09-04 (1,016.59), MSTR 09-18 (153.92).
- 200 open positions (mostly shadow books) carry unrealized P&L that is in equity, not in trade stats.

## Tables

### sim books - ALL TIME

| book | kind/book | technique (episodes) | trades (* <20) | net P&L $ | commissions $ | win % | PF | avg win $ | avg loss $ | first close | last close |
|---|---|----|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| EM Experimental | sim/- | enhanced_market 17 | 17 * | -1,035.75 | 68.64 | 11.8% | 0.16 | 96.75 | -81.95 | 2026-09-22 | 2026-09-24 |
| EM Practice | sim/- | enhanced_market 43 | 43 | -682.84 | 126.88 | 27.9% | 0.64 | 100.12 | -60.78 | 2026-09-10 | 2026-09-24 |
| Options Cartel Practice (archived) | sim/- | options_cartel 1 | 1 * | -61.13 | 2.08 | 0.0% | 0.00 | 0.00 | -61.13 | 2026-09-14 | 2026-09-14 |
| Practice (archived 2026-09-07) (archived) | sim/- | tip 7, manual 3, team2 2, enhanced_market 1 | 10 * | -1,887.65 | 222.32 | 20.0% | 0.17 | 191.13 | -283.74 | 2026-08-17 | 2026-09-04 |
| Team2 C1 Conjunction | sim/- | team2 5 | 5 * | -1,321.82 | 359.84 | 0.0% | 0.00 | 0.00 | -264.36 | 2026-09-18 | 2026-09-22 |
| Team2 Control | sim/- | team2 9 | 9 * | -1,664.78 | 524.16 | 11.1% | 0.23 | 507.66 | -271.56 | 2026-09-18 | 2026-09-24 |
| Team2 Practice (archived) | sim/- | team2 5 | 5 * | -578.81 | 166.40 | 20.0% | 0.04 | 26.28 | -151.27 | 2026-09-08 | 2026-09-17 |
| Team2 Sizing 0.5 | sim/- | team2 11 | 11 * | -415.87 | 455.52 | 27.3% | 0.76 | 434.65 | -214.98 | 2026-09-18 | 2026-09-24 |
| Tips Practice | sim/- | tip 35 | 29 | -911.68 | 141.44 | 31.0% | 0.53 | 112.64 | -96.27 | 2026-09-08 | 2026-09-24 |

### sim books - LAST 30 DAYS (closed 2026-08-25..2026-09-24)

| book | trades (* <20) | net P&L $ | commissions $ | win % | PF | avg win $ | avg loss $ | first close | last close |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| EM Experimental | 17 * | -1,035.75 | 68.64 | 11.8% | 0.16 | 96.75 | -81.95 | 2026-09-22 | 2026-09-24 |
| EM Practice | 43 | -682.84 | 126.88 | 27.9% | 0.64 | 100.12 | -60.78 | 2026-09-10 | 2026-09-24 |
| Options Cartel Practice | 1 * | -61.13 | 2.08 | 0.0% | 0.00 | 0.00 | -61.13 | 2026-09-14 | 2026-09-14 |
| Practice (archived 2026-09-07) | 7 * | -1,880.08 | 216.32 | 28.6% | 0.17 | 191.13 | -452.47 | 2026-08-31 | 2026-09-04 |
| Team2 C1 Conjunction | 5 * | -1,321.82 | 359.84 | 0.0% | 0.00 | 0.00 | -264.36 | 2026-09-18 | 2026-09-22 |
| Team2 Control | 9 * | -1,664.78 | 524.16 | 11.1% | 0.23 | 507.66 | -271.56 | 2026-09-18 | 2026-09-24 |
| Team2 Practice | 5 * | -578.81 | 166.40 | 20.0% | 0.04 | 26.28 | -151.27 | 2026-09-08 | 2026-09-17 |
| Team2 Sizing 0.5 | 11 * | -415.87 | 455.52 | 27.3% | 0.76 | 434.65 | -214.98 | 2026-09-18 | 2026-09-24 |
| Tips Practice | 29 | -911.68 | 141.44 | 31.0% | 0.53 | 112.64 | -96.27 | 2026-09-08 | 2026-09-24 |

### shadow books - ALL TIME

| book | kind/book | technique (episodes) | trades (* <20) | net P&L $ | commissions $ | win % | PF | avg win $ | avg loss $ | first close | last close |
|---|---|----|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Shadow: MK-alpha-trades | shadow/immediate | tip 1 | 0 | - | - | - | - | - | - | - | - |
| Shadow: flow-scan | shadow/immediate | tip 1 | 1 * | -2,386.05 | 15.60 | 0.0% | 0.00 | 0.00 | -2,386.05 | 2026-09-01 | 2026-09-01 |
| Shadow: 🌟｜ab | shadow/immediate | tip 35 | 7 * | -7,141.51 | 53.04 | 28.6% | 0.11 | 454.86 | -1,610.25 | 2026-09-03 | 2026-09-24 |
| Shadow: 🌟｜ab (armed) (QUARANTINED) | shadow/armed | tip 14 | 8 * | -1,076.29 | 0.00 | 37.5% | 0.02 | 6.48 | -219.15 | 2026-09-08 | 2026-09-24 |
| Shadow: 🌟｜common-stock | shadow/immediate | tip 11 | 0 | - | - | - | - | - | - | - | - |
| Shadow: 🌟｜common-stock (armed) (QUARANTINED) | shadow/armed | tip 8 | 7 * | -2,651.33 | 0.00 | 14.3% | 0.01 | 17.27 | -444.77 | 2026-09-04 | 2026-09-24 |
| Shadow: 🌟｜eva | shadow/immediate | tip 129 | 65 | 122,354.23 | 737.36 | 21.5% | 2.06 | 16,986.46 | -2,263.85 | 2026-09-03 | 2026-09-24 |
| Shadow: 🌟｜eva (armed) (QUARANTINED) | shadow/armed | tip 32 | 25 | -93.18 | 2.00 | 36.0% | 0.88 | 79.65 | -50.63 | 2026-08-31 | 2026-09-15 |
| Shadow: 🌟｜florida-man | shadow/immediate | tip 1 | 0 | - | - | - | - | - | - | - | - |
| Shadow: 🌟｜florida-man (armed) | shadow/armed | tip 1 | 1 * | 18.22 | 0.00 | 100.0% | inf | 18.22 | 0.00 | 2026-09-09 | 2026-09-09 |
| Shadow: 🌟｜giul-heatseeker | shadow/immediate | tip 4 | 1 * | 4.64 | 0.00 | 100.0% | inf | 4.64 | 0.00 | 2026-09-09 | 2026-09-09 |
| Shadow: 🌟｜jon-and-kian | shadow/immediate | tip 15 | 3 * | -1,455.85 | 45.76 | 0.0% | 0.00 | 0.00 | -485.28 | 2026-09-12 | 2026-09-22 |
| Shadow: 🌟｜jon-and-kian (armed) | shadow/armed | tip 4 | 4 * | -99.68 | 0.00 | 0.0% | 0.00 | 0.00 | -24.92 | 2026-09-03 | 2026-09-24 |
| Shadow: 🌟｜muggzone-options (QUARANTINED) | shadow/immediate | tip 81, bracket 2 | 47 | 40,206.72 | 431.56 | 25.5% | 1.78 | 7,624.75 | -1,465.44 | 2026-09-03 | 2026-09-24 |
| Shadow: 🌟｜muggzone-options (armed) (QUARANTINED) | shadow/armed | tip 7 | 6 * | 3,604.48 | 21.84 | 83.3% | 269.78 | 723.58 | -13.41 | 2026-09-03 | 2026-09-17 |
| Shadow: 🌟｜neal | shadow/immediate | tip 10 | 3 * | 7.18 | 0.00 | 33.3% | 1.09 | 88.36 | -40.59 | 2026-09-18 | 2026-09-24 |
| Shadow: 🌟｜neal (armed) | shadow/armed | tip 3 | 2 * | 83.85 | 0.00 | 50.0% | 14.14 | 90.23 | -6.38 | 2026-09-08 | 2026-09-23 |
| Shadow: 🌟｜tt (QUARANTINED) | shadow/immediate | tip 25 | 13 * | 41,238.64 | 150.80 | 38.5% | 3.70 | 11,304.97 | -1,910.78 | 2026-09-04 | 2026-09-22 |
| Shadow: 🌟｜tt (armed) | shadow/armed | tip 2 | 2 * | -67.78 | 0.00 | 0.0% | 0.00 | 0.00 | -33.89 | 2026-09-03 | 2026-09-11 |

### shadow books - LAST 30 DAYS (closed 2026-08-25..2026-09-24)

| book | trades (* <20) | net P&L $ | commissions $ | win % | PF | avg win $ | avg loss $ | first close | last close |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Shadow: flow-scan | 1 * | -2,386.05 | 15.60 | 0.0% | 0.00 | 0.00 | -2,386.05 | 2026-09-01 | 2026-09-01 |
| Shadow: 🌟｜ab | 7 * | -7,141.51 | 53.04 | 28.6% | 0.11 | 454.86 | -1,610.25 | 2026-09-03 | 2026-09-24 |
| Shadow: 🌟｜ab (armed) | 8 * | -1,076.29 | 0.00 | 37.5% | 0.02 | 6.48 | -219.15 | 2026-09-08 | 2026-09-24 |
| Shadow: 🌟｜common-stock (armed) | 7 * | -2,651.33 | 0.00 | 14.3% | 0.01 | 17.27 | -444.77 | 2026-09-04 | 2026-09-24 |
| Shadow: 🌟｜eva | 65 | 122,354.23 | 737.36 | 21.5% | 2.06 | 16,986.46 | -2,263.85 | 2026-09-03 | 2026-09-24 |
| Shadow: 🌟｜eva (armed) | 25 | -93.18 | 2.00 | 36.0% | 0.88 | 79.65 | -50.63 | 2026-08-31 | 2026-09-15 |
| Shadow: 🌟｜florida-man (armed) | 1 * | 18.22 | 0.00 | 100.0% | inf | 18.22 | 0.00 | 2026-09-09 | 2026-09-09 |
| Shadow: 🌟｜giul-heatseeker | 1 * | 4.64 | 0.00 | 100.0% | inf | 4.64 | 0.00 | 2026-09-09 | 2026-09-09 |
| Shadow: 🌟｜jon-and-kian | 3 * | -1,455.85 | 45.76 | 0.0% | 0.00 | 0.00 | -485.28 | 2026-09-12 | 2026-09-22 |
| Shadow: 🌟｜jon-and-kian (armed) | 4 * | -99.68 | 0.00 | 0.0% | 0.00 | 0.00 | -24.92 | 2026-09-03 | 2026-09-24 |
| Shadow: 🌟｜muggzone-options | 47 | 40,206.72 | 431.56 | 25.5% | 1.78 | 7,624.75 | -1,465.44 | 2026-09-03 | 2026-09-24 |
| Shadow: 🌟｜muggzone-options (armed) | 6 * | 3,604.48 | 21.84 | 83.3% | 269.78 | 723.58 | -13.41 | 2026-09-03 | 2026-09-17 |
| Shadow: 🌟｜neal | 3 * | 7.18 | 0.00 | 33.3% | 1.09 | 88.36 | -40.59 | 2026-09-18 | 2026-09-24 |
| Shadow: 🌟｜neal (armed) | 2 * | 83.85 | 0.00 | 50.0% | 14.14 | 90.23 | -6.38 | 2026-09-08 | 2026-09-23 |
| Shadow: 🌟｜tt | 13 * | 41,238.64 | 150.80 | 38.5% | 3.70 | 11,304.97 | -1,910.78 | 2026-09-04 | 2026-09-22 |
| Shadow: 🌟｜tt (armed) | 2 * | -67.78 | 0.00 | 0.0% | 0.00 | 0.00 | -33.89 | 2026-09-03 | 2026-09-11 |

### By technique - sim (Practice) books only, all time

| technique | trades (* <20) | net P&L $ | commissions $ | win % | PF | avg win $ | avg loss $ | first close | last close |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| manual | 3 * | -7.57 | 6.00 | 0.0% | 0.00 | 0.00 | -2.52 | 2026-08-17 | 2026-08-17 |
| options_cartel | 1 * | -61.13 | 2.08 | 0.0% | 0.00 | 0.00 | -61.13 | 2026-09-14 | 2026-09-14 |
| enhanced_market | 61 | -1,545.67 | 197.60 | 24.6% | 0.50 | 104.53 | -67.69 | 2026-09-01 | 2026-09-24 |
| tip | 33 | -2,510.66 | 255.84 | 30.3% | 0.33 | 122.31 | -162.34 | 2026-08-31 | 2026-09-24 |
| team2 | 32 | -4,435.30 | 1,605.76 | 15.6% | 0.29 | 367.58 | -232.34 | 2026-09-04 | 2026-09-24 |

### By technique x book - sim books

| technique / book | trades (* <20) | net P&L $ | commissions $ | win % | PF | avg win $ | avg loss $ | first close | last close |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| enhanced_market / EM Experimental | 17 * | -1,035.75 | 68.64 | 11.8% | 0.16 | 96.75 | -81.95 | 2026-09-22 | 2026-09-24 |
| enhanced_market / EM Practice | 43 | -682.84 | 126.88 | 27.9% | 0.64 | 100.12 | -60.78 | 2026-09-10 | 2026-09-24 |
| enhanced_market / Practice (archived 2026-09-07) | 1 * | 172.92 | 2.08 | 100.0% | inf | 172.92 | 0.00 | 2026-09-01 | 2026-09-01 |
| manual / Practice (archived 2026-09-07) | 3 * | -7.57 | 6.00 | 0.0% | 0.00 | 0.00 | -2.52 | 2026-08-17 | 2026-08-17 |
| options_cartel / Options Cartel Practice | 1 * | -61.13 | 2.08 | 0.0% | 0.00 | 0.00 | -61.13 | 2026-09-14 | 2026-09-14 |
| team2 / Practice (archived 2026-09-07) | 2 * | -454.02 | 99.84 | 0.0% | 0.00 | 0.00 | -227.01 | 2026-09-04 | 2026-09-04 |
| team2 / Team2 C1 Conjunction | 5 * | -1,321.82 | 359.84 | 0.0% | 0.00 | 0.00 | -264.36 | 2026-09-18 | 2026-09-22 |
| team2 / Team2 Control | 9 * | -1,664.78 | 524.16 | 11.1% | 0.23 | 507.66 | -271.56 | 2026-09-18 | 2026-09-24 |
| team2 / Team2 Practice | 5 * | -578.81 | 166.40 | 20.0% | 0.04 | 26.28 | -151.27 | 2026-09-08 | 2026-09-17 |
| team2 / Team2 Sizing 0.5 | 11 * | -415.87 | 455.52 | 27.3% | 0.76 | 434.65 | -214.98 | 2026-09-18 | 2026-09-24 |
| tip / Practice (archived 2026-09-07) | 4 * | -1,598.98 | 114.40 | 25.0% | 0.12 | 209.34 | -602.77 | 2026-08-31 | 2026-09-04 |
| tip / Tips Practice | 29 | -911.68 | 141.44 | 31.0% | 0.53 | 112.64 | -96.27 | 2026-09-08 | 2026-09-24 |

### By instrument - sim books

| technique / instrument | trades (* <20) | net P&L $ | commissions $ | win % | PF | avg win $ | avg loss $ | first close | last close |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| enhanced_market / options | 37 | -1,243.72 | 197.60 | 27.0% | 0.53 | 137.98 | -97.17 | 2026-09-01 | 2026-09-24 |
| enhanced_market / shares | 24 | -301.95 | 0.00 | 20.8% | 0.38 | 37.62 | -25.79 | 2026-09-14 | 2026-09-24 |
| manual / shares | 3 * | -7.57 | 6.00 | 0.0% | 0.00 | 0.00 | -2.52 | 2026-08-17 | 2026-08-17 |
| options_cartel / options | 1 * | -61.13 | 2.08 | 0.0% | 0.00 | 0.00 | -61.13 | 2026-09-14 | 2026-09-14 |
| team2 / options | 32 | -4,435.30 | 1,605.76 | 15.6% | 0.29 | 367.58 | -232.34 | 2026-09-04 | 2026-09-24 |
| tip / options | 26 | -2,730.26 | 255.84 | 26.9% | 0.21 | 106.77 | -183.03 | 2026-08-31 | 2026-09-24 |
| tip / shares | 7 * | 219.60 | 0.00 | 42.9% | 1.86 | 158.59 | -64.04 | 2026-09-15 | 2026-09-24 |

### Tips by SOURCE - sim (Practice) books, all time

| source (attribution) | trades (* <20) | net P&L $ | commissions $ | win % | PF | avg win $ | avg loss $ | first close | last close |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 🌟｜common-stock (signal 5) | 5 * | 106.57 | 6.24 | 40.0% | 1.38 | 194.95 | -94.45 | 2026-09-10 | 2026-09-23 |
| 🌟｜muggzone-options (signal 9) | 9 * | 95.81 | 47.84 | 33.3% | 1.34 | 124.73 | -46.39 | 2026-08-31 | 2026-09-22 |
| 🌟｜neal (signal 2) | 2 * | -7.02 | 0.00 | 50.0% | 0.92 | 85.85 | -92.87 | 2026-09-23 | 2026-09-24 |
| unknown (None 1) | 1 * | -27.18 | 2.08 | 0.0% | 0.00 | 0.00 | -27.18 | 2026-09-16 | 2026-09-16 |
| flow-scan (signal 1) | 1 * | -168.72 | 8.32 | 0.0% | 0.00 | 0.00 | -168.72 | 2026-08-31 | 2026-08-31 |
| 🌟｜eva (signal 1) | 1 * | -172.14 | 2.08 | 0.0% | 0.00 | 0.00 | -172.14 | 2026-09-09 | 2026-09-09 |
| 🌟｜florida-man (signal 1) | 1 * | -505.08 | 24.96 | 0.0% | 0.00 | 0.00 | -505.08 | 2026-09-09 | 2026-09-09 |
| 🌟｜jon-and-kian (signal 4) | 4 * | -806.37 | 85.28 | 25.0% | 0.11 | 102.84 | -303.07 | 2026-09-04 | 2026-09-22 |
| 🌟｜ab (signal 9) | 9 * | -1,026.53 | 79.04 | 33.3% | 0.21 | 90.12 | -216.15 | 2026-09-02 | 2026-09-24 |

### Shadow research books by source: immediate vs armed (closed round trips, all time)

| source | book | trades | net $ | win % | PF | open positions | equity now | start | equity - start |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MK-alpha-trades | immediate | 0 * | 0.00 | 0.0% | - | 1 | 9,532.60 | 10,000.00 | -467.40 |
| flow-scan | armed | 0 * | 0.00 | 0.0% | - | 0 | 10,000.00 | 10,000.00 | 0.00 |
| flow-scan | immediate | 1 * | -2,386.05 | 0.0% | 0.00 | 0 | 7,613.95 | 10,000.00 | -2,386.05 |
| 🌟｜ab | armed (Q) | 8 * | -1,076.29 | 37.5% | 0.02 | 6 | -85,613.61 | 10,000.00 | -95,613.61 |
| 🌟｜ab | immediate | 7 * | -7,141.51 | 28.6% | 0.11 | 28 | 4,431.47 | 10,000.00 | -5,568.53 |
| 🌟｜common-stock | armed (Q) | 7 * | -2,651.33 | 14.3% | 0.01 | 1 | 7,159.55 | 10,000.00 | -2,840.45 |
| 🌟｜common-stock | immediate | 0 * | 0.00 | 0.0% | - | 11 | 8,879.11 | 10,000.00 | -1,120.89 |
| 🌟｜eva | armed (Q) | 25 | -93.18 | 36.0% | 0.88 | 7 | 8,003.91 | 10,000.00 | -1,996.09 |
| 🌟｜eva | immediate | 65 | 122,354.23 | 21.5% | 2.06 | 64 | 245,310.57 | 10,000.00 | 235,310.57 |
| 🌟｜florida-man | armed | 1 * | 18.22 | 100.0% | inf | 0 | 10,018.23 | 10,000.00 | 18.23 |
| 🌟｜florida-man | immediate | 0 * | 0.00 | 0.0% | - | 1 | 8,598.75 | 10,000.00 | -1,401.25 |
| 🌟｜giul-heatseeker | immediate | 1 * | 4.64 | 100.0% | inf | 3 | 10,153.25 | 10,000.00 | 153.25 |
| 🌟｜jon-and-kian | armed | 4 * | -99.68 | 0.0% | 0.00 | 0 | 9,900.32 | 10,000.00 | -99.68 |
| 🌟｜jon-and-kian | immediate | 3 * | -1,455.85 | 0.0% | 0.00 | 12 | 9,442.49 | 10,000.00 | -557.51 |
| 🌟｜muggzone-options | armed (Q) | 6 * | 3,604.48 | 83.3% | 269.78 | 1 | 13,573.61 | 10,000.00 | 3,573.61 |
| 🌟｜muggzone-options | immediate (Q) | 47 | 40,206.72 | 25.5% | 1.78 | 36 | 36,271.66 | 10,000.00 | 26,271.66 |
| 🌟｜neal | armed | 2 * | 83.85 | 50.0% | 14.14 | 1 | 10,202.41 | 10,000.00 | 202.41 |
| 🌟｜neal | immediate | 3 * | 7.18 | 33.3% | 1.09 | 7 | 14,232.57 | 10,000.00 | 4,232.57 |
| 🌟｜tt | armed | 2 * | -67.78 | 0.0% | 0.00 | 0 | 9,932.22 | 10,000.00 | -67.78 |
| 🌟｜tt | immediate (Q) | 13 * | 41,238.64 | 38.5% | 3.70 | 12 | 56,530.23 | 10,000.00 | 46,530.23 |

### Equity vs starting cash (sim + live)

| book | kind | archived | start $ | cash $ | equity now $ | equity - start $ | closed-trip net $ | open positions |
|---|---|---|---:|---:|---:|---:|---:|---:|
| Live (IBKR) | live | False | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0 |
| Wealthsimple Trade (Corporate) | live | False | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0 |
| Wealthsimple Trade (Personal) | live | False | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0 |
| Wealthsimple Trade (Personal) | live | False | 0.00 | 41.79 | 4,708.15 | 4,708.15 | 0.00 | 0 |
| Webull (Cash) | live | False | 0.00 | 989.72 | 21,164.94 | 21,164.94 | 0.00 | 0 |
| Webull (Margin) | live | False | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0 |
| EM Experimental | sim | False | 9,849.60 | 8,813.86 | 8,813.86 | -1,035.75 | -1,035.75 | 0 |
| EM Practice | sim | False | 10,000.00 | 9,317.16 | 9,317.16 | -682.84 | -682.84 | 0 |
| Options Cartel Practice | sim | True | 10,000.00 | 9,938.87 | 9,938.87 | -61.13 | -61.13 | 0 |
| Options Cartel Practice - Capital Experiment | sim | True | 1,000,000.00 | 1,000,000.00 | 1,000,000.00 | 0.00 | 0.00 | 0 |
| Options Cartel Practice 10k | sim | False | 10,000.00 | 10,000.00 | 10,000.00 | 0.00 | 0.00 | 0 |
| Practice (archived 2026-09-07) | sim | True | 10,000.00 | -5,020.52 | 11,062.10 | 1,062.10 | -1,887.65 | 3 |
| Team2 C1 Conjunction | sim | False | 10,000.00 | 8,678.18 | 8,678.18 | -1,321.82 | -1,321.82 | 0 |
| Team2 Control | sim | False | 10,000.00 | 8,335.22 | 8,335.22 | -1,664.78 | -1,664.78 | 0 |
| Team2 Practice | sim | True | 10,000.00 | 9,421.19 | 9,421.19 | -578.81 | -578.81 | 0 |
| Team2 Sizing 0.5 | sim | False | 10,000.00 | 9,584.13 | 9,584.13 | -415.87 | -415.87 | 0 |
| Tips Practice | sim | False | 10,000.00 | 4,460.65 | 9,148.55 | -851.45 | -911.68 | 6 |

### Open positions (not in round-trip stats), sim books

- Practice (archived 2026-09-07): RKLB261016C00070000 qty 13 (tip, src 🌟｜jon-and-kian), partial realized 0.00
- Practice (archived 2026-09-07): ZURA qty 702 (tip, src 🌟｜common-stock), partial realized 0.00
- Practice (archived 2026-09-07): SOFI qty 236 (tip, src 🌟｜common-stock), partial realized 0.00
- Tips Practice: ACHR270115C00007000 qty 3 (tip, src 🌟｜ab), partial realized 0.00
- Tips Practice: PL qty 59 (tip, src 🌟｜neal), partial realized 0.00
- Tips Practice: ACHR261016C00006000 qty 5 (tip, src 🌟｜ab), partial realized 0.00
- Tips Practice: CRWV qty 8 (tip, src 🌟｜neal), partial realized 14.45
- Tips Practice: JELD qty 369 (tip, src 🌟｜common-stock), partial realized 0.00
- Tips Practice: COIN qty 10 (tip, src 🌟｜ab), partial realized 0.00

