# EM deterministic entry — integrated final review

**Verdict: hold this release pending DE-01 through DE-05.** The intended main architecture is present, and the tested deterministic fire path avoids the LLM. However, the implementation changes some existing entry eligibility, the after-close command cannot complete its actual path, and the snapshot/migration/reporting contracts are not yet complete. Return one corrected integrated delivery, not separate approval requests for each finding.

Reviewed production code: `758ccfb8e0a456d1df534f9e91a35e16f47cb352`; delivery `26c83bb`, base main `079472e`. Response read at `442eb95`, then updated at `fc6a295` during review. That follow-up changes only `test_technique_arming.py` and the response document; no production code changes invalidate the findings below.

Review checkout: `C:/Cursor/zargar-codex/.cache/em-deterministic-final`, detached at `758ccfb`. Primary remains `C:/Cursor/zargar-codex`, branch `codex/zargar-development`. No production code, runtime setting, arm, position, order or paid model call was changed/run. The migration preview was tested with an in-memory settings store, **not invoked against runtime**.

## Verified positives and test scope

- The supplied three new test files independently pass: **20 passed in 1.42 seconds**.
- The runner defaults other techniques to legacy; EM's main setting controls the new deterministic branch and legacy `useCritic=true` cannot invoke its critic in the supplied tested path.
- Model failures, advisory downgrading and model kill/refire counters are separated from deterministic refusal in the live branch. Existing quote/risk/dispatch checks remain downstream.
- Optional model review has no direct trading service; premarket review remains separate. The UI/API expose new policy metadata, and decision/timing fields are added to trade restore.
- Ten new isolated regression cases fail at their intended assertions in **1.31 seconds**; one additional executed-record case fails in **0.93 seconds**. The tests use real tracker/runner/CLI/report code with in-memory persistence/model seams where needed. No production or test database, engine startup, network or paid LLM was used.
- The later team response reports 103 passes for the broad DB group. Its arming run first had 26 passes/four failures; the two policy-dependent legacy cases plus a new deterministic real-rig case then passed, and the load-sensitive restore case passed alone. Selecting explicit legacy mode for tests of legacy behavior is appropriate. This is not independently reported here as a fresh full-file all-green arming run. Their 106/13 earlier totals remain team-reported.

The fixture latency numbers support that local calculation is fast. They do not substitute for the behavioral cases below or a measured end-to-end broker latency result.

## DE-01 — P1: preserve existing tracker semantics instead of adding entry filters

**Files:** `backend/zargar/technique/entry_decision.py`, `backend/zargar/technique/arming.py`, existing `backend/zargar/marketstructure/tracker.py` in the reviewed checkout.

Three actual-tracker reproductions:

1. A valid breakout candidate at **10:29 ET** completes the configured follow-through at **10:32**. The existing tracker accepts the candidate's eligible window and fires; the new decision layer adds a confirmation-bar window check and refuses `window_ineligible`.
2. Saved entry **100**, stop **99**, targets **101/108/112**; valid confirmation closes at **101.2**. The snapshot replaces the saved entry with `fill_price`, then requires every target to be ahead of that value. It refuses `geometry_invalid`, although the saved geometry is valid and the two-contract TP2 geometry still offers about 3.09R. Setup allowance must still pass all downstream admission checks; this reproduction is not asking to bypass them.
3. A tracker armed with volume floor **0.5** fires at **0.7** relative volume. The wrapper rereads current settings with floor **0.8** and judges the transition under a rule it did not use. It records the wrong effective threshold and refuses. The current threshold hash also omits confirmation inputs such as decisive-candle and range-break parameters.

**Correction:** snapshot the actual tracker thresholds/window branch and keep saved geometry distinct from observed trigger/entry-proxy price. Preserve candidate-versus-confirmation window semantics. Current risk/quote policies remain separate downstream checks and may still refuse. Do not introduce an all-targets-ahead requirement or new window policy as part of removing LLM latency. If such strategy changes are wanted, they require their own measured proposal.

**Acceptance:** adopt the three real-tracker cases unchanged, add short mirrors and an ineligible-candidate control, retain invalid saved-geometry refusal, and prove setup allowance still cannot bypass the order checks. See `entry-rule-review.md` and `test_codex_deterministic_rule_parity.py`.

## DE-02 — P2: executed decisions and profitability attribution must have one owner

**Files:** `backend/zargar/technique/arming.py::record_fire`, `backend/zargar/execution/planrunner.py::_fire_rest`, `backend/zargar/tools/em_profitability.py::build`.

A deterministic refusal updates `j.verdict` but leaves `j.extra`'s analysis verdict unchanged. `record_fire` persists that old analysis. The new regression shows a trade with deterministic `refuse` being persisted as analysis verdict **setup**. This contradicts the promised single executed-decision owner, even though no order is sent in this case.

The profitability report also selects the **first fire/intent with a trigger ID**, then attaches it to the latest projected trade. After a legacy veto followed by a deterministic refire, an actual +$97.92 deterministic fill is labeled legacy and loses its decision ID. Earlier attempts disappear from policy attempt counts.

**Correction:** make the executed deterministic verdict/reasons authoritative in the persisted setup/proposal context and UI. Keep a pre-gate analysis separately if needed. Join fire decisions, intents, orders and fills by attempt/decision/order identity, not the first event sharing a trigger. Retain every refused/deferred attempt and its policy version.

**Acceptance:** `test_codex_deterministic_record_owner.py` and the refire-attribution case in `test_policy_migration_reporting.py` pass. Cover same-trigger multiple attempts, partial fills and a legacy-to-deterministic switch without rewriting earlier history. This is required to measure the new mode's profitability honestly.

## DE-03 — P2: make preview/report settings reads genuinely read-only

**File:** `backend/zargar/tools/em_fire_policy_migration.py:25`; the same pattern exists in `tools/em_entry_evidence.py::_open`.

The preview calls `SettingsService.load()`. That function can migrate aliases/normalize settings, commit them and journal changes. An in-memory reproduction observes `add(execution.use_critic)` and `commit`. This establishes a write-capable preview, not proof that their reported runtime preview actually changed a setting.

**Correction:** resolve stored settings plus defaults/aliases through a non-mutating projection. Enforce a read-only database transaction for preview/report paths. The optional evidence run may append its evidence records, but must not implicitly migrate trading settings on startup. Reuse a small read-only resolver rather than a new settings subsystem.

**Acceptance:** the supplied preview case records zero writes/commits; legacy aliases and an explicit mode override still resolve as the runtime would. Do not rerun the current preview against production until this correction is made.

## DE-04 — P1 completeness: the real after-close command must run and isolate bad rows

**Files:** `backend/zargar/tools/em_entry_evidence.py:74,117`, `backend/zargar/technique/entry_evidence.py:94`.

The command imports `Bar` from `zargar.models`, which defines `BarRow`. On the first model-eligible row, the actual command aborts with `ImportError` before any evidence is produced. Missing required trigger data also raises during analysis construction outside the row's error handler rather than becoming an `invalid` outcome.

**Correction:** exercise the real CLI path with the actual mapped row type and fake provider; validate required frozen inputs and convert row-local failures into explicit evidence outcomes so later valid decisions can still be reviewed. A missing snapshot must not be fabricated into a setup or abort the entire day's review.

**Acceptance:** the actual-command and missing-snapshot cases in `test_em_evidence_boundary_regressions.py` pass without monkeypatching away the bar loader/import or the validation path. Retain no-model/no-engine test isolation and add mixed valid/invalid-row coverage.

## DE-05 — P1 evidence contract: freeze actual inputs, not a summary reconstructed later

The decision event stores summary checks and an input hash, but not the complete `EntrySnapshot`/policy that produced it. After close the command rereads the current `TechniqueRun` trigger and current bar rows, builds facts using fresh `Thresholds()`, and renders a new chart. Filtering bar timestamps to before the signal close does not prove those rows/versions were available when the decision happened.

There are also directly reproduced identity problems:

- `frozen_input` keeps nested references; changing the original plan/decision changes the supposedly frozen payload without updating its hash.
- Different evidence inputs can have different `evidenceInputHash` values but the same completion key, because the key ignores that hash.
- `promptHash` is a hash of an evidence version label, not the actual prompt/configuration supplied to the critic.
- Successful critic usage exists under `passRecord.usage`, but the evidence result loses it.

**Correction:** persist an immutable, replayable decision/policy/trigger snapshot or references to genuinely immutable versioned inputs at decision time. Deep-copy/serialize it once; heavy facts/rendering remains off the live entry path. Use the actual snapshot threshold/timeframe data, hash the actual reviewed input and prompt/config version, and include those identities in the evidence key. Corrected/backfilled inputs must be separately labeled retrospective evidence, never silently presented as the original snapshot. Capture actual usage.

Complete the same delivery's declared evidence behavior: date reports need a proper next-day upper bound; skipped/unavailable/failed records must not permanently count as successful reviews and suppress permitted retries; enforce/document after-close eligibility; derive signal-bar close from its real timeframe instead of universally adding 60 seconds. These are completion details for this command, not a request for a general background-job platform.

**Acceptance:** the immutable-copy, changed-input identity and usage cases pass. Add an end-to-end snapshot replay where the stored plan/bars/defaults subsequently change: the original input and result identity remain reproducible, and no later outcome enters the prompt. Missing historical evidence remains explicitly unknown.

## Same-patch UI cleanup

`frontend/src/components/technique/ArmedTab.tsx` adds a deterministic badge but retains the old header label derived from persisted `config.useCritic`. The migrated arms can therefore display both deterministic and **critic on**. Make the visible label use effective policy consistently. Normalize the migration preview's accepted mode names the same way as the runner. These are small completion fixes, not separate release projects.

## Required consolidated return

1. Fix DE-01 through DE-05 together, preserving the original 20 passing cases and adding the supplied eleven reproductions unchanged. Do not resolve parity cases by changing the agreed trading rules or making unknown/future data pass.
2. Return one combined SHA, per-finding closure table, actual-command evidence and complete affected regression results. Keep the explicit legacy tests and real-rig deterministic test added in `fc6a295`; report known baseline failures separately.
3. Run the migration preview read-only after its fix. Return effective settings and active-arm inventory, without rewriting or duplicating the 41 plans or changing positions.
4. Keep the current accepted runtime and preparation untouched until the corrected integrated delivery is reviewed. The new deterministic default changes future entry eligibility on boot; do not merge it into a release another desk will deploy before this hold is cleared.

No additional trading-policy decision is needed for these fixes. The user already chose deterministic entry for all EM families and both deliveries in one package. The scope is to implement that choice correctly, preserve existing deterministic rules, and supply genuine optional evidence—not reopen the overall design.
