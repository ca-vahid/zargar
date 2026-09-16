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
