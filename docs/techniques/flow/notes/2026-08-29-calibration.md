# Flow threshold calibration — 2026-08-29 (PRELIMINARY: one day-pair)

Tool: `python -m zargar.tools.flow_calibrate` (NEXT-GAPS FL1) — replays
`flag_contracts` over the `option_chain_snapshots` history for a grid of
thresholds and measures the overnight OI-confirmation rate (flagged volume
that became real open interest) against the all-contracts baseline.

Data: 2026-08-27 → 2026-08-28 (145 underlyings, ~650k rows, ONE overnight
pair). **Re-run when ≥ 5 day-pairs exist** (~Sept 5) before trusting the
numbers past a first cut.

## Headline findings

- **Baseline**: 28.1% of ALL active contracts (vol ≥ 100) grow OI overnight by
  ≥ 0.5× their volume (n=24,718). A flag rule must beat this to mean anything.
- **0-2 DTE flags are ANTI-signal**: with `dte_min=0` (the old default), 25-29%
  of flags are 0-2 DTE and the confirmation rate drops to 20-25% — BELOW
  baseline. Expiry-board churn was actively polluting the reads.
- **A DTE floor roughly doubles confirmation**: every `dte_min ≥ 2` combo sits
  at 34-56% confirmation.
- Best cells (highest confirmation at reasonable volume):
  `dte_min=5 / prem≥$250-500k / Vol-OI≥3` → 55-57% (n=140-211).
  `dte_min=3 / prem≥$250k / Vol-OI≥2-3` → 46% (n≈265).
- Raw symbols-flagged stays ~40-57/day at every combo — flag thresholds alone
  don't prune the SYMBOL count; the per-symbol score gate
  (`universe_score_min`, now premium-weighted) is what ranks the desk.

## Applied (live, journaled)

| key | was | now |
|---|---|---|
| techniques.flow.dte_min (NEW) | — (0) | **3** |
| techniques.flow.premium_min | 100,000 | **250,000** |
| techniques.flow.vol_oi_min | 1.25 | **2.0** |
| techniques.flow.premium_unit (NEW) | — | 1,000,000 (score is premium-weighted, FL2) |
| techniques.flow.calibrated (NEW) | — | **false** — FL4's conviction upgrade stays OFF |

`dte_min=3` chosen over 5 deliberately: 5 scored better on this single pair
(55% vs 44-46%) but excludes legitimate 3-4 DTE weekly plays, and one
day-pair is not enough to pay that cost. Revisit at the re-run.

## Flip criteria for `techniques.flow.calibrated` (FL4)

Turn it on (flow tips carry `explicit_call` when score ≥ `universe_score_min`
AND OI-confirmed) only when, over ≥ 5 day-pairs, the flagged-contract
confirmation rate stays ≥ 1.5× baseline at the applied thresholds.
