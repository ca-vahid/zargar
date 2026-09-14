# KB-06 — execution-integrity pause (design, NOT built) — 2026-09-13

Status: **design for review.** The clock-based `adoption_killswitch` (one
stop-out inside 5 minutes of adoption pauses every later tip auto-adoption for
the session — `TipAutoPaused`) stays exactly as it is until this replacement
is built, tested against the acceptance cases below, and reviewed. No setting
and no knowledge note changes with this document.

## Why the current rule is the wrong shape

The reviewer's finding (v0762 review, "KB-06 policy recommendation"): a fast
stop on a trade whose final geometry, sizing, quote evidence and fills were
all valid is a *clean losing trade*. Treating it as proof that every later
adoption must be refused confuses "we lost quickly" with "our execution was
broken". The daily-loss halt already owns the first; nothing owns the second.
Today's gate also has two mechanical defects the reviewer named:

- it is evaluated in ONE place — the signal auto-approval path
  (`signals/service.py` ~line 2106) — so arms, re-arms, proposal retries and
  the recovery sweep's triage never ask it;
- it decides on elapsed wall-clock time and the word "stop" in an exit
  reason, not on structured evidence.

## The replacement: pause on an integrity incident, never on speed alone

An **incident** is a persisted, journaled record that the automated entry
path produced or acted on something we cannot trust. It is opened by
evidence, scoped to what the evidence implicates, and released only by
explicit resolution.

| Observation | Behaviour |
|---|---|
| Fast stop; final entry geometry, sizing, quote evidence and fills all valid | Journal a diagnostic (`TipFastStopDiagnostic`). No incident. Ordinary loss limits decide independently. |
| Invalid geometry / risk plan detected BEFORE entry | That proposal is rejected or sent to review before ordering (geometry rev 2's validate → repair → resize → revalidate). Repeated systemic failures on one entry path (N in a session, N configurable) open an incident for that path. |
| A FILLED trade violated geometry or budget, used invalid evidence (stale mark, unconfirmed premium stop, chain/delayed quote where fresh was required), or has duplicate / unreconciled executions | Open an incident: pause affected NEW automatic entries; reconcile and repair before explicit release. Exits and reduce-only management continue. |
| A fast stop whose necessary evidence is MISSING or ambiguous | Open a `hold` incident: affected new automatic entries wait pending reconciliation. Missing evidence is not proof the trade was valid. |
| A shared component failure (feed, quote service, executor) touching several books / techniques | Widen the incident scope ONLY to the identified shared failure, with the scope journaled explicitly. |

### Incident record

Table `tip_execution_incidents` (or a platform table if another desk needs
it — decide at build time, not here):

| Field | Meaning |
|---|---|
| `id` | new_id |
| `opened_at` / `resolved_at` | UTC |
| `kind` | `integrity` (evidence of a defect) or `hold` (evidence missing) |
| `scope` | `{technique, portfolio_id?, source?, entry_path?}` — the narrowest set the evidence implicates |
| `cause` | structured code, e.g. `geometry_violation_filled`, `stale_mark_exit`, `duplicate_execution`, `unreconciled_fill`, `evidence_missing` |
| `evidence` | references only: position id, order ids, execution ids, journal event ids, run ids — never prose alone |
| `release_criteria` | what must be true to resolve (e.g. "executions reconciled", "geometry repaired and revalidated") |
| `resolver` | `user` or a named reconciliation job; `resolution` text |

### Who must ask

Every automated entry decision, not one: signal auto-approval, arm and
re-arm, proposal retry (`_maybe_retry_stale_quote`), the recovery sweep's
self-decisions, the shadow-arm morning job. A single `engine.entry_paused(scope)`
predicate (sibling of `trading_halted`) answers from the open incidents. Exits,
flattens and reduce-only management never consult it.

### Detection inputs (structured, never substring matching)

- Actual entry/exit execution timestamps from `executions`, not row
  `created_at/updated_at`.
- Exit reason CODES on the position record (`stop`, `premium_stop`,
  `time`, `target`, …) plus the evidence string already carried by fresh-mark
  and confirmation-v2 exits.
- `TipGeometryRepaired` / geometry-violation events, budget-gate outcomes.
- Execution reconciliation results (duplicate exec ids, fills without an
  order intent, quantity mismatches).

### Persistence and restarts

An open incident survives restart and date rollover — it is a row, not a
per-session flag. It is never cleared by a new session, a version change or
the loss halt resetting. Resolving one incident does not touch a loss halt,
and a loss halt lifting does not resolve an incident.

## Acceptance cases (all must exist as tests before the switch-over)

1. A valid, budget-compliant trade stopped out in 90 seconds does NOT open an
   incident; a diagnostic is journaled; the next adoption proceeds.
2. A filled trade whose final geometry violated the gate opens an `integrity`
   incident scoped to the technique+book; the next adoption on that book is
   refused with the incident id on the record.
3. A fast stop with missing quote evidence opens a `hold` incident; adoption
   waits; supplying the evidence (reconciliation job) resolves it.
4. A paused arm / re-arm / proposal retry cannot enter while the incident is
   open (three separate tests, one per path).
5. Protective exits, premium stops and flattens execute while an incident is
   open.
6. Restart with an open incident: still open, still enforced.
7. Resolving an incident does not clear a separate daily-loss halt; lifting a
   halt does not resolve the incident.
8. A shared-component incident pauses exactly the journaled scope and nothing
   else.

These complement geometry revision 2's ten acceptance cases. None of this is
a claim that either policy improves expected returns; it is a claim about
what evidence justifies refusing to trade.

## Relationship to the disputed kill-switch rules

The two `rule` notes describing the clock-based switch (`dbfd8177…`,
`7e72fd7f…`) are flagged as DISPUTED through the journaled path so no audit
can merge or expire them; they stay in the rulebook, marked, until the
replacement is built and the human decides which policy the rulebook states.
