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
