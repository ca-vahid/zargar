# Cartel opportunity coverage — 2026-09-15

Audit tree `b691afc`; parent reports runtime checkout `afbe3cff`, running process 0.7.87/build `5b7542da`. This report uses read-only queries and bounded pure analysis of saved inputs. No settings, plans, arms, orders, tests or engines were changed. All clock times are America/New_York.

**Tuesday does not support loosening the long market gate.** It does support measuring a separate bearish research cohort and collecting all nine identified long research names. Zero orders/fills means no observed trading return; it does not establish either a profitable filter or a missed profitable option trade.

## Frozen market gate and the actual day

Preparation `b026e513a1714235ad78b417803f5f8e` retained completed daily references from September 14. It was market-blocked, with `research_direction=long`, `market_alignment=moderate`, and no permission to unlock automatically intraday.

| Index | Frozen EMA8 | Frozen EMA21 | Frozen EMA50 | Sep 14 close |
|---|---:|---:|---:|---:|
| SPY | 763.731458 | 764.534403 | 758.557235 | 760.880005 |
| QQQ | 713.265808 | 713.760862 | 710.974939 | 709.179993 |

The saved intraday experiment has **26/26 quarter-hour snapshots**, 09:45 through 16:00, all from this preparation. All were available within the 120-second window: **60.502–118.260 seconds** after the boundary. There were **zero unavailable market snapshots, zero long-aligned snapshots and zero sustained long improvements**. The stored source bars reconstruct **390/390 exchange-class minute observations per index**.

- QQQ never reclaimed any frozen EMA on a one-minute close. Its highest observed minute close was **709.180115**, still below EMA50 710.974939. All 26 quarter-hour closes were below all three references.
- SPY never reclaimed EMA8 or EMA21 on a one-minute close. Its highest was **759.950012**, below both. It had 38 minute closes above EMA50, then crossed below on the **10:09 close, 758.530029**, and never reclaimed it.
- SPY quarter-hour closes at 09:45/10:00 were above EMA50 only. From **10:15 through 16:00**, both indices closed below all three frozen EMAs: **24 consecutive bearish-aligned closes**, representing **23 consecutive aligned pairs**. The first pair completed at **10:30**, observed at **10:31:16.023**. A prospective study must use that availability time, not backdate permission to 10:15.

Evidence checkpoints: `8322322859f675e03786a2d2e50518c8` (09:45), `c00a6358184f4f44c688651873d2d784` (10:15), `8c68071643079824206b7af3ca0a5f01` (10:30), `1212aa22ae33d56bec92d4023cdad1fc` (16:00). The runtime saved their long-side status as `not_aligned`; the bearish interpretation above is a separate reconstruction of the same frozen references.

## Nine research names versus five subscriptions

The preparation discovered **3,072** names, evaluated **3,070** histories (**99.935%**), and reported nine long research candidates. FISV failed for missing 2025-11-12 history; NFE for missing 2026-09-10 history. Those are two explicit historical-data exclusions, not the explanation for the absence of long market alignment.

| Candidate | Research shortlist | Historical baseline accepted | Local Tuesday minutes / exchange-class minutes |
|---|---|---|---:|
| BOX | Yes | Yes, 26/26 periods | 390 / 381 |
| NTNX | Yes | Yes, 26/26 periods | 390 / 371 |
| ARE | Yes | No: 25/26 periods, opening/broad policy fails | 390 / 350 |
| PPC | Yes | No: 24/26 periods, opening/broad policy fails | 390 / 344 |
| EL | Yes | Yes, 26/26 periods | 390 / 378 |
| DT | No | Not collected by this watcher | 0 / 0 |
| BILL | No | Not collected by this watcher | 0 / 0 |
| OCUL | No | Not collected by this watcher | 0 / 0 |
| GH | No | Not collected by this watcher | 0 / 0 |

Thus **5/9 (55.6%)** entered the intraday research subscription set, and **3/9 (33.3%)** had accepted historical baselines. The watcher recorded 130 candidate status rows: BOX/NTNX/EL contributed **78 `waiting_market` rows**; ARE/PPC contributed **52 `data_unavailable` rows**. Those 52 rows repeat **two cached baseline failures**, not 52 fresh provider failures. Context `597605028732d07403b1b56b503d6d9a`, saved **09:27:14.296**, retained the two errors throughout the session. Its predecessor context belonged to the earlier preparation and is not a second independent experiment.

`intraday_research.py:106` restricts collection to the first five market-blocked shortlist entries; `:113–152` stores one context; `:168–190` evaluates stock entry reads only after sustained market improvement. As the market never improved, none of the nine names generated an eligible research entry under this policy. `waiting_market` is not evidence that a stock's volume, crossing, stop and target-room checks passed. Conversely, names without subscriptions are unmeasured, not demonstrated failures.

The source-quality gaps matter for opportunity measurement if a later session does align. Counting 390 timestamps alone overstates usable history. Preserve source gates and retry missing historical baselines; do not lower coverage requirements to turn ARE/PPC green.

### DT and GH ranking interpretation

Saved analyses are DT `02537204414041d0a5b878d4c5ff13de` and GH `0cb5c383549b4a7da771ad4316307318`. Applying the same saved automatic-review policy selects:

| Name | Setup | Trigger | Structural invalidation | First target | Structural first-target R |
|---|---|---:|---:|---:|---:|
| DT | MA pullback | 53.509998 | 51.259998 | 53.810001 | 0.133335 |
| GH | Base | 168.970001 | 154.000000 | 170.869995 | 0.126920 |

Those values are below the selected five's structural R ranking: approximately BOX 1.00, NTNX .396, ARE .387, PPC .380 and EL .269. Omission is consistent with the frozen ranking. It is not proven bad ranking merely because a name later rose. The signal's actual session-extreme stop could produce different entry R and needs causal evaluation.

The parent audit separately retrieved post-close provider history: DT rose 52.77→55.17 and GH 167.25→175.68. These are **later retrieved underlying outcomes**, not prospective observations or option profits. Together with the omitted four's absence from local Tuesday bars, they justify measuring the entire research candidate set in the next cohort, rather than selecting a new ranking after seeing winners.

## Bearish research opportunity, without changed thresholds

The intraday implementation explicitly follows only market-blocked **long** preparations (`intraday_research.py:98`), so it never measured the sustained bearish regime above.

Using the saved September 14 inputs behind all 3,070 evaluated names:

1. **675 names** satisfy the existing non-directional stock gates (history, price, capitalization/classification, volume and ADR) and have close below both selected stock EMAs, 21 and 50. This count excludes the market-direction gate; it is not a trade count.
2. **32 names** also satisfy the unchanged short structural context: weekly-range, complete history, drying consolidation volume and base-range checks; negative relative strength versus SPY; and price within the configured 15% of the prior eight complete weeks' low. These are reconstructed research contexts, not saved executable plans or verified option opportunities.
3. To bound the follow-up, the **five highest prior-session-volume names among those 32** were independently run through the actual pure short screen, setup analyzer and automatic-review function using only their saved prior-session inputs. No rule or parameter changed.

| Name | Saved analysis ID | Result of bounded short review | Trigger / structural stop / first target | First-target structural R |
|---|---|---|---|---:|
| QS | `3f30573a703d4e37986186cc4ba9cf52` | Base candidate | 5.06 / 5.72 / 4.81 | .378788 |
| QUBT | `9fca53236f36432e82225e3afec6c40c` | MA-pullback candidate | 7.63 / 8.17 / 7.41 | .407408 |
| WEN | `3a027fd7d8344c8f98131a9cd0534a93` | Structural context passes; no automatic reviewed target plan selected | — | — |
| AA | `579bf8c621f94d3884aaa754ae78303a` | Base candidate; limited target room | 46.555 / 53.17 / 46.01 | .082389 |
| ZM | `bfbd31434c224df18089912526508be7` | Base candidate; limited target room | 94.66 / 102.25 / 93.32 | .176549 |

QS/QUBT are useful **next research subjects**, not recommendations to buy puts. None of these five has local Tuesday minute history. No same-time volume baseline, fresh post-alignment crossing, actual signal stop, executable put contract, spread, fill or exit was established. AA/ZM especially still require the existing actual entry-to-target minimum of .25R, calculated from the confirmation and its saved stop policy; their structural R does not bypass it.

As a selection-bias cross-check, the twelve highest-volume names among the broader 675 (ONDS, RIG, DRAM, ORCL, GRAB, BZ, PCG, SMR, WULF, CIFR, SOFI, JOBY) were also evaluated from saved inputs. **None passed all unchanged short setup checks.** High liquidity or a falling index is insufficient to manufacture an eligible Cartel short.

## Next experiments, ordered by economic usefulness

1. **Collect all qualifying research candidates, independent of the five execution slots.** Keep eligibility/ranking/risk unchanged. Retain the nine-name denominator, source-complete baselines, exact decision-time bars, and refusals. Retry ARE/PPC baseline gaps within the original cutoff instead of repeating a cached error all day. Compare the present five-name shortlist with the full candidate set prospectively; DT/GH are motivation to measure, not evidence to promote a replacement ranking.
2. **Add a separate, non-executing bearish research cohort.** Use the same strict bearish market definition, two timely consecutive closes, existing setup/volume/stop/chase rules, and predeclared selection from the saved universe. Record when alignment becomes available and only consider subsequent fully observed confirmations. Start with the 32 context candidates, with QS/QUBT examples to verify the pipeline. Do not turn Tuesday's reconstructed regime into retroactive orders.
3. **Measure funded option economics only after a qualifying stock confirmation.** Capture exact 21–90 DTE put/call contracts, independently dated Greeks, bid/ask, sizes, existing 20% spread and $5 ask limits, the $500 budget, integer quantity, fees and the actual exit policy. Score refusals, missing contracts, no-fills and unmeasured outcomes explicitly. Underlying open-to-close gains or target touches are not option returns.

The current evidence supports **broader, symmetric opportunity measurement**, while keeping the actual long gate and trading thresholds intact. It does not yet quantify foregone option P&L or demonstrate a profitable alternative.
