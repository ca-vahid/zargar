# Corrected EM deterministic delivery — 8e641e9

**The live deterministic-entry corrections are accepted in this bounded review. Final release sign-off remains conditional on the unfinished database-backed and solo arming groups.** Two non-trading reporting/evidence follow-ups remain below. They are not new entry-policy blockers; keep optional after-close LLM evidence off until its integrity check is corrected, and keep refusal-rate comparisons provisional.

Reviewed SHA: `8e641e9e7fd86f5b29beef339ad25401cd4c1a86`, correction commit `163e4a6`, integrated main `cd4c1c6`. Reviewed in `C:/Cursor/zargar-codex/.cache/em-deterministic-corrected`, detached. Primary folder remains `C:/Cursor/zargar-codex`, branch `codex/zargar-development`. No production/runtime/settings/arm/position changes were made.

## Independent verification

- All original reviewer reproductions and prior cases: **31 passed in 1.59s**.
- Added full after-close path: real fire -> persisted decision snapshot and copied bars -> actual chart render -> actual critic result processing with fake model transport: **passed**. The test destroys the current tracker/bar objects before the review and still completes from the captured record with usage and evidence-only authority.
- Changed bars under an unchanged declared hash: **failed** the expected refusal assertion. The two-case end-to-end group reports **1 passed, 1 failed in 3.89s**.
- Additional refusal-census case: **1 failed in 0.27s**.
- These tests use no real database/provider/model requests or running engine. They ran sequentially through `scripts/test-codex.ps1`. The supplied 118-case broader result is team-reported, not independently rerun here.

The inspected response document still contains `__FINAL_SHA__`, `__MAIN_SHA__`, result placeholders and pending DB/arming outcomes. Replace them with the actual final values in the completed handoff. A placeholder is not a recorded verification result.

## What is closed

| Area | Verified correction |
|---|---|
| DE-01 windows | Uses the tracker's candidate/touch window semantics without adding a second confirmation-window gate. |
| DE-01 geometry | Saved entry and observed fill proxy are separate; saved geometry no longer fails merely because confirmation passed TP1. |
| DE-01 rules | Uses the actual tracker thresholds/window flag and includes the missing confirmation parameters in the hash. |
| DE-02 executed owner | Refuse/defer becomes persisted `no_setup` with reason codes, rather than the old approved analysis. |
| DE-02 fill attribution | A later deterministic fill is attached to its decision ID instead of the first same-trigger legacy event. |
| DE-03 preview | Read-only settings resolution replaces the mutating service loader; the runner and preview share mode normalization. |
| DE-04 command | Normal eligible captured records reach a completed after-close review; missing inputs have row-local invalid/unavailable outcomes. The bad mapped-type import/current-bar query is removed. |
| DE-05 core capture | Complete decision/policy snapshots and raw source bars are captured before later review; inputs are deep-copied; current plans/bars are no longer reconstructed; actual prompt identity and usage are recorded; day bounds, retry eligibility and after-close checks are improved. |
| UI | Effective policy controls the badge/header; migrated arms no longer display a contradictory critic-on label. |

The deterministic branch still avoids the model, preserves distinct deterministic refusal handling and retains existing downstream quote/risk/dispatch controls. There is no request here for another trading-rule change or another broad infrastructure review.

## CR-01 — P2, optional evidence only: validate the declared evidence identity

`tools/em_entry_evidence.py` trusts `inputHash` and `frozenBarsHash`. In the added actual-command test, one stored bar is changed while its hash is left unchanged. The command renders the changed chart and calls the model under the old identity instead of returning invalid.

Before rendering or buying an opinion, recompute and validate the decision snapshot/policy hash and frozen-bars content/count hash using the same canonical representation as the producer. A mismatch should be an invalid row with no model call. Keep missing historical material unavailable, rather than trying to repair it from current data. The ordinary completed-path control must continue passing.

While closing this remaining DE-05 detail, use the persisted policy values for derived facts, or explicitly version and disclose a separate evidence-analysis policy. The current `_render_frozen` and call to `run_evidence` still instantiate `Thresholds()` rather than using the captured policy. This does not change the executed deterministic decision, but it should not be presented as reviewing under the exact frozen rule configuration without qualification.

Test file: `test_em_evidence_completed_path.py` (completed-path control plus hash-mismatch refusal). Supporting note: `evidence-closure-8e641e9.md`.

## CR-02 — P2, policy report only: retain earlier refusals in the totals

The attempt census now preserves the old legacy veto as an attempt, and the subsequent deterministic fill's P&L is correctly attributed. However, `summarize` increments refusal counts only from the latest trade/refusal projection, ignoring the census disposition. The same example reports the legacy policy as **one attempt, zero fills, zero refusals**, despite its explicit `vetoed` event.

Count immutable refusal/defer dispositions once by full attempt identity, then join downstream fill/refusal results without double-counting. Include run identity in deduplication keys so identical trigger labels/times on different plans cannot collide. Unknown unresolved attempts must remain unclassified rather than being forced into refusal.

The new case requires legacy attempts=1/refused=1 and deterministic fills=1/net=$97.92. No order behavior is involved. Test file: `test_codex_policy_refusal_census.py`. Supporting note: `migration-closure-8e641e9.md`.

## Consolidated release handoff

1. Append the two running regression groups' final results and actual SHA values to the handoff. Preserve explicit-legacy arming tests and the real-rig default deterministic test.
2. Finish CR-01/CR-02 in the same integrated handoff if possible; do not request a separate design approval or add unrelated work. These remain bounded evidence/report fixes, not a reason to redesign the now-accepted live-entry path.
3. Once the release checks pass, deterministic main-mode activation may proceed through the established combined-release process, with after-close model evidence **off** until CR-01 is closed. Premarket LLM, existing risk/exit rules and the 41 prepared arms retain their agreed treatment.
4. Report deployed full build SHA, effective deterministic mode on new/restored EM arms, zero fire-time model calls, and normal inventory/helper verification. Passing this review is not proof the build is running or that the new mode is profitable.

This accepts the requested live decision architecture and its corrected rule behavior while retaining transparent, limited follow-ups. No additional policy clarification from the user is required.
