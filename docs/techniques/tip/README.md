# Tips desk — state of play, what changed, known gaps

*Start here. Dated; the newest entry wins over any older doc in this folder. Update this
file whenever a rollout, an activation or a review changes what is true. Last full refresh:
2026-09-23 (adversarial review + plan implementation, 0.8.34). Superseded state-of-play text lives in
`HISTORY.md` - nothing is deleted, only moved.*

## Doc map

| File | What it is | Currency |
|---|---|---|
| `README.md` | this file — state, changes, gaps | current |
| `PLAN.md` | design record + decision log for intake → books (2026-08-27/28) | as-built history; its "Status" section is 2026-08-29 |
| `BUILD-PLAN.md` | Phase B (options expression) task list | as-built history (done) |
| `INTAKE-PLAN.md` | Discord auto-intake boundary, gateway, mirror | current; gateway ledger detail in `GATEWAY-PLAN.md` |
| `ANALYST.md` | the Tips Analyst charter (+ §10: the 2026-09-15/16 rules and tools) | current |
| `ARM-PLAN.md`, `ARM-GAPS-PLAN.md` | tip → arm enrichment, gap clusters A–F | as-built 2026-08-29; §0 wiring map still accurate |
| `GEOMETRY-RISK-PLAN.md` | pre-entry geometry + risk sizing | ACTIVE since 2026-09-14 (enforce) |
| `KNOWLEDGE-PLAN.md`, `KNOWLEDGE-BUILD-PLAN.md` | shared notes, TTLs, audits, safeguards, maintenance cycle | current through round 3 + the 2026-09-14 consolidation |
| `TRADING-RULES.md` | the METHOD judgement log (findings, change log) | current — every rule change is dated there |
| `research/EXPERIMENT-REGISTER.md` | the one identity per research experiment (mirror of `experiments_register.py`) | current (TMR-05) |
| `research/HOLD-STUDY-REPORT-TEMPLATE.md` | the paired hold-study report format | current |
| `research/2026-09-16-time-vol-scenarios.md` | time/IV scenario design + worked example (prototype, wired to nothing) | current |
| `research/2026-09-23-adversarial-review-and-plan.md` | the adversarial review, the plan and the measured results of its implementation (ADV-01..12) | **current - the working plan** |
| `research/FIVE-SESSION-CHECKPOINT.md` | durable owner of the five-session observation report (09-21..25) | current |
| `research/2026-09-22-s21-package.md`, `research/2026-09-19-*.md` | the September 21 / 19 review packages (decision tables P1-P11) | current record |
| `research/economics/` | generated reports (scorecard, dispositions, gate, context cost, model plan) | dated outputs |
| `HISTORY.md` | superseded state-of-play and "what changed" text from older refreshes | archive |
| `reviews/` | external review rounds, responses, deploy and incident records | dated records; `2026-09-14-kfin-response.md` (0.7.83–0.7.87, HOLD142, R147, the 2026-09-15 incidents) and `2026-09-16-tmr-plan-record.md` (TMR, INTRA, I175, the 2026-09-16 incident) are the current ledgers |

## State of play (2026-09-23)

- **Live:** 0.8.32 build `63613751` (S21 rev 2, deployed 2026-09-22 16:15 ET after the close); this package is
  0.8.34. Practice only: `trading.mode=practice`, every `allow_live_auto` false. Tips Practice
  (`techniques.tip.default_portfolio`) is the only book that trades tips; shadow books are research.
- **Five-session observation (2026-09-21..25) is running.** The relevance filter stays `observe`; the durable
  report owner is `research/FIVE-SESSION-CHECKPOINT.md` + the Windows task `ZargarTipsFiveSession`.
- **Economics to 2026-09-22 (scorecard v6):** marked -$820, priced model cost $736, marked after cost -$1,556
  over 10 sessions. Options cohorts realized -$1,034, shares +$360; mirrored source exits are the best exit
  class (+$332). Source return net of model cost is on the scorecard (only common-stock is positive).
- **Model cost lever (measured 2026-09-23):** conversation-scoped prompt caching cut the cost of four replayed
  3-turn reviews by 49.8% (`tools/tip_cache_pilot.py`). The compact review context was MEASURED UNSAFE (it lost
  a disarm and turned a close into a stop update) and stays off.
- **Entry controls:** geometry `enforce` (Practice), integrity pause, readiness cards, one exit authority -
  unchanged. New knobs from the plan are OFF by default (exposure caps, per-source review budgets, friction
  flag); the equal-risk share size is annotated on infeasible option cards (`shares_alternative=annotate`).
- **Knowledge:** propose-only; the pending consolidated ladder/trailing rule is non-operative until approved;
  37 operative rules, 41.7k chars on every call; rule reliance is NOT recorded (a known gap, ADV-11).
- **Research, observation-only:** entry-timing cohort, frozen + review capture, hold study (`holdstudy-v2`),
  MK own-book observe. The weekly one-page review is `tools/tip_weekly_review.py`.
- **Monitoring:** pre-open 08:52 ET, hourly ticks, 16:06 ET wrap-up (session-only crons - re-arm after a
  session restart). Deploys go after the close while Team2's study sessions count (a 09:30-15:45 ET restart
  excludes their session).

## What changed before 2026-09-19

Moved to `HISTORY.md` (2026-09-23): the 2026-09-15/16 change table, the E17 rounds and the
older state of play. They are accurate as history; the state above supersedes them.

## Known gaps, risks and what could be wrong (read before trusting a number)
- **Adversarial review + plan (0.8.34, `research/2026-09-23-adversarial-review-and-plan.md`, ADV-01..12):**
  measured results - conversation caching saves ~50% of a multi-turn review (built, knob `prompt_cache_scope`);
  compact review context is unsafe (built, off); the -$830 "first-seconds" option exits are NOT explained by
  overnight carry (sampled carry of <=7-DTE options was +$447 bid-to-bid on 5 samples) - they point at exits on
  the OPENING quote (see the premium-bleed open question below); eva's immediate shadow book (+$123.8k, META
  690C settled at intrinsic on a +11% move) is real research evidence that the analyst declined 82 of 83 eva
  ideas; four shadow books with unallocated sells / negative lots were quarantined (`tools/tip_shadow_audit.py`);
  the scorecard's option target-to-fill rows now compare the underlying (they had compared a premium with an
  underlying target). Rule reliance is not recorded, so no rule's value can be measured yet.
- **September 21 review package (0.8.30, `research/2026-09-22-s21-package.md`; review `reviews/2026-09-21-comprehensive-review.md`, reviewer regressions `tests/test_sep21_economics_review.py`):** cards price options on the execution fee basis with decoded contract metadata and state the target-price assumption (S21-01); the observation report joins run status, marks the checkpoint INCOMPLETE on any unresolved decision and exports every candidate, and `tools/tip_checkpoint_status.py` owns the five-session status (completed observe days only, one cutoff, exit codes, atomic STATUS) (S21-02); digests get one bounded repair (S21-07); scorecard v4 adds target-to-fill trails, all-in friction and same-underlying exposure (S21-03/04); quote records say which clock their age came from and fills carry decision/submission/fill-time samples apart (S21-04/05); raw-message coverage + bounded replay (`tip_outcomes --coverage`, `POST /api/tip/intake/replay/{id}`) (S21-07b); source stats label research books and blank quarantined ones (S21-08); context-cost study (`tools/tip_review_context_cost.py`: rulebook 68% + notes 28% of every review request) (S21-06). Rev 2 (0.8.32): structured checkpoint eligibility + empty-report rejection + one cutoff on every report; locked replay claim (`techniques/tip/replay_claim.py`); Team2 owns OPRA clock semantics (accepted) - the premium-stop two-observation rule keys on poll stamps (P11, owner's fix). Policy decisions P1-P11 prepared, NOT activated: target execution design `research/2026-09-21-target-execution-design.md`.
- **Five-session observation (window opens 2026-09-21): the durable owner is `research/FIVE-SESSION-CHECKPOINT.md`** + the Windows task `ZargarTipsFiveSession` (raw outputs in `C:/ProgramData/Zargar/tips-five-session`, `STATUS.json` READY/NOT-YET). Review-model evaluation safeguards rev 2: instructions compared (levels, fractions), no substituted evidence (missing = inconclusive), one suite-wide $35 ledger (`review_frozen.SuiteBudget`) - an estimate-based spending guard, not a guaranteed maximum. No paid run approved.
- **Opportunity package 2026-09-19 (0.8.25, `research/2026-09-19-opportunity-package.md`):** every actionable idea has ONE disposition (`tip_outcomes --dispositions`; 189 ideas, 34 takes, 22 filled, 7 avoidable misses - all from causes already fixed: six no-verdict analyst runs before E17 and one 10.5 s quote before `freshRetry`); a tip parked ONLY for a cold ticker is re-verified on its first real quote (`signals.cold_park_recheck_seconds`, same recovery sweep, now locked) instead of waiting up to 15 minutes; scorecard v3 adds dispositions and how closed positions ended; review cost is split by message type x useful action; a reviewed consolidation can be applied PENDING (born `needs_human`); the cheaper-model evaluation of intake reviews is PREPARED (`review_frozen.py`, capture knob `techniques.tip.review_capture_context` default off, 60 stratified cases, $35 estimate-based spending guard) - no paid run, no model change. Known gap: reviews before capture are not replayable (their request was never kept).
- **Economics review 2026-09-19, revision 2 (`research/2026-09-19-economics-review.md`; verdict `reviews/2026-09-19-economics-verdict.md`):** Tips Practice MARKED -$1,035.54 over 9 sessions and -$1,530.13 after >= $494.59 priced model cost (the primary metric; realized-after-cost -$1,540.27 is printed beside it; marks are 04:00 ET accounting-day cutoffs, not the 16:00 close). Supported: losses before operating cost and a large intake bill. NOT established: the cause of the losses - the six first-seconds exits (-$999.09) span 3 to 70 DTE and the largest, CCXI -$505.08, was 37 DTE; the corrected horizon study (38 eligible observations) shows a negative MEDIAN overnight drift for short-dated contracts with a roughly flat mean, and no demonstrated selection edge. D2 (opening exit guard) is NO-GO, D3 research only, D4 (operative rules keep the rule budget; pending proposals in a separate capped channel; rule supply stamped) is DONE, D5 is a prepared reversible manifest, the review gate stays in OBSERVE (an absent or unrestored desk component always reviews). `tools/tip_scorecard.py` is the reconciled view.
- **Premium-bleed exit on the opening bid (2026-09-18, open question):** the shared `premium_bleed` rule (premium <= -35% with the underlying within 3%) sold SMCI 41C at 09:30:24 on a fresh OPRA bid of 0.98 against a 0.98/1.13 book - -38% on the bid, -33.6% on the mid. The opening spread alone decided the exit. Not changed; record in `reviews/2026-09-16-tmr-plan-record.md` (EOD 09-18).

- **E17-01 (2026-09-17, FIXED in 0.8.11, deployed since):** the MRNA 165C 0.75 fill was a locally RECENTRED OPRA band (a stale 0.70 chart print bent the fresh 1.90/2.00 band to 0.65/0.75 and kept `source=opra`); venue bands are never recentred now and any derived estimate carries `derived:` provenance the sim refuses - audit in `reviews/2026-09-17-mrna-quote-audit.md`; the +$112.92 stays booked and is shown apart in method grading.
- **F-FILL-02 (2026-09-17, OPEN - user/reviewer decision):** simulated OPTION fills have no spread or flash-quote sanity by design (wide books are normal), so a one-lot OPRA quote 60% below the surrounding market that lived ~3 s priced a Practice fill (MRNA Sep-18 165C bought 0.75 between 1.90/2.01 quotes; sold 4 s later at 1.90, +$115). `TipFillVsQuote` flags such fills (vsMid far negative); every Practice number that includes them is labeled suspect until a rule exists. Candidate rule: refuse/flag an option fill when the top of book is 1x1 with spread > ~40% of mid or the price deviates > ~35% from the last qualified mid within 10 s. Share fills got the equivalent guards in 0.8.10 (F-HOLD-01, PLATFORM-RULES).

1. **(2026-09-23: the books with unallocated sells or negative lots are now QUARANTINED - ab/eva/common-stock armed,
   muggzone immediate + armed, tt immediate; `tools/tip_shadow_audit.py`; the scorecard's shadow census now runs
   FIFO from the book's first execution, which removed the window-cut artifact.)** The shadow armed books carry phantom SHORT share positions from the over-sell classes fixed on
   2026-09-15 (eva: TSLA −5, MU −13, AAPL −15, MSTR −36, SNOW −6, GOOGL −28, AMZN −57; ab: APLD −40,600,
   RDDT −64, GOOGL −2, AMZN −3; common-stock LULU −49; muggzone MSFT −2), with stale oversize stops still
   resting. No money, but the ARMED scorecards that judge source trust are polluted for those names.
   Nothing was placed; a journaled research reset (cancel oversize stops, reduce-only buys, re-seed the
   scorecards) is the user's decision.
2. **Under a 1% budget, option tips are a review product.** On 2026-09-15 fifteen of thirty-two enforced
   cards were gated "no quantity satisfies the $89 budget" (one-lot risk above the budget); on 2026-09-16
   (FOMC day) Tips Practice had 0 executions and four analyst skips. The feasibility annotation now tells
   the analyst before the verdict; a budget change is a user decision recorded in TRADING-RULES.
3. **Option evidence comes from CBOE's delayed chain** (delta age ≤ 900 s is a staleness bound, not
   liveness); `delta-linear-v1` can be wrong in a fast tape; the premium-at-risk (`stressRisk`) is the
   honest bound. The scenario prototype (`scenarios.py`) is research-only and reproduces the venue delta on
   its worked example; it forecasts nothing.
4. **Execution costs are diagnostics, not gates.** `execcost-v1` prices the round trip on a qualified
   quote and journals every realised fill against the decision quote (`TipFillVsQuote`); it changes no
   quantity, contract, limit or stop. Since 0.8.30 every fill also carries a fill-time quote sample labelled
   apart from the decision quote, and open positions show all-in friction (fees + spread) on the scorecard.
5. **Recap routing is OFF and unevaluated.** The classifier (`recap-read-v2`) is journaled on every
   multi-signal message; the compact candidate (`recap-candidate-v1`) has proven request-assembly parity
   with the replay, but the paid pairs need bundles WITH a captured classifier read - today's SPX-map and
   APLD bundles predate that capture and are coverage-limited cost measurements only. Suppressing
   entry-card creation for confirmed recaps is NOT built (cards are created before the appraisal).
6. **Review-gated cards do not auto-decide.** Under unattended practice a card that fails evidence sits
   pending until it expires; the counterfactual armed shadow book keeps trading full size, so the
   scorecard comparison drifts.
7. **An incident with no repair evidence stays open** until a labeled human override; the tick reports
   it, the override is the user's call.
8. **Geometry is Practice-only by construction.** Before any real-money tip the scope decision must be
   made explicitly and `docs/PRE-LIVE-PROFILE.md` re-tightened.
9. **Knowledge maintenance is propose-only**; the rulebook drifts only through analyst retros (family
   dedupe) and reviewed batches; nobody reads the proposals unless the Knowledge tab is opened. Three
   truncated `experiment:*` notes stay unproven.
10. **The MK own-book classifier is text rules + two extraction fields**, observed only (known blind
    spots in TRADING-RULES 2026-09-14); promotion to shadow needs the predefined criteria and a human verdict.
11. **Hold-study evidence is thin.** 25 paired close -> open samples by 2026-09-22 (`tools/tip_overnight_study.py`);
    direction only, no rule. An event-day session is labelled, not blended.
12. **Restarts remain the platform's biggest operational risk.** 2026-09-15 saw five restarts from three
    paths and an out-of-band stop; 2026-09-16 the watchdog killed a live engine on one timed-out probe and
    launched the checkout into a health-500 loop caused by a dropped runtime-only helper (fixed 10:50 ET).
    Rules: deploys through `/api/ops/restart-check` + the `ZargarRestart` task, never inside 09:30–10:30 /
    14:45–16:00 ET unless the app is dead; after every merge into the running checkout run the import
    check and `check-release`; after every restart verify liveness and ONE listener.
13. **Tools that mint a session need `backend/.env`** — run `tip_note_restore`, `tip_consolidation`,
    `mint_session`-based sweeps from `C:/Cursor/zargar/backend`. Research tools run from the worktree with
    `ZARGAR_DATABASE_URL` pointing at the runtime DB.
14. **Intake delivery depends on one helper process.** The liveness rule (`GET /api/tip/intake/liveness`,
    pending-streak warning, stall after 3 checks) catches a dead gateway; the ledger's gap recovery re-queues
    missed messages from cursors on reconnect (nothing lost on 2026-09-15 and 2026-09-16), but a stall
    means the desk is blind until someone relaunches `scripts/discord-intake.ps1`.

## Feasibility before the verdict and the whole exit path (PROF-01/02, 2026-09-15)

The analyst is told the approved planned-risk budget (not just the purchase allocation), must
`check_feasibility` before a take (units that fit at the declared stop; labelled research alternatives
at equal risk), and can `preview_payoff` (integer-unit ladder, every-target / first-target-then-stop /
stop-only arithmetic, fees, one-lot policy). Every TAKE is assessed server-side and the result rides on
`extraction.analyst.expression` / `.payoff` / `.execCost` / `.eventContext`;
`techniques.tip.analyst_feasibility_gate` annotate (default) | downgrade. The risk plan carries `payoff`
and `execCost`, shown on the card. Tools: `zargar.tools.tip_feasibility replay`,
`zargar.tools.tip_payoff_report`. Code: `techniques/tip/feasibility.py`, `payoff.py`, `execcost.py`.

## Analyst reasoning corrections + recap read (INTRA-01..03 / I175-01..04, 2026-09-16)

`payoff.break_even` / `premium_exit` / `expiry_value` and `payoff_preview.breakEven` + `horizon` (hold cap,
expiry date and exit assumption kept apart; intrinsic value only for a DECLARED held-to-expiry exit) +
`singleLot` (declared vs executable rungs derived from the executed unit sequence) keep the expiration
break-even apart from a sale before expiry and make one lot an exit-plan question (prompt rules of the
same names). `techniques/tip/recap.py` (`recap-read-v2`) reads a multi-signal message's shape before the
paid appraisal (journaled `TipRecapClassified`): a fresh priced actionable entry or entry cues force the
full route before any scoring; management stays full; a confirmed map/recap is compact-eligible.
`techniques.tip.recap_route` (off) can route those to the compact context defined once in
`recap.CANDIDATE` (`recap-candidate-v1`: core rules, ticker/source/core notes, the newest 12 mirrored
RECORDS within 24 h, a 2-tool budget, one header prefix) - the same builder the frozen `recap_candidate`
variant uses, so a replay evaluates the exact production request (parity proven unpaid; non-parity and
coverage gaps are declared, never filled).

## Event context + execution costs (TMR-01/02, 2026-09-16, advisory only)

`techniques/tip/events.py` labels every decision with the VERIFIED macro-event context (Tips-scoped
`techniques.tip.verified_events` with official URL + verification time; unknown coverage is never
"no event"; a replay sees only facts verified before its instant) - analyst header, record, cards,
cohort and hold-study rows. `techniques/tip/execcost.py` prices the instantaneous round trip on the
qualified quote (spread once + both sides' fees, quoted size, cost share of purchase; unknown on
stale/crossed/missing evidence) on the tools, the risk plan and the card, and journals one
`TipFillVsQuote` per realised fill. Neither gates, sizes or times anything.

## Research register + scenario prototype (TMR-03/05, 2026-09-16)

`research/EXPERIMENT-REGISTER.md` (mirror of `techniques/tip/experiments_register.py`) gives every study
one identity - hypothesis, variants, unit, episode identity, metric, costs, regime, evaluation window -
and every research report carries it. `techniques/tip/scenarios.py` (`bsm-local-v1`) is a research-only
time/volatility grid for one long option (design + worked example in `research/2026-09-16-time-vol-scenarios.md`);
it is wired to nothing. Hold-study reports follow `research/HOLD-STUDY-REPORT-TEMPLATE.md`.

## Research studies (PROF-03/05 → holdstudy-v2, observation only)

`tip_hold_snapshots` (jobs `tip_hold_snapshot` at exchange close − `hold_snapshot_before_close_minutes`
and `tip_hold_next_open` from 09:30 ET; knob `techniques.tip.hold_study_enabled`) pair overnight quote
drift (and the managed outcome where the position's own exit closed it first) against a predeclared
intraday close on qualified quotes inside declared exchange-calendar windows, admitted on the quote's own
sample time, one durable observation per position / session / leg / arm, nets including the allocated
entry fee and the exit cost, R rebased to the sampled size - `zargar.tools.tip_hold_study report`
(`requalify` repairs v1 rows). The frozen replay has `compact` (generic, PROF-05) and `recap_candidate`
(the production recap route, I175-04) variants with cache-aware usage and `coverageLimited` /
`coverage` on every pair - `zargar.tools.tip_frozen replay --variants current,recap_candidate`. Neither
changes method behaviour.

## Approval cards (readiness-v1, 2026-09-15)

A Tips card shows the analyst's OPINION and the EXECUTION READINESS as two independent statuses.
`context.readiness` (persisted by every refresh / automated refusal / manual approval attempt) lists
the actual blocking reasons by code - source not qualified for automatic trading (auto-only,
informational), planned risk over the approved budget, missing / stale / delayed quote, contract metadata
missing, risk evidence unavailable, exit plan review, an open execution-integrity incident, an
unsupported instrument, expiry - the final plan (purchase allocation limit vs the approved planned-risk
budget, risk per unit and its basis, final qty x risk, final stop, quote provenance, adjustments,
round trip now, event) and a fingerprint (final stop + admissible size + blocker set incl. incident
identity). "Refresh & revalidate" (`POST /api/proposals/{id}/revalidate`) re-fetches quotes, recomputes
geometry, sizing and the diagnostics, re-checks incidents and gates, saves the result - zero orders, the
limit only ever lowered. Approve submits exactly the displayed plan (revalidated at that instant; refused
when blocked, when the fingerprint changed, or when an incident opened meanwhile); a labeled override
names every failed check it accepts (only overridable ones: budget, plan review, incident, unsupported
instrument - never a missing / stale quote, missing evidence or expiry), needs a reason and is journaled
`ProposalOverridden` with the exposure. The claimed plan is frozen as `context.approvedPlan` and adoption
consumes it. Code: `backend/zargar/approvals/readiness.py`, `proposals.py::assess/revalidate`,
`frontend/src/pages/InboxPage.tsx::ProposalCard`; tests `tests/test_proposal_readiness.py`,
`tests/test_v085_approval_boundaries_review.py`, `tests/test_v086_final_boundaries_review.py`.

## Experiments (KFIN-09, built 2026-09-14; collection ON since 2026-09-15 00:26 ET)

`techniques.tip.entry_cohort_enabled` and `techniques.tip.frozen_capture_context` are ON by journaled
PATCH (code defaults stay off): the cohort records and samples, the analyst run stamps its context
manifest (incl. the route, the classifier read, the effective tool budget and the candidate version since
I175-04). Neither touches an order path; a pending delayed sample survives a restart through the
`tip-cohort-recovery` task. KF83-03/04: a delayed sample is the delay variant's evidence only inside
`entry_cohort_delay_tolerance_seconds` (60); a quote is executable comparison evidence only with venue
provenance (`opra`/`ibkr` for options), no delayed flag, a genuine source time, a valid uncrossed bid/ask
(and quoted size, since TMR-02) and an open option session (`cohort.qualify_quote`; stored records are
re-judged). Every cohort row carries the event label (`event_context`).

Two evidence tools, both isolated by construction (`tests/test_tip_kfin09_experiments.py`,
`tests/test_tip_frozen_compact.py`, `tests/test_tip_i175_parity.py`):

- **Frozen knowledge comparison** (`techniques/tip/frozen.py`, CLI `zargar.tools.tip_frozen`).
  `capture --signal <id>` builds an immutable case bundle from what the DB already holds (message,
  tool outputs, rule snapshot, notes, model + settings, the exact context manifest when capture was on -
  otherwise reconstructed and labeled). `replay --bundle fb-... --variants current,core_only,no_knowledge,
  compact,recap_candidate` runs the analyst prompt against the bundle only (a tool call is served from
  the bundle or refused "missing"; `save_note` captured, never written). `report` prints decision changes,
  grounding, protections, latency, tokens (incl. cache reads/creation and effective input), header size,
  the experiment identity and `coverageLimited` / `coverage` - counts only, no "better".
- **Entry-variant cohort** (`techniques/tip/cohort.py`, CLI `zargar.tools.tip_entry_cohort`). Every
  eligible open/add idea is a `tip_entry_cohort` row at its intake decision with the decision-time
  quote (age + provenance + size), the source-stated premium, gaps, the configured later sample and the
  event label; `report` simulates the declared variants (immediate, delay, premium cap) into separate
  result books under identical budget, fees and fill-at-ask assumptions, separating adequate from
  insufficient evidence, and carries the register identity. No P&L claim; promotion is a reviewed verdict.

## Rollback and where the receipts are

- Settings: `PATCH /api/settings {"techniques.tip.geometry_gate": "shadow",
  "techniques.tip.entry_pause_mode": "clock"}` (journaled; previous values recorded in
  `reviews/2026-09-13-pr91-pr93-response.md`). Research knobs: `hold_study_enabled`, `entry_cohort_enabled`,
  `frozen_capture_context`, `mk_ownbook_mode`, `recap_route` (off) — each a journaled PATCH.
- Knowledge: `reviews/2026-09-14-consolidation/manifest.md` (rollback mapping) and
  `reviews/2026-09-14-truncation-restoration/` (per-id revisions); receipts in `tip_knowledge_batches`.
- Positions: the RKT reconciliation (2026-09-15) and the MRNA bracket release (15:22 ET) are recorded in
  `reviews/2026-09-14-kfin-response.md`; the shadow-book phantom shorts await the user's reset decision.
- Incidents: `reviews/2026-09-14-kfin-response.md` (2026-09-15 outages, listener duplicates, `trading.mode`
  test) and `reviews/2026-09-16-tmr-plan-record.md` (the 10:40–10:53 ET watchdog loop).
