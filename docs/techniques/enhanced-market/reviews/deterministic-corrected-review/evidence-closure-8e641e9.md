# Delivery B bounded closure review — 8e641e9

Reviewed `8e641e9e7fd86f5b29beef339ad25401cd4c1a86` without DB writes, paid calls, engine startup or a test process. The root reviewer owns execution of the accompanying no-DB tests.

## Closed in code

- Live decisions now carry a detached serialized `EntrySnapshot`, the tracker policy, raw bars captured from the in-memory bar cache, and a bars-content hash.
- The after-close command reads those records; it no longer rebuilds normal evidence from current plan or current BarRows. Legacy rows without captured material are unavailable. The broken `models.Bar` path is gone.
- Missing snapshots are row-local invalid/unavailable outcomes; the batch continues.
- Nested evidence data is deep copied, and `evidenceInputHash` participates in the completion key.
- Prompt identity covers system text, critic source, output schema and model/effort. Usage comes from the actual `passRecord.usage` return path. Actual model-start time is recorded.
- Reports bound decisions to the requested New York day and join later evidence by decision ID. Noncompleted evidence remains retryable.
- A still-open session is refused even with `--force`. Settings are loaded through the read-only projection. Other evidence failures remain isolated from trading.

## Remaining DE-05 boundary — validate the content hashes before review

`entry_evidence.frozen_input()` copies the supplied `inputHash` and `frozenBarsHash`. `validate_frozen()` checks geometry/identity presence but never recomputes either hash. The command renders `p['frozenBars']` directly without checking those bytes against `frozenBarsHash`; those raw bars are also absent from the calculated `evidenceInputHash`. Changing a frozen bar while retaining its declared hash therefore preserves the evidence key while changing the chart and paid model input. The same contract requires checking snapshot/policy against `inputHash`.

This is the one remaining research-integrity correction requested by this bounded rereview. It does not put a model dependency on live entry and should not broaden the patch: before rendering/paying, recompute the existing hashes from the captured canonical data, validate count/cutoff, and return an invalid evidence outcome on mismatch. Use the recorded effective policy when deriving review facts, so the submitted material agrees with its declared inputs.

`test_em_evidence_completed_path.py` contains a successful full route from real runner fire to recorded snapshot to actual chart rendering and actual critic processing with only the model transport faked. It also contains the same captured row with a modified bar and unchanged hash, which must fail before a model request. The success assertion requires `completed`, a real rendered image, captured usage and `evidence_only`; marking all rows unavailable cannot satisfy it. The root reviewer will report execution results.

No additional infrastructure or trading-policy change is requested. The optional evidence setting should remain off until its full captured-input path is validated.
