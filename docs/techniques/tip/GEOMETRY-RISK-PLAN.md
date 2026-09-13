# Pre-entry geometry + risk sizing — design for review (2026-09-13)

**Status: PROPOSAL. Nothing here is built or active.** Requested by the user
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
2. **Risk reassessment when geometry changed.** Define
   `planned_risk = qty × expected loss at the analyst's stop`
   (for long options: `qty × (entry_premium − est. premium at stop)`,
   estimated by delta, floored at 25% of premium; for shares:
   `qty × stop_distance`). If the final stop widens the per-unit risk by more
   than `techniques.tip.geometry_resize_threshold_pct` (proposed 25%):
   - resize `qty` down to keep planned dollar risk ≤ the analyst's plan;
   - if the resize lands below 1 contract, the proposal is NOT auto-eligible:
     it goes to review with an explicit reason ("1-lot cannot honor the
     declared risk budget under the repaired stop") — a one-contract minimum
     never silently violates the budget;
   - every repair + resize is journaled (`TipGeometryRepaired` gains
     `phase: "pre-entry"`, `plannedRisk`, `finalRisk`, `resizedFrom/To`).
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
   - a post-fill stop change may only TIGHTEN risk, or widen it within the
     same `geometry_resize_threshold_pct` bound WITH a simultaneous
     proportional trim to preserve planned dollar risk;
   - every exception journals `TipGeometryRepaired phase: "post-fill"` with
     before/after risk; anything outside the bound goes to `needsAttention`
     instead of acting.

## Accounting (reviewer requirement)

Track separately per position: `plannedRisk` (at the final pre-entry plan),
`realizedLoss` (what actually happened), `stressLoss` (max theoretical).
Stops do not guarantee fills at the stop price; slippage between planned and
realized risk is a REPORTED quantity in the outcome table, not an assumption.

## Acceptance cases (to be tests before any code merges)

1. Wider repaired stop → qty resized down; planned dollar risk preserved.
2. Resize below 1 contract → proposal review-gated, never auto-approved.
3. Unchanged geometry → byte-identical behavior to today.
4. Fresh-quote retry re-runs validation; limit never raised.
5. Post-fill widen beyond the bound → needsAttention, no action.
6. Post-fill tighten → allowed, journaled.
7. Shares and options both honor planned-risk preservation.
8. Cash / concentration / premium caps still apply after resize.

## Out of scope

Changing the geometry rules themselves (what counts as "inside structure"),
option-pricing models beyond the delta estimate, and any change to live-book
behavior (Practice-first like everything else).
