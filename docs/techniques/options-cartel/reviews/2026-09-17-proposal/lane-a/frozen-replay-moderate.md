# Lane A frozen replay — 2026-09-08 → 2026-09-17 (market basis: moderate)

**Variant for information only:** this run uses the preparation's Moderate read as the market direction, which is NOT Lane A's definition; it shows what the lane would have planned had the Practice Moderate experiment's direction been accepted. Both readings are recorded per session in the table.

Generated 2026-09-18T01:55:24+00:00 by `zargar.tools.cartel_lane_a_eval` (read-only) from the original preparation run of each session and the frozen analysis runs it cited. Lane A parameters: base 10 sessions, ceiling tests ≥ 2 within 0.5%, confirmed pivots only, distance floor 0.5%, experimental planning R ≥ 1.5 **recorded, inactive**. Feasibility from the newest chain snapshot dated before the session with the effective cap $5.00; `unknown_stale` where none exists.

A `qualified` row is a planning verdict under Lane A's definition over frozen inputs. It is not an entry, a fill or an outcome; conclusions stop at the last supported stage. Only screen-and-context-passing rows can qualify (Lane A keeps those gates), so the rows below are the complete candidate set for the lane; the denominators are the preparation run's own counts.

## Sessions

| Session | Market strict / Moderate read | Discovered | Evaluated | Context-passing | Lane A qualified | Exp. 1.5R passes | Lane A stages | Feasibility of qualified | Current rules armed |
|---|---|---|---|---|---|---|---|---|---|
| 2026-09-08 | long / long (used: long) | 3090 | 58 | 2 | **0** | 0 | {'ceiling_tests': 2} | — | 1 |
| 2026-09-09 | mixed / long (used: long) | 3092 | 3084 | 39 | **4** | 0 | {'ceiling_tests': 24, 'data_error': 8, 'qualified': 4, 'distance_floor': 2, 'confirmed_target': 1} | {'unknown_stale': 3, 'affordable': 1} | 5 |
| 2026-09-10 | mixed / long (used: long) | 3083 | 3081 | 16 | **5** | 0 | {'ceiling_tests': 8, 'data_error': 2, 'qualified': 5, 'distance_floor': 1} | {'affordable': 1, 'unknown_stale': 4} | 4 |
| 2026-09-11 | short / short (used: short) | 3078 | 3077 | 35 | **0** | 0 | {'direction': 34, 'data_error': 1} | — | 5 |
| 2026-09-14 | mixed / long (used: long) | 3076 | 3075 | 12 | **1** | 0 | {'data_error': 1, 'ceiling_tests': 8, 'confirmed_target': 2, 'qualified': 1} | {'unknown_stale': 1} | 3 |
| 2026-09-15 | mixed / mixed (used: mixed) | 3072 | 3070 | 2 | **0** | 0 | {'data_error': 2} | — | 0 |
| 2026-09-16 | short / short (used: short) | 3066 | 3062 | 33 | **0** | 0 | {'direction': 29, 'data_error': 4} | — | 5 |
| 2026-09-17 | short / short (used: short) | 3059 | 3056 | 16 | **0** | 0 | {'data_error': 3, 'direction': 13} | — | 1 |

## Rows (context-passing symbols per session)

### 2026-09-08 — market long, preparation `4f312571` (created 2026-09-08 04:40:59Z; 3 runs that session)

| Symbol | Current rules | Current setup / R | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (chain date) | Note |
|---|---|---|---|---|---|---|---|---|
| SPCX | candidate → armed | inside_day / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| ZIM | candidate → awaiting_contract | ma_pullback / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |

### 2026-09-09 — market long, preparation `11279651` (created 2026-09-09 04:42:11Z; 4 runs that session)

| Symbol | Current rules | Current setup / R | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (chain date) | Note |
|---|---|---|---|---|---|---|---|---|
| SPCX | candidate → armed | ma_pullback / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| DRAM | candidate → armed | base / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| FISV | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: missing regular-session bar: 2025-11-12 |
| VG | candidate → armed | ma_pullback / — | qualified | 2 | 0.10 / 0.92% | fail | unknown_stale |  |
| CMG | candidate → armed | flag / — | distance_floor | 2 | 0.07 / 0.44% | — | — | First target 0.44% away; floor 0.5% (existing rule). |
| CPRT | candidate → armed | base / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| CVNA | candidate | — / — | qualified | 3 | 0.06 / 0.52% | fail | affordable (2026-09-08) |  |
| MNKD | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| OSCR | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| ANET | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| AA | candidate | — / — | qualified | 2 | 0.15 / 1.06% | fail | unknown_stale |  |
| OCUL | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| EL | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| UA | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: daily provider timestamp is not the expected US exchan |
| VRDN | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| NOG | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| BGC | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| MUR | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| LAZ | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| GROY | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| TGTX | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| EPAM | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| LRMR | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| NTRA | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| KEYS | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| CGEM | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| HNRG | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| ADEA | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: daily provider timestamp is not the expected US exchan |
| FUTU | candidate | — / — | qualified | 2 | 1.09 / 9.99% | fail | unknown_stale |  |
| GRAL | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| VIRT | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| WLY | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: daily provider timestamp is not the expected US exchan |
| WWW | candidate | — / — | distance_floor | 2 | 0.03 / 0.24% | — | — | First target 0.24% away; floor 0.5% (existing rule). |
| ANRO | candidate | — / — | confirmed_target | 3 | — | — | — | No confirmed daily pivot above the trigger (Fibonacci fallback is off in Lane A). |
| TBBB | candidate | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| HUBB | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: daily provider timestamp is not the expected US exchan |
| WCT | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: missing regular-session bar: 2026-07-20 |
| CTSO | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: missing regular-session bar: 2026-07-20 |
| SFWL | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: missing regular-session bar: 2026-07-20 |

### 2026-09-10 — market long, preparation `33e2a508` (created 2026-09-10 04:27:36Z; 3 runs that session)

| Symbol | Current rules | Current setup / R | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (chain date) | Note |
|---|---|---|---|---|---|---|---|---|
| SPCX | candidate → armed | inside_day / 0.57 | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| FISV | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: missing regular-session bar: 2025-11-12 |
| CVNA | candidate → armed | base / 0.06 | qualified | 2 | 0.06 / 0.52% | fail | affordable (2026-09-09) |  |
| COIN | candidate → armed | ma_pullback / 0.14 | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| ABUS | candidate → awaiting_contract | ma_pullback / 1.10 | qualified | 3 | 0.46 / 2.10% | fail | unknown_stale |  |
| ACVA | candidate/plan_blocked | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| EL | candidate → armed | ma_pullback / 0.59 | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| BGC | candidate/plan_blocked | — / — | qualified | 2 | 0.14 / 0.89% | fail | unknown_stale |  |
| GROY | candidate/plan_blocked | — / — | qualified | 2 | 0.07 / 0.57% | fail | unknown_stale |  |
| ZIM | candidate/plan_blocked | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| CTKB | candidate/plan_blocked | — / — | distance_floor | 2 | 0.05 / 0.31% | — | — | First target 0.31% away; floor 0.5% (existing rule). |
| TBBB | candidate/plan_blocked | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| NTRA | candidate/plan_blocked | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| FUTU | candidate/plan_blocked | — / — | qualified | 2 | 1.09 / 9.99% | fail | unknown_stale |  |
| GRAL | candidate/plan_blocked | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| SFWL | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: missing regular-session bar: 2026-09-08 |

### 2026-09-11 — market short, preparation `a973b3a4` (created 2026-09-11 04:49:37Z; 1 runs that session)

| Symbol | Current rules | Current setup / R | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (chain date) | Note |
|---|---|---|---|---|---|---|---|---|
| QUBT | candidate → armed | ma_pullback / 0.24 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| FISV | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: missing regular-session bar: 2025-11-12 |
| AMAT | candidate → awaiting_contract | ma_pullback / 1.20 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| VIK | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| ZM | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| CENX | candidate → armed | ma_pullback / 0.24 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| REZI | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| DNUT | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| YETI | candidate → armed | ma_pullback / 0.46 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| BHF | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| SVRA | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| KC | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| AAP | candidate → armed | ma_pullback / 0.74 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| HLIT | candidate → awaiting_contract | ma_pullback / 0.58 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| AMTM | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| LAZ | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| ACHC | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| CMC | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| VNDA | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| LQDA | candidate → awaiting_contract | base / 0.78 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| CLDX | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| ATAT | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| LRMR | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| NOMD | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| AVR | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| LFTO | candidate → armed | ma_pullback / 3.54 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| AURA | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| STLD | candidate → awaiting_contract | ma_pullback / 1.30 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| FUL | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| BOOT | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| KN | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| SSYS | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| PWR | candidate → awaiting_contract | flag / 0.25 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| ATRO | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| TLN | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |

### 2026-09-14 — market long, preparation `98bd007f` (created 2026-09-13 02:14:35Z; 3 runs that session)

| Symbol | Current rules | Current setup / R | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (chain date) | Note |
|---|---|---|---|---|---|---|---|---|
| FISV | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: missing regular-session bar: 2025-11-12 |
| APA | candidate → armed | inside_day / 1.80 | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| VERA | candidate/plan_blocked | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| NOV | candidate → armed | base / 0.79 | confirmed_target | 4 | — | — | — | No confirmed daily pivot above the trigger (Fibonacci fallback is off in Lane A). |
| OKTA | candidate → awaiting_contract | base / 0.91 | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| HOG | candidate/plan_blocked | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| CGNX | candidate → armed | ma_pullback / 0.26 | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| OII | candidate/plan_blocked | — / — | qualified | 2 | 0.27 / 2.18% | fail | unknown_stale |  |
| PPC | candidate/plan_blocked | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| SXC | candidate/plan_blocked | — / — | confirmed_target | 2 | — | — | — | No confirmed daily pivot above the trigger (Fibonacci fallback is off in Lane A). |
| URBN | candidate/plan_blocked | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| NTRA | candidate/plan_blocked | — / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |

### 2026-09-15 — market mixed, preparation `072d5e98` (created 2026-09-15 04:21:50Z; 7 runs that session)

| Symbol | Current rules | Current setup / R | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (chain date) | Note |
|---|---|---|---|---|---|---|---|---|
| FISV | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: missing regular-session bar: 2025-11-12 |
| NFE | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: missing regular-session bar: 2026-09-10 |

### 2026-09-16 — market short, preparation `ed6d9da2` (created 2026-09-16 02:26:52Z; 7 runs that session)

| Symbol | Current rules | Current setup / R | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (chain date) | Note |
|---|---|---|---|---|---|---|---|---|
| QS | candidate → armed | ma_pullback / 0.61 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| TOST | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| HIMS | candidate → armed | ma_pullback / 0.31 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| FISV | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: missing regular-session bar: 2025-11-12 |
| QUBT | candidate → armed | inside_day / 0.41 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| APTV | candidate → armed | base / 1.71 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| DNUT | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| NVT | candidate → awaiting_contract | wedge / 0.46 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| REAL | candidate → awaiting_contract | ma_pullback / 0.32 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| AAP | candidate → armed | ma_pullback / 0.20 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| CSTM | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| SVRA | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| ACHC | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| STLD | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| ALH | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| SSYS | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| PLAB | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| ORKA | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| EH | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| PWR | candidate → awaiting_contract | flag / 0.23 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| KN | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| LZB | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| KLIC | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| SKY | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| GNRC | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| RERE | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| XENE | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| AVR | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| URGN | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| ATHM | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| CLBR | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: 1 validation error for DailyBar
  Value error, invalid |
| MTAL | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: 1 validation error for DailyBar
  Value error, invalid |
| BRK.A | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: 1 validation error for DailyBar
  Value error, invalid |

### 2026-09-17 — market short, preparation `cee03dd7` (created 2026-09-17 01:11:47Z; 7 runs that session)

| Symbol | Current rules | Current setup / R | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (chain date) | Note |
|---|---|---|---|---|---|---|---|---|
| FISV | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: missing regular-session bar: 2025-11-12 |
| APTV | candidate → armed | breakout_retest / 5.16 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| TTWO | candidate → awaiting_contract | ma_pullback / 0.28 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| GNRC | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| PLAB | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| BWXT | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| STLD | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| SYNA | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| LZB | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| PWR | candidate → awaiting_contract | wedge / 0.07 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| SKY | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| MRCY | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| SSYS | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| CW | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=short, market=short). |
| WENN | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: 1 validation error for DailyBar
  Value error, invalid |
| BRK.A | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: 1 validation error for DailyBar
  Value error, invalid |

## Reading

- `direction` = the session was not strict-bullish or the row was a short candidate; Lane A does not plan it.
- `context` / `base_family` = the existing gates or the `base` geometry did not pass in the frozen analysis.
- `ceiling_tests` = the base ceiling was tested fewer than the required times (Lane A's one added source-backed requirement).
- `confirmed_target` = no confirmed pivot above the trigger (the Fibonacci fallback is off in Lane A).
- `distance_floor` = the existing 0.5% first-target floor; kept active.
- Experimental 1.5R is recorded per qualified row and applied nowhere.
- Feasibility `unknown_stale` means no dated chain observation exists for that name; the candidate stays in the denominator and no later stage is inferred.
