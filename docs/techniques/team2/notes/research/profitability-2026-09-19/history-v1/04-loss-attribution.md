# 4. Where profitability is lost

Replayed baseline rules, real option prints, fees included, no extra slippage, 2026-05-07 to 2026-09-11 unless stated
(323 trades; the five sessions after it are shown apart). Intervals are bootstrap 95%. Source: `results/final_stats.txt`,
`results/horizon_train.txt`. This page is MODELLED REPLAY on real prices, never actual fills (those are on page 1).

## The five layers

| Layer | Finding | Number |
|---|---|---|
| 1. Direction of the underlying | **None.** Measured from the real price at the decision minute, the underlying is on our side 50.5%, 50.9%, 48.4%, 51.6%, 54.1% and 49.8% of the time at 4, 10, 20, 30, 60 and 120 minutes, with a mean move of 0.00% | 283 training entries |
| 2. Entry timing | The read books its hypothetical fill at the EMA or level line; the order goes out after the bounce bar has closed. Measured from the line, direction looks like 61% at ten minutes; measured from the real price it is 51%. The apparent edge is the distance already travelled before we can buy | same entries |
| 3. Contract | Held with no exit rule at all, the chosen contract returns -1.5%, -4.4%, -3.3%, -3.3%, +0.1% and +3.1% net at the same six horizons, each within about one standard error of zero. A dearer contract (arm H5) loses less per trade but still loses | `results/horizon_train.txt` |
| 4. Spread and fees | $1.04 per contract per side is 3.9% of cost per round trip on a mean real premium of $0.56. Gross of fees the baseline is about zero; net it is -3.8%. One tick of slippage per leg moves it to -7.0% | 333 trades |
| 5. Exit management | 51% of trades are closed within two 2m bars at -11.7%. Stops take 222 of 323 trades. Targets pay +27% on average because the first level is close (median room 0.23% of price). Yet every exit variant tested was worse than the baseline's exits | table below |

Layers 1 to 3 say the same thing three ways: **the entry, as the code recognises it, does not predict the next two hours.**
Exits cannot recover an edge the entry does not carry, which is why nine exit and filter arms failed.

One more fact belongs here. Within 120 minutes of entry the contract prints at +50% or better on 53% of entries and at +100% on
31%. That is a ceiling no rule can reach, and it is what a 0DTE option does on any random entry. It explains why the author's
hand-picked winners look the way they do, and why it is not evidence of an edge.

## By setup

| Setup | Trades | Win rate | Mean net | 95% interval |
|---|---|---|---|---|
| pm_break_up | 87 | 25.3% | -6.33% | -14.5 to +3.9 |
| pm_break_down | 84 | 33.3% | -4.76% | -11.2 to +2.8 |
| scenario_1 (break of the prior-day high) | 74 | 33.8% | -2.05% | -9.6 to +6.4 |
| scenario_4 (break of the prior-day low) | 58 | 43.1% | +2.03% | -5.3 to +10.0 |
| scenario_2 | 15 | 20.0% | -10.54% | -21.6 to +4.2 |
| scenario_3 | 5 | 40.0% | +12.26% | -22.4 to +46.9 |

## By market condition (day type)

| Day type | Trades | Win rate | Mean net | 95% interval |
|---|---|---|---|---|
| normal | 159 | 35.8% | -1.84% | -6.8 to +3.4 |
| gap up | 70 | 24.3% | -4.80% | -14.8 to +7.1 |
| inside | 64 | 34.4% | -5.43% | -12.2 to +2.0 |
| gap down | 30 | 30.0% | -3.48% | -14.9 to +10.8 |

## By time of day

| Entry time (ET) | Trades | Win rate | Mean net | 95% interval |
|---|---|---|---|---|
| 09:45 to 10:00 | 39 | 38.5% | +4.31% | -10.4 to +22.8 |
| 10:00 to 11:00 | 142 | 31.7% | -5.16% | -10.2 to +0.4 |
| 11:00 to 12:00 | 77 | 29.9% | -4.23% | -11.3 to +3.5 |
| 12:00 to 14:00 | 44 | 36.4% | -0.56% | -10.9 to +10.0 |
| 14:00 to 15:30 | 21 | 28.6% | -7.89% | -20.3 to +6.5 |

## First entry versus re-entry, entry line, size bucket, symbol, direction

| Group | Trades | Win rate | Mean net | 95% interval |
|---|---|---|---|---|
| First entry (touch 1) | 200 | 30.0% | -2.97% | -8.1 to +2.7 |
| Re-entry (touch 2) | 123 | 36.6% | -3.96% | -9.4 to +2.1 |
| Entry on the EMA13 | 205 | 32.2% | -4.48% | -8.8 to +0.3 |
| Entry on the level | 104 | 32.7% | -2.74% | -10.2 to +5.9 |
| Entry on the EMA48 | 14 | 35.7% | +8.76% | -12.5 to +31.9 |
| Full size bucket | 102 | 36.3% | -0.32% | -6.8 to +7.0 |
| Small size bucket | 221 | 30.8% | -4.74% | -9.2 to +0.2 |
| SPY | 104 | 33.7% | -0.24% | -7.9 to +8.5 |
| QQQ | 99 | 32.3% | -5.52% | -11.4 to +0.7 |
| IWM | 120 | 31.7% | -4.25% | -10.4 to +2.3 |
| Long (calls) | 166 | 29.5% | -3.86% | -9.8 to +2.8 |
| Short (puts) | 157 | 35.7% | -2.80% | -7.5 to +2.6 |

**No cell is distinguishable from zero on the upside.** The cells that look positive (scenario 4, the first fifteen minutes, EMA48
entries, scenario 3) have intervals from deeply negative to strongly positive and were found by looking; none is a hypothesis
this study registered, and picking one now would be selection. They are listed as candidates for the order-free study on page 6.

## By exit and by hold

| Exit | Trades | Win rate | Mean net |
|---|---|---|---|
| Candle stop (one 2m close through the line) | 138 | 9.4% | -11.77% |
| Premium stop (-25%, judged at the 2m close, overshoots) | 84 | 2.4% | -29.79% |
| Target touched | 98 | 88.8% | +27.35% |
| Flatten 15:45 | 3 | 100% | +121.51% |

| Hold | Trades | Win rate | Mean net |
|---|---|---|---|
| Up to 2 bars (4 minutes) | 164 | 25.0% | -11.73% |
| 3 to 5 bars | 70 | 34.3% | -5.93% |
| 6 to 15 bars | 73 | 38.4% | +4.84% |
| More than 15 bars | 16 | 75.0% | +56.56% |

The hold table is survivorship, not a rule: trades that last are the ones that were right. Forcing trades to last (two-candle
stop, no target exit, 60-minute brackets) made results worse.

## Windows

| Window | Trades | Win rate | Mean net | 95% interval |
|---|---|---|---|---|
| Training 05-07 to 08-14 | 283 | 32.9% | -3.04% | -7.2 to +1.5 |
| Holdout 08-17 to 09-11 (baseline only, for information) | 40 | 30.0% | -5.54% | -13.4 to +3.6 |
| 09-14 to 09-18 | 10 | 0.0% | -17.12% | -22.6 to -12.0 |
| All | 333 | 31.5% | -3.76% | -7.6 to +0.1 |

## Book level (chronological, integer contracts, the desk's sizing, $10,000)

| Window | Final equity | Maximum drawdown | Final without the three best days | Green / red days |
|---|---|---|---|---|
| Training | $11,102 | $6,781 | $4,259 | 20 / 40 |
| All | $8,612 | $7,194 | $3,051 | not computed |
| Training, one tick of slippage per leg | $4,476 | $10,703 | $1,778 | not computed |

The training book ends above water only because of three days; without them it loses 57%. At the current sizing (6% of equity at
risk per entry, about a fifth of the book in premium) the drawdowns are the size of the account.
