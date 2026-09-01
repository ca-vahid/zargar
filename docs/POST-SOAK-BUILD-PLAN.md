# Post-soak build plan — tips pipeline, platform safety, and the morning surface

Companion to `docs/POST-SOAK-PLAN.md` (the queue + evidence). This is the working
plan: phases, checkboxes, files, knobs, tests, acceptance. Scratch items off as
they land; log findings under each phase like the other build plans.

**Scope decision (user, 2026-08-31):** everything from the queue EXCEPT T13.
**EM evolution / other-technique enhancement is owned by ANOTHER TEAM** — this
plan is tips-only plus everything technique-agnostic (platform safety, ops,
morning surface, UI). Consequences for us:
- We do not touch `zargar/technique/` (EM's own code), EM prompts/rulebooks,
  or `docs/techniques/enhanced-market/*`.
- Shared engine files (`execution/planrunner.py`, `risk.py`, `orders.py`,
  scheduler) are fair game but keep diffs SMALL and per-technique-resolved
  (`rt()` / `techniques.tip.*`), and every engine-level change lands a
  PLATFORM-RULES entry — that log is how the two teams stay honest.
- Before each session: `git log --oneline -10` for the other team's merges;
  own test DB (`zargar_test_<name>` on :5433); never assume `zargar_test` is free.

Standing constraints (unchanged): live-money gates stay off
(`techniques.tip.allow_live_auto`, `technique.arm.allow_live_auto`,
`trading.mode=practice`); every order inside `RiskGate.evaluate()`; journal every
decision; new knobs in `settings_service.DEFAULTS`; every UI change gates on
`npm run mobile-audit`; no restarts while an experiment batch runs.

---

## Phase 1 — Mornings are safe (T1 + T3 + T10)

The user is in Vancouver: the open is 06:30 local. The morning surface must make
"what needs me" a one-glance answer, and the close must never silently strand a
multi-day plan.

- [x] **1.1 Roll forensics.** DONE 2026-09-01 — **no bug**. The close is
  bar-driven (`_on_bar` → `_end_session` on the 15:59 bar) with a 16:05 ET
  clock fallback in `on_heartbeat`; on 08-31 it ran at 16:00:00 ET exactly:
  45 EM plans scored+disarmed, 2 multi-day tips ROLLED (AMZN→09-01 exp 09-18,
  GOOGL→09-01 exp 09-15; event ids 10210+ prove real-time insertion). The
  "missing rolls" was observation error: the review tick fired 15:27 ET,
  pre-close. Residual risk the watchdog (1.2) covers: a restart in the
  16:00–16:06 window can miss BOTH triggers (boot-roll covers plans restored
  later, but only at boot).
- [x] **1.2 Roll watchdog.** DONE 2026-09-01 — `PlanRunner.roll_stale()` (small
  shared-engine addition; loops `_end_session` so a weekend gap rolls through)
  + `desk.roll_watchdog` at `desk.roll_watchdog_at` (09:00 ET) sweeping every
  registered runner; rolled plans alert (`roll_watchdog` stage → needsAttention).
  Test `test_roll_watchdog_rescues_stale_plan` drives the REAL TipRunner:
  a plan stuck 4 days back rolls to today, journals, idempotent second sweep.
- [x] **1.3 Soak report nightly.** DONE 2026-09-01 — `desk.soak_nightly`
  (17:30 ET) calls `soak_report.collect` in-process; persistence is the
  scheduler's own `ScheduledJobRan` journal row (result payload) — no new state.
- [x] **1.4 Morning composer.** DONE 2026-09-01 — `zargar/desk.py`
  `DeskService.morning_report` + `GET /api/desk/morning`: pending proposals
  with `failClosed` + a prose `why`, plan attention reasons, source follow-up
  flags, overnight tips + status counts, armed counts per technique, rolls +
  watchdog result, latest soak, error-content count (Phase 4 wires the sweep).
- [x] **1.5 Delivery.** DONE 2026-09-01 — `desk.morning_send` at
  `desk.morning_at` (08:25 ET): web push + Telegram short form (counts + the
  needs-you lines), `POST /api/desk/morning/send` for the manual trigger;
  Dashboard "This morning" card (`MorningCard`) with fail-closed/follow-up/
  attention rows deep-linking to Approvals/Armed. (Now-view placement deferred
  to the Phase 3 mobile pass — the Dashboard card is phone-usable meanwhile.)
- [x] **1.6 Tests.** DONE 2026-09-01 — `tests/test_desk.py`: job registration,
  fail-closed surfacing (with + without a verdict), send composes the short
  form; plus the watchdog test in `test_tip_runner.py`. 5/5 green.

Acceptance: the report fires on schedule; a fail-closed proposal CANNOT miss it;
a stale plan is rolled + reported by 09:05 with no restart.

## Phase 2 — Auto-approve is earned per source (T2)

Auto is the platform default since 2026-08-31, but the analyst itself graded eva
"0/6 verified" while auto covered her. The trust ladder (shadow → alert →
proposal → auto) already exists as words; wire the top rung to the scorecard.

- [x] **2.1 Knobs.** DONE 2026-08-31 — `techniques.tip.auto_min_graded` (5) +
  `auto_min_hit` (0.4) in DEFAULTS and the Tips technique Settings panel.
- [x] **2.2 The gate.** DONE — after the fail-closed / verdict / live checks:
  `source_trust()` counts the source's CLOSED tip positions (tag
  `source:<name>`, realizedPnl>0 = hit); below either bar the proposal stays
  pending with `context.autoGate` + an intake note. Explicit per-source
  `mode: auto` bypasses (the human said so).
- [x] **2.3 Visibility.** DONE — policy editor shows "auto earned — N graded,
  H hit" / "auto pending — N/5" / "explicit — bypasses the bar" under the mode
  select (trust rides on `source_scorecards`); a gated Approvals card carries
  an "auto: not yet earned" pill with the reason in the tooltip.
- [x] **2.4 Tests.** DONE — `test_platform_auto_graduates_per_source` (fresh
  source pends; 5 winning closes graduate); explicit-override + live-gate
  tests unchanged. 79 green across pipeline/desk/tip suites.

  NOTE (behavior change on deploy): every current source starts
  "auto pending 0/5" — takes land as pending proposals until five of that
  source's tip positions have closed. That is the trust ladder working; flip a
  source to explicit auto in Tips → Sources to bypass while it accrues.

Acceptance: a brand-new Discord source can be set to the platform default and
its first five takes all land as pending proposals with the graduation note.

## Phase 3 — Shadow books read as research (T4)

Nine books (immediate+armed pair per source, flow-scan) currently look like
accounts. DONE 2026-08-31: exempt from the daily-loss halt (`risk.py`) so the
record never stops recording.

- [ ] **3.1 Research filter.** Blotter + Journal: a "research" toggle — phone
  default hides shadow rows, desktop default dims them (`opacity` on the row,
  not removal, so the tip-hue dot pairing shadow take ↔ real purchase stays
  meaningful). Persist the choice in `localStorage` (per-viewer convenience).
  Phone rules in `mobile.css` only.
- [ ] **3.2 Silence.** Shadow-book fills never toast and never push. They still
  journal and still stream on WS (the pages that want them read them).
- [ ] **3.3 One row per source.** `ShadowBooksPanel`: pair `immediate` + `armed`
  lanes on a single row per source — verdict chip first (the scorecard's call),
  then per-lane micro-columns. Keep the two-lane numbers visible (the comparison
  IS the experiment) but stop rendering them as two unrelated accounts.
- [ ] **3.4 Kill the cash column.** Book "cash" is meaningless research
  bookkeeping (eva: −$8,001.70). Display per-tip avg R, hit rate, open tips,
  committed $. Display-level fix now; book-accounting redesign ONLY if the
  scorecard needs it later (decide then, not now).
- [ ] **3.5 Research badge.** One `ResearchBadge` chip component ("🔬 research")
  wherever a shadow book leaks into a shared surface: order rows, engine
  position rows, armed-plan rows, proposal context. Grep for `kind === "shadow"`
  renders and unify.
- [ ] **3.6 Gate.** `npm run mobile-audit` + a desktop screenshot pass of
  Blotter, Journal, Portfolios, Armed.

Acceptance: with the filter on defaults, a phone Blotter shows only real trades;
nothing shadow ever toasts; the Portfolios panel answers "which sources are
earning trust" in one row per source.

## Phase 4 — Intake never loses a tip silently (T5 + T6 + T9)

Monday's theme applied to intake: every drop must be either correct or retried.

- [ ] **4.1 Parked re-verification, proven.** Cold-quote parks (MRVL fix) and
  price-position parks must re-judge when data arrives. Locate the park re-check
  path (tip runner / scheduler), confirm it re-runs VERIFICATION (not just the
  level watch) for `ticker_resolves` parks once a real quote exists, then
  appraises. Test: park on a cold quote → warm the quote → assert re-verified +
  analyst ran. Horizon expiry cleans up never-warming tickers (APPL) — test that
  too (`SignalExpiredUnfilled`).
- [ ] **4.2 Ticker sanity.** (a) A TINY explicit alias map in
  `signals/schemas.py` validators — `{"APPL": "AAPL"}` class of typos only,
  never fuzzy matching; journal when applied. (b) At verification, an unknown
  ticker (no quote, not in universe) gets ONE Yahoo chart existence probe;
  probe fails → park with detail "ticker not found at Yahoo — likely a typo",
  and the morning report lists it under "needs you". Test both.
- [ ] **4.3 Error-recovery sweep.** Scheduler every 15 min during market hours:
  `raw_content.status='error'` rows younger than 24h → `process_content` ONCE
  more (dedupe + `seen_count` make this idempotent; mark retried in meta so it
  never loops). Counters (retried/recovered/gave-up) into the soak report →
  morning report.
- [ ] **4.4 529 telemetry.** Count transient-retry events per day (extraction +
  analyst loop); soak report shows the trend so we know whether the (5, 20)s
  backoff is enough or a queue is needed. No new behavior — measurement first.

Acceptance: kill the API for a message (fake 529) → the tip is trading anyway
within one sweep cycle; a cold-quote park verifies itself when the feed warms
with zero human touches.

## Phase 5 — The rig stops lying about time (T7), then batch 2 (T8)

- [ ] **5.1 Pinned clock.** The 3 flaky tip_runner tests (short_tip_puts,
  guarded_trigger_stays_dormant, gapped_past_trigger_revives) share one cause:
  the rig arms at WALL-CLOCK time, so mid-session runs let
  `_complete_opening_bars` consume the real open before the test feeds its
  synthetic one. Make "now" injectable for the tip plan build + armer
  (`ZARGAR_TEST_NOW` env or a conftest fixture patching the clock source —
  follow how sim seeding is injected today), pin the rig pre-open, and CI-prove
  it: run the trio at three frozen times (pre-open / mid-session / post-close).
- [ ] **5.2 F-findings triage.** KNOWLEDGE-BUILD-PLAN Phase 5's F1–F11 against
  today's code: mark which are already fixed by the 08-31 work (F9 inferred
  ticker → shadow-gate; grounding changes), implement the still-open ones that
  matter for batch validity (silent drops F1, fresh/ticker_resolves constants
  F2, premium-vs-underlying F3, post-tip leakage F4, invented replay plans F5,
  live get_quote in historical mode F10), defer the taxonomy ones with a note.
- [ ] **5.3 Batch 2.** `tip_experiment` run: sample 30–50, NEW seed, since
  2026-06-01, after 5.1 + 5.2 land. Rubric batch review; findings logged in
  KNOWLEDGE-BUILD-PLAN Phase 5 as F12+; compare drop/park/replay rates against
  batch 1 to measure the fixes.

Acceptance: the tip_runner suite is green at any hour; batch 2's review shows
the batch-1 failure modes measurably reduced (or teaches us why not).

## Phase 6 — Toward real money (T14 → T11 → T12, in that order)

Operational, calendar-bound; code only where the checklists find gaps.

- [ ] **6.1 Real-device mobile pass** (`docs/MOBILE-ACCESS.md` checklist):
  Tailscale/HTTPS/token handoff on the actual phone, Now view, exit-only
  enforcement, push arriving. The morning report (Phase 1) rides on this.
- [ ] **6.2 Alpaca-paper overnight pass:** run app-managed option + venue-stop
  share positions on Alpaca paper across ≥3 nights incl. a weekend; reconcile
  daily; chaos-suite invariants hold against a real venue's latencies.
- [ ] **6.3 First-live-tip checklist:** diff current (AMBITIOUS practice)
  settings against `docs/PRE-LIVE-PROFILE.md` and re-tighten; one MANUAL live
  approval with minimum size on a Webull-supported option; write up what the
  desk does differently before any live-auto conversation. `allow_live_auto`
  stays off through this entire plan.

Acceptance: each gate produces a dated log entry in this file; 6.3 ends with a
go/no-go note, not a flipped switch.

---

## Sequencing & effort

| Order | Phase | Sessions (est.) | Depends on |
|-------|-------|-----------------|------------|
| 1 | Phase 1 (mornings) | 1–2 | — |
| 2 | Phase 2 (earned auto) | 1 | — |
| 3 | Phase 3 (shadow UI) | 1–2 | — |
| 4 | Phase 4 (intake) | 1–2 | 1.3 for counters |
| 5 | Phase 5 (rig + batch 2) | 2 | Phase 4 (extraction stable) |
| 6 | Phase 6 (real-money gates) | calendar | Phases 1–4 |

Phases 1–3 are independent — pick by mood; Phase 4 before 5 so batch 2 measures
a stable extractor. Phase 6 runs on the calendar, not the keyboard.

## Findings log

- (add dated findings here as phases land, in the style of the other build plans)
