# EM deterministic entry: architecture planning notes

Read-only source review pinned to `067aaaf`. This is an implementation design, not a code, settings, or activation change. Other desks, the runtime, and their files were not modified. Active documentation folder: `C:/Cursor/zargar-codex`, branch `codex/zargar-development`.

## Decision

Make deterministic admission the normal EM fire-time behavior for bounce, reject, breakout, breakdown, and wedge-break triggers. Keep the premarket plan/LLM workflow. Start with the fire-time LLM disabled. Optional evidence-only criticism can follow independently; it is not a prerequisite for removing the current wait. This removes the model's blocking opinion, not the closed-bar confirmation or market/risk checks. It also removes the existing model veto for momentum families, an intentional behavioral change to report by trigger family.

## Existing code and required intervention

| Source at 067aaaf | Verified behavior | Required change |
| --- | --- | --- |
| `backend/zargar/execution/planrunner.py:2602`, `_fire_rest` | Contract pick, deterministic hook, then awaited critic before entry | Add a small generic policy hook, defaulting to the present blocking behavior for every other desk. EM selects deterministic behavior. |
| `backend/zargar/technique/arming.py:90`, `analyze_fire` | Already model-free; delegates to `analysis_from_trigger` | Keep as EM analysis adapter; produce a versioned evidence/result snapshot from actual tracker confirmation. |
| `backend/zargar/technique/plans.py:818`, `analysis_from_trigger` | Declares breakout confirmation fields true from trigger kind; not independent live evidence | Do not use those convenience flags as proof of confirmation. Read actual tracker fired event/branch and frozen thresholds. |
| `backend/zargar/technique/arming.py:98`, `review_fire` | Fetches current bars, computes facts, renders chart, awaits model | Never invoke on the deterministic order path. Optional shadow must consume a frozen copy, not the live plan/trade objects. |
| `backend/zargar/technique/vision.py:384`, `run_critic` | Mutates analysis verdict/confidence/reasons in place | Preserve current semantics for premarket/legacy use; shadow gets a deep independent copy. |
| `backend/zargar/technique/arming.py:183`, `record_fire` | Persists the potentially critic-mutated analysis | Persist deterministic execution evidence; shadow opinion gets a separate later journal record. |
| `backend/zargar/execution/planrunner.py:2581`, `_critic_failed` | Errors can pause the plan after budget exhaustion | Never reached in deterministic/shadow mode. Shadow outages cannot consume execution failure budgets. |
| `backend/zargar/execution/planrunner.py:2649-2723` | Critic disposition, advisory bypass, kill/refire/cooldown/cap | Keep intact only for legacy blocking policy. Deterministic refusals have their own reason codes, never `critic_killed` or advisory override. |
| `backend/zargar/execution/planrunner.py:2810`, `_size_contracts`; EM `size_multiplier` | Actual auto sizing uses risk, equity, premium, Friday/0DTE and limits; no fire critic-confidence input | Preserve quantities and multipliers. Explicit regression prevents shadow confidence from entering sizing later. |

The existing confidence leak is into setup records, events, proposal context and displayed verdicts, not a demonstrated direct auto-sizing multiplier. Do not describe the change as removing a confidence sizing adjustment that does not exist in this tree.

## Concrete policy/API contract

1. Add an EM-only setting `techniques.enhanced_market.fire_decision_mode` with `deterministic` and `legacy_blocking` values. Normal EM default is deterministic; legacy is an explicit rollback route, not fallback on errors. Add a separate `techniques.enhanced_market.fire_shadow_enabled`, default false. Register exact keys; do not change global `execution.use_critic` or `execution.critic_mode` defaults.
2. Add a generic synchronous `fire_review_policy(ap, trade)` hook to `PlanRunner`. Its default returns the old policy. EM's override reads its explicit setting. Resolve once for each fire and include the resolved mode/version in its record. Generic code must not import EM policy or inspect EM technique IDs.
3. Under deterministic mode, per-arm `useCritic=true` does not resurrect blocking LLM calls, including restored and batch-created arms. Keep the old field parseable and expose it as a legacy compatibility field. New UI/API shows the effective deterministic mode and a separate optional shadow toggle. Under explicit legacy rollback, `useCritic` retains its old meaning. Do not let omission/default true silently opt into shadow either.
4. Expose effective fire mode, decision version and shadow setting in `TechniqueService.arm_options`, arm/list responses, and the EM arm dialog/status views. These fields must agree with execution even if a stored legacy arm says `useCritic=true`. Relevant UI: `frontend/src/components/technique/ArmDialog.tsx`, `ArmedTab.tsx`, and the frontend arm/config types.
5. Freeze a `deterministic-entry-v1` result on fire: run/session/trigger identity, actual tracker kind/direction, closed-bar source timestamp, decision timestamp, fired event/confirmation branch, effective threshold/settings version, verdict and machine-readable reasons, planned geometry. Append actual priced/sized geometry and all subsequent refusal reasons as the existing entry path progresses. Do not label a model opinion as the executed verdict.
6. The authoritative deterministic check must refuse its own failed/unknown mandatory condition independently of critic policy. A model's advisory mode must never permit a failed application rule.

## Rules to preserve without inventing a second strategy

Use `marketstructure/tracker.py` for touches, session windows, gap-day waits, direction, known-volume floor, gap states, false-break cap, and invalidation. Strict breakouts already require volume surge, decisive candle, and follow-through/hold. Existing range-break and gap-continuation exceptions must retain their current settings and be identified explicitly; do not accidentally tighten all momentum triggers to one strict branch.

Keep `_entry_gated`, final time guard, bounded fresh option refresh, spread/IV policy, sizing, quantity caps, remaining day budget, no-chase cap, R2, OrderManager and RiskGate in their present sequence. A deterministic pass means eligible to proceed through those checks, never automatic permission to submit. Exits are untouched.

Higher-timeframe fakeout/context and discretionary chart opinions do not yet have a universally quantified live predicate. List these as premarket context or not encoded; do not pretend the current trigger adapter implements every critic concern. Any new numerical filter is a separate versioned strategy change, not necessary to remove the LLM wait. This should be a narrow refactor of existing application authority plus explicit removal of model veto authority.

Entries still originate from the closed trigger bar. Do not turn quote callbacks into entry triggers, fabricate a pre-close opportunity, or equate tracker modeled fill price with an actual attainable order fill.

## Optional shadow, after the main patch

Freeze copies of source bars/facts/trigger, quote/contract, analysis and decision identity at the original fire. Enqueue without awaiting research work. Render charts and call the model outside the entry task using bounded workers; dropped/full/failed work is recorded as missing research. Do not call current `review_fire` unchanged in a background task: it reads later live bars and mutates live analysis. Shadow cannot veto, resize, rearm, pause, change stops, change setup validity, consume critic kill/failure budgets, or acquire the execution lock. Results append with the immutable fire ID and original cutoff, even if the trade has since closed. No mandatory terminal tracker or new research database is needed for initial LLM removal.

## Restore and migration

Persist or expose resolved mode/version separately from legacy `useCritic`. On new deployment, existing EM arms use the explicit EM mode at the next new fire without replaying old entries or rewriting historical opinion/disposition. Inventory paused/critic-capped plans; do not auto-unpause or clear historical counters. Do not clear `refire_at` indiscriminately because cooldowns can represent other state. If a carried critic-only cooldown needs release, produce an explicit narrowly scoped migration record; a next-session rollout avoids most of that issue. Active trades keep their original management and exit policy.

No batch rebuild, plan re-review, account migration, helper rewrite or source-ingestion work is necessary for this feature. Perform the existing combined-release checks on latest main and activate for EM Practice only. Real-money scope is not expanded by this planning request.

## Bounded deliveries and decisive checks

**Delivery 1:** policy hook, deterministic main path, accurate evidence/config/UI, optional shadow off. A stub critic that raises if invoked must not be called on any EM trigger family, auto/proposal path, or restored `useCritic=true` arm. Assert an entry can settle while a deliberately unresolved reviewer future remains unresolved. Every failed mandatory rule still prevents executor calls. Replay has no paid calls. Existing other-desk blocking/retry behavior stays identical.

**Delivery 2, optional:** isolated shadow snapshots/worker and comparison report. Demonstrate contradictory/late/error shadow output cannot change orders, sizing, setup validity, plan status or cooldowns; snapshot timestamps predate later bars; saturation never delays entries/exits. This delivery does not hold up Delivery 1.

Test preserved bounce/reject and strict/exception momentum paths, quote failure and changed final price/budget, disarm/flatten during awaits, restore compatibility, proposal content, and premium-stop independence. Run only relevant suites through the isolated test wrapper in an exclusive database window. No runtime changes were made while drafting this note.

Measure source-bar-close to intent/submission/fill p50/p95, refreshed-quote ages, admissions/refusals, fees/net outcome and worst excursions by family. Keep actual fills separate from hypothetical legacy alternatives; removing 15-20 seconds of model wait is expected latency improvement, not proof of net profit.
