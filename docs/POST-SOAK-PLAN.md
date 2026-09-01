# Post-soak plan — after the first live-market Monday (2026-08-31)

> **Scope decision (user, 2026-08-31):** everything below is being built EXCEPT
> T13 — **EM evolution and other-technique enhancement belong to another team**;
> this desk works tips + technique-agnostic platform/ops/UI only. The working
> plan (phases, checkboxes, tests, acceptance) is **`docs/POST-SOAK-BUILD-PLAN.md`**.

The first full soak (practice money, auto-approve on) produced 12 shipped fixes in
one day. The pattern behind almost every one: **the happy paths were right, the
failure paths defaulted open** (a crashed analyst approved a trade; a cold quote
read as a penny stock; a dead duplicate-guard key matched nothing). This plan turns
the day's findings into the next work queue.

Evidence sources: PLATFORM-RULES.md findings (2026-08-31 entries), the review-loop
tick reports, `docs/techniques/tip/KNOWLEDGE-BUILD-PLAN.md` Phase 5 (F1–F11),
`docs/NEXT-GAPS-PLAN.md` (operational gates, unchanged), live DB state at the close
(9 shadow books, 44 signals today, 52 armed plans).

## The queue

| # | Task | Why (today's evidence) | Effort | Priority |
|---|------|------------------------|--------|----------|
| T1 | Morning desk report (08:30 ET push + page) | Fail-closed proposals now *accumulate by design*; the user is in Vancouver (open = 06:30 PT) and needs one glance, not five tabs | M | **P0** |
| T2 | Per-source auto trust gate | Default `mode=auto` applies to sources the analyst itself calls "0/6 verified"; auto should be EARNED per source (the trust ladder exists — wire it) | M | **P0** |
| T3 | Multi-day roll watchdog | No `TechniquePlanRolled` events were seen after today's close; a stay-armed tip plan that fails to roll dies silently | S | **P0** |
| T4 | Shadow-book UI de-noise (cluster) | User: "a lot of extra noise… so we know they are not real"; eva's book shows −$8,001 *cash*, shadow fills mix into the Blotter | M–L | **P0** |
| T5 | Parked-tip re-verification check | Cold quotes now PARK tips (MRVL fix) — but nothing proves the park re-judges when the feed warms; APPL (typo) parks forever until horizon | S–M | P1 |
| T6 | Ticker sanity at extraction | "APPL" parked all day; a 3-line alias map + a Yahoo existence probe would have fixed or killed it in seconds | S | P1 |
| T7 | Pinned-clock test rig | The 3 flaky tip_runner tests share one diagnosed cause: the rig arms at wall-clock mid-session so `_complete_opening_bars` consumes the open | M | P1 |
| T8 | Knowledge experiment batch 2 | F1–F11 fixes from batch 1 are specified but unverified; today's grounding/ticker changes also touch extraction behavior | M | P1 |
| T9 | Intake error-recovery sweep + 529 telemetry | Two tips died to 529s before the retries shipped; content rows stuck in `status=error` are never re-tried | S | P1 |
| T10 | Soak report, scheduled + surfaced | `tools/soak_report.py` exists but runs by hand; it belongs in T1's morning report | S | P2 |
| T11 | Alpaca-paper overnight pass | NEXT-GAPS operational gate, unchanged — required before real-money overnight holds | M | P2 |
| T12 | First-live-tip checklist | PRE-LIVE-PROFILE re-tighten + one manual live approval before ANY live auto discussion | S | P2 |
| T13 | EM evolution pilot (T-6 continuation) | **→ OTHER TEAM** (user decision 2026-08-31); EVOLUTION-PLAN.md — not in our build plan | L | — |
| T14 | Real-device mobile pass | MOBILE-ACCESS checklist; the phone is how Vancouver mornings will actually be handled | S | P2 |

## P0 details

### T1 — Morning desk report
One artifact per market morning, delivered before the user wakes up (push +
Telegram + a `/api/desk/morning` page linked from the Dashboard):
- **Needs you:** pending proposals (incl. every fail-closed one, with the analyst
  failure reason), plans flagged by follow-ups ("close SPY" style), needsAttention.
- **Overnight:** tips that arrived after close and what intake did with them.
- **Today:** armed plans by technique (52 today), multi-day plans that rolled
  (or FAILED to roll — see T3), soak-report deltas (T10).
Build: engine scheduler job at 08:25 ET → compose from existing endpoints
(`armed/summary`, proposals, `tip_analyst_runs`, events) → `push.py` + Telegram;
keep the page server-rendered-simple (it is a report, not an app).
Accept: the report fires on a schedule, links deep-link (`/inbox/analyst/<id>`),
and a fail-closed proposal ALWAYS appears in it.

### T2 — Per-source auto trust gate
`techniques.tip.mode=auto` is the platform default since 2026-08-31. Add the
earned-auto rung the trust ladder was designed for:
- New knobs: `techniques.tip.auto_min_graded` (default 5) and
  `techniques.tip.auto_min_score` (scorecard trust threshold; judged on the
  ARMED book, which is already the rule).
- In the self-approve branch (`signals/service.py`): a source below the bar
  degrades auto → proposal, with an intake note saying which bar it missed.
- Per-source override stays absolute (an explicit `mode: auto` in the policy
  editor bypasses the bar — the human said so).
Accept: a fresh source's "take" lands as a pending proposal with the note; a
graduated source self-approves; test both + the override.

### T3 — Multi-day roll watchdog
- Verify tomorrow morning whether today's stay-armed tip plans rolled (boot-roll
  covers restarts, but tonight's close produced no `TechniquePlanRolled` events
  by 16:27 ET — find out why: scheduler timing vs. bar-driven roll).
- Add a 09:00 ET check: any armed plan with `planFor < today` that should have
  rolled → roll it now + `needsAttention` badge + morning-report line.
Accept: a plan armed Friday shows Monday's planFor by 09:05 without a restart.

### T4 — Shadow-book UI de-noise
The 9 research books (an immediate+armed pair per source + flow-scan) must read
as *research* everywhere, at a glance:
- **a. Blotter + Journal research filter** — a "research" toggle (default: hidden
  on phones, dimmed on desktop); the tip-hue dot linking shadow take ↔ real
  purchase stays. `mobile.css` for phone rules, per convention.
- **b. Silence** — shadow fills never toast, never push. (They still journal.)
- **c. One row per source** — ShadowBooksPanel pairs `immediate` + `armed` on a
  single row (they are two lanes of one question), scorecard verdict chip first.
- **d. Kill the cash column** — book *cash* is meaningless research bookkeeping
  (eva: −$8,001.70). Show per-tip R, hit rate, open-tip count, committed $.
  Decide: monthly book reset vs. cash-less accounting (recommend: display-level
  fix now, accounting redesign only if the scorecard needs it).
- **e. `ResearchBadge` component** — one reusable chip ("🔬 research") wherever a
  shadow book leaks into a shared surface (order rows, position rows, armed rows).
Order: a+b first (the actual noise), then c/d/e. Gate: `npm run mobile-audit`.
DONE already (2026-08-31): shadow books are exempt from the daily-loss halt
(`risk.py`, `test_shadow_books_exempt_from_daily_loss_halt`) — the record never
stops recording; every other RiskGate check still applies to them.

## P1 notes
- **T5:** the park re-check path exists for price-position parks; prove (test) it
  also re-runs verification for `ticker_resolves` parks when a quote warms, and
  that horizon expiry cleans up never-warming tickers (APPL).
- **T6:** alias map in `signals/schemas.py` validators ({APPL→AAPL, GOOG→GOOGL
  only if stated...} keep TINY and explicit); unknown ticker → one Yahoo chart
  probe at verification; still-unknown → park (unchanged).
- **T7:** freeze the rig clock (inject `now` into `arm_signal`/plan building or
  set `ZARGAR_TEST_NOW`); assert the trio passes at ANY wall-clock hour by
  running the suite with three frozen times (pre-open, mid-session, post-close).
- **T8:** rerun `tip_experiment` (sample 30–50, new seed) after F1–F11 +
  today's extraction changes; findings go to KNOWLEDGE-BUILD-PLAN Phase 5.
- **T9:** scheduler sweep: `raw_content.status='error'` rows < 24h old →
  re-`process_content` once; morning report counts retries/failures (T1).

## Standing constraints (unchanged)
Live-money gates stay off (`techniques.tip.allow_live_auto`,
`technique.arm.allow_live_auto`, `trading.mode=practice`). Practice risk values
are the AMBITIOUS posture — PRE-LIVE-PROFILE re-tightens before real money.
Never restart the app mid-experiment-batch; every UI change gates on
`mobile-audit`; every order path stays inside `RiskGate.evaluate()`.
