# 3. Opportunity ledger

How it was built. Every decision is reconstructed by the desk's own pure read (`simulate_session`) walking 1m bars forward in
time order, so a setup is recognised only with the bars that had closed. Option prices are real prints at the decision minute.
No option quote is invented. Nothing after a decision feeds that decision; the "what happened next" columns are outcomes.
Machine-readable ledger: each run file under `harness/` output keeps, per symbol-day, every event (`confirm`, `fire`, `skip_*`,
`exit`) with its time, price and reason; the summaries below come from `results/` and `harness/author_ledger.py`.

## A. The author's documented trades inside the data window, against ours

Real prints for his contract; our side is the baseline read on the same tape. Six executions plus one chart.

| Date | His trade (evidence class) | His contract on real prints | Our read | What we did | Why we missed it | Attribution |
|---|---|---|---|---|---|---|
| 09-01 IWM | 292P, card +474%, sold 12:34 (EXEC; entry time not documented) | session low 0.19, high 2.00 | scenario 4, puts: same | two entries 09:50 and 10:04 on the 291P, both stopped (-24.5%, -25.2%), then the loss cap | in the trade, shaken out twice within 12 minutes, then capped | exit management + loss cap |
| 09-03 SPY | 770C about 11:00, sold 11:19 "over 500%"; two earlier attempts stopped (EXEC) | 0.56 at 11:00, 2.38 at 11:19 (+325%), never below entry | scenario 1, calls: same | no trade all day | `skip_target_collision` x5 (planned target 768.00 was the broken level; his plan named 775.29), `skip_engulfing` x2 at 10:56 | signal rules: target derivation, engulfing filter |
| 09-09 IWM | 293P at the 09:41 retest of a 3-day level, +142% (EXEC per our note) | 0.49 at 09:41, 2.67 by the close (+445%), worst -10% | scenario 4, puts: same | entries 10:32 (-1.1%) and 10:42 (+12.3%), both sold at a near re-planned level; then `skip_target_collision` x16 | his entry precedes our 09:45 gate and needs a multi-day level (C2, off); our exits sold the whole position 0.5 points away | signal rules: entry gate, levels; exit management |
| 09-10 IWM | 288P about 14:00 after a five-hour wait, +85/+100% (EXEC per our note) | 0.40 at 14:00, 0.85 at 15:08 (+112%), worst -20% | scenario 4, puts: same | no trade all day | `skip_no_trade_zone` x3 in the morning, `skip_target_collision` x14 from 13:40, `skip_engulfing` at 14:04 | signal rules: target derivation, engulfing filter |
| 09-11 SPY | 768C at the 09:46 2m close, +50% trim, +$801 (EXEC per our note) | 0.40 at 09:46, best 0.57 at 09:59 (+42%), worst -30% | scenario 1, calls: same | no trade all day | `skip_no_trade_zone` at 09:46: the entry sat inside the pre-market range | signal rules: no-trade zone |
| 09-18 IWM | CHART ONLY, no execution: EMA13 pullback / bear-flag break about 09:46 to 09:52 | our 283P: 0.34 at 09:48, 0.72 at 10:05 (+112%) | scenario 4, puts: same | first entry 10:12 at 0.48, after the move; stopped 10:20 (-8.3%) | no refusal is recorded between 09:46 and 10:12: price never came back to the EMA13 within tolerance, and the code has no flag-break entry | signal rules: no flag detector (setup recognised late) |

One row of the fidelity table is excluded: the "2026-07-14 SPY 624C" card cannot be July 2026 (SPY traded near 750); its year was inferred wrongly.

Reading. **Direction and scenario matched on six of six. Winners captured: none.** No miss was caused by data availability or by
execution. Five are signal rules (target derivation twice, no-trade zone once, entry gate and levels once, missing flag entry once)
and one is exit management plus the loss cap. His contracts did what he said: the real prints confirm gains of +112% to +445%
with heat of -10% to -30% on the way.

Caution. These are his published winners. The same rules that refused them also refused trades that lost: the collision re-plan
(arm E1), measured on the training window, added trades that lost like the rest (`05-hypotheses-and-results.md`). Six rows cannot rank rules.

## B. Refusals across the whole replay window (279 symbol-days, 2026-05-07 to 09-18)

176 symbol-days traded, 103 did not.

| Refusal | Events | Symbol-days touched | Of which days with no trade at all |
|---|---|---|---|
| `skip_no_trade_zone` (inside the pre-market range) | 311 | 190 | 84 |
| `skip_target_behind` (price already through the target) | 293 | 53 | 25 |
| `skip_target_collision` (target is the setup's own level) | 288 | 36 | 31 |
| `skip_engulfing` (lunge into the EMA) | 134 | 94 | 38 |
| `skip_loss_cap` (two losses in the symbol) | 80 | 80 | 0 |
| `skip_no_contract` (no real print in the premium band) | 13 | 5 | 1 |
| `skip_range_confirmation` | 11 | 9 | 1 |
| `skip_last_entry` (after 15:30) | 279 | 279 | 103 |

## C. Live refusals, 2026-09-11 to 09-18 (journal, `TechniquePlanTriggerSkipped`, Practice then Control)

| Date | No-trade zone | Engulfing | Loss cap (symbol / desk) | Signal older than 3 minutes at decision | Max concurrent |
|---|---|---|---|---|---|
| 09-11 | 4 | 0 | 0 | 0 | 0 |
| 09-14 | 2 | 0 | 0 | 0 | 0 |
| 09-15 | 4 | 1 | 0 | 0 | 0 |
| 09-16 | 7 | 6 | 2 / 2 | 4 | 1 |
| 09-17 | 8 | 0 | 0 | 0 | 0 |
| 09-18 | 6 | 3 | 1 / 3 | 4 | 0 |

`backdated_signal_skip` (eight events on 09-16 and 09-18) is the only execution-side refusal in the period: a fire whose bar was
more than three minutes old when the decision ran. It is an operational item, reported apart from method performance; it did not
coincide with any of the author's trades.

## D. Displaced opportunities (book rules applied in time order, 2026-05-07 to 09-11)

| Group | Trades | Win rate | Mean net return | 95% interval |
|---|---|---|---|---|
| Taken by the book | 183 | 33.9% | -0.35% | -5.8% to +6.1% |
| Displaced because a position was already open | 46 | 30.4% | -10.26% | -17.8% to -2.1% |
| Displaced by the two-loss desk cap | 94 | 30.9% | -5.80% | -11.7% to +0.7% |

The displaced trades were worse than the taken ones. On this evidence the one-position rule and the two-loss cap protect the
book; the fidelity audit's concern that the cap costs winners (his 2026-09-03 third attempt) is one documented case against 94
measured ones.
