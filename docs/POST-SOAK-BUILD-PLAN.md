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

- [ ] **1.1 Roll forensics.** Find out why 2026-08-31's close produced zero
  `TechniquePlanRolled` events with 52 plans armed. Read `_roll_session` callers:
  is the roll bar-driven (next bar after close — none until tomorrow's pre-market?),
  scheduler-driven, or boot-only? Decide + document the intended trigger in
  PLATFORM-RULES. Fix if broken; a roll at close must not depend on a restart.
- [ ] **1.2 Roll watchdog.** Engine scheduler job 09:00 ET: any armed/paused plan
  whose `planFor < today's session` and whose horizon still has sessions left →
  roll it now (`_roll_session`), badge `needsAttention`, journal
  (`TechniquePlanRolled` with `via: watchdog`), and count it for the morning
  report. Test: freeze a plan at Friday's planFor, run the job, assert rolled +
  badged without a restart.
- [ ] **1.3 Soak report nightly.** Schedule `tools/soak_report.py` after the
  close (17:30 ET), persist the JSON (settings blob or a small table), keep the
  last 14. It becomes a data source for 1.4, not a separate surface.
- [ ] **1.4 Morning composer.** `GET /api/desk/morning` assembling, from existing
  sources (no new state): pending proposals — EVERY fail-closed one with the
  analyst failure reason (`intake` note text) — plans flagged by follow-ups,
  `needsAttention` anything, overnight tips + their intake outcomes
  (verified/parked/shadow/replayed/failed + why), today's armed counts by
  technique, rolls (incl. watchdog rescues), yesterday's soak deltas, error-sweep
  counters (Phase 4). CamelCase wire, deep-linkable ids.
- [ ] **1.5 Delivery.** Scheduler 08:25 ET → `push.py` (web push) + Telegram: a
  SHORT text (counts + the "needs you" lines) linking to the page. Dashboard gets
  a "This morning" card rendering the same endpooint. Phone: the card is the top
  of Now view — check with mobile-audit.
- [ ] **1.6 Tests.** Composer unit tests on canned state (one fail-closed
  proposal, one flagged plan, one overnight parked tip) asserting every item
  surfaces; scheduler wiring test (job registered at the right times).

Acceptance: the report fires on schedule; a fail-closed proposal CANNOT miss it;
a stale plan is rolled + reported by 09:05 with no restart.

## Phase 2 — Auto-approve is earned per source (T2)

Auto is the platform default since 2026-08-31, but the analyst itself graded eva
"0/6 verified" while auto covered her. The trust ladder (shadow → alert →
proposal → auto) already exists as words; wire the top rung to the scorecard.

- [ ] **2.1 Knobs.** `techniques.tip.auto_min_graded` (default 5) and
  `techniques.tip.auto_min_hit` (default 0.4 — fraction of graded ARMED-book
  tips that hit; the ARMED book is the judged book, per the standing rule).
  Both in DEFAULTS, both surfaced in the Tips technique settings panel.
- [ ] **2.2 The gate.** In the self-approve branch (`signals/service.py`,
  beside the fail-closed gate): resolve the source's ARMED-book scorecard;
  below either bar → degrade auto → proposal, intake note "auto not yet earned:
  N/5 graded (hit 0.33)" + journal. An explicit per-source `mode: auto` override
  in `techniques.tip.sources` BYPASSES the bar (the human said so) — the platform
  default `auto` is what graduates.
- [ ] **2.3 Visibility.** Per-source policy editor row shows graduation state:
  "auto (earned — 7 graded, 0.57)" vs "auto pending (2/5 graded)". Approvals
  card for a degraded proposal carries the same line.
- [ ] **2.4 Tests.** Fresh source + take → pending with note; graduated source
  (seed scorecard rows) → self-approved; explicit override → self-approved
  regardless; live book still additionally needs `allow_live_auto` (existing
  test extended).

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
