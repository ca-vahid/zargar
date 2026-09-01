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

- [x] **3.1 Research filter.** DONE 2026-08-31 — Blotter: a hide·dim·show seg
  (phone default hide, desktop default dim, remembered in localStorage; hover
  restores a dimmed row; the tip-hue pairing dot stays). Journal: a "🔬
  research" checkbox (default off) filtering shadow-book events by portfolioId.
- [x] **3.2 Silence.** DONE — shadow-book armed/fired/position_open toasts are
  quiet (errors still surface); the morning shadow-arm sweep no longer storms.
- [x] **3.3 One row per source.** DONE — ShadowBooksPanel groups the
  immediate/armed pair per source: Record (hits/graded — the same stats the
  earned-auto bar reads), per-lane P&L with open counts, one chart toggle and
  one delete for the pair, expandable combined positions.
- [x] **3.4 Kill the cash column.** DONE — equity/cash columns replaced by
  per-lane P&L + open counts + committed-$ tooltips; display-level only, book
  accounting untouched (redesign deferred until the scorecard needs it).
- [x] **3.5 Research badge.** DONE — `components/ResearchBadge.tsx` ("🔬
  research"), used on the panel header and Blotter position/order portfolio
  cells. (Armed-page rows deferred: shadow plans there already carry the book
  name; add the badge when that page next changes.)
- [ ] **3.6 Gate.** mobile-audit + desktop screenshots of Blotter, Journal,
  Portfolios — after deploy.

Acceptance: with the filter on defaults, a phone Blotter shows only real trades;
nothing shadow ever toasts; the Portfolios panel answers "which sources are
earning trust" in one row per source.

## Phase 4 — Intake never loses a tip silently (T5 + T6 + T9)

Monday's theme applied to intake: every drop must be either correct or retried.

- [x] **4.1 Parked re-verification.** DONE 2026-08-31 — `recovery_sweep` (a
  SignalService loop, `signals.recovery_interval_seconds` 900): a park whose
  ONLY failure is `ticker_resolves` re-verifies once a real quote exists (cold →
  the sweep nudges `ensure_symbol`; warm → full `verify_signal`, status moves
  to verified/shadow/parked/failed with a journaled `via: recovery_sweep`).
  Promotion arms the shadow plan the same day and may mint a proposal that
  NEVER self-approves from the sweep — the fail-closed and earned-auto gates
  live in intake, so promoted parks always wait for the human. Price-position
  parks stay the level watch's job, untouched. Deliberately NOT re-appraised
  (the intake appraisal stands; noted). Test: cold → nudge → warm → proposed +
  pending. Finding while testing: the SIM feed fabricates a price for any
  ensured symbol — the sweep's nudge itself warms the rig.
- [x] **4.2 Ticker sanity.** PARTIAL — the alias map shipped
  (`schemas.TICKER_ALIASES`, tiny + explicit, APPL→AAPL etc., pydantic
  gotcha: an underscored class attr becomes ModelPrivateAttr — module-level).
  The Yahoo existence probe is DEFERRED: a never-warming park now surfaces via
  the morning report (parked overnight tips) and expires on horizon; add the
  probe only if typo-parks recur.
- [x] **4.3 Error-recovery sweep.** DONE — same loop: `status='error'` content
  < 24h old re-processes ONCE (meta.recoveryRetried marked BEFORE the retry —
  never loops); counters ride the morning report's intake section.
- [x] **4.4 529 telemetry.** DONE — since-boot counters
  (`SignalService.counters` + `analyst.API_RETRIES`) surfaced in
  `GET /api/desk/morning` intake; measurement before any queue decision.

Acceptance: kill the API for a message (fake 529) → the tip is trading anyway
within one sweep cycle; a cold-quote park verifies itself when the feed warms
with zero human touches.

## Phase 5 — The rig stops lying about time (T7), then batch 2 (T8)

- [x] **5.1 Pinned clock.** DONE 2026-09-01 — `zargar/clock.py::now_ms()`
  (ZARGAR_TEST_NOW: ISO or epoch-ms; production always real time) consumed at
  ONE choke point: `build_tip_plan_for`'s as_of, which decides the plan's
  session — pinned to a fixed PAST pre-open moment in `tip_rig`, the armer's
  seed replay can never consume real wall-clock sim bars. **PROOF: the trio is
  green at all three frozen times (08:30 / 12:00 / 17:30 ET).** Fallout fixed
  along the way: the boot-roll test now pins one session back and computes
  production's real-clock roll target; `_armed_today` → any-live-plan check
  (a plan stuck on a past session is the watchdog's job, not a re-arm error);
  and two REAL bugs the un-broken duplicate guard exposed — a REJECTED order
  now frees its duplicate-window slot (`RiskGate.forget_submission` on the
  REJECTED transitions), and a failed native-mleg submit REJECTS its leg rows
  instead of leaving them SUBMITTED (they blocked the sequencing fallback's
  identical long leg). mleg-fallback test is suite-load timing-sensitive
  (25s quote pump); passes alone — noted, not chased.
- [ ] **5.2 F-findings triage.** KNOWLEDGE-BUILD-PLAN Phase 5's F1–F11 against
  today's code: mark which are already fixed by the 08-31 work (F9 inferred
  ticker → shadow-gate; grounding changes), implement the still-open ones that
  matter for batch validity (silent drops F1, fresh/ticker_resolves constants
  F2, premium-vs-underlying F3, post-tip leakage F4, invented replay plans F5,
  live get_quote in historical mode F10), defer the taxonomy ones with a note.
- [x] **5.3 Batch 2.** DONE 2026-09-01 — `--batch b2 --sample 40 --seed 11
  --since 2026-06-01` on the live app: 41 signals, all replayed, isolation
  PERFECT (0 proposals/orders/books/failed-runs/silent-drops). Rubric review
  run `38c4130201`; findings F13–F18 logged in KNOWLEDGE-BUILD-PLAN Phase 5
  with the b1 comparison: silent drops 14%→0, the `fresh` free-kill gone, no
  post-tip leakage cited, live-quote confusion gone by construction. Headline
  lesson: isolation OVER-corrected (41/41 skip — the historical header needs
  the tip's own evidence attached, F13) and the replay can arm against the
  tip's stated trigger side (F14) — the next batch's fix list.

Acceptance MET: the tip_runner suite is green at any hour; batch 2 measurably
reduced the batch-1 failure modes and taught two new ones.

## Phase 6 — Toward real money (T14 → T11 → T12, in that order)

Operational, calendar-bound; code only where the checklists find gaps.

*(PREP DONE 2026-09-01 — run-books below; the calendar gates themselves stay
manual, by design. Code prerequisites all shipped in Phases 1–5.)*

- [ ] **6.1 Real-device mobile pass** — run-book: `docs/MOBILE-ACCESS.md`
  checklist on the actual phone via https://zargar-desk.tail97d481.ts.net
  (Funnel). Verify IN ORDER: sign-in → Now view → the "This morning" card on
  the Dashboard → a push arriving (fire `POST /api/desk/morning/send` from the
  desk while holding the phone) → exit-only blocking a phone entry
  (`phone_entry_blocked`) → Blotter hides research rows by default. New since
  the checklist was written: the morning push (desk.morning_at) is the
  wake-up-to-one-glance flow this pass exists to prove.
- [ ] **6.2 Alpaca-paper overnight pass** — run-book: open one app-managed
  option position + one venue-stop share position on Alpaca paper before a
  normal close AND before a weekend (≥3 nights total); each morning check
  `position_reconcile` (09:05) reported clean, the venue GTC stop still
  standing, and the morning report's attention list empty. Chaos-suite
  invariants (test_position_chaos) are the spec; the pass is about REAL venue
  latencies — watch the exit in-flight guard's `exit_skip` log lines.
- [ ] **6.3 First-live-tip checklist** — run-book: (1) diff live settings
  against `docs/PRE-LIVE-PROFILE.md` and re-tighten (the practice values are
  the AMBITIOUS posture, never the baseline); (2) one MANUAL approval at
  minimum size on a Webull-CA-supported option from a source that has EARNED
  auto (Sources tab shows "auto earned"); (3) write the go/no-go note HERE,
  dated, before any conversation about `allow_live_auto`. Both live-auto keys
  stay off through this entire plan.

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
