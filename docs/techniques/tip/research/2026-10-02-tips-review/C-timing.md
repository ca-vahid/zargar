# C. Tips alert timing: from Discord post to fill

Scope: the two Tips Practice books (`4611946d…` from 2026-09-08, `88aa8a26…` from 2026-09-28). Data runs to 2026-10-02 16:30 ET.
Read-only analysis of `raw_content`, `signals`, `tip_analyst_runs`, `proposals`, `orders`, `executions`, `managed_positions`, `bars` and `events`. All times are measured from the Discord `postedAt` (`raw_content.meta.postedAt`). Where that field is missing, `received_at` is used.
Population: 248 proposals. 52 were executed (51 FILLED orders, 1 CANCELLED), 170 were rejected by the analyst, 24 expired and 2 failed. Of the 51 filled entries, 47 positions have closed.
Scripts and intermediate data are in this folder (`pull.py`, `an1..an9.py`, `props.json`, `drift.json`).

## 1. Latency chain, filled tips (n = 51)

| leg | n | median s | p75 | p90 | max |
|---|---|---|---|---|---|
| post -> received (gateway claim) | 48 | 0.1 | 0.4 | 1.0 | 8835 (09-14 outage) |
| received -> signal created (**extraction LLM** + verify) | 51 | 8.7 | 11.4 | 14.5 | 25.7 |
| signal -> appraisal start | 51 | 1.5 | 2.5 | 4.3 | 9.7 |
| **appraisal (analyst LLM, tool loop)** | 51 | **45.6** | 64.3 | 79.4 | 101.7 |
| appraisal end -> proposal | 51 | 0.5 | 0.9 | 1.4 | 798 |
| proposal -> approved (auto) | 51 | 0.2 | 0.3 | 0.8 | 58 761 (MRNA, overnight) |
| approved -> order | 51 | 0.1 | 0.1 | 0.1 | 0.9 |
| order -> first fill | 51 | 1.0 | 3.5 | 35.6 | 3 484 (resting limit) |
| **TOTAL post -> fill** | 51 | **66.7** | 94.6 | 390 | 67 640 |

By analyst model (filled tips, total under 1 h):

| model era | n | post->fill median | p75 | p90 | appraisal median | p90 |
|---|---|---|---|---|---|---|
| claude-opus-5 (to 09-23) | 30 | 84.0 s | 106 | 590 | 61.5 s | 82.9 |
| claude-opus-5-5 (from 09-23) | 20 | **46.7 s** | 55.2 | 62.2 | **30.2 s** | 39.7 |

Inside the intake run, across all live intake runs since 09-08 (trace timestamps):

| stage | n | median s | p75 | p90 |
|---|---|---|---|---|
| extraction LLM call | 1 818 | 7.2 | 11.1 | 17.6 |
| extraction, image posts (post->signal) | 169 | 17.0 | 22.4 | 47.2 |
| extraction, text posts (post->signal) | 631 | 8.7 | 15.4 | 32.2 |
| verification | 954 | 0.2 | 0.4 | 2.0 |
| appraisal (handed-off signals) | 344 | 29.8 | 45.6 | 68.1 |
| whole intake run (with appraisal) | 344 | 51.2 | 74.0 | 105.2 |

Appraisal split, all done appraise runs: tool execution takes a median of 0.1 s per run (p90 1.1 to 1.5 s). LLM turns take the rest: 36.4 s median on opus-5 and 18.4 s on opus-5-5, across about 3 to 4 tool calls per run.
A "take" costs more than a "skip". On opus-5-5 the median is 32.8 s for a take and 14.7 s for a skip; on opus-5 it was 65.3 s and 29.5 s.
**Where the time goes, filled tips on opus-5-5:** of about 47 s in total, the LLM steps take about 38 s (appraisal about 30 s plus extraction about 8 s, roughly 80%). Everything else takes about 3 to 5 s: verification, proposal, risk gate, order and a fill of about 1 s.

## 2. Price drift during the latency (filled tips)

The reference is the 1-minute bar at the post minute: its open, or the previous close. The comparison point is our fill. For share fills that is the fill price; for option fills it is the underlying bar at the fill minute. R is the underlying stop distance in the managed position (`config.risk`).

| measure | n | median | p75 | p90 | worse > 1% / > 0.5% | worse > 0.25R / > 0.1R | better |
|---|---|---|---|---|---|---|---|
| underlying, post -> our fill (%) | 51 | +0.04% | +0.15% | +0.49% | 2 / 5 | — | 17 |
| underlying, post -> our fill (R) | 51 | +0.010R | +0.024R | +0.10R | — | 1 / 6 | 17 |
| shares, source's stated price -> our fill | 8 | +0.28% | +0.72% | +0.90% | 1 / 3 | 0 / 2 | 3 |
| same, in R | 8 | +0.07R | +0.10R | +0.13R | — | | |
| option premium, contract's print at post -> our fill | 22 | 0.0% | +1.9% | +4.5% | 8 >1%, 3 >5% | n/a | 9 |
| option premium, source's stated price -> our fill | 23 | +0.5% | +4.5% | +7.1% | 11 >1% | n/a | 10 |

* The cost of our own latency is small. On the 27 share fills under 1 h, the drift from post to fill totals **$75.7**: $2.80 per trade, or 0.21% of notional, including the half-spread we pay by buying at the ask. For comparison, the closed Practice positions netted about -$770.
* The worst cases are fast movers in the first minutes: VSH at 09:33 (+2.2%, 0.14R), VKTX (+1.5%, 0.34R, the only case above 0.25R), ENOV (+0.83%, 0.13R) and JELD (+0.79%).
* Option premium drift is roughly 10 to 30 times the underlying drift (delta leverage on cheap contracts). In 11 of 23 option fills we paid more than 1% above the source's price. Most of that gap was already there when the message was posted (the source's print vs the contract's print at post time). Some source prices are averages ("NEW AVG .56", "AVG 2.41"), so those comparisons are not latency.
* Data-quality flag: three sim option fills landed far below the limit and the decision ask. MRNA 165C filled at 0.75 against an ask of 2.01; AAOI at 2.90 against a 3.30 limit; DAL at 1.56 against a 1.76 limit. MRNA's +$115 "win" rests on that fill.
  * Re-mark (W1.4, 2026-10-03; books not rewritten): all three were priced on an OPRA band that a stale chart print
    had recentred while it kept `source="opra"`, which E17-01 (v0.8.11, 2026-09-17) fixed. Re-marked on the live
    NBBO: MRNA would have rested unfilled (limit 1.95 under a 1.90 / 2.00 band), so drop it from the results. DAL
    fills at about 1.76 instead of 1.56 (-$80 on 4 contracts). AAOI fills at the limit, 3.30 at most, instead of 2.90
    (up to -$80 on 2 contracts). Record and residual fix: PLATFORM-RULES 2026-10-03.

## 3. Time of day

**Arrivals (weekday, ET hour, tips-mode sources since onboarding):**

| ET hour | raw msgs | signals | opens | proposals | filled |
|---|---|---|---|---|---|
| 08 | 9 | 2 | 1 | 0 | 0 |
| 09 | 411 | 467 | 304 | 95 | 6 |
| 10 | 415 | 215 | 105 | 33 | 11 |
| 11 | 291 | 137 | 84 | 24 | 7 |
| 12 | 230 | 122 | 66 | 22 | 9 |
| 13 | 172 | 87 | 39 | 12 | 5 |
| 14 | 194 | 107 | 57 | 29 | 11 |
| 15 | 244 | 153 | 85 | 25 | 3 |
| 16-23 | 135 | 47 | 30 | 0 | 0 |
| 00-04 | 15 | 4 | 4 | 0 | 0 |

The 15-minute buckets around the open break down as follows:

* 09:00-09:14: 8 signals.
* **09:15-09:29: 234 signals, 212 "opens", 72 proposals, 0 fills.** Almost all of these are eva's pre-bell level map. One post becomes 10 to 12 "sibling branches", and the analyst skips them all as conditional maps.
* 09:30-09:44: 142 signals, 10 proposals, 2 fills.
* 09:45-09:59: 83 signals, 13 proposals, 4 fills.

Buckets across the whole sample (signals):

| bucket | signals | opens |
|---|---|---|
| RTH 09:45-16:00 | 904 | 480 |
| premarket (to 09:30) | 245 | 215 |
| open 09:30-09:45 | 142 | 47 |
| weekend | 33 | 28 |
| after-hours | 27 | 14 |
| overnight | 23 | 19 |

Out-of-hours posts never become proposals, except the 09-14 backlog.

**Outcomes by entry time (Practice, closed managed positions):**

| entry window (ET) | n | wins | total $ | mean $ | mean % of cost | shares mean R (n) |
|---|---|---|---|---|---|---|
| 09:30-09:45 (first 15 min) | 2 | 2 | +148 | +74 | +21.5% | +1.79 (1) |
| 09:45-10:30 | 9 | 3 | +132 | +15 | +10.2% (MRNA 0.75 fill inflates this) | — |
| 10:30-12:00 | 11 | 2 | -842 | -77 | -19.0% | -0.35 (5) |
| 12:00-14:00 | 9 | 6 | -344 | -38 | -7.0% | +0.21 (7) |
| 14:00-16:00 | 16 | 7 | +134 | +8 | -1.6% | +0.29 (10) |
| after 09:45, all | 45 | 18 | -920 | -20 | -4.6% | +0.12 (22) |

The first-15-minute sample is two trades: MRNA shares (an overnight carry from a gateway outage) and HOOD 0DTE. It cannot support any claim about the open. The weak window is 10:30-12:00, which holds the September option bleeders (CCXI, AAOI, APLD, PURR).

## 4. Tips lost to timing

| cause | count | examples |
|---|---|---|
| Card waited for a human and expired (2 h TTL; 18 h overnight) | **24 expired** (20 of them marked `reviewRequired`); **0 of the 119 review-required cards were ever approved by a person** | 12 of the 24 expired because the source had already posted trim/close/update_stop. The median gap was about 22 min (0 to 106 min intraday): MSFT 505C trimmed after 12 min, INTC 120C 16 min, HOOD 140C 22 min, META 800C 33 min, INTC 130C closed after 54 min, GOOGL 345C 71 min |
| Gateway outage, delivered hours late | 1 outage, 33 messages, 1.5 to 4.8 h late (09-14 12:43 to 16:02 ET); a second batch on 09-29 17:14 to 17:54 (6 690 to 9 055 s, after hours) | MRNA (common-stock 14:46) arrived 2 h 27 min late, waited overnight and filled at 09:34 the next day. AMZN 260C (13 527 s) was skipped as "3h45m stale" |
| Queueing behind other messages (gateway) | 109 of 1 627 messages (6.7%) waited more than 60 s; 354 (22%) waited more than 10 s. **23 of 372 open signals waited > 60 s; 13 waited > 10 min** | 09-23 09:53-09:56: muggzone posts claimed 55 to 135 s late while each earlier message held the lane through its full appraisal |
| Order refused for quote age | 1 | AAPL 914 330C, "quote age 10.5s (max 10s)", 09-10 10:53 |
| Order refused, limit too far from mid | 1 | FRVO 25C, "limit 3.85 is 0.25 from mid 4.10 (max 0.20)" |
| Analyst skip citing chase / gap / stale | 13 proposals, mostly the *source's* chase, not ours | DELL 560C ("next-strike-up chase"), CRWD 245C, META 690C ("gapped"), QCOM ("stale chain spot") |
| Verification `price_deviation` (> 3% from claimed entry) | 12 signals | CIFR (19%), MRNA (18.6%), SMMT (8.4%). All are source recaps or stale prices; our ~9 s latency is not the cause |
| Verification `fresh` (content > 72 h old -> replayed) | 22 (plus 63 replayed in total) | Onboarding backfill, not live latency |
| `not_past_target`, premium target compared with the underlying | 18 failures; at least 11 real 0DTE/weekly option BTOs killed | "MSFT 505 0dte 1.00 sl .65 tp 1.30" was parked 09-28 with "live price 506.62 already at/past target 1.30". Also MU 990 (09-11), SPY 775, CRWV, QCOM, TSLA, SNOW, MRVL ×2, NVDA. The units guard (2026-09-08) still lets `instrument=unspecified` through |

## 5. Findings

1. **About 80% of post->fill time is LLM time, and most of it is the appraisal.** On opus-5-5 the chain is about 47 s: appraisal about 30 s, extraction about 8 s, everything else 3 to 5 s. Tool calls are about 0.1 s in total; each extra LLM turn adds 5 to 10 s.
2. **Moving the analyst to opus-5-5 (09-23) cut appraisal time in half** (61.5 s to 30.2 s median for filled tips) and post->fill from 84 s to 47 s. The p90 fell from 590 s to 62 s.
3. **Our latency costs little on the underlying.** The median is +0.04% (0.01R) and p90 +0.49% (0.10R); 1 of 51 fills was above 0.25R and 2 of 51 were more than 1% worse. The total on share fills was $76, about $2.80 per trade. Faster shares entries would gain only a few dollars per trade.
4. **Options are where seconds cost money.** The contract print moves 0% at the median, +1.9% at p75 and +4.5% at p90 between post and fill; 8 of 22 option fills were more than 1% worse and 3 were more than 5% worse. On the 0DTE and weekly lanes (muggzone, tt) the source's own trim often comes 10 to 30 min after the open. On these lanes 30 s is a measurable share of the move.
5. **The human-review path is dead on arrival.** 119 cards needed a human decision and none was approved by one. All 20 that the analyst did not skip expired; 12 of the 24 expired cards outlived the source's own trim or close (median about 22 min). Card push alerts exist only since 09-24 (4 sent, all 4 expired), and the TTL is 2 h, against trade horizons of 10 to 60 min.
6. **Head-of-line blocking in the gateway.** `discord_gateway.py` runs 2 global workers. It holds a per-channel lock across a synchronous `/api/ingest/manual` call (timeout 200 s) that includes the full appraisal. A BTO posted right after chatter therefore waits for the previous message's appraisal: 22% of messages waited more than 10 s and 6.7% more than 60 s. In the 09-23 09:53 burst, claims ran 55 to 135 s late. Filled tips were mostly spared (p90 1 s), but 23 of 372 opens waited more than 60 s.
7. **The single biggest delay was an outage, not latency.** On 09-14 the gateway went quiet from 12:43 to 16:02 ET, so 33 messages arrived 1.5 to 4.8 h late. One of them became the MRNA overnight fill. `TipIntakeStalled` fired 59 times, 40 of them during RTH weekdays.
8. **Host clock drift.** `claimedAt - postedAt` drifted about 1 s/day, from -2.4 s on 09-09 to -10.5 s on 09-21, then reset. The host clock was running behind Discord. This distorts every age check: the quote-age guard is 10 s, and one AAPL order was refused at 10.5 s on 09-10. It also distorts latency numbers measured before 09-22.
9. **Pre-market is noise for entries.** 234 signals land between 09:15 and 09:29 (one eva level map fans into 10 to 12 branches). They produce 72 proposals and 0 fills. The verdict is inherited, so it costs one appraisal per post, but every branch still creates a proposal row and a rejection.
10. **There is no evidence yet about the open.** Two closed entries fall in the first 15 minutes (both winners). After 09:45 the record is 45 trades, -$920, with 10:30-12:00 the worst window (-$842 over 11). The window effect is confounded with the September option-bleed era.
11. **A `not_past_target` units bug still kills option BTOs** when `instrument` is "unspecified". At least 11 real priced 0DTE BTOs were dismissed, expired or parked against a premium target; the latest is MSFT 505C on 09-28.
12. **Entries are marketable limits at the ask.** 49 of 51 filled within about 3.5 s. The two slow fills were ACHR contracts priced at the source's price, below the ask; they rested 19 and 58 min, and one AAL order was cancelled. ENOV shows the trade-off: the analyst said ≤18.16, the quote moved during the 20 s appraisal, and the order went at the 18.21 ask.

## 6. Improvement options

| # | option | expected impact | risk / notes |
|---|---|---|---|
| A | **Release the gateway's per-channel lock after extraction**, or make `/api/ingest/manual` return once the signal is recorded and run the appraisal asynchronously. Raise the worker count from 2 to 4-6. | Removes the queueing tail: 23 opens waited more than 60 s and 13 waited more than 10 min, about 6% of opens. Small effect on the median, large effect on p90 during bursts. | Ordering guarantees (open before close) must stay per channel at the *extraction* step. The appraisal can run out of order. |
| B | **Fast lane for clear, priced BTOs**: explicit ticker, strike, expiry and price, an `opens_position` verdict, and a source with earned auto. Use a deterministic pre-check: feasibility, a fill band ≤1.15× the source price, spread, budget. Enter on that, and run the full appraisal as a follow-up that can exit or disarm. | Saves the appraisal, about 30 s (median post->fill about 47 s down to about 15 s). On shares that is worth about $1 to 2 per trade; on options it is about half the 0 to 4.5% premium drift (p50 to p90). Rough value: 1 to 2% of premium on about half the option fills. | A take costs more than a skip because the analyst does real work there: risk budget, R3 escalation, hedges. Of 222 opus-5 appraisals, 158 were skips, so the fast lane would buy many trades the analyst rejects. Validate it as a **shadow lane first**: book the fast-lane decision beside the analyst's and compare. |
| C | **Run extraction and the market-data prefetch in parallel.** Prefetch the quote, chain and positions for the extracted ticker before the appraisal starts, and seed the analyst prompt with them. | The analyst currently spends 3 to 4 turns fetching (median 5 to 6 s before its first tool call). Seeding could cut 1 to 2 turns, about 8 to 15 s off the appraisal. | Low risk; needs care with the frozen-replay context manifest. |
| D | **A smaller or lower-effort model, or a skip-classifier, for the first pass.** Use a cheap gate (Haiku/Sonnet, about 3 to 5 s) that drops recaps, maps and commentary. Only opens reach Opus. | Skips are about 70% of appraisals, so latency mostly comes back on queued messages (option A) plus cost. Takes keep Opus. | Paid-model A/B pending (the cost package already notes the Sonnet-extraction A/B). |
| E | **Entry order: a marketable limit with a fill band referenced to the *source* price**, for example ask ≤ min(source × 1.10, decision ask + 1 tick). Cancel after N seconds. Do not use market orders. | Prevents paying more than 5% over the source price (3 of 22 option fills). The current ask-limit already fills about 1 s, and resting at the source price strands trades (the two ACHR cases). | Market orders on thin options are worse. Keep the reduce-only exits as they are. |
| F | **Pre-market handling**: collapse a multi-branch level-map post into one parked "watch map". Do not create per-branch proposal rows. Optionally arm level touches after 09:30 instead of "now" decisions. | Cuts 72 junk proposals and their journal noise; frees the 09:25 queue just before the open. | Arming from maps is new behaviour and must start in shadow. |
| G | **Card alerts and TTL by lane**: push at creation (already in place since 09-24), but set the TTL to about 15 to 20 min for 0DTE/weekly and 2 h for swings. Auto-expire on the source's trim/close (already in place). Add a one-tap approve from the push. For Practice under unattended mode, decide automatically instead of waiting. | 0 of 119 human cards were approved, so the honest choice is either to auto-decide in Practice or to make the cards actionable within minutes. Expected effect: the 20 expired would-be trades either become measured trades or vanish quickly. | A live book must stay human-approved (hard rule). |
| H | **Fix the clock**: enable Windows time sync (w32tm, hourly) and journal a skew check at startup and each morning. | Removes up to 10 s of false age on the 10 s quote-age guard and corrects latency metrics. | Trivial; no trading change. |
| I | **Fix the `not_past_target` units guard** for `instrument=unspecified` when a strike and premium are present. | Recovers about 1 to 2 real option BTOs per week (11+ since onboarding). | It is a verification bug, not a timing knob; needs a test using the MSFT 505C message. |
| J | **Intake liveness**: page when the gateway is idle for more than 3 min during RTH. The 09-14 outage lasted 3.3 h before recovery. | Each outage-hour during RTH delays about 30 messages. | Already partly built (`TipIntakeStalled`); the alerting lacks urgency. |

Suggested order: H, I, A (cheap, no trading-rule change), then C, then G (Practice auto-decide or short TTL), then B as a shadow-first experiment with predefined criteria. Leave the entry rules alone without a cost-aware cohort (`TipEntryStudy` policy).
