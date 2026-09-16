# EM deterministic entry — implementation plan for the dev team

**Decision: make deterministic application rules the main live EM decision mode. Keep premarket LLM review. Remove the fire-time LLM from entry authority and the entry path. Optional LLM reviews may be retained as separate evidence; they must never delay or alter an order.**

This implements the user's direction in the dedicated EM review task. No additional strategy-direction clarification is needed. Initial activation is for the existing EM Practice workflow; this does not authorize live-account auto-trading, another desk's policy change, or changes to exits/risk limits.

This document is the implementation handoff, not a claim that the production code has already changed. No runtime settings, armed plans, orders or production files were changed while preparing it. Source inspection is pinned to `067aaaf6be9d13495b9341ea732976fb20f76561`. Implement on the team's branch from the then-current integrated base, preserving other desks' work; do not deploy this old inspection commit as a release target.

## 1. What we are changing, and why

The current live path detects a trigger deterministically, picks an instrument, then awaits a vision critic before proceeding. On September 15 the 15 recorded critic traces took **14.13–21.99 seconds, averaging 17.57 seconds**. All fifteen final dispositions were advisory. That is measured waiting time, not proof of a dollar loss or proof that all fifteen would have filled sooner.

The default `momentum_only` critic policy still permits a model veto on breakout/breakdown/wedge-type entries. The new mode removes that live model authority too; this is an intentional policy change requested by the user, not a claim that those entry sets will be identical. Their existing deterministic confirmation requirements remain.

Most of the needed machinery already exists: `TriggerTracker`, deterministic EM plan construction and grading, option selection, quote quality, sizing, budget/capital limits, never-chase logic, R2, RiskGate and the final dispatch predicate. Use these functions instead of building a second strategy engine or translating prompt sentences into arbitrary new thresholds.

**Removing a call is not enough:** the critic currently mutates the live `TechniqueAnalysis` and replaces the fire verdict/confidence. That mutation reaches persisted setups and proposal context. Auto sizing at the inspected revision does not directly use critic confidence; do not invent such a dependency in the change description. Nonetheless, no optional future model output may mutate any executed decision, sizing input, setup validity or proposal.

## 2. Firm scope and defaults

| Concern | Required behavior |
|---|---|
| Main live mode | `deterministic`, all supported EM trigger families. |
| Fire-time LLM | Off in the first implementation. No prompt/chart preparation, model request, model semaphore, timeout wait or model-based veto on this path. |
| Premarket LLM | Existing sheet promotion, analyst review and preparation remain available and unchanged. Their approved plans become inputs to deterministic execution. |
| Optional critic evidence | Default off. Preferred first implementation is an after-close command/worker over frozen decision snapshots. It has no trading authority. |
| Other desks | Keep their current behavior. Generic shared hooks must default to the existing legacy path. |
| Trigger timing | Continue to use the existing completed trigger-timeframe bar. Removing the critic wait does not introduce intrabar entries. |
| Risk and execution | Existing quote source/freshness/spread/IV, sizing, cash/exposure, day-loss, session, chase, expiry, live-auto and final-dispatch checks continue to apply. |
| Exits | Existing stops, targets, partials, flatten timing, open-position management and protective exits remain unchanged. |
| New qualitative filters | Separate versioned research work; no new bounce-confirmation, trend, gap, volume or risk thresholds hidden in this latency change. |

Proposed authoritative settings:

```text
techniques.enhanced_market.fire_decision_mode = deterministic | legacy
  default after this release: deterministic

techniques.enhanced_market.fire_evidence_mode = off | after_close
  default: off
```

Keep the existing `critic_mode` and `useCritic` fields for legacy compatibility and other desks. They must not reactivate a blocking critic when EM's authoritative mode is deterministic. Unknown/invalid policy configuration should refuse new entries with an explicit policy error, never fall back silently to an LLM. Legacy mode is an explicit operational rollback, not an automatic fallback when a deterministic decision refuses.

Do not add a global `execution.*=deterministic` default that changes Team2, Tips or Cartel. Evidence collection for this work is separate from the already enabled quote-based P-02 exit observations.

## 3. Architecture: one execution decision owner

Use a generic runner hook, for example `fire_review_policy(ap)`, whose default preserves existing behavior. EM overrides it using its own authoritative setting. Keep EM method knowledge out of shared execution code.

Required flow:

```text
Approved plan + actual completed-bar tracker transition
  -> freeze attempt identity, plan/threshold version and trigger evidence
  -> deterministic setup decision
  -> record the decision using the normal journal owner
  -> choose/reuse contract through existing instrument policy
  -> bounded current-quote acquisition and final repricing/sizing
  -> existing admission / R2 / chase / risk checks
  -> existing final synchronous dispatch guard
  -> order, or explicit refusal/defer outcome

Frozen evidence record --after close, optional--> LLM evidence result
                                               (no path back to trading)
```

Contract selection can retain its existing relative placement if that avoids an unrelated refactor; the non-negotiable condition is zero model dependency before order/refusal. Do not duplicate quote fetching or the recently approved bounded quote refresh. Preserve necessary order write-ahead journaling and venue I/O; deterministic does not mean those operations disappear.

### Execution object versus model evidence

- `FireJudgement` and the setup/proposal persisted for execution must originate from deterministic evidence in deterministic mode.
- Do not pass live `ArmedPlan`, `Trade`, `TriggerTracker`, `FireJudgement` or `TechniqueAnalysis` references to a background critic.
- Do not implement this as `create_task(review_fire(ap, ..., j))`: the existing method reads current live state and its model pipeline mutates the analysis object.
- A late model refusal, confidence change, target suggestion or exception cannot cancel/reprice/resize a trade, invalidate a setup, arm/disarm a plan, alter a proposal or change a stop.
- Deterministic refusals must not enter the legacy `critic_advisory` branch. They remain refusals even if the obsolete critic-mode setting says advisory.
- Use separate deterministic disposition and evidence-review fields. Never label an app decision `critic_killed` merely because it refused.

## 4. Deterministic v1: explicit rule map

The first version should formalize the rules already responsible for execution and their evidence. It is not a new set of curve-fitted trading filters.

| Judgment | Deterministic v1 treatment |
|---|---|
| Plan/session identity, direction and complete entry/stop/target geometry | Validate the saved approved plan and its real tracker instance. Bad required geometry or expired/invalidated state refuses new entry. |
| Level existence | Use saved source/level provenance and the plan's structure window. Absence from a later redetected map alone is not proof the original level was fabricated. |
| Bounce / rejection at a level | Preserve the current tracker touch/volume and invalidation semantics. Do not quietly require a new reversal candle, reclaimed close or retest. Such a filter is a separate strategy experiment. |
| Normal breakout / breakdown | Preserve the actual close, volume/decisiveness and follow-through path defined by the current tracker and threshold snapshot. Removing a model veto does not remove these checks. |
| Wedge, gap-continuation or range-break branch | Preserve the branch's existing enablement and declared confirmation requirements. Record which branch fired; do not force a disabled experiment on or turn an intentional shortcut into strict follow-through without an explicit policy change. |
| Opening gap, trade windows, invalidation and false-break limit | Use current deterministic functions and their exact configured semantics. |
| Quote/executable price, spread, IV, expiry, option feasibility | Use the existing contract policy, refresh/rejudge and final quote guard. No invented replacement quote or relaxed threshold. |
| Risk, quantity, capital and actual exit-dependent R:R | Use the existing sizing/admission/RiskGate chain on current inputs. Retain zero quantity as a valid refusal. |
| “Too choppy,” higher-timeframe fakeout, emerging opposing shelf, chart nuance not presently encoded | Record as not encoded/diagnostic where relevant. Do not mark it as a passed app check, invent a threshold, or ask the model synchronously. Propose an exact separately versioned rule only after its inputs and behavior are defined. |
| Missing required execution evidence | Use explicit `unknown_required`/existing data-refusal handling; do not guess or call an LLM as fallback. |
| Missing optional context | Record unknown, retain existing treatment. In particular, do not convert a previously advisory missing-volume/context observation into a new hard filter. |

**Important implementation detail:** `analysis_from_trigger` currently constructs some breakout confirmation booleans from the trigger kind. Those DTO fields are not independent proof that confirmation occurred. Derive decision evidence from actual `TriggerTracker` transitions, source bars and the threshold/branch used. Missing evidence must not become `true` merely because the trigger is named breakout.

The companion rule-map document identifies existing coverage and qualitative gaps. Retiring discretionary momentum vetoes must appear explicitly in the release note. Do not claim exact behavioral equivalence to the LLM.

## 5. Pure decision contract and provenance

Put EM's policy in a small technique-owned module, e.g. new `backend/zargar/technique/entry_decision.py`. Prefer reusing existing pure predicates; do not recalculate a competing tracker state machine.

Suggested public contract:

```python
def evaluate_entry(snapshot: EntrySnapshot, policy: EntryPolicy) -> EntryDecision:
    """Pure: no I/O, model access, settings reads, clock reads or state mutation."""
```

The caller supplies time, policy and evidence. The frozen result should contain:

```text
decisionId / fireAttemptId       unique per attempt, not only per run+trigger
decisionMode                    deterministic
decisionVersion                 deterministic-entry-v1
ruleVersion / thresholdsHash     actual rules and parameters used
planId / planVersion             approved plan identity, including replacements
triggerId / triggerFamily        actual family and confirmation branch
signalBarStart / signalBarClose  source bar identity and completion time
sourceTime / receivedTime        when evidence existed and when the app received it
verdict                         allow | refuse | defer
reasonCodes                     stable codes, with facts/reference IDs
checks                          pass | fail | unknown | not_applicable,
                                with entry_required or diagnostic authority
inputHash                       immutable evidence identity
```

`allow` means the setup-level rules permit proceeding to the existing order checks; it is not an executor bypass or guarantee of a fill. Later quote/risk refusals remain separately journaled. Avoid calling the planned underlying entry an actual fill, and keep option premium units separate.

Capture enough bounded source data to reproduce the decision: required closed bars/features, tracker transition, plan/threshold versions, premarket approval provenance, and available quote/account context. Reuse existing persisted snapshots where valid. Heavy facts/chart rendering belongs outside the latency-sensitive path. Do not export raw runtime data into the reviewer worktree.

### Refusal and retry behavior

- Preserve structural invalidation and plan-expiry behavior.
- Use the existing entry retry/refire contracts for transient quote/data conditions; no new order after an ambiguous submission or while an earlier entry remains working.
- Missing LLM evidence or model failure is never a defer/refusal reason in deterministic mode.
- New deterministic attempts never increment critic failure/kill counters, pause after model failures, or acquire model-driven cooldowns.
- Do not blindly clear historical `refire_at`, paused statuses or risk halts. Classify critic-only legacy state during migration; retain unrelated risk/execution protection and review ambiguous cases explicitly.

## 6. Optional LLM evidence — default off, after-close first

The first release must be usable without this feature. After-close review is preferred to immediately launching a parallel model task: it removes chart-render/model-resource contention from the trading session as well as the direct await.

The evidence worker consumes a serialized immutable decision snapshot, not live objects or freshly queried later bars. Its prompt must exclude the later price path, actual profit and eventual order outcome when testing whether the original setup looked valid. Outcome comparison happens afterward in a separate report.

Evidence output:

```text
decisionId, inputHash, plan/rule version
model and prompt version
asOf / enqueuedAt / startedAt / completedAt
reviewOutcome = completed | unavailable | timed_out | budget_skipped | invalid
modelOpinion / modelConfidence / citedEvidence
cost/usage, error, disagreement category
authority = evidence_only
```

The worker must not import or receive order-placement, arm/disarm or settings-write capabilities. Use bounded concurrency, timeout and a separate configured evidence-call budget. A stopped worker or absent API key produces an evidence status, never a trading status change. Preserve the deterministic record and append the evidence rather than rewriting it.

Reuse existing journal/research conventions. Do not reuse EM source-ingestion jobs keyed to Discord note/revision IDs for trading-attempt ownership, and do not build a general job platform for this change. A scoped after-close command over recorded decisions is sufficient initially. If live asynchronous evidence is requested later, require the same isolation and bounded resources, with all rendering off the engine event loop.

## 7. Premarket behavior remains separate

The normal sheet -> analyst review -> approved/no-setup -> arm sequence continues. The analyst may supply chart interpretation and a structured proposal before trading; its result must still satisfy deterministic plan validation.

Show the distinction in the UI and daily report:

- **Premarket planning:** AI-assisted, where enabled.
- **Live entry decision:** deterministic, with policy version.
- **Optional later AI review:** evidence only, or off.

Do not turn off the source transcript/extraction pipeline or premarket analyst by disabling a global model setting. Do not imply an LLM decision is instantaneous, identical to app logic, or required to keep an already approved plan tradable.

## 8. Settings, existing arms and UI migration

The 41 existing September 16 arms were created with legacy `useCritic=true`. Simply changing the default for new arms is insufficient.

1. Resolve the authoritative EM mode at the new fire-attempt boundary and pin that mode/version for that attempt. New and restored arms must resolve the same policy.
2. In deterministic mode, old `useCritic=true`/`momentum_only` values cannot call the model or override an app refusal. Do not rewrite historical records as if they were deterministic.
3. Return `effectiveFireDecisionMode`, rule version and evidence mode through arm-options, preflight and armed snapshots. Store the effective policy with each decision/order trace.
4. Replace EM's “AI double-check before auto-buying” control with a clear deterministic-mode display and optional later-evidence control. Other desks' controls stay as they are. A missing LLM key must not disable EM deterministic execution for an already approved plan.
5. Migration preview lists active plans, effective old/new policy, critic-only paused/cooldown states and any unsupported required evidence. Do not duplicate arms or auto-unpause plans.
6. Change mode at a controlled boundary with no in-flight entry decisions. Existing positions retain their original fills, targets, stops, exits and owners. No mode toggle is allowed to re-fire a consumed historical trigger.
7. Keep `legacy` available as an explicit, journaled rollback. Do not toggle global `trading.mode` or live-auto gates as part of this migration.

## 9. File-by-file implementation map

Paths below identify the current code components; implement in the EM team's own worktree, not by editing the running checkout in place.

| Component | Work |
|---|---|
| `C:/Cursor/zargar/backend/zargar/execution/planrunner.py` | Generic execution-review policy hook; deterministic/legacy branch isolation in `_fire_rest`; distinct decision/disposition; snapshot identity and policy trace; preserve `_enter`, retry, restore, write-ahead and final guard. |
| `C:/Cursor/zargar/backend/zargar/technique/arming.py` | EM policy override; use deterministic rules and actual tracker evidence; `record_fire`, proposal and chat output use executed deterministic decision; remove critic mutation from the fast mode. |
| `C:/Cursor/zargar/backend/zargar/technique/entry_decision.py` (new) | Pure EM snapshot/decision contract and assembly of existing checks. |
| `C:/Cursor/zargar/backend/zargar/marketstructure/tracker.py` | Expose/retain actual confirmation evidence if not already accessible. Preserve the shared state machine and existing branch/threshold semantics. |
| `C:/Cursor/zargar/backend/zargar/technique/plans.py` | Stop treating analysis DTO booleans as measured proof; maintain compatibility while sourcing decision evidence from the tracker. |
| `C:/Cursor/zargar/backend/zargar/technique/vision.py` | Preserve premarket path; optional evidence runner gets its own copied analysis/input objects. No in-place mutation of execution-owned objects. |
| `C:/Cursor/zargar/backend/zargar/settings_service.py` | Authoritative EM mode and evidence defaults, validation and legacy mapping. |
| `C:/Cursor/zargar/backend/zargar/api/routes_technique.py` | Effective-policy metadata in arm options/preflight/armed APIs; retain compatible legacy request fields with explicit effective behavior. |
| `C:/Cursor/zargar/backend/zargar/events.py` and `research/events_contract.py` | Versioned deterministic-decision/evidence records; hooks return facts, runner owns trading-event journaling. |
| `C:/Cursor/zargar/frontend/src/types.ts` | Effective mode, policy version, deterministic reasons and separate evidence fields. |
| `C:/Cursor/zargar/frontend/src/components/technique/ArmDialog.tsx` | Correct EM controls/defaults, including restored legacy configuration. |
| `C:/Cursor/zargar/frontend/src/components/technique/ArmedTab.tsx` | Show “deterministic” and evidence status, not misleading “critic on” for non-blocking/off modes. |
| `C:/Cursor/zargar/frontend/src/pages/SettingsPage.tsx` | Separate premarket AI settings from live execution authority. |
| `C:/Cursor/zargar/backend/zargar/tools/em_fire_evidence.py` (optional new) | After-close snapshot-only LLM evidence command, separate delivery. |
| `C:/Cursor/zargar/backend/zargar/tools/em_profitability.py` | Group outcomes by execution-policy version and decision ID; separate actual fills, evidence opinions and modeled alternatives. |
| `C:/Cursor/zargar/docs/techniques/enhanced-market/TRADING-RULES.md` | Record user-authorized deterministic main mode and momentum-veto retirement; preserve previous policy history. |
| `C:/Cursor/zargar/docs/PLATFORM-RULES.md`, `docs/ARCHITECTURE.md` | Record the generic hook, unchanged other-desk defaults and the evidence-only boundary. |

## 10. Acceptance matrix — prove behavior, not just settings

Use real entry/dispatch boundaries where needed, fake provider/executor/model seams, and the isolated database through `scripts/test-codex.ps1`. No paid model requests or real orders are required for acceptance.

| Case | Required result |
|---|---|
| Valid deterministic bounce/reject, model unavailable | Eligible setup reaches normal quote/risk/dispatch flow; no model client or chart-render call. |
| Valid deterministic breakout/breakdown/wedge | Proceeds only after its actual configured tracker branch confirms; no discretionary model veto. |
| Incomplete confirmation/invalidated trigger | Deterministic refusal/defer persists; advisory legacy settings cannot override it. |
| Enabled range/gap continuation variants | Their configured branch requirements remain intact; disabled branches remain disabled. |
| Legacy veto mode | Explicitly selected legacy mode retains its old veto/failure behavior. |
| Old restored arm with `useCritic=true` | Effective deterministic mode still makes zero live model calls. |
| Model entry point is a never-resolving sentinel | Deterministic order/refusal completes without awaiting it. Also test an occupied model semaphore and slow renderer. |
| Late negative/positive critic result | Cannot change order count, quantity, limit, setup validity, proposal, owner, stops or plan state. |
| Repeated model failures in evidence mode | Evidence errors only; no critic failure budget, pause, kill cap or refire change. |
| Missing required deterministic input | Explicit required-evidence outcome, no guessed check or LLM fallback. |
| Unknown optional qualitative input | Correct unknown/diagnostic record; no newly invented gate. |
| Price/spread/budget changes during quote fetch | Existing size/admission behavior recomputes/refuses correctly; zero unaffordable forced contracts. |
| Quote/policy changes after earlier risk check | Final synchronous guard still refuses before executor submission. |
| Disarm, expiry, quiescence, pending/uncertain order, concurrent trigger | Existing lifecycle/ownership controls still prevent unintended entry or duplicate order. |
| Restart with held or partially filled position | Position/exit ownership restored unchanged; no replayed entry and no recovered LLM result altering the trade. |
| Proposal/alert/manual/add/retry paths | No EM path silently restores LLM authority; existing human proposal approval remains where required. |
| No LLM credentials | Existing approved EM plans remain executable deterministically; premarket unavailability is reported separately. |
| Other desks | Tip/Team2/Cartel reviewer policies, sizing and exits unaffected. |
| Snapshot replay | Same frozen inputs/rules produce the same deterministic output and reason codes; a kind label cannot manufacture confirmation. |
| Premarket/source review | Still operates under its own settings; disabling fire evidence does not disable analyst preparation or ingestion. |

Suggested new test groups: `test_em_deterministic_entry.py`, `test_em_deterministic_entry_integration.py`, and optional `test_em_fire_evidence.py` under `C:/Cursor/zargar/backend/tests`. Reuse the actual OrderManager/PlanArmer fixtures already used in the quote-refresh and final-dispatch reviews. Keep pure semantic tests fast; do not mirror implementation branches without testing a trading invariant.

Required affected regression coverage includes current EM execution/admission/quote-refresh/final-guard files, arming/restore, API/ingest preparation, research event contracts and shared-runner cross-desk cases. Run sequentially in an exclusive `zargar_test_codex` window. Document exact SHA/commands/results; report known unrelated failures separately.

## 11. Performance and profitability measurement

Measure timestamp boundaries separately: completed signal bar -> engine receives bar -> deterministic verdict -> contract/quote ready -> final admission -> order submission -> acknowledgment/fill. Record model calls on the live entry path as **zero**. Report local decision p50/p95/p99 under a pinned fixture/load; the target is bounded millisecond-scale local computation, not a promised subsecond complete broker transaction.

The decisive latency test is the never-resolving model sentinel with a completing deterministic entry/refusal. Normal quote/provider/DB/venue timing remains separately visible. Do not recover speed by deleting risk checks, using delayed quotes or bypassing order journaling.

At each close, compare policy-version cohorts on attempts, valid entries, refusals, paid spread/fees, actual entry movement, realized net P&L, open exposure and exit outcomes. Faster entry can improve or worsen price and can admit trades the older delayed/veto path did not take. Retain those additional losses and forgone winners in the comparison.

If optional LLM evidence runs after close, its measured response time cannot be used to fabricate an earlier live fill timestamp. A hypothetical delayed-price comparison requires contemporaneous historical executable evidence; otherwise label it unknown. Do not exclude refused/no-fill decisions from the evidence sample or call disagreement proof that either evaluator is better.

## 12. Delivery order and completion criteria

### Delivery A — deterministic main mode (required now)

Implement the authoritative EM policy, pure rule/evidence contract, runner branch, persisted decisions, restore/API/UI handling and acceptance tests. Keep fire evidence off. Preserve premarket LLM and all existing trade/risk policies. Publish the rule map and explicit momentum-veto retirement with the combined SHA.

**Done means:** all supported EM fire families have app-owned live decisions; no fire-time LLM or renderer/model resource can delay them; existing/restored arms use the intended mode; deterministic refusals cannot be downgraded by legacy advisory logic; shared desks remain unchanged. Return migration preview, tests, latency evidence and release/settings verification. Use the normal release owner/protocol at a safe boundary and verify the existing arms/positions/helpers afterward. Do not require another broad strategy debate or a completed optional evidence system to ship this requested main mode.

### Delivery B — optional frozen evidence (may follow)

Add the after-close evidence command and separate output/reporting only if the team/user wants to retain LLM criticism. Defaults stay off until collection is intentionally enabled. This delivery has no authority to trade and cannot become a prerequisite for Delivery A.

### Subsequent method research — explicit rule additions

Use recurring disagreement categories to propose exact deterministic features, inputs, thresholds and missing-data behavior. Evaluate each separately with frozen, as-of cohorts. A new trend/fakeout/chop/reclaim requirement is a new strategy rule, with its own version and evidence—not a hidden part of removing the LLM wait.

## 13. Team handoff text

> Please implement deterministic live entry as EM's main mode, following this plan. Keep premarket LLM planning, but remove the fire-time model from every EM entry's decision authority and latency path. Reuse existing tracker and risk/execution rules; do not introduce untested trading filters or claim full LLM equivalence. Start with optional critic evidence off, and make restored arms obey the new authoritative mode. Return the code, focused test/latency results, migration preview and exact integrated SHA for the normal release process. Optional later LLM review must consume frozen snapshots and remain evidence-only. Entries/exits/risk limits and other desks stay within their existing policies.

Supporting implementation notes in this folder: `2026-09-15-deterministic-entry-architecture-notes.md`, `2026-09-15-deterministic-rule-map.md`, and `2026-09-15-deterministic-shadow-plan.md`. This primary document resolves delivery/default choices; the notes are supporting detail.
