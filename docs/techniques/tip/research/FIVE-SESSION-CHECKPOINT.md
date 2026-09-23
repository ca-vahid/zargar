# Tips five-session observation — durable checkpoint

**Owner:** the Tips desk (whoever holds the desk on the due date — a person or an assistant session; this file, not a
coding session's timer, is the commitment). **Deliverable:** ONE report to the user and the review team after five
ACTUAL observed sessions. **Opened:** 2026-09-19. **Status:** collecting.

## What counts

- Window opens with the accounting session of **2026-09-21** (sessions run 04:00 ET → 04:00 ET).
- A session is **observed** only if the relevance filter journaled `TipReviewGate` decisions on that weekday session.
  A holiday, an outage or a day with intake down does not count; the window simply runs longer.
- The fifth session's mark is its 03:59 ET point the next morning. Earliest due date: **2026-09-26, after 04:05 ET**.
  If `STATUS.json` says `NOT-YET`, wait — do not report on fewer than five.

## What is produced without anyone remembering

Windows task **`ZargarTipsFiveSession`** (daily 02:00 Pacific from 2026-09-26, runs a missed start when the machine is
next up) executes `C:\ProgramData\Zargar\tips-five-session.ps1` (source: `scripts/tips-five-session.ps1`, rev 2), which
only launches `python -m zargar.tools.tip_checkpoint_status` (S21-02, 2026-09-22): an observed session is a COMPLETED
accounting day with observe decisions (the current day never counts), ONE cutoff (`until` = last completed day) drives
the count and every report, the gate must be in observe, every report's exit code is checked, and STATUS is written
atomically. Read-only on the database. It overwrites, in `C:\ProgramData\Zargar\tips-five-session\`:

| file | tool |
|---|---|
| `STATUS.json` | `READY` (five completed observe days, every required report produced with non-empty output, the gate report's structured `eligible: true`, no gap) / `NOT-YET` / `INCOMPLETE` (a weekday gap, or the gate report itself says unresolved decisions or false negatives exist - `incompleteReason`) / `FAILED` (a report failed, was empty, or the structured verdict was not written; partial output kept as `<name>.failed`) / `INVALID` (gate not in observe, or a mixed-mode day); the structured `eligibility` block is embedded |
| `review-gate-prospective.md` | `tip_review_gate_eval --since 2026-09-21 --until <cutoff> --prospective` — resolution of every decision (complete / running / failed / unmatched / unevaluable), **Checkpoint eligibility**, management false negatives on complete reviews only, ALL human-review candidates |
| `scorecard.md` | `tip_scorecard --since 2026-09-21 --until <last completed day>` — marked change after model cost (primary), realized beside it, priced / unpriced / partial model runs, dispositions, how positions ended |
| `opportunity-dispositions.md` | `tip_outcomes --dispositions --since 2026-09-21` — every idea's disposition, avoidable misses apart |
| `intake-coverage.md` | `tip_outcomes --coverage --since 2026-09-21` — every raw message's class (failed / pending messages listed with their replay budget) |
| `review-model-cases.md` | `tip_review_gate_eval --model-plan` — how many captured review cases exist per case type (P2 readiness) |

Outputs live outside the checkout on purpose: a dirty runtime checkout blocks deployments.

## The report (one message, when `READY`)

1. Missed actions: management false negatives among observe skip-decisions (must be 0) and the human-read list
   (corrections, possible entries, mixed messages, deferred actions).
2. Operating costs: priced, unpriced and partial model runs as separate lines; review spend the filter WOULD have
   removed — a would-have, not a saving, while the filter is in observe.
3. Marked performance after costs (primary), realized after costs beside it; questioned fills and shadow books apart.
4. Opportunity dispositions and avoidable misses; cold-ticker rechecks (`SignalColdParkRecheck`) and the waits they
   replaced.
5. P2 readiness: captured cases per type against the 60-case quota. No paid run without the user's approval; the $35 budget is an estimate-based spending guard, not a guaranteed maximum.

Boundaries that do not move with this report: P1 stays observe (no automatic enforcement), P3 approval expiry
unchanged, P4 research only, P5 pending, P6 exit and overnight policies unchanged, no production-model change.

Since 0.8.34 `python -m zargar.tools.tip_weekly_review --since 2026-09-21 --until 2026-09-25` stitches the same
sources (plus overnight carry, knowledge ledger, shadow audit and the research-switch table) into one page - use it
as the appendix, not as a substitute for items 1-5. Decisions queued behind this report: P1 (gate), conversation
caching (`prompt_cache_scope`, measured -49.8%), and the values for the new exposure / source-budget knobs.

## If something is off

- Task missing or disabled → re-register from `scripts/tips-five-session.ps1` (header comment), or run the script by hand.
- Tools fail → run the four commands from `C:\Cursor\zargar\backend` with the runtime venv; they need only the database.
- After delivering the report: set **Status** above to `delivered <date>`, link the report, and unregister the task.
