# Tips weekly decision review - 2026-09-21 to 2026-09-25

Generated 2026-09-25T20:48:36Z. Read-only; decisions are a human's, logged in TRADING-RULES with the evidence cited.

## 1. Scorecard (primary metric first)

# Tips economic scorecard (tips-scorecard-v6) - 2026-09-21 .. 2026-09-25

Tips Practice book only in the trading columns; shadow research books are listed apart and never summed. Realized = FIFO lots after ALLOCATED fees (the census engine; fees counted once, inside realized). Model cost = list-price ESTIMATE from `llm.rates` - not an invoice.

**Accounting day, not the market close:** a session runs 04:00 ET to 04:00 ET (the desk's day anchor). Its MARK is the last persisted equity point inside that window - the actual timestamp is printed; it is normally hours after 16:00 ET and includes any after-hours quote drift. Model runs are assigned to the same window (`tip_llm_cost` uses the calendar day instead, so its daily totals differ by the 00:00-04:00 ET runs).

**Primary metric = marked change after model cost.** Realized after model cost is printed beside it; they differ whenever open positions are marked.

Interval baseline: 8,964.46 = the 2026-09-20 accounting-day mark (09-21 03:59).

| session | mark at (ET) | mark equity | MARKED change | method realized net | fees in it | questioned net | repairs | realized total | model cost (priced) | unpriced runs | partial runs | **MARKED after model cost (primary)** | realized after model cost |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-09-21 | 09-22 03:59 | 8,966.61 | +2.15 | +2.79 | 0.00 | +0.00 | +0.00 | +2.79 | 122.50 | 0 | 0 | **-120.35** | -119.71 |
| 2026-09-22 | 09-23 03:59 | 9,180.04 | +213.43 | +248.45 | 14.56 | +0.00 | +0.00 | +248.45 | 101.26 | 0 | 0 | **+112.17** | +147.19 |
| 2026-09-23 | 09-24 03:59 | 9,132.89 | -47.15 | +46.57 | 0.00 | +0.00 | +0.00 | +46.57 | 60.39 | 0 | 0 | **-107.53** | -13.82 |
| 2026-09-24 | 09-25 03:59 | 9,148.55 | +15.65 | -78.51 | 2.08 | +0.00 | +0.00 | -78.51 | 21.95 | 0 | 0 | **-6.30** | -100.46 |
| 2026-09-25 | 09-25 16:48 | 9,035.86 | -112.69 | -98.16 | 0.00 | +0.00 | +0.00 | -98.16 | 5.45 | 0 | 0 | **-118.14** | -103.61 |
| **cumulative** | 09-25 16:48 | 9,035.86 | **+71.39** | **+121.14** | 16.64 | +0.00 | +0.00 | +121.14 | **311.55** | 0 | 0 | **-240.16** | -190.41 |

Open positions at the last mark: market value minus cost +183.57 (lots still open: 7); this is why marked and realized differ.


## Reconciliation

- **Cash from executions vs persisted cash** at every session close: largest difference $0.00 (reconciles).
- **Equity identity:** not printed - this report starts after the book's inception, so lots opened before the interval are outside the ledger window. Run from the book's first session for the full identity.
- **Questioned fill** 2026-09-17 MRNA260918C00165000 (evidence-quality): kept on the ledger, graded apart - docs/techniques/tip/reviews/2026-09-17-mrna-quote-audit.md.
- **Questioned fill** 2026-09-14 APLD261016C00030000 (execution-realism): kept on the ledger, graded apart - docs/techniques/tip/reviews/2026-09-14-eod-response.md (EOD-05); Yahoo 1m prints APLD261016C00030000 2026-09-14.
- Unallocated sells not explained by a repair: 2 (see the census exceptions).

## Model operating cost by stage (cumulative, list-price estimate)

| stage | runs/requests | input tokens | output tokens | priced $ | stamped | run-record | rollup (partial) | unpriced runs | unpriced input | partial runs | unknown calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| intake-review | 436 | 38,769,244 | 804,552 | 232.63 | 436 | 0 | 0 | 0 | 0 | 0 | 0 |
| appraise | 99 | 9,211,845 | 255,165 | 59.79 | 99 | 0 | 0 | 0 | 0 | 0 | 0 |
| extraction | 270 | 1,644,643 | 161,969 | 11.19 | 0 | 0 | 2 | 0 | 0 | 0 | 0 |
| retro | 21 | 878,485 | 56,687 | 7.04 | 21 | 0 | 0 | 0 | 0 | 0 | 0 |
| digest | 10 | 120,281 | 12,366 | 0.84 | 10 | 0 | 0 | 0 | 0 | 0 | 0 |
| transcribe | 4 | 8,612 | 1,260 | 0.06 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |

Attribution basis: `stamped` = usage.model recorded by the loop; `run-record` = the run's own model field written by the loop that called the provider (journaled changes to techniques.tip.analyst_model in the record: 1); `rollup (partial)` = nightly stage counters for extraction/transcription, which have no run record and lose in-memory counts across restarts - a LOWER BOUND. Digest and rule-audit are desk overhead (no source).

## How closed positions ended (net of fees; winners and losers together)

| exit | positions | net | winners | losers | held overnight | DTE at exit (options) |
|---|---:|---:|---:|---:|---:|---|
| ? | 2 | -132.15 | 0 | 2 | 1 | - |
| underlying stop | 1 | -88.93 | 0 | 1 | 1 | - |
| premium/stop exit in the first seconds of a session | 1 | -41.09 | 0 | 1 | 1 | 87 |
| dte | 1 | -0.08 | 0 | 1 | 0 | 1 |
| analyst mirrored the source's exit | 4 | +378.18 | 3 | 1 | 4 | 3, 3 |

Whole-trade results by how the position ENDED; 'held overnight' marks a trade that crossed a night - it is not overnight-only P&L. A bookkeeping repair is excluded here (see Reconciliation).

## Friction and exposure of open positions (S21-04; a diagnostic of an immediate round trip, not a forecast)

| symbol | qty | debit | entry fees | exit fees est. | spread at quote (role) | all-in $ | all-in % | hold cap | same-underlying other lots (cost) |
|---|---:|---:|---:|---:|---|---:|---:|---|---|
| ACHR270115C00007000 | 3 | 144.0 | 3.12 | 3.12 | 3.0 (decision) | 9.24 | 6.4 | 25 | 1 ($115.00) |
| PL | 59 | 999.46 | 0.0 | 0.0 | 0.59 (decision) | 0.59 | 0.1 | 15 | 0 ($0.00) |
| ACHR261016C00006000 | 5 | 115.0 | 5.2 | 5.2 | 5.0 (fill) | 15.4 | 13.4 | 12 | 1 ($144.00) |
| CRWV | 12 | 1046.04 | 0.0 | 0.0 | 0.6 (fill) | 0.6 | 0.1 | 10 | 0 ($0.00) |
| COIN | 10 | 1969.5 | 0.0 | 0.0 | 2.5 (fill) | 2.5 | 0.1 | 15 | 0 ($0.00) |
| SPY | 2 | 1535.66 | 0.0 | 0.0 | 0.06 (fill) | 0.06 | 0.0 | 3 | 0 ($0.00) |
| NBIS | 6 | 1422.6 | 0.0 | 0.0 | 1.2 (fill) | 1.2 | 0.1 | 10 | 0 ($0.00) |
| XLU | 36 | 1417.68 | 0.0 | 0.0 | 0.36 (fill) | 0.36 | 0.0 | 20 | 0 ($0.00) |

No friction threshold is applied; this is what the book pays to get in and out at the quoted market. Unknown inputs stay '?' (never estimated).

## Source return net of model cost (ADV-10; method realized, questioned apart, open at cost)

| source | filled ideas | completed | realized shares | realized options | model $ | **realized - model** | management actions | open at cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 🌟｜muggzone-options | 1 | 1 | +0.00 | -12.08 | 128.75 | **-140.83** | 9 | 0.00 |
| 🌟｜ab | 6 | 3 | -51.86 | +8.52 | 61.12 | **-104.46** | 16 | 1,473.68 |
| 🌟｜jon-and-kian | 2 | 1 | +3.35 | -41.09 | 9.02 | **-46.77** | 2 | 551.32 |
| 🌟｜tt | 1 | 0 | +0.00 | +0.00 | 28.65 | **-28.65** | 1 | 1,422.60 |
| 🌟｜eva | 0 | 0 | +0.00 | +0.00 | 26.12 | **-26.12** | 2 | 0.00 |
| 🌟｜neal | 4 | 2 | +7.43 | +0.00 | 19.53 | **-12.10** | 2 | 1,696.82 |
| 🌟｜giul-heatseeker | 0 | 0 | +0.00 | +0.00 | 3.18 | **-3.18** | 0 | 0.00 |
| MK-alpha-trades | 0 | 0 | +0.00 | +0.00 | 1.45 | **-1.45** | 0 | 0.00 |
| 🌟｜common-stock | 2 | 2 | +206.87 | +0.00 | 21.64 | **+185.23** | 7 | 0.00 |

Model $ is the list-price estimate of appraisals, retros and intake reviews attributed to the source; management actions = reviews that updated, closed or disarmed something we held (follow-up coverage). Open exposure is not credited. A source's row is evidence for allocation, never proof of an edge.


## 2. Opportunity dispositions

# Tips opportunity dispositions (opportunity-dispositions-v1) - ideas since 2026-09-21

Every ACTIONABLE idea (passed verification, or reached a proposal, plan or fill) has ONE disposition. An AVOIDABLE miss is one the desk caused by processing (failed analysis, expired approval, stale quote at submission, our own cancel) - a judgement, a risk boundary, or a level that never came is not.

| source | ideas | takes | filled | declined | risk-infeasible | late | analysis failed | approval expired | order unfilled | pending | avoidable |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| MK-alpha-trades | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 🌟｜ab | 18 | 8 | 6 | 10 | 1 | 0 | 0 | 0 | 0 | 1 | 0 |
| 🌟｜common-stock | 4 | 2 | 2 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| 🌟｜eva | 32 | 1 | 0 | 31 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| 🌟｜giul-heatseeker | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 🌟｜jon-and-kian | 4 | 4 | 2 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| 🌟｜muggzone-options | 21 | 8 | 1 | 13 | 7 | 0 | 0 | 0 | 0 | 0 | 0 |
| 🌟｜neal | 10 | 4 | 4 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 🌟｜tt | 7 | 1 | 1 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **all** | 98 | 28 | 16 | 69 | 11 | 0 | 0 | 0 | 1 | 1 | 0 |


## 3. Relevance filter (observe)

# Intake review gate - prospective decisions since 2026-09-21 through 2026-09-25

Coverage: 466 decision(s) over 5 accounting session(s) (2026-09-21, 2026-09-22, 2026-09-23, 2026-09-24, 2026-09-25); 0 decided with an incomplete desk read (always reviewed).

| resolution | decisions |
|---|---:|
| complete | 466 |
| running | 0 |
| failed | 0 |
| unmatched | 0 |
| unevaluable | 0 |

**Checkpoint eligibility: ELIGIBLE** - every decision is joined to a complete review and no complete review managed anything on a skip.

| mode | decision | skipped for real | messages | est. review cost |
|---|---|---|---:|---:|
| enforce | review | False | 19 | $0.61 |
| enforce | skip | True | 20 | $0.00 |
| observe | review | False | 342 | $170.02 |
| observe | skip | False | 75 | $43.33 |
| observe | skip | True | 10 | $0.00 |

**Management false negatives (complete reviews of observe skip-decisions that managed something): 0**

Human-review candidates among skip-decisions - ALL 75 exported (possible new entry, deferred action, mixed message, unresolved review); management proposals are listed apart from actions that succeeded:
- 2026-09-21 13:07 🌟｜neal ['CIFR'] run=cdb857f27de1460bbb0e1582204236e2 state=complete missedTip=None watch=['CIFR'] proposedManagement=None | neal trimmed half of a 1,000-share CIFR stock position at ~$18.96 (+17.56% on a $16.13 basis) — position commentary on a name the desk does not own. The attached image is a broker allocation row (CIFR 1,000 sh, $18,959.90 MV, last 18.96, basis 16.13, +$619.90/+3.38% day, +$2,832.40/+17.56% open), confirming his CIFR exposure is SHARES and giving his basis for the first time; he is now roughly half out with no stated stop or target on the remainder. get_positions shows zero CIFR anywhere (no shares, no options, no managed leg), so there is nothing to trim, tighten or close — per the position-commentary rule this is a skip, not an entry. It does settle the one open CIFR tip: the 9/08 parked tip is direction SHORT, extracted from a stale TradingView position-tool panel (entry 26.88/TP 13.78/SL 33.43), while the author was in fact LONG from 16.13 — wrong-direction and thesis-dead, so close it as an explicit lapsed decline (verdict already skip, never armed). Durable facts saved to ticker scope: basis 16.13, trim level ~18.96, remainder unmanaged.
- 2026-09-21 13:18 🌟｜muggzone-options ['HOOD'] run=0e4e51be9212405bb1d72438adde4d75 state=complete missedTip=None watch=['HOOD'] proposedManagement=None | MuggZone's premarket HOOD beat ('$126.75 premarket... lets see 150 eow') is a P&L tile on a position he already holds — a HOOD 10/02 $130 call up 12.62% — not a new entry. The attachment is a broker tile (image itself has expired from the mirror; transcript = 'HOOD 10/2 $130 Call ▲12.62%'), so this is the position-commentary family: no BTO verb, no fill price, no stop, no TP ladder — verification's discard is correct. Desk reconciliation: get_positions HOOD = [] — our HOOD arc is already closed (the 9/25 120C mirrored from his 9/18 alert realized +34%), so there is nothing to trim, tighten or close; the five open HOOD tips (his 9/25 120C 'take', 9/18 110C, 9/25 125C shadow, ab's 9/25 120C, eva's strike-less short) are lapsed husks that should be closed as explicit declines and must not have seenCount escalated by this beat. What changed: he has disclosed a NEW, further-OTM leg (110C → 120C → 125C → now 10/02 130C) on a name that has run four straight sessions — winning-leg escalation, and '150 eow' is +18% in 4 sessions, so the 130C only pays on the improbable leg. Saved a ticker-scoped note with the basis/coherence reasoning.
- 2026-09-21 13:38 🌟｜common-stock ['MRNA'] run=dec968ae36ca46b4b7787929b7e70f4f state=complete missedTip=None watch=['MRNA'] proposedManagement=None | KianTrades posted a fourth priced partial exit on his running MRNA commons position ("sold more at 162.10") — an exit beat, not an entry, and our own MRNA mirror is already fully closed. get_positions shows MRNA = [] : the managed mirror 916e14e488674b7ca57a551f73318a3d (basis 141.96) was scaled out across his 9/17 beats and the last free runner exited at/above its single 162 rung, so there is nothing left to trim, tighten or close on this update. MRNA quotes 162.12 (bid 161.70/ask 162.31, 0.38% spread, feed 0.1s) vs 154.04 prevClose, +5.2% today and ~11% above his last stated 156 scale — he keeps selling strength into a 4-session run off a 145.74 basis and never states residual size or a stop. New durable datum saved: his CLOSE staircase spans SESSIONS, not just one morning (153.21 → 156 → 'trim as you go' 159 → 162.10), so an early 'sold some' must never be read as the end of an arc. Verification correctly failed opens_position; no other exposure to this source apart from Jon's SBLK shares.
- 2026-09-21 13:40 🌟｜muggzone-options [] run=032ddea51f9544c0b62ace21a9798f0f state=complete missedTip=None watch=['TSLA', 'HOOD'] proposedManagement=None | MuggZone's 09:41 "if u snagged puts out of the gate theyre up 150%+" is a retro-brag coda on the exit arc he posted a minute earlier — no ticker, strike, expiry or basis, and the +150% actually belongs to a CALL (TSLA 9/23 375C +152.38%) in his own 09:40 screenshot. Reconciled against the desk: the +150% figure matches the 09:40 tile pair (HOOD 10/2 130C +107.94%, TSLA 9/23 375C +152.38%) already logged this run, so the word "puts" contradicts his own image — he was long calls into a +2.7% TSLA rip (374.26 vs 364.27 prevClose). That means this line does NOT revive a bearish TSLA thesis and does not reopen the TSLA 9/25 340P plan (run 8dcb0798) already disarmed at 09:40; all standing MuggZone TSLA put husks stay verdict skip. get_positions shows no TSLA or HOOD exposure — managed book is AAL 10/16 14C (+10%), SBLK 62sh, ACHR 1/2027 7C, none from this source — so there is nothing to trim, tighten or close. Saved a source note recording the new handling datum: when a tile is attached, trust the picture, not his directional noun.
- 2026-09-21 13:42 🌟｜ab ['APLD'] run=ad0dd9f1148843ee96f28c5e145a0fa7 state=complete missedTip=None watch=['APLD', 'AAL', 'ACHR', 'DAL', 'AAOI', 'AMZN'] proposedManagement=None | ab trimmed more than half of his APLD 10/16 30C at +30% at the open — the half-trim that failed to fill on 9/18 finally executed, ending his build campaign; the desk holds zero APLD so there is nothing to manage. Verification correctly failed this on opens_position: it is a trim on a position the source already holds, the classic position-commentary family, never an entry. get_positions shows no APLD exposure anywhere (managed book is AAL 10/16 14C and ACHR 1/2027 7C, both ab-sourced and untouched by this message), so there is no trim/tighten/close authority here. What changed materially: Sunday's 23:10 Mass Position Update still listed APLD 10/16 30C at FULL size (avg 1.67, +30%) because the 9/18 16:01 trim order never went through — that is now stale; he is sub-half size and de-risked, so his APLD conviction leg is finished scaling. The only standing APLD artifact, the 9/16 09:58 shadow ADD tip (10/16 30C, verdict skip, seenCount 1), should be closed as a lapsed decline — the author is exiting the exact leg it mirrored — and this message must not escalate its seenCount.
- 2026-09-21 13:52 🌟｜muggzone-options [] run=b4a21ae316544f4c9034d709cba7f93e state=complete missedTip=None watch=['TSLA', 'HOOD'] proposedManagement=None | MuggZone's 09:52 fragment completes his previous line — "waiting for a dip on tsla … to snag some Wednesday calls" — an intent-to-buy TSLA 9/23 calls on a pullback after he exited his 9/23 375C (+152%) at 09:40, with no strike, premium or dip level. Read as one sentence with beat 5 (same timestamp), this is a forward-expiry hint only: it names 'Wednesday' (2026-09-23) but no ticker in the fragment, no strike, no premium, no level and no fill — the weakest tier in this lane, so zero tradable signals is correct and it must not escalate seenCount on any TSLA husk. It re-confirms he is FLAT TSLA and bullish-on-a-dip, so the TSLA 9/25 340P plan disarmed earlier this run (run 8dcb0798) stays dead and the four other MuggZone TSLA tips remain verdict skip (the 340P, verdict 'take' with plan disarmed, should be closed as a lapsed decline). get_positions TSLA = [] — managed book is AAL 10/16 14C, SBLK 62sh, ACHR 1/2027 7C, none from this source — so there is nothing to trim, tighten, close or disarm. Saved a source-scope note tying beats 5 and 6 together.
- 2026-09-21 13:53 🌟｜muggzone-options [] run=5550c8b5f4eb499eb2a67f314c02e40d state=complete missedTip=None watch=['TSLA', 'HOOD'] proposedManagement=None | MuggZone's 09:52 'going in on na starter pos' is the third fragment of one sentence (waiting for a TSLA dip → Wednesday calls → starter position): a present-tense open with no ticker, strike, expiry, premium, size or level — un-mirrorable. Beats 5-7 of the same minute read as one line, so the implied name is TSLA 9/23 calls after he sold his 9/23 375C (+152%) at 09:40; but nothing priceable is stated and 'starter' announces a scale-in build, which carries adds rather than a stop. The premise is already contradicted by the tape: TSLA quotes 377.45 (+3.6% vs 364.27 prevClose, feed age 0.1s), above the 374.26 level where he exited — there was no dip, so if he did open here he chased. Desk reconciliation: get_positions TSLA = [] (managed book is AAL 10/16 14C, SBLK 62 sh, ACHR 1/2027 7C — none from this source), so there is nothing to trim, tighten or close; the TSLA 9/25 340P plan (run 8dcb0798) stays disarmed since his bias is long, and the five standing MuggZone TSLA husks remain skip/lapsed with no seenCount escalation from beats 5-7.
- 2026-09-21 13:55 🌟｜muggzone-options [] run=80e48ceb06a34cf18adefd93f2895767 state=complete missedTip=None watch=['TSLA'] proposedManagement=None | MuggZone's 09:55 "1st TP hit on TSLA" is a trim/management beat on the 9/23 385C he alerted at 09:52 (entry 2.25, TP1 3.00) — a position we deliberately skipped, and the desk holds nothing in TSLA. Reconciliation: get_positions TSLA = [] (managed book is AAL 10/16 14C, SBLK 62sh, ACHR 1/2027 7C — none from this source), so there is nothing to trim, tighten or close; the TSLA 9/25 340P plan (run 8dcb0798) stays disarmed since his bias is long and now winning, and the five standing MuggZone TSLA husks stay skip/lapsed. What changed: his 385C hit rung 1 within ~3 minutes with TSLA 377.50 (+3.6% vs 364.27 prevClose), so he is partially out with runners toward 3.65/4.80 — our skip was taken on the fill-band/ladder-inversion arithmetic (ask 2.70 = 1.20x his 2.25 print, TP1 only +0.30 at our basis vs his SL -0.95) and it forwent roughly +11% on our would-be basis, not his +33%. That is the accepted cost of the rule, not evidence against it. Also noted: the 09:54 SPX 7720 beats run in parallel and SPX is unpriceable on this desk, so any later bare "sold"/"TP2" beat must be tied back to its named ticker before acting.
- 2026-09-21 13:56 🌟｜muggzone-options [] run=09846d250b24497db222086733c0d919 state=complete missedTip=None watch=['TSLA'] proposedManagement=None | MuggZone trimmed part of his 09:52 TSLA 9/23 385C (2.25 entry) at 2.90 — a partial-trim/fill report on the alert we deliberately skipped on the fill band, not a new trade. The bare 'sold some at 2.90' is beat 10 of the morning arc: 09:55 '1st TP hit on TSLA @here' → tile (viewed) reading 'TSLA 9/23 $385 Call ▲47.94%' → this fill note; the tile plus the preceding line resolve the ambiguity with his parallel 09:54 SPX 7720 (entry 2.25, TP1 2.8), so 2.90 is a TSLA 385C partial — notably BELOW his own 3.00 TP1 rung, useful colour on how his ladder tags actually fill. Reconciliation: get_positions shows no TSLA (and no SPX) anywhere — managed book is AAL 10/16 14C (243a6cb…), SBLK 62sh (867c1fe…), ACHR 1/2027 7C (35255c4…), none from this source — so there is nothing to trim, tighten, close or disarm; the TSLA 9/25 340P plan (run 8dcb0798) stays disarmed since his bias is long and winning, and the five standing MuggZone TSLA husks stay skip/lapsed. Bookkeeping on our 09:52 skip is unchanged and honest: at the 2.70 live ask we forwent ~+0.29/contract (~+11%) versus his +29%, the exact trade-off the fill-band rule accepts; rungs 3.65/4.80 remain unproven. He is now partially out and running the rest, so a later 'sold the rest/all out' beat should be expected to close the arc.
- 2026-09-21 13:58 🌟｜muggzone-options [] run=20ab4bf2ae0d43588f17f1db6be43a6f state=complete missedTip=None watch=['ARM', 'TSLA', 'HOOD'] proposedManagement=None | MuggZone's 09:57 "just so much going on rn hard to alert" is a pure meta/apology beat with no ticker, contract or level — nothing tradable, but it flags that his stream this morning is deliberately fragmented and incomplete. Reconciled against the desk: get_positions shows no TSLA, SPX, ARM or HOOD in any account (managed book = AAL 10/16 14C 243a6cb…, SBLK 62sh 867c1fe…, ACHR 1/2027 7C 35255c4…; live = TQQQ/SPCX/MSFT.TO/AAPL.TO; EM sim = IREN 9/25 47.5C, AVGO 9sh), so there is nothing to trim, tighten, close or disarm — the TSLA 9/25 340P plan (run 8dcb0798) stays disarmed since his bias is long and he already exited/trimmed the 9/23 385C. The one substantive line in the surrounding window, 09:56 "also took ARM 340 calls 2.80", was NOT discarded: get_open_tips shows it already captured as a proposed ARM long 340C, seen 1, expiry NULL, analystVerdict skip — correctly declined on contract-identity (no expiry, no SL/TP, and several ARM weeklies can price 2.80 at that strike). Saved a source-scoped note recording the "hard to alert" warning: during these windows assume every fragment is incomplete by his own admission and require a full "entered <ticker> <strike> <exp> @ <price>" before anything is mirrorable.
- 2026-09-21 14:03 🌟｜muggzone-options ['SPX'] run=43b30ebbd5834052b3ae86ad7e4c8f11 state=complete missedTip=None watch=['SPX', 'TSLA', 'ARM'] proposedManagement=None | MuggZone hit his first target on the 09:54 SPX 7720 calls (entry 2.25) and sold 1/4 at 2.80, running the rest into 3.4/4.3 — position commentary on a leg the desk does not and cannot hold. This is the first management beat on his parallel SPX arc (09:54 'spx 7720 entry 2.25 TP 2.8 / 3.4 / 4.3'), the index twin of the TSLA 9/23 385C we skipped on the 1.15x fill band. get_positions shows zero SPX anywhere (managed book = AAL 10/16 14C, SBLK 62sh, ACHR 1/2027 7C), so there is nothing to trim, tighten or close; the TSLA 9/25 340P plan stays disarmed. Verification's ticker_resolves failure is genuine here — SPX has no quote or chain on this desk, so all seven parked MuggZone SPX husks (7720 x2, 7735, 7635, 7670 x2, 7660, all verdict skip, all expiry-less or expired) are structurally un-mirrorable and should be closed as lapsed declines. Logged the disambiguation that matters: 09:55 'sold some at 2.90' = TSLA 385C (tile-confirmed), 10:03 '2.80' = SPX 7720 — two arcs with identical 2.25 entries, so any bare future 'sold the rest' must be tied to a named ticker before acting.
- 2026-09-21 14:05 🌟｜muggzone-options [] run=f93103cb59224cdea0613e3991d1a7d8 state=complete missedTip=None watch=['TSLA', 'ARM', 'HOOD'] proposedManagement=None | MuggZone's 10:05 "retrace starting up @here" is a bare tape-call with no ticker, strike, expiry, premium or level — commentary colouring his two live arcs (SPX 7720 calls 3/4 left, partially trimmed TSLA 9/23 385C), not a trade. Beat 14 of a fragmented morning in which he explicitly said "hard to alert" (09:57). Reconciliation: get_positions shows the desk holds NO TSLA, SPX, ARM or HOOD anywhere — managed book is AAL 10/16 14C (243a6cb…, 2 lots @0.34, flat), SBLK 62 sh (867c1fe…), ACHR 1/2027 7C (35255c4…), none from this source — so there is nothing to trim, tighten, close or disarm, and the disarmed TSLA 9/25 340P plan (run 8dcb0798) stays dead. Tape check: TSLA 375.76 (+3.2% vs 364.27 prevClose, feed 0.2s), ~1.7 pts off the 377.5 area where his TP1 printed, i.e. a mild fade consistent with the words but far from any invalidation. Saved a source-scoped note recording the new "bare tape-call" taxonomy, his book state at 10:05 and the expectation that the next beats are "sold the rest"/"all out" on TSLA 385C and/or SPX 7720.
- 2026-09-21 14:06 🌟｜muggzone-options [] run=5fd86eab91a84c959dbaaa156bfee0dc state=complete missedTip=None watch=['TSLA', 'ARM', 'HOOD'] proposedManagement=None | MuggZone beat 15 is a bare dip-invitation ('possible good area to start getting better price entries') with no ticker, level, strike, expiry or premium — pure tape colouring continuing his 10:05 'retrace starting' line, and correctly non-actionable. Reconciliation: the desk holds nothing from this source — managed book is AAL 10/16 14C (243a6cb…, 2 lots @0.34, mark 0.335), SBLK 62sh (867c1fe…, +1.2%) and ACHR 1/2027 7C (35255c4…, -10%), live accounts are TQQQ/SPCX/MSFT.TO/AAPL.TO, EM sim IREN 9/25 47.5C + AVGO — no TSLA, SPX, ARM or HOOD anywhere, so there is nothing to trim, tighten, close or disarm; the TSLA 9/25 340P plan (run 8dcb0798) stays disarmed. What changed is only his own book context: after the 09:55 TSLA 9/23 385C partial at 2.90 and the 10:03 SPX 7720 1/4 trim at 2.80, he is flagging the pullback he said at 09:52 he was waiting for, i.e. this is a pre-alert that a priced re-entry (his 'Wednesday' 9/23 calls) may follow. Tape at 10:06: TSLA 375.36 bid/ask 375.32/375.40 (feed, 0.1s, +3.0% vs 364.27 prevClose), ~2 pts off the 377.5 area where his TP1 printed — a shallow fade, not a structural dip. A 'good area' with no number is a fabricated trigger, so no arming and no seenCount escalation on any TSLA/SPX/ARM/HOOD husk.
- 2026-09-21 14:07 🌟｜muggzone-options [] run=f457968dbcd347ff83efb9684210d48c state=complete missedTip=None watch=['TSLA', 'SPX', 'ARM', 'HOOD'] proposedManagement=None | MuggZone beat 16 'or scalp puts' is a ticker-less, price-less aside on the same 10:05-10:07 retrace chatter — zero actionable content and, arriving one minute after 'possible good area to start getting better price entries', it makes the chain two-sided (buy the dip OR short it) on an unnamed underlying. Reconciled at 10:08: get_positions shows nothing from this source anywhere — managed book is AAL 10/16 14C (243a6cb…, 2 lots @0.34, mark 0.335), SBLK 62 sh (867c1fe…, +1.4%) and ACHR 1/2027 7C (35255c4…, 3 lots @0.48, -10%); live accounts are TQQQ/SPCX/MSFT.TO/AAPL.TO and EM sim is IREN 9/25 47.5C + AVGO — so there is no TSLA, SPX, ARM or HOOD exposure to trim, tighten or close. Nothing changed on the campaigns; no exit plan was touched. The disarmed TSLA 9/25 340P plan (run 8dcb0798) explicitly stays dead — a bare 'scalp puts' with no ticker, strike, expiry, premium or level is a fabricated trigger and also contradicts his own live long book (SPX 7720 calls 3/4 left, TSLA 9/23 385C partially trimmed at 2.90, ARM 340C 'no dips'). Saved a source-scoped note logging the new two-sided-in-two-minutes pattern and the standing handling rule.
- 2026-09-21 14:08 🌟｜eva ['AAPL'] run=969560b57e6445819bfc30feff64e12c state=complete missedTip=None watch=['AAPL'] proposedManagement=None | eva posted a price-mark coda on the AAPL 337.5C 9/21 0DTE she narrated from third-party flow at 10:03 ("almost ITM") — commentary on a contract she never claimed to own, nothing actionable. This is the continuation of the 10:03 UW-tile flow narration, her 3rd non-actionable beat this morning (09:20 pre-bell map, 09:33 GOOGL STC + 09:35 "hit 4.60" coda). Tape confirms the words — AAPL 337.63 (+0.45% vs 336.13, feed 0.1s, 0.006% spread) so the 337.5 strike is now at/just through the money — but the 10:03 tile was bid-lean (Bid 19,110 vs Ask 17,990) with day net premium -$2.38M, so the print reads as premium selling into a 337.5 pin, not a directional call buy; it is also 0DTE, banned by the safety floor and the execution-mode rule. get_positions AAPL = [] (no shares, options or managed leg), so there was nothing to trim, tighten, close or disarm; the six standing eva AAPL tips (340C x2, 335C x2, 330C 9/18, 310P) stay verdict skip with no seenCount escalation and should be closed as lapsed declines. Saved a source-scoped note adding "there goes X / almost ITM" to her log-only coda taxonomy alongside the GOOGL "hit 4.60" line.

## 4. Intake coverage

# Tips intake coverage (raw message -> signal) since 2026-09-21

Every received message ends in ONE class. A failed extraction is not proof the message held no opportunity, and it is not a missed winner either: it is an unclassified message until it is recovered or a human reads it. Replay is bounded (2 attempts per message in total) and idempotent; a replayed message re-enters the ordinary intake with its own stated time, so an old tip is replayed on history, never traded.

| source | received | extracted (signals) | extracted (no signal) | pending | failed | recovered | refused/ignored |
|---|---:|---:|---:|---:|---:|---:|---:|
| MK-alpha-trades | 7 | 1 | 5 | 0 | 1 | 0 | 0 |
| 🌟｜ab | 118 | 65 | 53 | 0 | 0 | 0 | 0 |
| 🌟｜common-stock | 37 | 15 | 22 | 0 | 0 | 0 | 0 |
| 🌟｜eva | 43 | 34 | 9 | 0 | 0 | 0 | 0 |
| 🌟｜giul-heatseeker | 12 | 4 | 8 | 0 | 0 | 0 | 0 |
| 🌟｜jon-and-kian | 13 | 7 | 6 | 0 | 0 | 0 | 0 |
| 🌟｜muggzone-options | 257 | 73 | 184 | 0 | 0 | 0 | 0 |
| 🌟｜neal | 37 | 21 | 16 | 0 | 0 | 0 | 0 |
| 🌟｜tt | 49 | 23 | 26 | 0 | 0 | 0 | 0 |
| **all** | 573 | 243 | 329 | 0 | 1 | 0 | 0 |


## 5. Overnight carry

# Overnight carry of held Tips Practice positions (close -> next open, bid to bid)

| vehicle / DTE | samples | worse at the open | better | median % | mean % | $ (sum) |
|---|---:|---:|---:|---:|---:|---:|
| 0-7 DTE | 8 | 4 | 3 | -2.9 | +12.5 | +416.00 |
| 8-30 DTE | 7 | 2 | 3 | +0.0 | +4.6 | +12.00 |
| 31+ DTE | 10 | 5 | 3 | -3.6 | -5.1 | -62.00 |
| shares | 27 | 13 | 13 | +0.0 | +1.1 | +360.27 |

Excluded (a sample not fresh on both ends): {'fresh/pending': 9}. Bid-to-bid is what an exit at each sample would have realised; it is not the trade's P&L. Small samples: a direction, not a rule.

## 6. Knowledge ledger

# Tips knowledge ledger (ADV-11)

Operative rules: **37**, 41,748 chars (~10,437 tokens) re-sent on every analyst call. Suggested budget: 15 pinned/core rules; the rest proposals until they bind >= 3 dated cases.

| rule (first line) | chars | dated cases | supplied | relied | core | flags |
|---|---:|---:|---:|---:|---|---|
| RULE (adoption geometry — canonical family, consolidated 2026-09-14 from 28 rules; the cod | 2,372 | 1 | 574 | 4 |  | unbound |
| RULE (extends the hedge-leg-mirroring rule to IMPLICIT hedges — a full-format @everyone BT | 1,322 | 2 | 574 | 0 |  | unbound |
| RULE (execution mode, shares branch — sits beside "execution mode must match contract life | 1,293 | 2 | 574 | 2 |  | unbound |
| RULE refinement — instrument legality, the CASH-SECURED PUT branch (the 2026-09-08 covered | 1,257 | 2 | 574 | 0 |  | unbound |
| RULE (chart-image tips — the TradingView POSITION-TOOL PANEL is not the trade; read the an | 1,239 | 1 | 574 | 0 |  | unbound |
| RULE (generalizes the "premium-limit wish" rule beyond the lotto lane): a source's "lookin | 1,202 | 2 | 574 | 0 |  | unbound |
| RULE (process hygiene — an analystVerdict of "skip" must never end up ARMED): when my own  | 1,196 | 1 | 574 | 2 |  | unbound |
| RULE (hedge-leg mirroring — sits beside the "instrument legality / covered-call" rule): wh | 1,153 | 2 | 574 | 0 |  | unbound |
| RULE (fill discipline on lotto/0DTE mirrors — extends "execution mode must match contract  | 1,132 | 1 | 574 | 6 |  | unbound |
| RULE (new, sits beside the tt-lifecycle family): a source's SAME-SESSION RE-ENTRY after a  | 1,104 | 1 | 574 | 0 |  | unbound |
| RULE (instrument legality — a source's COVERED-CALL / premium-collection STO is never mirr | 1,088 | 2 | 574 | 0 |  | unbound |
| RULE (arming is not free — gate at_level plans on the SOURCE'S armed-book statistics): bef | 1,019 | 1 | 574 | 1 |  | unbound |
| RULE (closes the gap between "watchlist is not an open" and "execution mode must match con | 958 | 1 | 574 | 0 |  | unbound |
| RULE (new, closes the loop on the conditional-map family): when a source's DAILY level map | 848 | 2 | 574 | 1 |  | unbound |
| RULE (extends the "watchlist is not an open" family): a source's morning TWO-SIDED CONDITI | 843 | 1 | 574 | 2 |  | unbound |
| RULE (extends the "watchlist is not an open" rule): a re-posted THIRD-PARTY flow screensho | 773 | 2 | 574 | 1 |  | unbound |
| RULE (corollary to "a two-sided conditional level map is never an entry"): when one map me | 632 | 1 | 574 | 2 |  | unbound |
| RULE: A source's "eyeing / watching / top candidates" list is NOT an open — never mirror i | 515 | 2 | 573 | 2 |  | unbound |
| RULE refinement — adoption-geometry clause 1 (SIGN), new dated evidence + the MECHANISM th | 1,447 | 3 | 574 | 0 |  | - |
| RULE (extends the hedge-leg / two-sided-message family to EVENT STRADDLES): when a single  | 1,408 | 4 | 574 | 0 |  | - |
| RULE (author-disclaimed contract — sits in the "flow narration is not an open" family, and | 1,370 | 5 | 574 | 0 |  | - |
| RULE (refines strike-target coherence — the ATTENTION-SPIKE WING case): a deep-OTM call (> | 1,362 | 6 | 574 | 0 |  | - |
| RULE (refines "a tip whose expiry is not a LISTED expiry is a guess" — the MISSING-expiry  | 1,238 | 7 | 574 | 2 |  | - |
| RULE (lotto tape filter — sits beside the fill-band and execution-mode rules): a 0-3 DTE M | 1,225 | 4 | 574 | 3 |  | - |
| RULE (completes the escalation family — the WINNING-LEG variant, i.e. NEXT-STRIKE-UP re-en | 1,220 | 3 | 574 | 0 |  | - |
| RULE (contract-life sanity at TIP TIME — a pre-check that sits in front of the strike-targ | 1,216 | 6 | 574 | 2 |  | - |
| RULE (new, sibling of the "average-down through their own stop" rule): a source's ESCALATI | 1,188 | 5 | 574 | 1 |  | - |
| RULE (extends "execution mode, shares branch" to OPTION BTOs with a premium but no underly | 1,179 | 3 | 574 | 3 |  | - |
| RULE (execution mode must match contract life): never park an at_level / pullback plan on  | 1,134 | 3 | 574 | 4 |  | - |
| RULE (consolidates the "price-update line is not an open" and "trim alert is not an entry" | 1,108 | 4 | 574 | 18 |  | - |
| RULE (contract identity — a tip whose stated expiry is not a LISTED expiry is a guess, not | 1,090 | 7 | 574 | 1 |  | - |
| RULE (new, sits beside the "watchlist/commentary is not an open" family): a source's AVERA | 1,082 | 4 | 574 | 1 |  | - |
| RULE (session kill-switch — execution-integrity pause; replaces the 2026-09-04 clock claus | 1,070 | 3 | 574 | 0 |  | - |
| RULE (flow-scan specific, extends the "lean only counts when aggregates+OI agree" rule): d | 949 | 5 | 574 | 0 |  | - |

## 7. Shadow-book integrity

# Shadow research-book integrity (shadow-audit-v1, 2026-09-25)

| book | quarantined | realized net (FIFO) | unallocated sells | negative lots | evidence |
|---|---|---:|---:|---:|---|
| Shadow: 🌟｜ab |  | -7,141.51 | 0 | 0 | valid |
| Shadow: 🌟｜ab (armed) | YES | (not computable) | 1164 | 3 | UNRELIABLE: 1164 unallocated sell(s) - FIFO P&L is not computable; 3 negative open lot(s) - the book is short shares it never bought |
| Shadow: 🌟｜common-stock |  | -0.99 | 0 | 0 | valid |
| Shadow: 🌟｜common-stock (armed) | YES | (not computable) | 2 | 1 | UNRELIABLE: 2 unallocated sell(s) - FIFO P&L is not computable; 1 negative open lot(s) - the book is short shares it never bought |
| Shadow: 🌟｜eva |  | +122,477.29 | 0 | 0 | valid |
| Shadow: 🌟｜eva (armed) | YES | (not computable) | 19 | 7 | UNRELIABLE: 19 unallocated sell(s) - FIFO P&L is not computable; 7 negative open lot(s) - the book is short shares it never bought |
| Shadow: 🌟｜florida-man |  | +0.00 | 0 | 0 | valid |
| Shadow: 🌟｜florida-man (armed) |  | +18.22 | 0 | 0 | valid |
| Shadow: flow-scan |  | -2,386.05 | 0 | 0 | valid |
| Shadow: flow-scan (armed) |  | +0.00 | 0 | 0 | valid |
| Shadow: 🌟｜giul-heatseeker |  | +4.64 | 0 | 0 | valid |
| Shadow: 🌟｜jon-and-kian |  | -1,455.85 | 0 | 0 | valid |
| Shadow: 🌟｜jon-and-kian (armed) |  | -108.31 | 0 | 0 | valid |
| Shadow: MK-alpha-trades |  | +0.00 | 0 | 0 | valid |
| Shadow: 🌟｜muggzone-options | YES | (not computable) | 3 | 3 | UNRELIABLE: 3 unallocated sell(s) - FIFO P&L is not computable; 3 negative open lot(s) - the book is short shares it never bought |
| Shadow: 🌟｜muggzone-options (armed) | YES | (not computable) | 1 | 0 | UNRELIABLE: 1 unallocated sell(s) - FIFO P&L is not computable |
| Shadow: 🌟｜neal |  | +7.18 | 0 | 0 | valid |
| Shadow: 🌟｜neal (armed) |  | +164.07 | 0 | 0 | valid |
| Shadow: 🌟｜tt | YES | (not computable) | 3 | 0 | UNRELIABLE: 3 unallocated sell(s) - FIFO P&L is not computable |
| Shadow: 🌟｜tt (armed) |  | -67.78 | 0 | 0 | valid |

An unreliable book is never evidence. `--apply` quarantines the unreliable books that are not quarantined yet.

## 8. Research switches (each must answer a question or be switched off)

| setting | value | why it exists |
|---|---|---|
| `techniques.tip.review_gate` | "enforce" | relevance filter - observe until the five-session report |
| `techniques.tip.review_capture_context` | true | captures review requests for the cheaper-model / context evaluations |
| `techniques.tip.frozen_capture_context` | true | captures appraisal requests for frozen replays |
| `techniques.tip.entry_cohort_enabled` | true | entry-timing cohort (every eligible idea, delayed samples) |
| `techniques.tip.hold_study_enabled` | true | hold study: 15:50 + next-open samples (feeds the overnight carry study) |
| `techniques.tip.mk_ownbook_mode` | "observe" | MK own-book (off | observe | shadow) |
| `techniques.tip.prompt_cache` | true | prompt caching (cost only) |
| `techniques.tip.prompt_cache_scope` | "conversation" | prefix | conversation |
| `techniques.tip.review_context` | "full" | full | compact (compact measured unsafe 2026-09-23) |
| `techniques.tip.review_source_budgets` | {} | per-source review budgets |
| `techniques.tip.max_book_exposure_pct` | 0 | book exposure cap |
| `techniques.tip.max_name_exposure_pct` | 0 | name exposure cap |
| `techniques.tip.shares_alternative` | "annotate" | equal-risk share size on infeasible option cards |
| `techniques.tip.friction_flag_pct` | 0 | friction flag on cards |

