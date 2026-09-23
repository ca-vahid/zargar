# H6 — premium stop as a backstop, not the primary exit: registration

Registered 2026-09-22, **before any H6 replay was run**. This file is committed first; the results page
is written afterwards and may not amend anything here except in a dated note saying why.

## Why this arm, and why now

On 2026-09-22 the Team2 books lost $2,217 net on two QQQ round trips. The first (all three books,
$1,675 of the loss) was closed at 10:06 by the live premium stop — contract mid −28% against a −25%
limit — while QQQ was flat and closed above its EMA13 on every 2-minute bar until 10:36. The
contract then traded up to 0.76 by 10:34, two cents below its first trim.

One trade proves nothing. But the question it raises was never measured: the 2026-09-19 study
registered nine variants (two-candle stop, target room, new-extreme trim, conjunction zone, dearer
contract, collision re-plan, no target exit, two brackets) and **none varied the premium stop's
width.**

The author's own words put the EMA break first and the premium loss as a backstop:

- "typical stop outs under the EMA, −20/30%" (2024-10 image)
- "4 losses that ranged between −20% & −40% depending on how quickly I exit" (2025-03)
- "running hard stops… usually around the 20% max loss mark" (2023 podcast)

So the tested idea is: **keep the structural stop exactly as it is, and move the premium stop from
−25% to −40%, the top of his stated range**, so that on a 0DTE contract whose own noise exceeds 25%
the structure decides the exit and the premium stop only catches a genuine collapse.

## Arms

| arm | override | role |
|---|---|---|
| baseline | none | reference, re-run on the same code so the pair is clean |
| **H6** | `premium_stop_pct=40` | **the candidate** |
| H6d | `premium_stop_pct=100` | diagnostic only: structural stop and flatten with no premium stop at all. Never a candidate — a 0DTE book with no hard stop is not an acceptable policy. It bounds how much of any H6 effect is the premium stop at all |

Every other rule identical: sizing, contract selection, entries, candle stop, target, trims, flatten,
fees ($1.04/contract/side), no-trade zone, loss caps.

## Criterion (frozen, reused verbatim from the 2026-09-19 study)

**Criterion 1:** the mean net return per trade improves on the baseline by **at least 3 points** AND
the simulated book finishes **above** the baseline book. Differences are paired and date-clustered
(the same resampled sessions for both arms, 4,000 resamples, seed 20260919). Reported at zero
slippage and at one tick per leg; the arm must pass at one tick to be called robust.

Also reported, not part of the pass/fail: the difference without the three most influential sessions,
entries in both arms, and trades whose outcome changed direction.

## Window

Training window only, **2026-05-07 to 2026-08-14**, the same window the other nine arms used. The
holdout (2026-08-17 to 2026-09-18) is **not opened** by this registration. If H6 passes on training, a
separate decision opens the holdout once, for H6 alone.

## Known limitation, stated before the result

The harness evaluates the premium stop on real option prints at each 2-minute close. The live desk
evaluates it every ~2 seconds on the mid. Intrabar dips — like today's 10:06 — therefore trigger the
live stop more often than the harness can see. The harness measures the **width** of the rule, not the
live watch's microstructure, so a pass here would under-state rather than over-state how often the
live −25% stop cuts an intact trade. It would still need a prospective check on the live watch.

## What a result can and cannot authorise

- **Fail:** the premium stop stays at 25%. Recorded; no re-tuning to a different width on the same
  data (that would be a search, not a test).
- **Pass:** eligible for a separate proposal to open the holdout. Not activation. No Practice book is
  changed by this registration.
