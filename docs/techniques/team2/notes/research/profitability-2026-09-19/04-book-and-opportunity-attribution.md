# 4. Chronological opportunity and book attribution

## A. The 2026-09-18 divergence between C1 and Control, traced in the journal (actual events, independently verifiable)

Question: why did C1 not take the SPY put that Control and Sizing took at 10:22, and why did C1 then take a QQQ put that Control
and Sizing did not?

| ET | Control (and Sizing 0.5) | C1 Conjunction |
|---|---|---|
| 10:00:00 | SPY contact refused: inside the pre-market range (`skip_no_trade_zone`) | same refusal |
| 10:12:03 | IWM 283P bought (40 / 24) | IWM 283P bought (40) |
| 10:14:01 | no SPY event (the zone refusal is journaled once per setup, at 10:00); no fire | The conjunction zone ADMITS it: SPY `scenario_4@09:45` **touch #1 fires**, and the runner refuses it for `max_concurrent_positions` (the IWM position is open). The read records `fire_unfilled_live ... touch #1` |
| 10:16:01 | no fire | SPY **touch #2 fires**, refused again for `max_concurrent_positions`; `fire_unfilled_live ... touch #2` |
| 10:20:03 | IWM stopped (loss 1) | IWM stopped (loss 1) |
| 10:22:00 | SPY contact now outside Control's zone: **touch #1 fires**, SPY 758P bought (30 / 17) | The same contact is **contact #3** for C1: `late_touch ... past the first 2 pullbacks, watch-only (D9/P6)`. No entry |
| 10:24:01 | SPY stopped (loss 2): desk cap reached | — |
| 10:46 | QQQ `pm_break_down@10:30#1` fires, refused: `skip_loss_cap_desk` (two losses) | QQQ same fire; C1 has ONE loss, so it is admitted: QQQ 714P bought 10:46:17, stopped 10:48:02 |

Findings, in the order they matter:

1. **C1's newly admitted opportunities on that day were two SPY contacts at 10:14 and 10:16, and both were displaced by occupancy.**
   They produced no fill, but each SPENT one of the setup's two pullback allowances. A no-trade-zone refusal does not spend the
   allowance (D9/F18); a fire that the runner refuses does.
2. So when SPY offered the contact Control took at 10:22, C1 had no allowance left. C1 "missed" SPY because of its own earlier,
   unfilled admissions, not because of any difference in the 10:22 read.
3. C1's QQQ trade is a second-order effect of the same thing: having skipped the SPY loss, it still had room under the two-loss cap.
4. Consequence for the experiment: **the C1 book does not differ from Control by one factor in practice.** The zone rule changes
   which contacts fire, which changes allowance consumption, occupancy and the loss counter for the rest of the day. Any C1-versus-Control
   comparison must attribute admitted, displaced and downstream trades separately, as this table does. One day; no performance conclusion.
5. Whether a refused fire should spend the pullback allowance is a method question I am flagging, not changing.

## B. What the simplified book simulation reproduces, and what it does not

`harness/book.py` is a **SIMPLIFIED RESEARCH SIMULATION**. It is not decision-grade and its drawdowns are **not a calibrated
forecast of the running books**.

| Behaviour of the deployed system | In the simulation |
|---|---|
| One open position per book across the three symbols | reproduced (time order, across symbols) |
| Sizing: floor of min(bucket x equity x 6% / (premium x 25), $2,000 / (premium x 100), 40); checked against the 09-18 fills (40, 30, 24, 17 contracts) | reproduced |
| Integer contracts on every leg; trims and adds as whole contracts; fees on executed contracts | reproduced (v2; v1 used fractional percentages) |
| Two-loss desk cap on the deployed GROSS basis | reproduced (v2; v1 counted net losses) |
| 10% technique day-loss pause | reproduced on realized equity |
| A refused fire spends the setup's pullback allowance and changes later fires (section A) | **NOT reproduced**: a displaced trade is dropped and the symbol's later sequence is left as the per-symbol replay produced it. Direction of the error: unknown; it can remove later entries (as on 09-18) |
| Deferrals and re-prices by the live NBBO picker; partial fills; the stale-signal (`backdated`) refusal | not reproduced |
| Size-after-a-win rule, 15% book breaker | not reproduced |
| Marked-to-market equity between fills | not reproduced; `mtmTroughApprox` uses the lowest PRINT during each hold, which is neither a bid nor a continuous mark |

With those limits, on the corrected baseline (no extra slippage, $1.04 fee, `proxy` targets):

| Window | Taken | Displaced by occupancy | Displaced by the loss cap | Realized P&L | Largest realized drawdown | P&L of the three best days |
|---|---|---|---|---|---|---|
| 05-07 to 09-18 | 191 | 46 | 95 | +$797 | $7,855 | +$13,525 |
| Training 05-07 to 08-14 | 154 | 43 | 85 | +$3,318 | $7,855 | +$13,525 |
| Training, one tick of slippage per leg | 147 | 39 | 89 (+4 day-loss pause) | -$4,639 | $11,005 | +$10,273 |

The only robust statement: **the simulated book's result is smaller than the contribution of its three best days under every cost
assumption**, so it says nothing reliable about the sign of the expectancy, and its drawdown figures depend on sizing at about a
fifth of the book per trade. I no longer present the drawdown as a forecast.

## C. Displaced opportunities (descriptive; 05-07 to 09-11; date-clustered 95% intervals)

| Group | Trades | Dates | Mean net return | Interval |
|---|---|---|---|---|
| Taken by the book | 186 | 75 | -0.60% | -6.4 to +5.5 |
| Displaced by occupancy | 46 | 31 | -10.04% | -17.4 to -1.4 |
| Displaced by the two-loss cap (gross basis) | 90 | 36 | -5.41% | -11.9 to +1.7 |

The displaced trades were not better than the taken ones in this replay. That is weak evidence that the one-position rule and the
loss cap do not cost money; it is not proof that they help (the intervals overlap, and section A shows displacement also has
downstream effects this table cannot see).

## D. Refusals across the corrected baseline (279 symbol-days; read decisions, not data gaps)

| Refusal | Events | Symbol-days touched | Of which no trade that day |
|---|---|---|---|
| `skip_no_trade_zone` | 313 | 191 | 84 |
| `skip_target_behind` | 293 | 53 | 25 |
| `skip_target_collision` | 288 | 36 | 31 |
| `skip_engulfing` | 134 | 94 | 38 |
| `skip_loss_cap` (per symbol) | 78 | 78 | 0 |
| `skip_no_contract` (no observed print in the premium band) | 15 | 6 | 1 |
| `skip_range_confirmation` | 11 | 9 | 1 |
| `skip_last_entry` (after 15:30) | 279 | 279 | 103 |

## E. Live refusals 2026-09-11 to 09-18 (journal; Practice, then Control)

| Date | No-trade zone | Engulfing | Loss cap (symbol / desk) | Signal older than three minutes at the decision | Max concurrent |
|---|---|---|---|---|---|
| 09-11 | 4 | 0 | 0 | 0 | 0 |
| 09-14 | 2 | 0 | 0 | 0 | 0 |
| 09-15 | 4 | 1 | 0 | 0 | 0 |
| 09-16 | 7 | 6 | 2 / 2 | 4 | 1 |
| 09-17 | 8 | 0 | 0 | 0 | 0 |
| 09-18 | 6 | 3 | 1 / 3 | 4 | 0 |

OPERATIONAL (reported apart from method performance): eight `backdated_signal_skip` events on 09-16 and 09-18, fires whose bar was
more than three minutes old when the decision ran; and the sampled-monitor observation on page 1, section D.
