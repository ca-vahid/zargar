# The executable funnel, gate by gate (revision 2)

Source revision: origin/main `731edbd` (v0.8.11), 2026-09-17; wording corrected 2026-09-18 per review. Line numbers refer to that
revision; module paths are under `backend/zargar/techniques/options_cartel/` unless noted.
"Effective setting" is the persisted Practice policy (`techniques.options_cartel.preparation`,
last saved 2026-09-14 00:52Z) — not the code default where they differ.

Outcome classes (one per gate):

- **Removes** — the candidate leaves this preparation run; a later run re-evaluates from scratch.
- **Delays** — the item stays pending and is re-checked (by the pending watcher or a resumed run).
- **Fresh signal** — the armed plan stays armed; this bucket produces no signal, the next bucket can.
- **Invalidates** — the plan is retired for good (`disarmed`/`expired`); only a new preparation can recreate it.
- **Blocks submission** — a signal exists but no order is sent; the signal expires after 120 s and the plan waits for a new bucket.

Paths: **P** production (automatic preparation → arm → live entry), **R** manual replay
(`replay.py`, `replay_service.py`, `premium_replay.py`, `sweeps.py`), **S** prospective research
(`profitability_research.py`, `intraday_research.py`). R and S never place orders and never
change an arm; they share the pure reads (`screen`, `setups`, `entry.read_entry`) with P.

## A. Discovery and screen (P; S reuses the frozen rows)

| # | Gate | Where | Effective setting | Data needed | Outcome |
|---|---|---|---|---|---|
| A1 | Listing universe (TradingView primary US + reviewed ETFs) | `discovery.py:30-31` | price > 3, cap > 300 M (server-side) | screener page | Removes |
| A2 | Benchmark completeness: SPY/QQQ daily through the latest completed session | `preparation.py:321-330` | — | Yahoo 1d for two indices | Run stops in `waiting_for_benchmark` (whole run; retried per recovery budget) |
| A3 | Market alignment | `screen.py:74-101, 146-147` | `market_alignment=moderate` (Practice); bearish side strict | SPY/QQQ closes vs 8/21/50 EMA | Direction chosen for the whole run; with blocked alignment the run continues in research-only mode (no arms) |
| A4 | Daily history completeness + contiguity | `preparation_io.py:146-158`, `data.py:77-83` | 550 calendar days requested; latest session must be present; no missing trading day | Yahoo 1d per symbol | Removes as `data_error` (e.g. FISV "missing regular-session bar: 2025-11-12"; OHLC geometry errors) |
| A5 | Listing screen: price, market cap freshness (≤7 d), volume basis 10-day avg ≥ 500k, ADR ≥ 3% (20-day), price on the direction side of 21/50 EMA, optional relative volume / positive change / industry top-10 | `screen.py:146-197`, `rules.py` | profile `september_2026`; `industry_policy=context` (rank recorded, not enforced) | daily bars, fundamentals snapshot, industry snapshot | Removes (`filtered`) |

## B. Setup context and geometry (P, R, S)

| # | Gate | Where | Effective setting | Data needed | Outcome |
|---|---|---|---|---|---|
| B1 | Warm-up: ≥ max(2·base+1, RS+1, 50) daily bars | `setups.py:104-107` | base 10, RS 20 | daily | Removes |
| B2 | Exactly 8 complete weeks of context; weekly range ≤ 50%; within 15% of the directional weekly extreme | `setups.py:108-118` | `weekly_context_weeks=8`, `max_weekly_range_pct=50`, `max_distance_from_extreme_pct=15` | daily → weekly | Removes |
| B3 | Relative strength vs SPY over 20 sessions, date-aligned | `setups.py:120-128` | 20 | daily + SPY | Removes |
| B4 | Contraction: base volume ≤ 0.8 × prior 10 sessions; base range ≤ 15% | `setups.py:134-136` | `max_volume_ratio=0.8`, `max_base_range_pct=15` | daily | Removes |
| B5 | Family labelling: `base` always; `ascending_triangle`, `flag`, `pennant`, `wedge`, `inside_day`, `ma_pullback`, `breakout_retest` by geometry | `setups.py:142-173` | slopes 0.10%/bar, impulse 5%, touch 0.5%, ≥3 touches | daily | Not a gate: every family inherits the same B1–B4 pass |
| B6 | Trigger/invalidation per family (`base`: 10-session high/low; `inside_day`/`ma_pullback`: the mother/latest candle; `breakout_retest`: latest candle) | `setups.py:179-188` | — | daily | Sets geometry; invalidation can be far (PWR wedge: 9.4%) |

## C. Automatic review and ranking (P; S re-ranks the same pool)

| # | Gate | Where | Effective setting | Data needed | Outcome |
|---|---|---|---|---|---|
| C1 | Context passed and finite, correctly signed trigger/stop | `automatic_plans.py:133-137` | — | — | Removes |
| C2 | Targets: confirmed pivots beyond the trigger, else Fibonacci anchors (engineering) | `automatic_plans.py:138-154` | `allow_fibonacci_targets=true` | daily | Removes if none |
| C3 | Minimum first-target distance | `automatic_plans.py:155`, `quality.py` | `min_target_distance_pct=0.5` | — | Removes. **This is the only planning-time room check**; structural R is computed but not gated (PWR 0.075 passed) |
| C4 | Exit campaign constructible; best family by (first-target/risk ratio, non-`base`, name) | `automatic_plans.py:157-167` | `september_2026`, `whole_contracts_v2` | — | Removes if not constructible |
| C5 | Ranking: structural R, directional RS, daily volume | `preparation.py:478-479`, `quality.py:19-20` | `shortlist_ranking=quality` | — | Orders the pool; the worker checks at most 5×`focus_count`=25 and stops when 5 arms exist. **No contract information enters the ranking** |
| C6 | Capacity: existing arms/positions occupy slots; same symbol → `already_managed` | `preparation.py:52-67, 511-520` | `focus_count=5` | armed rows, managed positions | Removes for this run (symbol skipped) |

## D. Baseline, coverage and readiness (P only)

| # | Gate | Where | Effective setting | Data needed | Outcome |
|---|---|---|---|---|---|
| D1 | 20-session 1m baseline: slot sample only if all 15 minutes present; slot usable with ≥5 samples and positive median | `prepare.py:26-60`, `preparation_io.py:233-263` | 20 sessions, 15 m, `require_exchange_history=true` | Alpaca SIP 1m (Yahoo fallback), cached per provider | Removes as `plan_blocked` ("No supported same-time volume baseline") |
| D2 | Coverage policy | `preparation.py:551-556`, `preparation_readiness.py:9-20` | `coverage_policy=opening_and_broad` (slots 0–3 and ≥20/25 pre-close usable); `baseline_readiness=covered_periods` | D1 output | Removes as `plan_blocked` for this run; the run becomes resumable (≤3 attempts per evening/pre-open window, 5→10→20 min backoff). **Not re-checked in-session** |
| D3 | Contract selection from chain evidence: identity, uncrossed quotes, delta ≥0.25 (target 0.5), spread ≤20% (mid basis), OI ≥100, ask ≤ min(5, budget/100, equity·risk%/100) | `automatic_plans.py:planning_contract`, `preparation.py:87-106` | DTE 21–90 target 45; `max_ask=5`; budget 500 | CBOE chain (delayed) | Delays as `awaiting_contract`; the pending watcher retries every ~60 s from 45 min pre-open until the close. Observed 09-16/17: for TTWO, PWR, NVT no contract in the inspected snapshots passed all configured limits (premium and spread between them; the delta floor is 0.25) |
| D4 | Pre-arm readiness: coverage ready; window not expired; a usable slot still ahead; no missing/untrusted current-session minutes; no completed invalidating bucket; first target not already passed | `preparation_readiness.py:24-70` | `require_exchange_history` → `require_exchange_bars=true` | current-session tape (`bars` + recovery cache + bounded fetch) | Delays (non-terminal reasons) or **Invalidates** the pending item (`invalidated` / `target_passed` are terminal) |
| D5 | Arm with capacity and scope | `preparation.py:70-84, 577-581` | — | — | Armed; `validUntil` = close of the first session |

## E. Live observation and the closed-bar read (P; R uses the same `read_entry`)

| # | Gate | Where | Effective setting | Data needed | Outcome |
|---|---|---|---|---|---|
| E1 | Bar acceptance: 1m, RTH, closed, ≤120 s old | `observer.py:225-227` | 120 s | live bar | A late bar is dropped (loop stalls matter here) |
| E2 | Preparation expiry (`validUntil`) and horizon (`expiresAt`) | `runtime.py:405-413`, `entry.py:177-178` | `horizon_sessions=1` | clock | **Invalidates** (`expired`) |
| E3 | Bucket completeness (all 15 minutes) | `entry.py:70-77` | 15 m | tape | Fresh signal (`missing_bucket`; also resets the crossing state) |
| E4 | Trusted provenance for every minute in the bucket | `entry.py:83-87` | `require_exchange_bars=true` | `Bar.source` | Fresh signal (`untrusted_confirmation`; resets crossing state; **no measurements recorded**) |
| E5 | Bucket started after plan creation | `entry.py:88-89` | — | — | Skipped bucket |
| E6 | Close beyond the reviewed invalidation | `entry.py:90-93` | — | — | **Invalidates** (`disarmed`) |
| E7 | Bucket started after `observeAfter` (restart/resume/reset cutoff) | `entry.py:94-96` | — | — | Fresh signal (needs a new observed setup) |
| E8 | Closing-bell bucket cannot start an entry | `entry.py:104-106` | `covered_periods` | — | Fresh signal / none |
| E9 | Slot has a baseline | `entry.py:107-110` | `covered_periods` | plan baseline | Fresh signal (`unsupported_volume_period`) |
| E10 | Crossing: previous close on the wrong side, this close beyond the trigger | `entry.py:102, 128` | breakout mode | — | Fresh signal (no cross) |
| E11 | Quality: volume ≥ 1.5× slot baseline; close location ≥ 0.70; never-chase ≤ 0.5 planned R; first target not passed | `entry.py:113-114, 134-145` | `volume_multiple=1.5`, `min_close_location=0.7`, `max_chase_r=0.5` | — | Fresh signal (`watch_only`, measurements recorded) |
| E12 | Stop: session extreme since the open, all minutes present and trusted | `entry.py:146-155` | `stop_mode=session_extreme` | tape | Fresh signal if undeterminable |
| E13 | Executable R: (target1 − close)/(close − stop) ≥ 0.25 | `entry.py:158-161` | `min_target_r=0.25` (from `min_entry_target_r`) | — | Fresh signal |

## F. Signal to order (P only)

| # | Gate | Where | Effective setting | Data needed | Outcome |
|---|---|---|---|---|---|
| F1 | Consume: status/phase, `opensAt ≤ signal.at ≤ now < expiresAt`, id shape | `state.py:105-117` | — | — | Blocks submission |
| F2 | `_entry_conditions`: account scope, saved contract limits present, `validUntil`, workspace/book kind, mode/portfolio match, execution config unchanged, RTH, **signal ≤120 s old**, trusted bars for confirmation+stop window, slot in baseline, direction/targets match, underlying quote fresh (≤`risk.stale_quote_seconds`=10 s) and non-delayed, price/stop geometry, chase, executable R, target not reached, halts/pause/enabled, reconciliation, live permissions, **auto requires `risk.daily_loss_halt_pct` > 0** | `controller.py:64-145` | as listed | live quote, arm row | Blocks submission (signal expires at 120 s; plan waits for a new bucket) |
| F3 | `preflight`: plan horizon, pause/enabled, live acks, halts, reconciliation, technique daily loss (off), contract underlying/direction, expiry floor, overnight ack, fresh delta (≤120 s) and floor 0.25, fresh two-sided contract quote, premium ≤ min(5, budget), positive equity, FX, **affordable quantity** = min(budget/(ask·100), equity·risk%/(ask·100)) ≥ 1; then RiskGate dry run; then `contract_entry_checks`: fresh quote, fresh delta, premium cap, **spread ≤ saved 20% on the mid basis**, DTE in range | `execution.py:92-222`, `contract_entry_checks` at `:51-89` | budget 500, risk 10%, max 10 | contract quote + Greeks snapshot | Blocks submission; journaled `TechniqueCartelPreflight` |
| F4 | Spread-only reselection (Practice auto only): one bounded ≤20 s search within the same limits, then a second preflight | `contract_reselection.py:13-77` | `reselect_wide_contract=true` (default; deployed 2026-09-17 01:18Z) | chain | May change only the contract identity |
| F5 | Reserve, re-check F2 + vehicle conditions, `before_submit` guard at the broker boundary, then `OrderManager.place` → RiskGate | `controller.py:211-274`, shared `orders.py` | — | — | Blocks submission (a `pre_submit_rejected` disarms the plan) |
| F6 | Fill → adoption into the durable position manager (`app_managed` overnight for options); one exit authority | `adoption.py`, `position_adapter.py`, `exits.py` | `september_2026`, `whole_contracts_v2` | fills | Position held across sessions; **one contract has no trim rung and no breakeven move** |

## What is production, replay, research

| Path | Entry point | Uses gates | Never does |
|---|---|---|---|
| P production | `preparation.py` (08:45 / 20:20 ET jobs, pending watcher, `automatic_recovery`), `observer.py`/`runtime.py` | A–F | — |
| R manual replay | `replay_service.py`, `sweeps.py`, `premium_replay.py` | B, C (geometry), E (`read_entry` over historical minutes), exit policy over daily bars | D3–D5, F; no orders, no arm changes |
| S prospective research | `profitability_research.py` (frozen pool per preparation, baselines prewarmed off-hours), `intraday_research.py` | A, B, C over the frozen rows; E over observed minutes | arms, orders, approvals; a research row is never executable |

Two observations for the proposal: (1) the only *planning-time* quality bar is the 0.5%
distance (C3); the ≥1.5:1 reward/risk in the source's checklist (S14) is not implemented
anywhere (an engineering reading of it is proposed as an inactive experimental filter); (2)
contract feasibility (D3) is consulted only after ranking (C5) and only for the top 25, so names
with no contract passing the saved limits consume the 25-candidate checking budget and
pending-watcher work all day. They do not occupy focus slots: capacity counts occupied arms and
held positions (C6).
