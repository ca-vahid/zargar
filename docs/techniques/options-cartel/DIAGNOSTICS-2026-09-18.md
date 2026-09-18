# Cartel diagnostics completion — September 18, 2026

The implementation handback through `cb658c8` is integrated with current main. This release
does not activate Lane A, the 1.5R experiment, reconstructed volume, or change trading limits.

## Decision evidence

`cartel_decision_contexts` and `cartel_decision_bundles` are new additive tables created by
the normal schema startup. The observer captures distinct decision occurrences, full saved
session minutes, plan/baseline and observation cutoff. A content hash identifies each context
and occurrence. Exact retries are idempotent; later observations do not overwrite old rows.
The bundle, its context, arm update and `TechniqueCartelDecisionCaptured` event commit together.
Journal references include bundle/context IDs, hash, bucket end and observed time. No second
engine or background collector is introduced. Per-minute receipt timestamps were not previously
recorded: the bundle states only that these inputs were present at its observation cutoff.

The event identifies the occurrence; do not use `(run_id,bucket_end)` as a unique replaceable
row. Protective exits retain their existing independent manager. Rolling back code leaves the
additive evidence tables intact. These rows are evidence, never entry authorization.

## Provider reconstruction (offline only)

Command from backend, with read-only market-data access:

```powershell
python -m zargar.tools.cartel_volume_audit --env-file <runtime-backend-env-file> --out-dir <evidence-directory>
```

Rules are frozen in `volume_reconstruction.py` as `alpaca-minute-eligibility-v1`, using
[Alpaca's field-specific aggregation matrix](https://docs.alpaca.markets/us/docs/market-data-faq#how-are-bars-aggregated).
Tape and combined sale conditions determine price and volume eligibility separately. Unknown
conditions and incomplete pagination fail the comparison. Timestamp sorting preserves nanoseconds;
session bounds come from the exchange calendar. Volume tolerance is zero; price tolerance is 0.000001.

| Symbol/session | Provider bars | Returned trades | Emitted volume | Eligible volume in suppressed intervals | Result |
|---|---:|---:|---:|---:|---|
| PLAB 2026-09-16 | 346 | 17,796 | 871,489 | 9,334 | exact volume and price parity within declared tolerance |
| LZB 2026-09-16 | 335 | 14,285 | 580,195 | 11,264 | parity |
| PWR 2026-09-17 | 373 | 32,115 | 563,019 | 5,428 | parity |
| AAPL 2026-09-17 (liquid control) | 390 | 648,550 | 25,569,974 | 0 | parity |

Credential-free results, request parameters, completion times and response hashes live under
`reviews/2026-09-17-proposal/volume-audit/`. Early-close/nanosecond boundaries have a synthetic
fixture; no live early-close comparison is claimed. Historical trade responses describe the
provider's final state at collection, not what arrived at the original trading decision.

This establishes a reproducible provider interpretation, not profitability and not authority
to fill gaps with zero-volume candles. Before a Practice experiment, compare a versioned
historical/current volume basis on identical samples, define price/crossing/stop coverage, and
freeze its acceptance conditions. Keep suppressed eligible volume separate from emitted-bar sums.

## Method evaluation

Lane A remains an unwired pure evaluator. Strict has zero qualifiers among available frozen
analyses; the only strict-bullish day had 58 analyses and 3,032 prefiltered listings without
Lane A evidence. Moderate remains a separate information-only comparison. Hypothetical option
feasibility is not historical affordability. Do not skip nearby pivots to manufacture higher R.

## Verification

The handback on current main passed 58 focused tests, including the previously reported
restore-and-stop case. No failure was suppressed or labeled resolved without reproduction.
Added capture tests cover exact retry, changed-input revision, reconstruction from persisted
context, atomic rollback and missing context references. Registry coverage includes late
session counts, in-flight drops, duplicate delivery, throttled failure and retirement.
Final commands/results and deployment state are recorded in the release handoff.
