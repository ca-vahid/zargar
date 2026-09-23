# EM Experimental - frozen definitions (2026-09-19, `em-experiment-v1`)

User direction: `reviews/2026-09-19-ACTIVE-EXPERIMENTAL-PRACTICE-ROLLOUT.md` (reviewers' workspace). Frozen BEFORE the first experimental session.
A definition changes only by a new dated file with a new version. September 15-18 stay exploratory fixtures and validate nothing.

## What is compared

| Item | Value |
|---|---|
| Baseline | the existing **EM Practice** book, unchanged: model-reviewed evening preparation, ingestion auto-arm, production exits, `first_sale_rr_gate=off`, P-02 / P-06 as order-free observations |
| Experiment | **EM Experimental**, a separate sim-only Practice book, the INTEGRATED BUNDLE below, started at the baseline's recorded equity at the comparison timestamp |
| Same for both | market data, universe, plan sheet, deterministic plan builder, deterministic live entry decision, sizing and every risk limit (`risk_pct`, premium caps, position and exposure caps, per-book daily-loss halts), production stops and the rest of the exit ladder |
| Attribution | NONE per component. The experiment is one bundle; a difference between the books cannot by itself say which change caused it |

## The bundle (`techniques.enhanced_market.experiment.overrides`, resolved for the experimental book ONLY)

| Override | Value | Version |
|---|---|---|
| `preparation_policy` | `deterministic` - rules select eligible setups, zero model calls; the model review is ABSENT, not an approval or a veto | `em-prep-policy-v1` |
| `conditional_review_fix` | `apply` | `conditional-review-v1` |
| `prep_grade_floor` | `B` | same |
| `first_sale_rr_gate` | `enforce` - validated executable underlying bound, final quantity, unrounded, fail-closed, rechecked at final dispatch | `first-sale-v2` |
| `book_snapshot_observe` | `true` - its own recorder, ledger and capture ids | `book-snapshot-v3` |
| `source_candidates_execute` | `true` - a live, unexpired candidate of TODAY's session is PROMOTED once into a separately identified executable plan in this book | `source-continuation-v1`, `requalification-v1`, promotion `em-experiment-v1` |
| `runner_protection` | `execute` - after a CONFIRMED TP1 fill, the first completed bar that closes back through the saved TP1 exits the WHOLE remainder; a production decision on that bar (stop, flatten, scratch, target) goes first; never while an exit is working; once per trade | `tp1-reclaim-runner-exit-v1` |

P-02 (`small-position-exit-v1`) stays a paired OBSERVATION in both books. No blanket early-TP1 exit is switched on.

## Promotion boundary (frozen)

The research objects stay order-free everywhere: a `scenario:*` origin never arms through any path. Promotion COPIES a candidate into a new plan run with
a deterministic id, origin `experiment:<candidateId>`, the candidate's frozen single trigger, `eligibleFromTs` = the promotion minute (no earlier bar is
replayed; the gap rule is therefore unchecked, as for any late start) and `expiresTs` = the source horizon. Not promoted: a candidate that is terminal,
withdrawn, expired, not of today's session, not yet eligible, or without a complete entry, stop and target. A source-continuation trigger must pass the
deterministic eligibility owner and is skipped when the prepared plan already trades that exact trigger in the book (one position, not two). A
requalified child is admitted by its own frozen gates (R2, stop cap, author targets). One child per branch per session. Past its horizon, or once its
source is withdrawn, a promoted plan with no open trade is disarmed; an open position is managed to its exit.

## Identity and scope

Every experimental plan run is minted with tags `experiment:em-experiment-v1` and `xbook:<portfolioId>`; its orders carry the same tags; its decisions carry
the experiment stamp (version, overrides, policy versions, bundle hash) in the decision identity. The arm guard is two-way: a tagged run arms only in the
experimental sim book, and that book accepts only tagged runs. One arm per candidate PER BOOK. Rollback = pause the experimental book
(`POST /api/portfolios/<id>/pause`): entries stop, open positions stay managed, all evidence stays, nothing else changes.

## Daily comparison (`python -m zargar.tools.em_experiment_report report --date D`)

Net realized after fees, open exposure, marked vs covered-executable P&L, drawdown, trades / refusals / misses, model cost estimate, source alignment
(promoted plans by variant), data coverage; questionable fills listed apart. The experiment may lose simulated money: what is required is a CORRECT
experiment, not a profitable one. Review after 20 sessions or 60 baseline fills, whichever is later - a review, never an automatic promotion.
