# Post-ignition research and Practice pilot

Current implementation, reviewed 2026-09-13. Source: [Sean's September 11 continuation video](https://www.youtube.com/watch?v=7xSMgmLoqM8), S30. Full auto-generated transcript was read and selected scanner/CRCL/SCCO frames checked. See [video evidence](VIDEO-REVIEW.md).

## The sequence

Discover an unusually strong event, wait for quieter consolidation toward rising moving averages, then evaluate a prospective breakout. Do not buy merely because the event occurred or because a stock appears on the watchlist. A quiet next day need not meet the event's +5% discovery threshold again.

The ignition research list is maintained during preparation when `ignitionResearch` is enabled. Stored stages are `ignition_verified`, `consolidating`, `setup_ready`, `invalidated` and `expired`. Ready research sorts first; retired records are hidden unless requested. The API returns at most 200 records and the UI initially shows 25 inside a collapsed section. Read the as-of timestamp: records are updated when evaluated, not guaranteed current for every symbol between scans.

Research records have no order authority. To use the detector in automatically prepared plans, explicitly select `post_ignition_2026_09_11` under Method profile in Practice settings, save, and run fresh preparation. Live rejects this pilot. Existing general profiles are not silently switched; normal market/data/contract/risk/closed-bar gates still apply.

## Implemented detector v1

| Element | Current definition | Attribution |
|---|---|---|
| Event-day screen | price >5; change >5%; prior 10-session average volume >500K; ADR >2%; event close above EMA50 | Screen shown/described in S30; exact completed-data implementation is ours |
| ADR | prior 20-session mean of `(high-low)/low * 100` | Engineering lookback/formula |
| Ignition volume | >=3x prior 20-session mean, excluding event | Author illustrates 3–5x; exact denominator/boundary is engineering |
| Event search | up to 40 recent eligible event bars after EMA warm-up, with at least 55 total | Engineering |
| Consolidation | 2–15 completed post-event sessions | Engineering translation of waiting for development |
| Readiness | range <=12%; latest close within 3% of rising EMA8; mean consolidation volume <50% of event volume | Engineering |
| Invalidation | post-event close below event low, or a red candle with volume above event volume | Engineering |
| Prospective levels | consolidation high / low; confirmed prior pivots for targets, existing reviewed fallback rules where applicable | Measured interpretation; not author-certified prices |

These ignition thresholds are fixed in the versioned detector, not individually tunable in the current Settings page. Generic setup settings do not automatically tune this detector. The initial pilot is long-side only; no exact bearish mirror or automatic calibration is claimed.

The research stage can be recorded before the full execution analysis completes. A watchlist badge therefore does not certify every history/metadata gate. Missing catalyst evidence remains `unverified`; volume patterns do not identify the actual institutional buyers. Daily ignition volume and intraday confirmation volume are separate measurements.

## Entry, holding and limits

The video describes entering as a level breaks on a 5m/15m view. The app preserves the platform's completed-bar gate and causal session-low/high stop interpretation; it does not implement an intrabar entry from this video. The video's 2.5% price-to-stop example is not account risk or maximum option loss.

A thesis may last across sessions; an automatic child plan's evidence expires at its first intended entry-session close. Held-position management is independent and can continue. No new option DTE/strike/spread rule or partial-exit allocation was inferred from S30. Whole-contract allocation, affordability and fresh execution checks remain visible and mandatory.

Source-example calibration, richer catalyst/theme modelling, full thesis lifecycle and prospective option-return validation remain open. See [work status](PLAN.md).
