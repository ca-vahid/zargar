# Team2 method-fidelity matrix (author evidence vs. implementation)

Audit date 2026-09-18. Read-only. Checkout audited: `C:/Users/vispe/AppData/Local/Temp/t2prof` (git worktree).
The 2026-09-18 author recap exists only in the Codex checkout:
`C:/Cursor/zargar-codex/docs/techniques/team2/notes/research/2026-09-18-author-public-recap.md` (not found in t2prof).

Path shorthand: `DOC/` = `docs/techniques/team2/`, `X/` = `DOC/notes/x/`, `IMG` = `X/images/INDEX.md` (text descriptions of
the images; the jpgs themselves are not in the checkout — `DOC/notes/research/2026-09-08-author-study-evidence.md` says
"98 image-metadata JSON files and no JPG images"), `CODE/` = `backend/zargar/`, `T2/` = `CODE/techniques/team2/`.

What was read: `DOC/METHOD.md`, `DOC/AUTHOR-STUDY.md`, all 49 dated notes under `X/` plus `PARTIAL-…md` and `IMG`, the
2022 video transcript in full, the 2023 podcast transcript by keyword (stops, size, hold time, time of day, pullbacks),
`DOC/notes/research/2026-09-08-author-study-evidence.md`, `…/2026-09-12-week37-review-and-change-plan.md` §0–§2, the
2026-09-18 recap, the 2026-09-16/17 EOD entries of `DOC/TRADING-RULES.md`. Code: `T2/rules.py`, `T2/session.py`,
`T2/scenario.py`, `T2/regime.py`, the money-path parts of `T2/runner.py`, `CODE/execution/planrunner.py` (quote watch,
sizing), `CODE/execution/exits.py`, `CODE/marketstructure/dailylevels.py`, `CODE/settings_service.py` lines 124–201.
NOT read: `DOC/notes/market-watch.md` (600 KB), most of `DOC/TRADING-RULES.md`, `DOC/PLAN.md`, `T2/levels.py` /
`T2/plan.py` / `T2/premium.py` beyond their signatures. I did not see any image; every image fact below is second-hand
from `IMG`, METHOD §7b or the 09-08 evidence ledger.

Evidence classes (strict):
- **EXEC** = EXECUTION-DOCUMENTED: a broker card / P&L or an alert with a fill price from the author's own account.
- **CHART** = CHART-ANNOTATION: an annotated chart or a narrated recap without a fill; setup evidence only.
- **RULE** = STATED-RULE: text without a worked example.
- **NONE** = nothing found.

Labels: **SUPPORTED** (explicitly supported) / **INFERRED** (we chose a number or rule the author never states) /
**UNRESOLVED** (author material contradictory or silent).

---

## A. Levels

| Behavior | What the author documents | Evidence | What our code does | Label | Divergence risk for profitability |
|---|---|---|---|---|---|
| PDH/PDL definition | "highest & lowest price of the previous trading session (RTH)" — `X/2025-06-21-…spy-thread.md` | RULE (+ many CHART) | Highest-high / lowest-low 15m RTH bar of the previous session, `CODE/marketstructure/dailylevels.py:60-72` | SUPPORTED | Low. |
| PDH/PDL zone width | "High of day wick to the following candle body" on the 15m — `X/2022-11-05…`, `X/2025-03-28…`, `X/2025-10-18…`; but "connect that to a nearby candle body" — `X/2025-01-30…`; reader: "you draw the zones different quite often" (unanswered) — `X/2024-01-10…` | RULE + CHART (`IMG` 2081050857597211029-1: widths ≈0.1–0.17 %) | Literal rule: extreme wick → body edge of the NEXT 15m bar; last-bar extreme or doji collapses to a zero-width zone, `dailylevels.py:69-79` | SUPPORTED for the default; UNRESOLVED for edge cases (last bar, large next body, multiple candle bodies) | Medium: the zone edge is the scenario trigger AND the level-retest/stop line; a different body choice moves all three. |
| PMH/PML definition | "highest & lowest price from 4am to 9:30am EST", "dotted lines" — `X/2025-06-21…` | RULE | max/min of 1m bars in session "pre", `dailylevels.py:82-86`; PM touch tolerance `pm_tol_atr` 0.25 × 2m ATR (`T2/rules.py:36`) | Definition SUPPORTED; tolerance INFERRED | Low/medium: tolerance decides what is a "retest". |
| Multi-day "key" levels as ENTRY levels | 2026-09-09: "IWM broke 3 days of support … at our 293.43 zone"; 09-11: 764.47 (session high two days back) "my line in the sand for calls" — `DOC/notes/research/2026-09-12-week37-…md` §2.1 | EXEC (three week-37 trades, per our own note; posts read through a logged-in browser, charts kept locally, not in git) | Entry levels are yesterday's zones and today's PM lines only. Older pivots exist as TARGETS only (`target_lookback_sessions` 10, `rules.py:39`). C2 `key_levels` built, default `"off"` (`rules.py:92`, `settings_service.py:160`) | UNRESOLVED (author uses them; no causal definition exists) | High: on 2026-09-11 our PDH zone was ~6 points below where he traded; we could not see his level at all. |
| Targets = next zone | "the last strong rejection we had above the PDH will be my first upside target" — `X/2025-08-09…`; "I look back as far as I need" — `X/2023-02-18…` | RULE + CHART; EXEC for "selling here at my target" (QQQ 2025-10-17, `IMG` 1979379268410130815-1) | 15m pivots, window 2, 10-session lookback (`T2/levels.py:19-29`); range day target = opposite zone (`session.py:306-307`); PM-break target = the PDH/PDL zone edge (`session.py:322,330`); gap-day re-derivation F81/F81b | Concept SUPPORTED; pivot window, lookback 10, "strong" = any pivot: INFERRED | Medium/high: the target is a FULL exit (row in §I); a weak nearby pivot caps winners (2026-09-08 QQQ exits 2–4 min at a target one strike away, week-37 note §1). |
| Intraday S/R zones as levels | "Look for areas where price has found support and resistance early in the day" — `X/2023-02-18…` | RULE (2023) | Not built as entry levels; running HOD/LOD used only as a re-entry target (`hod_target="reentry"`, `rules.py:68`) | UNRESOLVED | Low/medium. |

## B. Trend / EMA regime

| Behavior | What the author documents | Evidence | What our code does | Label | Divergence risk |
|---|---|---|---|---|---|
| 13/48/200 EMA on 2m, ext hours on | "13 / 48 / 200 EMA's on the 2 minute chart (extended hours on)" — `X/2025-04-05…`, `X/2026-02-08…` | RULE + CHART | `ema_fast/mid/slow` 13/48/200, `entry_tf_min` 2 (`rules.py:26-29`); fed extended-hours bars, seeded from 12 prior sessions (`warmup_sessions`, `rules.py:99`) | SUPPORTED (warm-up length INFERRED) | Low. |
| Direction filter | "Always favor calls in a bullish trend… puts in a bearish trend" — `X/2026-02-08…`; ladder "Above 200 EMA = Bullish; +48 = More; +13 = Mega" — `X/2025-03-11…`; "price over the 200ema for pullback entries to the 13 and 48ema" — `X/2023-02-18…` | RULE + CHART | Every entry except the 200-flush needs the FULL ordered stack `fast>mid>slow` (`CODE/marketstructure/indicators.py:83-88`; gate `session.py:535`) | INFERRED as a hard gate: his ladder treats "above the 200" as already bullish; the 2025-10 SPY 671p EXEC example entered with 48 still above 200 (evidence ledger, image G3go_vrW8AAfI5y) | Medium/high: after a gap or a reversal the ext-hours 200 EMA lags; requiring the full stack can delay the first entry until the move is mature (candidate cause of the 2026-09-18 20-minute lag — NOT verified, needs the trace). |
| Chop filter (EMA fan) | "tightly stacked or braided together … clear indication of chop" — `X/2025-10-04…` | RULE + CHART | `fan_trend_min_atr` 0.60: (max−min of the 3 EMAs) / 2m ATR < 0.60 = chop (`rules.py:32`, `regime.py:80-82`, gate `session.py:537`) | Concept SUPPORTED; 0.60 × ATR INFERRED ("The author describes appearance… not a universal 0.60-ATR threshold" — `DOC/AUTHOR-STUDY.md` §4) | Unknown; 0.6 ATR is a very small spread (the 200 EMA is normally several ATR from the 13), so the gate probably rarely binds — i.e. we may trade chop he would skip. |
| EMA48 second line of defense | "After a few 13 EMA taps, I'll start watching for that possible 48 EMA dip" — `X/2025-04-27…`; IWM: entry 1 at EMA13 fails, entry 2 at EMA48 wins — `IMG` 1961977216818163982-1 | RULE + CHART | `allow_ema48_entries` True: any bar touching EMA48 (and not EMA13) and closing on side fires (`session.py:549-551`), no "after a few taps" precondition | Concept SUPPORTED; unconditional use INFERRED | Low/medium. |
| Flags (third A+ item) | "Above PDH ✅ Bullish EMA trend ✅ Bull Flagging ✅" — `X/2025-06-21…`; "5 minute = Flags / trend lines" — `X/2025-09-07…` | RULE + CHART + EXEC (SPY 648c "bull flag", `IMG` 1961977219590574391-1) | NOT BUILT: `flag_tf_min: int = 5 … NOT WIRED (no flag detector yet)` (`rules.py:31`). Proxy only: engulfing-bar skip `pullback_body_mult` 2.0 (`session.py:662`) | Author rule MISSING from the implementation | Medium/high: one of his three confirmations is absent; we take every touch that closes on side, he takes orderly flags ("even channel pullback", 2022 video 03:34). |

## C. 15-minute confirmation

| Behavior | What the author documents | Evidence | What our code does | Label | Divergence risk |
|---|---|---|---|---|---|
| Break = 15m body close beyond the level | "letting the 15 minute candle body close above / below your key level" — `X/2026-03-01…`; entry criteria `X/2026-07-25…` | RULE + CHART; EXEC: SPY 711c 2026-04-17 "wait for the 15 minute close then look at the 711c" (`IMG` 2081050846666891284-1); QQQ 606c 2025-10-17 | `body_closed_beyond` = close beyond the level (`scenario.py:85-87`); scenario set on the 15m close beyond the ZONE edge (`scenario.py:202-205`); margin/body-ratio knobs at 0 (`rules.py:37-38`) | SUPPORTED | Low. But note the rule is 2025-09+ wording; older EXEC trades predate it (§1). |
| Is the 15m close mandatory for EVERY entry? | 2026-09-09 IWM 293P entered "on the 09:41 retest" — before any 15m RTH bar had closed (week-37 note §1); 2024-07-09 IWM 201p entry box 09:38–09:50 (`IMG` 1810706353427771759-1); 2026-09-03 first 771c card already +25 % at 09:52 (`IMG` 2095571390321865119) | EXEC (3 instances of entries at/before the first 15m close) | Every setup is minted only on a 15m close; no entry before a 2m bar whose close is ≥ 09:45 (`first_entry_min`, `rules.py:54`, gate `session.py:483`) | UNRESOLVED: the teaching says wait; his own fills show early retest entries | High on gap/trend mornings: his documented winners on 09-03 (first attempts), 09-09 and 2024-07-09 started before we are allowed to act. |
| Reject PDH / bounce PDL (range scenarios) | "Price rejects the Previous Day High Resistance Zone" — `X/2025-10-18…` (no candle definition) | RULE + CHART | One 15m bar whose high reached the zone and closed below the zone bottom (mirror for PDL) (`scenario.py:206-209`) | INFERRED (the single-bar definition is ours) | Medium. |
| Range-day extra confirmation | "confirmation … with things like Bearish EMA crosses, PML breaks, bear flags etc." — `X/2025-09-27…` | RULE | `range_day_confirmation` True: price must have CLEARED the PM level (`session.py:617-622`); the only alternative is the 200-EMA flush (`session.py:531-534`) | INFERRED: he lists alternatives; we require one specific one | Medium. |
| Bias flip | "as long we hold above that PDH zone" — `X/2025-10-18…` | RULE | 15m close back through the zone flips the scenario and kills scenario setups (`scenario.py:214-222`, `session.py:308-310`) | INFERRED (reasonable reading) | Low/medium. |
| PM-break setup lifetime | "About 30 minutes into today's session we broke the PMH and immediately went from chop to trend" — `X/2024-05-24…` | CHART | One PM-break setup per side per day on the FIRST 15m close beyond the PM level (`pm_up_done`, `session.py:320-335`); **PM-break setups are never invalidated** — only `scenario_*` setups die on a flip (`session.py:309`; all `dead=` sites: 310, 377, 382) | INFERRED | Medium: a failed PM break keeps firing pullbacks for the rest of the day if the stack agrees. |

## D. Entry trigger and entry timing

| Behavior | What the author documents | Evidence | What our code does | Label | Divergence risk |
|---|---|---|---|---|---|
| Entry timeframe | "I take all my entries on the 2 minute timeframe" — `X/2025-01-30…` | RULE + EXEC | 2m closed bars aggregated from 1m (`session.py:228`) | SUPPORTED | Low. |
| Trigger = pullback to EMA13 / level retest | "15 minute candle close above PMH followed by a 2 minute dip back into the 13 EMA for my entry" — `X/2026-07-25…` | RULE + EXEC (SPY 711c @ .60; QQQ 472p @ .55 "at the 13 EMA retest") | EMA13 touch: bar reaches within 0.25 ATR of EMA13 and CLOSES back on the trade's side (`session.py:547`); level retest same shape on the setup anchor (`session.py:553`) | Concept SUPPORTED; tolerance and "must close on side" INFERRED | See next row. |
| Does entry wait for a bar CLOSE? | "Taking your entry as close to that as possible keeps losses small" — `X/2025-09-07…`; 2022 video 12:33: "it closes under this little green candle here was my entry"; 2026-09-11 SPY 768C "at the 09:46 2m close" (week-37 note); alerts such as "I'm taking SPY 770c" on "Getting the 768.00 retest now" (`IMG` 2095599035113693522-1) | Mixed EXEC: some at the touch, some on a 2m close | ALWAYS waits for the 2m close, then picks a contract, quotes up to 8 candidates live, sizes and sends a limit. The MODEL books the entry AT the EMA/level price (`entry_spot = ema`, `session.py:600-601`, fill `session.py:816`) while the live order is priced on the NBBO after the close (`T2/runner.py:192-204`, `581-690`) | UNRESOLVED (author does both); our model/live mismatch is ours | High: live pays for the bounce already printed (long: close > EMA) while the stop line is the EMA itself — the live trade starts closer to its stop in premium terms than the model believes, and METHOD T6 ("the entry limit sits at the EMA/level, never at market after the bounce is visible", `DOC/METHOD.md:220-223`) is not what the runner does. |
| Time from level break to entry | 2026-09-18 IWM chart: PML break, entry illustrated "around 09:46–09:52"; ours filled 10:12:03, "approximately twenty minutes after… during the rebound" — Codex recap file | CHART (author) vs our EXEC fill | No limit on setup age: a setup confirmed at 09:45 can fire at any later pullback until 15:30 (`session.py:509`); first/second PRICED touch only | UNRESOLVED (one dated comparison; cause not traced) | High: the first pullback is "where most of my money is made" (podcast 39:08); an entry 20 min later is a different trade. |
| First or second pullback only | "enter on the first or second pullback into the EMA's" — `X/2026-01-18…`; third bounce "right by the resistance zone" is where early buyers exit — podcast 39:42–40:08 | RULE (+ interview) | `pullback_max_touches` 2 (`rules.py:44`); only PRICED fires and engulfing bars spend the allowance; refusals (no-trade zone, no contract, target behind) do not (`session.py:593-599, 653-666, 814`); `pullback_reset_atr` 0.5 defines a new pullback (`rules.py:46`) | Preference SUPPORTED; every counter rule INFERRED (METHOD §0b item 5 says so) | Medium/high: because refused contacts do not count, "touch #1" can be the 5th real pullback of a mature move — the opposite of his warning. |
| Engulfing pullback skip | "big engulfing candles… into the EMA. Those are always less likely to work out. They still can" — 2022 video 03:50 | RULE (soft) | Hard skip when body > 2.0 × avg body of the session's 2m bars (`session.py:662`) | INFERRED threshold | Low/medium. |
| Break & base | "that break & base over pre market high is so nice… loading up these cheap 574c" — `IMG` 1961977219590574391-3 | EXEC (entry alert; no exit card described) | `base_bars` 3 within `base_tol_atr` 1.0 (`rules.py:51-52`, `session.py:565-573`) | Concept SUPPORTED, numbers INFERRED | Low/medium. |
| 200-EMA flush | "going to use the break of 200 EMA support as my trigger for puts" — `IMG` 1979379272990277934-1 | EXEC (one example) | `allow_ema200_flush` on range days: 13<48 and a 2m close through the 200 (`session.py:531-534`) | One example generalised: INFERRED | Low. |
| Flag-break entry / scaling in before a trim | "if we hold the 13ema and break this flag I'll be looking at 631p… all loaded up with .50 average" — `IMG` 1953540502995055061-2; QQQ ".31 average now" — `IMG` …590574391-2; 09-11 "wanted another retest of our key level to add full position" | EXEC | Not built. One full-size entry; adds only AFTER a trim (`add_on_retest`, `max_adds` 1, `session.py:460-479`) | Author behavior MISSING (METHOD X5 admits it) | Medium: he starts partial and averages while the level holds; we commit full size on bar one. |
| Stale signal | none found | NONE | Fire older than 3 min at decision time is dropped (`max_signal_age_min`, `rules.py:91`, `runner.py:1671-1687`) | INFERRED (operational) | Low. |

## E. No-trade conditions / no-trade days

| Behavior | What the author documents | Evidence | What our code does | Label | Divergence risk |
|---|---|---|---|---|---|
| Inside the pre-market range | "I typically try to avoid taking trades inside of the pre market high / low range. There are some exceptions" — `X/2025-08-09…`; "Not a hard rule for me" — `X/2025-06-21…`; sizing image labels PMH→PML "No trade zone" (`IMG` 1961977207825616952-1); two of three week-37 winners were inside the PM range (week-37 note §2.2) | RULE (soft) + CHART; EXEC counter-examples | Hard ban: `sizing_bucket` returns `none` for any entry price inside PMH–PML, including gap days (F15) (`scenario.py:59-73`, refusal `session.py:646-650`); exception only for the retest of the PM level itself → small (`session.py:629-633`); `no_trade_zone="conjunction"` built, OFF (`rules.py:93`) | INFERRED as a hard rule ("loose guide" in his words) | High: our own measurement says it blocks 59 % of RTH minutes over 13 sessions and 100 % of 2026-09-11 (week-37 note §2.2). |
| Inside yesterday's range | "balanced days between the PDH & PDL can be a bit more choppy"; "size down for scenarios 2 & 3" — `X/2025-03-15…` | RULE | Small size (0.5), not refused (`scenario.py:71-73`) | SUPPORTED in kind; 0.5 INFERRED | Low. |
| Braided EMAs | see B | RULE | see B | — | — |
| Event / macro days | not found in any captured note | NONE | `avoid_event_days` False (`rules.py:110`) | UNRESOLVED | Unknown. |
| Days he sits out | 2026-09-08: "I did not trade yesterday" (post 2097723030097330293, week-37 note §2). Reason: **not found** in our notes. 2026-09-03 pinned post: "it's gonna be a chill Friday for me" (intent for 09-04; whether he traded: not found). 09-10: waited "almost 5 hours" for one trade | EXEC-level statement of a no-trade day (1) | No discretionary sit-out exists; the desk trades whenever gates pass (2026-09-08: two QQQ entries, −$65.84 net, week-37 note §1) | UNRESOLVED | Medium: his no-trade days are discretionary; we have no analogue and no reason on record. |

## F. Contract choice

| Behavior | What the author documents | Evidence | What our code does | Label | Divergence risk |
|---|---|---|---|---|---|
| Expiry | Podcast description: "day trading SPY & QQQ 0DTE options"; every broker card in `IMG` is same-day expiry | EXEC (9 card-days) | `dte_policy` "0dte" (`rules.py:86`) | SUPPORTED | Low. |
| Premium target | Never stated as a rule. Priced examples: .60 (SPY 711c), .54 (SPY 648c), .55 (QQQ 472p), .50 avg (SPY 631p), .50 (SPY 624c), .31 avg (QQQ 572c), .20 (IWM 201p). "Part 2… exp dates, strike prices, positions sizes, trimming" promised twice, never found (`X/2025-08-09…`, `X/2025-10-18…`) | EXEC (7 priced examples), no RULE | Closest live ask to `target_premium` 0.60 inside [0.20, 0.90] (`rules.py:87-90`; band = target × `MAX_OVER_TARGET` 1.5, `T2/premium.py:25`; live picker `runner.py:581-690`) | INFERRED (METHOD §0b item 2 says "OUR expression… not a quoted rule") | Medium: 0.60 is the top of his observed range, not the centre; IWM example is 0.20 (= our floor). |
| Strike distance | SPY ~$2 OTM (0.3 %), QQQ 472p $8.5 OTM, QQQ 480c $6.4 OTM, SPY 505p $17 OTM; 2026-09-10 IWM 288P "slightly ITM under 287.83" (week-37 note §2.4) | EXEC | OTM only: strictly beyond spot (`runner.py:621`); distance falls out of the premium target | UNRESOLVED (no rule; one ITM counter-example) | Low/medium. |
| Never chase | "We're not chasing" — 2022 video 03:17 (about the underlying) | RULE (underlying, not the option) | Entry limit = min(ask + 1 tick, 0.90) and cancel if unfilled (`runner.py:192-204`) | INFERRED | Low. |
| Costs | none found (his cards are Webull US) | NONE | `fee_per_contract` 1.04 per side (`rules.py:113`); 2026-09-18 IWM: gross −$120.40, commissions $83.20 on 40 contracts (Codex recap) | Ours (venue fact) | High as a structural drag: ~$2.08 round trip per contract is ≈4 % of a $0.50 premium; a quick −6 % stop becomes −10 %. Not a method divergence, but it changes which of his behaviours (fast scratch exits) are affordable. |

## G. Sizing

| Behavior | What the author documents | Evidence | What our code does | Label | Divergence risk |
|---|---|---|---|---|---|
| Size by location | "Its a loose guide of how I want to approach sizing" — `X/2025-08-31…`; image: Full / Small / No trade zone | RULE (loose) + CHART | `size_full` 1.0, `size_small` 0.5, `size_none` 0 (`rules.py:102-104`) | Buckets SUPPORTED; 0.5 and the hard zero INFERRED | Medium. |
| Number of contracts / risk per trade | +$4,389.61 at +166 % on a $0.55 contract ⇒ ≈ 48 contracts (our arithmetic, METHOD V10); podcast 45:22–45:58 "$200 / $750 / $1,000" risk figures (speaker attribution uncertain, `DOC/AUTHOR-STUDY.md` §8); "Start small and aim for consistency" — `X/2025-03-15…`; account size: not found | 1 EXEC data point; otherwise NONE | Risk-based: contracts = equity × `risk_pct` 6 % ÷ (ask × 100 × 25 %), × bucket, capped by `budget_per_trade` $2,000 and the 0DTE policy `max_contracts` 40 (`settings_service.py:133-134,197-199`; `planrunner.py:2937-2996`). On a $10k book a $0.49 contract → 40 contracts ≈ $1,960 premium ≈ 20 % of the book per entry | INFERRED entirely | High: sizing is ours. 6 % risk per attempt with up to 3 attempts per setup and a 2-loss cap is an aggressive profile his material does not document. |
| Shrink after a win | "there's no reason to risk 750 bucks on this next trade… I'll risk 200" — podcast 45:22 (auto-transcript, speaker unlabeled) | RULE (weak attribution) | `shrink_after_win`: size × 0.5 once the MODEL's day P&L % is positive (`session.py:670-671`) | INFERRED formula | Low/medium. |
| Too small to trim | none | NONE | < 3 contracts: first trim skipped, second level closes all (`runner.py:1882-1898`) | INFERRED | Low at current size. |

## H. Stops (what invalidates a trade)

| Behavior | What the author documents | Evidence | What our code does | Label | Divergence risk |
|---|---|---|---|---|---|
| Structural stop on a 2m close | "Stop loss is a 2 minute candle close under that PMH level" — `X/2026-04-17…`; "I stop out if the 13 EMA does not hold" — `X/2025-05-17…`; 2022 video 08:55 "a candle close above this 13 EMA" | RULE + CHART (`IMG` 1964745969930817924-1 red box = one candle closing under EMA13; SPY 12:50 "1 candle lost") | First 2m CLOSE through the guard line: current EMA13 (or EMA48 / EMA200 / the setup anchor, by entry kind) → exit 100 % at market (`session.py:425-435`; `runner.py:1689-1734`, `force_market` for stops) | SUPPORTED | See §2 — the rule is his, the zero tolerance and the entry-after-the-close combination are ours. |
| One candle, or two? | "only risk a candle or 2 beyond that level before I cut the trade" — `X/2025-08-31…` | RULE | Always exactly one close, no tolerance, no second-candle grace (`stop_candles: 1 … informational (always one)`, `rules.py:60`) | UNRESOLVED (he says both); we took the tighter | High given our results (7 of 7 stopped in 2–8 min): "a candle or 2" and reported −20…−40 % losses imply he tolerates more adverse movement than a first marginal close. |
| Which line for an EMA entry | "keep your stop on the other side of it [the EMA]" — `X/2025-05-03…` | RULE | The LIVE EMA13 value on each bar — it moves toward price every bar; a flat flag lasting 2–4 bars is closed through by the rising/falling EMA (`session.py:427-429`) | SUPPORTED literally | Medium/high: see §2 hypothesis. |
| Premium hard stop | "running hard stops… usually around the 20% max loss mark" — podcast 16:19 (2023); 2025: "4 losses that ranged between -20% & -40% depending on how quickly I exit" — `X/2025-03-15…`; 2024-10: "typical stop outs under the EMA, −20/30%" (`IMG` 1844848069504020557-1) | RULE (2023) + aggregate self-report | Two premium stops: (a) MODEL premium ≤ −25 % at a 2m close (`premium_stop_pct` 25, `session.py:422-424`); (b) LIVE contract mid ≤ paid × 0.75 (never tighter than 3 ticks), two distinct fresh quotes ~2 s apart, market sell (`planrunner.py:835-884`, `exits.py:125-149`, `settings_service.py:170-171,183`) | 20 % historical SUPPORTED; 25 %, mid basis, tick floor, 2-poll confirmation INFERRED | Medium: the model stop (a) is measured from a hypothetical fill at the EMA price with flat-IV Black-Scholes, not from our real fill — it can sell a live position on a number that is not the contract's. |
| Intra-bar crash stop on the underlying | none | NONE | Underlying last beyond (guard ∓ 1 ATR) by a further 0.25 × risk for 2 polls → market exit (`runner.py:1607-1620`, `exits.py:105-122`, `planrunner.py:894-908`) | INFERRED (safety) | Low. |
| Time stop | "you can't be holding through a half an hour of chop" — podcast 14:32 | RULE (soft) | None other than the 15:45 flatten | UNRESOLVED | Low/medium. |
| Conviction holds | 2026-09-03: "I was up 25 to 30% on both and I told everyone I wasn't gonna sell for small gains" — then stopped out of both — `X/2026-09-03…` | EXEC | No discretion; no break-even logic ("never let the trade go red after this point", week-37 note §2.5, is NOT built — C5 undefined) | UNRESOLVED | Medium. |

## I. Profit taking

| Behavior | What the author documents | Evidence | What our code does | Label | Divergence risk |
|---|---|---|---|---|---|
| First trim cue | "My first target after entry is always that push to new highs / lows" — `X/2025-05-03…`; "New low of day is a great spot to lock in gains" — `IMG` 1810706353427771759-1; "high of day break is always a big trim" (week-37) | RULE + EXEC | `trim_cue="premium"`: +50 % on the contract's live BID, fee-adjusted, checked every 1m bar (`runner.py:1866-1924`); `new_extreme` cue built, OFF (`rules.py:53`) | Cue INFERRED as premium-only (he cues on price structure; % is how he reports it) | Medium: at +50 % net of fees on the bid, many base hits he books ("+35 %", "+40 %" in `X/2025-03-15…`) never reach our first trim and ride back to the stop. |
| Trim levels | "scaled out at 50% and 100%" — `IMG` 1961977219590574391-1; "first trim at 90%, then fully out at 130%" (METHOD X4) | EXEC (2 examples, different ladders) | +50 % / +100 %, one third each (`rules.py:62-65`) | Levels weakly SUPPORTED (one example); fractions INFERRED ("trimmed a bunch", "trim heavy" suggests more than 1/3) | Medium. |
| Runner exit | "using the 13 EMA break as a visual for a trailing stop on runners" — `X/2025-05-03…`; "13 EMA break is my stop on the runners" (week-37) | RULE + EXEC | 2m close through the ENTRY-KIND guard (EMA13 only for `ema` entries; a level/EMA48/EMA200 entry trails its own line) (`session.py:427-435`; "`runner_exit`… knob is informational", `rules.py:66`) | SUPPORTED for EMA13 entries; INFERRED for the others (AUTHOR-STUDY §10 flags this) | Medium: a level-retest runner trails the LEVEL, giving back far more than his EMA13 trail. |
| Sell at target | "selling here at my target" (QQQ 603.19) — `IMG` 1979379268410130815-1; "target hitting here guys. I just sold the rest" — `IMG` 1908549474886312373-1 | EXEC | `target_exit` True: 100 % of the remainder on the first touch of the target (2m high/low in the model, first live print in the book) (`session.py:409-420`, `runner.py:1848-1864`) | SUPPORTED — but he sells "the rest" after trims; we sell everything even if no trim happened | Medium: with pivot targets that can be near, this converts would-be runners into small full exits. |
| Discretionary big exits | "that's enough for me, I'm selling mine" at +474 % — `IMG` 2095671547184988332-1; "sold into strength when I thought we were extended from the 13 EMA" — `IMG` 1905768108352250355-1 | EXEC | No "extended from EMA13" exit | Author behavior MISSING | Low/medium. |
| Trim then re-add | "I like to get a bunch trimmed on that first push so I can free up room for adds" — `IMG` 1979379272990277934-1 | EXEC (one example) | `add_on_retest` True, `max_adds` 1 (`rules.py:82-83`) | One example generalised: INFERRED | Low. |

## J. Re-entry / attempts per day

| Behavior | What the author documents | Evidence | What our code does | Label | Divergence risk |
|---|---|---|---|---|---|
| Re-entering the same idea | "Today I stopped out of both these entries on $SPY calls before hitting the trade that ran 10x" — `X/2026-09-03…`; IWM 3 entries in one trend (`IMG` …818163982-1) | EXEC | Up to 1 + `max_reentries` 2 = 3 entries per setup (`rules.py:105`, `session.py:667-669`) | SUPPORTED in kind | — |
| Trades per day | "I average 1-3 trades per day" — `X/2025-01-30…`; "I'm looking to take five or less" — podcast 29:45; "1 or 2 trades a day is more than enough" — `X/2025-05-03…` | RULE | No explicit trade-count cap; bounded by the loss cap, 1 concurrent position, touches | SUPPORTED loosely | Low. |
| One position at a time across SPY/QQQ/IWM | not found | NONE | `max_concurrent_positions` 1 per book (`rules.py:108`, `runner.py:1575-1589`) | INFERRED | Medium: 2026-09-16 IWM 10:02 was refused for concurrency (TRADING-RULES 2026-09-16 EOD). |

## K. Time-of-day windows and flatten

| Behavior | What the author documents | Evidence | What our code does | Label | Divergence risk |
|---|---|---|---|---|---|
| Earliest entry | "before 10 a.m.… a little riskier, but if the setup's there I'll still take it" — podcast 15:12–15:25; EXEC entries 09:41 (2026-09-09), ~09:45 (2024-07-09), 09:46 (2026-09-11), before 09:52 (2026-09-03) | RULE + EXEC | No entry before a 2m bar closing ≥ 09:45 AND after a 15m close created a setup (`rules.py:54`, `session.py:483`); `early` tag only (`rules.py:57`) | INFERRED gate (follows from the 15m rule, which his own fills sometimes precede) | High — see C row 2. |
| Lunch / afternoon | "I don't have like a no trade time" — podcast 15:06; EXEC 13:24 SPY 648c, ~14:00 IWM 288P | RULE + EXEC | No lunch block | SUPPORTED | Low. |
| Last entry 15:30 | not found | NONE | `last_entry_min` 15:30 (`rules.py:55`; RiskGate policy `settings_service.py:133-134`) | INFERRED | Low/medium: 2026-09-18 QQQ late bull flag (author CHART) overlapped our cutoff/loss-cap refusal (Codex recap) — relationship not established. |
| Flatten 15:45 | not found ("These statements do not establish… an author rule to flatten at precisely 15:45" — AUTHOR-STUDY §8) | NONE | `flatten_min` 15:45, market (`rules.py:56`, `runner.py:1758-1786`) | INFERRED (0DTE safety) | Low. |

## L. Loss limits per day

| Behavior | What the author documents | Evidence | What our code does | Label | Divergence risk |
|---|---|---|---|---|---|
| Max losing trades per day | None found. Counter-evidence: 2026-09-03 two stop-outs, then a third entry that paid +537 % | EXEC | `max_losses_per_day` 2, counted per book across SPY+QQQ+IWM from real closed losers (`rules.py:106-107`, `runner.py:1557-1572`, `1987-2018`) | INFERRED — and contradicted by his best-documented day | **Highest**: under our cap the 2026-09-03 third entry is refused if the first two closed red (their P&L at the stop is not stated — they were +25/+26 % before stopping). 2026-09-18: our QQQ bullish read was refused under this cap (Codex recap). |
| Daily dollar/percent halt | none | NONE | `daily_loss_halt_pct` 10 % of the book pauses Team2's plans (`settings_service.py:200`) | INFERRED | With 6 % risk per entry, ~2 stops. |
| Red days | "Yes, of course I have red days" — `X/2025-01-30…`; a red-day post dated 2026-09-17 exists (status 2100672806392623545; content NOT captured) | EXEC exists, not captured | — | — | We have no record of what he does after a red day. |

---

## 1. Author's documented trades, losses and no-trade days

Every dated instance found. "Card" = a broker (Webull) P&L card described in `IMG`. Times ET. An annotated chart is NOT
an execution. Dates in italics are inferred from the contract expiry on the card or from our own notes.

| # | Date | Sym / dir | What is documented | Entry | Contract | Size | Exit / P&L | Hold | Class | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2022-10-14 (Fri) | AMD puts | Narrated recap: missed flag entry, entered on EMA13 pullback; stop "a candle close above this 13 EMA" | not given | not given | n/f | "contracts went about 90… nearly a hundred percent"; runner "stopped us out" on the EMA13 close | n/f | CHART (narrated, no fill) | `DOC/notes/video/2022-10-17-…md` 06:30–10:00 |
| 2 | 2022-10-14 | QQQ puts | Waited ~10 min for a 48 EMA test under PML; entered on the candle close | not given | n/f | n/f | "This move right here was 100%" | n/f | CHART (narrated) | same, 10:45–13:40 |
| 3 | 2022-11-04 | AAPL short | "350% $aapl trade review" | n/f | n/f | n/f | +350 % claimed | n/f | claim only | `X/2022-11-05…` |
| 4 | 2023-02 (week) | QQQ | "Catching 100% move up into Zone 4, then a 400% move on the rejection" | n/f | n/f | n/f | claims | n/f | CHART + claim | `X/2023-02-18…` |
| 5 | 2023-12-08 | IWM calls, AAPL | "+100% on $IWM, +50% on $AAPL" | n/f | n/f | n/f | claims | n/f | CHART + claim | `X/2023-12-10…` |
| 6 | 2024-05-24 | QQQ long | Inside day; PMH broke "about 30 minutes into today's session"; "charts and trades that I personally alerted" | ~10:00 | n/f | n/f | n/f | n/f | CHART | `X/2024-05-24…` |
| 7 | *2024-07-09* | IWM puts | Plan 201.84 → 199.88; "I'm adding IWM 201p @ .20" on the retest (box 09:38–09:50); trim at new LOD "everyone should be up 100%"; card +157.50 % 10:32 "down to runners" | ~09:45 | IWM 201P 0DTE, ~$1 OTM, $0.20 | n/f | +100 % trim; +157.5 % at 10:32, runners still open | ≥ ~45 min | **EXEC** (card) | `IMG` 1810706353427771759-1 |
| 8 | 2024-10 (one week) | mixed | "10 alerts, 7 W / 3 L"; wins +330/+200/+80/+130/+100/+100/+150 %; losers "typical stop outs under the EMA, −20/30%" | — | — | — | aggregate | — | self-reported aggregate (LOSSES: 3, no detail) | `IMG` 1844848069504020557-1 |
| 9 | 2025-01 (month) | mixed | "35 trades… 28 wins, 7 losses… didn't have a single [red day]"; one "easy 150%+ trade" on a PDH retest | — | — | — | aggregate | — | self-reported aggregate | `X/2025-01-30…` |
| 10 | *2025-03-10* | QQQ puts | 10:05 "watching puts on the retest of 480.53"; 10:15 "I'm taking QQQ 472p @ .55"; card +166.07 % 10:57; **P&L +$4,389.61**; "scaled out on the way down and sold into strength" | 10:15 | QQQ 472P 0DTE, $8.5 OTM, $0.55 | ≈48 contracts (our arithmetic) | +166 %, +$4,389.61 | 42 min | **EXEC** (card + $) | `IMG` 1905768108352250355-1 |
| 11 | 2025-03-11 | index puts | "the main example in this thread is from today": PDL break, bearish stack, flag into EMA13 | n/f | n/f | n/f | n/f | n/f | CHART | `X/2025-03-11…` |
| 12 | 2025-03 (month) | mixed | 03-15: 18 alerts 14 W / 4 L, wins +35…+210 %, "4 losses that ranged between -20% & -40%"; 03-28: 31 trades 26 W / 5 L, "Account up a respectable 140%" | — | — | — | aggregate | — | self-reported aggregate (LOSSES: 4–5, size only) | `X/2025-03-15…`, `X/2025-03-28…` |
| 13 | *2025-04-02* | QQQ calls | "I'm taking QQQ 480c" ~11:55 on a 13/48 EMA pullback; 13:14 "sold the rest of mine for 350%"; card +361.36 % | ~11:55 | QQQ 480C 0DTE, $6.4 OTM, premium n/f | n/f | +350 % | ~79 min | **EXEC** (card) | `IMG` 1908549474886312373-1 |
| 14 | *2025-04-04* | SPY puts | Crash day; "taking some more SPY 505p here" (SPY ≈ 522); card +424.51 %; "sold for 400%" 10:51 | n/f (adds) | SPY 505P 0DTE, $17 OTM | n/f | +400 % | n/f | **EXEC** (card) | `IMG` 1908549478438887528-1 |
| 15 | 2025-04 (week) | IWM puts | "+100% on some $IWM puts" | n/f | n/f | n/f | claim | n/f | claim | `X/2025-04-05…` |
| 16 | 2025-04-24 | SPY calls | Scenario 3, EMA13 pullback; "1 candle risk, 10+ candle reward" | n/f | n/f | n/f | n/f | ≥20 min implied | CHART | `X/2025-04-24…` |
| 17 | 2025-06-13 (approx.) | QQQ calls | "my last trade of the week… a few nice dip buying opportunities" | n/f | n/f | n/f | n/f | n/f | CHART | `X/2025-06-15…` |
| 18 | *2025-08-07* | SPY puts | Bear flag at PDH; "if we hold the 13ema and break this flag I'll be looking at 631p"; "all loaded up with .50 average"; continuation to 631.13 | 10:36 (scaled in) | SPY 631P 0DTE, ~$2.5 OTM, $0.50 avg | n/f | exit n/f | n/f | EXEC (entry only; no exit/P&L) | `IMG` 1953540502995055061-2 |
| 19 | 2025-08 (2nd half) | SPY calls | 12:50 entry at EMA13 → **"1 candle lost"**; re-entry 13:28 after a 48 EMA bounce → ran to 649.25 | 12:50 / 13:28 | n/f | n/f | loss size n/f | loser: one 2m candle | CHART (**LOSS**, annotation) | `IMG` 1961977214620348801-1 |
| 20 | 2025-08 (same week; probably the same day as #19 — not verified) | SPY calls | 13:24 "I'm taking some SPY calls here… 648c @ .54"; "scaled out at 50% and 100%"; 14:33 "100% on these runners, I'm selling them" | 13:24 | SPY 648C 0DTE, ~$1 OTM, $0.54 | n/f | +50 % / +100 % trims, runners +100 % | 69 min | **EXEC** (alert prices; card not mentioned) | `IMG` 1961977219590574391-1 |
| 21 | 2025-08 (2nd half) | IWM calls | Entry 1 at EMA13 **fails**, entry 2 at EMA48 wins, entry 3 at 13/48 wins; "high of day resistance is the main target" | n/f | n/f | n/f | n/f | n/f | CHART (**LOSS**, annotation) | `IMG` 1961977216818163982-1 |
| 22 | 2025-08 (2nd half) | PMH break & retest ×2 | "Faked out on 1, got the move on the other… Moderate position sizing" | n/f | n/f | "moderate" | n/f | n/f | CHART (**LOSS** mentioned) | `X/2025-08-31…` |
| 23 | *2025-08-26* | QQQ calls | "calls on the break & retest of PMH"; ".31 average now… if that breaks I'm out"; 12:17 "new high of day and up over 100%"; card +111.29 % | n/f (averaged) | QQQ 572C 0DTE, $0.31 avg | n/f | +111 % | n/f | **EXEC** (card) | `IMG` 1961977219590574391-2 |
| 24 | *2025-08-27* | QQQ calls | "I'm taking QQQ 574c… that break & base over pre market high is so nice"; ran to 573.29 | n/f | QQQ 574C 0DTE | n/f | n/f | n/f | EXEC (entry only) | `IMG` 1961977219590574391-3 |
| 25 | *2025-10-17* | QQQ calls | Plan 595.50 → 603.19 → 608.31; "looking at the 606c if we get this 15 minute candle close above pre market high"; entry on PMH 599.52 + EMA13 retest; 10:16 "selling here at my target"; card +118.03 %; "called it a day by 11am" | ~10:04 | QQQ 606C 0DTE, $6.5 OTM | n/f | +118 % at target | 12 min | **EXEC** (card) | `IMG` 1979379268410130815-1; `X/2025-10-18…` |
| 26 | 2025-10 (date not stated in `IMG`; METHOD T8 says 10-17) | SPY puts | 15m sweep of PDH, bearish cross, "break of 200 EMA support as my trigger"; "I'm taking SPY 671p"; "trimmed a bunch"; "re-upped a full position… up 100%"; PML final target; 10:57 "cashing out" | n/f | SPY 671P 0DTE | "full position" re-up | ≥ +100 % | n/f | EXEC (alert text; card not mentioned) | `IMG` 1979379272990277934-1 |
| 27 | *2026-04-17* | SPY calls | 10:10 "wait for the 15 minute close then look at the 711c"; "I'm taking SPY 711c @ .60" on PMH 708.79 + EMA13 retest; 10:46 "pushing ITM and up over 120%. I'm selling"; card +122.41 % | ~10:10+ | SPY 711C 0DTE, ~$2 OTM, $0.60 | n/f | +122 % | ≤36 min | **EXEC** (card) | `IMG` 2081050846666891284-1 |
| 28 | *2026-07-14 (date inferred; SPY traded near 750 in July 2026, so a 624 call cannot be this date: the year is wrong, probably 2025)* | SPY calls | Gap into 620.91 zone, bounce, "multiple 15 minute rejections at pre market high — wait for the break"; "buying the 13 EMA pullbacks"; SPY 624c at 0.50 with repeated dips/adds; PDH 624.86 reached | n/f | SPY 624C, $0.50 | n/f (adds) | n/f | n/f | EXEC (entry price only) | `IMG` 2081050843768660321-1; 09-08 evidence ledger (HOFXNMBbEAAemSh) |
| 29 | *2026-09-01* | IWM puts | PDL break; card IWM $292 Put +474.14 %; "that's enough for me, I'm selling mine" 12:34 | n/f | IWM 292P 0DTE, ~ATM | n/f | +474 % | n/f | **EXEC** (card) | `IMG` 2095671547184988332-1 |
| 30 | 2026-09-03 | SPY calls ×3 | 08:45 plan "768.00 zone… room up to 775.29". Cards: 771c +25.00 % (09:52), 770c +26.14 % (10:24) — **both later stopped out**; third "I'm taking SPY 770c" ~11:00 on the 768 retest; 11:19 "selling right now for over 500%" (+536.99 %) | <09:52, <10:24, ~11:00 | SPY 771C / 770C 0DTE, ~$2 OTM | n/f | two stop-outs (P&L at the stop NOT stated); +537 % | winner ~19 min | **EXEC** (3 cards; **2 stopped attempts**) | `X/2026-09-03…`; `IMG` 2095571390321865119, 2095599035113693522 |
| 31 | 2026-09-04 | — | Reflection post: acknowledges losses, missed moves, imperfect exits in a profitable week (content summarized, not captured) | — | — | — | — | — | statement | 09-08 evidence ledger |
| 32 | 2026-09-08 | — | **"I did not trade yesterday"** (posted 09-09). Reason: not found | — | — | — | — | — | **NO-TRADE DAY** | week-37 note §1–2 |
| 33 | 2026-09-09 | IWM puts | 293P "on the 09:41 retest of a 3-day support 293.43"; targets PML 291.19 → 289.98; +141.77 %; rolled to a lower strike at the PML flip (+65 %) | 09:41 | IWM 293P 0DTE | n/f | +141.77 %, then +65 % | n/f | EXEC per our note (posts + local charts; not re-verified here) | week-37 note §1 |
| 34 | 2026-09-10 | IWM puts | Waited "almost 5 hours"; 288P ~14:00 on the retest of 287.83 after the 15m body close under it | ~14:00 | IWM 288P 0DTE, slightly ITM | n/f | +85 % / +100 % | n/f | EXEC per our note | week-37 note §1, §2.4 |
| 35 | 2026-09-11 | SPY calls | 768C "at the 09:46 2m close", EMA13 pullback holding 764.47; trim at HOD break 766.37 (+50 %); runners stopped on the EMA13 break; **+$801**; "1 and done Friday" | 09:46 | SPY 768C 0DTE | "entered some calls… wanted another retest… to add full position" (partial size) | +50 % trim, +$801 total | n/f | EXEC per our note ($ stated) | week-37 note §1, §2.5–2.7 |
| 36 | 2026-09-17 | — | A "red-day post" exists on the profile (status 2100672806392623545). **Content not captured.** | — | — | — | — | — | **LOSING DAY, undocumented** | Codex recap 2026-09-18 |
| 37 | 2026-09-18 | IWM puts | Educational chart: PDL 285.28 flips to resistance, PML 284.19 breaks, bearish stack; entry illustrated at the EMA13 pullback / bear-flag break "around 09:46–09:52"; scale out into new lows; runners stopped on the EMA13 break; low ≈282.7 then rebound 10:12–10:20 | chart arrow only | none stated | none | none stated | — | CHART ("not a broker execution record") | Codex recap 2026-09-18 |
| 38 | 2026-09-18 | QQQ calls | PDH 718.04 break, bullish stack, bull flag 719.1–719.6, late rally above 721 | — | — | — | — | — | CHART | Codex recap 2026-09-18 |

Undated but documented: the 2025-09-07 "entering near my stop levels" QQQ slide (CHART, `IMG` 1964745969930817924-1);
the four PMH and four PML examples in `X/2026-07-25…` (CHART); the TSLA walkthrough in the 2022 video (hypothetical).

**Counts**
- EXEC with a broker card: **9 trade-days, 11 cards** (#7, 10, 13, 14, 23, 25, 27, 29, 30 ×3). All 9 days ended as winners.
- EXEC by alert text / our own note without a card described: **8** (#18, 20, 24, 26, 28, 33, 34, 35). All winners or exit unknown.
- CHART / narrated / claim only: **13** dated rows (#1–6, 11, 15–17, 19, 21, 22, 37, 38 — some rows hold several charts).
- Self-reported aggregates: 3 (#8, 9, 12).
- **Individually documented losing trades: 5** — two 2026-09-03 stop-outs (EXEC, loss size not stated), SPY 12:50
  "1 candle lost" (CHART), IWM entry 1 (CHART), "faked out on 1" (CHART). **Zero losing trades have a stated entry
  price, exit price, premium loss or hold time.** Aggregate loss sizes: −20/30 % (2024-10), −20…−40 % (2025-03).
- No-trade days: **1** (2026-09-08, reason not found). Losing days: **1** known to exist (2026-09-17, not captured).
- Priced entries: 7. Entries with a known time: 10. Trades with a dollar P&L: 2 (#10, #35). Trades with a stated size: 0.

Selection bias is total: he publishes what he chooses. The sample cannot estimate a win rate, a loss distribution or a
hold-time distribution for losers.

---

## 2. Hold time and stop behavior

### What the author says and shows

Hold time, winners (EXEC): ≥45 min (IWM 2024-07-09, still holding runners), 42 min (QQQ 472p), ~79 min (QQQ 480c),
69 min (SPY 648c), ≤36 min (SPY 711c), 12 min (QQQ 606c, sold at target), ~19 min (SPY 770c third attempt). Stated range:
"there can be like just a couple of two-minute candles… the long ones can run like up to an hour or two" and "I'm a
scalper" (podcast 15:40–16:00). "you can't be holding through a half an hour of chop" (podcast 14:32).

Hold time, losers: only "1 candle lost" (one 2m candle, CHART) and the teaching pictures ("The loss is restricted to 1
candle, while the win is able to run for multiple" — `X/2025-05-03…`). The 2026-09-03 stopped attempts were held long
enough to be +25 % and +26 % first (cards at 09:52 and 10:24) — minutes to tens of minutes, not stated.

What makes him exit a loser — four different statements that do NOT reduce to one rule (METHOD §0b item 4 agrees):
1. Structural, 2m close: "Stop loss is a 2 minute candle close under that PMH level" (`X/2026-04-17…`, the only
   explicit stop rule in a post); "I stop out if the 13 EMA does not hold" (`X/2025-05-17…`).
2. Looser: "only risk a candle or 2 beyond that level before I cut the trade" (`X/2025-08-31…`).
3. Level as the line for a retest/base entry: ".31 average now — testing that pre market high again; if that breaks
   I'm out" (`IMG` …590574391-2) — note he was AVERAGING IN while price sat at the level.
4. Premium: "hard stops… usually around the 20% max loss mark… If it goes below that you pretty much have to accept
   that you timed it wrong" (podcast 16:19–16:41, 2023). Realised: "−20% & −40% depending on how quickly I exit upon my
   stop level breaking" (`X/2025-03-15…`); "typical stop outs under the EMA, −20/30%" (2024-10).

Read together: his typical LOSER costs 20–40 % of premium. **Our seven round trips lost 3–25 % in 2–8 minutes.** Our
losers are smaller and faster than anything he reports, which says our exits fire earlier in the adverse move than his
do — we are scratching trades he would still be in (and paying ≈4 % of premium in commissions each time).

### How our stop works, precisely

An open position is judged in this order on each 2m close in the pure read (`T2/session.py:398-480`), and
independently every ~2 s by the shared quote watch. Any one of these closes 100 % of the remainder:

| # | Stop | Bar / clock | Close-based or touch | Level | Order | file:line |
|---|---|---|---|---|---|---|
| 1 | Flatten | 2m close with m+2 ≥ 15:45; plus a wall-clock flatten on every 1m bar ≥ 15:44 | clock | — | market | `session.py:405-407`; `runner.py:1396-1397`, `1758-1786` |
| 2 | Target | model: 2m bar HIGH/LOW touches; book: first fresh underlying print ≥/≤ target | **touch** | plan target / HOD-LOD / re-planned level | reduce-only limit at the contract's bid, re-priced to market if stuck | `session.py:409-420`; `runner.py:1848-1864`; `planrunner.py:885-893` |
| 3 | **Model premium stop** | 2m close | close (of the underlying), priced by the MODEL | modelled Black-Scholes premium (flat session IV, −1 tick) ≤ −25 % versus a **hypothetical entry at the EMA/level price** (`entry_spot`), not our fill | market (`force_market`) | `session.py:401-402, 422-424`; entry basis `session.py:600-609, 816-823`; `runner.py:1689-1734` |
| 4 | **One-candle structural stop** | 2m close | **close-based, zero tolerance** | `ema` entry → the CURRENT EMA13; `ema48` → current EMA48; `ema200` → current EMA200; `level`/`base` → the setup anchor. After any trim the same test is labelled the runner exit | market | `session.py:425-435`; `_kind_for` `runner.py:54-68` |
| 5 | **Live premium stop** | ~2 s poll (`quote_exit_seconds` 2.0) | quote-based, needs **2 distinct fresh real-time option quotes** | contract **mid** ≤ min(paid × 0.75, paid − 3 ticks); on a $0.49 fill that is 0.3675 | market | `planrunner.py:835-884`; `exits.py:125-149`; `settings_service.py:170-171, 183, 566-568` |
| 6 | **Underlying crash stop** | ~2 s poll, 2 consecutive polls | quote-based (underlying last) | trade.stop = guard ∓ 1 × ATR(2m); fires when last is a further 0.25 × |entry−stop| beyond it (≈ guard ∓ 1.25 ATR) | market | `runner.py:1607-1620`; `exits.py:105-122`; `planrunner.py:894-908` |

The earliest a position can be stopped is the 2m close after the entry bar (2 minutes). There is no minimum hold, no
second-candle grace, no tolerance band on the stop (the ENTRY touch has a 0.25-ATR tolerance, `session.py:543-547`; the
stop has none, `session.py:429`), no break-even logic, no partial stop.

### Why 2–8-minute stop-outs at −3…−25 % are the expected output of these rules (reasoned from the code; NOT traced on the seven fills)

1. The entry condition guarantees price is sitting ON the stop line: the fire bar must have reached within 0.25 ATR of
   the EMA13 and closed just back on side (`session.py:547`). The stop is a close through that same line. The distance
   between entry and invalidation is, by construction, a fraction of one 2m ATR.
2. The live order goes out AFTER that close, at the contract's ask (+1 tick, capped at $0.90), while the read assumes a
   fill at the EMA price. On a long, the live fill happens at a HIGHER underlying than the model's (the close of the
   bounce bar or later), yet the stop line is the EMA either way: a mere return to the EMA is already a mark-down on
   the live contract, while the model still reads about 0 %.
3. The guard for an EMA entry is the MOVING EMA13. In a consolidation (the bull/bear flag he waits for) the EMA13
   converges on price within 2–4 bars, so a sideways flag that closes one cent through it exits the trade — consistent
   with "all within 2–8 minutes". He describes buying flags INTO the EMA and watching the 48 as the "second line of
   defense" (`X/2025-04-27…`); our EMA13 entry never gets that second line.
4. A −3 % to −25 % realised loss means rule 4 (structural close) fired long before either premium stop could (−25 %).
   His reported −20…−40 % says his real exits happen later in the adverse move than a first marginal close.
5. Rule 3 can also fire on a number that is not ours (model premium from a hypothetical EMA-price entry).

Which of the seven were closed by rule 3 vs rule 4 vs rule 5 was NOT checked here (no database access); the 2026-09-16
EOD entry records "two QQQ stop-outs at 10:00 and 10:08" and 2026-09-17 "one QQQ 717C round trip of 16.8 s at
$0.69/$0.69" (a target collision, since fixed) — `DOC/TRADING-RULES.md:3156, 3228`.

---

## 3. Assumptions we introduced (no author support), most suspicious first

1. **Two-loss daily cap, desk-wide (`max_losses_per_day` 2, `losses_desk_wide`)** — `rules.py:106-107`,
   `runner.py:1557-1572`. No author source; his best-documented day (2026-09-03) is two stop-outs followed by the +537 %
   third entry. The cap converts "two small scratches" into "done for the day" and is exactly what refused our QQQ read
   on 2026-09-18. Combined with #2 (scratches are frequent) it is the most direct way the desk locks in small losses and
   forfeits the payer.
2. **Zero-tolerance, single-close, full-size stop on the moving EMA13, paired with an entry that fires only after the
   bounce bar has closed on that same line** — `session.py:425-435, 547`. The close rule is his; the zero tolerance, the
   absence of "a candle or 2", the absence of the EMA48 as a second line for an EMA13 entry, and entering after the
   close rather than at the touch are ours. Observed result: 7/7 stopped in 2–8 min at −3…−25 %, versus his −20…−40 %.
   With $2.08 round-trip commission per contract every scratch is materially negative.
3. **No setup ageing; refused contacts do not spend the two-pullback allowance** — `session.py:509, 593-599, 814`. His
   edge statement is the FIRST pullback after the break (podcast 39:08) and a warning about late bounces near
   resistance (39:42). Ours can take "touch #1" twenty minutes and several real pullbacks later (2026-09-18: 10:12 fill
   vs his ~09:46–09:52 illustration, into the rebound).
4. **The 09:45 gate + mandatory 15m close for every entry** — `rules.py:54`, `session.py:483`. His own fills at 09:41,
   ~09:45, 09:46 and before 09:52 show early retest entries; on those mornings we start after the first leg.
5. **V6 "no-trade zone" as a hard ban on any entry price inside PMH–PML, including gap days** — `scenario.py:59-73`.
   His words: "loose guide", "not a hard rule for me", "some exceptions"; two of three week-37 winners were inside it;
   we measured 59 % of RTH minutes blocked. (Counter-risk: he also says the PM range is chop; lifting it adds trades of
   unknown quality — the conjunction variant is an untested middle.)
6. **Entry levels limited to yesterday's zone and today's PM lines** — author anchors on multi-day levels (three of
   three week-37 trades). Missing capability rather than a wrong number, but it decides whether we see his trade at all.
7. **Sizing: 6 % of equity at risk per entry, ≈20 % of the book in premium, 40-contract cap, full size on bar one** —
   `settings_service.py:133-134, 197-199`, `planrunner.py:2937-2996`. Nothing in his material gives account-relative
   risk; his documented practice is partial entries averaged in at the level (".31 average", ".50 average", "add full
   position" on a second retest). Full size at once maximises both commission drag and the cost of rule #2's scratches.
8. **Full exit of the whole remainder at the first touch of a pivot target** — `session.py:409-420` with targets from a
   window-2 pivot search (`T2/levels.py:19-29`). He sells "the rest" at target AFTER trimming and re-targets the next
   zone on a break; we close everything, even untrimmed, at what can be a weak nearby pivot (2026-09-08: target one
   strike away, 2–4-minute fee-negative exits).
9. **First trim only at +50 % fee-adjusted on the live BID** — `runner.py:1866-1924`. His cue is structural (new
   high/low of the move) and his published win list includes +35 %, +40 %, +60 %, +75 %. Between our entry and +50 % on
   the bid nothing is booked, so base hits round-trip to the structural stop.
10. **Full ordered EMA stack as a hard entry gate; 0.60-ATR fan threshold** — `session.py:535-537`, `rules.py:32`. His
    ladder calls "above the 200" already bullish; his SPY 671p entry had 48 > 200. The stack gate can delay entries
    after gaps/reversals; the fan threshold is probably too loose to filter chop at all. Direction of the P&L effect
    unknown.
11. **Model premium stop measured on a modelled contract from a hypothetical fill** — `session.py:401-424`. Can
    market-sell a live position on a number unrelated to the contract held.
12. **Premium-targeted strike at $0.60 (closest), OTM-only, band 0.20–0.90** — `rules.py:87-90`, `runner.py:621`. His
    seven priced entries run 0.20–0.60 (median ≈0.54); 0.60 is the top of his range, and he has used a slightly ITM
    strike. Cheaper/farther vs dearer/nearer changes gamma, spread cost and how a one-candle adverse move prices.
13. **One concurrent position across SPY/QQQ/IWM** — `rules.py:108`. No source. With #1, the first symbol to fire
    decides the day.
14. **Runner for a level/EMA48/EMA200 entry trails its own entry line, not the EMA13** — `session.py:427-428`. He says
    EMA13 for runners without qualification.
15. **Range-day confirmation = "must have cleared the PM level"** — `session.py:617-622`. He lists alternatives.
16. **No flag detector** (`rules.py:31`) — a missing author rule rather than an added one; every on-side touch is taken.
17. **`size_small` 0.5, trim fractions 1/3, `shrink_after_win` ×0.5, `pullback_body_mult` 2.0, `pullback_max_bars` 8,
    `pullback_reset_atr` 0.5, `base_bars` 3 / `base_tol_atr` 1.0, `pm_tol_atr` 0.25, `max_reentries` 2,
    `max_signal_age_min` 3, last entry 15:30, flatten 15:45, daily halt 10 %** — all ours; individually lower impact.

---

## 4. Open questions that only discretionary judgment or new author evidence can resolve

1. **What does he actually do when the first 2m candle closes marginally through the EMA13?** "One candle", "a candle
   or 2", a 20 % premium stop and realised −20…−40 % cannot all be the same rule. We have zero losing trades with
   entry/exit prices or times. Capturing 10–20 of his losing alerts (entry, exit, premium, minutes held) is the single
   most valuable piece of new evidence.
2. **Does he require the 15m close before EVERY entry, or only for the "A+ break" family?** His 09:41, ~09:45 and
   pre-09:52 fills suggest the level-retest family is traded without it, at least on gap/trend mornings.
3. **How many stop-outs before he stops for the day?** 2026-09-03 shows at least two then a third. The content of the
   2026-09-17 red-day post is not captured and might answer this directly.
4. **Why did he not trade on 2026-09-08?** Not recorded. His sit-out criteria are entirely unknown.
5. **Entry at the touch or on the 2m close?** Both appear. If at the touch (limit resting at the EMA/level), our
   close-then-quote-then-order path is a different trade; if on the close, the stop needs room his words imply.
6. **How does he size?** Account size, contracts per trade, the meaning of "small"/"moderate", and whether the first
   entry is normally partial (".31 average", "add full position") are unknown. The promised "part 2" (expiries,
   strikes, sizes, trimming) was never found.
7. **Which levels are "his" levels on a given day?** The week-37 trades used 2–3-day-old levels. No causal definition
   exists (C2 is a desk draft).
8. **When does the PM-range avoidance apply?** "Typically", "exceptions… if I really like the setup". What makes him
   like it is not stated.
9. **Trim fractions and the first-trim cue.** "Trimmed a bunch", "big trim" at the HOD break, "majority of my profit"
   on the 15-minute follow-up candle (unverified at post level, per the 09-08 ledger — do not infer a rule).
10. **Contract selection rule.** Is it a premium (~$0.50), a delta, "the strike beyond the target", or discretion? One
    slightly-ITM example (2026-09-10) contradicts OTM-only.
11. **Does he trade more than one index at a time?** Not found.
12. **What happened on 2026-09-18 between 09:45 and 10:12 in our read?** A desk question, not an author question, but it
    must be answered from the trace before any rule is blamed: which gate (stack, fan, no-trade zone, range
    confirmation, target, contract, first-entry clock) held the entry for ~20 minutes.
13. **Is any of this profitable after our costs even if reproduced faithfully?** His record is self-reported, unaudited,
    commission-free (Webull US) and survivorship-selected; fidelity and profitability are separate axes
    (`DOC/AUTHOR-STUDY.md` §11).
