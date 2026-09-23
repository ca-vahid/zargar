# Tips desk - history (superseded README sections)

*Moved here from README.md on 2026-09-23 so the README stays current. Accurate as history; never the current state.*

## State of play as of 2026-09-16

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

