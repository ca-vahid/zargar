# Lane A frozen replay — 2026-09-08 → 2026-09-17 (book 0b48ed48, practice, market basis: moderate)

**Information-only variant:** the preparation's Moderate read is used as the market direction, which is NOT Lane A's definition. Generated 2026-09-18T02:47:39+00:00 by `zargar.tools.cartel_lane_a_eval` (read-only). Population = every frozen analysis run under the session's original preparation run; the old planner's own row/shortlist statuses are reported beside Lane A's verdict, never used as the denominator. Lane A parameters: base 10 sessions, ceiling tests ≥ 2 within 0.5%, confirmed pivots only, distance floor 0.5%, experimental planning R ≥ 1.5 **recorded, inactive**.

Feasibility is **hypothetical under stated assumptions**: the nightly chain snapshot dated the previous exchange session (research job ~16:30 ET, date-only records), the preparation's saved contract limits, and the effective cap min(policy, budget/100, equity x risk%/100) with the book equity last persisted before the run. It is not historical affordability. A `qualified` row is a planning verdict, not an entry, fill or outcome.

## Sessions

| Session | Original run | Market strict / Moderate (used) | Population | Lane A stages | Qualified | Exp. 1.5R passes | Feasibility of qualified | Old planner armed | Later runs |
|---|---|---|---|---|---|---|---|---|---|
| 2026-09-08 | `4f312571` 2026-09-08 04:40Z complete | long / long (long) | 58 (0 reused from earlier runs; +3032 rows without analysis) | {'context': 22, 'screen': 34, 'ceiling_tests': 2, 'prefiltered': 3032} | **0** | 0 | — | 1 | 0 |
| 2026-09-09 | `02b8a8bb` 2026-09-09 03:37Z partial | mixed / mixed (mixed) | 3080 (0 reused from earlier runs; +11 rows without analysis) | {'direction': 3080, 'unavailable_evidence': 11} | **0** | 0 | — | 0 | 3 |
| 2026-09-10 | `33e2a508` 2026-09-10 04:27Z partial | mixed / long (long) | 3081 (0 reused from earlier runs; +2 rows without analysis) | {'screen': 2755, 'context': 309, 'qualified': 5, 'ceiling_tests': 10, 'distance_floor': 2, 'unavailable_evidence': 2} | **5** | 0 | {'unknown_stale': 4, 'affordable': 1} | 4 | 2 |
| 2026-09-11 | `a973b3a4` 2026-09-11 04:49Z partial | short / short (short) | 3077 (2554 reused from earlier runs; +1 rows without analysis) | {'direction': 3077, 'unavailable_evidence': 1} | **0** | 0 | — | 5 | 0 |
| 2026-09-14 | `98bd007f` 2026-09-13 02:14Z partial | mixed / long (long) | 3075 (0 reused from earlier runs; +1 rows without analysis) | {'screen': 2778, 'context': 283, 'ceiling_tests': 10, 'distance_floor': 1, 'confirmed_target': 2, 'qualified': 1, 'unavailable_evidence': 1} | **1** | 0 | {'unknown_stale': 1} | 3 | 2 |
| 2026-09-15 | `072d5e98` 2026-09-15 04:21Z partial | mixed / mixed (mixed) | 3070 (2013 reused from earlier runs; +2 rows without analysis) | {'direction': 3070, 'unavailable_evidence': 2} | **0** | 0 | — | 0 | 18 |
| 2026-09-16 | `ed6d9da2` 2026-09-16 02:26Z partial | short / short (short) | 3062 (0 reused from earlier runs; +4 rows without analysis) | {'direction': 3062, 'unavailable_evidence': 4} | **0** | 0 | — | 5 | 28 |
| 2026-09-17 | `cee03dd7` 2026-09-17 01:11Z partial | short / short (short) | 3056 (0 reused from earlier runs; +3 rows without analysis) | {'direction': 3056, 'unavailable_evidence': 3} | **0** | 0 | — | 1 | 14 |

## Old planner outcome of the same population

| Session | Classes |
|---|---|
| 2026-09-08 | {'screen_or_context_rejected': 56, 'old_planner_candidate:armed': 1, 'old_planner_candidate:awaiting_contract': 1, 'prefiltered': 3032} |
| 2026-09-09 | {'screen_or_context_rejected': 3049, 'research_only': 31, 'unavailable_evidence': 11} |
| 2026-09-10 | {'screen_or_context_rejected': 3064, 'old_planner_candidate:awaiting_contract': 1, 'old_planner_candidate:not_shortlisted': 9, 'old_planner_candidate:armed': 4, 'old_planner_rejected': 3, 'unavailable_evidence': 2} |
| 2026-09-11 | {'screen_or_context_rejected': 3034, 'old_planner_rejected': 9, 'old_planner_candidate:armed': 5, 'old_planner_candidate:not_shortlisted': 24, 'old_planner_candidate:awaiting_contract': 5, 'unavailable_evidence': 1} |
| 2026-09-14 | {'screen_or_context_rejected': 3061, 'old_planner_candidate:armed': 3, 'old_planner_rejected': 3, 'old_planner_candidate:not_shortlisted': 7, 'old_planner_candidate:awaiting_contract': 1, 'unavailable_evidence': 1} |
| 2026-09-15 | {'screen_or_context_rejected': 3061, 'research_only': 9, 'unavailable_evidence': 2} |
| 2026-09-16 | {'screen_or_context_rejected': 3020, 'old_planner_candidate:armed': 5, 'old_planner_candidate:not_shortlisted': 21, 'old_planner_rejected': 13, 'old_planner_candidate:awaiting_contract': 3, 'unavailable_evidence': 4} |
| 2026-09-17 | {'screen_or_context_rejected': 3041, 'old_planner_rejected': 2, 'old_planner_candidate:armed': 1, 'old_planner_candidate:not_shortlisted': 10, 'old_planner_candidate:awaiting_contract': 2, 'unavailable_evidence': 3} |

## Lineage (all preparation runs per session; later runs are recovery, not original-time eligibility)

- **2026-09-08**: `4f312571` 2026-09-08 04:40Z complete market long/long armed 1
- **2026-09-09**: `39fa3e1c` 2026-09-09 00:20Z no_market_alignment market unknown/unknown armed 0; `bc8e704a` 2026-09-09 01:58Z no_market_alignment market mixed/mixed armed 0; `02b8a8bb` 2026-09-09 03:37Z partial market mixed/mixed armed 0; `11279651` 2026-09-09 04:42Z partial market mixed/long armed 5
- **2026-09-10**: `28f58799` 2026-09-10 00:20Z partial market unknown/unknown armed 0; `33e2a508` 2026-09-10 04:27Z partial market mixed/long armed 4; `57aab353` 2026-09-10 05:31Z partial market mixed/long armed 1
- **2026-09-11**: `a973b3a4` 2026-09-11 04:49Z partial market short/short armed 5 (resumed from `887e0bee`)
- **2026-09-14**: `f451f827` 2026-09-12 00:20Z partial market unknown/unknown armed 0; `98bd007f` 2026-09-13 02:14Z partial market mixed/long armed 3; `ccaa6c2c` 2026-09-14 00:52Z partial market mixed/long armed 0
- **2026-09-15**: `e365b997` 2026-09-15 00:20Z waiting_for_benchmark market unknown/unknown armed 0; `74b0f7b9` 2026-09-15 00:20Z waiting_for_benchmark market unknown/unknown armed 0; `bb66cb11` 2026-09-15 00:25Z waiting_for_benchmark market unknown/unknown armed 0; `4a3d3738` 2026-09-15 00:49Z waiting_for_benchmark market unknown/unknown armed 0; `dfea7456` 2026-09-15 00:54Z waiting_for_benchmark market unknown/unknown armed 0; `0844b834` 2026-09-15 00:59Z waiting_for_benchmark market unknown/unknown armed 0; `d1f642d3` 2026-09-15 01:08Z waiting_for_benchmark market unknown/unknown armed 0; `7ce9e5b0` 2026-09-15 01:13Z waiting_for_benchmark market unknown/unknown armed 0; `8c9a6a91` 2026-09-15 01:18Z waiting_for_benchmark market unknown/unknown armed 0; `81b6d920` 2026-09-15 01:23Z waiting_for_benchmark market unknown/unknown armed 0; `38deb5b4` 2026-09-15 01:28Z waiting_for_benchmark market unknown/unknown armed 0; `20bd99ae` 2026-09-15 01:33Z waiting_for_benchmark market unknown/unknown armed 0; `072d5e98` 2026-09-15 04:21Z partial market mixed/mixed armed 0 (resumed from `cf8834f1`); `99278d42` 2026-09-15 04:34Z partial market mixed/mixed armed 0 (resumed from `072d5e98`); `6455e37d` 2026-09-15 04:49Z partial market mixed/mixed armed 0 (resumed from `99278d42`); `970f33bc` 2026-09-15 05:09Z partial market mixed/mixed armed 0 (resumed from `6455e37d`); `c612794b` 2026-09-15 12:45Z partial market mixed/mixed armed 0 (resumed from `970f33bc`); `e3cde41e` 2026-09-15 13:00Z partial market mixed/mixed armed 0 (resumed from `c612794b`); `b026e513` 2026-09-15 13:26Z partial market mixed/mixed armed 0 (resumed from `e3cde41e`)
- **2026-09-16**: `f1bb38d5` 2026-09-16 00:10Z waiting_for_benchmark market unknown/unknown armed 0; `b7fd41d1` 2026-09-16 00:18Z waiting_for_benchmark market unknown/unknown armed 0; `866d97b8` 2026-09-16 00:20Z waiting_for_benchmark market unknown/unknown armed 0; `58b2fdce` 2026-09-16 00:23Z waiting_for_benchmark market unknown/unknown armed 0; `54f472f1` 2026-09-16 00:28Z waiting_for_benchmark market unknown/unknown armed 0; `e9c0f53b` 2026-09-16 00:33Z waiting_for_benchmark market unknown/unknown armed 0; `d37b6f39` 2026-09-16 00:38Z waiting_for_benchmark market unknown/unknown armed 0; `c37cc76d` 2026-09-16 00:43Z waiting_for_benchmark market unknown/unknown armed 0; `7da93979` 2026-09-16 00:52Z waiting_for_benchmark market unknown/unknown armed 0; `d27fd92c` 2026-09-16 00:57Z waiting_for_benchmark market unknown/unknown armed 0; `5383488f` 2026-09-16 01:02Z waiting_for_benchmark market unknown/unknown armed 0; `e6c35152` 2026-09-16 01:07Z waiting_for_benchmark market unknown/unknown armed 0; `b288ae2b` 2026-09-16 01:12Z waiting_for_benchmark market unknown/unknown armed 0; `870dfe1c` 2026-09-16 01:41Z waiting_for_benchmark market unknown/unknown armed 0; `f88011f0` 2026-09-16 01:46Z waiting_for_benchmark market unknown/unknown armed 0; `349408c4` 2026-09-16 01:51Z waiting_for_benchmark market unknown/unknown armed 0; `27945174` 2026-09-16 01:56Z waiting_for_benchmark market unknown/unknown armed 0; `f572d0b4` 2026-09-16 02:01Z waiting_for_benchmark market unknown/unknown armed 0; `b9bde169` 2026-09-16 02:06Z waiting_for_benchmark market unknown/unknown armed 0; `5d0474de` 2026-09-16 02:11Z waiting_for_benchmark market unknown/unknown armed 0; `4cbb91dc` 2026-09-16 02:16Z waiting_for_benchmark market unknown/unknown armed 0; `30b113f6` 2026-09-16 02:21Z waiting_for_benchmark market unknown/unknown armed 0; `ed6d9da2` 2026-09-16 02:26Z partial market short/short armed 5; `6ac86f85` 2026-09-16 02:52Z partial market short/short armed 0 (resumed from `ed6d9da2`); `f5fa1018` 2026-09-16 03:15Z partial market short/short armed 0 (resumed from `6ac86f85`); `5b252a94` 2026-09-16 03:41Z partial market short/short armed 0 (resumed from `f5fa1018`); `75de9fa7` 2026-09-16 12:45Z partial market short/short armed 0 (resumed from `5b252a94`); `97a0780a` 2026-09-16 12:59Z partial market short/short armed 0 (resumed from `75de9fa7`); `e02f0a2b` 2026-09-16 13:24Z partial market short/short armed 0 (resumed from `97a0780a`)
- **2026-09-17**: `54438c99` 2026-09-17 00:20Z waiting_for_benchmark market unknown/unknown armed 0; `f76ee34a` 2026-09-17 00:24Z waiting_for_benchmark market unknown/unknown armed 0; `eb7efb62` 2026-09-17 00:29Z waiting_for_benchmark market unknown/unknown armed 0; `a2ed9e18` 2026-09-17 00:34Z waiting_for_benchmark market unknown/unknown armed 0; `70f7c328` 2026-09-17 00:39Z waiting_for_benchmark market unknown/unknown armed 0; `67704047` 2026-09-17 00:45Z waiting_for_benchmark market unknown/unknown armed 0; `ac1c6e72` 2026-09-17 00:50Z waiting_for_benchmark market unknown/unknown armed 0; `fb5d4965` 2026-09-17 01:06Z waiting_for_benchmark market unknown/unknown armed 0; `cee03dd7` 2026-09-17 01:11Z partial market short/short armed 1; `467e472e` 2026-09-17 02:35Z partial market short/short armed 0 (resumed from `46b712ad`); `c45b6dff` 2026-09-17 02:50Z partial market short/short armed 0 (resumed from `467e472e`); `a3244050` 2026-09-17 03:18Z partial market short/short armed 0 (resumed from `c45b6dff`); `7a0a0964` 2026-09-17 12:45Z partial market short/short armed 0 (resumed from `a3244050`); `8b11e3ce` 2026-09-17 12:58Z partial market short/short armed 0 (resumed from `7a0a0964`); `bc78bc51` 2026-09-17 13:23Z partial market short/short armed 0 (resumed from `8b11e3ce`)

## Rows that reached the history stages (screen and context passed under Lane A)

### 2026-09-08 — 2 rows; saved limits {'dte_max': 90, 'dte_min': 21, 'max_ask': 5.0, 'target_dte': 45, 'min_abs_delta': 0.25, 'refresh_limit': 6, 'max_spread_pct': 20.0, 'target_abs_delta': 0.5, 'min_open_interest': 100}; effective cap $5.00 (policy; equity 10000.0 at 2026-09-08T04:40:46.391000+00:00)

| Symbol | Old planner | Later recovery | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (snapshot date) | Failure sets | Note |
|---|---|---|---|---|---|---|---|---|---|
| SPCX | old_planner_candidate:armed | — | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| ZIM | old_planner_candidate:awaiting_contract | — | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |

### 2026-09-09 — 0 rows; saved limits {'dte_max': 90, 'dte_min': 21, 'max_ask': 5.0, 'target_dte': 45, 'min_abs_delta': 0.25, 'refresh_limit': 6, 'max_spread_pct': 20.0, 'target_abs_delta': 0.5, 'min_open_interest': 100}; effective cap $5.00 (policy; equity 10000.0 at 2026-09-09T03:36:44.979000+00:00)

| Symbol | Old planner | Later recovery | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (snapshot date) | Failure sets | Note |
|---|---|---|---|---|---|---|---|---|---|

### 2026-09-10 — 17 rows; saved limits {'dte_max': 90, 'dte_min': 21, 'max_ask': 5.0, 'target_dte': 45, 'min_abs_delta': 0.25, 'refresh_limit': 6, 'max_spread_pct': 20.0, 'target_abs_delta': 0.5, 'min_open_interest': 100}; effective cap $5.00 (policy; equity 10000.0 at 2026-09-10T04:27:32.085000+00:00)

| Symbol | Old planner | Later recovery | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (snapshot date) | Failure sets | Note |
|---|---|---|---|---|---|---|---|---|---|
| ABUS | old_planner_candidate:awaiting_contract | awaiting_contract@05:31 | qualified | 3 | 0.46 / 2.10% | fail | unknown_stale |  |  |
| ACVA | old_planner_candidate:not_shortlisted | — | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| BGC | old_planner_candidate:not_shortlisted | — | qualified | 2 | 0.14 / 0.89% | fail | unknown_stale |  |  |
| COIN | old_planner_candidate:armed | — | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| CTKB | old_planner_candidate:not_shortlisted | — | distance_floor | 2 | 0.05 / 0.31% | — | — |  | First target 0.31% away; floor 0.5% (existing rule). |
| CVNA | old_planner_candidate:armed | — | qualified | 2 | 0.06 / 0.52% | fail | affordable (2026-09-09) | {'spread+open_interest+premium': 3, 'open_interest+premium': 36, 'open_interest': 11, 'spread+open_interest': 9, 'delta+open_interest': 5, 'delta': 8, 'delta+spread+open_interest': 11, 'delta+spread': 22, 'premium': 20, 'quotes+delta': 2} |  |
| EL | old_planner_candidate:armed | — | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| FUTU | old_planner_candidate:not_shortlisted | awaiting_contract@05:31 | qualified | 2 | 1.09 / 9.99% | fail | unknown_stale |  |  |
| GRAL | old_planner_candidate:not_shortlisted | — | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| GROY | old_planner_candidate:not_shortlisted | — | qualified | 2 | 0.07 / 0.57% | fail | unknown_stale |  |  |
| MUR | old_planner_rejected | — | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| NTRA | old_planner_candidate:not_shortlisted | awaiting_contract@05:31 | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| OCUL | old_planner_rejected | — | distance_floor | 2 | 0.01 / 0.17% | — | — |  | First target 0.17% away; floor 0.5% (existing rule). |
| SPCX | old_planner_candidate:armed | — | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| TBBB | old_planner_candidate:not_shortlisted | awaiting_contract@05:31 | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| TGTX | old_planner_rejected | — | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| ZIM | old_planner_candidate:not_shortlisted | armed@05:31 | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |

### 2026-09-11 — 0 rows; saved limits {'dte_max': 90, 'dte_min': 21, 'max_ask': 5.0, 'target_dte': 45, 'min_abs_delta': 0.25, 'refresh_limit': 6, 'max_spread_pct': 20.0, 'target_abs_delta': 0.5, 'min_open_interest': 100}; effective cap $5.00 (policy; equity 10000.0 at 2026-09-11T04:49:37.232000+00:00)

| Symbol | Old planner | Later recovery | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (snapshot date) | Failure sets | Note |
|---|---|---|---|---|---|---|---|---|---|

### 2026-09-14 — 14 rows; saved limits {'dte_max': 90, 'dte_min': 21, 'max_ask': 5.0, 'target_dte': 45, 'min_abs_delta': 0.25, 'refresh_limit': 6, 'max_spread_pct': 20.0, 'target_abs_delta': 0.5, 'min_open_interest': 100}; effective cap $5.00 (policy; equity 10000.0 at 2026-09-13T02:14:19.434000+00:00)

| Symbol | Old planner | Later recovery | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (snapshot date) | Failure sets | Note |
|---|---|---|---|---|---|---|---|---|---|
| APA | old_planner_candidate:armed | already_managed@00:52 | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| CGNX | old_planner_candidate:armed | already_managed@00:52 | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| CLF | old_planner_rejected | — | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| COIN | old_planner_rejected | — | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| DT | old_planner_rejected | — | distance_floor | 2 | 0.00 / 0.05% | — | — |  | First target 0.05% away; floor 0.5% (existing rule). |
| HOG | old_planner_candidate:not_shortlisted | — | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| NOV | old_planner_candidate:armed | already_managed@00:52 | confirmed_target | 4 | — | — | — |  | No confirmed daily pivot above the trigger (Fibonacci fallback is off in Lane A) |
| NTRA | old_planner_candidate:not_shortlisted | — | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| OII | old_planner_candidate:not_shortlisted | — | qualified | 2 | 0.27 / 2.18% | fail | unknown_stale |  |  |
| OKTA | old_planner_candidate:awaiting_contract | expired@00:52 | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| PPC | old_planner_candidate:not_shortlisted | — | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| SXC | old_planner_candidate:not_shortlisted | — | confirmed_target | 2 | — | — | — |  | No confirmed daily pivot above the trigger (Fibonacci fallback is off in Lane A) |
| URBN | old_planner_candidate:not_shortlisted | — | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |
| VERA | old_planner_candidate:not_shortlisted | — | ceiling_tests | 1 | — | — | — |  | Ceiling tested 1 time(s); Lane A requires 2. |

### 2026-09-15 — 0 rows; saved limits {'dte_max': 90, 'dte_min': 21, 'max_ask': 5.0, 'target_dte': 45, 'min_abs_delta': 0.25, 'refresh_limit': 6, 'max_spread_pct': 20.0, 'target_abs_delta': 0.5, 'min_open_interest': 100}; effective cap $5.00 (policy; equity 9938.869999999999 at 2026-09-15T04:21:32.860000+00:00)

| Symbol | Old planner | Later recovery | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (snapshot date) | Failure sets | Note |
|---|---|---|---|---|---|---|---|---|---|

### 2026-09-16 — 0 rows; saved limits {'dte_max': 90, 'dte_min': 21, 'max_ask': 5.0, 'target_dte': 45, 'min_abs_delta': 0.25, 'refresh_limit': 6, 'max_spread_pct': 20.0, 'target_abs_delta': 0.5, 'min_open_interest': 100}; effective cap $5.00 (policy; equity 9938.869999999999 at 2026-09-16T02:26:43.093000+00:00)

| Symbol | Old planner | Later recovery | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (snapshot date) | Failure sets | Note |
|---|---|---|---|---|---|---|---|---|---|

### 2026-09-17 — 0 rows; saved limits {'dte_max': 90, 'dte_min': 21, 'max_ask': 5.0, 'target_dte': 45, 'min_abs_delta': 0.25, 'refresh_limit': 6, 'max_spread_pct': 20.0, 'target_abs_delta': 0.5, 'min_open_interest': 100}; effective cap $5.00 (policy; equity 9938.869999999999 at 2026-09-17T01:11:18.230000+00:00)

| Symbol | Old planner | Later recovery | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (snapshot date) | Failure sets | Note |
|---|---|---|---|---|---|---|---|---|---|

## Reading

- `direction`: not a strict-bullish session or not a long analysis — Lane A does not plan it.
- `screen` / `context`: the existing (unchanged) gates failed in the frozen analysis; the failed gate or check is named.
- `base_family`, `ceiling_tests`, `confirmed_target`, `distance_floor`: Lane A's own stages.
- `missing_analysis` / `unavailable_evidence` / `prefiltered`: a preparation row with no frozen analysis run, a daily-history error, or a listing the (then strict) industry pre-filter excluded before any history was fetched.
- Population = analyses parented by the original run plus analyses its rows cite (a resumed run reuses analyses an earlier run created); the reused count is shown per session.
- Old planner classes: `old_planner_rejected` = context passed but the current automatic review filtered it; `old_planner_blocked` = plan_blocked; `old_planner_candidate:<shortlist status>`.
- Later recovery lists shortlist statuses from later runs of the same session; it never changes the original-time verdict.
- Feasibility `unknown_stale`: no nightly snapshot for the previous session; the row stays in the denominator and no later stage is inferred.
