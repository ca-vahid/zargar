# Tips desk — state of play, what changed, known gaps

*Start here. Dated; the newest entry wins over any older doc in this folder. Update this
file whenever a rollout, an activation or a review changes what is true. Last full refresh:
2026-09-16 13:00 ET (after the I175 / TMR builds; live 0.7.96 build `4c84697` since 10:52 ET).*

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
| `reviews/` | external review rounds, responses, deploy and incident records | dated records; `2026-09-14-kfin-response.md` (0.7.83–0.7.87, HOLD142, R147, the 2026-09-15 incidents) and `2026-09-16-tmr-plan-record.md` (TMR, INTRA, I175, the 2026-09-16 incident) are the current ledgers |

## State of play (2026-09-16)

- **Live:** 0.7.96 build `4c84697` (since 10:52 ET, launched by the watchdog — see incident below); the
  running checkout carries 0.7.97 with the I175 work merged and NOT deployed (next coordinated deployment
  after the close). Practice only: `trading.mode=practice`, every `allow_live_auto` false. The Tips
  Practice book (`techniques.tip.default_portfolio`) is the only book that trades tips; the shadow books
  (immediate / armed) are research.
- **Entry controls, ACTIVE by journaled settings since 2026-09-14:** `techniques.tip.geometry_gate=enforce`
  and `techniques.tip.entry_pause_mode=integrity`. Code defaults remain `shadow` / `clock`. Rollback is one
  journaled PATCH back; it never clears an incident row and never touches a position's stop.
- **Geometry (enforce):** stop finalized and size derived from it against `risk_pct` 1% of equity
  (`risk_budget_per_tip` 0 = percent budget) BEFORE the order; recomputed at submission and at every
  revalidation; evidence missing → review-gated card, never auto. Shares sized at the executable limit;
  options need delta ≤ 900 s old, a fresh non-delayed underlying reference and an explicit multiplier.
  Post-fill: tighten immediately, widen only trim-first with a durable attempt.
- **Approval cards (readiness-v1, 0.7.85–0.7.87):** the analyst's OPINION and the EXECUTION READINESS are
  two statuses; "Refresh & revalidate" is zero orders; Approve submits exactly the displayed plan bound
  by a fingerprint (final stop, admissible size, blocker set incl. incident identity); overrides are
  labeled, reasoned and journaled. Since 2026-09-16 the card also shows the **round trip now** (TMR-02)
  and the **event** label (TMR-01); neither is in the fingerprint.
- **Integrity pause:** a persisted `TipExecutionIncident` pauses every automated tip entry, never exits;
  release needs evidence bound to the incident or a labeled human override. A valid fast loss is a
  `TipFastStopDiagnostic`. No incident has been open since 2026-09-14 18:22 ET.
- **One exit authority (PR #145, live):** when the manager adopts a filled share proposal it cancels the
  entry order's resting bracket children; the venue GTC stop follows the held quantity after every trim
  and is re-registered after a restart (PR #138). Both fixes came from real over-sells on 2026-09-15
  (RKT −59, MRNA 14 resting against 7 held).
- **Analyst (ANALYST.md §10):** the approved planned-risk budget comes first (`check_feasibility` before a
  take; `preview_payoff` for the integer-unit ladder, fees, one-lot policy, the EXPIRATION break-even
  beside before-expiry scenarios, the horizon with the hold cap kept apart from the expiry); one lot is
  an exit-plan question, never a rejection by itself; `analyst_feasibility_gate=annotate`.
- **Research, all observation-only:** entry-timing cohort ON (since 2026-09-15); frozen capture ON
  (variants current / core_only / no_knowledge / compact / recap_candidate); hold study `holdstudy-v2`
  (calendar-relative jobs: pre-close at exchange close − 10 min, next-open from 09:30 searching the
  09:30–09:45 window; admission on the quote's own sample time; one observation per position / session /
  leg / arm; first protocol-correct capture 2026-09-16 15:50 ET); MK own-book `observe`. Every report
  carries its register identity. Compact context is NOT adopted; `techniques.tip.recap_route=off`
  (classify + journal only).
- **Event awareness (TMR-01):** the desk carries its own verified events (`techniques.tip.verified_events`,
  default = FOMC 2026-09-16 14:00 / 14:30 ET from the Federal Reserve calendar, verified 2026-09-15
  23:35 ET, coverage through 2026-09-18); the shared manual calendar `research.macro_events` is EMPTY and
  no desk enforces event days. A date beyond coverage reads UNKNOWN, never "no event".
- **Knowledge:** propose-only maintenance (`knowledge_apply_enabled=false`); the reviewed consolidation
  batches were applied 2026-09-14; model-written rules are proposals (`needs_human`).
- **Monitoring:** the desk's Claude session runs a pre-open tick, 30-minute session ticks (:03/:33) and a
  16:06 ET wrap-up, plus one-shot checkpoints for event days. Session-only crons — a session restart
  drops them and they must be re-armed. After EVERY app restart the tick checks intake liveness and
  that exactly ONE Discord listener runs.

## What changed on 2026-09-15/16 (why older docs read differently)

- **E17 F1-R2 / F2-R2 (2026-09-17 late):** an OPTIONAL call cut at the reserve boundary records unknown/partial usage and the loop then requests the final answer with tools off inside the original deadline (a cut FINAL call stays a typed `timeout`); `parse_single_object` and `_parse_result_json` strip every fence marker and scan the complete reply (a schema-valid object after a closing fence = `ambiguity:`); provider-retry backoff awaits `analyst._backoff_sleep` (tests replace the seam, never `asyncio.sleep`). Tests: reviewer's `tests/test_e17_reserve_fence_review.py` (4) + `tests/test_tip_e17_r2.py` (4).
- **E17 round 3 (2026-09-17 late):** the two reply parsers REFUSE (`ambiguity: scan limit reached ...`) when their 20-object scan ends with JSON content unexamined - never a certified unique answer over unread content; digest usage and every rule-audit attempt (success/error/cancelled) carry the model; the frozen replay harness has an explicit `--cache off|on` switch and an ENFORCED `--budget-usd` ceiling (`frozen.ReplayBudget`: estimate checked before each attempt, provider usage charged after, unknown-billed attempts at estimate; a paid replay without a cap is refused) with per-attempt accounting and the cacheable prefix measured apart from the uncached header (~5.3k vs ~20.4k tokens on the SBLK bundle; the day's appraisals averaged ~46.5k input per CALL, 178k was per run). Production caching stays OFF; the paid pilot waits for the go. Tests: reviewer's `tests/test_e17_scan_limit_review.py` (3) + `tests/test_tip_e17_r3.py` (5).

- **E17-F1..F3 (Codex follow-up, 2026-09-17 late):** F1 - `run_agent_loop` re-reads the monotonic clock after every provider reply, before every retry attempt and before every tool; optional (tool-capable) calls are bounded to `remaining - reserve` and abandoned for the final call when that budget is gone; a reply landing inside the reserve has its tool requests stubbed. F2 - `parse_single_object` (analyst + review) and `_parse_result_json` (intake) accept exactly ONE schema-valid object with harmless prose / fences / unrelated JSON; a second schema-valid object raises `ambiguity:` (bounded same-transcript clarification for appraisals, typed failure for intake's second attempt) - never first-object-wins. F3 - `tools/tip_llm_cost.py` prices `usage.model` (the model that consumed the tokens), keeps `extractionModel` apart on intake records, uses `opinion.model` only as a qualified fallback on appraise/retro, normalises legacy list-shaped usage. Tests: reviewer's `tests/test_e17_followup_review.py` (3, verbatim) + `tests/test_tip_e17_followup.py` (5).

- **E17-03 operating cost (2026-09-17 evening, v0.8.11):** `IntakeRun.model` (set by the intake service from the extractor) rides every persisted intake record; `usage.model` and `usage.promptCache` are stamped on every loop run. `python -m zargar.tools.tip_llm_cost --since <date> [--until] [--json]` reads `tip_analyst_runs.opinion.usage` (+ the nightly `TechniqueHookStats.llm` stage rollups) and prices per day x kind x model ONLY from `llm.rates` (`{model: {in, out, cacheRead, cacheWrite}}` in $/Mtok; empty = UNPRICED - no bill is inferred); `unknownCalls` / `partialRuns` / `runsWithoutUsage` mark a lower bound. `techniques.tip.prompt_cache` (default False) marks the stable prefix (system + schema + tool definitions) `cache_control: ephemeral`; the per-run header (quotes, positions, evidence) stays outside the cache. Reviewer's rule: validate actual cache hits, billable cost and latency on identical prefixes before claiming savings; an enable is the user's call. Tests: `tests/test_tip_llm_cost_e17.py` (4).

- **E17-02 deadline discipline (2026-09-17 evening, v0.8.11):** `analyst.run_agent_loop` runs under a monotonic end-to-end deadline (`TIMEOUT_S` 120 s) with a FINAL-ANSWER RESERVE (`techniques.tip.analyst_final_reserve_s`, 20 s, clamped to half the budget): inside the reserve tools are off (`tool_choice none`, requests stubbed - no duplicate side effects) and the model is told to answer; each provider call is bounded by the remaining budget. A run without a final answer persists `opinion.failure = {kind: timeout|deadline|cancelled|validation|error, stage, detail, elapsedS, remainingS, reserveS}` - never an empty error - and `usage.partial/unknownCalls` count a call that was in flight. The same-transcript repair obeys the same deadline with tools off. Intake `_parse_result_json` takes the FIRST complete object (`raw_decode`) and types validation errors. Fixtures: today's AMZN (deadline after 4 calls + a cancelled repair, empty error), TQQQ (cancelled 3rd call after a saved note), TSLA (trailing characters). Tests: `tests/test_tip_deadline_e17.py` (6).

- **Knowledge tab pagination (2026-09-16 evening, v0.8.06):** `GET /api/tip/notes/search` takes `category` (all | rule | ticker | source | general | flagged | daily | experiment | other) and filters on the server BEFORE paging; `total` is the filtered total and `counts` are global per-category counts over the history/search filter. The tab shows "N match · M loaded" apart, load-more names the next page size, and the category buttons / Needs-you banner read the global counts - older rules and flagged notes beyond the first 200 rows were previously unreachable and uncounted. Analyst supply limits unchanged (`tests/test_tip_knowledge_pagination.py`).

| Older statement | Now |
|---|---|
| "hold study samples at 15:50 / 09:36 fixed" (PROF-03 v1) | `holdstudy-v2`: exchange-calendar windows, jobs relative to the close and from 09:30, admission on the actual sample time, durable observation identity, fees both sides, R rebased to the sampled size, carry reported as quote drift APART from the managed outcome; the three 2026-09-15 v1 rows are `outside_window` / insufficient |
| "the first paired frozen report printed None token values" | corrected from the persisted report: 68,917 vs 37,235 input tokens, 2 vs 3 calls, coverage-LIMITED (missing tool calls, uncapturable image); mixed reading, compact not adopted |
| "a one-lot option is an unmanageable binary" (analyst rationales 09-16) | one lot is an exit-plan question (`singleLot`, INTRA-02/I175-02); skip only when the thesis depends on scaling or one unit does not fit the budget |
| "break-even 352.19 sits above the ceiling, so the trade only pays on a break" | strike + premium is the EXPIRATION break-even; a sale before expiry pays when the executable bid exceeds entry + costs (INTRA-01, I175-03) |
| "the venue GTC stop protects the remaining shares" | it did not follow trims (RKT) and coexisted with bracket children (MRNA) until PR #138 / #145 |
| "a watchdog restart is an app restart" | it restores the ENGINE only; helper windows (Discord gateway, EM ingestion) die and must be relaunched; a second start can leave two listeners (PLATFORM-RULES 2026-09-15/16) |
| "merged, not deployed" is safe | the watchdog launches the checkout AS IT STANDS — a converged checkout must be launch-ready at every instant (import + check-release after every merge) |

## Known gaps, risks and what could be wrong (read before trusting a number)
- **Five-session observation (window opens 2026-09-21): the durable owner is `research/FIVE-SESSION-CHECKPOINT.md`** + the Windows task `ZargarTipsFiveSession` (raw outputs in `C:/ProgramData/Zargar/tips-five-session`, `STATUS.json` READY/NOT-YET). Review-model evaluation safeguards rev 2: instructions compared (levels, fractions), no substituted evidence (missing = inconclusive), one suite-wide $35 ledger (`review_frozen.SuiteBudget`). No paid run approved.
- **Opportunity package 2026-09-19 (0.8.25, `research/2026-09-19-opportunity-package.md`):** every actionable idea has ONE disposition (`tip_outcomes --dispositions`; 189 ideas, 34 takes, 22 filled, 7 avoidable misses - all from causes already fixed: six no-verdict analyst runs before E17 and one 10.5 s quote before `freshRetry`); a tip parked ONLY for a cold ticker is re-verified on its first real quote (`signals.cold_park_recheck_seconds`, same recovery sweep, now locked) instead of waiting up to 15 minutes; scorecard v3 adds dispositions and how closed positions ended; review cost is split by message type x useful action; a reviewed consolidation can be applied PENDING (born `needs_human`); the cheaper-model evaluation of intake reviews is PREPARED (`review_frozen.py`, capture knob `techniques.tip.review_capture_context` default off, 60 stratified cases, $35 ceiling) - no paid run, no model change. Known gap: reviews before capture are not replayable (their request was never kept).
- **Economics review 2026-09-19, revision 2 (`research/2026-09-19-economics-review.md`; verdict `reviews/2026-09-19-economics-verdict.md`):** Tips Practice MARKED -$1,035.54 over 9 sessions and -$1,530.13 after >= $494.59 priced model cost (the primary metric; realized-after-cost -$1,540.27 is printed beside it; marks are 04:00 ET accounting-day cutoffs, not the 16:00 close). Supported: losses before operating cost and a large intake bill. NOT established: the cause of the losses - the six first-seconds exits (-$999.09) span 3 to 70 DTE and the largest, CCXI -$505.08, was 37 DTE; the corrected horizon study (38 eligible observations) shows a negative MEDIAN overnight drift for short-dated contracts with a roughly flat mean, and no demonstrated selection edge. D2 (opening exit guard) is NO-GO, D3 research only, D4 (operative rules keep the rule budget; pending proposals in a separate capped channel; rule supply stamped) is DONE, D5 is a prepared reversible manifest, the review gate stays in OBSERVE (an absent or unrestored desk component always reviews). `tools/tip_scorecard.py` is the reconciled view.
- **Premium-bleed exit on the opening bid (2026-09-18, open question):** the shared `premium_bleed` rule (premium <= -35% with the underlying within 3%) sold SMCI 41C at 09:30:24 on a fresh OPRA bid of 0.98 against a 0.98/1.13 book - -38% on the bid, -33.6% on the mid. The opening spread alone decided the exit. Not changed; record in `reviews/2026-09-16-tmr-plan-record.md` (EOD 09-18).

- **E17-01 (2026-09-17, FIXED in 0.8.11, not yet deployed):** the MRNA 165C 0.75 fill was a locally RECENTRED OPRA band (a stale 0.70 chart print bent the fresh 1.90/2.00 band to 0.65/0.75 and kept `source=opra`); venue bands are never recentred now and any derived estimate carries `derived:` provenance the sim refuses - audit in `reviews/2026-09-17-mrna-quote-audit.md`; the +$112.92 stays booked and is shown apart in method grading.
- **F-FILL-02 (2026-09-17, OPEN - user/reviewer decision):** simulated OPTION fills have no spread or flash-quote sanity by design (wide books are normal), so a one-lot OPRA quote 60% below the surrounding market that lived ~3 s priced a Practice fill (MRNA Sep-18 165C bought 0.75 between 1.90/2.01 quotes; sold 4 s later at 1.90, +$115). `TipFillVsQuote` flags such fills (vsMid far negative); every Practice number that includes them is labeled suspect until a rule exists. Candidate rule: refuse/flag an option fill when the top of book is 1x1 with spread > ~40% of mid or the price deviates > ~35% from the last qualified mid within 10 s. Share fills got the equivalent guards in 0.8.10 (F-HOLD-01, PLATFORM-RULES).

1. **The shadow armed books carry phantom SHORT share positions** from the over-sell classes fixed on
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
   quantity, contract, limit or stop. The first fill records arrive with the next Tips Practice fill.
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
11. **Hold-study evidence starts 2026-09-16.** The first valid paired report is due 2026-09-17 after the
    09:30–09:45 window (template in `research/`); an event-day session is labelled, not blended.
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
