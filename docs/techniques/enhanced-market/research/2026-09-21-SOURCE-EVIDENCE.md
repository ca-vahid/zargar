# Source to plan, 2026-09-21: all 21 research rows, and what stopped each one

Order-free research. Nothing here armed, traded or could have: every row's origin is `scenario:*`, which
`PlanRunner.arm` refuses by construction. Compiled from `technique_source_candidates`, the scenario and
extraction artifacts and the stored 1-minute bars. No paid model call was made to produce it.

## The two notes are kept apart

| note | author | kind | posted (UTC) | evidence the app had | usable at |
|---|---|---|---|---|---|
| `f42af4852d3d446d9ca8b193b7adede3` | EnhancedMarket (the method's author) | video, 659 s | 13:02:18 | **transcript only** | 13:15:38 |
| `345a385de5fd4c66a75dda4f1413d396` | EvaPanda | text post, 935 chars | 13:20:27 | the post's text | 13:22:48 |

The video note's two images are a Periscope thumbnail and a TikTok thumbnail, not chart screenshots. The
author spent the broadcast drawing on charts the app never received, which is the single largest reason
his ideas produced no geometry. His public testimonials say nothing about his own realised results and
are not treated as evidence of anything here.

One fact governs all 18 continuation rows: each was decided at 09:30:53 ET on **zero closed bars**
(`barsIntegrity.bars = 0`) and never re-decided.

## The 18 source-continuation rows

Levels marked *author* are numbers the author actually stated. Every stop is app-derived: **no author
supplied a stop anywhere**, and none was invented (`stopNote: "the author stated no stop - unknown,
never invented"`).

| # | symbol | author | stated condition | author level / targets | app geometry (entry / stop / targets, R:R) | outcome | class |
|---|---|---|---|---|---|---|---|
| 1 | SPX | Eva | reject or fail 7680 | 7700 / 7665… | none | held | symbol not in the tradable universe |
| 2 | SPX | Eva | above 7700 | 7700 / 7725… | none | held | symbol not in the tradable universe |
| 3 | (MRNA) | EM | break last week's high ~196 | 196 / none | none | held | **evidence named AMD, not MRNA** - see below |
| 4 | AAPL | EM | "break the high" | none | none | held | chart geometry the app never received |
| 5 | AMZN | EM | "break through resistance zone" | none | none | held | chart geometry the app never received |
| 6 | AMZN | Eva | above 255 | 255 / 257, 260 | 255.19 / 252.51 / 256.23, 257.14, 257.79 — **R:R 0.97** | refused | failed R2 |
| 7 | ARM | Eva | above 291 | 291 / 300 | none (saved plan's longs sit at 268.15 / 266.87) | held | incompatible saved plan |
| 8 | GOOGL | Eva | "needs to get bid up" | none | none | held | **no numeric level was ever stated** |
| 9 | META | Eva | above 682 | 682 / 694, 700 | 682.95 / 657.50 / 685.83, 688.35, 690.15 — **R:R 0.28** | refused | failed R2 **and** the 3% stop cap (3.7%) |
| 10 | MU | Eva | above 1050 | 1050 / 1080… | none (saved plan's long sits at 1016.44) | held | incompatible saved plan |
| 11 | NFLX | EM | "continuation out of consolidation" | none | none | held | chart geometry the app never received |
| 12 | NVDA | Eva | above 225 | 225 / 230 | 224.56 / 218.54 / 229.05, 233.54, 238.03 — **R:R 2.24** | refused | failed R2 |
| 13 | QQQ | EM | hold the gap-up at 728 | 728 / 729 | none (plan triggers 0.86% and 0.90% away, outside the 0.5% region) | held | incompatible saved plan |
| 14 | SMCI | EM | "break through resistance" | none | none | held | chart geometry the app never received |
| 15 | SNDK | EM | "break through the level" | none | none | held | chart geometry the app never received |
| 16 | SPY | EM | hold through 766 | 766 / 769 | none | held | no same-day plan existed |
| 17 | TSLA | Eva | above 374 | 374 / 382, 389, 400 | 374.12 / 362.63 / 381.60, 389.08, 396.57 — **R:R 1.95** | refused | failed R2 **and** the 3% stop cap (3.1%) |
| 18 | TSLA | EM | "break the previous high" | none | none | held | chart geometry the app never received |

Rows 4, 5, 11, 14, 15 and 18 are the author pointing at a line on his screen. The app's own wording is
"the author gave no numeric level", which is literally true; the number existed, on a chart we never saw.
Row 8 is the one case where no level existed at all, in a text post with no chart.

**Refusal tally.** Failed R2 five (AMZN, META, NVDA, TSLA, and MU's requalification) · failed the stop cap
one, plus two more that failed it alongside R2 · chart geometry unavailable six · incompatible saved plan
four · no numeric level one · symbol outside the universe two · symbol conflict one · no author target one.
**Expired horizon: none.**

## The 3 requalification rows

| symbol | entry (fresh break) | stop | targets | disposition | reason |
|---|---:|---:|---|---|---|
| MU | 1064.49 (09:44, confirmed 09:48) | 1035.21 | 1080, 1100, 1125, 1150 (author's own) | refused | R:R 2.07 to 1125, below 3 |
| SMCI | 41.13 (09:42, confirmed 09:46) | 39.80 | none stated | refused | stop 3.23% wider than the 3.0% cap |
| SNDK | 1812.00 (09:38, confirmed 09:42) | 1776.08 | none stated | held | no author target beyond the entry - none invented |

## The AMD / MRNA hold, and the one-word fix

The row was held as `evidence_names_AMD_not_MRNA`. The transcript's topic turns between `[4:37]` and
`[4:43]`; the numbers 160 and 196 are spoken at `[4:54]`, inside the Moderna passage, and AMD's only
number, 584, is at `[4:27]`, six lines earlier and outside the selected window.

**The span the extractor chose was correct.** What failed was the label on it: the transcriber wrote
**"maderna"**, which matched neither the ticker pattern nor the alias `moderna`, so the locator's
carry-forward rule ("a speaker stays on a chart until he names the next one") kept AMD's label across the
whole passage. `symbolSeen` was false, so the hold was also *correct under the rule as written* - the app
refused to resolve a ticker its evidence never verifiably named.

The fix is one alias. `ALIASES` already carries transcription variants, not just company names ("in video"
for NVDA, "app loving" for APP), and now carries "maderna" for MRNA. The real transcript lines are pinned
as a fixture in `tests/test_em_source_topic_switch.py`, including the case that must still be refused: a
ticker the evidence never names is still never inferred. The span logic is untouched.

Even resolved, this row would have produced nothing: the day's MRNA plan had **zero valid triggers** and
its longs sat at 150-160, nowhere near 196.

## Case studies, including the ones that did not work

Session tape from stored 1-minute exchange bars, 09:30-15:59 ET.

| symbol | open | high (time) | low (time) | close | author level reached? | first author target reached? |
|---|---:|---|---|---:|---|---|
| META | 680.01 | **753.00 (15:34)** | 679.60 | 741.07 | yes, first minute | **yes, 694 at 09:31; 700 at 09:33** |
| AMZN | 256.29 | 259.49 (15:24) | 253.60 (09:48) | 258.46 | opened above 255 | 257 at 10:11; **260 never** |
| SMCI | 40.63 | 41.72 (13:24) | 40.00 (09:38) | 41.19 | no level stated | n/a |
| TSLA | 371.64 | 378.36 (10:32) | 371.07 | 375.25 | yes, first minute | **382 never** |
| MU | 1044.99 | 1064.49 (09:44) | 1030.68 (10:13) | 1043.32 | yes, 09:32 | **1080 never** |
| SNDK | 1825.67 | 1834.49 (09:30) | 1737.01 (13:27) | 1766.08 | no level stated | faded all day |

**META is the expensive-looking one and the most carefully stated.** Our candidate's whole target ladder
topped out at 690.15, below the author's first target of 694, and its stop sat 25.46 points away - 3.7% of
entry - which is what made the reward:risk 0.28. The stop is the defect, not the targets. The session high
of 753 is **not** evidence that our alternative would have earned that move: no order existed, no fill
existed, and a single path is not a distribution. It also belongs to EvaPanda, not to the method's author,
whose own recorded view of META that morning was a veto: "a little iffy, nothing really there".

**The counterexamples matter as much.** TSLA's first stated target was never reached. MU's first stated
target was never reached, and its requalified stop would have been breached at 10:10. SNDK fell 3.3% from
the open, and its requalified entry sat above the market from 09:31 onward. SMCI's 1.00x breakout volume
and 3.23% requalification stop were real gates doing their job. A rule tuned to admit META would have
admitted these too.

## What could not be established

- **Why the candidate builder saw no plan for GOOGL, NFLX and SPY.** SPY had an armed plan for this session,
  built two days earlier, yet the row recorded `plansSeen = 0`. The plan set evidently held only same-day
  runs; the mechanism is not visible in the stored rows and is not inferred here.
- **Whether the continuation rows were re-evaluated after the open.** All 18 show zero bars and identical
  created/updated stamps. A later pass would re-derive the same hold, so the table cannot distinguish
  "ran again and agreed" from "never ran again".
- **Any outcome for the 21 rows.** `outcomeProxy` is null on every one: nothing triggered, so nothing was
  scored. Every price above is a direct read of the stored bars, labelled as such, not a simulated fill.
- **Whether a TP2 measure would change the verdicts.** Every continuation refusal reads "to TP3", while
  production resolves the gate target to TP2 for fewer than three contracts. Recorded, not tested.
