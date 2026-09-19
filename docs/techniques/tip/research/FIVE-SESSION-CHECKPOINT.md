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
next up) executes `C:\ProgramData\Zargar\tips-five-session.ps1` (source: `scripts/tips-five-session.ps1`). Read-only on
the database. It overwrites, in `C:\ProgramData\Zargar\tips-five-session\`:

| file | tool |
|---|---|
| `STATUS.json` | `READY` / `NOT-YET`, observed-session count, the last completed accounting day |
| `review-gate-prospective.md` | `tip_review_gate_eval --since 2026-09-21 --prospective` — skip decisions, management false negatives, the human-read list |
| `scorecard.md` | `tip_scorecard --since 2026-09-21 --until <last completed day>` — marked change after model cost (primary), realized beside it, priced / unpriced / partial model runs, dispositions, how positions ended |
| `opportunity-dispositions.md` | `tip_outcomes --dispositions --since 2026-09-21` — every idea's disposition, avoidable misses apart |
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
5. P2 readiness: captured cases per type against the 60-case quota. No paid run without the user's approval.

Boundaries that do not move with this report: P1 stays observe (no automatic enforcement), P3 approval expiry
unchanged, P4 research only, P5 pending, P6 exit and overnight policies unchanged, no production-model change.

## If something is off

- Task missing or disabled → re-register from `scripts/tips-five-session.ps1` (header comment), or run the script by hand.
- Tools fail → run the four commands from `C:\Cursor\zargar\backend` with the runtime venv; they need only the database.
- After delivering the report: set **Status** above to `delivered <date>`, link the report, and unregister the task.
