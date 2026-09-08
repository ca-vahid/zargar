# Team2 author study for independent daily review

Studied 2026-09-08. This is Codex's source-based understanding for the dedicated Team2 review task. It supplements the team's existing METHOD and judgement log; it does not change the trading method or authorize parameter changes.

## Main conclusion

Casey's method is discretionary intraday trading of movement between support/resistance areas, using EMA structure and simple chart patterns to choose direction, time entries near invalidation, and manage a portion of the move. The strongest repeatedly taught setup is a confirmed level break followed by an early pullback into the 2-minute EMA trend. His full practice also includes range reversals, level retests, bases, deeper EMA entries, re-entries and adds.

The public material explains the framework well. It does not specify a complete mechanical algorithm for every decision. We can assess fidelity to that framework, but should not call our fixed thresholds an exact reproduction of his discretion. His [September 7 statement on discretion](https://x.com/Team2Trading/status/2097048056701354167) explicitly emphasizes experience and judgment.

## Evidence and coverage

Read all **49 existing X source-note files**, covering 2022–2026, under `notes/x/` (excluding the PARTIAL inventory); read both full captured transcripts (2022 overview, 2023 interview). Their contents were inspected in this task, not merely their summaries in METHOD.md. The notes are historical captures, not proof that every original post remains unchanged today.

Fresh browser research verified the public profile and September 2026 posts, the July 2026 entry thread through its public unroll, and five older threads previously listed as uncaptured. Independently inspected **16 chart images** through their public source URLs, including all four September 7 teaching slides. New-source summaries and an image ledger are in [the research evidence note](notes/research/2026-09-08-author-study-evidence.md).

This is a comprehensive study of the available method material, **not an exhaustive archive of roughly 11,900 posts**, every reply, or private Discord activity. X's unauthenticated profile exposes only a short slice, and targeted search requires login. One known historical post remains unavailable. A search-index reference to a newer “15 minute follow up” remains unverified at the original-post level and is not promoted to a rule here. No paid material was required for the core framework.

Evidence labels used below:

- **Explicit:** directly stated by Casey in a source, with its context retained.
- **Demonstrated:** visible in an author-posted chart/recap; establishes an example, not a universal rule or audited result.
- **Interpretation:** our synthesis or implementation choice; needs independent validation.
- **Unresolved:** sources do not establish a precise answer, or their statements vary.

## 1. His objective and daily operating rhythm

He seeks a manageable portion of a trend, not every move or the exact top/bottom. The work starts with a map before the session: the prior day's boundaries, the pre-market range and further targets. Bias follows the price reaction to those areas. He waits for confluence, enters near a defined stop, takes profits, and reassesses after failures. [March 2025 objective](https://x.com/Team2Trading/status/1899265720011411841)

The current beginner prescription is one or two high-quality trades, small size and modest realized wins, followed by gradual sizing and runners after consistency develops. It is a learning progression, not proof that Casey himself always stops after exactly two trades. The 2023 interview describes two or three opportunities, sometimes five; the January 2025 thread describes an average of one to three. [September 7 starter guide](https://x.com/Team2Trading/status/2097014383394394431), [January 2025 thread](https://x.com/Team2Trading/status/1885114365117902957)

Review implication: missed moves and ordinary losses are not sufficient reasons to change the system. His September 6 post emphasizes repeating a small number of familiar setups and avoiding wholesale changes or abrupt sizing increases after a loss. This supports review and learning without requiring daily retuning. [Consistency post](https://x.com/Team2Trading/status/2096686674894062075)

## 2. Chart preparation and levels

**Explicit:** PDH/PDL are the previous regular trading session's high/low. PMH/PML are the highest/lowest prices from 04:00 to 09:30 Eastern. PDH/PDL become zones; PMH/PML normally remain lines. [June 2025 definitions](https://x.com/Team2Trading/status/1936502368247644519)

The repeated zone recipe uses a 15-minute chart and connects the extreme wick to the following candle body. A January 2025 description instead says a nearby candle body. The visual examples support zones with actual width, not interchangeable single-price triggers. The source does not resolve all edge cases: last-bar extremes, several equal extremes, very large following bodies, or exactly which adjacent body he might select discretionarily. [Original zone lesson](https://x.com/Team2Trading/status/1588795600661008384), [January wording](https://x.com/Team2Trading/status/1885114365117902957)

**Explicit:** further targets come from prior areas of strong rejection or bounce. He can look back as far as needed, and also uses intraday support/resistance when inside larger zones. Large unobstructed gaps between zones are attractive; approaching the next zone requires caution. A target can become a new breakout/retest area if price accepts beyond it. [February 2023 zone ladder](https://x.com/Team2Trading/status/1626883007209693184), [August 2025 pivot explanation](https://x.com/Team2Trading/status/1954180176314786139)

**Interpretation:** an automatic pivot window and a fixed ten-session lookback approximate this process. They are not an author-specified target algorithm. No historical target found does not mean unlimited upside/downside is safe.

## 3. Bias and the four scenarios

| Reaction | Bias | Typical opportunity and boundary |
|---|---|---|
| Break and hold above PDH zone | Calls | Expansion toward the next resistance; buy supportive pullbacks |
| Reject PDH zone | Puts | Range reversal toward lower support; seek confirming weakness |
| Bounce from PDL zone | Calls | Range reversal toward higher resistance; seek confirming strength |
| Break and hold below PDL zone | Puts | Expansion toward the next support; sell-side trend pullbacks |

These are conditional scenarios, not a prediction fixed for the whole day. Scenarios 2/3 receive more caution; EMA changes, flags and pre-market breaks help confirm them. Price can transition from a support bounce to a PMH break and then a PDH breakout during the same session. [Four-scenario lesson](https://x.com/Team2Trading/status/1972033668953919542), [May 2025 sequence](https://x.com/Team2Trading/status/1923816972179079546)

**Inside days:** PMH/PML can identify the cleaner move within a wide prior-day range. Breaking PMH favors a move toward upper resistance; breaking PML favors a move toward lower support. The destination can become chop again, so a successful inside-day entry is not automatically permission to hold through PDH/PDL. [Inside-day example](https://x.com/Team2Trading/status/1794130747399581828)

**Gap days:** Casey explicitly watches for a 15-minute close outside the pre-market range and then a 2-minute 13-EMA pullback. PM levels also provide confirmation when located beyond the prior-day boundaries. Do not assume being above PDH alone establishes a clean entry if PM resistance still blocks the path. [Gap-day lesson](https://x.com/Team2Trading/status/1972731496307011990), [March 2026 context](https://x.com/Team2Trading/status/2030765372497076306)

## 4. EMA structure and momentum

**Explicit:** use 13, 48 and 200 EMAs on the 2-minute chart with extended hours enabled. In the strongest bullish structure, 13 is above 48 above 200, with price above them; bearish is the mirror. Closely intertwined, flat or repeatedly crossing averages warn of consolidation. Separation and orderly structure indicate momentum. [February 2026 EMA guide](https://x.com/Team2Trading/status/2020567514644922429), [October 2025 fan explanation](https://x.com/Team2Trading/status/1974585826370863535)

The 13 is the first pullback area in strong momentum. The 48 is the next area he watches during a deeper pullback or reduced momentum. The 200 is the broader directional reference. He describes levels and EMAs as confluence: a zone bounce alone can still meet EMA resistance; an EMA rejection alone can still meet zone support. [Lines of defense](https://x.com/Team2Trading/status/1916508324901912941), [Confluence explanation](https://x.com/Team2Trading/status/1899265720011411841)

**Interpretation:** fan width divided by ATR, exact tolerance bands and warm-up length are numerical translations. The author describes appearance and behavior, not a universal 0.60-ATR threshold. A newly developing reversal is distinct from an already fully aligned continuation trend; see the 200-EMA example below.

## 5. Confirmation, entry and setup families

**Explicit core sequence:** identify a meaningful level; wait for a 15-minute candle to close beyond it; then use the 2-minute chart for a pullback into the matching EMA trend. A wick through a level is not the same confirmation. The January lesson prefers the first or second pullback. The July lesson gives both bullish PMH and bearish PML examples. [January 2026](https://x.com/Team2Trading/status/2013059643099271321), [July 2026](https://x.com/Team2Trading/status/2081050829214372301)

The March confirmation lesson describes avoiding premature breakout entries and then buying lower-timeframe dips. It does not prescribe waiting for a second completed 15-minute candle after the confirming close. Nor does “body close” establish a minimum body ratio, ATR margin or requirement that the entire body lie beyond the level. Those would be additional conditions. [15-minute close lesson](https://x.com/Team2Trading/status/2028179533275463855)

| Family | Evidence | What must remain distinct |
|---|---|---|
| Confirmed break -> early EMA13 pullback | Explicit; repeated 2025–26 | The level establishes context; an EMA touch alone is insufficient |
| Broken-level retest | Explicit; PMH/PML and PDH/PDL examples | The broken level can be the entry and stop reference, especially with EMA confluence |
| Deeper EMA48 pullback | Explicit in 2022 video and 2025 EMA lessons; demonstrated IWM sequence | A stopped 13-EMA attempt need not invalidate the larger structure |
| Break and base | Demonstrated QQQ PMH and September SPY examples | A held base beyond a level need not print an exact EMA13 touch |
| Rejection/reversal -> 200-EMA break | Demonstrated SPY 671p example | Developing EMA cross and 200 break; full mature stack was not yet present at entry |
| Re-entry / trim then add | Explicit recaps and images | A new entry, a replenishment after a trim and holding a losing trade are different actions |

The [April 2026 PMH setup](https://x.com/Team2Trading/status/2045207389079757153) explicitly uses the level retest and a 2-minute close under PMH as its stop. The [2024 IWM explanation](https://x.com/Team2Trading/status/1810706353427771759) says he sometimes plays both the break and the retest. Earlier zone lessons teach several ways to trade a zone. Thus the later A+ pullback sequence is the best-defined core setup, but cannot be used to erase every other documented setup from his history.

## 6. Pullback quality, flags and remaining room

**Explicit:** bull/bear flags are continuation patterns that provide timing and confirmation. Do not treat a bull flag as evidence to short an uptrend, or a bear flag as evidence to buy a downtrend. The 2022 video favors an orderly drift into the EMA over a large opposing candle. [Flag lesson](https://x.com/Team2Trading/status/1693133239307944383), [2022 overview, 03:17–05:51](https://www.youtube.com/watch?v=xm8pWnaAZU4&t=197s)

He uses 15 minutes for levels, 5 minutes for flags/trend lines, and 2 minutes for EMA entries; newer examples prominently pair 15 and 2. Patterns are frequently described as additional confluence, not an invariant requiring an identified flag on every trade. [Timeframe division](https://x.com/Team2Trading/status/1964745964625027202)

**Important qualification:** early pullbacks are preferred, but the 2023 warning about a third pullback is specifically about chasing a mature move near resistance. It is not an explicit mechanical definition of every touch, reset or rejected attempt. January 2026 strengthens the early-entry preference; other charts show adds and several entries. Assess setup age, remaining distance to target and whether the structure reset, alongside any count. [Interview, 38:27–41:38](https://www.youtube.com/watch?v=7zRANikMiww&t=2307s)

## 7. Stops, profit-taking and re-entry

**Explicit principle:** enter close to the level/EMA that makes the setup valid, and exit when that premise fails. “Risk one candle” describes prompt structural invalidation; it is not a guaranteed option loss, a fixed dollar risk, or a guarantee that reward exceeds risk. Some posts say one candle, the August 31 discussion says one or two, and the PMH example precisely specifies a 2-minute close. [May entry/exit lesson](https://x.com/Team2Trading/status/1918781802334085517), [August stop discussion](https://x.com/Team2Trading/status/1961977205787107425)

The 2023 interview describes hard stops around 20% of premium. A newly recovered April 2023 review also states predetermined stops targeting losses at or below 20%. In March 2025 he reports actual losses between 20% and 40%, depending on speed of exit. Treat these as historical policy/realization evidence, not a timeless guaranteed 20% cap or proof that wider losses are desirable. [Interview, 16:06–16:41](https://www.youtube.com/watch?v=7zRANikMiww&t=966s), [April 2023 review](https://threadreaderapp.com/thread/1650038773173075970.html), [March 2025 results](https://x.com/Team2Trading/status/1900742551696761039)

**Explicit and demonstrated exit behavior:** take some gains on a new high/low push, scale out as price extends from EMA13, leave runners while the trend holds, and watch the next level as the destination. Images show +50%/+100% trims, sale when a contract moves ITM, and full discretionary sales before the ultimate target. Exact fractions and precedence are not specified as universal rules. [May profit-taking lesson](https://x.com/Team2Trading/status/1918781802334085517), [May 2023 scale-out teaching](https://threadreaderapp.com/thread/1660044148051968000.html), [Image evidence ledger](notes/research/2026-09-08-author-study-evidence.md)

**Explicit:** in the September SPY recap he stopped two attempts despite interim gains before participating in the larger upside move. The chart distinguishes Casey's roughly +500% sale from larger member cards. Do not credit him with the maximum advertised contract move or sum screenshots as realized returns. The example establishes persistence with a still-valid idea, not permission to ignore stops or remove daily risk limits. [Stop/re-entry explanation](https://x.com/Team2Trading/status/2095571390321865119), [Recap](https://x.com/Team2Trading/status/2095599035113693522)

## 8. Contracts, sizing and time of day

**Explicit:** the 2023 interview discusses SPY/QQQ 0DTE options. **Demonstrated:** recap cards show same-day contracts across SPY/QQQ/IWM, with several entry premiums around $0.20–$0.60. However, the evidence does not establish a universal exact premium band, a complete expiry selection policy, or a fixed one/two-strike OTM rule. QQQ 472p with underlying near 480 and SPY 505p near 522 demonstrate much greater strike distances. Premium, volatility and the intended move matter; the exact selection algorithm remains unresolved. [Interview](https://www.youtube.com/watch?v=7zRANikMiww), [QQQ example](https://x.com/Team2Trading/status/1905768108352250355), [SPY example](https://x.com/Team2Trading/status/1908549478438887528)

**Explicit sizing principle:** be more cautious in ranges and more willing to size in clean expansion. His sizing diagram labels full/small/no-trade areas when PMH/PML sit inside the PDH/PDL boundaries. The accompanying prose calls it a loose guide and acknowledges exceptions. It supplies neither account-risk percentages nor the fraction denoted by “small.” It also does not specify every ordering of overlapping gap-day ranges. [Sizing diagram](https://x.com/Team2Trading/status/1961977207825616952), [Risk-on/risk-off qualification](https://x.com/Team2Trading/status/1936502368247644519)

A broad PM-range ban is a reasonable explicit policy for an automated implementation, but Casey describes exceptions for himself and stronger avoidance guidance for newer traders. We should record that distinction rather than claim an exact match. [March 2025 qualification](https://x.com/Team2Trading/status/1900742551696761039)

**Explicit historical timing:** in the interview he says he has no absolute no-trade time, may trade lunch if momentum exists, and treats pre-10:00 entries cautiously. Trades may last a few 2-minute candles or an hour or two. These statements do not establish today's broker cutoff or an author rule to flatten at precisely 15:45. [Interview, 14:44–16:04](https://www.youtube.com/watch?v=7zRANikMiww&t=884s)

The interview contains a discussion of protecting prior gains with smaller subsequent risk. Its auto-transcript lacks speaker labels; the $500-win/$200-risk illustration is not securely attributable to Casey alone. More importantly, an exact rule limiting risk to half the day's P&L is not stated. Treat that formula as Zargar's chosen discipline, supported only at the principle level.

## 9. Evolution and apparent contradictions

| Period | What the inspected sources establish |
|---|---|
| 2022 | Prior-day/overnight levels, 2-minute EMA pullbacks, structural stops; examples also include individual stocks. Zone posts discuss break, rejection and retest. |
| 2023 | Target-zone ladders, intraday pivots, orderly flags, 0DTE timing/risk discussion, early-pullback preference and systematic-loss acceptance. |
| 2024 | Explicit PM-range and inside-day lessons, level-specific retest stops; break entries remain discussed. |
| 2025 | Repeated four-scenario and EMA-fan explanations, qualitative sizing guide, visible base/EMA48/200-flush/add examples; explicit 15-minute confirmation is present by the September gap and November setup lessons. |
| 2026 through September 7 | Strong repeated 15-minute-close -> 2-minute-entry instruction; explicit PMH close-stop example; continued emphasis on consistency, small beginner sizing, and discretionary experience. |

Later, more specific teaching should guide the relevant setup. A later short starter guide is not evidence that all omitted older practices were abolished. Conversely, an older discretionary breakout does not negate the later explicit confirmation requirement for the A+ continuation setup. Maintain setup-specific and date-specific provenance.

## 10. Zargar alignment checkpoints

Local inspection baseline: `C:/Cursor/zargar-codex`, `codex/zargar-development`, HEAD `96b67a1`. No deployed settings or runtime behavior verified. These are comparison points for review, not a completed execution audit.

| Area | Local representation | Source-based assessment |
|---|---|---|
| Levels/timeframes | Prior-day zones, PM lines, extended-hours 2m EMAs, 15m scenarios | Core concepts match; zone edge cases and data construction still require verification |
| Trend/fan | Stack and ATR-normalized width in `regime.py` | Numerical approximation of visual judgment |
| Entry families | EMA13, EMA48, level, base and 200-flush paths in `session.py` | Broad family coverage exists; code explicitly exempts the developing 200-flush setup from the mature-stack gate |
| Flags | `flag_tf_min` documented as not wired; entry body/base heuristics | A body-size or base check is not proof of genuine flag recognition |
| Pullback limits | Two-touch default; exact counting and re-entry gates | Early-entry preference supported; precise counter/reset behavior is ours |
| Targets | Fixed-lookback pivots, optional re-entry HOD/LOD target | Simplification of discretionary zone selection and available room |
| Stops | Entry-reference structural stop; default 25% premium protection; live mid/tick settings | Source supports structural invalidation and premium discipline; exact 25%, quote basis and floor are our policy |
| Runner exits | Simulation uses the original entry-kind guard; `runner_exit` says informational | Compare this with the author's EMA13 runner guidance when a trade began at a level/EMA48; do not assume the label proves parity |
| Trims/adds | +50/+100, approximately thirds, one add by default | Examples support the behaviors; exact ladder/fractions/count are not author constants |
| Contract choice | 0DTE, target 0.60, floor 0.20, closest-premium picker and chase cap | Deliberate expression policy inferred from examples; not a fully published author algorithm |
| Sizing/halts | Full/small multipliers, budget/risk percentages, loss/concurrency caps, shrink-after-win formula | Platform/desk risk controls, not verified Casey account rules |
| Schedule | 09:45–15:30 entries, 15:45 flatten | Implementation constraints; do not attribute every cutoff to the author |

Relevant code: `backend/zargar/techniques/team2/{rules,regime,scenario,levels,session,runner,service}.py`, `backend/zargar/marketstructure/dailylevels.py`, and `backend/zargar/settings_service.py`. Read paths and selected decision branches were inspected; no claims of test or live parity are made here.

## 11. How this informs the upcoming daily review

For every proposed change, ask:

1. What did the author framework say to do at that moment, before the outcome was known? Identify setup family, levels, trend, confirmation, entry risk and target room.
2. Is the issue our observation/data, a code defect, an approximation of discretion, or an intentionally new strategy variant?
3. Was the trade actually executable on the selected option, after spread, fees, latency and fills? An underlying chart win does not prove an option/account win.
4. What valid winners/opportunities would the change remove, and what extra losses/exposure would it introduce?
5. Is the conclusion about one session, several comparable setups, or a broader validated pattern? Keep author fidelity and measured profitability as separate axes.

Examples: widening a stop to rescue a loser is not automatically more faithful; removing all range trades would discard an explicitly taught family; changing EMA periods because they fit yesterday better is a new variant; improving flag detection or preventing a pre-confirmation entry can improve fidelity if backed by reproducible evidence.

The public claims of high win rates and large percentage gains are self-reported context. The inspected posts do not supply a complete, reconciled, fee-adjusted trading ledger. This study establishes what to compare against, not that Casey's claims or our implementation's profitability have been independently verified.

## 12. Completion and open uncertainties

- [x] Studied the available source corpus across years and both captured transcripts.
- [x] Checked fresh public guidance and recovered older omitted threads.
- [x] Independently inspected representative images covering levels, trend, entries, sizing, exits and re-entries.
- [x] Documented the complete operating flow and separated author rules, examples and implementation choices.
- [x] Recorded provenance limits, conflicting statements and targeted review checkpoints.
- [ ] Exhaustive historical-feed/reply capture is unavailable in this unauthenticated session and is not claimed.
- [ ] Exact discretionary exceptions, universal contract/trim formulas and the newer follow-up-candle wording remain unresolved; they must not be invented.

Ready to review the team's daily outcome using this baseline. Further source work should be driven by a specific unresolved proposal or newly supplied author material.
