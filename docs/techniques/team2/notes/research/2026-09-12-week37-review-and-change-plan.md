# Week 37 review (2026-09-08 → 09-11) and the change plan — FOR REVIEW, nothing implemented

Written 2026-09-12 (Saturday) by the Team2 desk. Sources: the runtime journal (`events` joined to `technique_runs`
where `technique='team2'`), the Team2 Practice book (`portfolios` / `orders`), the frozen-input sweeps below (dataset
`522d120e6af4…`, 48 symbol-sessions 08-20..09-11), the watch job's findings F110–F122, and the author's posts read
through the user's logged-in browser on 2026-09-12 (post ids in §2; the four annotated charts are kept locally under `notes/research/week37-author-charts/`, jpgs stay out of git like `notes/x/images`). Sweep numbers are the premium MODEL's summed
trade percentages on Yahoo's tape (F119) with the synthetic strike grid (F104): directionally useful, not P&L.

## 0. The one-paragraph version

The author won three of three trades this week (Wed IWM +141 %, Thu IWM +85/+100 %, Fri SPY +50 %; he did not
trade Tuesday). We filled one day (Tue QQQ, two entries, −$66 net) and refused everything else. Every one of his three
entries was a **retest of a multi-day support/resistance level after a 15-minute body close**, entered on a **2-minute
EMA13 pullback**, and two of the three happened **inside the pre-market range** — the exact place our V6 no-trade zone
refuses. Our read agreed with his read on all three days (same level, same direction, same 15m confirmation); what
separated his three winners from our zero was (1) the no-trade-zone rule as we wrote it, (2) levels: he anchors on the
strongest level of the last several days, we anchor on yesterday's high/low only, (3) the two picker defects already
fixed this week (F104/F105/F108), and (4) on Wednesday, the stale gap-day target (fixed, F81). The proposal below
changes (1) and (2) as method changes with evidence, keeps everything else, and asks the other team to review before
anything is built. Evidence for (1) is strong on the frozen sample: **+28 trades, pnl%-sum 209.5 → 358.6, win rate
.352 → .366, no scenario turns negative.** Evidence for (2) is the author's three charts; it needs a sweep before it
is more than a hypothesis.

## 1. Scorecard, day by day

| Day | Tape | Author (his account) | Us: read | Us: book | Why we did not trade |
|---|---|---|---|---|---|
| Tue 09-08 | normal | did not trade ("I did not trade yesterday", 09-09) | QQQ `pm_break_down` fired twice 10:02 / 10:06 | QQQ 714P ×14 (0.655→0.61) and ×9 (0.63→0.68): **−$65.84 net** incl. $47.84 fees | traded; both exits at the planned target 716.34 within 2–4 minutes — a target one strike away is not a trade |
| Wed 09-09 | gap down | IWM 293P on the 09:41 retest of a **3-day support 293.43** that flipped; targets PML 291.19 → 289.98; +141.77 %, rolled into a lower strike at the PML flip (+65 %) | IWM `pm_break_down` at 10:45, 13 pullbacks | 0 | every pullback `skip_target_behind`: the 17:00 target (293.56) sat above price after the gap — **F81, fixed v0.7.34** |
| Thu 09-10 | gap down | IWM 288P at ~14:00 on the retest of **287.83** (7 wicks that day; our PML) after the 15m body close under it; +85 % / +100 % | IWM `pm_retest` ×9 13:40–14:02, same level | 0 | `skip_no_contract` ×14: the $1 model grid never priced the listed 287.5 put — **F104/F105/F108, fixed v0.7.43–0.7.48** |
| Fri 09-11 | gap up ~1 % | SPY 768C at the 09:46 2m close — an EMA13 pullback holding **764.47** ("our key level", = the 09-09 session high, two days back); trim at the HOD break 766.37 (+50 %), runners stopped on the 13 EMA break; +$801 | all three: scenario 1 (break PDH) on the 09:45 close; SPY's first pullback **09:46 @765.27 — the same candle** | 0 | `skip_no_trade_zone` on every pullback all day (SPY 18, QQQ 11, IWM 21+1): the RTH session sat inside a PM range 8–15 ATR wide — **F112–F115, NOT fixed, user's call** |

Cohort accounting: cohort v1 = 12 sessions (08-26..09-10), one day with fills; cohort v2 = 1 session (09-11), zero
fills, full trail on the record (listing, warm-up, 30+ `skip_no_trade_zone`, no `trail_gap`). The book stands at
$9,934.16.

What the model would have done this week on the tape as the rules stand (sweep, baseline): 7 trades, +140.4 — Tue QQQ
+32/+33, Wed IWM +47/+68 (with F81b), Wed SPY −21/−8, Thu SPY −11. The live desk took only Tuesday's two. So even
with every plumbing defect fixed, the rules as written find three winning days out of four only through Wednesday's
IWM; Thursday and Friday stay empty. That is the method gap this plan is about.

## 2. What he did that we did not (evidence per point)

Posts: 2097723030097330293 (did not trade Tue), 2097800476561678782 + 2097756162976530919 + 2097771160595517923
(Wed plan, recap, intraday flip), 2098137141838795024 + 2098186107460669706 (Thu patience, "15-minute follow-up"),
2098481359241277911 + 2098654455101370413 (Fri trade + annotated 2m chart), 2098812715301294495 (Sat "starter
package": 4 levels, 13/48/200 EMA, bull/bear flags, 1–2 trades a day, base hits).

1. **His level is the strongest S/R of the last several days, not yesterday's high/low.** Wed: "IWM broke 3 days of
   support this morning at our 293.43 zone" (a level three sessions old). Thu: 287.83, "7 candles wick'd off this level
   today" (also our PML). Fri: 764.47 = the 09-09 RTH high, two sessions back, reclaimed by the gap and "my line in the
   sand for calls today." Our zones are L1.1/L1.2 only (the previous session's high and low); prior-session pivots
   exist in `levelLadder` (`target_lookback_sessions=10`) but only as **targets** (L3), never as an entry level. On
   Friday our PDH zone was 758.85–760.11 (Thursday's high) — six dollars below where the day was traded; a pullback to
   the EMA13 at 765 could never be "a retest of the level" in our read.
2. **He trades the retest inside the pre-market range when price is beyond the day's structure.** Fri entry 765.2 with
   PM range 758.17–766.53; Thu entry ~287.8 with PM range 287.68–291.30 (at the PML, the range's edge). Our
   `sizing_bucket` returns `none` for any entry inside PMH–PML (V6's picture, widened deliberately on 2026-09-04, F15).
   B5 in his own words is the **conjunction**: "Inside both ranges (PDH–PDL and PMH–PML) = risk off." F112–F115
   measured that V6's reading blocks 59 % of RTH minutes over 13 sessions and 100 % of Friday, and that neither a
   narrower PM window (F113) nor waiting (F115) rescues it. He says he "typically" avoids the PM range — and then
   traded inside it twice this week when the level was there.
3. **Targets from the morning's structure** (Wed: PML then the next pivot). Built as F81/F81b; F81b is ON under
   observation. Nothing new to propose; the sweep says conjunction + F81b-off is slightly better (373.6 vs 358.6) —
   F81b stays under its own review clock, not this plan's.
4. **Contract choice**: the listed half strike (Thu 287.5), and the strike one through the level (Thu 288p, slightly
   ITM under 287.83). F104/F105/F108 are fixed and deployed; near-ITM eligibility remains the user's separate
   decision (Codex). Not in this plan.
5. **Management**: "high of day break is always a big trim", "13 EMA break is my stop on the runners", "the 15-minute
   follow-up candle is where I secure the majority of my profit", "I will never let the trade go red after this point."
   We have X1 (`trim_cue=new_extreme`) as a knob; measured this week it is **worse** than premium trims alone (135.1 vs
   209.5) and slightly worse combined with the conjunction (310.6 vs 358.6). His trim is a *scale-out into the
   momentum*, which the premium trims already approximate. **No change proposed.** A breakeven stop after the first
   trim ("never red after this point") is worth one sweep — listed as C5, low priority.
6. **Position building**: "entered some calls", "wanted another retest of our key level to add full position" — a
   half-size first entry, add on the level retest. Ours: X5 adds only after a trim. Listed as C4 for measurement.
7. **Discipline**: "1 or 2 trades a day with confluence", "1 and done Friday", waited "almost 5 hours" Thursday. Our
   caps (max 2 re-entries, 2 losses desk-wide, 1 concurrent) already encode this; Tuesday's two quick target exits
   show the opposite problem (see C3).

## 3. Measurements (frozen inputs, out of tree; scripts in the desk's scratch, reproducible from `bars`)

Dataset `522d120e6af4…` (validated sessions, 08-20..09-11, SPY/QQQ/IWM, 48 symbol-sessions). Baseline = today's rules.

| Variant | trades | wins | wr | pnl%-sum | avg win / loss | this week |
|---|---|---|---|---|---|---|
| **baseline** | 54 | 19 | .352 | **209.5** | 41.3 / −16.4 | 7 tr, +140.4 |
| **B5 conjunction** (none only inside BOTH ranges) | 82 | 30 | .366 | **358.6** | 45.5 / −19.4 | 21 tr, +328.9 |
| no PM zone at all | 104 | 35 | .337 | 349.5 | 48.3 / −19.4 | 26 tr, +431.7 (IWM Fri −32.9) |
| conjunction + `trim_cue=new_extreme` | 83 | 33 | .398 | 310.6 | 37.7 / −18.6 | 21 tr, +319.4 |
| conjunction + F81b off | 74 | 28 | .378 | 373.6 | 44.6 / −19.0 | 18 tr, +288.9 |
| conjunction + small bucket = 0 | 57 | 19 | .333 | 58.5 | 47.4 / −22.2 | 19 tr, +263.4 |
| `trim_cue=new_extreme` alone | 54 | 20 | .370 | 135.1 | 33.0 / −15.4 | 7 tr, +121.4 |

Conjunction vs baseline, matched by trade: 44 shared (unchanged), **38 added for +134.6**, 10 lost for −14.5. The
added trades are the gap-day scenario_4/scenario_1 entries the zone was eating (scenario_4 goes 4 → 26 trades,
+28.7 → +210.7). This week it takes Fri SPY (−10.4, +27.2), Fri QQQ (+62.5, +40.7), Thu SPY (+104.0), Thu IWM (+54.2,
−53.1), Wed IWM (+55.8, −12.9) on top of the baseline's. Removing the PM zone entirely adds volume but not edge
(26 more trades for −9 vs the conjunction, and scenario_1/2 turn negative) — the conjunction is the right reading, not
"no zone". The "small bucket = 0" row shows the middle rung matters: killing it costs 300 points, i.e. most of the
conjunction's added trades are SMALL-size entries between the PDH/PDL zone and the PM level, exactly V6's picture.

Caveats the reviewer should hold against these numbers: (a) model marks at one sigma, not fills — cohort v1 shows the
live picker and the model disagree at the band's edge; (b) Yahoo's tape, while the desk trades Alpaca's (F119, QQQ
disagrees on 40 % of minutes); (c) synthetic strike grid in the sweep (F104 — history has no listings); (d) 48
symbol-sessions is one regime (a trending, gappy three weeks); (e) the conjunction variant was measured by
monkey-patching `sizing_bucket` in-process, not with a knob — the build must reproduce these numbers first.

## 4. The change plan (numbered; nothing built; the other team reviews first)

### C1 — No-trade zone = B5's conjunction (rule change; the big one)

- **Rule (METHOD B5, V6):** an entry is `none` only when price is inside BOTH the PM range and the PDH–PDL zone
  range; between a PDH/PDL zone and the PM level it is `small`; beyond the zones `full`. Unchanged: V6's three buckets
  and multipliers, `pm_tol_atr`, the PM window (04:00–09:30, F113 showed the window is not the lever).
- **Code:** `techniques/team2/scenario.py::sizing_bucket` (one function; used by `session.py:538` for entries and
  `plan.py:90` for `sizingAtOpen`). Knob `techniques.team2.no_trade_zone = "pm_range" | "conjunction"` (rules field
  `no_trade_zone`, SETTINGS_MAP, DEFAULTS) so the sweep can run both and the live desk can be switched back without a
  deploy. Default stays `pm_range` until the user flips it; the sweep harness must reproduce §3's 82 / 358.6 exactly.
- **Tests:** pure `sizing_bucket` cases for the four regions × both modes; a session-level test that Friday's shape
  (PM range containing the RTH session, scenario 1 confirmed above the PDH zone) fires under `conjunction` and refuses
  under `pm_range`; the F15 regression (QQQ 2026-09-04 10:02, a `pm_break_up` entry 0.62 under the PMH, inside both
  ranges) must STILL refuse — that was the case F15 widened the zone for, and the conjunction keeps it.
- **Risk:** more entries on gap days = more small-size trades; the desk-wide two-loss cap and the 6 % risk cap bound
  it. Watch `skip_no_trade_zone` counts fall and `contract_*` verdicts rise in cohort v2.
- **Promotion:** flip in Practice on the user's word after review; measure 10 live sessions; the book decides.

### C2 — Multi-day levels as entry levels (method extension; needs a sweep before it is a proposal)

- **Rule (new, L1.5 draft):** besides PDH/PDL, mark the last `N` sessions' RTH highs/lows and the pivots already in
  `levelLadder`; a level that has been touched by ≥ `k` 15m wicks over the last `m` sessions (author: "3 days of
  support", "7 candles wick'd off this level") is a **key level**. A 15m body close through a key level sets the bias
  exactly like a PDH/PDL zone (scenario logic unchanged); the entry is the 2m EMA13 pullback on the retest (T1/T2
  unchanged). Targets: the next key level / PM level / ladder rung (L3 unchanged).
- **Why:** all three of his entries this week anchored on such a level (293.43 = 3-day support; 287.83 = 7-wick level
  and PML; 764.47 = the 09-09 high). Our four levels do not contain two of the three.
- **Code sketch:** `techniques/team2/levels.py` (already builds the ladder) gains `key_levels(bars15m, sessions=5,
  min_touches=3, tol=…)`; `plan.py::build_skeleton` adds `keyLevels` to the plan; `session.py` treats a key level as a
  zone for scenario detection when it lies beyond the PDH/PDL zones on the day's side (so it only matters on the
  gap/flip days where PDH/PDL are far away). Knob `techniques.team2.key_levels = off|on` (default off).
- **Measure first:** the sweep on the frozen dataset with `key_levels=on`, matched trade lists; it must not take
  trades on non-gap days that the baseline refuses for good reasons. If it does not add net positive on the sample it
  stays a research note. **This is the one item that could be wrong; C1 is not.**

### C3 — A target one strike away is not a trade (small rule; measure)

- Tuesday's two fills exited at the planned level 716.34 within 2–4 minutes for −4.5 % and +8 % on premium and −$66
  after fees. The author's targets are at least the next structural level away. Proposal: `min_target_atr` (e.g. 1.5
  × 2m ATR from entry) — an entry whose target is nearer than that is refused `skip_target_near`, journaled like
  `skip_target_behind`. Sweep it; expected effect small and positive (it removes fee-negative scalps).

### C4 — Add on the level retest (author's position building; measure)

- Half size on the first EMA13 pullback, the other half on the next hold of the key level (his "wanted another retest
  of our key level to add full position"). Ours adds only after a trim (X5). Variant `add_on_level_retest` for the
  sweep; only if C2 lands, since "the key level" is C2's object.

### C5 — Breakeven after the first trim (author's "never red after this point"; measure)

- After TP1, move the premium stop to entry. Sweep variant `breakeven_after_trim`. Low priority; premium-stop
  interaction with 0DTE noise is the risk (he explicitly trades 0DTE and "tries not to get stopped out of a valid
  trade").

### C6 — Data prerequisite: one tape (F119; shared engine; the other desks' call)

- The live desk trades Alpaca's bars and every sweep/replay scores Yahoo's; on QQQ 40 % of minutes differ. Every
  number in §3 is Yahoo. Recommendation as F119 option (a): a per-venue provenance value and Alpaca-over-Yahoo
  precedence for streamed symbols in `marketdata.merge_exchange` / `persist_bars`. Without it, C1's live result and
  its sweep are not the same experiment. This is not Team2 code; it is listed so the reviewers can sequence it.

### Explicitly NOT proposed

- Narrowing the PM window (F113: does nothing on gap days). Removing the PM zone (worse than the conjunction, §3).
- `trim_cue=new_extreme` (worse on the sample). Any change to the 15m confirmation, EMA13/EMA48 pullback, 0DTE band,
  premium trims, flatten, F81, F81b's review clock, near-ITM eligibility (user's separate decision), or risk caps.
- Anything to the picker or the trail (v0.7.43–0.7.48 are in cohort v2's observation period).

## 5. Sequencing and governance

1. Other team reviews this note (questions in §6). 2. C1 built behind its knob, tests + sweep reproduction, Codex
review, deploy through the door; the user flips the knob in Practice. 3. C6 in parallel by the platform owners.
4. C2 measured; proposal or research note. 5. C3/C4/C5 sweeps as one batch of variants for the twenty-session review.
Cohort v2's clock does not restart for C1 (it is a rule, not an execution-path change) but the review must split
sessions before/after the flip. Everything is logged in TRADING-RULES' change log with the sweep hashes.

## 6. Questions for the reviewing team

1. Is the conjunction reading of B5 the author's rule or our convenient reading? The text ("inside both ranges = risk
   off") and his two inside-range entries this week say conjunction; F15's 2026-09-04 case says the zone matters when
   both ranges overlap. The test in C1 keeps F15's case refused. Do you agree that is the right boundary?
2. §3's numbers are model marks on Yahoo's tape with a grid ladder. Which of (a)–(e) in the caveats would change your
   verdict on C1 if it went the wrong way, and should C6 land first?
3. C2: is "≥ k wicks over m sessions" the right definition of the author's key level, or is it the ladder's pivots
   plus a recency rule? He never states a rule; three charts are the whole evidence.
4. Should C1 be flipped in Practice immediately after review (the user's stated preference is to run rules live
   rather than forget them), or held for the twenty-session review with the other variants?

## Addendum 2026-09-13 — the other team's verdict, and what was done about it

Verdict received: GO for research and C6; NO-GO for flipping C1 in Practice as written. Two findings: (1) the F15
preservation claim was wrong — QQQ 2026-09-04 10:02 (entry 721.44, PDH 718.91, PM 717.13–722.06) is inside the PM
range but OUTSIDE yesterday's range, so a pure conjunction allows it; (2) the improvement is concentrated in the
motivating week (+188.5 this week, −39.4 earlier) and summed percentages are not the book (no size multipliers, no
shared concurrency or loss limits). Both accepted. What follows is the response, in their recommended order.

### A. C1 geometry corrected: ordered truth table (built, tests, DISABLED by default)

`sizing_bucket(price, zones, pmh, pml, mode)` with `in_pm` = pml ≤ price ≤ pmh and `beyond` = above the PDH zone top
or below the PDL zone bottom:

| mode | in_pm | beyond | bucket | note |
|---|---|---|---|---|
| pm_range (today) | yes | any | **none** | V6's picture, F15 widened it to gap days |
| pm_range | no | yes | full | |
| pm_range | no | no | small | |
| conjunction | yes | no | **none** | B5: inside BOTH ranges = risk off |
| conjunction | yes | yes | **small** | beyond yesterday's zone but inside the PM range — V6's rung, never full |
| conjunction | no | yes | full | |
| conjunction | no | no | small | |

So the reviewers' sizing ambiguity is resolved as **small**, never full, inside the PM range. F15's case is NOT kept by
the geometry (conjunction → small); it is a separate, explicit condition, `pm_room_atr`: an entry inside the PM range
that is not the pm_break retest (F20) and has less than `pm_room_atr` × ATR of room to the PM boundary ahead is refused
`skip_pm_room`. F15's case has 0.62 of room; Friday's SPY candle 1.26 = 2.2 ATR. Knobs (all off by default, live read
unchanged, proven by `tests/test_team2_no_trade_zone.py`): `techniques.team2.no_trade_zone` (`pm_range` |
`conjunction`), `techniques.team2.pm_room_atr` (0 = off), and C3's `techniques.team2.min_target_atr` (0 = off).

### B. Canonical reproduction and chronological, book-level assessment

Same dataset (`522d120e6af4…`), the sweep now driven by the knobs (no monkey-patching). "Book" = a chronological
simulation across the three symbols with one open position at a time desk-wide, two losses end the day, and each
trade weighted by its size multiplier at $600 of premium per full unit — a labelled scale, not the Practice book.

| variant | trades | wr | pnl%-sum | earlier (08-20..09-04) | this week | book total | book earlier | book week | max DD |
|---|---|---|---|---|---|---|---|---|---|
| baseline | 54 | .352 | 209.5 | 47 tr, +69.1 | 7 tr, +140.4 | +$471 | +$282 | +$189 | −$320 |
| **conjunction** | 82 | .366 | 358.6 | 61 tr, +29.7 | 21 tr, +328.9 | **+$1,514** | **+$656** | +$858 | −$565 |
| conjunction + room 1.0 ATR | 81 | .358 | 334.0 | +5.1 | +328.9 | +$1,407 | +$550 | +$858 | −$565 |
| conjunction + room 1.5 | 77 | .338 | 219.7 | +0.7 | +218.9 | +$1,137 | +$561 | +$575 | −$565 |
| conjunction + room 2.0 | 71 | .352 | 259.4 | +27.6 | +231.8 | +$1,272 | +$467 | +$804 | −$559 |
| conjunction + room 3.0 | 66 | .333 | 223.7 | +21.7 | +202.0 | +$572 | +$504 | +$68 | −$397 |
| C3 min target 1.0 ATR | 43 | .302 | 97.2 | +22.2 | +74.9 | +$34 | −$9 | +$43 | −$467 |
| C3 min target 1.5 ATR | 38 | .237 | 15.9 | −59.0 | +74.9 | +$61 | +$18 | +$43 | −$445 |

Readings, stated carefully:

- The reviewers' split is confirmed on summed percentages: the conjunction is worse than baseline on the earlier
  portion (+29.7 vs +69.1). **At book level the sign flips** (+$656 vs +$282 earlier), because every one of the 38
  added trades is SMALL size (half a unit) while the 10 lost baseline trades were full size — the raw sum overweights
  the additions. Whether that is reassuring or an artefact of the $600/half-unit scale is exactly the question a
  prospective Practice comparison answers; it is not settled here. Drawdown rises from −$320 to −$565 either way.
- Added trades by date: 08-20 +100.9, 08-24 −19.4, 08-25 +45.1, 08-27 −81.3, 08-31 −0.7, 09-01 −65.6, 09-03 −10.7,
  09-04 −14.3, 09-08 +22.2, 09-09 −32.7, 09-10 +71.1, 09-11 +120.0. Six of twelve dates negative; the gains sit on
  four dates. 16 trading dates is the whole sample; the reviewers' "not 48 independent days" stands.
- **The room rule does not earn its place on this sample**: every threshold lowers the result, and 2.0 ATR (the value
  that would keep Friday's candle) costs 100 points, 20 of them on the earlier portion where it was meant to help.
  F15's case is one refusal; the rule refuses many more that were fine. Recommendation: keep `pm_room_atr = 0`; if the
  team wants F15's case excluded, it needs a narrower condition than distance to the boundary (e.g. only when the
  scenario itself is a pm_break, or only within the last N minutes of a failed break), which nobody has measured.
- **C3 as measured is rejected**: a minimum target room of 1.0–1.5 ATR removes more good trades than fee-negative
  scalps (book +$471 → +$34). The reviewers asked for entry-to-target room, stop distance AND costs measured
  together; this was the room alone and it is negative enough that the fuller study is not worth its cost now.
  Tuesday's two QQQ scalps stay a note, not a rule.

### C. Status of each proposal after the review

| | Verdict | Now |
|---|---|---|
| C1 conjunction | build behind a disabled knob; do not activate | **built, off, tests; awaiting a defined Practice experiment after C6** |
| C1 room rule | resolve as an explicit condition | built as `pm_room_atr`, **measured negative, stays 0** |
| C2 multi-day levels | research; freeze a causal definition | not started; needs the definition first (clustering, independent touches, recency, ranking, invalidation) |
| C3 min target room | independent sweep | **swept, negative, dropped as specified** |
| C4 add on retest | research with one risk budget | not started |
| C5 breakeven after trim | research; distinguish whole-trade vs remaining-contracts | not started; the reviewers are right that Friday's chart does not establish it |
| C6 one tape | GO, platform ownership | request written in PLATFORM-RULES (2026-09-13); precedes any activation |

Sequence agreed: geometry corrected (A) → canonical inputs (C6, platform) → variant reproduced on the canonical tape →
book-level risk re-assessed → a separately labelled prospective Practice comparison proposed for approval. Nothing is
active. `trim_cue=new_extreme` remains rejected; near-ITM eligibility remains the user's separate decision.
