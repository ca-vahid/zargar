# EM source opportunities: September 14 reassessment

Prepared from the completed September 14 session, with SELECT-only runtime reads on September 15 UTC. This returns the review to source ideas and trading opportunities while the separate worker fixes proceed. No runtime changes, tests, paid analysis, backfills, or orders were performed.

**The strongest confirmed source miss today is failure to represent MSFT's stated long continuation. AAPL and MRNA did not reach their stated triggers. META remains an incompletely specified long scenario, not a proven missed trade.** This four-name cohort is materially different from the independent bounce/rejection trades that the EM Practice account actually executed.

## Evidence and timing

Read current `technique_method_notes`, `technique_runs`, `technique_armed`, selected `events`, `technique_source_artifacts`, and exchange-provenance `bars`. Each of AAPL, META, MRNA and MSFT has **390 distinct one-minute RTH bars**, 09:30 through 15:59 ET, with no alternate-source rows in that interval. These are historical stored bars; the table does not certify precisely when each bar reached the live engine. Bars identify minute starts. A decision using a minute's close can occur only after that minute ends, plus feed and processing delay.

The detailed interpretation of the eight morning recordings and three chart images comes from the earlier complete source reviews, linked below. Current database reads verify September 14's note metadata, extracted board, linked plan states and complete underlying path. Raw transcripts or database exports were not saved here.

The morning video note is `08c902695d5344eebe7bbd76ce9bd62f`, posted **09:02:38.750 ET**. Its legacy extraction records **09:15:35.234 ET**, and board completion records **09:15:45.413 ET**. Those timestamps support that the app had processed the morning narrative before the open. They do not establish the precise availability of every spoken field. The later backfilled transcript and extraction artifacts explicitly retain `availability=unknown` and null `completed_at`; their September 15 insertion time must not be backdated into a precise original availability claim.

| Refinement note | Source posted ET | Server stored ET | Conservative historical availability bound | Current status |
|---|---|---|---|---|
| MSFT `a5a519f64605447b8d4ef69d2145267e` | 09:20:50.645 | 09:20:48.234 | Use the later 09:20:50.645; clocks differ by about 2.4 sec | `new`, no extraction or board |
| AAPL `5852d8befaee4816a2f9ef8d5432fad2` | 09:21:05.640 | 09:23:21.018 | 09:23:21.018 | `new`, no extraction or board |
| MRNA `f1a2fa702a6e417b9d64ac8e2fdd673f` | 09:22:39.515 | 09:23:21.620 | 09:23:21.620 | `new`, no extraction or board |

These are conservative documentary bounds, not certified machine-action times. All three captions existed in the stored inbox before 09:30, although their exact numeric refinements did not drive a completed caption analysis.

## The four morning watches against the completed session

| Source scenario known before the open | What our selected plan actually represented | Full RTH evidence | Correct classification |
|---|---|---|---|
| **MSFT long above 498.97 toward 505+**. Morning video: relative strength and break Friday resistance. Caption supplies the exact entry/target condition. No author stop, contract or confirmation count. | Existing run `8979b99f5f7e47d8846c21d32661afa8`, created September 13, represented **short resistance rejection at 509.56**, stop 514.751. The source board called this ticker armed. | Open 497.50; first high above 498.97 at 09:30, first close above at 09:48; first 505 touch at 11:36; full-session high 509.93. | **Unrepresented source continuation with an observed underlying trigger-to-target sequence.** This is a research opportunity, not a proven profitable option trade. The later put has a separate thesis and outcome. |
| **AAPL long above 336.22**. Morning speech said 336; the caption precisely names 336.22. | Run `a47494fc4f494df2bf4cd2a5aefc72ba` genuinely armed a long breakout at **336.22** at about 09:15:41, before the later caption. Stop 330.5688 and targets 342.9444 / 349.6688 / 356.3932 are system-generated. | Open 334.83; session high **335.50**, low 331.34. End state `not_triggered`, no trade. | **Correct no-trigger outcome.** The missing caption analysis did not cause a missed 336.22 entry that day. The numeric match was independent agreement, not proof the caption generated the plan. |
| **MRNA long above 149.73**, wedge context with possible swing into Friday/next week. Caption confirms symbol and level. No author stop or exact target. | Run `102f48c30c4a4aa5a149701f4b0b5c4a` instead tested breakout **148.5613**, stop 144.01, rejected for 0.26R and 3.1% stop distance. No corresponding source plan armed. | Open 144.925; high **147.3399**, low 139.02. Neither author 149.73 nor our lower 148.5613 was touched. | **Different generated geometry, but no source trigger today.** Do not count the rejection as a lost profitable trade. Possible swing horizon remains a separate unsupported/mismatched lane. |
| **META long reclaim/break of double-top resistance after liquidity grab and higher lows; hold required.** No numerical trigger, stop or target in the stored morning speech. | Existing run `6cddde1e3ef74c1c8b10bbb587019b37`, created September 13, had only valid **short rejection 663.7467**. It was gap-voided; no trades. | Open 657.83; high 668.60, low 649.22. | **Source direction/setup unrepresented; executable eligibility unresolved.** Do not invent a long level from our opposite-direction plan or infer an author winner from the day's high. |

The source cohort has four watches: two definite numeric levels never reached, one numeric long with an observed underlying move that our selected plan did not represent, and one incomplete qualitative long. It is not four executable missed purchases. No numerical author stop was given for any of the four.

## MSFT shows why entry timing must be specified before scoring

| ET minute | Underlying observation | Interpretation available at that point |
|---|---|---|
| 09:30 | O 497.50, H 499.10, L 496.73, C 498.03 | A touch/break policy could trigger, but the minute closes back below 498.97. A close-confirmed policy has no entry yet. Intraminute order is not recoverable from OHLC. |
| 09:31 | H 499.80, L 496.28, C 496.84 | Another excursion above the level reverses. Simply calling the first touch a successful long conceals early adverse movement. |
| 09:34 | L **495.3416** | This low was known before the later 09:48 closing break. Whether it defines invalidation is a separately declared strategy decision, not an author instruction. |
| 09:47 | C 498.7495 | Still below the source level. |
| 09:48 | O 498.74, H 500.13, L 498.5815, C **499.99** | First completed one-minute close above 498.97. Its close becomes usable after 09:49 plus latency; **498.97 cannot be assigned as a guaranteed entry fill to a close-confirmed strategy**. |
| 09:50 onward | First small retest low 498.87; further retracements occur later | Break and hold versus break/retest are different sequences. A generic one-bar test cannot certify the intended confirmation or order execution. |
| Before 11:36 | Post-09:48 minimum **498.39**; twelve later minutes have low at/below 498.97; fresh closing re-crosses at 10:28 and 10:37 | An automatic stop at the source level or unconditional breakeven shift can be stopped out before the eventual target. Refire policy also changes results. |
| 11:36 | H 505.10 | First 505 touch, the caption's lower-bound target area. This is target-touch evidence, not proof an option exit was executable. |
| 11:37 | H 505.30, C 505.28 | The source chart's independently marked 505.18 was reached. The caption already supplied 505+; the chart line is not an invented separate author TP1 rule. |

At the 09:48 close, only about **$5.01** remains to 505, compared with **$6.03** at the stated 498.97 threshold. Confirmation therefore changes entry price and remaining reward as well as false-break exposure. For illustration only, pairing that close with the already observed 495.3416 opening low produces approximately **1.08R** before buffers and costs; using that low as a stop is not being recommended or attributed to the author. The example shows why a later entry cannot inherit a threshold-based R:R claim and why a generic 3R rejection requires reviewing the actual chosen geometry.

The independent system short entered one Sep 18 507.5 put at about 12:50:33, after the source long's 505 area had already been reached. The current plan projection records a 15:56 flatten at 6.50 versus 5.45 entry, gross +$105. Fee reconciliation belongs in the account report. This later short is not proof that the morning long thesis was contradicted while still active, and its P&L must not be used to score the long idea.

## What the author appears to intend, and what the scanner actually supplied

Across the earlier full reviews, the recurring author process is: identify consolidation near a meaningful prior-session or chart level; rank a few relative-strength/weakness names; wait for a specified break, reclaim or retest; preserve room to the next objective after a gap; and decline unsuitable contracts. Some days contain few or no complete setups. These principles do not imply buying every mentioned ticker.

The observed September 14 implementation took source **symbols**, then reused or generated a symmetric technical plan. In two of four selected names it called an independent **short reversal** coverage for a **long continuation**. In a third it rejected different geometry. In AAPL it genuinely represented the source level and correctly did nothing because price never arrived. That distinction answers more than a blanket statement that the scanner is too strict.

The older reviewed mornings provide concrete follow-up controls, without claiming their full-session outcomes were recomputed here:

- September 9 AAPL note `96243adc5b6446ab8a2c9f5eb3eeafc0`: source short toward approximately 312.8, while the reused short entered 305.67, already below that target. Same symbol/direction still was not the same trade.
- September 9 SPY, same note: a downside idea only **after an upward retest**, omitted from candidates inside a broad veto. Numeric retest level was absent, so this is a retained incomplete watch rather than a missed executable short.
- September 10 MSFT note `7e056663814c4038ba9bbefd0b2371c3`: author was **managing puts already held overnight**, potentially taking profit toward 487.31/484. This must not be counted as a fresh entry signal.
- September 11 note `8a7f85ba914f410d93098666f91e6020`: unidentified long 376 to 369 has conflicting geometry; a second ticker is uncertain. Keeping those parked is appropriate.
- September 4 MU note `d58ea44a8c16468081d0c6f369a85e4a`: author favored long through 968 toward about 989; our board instead rejected a rejection at 959.044. This is another source representation case to compare as of that day, not yet a proven profitable missed option.

## Work that can proceed now, without waiting for the worker PR

1. **Maintain this manual source ledger for the same frozen September 1-14 cohort.** Each row needs source ID, conservative available-at evidence, side, condition, explicit versus system-supplied geometry, horizon, and aligned/different/missing plan. Resolve actual known prices from the existing source record; park genuinely missing fields. The work needs no production source-table changes.
2. **Use MSFT as the first diagnostic comparison, and AAPL/MRNA as no-trigger controls.** Compare explicitly named first-touch, completed-close, and break/retest entry definitions on the same 498.97/505+ source idea. Include the early false excursions and all failed attempts. Do not select whichever variant wins this session.
3. **Complete a stop policy before reporting returns.** The author did not supply a stop. Freeze an independently justified structure rule and its buffers using information available at the decision time; reject candidates without defensible geometry. Keep source fields intact. This is a hypothesis to evaluate, not permission to weaken risk controls.
4. **Keep underlying diagnostics separate from executable option scoring.** Historical option bid/ask, source time, spread, contract selection, quantity, fees, expiry and capital availability must exist at each hypothetical decision. If absent, mark the row unscorable for options. Never substitute the best later option or equate a stock target touch to an option return.
5. **Keep META incomplete until contemporaneous chart evidence resolves the intended level.** A later winning chart or our short level cannot fill this gap. Confirming a historical source is research; live entry still needs its own eligibility and current quote evidence.
6. **Evaluate later, untouched sessions before any promotion.** These dates have already informed multiple hypotheses, so they are development evidence. Neither a fixed scanner nor this successful underlying MSFT path establishes a profitable strategy. The first operational deliverable is a trustworthy source-versus-system daily comparison, with no automatic orders from this research ledger.

The practical recommendation is to study a separately identified source continuation lane while preserving the existing independent bounce/rejection lane and normal execution constraints. Increasing the number of purchases is not the success criterion. Capturing the intended scenario, knowing why it was or was not eligible, and evaluating its executable return are.

## Related evidence

- [Full September 1-4 source review](C:/Cursor/zargar-codex/docs/techniques/enhanced-market/reviews/2026-09-14-morning-transcripts-early.md)
- [Full September 9-14 source review](C:/Cursor/zargar-codex/docs/techniques/enhanced-market/reviews/2026-09-14-morning-transcripts-late.md)
- [Three visually inspected source charts](C:/Cursor/zargar-codex/docs/techniques/enhanced-market/reviews/2026-09-14-chart-attachments-study.md)
- [Original author study](C:/Cursor/zargar-codex/docs/techniques/enhanced-market/reviews/2026-09-14-author-study.md)
- [Method evolution and scanner translation](C:/Cursor/zargar-codex/docs/techniques/enhanced-market/reviews/2026-09-14-method-evolution-audit.md)

Active documentation folder: `C:/Cursor/zargar-codex`, branch `codex/zargar-development`. Only this derived report was added. No recommendation in this report activates a method, changes execution, or authorizes the still-separate historical monetary repair.
