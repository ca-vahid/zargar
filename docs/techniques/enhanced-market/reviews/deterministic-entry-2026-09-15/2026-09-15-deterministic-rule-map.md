# EM deterministic entry: rule map and first implementation boundary

Prepared 2026-09-15. Read-only code review pinned to `067aaaf`; the working checkout remains on `codex/zargar-development`. This note supports the full implementation plan. No settings, orders, database records or production code changed; no paid model calls or tests were run for this mapping.

## Finding

Most of the entry decision already exists as application code. `PlanArmer.analyze_fire()` constructs a deterministic assessment from the trigger. The shared runner then awaits a separate vision critic before continuing to quote refresh, sizing and admission. Removing that awaited dependency does not require replacing the planning system or its existing risk controls.

There is one important behavior change to disclose. Under `momentum_only`, negative critic opinions are already advisory for bounces and rejections, but can veto breakouts, breakdowns and wedge breaks. A deterministic main mode removes this discretionary veto for those momentum families. It must record that policy change explicitly; it cannot claim to reproduce every qualitative model judgment.

## Code map at the reviewed commit

| File | Existing responsibility |
| --- | --- |
| `C:/Cursor/zargar-codex/backend/zargar/technique/arming.py:89` | Deterministic `analyze_fire`; immediately following `review_fire` assembles chart, facts and live context for the LLM. |
| `C:/Cursor/zargar-codex/backend/zargar/technique/vision.py:384` | Critic prompt: fakeouts, higher timeframe, volume, chop, R:R and chase; model mutates the supplied analysis. |
| `C:/Cursor/zargar-codex/backend/zargar/technique/plans.py:817` | `analysis_from_trigger` adapter creates an analysis DTO from a planned trigger. |
| `C:/Cursor/zargar-codex/backend/zargar/marketstructure/tracker.py:245` | Existing live/replay trigger state machine: gap, stop invalidation, touch/break, volume, confirmation, false-break exhaustion. |
| `C:/Cursor/zargar-codex/backend/zargar/marketstructure/candles.py:79` | Existing decisive-candle calculation. |
| `C:/Cursor/zargar-codex/backend/zargar/technique/plans.py:420` | Plan validity, saved levels, structural stops, target construction and grading for each family. |
| `C:/Cursor/zargar-codex/backend/zargar/execution/planrunner.py:2599` | Fire pipeline and awaited reviewer, then recording and entry admission. |
| `C:/Cursor/zargar-codex/backend/zargar/execution/planrunner.py:2933` | Bounded entry-quote refresh; keep after analysis immediately before reprice/sizing. |
| `C:/Cursor/zargar-codex/backend/zargar/execution/planrunner.py:3241` | Final dispatch guard; remains authoritative alongside RiskGate. |
| `C:/Cursor/zargar-codex/backend/zargar/technique/rulebook.py` | Effective threshold source and rule IDs. Values in this file are defaults, not proof of current runtime settings. |
| `C:/Cursor/zargar-codex/docs/techniques/enhanced-market/TRADING-RULES.md:74` | Prior decision and limits of the fire-time critic evidence. |

## What can be expressed deterministically now

| Judgment the critic is asked to make | Existing measurable authority | First deterministic mode |
| --- | --- | --- |
| Is this a valid planned setup? | Saved trigger validity, level provenance, session/plan identity, arm policy. | Reuse those facts and the existing arm boundary. Do not replace them with a model confidence score. |
| Did price reach the bounce/rejection level? | Tracker intersection with the configured level band, direction-aware stop invalidation. | Preserve current touch semantics. The band permits proximity, not necessarily an exact-price touch; report the actual geometry. |
| Is bounce/rejection volume sufficient? | Tracker relative volume from prior-session profile, or its existing intraday fallback; configured floor. Unknown keeps the trigger watching. | Reuse the same computation and unknown handling. Do not convert missing volume into zero, pass, or a new threshold. |
| Is a normal breakout/breakdown/wedge break confirmed? | Close through level; volume surge; `is_decisive`; follow-through count and holding the level; false-break exhaustion. | Require evidence of the tracker path that actually fired, with its effective settings. Mirror direction for breakdowns. |
| Is the candle weak or rejecting? | Candle body, size, leading-wick ratio and direction already feed normal-break confirmation. | Reuse for that family. Do not add a reclaim/hammer requirement to bounces or rejections in this release. |
| Is the session/window/gap eligible? | Tracker window, gap-void/past/through checks and configured gap-day wait; final runner gate. | Preserve effective experiment switches and final wall-clock checks. Keep `gap_unchecked` visible; missing opening evidence is not a fabricated gap assessment. |
| Is there enough reward for the intended exit? | Planned R2 plus post-price/quantity admission against actual production exit rung. | Keep both. Do not use model-reported R:R or the farthest target when production exits earlier. |
| Is the entry chased? | Existing level/entry semantics, price caps and final entry checks. | Reuse unchanged. A fresh quote still cannot override the cap. |
| Are contract conditions acceptable? | EM rejudge spread/IV; current quote provenance/age, finite uncrossed book, RiskGate, quantity/budget checks. | Keep unchanged. Quote refresh is a separate bounded network dependency, not an LLM decision. |
| Is the stop inside chop? | Plan-time sideways-trend/ATR stop-width test for bounce/reject; runtime failed-break counter for break families. | Preserve these specific tests. They do not implement every subjective form of live chop. |
| Is the old level absent from today's detector? | Saved level provenance intentionally survives changing live detection windows. | Never reject solely for that absence. Preserve build-session provenance and trigger identity. |
| Are the interpolated trim targets fabricated? | The saved production target ladder deliberately interpolates method trim levels. | Never reject merely because a trim lies between chart levels. Keep target basis in evidence. |
| Is short direction itself disallowed? | Effective long-only/side policy; reject/breakdown use puts as appropriate. | Preserve the actual side policy. Never add a generic long-only restriction through this refactor. |

## Distinct family contracts

1. **Bounce, long:** level-band interaction plus measurable configured volume, eligible window/gap state, intact stop and existing admission. No new completed-close reclaim requirement. The method explicitly says not to wait for visual confirmation (T4.2).
2. **Reject, short:** direction-aware mirror of bounce. No new rejection-candle requirement. Current short-policy and contract expression remain intact.
3. **Breakout, long:** normal path requires direction-correct close through resistance, configured surge, decisive candle, and configured follow-through that holds the level.
4. **Breakdown, short:** direction-aware mirror of normal breakout.
5. **Wedge break:** saved valid wedge geometry and target/stop construction, then the existing break confirmation path. Do not call a generic breakout a proven wedge.
6. **Existing range-break/gap-continuation variants:** the tracker has explicit configured shortcuts. Range-break can fire on the break close with the volume floor; loose gap continuation can do likewise. Preserve their effective configuration and record `confirmationVariant`, `rangeBreak`, and continuation provenance. Do not silently demand normal follow-through, and do not report that those shortcuts passed tests they bypassed.

The shared `analysis_from_trigger` DTO currently assigns `breakout_volume_confirmed`, `breakout_decisive_candle`, `breakout_follow_through`, and `breakout_holds_level` from the trigger kind. Those fields are not adequate evidence for the new decision record. Read the actual tracker transitions and measurements; emit `not_applicable`/`not_evaluated` for deliberately bypassed checks.

## Judgments not completely covered by existing code

The critic can describe a newly formed opposing shelf, a lower-timeframe break failing against higher-timeframe context, weakening momentum/divergence, or broad live chop. Plan-time grades, confluences, and the existing false-break rule capture parts of this, not all of it. In particular, a positive higher-timeframe confluence is not proof that a new hard higher-timeframe veto exists; the current plan builder often uses it for grading rather than validity.

Do not turn any of these phrases into an untested entry blocker just to claim a complete model replacement. For the first deterministic policy, mark the unmatched judgment `not_evaluated` in research evidence and preserve established hard rules. State explicitly that the momentum-family model veto is retired, rather than pretending those judgments were reproduced. The user has asked for application rules as the main execution authority; this first version is a clear, bounded policy rather than a model imitation.

A later version may define an exact new rule with bounded inputs, known availability times, existing indicator functions where possible, an unknown-data policy, and a prospective comparison. Two separate examples are a bounce reclaim confirmation and an opposing-level room test. Both change trading behavior and timing, so neither belongs implicitly in the latency-removal patch. No new profitable threshold is inferred here.

## Minimal first implementation

Add an EM-owned pure `evaluate_entry(snapshot)` or equivalent hook that emits a versioned structured decision. Reuse the tracker and existing guards instead of forking their mathematical definitions. The snapshot contains the session/plan/trigger identity, effective configuration, immutable trigger path and measurements, last completed bars, planned geometry, and the availability timestamp for every input used. Evaluation must perform no network call, render no chart, and await no model or research persistence.

Return the decision (`eligible`, `hold`, or `refuse`), policy version, confirmation variant, rule results and reason codes. `eligible` means the deterministic setup checks passed; it is not permission to bypass contract selection, fresh quote checks, risk, current plan ownership or final dispatch. Keep the existing persisted trade/intent record as the authoritative execution record; optional research evidence must not delay protective exits.

Suggested reason categories: `trigger_not_fired`, `plan_not_current`, `stop_invalidated`, `window_ineligible`, `gap_ineligible`, `volume_unknown`, `volume_below_floor`, `break_not_confirmed`, `level_exhausted`, `unsupported_confirmation_variant`, followed by the existing contract/risk refusal reason. Do not collapse them to `critic_killed` or treat technical missing evidence as a proven bad strategy.

For legacy restored arms, reuse the persisted tracker and plan state. If a new evidence field cannot be reconstructed, record that as unknown with its provenance; do not silently claim confirmation or silently revive the synchronous LLM. The full plan should choose a clearly documented migration/default behavior for legacy state before activation.

The fast policy must be separate from optional LLM evidence. Model output gets its own later event tied to the immutable fire snapshot and may never mutate the authoritative analysis, order, quantity, target, stop, cooldown, refire count, pause state, or recorded deterministic verdict. A timed-out or failed background opinion cannot consume the old critic-failure budget or pause an otherwise eligible plan.

## Acceptance cases that test the rule map

- Each of bounce, reject, breakout, breakdown and wedge break has one valid and one failed/unknown mandatory-evidence case, with direction and reason preserved.
- A bounce inside the existing tolerance band can pass without a bullish/reclaim candle when all original checks pass; a separate test proves a close through the stop still invalidates it.
- Normal momentum confirmation waits for its existing surge/decisive/follow-through requirements; missing volume remains unconfirmed. Mirrored puts use the correct price direction.
- Configured range-break/loose-continuation paths retain current behavior and record bypassed conditions honestly. The same input with those switches off takes the normal path.
- A non-re-detected prior-session level and interpolated trim targets are not rejected merely for those facts.
- A missing live higher-timeframe feature is marked unevaluated, not converted into agreement or a new veto.
- Existing window/gap-day wait, failed-break exhaustion, quantity-dependent R2, never-chase, risk caps, quote source/age/spread and zero-size refusal still decide identically when quotes and state are held fixed.
- A negative, late, failed or hanging LLM evidence call cannot change the deterministic decision or delay entry; mutating its copy of the analysis cannot affect the original.
- An LLM key/provider is absent: deterministic mode still works and premarket LLM behavior remains independently configured.
- Restored arms produce the same decision version and effective policy as fresh arms; no model outage can increment execution failure/pause state in deterministic mode.

This mapping is based on inspected code and saved project findings. It is not a profitability forecast. Historical calls can explain disagreements, but comparison of actual net results requires prospective executable quotes, costs, timing and all admitted/refused opportunities.
