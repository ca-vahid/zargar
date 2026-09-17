# 2026-09-16 - trading awareness + TMR-01..05 development plan (recorded 2026-09-15 23:40 ET)

Source: the review team's two-part plan
`C:/Cursor/zargar-codex/docs/techniques/tip/reviews/2026-09-16-trading-and-development-plan.md`
(prepared 2026-09-15; "documentation only - start the development work during September 16 business
hours; do not implement or activate this plan tonight"). The user's decision (2026-09-15 evening):
part 1 is tonight's awareness note, part 2 starts 2026-09-16 during business hours and is applied
after the close through the next coordinated deployment once all is well. **Nothing was implemented,
activated, scheduled in the app, or written to settings tonight.**

## Facts verified tonight (read-only)

- **FOMC:** the Federal Reserve calendar (https://www.federalreserve.gov/newsevents/2026-september.htm,
  fetched 2026-09-15 ~23:35 ET) lists the two-day meeting **September 15-16, 2026**, the statement at
  **2:00 p.m. ET on the 16th** and the press conference at **2:30 p.m. ET** (11:00 / 11:30 PT). This
  verifies the schedule only - not the content, not the direction.
- **The app is event-blind today:** `research.macro_events` (the shared manual macro calendar,
  `research/macro_calendar.py`, placeholder v0 from the Team2 desk) is **empty** on the live settings;
  its docstring EXAMPLE shows "2026-09-17 FOMC decision" (a wrong example date, not live data). No desk
  enforces event days: `techniques.team2.avoid_event_days` False; Tips/EM/Cartel have no such knob set.
  Coverage unknown is not "no event" - TMR-01 must surface the verified event without pretending the
  calendar has coverage it lacks, and any write to the shared list is coordinated with the Team2 desk
  first (it is the only consumer that could turn an entry into a skip, and only if its knob were on).
- Live build at the time of writing: 0.7.91 `a4d241b`; `trading.mode` practice; all live-auto gates off;
  hold study `holdstudy-v2` deployed (first protocol-correct capture 15:50 ET 09-16).

## Part 1 - tomorrow's awareness checklist (desk actions, ET / PT)

| When | Desk does | Not implied |
|---|---|---|
| before 09:30 / 06:30 | confirm the running build, Tips positions + stops, working orders, intake liveness (one listener), unresolved incidents - from current state | no restart just because a session starts |
| 09:30 onward | read execution readiness (risk $, final qty, limit, stop) separately from the analyst's TAKE; refresh stale cards through the existing flow | TAKE is not a fill; allocation is not the loss budget |
| all session | per idea: exact contract, spread/fees, source age, expected hold, whether one unit fits; unknown inputs stated | never raise limits or swap contracts to turn a refusal into a trade |
| before 14:00 / 11:00 | label decisions as before/after the Fed event with time-to-event; recheck the official schedule; if TMR-01 is not live, keep this checklist and record the label in the desk report | not an automatic no-trade day, no direction call |
| 14:00 / 11:00 | FOMC statement: keep exact quote/decision timestamps; event-period outcomes identifiable in research | a fast move proves nothing about earlier decisions |
| 14:30 / 11:30 | press conference: spreads, quote age, existing protections; statements apart from confirmed data | no stop loosening, source promotion or strategy rewrite |
| 15:50 / 12:50 | verify the first valid pre-close capture: per eligible observation the actual sample time (observedAt), sourceTs, quote qualification, size; missing/late visible | a capture is not a sell/hold instruction |
| after 16:00 / 13:00 | EOD: realized net P&L, open marked P&L, costs, no-fills, research results apart; accepted/blocked ideas and source/setup counts; label the Fed-event context | one Fed-day result is not a rule |
| 09-17 09:30-09:45 / 06:30-06:45 | complete the overnight pair from the 09-16 pre-close observation; managed exits apart from quote drift | the invalid 09-15 rows yield no valid pair |

Standing: Practice scope and risk limits unchanged; feasibility `annotate`; compact context unadopted;
hold/entry/frozen studies research-only. Closed corrections are not proof of a profitable strategy.

## Part 2 - development brief for 2026-09-16 (owner: Tips desk unless stated)

Order: TMR-01 -> TMR-02 -> TMR-03/TMR-05 documents; TMR-04 runs alongside. Every addition
informational or research-only; no new trading gate, threshold, quantity or contract change.

| ID | Deliverable | Acceptance | Boundary |
|---|---|---|---|
| TMR-01 P1 verified event context | FOMC 09-16 14:00 / 14:30 ET in the analyst context/card and research records with official URL, UTC/ET, verification time, time-to-event; event-day observations distinguishable | ET/PT/UTC correct; unknown coverage != no event; no historical input may use a fact learned later; zero orders | advisory; shared-calendar writes coordinated with the Team2 desk; no event-day ban |
| TMR-02 P1 execution-cost diagnostic | qualified bid/ask + size, source time, exact multiplier, entry/exit fees, instantaneous round-trip cost `(ask-bid) x mult x qty + entry fees + exit fees`, cost as share of purchase value, fill-vs-quote observations - on feasibility/payoff/cohort outputs; unavailable = unknown | multipliers/fee bases right; stale/crossed/missing refused; spread never charged twice (a scenario already exiting at bid does not subtract it again); no midpoint fill; no orders | annotate/report only; no spread threshold, qty change, alt contract, risk change |
| TMR-03 P2 time/volatility scenario design | written model/input spec for a small grid (target soon/later, flat + elapsed time, declared IV changes) + one frozen worked example if qualified evidence exists | Greek units, timestamps, model version, limits documented; missing Greeks/IV unknown; local approximation is not a big-move forecast | research prototype; existing risk estimator and execution gate preserved |
| TMR-04 P1 operate existing studies | verify the 15:50 capture; entry-timing cohort continues; new frozen full/compact cases marked complete vs coverage-limited; 09-17 paired-report template | observedAt vs sourceTs; eligible/missing/late counted; same evidence across variants; zero trading/knowledge writes; no current quotes for missing history | collection under the reviewed protocol; no new pipeline, no winner |
| TMR-05 P2 experiment register + scorecard | per experiment: hypothesis, variant definition, eligible setup, holding-episode identity, primary metric, costs, policy/build regime, alternatives tried, prospective evaluation window; reports carry this identity | repeated alerts/quotes are not independent trades; partials and fees once; event sessions and incomplete evidence visible; no sample count called proof | documentation/reporting only; no allocation or promotion |

Testing: small targeted arithmetic / timestamp-eligibility / no-side-effect checks; reuse existing
regressions; widen only for shared scheduler/order/calendar changes or failures. Deployment: stage and
test in business hours; ship on the next coordinated deployment when readiness permits; no forced
restart for a clock; no termination of paid analysis; no silent shared-desk behaviour change. EOD
handoff: task IDs, exact commit/PR, sample card/report, tests with counts and scope, known limits,
and separate **built / merged / deployed / collecting / evaluated** statuses, plus the next
observation or reviewer decision needed.

Carried forward, not part of this build: helper-lifecycle gaps (platform/start-path owner);
the Flow degraded-day repair test (now owned by the Tips desk per the project lead, fixed test-only
in PR #163 - no further action unless the baseline fails again).

## Desk checkpoints armed for 2026-09-16 (session one-shots; not app jobs)

08:25 ET pre-open state; 09:45 ET development kickoff (TMR-01 -> TMR-02 -> TMR-03/05 docs, TMR-04
alongside); 13:50 ET Fed pre-check (decisions before/after, time-to-event label); 15:52 ET capture
verification; 09-17 09:47 ET overnight pair. The recurring 30-minute ticks and the 16:06 ET wrap-up
carry the rest of the checklist.

## Built 2026-09-16 (business hours): TMR-01 and TMR-02 - advisory / research only

**TMR-01 verified event context** - `techniques/tip/events.py`. A Tips-scoped, provenance-carrying
list (`techniques.tip.verified_events`; None = the module DEFAULT: FOMC statement 2026-09-16 14:00 ET
and press conference 14:30 ET, official URL, `verifiedAt` 2026-09-16T03:35Z = 23:35 ET 09-15,
`coverageThrough` 2026-09-18) beside the shared manual calendar (read separately as
`sharedCalendar`, never merged into a verified claim). `event_context(now, as_of)` returns the
session's label: `status` event-day / no-scheduled-event / unknown (a date beyond coverage is
UNKNOWN, not "no event"), each event with ET and UTC instants, `secondsUntil`, `timeUntil`
(T-2h14m / T+1h05m), phase before/after, URL and verification time; a knowledge cut hides entries
verified after the decision instant (a historical replay never sees a fact first learned later;
entries without a verification time are never shown). Surfaces: the analyst header
(`EVENT CONTEXT (...)` line under "Today (ET)" on appraise and intake runs, so every frozen bundle
captures it), the analyst record (`eventContext`, replays labelled at their own asOf), every new
card's `context.eventContext` and the readiness plan (`plan.eventContext`, shown as the card's
"event" row; NOT part of the fingerprint), cohort rows (`event_context` column, additive), hold-study
observations (`window.event`) and adopted positions (`extras.eventContext`). Zero orders: labels
only; no shared-calendar write (the Team2 desk owns `research.macro_events`; it stays empty).
Tests: `tests/test_tip_event_context.py` (7: zones/time-until/provenance, phase flip, unknown vs
no-event, knowledge cut, shared list apart, defaults/override, engine: label rides a card and
places nothing).

**TMR-02 execution-cost diagnostic** - `techniques/tip/execcost.py`. `round_trip()` on a QUALIFIED
quote (the cohort's qualification: provenance, delayed flag, genuine source time, two-sided, option
session): `roundTrip = (ask - bid) x multiplier x qty + entryFees + exitFees`, with `spreadPerUnit`,
`spread`, `purchaseValue` (at the ask), `costShareOfPurchase`, `spreadPctOfAsk`, quoted `bidSize` /
`askSize` (now carried on every cohort quote record), `sourceTs` / `sampledAt` / `quoteAgeS`, the fee
basis (options per contract per side + `sim.reg_fee_per_contract`; shares a flat commission per
order per side) and the reminder that a payoff scenario exiting at the bid already carries this
spread. Stale / crossed / one-sided / missing evidence or a zero quantity -> every money field None,
`status: unknown` with reasons. `fill_vs_quote()` compares ONE realised fill with the decision
quote (vsLimit, vsAsk, vsAskDollars, vsMid; positive = worse), never averaged. Surfaces: the analyst's
`check_feasibility` / `preview_payoff` tool outputs (`execCost`), the analyst record, the risk plan
(`RiskPlan.execCost`, recomputed at every admission/revalidation on the FINAL size; NOT in the
fingerprint), the readiness plan and the card's "round trip now" row, and at adoption the journal
event `TipFillVsQuote` + `extras.fillVsQuote`. No gate, threshold, quantity, contract or limit is
changed by any of it. Tests: `tests/test_tip_execcost.py` (5: option arithmetic incl. regulatory
fee, shares flat commission, every unqualified case unknown, fill-vs-quote, engine diagnose touches
nothing).

**Sample (from the tests, option 2 x XYZ 100C, bid 1.40 / ask 1.50, $0.99 + $0.05 per contract):**
spread $20.00 (0.10/unit) + entry $2.08 + exit $2.08 = **round trip $24.16 = 8.05 % of the $300
purchase**; a $0.99 fee on shares reads $0 commission -> the spread is the whole cost. Card row:
`round trip now  $24.16 (8.1% of $300) · bid 1.4 / ask 1.5 · size 12x30 · 1s`; event row:
`FOMC statement 2026-09-16 14:00 ET (T-2h14m), FOMC press conference 2026-09-16 14:30 ET (T-2h44m)`.

**Verification:** 12 new checks pass; regression slice readiness / v086 / geometry wiring /
expression gate / payoff / hold study / prof142 / pr147 = 46 passed, 1 failed
(`test_tip_geometry_wiring::test_enforce_mode_finalizes_stop_and_resizes_before_entry` - passes
alone twice on this branch and on the unmodified checkout; sim-price sensitivity of the grouped run,
not touched here). Frontend build green. Statuses at the time of writing: **built, merged - not
deployed** (ships on the next coordinated deployment after the close); collecting: n/a; evaluated: n/a.

## Built 2026-09-16 (second block): TMR-03 design, TMR-05 register, TMR-04 template - research only

**TMR-03 time/volatility scenario design** - `docs/techniques/tip/research/2026-09-16-time-vol-scenarios.md`
+ prototype `techniques/tip/scenarios.py` (`bsm-local-v1`, NOT wired into any card, gate, sizing or order
path; the delta-linear risk estimator and the execution gate are untouched). Grid: flat underlying after
1/5/10 days, target reached soon (1 day) / later (half the remaining time), each at IV -5 / 0 / +5 points;
dollars per contract against the premium paid; the model's value and mispricing at t0 printed beside it;
theta per day and vega per IV point in dollars; every output carries model version, rate assumption,
inputs with sources/timestamps and the limits (local approximation, no path/stop modelled, exits at model
value - execution cost is execcost's job). Missing inputs -> `unknown` with the names. Worked example on
frozen desk evidence (SLV Nov-20 65C: CBOE delayed snapshot 09-15 IV 0.4665 / venue delta 0.3144, SLV close
57.55, 65 DTE, mid 2.085 as the premium stand-in, target 61.8): the local model reproduces the venue delta
(0.3143) and mid (2.078); theta -$3.27/day, vega +$8.62/IV point; the same target reached at the halfway
point with IV 5 points lower LOSES $21 while reached within a day it makes +$107..+$209 - the arithmetic
behind "a good thesis is not a good option purchase". Labelled coverage-limited (delayed snapshot, close
not a decision-time quote, local Greeks beyond delta). Tests: put-call parity, venue-delta agreement,
grid dollars, declared limits, unknown inputs.

**TMR-05 experiment register** - `techniques/tip/experiments_register.py` (`experiments-v1`) mirrored by
`docs/techniques/tip/research/EXPERIMENT-REGISTER.md` (a test keeps the id lists equal): entry-timing-cohort,
overnight-hold, frozen-context, mk-ownbook-observe, feasibility-annotate - each with hypothesis, variant
definitions, eligible setup, unit of observation (repeated alerts/quotes are not independent trades),
holding-episode identity, primary metric, costs, policy/build regime, alternatives tried, prospective
evaluation window with a decision rule, and status. Reports now carry the identity block: the hold-study
aggregate (`experiment`), `frozen.compare` (`experiment`), the cohort report (`experiment`); the identity's
caveat states that partials and fees count once, event sessions and incomplete evidence stay visible, and
no sample count is called proof. Documentation/reporting only - no allocation or promotion.

**TMR-04 operate existing studies** - `docs/techniques/tip/research/HOLD-STUDY-REPORT-TEMPLATE.md` (the
09-17 09:47 ET paired report: counts per arm/setup incl. missing/late/ineligible/outside_window, actual
sample times vs sourceTs vs jobStartedAt, fee/risk basis per observation, quote drift apart from managed
exits, aggregate, reading). The 15:50 ET capture is verified by the 15:53 ET checkpoint; the entry-timing
cohort keeps collecting unchanged; new frozen pairs are run after the close only (paid) and marked
complete vs coverage-limited by `frozen.compare`.

**Verification:** `tests/test_tip_scenarios_register.py` (5) + hold study + frozen compact + KFIN-09
experiments = 22 passed. Statuses: **built, merged - not deployed** (next coordinated deployment after
the close); collecting: hold study (09-16 15:50 ET onward), cohort, frozen captures; evaluated: nothing.

## Incident 10:40-10:53 ET: watchdog restart loop on a health 500 - caused by this desk, fixed

At 10:40:09 ET the watchdog judged the running 414a86c process DOWN (no answer on :8420; the cause is
not in the watchdog log) and started the checkout AS IT STOOD: `c3842eb` / 0.7.96 (the converged,
merged-not-deployed tree). That process never answered `/api/health` (HTTP 500): the running checkout's
`backend/zargar/__init__.py` had lost the EM desk's `build_sha` helper - a runtime-branch-only addition
that the EM desk's `api/app.py` imports - because this desk's conflict resolution on 2026-09-15 evening
took main's bare `__version__` file. The watchdog looped (start, 180 s without health, kill, start) at
10:40 and 10:46 ET; the Discord intake died with each restart. Fix at 10:50 ET: the helper restored
verbatim with version 0.7.96, committed on the runtime branch (`4c84697`, pushed); the watchdog's 10:52 ET
start came up healthy - **0.7.96 build `4c84697`, 65 armed (60 plans restored), sim book restored,
Tips Practice MRNA venue stop registered, SLV/T app-managed, gates unchanged (practice, live-auto off),
no incident**. One Discord listener (the watchdog start relaunched one; this desk's duplicate stopped),
liveness live, ledger pending 2 (recovering). Consequence: **0.7.96 is LIVE since 10:52 ET, unplanned**
- TMR-01/02 (event context, execution cost), TMR-05 (register on reports), PR #145/#150 etc. are
deployed; TMR-03 is inert code. Statuses now: TMR-01 built/merged/deployed/collecting; TMR-02
built/merged/deployed/collecting (first `TipFillVsQuote` on the next fill); TMR-03
built/merged/deployed(inert)/n-a; TMR-04 collecting (15:50 ET capture on the corrected protocol);
TMR-05 built/merged/deployed. Evaluated: nothing. Lessons: PLATFORM-RULES change log 2026-09-16.

## INTRA-01..03 (review team, 2026-09-16 10:52 ET) - built the same day, research/reasoning only

Source: `C:/Cursor/zargar-codex/docs/techniques/tip/reviews/2026-09-16-intraday-1052.md`. Risk limits, approvals,
feasibility mode and the safety floor are unchanged; nothing forces a take.

**INTRA-01 expiration break-even versus an earlier sale.** The GOOGL 10:49 ET appraisal (ab, Sep-18 350C,
ask 2.19, delta 0.356, 2 DTE) reasoned "breakeven 352.19 sits ABOVE the 350 ceiling ... so the trade only
pays on a decisive FOMC break" - that is the EXPIRATION break-even; a call sold before expiry pays whenever
its executable bid exceeds entry + costs, whatever the underlying is versus 352.19. Built: `payoff.break_even`
(strike +/- premium, labelled HELD-TO-EXPIRY only), `payoff.premium_exit` (P&L of a sale at a later executable
- or labelled synthetic - bid, fees on both sides, unknown without both premiums), `payoff.expiry_value`;
`payoff_preview` now prints `breakEven` and `horizon` (dte, declared hold sessions, exit assumption
before/at expiry) BESIDE the before-expiry scenarios; the analyst's `preview_payoff` tool receives the
contract's strike/type/expiry and the opinion's hold, and the record keeps both blocks. Prompt rule
"BREAK-EVEN IS AN EXPIRATION NUMBER" with the independent skip reasons preserved. Acceptance (synthetic,
labelled): a 2-DTE 350 call bought 2.19 and sold at a later bid 2.50 with the underlying at 349 (< strike
< 352.19) nets +$28.92 after $2.08 of fees; held to expiry at 349 it is worth 0 (-$221.08); a missing exit
premium is unknown. The GOOGL skip may still be right on the tape / source-record / attainable-gain reasons
- those stand; only the break-even reasoning is corrected.

**INTRA-02 one lot as an exit-plan question.** META 09:46 ET ("a single unmanageable binary while tt
scales out in fragments") and GOOGL ("ONE binary lot cannot replicate ... fragment scale-outs"). Built:
`payoff_preview.singleLot` - declared rungs vs executable rungs, `collapsed`, `canCopyPartials`, and the
note that one contract executes ONE exit (first target or a premium exit) to be judged on its own net
payoff (`oneLot` / `tp1ThenStop`), skipping only when the thesis DEPENDS on scaling or one unit does not
fit the budget; prompt rule "ONE LOT IS AN EXIT-PLAN QUESTION, NOT A REJECTION". Acceptance: a 3-rung source
plan on 1 contract -> declared 3 / executable 1 / cannot copy partials, `oneLot` = the first-target exit net
(+$77.92 on the synthetic case) = `tp1ThenStop`; 3 contracts can copy the rungs; a one-unit budget failure
still refuses (`feasibility` qty 0, reason = budget).

**INTRA-03 recap cost - measured, a cheap read built, routing gated OFF for evaluation.** Today's four
appraisals (`tip_analyst_runs.opinion.usage`): SPX map (eva) 2 calls 78,699 in / 981 out; META (tt) 3 calls
125,296 / 3,758; APLD digest (ab) 4 calls 154,177 / 1,948; GOOGL (ab) 3 calls 124,248 / 3,223 - total
**482,420 in / 9,910 out / 12 calls**, 37k-45k input per call (the header: rulebook + notes + 3-day
history, re-read on every call; cache reads 0). The lever is per-call size x call count, not one context.
Built (`techniques/tip/recap.py`, `recap-read-v1`): a deterministic message-shape read BEFORE the paid
appraisal - branches vs fan-in, both sides of one underlying (a level map), priced opens, management
actions (trim/close/update_stop), recap cues vs entry cues, distinct tickers -> category recap /
management / new / mixed / single with a confidence and a recommended route; journaled on every
multi-signal message as `TipRecapClassified` (category, confidence, recommended vs actual route, knob,
reasons, features). Routing knob `techniques.tip.recap_route` = **off (default: classify + journal only)**
| compact: a confident recap with no management instruction gets the COMPACT context (core rules only,
notes for this ticker/source + core notes, 24 h / 12-line history, tool budget `recap_max_tools` 2) with a
header line saying so; the verdict, tools, safety floor and card handling are unchanged; the run records
`headerMode`, `headerChars` and the read. Management instructions and ambiguous mixed content stay on the
full route by construction; a single priced BTO is untouched. Acceptance: the SPX-map shape reads recap
(confidence >= 0.8, route compact); a trim/stop/close post reads management (full); a single priced BTO
single (full); priced opens beside management -> mixed (full); entry cues + priced opens -> full.
**Evaluation before switching the knob:** replay today's SPX-map and APLD-digest bundles under `current`
vs `compact` after the close (paid, two pairs) and compare verdicts / header chars / tokens / calls with
`frozen.compare` (coverage flagged); switching `recap_route` is a reviewer decision. Not done: suppressing
entry-card creation/pricing for confirmed recaps - the cards are created before the appraisal; it needs
the same evaluation first and is recorded as the next step.

**Verification:** `tests/test_tip_intra_reasoning.py` (6) + payoff/feasibility + expression gate +
profitability preview = 16 passed; intake pipeline slice (`test_signals_tip`, `test_tip_activation`,
`test_tip_kfin09_experiments`) 37 passed. Status: built, merged - not deployed (the live 0.7.96 process
predates it; ships on the next coordinated deployment after the close); INTRA-03 routing collecting
classifications once deployed, evaluated after the frozen pairs.

## I175-01..04 (review of PR #175, 2026-09-16) - built the same afternoon; recap routing stays OFF

Source: `C:/Cursor/zargar-codex/docs/techniques/tip/reviews/2026-09-16-pr175-verdict.md`; the reviewer's
three regressions adopted verbatim as `tests/test_pr175_review.py` (all three failed on `412dd1c`).

**I175-01 mixed messages stay full.** `recap.classify` (`recap-read-v2`) now applies two FULL-route
conditions BEFORE any recap scoring: a fresh priced actionable open/add anywhere in the message, or entry
cues on actionable content -> category `mixed`, route `full` (the reviewer's case - an AAPL call/put map,
MSFT and TSLA shares and one actionable NVDA call at 1.00 with "BTO NVDA calls at 1.00" - now reads
`mixed / full`, `freshPricedEntries: 1`). A recap's OLD averages (priced but non-actionable opens, e.g. the
APLD "unrealized only" digest) count as a recap feature (`oldAverages`), not as entries, so the holdings
digest still reads `recap / compact-eligible`. Management (trim/close/update_stop) stays full; a clean level
map stays compact-eligible. No card is suppressed and no verdict is changed by the read.

**I175-02 partial-copy labels from the executed units.** `payoff_preview.singleLot` derives
`canCopyPartials` from the integer sequence execution actually runs (`executedUnits`): every positive rung
must receive >= 1 unit; `reproducesWeights` says whether the integer split equals the declared fractions;
`uncoveredRungs` names the rungs that get nothing. The reviewer's case: 3 contracts x 80/10/10 executes
`[2, 1, 0]` -> `canCopyPartials: False`, `uncoveredRungs: [3]`, note "rung(s) [3] receive no unit at this
size - the ladder is not copied". 3 x 40/30/30 -> `[1, 1, 1]` covers every rung but does not reproduce
the weights; 10 x 50/30/20 reproduces them. One contract's first-target behaviour is unchanged
(`oneLot` = first-target exit net).

**I175-03 hold cap, expiry date and exit assumption are three things.** `payoff.horizon_block`: the
MAXIMUM hold (`maxHoldSessions`) is converted to a calendar date on the exchange calendar
(`holdCapEndsOn`; Fri 09-18 + 2 sessions = Tue 09-22), the `expiryDate` is kept apart, and
`exitAssumption` is "before expiry (target / stop / premium exit) - a hold cap is a maximum, not an exit
time" unless the caller DECLARES `exit_at_expiry`, which alone produces "declared: held to expiry" and an
`expiryScenario` valued at intrinsic value minus premium and both sides' fees (349 -> 0 intrinsic, net
-$221.08; 355 -> 5.00, net +$278.92 on the 2.19 call). `holdCapReachesExpiry` is informational. Unknown
inputs stay unknown. The verified early-sale example (+$28.92 net, $2.08 fees) is untouched. The analyst's
`preview_payoff` tool passes the contract's expiry date and an optional `exit_at_expiry` flag.

**I175-04 replay parity before any paid pair.** ONE versioned configuration `recap.CANDIDATE`
(`recap-candidate-v1`: core rules via `compact_rules`, core + ticker + source notes via `compact_notes`,
24 h / 12-record history, 2-tool budget, the exact header prefix template, the prompt-rule names) is the
source for BOTH the production compact route (`analyze_tip` header prefix, history query, tool budget,
`recapCandidate` version on the run) and the new frozen variant `recap_candidate`
(`frozen.variant_knowledge`, assembled by the same `recap.build_candidate_context` on the bundle's captured
rules / notes / history; `_rebuild_header` prepends the prefix; `replay` takes the variant's `maxTools`).
Declared, never filled: the 24-hour history bound is not verifiable on captured lines (the newest 12
captured records are used - a gap on the report), and the replay keeps the bundle's CAPTURED system prompt
for baseline parity (an INTRA-rule-free prompt is a declared difference, not corrected from today).
Unpaid parity check `test_replay_recap_candidate_matches_the_production_route_unpaid`: identical rule ids,
note ids, rules/notes text, history lines (newest 12), prefix (incl. the confidence) and tool budget between
`build_candidate_context` and the frozen variant on the same inputs; the rebuilt header keeps the same
evidence time; the `current` variant is untouched; an empty captured history stays empty. The generic
`compact` variant (PROF-05) is left as is and is NOT the candidate. Next: after the close, the two paid
pairs on today's SPX-map and APLD-digest bundles under `current` vs `recap_candidate` (plus fresh-entry,
management and mixed negative controls for the classifier from today's journal), reported with
coverage / missing-evidence / cost / latency - the reviewer decides `recap_route`.

**Verification on the final commit:** `tests/test_pr175_review.py` (3, reviewer) + `tests/test_tip_i175_parity.py`
(4 incl. the parity check) + `tests/test_tip_intra_reasoning.py` + payoff/feasibility + expression gate +
profitability preview + frozen compact + KFIN-09 experiments + tip activation = **36 passed** (the 16 prior
checks retained, two of them updated for I175-03's separated horizon). Standing: `recap_route` off,
`analyst_feasibility_gate` annotate, no card suppression, no risk-limit change, no forced TAKE. Status:
built, merged - not deployed (the live 0.7.96 process predates PR #175 and this fix; ships on the next
coordinated deployment after the close).

## I175-04 follow-through (review of PR #177, 2026-09-16 afternoon) - replay parity on the ACTUAL request

The reviewer's two checks adopted verbatim (`tests/test_pr177_capture_parity_review.py`; both failed on
`c6fb097`). (1) **History by RECORDS:** production supplies 12 mirrored records (a multi-line message is
one record; `- [<label>] author: ...` starts a record); the candidate and the frozen rebuild now count
records (`recap.trim_history_records`, `historyRecords`), so a 12-record history with two lines each is
kept whole. (2) **Classifier metadata through capture:** the run's opinion carries `recapRead`,
`headerMode`, `headerChars`, `recapCandidate`; `build_bundle` copies them onto `bundle.run`, and the
captured manifest records `headerMode`, `recapRead`, `classifierVersion`, `maxTools` (effective budget)
and `recapCandidate`; the `recap_candidate` variant reads the confidence FROM the capture (0.87 stays
0.87) and is `available: False` / coverage-limited when no read was captured - it never substitutes
zero. A compact-route capture's header already carries the prefix: the rebuild keeps it exactly once.
The variant reports `parity` = {headerMode, capturedCandidate, capturedMaxTools, classifierVersion,
promptIdentity (system sha), status production-request | treatment-only, gaps} - a full-route capture
replayed under the candidate is declared "treatment-only", a version mismatch "non-parity".
**Request-assembly parity (unpaid, real capture):** a compact-route run on the engine with a scripted
client is captured verbatim; the replay rebuilds from that bundle the EXACT production request text
(prefix once, same rules/notes/history), the same effective tool budget (2), classifier version and
prompt identity (`test_actual_compact_request_is_reproduced_by_the_replay_from_the_capture`); the
full-route baseline stays the captured text. Results: reviewer 2 + parity 5 + PR175 3 + intra reasoning
6 + frozen compact + KFIN-09 + activation = **29 passed**. Standing: `recap_route` off; no risk-limit,
permission or card-suppression change. Status: built, merged - not deployed (rides the next coordinated
deployment; the accepted reasoning/payoff fixes ship with the route off). The two paid pairs run only on
bundles that carry a captured classifier read; today's SPX-map and APLD bundles predate that capture and
are declared non-parity / coverage-limited - the evidence set is compact-route captures once the route
is allowed.

## PAR178-01/02 (review of PR #178, 2026-09-16 afternoon) - exact order, captured budget, offline harness

Reviewer's two cases adopted verbatim (`tests/test_pr178_route_parity_review.py`, parametrized siblings /
tool_budget; both failed on `ea1f6f5`). **PAR178-01:** production composes a request as historical note,
siblings, compact prefix, base; the manifest now records that `componentOrder` and the exact
`compactPrefix`; the exact rebuild swaps only the rules/notes/history blocks and adds a prefix only when
the captured head carries none (then in production's position), so a multi-branch compact capture rebuilds
to the identical text - verified by the request hash (`frozen.request_hash` == the manifest's `headerSha`).
The reconstructed path composes in the same order. **PAR178-02:** an exact replay of a compact capture uses
the CAPTURED effective tool budget (a one-tool capture replays with one; `parity.budgetSource=captured`);
the candidate default (2) applies only when the treatment is assembled on a full capture; a captured budget
that differs from the default is declared "a separate treatment" on the parity block. **`current` on a
compact capture is flagged** (`treatment: compact (captured request)`, `isFullControl: False`, gap) - it is
not the full-route control. **Harness:** `frozen.assemble_treatments(bundle)` (CLI `tip_frozen assemble
--bundle`) assembles both requests offline from the same frozen inputs - no model, no writes - with request
hashes, sizes and budgets: a full-route capture yields full (hash == captured) and candidate (differs); a
compact capture yields the candidate by exact hash and declares the full control unavailable (capture the
two treatments explicitly). Results: reviewer 2 + parity 6 + PR177 2 + PR175 3 + intra reasoning 6 +
frozen compact + KFIN-09 = **28 passed**. Standing: `recap_route` off; no risk, permission or
card-suppression change; built, merged - not deployed.

## Pre-EOD review items (2026-09-16 15:45 ET) - TMR02-WIRE fixed; paid pairs held; register updated

**TMR02-WIRE (confirmed defect, fixed):** `_compute_risk_plan` attached the execution-cost diagnostic with an
undefined name (`pdict`) inside a swallowed `try`, so every persisted risk plan carried an empty `execCost`
(the live GOOGL card included). Fixed: the in-scope exact `symbol` is used and a diagnostic failure is
reported on the plan (`status: unknown`, `reasons: ["diagnostic failed: ..."]`) and logged - never
swallowed. The reviewer's integration test is adopted verbatim (`tests/test_tmr02_card_wiring_review.py`:
a qualified share card, revalidated, persists `riskPlan.execCost.status == known` and the readiness plan's
`roundTrip`; zero orders). One of this desk's engine tests compared the diagnostic with a second quote read
that ticked in between - it now judges the diagnostic on its own captured fields. Results: wiring 1 +
execcost 5 + event context 7 + proposal readiness = 19 passed on the first run (one race fixed), then the
wiring + execcost files 6 passed. Status: built, merged - not deployed (the live 0.7.96 process still
carries the empty field; the fix rides the next coordinated deployment).

**Paid pairs HELD:** unpaid assembly (`tip_frozen assemble`) of the 2026-09-16 SPX-map and APLD-digest
bundles shows no captured classifier read, so the `recap_candidate` inputs are unavailable (non-parity) -
no paid replay was run. Adequate inputs come from prospective captures once a classifier read is on the
record (live now on 0.7.96? no - the read is journaled by `TipRecapClassified` only from the next deploy)
or from isolated frozen inputs assembled through the harness. Live recap routing stays OFF.

**Register:** the `frozen-context` entry now distinguishes the captured `current` request (a control only
on a full-route capture) from a genuine full control, lists `recap_candidate` as the production candidate,
requires a captured classifier read for the recap question, and records the held SPX/APLD pairs.

## 15:53 ET capture verification (TMR-04) - first holdstudy-v2 pre-close capture, one arm missing

`tip_hold_snapshot` ran at 15:50:10 ET (calendar-relative, result 2). Two `carry` observations, both
`fresh`, both inside the window (`verdict inside`; observedAt = the quote's sampledAt 15:50:10 ET, jobStartedAt
15:50:10 ET, sourceTs 0 = the shares feed's receipt basis), `observation_key` holdstudy-v2, expected next
session 2026-09-17, event label `event-day`: **MRNA** 7 shares on Tips Practice (plannedRisk $52.52 for 7) and
**AFRM** 27 shares on the ab ARMED SHADOW book. Counts: carry eligible 2 / fresh 2 / ineligible 0 / missing 0 /
late 0. The 2026-09-15 rows stay `outside_window` (their next-open sample at 09:30 ET is irrelevant: the pair
is insufficient by the pre-close status; they are excluded).

**Gap found and fixed (merged, not deployed):** the `intraday_exit` arm observed NOTHING - a closed position
leaves manager memory, and `snapshot_preclose` read `mgr.positions()` only, so today's three Tips Practice
exits (T 13:15 ET, SLV 15:00 ET, GOOGL Oct-16 360C 15:17 -> 15:30 ET) were not recorded: intraday_exit eligible 3
/ observed 0 / missing 3 (counted, not repaired - no hand sampling). Fix: today's closes are read from the
durable `managed_positions` record (closedMs on the session date) and adapted through the manager's own
row reader; every observation now carries `portfolio_id` + `book_kind` (sim / shadow) so the paired report
separates the Practice book from the shadow books (`books` per setup). Test: the engine case adopts a
second position, closes it, and the snapshot records one `intraday_exit` observation with the exit price and
the book kind (`late` when observed outside a pinned window - the R147 admission at work). Hold-study slices:
16 passed. First protocol-correct PAIR candidates for 2026-09-17: MRNA (Practice) and AFRM (shadow).

## End of session 2026-09-16 (16:06 ET) - fills, fees, marked equity, research coverage, deployment status

Labels: every number below is an FOMC event-session number (`event-day`; decision 14:00 ET, presser 14:30 ET) -
BEFORE/AFTER comparisons across this session are not a like-for-like read.

**Tips Practice fills and exits (all managed exits, technique-sourced, sim book):**

| Position | Entry | Exit | Fees (today) | Realized (trip) | Exit reason |
|---|---|---|---|---|---|
| T Jan-15-27 29C x4 (opened 09-10) | - | 13:15:02 ET @ 0.5499 | $4.16 | +$3.64 today (position lifetime +$131.96 incl. earlier scale-outs) | bar closed through the stop 26.30 (close 26.295) |
| SLV Nov-20 65C x1 | - | 15:00:04 ET @ 1.7996 | $1.04 | -$40.12 | bar closed through the stop 57.40 (close 56.9505) |
| GOOGL Oct-16 360C x1 (armed tips plan) | 15:17:00 ET @ 5.40 | 15:30:09 ET @ 5.149 | $2.08 (both sides) | -$27.18 | intra-bar quote breach (341.42 vs stop 345.2814) |
| MRNA 7 sh | held | open | - | +$25.62 marked | venue GTC stop 134.37 (single exit authority) |

Tips Practice today: fees $7.28 (4 executions), realized -$63.66 on the three trips; marked equity **$8,806.21** vs
day start $8,923.85 (-$117.64 on the day, marks included), cash $7,786.87. Desk ledger (all books): today's
realized -$690.91 (Team2 QQQ 0DTE -$479.69, EM CRCL/CVNA/CRWV/SNDK -$147.56 net, Tips -$63.66); banked
-$1,899.80, riding +$24.71, unexplained $0.01. No open incidents; halt off; zero pending proposals; 4 proposals
created and rejected by the analyst (SPY 760C x2 budget-gate, AMZN wish, TQQQ, GOOGL - all skips on the record).

**Research coverage (0.7.96, the running build):** entry-timing cohort 14 rows (13 blocked / 1 declined; quote
status 9 fresh / 5 ineligible, all delayed samples taken); analyst runs 81 (12 appraise, 69 intake) - all 12
appraise runs carry the exact context manifest (`contextManifest`), no bundle materialised today (the two
`tip_frozen_bundles` rows are 09-15; a bundle is built on demand from a captured run); `TipRecapClassified` 0
and `TipFillVsQuote` 0 (both journals ship with the next deploy); hold study: 2 carry observations at 15:50 ET
(MRNA Practice, AFRM ab armed shadow), intraday_exit 0 observed / 3 eligible (defect fixed in PR #184, not
deployed - the three exits above are the missing rows, not repaired by hand). Paid frozen pairs: none run
(held - no captured classifier read). Recap routing OFF; risk limits unchanged; no method change.

**Deployment status:** running process 0.7.96 build 4c84697 (watchdog launch 10:52 ET); running checkout
`C:/Cursor/zargar` at aef37c3 = origin/main 0.7.98 (import + check-release green, runtime branch pushed).
Merged, NOT deployed: PR #175 (INTRA), #177/#178 (I175/PAR178 parity), #181, #183 (TMR02-WIRE), #184 (hold
exits + book kind). Next coordinated deployment via the EM desk after the user's go; the ZargarRestart task
only after `/api/ops/restart-check` (safe:true, techniqueRunning 0 at 16:01 ET).

**Cross-desk note (INTC, 15:29 ET blip):** the "sim fill handling failed for INTC" line is the sim executor
judging bracket SELL 19 INTC LMT 106 (`9423b723...`) on the **Tips shadow immediate book** "Shadow: eva"
(`b56d8e5a...`, research): `SimFillWaiting` at 15:22 / 15:34 / 15:42 ET (uncrossed / stale-receipt quote
during the blip), order still ACCEPTED, filled 0, executions 0, INTC ~100.7 vs the 106 target - nothing to
reconcile, no unprotected money position (shadow book, no managed position). No order placed.

**Thursday 2026-09-17:** 09:30 ET next-open sample for the MRNA / AFRM carry rows (calendar-relative job, in-window
retries); 09:47 ET first paired report by book kind per `research/HOLD-STUDY-REPORT-TEMPLATE.md`.

## HOLD-SCOPE-01/02 (Codex final EOD verdict, 2026-09-16 evening) - performance by book kind; quarantined inventory is diagnostic

**HOLD-SCOPE-01 (confirmed, fixed):** `aggregate` grouped by setup only and summed Practice (sim) and shadow
results into one net figure beside a `books` count. Now `setups` is keyed `<bookKind>:<setup>` (Practice = `sim`,
`shadow`, `live`, `unknown` - each group holds exactly one book kind, with its own denominators: adequate pairs,
insufficient, ineligible); the pooled per-setup view survives only as `pooledDiagnostic` with
`performance=false` and the label "DIAGNOSTIC ONLY, not Tips Practice expectancy". `compare_row` carries
`bookKind` (`unknown` when absent - never assumed Practice) and `portfolioId`.

**HOLD-SCOPE-02 (confirmed, fixed):** the observation did not carry the book's quarantine status and `compare_row`
graded a quarantined shadow row adequate. Now every observation persists `book_status` at capture (quarantined,
quarantine note, archived, the position's status); `book_eligibility(row)` returns `quarantined` / `attention` /
`unknown` / `eligible`, and a non-eligible row keeps its computed arms as a DIAGNOSTIC (`diagnosticOnly=true`,
reason on the row) but is never `adequate` and never enters a performance bucket (counted under `ineligible`,
apart from `insufficient`). Rows captured before the column existed resolve their scope from the DURABLE
relationship (position -> portfolio -> kind / quarantined, labeled "resolved from the durable book as it stands
now") in the report tool; what cannot be resolved stays `unknown`. The prior shadow-book exclusion from trust /
lane grading is untouched - the hold study never reintroduces those books as evidence.

**Also (reviewer's coverage note):** the durable-close read now selects by the CLOSURE window (`state.closedMs` on
the session date) instead of a 45-day creation age, so a campaign opened weeks ago and closed today is observed.

**Tests:** the reviewer's `tests/test_hold_book_scope_review.py` adopted verbatim (2) + this desk's
`test_scope_provenance_is_never_assumed_practice` + hold study = 11 passed; prof142 4 passed; pr147 4 passed.
Sub-second pure checks; no broad cycle.

**Separated report example (runtime DB, 2026-09-16 evening, before the next-open sample; every number is
insufficient or diagnostic - nothing here is a result):**

| book kind | setup | obs | positions | adequate pairs | insufficient | ineligible (diagnostic) |
|---|---|---:|---:|---:|---:|---:|
| shadow | shares | 1 (AFRM 27 sh, ab ARMED shadow) | 1 | 0 | 0 | 1 - quarantined (EOD-09 2026-09-14 runaway; results invalid until reconciled) |
| sim | option:longer(>14d) | 2 (SLV, T on 2026-09-15) | 2 | 0 | 2 - outside_window (v1 rows) | 0 |
| sim | shares | 2 (MRNA 09-15 outside_window; MRNA 09-16 next-open pending) | 1 | 0 | 2 | 0 |

Pooled diagnostic (labeled, not performance): shares obs 3 = sim 2 + shadow 1. Honest sample for tomorrow: ONE
prospective Practice carry pair (MRNA 7 sh, eligible if its 09:30-09:45 ET bid qualifies); ZERO validated shadow
pairs (AFRM stays diagnostic). Today's three intraday exits (T, SLV, GOOGL Oct-16 360C) stay MISSING - not
backfilled with later quotes.

**Accounting labels (reviewer):** T's +$3.64 is today's FINAL TRANCHE (x4 @ 0.5499), not the round trip - the
completed T campaign (opened 2026-09-10) earned +$102.84 net. Fees charged to cash today were $7.28 (4 executions);
today's matched realized -$63.66 additionally allocates $5.20 of prior T/SLV entry fees (allocated entry + exit
fees $12.48 against gross -$51.18). The two fee views are reported apart from now on. Equity baselines: day-boundary
03:59:57 ET $8,923.85 (change -$117.64) and pre-open 09:29:52 ET $8,934.63 (RTH marked change -$128.42); neither
is realized P&L.

**Deployment:** merged, not deployed; recap routing stays OFF; paid pairs stay held. After the coordinated deploy:
verify the live build and the MRNA venue stop (SELL 7 STP 134.37 GTC).

## CAP187-01 (Codex, research follow-up after HOLD-SCOPE clearance) - the close transition is capture-safe

**Confirmed, fixed:** `PositionManager._mark_closed` popped the position from memory and only then persisted the
closed row; a capture between the two saw the close nowhere (the hold-study integration test failed twice on
that race). The write now happens first and the pop follows in a `finally`, so a reader finds the closed
position in memory until the durable row carries it. One ordering change on the shared close path - no order,
stop or journal behaviour changes (PLATFORM-RULES entry "A durable position is persisted BEFORE it leaves
memory"). **Deterministic test** `test_close_transition_is_capture_safe_at_the_persistence_boundary`: the hold-study
snapshot is invoked from inside the manager's own persist call for the closed transition - it asserts the
boundary was real (still in memory, durable row not yet closed) AND that the capture recorded the
`intraday_exit` observation; a later capture adds nothing (one observation per key). The existing
integration assertion (`n2 >= 1` after `wait_for(gone)`) is preserved, not weakened. Today's three missed
intraday exits stay MISSING - nothing is repaired or backdated. MRNA's carry observation is unaffected.

## End of session 2026-09-17 (16:06 ET) - observation-and-validation day

Live build all day: 0.8.09 `dd525de` (EM desk's release; every Tips merge through PR #188 is an ancestor). Merged, NOT
deployed: PR #196/#197 (Knowledge pagination, live already via 0.8.08), PR #199 (sim share-session + spread guards, 0.8.10;
runtime checkout `70f6b90`, rides the EM desk's coordinated deploy after the close). No restart during the session.

**Tips Practice - fills, exits, P&L (cash fees and allocated fees stated apart):**

| Position | Entry | Exit(s) | Cash fees | Realized | Label |
|---|---|---|---:|---:|---|
| MRNA 7 sh (campaign opened 2026-09-15) | 141.96 | 09:39 2 @152.97 (source follow-up), 09:45 2 @154.37 (TP1), 09:55 1 @156.45, 10:00 1 @159.59 (follow-ups), 11:04 1 @157.11 (venue GTC stop) | $0.00 | **+$94.10** whole campaign (five tranches today) | overnight-hold pair's managed result: known (+$94.10 vs quote-drift +$69.02 at 09:30) |
| MRNA Sep-18 165C x1 | 10:04:54 @0.75 | 10:04:58 @1.90 (premium TP1 +100%, quote watch) | $2.08 | **+$112.92** | **SUSPECT FLASH FILL (F-FILL-02)**: decision quote 1.90/2.01, fill on a 3-second OPRA quote 0.65/0.75 sizes 7x1, TipFillVsQuote vsMid -1.205 (-$120.50 "improvement") |
| ORCL Sep-25 160C x1 | 10:24 @1.64 (ask; 1.63/1.64) | 11:04 @1.44 (12% premium stop, second distinct observation) | $2.08 | **-$22.11** | clean fill (vsMid +0.005) |
| SMCI Sep-25 41C x1 | 10:45 @1.59 (ask; 1.55/1.59) | open | $1.04 | marked -$26.00 | clean fill (vsMid +0.02); premium stop guard, target 41.3 |
| ACHR Jan-27 7C x3 | 11:38 @0.48 (ask; 0.47/0.48) | open | $3.12 | marked $0.00 | clean fill (vsMid +0.005); fixed stop 4.75, ladder 5.95/6.6/7.4 |
| SBLK 62 sh | 14:48 @31.91 (ask; 31.89/31.91) | open | $0.00 | marked -$6.82 | clean fill (vsMid +0.01); venue GTC stop 30.58 for 62 (geometry moved 30.95 -> 30.58 inside structure); overnight `venue_stop`, hold cap 15 sessions |

Cash fees charged today: $8.32 (12 executions; shares $0, options $1.04 per contract per side). Realized today on Tips Practice:
**+$184.91** (ledger trips), of which $112.92 is the suspect flash fill; excluding it, +$71.99. Equity baselines (Tips Practice,
`equity_points`): day boundary 03:59:56 ET $8,822.87; pre-open 09:29:49 ET $8,858.64; close 16:01:30 ET **$8,925.42**
(change on the day-boundary basis +$102.55; RTH marked change +$66.78). Desk-wide realized today +$374.30 (EM ORCL b1
+$250.92, CRCL puts +$53.76, SCHW/TXN/COHR/BMNR mixed; Team2 QQQ 0DTE -$33.28) - not reconciled here beyond the Tips rows.

**Decision funnel (every tip counted):** 56 signals today across 8 sources. Verification failed 33 (no proposal: ab 2,
common-stock 3, eva 4, jon-and-kian 1, MK-alpha-trades 4, muggzone-options 15, neal 2, tt 2); parked 2 (eva) + 1 later
(SignalParked x3); shadow-only 1 (eva). Lane decisions 13, all `proposal`. Cards 15: **executed 5** (MRNA 165C, ORCL 160C,
SMCI 41C, ACHR 7C, SBLK - analyst `take` on each), **rejected 9** (analyst `skip`: 6 on the $89-90 planned-risk budget -
MRNA 165C 09-25 map, MU 980C, GOOGL 355C, MU 1035C, ORCL 170C second leg, HOOD 110C; 1 contract-identity fail - AMD 170C
deep ITM; 1 undisclosed average-down - MU 980C 15:56; 1 wish/no-stop - AMZN 265C), **expired 1** (AMZN Nov-20 300C x2,
review-gated on budget, unanswered 10:28 -> 12:28). Entry-timing cohort: 18 rows (proposed 5 fresh; blocked 6 fresh + 3
ineligible; parked 2 missing + 1 fresh; declined 1 ineligible). Shadow books (research, never performance): immediate
books bought on every tip (ab 2, eva 2, muggzone 5, tt 2 buys, no sells); armed books: ab AFRM (QUARANTINED book, pre-market
stop fill at 03:59 then re-entry 09:35), muggzone MSFT (+$3.02 TP1). By setup: shares 2 Practice entries (MRNA campaign
close, SBLK), options 4 Practice entries.

**Cards / geometry:** 27 `TipGeometryRepaired` events, 9 of them review-gated (all "no quantity satisfies the budget" -
declined by the analyst except the AMZN 300C card, which expired). Repairs with substance: MSFT adoption stop re-placed
(armed shadow), SBLK stop 30.95 -> 30.58 (pre-entry, submit, post-fill kept), AMD/MU wrong-side targets dropped on cards
that were then skipped. **Incidents:** none opened, none released; no fast-stop diagnostic, no auto-pause, no retry, no halt;
2 `TipIntakeStalled` during the in-flight backlog (5 -> 12 envelopes, drained to 0 by 11:30) - not a stall.

**Execution-cost diagnostics (TMR-02 on 0.8.09):** `riskPlan.execCost` present on every card (known where the quote
qualified; honest `unknown` with reason where it did not); `TipFillVsQuote` on all 5 genuine entries - 4 at the ask
within a cent of mid, 1 flash fill. **F-FILL-02 (finding, no change made; user/reviewer decision):** the sim executor
applies no spread or flash sanity to options by design; a one-lot OPRA quote 60% below the surrounding market lived ~3 s and
priced a Practice fill that banked +$115 in 4 s; a shadow book showed the same at 09:30 (GOOGL 355C on a 3.60/6.35 1x1
quote). Candidate rule: refuse/flag an option fill when the top of book is 1x1 with spread > ~40% of mid, or when the
price deviates > ~35% from the last qualified mid within 10 s. Labeled suspect in every number above.

**Carried overnight (Tips Practice):** SBLK 62 sh with the venue GTC stop 30.58 (single exit authority verified: entry
bracket children cancelled, `venueStopQty` 62); SMCI Sep-25 41C x1 and ACHR Jan-27 7C x3, both long options, app-managed
(premium-stop guard / fixed stop + ladder), `overnight` acknowledged by the analyst policy. NOTE: the live executor is still
pre-0.8.10, so SBLK's stop could trigger pre-market on a placeholder quote (F-HOLD-01) until tonight's deploy.

**Hold study, 15:50 ET capture (first on the fixed code, `book_status` stamped):** 9 observations. Tips Practice (sim):
carry SBLK, SMCI 41C, ACHR 7C (all fresh, inside window); intraday_exit MRNA 165C (exit 1.90), MRNA shares (avg exit 155.40),
ORCL 160C (1.44). Shadow: AFRM carry + AFRM intraday_exit (44.991 - the 03:59 fill; book QUARANTINED -> diagnostic only),
MSFT intraday_exit (armed shadow). Yesterday's three missing exits stay missing. Next-open sample 09:30 ET 2026-09-18 for
the three Practice carries; the MRNA pair from 09-16 is now complete on the managed side (+$94.10 campaign vs +$69.02 drift).

**Armed multi-day tip plans rolling at the close:** 12 (AAL, AAOI, AMZN, DAL, GOOGL, MSTR, MU, PLTR, RKT, SBLK, T, TSLA).
**Tonight's jobs:** `tip_retro` judges the three Practice closes (MRNA shares +94.10, MRNA 165C +115.00, ORCL 160C -20.03)
and the two shadow closes (AFRM -730.05 quarantined, MSFT +3.02); `tip_knowledge_maintenance` stays propose-only (batches:
23 proposed, 4 applied historically, 14 failed scopes set aside); digests per knob.

**Research coverage:** cohort 18 rows; analyst runs 105 (13 appraise all with the exact context manifest AND a captured
classifier read - `TipRecapClassified` is live on 0.8.09, 92 rows today); `TipEntryStudy` 28. **Frozen pair readiness:**
bundle `fb-e0221ed3d071cc60` captured from today's SBLK take run (manifest exact, 6 tool outputs, 48 rules, 12 notes,
classifier `recap-read-v2`) and `tip_frozen assemble` produced both treatments offline with `gaps: []` - `current` = the
full-route CONTROL (`headerMode full`), `recap_candidate` = treatment-only (correct label on a full-route capture; the
candidate's 24-hour history bound is not verifiable on captured lines - stated). This is the first COMPLETE offline
full/candidate pair; the paid replay is the user's/reviewer's call - none run. Recap routing OFF.

**Platform notes today:** 32 event-loop stalls - EM desk diagnosis: host paging (commit 57.7 GB vs 32 GB physical; 79 s at
11:25, ~27 s at 13:29/13:31 in WSARecvInto = process not running) plus one real cluster 08:26-08:33 PT from the Cartel
profitability collector; mitigation = fewer resident processes (user). Verified events set 09:26 ET from official sources
(DOL claims 08:30, Philly Fed 08:30, Treasury auctions 11:30/13:00; 09-18: Fed G.17 09:15, Bowman 09:30, BLS state
employment 10:00). Open items owned elsewhere: Telegram paging credentials empty; ab shadow book quarantined; TSLA on eva
armed shadow in `attention` since 09-14.
