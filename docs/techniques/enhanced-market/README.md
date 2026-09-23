# EM Options (EnhancedMarket) — state of play, doc map, known gaps

*Start here. Dated; the newest entry wins over any older document in this folder. Update this file
whenever a release, an activation or a review changes what is true. Last full refresh: 2026-09-22
evening (profitability plan implemented: stop rule, scorecard, exit quotes, BRK.B stream, recurring batch).*

## Doc map

| File | What it is | Currency |
|---|---|---|
| `README.md` | this file: state, what changed, known gaps | current |
| `METHOD.md` | the codified rulebook (numbered rules T1..T5, R1..R6 from the author's book; our extrapolations marked) | current; rule changes are dated in `TRADING-RULES.md` §5 |
| `TRADING-RULES.md` | EM's judgement log: rules under observation (§1), findings (§2), theories (§3), backlog (§4), change log (§5) | current; every claim dated with its evidence |
| `PIPELINE-PLAN.md` | build plan of the analysis pipeline (deterministic facts + vision passes + grounding) and what was learned | as-built history 2026-08-21; build order table kept current |
| `WALKFORWARD-PLAN.md` | session plans, walk-forward validation, live arming (phase 2), Validation tab, decisions | as-built 2026-08-22 with dated corrections; §9 item 3 describes the live fire path |
| `REVIEW-PLAN.md` | the review loop: trace, provenance, outcomes, reviews, replay, `/technique-review` skill | current (applies to premarket plan runs; live fire decisions are journaled events, not runs) |
| `EVOLUTION-PLAN.md` | method evolution loop: variant harness, ingestion, shadow instances; experiment log | current; "Where this stands" dated |
| `INGESTION-PLAN.md` | the author's Discord/video ingestion, board check, auto-arm boundary | current |
| `METHOD-CHANGE-PLAN-2026-09-12.md` | C1..C6 method change plan and verdicts (shares fallback, gap-day wait, liquidity screen) | as-built; verdicts in `TRADING-RULES.md` §5 2026-09-12 |
| `FLOW-CONFIRMATION-PLAN.md` | T-12 flow confirmation: measured and rejected on history | closed 2026-09-09 |
| `METHOD-REVIEW-2026-08-26.md` | the first book-vs-app audit | historical |
| `research/` | frozen profitability cohorts, per-session profitability reports, the order-free source-candidate ledger | current, dated files |
| `reviews/` | external review rounds, delivery responses, release verdicts, adopted regression packets | dated records; latest: `2026-09-22-PROFITABILITY-PLAN.md` |
| `research/experiment/` | the two-book experiment: per-session checks, reports, scorecards, reviews, build lineage | current, dated files |
| `notes/` | author video transcripts and feed notes | dated |

## State of play (2026-09-22 evening)

- **2026-09-23: EM is fully deterministic (user decision, v0.8.37, `em-deterministic-prep-v1`).** The baseline book is
  prepared by rules inside the engine (`technique/em_deterministic_prep.py`, `trigger=prepare`, event `TechniquePrepared`,
  manual `POST /api/technique/em/prepare`) once `preparation_policy=deterministic`; the paid nightly review (which was
  $1,104 of EM's $1,109 model spend) stands down (`paid_review=false`). `rules_vs_model` is superseded by that decision;
  the only automatic EM model call left is author-note ingestion (cents a day). TRADING-RULES §5 2026-09-23.
- **EM has not shown an edge.** 38 closed trades over 8 sessions across the books: −$219.40 after fees (about −$336 with
  the disputed ORCL fill at the ask), 29% winners, profit factor 0.84; 27 of 38 ended at the stop, and 18 of those
  kept running another 1R against the position (wrong entries, not tight stops). The 95% range of the average trade
  straddles zero. All EM trading is SIMULATED; the only real money EM spends is the baseline's nightly paid model
  review (~$50-62 a night). Full analysis: `reviews/2026-09-22-PROFITABILITY-PLAN.md`.
- **The EM stop rule is adopted (`em-stop-rule-v1`, user decision 2026-09-22).** Counted forward from 2026-09-22: after
  20 evaluable sessions, if the baseline's cumulative R is at or below zero AND the session-bootstrap upper bound of
  the average trade is below +0.1R, the paid review stops (`techniques.enhanced_market.paid_review` → false) and the
  baseline stays watch-only. The close check reports it every day and raises a keyed `stoprule` notice when it trips;
  flipping the switch is a human step. Code `technique/em_scorecard.py`, report `python -m zargar.tools.em_scorecard`.
- **Two books, both needed, nothing to remove.** EM Practice (baseline, paid model review) and EM Experimental
  (`07ef1e867cad4150bc81e072a8fd600a`, `em-experiment-v1` bundle, rules-only preparation, zero model calls). The A/B
  between them is the preregistered `rules_vs_model` test: if the free book does no worse over 20 sessions, the paid
  review is not earning its cost. The old shared "Practice (archived 2026-09-07)" book is already archived and holds
  Tips positions - left alone.
- **Midday is OFF again** (`technique.arm.midday_trading` false, 2026-09-22): the midday experiment met its
  preregistered 30-fire threshold and its trades lost −0.30R each; R6 stands. TRADING-RULES §5 2026-09-22.
- **Preregistered tests, thresholds fixed before the data** (`em_scorecard.TESTS`, reported at every close; a test
  that reaches its sample raises a keyed `decision` notice, it never changes anything itself): shares fallback vs
  options (20 trades), short puts in the prime windows (20), stop size against the 1-minute range (40 stops), one-touch
  carried levels (15), rules vs model (20 sessions).
- **New measurement:** `TechniqueExitQuote` (`exit-quote-v1`, on by default, observation only) records the quote each
  exit was decided on, bound to its exit order - the exit-side spread was an estimate until now.
- **BRK.B now streams** (a US share class `^[A-Z]{1,5}\.[ABC]$` passes `is_us_equity`; Alpaca spells it with the dot).
  On 2026-09-22 its plans saw one Yahoo-polled bar every 3-5 minutes (42 of 113 stale-bar errors) while storage showed
  all 390 - the record hid the gap. PLATFORM-RULES 2026-09-22.
- **Recurring preparation:** `scripts/em-evening-batch.py` (weekday task `ZargarEmEveningBatch`, 14:05 PT: resumable,
  one paid read at a time, one batch at a time, honours `paid_review`) and `ZargarEmAfterArming` (verifies both books
  for the NEXT weekday). Install/refresh with `scripts/em-install-session-checks.ps1`; the per-date one-off copies are
  superseded. Session checks: clock 06:05, pre-open 06:07, post-replan 06:32, exceptions x3, close 13:37 PT.
- **Live entry is deterministic** (`deterministic-entry-v1`, since 2026-09-15): `technique/entry_decision.py` judges the
  tracker's transition in under a millisecond and journals `TechniqueEntryDecision`; no model on the entry path.
  Exits: stop on bar close, 0.25R quote-breach brake, premium stop, ladder trims (P-06 runner protection executes in
  the experimental book only). Shares are the Practice fallback when the option is untradeable (C2).
- **Host clock** was 10.7 s slow on 2026-09-21 (the experimental admission gate correctly refused every entry); repaired
  that evening to +0.3 ms and checked against an NTP quorum before every open (`tools/clock_health.py`).
- History of every earlier state (deployments, review rounds, receipts) is in `TRADING-RULES.md` §5 and `reviews/`.

## Measurement and reporting

- `tools/em_profitability.py` (order-free): per-session report beside the frozen cohorts
  (`research/PROFITABILITY-COHORTS-2026-09-15.md`); rows carry policy version, decision id, timing and quote-refresh
  facts; the attempt census comes from every run's immutable fire events, so refused attempts without a trade row are
  counted once per (run, trigger, decision).
- `tools/em_fire_policy_migration.py preview`: read-only effective policy over the stored arms (never writes).
- `tools/em_source_candidates.py`: the author's morning levels as an order-free ledger, evaluated after the close;
  rows never arm.
- `tools/em_scorecard.py` (em-scorecard-v1): FIFO track record per book, the stop rule verdict and every preregistered
  test; written each close to `research/experiment/<date>-scorecard.md`. `tools/em_experiment_report.py` is the daily
  two-book comparison; `tools/em_experiment_check.py` verifies both books (pre-open, post-replan, after arming).
- The morning tick (session-local cron) reports health, the EM funnel, deterministic decisions and model calls every
  half hour from 06:20 PT.

## Known gaps, risks and what could be wrong

- **No edge shown, and the losses cluster** in short puts (reject), midday and the long-shares fallback - one
  overlapping cluster, not three findings. Each is a preregistered test, not a change (see state of play).
- **Friction against small option positions:** entry-side spread about $167 and fees $93.60 across 24 option trades
  against an option gross of +$60; the exit side is measured only from 2026-09-23 (`TechniqueExitQuote`).
- **The flat 0.5% stop floor is volatility-blind** when no invalidating structure is found (6 of 9 stops on 09-22 were
  exactly 0.50%); the `stop_vs_volatility` test decides it - do not touch `stop_buffer` before then.
- **Quote-time skew on option observations** in the capture recorder: OPRA `source_ts` is most likely poll time, not
  vendor time (Team2 finding; owner in PLATFORM-RULES). It limits the executable-profit measurement, not trading.
- **Budget bounds refuse most fires on volatile names:** 4 of 7 fires on 2026-09-16 were refused by the F33 daily-loss bound or
  the FIX-03 2% trade budget because one contract risks more than the budget. The bounds are correct; the question is
  whether a shares fallback should be tried when the option is affordable but over budget (not built; needs a decision).
- **Quote-breach stops within minutes of entry** (CRCL, CVNA on 2026-09-16; several on 09-14/15): the 0.25R crash brake fires
  on the underlying's live quote. Under measurement in the profitability report; no change without a cohort.
- **Timing field for non-1m plans:** `barCloseTs` uses the plan's trigger timeframe, so Tips fires on 5-minute plans
  show a close in the future. Diagnostic only; EM's 1-minute timing is correct. Fix pending on the EM branch.
- **Yahoo 1m depth (~20 sessions)** bounds how late a run can be scored; frozen bars on each decision make the
  after-close evidence replayable regardless.
- **FIX-01 v4 money repair** (`tools/em_reconcile_fallback.py --apply`) remains a human step under its scoped GO.
