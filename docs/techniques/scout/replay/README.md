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
