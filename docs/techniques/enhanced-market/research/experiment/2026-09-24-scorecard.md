# EM scorecard (em-scorecard-v1)

Generated 2026-09-25T02:21:03+00:00. Read-only; changes nothing.

## Track record

| | Trades | Net after fees | Win rate | Profit factor | Sum R | Mean R |
|---|---:|---:|---:|---:|---:|---:|
| All EM books | 61 | -1545.67 | 25% | 0.50 | -18.83 | -0.309 |
| All, disputed fills at a fair price | 61 | -1662.67 | 25% | 0.47 | -20.92 | -0.343 |
| De-duplicated (a copied trade counted once) | 53 | -1061.07 | 26% | 0.57 | -14.61 | -0.276 |
| EM Practice | 43 | -682.84 | 28% | 0.64 | -8.02 | -0.187 |
| EM Experimental | 17 | -1035.75 | 12% | 0.16 | -11.72 | -0.689 |
| Practice (archived, shared) | 1 | +172.92 | 100% | unknown | +0.91 | +0.910 |

R is the method's own risk unit: the entry-to-stop distance for shares, the 50% premium stop for options - what each trade planned to lose, so it is not fitted to outcomes.

## The stop rule

**COLLECTING** - 3 of 20 evaluable sessions since 2026-09-22.

Adopted 2026-09-22, counted from 2026-09-22: after 20 evaluable sessions, if cumulative R is at or below 0 and the optimistic average trade is below +0.10R, stop the paid review and keep EM watch-only: plans still built and scored, no money spent. It decides the paid model review that prepares the baseline book; the rule reports, a person acts.

## Preregistered tests

| Test | Question | Registered | Threshold | Now | Status | Reading (not a verdict until ready) |
|---|---|---|---|---:|---|---|
| midday | does allowing entries between 10:30 and 14:45 ET add value? | 2026-08-26 | 30 scored midday fires | - | **decided** | 2026-09-22: OFF. 62 fires; filled midday trades lost −0.30R each against −0.09R in the prime windows (not statistically separable, p = 0.36). No evidence FOR midday, so the book's R6 stands. |
| shares_fallback | does the shares fallback do as well as the option leg? | 2026-09-12 | 20 from 2026-09-12 | 22 | ready | {"sharesMeanR": -0.523, "optionsMeanR": 0.045, "shares": 22, "options": 15} |
| short_puts_prime | do short puts pay in the prime windows, now that midday is off? | 2026-09-22 | 20 from 2026-09-23 | 4 | collecting | {"meanR": -0.364, "net": -282.2} |
| stop_vs_volatility | are stops that are small against the stock's own range stopped by noise? | 2026-09-22 | 40 from 2026-09-23 | 13 | collecting | {"tight": 5, "tightReachedTp1": 0.6, "wide": 8, "wideReachedTp1": 0.25} |
| one_touch_levels | do entries off a level touched only once lose disproportionately? | 2026-09-22 | 15 from 2026-09-23 | 4 | collecting | {"oneTouchMeanR": -0.069, "restMeanR": -0.742, "oneTouch": 4, "rest": 13} |
| rules_vs_model | does free rules-only preparation do no worse than the paid model review? | 2026-09-19 | 20 (superseded) | - | **decided** | 2026-09-23: SUPERSEDED BY DECISION, not answered - EM is fully deterministic (both books prepare by rules). The model-veto study (research/2026-09-23-MODEL-VETO-STUDY.md, 18 scored sessions) found no measurable value in the veto: approved +0.26R vs vetoed +0.12R per filled trade, overlapping intervals. |
| break_vs_level | do break triggers (ladder targets) lose against level-anchored bounce/reject triggers? | 2026-09-23 | 30 from 2026-09-24 | 0 | collecting | {"breakMeanR": null, "levelMeanR": -1.02, "breaks": 0, "levels": 7} |

## Friction

Fees 197.6. Entry-side option spread 171.5 across 37 trades. Exit-side option spread +73.14 across 13 trades (measured only from 2026-09-23, when the exit quote began to be recorded). Option gross -1046.12.

## Kept, but not believed

- impaired: 2026-09-21 EM Experimental - host clock 10.5 s behind true time; the admission gate correctly refused every experimental entry as future-dated (reviews/2026-09-21-FIX-CLOSURE.md)
- disputed fill: ORCL 2026-09-17: a buy limit at 2.29 recorded a fill at 1.12 while the quote was 2.10 / 2.29 - below any price offered (E17-01). Reported as booked AND at the ask; never silently replaced

STOP-RULE: collecting
TESTS-READY: shares_fallback
