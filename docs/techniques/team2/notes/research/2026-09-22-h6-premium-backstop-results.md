# H6 — premium stop as a backstop: results

Registration: `2026-09-22-h6-premium-backstop-registration.md`, committed (`fed75988`) before any
replay below was run. Nothing in the registration was amended.

**Verdict: H6 FAILED criterion 1, by a wide margin. The premium stop stays at 25%.**

## Results (training window 2026-05-07 to 2026-08-14, 69 sessions, real option prints)

Paired, date-clustered differences against a baseline re-run on the same code (4,000 resamples, seed
20260919). The re-run baseline reproduces the study's 282 training trades exactly.

| arm | slippage | trades | arm mean | diff vs baseline | 95% interval | diff without the 3 most influential sessions |
|---|---|---|---|---|---|---|
| baseline | 0 | 282 | −2.99% | — | — | — |
| **H6** premium stop −40% | 0 | 280 | −2.81% | **+0.18** | −0.57 to +1.21 | −0.50 |
| **H6** premium stop −40% | 1 tick | 278 | −6.48% | **+0.42** | −0.70 to +1.85 | −0.64 |
| H6d no premium stop (diagnostic) | 0 | 279 | −3.36% | −0.37 | −1.71 to +0.99 | −0.46 |
| H6d no premium stop (diagnostic) | 1 tick | 276 | −6.76% | +0.14 | −1.21 to +1.84 | −1.12 |

Criterion 1 needs at least +3.0 points. The estimated probability of a 3-point improvement is 0.000
at zero slippage and 0.001 at one tick. Both H6 differences turn negative once the three most
influential sessions are removed, so even the small positive estimate rests on a handful of days.

## What this means

- **The premium stop's width is not where Team2 loses money.** Moving it from 25% to 40% changes
  almost nothing, and removing it altogether is no better. On 278 of 280 trades the two arms enter
  identically; the structural stop, the target and the flatten decide most exits either way.
- **2026-09-22 trade 1 was an outlier, not a pattern.** A stop cutting an intact trade that later
  nearly reached its trim is real, but across 69 sessions it is roughly offset by the trades the
  same stop rescues. Changing the rule on the strength of that one trade would have been fitting a
  story.
- **The negative result is itself worth having.** Together with the nine variants of 2026-09-19,
  eleven single-factor changes have now been measured on real prints. None clears the criterion.

## Stated limitation, unchanged from the registration

The harness applies the premium stop at 2-minute closes; the live desk applies it every ~2 seconds
on the mid. Intrabar dips can trigger the live stop where the harness cannot see them, so this
result may under-state how often the live −25% stop cuts an intact trade. The honest next step is a
cheap prospective count — every live premium stop that fires while the 2-minute structure is intact,
and what the contract did afterwards — rather than another replay arm.

## No re-tuning

Per the registration, no other width is tried on this data. Searching 30%, 35%, 45% until one looks
better would be a search, not a test, and would spend the training window's credibility.

Replay files (not in the repository): `train_base_s{0,1}.json`, `train_H6_s{0,1}.json`,
`train_H6d_s{0,1}.json`, produced with `PYTHONPATH` pointed at this worktree's backend.
