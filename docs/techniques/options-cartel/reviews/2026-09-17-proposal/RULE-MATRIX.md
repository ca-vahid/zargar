# Rule matrix — where each requirement comes from

Classes: **Source** (explicit in the author's material, with the source id and version),
**Engineering** (our numeric or algorithmic interpretation), **Safeguard** (execution/account
protection, not strategy), **Provider** (a limitation of the data feed we use), **Unresolved**
(an assumption nobody has tied to a source or a measurement). A passing test shows the filter
is implemented as written; it does not show the filter belongs in the strategy. Source ids
resolve in `../../SOURCES.md`; version conflicts are in `../../SOURCE-REVIEW.md` and
`../../METHOD.md` §M8.

| Requirement | Effective value (Practice) | Class | Source / version | Implemented in | Note for Lane A |
|---|---|---|---|---|---|
| Top-down: market → theme → leader → setup | — | Source | S01 (Sep 2026) | preparation order | keep |
| Market gauge SPY/QQQ vs 8/21/50 EMA, both indices | strict for bearish; moderate (Practice) for bullish | Source (gauge), Engineering (two-index resolution, moderate) | S02 (Jun 2026); M1 says the author does not resolve index disagreement | `screen.py:74-101` | Lane A: **strict** bullish only |
| Industry top-10 weekly AND monthly | context only | Source (S01) | S01 | `screen.py:182-197`, `industry.py` | keep as context; not a gate |
| Price > $3, cap > $300 M, volume > 500k, ADR > 3%, above 21/50 EMA | as listed (10-day avg volume, 20-day ADR) | Source thresholds; Engineering lookbacks | S02 text (ADR 3%) vs S02 image (ADR 2%, 10-day volume) — real conflict (D14) | `rules.py`, `screen.py` | keep profile `september_2026`; conflict stays documented |
| Relative volume > 1 | off | Source in older variants | S13/S14/S24 | `rules.py:33` | off in Lane A |
| Weekly context: substantial base, near highs, limited overhead supply | 8 complete weeks; range ≤ 50%; within 15% of extreme | Source concept; Engineering numbers | S01 (concept) | `setups.py:108-118` | keep numbers, label engineering |
| Relative strength vs benchmark | 20 sessions | Engineering | M2 "relative strength" unnumbered | `setups.py:120-128` | keep |
| Contraction: quieter consolidation, tightness | base volume ≤ 0.8× prior; range ≤ 15% | Source concept; Engineering numbers | M3 (S01/S02) | `setups.py:134-136` | keep; measure, don't tune |
| Setup family labels (flag, wedge, inside day, base, MA pullback, retest) | geometric classifiers | Source names; Engineering geometry | S01 list; S18 names ascending triangle | `setups.py:142-173` | Lane A uses **one** family (`base` with ceiling touches) |
| "Repeatedly rejected resistance" as the trigger | not implemented (ceiling touches only for ascending_triangle) | Source | S02 | — | **add** to Lane A: ≥2 touches of the base ceiling within 0.5% |
| Reward/risk ≥ 1.5:1 before entry | not implemented (only 0.5% distance) | Source (basis unresolved: first target? final?) | S14 checklist | — | **add** to Lane A at planning: first target vs trigger-to-invalidation ≥ 1.5 |
| First target = nearest confirmed pivot | pivots, else Fibonacci | Source (targets at resistance, S02); Engineering (Fibonacci anchors, 1.272/1.618/2.0) | S02; anchors ours | `setups.py:_targets`, `automatic_plans.py:138-154` | Lane A: pivots only; Fibonacci fallback **off** |
| Minimum first-target distance 0.5% | 0.5% | Engineering | — | `automatic_plans.py:155` | superseded by the 1.5R planning rule in Lane A |
| Confirmation timeframe | 15 m closed bucket | Source allows 5m/15m (S02), 15m/30m (S01); closed bar is a platform adaptation (PLATFORM-RULES 8) | S02 / S01 / S03 (5m) — Q1 open | `plans.py:16`, `entry.py` | keep 15 m |
| Volume confirmation | ≥ 1.5× same-slot 20-session median | Source concept ("returning volume"); Engineering number and baseline definition | S01/S05 | `entry.py:113`, `prepare.py` | keep number; **baseline construction is where the provider issue lives** |
| Close location ≥ 0.70 | 0.70 | Engineering (S05: "close near the high") | S05 | `entry.py:114` | keep |
| Never-chase ≤ 0.5 planned R | 0.5 | Engineering | — | `entry.py:142` | keep |
| Initial stop | session extreme at confirmation | Engineering (D7) reading of S02 "low of the daily breakout candle" (causal problem, Q2) | S02 (Jun 2026) vs S03 (2024, intraday bar low) | `entry.py:146-155` | keep for execution; measure the daily-candle-low variant order-free |
| Executable R ≥ 0.25 at entry | 0.25 | Safeguard/Engineering | — | `entry.py:160`, `controller.py` | keep |
| Gap handling: no entry on the gap, wait for retest | `allow_gap_retest=true` (retest mode only) | Source | S12 | `entry.py:97-101` | Lane A is breakout mode; unchanged |
| Option delta ≥ 0.25 | 0.25 floor, 0.5 target | Source floor (S15); Engineering target | S15 | `contracts.py`, `execution.py` | keep |
| DTE 21–90, target 45 | as listed | Unresolved (M6: no universal DTE in the text; HOOD example ≈ 5–6 weeks) | — | `automatic_plans.py:61-63` | keep, label unresolved |
| Ask ≤ $5 and premium budget $500 | $5 / $500 | Safeguard (account size) | — | `preparation.py:87-96`, `execution.py` | keep; **check affordability before ranking** |
| Spread ≤ 20% (mid basis) at selection and at final submission | 20% | Safeguard | — | `automatic_plans.py`, `execution.py:84-85` | keep; reselection now deployed |
| Open interest ≥ 100 | 100 (selection only) | Safeguard | — | `automatic_plans.py:241` | keep |
| Risk = full premium debit; size = min(budget, equity·risk%) | 500 / 10% | Safeguard (D12) | S20 1%, S23 staged — not adopted | `execution.py:189-197` | keep |
| One Practice book, auto needs a book loss halt | book `0b48…`; `risk.daily_loss_halt_pct` > 0 | Safeguard (PLATFORM-RULES 10, 15) | — | `controller.py`, `accounts.py` | keep |
| Exits: 25% at first target then stop to entry; 3×ATR extension; daily closes under 8/21/50 | 25/25/20/20/10 | Source (S01) for the first trim, extension and EMA rungs; Engineering for the later fractions | S01 vs S02 vs S08 variants (M8) | `exits.py` | keep; **one contract cannot express it** (Safeguard consequence) |
| Whole-contract v2 for 2–3 contracts | on (Practice) | Engineering experiment | — | `exits.py:130-133` | keep |
| Options held overnight app-managed with acknowledgement | on | Safeguard (platform) | — | `adoption.py:119-126` | keep |
| Entry window = first session only; expiry at its close | `horizon_sessions=1`, `validUntil` | Engineering | M7: "wait for a planned trigger rather than forcing trades every day" | `preparation_readiness.py:117-119` | keep; expiry ≠ missed entry; the next run rebuilds |
| 20-session baseline, ≥5 samples per slot, all 15 minutes present | as listed | Engineering (baseline) × **Provider** (minute omission) | — | `prepare.py:48-54` | **verify no-trade intervals (D1) before relaxing** |
| Coverage policy first hour + 80% pre-close | `opening_and_broad` | Engineering | — | `preparation.py:553-554` | keep until D1 evidence |
| Trusted provenance (`exchange`) for every minute in a confirmation bucket and the stop window | on | Safeguard × **Provider** | — | `entry.py:83`, `controller.py` | keep; same D1 verification applies |
| Bar accepted only if ≤120 s old; signal valid 120 s; delta fresh ≤120 s; quote fresh ≤10 s | as listed | Safeguard | — | `observer.py`, `controller.py`, `execution.py` | keep; measure dropped-for-age bars |
| Daily history must be contiguous (no missing trading day) | on | Safeguard × Provider | — | `data.py:77-83` | keep (FISV excluded correctly) |
| Intraday research, profitability research, bearish proxy | on, non-executing | Research | — | `intraday_research.py`, `profitability_research.py` | untouched by Lane A |
| Bearish framework: puts, weak stocks/groups, support breaks, daily-high stop | strict short alignment; same geometry mirrored | Source (S21, full description) | S21 | `screen.py`, `setups.py`, `exits.py` | **untouched** — Lane A is additive |
