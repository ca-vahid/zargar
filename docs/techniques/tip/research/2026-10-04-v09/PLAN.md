# Tips v0.9 plan - profit, horizons, stops, live safety (2026-10-04)

Inputs: [R1 money path](R1-money-path.md) · [R2 Tips pipeline](R2-tips-pipeline.md) · [R3 our horizon/exit record](R3-horizon-exits.md)
· [R4 external evidence (deep research, 103 agents, 3-vote verified)](R4-external-evidence.md).
User direction: maximise profit, avoid mistakes, cut losses in time, best information at decision time; plan each trade as
days / ~a week / multi-week (or months) with smart profit taking. Go-live: paper Monday 10-05, live after it passes.

**Already shipped tonight (0.8.62):** account-type guard, pending orders in the cap, T+1 unsettled proceeds, USD-only
live cash, venue-stop death re-placed, trim retried as a trim, BMO earnings window, one earnings resolver, per-book risk
overrides, spread sizing by debit, band only on the stated contract, sibling level strip, re-ask crash safety.

## What the evidence says (the design constraints)

1. **Stops are risk control, not edge** (R4, high: Kaminski-Lo; trailing-stop study). Tight/daily-checked stops cost
   return; wide stops survive costs. **Our record agrees** (R3): our stops sit at a median 1.15x ATR, 21-29% of stop-outs
   later reached +1R; a 3x-ATR stop at the SAME dollar risk (smaller size) beat it in every group, worst decile
   -1.67R -> -0.92R.
2. **Winners need time** (R3): median winner peaked at session 7; the desk held a median of 2 sessions vs the analyst's
   planned 10; day-1 exits ~0R; trailed stops were the only class that made money (+$770, 48% of MFE kept).
3. **Profit taking** (R3): on +2R runs a 3x-ATR trail kept 51% of the move, breakeven-at-1R only 35%; selling 1/3 at +1R
   then trailing raised the hit rate 44% -> 57% at equal mean.
4. **Sizing** (R4, high): fractional Kelly <= 1/4 on a shrunk, per-source edge; until a source has a graded record use
   fixed-fractional 0.5-1% of equity at risk and a cap on total open risk.
5. **Sources** (R4, high): ~56% of finfluencers have negative skill; popularity/frequency point the wrong way - grade
   each source on its own after-cost record.
6. **Decision-time info** (R4, medium): relative-volume shock mildly positive (~1-month holds); high days-to-cover is a
   warning; after a market decline + high volatility, momentum entries are hostile. (R3): entries >= 2% above prior
   close fade after ~3 sessions; down-day entries keep rising; low-ATR names (<2.5%) and short tips lose.
7. **Cash account** (R4, high): buy only with settled cash; never sell a position bought with unsettled proceeds before
   they settle (else 90-day cash-up-front restriction). T+1.
8. **Not answered by evidence** (R4 caveats): horizon-by-setup rules, ladder design, VIX/macro hard blocks, execution
   costs - so those ship **observe-first** or as defaults with measurement.

## V1 - Live safety leftovers (must land before real money)

- [ ] **V1.1 At-level arms use the book's sizing** (R1 B1): armed fires on a bound book size through `_tip_budget`
  (cap, glide, slot cap, risk %), not the source's budget; then re-enable `armAtLevel` on the IBKR book.
- [ ] **V1.2 Reconnect order**: run execution catch-up BEFORE the account sync after a reconnect (R1 M: double-count).
- [ ] **V1.3 Cash lag after a buy**: subtract today's buys not yet reflected in the IBKR cash summary (R1 M).
- [ ] **V1.4 Partially filled entry gets its stop immediately** for the filled quantity (R1 M).
- [ ] **V1.5 Hand-off failure**: an approve whose venue hand-off failed is marked failed, never left pending (R1 M).
- [ ] **V1.6 Cancel/replace race**: wait for the cancel confirmation (bounded) before a replacement sell rests (R1 M).
- [ ] **V1.7 Good-faith guard on SELLS**: a position bought with unsettled proceeds is not sold before settlement unless
  it is a protective stop (journaled, alerted) (R4 #7).
- [ ] **V1.8 Live config**: live book (kind live), USD cash, `risk.book_overrides` for it (max position $3,500, daily
  halt 4%, max position 35%), `risk.require_market_hours` on, `maxOpenPositions` 3-4, `budgetPerTip` ~$900-1,000,
  `riskPct` 0.75-1%, `allow_live_auto` on the user's go.

## V2 - Horizon at entry (days / week / multi-week)

- [ ] **V2.1 Horizon classes** carried on every proposal/position (`horizon`): **short** (<= 3 sessions), **swing**
  (default, 10), **extended** (20+, trend). Rules at entry (R3, low-medium confidence; start labelling + observe):
  short = chased entry (>= 2% above prior close), gap >= 2%, catalyst/news tip, low-ATR name; extended = down-day entry,
  source with a graded multi-week record (e.g. neal), position at >= +2R by session 5 (promotion); else swing.
- [ ] **V2.2 Exit policy by horizon** (defaults, all ATR-based on daily bars):
  - short: stop 2x ATR, take 1/2 at +1R, rest trails 2x ATR, time stop 3 sessions.
  - swing: stop 3x ATR (size from it), 1/3 at +1R then breakeven, trail 3x ATR, time stop 10 sessions only if < +0.5R.
  - extended: stop 3x ATR, 1/3 at +1.5R, trail 3x ATR judged on the daily close, no time stop while above the 20-day MA;
    months-class (low confidence, R4 trend study) trails 8-10x ATR.
- [ ] **V2.3 Promotion**: swing -> extended when +2R by session 5 and above the 20-day MA; never demote a winner into a
  tighter stop.
- [ ] **V2.4 No same-day share plans** (min time stop 2 sessions) and **short tips watch-only** (R3: negative under every
  exit, n=67).
- [ ] **V2.5 The analyst chooses the horizon** with a reason (`horizon`, `horizon_reason`) from the header facts below;
  the app validates it against V2.1 and records disagreements (graded).

## V3 - Stops that cut losses in time without noise

- [ ] **V3.1 Minimum stop 2x ATR, default 3x ATR, sized from the stop** (same $ risk) - replaces the 0.75% width floor.
- [ ] **V3.2 Exit judged on the 15m/daily CLOSE for swing/extended**, intrabar only for the crash brake (gap / -0.5R
  beyond the stop) (R4 #1).
- [ ] **V3.3 Gap risk**: overnight venue stop stays at the policy stop; a gap through it exits at the open (already),
  and a gap-down entry day never re-enters the same tip.
- [ ] **V3.4 Thesis stop**: exit when the reason dies (source closes, level lost on close) independent of price stop
  (mirror already; add "level lost on the daily close").

## V4 - Smart profit taking

- [ ] **V4.1 Ladder by horizon** (V2.2) replacing the analyst's ad-hoc targets as the default; analyst targets beyond
  are kept as extra trims.
- [ ] **V4.2 Trail activation** only after +1R; trail = 3x ATR (2x for short), ratchet only.
- [ ] **V4.3 Breakeven only with a partial** (R3: breakeven alone kept 35%).
- [ ] **V4.4 Runner rule**: after the last target, keep a 1/3 runner on the trail (no full exit at TP).

## V5 - Sizing that uses the whole account without over-concentration

- [x] **V5.1 Risk-first sizing** (built 2026-10-05: `techniques/tip/sizing.py` + `decision.py`; `risk_first_sizing`, `max_open_risk_pct` 5 / per-book `maxOpenRiskPct`): qty = risk budget / stop distance, then capped by cash and per-name exposure (not by a
  fixed $ per tip). Risk budget = 0.75-1% equity; total open risk cap 4-5% equity; max 3-4 positions on $7k, 7 on
  Practice.
- [x] **V5.2 Per-source Kelly once graded** (built 2026-10-05, `source_kelly_mode` = observe by default): after >= 20 graded trades, risk = min(1%, 1/4 Kelly of the shrunk edge);
  negative edge -> watch-only (R4 #4, #5).
- [x] **V5.3 Sector / correlation cap** (built 2026-10-05: sector part, `max_per_sector` 2; per-name cap stays `max_name_exposure_pct`): max 2 positions per sector, per-name cap 40% of equity.
- [ ] **V5.4 Fractional shares (IBKR supports US fractional via API for eligible stocks)** - investigate; until then
  refuse a name whose one share exceeds the per-trade cap (shipped).

## V6 - Best information at decision time (in the analyst header + card)

- [x] **V6.1 Context block** (built 2026-10-05: `techniques/tip/entry_context.py`, header via prefetch + card `entryContext`): ATR %, relative volume (today vs 20-day), distance to 20/50-day MA, gap % vs prior close,
  relative strength vs SPY (5/20-day), days-to-cover/short interest (when available), market regime (SPY vs 200-day,
  2-year return, VIX level), earnings date + timing, tier-1 events in the horizon (have).
- [x] **V6.2 Regime guard (observe -> enforce)** (built 2026-10-05, `regime_guard` = observe, `TipRegimeShadow`): hostile regime (SPY 2-yr return < 0 and high vol) halves momentum
  entries (R4 #8).
- [x] **V6.3 Chase filter** (built 2026-10-05, `chase_filter` = observe, `TipChaseShadow`): entry >= 2% above prior close -> short horizon + half size (R3), observe first.
- [x] **V6.4 Source grade on every card** (built 2026-10-05: `context.sourceGrade`, one line on the card): graded after-cost record, hit rate, mean R, Kelly fraction (V5.2).

## V7 - Measurement

- [ ] **V7.1 Horizon/exit study re-run** after 20 sessions (R3 script in this folder) and the preregistered promotion
  criteria per rule (EXPERIMENT-REGISTER).
- [x] **V7.2 Execution-cost ledger** (built 2026-10-05: `python -m zargar.tools.tip_exec_costs`) for the IBKR book: commission, spread paid, slippage vs decision quote, FX.
- [x] **V7.3 Daily desk report** (built 2026-10-05: morning report `tips` block, `techniques/tip/desk_metrics.py`) shows horizon mix, % of MFE kept, noise stop-outs, capital utilisation.

## Order

1. **Monday 10-05:** paper session on 0.8.62 (no v0.9 changes during market hours).
2. **After Monday's close:** V1 (all) -> V3.1 + V5.1 (wider stops sized from the stop) -> V2 labels + V2.2 exits on
   Practice -> V4 -> V6.1 context -> V5.2/5.3 -> V6.2/6.3 observe.
3. **Go-live:** when V1 is done and the paper session passed; the live book starts on V2/V3/V4 defaults.
