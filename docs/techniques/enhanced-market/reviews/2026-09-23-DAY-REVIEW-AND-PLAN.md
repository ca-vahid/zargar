# EM 2026-09-23: day review and plan

Written after the close at the user's request (review, research the author's day, remove any useless EM book, make the
approach more profitable). Simulated money throughout; EM has not traded real money.

## How EM did today

The second session in which both books traded. A down, choppy day: SPY opened 772.79, low 766.50, closed about 768.5
(-0.6%).

| | EM Practice (baseline) | EM Experimental |
|---|---:|---:|
| Net after fees | **-120.18** | **-105.75** |
| Entries filled | 7 | 7 |
| Exits | 5 stops, 3 TP1, 2 TP2, 1 TP3, 1 flatten | 4 stops, 1 TP1, 1 P-06, 1 TP2, 1 flatten |
| Marked intraday peak over the open | +488.83 | +100.92 (executable +84.18) |
| Max drawdown (marked) | -772.31 | -386.01 |

- **Winners:** HOOD short +177.92 (TP2) in both books; VZ +42.42 in the baseline, which ran its full ladder.
- **Losers:** GOOGL -136.08 (both books), AMZN -104.32 and OKLO -66.24 (baseline), INTC -102.27 (experiment).
- **On the four trades both books entered, the experiment did better (+45.53 vs +7.96).** P-06 runner protection turned
  LITE from -10.09 into +15.58, and SNDK lost half as much.
- **The experiment's extra, rules-only admissions lost -151.28 across 3 trades.**
- **Track record:** 52 closed trades, -445.33, profit factor 0.78. The stop rule stands at 2 of 20 sessions and no
  preregistered test is ready.

## The author's day

Nothing public. Web searches found no post or result for EnhancedMarket on 2026-09-23. Our ingestion has one post, a
live stream at 09:02 ET revisiting Monday's breakout and naming "top setups", with no trade recap. The other morning note,
from EvaPanda (a separate contributor), called a small gap down with SPX 7760 as the pivot. As on 09-22, the method's
worth has to come from our own records.

## The finding that looked important, and what the data says

On both two-book sessions, every trade that ONLY the rules-only preparation admitted lost: 7 trades, -276, about -0.98R
each. The model-approved trades in the same book on the same days averaged -0.17R. That arrived the same day EM went
fully deterministic, so it had to be checked on more data before being believed.

**The model-veto study** (`research/2026-09-23-MODEL-VETO-STUDY.md`; 18 scored sessions, 2,112 rules-eligible triggers,
session-clustered intervals) **found no measurable value in the veto**:

| | Filled | Mean R | 95% CI |
|---|---:|---:|---|
| Approved by the model | 44 | +0.26 | -0.15 .. +0.81 |
| Vetoed by the model | 37 | +0.12 | -0.24 .. +0.44 |

The vetoed trades added positive R, and no reason family held up out of sample. So the 7-trade streak is most
likely chance, and the deterministic decision stands on the larger record. The streak is still recorded, and the scorecard
keeps counting.

The study surfaced one pattern: **break triggers** (breakout / breakdown, whose targets are the unanchored 2/4/6% ladder)
made -0.27R over 22 fills, against **level-anchored bounce / reject** at +0.40R over 54. It did NOT hold on the later
sessions (the test split was neutral), so it becomes a preregistered test (`break_vs_level`, 30 break fills from
2026-09-24), not a rule.

## A defect found on the way: outcome scoring had stopped

**Symptom:** no plan for a session after 2026-09-18 had a scored outcome. Those scores are what every EM study, the
Validation tab and the review loop read.

**Cause:** the scorer took the 400 newest runs and scored 25 per pass, newest first. Since the experiment and the
deterministic preparation began, EM mints ~300 plan runs a night for a session that has not started. Those runs cannot
be scored yet, but they took every slot on every pass.

**Fix (0.8.40):**
- a plan whose session has not opened is skipped;
- finished sessions are scored oldest-first, 60 per pass;
- a run that fails 3 times is set aside, so it can never block the queue.

The backlog of ~700 runs drains in about six hours after deploy. Tests: `tests/test_em_outcome_scoring_order.py`.

## Books: nothing to remove

Both EM books stay. Neither is useless, but their roles changed today:

- Since 2026-09-23 **both books prepare by the same rules** (the baseline was model-reviewed until then), so they arm the
  same candidates: 95 each for 09-24.
- **The Experimental book now isolates the bundle's execution parts:** first-sale reward:risk enforcement, P-06 runner
  protection as a real exit, and promoted source candidates. Today that difference was measurable on matched trades
  (+45.53 vs +7.96).
- **`rules_vs_model` is closed by decision.** The comparison the books now make is **bundle vs production exits on the
  same entries**, a cleaner test than before.
- **Retiring it would lose the only live evidence for P-06.** The baseline records P-06 only as an observation.

## Plan

**Done today:**
1. EM fully deterministic (0.8.37): zero model spend, from about $300 a week.
2. 1h and 1d history from Alpaca (0.8.38).
3. Outcome scoring fixed (0.8.40).
4. `break_vs_level` registered; `rules_vs_model` retired (0.8.40).

**Decisions already pre-written, waiting for data:**

| Test | Now | Decides |
|---|---|---|
| `shares_fallback` | 19 of 20 | If shares still lose against options (-0.43R vs +0.13R today), turn the shares fallback off (`techniques.enhanced_market.entry_fallback=off`): fewer trades, option-only. The close check raises the `decision` notice at 20. |
| `break_vs_level` | 0 of 30 | If breaks still lose, drop break triggers from preparation (level-anchored only). |
| `stop_vs_volatility` | 6 of 40 | Whether the flat 0.5% stop floor should scale with the stock's range. |
| `one_touch_levels` | 3 of 15 | Whether one-touch carried levels are excluded. |
| `short_puts_prime` | 1 of 20 | Whether short puts are kept in the prime windows. |
| stop rule | 2 of 20 sessions | Whether EM keeps trading in Practice at all; its original action, stopping the paid review, is already done. |

**What NOT to do:** retune anything from today's losses, or from the 7-trade streak. Every candidate change above has a
fixed sample; acting before it is reached is how a method gets fitted to its last week.
