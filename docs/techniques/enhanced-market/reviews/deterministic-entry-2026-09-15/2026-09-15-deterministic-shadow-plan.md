# EM deterministic entry: optional LLM evidence plan

Planning supplement, 2026-09-15. Code inspected at `067aaaf`; no production code, settings, jobs, orders or database state changed. This is an optional third delivery after the deterministic entry implementation and its release checks. It must not postpone removing the blocking fire-time model call.

## Recommended first release

Use the deterministic app decision for every supported EM trigger family. Leave fire-time LLM evidence **off** initially. Premarket planning may continue to use the LLM. Preserve fresh-quote refresh, contract selection, quantity calculation, final admission and all risk checks.

The optional evidence feature should initially be an after-close command over frozen decision records. That is the smallest implementation which genuinely removes model latency and resource competition from trading. If the team later wants intraday evidence, run the same bounded worker outside the engine process with its own concurrency limit. Do not build another general job platform.

This feature compares a historical LLM opinion with the actual deterministic decision. It does not claim to reproduce the exact old delayed trade or its profit.

## Why simply making the current call asynchronous is insufficient

At the reviewed commit:

- `backend/zargar/technique/arming.py::review_fire` reads live bars, the mutable trade contract and armed-plan context, builds a chart and computes facts, then calls the vision critic.
- `backend/zargar/technique/vision.py::VisionPipeline.run_critic` changes its supplied `TechniqueAnalysis` in place, including verdict, reasons and confidence.
- `backend/zargar/execution/planrunner.py` consumes that judgement for persisted setup/proposal data, admission and other downstream state. Existing failure accounting can pause a plan; current reviewer policies can kill or rearm a trigger.
- The existing exit-shadow recorder proves the useful pattern of pure bounded capture plus off-path recording, but it accepts live armed-plan references. Do not copy that ownership model into a late LLM judgement.

Therefore `create_task(review_fire(ap, tid, tracker, trade, judgement))` is explicitly unacceptable. Removing an `await` does not eliminate mutation, event-loop chart rendering, shared-client competition or late effects on sizing/proposals.

## Immutable decision record

Create one stable `decisionId` before the first irreversible entry action. It identifies a **fire attempt**, including refused attempts, independently of the eventual entry order ID. A repeated trigger after cooldown gets a new ID; restored pending orders retain the original ID. Link order IDs and later fills as separate lifecycle facts.

Extend the existing fire/entry decision journal rather than changing the source-note tables. Keep one versioned serialized evidence envelope or immutable reference set:

| Field | Required content |
| --- | --- |
| Identity | decision ID, technique, Practice book, session, run/plan identity and content hash, trigger ID and family, attempt ID, input schema version |
| Decision | deterministic policy/version, gate outcomes and measured values, effective thresholds, deterministic confidence/score if used, proposed direction/entry/stop/targets, final disposition |
| Market facts | bounded closed-bar slice or immutable bar snapshot references, exact bar-close cutoff, source and availability timestamps, underlying price and quote provenance, selected contract and quoted book, Greeks with their timestamps/unknown state |
| Plan facts | saved level/target provenance, source revision/availability when present, premarket assessment and effective plan revision |
| Timing | trigger bar source time, received time, decision start/end, quote-refresh start/end, final guard, submit and acknowledgement, using monotonic elapsed durations plus UTC timestamps |
| Economics | actual price/quantity/budget when available, intended geometry separately from actual entry, fees and fill IDs through later lifecycle links |
| Evidence status | off, requested, completed, skipped-capacity, incomplete-input, failed, cancelled or interrupted; never substitute missing evidence with an approval |

Use snapshots of what was knowable at decision time. A worker that starts later must not query the latest plan, note, market bars, quotes, settings or knowledge to fill gaps. If a field is missing, mark it unknown. No post-entry outcomes in the critic prompt. Keep final actual outcome links outside the input hash.

Reuse facts already computed for the deterministic decision. The trading path must not render charts, fetch model credentials, reserve a model slot, await an evidence write or download bars for this feature. If a bounded evidence payload cannot be captured within the existing journal budget, record the input as incomplete and skip the opinion. Mandatory existing order/decision journaling remains mandatory; optional research does not get a second synchronous database round trip before submission.

The final guard must continue to read current executable quotes/risk state after ordinary awaits. Its new result is an append-only stage of the same decision, not an overwrite of the earlier snapshot or permission to omit the guard.

## Optional evidence worker contract

Suggested small EM-owned modules:

- `backend/zargar/technique/entry_evidence.py`: frozen input/output schema, canonical hashes, render facts from snapshot, construct an isolated analysis object, one critic evaluation.
- `backend/zargar/tools/em_entry_evidence.py`: after-close command taking session/decision IDs and a maximum count; outputs append-only evidence records and a comparison report. No engine startup and no trading service object.
- Existing `events.py` and the EM report conventions: a distinct result event or research artifact keyed to `decisionId`.

Worker identity is `(decisionId, inputHash, policyVersion, promptHash, model, modelConfigHash)`. Retrying the same item must reuse its recorded completion. A changed model/prompt creates an explicitly distinct evidence version, not a silent overwrite. Late results can append evidence only and must not call arm, proposal, order, cancel, risk-halt, reprice, setup-promotion or plan-mutation APIs.

Keep existing source revision infrastructure unchanged. `source_revisions.py` jobs are keyed to author-note revisions and control transcription/extraction/board progress. A fire attempt is not a source-note processing stage; reusing those jobs would reconnect trading evidence to the lifecycle recently separated and fixed.

For the first optional command, one concurrent request, a finite maximum session count/cost, and a bounded wall-clock timeout are enough. Failure or interruption is an evidence outcome. Do not automatically restart the engine to resume evidence. No unbounded retry or guaranteed paid-call exactly-once claim: if the provider completed but its acknowledgement was lost, report an uncertain evidence attempt and require explicit rerun/versioning.

For a later intraday worker, keep bounded queue capacity, separate model concurrency/HTTP resources and bounded recording resources. A full queue or exhausted evidence budget drops/skips evidence visibly; entries and protective exits never await capacity, completion, retries or shutdown drain. CPU-heavy chart rendering belongs outside the engine event loop. Do not use entry fire tasks or `drain_fires()` as the worker lifecycle.

## Evidence output and interpretation

Each completed opinion records its input hash, model/config/prompt identity, elapsed queue/API/render/write timings, completion time, structured verdict/violations/confidence and token cost. The label is **LLM evidence only; no trading effect**. Keep deterministic confidence and LLM confidence in separate fields, including UI/API/proposal serialization and restore paths.

Report every eligible deterministic decision, including refused entries, unavailable contracts and dropped evidence. Compare disagreement by setup family, direction, decision-time data quality, delay and cost. Show coverage before win rates; exclude no cases silently.

Profitability report requirements:

1. Actual deterministic trades use matched fills and fees, with realized and open marked exposure separated.
2. For an LLM veto on an executed deterministic trade, report that trade's actual subsequent outcome as a disagreement case. Do not claim that omitting it would leave portfolio slot allocation and all later trades unchanged.
3. A faster-versus-delayed comparison needs recorded executable same-contract quotes with sizes at the relevant times. Freeze any simulated delay before evaluating outcomes; the asynchronous worker's finish time is not the historical old-path submit time.
4. Preserve failed/unfilled/partial orders, missed later winners due to capacity, and saved losers. Never use an underlying candle high as an executable option price.
5. Where a paired outcome lacks quote coverage or counterfactual quantity evidence, report unknown. Keep underlying-only proxy results clearly separate from net option performance.
6. Report trigger-receipt to submit p50/p90/p95, quote-refresh time, quote age at final guard, spread/fees and refused reasons. Separate chart/model time saved from provider/order latency still required.

Start with daily evidence over a frozen policy. Review the first several sessions for coverage and behavior; no small sample or rising win rate alone establishes an edge.

## Acceptance matrix for the main mode and optional evidence

These are focused implementation requirements, not tests to execute in this planning task.

| Case | Required result |
| --- | --- |
| Model off, unavailable, or client constructor raises | Deterministic eligible entry reaches ordinary final admission without touching the model client. |
| Model never resolves / evidence queue full / shared API rate-limited | Submit and reduce-only exit test barriers finish without releasing any LLM barrier; evidence outcome alone changes. |
| LLM returns kill or confidence 0 vs 1 | Same deterministic verdict, contract, quantity, stop, targets, timing path and proposal economics; no critic failure/veto counters, cooldown, rearm or halt mutation. |
| Chart rendering or evidence DB write blocks | Trading event loop and protective exits continue; no evidence-await dependency. |
| Every trigger family and side | Bounce, reject, breakout, breakdown and wedge-break use the declared deterministic policy in auto, proposal and alert routes. No hidden momentum-family model veto. |
| Current risk changes while quote refresh awaits | Existing final guard refuses as appropriate, regardless of a prior deterministic or LLM approval. |
| Source/plan/settings change after capture | Evidence input remains byte/hash-identical to its frozen version; newest values never enter that historical prompt. |
| Reentry, retry, and restart | Fire attempt IDs are distinct; order retries share the correct parent decision; restored work and partial fills retain mode/version and do not call the LLM. |
| Partial fill or pending exit while evidence completes | Only the evidence record changes; no extra entry, trim, cancellation, ownership or remaining-quantity mutation. |
| Duplicate/late/ambiguous result | Once-only local completion by evidence key; uncertain paid attempt is disclosed; never change trade or setup records. |
| Premarket and other desks | Premarket LLM still runs when requested; Tips/Team2/Cartel unchanged by EM defaults. |
| Missing quote/availability | Decision retains existing refusal/unknown policy; report does not invent a successful LLM or profitable counterfactual. |

For timing isolation, prefer deterministic barriers and call spies over fragile wall-clock thresholds. One load check can then measure engine-loop and submit latency under slow evidence work. Scope database tests to `zargar_test_codex`, sequentially in an exclusive window, through `scripts/test-codex.ps1`.

## Delivery sequence

1. Main implementation: deterministic fire policy, no model dependency across entry/retry/proposal/restore paths, explicit versioned decision identity and compatibility for existing arms. Preserve all execution safeguards.
2. Combined-tree verification and Practice rollout of the deterministic mode, plus latency and outcome reporting from existing execution facts. Fire-time LLM off. This is the user's primary change.
3. Optional separate evidence command/worker on frozen inputs. Ship after the deterministic path is accepted; default off until the separate isolation checks pass. Evidence completion is never a condition for placing a trade or finishing a release.

The user authorized the deterministic direction. No additional strategy approval is needed to write this implementation; the main handoff should still distinguish code acceptance, combined release verification and profitability evidence. Unsupported discretionary judgements must be stated as unimplemented or replaced by explicit versioned app rules, not described as proven equivalent to an LLM.
