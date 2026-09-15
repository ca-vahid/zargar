# Options Cartel — September 15, 2026 profitability review

Review scope: profitability, opportunity selection and testable improvements. Reliability is treated as a supporting measurement constraint. This review changed no code, trading settings, orders, positions or runtime processes.

## Today's book

**No trades, $0 net P&L, no open Cartel position. Options Cartel Practice remains $9,938.87.** The book's cumulative result since its $10,000 reset is **-$61.13**, from Monday's single APA round trip. Tuesday did not add a loss or a gain. The combined Practice dashboard includes other techniques and is not this desk's result.

| Measure | September 15 |
|---|---:|
| Entry orders / exit orders / fills | 0 / 0 / 0 |
| Fees / realized P&L / open marked P&L | $0 / $0 / $0 |
| Closed campaigns / open instruments | 0 / 0 |
| Discovered / daily histories evaluated | 3,072 / 3,070 |
| Long research candidates / watched shortlist | 9 / 5 |
| Executable qualifying setups / armed | 0 / 0 |

Preparation `b026e513a1714235ad78b417803f5f8e` was blocked by market alignment. This was not a premium-budget or 10%-risk-ceiling refusal; increasing either would not have changed today's authorization.

## Was staying out the right call?

The measured evidence supports abstention from the current long-entry strategy today. It does not prove that every profitable trade in the wider market was unavailable.

The overnight assessment used September 14 daily closes: QQQ was below its 8/21/50 EMAs; SPY was below 8/21 but above 50. The new monitor recorded **26 of 26 quarter-hour observations** from 09:45 to 16:00 ET. None established long alignment or sustained long improvement. QQQ never closed above its frozen daily 50 reference in the minute tape; neither index reclaimed its daily 8/21 references. SPY lost its 50 reference on the 10:09 minute close and did not regain it.

The five watched long candidates were BOX, NTNX, ARE, PPC and EL. The most useful question was therefore whether disabling the market gate would have exposed an otherwise strong set of entries. On the available evidence, it did not.

### Long candidates under their existing stock-entry rules

This table is a retrospective stock-price study with the market-permission gate deliberately excluded for diagnosis. The actual app stayed out. It is not a simulation of executable option profit.

| Stock | What the saved rules/tape showed | Economic interpretation |
|---|---|---|
| BOX | Valid 15m stock confirmation at 12:00 ET; relative volume 1.63x, close location 0.786. Next minute opened 35.24; active underlying stop 34.45; target one 36.05. | Subsequent high only 35.245; EOD 34.815, about **-1.21% / -0.538 underlying R** from that reference. Neither stop nor first target was reached. This would be an open losing stock mark, not a realized option loss. |
| NTNX | Price later touched target one, but the 11:00 crossing had only **0.673x** baseline volume. Earlier untrusted minutes also prevented a verified session-low stop. | A target touch after an invalid entry signal is not a missed valid trade. Even a 1x volume threshold did not qualify that crossing. |
| ARE | Original 15m coverage 25/26; required opening/broad coverage failed. The 5m variant had adequate baseline coverage, but its crossing still failed session-context and minimum-target-R checks. | Its day high was just below target one. It does not establish a missed executable gain. |
| PPC | Original 15m coverage 24/26; price never reached the long trigger and the setup invalidated. | Repairing coverage alone would not have created a long entry today. |
| EL | Price never reached the long trigger; invalidated at 12:15. | No entry to rescue by changing position size or exit rules. |

BOX's daily high occurred before the baseline entry. Counting the whole-day high as favorable excursion after entry would substantially overstate the opportunity. Its post-entry favorable excursion was only about **0.006R**.

## The sweep: seven policies, nine candidates

I ran a bounded offline comparison of baseline 15m entries, 5m, 30m, volume 1x, volume 2x, breakout-candle stops, and retest entries. All other applicable source, target, close-location and chase checks stayed in place. Volume baselines were rebuilt for changed timeframes.

The original five use their pre-open historical baseline caches. DT, BILL, OCUL and GH were additionally examined with post-close Alpaca history; that is a separate retrospective data cohort, not proof of what the engine had observed live. The study contains **63 policy/candidate cases, not 63 independent trades**.

| Variant | Candidates with accepted baseline coverage | Stock confirmations | Result worth noting |
|---|---:|---:|---|
| Baseline: 15m, 1.5x volume | 7/9 | 1 — BOX | Negative EOD stock mark; neither protective stop nor target one reached. |
| 5m, same other limits | 9/9 | 1 — BOX | Earlier at 09:40; next open 35.20, EOD 34.815, about -0.513R. Earlier did not make this stock opportunity attractive. |
| 30m | 6/9 | 0 | No evidence here that waiting longer added opportunities. |
| Volume 1x | 7/9 | 1 — BOX | No incremental signal over baseline. |
| Volume 2x | 7/9 | 0 | Removes BOX, but one day cannot establish that 2x is superior. The actual market gate already kept us out. |
| Breakout-candle stop | 7/9 | 1 — BOX | Stop near 35.01 was touched at 14:48. This changes the risk denominator and holding path; do not compare its -1R mechanically with the baseline's open -0.538R. |
| Retest | 7/9 | 0 | No additional qualifying retest under the preserved rules. |

**Conclusion:** the sweep does not support an immediate blanket volume relaxation, larger budget, or universal switch to faster entries. The actual production result would remain zero trades for all these variants because market permission was blocked.

## Strong stocks we did not focus on: the more interesting question

Two omitted research names did have strong days in post-close provider history:

| Stock | Open → close | Change | Saved trigger / target one | Why this is not yet a proven missed trade |
|---|---|---:|---|---|
| DT | 52.77 → 55.17 | +4.55% | 53.51 / 53.81 | At 15m confirmation: volume 1.19x, close location 0.661, target room 0.249R — all below the saved requirements. At 5m, volume/close quality passed, but target room was only 0.155R. |
| GH | 167.25 → 175.68 | +5.04% | 168.97 / 170.87 | At 09:45, price had already passed target one. At 09:35 on the 5m variant, remaining target room was only 0.103R. |
| BILL | 49.04 → 49.97 | +1.90% | Saved research geometry retained in the analysis | No qualifying entry in the preserved-policy sweep; retrieved tape had 344 minutes, so it is not complete live-observation evidence. |
| OCUL | 10.78 → 10.21 | -5.29% | Saved research geometry retained in the analysis | Invalidated rather than generating a long signal. Broader coverage includes losers too. |

DT and GH were not excluded by a random bug: our ranking puts structural first-target R ahead of relative strength and volume. Their structural R was only **0.133 and 0.127**, compared with BOX's approximately **1.0**. That is precisely why the ranking deserves profitability research: it measures room to the nearest target relative to a reviewed structural invalidation, while execution normally uses a different, evolving session-extreme stop and a quantity-dependent exit campaign.

However, **ranking alone would not have admitted DT or GH** under the existing entry criteria. They were also market-blocked, and their first-target checks failed. We should not erase nearby resistance or lower a threshold to fit these two winners after seeing the close.

The worthwhile hypothesis is whether our selection and target hierarchy capture meaningful opportunity as well as Sean's theme/leader framework — and whether the first chart target is the right economic filter for the actual funded campaign. This requires measuring all candidates, including losers and non-entries, before changing execution.

## A direction gap: bearish research

From the 10:15 quarter-hour close onward, both indices were below all three frozen daily EMA references: **24 consecutive bearish observations**, with the first two-observation pair available around **10:31 ET**. The research monitor currently studies long recovery only. It therefore cannot tell us whether a properly selected downside strategy had an edge in this environment.

A bounded read of the saved pre-session universe found **675** stocks passing the neutral listing checks and below the selected stock EMA21/50 criteria; **32** also passed the unchanged directional structural context checks. These are screening results, not tradable puts or an exact replication of the author's bearish scanner.

Two higher-volume examples from the structural subset:

- **QS:** saved short trigger 5.06, invalidation 5.72, first target 4.81. Post-close tape showed raw 15m downward crossings at 11:00 and 15:45; day low 4.98 never reached that target. Open-to-close change was -2.42%. Baseline volume, full entry checks and contemporaneous option eligibility were not established for those crossings.
- **QUBT:** saved short trigger 7.63; day low 7.7801 stayed above it. The stock rose about 0.38% from open to close, so a bearish index environment alone would not justify a put entry.

This makes bearish **research** a useful next branch of the method. It does not justify automatically buying puts tomorrow or treating every mixed morning as bearish permission. The existing execution gate is unchanged.

## What Sean posted

Sean's September 15 posts explicitly support cash and patience in poor conditions: [13:00 PT environment post](https://x.com/SRxTrades/status/2099951391816999321) and [10:00 PT discipline post](https://x.com/SRxTrades/status/2099906095279989015). These support our cash benchmark; they are not a verified report of his actual daily P&L.

His [September 14 management post](https://x.com/SRxTrades/status/2099641849212293453) distinguishes taking strength sooner in chop from allowing more time in clean trends. His [September 13 system framework](https://x.com/SRxTrades/status/2099241717983486243) emphasizes market → theme → leader → setup → trigger → risk. The [March 30 bearish framework](https://x.com/SRxTrades/status/1906420174246510756) supports downside setups when the indices are below their key averages, with weak groups and weak stocks selected deliberately.

His [September 14 selective examples](https://x.com/SRxTrades/status/2099566349320438117) included a VWAP reclaim, leveraged shares and adding to an existing position. Those cannot be used as equivalent fills for our fresh option-breakout cohort.

No verified September 15 Cartel account return was obtained. The inspected Cartel profile still showed the older DRAM percentage highlight; promotional peak percentages lack the quantities, weighted exits and costs needed for an account comparison.

## Profitability development priorities

### 1. Observe the full candidate pool and compare selection methods

Keep five execution slots if desired, but measure all nine eligible research names, with an explicitly bounded observation pool for larger days. Compare the current structural-R-first ranking with a frozen theme/leader-first challenger using the same market and execution eligibility. Measure usable entries, net option results when quotes exist, false breaks, concentration, and opportunity capture at the same capital limit.

Do not count DT/GH's whole-day gain as missed profit. Acceptance requires a subsequent period, costs, the same opportunity denominator and results that do not depend on the largest winner.

### 2. Diagnose target hierarchy and actual campaign economics

Preserve every saved resistance level. Record why a target is minor versus major using only pre-entry evidence, the actual session-stop distance, feasible whole-contract quantity and the first exit that quantity can execute. Compare the present first-target veto against one predefined campaign-aware research policy. Keep this separate from changing market permission.

DT/GH make this worth studying, not automatically loosening. A two-gate change (for example faster confirmation plus different target policy) must be registered as a joint challenger and tested prospectively, not discovered by repeatedly fitting today's winners. Include spreads, fees and the cost of false breaks before any promotion.

### 3. Add a separately versioned bearish research cohort

Prepare weak leaders in weak groups from pre-session data, using a clearly identified bearish source variant. Record eligibility after confirmed bearish market context and accept only subsequent fresh signals. Collect put quotes and contract-selection failures without placing orders. Compare net opportunities with the cash baseline; include days like QUBT where no trigger occurred.

No automatic long-to-short flip, retrospective entry, risk increase or Live activation is proposed here.

### 4. Test failed-break containment and environment-dependent exits

BOX's post-entry path had almost no favorable follow-through. Study a predefined failed-break/time-based exit and a separate weak-environment strength-trim rule against the existing campaign. Use completed source-qualified bars, actual feasible quantities and identical entry cohorts. Count good trades cut prematurely as well as losses reduced.

BOX's first 15m close back below trigger was 12:15, but that bucket contained sampled data. We did not book imaginary exit savings from it. One-contract positions cannot reproduce percentage trims; do not invent fractional option sales or silently migrate their exit policy.

### 5. Measure expression choice where contract constraints actually bind

For an otherwise valid setup whose option cannot fit unchanged contract/budget limits, compare ordinary unlevered shares with skipping. Use equal cash caps and report differing leverage/stop risk. This was not today's primary bottleneck because the market gate stopped the process earlier. It is a lower-priority conditional experiment, not a reason to raise the premium cap now.

## What stays unchanged today

Keep the execution market gate, 10% ceiling, $500 premium budget, source-quality protections and current trade-management policies. Today's evidence does not support changing them simply to increase activity. The next work should improve the opportunity model and establish net expectancy, not turn a correct cash day into a forced trade.

Reliability caveats are limited to measurement here: some archived stock minutes are sampled, ARE/PPC lacked acceptable 15m baseline coverage, and no contemporaneous selected option/quote sequence exists for the blocked research candidates. Those facts constrain profit claims. They are not an invitation to make this another broad infrastructure rewrite.

## Evidence and reproducibility

- Audit checkout: `C:/Cursor/zargar-codex/.cache/cartel-profitability-20260915`, detached `b691afc`.
- Runtime checked after close: healthy v0.7.87, process build `5b7542da7f07d4b97826ca5b54c740d2626aacac`; checkout `afbe3cff86bcf112e0928fa17958189244939f1b`. Relevant Cartel code had no diff from the audit snapshot.
- Actual account: `0b48ed48de2f4030b49942b52858356d`; preparation and archived research context were read with read-only API/SQL.
- Supporting artifacts are preserved in `reviews/2026-09-15/`: `profitability-findings.md`, `market-opportunities.md`, `author-profitability-review.md`, both sweep scripts and their derived JSON results. Scripts read runtime data without modifying it; the expanded script also requests post-close provider history. Future reruns may see provider revisions and must not be mislabeled as original decision-time evidence.
- The expanded study's four extra long names and two bearish examples used explicitly post-close, read-only Alpaca retrieval. No histories were written into the runtime, and no settings, arms or orders changed.
- Underlying scenario results are not option P&L. Open marks are not closed returns. One session is exploratory evidence, not optimization or profitability validation.
