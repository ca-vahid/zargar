# A. Tips desk outcomes review, 2026-09-08 to 2026-10-02

Read-only analysis as of 2026-10-02 evening ET. Every dollar figure is **net of `executions.commission`**. A "trade" is one flat-to-flat episode per (book, contract) built FIFO from `executions` (options x100). Each episode is linked to its `managed_positions` row through the leg's `entryOrderId`, which gives the source tag and close reason. All 51 episodes matched.

The numbers reconcile with `zargar.tools.tip_scorecard`:
- **Old book:** realized -1,086.82, marked -1,053.78, fees 149.76 inside realized (158.08 counting the questioned fills).
- **New book:** realized +101.66 (+102.13 including a CVX partial trim), marked +54.67, fees 0.

Files used: `data.json`, `desk.py`, `shadow.py` and `missed.py` in this folder (the scripts and the data they read).

**About the samples:** 46 closed trades in total: 37 in the old book and 9 in the new one. The new book has 5 sessions and 9 closed trades, so none of its numbers is statistically meaningful.

---

## 1. Whole-record P&L

### Per book

| book | closed trades | realized net $ | marked (equity - 10,000) | open lots | fees | win rate | avg win | avg loss | payoff | expectancy/trade |
|---|---:|---:|---:|---|---:|---|---:|---:|---:|---:|
| Tips Practice (old, 09-08 to now) | 37 | **-1,086.82** | **-1,053.78** (equity 8,946.22) | PL 59 sh (+33.04 MTM) | 158.08 | 13/37 (35%) | +82.79 | -90.13 | 0.92 | **-29.37** |
| Tips Practice 09-28 (new) | 9 | **+101.66** | **+54.67** (equity 10,054.67) | CVX, IBM, VSH, ENOV, cost $4,403, -47.46 MTM | 0.00 | 5/9 (56%) | +46.84 | -33.13 | 1.41 | **+11.30** |
| both | 46 | -985.17 | -999.11 | | 158.08 | 18/46 (39%) | +72.80 | -81.99 | 0.89 | -21.42 |

Model operating cost was **$872.64** (list-price estimate, shared across the whole window and not specific to either book). After model cost the old book is at -1,926 marked. The new book's window carried about $37.6 of model cost, so it is about +17 marked after model cost.

### By vehicle (DTE measured at entry)

| vehicle | n | net $ | win | avg win | avg loss | payoff | expectancy | fees | return on notional |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|
| shares (both books) | 22 | **+258.78** | 12/22 (55%) | +64.36 | -51.36 | 1.25 | **+11.76** | 0.00 | +0.8% (old), +0.7% (new) |
| options 0-4 DTE | 8 | -285.96 | 2/8 (25%) | +60.76 | -67.91 | 0.89 | -35.75 | 45.76 | |
| options 5-29 DTE | 6 | -246.99 | 2/6 (33%) | +32.88 | -78.19 | 0.42 | -41.16 | 22.88 | |
| options 30+ DTE | 10 | -711.00 | 2/10 (20%) | +175.38 | -132.72 | 1.32 | -71.10 | 89.44 | |
| all options (old book only) | 24 | **-1,243.95** | 6/24 (25%) | | | | -51.83 | 158.08 | **-14.6%** of $8,514 |

### By source (both books)

| source | n | net $ | win | avg win | avg loss | payoff | expectancy |
|---|---:|---:|---|---:|---:|---:|---:|
| ab | 16 | **-368.79** | 6/16 | +54.10 | -69.34 | 0.78 | -23.05 |
| florida-man | 1 | -505.08 | 0/1 | | -505.08 | | -505.08 |
| eva | 1 | -172.14 | 0/1 | | -172.14 | | -172.14 |
| muggzone-options | 8 | -113.53 | 2/8 | +82.42 | -46.40 | 1.78 | -14.19 |
| jon-and-kian | 6 | -41.20 | 3/6 | +35.86 | -49.60 | 0.72 | -6.87 |
| common-stock | 7 | +12.12 | 2/7 | +194.95 | -75.56 | 2.58 | +1.73 |
| tt | 3 | +17.95 | 2/3 | +22.56 | -27.18 | 0.83 | +5.98 |
| neal | 4 | **+185.50** | 3/4 | +92.79 | -92.87 | 1.00 | +46.38 |

### By exit reason class

| exit class | n | net $ | win | avg | notes |
|---|---:|---:|---|---:|---|
| premium stop / bleed | 11 | **-1,212.23** | 0/11 | -110.20 | options only; 6 of them in the opening minutes (-829.85) |
| underlying stop (initial, venue GTC / bar close / quote breach) | 13 | **-762.21** | 2/13 | -58.63 | |
| stop after trailing to at or above entry | 7 | **+656.72** | 6/7 | +93.82 | ON +159, VKTX +296, MRNA +94, IONQ +86 |
| target (quote-watch or bar) | 4 | +402.08 | 4/4 | +100.52 | GOOGL opt +248, MRNA opt +113, MU +22, DAL +19 |
| mirrored source exit | 7 | -115.32 | 4/7 | -16.47 | old: META -121, NFLX -12, AAL +14, ACHR +9; new: UBER -39, MSTR +34, TLT +0.2 |
| analyst close (own call) | 1 | +51.92 | 1/1 | | HOOD |
| stale exit | 1 | +33.26 | 1/1 | | CRWV, 5 sessions below 0.5R |
| time / DTE floor | 1 | -0.08 | 0/1 | | RKLB |
| manual / repair | 1 | -39.31 | 0/1 | | RKT venue-oversell repair |
| **opening-minutes exits (09:30-09:35 ET), all classes** | 11 | **-961.81** | 1/11 | -87.44 | old -958.1 on 8 trades; new -3.7 on 3 trades |

### By holding period (sessions between entry and exit)

| holding | n | net $ | win | avg win | avg loss | expectancy |
|---|---:|---:|---|---:|---:|---:|
| same day | 9 (all in the old book) | -345.64 | 2/9 (22%) | +82.42 | -72.93 | -38.40 |
| 1-2 sessions | 27 | -446.29 | 12/27 (44%) | +68.96 | -84.92 | -16.53 |
| 3+ sessions | 10 | -193.24 | 4/10 (40%) | +79.50 | -85.21 | -19.32 |
| new book, 3+ sessions | 2 | +91.67 | 1/2 | | | |

### Risk-plan era vs pre-risk-plan era

The risk plan is `config.extras.riskPlan`, which has been enforced since about 2026-09-14.

| cohort | n | net $ | win | avg win | avg loss | mean R | sum R |
|---|---:|---:|---|---:|---:|---:|---:|
| **no risk plan** (entries 09-08 to 09-16, almost all options) | 12 | **-1,152.21** | 2/12 | +175.4 | -150.3 | n/a | n/a |
| with risk plan, shares | 21 | **+298.09** | 12/21 | +64.4 | -52.7 | **+0.20R** | +4.10R |
| with risk plan, options | 13 | -131.05 | 4/13 | +46.8 | -35.4 | -0.19R | -2.42R |
| with risk plan, all | 34 | +167.04 | 16/34 | +60.0 | -44.0 | +0.05R | +1.68R |

## 2. Before vs after the 2026-09-28 fresh start

| | before (old book, entries 09-08 to 09-25) | after (new book, entries 09-28 to 10-02) |
|---|---|---|
| closed trades | 37 (13 shares, 24 options) | 9 (all shares) |
| realized net | -1,086.82 (−29.37/trade) | +101.66 (+11.30/trade) |
| marked | -1,053.78 | +54.67 |
| win rate / payoff | 35% / 0.92 | 56% / 1.41 |
| fees | 158.08 | 0.00 |
| largest loser | CCXI opt -505.08 | KWEB -67.58 (-1.01R) |
| avg loss | -90.13 | -33.13 |
| opening-minutes exits | 8 trades, -958.1 | 3 trades, -3.7 (MU +22.5 target, MO -20.7, PRAX -5.5) |
| mirrored exits | 4 trades, -110.3 | 3 trades, -5.0 (now on the held shares leg) |
| deployed capital (RTH average / max) | 27% / 71% | 48% / 88% |
| max concurrent positions | 8 | 7 (cap hit) |

**Like-for-like caveat:** the old book's shares cohort was already +157.13 on 13 trades (+0.8% of notional), almost the same as the new book's +0.7% of notional. The fresh start's improvement is mostly "stopped trading options", not a better shares process. The old book's whole loss came in its first three sessions: equity went 10,000 → 8,572 by the 09-10 close (−1,428), then 8,572 → 8,948 (+376) over the next 15 sessions.

## 3. Sizing

| | old shares | old options | new shares |
|---|---:|---:|---:|
| median position notional | $1,280 | $191 (mean $355) | $1,451 (mean $1,454) |
| median planned risk (riskPlan) | $70.2 | $67.9 | $57.0 |
| median risk budget (1% of equity) | $90.4 | $89.6 | $100.0 |
| planned risk / budget | ~78% | ~76% | ~57% |
| realized R on full stop-outs | SBLK -1.03, U -1.01, JELD -0.97 | premium stops −0.3 to −0.9R | MO -1.03, KWEB -1.01 |

- **Small positions:** some new-book positions risk far below budget: PRAX $9.9, CVX $11.6, TLT $15.6, MO $20, MU $24.8 (1 share at $1,055, an integer floor).
- **Pre-risk-plan options:** losses ran to 19-70% of premium (CCXI -70%, AAOI -37%, GS -37%), i.e. 2-5x the 1% budget.
- **Refusals:**
  - `TipLaneDecided lane=refused` was journaled once, for the 7-position cap, on the new book (signal b3c0fb73...).
  - 18 of 170 declines cite the risk budget or `check_feasibility` qty 0, almost all on options contracts. Five of those came after 09-28: RKT, AMZN, U, an MU spread and an MU put.
  - The scorecard's risk_infeasible count is also 18.
  - No cash refusals were found.
- **Capital utilisation:** the old book averaged 27% deployed during RTH (max 71%); the new book averages 48% (max 88%). Daily means range 0.33-0.70. Four open new-book lots hold $4,403 at cost.

## 4. Shadow books: does the analyst's selection add value?

The shadow books are FIFO per signal: closed lots plus open lots marked at the last 1m close. An expired option is marked at intrinsic value from the underlying's close on expiry day. Fees are included. Books are **excluded** when `quarantined=true` or when the FIFO has unallocated (phantom-short) sells.

The excluded books are:
- quarantined: ab (armed) [ARCH] with 1,164 unallocated sells (-40,669 sh); eva [ARCH] with +$207k artifact P&L; eva (armed) [ARCH]; muggzone [ARCH] and (armed) [ARCH]; tt [ARCH]; common-stock (armed) [ARCH]
- not quarantined but showing unallocated sells: the **live "Shadow: tt" book (1 sell, 11 units)** and the **live "Shadow: ab (armed)" book (2 sells, 16 units)**

**Clean immediate books** (buy at tip time, mostly the stated option):

| source (clean immediate books, all eras) | signals | cost $ | net $ | return on cost |
|---|---:|---:|---:|---:|
| ab (live + archived) | 54 | 96,510 | -24,050 | -24.9% |
| eva (live only) | 44 | 82,365 | -23,891 | -29.0% |
| muggzone-options (live only) | 34 | 57,916 | -19,558 | -33.8% |
| jon-and-kian (live + archived) | 19 | 44,125 | -7,431 | -16.8% |
| common-stock (live + archived) | 13 | 39,610 | -2,933 | -7.4% |
| neal (live + archived) | 17 | 36,978 | +3,517 | **+9.5%** |
| giul-heatseeker | 6 | 10,800 | +279 | +2.6% |
| MK-alpha-trades | 2 | 3,540 | -623 | -17.6% |
| flow-scan, florida-man | 2 | 3,995 | -3,837 | -96% |

Armed books (shares at the tip's level, clean ones only) are near flat: ab (armed) live -1.1%, jon-and-kian (armed) -0.2% / -0.9%, neal (armed) +2.8%, tt (armed) -0.4%, florida-man +1.4%, muggzone (armed) live -0.6%. Their realized dollars are tiny (≤ $164 per book).

**Selection test 1 (shadow immediate return by analyst verdict, clean books only):**

| verdict | n | return on cost | mean | median | win |
|---|---:|---:|---:|---:|---:|
| take | 63 | **-17.1%** | -25.4% | -18.9% | 17/63 |
| skip | 111 | **-25.3%** | -28.6% | -23.4% | 31/111 |
| watch | 15 | -3.1% | -2.1% | -0.2% | 7/15 |

By source the edge flips sign:
- ab: take -36.4% vs skip -25.5%
- eva: take +42.9% (n=3) vs skip -34.3%
- jon-and-kian: take -5.5% vs skip -75.3% (n=3)
- muggzone: take -37.6% vs skip -31.7%
- neal: take +13.1% vs skip +1.7%

**Selection test 2 (underlying move in the tip's direction after the proposal, 1m bars):**

| | n | mean 1-session | mean 5-day | share ≥ +5% in 5 days | median 7-day MFE |
|---|---:|---:|---:|---:|---:|
| executed takes | 52 | -0.00% | **+0.04%** | 7/52 (13%) | +4.4% |
| declined (skip + watch) | 170 | +0.28% | **+1.19%** | 38/170 (22%) | +6.2% |

**What the desk actually did on the same signal** (29 pairs that have a clean immediate fill): desk mean **-7.1%** on notional vs shadow **-29.7%**.

## 5. Missed opportunities

There were 170 declined proposals: 155 skip, 15 watch, 131 distinct ticker-days. Of these, 147 were long tips.

| when (UTC) | source | ticker | verdict | why declined (short) | 5-day move | shadow fill |
|---|---|---|---|---|---:|---:|
| 09-16 19:47 | neal | TQQQ | watch | risk budget: 1 contract does not fit | +16.0% | **+108%** (TQQQ 12/18 70C) |
| 09-16 19:34 | ab | SPY | skip | budget: $213 delta-linear vs $88 | +2.0% | **+299%** (SPY 9/25 760C) |
| 09-25 14:23 | ab | LITE | skip | | +15.2% | +10% |
| 09-22 13:50 | muggzone | MRNA | skip | | +13.2% | n/a (quarantined book) |
| 09-17 19:42 | muggzone | HOOD | skip | | +11.0% | n/a |
| 09-16/17 | eva | MRNA, INTC, ARM, META, MU, ZS (x13 rows) | skip | morning map/digest branches (auto-skip rule N8) | +8% to +25% | n/a (quarantined eva book) |
| 09-24 19:03 | neal | U | watch | | +8.1% | -0.5% (shares) |

Counter-examples, where the skip was right: ab HOOD 9/25C skip, underlying +12.4% but shadow -100.8% (the option expired worthless first). The eva skips that clean books cover averaged -34.3%.

---

## Findings

1. **Options were the loss engine, and most of it came before the risk plan existed.** The 24 option trades lost -1,243.95 (-14.6% of notional, 6/24 wins) and carried 100% of the $158 fees. The 12 trades without a `riskPlan` (entries 09-08 to 09-16) lost -1,152.21. Five single trades did 1,262 of it: CCXI -505, AAOI -214, APLD -210, GS -172, PURR -159. Under the risk plan, options lost only -131 (-0.19R mean).
   *Option:* keep the lotto/options lane off until a risk-planned options cohort of at least 30 trades shows a positive mean R. If options come back, size by premium-at-risk (`max_premium_per_tip` = the 1% budget, not $750).

2. **Shares were modestly positive in both eras, and the fresh start mostly removed options.** Risk-planned shares: 21 trades, +298.09, 12/21 wins, +0.20R mean. Old shares returned +0.8% of notional and new shares +0.7%: the same process.
   *Option:* judge the 09-28 rules against the old shares cohort, not against the old book total, or the new rules get credit they did not earn. The evaluation unit should be R per trade, and 9 trades is far too few.

3. **Trailing stops and targets made all the money; initial stops and premium stops lost it.** By class:
   - trailed stop: +656.72 on 7 trades (6 wins)
   - target: +402.08 on 4 (4 wins)
   - initial stop: -762.21 on 13
   - premium/bleed: -1,212.23 on 11 (0 wins)

   *Option:* keep `trailing.after_r=1.0` and quote-watch targets. For shares, test a cheaper breakeven move: no breakeven before +1R today. Track the "MFE before stop" of the 13 initial-stop losers to see how many reached +0.5R first.

4. **Opening-minutes exits were the single worst bucket.** 11 trades exited between 09:30 and 09:35 ET for -961.81, with 1 win. The six option premium stops at the open (CCXI, GS, DAL, HIMS, SMCI, CORZ) cost -829.85: overnight gaps or wide opening spreads triggered premium stops on the first mark. On shares since 09-28 the bucket is harmless (-3.7).
   *Option:* if options return, add an opening-spread guard: do not judge a premium stop on marks before about 09:35 unless the underlying has also breached its stop. Treat holding an option overnight as a decision with an explicit gap-risk budget.

5. **Mirrored source exits roughly break even and depend on matching the leg.** 7 trades for -115.32, of which old META -120.64 was a same-day 0DTE. Since 09-28, mirroring on the held shares leg gave -5.0 over 3 trades. `TipSourceExitNotMirrored` fired 5 times (ACHR, DAL x4) because the strike or expiry differed. Correctly so, but those author exits went unused.
   *Option:* for shares-first positions, mirror on the underlying (any author close/trim on that ticker) and record a mismatch rather than ignoring it. Measure mirrored-exit vs counterfactual-hold on the next 20 occurrences before trusting the rule.

6. **Source quality is real but rests on tiny samples.**
   - **neal** is the only source positive everywhere: desk +185.50 on 4 trades; shadow immediate +9.5% on 17 signals; armed +2.8%.
   - **ab** is the most-traded and worst: desk -368.79 on 16 trades, shadow -24.9% on 54. Its analyst takes do worse than its skips (-36.4% vs -25.5%), and ab takes moved -1.9% in 5 days vs ab declines -0.6%.
   - **muggzone** (shadow -33.8%) and **eva** (-29.0%) lose heavily when bought at tip time. Muggzone also carries the largest model cost ($344).

   *Option:* move per-source budgets: give neal the full budget, cut ab to half until its shares cohort reaches n≥15 with positive R. Charge model cost against the source when ranking (muggzone is -570 after model cost in the scorecard).

7. **The analyst's selection does not show a measurable edge on the underlying.**
   - Executed takes moved +0.04% mean over 5 days (13% of them moved ≥5%); declined ideas moved +1.19% (22% moved ≥5%), n=52 vs 170.
   - On clean shadow fills, takes beat skips slightly (-17.1% vs -25.3% on cost), but the median gap is small (-18.9% vs -23.4%) and the sign flips by source.

   It is a long-biased September tape, so declined longs benefited from beta.
   *Option:* run a blinded check: score the analyst against a dumb rule ("take every priced BTO from neal/common-stock, shares, 1% risk") on the same signals for the next 20 sessions. Report take-vs-skip forward returns per source every week (beta-adjusted against SPY/QQQ).

8. **The desk's execution layer adds a lot of value relative to copying the tip.** On the 29 signals where both exist, the desk made -7.1% mean on notional vs -29.7% for the immediate shadow. The biggest gaps:
   - AAOI -37% vs -100%
   - SPY shares +0.1% vs the option -101.5%
   - UBER -2% vs -54.5%
   - KWEB -3.4% vs -29.9%

   Copying the author's option and holding is strongly negative across the clean books (-17% to -34% for 4 of the 6 largest sources).
   *Option:* this argues for keeping shares-first plus the stop discipline as the default. Use immediate books as a "do not copy the vehicle" warning, not as a target.

9. **Risk sizing is disciplined on shares but under-uses the budget.** Full stop-outs realise -0.97R to -1.03R (SBLK, U, JELD, MO, KWEB), so geometry and fills behave. But new-book planned risk has a median of $57 vs a $100 budget (57%), and several positions risk $10-25 (PRAX, CVX, TLT, MO, MU 1 share).
   *Option:* if the edge holds, size toward the full 1% (use fractional-share-free rounding up when the budget allows, with a minimum risk of 0.5% or skip). That roughly doubles expectancy per slot without a rule change. Alternatively, keep the size and stop counting $10-risk trades as evidence.

10. **The 7-position cap binds now that utilisation has doubled.** The new book hit 7 concurrent positions, averages 48% deployed (max 88%), and journaled one cap refusal. The old book ran at 27%.
    *Option:* log every cap/cash refusal with its signal and follow its shadow forward return, so the cap's opportunity cost is measured. Today only 1 refusal is visible. Consider a soft cap: the 8th slot only for sources with positive R.

11. **Budget-infeasible option tips are a recurring miss with no shares fallback.** 18 declines were "check_feasibility qty 0", and 5 of them came after 09-28 (AMZN, U, MU x2, RKT). TQQQ (watch, budget) went +16% underlying / +108% shadow, and SPY 9/25 760C (skip, budget) went +299% shadow.
    *Option:* when the named contract fails the budget, re-express it on shares at the 1% risk instead of declining. That appears to be the intent of shares-first, but these cards still say "one contract does not fit".

12. **Most "big misses" are eva map/digest branches.** Of the 29 declined rows with ≥8% follow-through, 13 are eva morning-map branches (MRNA, INTC, ARM, META, MU, ZS), auto-skipped by rule N8 and often duplicated. These are not tradeable calls, and eva's clean shadow skips average -34%. Real misses are few: neal TQQQ, ab LITE (+15%), muggzone MRNA/HOOD.
    *Option:* dedupe digest branches before counting misses. Track "map names that later triggered" as a watchlist feature (alert only), not as entries.

13. **Shadow-book data integrity is still leaking.** Seven quarantined books, plus two live non-quarantined books ("Shadow: tt", "Shadow: ab (armed)"), have FIFO-unallocated sells, i.e. sells with no matching lot. The quarantined archived eva book reports +$207k and muggzone/tt archived books +16% to +32%. Including them would flip every conclusion (+57% for "skip").
    *Option:* auto-quarantine any shadow book the moment a sell exceeds the open lot (FIFO check in the shadow executor), and quarantine the two live books now (a human step).

14. **Fixed costs dwarf the edge.** Model cost was $872.64 over the window vs -985 realized. Since 09-28 it is about $37.6 for +54.67 marked, so the cost package worked, but the desk is still only about +$17 after model cost.
    *Option:* keep the cheap configuration. Spend model tokens per source in proportion to that source's measured R (muggzone: $344 of model cost, 0 shares fills since 09-28).

## Honest limits

- **Small samples:** 9 trades in the new book and 34 risk-planned trades in total. Nothing here passes a significance test.
- **Shadow marks:** shadow-book open options are marked at the last 1m print, so stale prints are possible on thin contracts. Shadow sizing is research sizing (about $1.8k per tip).
- **Missed-move estimate:** the underlying move uses 1m bars at the proposal timestamp. 7 calendar days stands in for "5 sessions".
- **Quarantined books:** missed opportunities from quarantined books (eva and muggzone before 09-27) have no usable shadow fill.
