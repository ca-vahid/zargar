# Scout replay (P2) - screens on history, no LLM

Tool: `backend/zargar/tools/scout_replay.py` (its docstring lists the method and the biases). Every run appends its
parameters and headline to `VARIANTS.jsonl`; a number quoted from here must name its run label.

## First runs, 2026-10-11 (5 runs = 3 preregistered + 2 diagnostic)

Costs charged: 0.63% round trip (US$1 per order on US$600, 0.15% assumed half spread per side). Gates: price,
dollar volume, market cap. Entry at the session open, stop 2 x ATR(14), time exit.

| Run | Lane | Period | Trades | Mean net / trade | Mean net minus SPY | t, month-clustered (net minus SPY) |
|---|---|---|---|---|---|---|
| `s1-v2` | S1 strict (opportunistic insiders) | 2018-01 to 2026-09 | 268 | +0.79% | -0.45% | -0.39 |
| `s1-v2` | S1U (needs unclassified insiders) | same | 3,291 | -0.03% | -1.04% | -1.47 |
| `s1-v1-no-insider-min` | S1 strict, no per-insider minimum | same | 271 | +0.80% | -0.44% | -0.38 |
| `s1-v1-no-insider-min` | S1U, no per-insider minimum | same | 3,370 | -0.07% | -1.08% | -1.32 |
| `s2-v2` | S2 selected (top decile on volume) | 2023-01 to 2026-09 | 1,898 | -0.50% | -1.23% | -5.46 |
| `s2-v2` | S2 baseline (other gate-passing reporters) | same | 25,069 | -0.40% | -1.14% | -5.90 |
| `s1-no-stop` (diagnostic) | S1 strict / S1U | 2018-01 to 2026-09 | 268 / 3,291 | +1.39% / +0.29% | -0.32% / -1.31% | +0.58 / -0.82 |
| `s2-no-stop` (diagnostic) | S2 selected / baseline | 2023-01 to 2026-09 | 1,898 / 25,071 | -0.13% / -0.27% | -0.94% / -1.12% | -4.13 / -5.24 |

## What it says

1. **Neither screen shows an after-cost edge on history.** No lane beats SPY over its own holding days in any
   run; S1 strict is positive in absolute terms (+0.8% per 20-session trade) but below SPY, and its 268 trades
   in 8.7 years (2.6 a month after gates) cannot separate it from zero.
2. **S2's ranking adds nothing.** The top-decile-on-volume reactions (-0.50%) do no better than every other
   company that reported the same days (-0.40%), and this on a universe that EXCLUDES delisted companies, which
   flatters both. Consistent with PLAN F2 (post-earnings drift ~0 since 2017).
3. **The stop is not the cause.** Removing it lifts absolute returns a little and leaves every SPY-relative
   number negative.
4. **The per-insider minimum barely matters on history** (3,370 -> 3,291 S1U trades); it stays for the reason it
   was added (plan-like "clusters").

## What it does not say

- SPY is a large-cap benchmark in years when small and mid caps lagged it; a size-matched benchmark would be
  kinder to every lane. The S2 comparison against other reporters does not have this problem.
- Entry at the open is a proxy for the live 10:00 ET rule; the live spread gate, earnings-in-hold, corporate
  actions and Tips gates are not applied.
- Nothing here tests the LLM filter (PLAN F5: it can only be judged prospectively).

## Consequence for the paper run

The screens are a roughly zero-edge candidate source. The open question the prospective run can still answer is
whether an analyst lane's KEEP book beats its own screen book and the peer-matched random book. A screen book
that merely tracks the random book is the expected result, not a failure of plumbing. No threshold is changed on
the strength of these runs; two of the five were diagnostic and count toward the variants tried.

## Long holds, 2026-10-11 evening (8 more runs, all diagnostic)

Question (user, 2026-10-11): would the same signals work as longer-term trades? Same screens, gates and costs;
only the hold and the stop change. "No stop" = time exit only. Entries in the last months of the period exit at
the end of the data, so the 120-session row is short of full holds for 2026 entries.

| Run | Lane | Hold | Stop | Trades | Mean net / trade | Mean net minus SPY | t, month-clustered |
|---|---|---|---|---|---|---|---|
| `s1-hold40-nostop` | S1 strict / S1U | 40 | none | 268 / 3,291 | +2.86% / +1.63% | -0.94% / -1.81% | -0.84 / -1.68 |
| `s1-hold60-nostop` | S1 strict / S1U | 60 | none | 268 / 3,291 | +6.39% / +5.83% | +0.74% / -0.23% | -0.84 / -1.84 |
| `s1-hold120-nostop` | S1 strict / S1U | 120 | none | 268 / 3,291 | +7.94% / +6.79% | -1.78% / -3.68% | -1.35 / -4.23 |
| `s1-hold60-stop3` | S1 strict / S1U | 60 | 3 x ATR | 267 / 3,283 | +2.96% / +2.55% | -0.91% / -1.19% | -1.85 / -2.04 |
| `s2-hold20-nostop` | S2 selected / baseline | 20 | none | 1,898 / 25,071 | +0.55% / +0.19% | -0.86% / -1.35% | -3.09 / -4.50 |
| `s2-hold40-nostop` | S2 selected / baseline | 40 | none | 1,898 / 25,071 | +1.57% / +0.75% | -1.08% / -2.21% | -2.30 / -4.42 |
| `s2-hold60-nostop` | S2 selected / baseline | 60 | none | 1,898 / 25,071 | +2.95% / +2.09% | -1.58% / -2.80% | -2.12 / -5.19 |
| `s2-hold60-stop3` | S2 selected / baseline | 60 | 3 x ATR | 1,898 / 25,066 | +1.60% / +1.28% | -1.55% / -2.10% | -2.58 / -5.52 |

Reading:

1. **A longer hold does not create an edge.** Absolute returns grow with the hold because the market rose; against
   SPY over the same days every lane is negative on the month-clustered test. The one positive pooled mean (S1 strict
   at 60 sessions, +0.74%) has a negative clustered t: a few busy months carry it.
2. **A stop costs return at every horizon tested** (60 sessions: S1 strict +6.39% without, +2.96% with 3 x ATR).
3. **S2's ranking helps a little at longer holds** (selected beats the other reporters by 0.5 to 1.2 points at 20 to
   60 sessions) but both stay below SPY.
4. 13 runs have now been tried on this data (3 preregistered + 10 diagnostic). Nothing here changes a live setting.