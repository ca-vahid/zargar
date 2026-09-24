# EM scorecard (em-scorecard-v1)

Generated 2026-09-23T20:37:08+00:00. Read-only; changes nothing.

## Track record

| | Trades | Net after fees | Win rate | Profit factor | Sum R | Mean R |
|---|---:|---:|---:|---:|---:|---:|
| All EM books | 52 | -445.33 | 29% | 0.78 | -9.53 | -0.183 |
| All, disputed fills at a fair price | 52 | -562.33 | 29% | 0.72 | -11.62 | -0.223 |
| De-duplicated (a copied trade counted once) | 46 | -320.80 | 30% | 0.81 | -7.47 | -0.162 |
| EM Practice | 38 | -243.42 | 32% | 0.83 | -2.53 | -0.067 |
| EM Experimental | 13 | -374.83 | 15% | 0.34 | -7.91 | -0.608 |
| Practice (archived, shared) | 1 | +172.92 | 100% | unknown | +0.91 | +0.910 |

R is the method's own risk unit: the entry-to-stop distance for shares, the 50% premium stop for options - what each trade planned to lose, so it is not fitted to outcomes.

## The stop rule

**COLLECTING** - 2 of 20 evaluable sessions since 2026-09-22.

Adopted 2026-09-22, counted from 2026-09-22: after 20 evaluable sessions, if cumulative R is at or below 0 and the optimistic average trade is below +0.10R, stop the paid review and keep EM watch-only: plans still built and scored, no money spent. It decides the paid model review that prepares the baseline book; the rule reports, a person acts.

## Preregistered tests

| Test | Question | Registered | Threshold | Now | Status | Reading (not a verdict until ready) |
|---|---|---|---|---:|---|---|
| midday | does allowing entries between 10:30 and 14:45 ET add value? | 2026-08-26 | 30 scored midday fires | - | **decided** | 2026-09-22: OFF. 62 fires; filled midday trades lost −0.30R each against −0.09R in the prime windows (not statistically separable, p = 0.36). No evidence FOR midday, so the book's R6 stands. |
| shares_fallback | does the shares fallback do as well as the option leg? | 2026-09-12 | 20 from 2026-09-12 | 19 | collecting | {"sharesMeanR": -0.43, "optionsMeanR": 0.126, "shares": 19, "options": 14} |
| short_puts_prime | do short puts pay in the prime windows, now that midday is off? | 2026-09-22 | 20 from 2026-09-23 | 1 | collecting | {"meanR": 1.271, "net": 177.92} |
| stop_vs_volatility | are stops that are small against the stock's own range stopped by noise? | 2026-09-22 | 40 from 2026-09-23 | 6 | collecting | {"tight": 3, "tightReachedTp1": 0.667, "wide": 3, "wideReachedTp1": 0.0} |
| one_touch_levels | do entries off a level touched only once lose disproportionately? | 2026-09-22 | 15 from 2026-09-23 | 3 | collecting | {"oneTouchMeanR": 0.461, "restMeanR": -0.595, "oneTouch": 3, "rest": 7} |
| rules_vs_model | does free rules-only preparation do no worse than the paid model review? | 2026-09-19 | 20 from 2026-09-22 | 2 | collecting | {"experiment": {"trades": 13, "net": -374.83, "fees": 20.8, "winRate": 0.154, "avgWin": 96.75, "avgLoss": -51.67, "profitFactor": 0.34, "sumR": -7.91, "meanR": -0.608, "rCount": 13}, "baseline": {"trades": 10, "net": -29 |

## Friction

Fees 122.72. Entry-side option spread 111.5 across 31 trades. Exit-side option spread +30.53 across 7 trades (measured only from 2026-09-23, when the exit quote began to be recorded). Option gross -100.01.

## Kept, but not believed

- impaired: 2026-09-21 EM Experimental - host clock 10.5 s behind true time; the admission gate correctly refused every experimental entry as future-dated (reviews/2026-09-21-FIX-CLOSURE.md)
- disputed fill: ORCL 2026-09-17: a buy limit at 2.29 recorded a fill at 1.12 while the quote was 2.10 / 2.29 - below any price offered (E17-01). Reported as booked AND at the ask; never silently replaced

STOP-RULE: collecting
TESTS-READY: none
