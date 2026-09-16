# Time / volatility scenarios for a long option - design + one worked example (TMR-03, 2026-09-16)

**Status: research prototype.** `backend/zargar/techniques/tip/scenarios.py` (`bsm-local-v1`) is NOT wired
into any card, gate, sizing or order path. The desk's risk estimator (`geometry.py`, `delta-linear-v1`)
and the execution gate are untouched; this document specifies a narrower, separate question for
research reports.

## 1. Question and grid

For ONE long option position (or candidate), how would the contract's value move if:

| scenario | underlying | time elapsed | IV |
|---|---|---|---|
| flat | stays at today's spot | 1, 5, 10 calendar days | today's IV, -5 points, +5 points |
| target-soon | reaches the declared target | 1 day | same three |
| target-later | reaches the declared target | half the remaining time to expiry | same three |

Output per cell: model value and `pnlDollars = (value - premiumPaid) x multiplier x qty`. `premiumPaid` is
the position's own entry (or the current mid for a candidate); the model's value at t0 and
`modelMinusPaid` are printed beside it so the model's mispricing of TODAY is visible, not hidden.

## 2. Model, inputs, units, sources

- Model: Black-Scholes-Merton, European, no dividends, flat rate (`DEFAULT_RATE` 0.04, declared on every
  output). Greeks per ONE unit of underlying: `delta`, `gamma`, `theta` per calendar DAY, `vega` per 1.00 of IV
  (the report also prints theta and vega in dollars per contract per day / per IV point).
- Inputs and where they come from: spot (a qualified underlying quote or an exchange bar, with its
  timestamp); strike and expiry (the OCC symbol); days to expiry (calendar days from the decision date);
  IV (the chain snapshot's IV or the live snapshot's `mid_iv`, with its timestamp); premium paid (the fill);
  target (the analyst's declared target). Every input's source and time is carried in `inputs`.
- Unknowns: any missing input (no IV, no spot, no DTE, no premium) makes the whole grid `unknown` with the
  missing names listed - never a guess. Non-positive inputs are refused with the reason.

## 3. Limits (declared on every output)

- A local approximation on today's IV: not a calibrated forecast for a large move, an event day, early
  exercise, dividends or a thin strike.
- The underlying's PATH between now and the scenario time is ignored: no stop hit is modelled here; the
  managed-exit question belongs to the hold study.
- Exits are valued at the model value, not at a bid: execution cost is the `execcost-v1` diagnostic's job,
  charged once there (`(ask - bid) x multiplier x qty + fees`).

## 4. Worked example (frozen evidence, coverage-limited)

Position: Tips Practice **SLV Nov-20-2026 65 call x1**, entered 2026-09-15 10:05 ET. Evidence used, all
from the desk's own records, none fetched today for the example:

| input | value | source / time |
|---|---|---|
| spot | 57.55 | SLV 1m exchange bar close, 2026-09-15 16:00 ET |
| strike / expiry | 65 / 2026-11-20 | OCC |
| days to expiry | 65 | calendar days from 2026-09-16 |
| IV | 0.4665 | CBOE delayed chain snapshot dated 2026-09-15 (nightly research feed) |
| venue delta (for comparison) | 0.3144 | same snapshot |
| premium paid (stand-in) | 2.085 | the snapshot MID (bid 2.05 / ask 2.12); the position's actual fill is on the order record and should replace this in a live report |
| target | 61.8 | the position's second ladder rung (policy 2026-09-16 09:32 ET) |

Coverage limits of this example: the chain snapshot is DELAYED evidence (not a qualified live quote); the
spot is a close, not a decision-time quote; theta/vega/gamma are the LOCAL model's, the venue's are not
recorded (the chain table holds IV and delta only).

Model at t0: value **2.0776** (mid 2.085, `modelMinusPaid` -0.0074), delta **0.3143** (venue 0.3144 - the
local model reproduces the venue's delta on these inputs), gamma 0.0313, theta **-0.0327/day = -$3.27 per
contract per day**, vega 8.62 = **+$8.62 per contract per IV point**.

Grid ($ per contract, premium 2.085):

| scenario | hold days | IV -5 pts (0.4165) | IV unchanged (0.4665) | IV +5 pts (0.5165) |
|---|---:|---:|---:|---:|
| flat at 57.55 | 1 | -45.81 | -4.02 | +39.32 |
| flat at 57.55 | 5 | -57.17 | -17.27 | +24.23 |
| flat at 57.55 | 10 | -71.59 | -34.16 | +4.93 |
| target 61.8 reached soon | 1 | +106.73 | +157.82 | +209.13 |
| target 61.8 reached later | 32.5 | **-21.32** | +13.94 | +49.62 |

Reading (of the arithmetic, not a forecast): on this contract a 5-point IV move is worth about as much as
ten days of time; the SAME target reached at the halfway point with IV 5 points lower loses money, while
reached within a day it makes +$107 to +$209. That is the whole point of separating "good thesis" from
"good option purchase": the target is only half of the outcome. Whether IV will fall after the Fed event
is not something this model knows.

## 5. What would make this more than a prototype

Qualified live inputs at decision time (the execcost quote record already carries `sourceTs`/`sampledAt`);
the venue's own Greeks persisted beside IV; a recorded model-vs-realised comparison per closed position
(the hold study's managed outcome supplies the realised side); and a reviewer verdict before any card
shows a scenario number. None of that is promised for today.
