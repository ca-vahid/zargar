# Team2 technique — judgement log

*The METHOD (`METHOD.md`) is what the author says; this file is what WE have learned about it —
findings, open questions with decision thresholds, theories, and the change log of every rule or
parameter change, each dated and citing its run / scorecard / sweep. Engine-level lessons go to
`docs/PLATFORM-RULES.md` instead. Opened 2026-09-03; nothing has run yet.*

## Rules under observation

| Rule | Current value | Question | Decides it | Status |
|---|---|---|---|---|
| Q1 contract | **0DTE, strike by premium ≈ $0.50–0.60 (decided, D3)** | Would 1DTE survive as a variant? Does the $0.50 strike beat the first-OTM strike? | sweep with the premium-path scorer (E8): 0DTE-$0.50 vs 0DTE-first-OTM vs 1DTE | decided 2026-09-03; variants open |
| Q2 size buckets | 1.0 / 0.5 / 0 | Is the middle bucket worth trading at all? | sweep expectancy per bucket, ≥ 60 sessions | open |
| Q3 exit ladder | 50% at new-high push, runner on EMA13 close | Does the runner add R after costs? | sweep 30/50/70 + no-runner | open |
| Q4 entry window | 09:45–15:30 | Are post-noon fires net positive with 0–1 DTE decay? | per-window expectancy | open |
| Q5 PM tolerance | ±0.25 ATR(2m) | Retest hit-rate vs false touches | touch-count audit on replay rows | open |
| C1 15m close | required | How many valid fires does the 15m rule cost vs how many fakeouts it saves? | replay with the gate off (`include_invalid`) | open |
| D9 pullback count | first two | Third touches: return or noise? | sweep 1/2/3 | open |

## Findings

- **F1 (2026-09-03, images)** The author's vehicle is **0DTE, 1–2 strikes OTM, $0.20–$0.60 premium**
  in every recap found (5 trades, 2024–2026; METHOD §7b). Consequence: the method's stated
  win rates are on lottery-priced contracts where a one-candle stop is −20–40% and a trend day
  is +400%; our outcome scoring must simulate the PREMIUM path (theta + gamma on 0DTE), not the
  underlying's R — `simulate_position` stamps `premiumPathSimulated: false`, which is not good
  enough here. Open: 0DTE is on the platform never-list for non-EM techniques (user decision).
- **F2 (2026-09-03, images)** The sizing guide is three buckets keyed to the 15m map (full beyond
  the PDH/PDL zones, small between the prior-day zone and the PM level, none inside the PM range).
- **F3 (2026-09-03, images)** Exits are quoted in premium %: +50% / +100% trims, "sold when it went
  ITM", runners on the 13 EMA. The first trim's cue is the new high/low of day, i.e. a PRICE event —
  so the ladder can be expressed as price-triggered with premium-% telemetry.
- **F5 (2026-09-03, images)** Strike is chosen by PREMIUM, not distance: entry asks cluster at
  $0.50–0.60 (SPY/QQQ) and $0.20 (IWM) while OTM distance ranges 0.3–1.8%. Expression policy
  candidate: `strike = first OTM strike with ask ≤ techniques.team2.target_premium` (default 0.60),
  with a floor so we never buy the $0.05 lottery. A full-size position ≈ $2.6k premium (~48
  contracts) in one recap — our `budget_per_trade` scale, not a per-contract count.
- **F6 (2026-09-03, images)** "Sell at target" is literal: the pre-planned next level is an
  outright exit on touch, after earlier trims — the exit ladder ends with a price target, not only
  the EMA trail.
- **F7 (2026-09-03, podcast 2023)** Hard premium stop ≈ **−20%** on 0DTE ("the sweet spot"), on top
  of the candle rule; no time-of-day gate (pre-10:00 flagged riskier); 2–5 trades/day; the FIRST
  13 EMA pullback after the break is "where most of my money is made", the third is the trap.
  Daily risk discipline: shrink $ risk after a win so one loss cannot erase the day.
- **F4 (2026-09-03, video 2022)** "We buy pullbacks, we don't buy breakouts." An extended entry
  (large engulfing candle into the EMA) is explicitly the bad entry; the good one is an even,
  flag-like drift into the EMA. Candidate gate: pullback slope / body-size filter on the 2m bars.

## Theories to test

- T1 The 15m-close confirmation is the load-bearing rule (added by the author only in 2026 after
  years without it); expect it to cut fires by ~40% and raise win rate materially.
- T2 Range-day scenarios (reject PDH / bounce PDL) will underperform trend-day scenarios enough that
  the desk should start with scenarios 1 and 4 only.
- T3 "Ext hours on" EMAs matter mostly for the first 30 minutes (the 200 EMA otherwise has no
  history at 09:30); after ~11:00 RTH-only EMAs converge.

## Change log

| Date | Change | Evidence | By |
|---|---|---|---|
| 2026-09-03 | Method codified v0.1 from 49 public posts; desk opened | `SOURCES.md` | Team2 desk |
| 2026-09-03 | D3 decided by the user: Team2 is a 0DTE technique; RiskGate gets a per-technique 0DTE policy (E6) instead of the hard-coded EM/tip ids. Engine is ENRICHED, not forked (PLAN §3b, E1–E12) | METHOD §7b/§7c, images INDEX | Team2 desk |
| 2026-09-03 | Completeness review before the build (PLAN §3c, groups A–H): added day-type classifier, target discovery, zone+EMA gate, range-day confirmation, 5m flag detector, pullback-quality gate, re-entry cap, concurrency cap; bank ext-hours bars from tonight, ^VIX/^VIX1D fetch, fee+slippage in the premium scorer, calibration vs the author's 9 documented trades, market calendar (half days); OPRA-only fires, flatten discipline; per-technique 0DTE policy caps; nightly arming ops; review/evolution loop; settings panel + page | audit of METHOD vs PLAN | Team2 desk |
| 2026-09-03 | **Build v0.1 landed** (PLAN P0–P3 partial, 43 checkboxes): shared primitives + Team2 package + runner (alert mode) + page + sweep. Build-time judgement calls, each a rule the sweep must vindicate: (1) entry mechanics live in ONE pure session walk (`session.py`) instead of `TriggerTracker` — parity by construction; (2) trims are decided on the MODEL premium (BS on the VIX proxy) live too — the execution scorecard must compare against the real premium before proposal mode; (3) the "new high/low of day" trim cue is expressed as +50%/+100% premium (author's own numbers), price cue not yet modelled; (4) range-day confirmation = price beyond the PM level on the trade's side; (5) the event-day gate is a plan flag from the manual macro list, off by default | tests: 35 Team2 + 14 primitives green; shared suites 239 green | Team2 desk |

- **F8 (2026-09-03, calibration)** Flat-IV Black–Scholes on the author's four fully documented trades
  (entry premium, entry/exit spot read off his charts): SPY 711c +137% model vs +122% reported; QQQ 472p
  +211% vs +166%; IWM 201p +187% vs +157%; SPY 648c +114% vs +100%. The model is **consistently 12–45%
  optimistic** (chart-read spots, exits taken before the extreme, real spread on the way out). Until the
  execution scorecard measures our own fills, read sweep gains with a ~0.8 haircut; losses (−20/−30% stops)
  are premium-defined and unaffected. Test: `test_premium_model_calibrates_to_the_authors_trades`.
