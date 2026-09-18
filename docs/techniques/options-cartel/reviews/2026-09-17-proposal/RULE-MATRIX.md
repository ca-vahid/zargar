# Rule matrix — where each requirement comes from (revision 2)

Classes: **Source** (explicit in the author's material, with source id and version),
**Engineering** (our numeric or algorithmic interpretation), **Safeguard** (execution/account
protection), **Provider** (a limitation or semantic of the data feed), **Unresolved** (an
assumption tied to neither a source nor a measurement). A passing test shows a filter is
implemented as written, not that it belongs in the strategy. Source ids resolve in
`../../SOURCES.md`; version conflicts in `../../SOURCE-REVIEW.md` and `../../METHOD.md` §M8.

| Requirement | Effective value (Practice) | Class | Source / version | Implemented in | Lane A (revision 2) |
|---|---|---|---|---|---|
| Top-down: market → theme → leader → setup | — | Source | S01 (Sep 2026) | preparation order | keep |
| Market gauge SPY/QQQ vs 8/21/50 EMA, both indices | strict bearish; Moderate (Practice) bullish | Source (gauge); Engineering (two-index resolution, Moderate) | S02 (Jun 2026); M1: author does not resolve index disagreement | `screen.py:74-101` | Lane A plans only on **strict** bullish sessions; Moderate/bearish paths untouched |
| Industry top-10 weekly AND monthly | context only | Source | S01 | `screen.py:182-197`, `industry.py` | context, not a gate |
| Price > $3, cap > $300 M, volume > 500k, ADR > 3%, above 21/50 EMA | as listed (10-day avg volume, 20-day ADR) | Source thresholds; Engineering lookbacks | S02 text (ADR 3%) vs S02 image (ADR 2%, 10-day volume) — real conflict (D14) | `rules.py`, `screen.py` | keep profile `september_2026` |
| Relative volume > 1 | off | Source (older variants) | S13/S14/S24 | `rules.py:33` | off |
| Weekly context: substantial base, near highs, limited overhead supply | 8 complete weeks; range ≤ 50%; within 15% of extreme | Source concept; Engineering numbers | S01 | `setups.py:108-118` | keep, labelled engineering |
| Relative strength vs benchmark | 20 sessions | Engineering | M2 | `setups.py:120-128` | keep |
| Contraction: quieter consolidation, tightness | base volume ≤ 0.8× prior; range ≤ 15% | Source concept; Engineering numbers | M3 | `setups.py:134-136` | keep; measure |
| Setup family labels | geometric classifiers | Source names; Engineering geometry | S01 list; S18 | `setups.py:142-173` | Lane A: one family, `base` + ceiling tests |
| "Repeatedly rejected resistance" as the trigger | not implemented for `base` | Source | S02 | — | **add**: ≥2 touches of the base ceiling within 0.5% (tolerance ours) |
| Reward/risk ≥ 1.5:1 before entry | not implemented | **Engineering interpretation** of a source checklist whose basis is unstated | S14 | — | `lane_a_min_planning_r`, **inactive by default**, basis trigger-to-reviewed-invalidation, effect reported before activation |
| First target = nearest confirmed pivot | pivots, else Fibonacci | Source (targets at resistance); Engineering (Fibonacci anchors) | S02; anchors ours | `setups.py:_targets`, `automatic_plans.py:138-154` | pivots only; Fibonacci off → `no_confirmed_target` |
| Minimum first-target distance 0.5% | 0.5% | Engineering | — | `automatic_plans.py:155` | stays active until the experimental filter is measured |
| Confirmation timeframe | 15 m closed bucket | Source allows 5m/15m (S02), 15m/30m (S01); closed bar = platform rule | Q1 open | `plans.py:16`, `entry.py` | keep |
| Volume confirmation | ≥ 1.5× same-slot 20-session median | Source concept; Engineering number and baseline | S01/S05 | `entry.py:113`, `prepare.py` | keep the number; baseline construction depends on D1 |
| Close location ≥ 0.70 | 0.70 | Engineering (S05 "close near the high") | S05 | `entry.py:114` | keep |
| Never-chase ≤ 0.5 planned R | 0.5 | Engineering | — | `entry.py:142` | keep |
| Initial stop | session extreme at confirmation | Engineering (D7) reading of S02's daily-candle-low rule (causal problem, Q2) | S02 vs S03 | `entry.py:146-155` | keep for execution; two labelled observations (hindsight daily low; close-switch) |
| Executable R ≥ 0.25 at entry | 0.25 | Safeguard/Engineering | — | `entry.py:160`, `controller.py` | keep; reported separately from structural R and option dollar risk |
| Gap handling: wait for a retest | `allow_gap_retest=true` (retest mode) | Source | S12 | `entry.py:97-101` | unchanged |
| Option delta ≥ 0.25 | 0.25 floor, 0.5 target | Source floor (S15); Engineering target | S15 | `contracts.py`, `execution.py` | keep; note TTWO's cheaper contract failed spread, not delta |
| DTE 21–90, target 45 | as listed | Unresolved (M6) | — | `automatic_plans.py:61-63` | keep, labelled unresolved |
| Ask ≤ $5 and premium budget $500, equity × risk% cap, multiplier, FX | effective cap = min(policy, budget, equity cap) | Safeguard | — | `preparation.py:87-96`, `execution.py` | keep; feasibility computed from these effective values (D2), never hardcoded |
| Spread ≤ 20% of mid at selection and submission | 20% | Safeguard | — | `automatic_plans.py`, `execution.py:84-85` | keep; add cents and quantity-adjusted dollars as diagnostics (D5) |
| Open interest ≥ 100 | 100 (selection only) | Safeguard | — | `automatic_plans.py:241` | keep |
| Risk = full premium debit; size = min(budget, equity·risk%) | 500 / 10% | Safeguard (D12) | S20 1%, S23 staged — not adopted | `execution.py:189-197` | keep |
| One Practice book; auto needs a book loss halt | book `0b48…`; `risk.daily_loss_halt_pct` > 0 | Safeguard (PLATFORM-RULES 10, 15) | — | `controller.py`, `accounts.py` | keep |
| Exits: 25% at first target then stop to entry; 3×ATR extension; daily closes under 8/21/50 | 25/25/20/20/10 | Source (S01) first trim/extension/EMA rungs; Engineering later fractions | S01 vs S02 vs S08 (M8) | `exits.py` | keep; one contract cannot express it |
| Whole-contract v2 for 2–3 contracts | on (Practice) | Engineering experiment | — | `exits.py:130-133` | keep |
| Options held overnight app-managed with acknowledgement | on | Safeguard | — | `adoption.py:119-126` | keep |
| Entry window = first session only | `horizon_sessions=1`, `validUntil` | Engineering | M7 | `preparation_readiness.py:117-119` | keep; expiry reason recorded |
| 20-session baseline, ≥5 samples per slot, all minutes present | as listed | Engineering × **Provider** (SIP 1Min bars omit minutes whose trades produced no eligible bar — probe: odd lots) | — | `prepare.py:48-54` | unchanged until D1 classification is recorded and reviewed |
| Coverage policy first hour + 80% pre-close | `opening_and_broad` | Engineering | — | `preparation.py:553-554` | unchanged |
| Trusted provenance for every minute in a confirmation bucket and stop window | on | Safeguard × Provider | — | `entry.py:83`, `controller.py` | unchanged; D1 classes get their own labels, never `exchange` |
| Bar accepted ≤120 s old; signal 120 s; delta ≤120 s; quote ≤10 s | as listed | Safeguard | — | `observer.py`, `controller.py`, `execution.py` | keep; D4 counts dropped bars |
| Daily history contiguous | on | Safeguard × Provider | — | `data.py:77-83` | keep |
| Intraday research, profitability research, bearish proxy | on, non-executing | Research | — | `intraday_research.py`, `profitability_research.py` | untouched |
| Bearish framework: puts, weak stocks/groups, support breaks, daily-high stop | strict short alignment; mirrored geometry | Source (S21) | S21 | `screen.py`, `setups.py`, `exits.py` | **untouched** — Lane A is additive |
