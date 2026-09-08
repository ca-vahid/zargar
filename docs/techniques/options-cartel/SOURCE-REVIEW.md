# Cross-version source review — 2026-09-06

All 21 full texts from the captured Sean archive index have been read, in
addition to the early focus-list excerpt S03. S01's eleven images were visually
inspected. This does not establish complete X account, image or video coverage.
IDs below resolve to direct archive/original links in SOURCES.md.

## Execution details added by this pass

**Gap handling (S12).** A gap beyond a planned breakout is not a market-order
invitation. Wait for price to retest the level; if it never does, wait for a
new daily setup. The entry kernel now has an explicit `allow_gap_retest` option
for retest-mode plans. Existing saved snapshots default false so their behavior
does not change implicitly. New gap-retest plans still need a complete candle,
actual level contact, relative volume, directional close and chase checks.

**Retest quality (S13).** The older detailed retest example asks for a hammer or
bullish engulfing candle and defending volume. Current close-location/volume
confirmation is not proof of that exact candlestick test. Add an explicit
source-profile reversal-pattern option and examples before claiming this path
fully reproduces S13. The latest main thread does not mandate that named filter.

**Bearish method (S21).** This is supported by a full directional description,
not merely one winning put example: SPY/QQQ below 8/21/50 EMAs; weak stocks below
the averages, negative change, relative volume >1; distribution/tight bases near
the lows; break beneath support on volume; puts; high of the daily breakdown
candle as stop; support levels for exits. QCOM 149 and MRVL illustrate the path.
The daily-high-at-entry interpretation mirrors the causal daily-low rule.

**Option selection (S15/S06).** Sean warns against delta below 0.25 in ordinary
option selection and against time decay. S06 describes occasional low-premium
short-dated exceptions and preferring shares when ADR/IV make options expensive.
Use absolute delta for puts as an explicit directional interpretation; do not
invent a positive put delta. No universal DTE range or premium price was supplied
by the inspected texts. Preflight now checks independently observed delta
freshness and the 0.25 absolute floor, with explicitly documented lower-threshold
exceptions. The 120-second observation-age limit is an engineering choice, not
Sean's number. A routine selection API now ranks refreshed candidates within
reviewed DTE/delta/price limits and reports search coverage. Its UI and actual
submission-time integration remain unfinished.

**Risk and exposure (S20/S23).** S20 specifies 1% risk per trade. S23 describes
0.5%, 1%, then 5% learning-stage risk with different performance targets. These
are dated frameworks, not an instruction to automatically escalate risk with
elapsed account age. Default preflight risk remains 1%; full option debit is
reserved as a conservative engineering risk basis. Performance targets and
claimed compounding outcomes are not validated expected returns.

**Taking profits in weaker conditions (S11/S13/S14/S21).** The first trim can
increase to 50% when follow-through is weak. These texts do not fully specify
how to redistribute the remaining target/runner fractions or mechanically
identify weak follow-through. A reviewed allocation can express it, but do not
silently change the September first-quarter rule or fabricate a switching rule.

**Reward/risk (S14).** The execution checklist says at least 1.5:1. It does not
identify whether that applies to the first target, final target, or an option
premium forecast. S23 contains other staged targets. Record the selected basis
when adding a rule; do not treat underlying R as a measured option return.

## Scanner evolution

### Image cross-check: a real conflict, not a resolved universal rule

S02's actual scanner image `HL2QABMWYAAXbHO.png` shows **Avg vol, 10D >500K**
and **ADR >2%**; the same thread's text says ADR >3%. It also confirms price >$3,
cap >$300M and EMA21/EMA50 below price. The current June text-based prototype
uses ADR >3% and last-completed-day volume as a disclosed earlier engineering
interpretation. It does **not** reproduce this scanner screenshot. The new
`june_2026_image` profile now explicitly implements the screenshot's 10-session
average-volume and ADR >2% criteria. The two remain selectable and snapshotted;
this resolves representation of the conflict, not which was the author's final
intended setting. Neither profile has been independently performance-calibrated.

S13's retest chart `GsZEdeJXUAA-D_w.jpg` is TSLA on 5m with a labeled 294.93
trigger and later retests. Its indicator legend shows `Vol (20)` and the
ADR/ATR table parameters `(20, 14)`. This supports those indicator lookbacks in
that example; it does not by itself establish the indicator's ADR formula or
the June scanner's ten-day liquidity average as a universal setting.

S05 images: `G_h4biNWMAETU6k.png` is a directional price/volume interpretation
matrix; `G_h4cK0WkAEcFPK.png` shows the volume MA rendered as an area/cloud.
The latter is the Style tab, so no period can be inferred from it. Local
reference images are under `.cache/options-cartel/media/`.

| Period / source | Specific differences |
|---|---|
| Mar 2025 S21 | Bearish price >$3, cap >$300M, volume >500K, relative volume >1, negative change, below 8/21/50. |
| Mar 2025 S23 | One checklist adds institutional ownership >20%; no exact measurement source specified. |
| Apr 2025 S20 | Explicit bullish/bearish relative-volume scans and EMA ordering. |
| May 2025 S14 | Relative volume >1 and price above 8/21/50. |
| Jun 2025 S13 | Market cap >$2B, current volume >1M, relative volume >1. |
| Jul 2025 S12 | Average volume >500K rather than explicitly current-day volume. |
| Aug–Oct 2025 S09–S11 | ADR >2%, usually price above 21/50; four or five focus names. |
| Nov 2025 S18 | Price above 8/21, ADR >2%, five to seven focus names. |
| May/Jun/Sep 2026 S04/S02/S01 | Current implementation profiles; differences retained in METHOD.md. |

The older screens must not be blended into a fictional timeless set of author
rules. The app currently implements the three 2026 profiles, supplemented by
explicitly labeled engineering measurements and documented older clarifications.

## Process and source cautions

- S16/S19 emphasize plan discipline and reviewing losing trades; no averaging
  down. An automatic system needs attribution for skipped, invalid and losing
  setups as much as for winners.
- S17 describes scaling only after three profitable months. This is context,
  not permission to enable live-auto or increase limits automatically.
- S23 describes the first and last market hours but also calls that one hour
  total. The arithmetic is inconsistent; do not invent a precise mandatory
  session schedule from the promotional time claims.
- S18 mentions ascending triangles. A separate measured ascending-triangle
  candidate is now available; its numerical definition remains uncalibrated.
- Screenshots of results, maximum contract marks and the public ledger's highest
  trim returns are not weighted realized P&L. No calibration/graduation uses them.

## Remaining source work

September video S24 has been reviewed after user CAPTCHA completion; inspect the
remaining linked videos, key older charts for exact entries/stops/contract dates, additional
public posts and related educators, and the remainder of Sean's ledger with
losses classified by method/date. Capture an explicit coverage boundary and
remaining access gaps; do not claim the entire X history was read.

S25's HIMS post and all four attachments now have an attribution review in
EXAMPLES.md. They contain different member contracts alongside Sean's chart,
so they cannot be collapsed into a single entry/exit record. S26 explicitly
separates Sean and Yousuf recap groups and includes a reported losing trade.

S06's eleven images are now inspected. TSLA's stated 29.20 exit conflicts with
44.30 in the images; QBTS's stated profit differs by 50 from the summary. MSTR's
row dates coincide with its March 28 contract expiry. These findings remain
source-version/exception evidence, not permission to alter the platform's
expiry floor or to fit the replay to the largest displayed return.

## June-thread image review — 2026-09-07

All fifteen S02 images are now inspected. The market-framework image explicitly
labels downside trading below the EMAs, while the accompanying text emphasizes
smaller size or abstention; neither supplies a numeric size multiplier. The
scanner confirms ADR 2% and 10-day average volume, preserving the already-recorded
text/image distinction. Its results table is volume-sorted and includes relative
volume values below one, so the later video's relative-volume gate must not be
silently imposed on this older scanner profile.

Four setup crops and the FLEX charts emphasize consolidation above the averages,
repeated resistance and quieter volume before expansion. AMKR images show the
intraday breakout, daily-candle stop and two Fibonacci targets. The intraday and
daily trigger annotations are not numerically identical; no explanation of the
price basis is supplied. The target graphic does not establish a repeatable
anchor-selection procedure. Do not merge the images into a precisely timed
execution record or infer universal Fibonacci settings from the illustration.

The opening dashboard remains a performance claim. It provides no trade-level
cash flows or independent verification of the displayed statistics.

## May-thread image review — 2026-09-07

All sixteen S04 images were inspected. A newly confirmed discrepancy requires a
separate scanner-image interpretation: the May text names stock EMA8/21 and
positive daily change, while `HHVjfvEXkAAYxRo.jpg` shows stock EMA21/50 and
10-day average volume >500K. Its results image includes negative-change NVDA and
MARA rows, consistent with the absence of an active positive-change filter.
ADR >2%, price >3 and capitalization >300M agree. Do not overwrite the existing
May text profile. A separately sourced `may_2026_image` profile is now implemented;
it retains May's written market-context interpretation and changes the stock
scanner filters shown in the image.

The examples show MU/SNDK flat-top bases, an AXTI wedge/retest, ARM pennant and
UAMY cup/handle context. The UAMY text's 12.61 level differs from the line labeled
12.23 in its trigger image; the adjacent base image labels 11.98. SNDK's daily
entry image labels 287.73, its 5m trigger image 288.56, and its stop/management
images 288.19. These cannot be silently combined into one exact entry/stop pair.

The management image clearly illustrates first strength trimming, then 8/21 EMA
trims and continued holding while the 50 EMA has not broken. It does not prove
a final realized return for the remaining portion. The retest example does not
quantify the claimed higher win rate; no expectancy is inferred from the picture.

## January volume-thread image review — 2026-09-07

All fourteen S05 images are now inspected. The volume cloud is a moving-average
area display. Its settings image shows Style, not the input lookback, so the
cloud period remains unverified. The diagrams and examples reinforce the sequence
of an initial high-volume move, quieter consolidation, and renewed volume on
continuation. A later increase in red volume is labeled as weakening momentum;
this is contextual evidence, not a quantified independent sell rule.

The USAR target image `G_hzetsXQAA9LKx.png` labels three profit targets and says
the remainder sells on a close below EMA8. Together with the text's quarter-size
trimming, this supports a distinct January example exit variant: three strength
quarters followed by an EMA8 quarter. It must not replace May's target/8/21/50
or June's two-target/8/21 profiles. The named `january_2026_volume` variant is now
implemented, with three reviewed target prices required.

The Fibonacci tool displays extension levels in that example, but the narrative
does not establish a general anchor-selection algorithm. USAR's trigger and stop
labels vary across the daily and intraday pictures, so they remain individual
annotations rather than a single reconstructed execution. The highlighted
risk/reward area and later price peak do not supply weighted realized fills.

## December strategy images — 2026-09-07 review

All fifteen S08 images were inspected in Chrome. The scanner visibly specifies
change >0.01%, stock EMA21/50, ADR2 and 10-day average volume >500K. This clarifies
the text's unspecified volume window and the units of its change filter; it is
not identical to a generic positive-change condition. The result list is sorted
by share volume and contains relative-volume values below one.

The FROG/ASTS/TSLA/STX examples show contraction, declining consolidation volume
and moving-average context; the MU sequence shows a breakout, initial stop and
three targets. Both the text and exit image support three quarter-position trims
followed by an EMA8 runner, corroborating the later January volume example's exit
shape. Do not merge slightly different price annotations between images into
exact broker fills. The performance screenshot is account-level reporting, not
a complete attributable strategy ledger. The video link remains unreviewed.

## Implemented source updates after the full-suite baseline

- Add a distinct May scanner-image profile: stock EMA21/50, ADR2, 10-session
  average volume and no positive-change gate. Keep May's written market-context
  interpretation and separately selected exit schedule explicit; do not relabel
  the existing May text profile or existing saved snapshots.
- Add the January image's three-reviewed-target/EMA8 quarter schedule in both
  the pure campaign builder and the plan form. Missing target prices must block
  preparation, and the source identity must be S05 rather than May or June.
- Verify profile-only API construction against the named factory. Current
  `CartelRules.image_defaults` expands image/video profiles, while May/June text
  defaults are set in `for_profile`. Partial raw rule input should not silently
  use another profile's base defaults. Preserve explicitly supplied values and
  fully serialized historical snapshots while adding parity tests.

These changes were implemented after the full-suite baseline ended. Profile-only
construction now uses the same default expansion as the named factory, preserving
explicit values. The screen/exit/preparation/collection selection passed 75 tests.
The new UI selections still require browser acceptance.

## Earlier focus-list entry source — 2026-09-07 review

S03 is now fully read: eight posts and five images. The GME daily chart marks
repeated resistance around 17.30; its intraday images explicitly label a 5m
close above the trigger and the breakout candle's low as the stop. The MRNA
image repeats that same process. This confirms `breakout_bar` as a distinct
historical source choice, rather than treating all author references to a
breakout-candle low as the completed daily low.

The historical charts display a volume indicator labeled with 20, but that
does not establish the period of S05's later cloud or imply a same-time-of-day
20-session baseline. Those are different measurements and remain separately
documented. No complete option contract, partial-fill ledger or outcome series
is provided by these entry illustrations.

## October 2025 image review (S09)

All fourteen images in the [October thread](https://threadreaderapp.com/thread/1977521570970014035.html)
were inspected. The scanner shows price >3 USD, cap >300M USD, Change >0.01%,
EMA21/50 below price, ten-day average volume >500K and ADR >2%. Its results
include relative volume below one; do not import September-video relative-volume
requirements into this version.

QBTS, OKLO, USAR and RKLB illustrate daily bases/flags, quieter consolidation
and expansion volume. MP's chart resistance annotation is 82.70, while the text
states 82.5; preserve that discrepancy. IONQ supplies daily and five-minute entry,
daily-low stop, and three-target illustrations. These are chart annotations,
not a complete option fill ledger or a rule for algorithmically choosing all
Fibonacci anchors. The account image is labeled Incomplete and does not establish
broker-verified methodology returns. No production rule was changed during the
ongoing full regression.

## September 2025 image review (S10)

All thirteen images from the [September 2025 thread](https://threadreaderapp.com/thread/1971976644362674547.html)
were inspected. Scanner filters show ten-day average volume >500K, price >3 USD,
cap >300M USD, Change >0.01%, ADR >2%, and price above EMA21/50. The separate
results screenshot explicitly sorts Volume 1 DAY descending. Filtering average
liquidity and ranking current-day volume are distinct; `screen.py::focus_list`
already uses dailyVolume for ordering. Several displayed relative volumes are
below one, so a universal relative-volume >1 requirement would contradict this
version.

TSLA, IONQ, OKLO and RUN illustrate tight daily bases and declining consolidation
volume. TSLA's five-minute chart explicitly labels its stop as the breakout day's
low and marks expansion volume. The final daily chart identifies three prior
resistance targets; it does not supply a complete option execution ledger. No
rule or test code was changed during the full-suite run.

## August 2025 image review (S11)

All fifteen images from the [August thread](https://threadreaderapp.com/thread/1954612413979873689.html)
were inspected. The scanner uses price >3 USD, cap >300M USD, EMA21/50 below
price, ten-day average volume >500K and ADR >2%. Its Change control is unset,
and the results contain negative daily changes. Do not add the positive-change
filter from September/October to this image version.

Examples cover JOBY, AAPL, QS and TSLA daily/weekly structure, followed by SMCI
entry, stop and Fibonacci targets. Although the text describes five-minute
confirmation, the SMCI intraday chart header is 15 minutes. Preserve both as
source evidence rather than relabeling the image. The 2025-created SMCI daily
illustration shows earlier history; its annotated prices alone cannot establish
contemporaneous option fills or adjustment conventions.

The text explicitly increases the first trim to 50% when markets fail to follow
through. It does not define a measurable follow-through threshold or fully
specify the remaining fractions for that exception. This is a discretionary
variant requiring review, not permission to invent an automatic trigger.

## July 2025 image review (S12)

All fifteen images from the [July thread](https://threadreaderapp.com/thread/1944548375669424513.html)
were inspected. The scanner shows thirty-day average volume >500K, price >3 USD,
cap >300M USD, Change >0.01% and EMA21/50 below price. No ADR filter is visible in
that screenshot; do not silently substitute a later ten-day/ADR-filtered profile.

COIN's intraday image explicitly labels entry on the first five-minute candle
close, with volume confirmation. Its daily stop illustration marks the day's
low, and its final chart marks three previous-resistance targets. These provide
additional support for closed-bar entry and planned risk without establishing
exact option fills. Chart levels vary between panels and remain separate evidence.

MSTR's retest illustration is dated October 2024, although reused in the July
2025 thread; it shows breakout, pullback/retest and continuation. It supports
the retest concept but does not define the app's numerical tolerance or expiry
window. Weekly cup/cup-and-handle annotations in MSTR/GOOGL are context examples;
a calibrated dedicated cup detector is not established by the current code.

## June 2025 image review (S13)

All fifteen images from the [June 2025 thread](https://threadreaderapp.com/thread/1929326825689223595.html)
were inspected. The scanner shows price >3 USD, cap >2B USD, daily volume >1M,
relative volume >1, Change >0.01%, and EMA8/21/50 below price. Average-volume
and ADR filters are not active in that screenshot. This materially differs from
later 300M/500K scan variants and must not be silently merged with them.

QBTS, TSLA, PLTR, HIMS and PONY illustrate daily/weekly bases and contractions.
The TSLA intraday panel explicitly labels a five-minute candle-close entry with
volume confirmation. A separate retest panel and day-low stop panel accompany
three prior-resistance targets. Entry annotations vary slightly between panels;
retain the source panel and timestamp for any numerical calibration instead of
collapsing them to one supposedly exact price. The screenshots are retrospective
illustrations, not a complete point-in-time universe or option execution ledger.

## May 2025 image review (S14)

All fourteen images from the [May 2025 thread](https://threadreaderapp.com/thread/1919903220274503838.html)
were inspected. The scanner shows price >3 USD, cap >300M USD, Change >0.01%,
relative volume >1, and EMA8/21/50 below price. No absolute-volume or ADR filter
is visible in that screenshot; do not import a later screenshot's thresholds
into this version without labeling the interpretation.

UBER's charts mark repeated resistance around the text's 86.6 trigger. PLTR's
intraday chart explicitly labels five-minute candle-close confirmation with high
volume; separate daily panels show a stop and three prior-resistance targets.
HIMS supplies a distinct retest-entry illustration with a lower stop. PONY and
OKLO illustrate compact bases and volume expansion. These examples support
closed-bar and retest concepts, but do not supply a full option-fill history or
numerical retest tolerance. The text's minimum reward/risk checklist remains a
separate source statement; retrospective price annotations are not proof of
achievable execution or weighted returns.

## Market adaptation and process threads (S15–S17)

The [March market-adaptation text](https://threadreaderapp.com/thread/1902168481807704139.html)
was checked alongside its account photograph. It distinguishes upside calls,
downside puts with limited exposure, and abstention during sideways conditions.
Its delta warning concerns values below 0.25; it does not establish a complete
contract-selection algorithm or justify treating the account photograph as
verified performance. The [February process thread](https://threadreaderapp.com/thread/2025358170734911980.html)
uses a historical loss-calendar image. The [January scaling thread](https://threadreaderapp.com/thread/2011214289596793275.html)
has no tweet-media images in the served archive. Neither adds an automatic
position-size escalation rule; their process guidance remains distinct from
fixed execution parameters.

## November 2025 image review (S18)

All twelve images from the [November thread](https://threadreaderapp.com/thread/1990160530255032607.html)
were inspected. The scanner uses EMA21/50 below price, ten-day average volume
>500K, ADR >2%, price >3 USD, cap >300M USD and Change >0.01%. The market diagram
uses 8/21 for long versus short/sit-out context. These are different roles for
stock filters and market averages.

The setup illustrations include ONDS trendline structure, OKLO's base, RKLB's
flat top, ASTS's wedge and NAMS resistance. They should not all be relabeled
ascending triangles merely because the text lists that setup family.

IONQ's management panel labels strength trimming, reduction below EMA8 and a
full remaining exit below EMA21. It does not quantify the first two allocations;
this image must not inherit an unrelated fixed-quarter schedule silently. Its
intraday entry/stop panel remains separate from the daily management illustration.
The aggregate profit-factor/win-rate screenshot lacks the complete trade history
needed for independent outcome verification.

## March bearish-strategy image review (S21)

All twelve images from the [March bearish thread](https://threadreaderapp.com/thread/1906420167015288953.html)
were inspected and cached locally (`GnT*`). The scanner shows price above 3,
capitalization starting at 300M, volume starting at 500K, relative volume above
one and negative change. Its EMA fields are 10/20/50 above price, distinct from
later 8/21/50 or 21/50 stock screens. NASDAQ/NYSE, primary listing and current
trading day are selected; symbol types include common stock, depositary receipts
and ETFs. Do not infer a finite upper bound from the slider's open-ended labels.

SMH, MRVL, ADBE and QCOM illustrate distribution, weak consolidations and support
breaks. The MRVL intraday and daily panels place the stop above entry and show
lower support targets, consistent with a downside trade expressed through puts.
Panel price annotations differ and remain separate evidence. The screenshots
do not establish exact option contracts, premiums or achieved weighted returns.
No execution rules were changed during the ongoing regression.

## Final indexed-archive media review (S22–S23)

All five images in the [March volume/process thread](https://threadreaderapp.com/thread/1904673946584113641.html)
were inspected: account summary, TSLA accumulation/distribution diagram, volume
crop, breakout crop and a short P&L-calendar excerpt. They illustrate the
price/volume interpretation but do not identify institutional counterparties
or supply a full fill ledger. The linked video offered through replies remains
unreviewed because no usable public URL was retrieved.

The [March scaling thread](https://threadreaderapp.com/thread/1903600212376948839.html)
contains one account-summary image, now inspected. It adds no numerical trade
entry/exit rule and does not independently validate the staged-risk growth claims.
The earlier distinction between authored risk examples and automatic escalation
remains in force.
