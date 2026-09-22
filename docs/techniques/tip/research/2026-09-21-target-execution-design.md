# Target execution: bar-touch + market vs quote-touch / resting limit — PREPARED, NOT ACTIVATED (S21-03)

Prepared 2026-09-22 from the 2026-09-21 review. Nothing in this note changes the live manager. It is the explicit
execution-policy comparison the review asked for, with the evidence the scorecard now records, so a decision can be made
on measured cases instead of one instance.

## What the live manager does today (unchanged)

`execution/policies.py` judges a ladder target on the **closed bar's** high (long) / low (short) of the position's
policy timeframe (15m for tips). `execution/positions.py` then sells the rung as a **limit at the bid it sees at that
moment** (a marketable limit; `MKT` only when forced by a stop). The entry order's venue take-profit child is cancelled on
adoption so the manager is the single exit authority. The card's payoff scenarios assume an exit **at** the target price
(now stated on every card, S21-01).

## The measured instance (VKTX, 2026-09-21)

| | |
|---|---|
| entry | 50 sh @ 29.74, 15:23:26 ET |
| first touch of TP1 30.60 on the 1m tape | 15:26 (bar high 30.70) |
| manager decision (15m bar close) | 15:30:00 |
| order | sent 15:30:00 as the bid the manager saw; filled 15:30:01 @ 29.904 for 17 sh |
| target-to-fill shortfall | 0.696/sh, **$11.83** on 17 sh (gross at target would have been +$14.62 vs +$2.79 realised) |

This is arithmetic between the touched target and the realised fill. It is **not** evidence that a 17-share limit at
30.60 would have filled: the 1m bar's high is a print, not resting liquidity, and a limit that fills only on a spike can
also fill a spike-and-reverse at a worse expectation. One case decides nothing.

## The comparison to run (order-free, on the record the scorecard now keeps)

Scorecard v4 records for every target rung: first-touch time, decision time, order time, fill time and price, the
limit sent, and the shortfall. Over the observation window and beyond, tabulate per rung:

1. **Current policy** (bar-touch, marketable limit at the next 15m close): realised price vs target, touch-to-decision
   minutes, and how often the bar's touch had reversed by the close (fill worse than target by > one spread).
2. **Quote-touch policy** (hypothetical): exit when the **executable quote** (bid for a long) reaches the target - not a
   bar high; requires the 2 s quote watch to carry an exit path, which today it deliberately does not for entries and
   only does for protective stops.
3. **Resting limit at the target** (hypothetical): one reduce-only limit per rung, coordinated with the venue stop so the
   stop's quantity follows fills (the `venueStopQty` rule) and never double-sells.

For 2 and 3 the scorecard's touch/decision/fill trail gives an upper bound (fill at the touched price) and a lower bound
(no fill unless the quote traded through); the truth is in between and unknowable without resting the order.

## Cases the design must handle before anyone activates it

- **Reversal**: the touch is a single print; the resting limit fills, the bar closes lower. Compare the realised
  distribution, not the best case.
- **Failed fill**: the limit rests unfilled, price falls to the stop. The stop must remain the authority; the resting
  rung must be cancelled before or atomically with the stop's fill (one exit authority).
- **Partials**: a rung fills partly; the venue stop quantity is resized to the held quantity (existing rule), and the
  remaining rung quantity stays resting or is cancelled - decide and journal.
- **Restart**: resting rungs must be restored/reconciled like the venue stop (`SubmitUncertain` rules apply).
- **Options**: a rung on an OPTION is a premium target; the executable quote is the OPRA bid, and a resting limit on a
  thin contract is the same friction question as S21-04.
- **Reduce-only and RiskGate**: every rung passes `RiskGate.evaluate()` as a reduce-only intent (no change).

## Decision boundary

Not a bug fix. It changes what the desk receives on winners and what it risks on reversals, so it is a **policy
decision** to be taken on the measured comparison above, in Practice first, per technique (Tips only), with its own
rollback. Until then the card says what it assumes and the scorecard says what was received.
