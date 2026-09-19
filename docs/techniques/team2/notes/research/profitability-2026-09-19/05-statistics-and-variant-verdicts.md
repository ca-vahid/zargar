# 5. Revised statistics and the nine variant verdicts

Everything here is **simulated execution on real trade prints** (page 3), never fills. Intervals are 95%, from a bootstrap that
resamples whole SESSIONS (4,000 resamples, seed fixed), so the three symbols of one day and repeated entries of one setup are not
treated as independent. Source files: `results/baseline_stats.jsonl`, `results/arm_pairs.jsonl`, `results/horizon_train.txt`.
Status: developer-reported; every number is reproducible from the listed replay files (`results/replay_file_identities.sha256`).

## A. Baseline, by window (no extra slippage, $1.04 fee, `proxy` target scenario)

| Window | Sessions (with a trade) | Trades | Setup opportunities | Mean net per trade | Date-clustered 95% | Naive 95% (for comparison) | Win rate |
|---|---|---|---|---|---|---|---|
| All, 05-07 to 09-18 | 93 (78) | 332 | 222 | -3.71% | -7.92 to +0.75 | -7.62 to +0.19 | 31.9% |
| Training, 05-07 to 08-14 | 69 (60) | 282 | 186 | -2.99% | -7.79 to +2.26 | -7.41 to +1.43 | 33.0% |
| Holdout 08-17 to 09-11, DESCRIPTIVE (seen before any registration) | 19 (15) | 40 | 28 | -5.46% | -9.85 to -1.19 | -13.95 to +3.04 | 32.5% |
| 09-14 to 09-18, DESCRIPTIVE | 5 (3) | 10 | 8 | -17.12% | -25.9 to -10.0 | — | 0% |

Concentration (all dates): the three best sessions contribute +746 percentage points against a total of -1,232; the mean without the
best one, three and five sessions is -4.76%, -6.24% and -7.16%. No positive result anywhere depends on fewer days than that.

## B. The same baseline under different execution assumptions (all dates). No row is "the" correct model

| Extra slippage per leg | Fee per contract per side | Target scenario | Mean net | Date-clustered 95% |
|---|---|---|---|---|
| 0 | $0 | proxy (touch-minute VWAP) | +0.19% | -4.12 to +4.79 |
| 0 | $0.65 | proxy | -2.09% | -6.39 to +2.51 |
| 0 | $1.04 (the Practice books' fee) | proxy | -3.71% | -7.92 to +0.75 |
| 0 | $1.04 | bar-close exit after the touch | -3.20% | -7.81 to +1.88 |
| 0 | $1.04 | touch-minute HIGH (most favourable) | -0.32% | -5.12 to +4.69 |
| 1 tick | $0 | proxy | -3.56% | -7.78 to +0.90 |
| 1 tick | $0.65 | proxy | -5.84% | -9.93 to -1.52 |
| 1 tick | $1.04 | proxy | -7.55% | -11.53 to -3.28 |
| 1 tick | $1.04 | bar-close | -7.15% | -11.60 to -2.32 |
| 2 ticks | $0 | proxy | -7.46% | -11.43 to -3.19 |
| 2 ticks | $0.65 | proxy | -9.89% | -13.84 to -5.65 |
| 2 ticks | $1.04 | proxy | -10.96% | -14.91 to -6.71 |

Reading it with page 1's proxy validation (the print proxy looked about two cents per round trip PESSIMISTIC against 15 actual legs):

- The point estimate is negative under every assumption that includes the books' actual fee, and the interval excludes zero as soon
  as one tick of adverse slippage per leg is assumed. **Negative estimate under these assumptions.**
- Under the two most favourable assumptions (no fee, or every target sold at the touch minute's high) the estimate is about zero and
  the interval is symmetric around it. Nothing in the grid is positive with an interval above zero.
- One tick per leg costs about 3.8 points and the full fee about 3.9 points: execution assumptions move the answer by MORE than the
  width we would need to call an edge. **Conclusion for the baseline: no established after-cost edge; the sign is not established
  either; an edge larger than about +1% to +5% per trade (depending on the assumption) is unlikely on this sample.**

## C. Direction and magnitude at the decision (training entries, exit-free, DESCRIPTIVE)

| Minutes after execution | Underlying on our side | Mean signed underlying move (95%) | Chosen contract, print-to-print after two commissions (95%) | Unknown |
|---|---|---|---|---|
| 4 | 50.0% | +0.008% (-0.009 to +0.026) | -1.7% (-5.6 to +2.6) | 1 |
| 10 | 50.7% | 0.000% (-0.025 to +0.026) | -4.4% (-9.5 to +0.6) | 0 |
| 20 | 48.6% | +0.008% (-0.034 to +0.052) | -3.1% (-13.0 to +8.8) | 0 |
| 30 | 51.4% | +0.003% (-0.047 to +0.056) | -3.1% (-14.9 to +12.4) | 0 |
| 60 | 53.9% | +0.001% (-0.080 to +0.089) | +0.3% (-21.7 to +31.7) | 3 |
| 120 | 50.0% | -0.010% (-0.113 to +0.090) | +3.2% (-27.5 to +42.2) | 15 |

A favourable-direction rate near 50% does not by itself mean zero expectancy, so the magnitude is shown: the mean underlying move is
indistinguishable from zero and its interval is about +/-0.05% at thirty minutes (roughly +/-35 cents on QQQ). The option intervals
are wide: they do not show a loss, they show that **this sample cannot detect an option edge smaller than about ten to fifteen
points at thirty minutes.** The first package's sentence "the entry carries no directional information" was too strong. Supported:
"no directional edge was detected; a small one cannot be excluded".

## D. The nine registered variants, re-measured under the corrected harness (training window only; no value or criterion changed)

Criterion 1 (frozen): the mean net return per trade improves on the baseline by at least 3 points AND the simulated book finishes
above the baseline book. `diff` is a paired, date-clustered difference (the same resampled sessions for both arms).

| Arm | Trades (base 282) | Arm mean | diff, no slippage (95%) | diff without its 3 most influential sessions | diff at 1 tick (95%) | Entries in both: base -> arm | Only in the arm (n, mean) | Only in the baseline (n, mean) | Criterion 1 |
|---|---|---|---|---|---|---|---|---|---|
| H1 two-candle stop | 284 | -4.60% | -1.62 (-3.71 to +1.36) | -2.91 | -1.72 (-3.19 to -0.14) | 250: -3.09 -> -3.58 | 34, -12.1 | 32, -2.2 | failed |
| H2 target room 1.5 ATR | 237 | -1.71% | +1.27 (-1.26 to +4.44) | -0.28 | +1.36 (-1.16 to +4.48) | 220: -3.20 -> -3.20 | 17, +17.5 | 62, -2.2 | failed |
| H3 new-extreme trim | 283 | -3.64% | -0.65 (-1.52 to +0.09) | -0.13 | -0.79 (-1.69 to -0.04) | 281: -3.30 -> -3.41 | 2 | 1 | failed |
| H4 conjunction zone | 320 | -2.53% | +0.46 (-1.65 to +2.58) | +0.29 | +0.43 (-1.60 to +2.46) | 245: -2.28 -> -2.18 | 75, -3.7 | 37, -7.7 | failed |
| H5 $1.20 contract | 281 | -2.02% | +0.97 (-0.19 to +1.95) | +1.55 | **+2.70 (+1.24 to +4.18)** | 279: -3.48 -> -2.15 | 2 | 3 | failed |
| E1 collision re-plan | 299 | -3.12% | -0.13 (-0.90 to +0.55) | +0.08 | -0.10 (-0.82 to +0.54) | 281: -2.93 -> -2.93 | 18, -6.0 | 1 | failed |
| E2 no target exit | 259 | -7.10% | -4.11 (-7.03 to -1.17) | -2.64 | -4.18 (-6.84 to -1.56) | 251: -3.40 -> -7.05 | 8, -8.6 | 31, +0.4 | failed |
| X1 bracket +50% | 241 | -5.62% | -2.64 (-6.70 to +1.46) | -3.42 | -0.36 (-4.65 to +3.94) | 241: -2.01 -> -5.62 | 0 | 41, -8.8 | failed |
| X2 bracket +100% | 228 | -6.26% | -3.27 (-8.48 to +2.46) | -4.79 | -0.99 (-6.33 to +4.96) | 228: -2.65 -> -6.26 | 0 | 54, -4.4 | failed |

Second half of criterion 1, from the SIMPLIFIED book simulation (not decision-grade; realized equity from $10,000 on the training
window): baseline 13,318; H1 11,799; H2 21,824; H3 11,591; H4 5,413; H5 12,276; E1 11,626; E2 5,703; X1 2,788; X2 2,138. Only H2's
book finishes above the baseline's, and H2 fails the first half.

Timing check (review amendment 3): the harness logs each entry's execution time, but the read's lifecycle (stops, trims, holds) still
counts from the decision time. Entries executed a minute or more late are therefore flagged and every comparison is repeated
without them. Across all 26 replay files there is exactly ONE such entry (arm H4, one-minute lag); excluding it moves H4's
difference from +0.46 to +0.47 (and +0.43 to +0.45 at one tick). The baseline has none.

Censored trades: none in any arm. Probability that the difference is at least +3 points (bootstrap share): at most 0.13 without
slippage (H2) and 0.34 at one tick (H5).

### Verdicts (wording as required)

| Arm | Verdict | Did the correction change it? |
|---|---|---|
| H1 | Failed the preregistered criterion under this harness; the estimate is worse than the baseline and the interval excludes zero at one tick | No |
| H2 | Failed the preregistered criterion. Its +1.3 points rests on three sessions: without them it is -0.3. Its 17 arm-only entries are an eligibility change (a refused near-target entry frees the setup for a later one), reported apart | No |
| H3 | Failed the preregistered criterion | No |
| H4 | Failed the preregistered criterion. It ADMITS 75 entries (mean -3.7%) and LOSES 37 baseline entries (mean -7.7%): the displacement mechanism of page 4, section A, visible in the replay | No |
| H5 | Failed the preregistered criterion (+0.97, and +2.70 at one tick, both under 3 points; the arm's own mean stays negative). **It is the only arm whose improvement has an interval above zero**, and only under the one-tick assumption: a dearer contract is less sensitive to a fixed tick and a fixed fee. That is an arithmetic property of costs, not evidence of an entry edge | Ranking: first at one tick, second without slippage (was second in v1) |
| E1 | Failed the preregistered criterion; no measurable effect on entries common to both | No |
| E2 | Failed the preregistered criterion; worse than the baseline with an interval below zero | No |
| X1, X2 | Failed the preregistered criterion. At one tick their difference from the baseline is indistinguishable from zero. They do not show that exits are irrelevant: two bracket shapes were tried, on entries chosen by the baseline's own exits | No |

Ranking by difference without slippage: H2, H5, H4, E1, H3, H1, X1, X2, E2: identical to v1. At one tick H5 moves ahead of H2.
**No verdict changed after the correction.** The holdout was not opened for any arm, in either pass.

What the nine failures do NOT establish: that exits are irrelevant (seven of the nine touch exits or filters, in one fixed value
each); that no filter exists; or that the method cannot be profitable. They establish that none of these nine values met the
criterion frozen for it.

## E. Descriptive subgroup cells

The first package printed subgroup tables (setup, day type, hour, entry line, size bucket, exit, hold) with naive intervals. They are
kept in `history-v1/04-loss-attribution.md` for the record. They were examined before any registration, their intervals ignore
clustering, and cells that look positive there (scenario 4, 09:45 to 10:00, EMA48 entries) are exactly what page 7 is designed to
test prospectively. They are not findings.
