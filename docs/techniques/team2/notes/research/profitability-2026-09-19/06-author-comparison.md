# 6. Source-grounded author comparison

For this pass I opened the source images themselves, not the capture index: `notes/x/images/2095671547184988332-1.jpg` (09-01),
`2095571390321865119-1.jpg`, `-2.jpg` and `2095599035113693522-1.jpg` (09-03), and the four charts in
`notes/research/week37-author-charts/` (09-09 plan, 09-09 PML flip, 09-10 follow-up, 09-11 trade). The 2026-09-18 post is NOT in
our captures: for it I rely on the other team's written reading (`2026-09-18-author-public-recap.md` in their checkout) and say so.
Trace output: `results/author_trace.txt` (`harness/author_trace.py`, baseline read on the same tape, real prints).

## Evidence classes used below

- **EXEC-TP**: documented execution with a timestamp AND a price. **None of the six has both.**
- **EXEC-T**: documented execution with a timestamped entry alert, no price.
- **EXEC-C**: documented execution by a broker card (contract, open P&L %, share time); the entry time and price are NOT shown.
- **AREA**: an illustrated entry area on a chart. **EDU**: a retrospective educational example. **CLAIM**: an unpriced performance claim.

A card's percentage lets the entry price be IMPLIED (card-minute prints / (1 + %)), if the card shows the whole position's open
P&L. He scales in and out, so this is an inference, labelled as such, and never treated as his fill.

## The comparisons

| Date | What the source shows | Class | Implied entry (inference) and where the contract traded at it | Our read at that time | Divergence, and how sure |
|---|---|---|---|---|---|
| 09-01 IWM 292P | Card +474.14%, shared 12:34. A 15m chart of the drop. No entry alert, time or price in the image | EXEC-C | $0.27 to $0.29; the contract traded there 10:25 to 10:49 and 11:38 to 12:02 | Same scenario (4, puts). We entered 09:50 (291P, -24.5%, candle stop 10:02) and 10:04 (-25.2%, premium stop 10:08), then the symbol's two-loss cap from 10:10 | If his entry was in either implied window we were ALREADY capped out. Attribution: exits plus the loss cap. Confidence LOW: his entry is not documented |
| 09-03 SPY 770C | Plan 08:45: "768.00 zone... room up to 775.29". Cards: 771C +25.00% at 09:52, 770C +26.14% at 10:24 (open P&L; the index says both were later stopped, the images do not show it). Alert "Getting the 768.00 retest now", then "I'm taking SPY 770c" (message time not visible; the inset chart ends about 10:56 to 11:00). Card +536.99% at 11:19 | EXEC-C (third attempt), with an untimed alert | $0.35 to $0.37; traded there 10:54 to 10:57 (and earlier, 10:07 to 10:52) | Same scenario (1, calls). 09:45: our pre-market-break setup's target was 768.00, the level it had just broken ("no room", F76); 09:56 `skip_target_collision`; 10:56 `skip_engulfing` (the wick he bought); no trade all day | Two signal-rule causes, both directly visible: our plan carried 768.00 as the upside target where his plan says 775.29, and the engulfing filter refused the 10:56 bar. Confidence MEDIUM-HIGH on the target, MEDIUM on the timing |
| 09-09 IWM 293P | Plan: "IWM broke 3 days of support... at our 293.43 zone", targets 291.19 then 289.98. 09:41 "I'm WATCHING the 293p"; then "I'm getting IWM 293p" (no visible time). Card +141.77% at 10:19; 292P card +65.28% at 10:57; "PML area will be my stop" | EXEC-C with a timed WATCH alert, untimed entry | $0.43 to $0.48; traded there 09:36 to 09:45 and 10:04 to 10:06 | Same scenario (4, puts). Our first contact was 09:56 and was refused: `skip_no_trade_zone` (293.08 is inside the pre-market range 292.62 to 294.82). Trades at 10:32 and 10:42 on re-planned near targets (-1.1%, +12.3%) | The first package said his entry "preceded our 09:45 gate". **Not supported**: 09:41 is a watch alert and the implied price also fits 09:45. What IS shown: his level is a three-day level (we carry none while C2 is off) and our first contact sat inside the no-trade zone. Confidence MEDIUM |
| 09-10 IWM 288P | "the 15 minute candle finally closed under our level. I'm watching those 288p now", then "I'm taking IWM 288p" (no visible time). Card +85.37% at 14:10; 14:12 "up 80%+ on these runners". Chart: seven wicks off 287.83 during the day | EXEC-C, untimed entry | $0.37 to $0.41; traded there 13:57 to 14:01 (and many earlier windows) | Same scenario (4). Our PM-break setup's target was 287.83, its own level: `skip_target_collision` from 13:40; 14:04 `skip_engulfing`; morning contacts inside the no-trade zone; no trade | Signal rules: target derivation (the broken level has no farther destination on our plan) and the engulfing filter. Confidence MEDIUM |
| 09-11 SPY 768C | 09:39 "SPY held the retest of our 764.47 zone... looking at 768 calls". **09:46 "I'm taking SPY 768c"** (timestamped). "Entered some calls... wanted another retest to add full position". 10:00 "Up 50% get those trims". Runners stopped on the 13 EMA break. P&L card +$801.66 for the day | EXEC-T (the only timestamped entry of the six); no price | First print of the 09:46 minute $0.40; the +50% alert at 10:00 implies $0.29 to $0.38 if it describes the whole position | Same scenario (1). 09:46 `skip_no_trade_zone`: the entry (765.27) was inside the pre-market range (758.17 to 766.53); no trade all day | Signal rule: the pre-market no-trade zone. Best-documented case. Confidence HIGH. Note his outcome: a partial position, +50% trim, "trade peaked around $1,100 with $800 realized" |
| 09-18 IWM | Educational recap chart; entry illustrated about 09:46 to 09:52; no contract, price or fill. NOT in our captures: read by the other team | AREA / EDU | none | Same scenario. No refusal recorded between 09:46 and 10:12; first contact 10:12, stopped 10:20 | A setup recognised late relative to an ILLUSTRATED area. It does not establish that he traded it. Confidence LOW |

Removed from the first package: a "2026-07-14 SPY 624C" row. SPY traded near 750 in July 2026; the year had been inferred wrongly.

## What the six rows do and do not show

- Direction and scenario agreed six times out of six. That is agreement with a PUBLISHED, SELECTED set; it is not a hit rate.
- In the five executions we did not hold his trade. The visible causes are our own rules: target derivation (twice), the pre-market
  no-trade zone (twice, once with a missing multi-day level), the engulfing filter (twice, as a second cause), and one case of
  exits plus the loss cap. None was caused by missing data or by execution.
- Real prints are consistent with what he posted: every card percentage maps to a price at which his contract really traded.
- **Not shown:** that those rules cost money overall. The refusals that blocked these five also blocked losing trades; the
  collision re-plan arm, which would admit the two collision cases, did not improve the training window (page 5; these dates are outside it). Six selected winners cannot rank rules.

## Standing limitation

His record holds 17 documented executions and they are all winners. Five losing trades are mentioned; none has an entry price, an
exit price, a size or a hold time; one red day (2026-09-17) exists and was not captured. No win rate, loss size or stop tolerance can
be estimated from it. **"His edge is selection" is therefore a hypothesis** (page 7 is designed to probe a codeable version of it),
alongside at least two others the evidence cannot separate: that his results are as published but not repeatable by rule, or that
the unpublished losers offset them.
