# Cheaper intake-review processing - frozen evaluation plan and budget (history since 2026-09-09)

No provider call was made to produce this plan. Candidates are evaluated on the EXACT captured request of real reviews (`review_frozen.py`): tools are served from the case, a management tool is recorded as a proposed action and never executed. Production keeps its model whatever the result.

| case type | in history | per day | quota | captured now | median in / out tokens | Sonnet 5 | Haiku 4.5 | same cases on Opus 5 (recorded mean) |
|---|---:|---:|---:|---:|---|---:|---:|---:|
| management | 51 | 5.1 | 20 | 0 | 155,303 / 2,611 | $8.75 | $4.38 | $16.95 |
| missed_entry_flag | 21 | 2.1 | 10 | 0 | 137,088 / 2,761 | $3.92 | $1.96 | $7.66 |
| correction | 8 | 0.8 | 8 | 0 | 132,067 / 1,679 | $2.92 | $1.46 | $6.38 |
| mixed_multi_ticker | 16 | 1.6 | 6 | 0 | 117,205 / 1,681 | $1.96 | $0.98 | $3.84 |
| note_only | 463 | 46.3 | 16 | 2 | 120,017 / 1,777 | $5.36 | $2.68 | $10.55 |

**Budget: $35 estimate-based spending guard, not a guaranteed maximum** - actual billing can exceed a reservation; the guard refuses the NEXT attempt once recorded spend plus the next reservation would pass $35, so the final bill can end above it by at most one attempt's overrun, which is recorded (`review_frozen.SuiteBudget`: ONE durable ledger across both models, every case, turn, retry and separate invocation; each attempt is reserved BEFORE it is sent at request chars / 3 input + the full max_tokens output x 1.25, settled from the provider's usage, and left charged at its reservation when billing is unknown; SDK retries disabled; the guard cannot be raised by a later run) = Sonnet 5 $22.91 + Haiku 4.5 $11.46, one pass per model, including a 30% margin. No repeat passes inside this budget.

Replayable today: 2 captured review(s) of 559 in history. A review before capture was switched on kept its tool results but not its request, so it cannot be replayed faithfully; the quotas fill from reviews captured prospectively. At the per-day rates above the rare case types (management, missed-entry, correction) set the calendar, not the budget.

Comparison (safeguards rev 2): the actual INSTRUCTION is compared - target, stop levels, targets, fractions, sale fraction, hold cap; a changed level is a disagreement. A read is served only for the exact tool + arguments the case recorded; anything else stays MISSING and makes the case INCONCLUSIVE - never an equivalence pass. Limitation that remains: the guard is estimate-based - reservations use request characters / 3 and list prices, not the provider's tokenizer or invoice; the total stays within the guard only while no single attempt bills more than 1.25x its reservation.

Acceptance to even DISCUSS a change (not an activation rule): zero missed management actions, zero invalid replies on the management and correction cases, missed-entry flags matched, and every disagreement read by a human. One pass is not a measure of run-to-run variance.
