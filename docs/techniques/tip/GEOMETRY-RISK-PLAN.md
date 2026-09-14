# Pre-entry geometry + risk sizing — design for review (2026-09-13)

Final-pass corrections (C95-02/03/04/05, combined tree PR #95): risk accounting carries
provenance (executed vs hypothetical shadow plan); `widen_stop` is strictly durable before
exposure; the trim attempt is bound to the order intent and an attempt without an ACK holds,
never re-trims; a review-only spread never auto-opens; the contract multiplier comes from the
OCC identity (adjusted = unknown = review).

Readiness-review fixes (G91-01..06, head `3ffd6ce`; combined tree PR #95): enforce never admits
by absence (a failed/missing plan is review-gated; the FINAL refusal at submission reverts an
automated approval); shares are sized at the executable limit; Greek per-field age, a fresh
non-delayed underlying reference and an explicit contract multiplier are required (unknown =
review); the bracket is built from the FINAL plan; submission recomputes the whole plan; the
gate is Practice-scoped; the trim-first exception carries a durable attempt identity, recovers
an existing trim instead of trimming twice, re-reads unknown outcomes and re-checks the actual
residual before any widen; `widen_stop` validates the actual position under the guard and
persists before exposing; accounting is wired into the analyst positions tool and the retro.

**Status (2026-09-14): BUILT on branch `claude/tips-geometry-rev2` (PR open
for implementation review), NOT active.** `techniques.tip.geometry_gate`
defaults to `shadow` — every tip proposal computes and journals its risk
plan (`TipGeometryRepaired phase: pre-entry`, `enforced: false`) while
sizes and stops stay exactly as before; `enforce` is a separate, reviewed
activation. Code: `techniques/tip/geometry.py` (pure: budget, unit-loss
estimator `delta-linear-v1`, sizing invariant, submission revalidation,
post-fill decision + trim-first reducer, accounting), wiring in
`approvals/proposals.py` (`_pre_entry_geometry`, `_admit_geometry` for
`via=auto` and the stale-quote retry), `signals/service.py` (a review-gated
card never auto-approves), `techniques/tip/lifecycle.py`
(`run_geometry_exception`, `reconcile_geometry_exceptions`), and the shared
`execution/positions.py` additions `Managed.extras` / `set_extras` /
`widen_stop` (PLATFORM-RULES change log). Tests: `tests/test_tip_geometry_rev2.py`
(the ten acceptance cases + budget authority, pure) and
`tests/test_tip_geometry_wiring.py` (engine wiring on the sim broker).
Budget B = `techniques.tip.risk_budget_per_tip` when > 0, else
`techniques.tip.risk_pct` % of the book's equity — approved policy knobs,
never the model's quantity. Requested by the user
(2026-09-11: "validate geometry and sizing before entry, with explicit,
bounded post-fill exceptions") and the independent reviewer (next-priorities
review, item 1). Motivating incident: SPCX 2026-09-10 — the adoption gate
re-placed the analyst's 151.1 stop at 144.5 ("inside recent structure")
AFTER the fill, silently turning a ~1.6% invalidation into a ~5.9% one while
the size stayed justified by the narrower stop.

## Principle

The trade that fills must be the trade the analyst evaluated. Geometry is
finalized BEFORE capital commits; the size is derived from the FINAL stop;
any post-fill repair is a bounded, journaled exception — never a silent
redefinition of the risk.

## Flow

1. **At proposal creation** (`create_from_signal`), run the geometry check
   (`check_exit_geometry`) on the analyst's exit plan against structure —
   the same rules that today run at adoption:
   - wrong-side / penny targets: dropped (as today), recorded on the proposal;
   - invalid or inside-noise stop: re-placed at structure — but now BEFORE
     entry, producing the FINAL stop.
2. **Risk budget enforced on EVERY widening** (revised per review,
   2026-09-13). The authoritative dollar budget **B** comes from approved
   desk policy (`techniques.tip.risk_budget_per_tip`, resolved via `rt()`) —
   never from the model's proposed quantity. Units are explicit: for options,
   `unit_loss = (entry_premium − est_premium_at_stop) × multiplier` where
   `multiplier` comes from the CONTRACT METADATA (100 for standard OCC;
   currency = the contract's), estimated by delta (long call: +delta ×
   stop_distance; long put: |delta| × stop_distance), floored at 25% of
   premium×multiplier — an ENGINEERING assumption, versioned on the plan,
   never called a guaranteed loss cap (gamma/vol/time excluded); the full
   premium-at-risk (stress loss = premium × multiplier × qty) remains an
   independent constraint. For shares, `unit_loss = stop_distance`.
   **Invariant on every proposal: `qty × final_unit_loss ≤ B`** — enforced
   regardless of how small the widening is (the materiality threshold
   `geometry_resize_threshold_pct` only classifies review-vs-log severity,
   it never waives the invariant). Round qty DOWN; cash / premium / notional
   / concentration caps apply after; if no quantity satisfies B, NO
   automatic entry. Missing/stale Greeks → no estimate → review, never a
   guess. A 1-contract minimum never silently violates B. Every repair +
   resize journals `TipGeometryRepaired` `phase: "pre-entry"` with
   `plannedRisk`, `stressRisk`, `finalRisk`, `estimatorVersion`,
   `resizedFrom/To`.
3. **Persist the full risk plan on the proposal**: entry ref, final stop,
   targets/fractions, quote quality (source/age at pricing), qty, planned
   risk, stress loss (premium to zero for options). The approval path and
   the triage read THE SAME persisted plan — no recomputation drift.
4. **Revalidation triggers before submission**: a refreshed quote that moves
   the admissible limit, or a stale-quote retry, re-runs steps 1–2 against
   the new price (the never-raise limit rule stands; cash/concentration/
   never-chase caps unchanged).
5. **Post-fill exceptions (bounded, explicit):**
   - allowed ONLY for positions that already exist when a defect is found
     (restored legacy positions, adopted partial fills);
   - a post-fill stop change may only TIGHTEN risk immediately. A WIDEN
     requires an EXECUTION-STATE SEQUENCE, never assumed atomicity (review
     condition): (1) submit the proportional trim FIRST with the tighter
     stop still armed; (2) the wider stop takes effect ONLY after the trim
     is confirmed filled; (3) a rejected / partially filled / unknown-outcome
     trim leaves the tighter stop in force (partial → recompute the residual
     widen bound from actual filled qty; unknown → reconcile before any stop
     change); (4) each transition persists write-ahead and is reconciled at
     restart — a restart between steps resumes from the persisted state;
   - every exception journals `TipGeometryRepaired phase: "post-fill"` with
     before/after planned risk and the trim order ids; anything outside the
     bound raises `needsAttention` — which is a signal to a person, not
     itself protection: the tighter stop remains armed meanwhile.

## Accounting (reviewer requirement)

Track separately per position: `plannedRisk` (at the final pre-entry plan),
`realizedLoss` (what actually happened), `stressLoss` (max theoretical).
Stops do not guarantee fills at the stop price; slippage between planned and
realized risk is a REPORTED quantity in the outcome table, not an assumption.

## Acceptance cases (to be tests before any code merges; expanded per review)

1. Wider repaired stop → qty resized down; `qty × unit_loss ≤ B` holds.
2. A SMALL widening below the materiality threshold still triggers resize
   when B would be breached (the threshold never waives the invariant).
3. Resize below 1 contract → proposal review-gated, never auto-approved.
4. Unchanged geometry that ALREADY satisfies B → behavior preserved;
   unchanged geometry that already VIOLATES B → flagged, not grandfathered.
5. Fresh-quote retry re-runs validation; limit never raised.
6. Contract multiplier applied in unit loss AND stress loss; puts use
   |delta|; missing/stale Greeks → review, no estimate invented.
7. Post-fill widen: trim-first sequence — rejected trim keeps tight stop;
   partial trim recomputes the bound from actual fills; unknown outcome
   reconciles before any stop change; restart between steps resumes.
8. Post-fill tighten → immediate, journaled.
9. Shares and options both honor B; cash/concentration/premium caps apply
   after resize.
10. Planned vs stress vs realized loss recorded separately per position.

## Out of scope

Changing the geometry rules themselves (what counts as "inside structure"),
option-pricing models beyond the delta estimate, and any change to live-book
behavior (Practice-first like everything else).
