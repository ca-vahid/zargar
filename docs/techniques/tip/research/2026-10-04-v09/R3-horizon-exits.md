# R3. Tips desk: trade horizon and exits, from our own record

Read-only study run on 2026-10-04 against the runtime DB. Bars run through **2026-10-02**. Nothing was written to the DB.

- **Scripts:** `fetch_bars.py` (export) and `r3.py` (analysis) in this folder.
- **Raw output:** `data/r3_output.txt` (full tables, about 570 lines).
- **Row-level data:** `data/r3_rows.json`.

## Bottom line (read this first)

1. **We cannot answer "months".** The longest path in the data is 18 sessions. Only 100 tip entries have 20 sessions after them. All horizon claims below stop at about 2-4 weeks.
2. **Same-day exits earn nothing.** Exiting at the first close is about 0R in every cohort:
   - tip longs: -0.02R (n=312)
   - desk entries: +0.04 to +0.10R
   - shorts: -0.07R

   Median MFE by the first close is only +0.19R. Don't plan shares trades as intraday.
3. **Winners take a week or more.** Among tip longs that reached at least +1R within 10 sessions (n=192):
   - the median peak came in **session 7**
   - 79 of the 192 peaked in sessions 9-10, i.e. were still running when the window closed
   - by session 3 the median winner had reached only 43% of its 10-session MFE; by session 5, 78%

   Median MFE in R grows steadily with time: +0.19 at 1 session, +0.52 at 3, +0.83 at 5, +1.19 at 10, +1.78 at 20. MAE grows more slowly: -0.19, -0.47, -0.59, -0.79, -0.82.
4. **Holding longer did not pay on average, because the stop takes most trades out first.** With the original stop, the mean result is roughly flat whatever the time stop (tip longs, 10+ sessions of data):

   | time stop | mean R |
   |---|---:|
   | 1 session | -0.02 |
   | 3 sessions | +0.09 |
   | 5 sessions | +0.14 |
   | 10 sessions | +0.08 |
   | 20 sessions | +0.27 |

   **Ticker-clustered, all of these are about 0** (-0.18 to +0.02). The positive means come from a few tickers that were tipped again and again (eva map names, MU, MRNA).

   **There is no robust "best horizon" edge in the tip flow.** The one robust lever is how the stop is placed (point 5).
5. **The most consistent finding is wider stops with smaller size, at equal $ risk.** A stop at 3×ATR14 with a 10-session cap beat the original stop with the same cap in every cohort, including the SPY control:

   | cohort | original stop | 3×ATR stop |
   |---|---:|---:|
   | desk | -0.17R (worst decile -1.67) | **+0.13R** (worst decile -0.92) |
   | tip longs | +0.08R | **+0.18R** (date-clustered CI **+0.09..+0.26**) |
   | tip shorts | -0.65R | -0.22R |
   | SPY at the same timestamps | -0.86R | -0.20R |

   The desk's initial stops are a median **1.15×ATR** (p25 0.82×ATR), so they sit inside daily noise. 21-29% of stop-outs later reached +1R within 10 sessions.
6. **Short tips lost money under every exit policy** (-0.22 to -0.85R mean, n=67 with 10+ sessions; ticker and date CIs are mostly below 0). Exits cannot fix the direction.
7. **Trails at about 1×ATR let runs go too early.** On the desk's trailed and target exits:
   - median capture was 48-60% of the MFE during the hold
   - the post-exit 10-session high was a mean **+7.0R above entry for trailed stops** (MRNA +8.9, VKTX +10.0, GOOGL +37.8) and +2.6R for targets

   On tip runs that reached at least +2R (n=132, mean MFE +4.9R), share of the MFE kept, by policy:

   | policy | share of MFE kept |
   |---|---:|
   | 3×ATR chandelier | 51% (+1.32R) |
   | 2×ATR | 46% |
   | breakeven at 1R | 35% |
   | 1.5×ATR | 26% |

## Data and method

- **DESK cohort.** All 52 Tips managed positions in both Practice books (old `4611946d`: 37 closed + 1 open; new `88aa8a26`: 10 closed + 4 open). The path is the **underlying** from the fill, with **R = `config.risk`**, the distance from entry to the initial stop on the underlying.
  - **Actual R:** shares = realized $ / (risk × qty); options = realized $ / `riskPlan.plannedRisk`. Options without a risk plan get no actual R.
- **SIG cohort.** This is the shares lane of the immediate shadow books: buy (or short) the **underlying** at the next 15m bar open after intake. A tip arriving outside regular hours enters at the next open.
  - One row per (source, ticker, direction, entry session): 564 rows, 469 long and 95 short.
  - Stop provenance: 1.5×ATR14 for 493 rows (most), the analyst's `underlying_stop` for 58, the tip's own stop for 13.
  - Sources: eva 265 rows (dominant), muggzone 133, ab 40, tt 27, neal 26, jon-and-kian 24, others ≤17.
- **Bars.** 15m RTH bars are aggregated from 1m. When a session has no 1m bars, its daily bar is used, with the stop assumed to be hit first. 348 of 7,348 sessions used daily bars and 534 had no bars at all.
- **Simulation rules:**
  - Stops fill at the stop price, or at the open on a gap through.
  - When a stop and a target fall inside the same bar, the stop is taken first.
  - Costs are 5 bp per side.
  - R is measured on **each policy's own stop**, so every policy carries equal $ risk.
  - $ = R × $100 (1% of $10k).
- **No options were re-priced.** No Black-Scholes was used. Options rows are judged on their underlying path only.
- **Clustering.** Bootstrap CIs resample entry dates. "Ticker-clustered" means averaging per ticker first, then across tickers. Because many tips repeat the same names, **the ticker-clustered number is the honest one**.
- **Beta context.** SPY bought at the same timestamps returned -0.07% / -0.08% / +0.19% / -0.27% at 1 / 5 / 10 / 20 sessions. Tip underlyings returned +0.08% / +0.94% / +2.95% / +5.67%. The tape was flat, so the tip-long drift is idiosyncratic, but it is concentrated in a few repeatedly-tipped names.

## Q1. Price path after entry

| cohort | horizon (sessions) | n | median MFE R / % | median MAE R / % | share MFE ≥1R | share MAE ≤-1R |
|---|---:|---:|---|---|---:|---:|
| DESK, all | 1 | 52 | +0.17 / +0.7% | -0.13 / -0.6% | 6% | 2% |
| | 3 | 49 | +0.54 / +2.7% | -0.55 / -2.1% | 31% | 16% |
| | 5 | 44 | +0.66 / +3.9% | -0.71 / -3.7% | 39% | 41% |
| | 10 | 28 | +1.39 / +7.1% | -1.09 / -5.6% | 54% | 54% |
| SIG longs | 1 | 469 | +0.19 / +0.8% | -0.19 / -0.9% | 5% | 3% |
| | 2 | 454 | +0.40 / +2.0% | -0.33 / -1.7% | 15% | 11% |
| | 3 | 443 | +0.52 / +2.7% | -0.47 / -2.3% | 23% | 19% |
| | 5 | 410 | +0.83 / +4.2% | -0.59 / -2.9% | 43% | 30% |
| | 10 | 313 | +1.19 / +6.9% | -0.79 / -4.0% | 61% | 39% |
| | 20 | 100 | +1.78 / +8.1% | -0.82 / -4.4% | 70% | 43% |
| SIG shorts | 5 | 86 | +0.50 / +1.8% | -0.94 / -3.4% | 27% | 47% |
| | 10 | 67 | +0.74 / +2.5% | -1.34 / -6.0% | 33% | 67% |

**Peak session of winners** (MFE ≥1R within 10 sessions):

| cohort | n | median peak session | notes |
|---|---:|---|---|
| SIG longs | 192 | S7 | 79 peaked in S9-S10, i.e. censored and still running |
| DESK | 15 | S7 | |
| SIG shorts | 22 | S4.5 | they peak and reverse within about a week |

**DESK actual exits by class** (closed positions, underlying R):

| exit class | n | $ net | mean actual R | MFE during hold | exit R (underlying) | median capture | post-exit 10-session high |
|---|---:|---:|---:|---:|---:|---:|---:|
| premium stop/bleed | 12 | -1,027 | -0.33 | +0.34 | -0.17 | n/m | +1.07 |
| initial stop | 11 | -831 | -0.73 | +0.26 | -0.84 | n/m | +0.64 |
| trailed stop (≥ entry) | 10 | **+770** | +1.18 | +2.48 | +1.35 | **48%** | **+6.97** |
| source/analyst exit | 6 | +22 | +0.11 | +0.80 | +0.21 | 28% | +1.14 |
| target | 5 | +242 | +0.67 | +1.03 | +0.62 | 60% | +2.62 |
| time/stale/DTE | 2 | +35 | +0.21 | +0.78 | +0.49 | 65% | +0.98 |

- **Trailed stops carried the book.** They are the only class that both captured MFE and had MFE to capture.
- **Losers never got going.** Initial-stop losers had a mean MFE of only +0.26R before stopping. Few of them were "winners that turned".
- **Actual hold vs plan.** The desk held a median of **2 sessions**, against a median analyst `max_hold_sessions` of **10**; 40 of 45 positions exited before their stated hold. **Our record is mostly 1-3 session holds, because stops and trails end trades long before the plan's horizon.**

## Q2. Alternative exit policies on the same entries

### SIG longs with at least 10 sessions of data

n=313; 66 entry dates; 94 tickers.

| policy | mean R | date-clustered 95% CI | ticker-clustered | median | hit | worst decile | total $ | sessions held |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| time 1 + stop | -0.02 | -0.09..+0.06 | -0.01 | -0.04 | 42% | -0.76 | -603 | 1.0 |
| time 3 + stop | +0.09 | -0.16..+0.34 | +0.02 | +0.06 | 51% | -1.24 | +2,849 | 2.9 |
| time 5 + stop | +0.14 | -0.12..+0.43 | -0.04 | +0.13 | 55% | -1.42 | +4,247 | 4.4 |
| time 10 + stop | +0.08 | -0.12..+0.28 | -0.18 | -0.32 | 41% | -1.47 | +2,479 | 7.7 |
| time 20 + stop | +0.27 | +0.03..+0.56 | -0.06 | -0.18 | 47% | -1.48 | +8,556 | 11.3 |
| hold 20, no stop | +1.02 | +0.54..+1.63 | +0.10 | +0.55 | 64% | **-2.49** | +32,081 | 16.5 |
| chandelier 1.5 ATR | +0.11 | -0.11..+0.35 | | -0.12 | 44% | -1.26 | +3,398 | 6.3 |
| chandelier 2 ATR | +0.17 | -0.04..+0.39 | -0.00 | -0.34 | 38% | -1.41 | +5,312 | 8.2 |
| chandelier 3 ATR | +0.24 | +0.01..+0.49 | -0.00 | -0.21 | 44% | -1.46 | +7,545 | 10.2 |
| trail 5% | +0.18 | +0.02..+0.35 | **+0.15** | -0.14 | 45% | -1.29 | +5,726 | 5.6 |
| trail 8% | +0.03 | -0.17..+0.26 | | -0.33 | 37% | -1.45 | +1,057 | 7.8 |
| breakeven at 1R, time 10 | +0.11 | -0.08..+0.32 | -0.10 | -0.06 | 35% | -1.41 | +3,573 | 7.2 |
| target 1R, time 5 | +0.18 | -0.05..+0.43 | +0.09 | +0.38 | **60%** | -1.34 | +5,651 | 3.6 |
| 1/2 at 1R + breakeven, time 10 | +0.14 | -0.06..+0.35 | -0.02 | +0.43 | 57% | -1.38 | +4,361 | 7.2 |
| 1/3 at 1R + breakeven + 2ATR trail | +0.19 | -0.01..+0.41 | +0.01 | +0.29 | 57% | -1.40 | +5,800 | 8.6 |
| 1/3 at 1R + breakeven + 2ATR trail, time 5 | +0.17 | -0.08..+0.44 | +0.05 | +0.31 | 60% | -1.34 | +5,322 | 4.3 |
| **stop 3×ATR, time 10 (smaller size)** | **+0.18** | **+0.09..+0.26** | +0.01 | +0.09 | 56% | **-0.96** | +5,504 | 9.6 |
| stop 2×ATR close-based, brake 1.5R, time 10 | +0.22 | +0.06..+0.36 | -0.04 | +0.08 | 53% | -1.32 | +6,753 | 9.3 |
| SPY control: stop 3×ATR, time 10 | -0.20 | -0.51..+0.11 | | | | | | |
| SPY control: time 10 + stop | -0.86 | | | | | | | |

### DESK entries

The desk's own entries and stops, simulated as shares on the underlying; n=52, or 28 with at least 10 sessions. The "capped" column limits each trade at +5R, because GOOGL 09-16 had a 0.63 stop on a 340 stock.

| policy (desk, 10+ sessions) | mean R | capped | median | CI | worst decile |
|---|---:|---:|---:|---|---:|
| time 1 + stop | +0.10 | +0.10 | -0.04 | -0.12..+0.52 | -0.60 |
| time 3 + stop | +0.82 | **+0.39** | -0.19 | -0.17..+2.23 | -1.05 |
| time 5 + stop | +0.71 | +0.29 | -0.25 | -0.35..+2.53 | -1.27 |
| time 10 + stop | -0.17 | -0.26 | -1.01 | -0.73..+0.58 | -1.67 |
| chandelier 2 ATR (n=22) | +0.91 | +0.45 | -0.38 | -0.36..+3.03 | -1.63 |
| 1/3 at 1R + breakeven + 2ATR trail (n=22) | +0.66 | +0.43 | -0.39 | | -1.63 |
| stop 3×ATR, time 10 (n=22) | +0.13 | +0.13 | +0.10 | -0.10..+0.39 | **-0.92** |

- **Desk actual result:** mean actual R +0.12 over 47 closed trades; shares only +0.25R (n=23). New-book shares (n=13, at most 5 sessions) are about 0R under every policy. The new book is too young to rank policies.
- **Desk with tight stops:** the 2-5 session time stops and the 2×ATR chandelier look best, but only through a few large runs (VKTX, MRNA, GOOGL). Their medians are negative and their CIs span 0.

### By group

Read the following with n=10-20 per group.

- **Source** (tip longs, 10+ sessions):
  - **neal** is positive at every horizon. It improves out to 20 sessions (+0.93R), and the 3ATR trail after 1R gave +0.98R (n=14).
  - **ab** is negative at nearly every horizon (n=20).
  - **muggzone** is about 0 up to 5 sessions and positive only beyond 10 sessions (+0.27R at 20).
  - eva's 142 rows carry the cohort mean.
- **Stated instrument:** tips that named **shares** did best (+0.5 to +1.0R from 3 sessions on, n=22). **Call** tips sit around +0.1 to +0.3R.
- **The tip's own timeframe label doesn't predict:** "swing" tips were -0.07R at 10 sessions vs "day_trade" +0.12R.
- **Analyst verdict:** "take" rows were **worse** than "skip" rows at every horizon (-0.26 vs +0.16R at time 10, n=32 vs 171). This matches A-outcomes finding 7.

## Q3. Can we predict the horizon at entry?

**The analyst's stated hold doesn't predict.** Only 37 tip rows with 10+ sessions carry `max_hold_sessions`. No bucket shows a pattern, and every bucket has n≤11. On the desk, max_hold 0-2 averaged +0.56R (n=4), 3-8 averaged -0.14R (n=13) and 9+ averaged -0.03R (n=18), with holds of 1.5 / 2.0 / 3.7 sessions. The stated hold isn't what ends trades.

**Some observable features help, on tip longs with 10+ sessions.** For each entry the table shows mean R at a time stop of 1 / 3 / 5 / 10 sessions, with ticker-clustered values in brackets and the date-clustered CI at 10 sessions:

| feature at entry | n | 1 | 3 | 5 | 10 | CI at 10 |
|---|---:|---:|---:|---:|---:|---|
| **entry ≤ -2% vs prior close** (tip on a down day) | 31 (22 tickers) | +0.02 | +0.18 | +0.39 (+0.42) | **+0.55 (+0.58)** | -0.15..+1.05 |
| **entry ≥ +2% vs prior close** (chasing) | 101 (56 tickers) | +0.05 | +0.11 | +0.05 (-0.07) | **-0.10 (-0.23)** | -0.37..+0.23 |
| gap ≥ +2% at the open | 82 | +0.04 / +0.05 | | | -0.28 / -0.25 | |
| ATR < 2.5% of price | 67 (13 tickers) | -0.11 | -0.09 | -0.16 | **-0.40** (-0.11) | -0.68..-0.11 |
| ATR > 6% of price | 61 (30 tickers) | 0.00 | +0.17 | +0.32 | +0.43 (-0.08) | -0.11..+1.06 |
| tip arrived outside RTH (entry next open) | 135 (48 tickers) | -0.01 | +0.16 | +0.25 | +0.29 (+0.11) | -0.02..+0.59 |
| tip arrived in RTH | 177 (80 tickers) | -0.02 | +0.04 | +0.05 | -0.08 (-0.21) | -0.30..+0.14 |
| prior-day relative volume > 3 | 7 | | | | negative | |
| catalyst / earnings field set | 48 | -0.08 | -0.00 | -0.01 | -0.23 | |

For the gap row, the two figures at 1 and at 10 sessions are the two gap buckets: +2..+5% and above +5%.

- **Same-day relative volume** to entry showed no pattern.
- **Distance to MA20** showed no monotone pattern.
- **MA50** could not be computed: there is too little daily history for most names.

**Simple encodable horizon rule.** Low confidence: none of the CIs excludes 0 except low-ATR at 10 sessions. Apply at entry, longs only:

| class | trigger (observable at entry) | time cap | exit |
|---|---|---|---|
| **H-short (2-3 sessions)** | entry ≥ +2% above prior close **or** gap ≥ +2% **or** catalyst/earnings set **or** ATR < 2.5% | 3 sessions | take 1/2 at +1R, stop to breakeven, flat at the 3rd close |
| **H-swing (5-10 sessions)**, the default | everything else | 10 sessions; the stale rule (5 sessions below +0.5R → exit) stays | 1/3 at +1R, breakeven, trail the rest at 3×ATR |
| **H-extended (10-20 sessions)** | entry ≤ -2% below prior close, **or** an H-swing position at ≥ +2R by session 5, **or** a source with a positive long-horizon record (today only neal) | 20 sessions | 3×ATR chandelier only after +1R, no fixed final target |
| Intraday | none (no evidence) | n/a | do not plan same-day shares exits |
| Months | not testable (≤ 18 sessions of data) | n/a | don't plan for it |

## Q4. Stop-outs: noise or right?

Simulated on the original stop with a 20-session hold:

| cohort | stop-outs | later reached +1R within 10 sessions (noise) | went on to -2R without recovering (right) | neither | stopped in session 1 |
|---|---:|---:|---:|---:|---:|
| DESK | 24 of 52 | 5 (21%) | 10 (42%) | 9 | 1 |
| SIG longs | 174 of 469 | 51 (29%) | 40 (23%) | 83 | 14 |
| SIG shorts | 60 of 95 | 5 (8%) | 22 (37%) | 33 | 1 |

**At equal $ risk, wider stops win**, comparing a 10-session hold:

| cohort | original stop | 2×ATR | 3×ATR | 2×ATR close-based + 1.5R intraday brake |
|---|---:|---:|---:|---:|
| DESK (10+ sessions, n=22-28) | -0.17 (worst decile -1.67) | +0.09 (-1.02) | **+0.13 (-0.92)** | +0.09 (-1.36) |
| SIG longs (n=313) | +0.08 (-1.47) | +0.14 (-1.20) | **+0.18 (-0.96)**, CI +0.09..+0.26 | +0.22 (-1.32) |
| SIG shorts (n=67) | -0.65 | -0.42 | -0.22 | -0.44 |
| SPY control (n=313) | -0.86 | -0.39 | -0.20 | -0.26 |

**A close-based stop alone, on the original distance, is worse.** It keeps the tight distance but adds gap/brake risk: SIG longs +0.23R but worst decile -1.90; desk -0.07R, worst decile -2.28. **The gain comes from the distance, not from judging on the close.**

## Q5. Profit-taking

Left on the table after the desk's winning exits, in R beyond the exit price; the figure in brackets is the post-exit 10-session high:

| position | exit | R left on the table |
|---|---|---:|
| MRNA (shares) | trailed at +1.8R | +7.1R (+8.9R) |
| VKTX | trailed at +4.4R | +5.5R |
| MSTR | author-flat at +0.85R | +3.1R |
| HOOD (option) | target | +2.0R |
| IONQ | trailed at +1.0R | +1.3R |
| MU | target at +0.9R | +1.2R |
| DAL | target | +1.05R |
| SPY, NBIS, XLU, TLT, CRWV | | +0.4 to +0.8R each |

Only RKT (manual exit) saw no further high.

On SIG runs that reached ≥ +2R (n=132, mean MFE +4.9R), mean R kept:

| policy | mean R kept | share of MFE kept |
|---|---:|---:|
| chandelier 3 ATR (from entry or after 1R) | +1.32 | 51% |
| chandelier 2 ATR | +1.20 | 46% |
| target 2R, time 10 | +1.17 | 48% |
| 1/3 at 1R + breakeven + 2ATR trail | +1.06 | 43% |
| time 10 + stop | +1.04 | 41% |
| breakeven at 1R, time 10 | +0.99 | 35% |
| trail 8% | +0.85 | 35% |
| chandelier 1.5 ATR | +0.80 | 26% |
| time 5 + stop | +0.79 | 28% |

**What protection costs on the full cohort** (tip longs, 10+ sessions):

| policy | mean R | hit rate |
|---|---:|---:|
| 3×ATR chandelier | +0.24 | 44% |
| 2×ATR chandelier | +0.17 | 38% |
| 1/3 at 1R + breakeven + 2ATR trail | +0.19 | 57% |

The scale-out costs almost nothing in mean, lifts the hit rate from 44% to 57% and the median from -0.21 to +0.29R. That is the smoother ride at about the same expectancy.

## Recommendations (encodable; confidence flagged)

| # | change | parameter values | evidence | confidence |
|---|---|---|---|---|
| 1 | **Minimum stop distance, sized for equal risk.** The stop is the wider of the structure stop and k×ATR14; qty = risk budget / distance | k = **2.0** now, test **3.0**; size from the final distance (geometry gate already does qty from stop) | All 4 cohorts improve in mean and worst decile, including the SPY control. Desk stops are a median 1.15×ATR. | **Medium** (the most consistent result; its ticker-clustered gain is smaller, -0.18 → +0.01) |
| 2 | **No same-day plans for shares.** A tip shares position gets a minimum horizon of 2 sessions, so no `time_stop_sessions` < 2 | `time_stop_sessions >= 2` (the MU tt plan had 1) | Day-1 exits are about 0R in every cohort; median MFE by the day-1 close is +0.19R | Medium |
| 3 | **Replace the trail after TP1 with an ATR chandelier** instead of the ~1×ATR 15m-structure trail | `trailing: {mode: atr, atr_mult: 3.0, after_r: 1.0}` on the remainder; keep TP1 = 1/3 at +1R | Desk trailed exits captured 48% and left a mean +7R post-exit high. 3×ATR kept 51% of big runs vs 26% at 1.5×ATR. Equal-risk means: 3ATR +0.24 vs 1.5ATR +0.11 on tip longs | Low-medium |
| 4 | **Horizon classes at entry:** H-short / H-swing / H-extended, using the rules in the Q3 table | caps of 3 / 10 / 20 sessions; chase threshold +2% vs prior close; dip threshold -2%; low-ATR threshold 2.5% | Chased entries fade after 3 sessions (ticker-clustered -0.23R at 10); dip entries keep rising (+0.58R at 10, n=31) | **Low**: CIs include 0 and n is 31-101; run it as shadow-annotate first |
| 5 | **Breakeven only together with a partial.** Don't move to breakeven alone at +1R | drop the bare breakeven; use 1/3 at 1R + breakeven + trail | Bare breakeven at 1R: 35% hit rate, kept 35% of big runs; with the 1/3 partial: hit rate 57%, same mean | Low-medium |
| 6 | **Short tips:** no exit policy rescues them | keep puts-only, but treat short tips as watch-only until a short cohort shows positive R (n≥30) | Every policy is negative (-0.22 to -0.85R) on n=67 | Medium (direction-specific to a flat-to-up September tape) |
| 7 | **Use the stated hold as an upper bound only;** don't model the horizon on it | no change | `max_hold_sessions` doesn't predict (n≤11 per bucket); trades end after a median 2 sessions | Medium (that it doesn't predict) |
| 8 | **Re-run this study at about 20 more sessions** (target ≥ 30 new-book shares closes and ≥ 150 tip entries with 20 sessions of data) before promoting 3 or 4 | `r3.py` as is | The new book has 13 entries and at most 5 sessions | n/a |

## Honest limits

- **Small samples.** The desk has 52 entries (28 with 10+ sessions). Desk options are judged on their underlying only, never on premium.
- **Stops are mostly synthetic.** 87% of the tip cohort uses a synthetic 1.5×ATR stop, so its "original stop" mostly means 1.5×ATR.
- **One concentrated window.** The tip cohort is dominated by eva (45%) and by repeat tickers. Every robustness split (non-eva, ticker-clustered, first vs second half of dates) shrinks the horizon effects toward 0. Only the wide-stop effect keeps its sign in most splits. All of it is one window (tip intake from August 2026, bars to 10-02).
- **Coverage and censoring.** Entries after about 09-04 have fewer than 20 sessions; open rows are marked at the 10-02 close. 7% of path sessions had no bars at all, and 5% fell back to daily bars, where the stop was assumed first (conservative).
- **Execution assumptions.** Cost is a flat 5 bp per side. Fills are idealised at the stop price except on gaps. No borrow costs were charged on shorts.
