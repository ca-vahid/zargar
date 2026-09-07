# Source examples and attribution

These are source observations, not broker-verified executions or a performance
dataset. Unknown entries, allocations and exits remain unknown. Each attachment
must retain its own actor, contract and dates before it can join a replay case.

## S25 — HIMS, June 3, 2025

[Original Cartel post](https://x.com/TheOptionCartel/status/1929991503897866536).
Text and all four images inspected in Chrome on 2026-09-07. The text describes
a short swing holding period with July options and a move of stops to breakeven.

| Attachment | Observed evidence | Boundary |
|---|---|---|
| [1: Sean chart](https://x.com/TheOptionCartel/status/1929991503897866536/photo/1) | Daily HIMS chart. Sean annotation: July 18 $65 calls at 5.30; subsequent trim annotation at 9.60. | Original quantity, trim fraction, initial stop and final exit absent. Annotation times have no proven timezone. |
| [2: member record](https://x.com/TheOptionCartel/status/1929991503897866536/photo/2) | July 18, 2025 $60 call; one bought May 30 at 5.40, one sold June 3 at 9.51. | Different strike and entry date; not Sean's annotated trade. |
| [3: member result](https://x.com/TheOptionCartel/status/1929991503897866536/photo/3) | July 18 $65 call; closed June 3. | Member-specific execution; cannot fill gaps in Sean's allocations. |
| [4: member positions](https://x.com/TheOptionCartel/status/1929991503897866536/photo/4) | Both January 16, 2026 and July 18, 2025 $65 calls displayed. | Different expiries; position returns are not proof of complete realized cash flows. |

Do not combine these attachments into one trade, infer a default DTE from them,
or use the largest displayed return as campaign P&L. The source does not establish
whether breakeven here refers to option premium or underlying price.

## S26 — mixed-trader recap, May 29, 2024

[Cartel recap](https://x.com/TheOptionCartel/status/1795982831342027219) explicitly
groups AMZN, HOOD and losing RUN under Sean, and TSLA under Yousuf. The text reports
RUN at -43%, but supplies no complete contract or execution history. It establishes
that the account contains multiple traders' results and reported losses; it does
not establish a method expectancy or a default stop percentage. Text inspected
2026-09-07; no source-complete replay can be constructed from this recap alone.

## S06 — January 2, 2026 five-trade thread: image review

[Archived thread](https://threadreaderapp.com/thread/2007213167189885042.html).
All eleven linked images were inspected on 2026-09-07; local reference copies
are under `.cache/options-cartel/media/`. Chart axes are small, so exact intraday
prices/timestamps are taken only from legible annotations or the thread text.

| Case | Additional image evidence | Calibration boundary |
|---|---|---|
| HOOD | Summary row has leading date 05/07/2025 and close date 06/06/2025. Charts label an undercut/rally, wedge break, EMA recross, flag entry and later extension. | Text supplies 48.80 trigger, 48.32 stop and 55/63 targets. Cropped row's leading date is interpreted as entry date; no time/timezone or fill quantities. |
| TSLA | Summary row has 09/11/2025 and 09/16/2025, entry 3.80 and exit 44.30. Chart labels contraction, a large wedge, tight daily setup and accumulation volume. | Thread text says exit 29.20, conflicting with both summary images. Neither value is silently chosen as execution truth. |
| RGTI | Row dates 09/12/2025–10/16/2025 match the text. Chart labels a broad cup/handle base and volume expansion. | Share expression is explicit in the text because of high ADR/IV; this does not define a universal IV threshold. |
| MSTR | Summary row shows 03/28/2025 for both dates; text names the March 28 $300 put. Chart labels distribution, a bear flag and a low-volume rebound. | This supports a same-day-expiry example, not routine 0DTE permission. Cartel's platform expiry gate remains distinct from the author's rare exception. |
| QBTS | Header summary shows close date 05/29/2025 and profit 59,550, versus 59,500 in text. Chart labels a broad base and low-volume consolidation. | The displayed profit discrepancy and absent partial quantities prevent exact realized-P&L reconstruction. |

Summary images label a net ROI that does not equal a simple entry-to-final-exit
ratio. Partial exits could explain a difference, but the required cash flows are
not shown. These values are author-reported outcomes, not independently verified
or substitutes for a weighted fill ledger. The top-winner selection also cannot
establish performance over all trades.

## Requirements for the calibration corpus

Preserve source post and attachment, attributed trader, symbol, full contract,
entry/exit timestamps and their timezone confidence, observed prices, quantities,
fees, underlying trigger/stop and every unknown. Classify an item as an alert,
chart annotation, reported fill, position mark or recap. Only complete matching
cash flows can support weighted realized returns. Annotated setup examples may
test geometry while remaining unscorable for execution returns.
