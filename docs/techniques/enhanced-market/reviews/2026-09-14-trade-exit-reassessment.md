# EM actual trades and exits: return to strategy review

**Finding:** the completed dedicated EM Practice book is profitable in this very small sample, while the complaints about scarce trades and profit giveback still identify useful research questions. September 14 closed **+$364.49 net**, and the five completed positions since this account began total **+$294.13 net**. These are simulated executions after recorded commissions, not a claim of live profitability or a reliable edge.

Read-only runtime database snapshot: **September 14, 2026, 23:36 ET**. Portfolio `045d8c35b3f149628ea001ae90a58edb`, named `EM Practice`, kind `sim`, starting cash $10,000. All five position quantities are zero and current cash is $10,294.127. The earlier comprehensive review correctly reported its intraday cutoff; this report adds MSFT's completed exit. No orders, settings, monetary corrections, or runtime changes were made.

## Completed execution ledger

All times are New York time. Money is USD. The ledger has eleven fills; order security types establish the correct multiplier, independently of the damaged plan projection.

| Session / position | Entry fill | Exit fill(s) | Gross P&L | Recorded commissions | Net P&L | Recorded exit |
|---|---|---|---:|---:|---:|---|
| Sep 10, two HOOD Sep 11 $114 puts | 09:47:21.532, 2 at $1.73 | 10:01:39.186, 2 at $1.399 | -$66.20 | $4.16 | **-$70.36** | Underlying quote-stop breach |
| Sep 14, 100 HPQ shares | 09:31:22.132, 100 at $34.77 | 09:37:03.508, 30 at $34.803; 09:51:28.608, 70 at $34.6531 | -$7.193 | $0 | **-$7.193** | TP1 trim, then underlying quote stop |
| Sep 14, one HOOD Sep 18 $115 put | 09:35:21.621, 1 at $3.45 | 09:38:01.073, 1 at $3.90 | +$45.00 | $2.08 | **+$42.92** | All at TP2 |
| Sep 14, two INTC Sep 14 $96 calls | 09:33:24.694, 2 at $1.00 | 11:42:03.381, 2 at $2.15 | +$230.00 | $4.16 | **+$225.84** | All at TP2 |
| Sep 14, one MSFT Sep 18 $507.50 put | 12:50:33.718, 1 at $5.45 | 15:56:00.980, 1 at $6.50 | +$105.00 | $2.08 | **+$102.92** | Session flatten |

September 14 exact net is $364.487; dedicated-account total is $294.127, after $12.48 total commissions. Three positions won and two lost. INTC contributes $225.84 of the $294.127 total. Reporting an average or win rate as an established strategy property would overstate five observations. All commissions are allocated to closed positions; there is no open entry-fee balance in this book.

**Accounting separation:** `positions.realized_pnl` and most plan projections are gross of commissions. HPQ's plan projection still incorrectly reports **-$719.30** and multiplier 100. The execution ledger and cash already reflect the real **-$7.193** share loss. Do not subtract another $712.107 from cash or describe the old projection as money lost. The separately approved five-record FIX-01 repair remains unapplied and outside this review.

## What the givebacks actually show

### HOOD September 10: genuine favorable option movement, an ambitious target, then a stop

The two puts were bought at $1.73 and ultimately sold at $1.399 for a $70.36 net loss. The stored **exchange-tagged option bars** show $1.98 at 09:48, $2.13 at 09:50, and a high/close of approximately **$2.33 at 09:51**, before declining to $1.60 at 10:00. This is direct evidence of favorable movement in this contract, not an inference from the underlying alone. The $2.33 historical trade/bar price is approximately 34.7% above entry; it is **not a bid quote, an available two-contract exit, or $120 of proven attainable profit**.

The underlying short plan used entry 115.09, stop 115.6655, and targets **111.3716 / 108.118 / 105.794**. That put TP1 **6.461 initial underlying risk units** away and the configured two-contract full exit at TP2 **12.115 units** away. Between completed post-entry bars and the exit, HOOD reached 113.50, a favorable move of approximately **2.763R**, and then reversed. Neither target was reached. Therefore this loss was not a failure to execute an already reached TP2. Its central strategy question is whether a brief at-level rejection should demand such a distant objective before taking any money off.

At 10:01:38.491 the exit event records underlying quote 115.925 through the 115.6655 stop, beyond the configured 0.25R quote-breach buffer. A market exit followed, filled about 0.70 seconds later. The recorded mechanism is underlying risk protection, not a premium-profit rule.

The contemporary critic called out closer support around 114.51 and 114.02 and criticized the distant target. That opinion existed before entry and was advisory. It is evidence for investigating obstacle-aware targets; it does not independently verify every critic assertion or prove that restoring all critic vetoes would help. Compare the same rule against the profitable INTC and September 14 HOOD cases, not only this loss.

### HPQ September 14: target observed, profit mostly gone before the sell

The plan's TP1 was 35.1462. The 09:36 exchange bar reached **35.19**, but closed at **34.87**. The TP1 exit intent was recorded at 09:37:00.461 and the 30 shares filled at **34.803** at 09:37:03.508. That trim earned only **$0.99**, despite the earlier target touch. The remaining 70 shares later lost $8.183.

This is the clearest execution-timing example: a completed-minute target observation does not secure that target's price. It supports comparing a feasible target execution method while retaining the same target. It does not establish that a resting order would necessarily have filled, nor that a universal earlier percentage target is optimal. A no-latency fill at the high would be hindsight.

The earlier false plan loss halt was real, but it was caused by the 100x projection error. It must not distort the exit study or be mistaken for a $719 economic drawdown.

### HOOD and INTC September 14: preserve the successful exits in the comparison

HOOD's single put exited at TP2 for **+$42.92 net**. Exchange-tagged option bars during fully contained post-entry minutes range up to roughly $4.57 versus the eventual $3.90 fill, but there is no contemporaneous bid path establishing that higher price was sellable. A successful exit can still have execution slippage; it is not automatically a missed-profit failure.

INTC's two same-day calls exited at TP2 for **+$225.84 net**, a 112.92% net gain relative to $200 paid premium. Its contained option bars span approximately $0.64 to $2.30. A policy that takes profit earlier or tightly trails premiums must also report how much of this winner it gives up, and whether the early adverse move would have stopped it. Choosing a rule only because it rescues HOOD would be selective fitting.

### MSFT September 14: independent short, no reached target, positive close

MSFT bought one put for $5.45 after a 25-second critic timeout and flattened at $6.50 at **15:56:00.980**, earning **+$102.92 net**. The persisted sizing message described a roughly $204 risk allowance but about $278 modeled loss per contract before repricing; the older minimum-one behavior admitted a lot that did not fit that model. A profitable outcome does not validate that sizing exception. The corrected risk-sized policy must be a separate future cohort.

This was an independent midday **short rejection** at 509.56 with stop 514.751 and targets **502.8106 / 496.9048 / 492.6864**. Fully contained post-entry exchange bars have a low of about **504.70**: even TP1 was not reached. Its actual exit is consistent with an untouched target ladder and a session flatten, rather than an unexecuted take-profit. It is not the outcome of the author's morning MSFT long scenario.

The option data needs particular caution. Sampled bars show early highs of **$7.10 at 12:51–12:52**, while neighboring exchange-tagged bars show $5.40 at 12:50, $5.65 at 12:54 and $5.66 at 12:56. We cannot establish the sampled maximum's freshness, source observation, or executable bid from these rows. Exchange-tagged fully contained bars later reach $6.50 and fall as low as about $4.60. Do not call the sampled $7.10 a $165 profit that the system definitely could have captured.

## Evidence quality and research boundary

The database does contain option OHLC bars; the correct limitation is **missing historical executable bid/ask evidence**, not a complete absence of option history. Fully contained post-entry bars exclude the entry minute and partial exit minute, preventing a pre-entry high from being counted as an available exit.

| Contract | Fully contained exchange-tagged bars | Their low / high | Sampled bars in same interval |
|---|---:|---|---:|
| HOOD Sep 11 $114 put | 12 | $1.60 / $2.33 | 1, high $2.61 |
| HOOD Sep 18 $115 put | 2 | $3.95 / $4.57 | 0 |
| INTC Sep 14 $96 call | 123 | $0.64 / $2.30 | 5 |
| MSFT Sep 18 $507.50 put | 68 | $4.60 / $6.50 | 116, high $7.10 |

`bars.source='exchange'` is the application's stored label; it is not a tick-level venue attestation. Bars can be corrected after the fact and contain no received-at timestamp proving when the live engine first knew that value. `BarAggregator.on_quote` constructs sampled bars from `last`, or `mid` if no positive last; these are not bid bars. There is no `execution_evidence` row for any of the eleven fills. Available daily chain snapshots have no intraday observation times and cannot establish intervening exit liquidity. No complete NBBO history for these contracts was found in the inspected storage.

Consequently the historical evidence supports **diagnosis and experiment selection**, but not a precise new policy P&L curve based on selling at the option highs. Preserve the recorded simulated fills as the accounting baseline and keep bar-price illustrations separate.

## One bounded next experiment

**Recommend an exit-only forward shadow comparison on the same actual EM admissions, option contracts, filled entry prices and whole quantities.** No new source interpretation, entry loosening, or higher risk is needed to answer this first question.

1. **Control:** current quantity-aware target/stop/flatten policy, including full TP2 exit for one/two contracts. Record execution cost and timing.
2. **Execution variant:** identical targets and quantities, but evaluate profit targets against fresh underlying observations and record the immediately available option bid and size. This isolates HPQ's observed completed-bar delay. Do not credit a fill before that observation or at an underlying target converted into an invented option price.
3. **Policy variant, registered separately:** an at-level bounce/rejection exit at the first eligible opposing structural level, selected from the saved pre-entry facts, with stop and time cap unchanged. Freeze the level-quality, tie-break, rounding, and one/two/three-plus quantity rule before evaluation. If no eligible level or known availability exists, label that observation ineligible rather than choosing the later reversal point. Source teaching does not provide every missing parameter; these are our experiment choices.

Evaluate control versus execution variant first; evaluate structural-policy changes using the same observation cadence to avoid combining two effects. Do not optimize a grid of +20/+25/+30% stops on these five trades. HPQ and September 10 HOOD motivate the questions; September 14 HOOD/INTC/MSFT are mandatory counterexamples. Research output should include all covered admissions, bid-based net outcome estimates, data gaps, worst loss, maximum observed executable gain and giveback, holding time, extra turnover, and gains sacrificed on winners. A separate chronological validation cohort is required before adopting a policy; five positions are a case study, not calibration or proof of edge.

For the next daily review, the first useful deliverable is a one-row timeline for every actual fill and every admissible-but-unfilled setup: source scenario, our direction/level, first eligible time, refusal or entry, actual quantity, first target observation, exit submission/fill, net result, and evidence availability. This can proceed while the worker reliability fixes remain with the development team.

## Reproduction pointers

- Authoritative tables: `executions JOIN orders` on order ID; portfolio filter above; `positions`; `portfolios`; `technique_armed.state.trades`; `events`; `bars` with symbol, timeframe, millisecond timestamp and source; `execution_evidence`; `option_chain_snapshots`.
- Plan/run IDs: HOOD Sep 10 `259fc0d016c445bf98d8c96c582c670d`; HOOD Sep 14 `18fa9b0fdba4486da9e8f3b084333945`; HPQ `4d46f31870224793aa3ad84345c4535e`; INTC `e568dcc1e8f74f049040095c2a061bcc`; MSFT `8979b99f5f7e47d8846c21d32661afa8`.
- Exact journal anchors: HOOD Sep 10 fire event `54189`, stop `54350`; MSFT fire `98856`, flatten `99228`. Original source/history discussion: [comprehensive review](2026-09-14-comprehensive-review.md), [execution audit](2026-09-14-execution-audit.md), [comprehensive fix plan](2026-09-14-comprehensive-fix-plan.md).
- Gross ledger arithmetic: buys negative and sells positive, multiplied by 100 for order `sec_type=OPT`, otherwise one; subtract each execution's commission exactly once. Round only the displayed total.
- Read-only access used `PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=10000'`; no live table or test database was changed, and no raw database export was created. Primary folder remains `C:/Cursor/zargar-codex`, branch `codex/zargar-development`; existing work is preserved.
