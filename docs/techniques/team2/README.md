# Team2 technique — research folder

*Started 2026-09-03. Candidate technique #4 for the multi-technique platform
(`docs/TECHNIQUE-PLATFORM-PLAN.md`; build guide `docs/BUILDING-A-TECHNIQUE.md`).
Working id: `team2` (display "Team2"); rename before registering if the user prefers.*

**Desk decision (user, 2026-09-03): this session/group IS the Team2 desk.** Team2 is built completely
separately from EM — its own docs, plan builder, runner, review loop and evolution loop, with the goal of
arming its own plans every night. Shared engine code and generic tools are reused; nothing inside EM's
package is touched for Team2.

## What this is

Casey (@Team2Trading) day-trades SPY / QQQ / IWM options off four daily levels (previous-day
high/low as 15m zones, pre-market high/low as lines), a 13/48/200 EMA regime read on the
2-minute chart, a 15-minute-close confirmation of level breaks, and 2-minute pullback entries
with a one-candle stop. He says the whole method is public on his X feed; the Discord adds
live alerts. This folder holds **everything we captured, verbatim, so it never has to be
fetched again**, plus our codification of it.

## Doc map

| File | What |
|---|---|
| `README.md` | this — status, capture method, next steps |
| `METHOD.md` | the codified rules (L/B/E/C/T/S/X/Z numbering), version drift, open questions, engine-fit notes |
| `SOURCES.md` | index of every captured post: date, id, kind, one-line summary, note file |
| `notes/x/*.md` | one file per X post/thread, text verbatim with frontmatter (url, date, capture method, what images were NOT captured) |
| `notes/x/PARTIAL-…md` | ids seen but not (yet) captured |
| `notes/video/*.md` | auto transcripts of the author's videos (`tools/transcribe_video.py`; audio in `notes/video/media/`, gitignored) |
| `PLAN.md` | the desk plan: charter, decisions D1–D14, engine work list §3b, completeness review §3c, build phases P0–P6, testing bar |
| `TRADING-RULES.md` | the desk's judgement log: rules under observation, findings, theories, change log |
| `tools/` | `extract_threads.py`, `build_sources_index.py`, `transcribe_video.py`, `fetch_tweet_media.py` |
| `notes/x/images/` | 145 tweet images (jpg, local only) + JSON metadata + `INDEX.md` describing the ones read |
| `AUTHOR-STUDY.md` | Codex's independent source study of the author (2026-09-08): explicit / demonstrated / interpretation / unresolved labels per rule |
| `CODEX-REVIEW-SCRATCHPAD.md` | Codex's review charter and baseline notes for its independent Team2 review task |
| `notes/archive/market-watch-2026-09-03-to-09-14.md` | the 30-minute market-hours watch log, RETIRED 2026-09-24 (replaced by the end-of-day receipt, `team2_exit_review` and the opportunity audit; findings mirrored into TRADING-RULES) |
| `notes/research/` | dated research notes: author-study evidence (09-08), review feedback, the week-37 review + change plan (09-12) with its addendum, the C2 key-levels spec (09-13), the C1/sizing controlled comparisons and the sizing-cap experiment sheet rev. 2 with its §2b parallel design (09-15). `c6-evidence.json` is the reviewed C6 record the readiness receipt reads (`satisfied`, `reviewedBy`, `date`, `datasetVersion`, `reference`) — absent until C6 lands |
| `notes/research/2026-09-17-premarket-input-reconciliation.md` | the 09-17 frozen-vs-bank reconciliation: the private tape accepted exchange corrections the bank never kept (SPY 660.65, IWM 283.92, QQQ 716.76); mechanism, evidence, C6 consequence |
| `notes/research/2026-09-16-c6-completion-plan.md` | C6 (one tape) — definition, what is measured today, the completion steps with owners and evidence, the receipt path; never waived |
| `notes/research/profitability-20260915-exploratory/` | the exploratory profitability comparison: `research_profit.py` (48 paired cells 08-20 → 09-11, tape `27516b61…`), `calibrate_practice.py` (Practice-scale on the loss-risk sizing basis, 40-contract cap), JSON outputs. EXPLORATORY, pre-C6 — never label it canonical |
| `notes/research/week37-author-charts/` | the author's annotated charts for the week-37 review (jpg, local only) |

Code: `backend/zargar/techniques/team2/` (see ARCHITECTURE.md); shared primitives live in `marketstructure/`,
`options/pick.py`, `research/` per `BUILDING-A-TECHNIQUE.md`. Run the technique's tests with
`pytest tests/test_team2_*.py tests/test_codex_*.py tests/test_marketstructure_extended.py` (own DB `zargar_test_team2` on :5433;
the `test_codex_*` files are reviewers' regressions adopted verbatim; `tests/test_book_pause.py` covers the per-book pause);
sweep with `python -m zargar.tools.team2_sweep` (`--set key=value` overlays = the only way a variant is measured);
C2 paired report `python -m zargar.tools.team2_c2_report` (validation window sealed in the tool); experiment readiness
receipt `python -m zargar.tools.team2_receipt` (read-only: PREPARED vs READY, blockers, cardinality, provenance, C6 record);
pre-market input audit `python -m zargar.tools.team2_pm_audit --date <session>` (read-only: frozen PMH/PML vs the bank, contributing
minutes and their revision chains); diagnostics report `python -m zargar.tools.team2_diag_report --date <session>` (shadow measurements: entry situations and contract
choices after costs, with coverage; `techniques/team2/diagnostics.py` is the pure module, `tests/test_team2_diagnostics.py`;
v0.8.02: a quote is evidence only when live, sane and fresh by its own source timestamp; unknown enters no denominator).

## Status (2026-09-16)

> **2026-09-19 profitability study, corrected pass (read this first): `notes/research/profitability-2026-09-19/00-decision-sheet.md`.** Decision:
> INSUFFICIENT EVIDENCE of an after-cost edge. Simulated on real option prints the baseline's mean is -3.7% per trade (date-clustered
> 95%: -7.9 to +0.8) at the books' fee, about zero with no fee, -7.6% at one tick per leg; the print proxy itself errs by about three
> cents per leg against our fills. Nine preregistered variants failed their criterion. The product replay's premium formula reports
> +22% on the same trades, so formula-scored sweep figures below are unreliable. Control / Sizing 0.5 / C1 were left untouched.
> Next step, accepted by the review team: the ORDER-FREE selection study. Its collector is built and DEFAULT OFF
> (`techniques.team2.selection_study`, `notes/research/profitability-2026-09-19/08-collector-package.md`); it is not enabled or deployed.

**Where the desk stands.** Team2 trades its own Practice book (`Team2 Practice`, $10,000 start, sim fills on live NBBO)
in `auto` mode since 2026-09-08 (auto on the shared Practice book from 2026-09-04). Live release **v0.7.94** (deployed
2026-09-15 evening). Plans for SPY/QQQ/IWM are minted at 17:00 ET and armed automatically, completed at 09:25 and
finalized on the 09:30 open. Risk limits: $2,000 premium per trade, 6 % loss risk, 0DTE cap 40 contracts, 10 %
technique day-loss pause, 15 % book breaker, two losses per book per day, flatten 15:45. Deploys go only through the
scheduler's `ZargarRestart` task after `/api/ops/restart-check` says clear (PLATFORM-RULES invariant 18; assistant
shells are elevated and `start.ps1` refuses them). A scheduled watch job reads the desk every 30 minutes in market hours.

**Evaluation cohorts.** Cohort v1 (2026-08-26..09-10): read evidence only — the synthetic strike grid, the delayed-chain
veto, the model veto, stale gap-day targets and the F75 history defects meant the book rarely reached an order (one
filled day, 09-08 QQQ, −$66). **Cohort v2 started 2026-09-11 on v0.7.45+**: listed strikes are the ladder, live quotes
are the only contract authority, one warm-up rule, and the full candidate → quotes → verdict → order → fill → exit
trail is journaled (`TechniquePlanContract`, `TechniquePlanRead`, trail gaps recorded). The 2026-09-14 EOD corrective
batch (A–G, v0.7.73 → v0.7.82, CLOSED by the other team) and the F127 cap clamp (v0.7.88) apply from 2026-09-15.
**First cohort-v2 fills 2026-09-16:** two QQQ scenario-1 entries (23 and 18 contracts), both stopped inside four
minutes, −$480 on the book ($9,934 → $9,454); the 09-15 IWM candidate had been refused by the F127 defect. One day
proves nothing either way. Twenty sessions of cohort v2 trigger a REVIEW, never a promotion (PLAN §3d).

**Profitability track (2026-09-15, both steps accepted by the other team).** The exploratory controlled comparison
(`notes/research/2026-09-15-c1-and-sizing-controlled-comparisons.md`; pre-C6 Yahoo tape, 48 paired cells) put the
**sizing cap first** (`size_full` 0.5: Practice-scale +$2,231 / DD −$635 vs baseline +$1,374 / DD −$993 on the
loss-risk sizing basis) and **C1 conjunction** as the follow-on (+$6,415 but DD −$2,619 = 26 % of the book). The
experiment sheet rev. 2 (`2026-09-15-sizing-cap-experiment-sheet.md`) is accepted: a sampled −$800 marked-to-market
review threshold per book whose breach PAUSES that book (entries and adds off, exits on, no automatic revert to 1.0),
ten completed sessions, twenty fills = interim review, fills judged separately from the labelled replay.
**Parallel experiments are BUILT, PREPARED and OFF (v0.7.93 → v0.7.94):** three labelled sim books at $10,000 —
`Team2 Control`, `Team2 Sizing 0.5` (role `sizing`, `size_full` 0.5, −$800) and `Team2 C1 Conjunction` (role `c1`,
`no_trade_zone=conjunction`, −$1,000 policy threshold) — described by `techniques.team2.experiments` (validated
whole-map schema, one override per role, control = the default book, overrides FROZEN on the plan at mint, per-book
loss/concurrency counters and pause, sim-only, verified transitions that block minting when unconfirmed). The
read-only receipt (`python -m zargar.tools.team2_receipt`) reports **PREPARED with the single blocker C6**. Activation
path: reviewed `notes/research/c6-evidence.json` → `techniques.team2.default_portfolio` = Control →
`experiments.enabled=true` → forced plan-now → receipt READY → the other team's GO. Until then `Team2 Practice` stays
the default book, nothing is paused, research settings are unchanged, and no experiment touches a real-money account.

**Profitability diagnostics (2026-09-16 evening, v0.8.01, other team's EOD GO).** After the day's two QQQ stop-outs (−$480) the
review asked for MEASUREMENTS, not filters: the close report now counts unique decisions from a durable ledger (the display buffer
had evicted refusals) and carries an immutable decision-time view beside the corrected-history rows; every fire records its entry
location (confirmation close, pullback candle, level, entry line, the underlying at the order boundary, ATR distances; labels
`sameCloseConfirmation` / `movedAway`) and its attempt context (first vs subsequent into the setup, previous loss); the picker keeps
the selected contract and the alternatives it examined with quotes and Greeks and follows them at 2/5/10 min and the actual exit
for after-cost comparison (unknown stays unknown); allocation-refused candidates are quoted in the shadow. Report:
`python -m zargar.tools.team2_diag_report --date <session>`. No delta floor, entry-distance cutoff or re-entry ban exists — the
review chooses from evidence. Baseline and the three experiment books are unchanged. **C6 is the priority dependency**: the
completion plan is `notes/research/2026-09-16-c6-completion-plan.md` (the banked exchange tape covers every RTH minute of
2026-08-20 → 09-16 for all three symbols; the open item is the live-vs-replay ATR difference and the reviewed evidence record).

**2026-09-17 development (v0.8.12, PR open — deployment NOT approved):** the target identity guard (a setup's destination must be
distinct from and beyond its source level, judged alike for EMA and level entries; `skip_target_collision`; switch
`techniques.team2.target_identity_guard`), pre-market extrema provenance + `team2_pm_audit`, chain-listing cache/coalescing/retry,
and the shadow payoff/room/coverage/gross-vs-net diagnostics. The 09-17 book: −$33.28, all commissions, one 16.8 s round trip.

**Rules under observation / research (TRADING-RULES "Rules under observation"):** F81b `target_replan=structure` (gap
days) ON since 09-09; C1 no-trade zone = B5 conjunction, C1 room rule and C3 minimum target room BUILT BEHIND KNOBS AND
OFF (v0.7.53) — C1 now has its labelled experiment book prepared; **C2 multi-day key levels BUILT behind `key_levels`
(OFF, v0.7.58–0.7.61), accepted, development sweeps GO once C6 lands, validation 2026-09-14 → 10-09 sealed in the
report tool**; C4 add on retest and C5 breakeven after trim have no frozen definition. Near-ITM contract eligibility is
an open user decision.

**Built (milestones):**
- 2026-09-03 v0.1: shared primitives (ext-hours bars, aggregation, EMA, zones, market calendar, VIX proxy), the pure
  read `session.py` used live and in replay, runner, service, RiskGate 0DTE policy, premium-targeted picker, API, page,
  sweep CLI. 2026-09-04: second image review (T7/T8/E5/X5/X6/V12), posture pass (adds, HOD target, live-premium
  trims), auto mode, halt scopes, F13–F46 from the first live days.
- 2026-09-08 v0.7.13: engine hosting moved out of the assistant's process tree (watchdog + restart tasks), read
  integrity (fingerprints, session sigma from the chain, open finalized on the 09:30 bar, target breach hook).
- 2026-09-09 v0.7.28–0.7.32: the F75 shared-history repair (bar provenance, calendar gate, sim isolation, quarantine
  + Alpaca backfill, content-hashed datasets, session validation in every consumer, restart readiness door); Codex's
  ten review findings fixed with their regressions adopted verbatim.
- 2026-09-10 v0.7.34–0.7.49: F81 gap-day target re-derivation (+ F81b entry-time fallback), the picker rebuilt on
  listed strikes and fresh quotes (F104/F105/F108), one warm-up rule (F99), EM scorer boundary (F107), the journaled
  trail and trail gaps, the watch job's F88/F91/F100/F101/F106/F110/F111 fixes.
- 2026-09-13 v0.7.53: C1/C3 research knobs (off), ordered no-trade-zone truth table, chronological + book-level
  assessment tooling (scratch), C6 request to the platform owners.
- 2026-09-13 v0.7.58–0.7.61: C2 definitions D1/D2/D3 built behind `key_levels` (off) with the flip/expiry state
  machine, masks, key-level confirmations/retests/target rungs, sweep funnel and 19 causal fixtures; two review rounds
  (setup identity, hard cluster diameter, no ATR fallback, then a REGRESSION: the tie-break had reached zone/PM
  selection with C2 off — scoped and fixed the same evening); the paired report tool `zargar.tools.team2_c2_report`.
- 2026-09-14 v0.7.73–0.7.82: the EOD corrective batch A–G (CLOSED) — durable refusal overlay riding the shared
  `state_extras`/`restore_extras` hooks, ONE `entry_gate` at pre_order/order/retry plus the synchronous
  `entry_guard_predicate` inside OrderManager's `before_submit`, per-plan decision watermark (`backdated_signal_skip`),
  funnel from durable verdicts (`journalOnly`), uncertain submissions (`SubmitUncertain` → trade stays `submitting`,
  resolved only by the venue's report or the persisted order row at restore) with cumulative fills booked before
  classification, present-time S1 stop for a position the model no longer holds (`orphan_stop`). Four reviewer packets
  adopted verbatim (`test_codex_team2_v076_boundaries`, `v078_reconciliation`, `v080_terminal_fill`, `v081_cumulative`).
- 2026-09-15 v0.7.88–0.7.94: F127 — the sizer clamps to the 0DTE cap only for a contract whose OCC expiry is today
  (v0.7.88); per-book pause surviving restart and day rollover (v0.7.90, `POST /api/portfolios/{id}/pause`); the
  exploratory comparisons and the sizing-cap sheet; parallel experiment infrastructure (v0.7.93) and its two review
  rounds (v0.7.94: strict whole-map schema with roles, frozen overrides, sim-only arm, verified transitions,
  provenance-stamped plans `appVersion`/`build`/`codeVersion`, receipt cardinality + C6 record, read-only settings
  load); door fixes (restart transcript before the lease, 300 s lease wait naming the owner, `start.ps1` refuses
  elevated shells, 180 s health wait).

**Open (by choice or pending):** C6 one tape (F119, platform owners) — the only blocker on the receipt; the other
team's activation GO; C2 development sweeps (after C6); C4/C5 definitions; near-ITM policy (user); the twenty-session
cohort-v2 review; 5m flag detector (A5) and intraday zones (A11) never built; `/team2-review` skill not built (the watch
job and dated research notes do that work); the sweep still walks a synthetic strike grid for history (no as-of
listings) and scores the model's premium path, not fills; test debt: `test_nightly_plan_arm_and_alert_mode_fire` is
time-of-day dependent (fails after 20:00 ET on main).

## Known gaps, risks and what could be wrong (2026-09-16 — read this before trusting any number above)

- **Every sweep number in this folder is a MODEL result on YAHOO's tape.** The premium is Black–Scholes at one sigma
  (12–45 % optimistic on the author's documented trades, F8), the strike is a synthetic $1 grid for history (F104: no
  as-of listings exist), and the bars are Yahoo's while the live desk trades Alpaca's (F119: QQQ differs on 40 % of
  minutes). Until C6 lands, a sweep and the live book are two different experiments. Treat pnl%-sums as directional.
- **The Practice book has two filled days.** Cohort v1 produced one day with fills (09-08 QQQ, −$66); cohort v2's
  first fills came 2026-09-16 (two QQQ stop-outs, −$480) after four sessions without one — the 09-15 IWM candidate
  was refused by the F127 cap defect (fixed v0.7.88). Nothing in this folder is evidence of profitability. The twenty-
  session review is a checkpoint, not a verdict, and needs candidate-to-fill traces, not session counts.
- **Every profitability number is exploratory.** The 2026-09-15 comparisons ran on the pre-C6 Yahoo tape and the
  Practice-scale figures come from an APPROXIMATE calibration (`calibrate_practice.py`: loss-risk sizing, the $2,000
  budget and the 40-contract cap; research dollars never transfer). The sizing-cap edge is a drawdown story on
  identical trades; C1's edge concentrates in week 37. Both are hypotheses with a frozen sheet, not results.
- **The shadow diagnostics have never run a live session** (v0.8.01 deployed the evening of 2026-09-16; the review's three
  boundaries fixed in v0.8.02 the same night — a follow-up is unknown unless the quote is fresh by its own source time): the follow-up quotes
  ride the ~2 s quote watch and the options service's live re-pricing; the first session will show how many observations come back
  UNKNOWN (no OPRA quote, taken late after a restart). Counts will be tiny; the report ranks, it does not decide.
- **The experiment infrastructure has never run a live session.** Minting, arming, restart identity and transitions
  are proven in tests (one on the real engine) and the receipt has said PREPARED on the live desk — it has never said
  READY, and no experiment plan has been armed for real. The first live experiment day is the first test of the
  per-book counters and the pause-on-breach path under real quotes.
- **The read agreeing with the author is not the same as trading like him.** Three of his week-37 entries were inside
  the pre-market range or on a multi-day level our rules do not carry. C1/C2 are hypotheses with frozen tests, not
  fixes; C1's gain concentrates in one week and raises drawdown; C2 is unmeasured.
- **Regressions have reached the live path from research code twice in one day** (the 0.7.46 duplicated version
  fields earlier in the week; the 0.7.60 tie-break that changed zone/PM selection with C2 off). The guard is the
  reviewers' before/after tests and the "byte-identical with the knob off" tests — which compare on/off within the
  NEW implementation, not against a snapshot of the old one. A change to `session.py` should be assumed to touch the
  live read until a before/after test says otherwise.
- **The watch job and the desk both edit TRADING-RULES and release versions**; three desks release several versions
  a day; version collisions happened five times. Always check origin/main's `APP_VERSION` before stamping, and never
  resolve a version-file conflict by keeping both sides.
- **Execution-state durability (v0.7.76)**: the refused-fire list and the decision watermark ride the armed state on
  every persist and are rebuilt from the journal; a crash between a journaled verdict and the next persist is reported
  as `journalOnly` evidence in the funnel, never as zero. Not yet exercised by a real mid-session restart.
- **Corrections**: a fire/add/trim/exit that a corrected minute surfaces after its minute was judged is recorded
  (`backdated_signal_skip`), not acted on — including a historical EXIT (judgement accepted by the other team
  2026-09-14). Since v0.7.78 a book position the model no longer holds keeps the method's present-time one-candle stop
  (`orphan_stop`, S1 on the current 2m close) besides the live trims, target breach, quote stop and flatten.
- **Uncertain submissions (v0.7.78, resolved v0.7.80)**: an entry whose venue hand-off got no answer stays `submitting`
  (exposure reserved, order id registered, alert raised) until the venue's own report of that order arrives — live, or
  read from the persisted order row after a restart. An in-flight or missing row keeps the uncertainty; a human may
  still have to look at the venue. Not yet exercised against a real venue.
- **Journal completeness**: `_log` events are in-memory (capped, lost on restart); only `_trail` writes are durable.
  A plan whose snapshot shows `trailGaps` is an incompletely observed session. The morning-report line, the
  `/team2-review` skill, the 5m flag detector (A5) and intraday zones (A11) were never built.
- **Execution-path unknowns**: OPRA quotes have dropped for ~49 minutes in a session (F117) — entries are deferred,
  not filled, during an outage; fills are sim fills at the live NBBO, never real fills; the never-chase cap and
  premium stop have not been exercised by a live-money order.
- **Open user decisions**: near-ITM contract eligibility (the author's 288p under 287.83); whether C1 gets a labelled
  Practice experiment after C6; whether F81b stays after its ten live gap-day entries.
- **The door has sharp edges**: assistant shells on this machine are ELEVATED — `start.ps1` refuses them (exit 8) and
  an engine booted elevated can only be stopped by the user's elevated `stop.ps1` (F89); the watchdog restarts the
  engine within ~3 minutes of a manual stop; `restart.ps1` skips its restoration comparison when the pre-stop inventory
  capture times out — compare armed / resting / managed counts by hand when the transcript says so.
- **Test debt**: `test_nightly_plan_arm_and_alert_mode_fire` depends on the wall clock (fails after 20:00 ET on
  unpatched main); `test_auto_options_one_contract_lifecycle` (EM) fails on unpatched main; three restore/nightly
  tests are load-flaky under parallel suites and pass alone; the FA-01 parameterizations in
  `test_codex_team2_v076_boundaries.py` are skipped on main because `_entry_guard` lives only on the EM branch.
- **Docs that can drift**: PLAN §2's decision table and this Status block are hand-maintained snapshots; the change
  log in TRADING-RULES is the authority when they disagree. METHOD §11 and PLAN §3b/§3c are 2026-09-03 build notes
  kept for history, not current descriptions.

## How the data was captured (so it can be repeated)

- **Logged out** (in-app browser or curl): single `x.com/Team2Trading/status/<id>` pages render the post text; the
  unauthenticated profile shows only the ~5 newest posts; `cdn.syndication.twimg.com/tweet-result?id=<id>&token=a`
  returns the full text + media URLs as JSON for any id (no login, occasionally rate-limited);
  `pbs.twimg.com/media/<id>.jpg?name=large` serves the image. WebFetch gets 402/403 from X; Thread Reader
  (`threadreaderapp.com/thread/<id>.html`) unrolls threads someone once unrolled and its "More from" cards expose
  earlier ids via `div[data-link-href]`.
- **Logged in** (the user's Chrome through the Claude in Chrome extension; pick the browser with `switch_browser`,
  the user names it, e.g. "i7 Home Laptop"): `x.com/search?q=from%3ATeam2Trading%20since%3AYYYY-MM-DD%20until%3AYYYY-MM-DD&f=live`
  lists every post and reply for a day (dates are UTC-ish, use a two-day window); `read_page filter=interactive`
  exposes the status ids, then fetch each by id as above. Never type credentials; the browser must already be signed in.
- Truncated tweets in a thread expand by clicking every "Show more" via `javascript_tool`. Search engines index only
  a fraction (`site:x.com Team2Trading <phrase>` found ~12 ids). Bulk pages: `extract_threads.py`.
- Images stay local (`*.jpg` gitignored, 2026-09-03 user decision); the JSON metadata and INDEX.md are committed.

## Not captured yet (ids known)

See `notes/x/PARTIAL-threads-seen-not-yet-captured.md` and the tail of `SOURCES.md`. The
chain keeps going back through 2024; the 2025–2026 material already states every rule
several times, so older threads are low value except for the bull/bear flags thread. Week-37 posts
(2026-09-09..09-12) are indexed in `SOURCES.md` with their ids; their text lives in the week-37 review note.
