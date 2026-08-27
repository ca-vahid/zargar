# Rulebook index — rule id → statement → spec section

Generated from `backend/zargar/technique/rulebook.py` (`RULES`) and the headings of
`docs/techniques/enhanced-market/METHOD.md` (which cites the PDF pages). When a review needs the
book's own words, read the spec section first; for the PDF use the `pdf` skill or
`Read` with `pages=` on `docs/Day Trading 101 - From Beginer to Expert.pdf`.

| rule | statement | spec section (line) |
|---|---|---|
| `T1.1` | Support stalls declines; resistance stalls advances. | T1.1 Definitions (L53) |
| `T1.2` | A level needs >=2 touches to be real; 3+ is strong. | T1.2 What makes a level real (L57) |
| `T1.3a` | Prior-day HOD/LOD levels are the strongest. | T1.3 Level sources, in priority order (L66) |
| `T1.3b` | Previous day's support/resistance carries into today. | T1.3 Level sources, in priority order (L66) |
| `T1.3c` | Intraday swing highs/lows with >=2 touches are levels. | T1.3 Level sources, in priority order (L66) |
| `T1.3d` | Round numbers act as levels on their own. | T1.3 Level sources, in priority order (L66) |
| `T1.5` | Trendlines: <=45 degrees, consistent anchoring, >=3 touches. | T1.5 Trendline drawing rules (L83) |
| `T2.1` | Rising price + rising volume confirms the trend. | 3. Module T2 — Volume analysis (L93) |
| `T2.2` | Rising price + falling volume is bearish divergence. | 3. Module T2 — Volume analysis (L93) |
| `T2.3` | Falling price + falling volume means selling is exhausting. | 3. Module T2 — Volume analysis (L93) |
| `T2.4` | A volume spike after a long trend can mark a climax reversal. | 3. Module T2 — Volume analysis (L93) |
| `T2.5` | A breakout with a volume surge is genuine. | 3. Module T2 — Volume analysis (L93) |
| `T2.6` | A breakout on low volume is a fakeout warning. | 3. Module T2 — Volume analysis (L93) |
| `T2.7` | Large volume on small price movement signals institutional activity. | 3. Module T2 — Volume analysis (L93) |
| `T2.8` | Low volume in consolidation precedes a significant move. | 3. Module T2 — Volume analysis (L93) |
| `T2.9` | Volume is always judged against a time-of-day baseline. | 3. Module T2 — Volume analysis (L93) |
| `T3.1a` | Falling wedge: lower highs and lower lows. | T3.1 Falling wedge (the primary pattern) (L119) |
| `T3.1b` | Falling wedge: converging lines, upper steeper than lower. | T3.1 Falling wedge (the primary pattern) (L119) |
| `T3.1c` | Falling wedge: volume decreases as it forms. | T3.1 Falling wedge (the primary pattern) (L119) |
| `T3.1d` | Falling wedge entry: decisive break above the upper trendline. | T3.1 Falling wedge (the primary pattern) (L119) |
| `T3.1e` | Falling wedge stop: below the lowest point of the wedge. | T3.1 Falling wedge (the primary pattern) (L119) |
| `T3.1f` | Falling wedge target: widest height projected from the breakout. | T3.1 Falling wedge (the primary pattern) (L119) |
| `T3.2` | Consolidation gives a tight stop and a high-probability entry. | T3.2 Consolidation / flag patterns (L142) |
| `T3.3a` | True breakout: volume tapers into the level, then surges. | T3.3 Breakout vs Fakeout (L147) |
| `T3.3b` | True breakout: large candle closing clearly beyond, minimal wicks. | T3.3 Breakout vs Fakeout (L147) |
| `T3.3c` | True breakout: follow-through in the next few candles. | T3.3 Breakout vs Fakeout (L147) |
| `T3.3d` | Fakeout: no volume behind the move. | T3.3 Breakout vs Fakeout (L147) |
| `T3.3e` | Fakeout: quick reversal, long wick, closes back inside. | T3.3 Breakout vs Fakeout (L147) |
| `T3.3f` | Fakeout: fails to hold the level it broke. | T3.3 Breakout vs Fakeout (L147) |
| `T3.3g` | A lower-timeframe breakout may be a higher-timeframe fakeout. | T3.3 Breakout vs Fakeout (L147) |
| `T3.4a` | Close near the high = buyers control; near the low = sellers. | T3.4 Candlesticks & momentum (L170) |
| `T3.4b` | Long wicks are rejection; lower wick bullish, upper bearish. | T3.4 Candlesticks & momentum (L170) |
| `T3.4c` | Dominant-colour candles grow larger in a strong trend. | T3.4 Candlesticks & momentum (L170) |
| `T3.4d` | Context overrides the individual candle. | T3.4 Candlesticks & momentum (L170) |
| `T3.5a` | Uptrend = higher highs and higher lows. | T3.5 Trend structure (L185) |
| `T3.5b` | Downtrend = lower highs and lower lows. | T3.5 Trend structure (L185) |
| `T4.1` | Enter at the level; compute R:R from the level, never chase. | T4.1 The entry principle (L195) |
| `T4.2` | Do not wait for visual confirmation on a bounce entry. | T4.2 The "visual confirmation" trap (L216) |
| `T4.3a` | Stop is mental, referenced just beyond the invalidating level. | T4.3 Stop-loss (L231) |
| `T4.3b` | On a stop touch, judge the reaction before exiting. | T4.3 Stop-loss (L231) |
| `T4.3c` | Averaging down requires a hard stop, not a mental one. | T4.3 Stop-loss (L231) |
| `T4.4a` | Scale out 30/40/15 with a 15% runner. | T4.4 Take-profit ladder (L250) |
| `T4.4b` | Never exit on P&L; exit on the chart. | T4.4 Take-profit ladder (L250) |
| `T4.5` | Average down only with a catalyst, with the trend, at support, preplanned. | T4.5 Averaging down (L268) |
| `T5.1` | Trade strikes just out of the money. | 6. Module T5 — Options expression (L285) |
| `T5.2` | Weeklies to current-week Friday; 0DTE with reduced size. | 6. Module T5 — Options expression (L285) |
| `T5.3` | Do not buy elevated IV — IV crush loses money on a correct call. | 6. Module T5 — Options expression (L285) |
| `T5.4` | Avoid wide spreads, inflated premium, high theta / low delta. | 6. Module T5 — Options expression (L285) |
| `R1` | Risk 0.5-1% per trade; 5% is the hard ceiling; never full-port. | R1 Position sizing (L316) |
| `R2` | Require R:R >= 3.0. | R2 Win rate / R:R (L328) |
| `R3.1` | No trade when volume is below 50% of average. | R3 No-trade conditions (L336) |
| `R3.2` | No trade in choppy action or after >2 false breakouts in the first hour. | R3 No-trade conditions (L336) |
| `R3.3` | No trade on poor contract conditions. | R3 No-trade conditions (L336) |
| `R3.4` | No trade on holidays, FOMC days, or major economic releases. | R3 No-trade conditions (L336) |
| `R5` | One contract per trade while the technique is being validated. | R5 One-Contract Rule (L354) |

## Rule → detector / check that enforces it

| rule | enforced by |
|---|---|
| T1.2, T1.3a–d | `levels.detect_levels` (touch clustering, prior-day HOD/LOD, round numbers) |
| T1.5 | `structure.fit_line`, `detect_wedge` slope checks |
| T2.1–T2.9 | `volume.build_profile` / `assess_volume` (time-of-day baseline, spike/dry-up/floor) |
| T3.1a–f | `structure.detect_wedge`, `setups.build_breakout_setup` (wedge target = widest height) |
| T3.2 | `setups` consolidation handling, PASS 2 prompt |
| T3.3a–g | `setups.classify_breakout` (volume, decisive candle, follow-through, holds level); PASS 4 critic; `grounding` breakout_confirmed |
| T3.4a–d | `candles.metrics` / `classify` |
| T3.5a–b | `structure.read_trend` |
| T4.1, T4.2 | `setups.build_bounce_setup` (entry AT the level, no confirmation); `grounding` bounce_not_chased / entry_grounded |
| T4.3a–c | stop kind/reference in `TechniqueAnalysis`; `grounding` stop checks |
| T4.4a | `setups.build_ladder` 30/40/15 + 15% runner; `outcome.simulate_plan` trims |
| T5.1–T5.4 | `options.pick_for_setup` (just-OTM strike, current-week Friday, IV/spread/theta warnings) |
| R1 | `service._emit_proposal` sizing (`technique.default_risk_pct`, `max_risk_pct`) |
| R2 | `setups.risk_reward` + `valid`; `grounding` rr_meets_R2; `min_risk_reward` |
| R3.1 | `volume.assess_volume.below_floor` → candidate no-trade reason |
| R3.2–R3.4 | model judgement (PASS 3/4) — not detected deterministically |
| R5 | proposal qty / note only |
