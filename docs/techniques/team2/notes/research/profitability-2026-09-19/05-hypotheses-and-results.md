# 5. Ranked hypotheses and what the measurement said

Definitions, windows and the six acceptance criteria were frozen and pushed before each round was run
(`../2026-09-19-profitability-preregistration.md`; commits 5bc329e3, 038ab13f, 2db47a49). One factor per arm, values fixed,
no grid search. Same harness for every arm: real option prints, $1.04 per contract per side, integer contracts, the desk's sizing,
one position at a time and two losses per day across the three symbols.

## Ranking before measurement, and why

| Rank | Arm | Factor | Support in the audit | Author support |
|---|---|---|---|---|
| 1 | H1 | Candle stop needs two consecutive 2m closes | 51% of trades closed within two bars at -11.7% | "only risk a candle or 2" (stated rule; he also says one) |
| 2 | H2 | Refuse a target nearer than 1.5 ATR | Near targets hit often and pay less than fees | none (our rule C3) |
| 3 | H3 | First trim on a new extreme of the move | His published cue | stated rule |
| 4 | H4 | No-trade zone only inside both ranges | He calls the pre-market range a "loose guide"; this is the live C1 arm | stated |
| 5 | H5 | Buy the $1.20 contract instead of $0.60 | Fee drag 3.9% vs about 1.7% | none; his fills are $0.20 to $0.60 |
| 6 | E1 | Re-plan a target that is the setup's own level | Emptied 31 symbol-days, two of his winners among them | his plan named a farther level |
| 7 | E2 | No outright sale at the first level | His winners run +112% to +445% | he sells "the rest" after trimming |
| 8 | X1 | Resting limit at +50%, premium stop -30%, 60-minute cap | 53% of entries print +50% within two hours | "sells into strength" |
| 9 | X2 | The same with the limit at +100% | 31% print +100% | same |

## Results on the training window (2026-05-07 to 2026-08-14, 66 sessions x 3 symbols)

Criterion 1 needs the mean net return per trade to beat the baseline by 3 points AND the book to finish above the baseline book.

| Arm | Trades | Mean net | vs baseline | Win rate | Book final | Max drawdown | Book without its 3 best days | SPY / QQQ / IWM mean | Criterion 1 |
|---|---|---|---|---|---|---|---|---|---|
| Baseline | 283 | -3.04% | | 32.9% | $11,102 | $6,781 | $4,259 | +0.5 / -4.6 / -4.9 | |
| H1 two-candle stop | 285 | -4.51% | -1.47 | 34.4% | $6,695 | $10,739 | $1,848 | -1.5 / -5.4 / -6.6 | FAIL |
| H2 target room 1.5 ATR | 238 | -1.76% | +1.28 | 28.6% | $17,448 | $9,306 | $6,517 | +2.1 / -3.5 / -3.7 | FAIL (under 3 points; drawdown 37% worse also fails criterion 6) |
| H3 new-extreme trim | 284 | -3.71% | -0.67 | 33.1% | $8,877 | $7,601 | $3,707 | -2.1 / -4.3 / -4.7 | FAIL |
| H4 conjunction zone | 321 | -2.54% | +0.50 | 33.3% | $5,314 | $6,775 | $2,366 | -0.5 / -4.2 / -3.0 | FAIL |
| H5 $1.20 contract | 282 | -1.98% | +1.06 | 33.0% | $10,976 | $6,399 | $5,502 | +1.2 / -2.7 / -4.3 | FAIL |
| E1 collision re-plan | 300 | -3.16% | -0.12 | 33.3% | $9,707 | $7,924 | $3,555 | +0.2 / -4.5 / -5.1 | FAIL |
| E2 no target exit | 260 | -7.17% | -4.13 | 20.8% | $5,209 | $10,352 | $2,419 | -2.6 / -8.2 / -10.5 | FAIL |
| X1 bracket +50% | 241 | -5.77% | -2.73 | 38.6% | $2,702 | $8,261 | $1,510 | -4.7 / -8.1 / -4.9 | FAIL |
| X2 bracket +100% | 228 | -6.41% | -3.37 | 27.2% | $2,420 | $12,539 | $1,219 | -5.3 / -6.9 / -7.1 | FAIL |

Fill sensitivity: baseline at one tick per leg -7.00% per trade, book $4,476. X1 and X2 under their registered stress case
-7.42% and -8.05%. No arm passed criterion 1, so criteria 2 to 6 were not needed and **the holdout was never opened for any arm**.
It stays clean for a future registration (for round-2 style ideas that came from holdout dates it is contaminated, as registered).

## Verdicts

| Arm | Verdict | One-line reason |
|---|---|---|
| H1 | REJECT | Waiting for a second close loses more per trade and doubles the drawdown. The tight stop is not the leak |
| H2 | REJECT as registered | The best of the nine, but +1.3 points is inside the noise, the mean stays negative and the book result is one day (+$5,105) |
| H3 | REJECT | No improvement |
| H4 | REJECT on this evidence | 38 more trades with the same negative expectancy; the book halves. The live C1 book continues to its own planned review; this is the first real-price evidence about it and it is not favourable |
| H5 | REJECT | Cuts the fee drag as expected and still loses |
| E1 | REJECT | Adds 17 trades on the training window and they lose like the rest. The two author winners that prompted it lie outside the training window and were not used to judge it |
| E2 | REJECT | Letting positions run without the level exit is the worst arm |
| X1, X2 | REJECT | Selling into strength with a resting limit does not pay for the stops |

## Dependence on dates and symbols

Every book result, the baseline included, rests on a handful of days: best day +$4,242 in a training book that finishes +$1,102.
Remove three days and every arm is below $6,600, most below $4,300. SPY is the only symbol near zero in any arm; QQQ and IWM are
negative in all ten. Nothing here survives the removal of its best days, which is the definition of no repeatable edge.

## What the nine failures have in common

They all change what happens AFTER the entry, or filter entries by a mechanical property. The entry itself has no directional
information at the moment we can act on it (page 4, layer 1). The remaining candidates are therefore about SELECTION, which is
the part of the author's method that is judgment: his A+ checklist (a flag into the EMA, the level's age, waiting hours for one
trade, "one and done", sitting out). None of that is documented tightly enough to code and test today.
