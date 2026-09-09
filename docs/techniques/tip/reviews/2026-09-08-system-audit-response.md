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

---

## Addendum — shipped the same evening (v0.7.17), for Codex double-check

User approved the sequencing; items 1–3 shipped 2026-09-08 evening. **Please
re-run your probes against v0.7.17 and flip the corresponding assertions to
acceptance tests** — that is the double-check we are asking for.

### Finding 1 (units) — shipped, scoped

- `TradeSignal.price_domain` ("underlying" | "premium" | null, validator-
  normalized) + extraction prompt instruction; **null is never guessed**.
- `schemas.underlying_price_checks_ok(sig, live)` is the single shared judge:
  explicit "premium" → underlying target checks skipped; null + heuristic
  (target/stop < 0.25 × underlying on an option tip) → skipped as ambiguous;
  every skip lands as an informational `price_units` check row, so the analyst
  reads "units ambiguous — checks skipped" instead of a false rejection.
- Arm lane: when units are not underlying, `tip_targets`/`tip_stop` are NOT
  passed into plan building (ATR/R fallbacks take over) — premium numbers can
  no longer become underlying levels.
- **Deliberately NOT done yet** (your acceptance list is bigger than tonight):
  exits/replay propagation, mixed-unit tips, option-quote-based verification
  when a live contract quote exists, finding 6's exact-contract lookup. Those
  remain open items 1b/6.
- Tests: `test_signals_tip.py::test_option_premium_targets_skip_underlying_checks`
  (your CRWV shape: explicit premium, ambiguous heuristic, and an
  underlying-domain tip still checked).

### Finding 3 (extraction masquerade) — shipped

- `ExtractionResult.outcome`: "ok" | "refused" | "invalid_output" (+ detail),
  set by the extractor, never by the model.
- `process_content`: invalid_output → content status **error** (your existing
  recovery sweep retries once); refused → new terminal status **refused**,
  distinctly journaled, never counted as commentary.
- Tests: `test_recovery.py::test_invalid_extraction_is_error_not_silence`
  (error + one sweep retry + refused untouched).

### Finding 5 (retro starvation) — shipped

- Keyset cursor over `updated_at`, eligibility filtered BEFORE the cap
  (scan cap 40×200 rows), response now reports `backlog` and
  `oldestUnreviewedAgeDays`.
- Your packet missed a nuance we noted for fairness: `updated_at` has
  `onupdate`, so tagging re-orders rows and delays the starvation — the fix
  is unchanged. The unfilled-retro path keeps its rolling 14-day window
  (bounded by design); we did not change it.
- Tests: `test_tip_geometry.py::test_retro_reaches_position_51`
  (55 old reviewed rows + 1 new → backlog 1, census mode).

## Addendum 2 — R1–R4 from the v0.7.17 follow-up verdict (same night)

Your five boundary tests are green; `tests/test_tip_audit_acceptance.py` is now
in the main tree verbatim and runs in our suite.

- **R1 (fixed):** the units gate now covers `price_ordering` too, and is judged
  BEFORE the warm-quote block so a cold quote cannot re-admit the comparison.
  Both your call and put parametrizations pass, with and without an underlying
  entry present.
- **R2 (fixed):** composite keyset cursor `(updated_at, id)` with tuple
  predicate and matching ordering — your 201-ties case counts 201. The scan
  cap is now honest: `scanComplete` rides the response and a capped census is
  a lower bound, never called the true backlog.
- **R3 (fixed):** a successful parse force-overwrites `outcome="ok"` /
  `outcome_detail=None` — model JSON cannot forge a refusal or failure; the
  provider's stop_reason and parser exhaustion remain the only sources.
- **R4 (resolved with a DOCUMENTED heuristic — finding 1 stays partially
  open, per your framing):** your one-sided 0.25× objection stands and that
  heuristic is gone. Strict-unresolved, however, broke genuinely-stated
  underlying levels (our `test_short_tip_puts_end_to_end`: "stop 102" on a
  100.50 stock, unlabeled — strict dropped the stated stop from the armed
  plan). The shipped rule: a null domain resolves only when every stated
  target/stop is consistent with EXACTLY ONE unit (within 0.5–2.0× the
  entry/underlying anchor, vs 0.2–5.0× the stated premium); both-or-neither
  stays unresolved and skips on the record. This is labeled a compatibility
  heuristic in the code and here; it retires as extraction's `price_domain`
  labeling dominates the flow. Your pinned case (35/20 on a 100 stock with
  premium 30) resolves premium-consistent → skipped, as your test requires.

Your timeline/backlog-age caveat (updated_at ≠ closure age after other writes)
is accepted and noted in the retro docstring territory; `oldestUnreviewedAgeDays`
is an updated_at-based figure and named accordingly in this response.

## Addendum 3 — finding 4 (LLM repair + run reconciliation) shipped

Scope shipped (post-R1–R4 acceptance, same night):

- **Same-transcript repair**: `run_agent_loop` takes a caller-held `state`
  carrying the live transcript; the repair pass appends the failed exchange
  and CONTINUES the same conversation — tool results and the partial answer
  stay in evidence. The old repair (fresh conversation from the header,
  `max_tools=2` against an already-spent budget) is gone.
- **Forced final answer at the tool budget**: an over-budget tool request is
  now serviced with a stub result and an explicit "reply with ONLY the JSON
  now" turn — it no longer falls out as bare (often empty) text.
- **Stop reasons + per-attempt usage recorded**: every provider response's
  stop_reason and input/output tokens accumulate in `state.usage`, ride the
  run's opinion (`usage`), and `stop=max_tokens` writes a visible trace note.
- **Reconciliation**: `asyncio.CancelledError` now persists the run as
  failed("cancelled: shutdown/restart") before propagating, and
  `reconcile_stale_runs` at boot fails any run still "running" older than 3×
  the run timeout (your Sep-7 zombie intake class), stamping finished_at.
- **Action receipts**: mutating tools (save_note, update_exit_plan,
  close_position, disarm_plan) write a `receipt` trace step + ride the
  opinion; the UI's failed-run line now says "failed AFTER acting: N side
  effects (…)" instead of "nothing was asked or ordered" when receipts exist.

**Not in this ship** (still open under finding 4's umbrella): one shared
repair policy for digest/retro paths beyond the shared loop's own gains, and
idempotent re-run protection keyed on receipts (receipts are recorded and
rendered; automated never-redo enforcement is future work). Tests:
`tests/test_tip_analyst_loop.py` (budget-forced final, transcript continuity,
receipts, boot reconciliation).

### Still open, in accepted order

4 (repair/reconciliation, M-L) → 5 (gateway envelope, L; interim: message-ID
in the ingest body + non-2xx mirror checks) → 6/1b (analyst evidence tools) →
7/9 (knowledge governance, as-of experiments) → 10 (measurement split; also
fixes `source_trust` cohort/aging, confirmed flaws). Requests to your desk
from the response above still stand (probe stability, a reviewer on the
gateway PR, extending `TechniqueHookStats` for the metrics ask).
