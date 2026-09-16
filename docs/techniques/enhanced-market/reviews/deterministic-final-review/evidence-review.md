# Delivery B review at 758ccfb

Scope: `backend/zargar/technique/entry_evidence.py`, `backend/zargar/tools/em_entry_evidence.py`, the decision-event producer, and the actual vision return shape. No runtime services, database writes, paid calls, or pytest processes were started by this reviewer. The root reviewer owns the sequential test run.

Delivery B is not complete enough to accept as the promised frozen after-close comparison. It remains default-off and does not place orders. These findings concern research validity and a broken command; they do not justify putting an LLM back in the live order path.

## EB-01 — the real after-close path aborts before producing evidence

**P2, confirmed code defect.** `backend/zargar/tools/em_entry_evidence.py:74` imports `Bar` from `zargar.models`, where the mapped type is `BarRow` (`models.py:192`); no `Bar` alias exists. On the first eligible row with an available client, `run()` awaits `_bars_upto()` at line 117 before its exception handler, so it raises `ImportError`. Existing tests exercise `run_evidence()` directly and never traverse the actual command path.

Also, `entry_evidence.py:94` builds the analysis outside its try block. A missing or malformed saved trigger raises instead of recording an invalid snapshot and continuing to the next decision. The current trigger fetch returns `{}` when a run/trigger is missing, so this is a real batch boundary.

Correction: use the actual mapped type if this query remains necessary; validate/load each frozen input inside the row's error boundary, record `invalid`/`unavailable` as appropriate, and continue. Never pay for a chart-based opinion when the required as-of input is unavailable.

Acceptance: run the real command body through its normal read/record boundaries with one eligible decision and fake model transport; include a missing-snapshot row followed by a valid row. Both must have explicit outcomes and the command must finish. `test_after_close_cli_processes_a_real_eligible_row_without_import_abort` and `test_missing_required_snapshot_becomes_invalid_evidence_not_batch_abort` reproduce the failures without a database or paid call.

## EB-02 — the persisted record is not the immutable input that the later model sees

**P2, research-comparison blocker.** The current live hook returns only `EntryDecision.to_dict()` (`technique/arming.py`, `entry_decision.py:114`), and `execution/planrunner.py:2687-2693` journals that summary. The actual snapshot, source bars and effective threshold values are not stored with the record. After close, the evidence command reads the current `TechniqueRun.result.plan` at lines 63-68 and queries current `BarRow` values at lines 71-78, then uses default `Thresholds()` at lines 123 and 130. Filtering bars by bar-close time does not establish when that version was available: `marketdata.py:410-434` intentionally replaces stored OHLC/provenance with newer/better observations.

Consequently, later corrections or plan changes can alter the material submitted to the model while retaining the original decision's `inputHash`. It cannot reconstruct and verify the deterministic snapshot from the journal either.

There are two directly reproducible identity errors:

- `frozen_input()` at `entry_evidence.py:32-37` makes shallow copies. Editing a source trigger's nested target/entry or a decision's checks changes the supposed frozen payload without changing its recorded `evidenceInputHash`.
- `evidence_key()` at line 57 ignores `evidenceInputHash`; two different planned-trigger inputs get the same completion/deduplication key. `promptHash` at CLI line 98 is a hash of the constant string `entry-evidence-v1`, not of the actual system prompt, critic instructions, output schema or relevant configuration.

Correction: persist a serialized, detached as-of snapshot (or immutable content-addressed reference) at the decision boundary, including the actual trigger geometry/transition, effective rules and the evidence data available then. The later command must validate its hash and use only those inputs. Capture raw data without rendering or model work on the entry path. Old decisions lacking a reconstructable snapshot must be explicitly unavailable; do not manufacture a frozen historical view by querying mutable current rows. Include the actual submitted-input and prompt/schema/config identities in evidence completion identity. Keep original deterministic records untouched.

Acceptance: replay a saved snapshot after changing the live plan, tracker, defaults and BarRows; the evidence input must stay identical, or refuse when the original snapshot is absent. Recompute the hash from serialized bytes before use. A changed actual review input or actual prompt must produce a different evidence identity. Included tests reproduce nested mutation and key collisions.

## Bounded completion details for the same patch

These need no new infrastructure or separate approval cycle:

- **Usage:** `VisionPipeline.run_critic()` returns usage under `critic['passRecord']['usage']` (`vision.py:434`); `entry_evidence.py:107` reads `critic['usage']`, so successful paid results always lose usage. Included test uses the real return shape and requires the expected usage.
- **Session reporting:** CLI `report(date)` at lines 149-152 has a lower time bound only. Asking for an earlier date after subsequent sessions includes those later decisions and corrupts the stated daily coverage. Bound decisions to the requested New York session/day; join later evidence by those decision IDs so late reviews remain visible without adding other sessions.
- **Retry eligibility:** `_decisions()` at lines 54-55 regards every prior outcome, including `budget_skipped`, `unavailable` and `timed_out`, as permanently complete. A first run exhausting the 40-call cap writes skipped records for all remaining decisions, and later reruns will not evaluate them. Preserve attempt history while treating only successful terminal evidence as complete, or require a documented explicit retry mechanism with the same frozen inputs and bounded spend.
- **After-close eligibility:** the command checks the `after_close` setting but never checks the requested session has closed. Refuse a current still-open session before rendering/model work; a force switch that merely bypasses the setting should not silently turn the feature into an intraday worker.
- **Clock/config identities:** `startedAt` currently equals enqueue time even when bar retrieval/rendering happens first, and CLI `--timeout` is ignored whenever the setting exists. Stamp the actual model start separately and apply an explicit finite bound. A model's retry is a provider attempt too; the stated paid-call budget should cover retries, not merely loop iterations.

No evidence trading mutation was found. The model receives a fresh analysis DTO; the command opens no engine/order/arming service. Preserve that isolation. Full prompt equivalence is not currently demonstrated: the reused live prompt assumes gates passed even for deterministic refused/deferred rows, and the legacy DTO manufactures breakout booleans from kind. Supply truthful measured/unknown confirmation facts in evidence inputs rather than treating those legacy DTO flags as observations.

Reproductions: `test_em_evidence_boundary_regressions.py` beside this report. The root reviewer will append executed test results and decide final finding numbering for the combined handoff.
