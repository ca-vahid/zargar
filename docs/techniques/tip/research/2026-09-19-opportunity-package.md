# Tips — profitability and missed-opportunity package (2026-09-19)

Baseline = [the economics review, revision 2](2026-09-19-economics-review.md). This package adds opportunity
tracking, one confirmed delay fix, cost attribution by useful action, account-fit research, the closed-position
table, the reversible duplicate-rule consolidation path and the cheaper-model evaluation plan. **Nothing here raises a
risk limit, forces a trade, substitutes an instrument, changes an exit or overnight policy, promotes a source or
changes a production model.** The relevance filter stays in `observe`.

All numbers: Tips Practice book, accounting sessions 2026-09-08 .. 09-18, regenerate with the commands shown.

## 1. What was built

| piece | where | behaviour change |
|---|---|---|
| Opportunity dispositions — every actionable idea gets ONE disposition with timestamps, reason and linked run/order ids | `tools/tip_outcomes.py --dispositions` (reuses the census; `classify_disposition` is pure) | none (report) |
| Cold-ticker park fast path — a tip parked ONLY for `ticker_resolves` re-runs the ordinary recovery sweep as soon as its quote is warm (≤ `signals.cold_park_recheck_seconds`, 60 s; 0 = off) | `signals/service.py` (`cold_only_park`, `_cold_park_recheck`; `recovery_sweep` now holds a lock) | **confirmed delay fix**; same recovery path, same gates |
| Scorecard v3 — adds "Opportunity dispositions" and "How closed positions ended" (net of fees, winners and losers together, DTE at exit, crossed a night) | `tools/tip_scorecard.py` | none (report) |
| Review cost by message category × what the review DID | `tools/tip_review_gate_eval.py` (retrospective) | none (report) |
| Pending consolidation — a reviewed merge can be born `needs_human` (non-operative) while its disputed duplicates are superseded, revision-checked and reversible | `signals/service.py::apply_knowledge_batch` (`pending`), `techniques/tip/consolidation.py` | only when a manifest says `pending: true`; older manifest hashes unchanged |
| Review-request capture + order-free review replay for a cheaper-model evaluation | `techniques/tip/review_frozen.py`, knob `techniques.tip.review_capture_context` (default OFF), `tip_review_gate_eval --model-plan` | none until the knob is on; then observation only |

Tests (focused): `test_tip_cold_park_recheck.py`, `test_tip_review_frozen.py`, `test_tip_scorecard.py`,
`test_kfin_followups.py`, `test_recovery.py`, `test_tip_review_gate.py`.

## 2. Opportunity-loss findings

Source: `economics/opportunity-dispositions-2026-09-08_2026-09-18.md`.

| | count |
|---|---:|
| actionable ideas | 189 |
| analyst TAKES | 34 |
| filled | 22 |
| deliberately declined (skip / watch) | 149 |
| risk-infeasible (no quantity fits the approved risk budget) | 6 |
| late (source already trimming / closing) | 1 |
| analysis failed | 6 |
| order unfilled | 5 |
| **avoidable (the desk's own processing)** | **7** |

* **All 7 avoidable misses are already-fixed causes.** Six are analyst runs that returned no usable verdict (five
  before the 09-17 E17 corrections, one on 09-17 before its deployment) — fail-closed, so the card waited out its
  120-minute limit. One is a 10.5 s quote against a 10 s limit on 09-10, the case the single fresh-quote retry
  (`freshRetry`) was built for. No outcome is assigned to a trade that did not happen.
* **Not avoidable, and kept that way:** 6 takes no quantity could fit inside the approved risk budget, 2 armed plans
  whose level never came, 1 order refused by a risk-gate price check, 1 DAY limit that never traded.
* **Confirmed unnecessary delay (fixed here):** 44 of 49 parks since 09-08 failed only `ticker_resolves` — the symbol
  had no quote yet. They were cured only by the 15-minute recovery sweep: SBLK +5 min, GS +7 min, RKT +13 min after a
  TAKE. The fast path re-verifies on the first real quote instead. Fresh-quote, plan-integrity and risk checks are the
  sweep's own and are unchanged.
* **Stale approvals:** the 11 expired cards are 5 "source already trimmed/moved its stop" (correct), and 6 that waited
  the full 120 minutes — 4 with no verdict (above) and 2 risk-infeasible takes. A risk-infeasible card cannot be
  approved without a labelled human override, so it lingers by design; shortening it is a decision (table §5).
  Since 09-16 the analyst checks feasibility BEFORE a take, which removes most of these at the source.
* **Duplicate work: not material.** 2 re-appraisals in the window (after-hours takes re-judged at the next open — by
  design); about ten intake reviews of identical template text across different days. Nothing to fix.

## 3. Intake cost by useful action

Source: `economics/review-gate-retrospective-2026-09-09_2026-09-18.md` (list-price estimate, not an invoice).
Note-only reviews are 461 of 557 and about $300 of the $375 review spend; management reviews are 51 ($43) and
missed-entry flags 21 ($16). The `observe` gate would have skipped 186 reviews ($121.83) with **zero** management
false negatives on history. **Recommendation: no enforcement now.** Decide after the five-session prospective window
(09-21 .. 09-25) on the same two conditions: zero management false negatives AND a human read of every skipped
message that carried a correction, a possible entry or a mixed message.

## 4. Research results (no activation)

**Account fit (shares at equal risk).** `tip_feasibility replay --since 2026-09-14`: 17 takes, 11 fit, 6 no-trade.
For 4 of the 6 a share position at the same dollar risk was possible: MU 1 sh +$89.96, AFRM 14 sh −$33.07,
AMZN 7 sh −$2.39, MSFT 3 sh −$16.35 at +3 sessions, no stop touched. n = 4: a direction to keep measuring, not
evidence. Never substituted automatically.

**How closed positions ended** (scorecard v3, net of fees, reconciles to the realized total): the table separates
questioned fills, first-seconds-of-session premium/stop exits, source-mirrored closes, underlying stops, in-session
premium stops and targets, with winners, losers, nights crossed and DTE at exit side by side. It is whole-trade P&L by
final exit kind — not overnight-only P&L. Entry horizons (v2, 38 eligible observations) and the hold study stand as
in the baseline: **no demonstrated selection edge**, D2 stays NO-GO, D3 research only.

**Cheaper review model.** `economics/review-model-evaluation-plan.md`: 60 stratified cases (20 management,
10 missed-entry, 8 correction, 6 mixed, 16 note-only), Sonnet 5 and Haiku 4.5, one pass each,
**$35 hard ceiling** enforced by `frozen.ReplayBudget`. Historical reviews kept their tool results but not their
request, so none is faithfully replayable today; cases fill from reviews captured once
`techniques.tip.review_capture_context` is on. Management tools are recorded as proposals and never executed.

## 5. Decisions (one table)

| # | decision | recommendation | evidence | default if undecided |
|---|---|---|---|---|
| P1 | Enforce the relevance filter | wait for the five-session report | 186/557 skippable, $121.83, 0 management false negatives (history only) | stays `observe` |
| P2 | Run the paid cheaper-model evaluation ($35 cap) | approve once ≥ 60 stratified cases are captured | plan above; ~10× lower list price on 80% of spend | not run; production model unchanged |
| P3 | Risk-infeasible cards wait 120 min | shorten to the quote-freshness horizon or keep for human override | 2 of 11 expiries; no trade lost | unchanged |
| P4 | Shares alternative when no option quantity fits the risk budget | keep measuring to n ≥ 20 before any proposal | n = 4, mixed | research only |
| P5 | Approve the pending consolidated ladder/trailing rule | human read in Knowledge → Audit proposals | D5 manifest `30c9891efc712b49` | stays non-operative |
| P6 | D2 exit policy / D3 overnight policy | no change | baseline review | off |

## 6. Five-session observation

Window 2026-09-21 .. 09-25. No prospective evidence exists yet and none is claimed here. The report
(`tip_review_gate_eval --prospective`, scorecard v3, dispositions) is produced after the fifth session.

## 7. Rollout record (2026-09-19)

- Merged as PR #235 (main `89682b8e`). Deployed through `deploy.ps1` + the `ZargarRestart` task on Saturday with the
  market closed: receipt `phase=verified`, running build `923e28d2` (runtime line + main), version 0.8.25.
- After the restart: 6 open managed tip positions, 28 resting orders, SBLK venue stop 30.58 x 62 ACCEPTED - identical
  to before. Intake liveness `live`. `trading.mode` practice; live-auto gates, `recap_route`, the feasibility gate,
  knowledge propose-only and `review_gate` (observe) unchanged.
- D5 applied through `POST /api/tip/knowledge/consolidate` (payload hash `5afdc8923878cba0`, batch
  `d5-ladder-trailing-30c9891efc712b49`): the six duplicate proposals were superseded at their reviewed revision inside
  one transaction and never became operative; the consolidated rule `19777467` was born `needs_human` and stays
  non-operative until a human approves it (P5). Rollback: the receipt in `tip_knowledge_batches` lists every
  superseded id and revision.
- `techniques.tip.review_capture_context` switched ON via the journaled settings API (observation only) so the
  cheaper-model evaluation cases accumulate during 09-21 .. 09-25. No paid run was made.
