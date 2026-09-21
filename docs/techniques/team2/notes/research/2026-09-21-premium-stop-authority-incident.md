# F129 — a pricing model forced a live sale: the 2026-09-21 IWM incident and the fix

Date: 2026-09-21 · Desk: Team2 · Scope: the model-to-order path only. No threshold, fee convention,
quote-validity policy, sizing, experiment override, selection-study or C2 change.

## 1. What happened

Book `Team2 C1 Conjunction`, plan run `9842047f8c0547fe99bc173fb9c0ae54`, trigger
`scenario_1@09:45#1`.

| time (ET) | record | what it says |
|---|---|---|
| 10:36:00 | `TechniquePlanRead` `model_out_of_band` | the modelled pick was outside the premium band; the live quotes decide (F108) |
| 10:36:03 | `TechniquePlanContract` `contract_picked` | `IWM260921C00286000`, ask 0.33 / bid 0.32, source `opra` |
| 10:36:03 | `TechniquePlanTriggerFired` | EMA13 285.77 held, close 285.83, bull stack; the read's own estimate was "buy call 286 ≈ $0.18" |
| 10:36:13 | execution | BUY 35 @ **0.33**, fee 36.40 |
| 10:40:01 | `TechniquePlanExit` | `kind=stop`, `MKT`, reduce-only, reason **"premium stop: -32% ≤ −25% (P1/D13)"** |
| 10:40:03 | execution | SELL 35 @ **0.2899**, fee 36.40 |

Result: −$140.35 gross, −$213.15 after fees. The same thing happened again the same morning on
touch #2: bought 11:30:40 @ 0.32, sold 11:36:09 @ 0.2899, on the same modelled −32%.

## 2. Where the −32% came from

It was never the contract the desk held.

- The **model's** proxy was marked ≈ $0.1794 at entry and ≈ $0.1391 at the exit. With the
  $1.04/contract fee convention the pure read uses, that is −32%: `(13.91 − 1.04 − (17.94 + 1.04)) /
  (17.94 + 1.04)`.
- The **held** contract went 0.33 → 0.2899, about −12% gross.
- Under the desk's *configured* premium stop (`premium_stop_pct` 25, `premium_stop_basis` mid,
  `premium_stop_min_ticks` 3) the stop line on a $0.33 fill is
  `min(0.33 × 0.75, 0.33 − 3 ticks) = 0.2475`. The contract never reached it.

The divergence is exactly what the 10:36:00 `model_out_of_band` read announced: the model was
pricing a different (out-of-band) strike while the live NBBO picker filled the real one.

## 3. The defect

`Team2Runner._exit_from_event` consumed the pure read's instructions. For a modelled **trim** it
first asked the contract's own live premium (`_live_pct`) and deferred when the contract had not got
there (`trim_deferred_live`). For a modelled **premium stop** it asked nothing: the instruction went
straight to `_exit(..., force_market=True)`. A monetary decision made on a proxy price was therefore
able to market-sell a live position on its own.

Every other Team2 exit reads the underlying — the S1 candle stop, the X3 target, the C3 flatten —
which the model and the desk share. The premium stop is the only *priced* one, and it was the only
one with no live check.

## 4. Did the structural stop independently require the 10:40 exit?

**Yes.** The entry leaned on EMA13 (`entry_kind = ema`), and the journalled fire snapshot puts EMA13
at 285.7729 on the 10:36 2m bar. Rolling that forward over the stored exchange bars:

| 2m close (ET) | close | EMA13 | through? |
|---|---|---|---|
| 10:36 | 285.83 | 285.7729 | held |
| 10:38 | 285.77 | 285.7732 | held |
| **10:40** | **285.72** | **285.7656** | **through** |
| 10:42 | 285.75 | 285.7633 | through |

With `stop_candles = 1` the S1 one-candle stop fires on that same 10:40 close. The second round trip
is the same story: the 11:36 close 285.85 was through EMA13 285.9175.

So the money was not lost to the defect — both exits were structurally due at the moment they
happened. What was wrong is the **authority and the record**: the desk sold on a modelled price and
the journal attributed the sale to a premium stop that the held contract never breached. On a day
where structure had *not* also broken, the same defect sells a position that its own stop says to
keep.

## 5. The fix

**One rule: a monetary premium decision is judged on the fill the desk paid and a valid live quote
for the contract it holds, under the convention already configured.** Nothing about the threshold,
the fee convention or the quote-validity policy changes.

- `PlanRunner.live_premium_basis(trade)` (shared) is now the single implementation of "what price
  does the configured premium stop measure right now, and where did it come from". It is the 2 s
  quote watch's own logic, extracted verbatim: per-technique basis (F30), `stale_seconds`, no
  delayed rows (R4), and a *fresh* real-time quote with no bid is `0.0` — a total bleed, not a gap.
  The quote watch now calls it, so the two paths cannot drift.
- `Team2Runner._premium_stop_authority` runs the same `premium_stop_breach` predicate the live watch
  runs, with the same `premium_stop_pct` / `premium_stop_basis` / `premium_stop_min_ticks`.
- In `_exit_from_event`, a modelled instruction whose reason is a premium stop now sells only if
  that check confirms on the held contract. Otherwise nothing is sold and the disagreement is
  recorded as `premium_stop_not_live` (log + `TechniquePlanRead`), with the model's own numbers kept
  under `model` as diagnostics.
- Structural instructions are untouched: the candle stop, the target and the flatten still act
  immediately, and the failed-exit watchdog, the underlying quote stop and the 15:45 flatten are not
  in this path at all.

### The model closing its proxy while the book stays open

That is now an ordinary state, so it is handled by the guard that already exists for it. When the
model's proxy is closed and ours is not, `_guard_orphaned_positions` (G) judges the S1 rule on the
**current** 2m close against the line the entry leaned on and issues the stop *now*. In the incident
this produces the same 10:40 exit, correctly attributed to present-time structure. Occupancy is
unaffected (`max_open_trades` counts the desk's own open/working trades, so the model re-entering
its proxy cannot open a second position), and loss accounting is unaffected (a money-mode plan is
judged by its **book** — filled, closed losers only — so a proxy the model closed spends no loss
allowance).

### The journal now names the authority

Every exit this path produces carries an `authority` record on `TechniquePlanExit`:
who decided (`held_contract`, `live_quote_watch`, `model_structural`, `model_tp3`, `model_flatten`,
`present_time_structural`), the fill basis, the live quote with its source timestamp and age, the
return that follows from the two, the configured threshold, and the stated convention. Model numbers
ride along under `model` and are never the basis.

## 6. Audit of the other model-generated monetary instructions

| instruction | priced by | verdict |
|---|---|---|
| modelled trim (`tp1` / `tp2`, V2 and the X1 new-extreme cue) | model premium | already gated on the contract's live premium (`trim_deferred_live`) — unchanged |
| modelled premium stop | model premium | **was ungated — fixed here** |
| modelled candle stop (S1), target (X3/V11, X3b), flatten (C3) | the underlying | shared with the desk; unchanged, now attributed |
| X5 add | live ask, live size, RiskGate, never-chase | the *trigger* is structural, but the model's add assumes the model's trim happened. With the book still whole there is no freed room and the add would carry more size than the method describes. An add is now refused in that state (`add_no_room`) — the same authority rule, not a new threshold |
| entry / contract choice | live NBBO picker (`quotes` authority, F104/F105/F108) | already correct: the model never vetoes and never prices an order |
| live quote-watch premium stop, underlying quote stop, failed-exit watchdog, `_clock_flatten` | the desk's own quotes and clock | never model-driven; unchanged |

## 7. Acceptance tests

`backend/tests/test_team2_premium_stop_authority.py`, 13 cases:

- **(a)** the model breaches its stop and the held contract does not → nothing is sold, and the
  record carries fill basis, live quote, source timestamp, return and threshold.
- **(b)** the held contract breaches and the model does not → protection still acts; **(b2)** the
  2 s live watch keeps its own authority and forward-confirmation rule.
- **(c)** the structural stop fires → the exit is allowed and attributed; **(c2)** after a deferred
  premium stop the present-time S1 guard takes the position out with its own authority.
- **(d)** missing, stale and delayed quotes → no model-priced sale, no substituted model price;
  **(d2)** a fresh real-time quote with no bid is still a total bleed.
- **(e)** the disagreement survives a restart: the position, its cost basis and its protection all
  come back off the durable row.
- **(f)** partial fills and a completed trim keep the remaining quantity and the original cost
  basis, and a duplicate model event never sells twice; **(f2)** an add never re-fills room the desk
  did not free.
- **(g)** target, flatten and the live-trim deferral are unchanged and each says its authority.
