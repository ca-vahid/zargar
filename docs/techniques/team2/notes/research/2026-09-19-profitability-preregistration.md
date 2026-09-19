# Team2 profitability study: preregistration (frozen 2026-09-19, before any variant was measured)

Status: FROZEN. Written after the baseline was measured and before any hypothesis arm was run. A later edit to a
definition or a criterion invalidates the comparison it touches and must be recorded as a new registration.

## What had been looked at when this was frozen

- Actual fills of all four Team2 books (runtime database, read-only).
- The BASELINE rules replayed on 2026-05-07..2026-09-18 (93 sessions x SPY/QQQ/IWM), first with the formula premium and then with
  real option prints. No variant arm had been run.
- The method-fidelity audit (author evidence vs. implementation).

## Measurement harness (identical for every arm)

- Tape: Alpaca SIP 1m bars, extended hours included, fetched read-only into a local cache. Twelve warm-up sessions, the same
  `build_skeleton` / `complete_plan` / `simulate_session` functions the desk runs. Strikes walk the $1 grid (no as-of listing
  exists for past sessions: a stated limitation; IWM half strikes are not tested).
- Prices: REAL option prints only (Alpaca 1m option trade bars). Decision-time marks = the open of the option minute that starts
  at the decision; target-touch exits = the VWAP of the minute in which the underlying touched; management marks = the last
  real print at the 2m close. A contract with no print is not eligible. No option price is modelled or interpolated.
  Validation: against the desk's 16 actual fills the minute-open proxy has median error $0.00 (range -0.105..+0.04).
- Costs: $1.04 per contract per side (the Practice books' fee). Central case slippage 0 ticks (the validation shows our fills at
  the minute open); stress case 1 tick per leg; second stress 2 ticks per leg.
- Per-symbol replay does not see the desk-wide limits. The BOOK simulation applies them afterwards in time order: one position at a time
  across symbols, two losses per day desk-wide (unless the arm changes it), $10,000 start, the desk's sizing (risk 6% of equity
  against the 25% premium stop, $2,000 premium cap, 40-contract cap, integer contracts, size bucket multiplier), fees per contract.
  A trade whose entry falls while another position is open, or after the day's cap, is dropped (a stated approximation: the
  per-symbol sequence after a dropped trade is not re-simulated).

## Windows

- TRAIN: 2026-05-07 .. 2026-08-14. Arms are compared here first.
- HOLDOUT: 2026-08-17 .. 2026-09-11. Looked at once, for the arms that pass TRAIN, with no re-tuning.
- 2026-09-14 onward: never used for selection. Actual fills from those dates are reported as actual fills. C2 (`key_levels`)
  is not run on any date on or after 2026-09-14 in this study; its sealed validation window stays sealed.

## Hypotheses (one factor each; every other rule stays at the baseline)

| id | factor | definition | source of the idea |
|----|--------|------------|--------------------|
| H1 | stop confirmation | `stop_candles=2`: the candle stop (S1) needs TWO consecutive 2m closes through the guard line; premium stop, target, flatten unchanged | Author: "only risk a candle or 2 beyond that level"; 51% of baseline trades exit within two bars at a mean of -11.9% |
| H2 | target room | `min_target_atr=1.5`: refuse an entry whose target is nearer than 1.5 x 2m ATR | Attribution: near targets are hit often and pay less than fees; rule C3 exists, off |
| H3 | trim cue | `trim_cue=new_extreme` | Author's X1 cue is a new high/low of the move, not +50% |
| H4 | no-trade zone | `no_trade_zone=conjunction` | Author calls the pre-market range a "loose guide"; this is the live C1 arm |
| H5 | contract | `target_premium=1.20` (band 0.20..1.80) | Fee drag is ~4% of a $0.50 contract per round trip and ~1.7% of a $1.20 one; NOT author-supported (his fills are $0.20-0.60) |

No other arm, threshold value or combination is part of this registration. Values are fixed as written: no grid search.
Combinations may be examined only as exploratory and must be labelled so.

## Acceptance criteria (all must hold for "supported")

1. TRAIN: mean net return per trade improves on the baseline by at least 3 percentage points, and the book simulation ends higher than the baseline book.
2. HOLDOUT: same sign of improvement on both measures. No minimum size (the holdout is ~19 sessions).
3. Robust to fills: criterion 1 still holds at 1 tick per leg.
4. Not one day: with each arm's three best dates removed, the book still beats the baseline book with its three best dates removed.
5. Not one symbol: at least two of the three symbols improve on mean net return per trade.
6. Risk: the book's maximum drawdown is not more than 25% worse than the baseline's.

An arm that is "supported" is a candidate for a prospective Practice experiment. It is not evidence of profitability by itself:
an arm can beat a losing baseline and still lose. The adopt / reject / insufficient-evidence decision belongs to the prospective
experiment, not to this replay.

## What this study cannot show

- Queue position, partial fills and the true NBBO at our decision instant (prints, not quotes).
- The author's discretion (flags, "A+" selection, sitting out), which the code does not implement.
- Behaviour on dates before 2026-05-07 or in a different volatility regime.

---

## Round 2 (registered 2026-09-19, after round 1 was measured on TRAIN and before any round-2 arm was run)

Round 1 on TRAIN: no arm met criterion 1 (results in the review package). Round 2 comes from the OPPORTUNITY LEDGER against the
author's six documented trades inside the data window (2026-09-01..09-18): same direction on six of six, none of his winners
captured. Those dates lie in the HOLDOUT and after it, so for round 2 the holdout is CONTAMINATED as a source of ideas and is
not used as confirmation. Round-2 arms are judged on TRAIN only (dates that played no part in forming the idea) and can only
earn a PROSPECTIVE Practice experiment, never an adoption.

| id | factor | definition | source of the idea |
|----|--------|------------|--------------------|
| E1 | target collision | `target_collision=replan`: when a setup's planned target IS its own source level, re-derive the destination from the next structural level beyond the entry (the F81b order: pre-market extreme ahead, else next ladder level), on any day type; still refused when nothing distinct lies ahead. Default `refuse` is unchanged | Collision refusals emptied 31 of 36 symbol-days they touched, including the author's 2026-09-03 SPY and 2026-09-10 IWM winners; his own plan named a farther level |
| E2 | target exit | `target_exit=false`: no outright sale of the whole position at the first planned level; trims, the candle stop and the flatten manage it | His documented winners run +112% to +445% on real prints; our baseline sells 100% at the first level for +26% on average |

Criteria: the same six as round 1, with criterion 2 (holdout) replaced by: "reported on the holdout for information, not as
confirmation". No other arm or value.

---

## Round 3 (registered 2026-09-19, after rounds 1 and 2 failed on TRAIN and before any round-3 arm was run)

Observation that prompted it (baseline entries, TRAIN, real prints, exit-free): the chosen contract prints at +50% or better within
120 minutes on 53% of entries and at +100% on 31%, while the baseline wins 33% of trades: exits are judged on 2m closes and the
whole position is sold at the first level. The author "sells into strength".

Entries are the BASELINE's entries, unchanged (from the TRAIN baseline run). Only the exit differs. An entry made while the same
symbol's bracket position is still open is dropped.

| id | exit definition (real option 1m prints) |
|----|------------------------------------------|
| X1 | Resting limit sell of the whole position at entry x 1.50, filled at the limit when a later minute prints at least one tick above it. Premium stop: a 1m option close at or below entry x 0.70 sells at the next minute's open. Time stop: 60 minutes after entry, sell at that minute's open. Flatten 15:45. No candle stop, no target exit, no trims |
| X2 | The same with the limit at entry x 2.00 |

Costs, windows and criteria as round 2 (TRAIN only; can only earn a prospective experiment). Stress case: limit fills require two
ticks above the limit and every market exit gives up one tick. No other bracket values.
