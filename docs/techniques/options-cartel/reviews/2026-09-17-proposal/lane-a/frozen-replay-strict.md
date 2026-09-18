# Lane A frozen replay — 2026-09-08 → 2026-09-17 (market basis: strict)

Lane A's definition uses the **strict** read (both indices above their 8/21/50 EMAs). Both readings are recorded per session in the table.

Generated 2026-09-18T01:55:13+00:00 by `zargar.tools.cartel_lane_a_eval` (read-only) from the original preparation run of each session and the frozen analysis runs it cited. Lane A parameters: base 10 sessions, ceiling tests ≥ 2 within 0.5%, confirmed pivots only, distance floor 0.5%, experimental planning R ≥ 1.5 **recorded, inactive**. Feasibility from the newest chain snapshot dated before the session with the effective cap $5.00; `unknown_stale` where none exists.

A `qualified` row is a planning verdict under Lane A's definition over frozen inputs. It is not an entry, a fill or an outcome; conclusions stop at the last supported stage. Only screen-and-context-passing rows can qualify (Lane A keeps those gates), so the rows below are the complete candidate set for the lane; the denominators are the preparation run's own counts.

## Sessions

| Session | Market strict / Moderate read | Discovered | Evaluated | Context-passing | Lane A qualified | Exp. 1.5R passes | Lane A stages | Feasibility of qualified | Current rules armed |
|---|---|---|---|---|---|---|---|---|---|
| 2026-09-08 | long / long (used: long) | 3090 | 58 | 2 | **0** | 0 | {'ceiling_tests': 2} | — | 1 |
| 2026-09-09 | mixed / long (used: mixed) | 3092 | 3084 | 39 | **0** | 0 | {'direction': 31, 'data_error': 8} | — | 5 |
| 2026-09-10 | mixed / long (used: mixed) | 3083 | 3081 | 16 | **0** | 0 | {'direction': 14, 'data_error': 2} | — | 4 |
| 2026-09-11 | short / short (used: short) | 3078 | 3077 | 35 | **0** | 0 | {'direction': 34, 'data_error': 1} | — | 5 |
| 2026-09-14 | mixed / long (used: mixed) | 3076 | 3075 | 12 | **0** | 0 | {'data_error': 1, 'direction': 11} | — | 3 |
| 2026-09-15 | mixed / mixed (used: mixed) | 3072 | 3070 | 2 | **0** | 0 | {'data_error': 2} | — | 0 |
| 2026-09-16 | short / short (used: short) | 3066 | 3062 | 33 | **0** | 0 | {'direction': 29, 'data_error': 4} | — | 5 |
| 2026-09-17 | short / short (used: short) | 3059 | 3056 | 16 | **0** | 0 | {'data_error': 3, 'direction': 13} | — | 1 |

## Rows (context-passing symbols per session)

### 2026-09-08 — market long, preparation `4f312571` (created 2026-09-08 04:40:59Z; 3 runs that session)

| Symbol | Current rules | Current setup / R | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (chain date) | Note |
|---|---|---|---|---|---|---|---|---|
| SPCX | candidate → armed | inside_day / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |
| ZIM | candidate → awaiting_contract | ma_pullback / — | ceiling_tests | 1 | — | — | — | Ceiling tested 1 time(s); Lane A requires 2. |

### 2026-09-09 — market mixed, preparation `11279651` (created 2026-09-09 04:42:11Z; 4 runs that session)

| Symbol | Current rules | Current setup / R | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (chain date) | Note |
|---|---|---|---|---|---|---|---|---|
| SPCX | candidate → armed | ma_pullback / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| DRAM | candidate → armed | base / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| FISV | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: missing regular-session bar: 2025-11-12 |
| VG | candidate → armed | ma_pullback / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| CMG | candidate → armed | flag / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| CPRT | candidate → armed | base / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| CVNA | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| MNKD | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| OSCR | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| ANET | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| AA | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| OCUL | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| EL | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| UA | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: daily provider timestamp is not the expected US exchan |
| VRDN | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| NOG | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| BGC | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| MUR | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| LAZ | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| GROY | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| TGTX | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| EPAM | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| LRMR | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| NTRA | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| KEYS | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| CGEM | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| HNRG | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| ADEA | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: daily provider timestamp is not the expected US exchan |
| FUTU | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| GRAL | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| VIRT | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| WLY | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: daily provider timestamp is not the expected US exchan |
| WWW | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| ANRO | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| TBBB | candidate | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| HUBB | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: daily provider timestamp is not the expected US exchan |
| WCT | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: missing regular-session bar: 2026-07-20 |
| CTSO | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: missing regular-session bar: 2026-07-20 |
| SFWL | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: missing regular-session bar: 2026-07-20 |

### 2026-09-10 — market mixed, preparation `33e2a508` (created 2026-09-10 04:27:36Z; 3 runs that session)

| Symbol | Current rules | Current setup / R | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (chain date) | Note |
|---|---|---|---|---|---|---|---|---|
| SPCX | candidate → armed | inside_day / 0.57 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| FISV | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: missing regular-session bar: 2025-11-12 |
| CVNA | candidate → armed | base / 0.06 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| COIN | candidate → armed | ma_pullback / 0.14 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| ABUS | candidate → awaiting_contract | ma_pullback / 1.10 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| ACVA | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| EL | candidate → armed | ma_pullback / 0.59 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| BGC | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| GROY | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| ZIM | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| CTKB | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| TBBB | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| NTRA | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| FUTU | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| GRAL | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
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

### 2026-09-14 — market mixed, preparation `98bd007f` (created 2026-09-13 02:14:35Z; 3 runs that session)

| Symbol | Current rules | Current setup / R | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (chain date) | Note |
|---|---|---|---|---|---|---|---|---|
| FISV | data_error | — / — | data_error | — | — | — | — | Daily history error in preparation: missing regular-session bar: 2025-11-12 |
| APA | candidate → armed | inside_day / 1.80 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| VERA | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| NOV | candidate → armed | base / 0.79 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| OKTA | candidate → awaiting_contract | base / 0.91 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| HOG | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| CGNX | candidate → armed | ma_pullback / 0.26 | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| OII | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| PPC | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| SXC | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| URBN | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |
| NTRA | candidate/plan_blocked | — / — | direction | — | — | — | — | Lane A plans only long setups on strict-bullish sessions (direction=long, market=mixed). |

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
