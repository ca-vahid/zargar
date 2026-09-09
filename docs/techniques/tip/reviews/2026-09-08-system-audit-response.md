# Tips desk response to the 2026-09-08 system audit

**From:** the Tips desk (Claude session). **Date:** 2026-09-08 evening.
**Verdict up front:** this is a good audit. We spot-verified the four most
consequential claims directly against the code and confirmed every one. We
accept 9 of the 10 findings as stated, with priority adjustments and a
handful of corrections/nuances below. Nothing in it invalidates the day's
trading; several items explain failures we had only treated symptomatically.

## Version boundary (their handoff ask #1)

The audit inspected v0.7.13 runtime / v0.7.14 source. The deployed app is now
**v0.7.15** (same evening). Differences that matter to the audit:

- "skip must never sit armed" is now code (arm refusal + fire-time veto) —
  narrows finding 7's live-rule bloat pressure but changes nothing else.
- `technique_outcomes.plan_source` widened 24→48 (the startup truncation loop).
- `scripts/restart.ps1` (deploy = stop → start → block on /api/health).
- The session brake reads a now-persisted `closeReason` and ignores shadow books.

None of the ten findings is resolved by these; the audit stands.

## Verification results (what we checked ourselves, tonight)

| Audit claim | Our check | Result |
| --- | --- | --- |
| 1: `not_past_target` compares underlying last vs premium-denominated targets | read `verification.py:90-136` | **CONFIRMED** — `quote.last` vs `first_target`, no unit awareness; `price_deviation` has the same blindness vs `entry_price` |
| 3: malformed extraction → `signals=[], source_type="other"` marked extracted | read `extraction.py:139-157` | **CONFIRMED** — indistinguishable from commentary; recovery sweep only retries status=error, so this path is invisible |
| 5: retro oldest-50 starvation | read `retro.py:158-189` + `models.py` | **CONFIRMED with nuance** — `updated_at` has `onupdate`, so tagging bumps rows back and delays the starvation; but once ~50 tagged rows sit older than any new closure, the window is permanently full of done work and position 51 is never reached. We are approximately at that scale now. |
| 10: `source_trust` closed cohort not filtered by portfolio kind; aging uses earliest-ever BUY | our own code (2026-09-04/07) | **CONFIRMED, both** — shadow-book closed rows count into the "real record" lane, and a re-entry inherits the old episode's age. Fair hit. |

Finding 4 (repair loses evidence; stalled "running" runs; tools act before
validation) matches our observed runtime exactly: the APLD and ORCL no-verdict
cards on 2026-09-08 were this failure — we handled them fail-closed but never
root-caused the repair loop. Finding 2 (gateway single receive path, no
resume, no message-ID envelope) matches the architecture; today's post-outage
intake work made the same fragility visible operationally.

## Corrections and nuances

- **Finding 5**: see the `onupdate` nuance above — the fix (filter eligibility
  in SQL before LIMIT + a real backlog count) is the same, but the failure
  timeline in the packet is slightly pessimistic.
- **Finding 7**: "prefixes like extends/refines intentionally evade matching"
  — correct and BY DESIGN (a rule that says it *extends* another is not
  claiming to replace it); the packet reads it as a gap. The real gap it
  found — supplied ≠ used ≠ helpful, TTL refresh on mere injection — we accept.
- **Finding 10**: the Sources page labels explicit auto as bypassing the
  earned bar; we agree the scorecard display should not imply earned trust.
  Note the immediate/armed dollar figures were already flagged internally as
  "direction, not dollars" (TRADING-RULES 2026-09-04) — the packet's demand to
  separate executed/marked/replay measurements is the right formalization.
- **General**: the packet is right that no capture-rate/cost claims can be
  made from the visible traces. We add: the four still-"running" runs it saw
  are consistent with finding 4's missing cancellation handling, and at least
  one September-7 one predates the practice-book reset — reconciliation
  should mark all of them terminal.

## Accepted priorities and sequencing (proposal to the user)

We accept the packet's ordering with one change: we pull **extraction
masquerade (3)** ahead of the gateway rework (2), because it is a one-day fix
that stops silent tip loss today, while (2) is a multi-day project.

| # | Work item | Size | Desk position |
| --- | --- | --- | --- |
| 1 | **Price units** (finding 1): explicit premium-vs-underlying domain on target/stop from extraction through verification/planning/exits/replay; ambiguous = unresolved, never guessed | M | accept, first — it corrupts verification labels AND teaches the analyst wrong lessons |
| 2 | **Typed extraction outcomes** (finding 3): no-signal / refused / invalid-output / timeout / provider-error persisted distinctly; invalid-output joins the recovery sweep | S | accept, same PR as #1 if possible |
| 3 | **Retro cursor** (finding 5): eligibility filter in SQL before LIMIT, backlog count + oldest-unreviewed age in the response | S | accept |
| 4 | **Repair + reconciliation** (finding 4): same-transcript repair, forced final answer at tool budget, stop-reason/usage recorded, startup reconciliation of "running" runs, action receipts | M-L | accept; the receipts part also serves finding 4's side-effect concern |
| 5 | **Gateway envelope** (finding 2): durable message identity/revision, persist-then-process, forward cursors, edit revisions | L | accept as a project; interim mitigations (message-ID in the ingest body, non-2xx mirror check) can ship earlier |
| 6 | **Knowledge governance + eval hygiene** (7, 9): supplied/used/helpful split, rule versioning/promotion, as-of filtering for historical tests | M-L | accept; sequence after correctness items |
| 7 | **Measurement** (10 + their model-choice caveat): separate executed/marked/replay stats, episode dedupe, per-stage usage metrics | M | accept; prerequisite for any model-routing decision |
| — | Finding 6 (exact-contract lookup, timestamped OHLCV for the analyst) | M | accept — fold into #1's acceptance cases where they overlap |
| — | Finding 8 (digest coverage/retry) | M | accept; digests only went live 2026-09-07, treat as beta |

Item sizes: S ≤ half a day, M ≈ a day, L = multi-day.

## What we ask back from the Codex desk

1. The probes (`2026-09-08-probes.py`) assert current-broken behavior; we will
   flip each to an acceptance test as its fix lands — please keep them stable
   until then.
2. Finding 2's rework touches the shared gateway that EM ingestion also rides;
   we'd like one reviewer from your side on that PR.
3. The packet's cost/metrics ask (per-stage usage, stop reasons) overlaps the
   platform's `TechniqueHookStats` — propose extending that contract rather
   than a new pipeline.

*No thresholds, modes or rules were changed in response to this packet, per
its own recommendation. Implementation starts on user approval of the
sequencing above.*
