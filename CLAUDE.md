# Zargar — agent notes

Personal trading app: Python asyncio engine + FastAPI (port 8420),
React/Vite SPA, Postgres in Docker (the only dockerized piece — do not
dockerize the app). Single user. Venues: SnapTrade (Wealthsimple + Webull CA,
live today) and IBKR (native, once the account activates). Read
`docs/ARCHITECTURE.md` before non-trivial changes; `docs/ROADMAP.md` holds
the plan.

## Commands

```bash
docker compose up -d                                   # Postgres (required for tests & runtime)
cd backend && .venv/bin/python -m pytest               # backend tests (real Postgres, no mocks-only DB)
cd backend && .venv/bin/python -m zargar.main          # run engine+API (+UI if ZARGAR_FRONTEND_DIST set)
cd frontend && npm run build                           # typecheck + production build (the frontend gate)
cd frontend && npm run dev                             # hot-reload UI on :5173, proxies :8420
./scripts/start.sh | scripts\start.ps1                 # one-process app for the user
cd backend && .venv/bin/python -m zargar.tools.ibkr_check   # read-only IBKR connectivity test
cd backend && .venv/bin/python -m zargar.tools.snaptrade_check          # SnapTrade status/accounts
cd backend && .venv/bin/python -m zargar.tools.snaptrade_check --upgrade # re-auth a connection to trade
cd backend && .venv/bin/python -m zargar.tools.snaptrade_options_check   # read-only: which accounts can trade options
cd backend && .venv/bin/python -m pytest tests/test_technique_*.py       # technique pipeline (no LLM calls)
cd backend && .venv/bin/python -m pytest tests/test_signals_tip.py tests/test_tip_runner.py  # Tip technique (no LLM)
cd backend && .venv/bin/python -m pytest tests/test_flow_scan.py tests/test_flow_api.py      # Flow technique (no chain fetches)
cd backend && .venv/bin/python -m pytest tests/test_position_*.py tests/test_platform_*.py  # platform + durable positions (chaos suite)
cd backend && .venv/bin/python -m pytest tests/test_options_*.py tests/test_snaptrade_options.py  # options (stubbed CBOE/SnapTrade)
cd backend && .venv/bin/python -m zargar.tools.technique_review list --unreviewed   # review loop CLI (dump/score/review/diff/replay)
cd backend && .venv/bin/python -m zargar.tools.technique_review sweep --start 2026-07-01 --end 2026-08-20   # walk-forward sweep (deterministic)
```

Options trading: research + build plan + status in `docs/OPTIONS-PLAN.md`.
Code: `backend/zargar/options/` (occ symbology, chain providers, OptionsService),
`api/routes_options.py`, UI `frontend/src/pages/OptionsPage.tsx` +
`components/OptionChain.tsx` / `OptionTicket.tsx`. Internal option symbol =
**unpadded OCC** (`F260828C00014500`); `occ.to_snaptrade()` pads at the venue.

Technique pipeline (EnhancedMarket method): spec in `docs/techniques/enhanced-market/METHOD.md`,
build plan + lessons in `docs/techniques/enhanced-market/PIPELINE-PLAN.md`, code in
`backend/zargar/technique/`, UI in `frontend/src/pages/TechniquePage.tsx`.
Review loop (trace, provenance, outcomes, reviews, replay, bundle):
`docs/techniques/enhanced-market/REVIEW-PLAN.md`; the `/technique-review` skill
(`.claude/skills/technique-review/`) audits one run end-to-end and plans the fix.
Session plans + walk-forward + live arming: `docs/techniques/enhanced-market/WALKFORWARD-PLAN.md`
(`technique/plans.py`, `walkforward.py`, `arming.py`; UI Validation tab).
**Multi-technique platform (BUILT through phase 5, 2026-08-27):** `docs/TECHNIQUE-PLATFORM-PLAN.md`;
**start any new technique at `docs/BUILDING-A-TECHNIQUE.md`**. The registry
(`zargar/techniques/base.py`, `GET /api/techniques`) lists THREE techniques: `enhanced_market`
("EM Options"), `tip` ("Tips") and `flow` ("Flow") — the nav renders it; never hard-code a
technique name into the UI. Rules for new code: pure bar analysis (levels, touches, distance %,
volume, candles, structure, the `TriggerTracker` state machine, `simulate_plan`) lives in
`zargar/marketstructure/` — parameterised by a `MarketRules` value, never by reading a technique's
rulebook; money handling (arm/fire/enter/manage/exit/alerts, durable positions) belongs to
`zargar/execution/`; a technique owns only its plan construction, prompts/schemas, grading,
policies (expression, exits, critic) and its own `docs/techniques/<id>/TRADING-RULES.md`. Settings:
runtime keys resolve `techniques.<id>.<key>` → `execution.<key>` (read via `PlanRunner.rt()`);
method-specific knobs are plain `techniques.<id>.*` keys in `settings_service.DEFAULTS` (EM's
legacy `technique.*` prefix is grandfathered — don't copy it).
**Tip technique (BUILT 2026-08-27, incl. options expression):** `docs/techniques/tip/PLAN.md` +
`BUILD-PLAN.md`. Never user-token Discord automation (self-bots — ToS ban risk) and never
alert-room auto-execution; reading the OS notifications Discord delivered to the user IS allowed
(`zargar/tools/discord_watch.py`, POC 2026-08-28) — boundary table + intake phases in
`docs/techniques/tip/INTAKE-PLAN.md`. The **Tips Analyst** (`techniques/tip/analyst.py` + `lifecycle.py`; charter =
`docs/techniques/tip/ANALYST.md`) is an INDEPENDENT trader persona — EM's method book never
applies to it ("our book" in its tools = the desk's own positions, not the EM PDF). It
appraises each tradable tip onto `extraction.analyst` **with its own exit plan** (scale-out
targets/fractions, stop or premium-stop guard, hold cap); every run persists a **TipAnalystRun**
(kinds appraise/intake/retro, full play-by-play, streamed live on the `tip_analyst` topic — UI
Tips > Analyst, deep link `/inbox/analyst/<id>`), reads/writes **shared knowledge notes**
(`tip_notes`, save_note tool, Knowledge panel) and maintains **its own trading rules** (scope
`rule`, injected into every run; retros update them). Filled tip proposals are adopted into
`engine.position_manager` with the analyst's policy (`lifecycle.adopt_when_filled`); closed tip
positions get a nightly **retro** (`tip_retro`, `techniques.tip.retro_*`).
Tip **proposals trade the tip's vehicle** (`approvals/proposals.py::create_from_signal`):
the analyst's "take" contract, else the book's expression, BUY-to-open only — a short tip
with no usable put proposes nothing; sized by `budget_per_tip`; context carries
`vehicle`/`explain`/`analystRunId`. `mode: auto` sources self-approve (analyst "take" or
analyst off; live portfolios also need `techniques.tip.allow_live_auto`). **Tips → arm
enrichment plan (5 phases, checkboxes): `docs/techniques/tip/ARM-PLAN.md`** — analyst-chosen
now-vs-at-level, one exit authority, zones/scale-ins, conditions, spreads; **gap-closure plan
(clusters A–F, BUILT 2026-08-29): `docs/techniques/tip/ARM-GAPS-PLAN.md`** — MULTI-DAY
STAY-ARMED plans (a plan whose horizon spans sessions ROLLS at each close — `plan_horizon`
hook, `_roll_session`, boot-roll on restore; EM stays single-session), partial-fill adoption,
verified spread rollback, never-chase caps, action-aware follow-ups (a "close" never opens;
expires proposals, flags waiting plans; analyst `disarm_plan`), re-arm replaces, nightly lane
grading + unfilled retros, tip-scoped knobs (`techniques.tip.enforce_session_windows` etc.
beat the EM-named legacy keys for tips), Settings "Tips technique" panel + per-source policy
editor. **`docs/NEXT-GAPS-PLAN.md` is BUILT (2026-08-29)** — A8 weekly rule audit, native mleg
spreads (`OrderManager.place_spread` + `evaluate_spread`, opt-in via `options.mleg_accounts`),
flow calibration (`tools/flow_calibrate.py`; re-sweep at ≥5 day-pairs), HMAC webhook auth,
the soak report (`tools/soak_report.py`) and `docs/PRE-LIVE-PROFILE.md`; what remains are
OPERATIONAL gates (practice soak calendar, Alpaca-paper pass, first live tip, real-device
mobile) — Telegram intake stays deprioritized, don't build it unasked. Its §0 records the
AMBITIOUS practice limits set 2026-08-29 (raised risk caps + all Discord sources
botsOnly=false) — re-tighten before real money (PRE-LIVE-PROFILE), never treat the practice
values as the safe baseline.
**Post-soak plan (2026-08-31; phases 1–5 BUILT 2026-09-01):** `docs/POST-SOAK-PLAN.md`
(queue + first-soak findings) + `docs/POST-SOAK-BUILD-PLAN.md` (checkboxes + findings) —
morning desk surface (`zargar/desk.py`: 08:25 report/push, 09:00 roll watchdog, nightly
soak), EARNED auto per source (`auto_min_graded`/`auto_min_hit`; explicit per-source auto
bypasses), shadow-book de-noise (Blotter hide/dim/show, no research toasts, one row per
source, `ResearchBadge`), intake recovery sweep (cold parks re-verify — promotions never
self-approve; error content retries once), pinned test clock (`zargar/clock.py`,
ZARGAR_TEST_NOW), batch-1 F-fixes harness-enforced. Phase 6 (real-device/Alpaca/first
live tip) = manual calendar gates with run-books in the build plan.
**Team split: EM evolution + other-technique enhancement = ANOTHER TEAM; this desk works
tips + technique-agnostic platform only** — keep shared-engine diffs small, per-technique
resolved (`rt()`), PLATFORM-RULES-logged; check `git log` for their merges each session.
**Knowledge system + historical experiments (BUILT 2026-08-30):** `docs/techniques/tip/KNOWLEDGE-PLAN.md`
(research + decided options) + `KNOWLEDGE-BUILD-PLAN.md` (phases, findings). Tip notes have per-scope
TTLs (`daily:*` 14d, `ticker:`/`source:` 90d — citation in a live run refreshes; `rule`/`general`
audit-gated; expiry is QUERY-TIME, no sweep; 📌 pin clears it) and the weekly audit also judges
ticker/source/general groups (`run_knowledge_audit`). Discord watch entries carry `mode: tips|context`:
context channels (trading-floor) mirror + digest but NEVER auto-intake; `onboardDays` backfill cap is
90 (mirror cap 50k). Digests: `techniques/tip/digest.py` — one `daily:<date>` note per channel-day +
≤5 promoted nuggets (ticker:/source: only), digest-now button, nightly gated by
`techniques.tip.digest_enabled`. Historical experiments: `tools/tip_experiment.py` (+
`techniques/tip/experiment.py`, API `/api/tip/experiment/*`): signals tagged `extraction.experiment`
are FORCED onto the replayed path — zero orders/books/proposals/dedupe/scorecards (PLATFORM-RULES
invariants 12–13, guard tests in `tests/test_platform_separation.py`) — appraised in historical mode
and graded by a rubric batch-review run. UI: Tips → **Knowledge** tab (`/inbox/knowledge`).
Intake stays in `zargar/signals/` (extraction v2 with Discord shorthand + screenshot transcription,
dedupe→`seen_count`, verification where price-position failures **park** the signal, an implied
non-actionable call demotes to **shadow** — books + scorecard, never a proposal — and content whose
own `stated_at` is > `techniques.tip.max_tip_age_hours` old is **replayed** on history via
`techniques/tip/replay.py` instead of traded); the technique is `zargar/techniques/tip/` (plan.py builds level-touch plans, horizon.py
bounds waiting by the tip's contract expiry − `techniques.tip.entry_cutoff_dte`, express.py picks
the stated contract verbatim, runner.py = `TipRunner(PlanRunner)`). **Dual shadow books per source**
(`Portfolio.book`): "immediate" buys at tip time, "armed" waits for the level (morning
`tip_shadow_arm` scheduler job) — never blended; the scorecard compares them and the trust bar is
judged on the ARMED book. Filled tip entries hand off to `engine.position_manager` (2b) and the
session runner forgets them. UI: `pages/InboxPage.tsx` = the **Tips** page (Tips · New tip · Analyst · Inbox tabs,
+ a set-apart ⚙ Sources config tab; bare `/inbox` = the Tips list).
**Flow technique (BUILT 2026-08-27, context-only — places no orders):** `docs/techniques/flow/PLAN.md`
+ `UI-PLAN.md`. Nightly scan (16:45 ET, engine scheduler) reads `option_chain_snapshots` (research
feed is the single writer; scoring-only live fallback) → `flow_reads` verdicts (Vol/OI flags,
overnight OI confirmation, repeat streaks). Context lines are journaled per delivery
(`FlowContextServed`) into tip verification and EM analyze (`config.flowContext` — a note, never a
rule); symbols scoring ≥ `techniques.flow.universe_score_min` on 2 of 3 days join the universe as
provenance "flow". UI: `pages/FlowPage.tsx` (Reads desk · Symbol Story drill-in · Brief tab).
Thresholds got their FIRST calibration 2026-08-29 (`tools/flow_calibrate.py`, flow PLAN §7:
dte_min=3, premium_min 250k, vol_oi_min 2.0, premium-weighted score) — PRELIMINARY on one
day-pair; re-run the sweep at ≥5 day-pairs before flipping `techniques.flow.calibrated`
(which upgrades confirmed high-score flow tips to explicit_call).
**Parallel Claude sessions:** the shared test DB (`zargar_test`) is dropped/recreated per test —
concurrent sessions corrupt each other's runs (phantom FK errors, DROP deadlocks). When another
session may be testing, create your own DB on :5433 and set
`ZARGAR_TEST_DATABASE_URL=postgresql+asyncpg://zargar:zargar@127.0.0.1:5433/zargar_test_<name>`. The runtime also holds positions
for **days or weeks** (BUILT 2026-08-27: `execution/positions.py` + `policies.py` + `simulate.py`;
guide in `docs/BUILDING-A-TECHNIQUE.md` §2b): exits are policies-as-data (ladder / trailing / time /
DTE / credit-target), state is write-ahead and restored regardless of date, shares held overnight get
a venue-side GTC stop, options overnight require `app_managed` + the explicit acknowledgement, and
the chaos suite (`tests/test_position_chaos.py`, 14 scenarios incl. live-vs-simulate parity) is the
acceptance gate — real money holds overnight only after an Alpaca-paper pass + practice soak.
**Sign-in (2026-08-26):** `docs/AUTH.md`. `zargar/auth.py` verifies Google ID tokens (PyJWT + Google JWKS)
and gates on `ZARGAR_GOOGLE_ALLOWED_EMAILS`, then issues an HS256 session (HttpOnly `zargar_session`
cookie + token in the body for WS `?token=`). `require_auth` accepts static token, bearer session, cookie
or `?token=`; `/api/auth/*` are the only public routes. Microsoft/Office 365 are listed as disabled
providers on the login page (`AuthService.providers()`). Frontend: `pages/LoginPage.tsx` gates `App`
when `auth.required && !user`; a 401 anywhere flips the store to the login screen.
**Mobile (built 2026-08-26):** `docs/MOBILE-PLAN.md` (phases, decisions) and `docs/MOBILE-ACCESS.md`
(Tailscale/HTTPS/token handoff, real-device checklist). Phones (< 640px, or landscape ≤ 500px tall,
`lib/viewport.ts`) get a bottom tab bar (Now · Trade · Tips · Portfolio · More), no sidebar, a
compact TopBar with HALT always visible, and `Sheet` instead of modals/popovers (`components/Sheet.tsx`;
`Modal` becomes a Sheet on phones). `src/mobile.css` is the ONLY place for phone/touch rules — it loads
after `styles.css`; never add `@media (max-width…)` to `styles.css`. Armed "Now" (`components/armed/
NowView.tsx`) is the phone home fed by `GET /api/technique/armed/summary`. Safety: `mobile.exit_only`
(default on) + RiskGate `phone_entry_blocked` — the API stamps `OrderIntent.client` from the
`X-Zargar-Client` header, never from the body. Push: `zargar/push.py` (pywebpush, VAPID + subscriptions
in settings), SW at `frontend/public/sw.js` (shell only, never `/api`). Gate every UI change with
`cd frontend && npm run mobile-audit` (Playwright device matrix; screenshots in `frontend/.mobile-shots/`,
gitignored; sign-in is enforced, so pass `ZARGAR_SESSION=$(python -m zargar.tools.mint_session)` from
`backend/` or every route screenshots the login page); `scripts/start.ps1` rebuilds dist when sources are newer — don't run `npm run build` in
parallel with it.
**New technique? Start at `docs/BUILDING-A-TECHNIQUE.md`** — the engine's capabilities (marketstructure,
PlanRunner hooks, settings resolver `techniques.<id>.<key>` → `execution.<key>`, scheduler, calendar,
chain snapshots, tags/caps, never-list) and the testing bar. **`docs/PLATFORM-RULES.md` is the shared judgement log** (invariants, engine-level findings, shared-knob
change log) — read it before touching the runtime. **`docs/techniques/enhanced-market/TRADING-RULES.md` is
EM's own judgement log** — findings, open questions with
decision thresholds (e.g. is `gap_void_r=1.0` too strict), theories, and the change log
of every rule/parameter change. Update it whenever a session teaches something about
the METHOD (not the code); date every claim and cite its run/scorecard/sweep. Check its
"Rules under observation" before tuning any technique threshold.

Tests default to `postgresql+asyncpg://zargar@127.0.0.1:5433/zargar_test`
(override: `ZARGAR_TEST_DATABASE_URL`). Runtime default is port 5432 per
docker-compose.

## Versioning

App version = `frontend/src/changelog.ts` (`APP_VERSION` + the curated CHANGELOG the
top-bar `v…` chip shows), mirrored in `frontend/package.json`, `backend/zargar/__init__.py`
and `backend/pyproject.toml` — bump all four together. Every user-visible change adds a
CONCISE entry (tag: major/new/improved/fixed/security) to the current release's block;
start a new block when the user calls a release. `/api/health` reports the version.

## Hard rules

- **Every order goes through `RiskGate.evaluate()`** — no code path may submit
  to an executor without it (bracket children are the one exception; they only
  reduce exposure). Kill-switch state must always be honored.
- **Journal every decision** via `Journal.append()` (`events` table is
  append-only; never update/delete rows). Quotes are never journaled.
- Money paths are write-ahead: persist the intent before routing; on unknown
  outcomes reconcile, never resubmit blindly.
- New runtime knobs go in `settings_service.DEFAULTS` (dot-keys) so they're
  UI-editable and journaled — not in env config, unless needed pre-DB.
- Wire format is camelCase (REST + WS). WS deltas are per-topic; quotes are
  conflated ~10 Hz for the UI while engine consumers read the raw bus.

## Gotchas (learned the hard way)

- `zargar/api/*.py` must NOT use `from __future__ import annotations` —
  FastAPI can't resolve locally-scoped Pydantic request models from string
  annotations (params silently become query args).
- Zustand selectors must return **stable references**: never `.filter()` /
  `Object.values()` inside a selector (React error #185 infinite loop);
  select the container, derive with `useMemo`.
- Highcharts v12: import from `highcharts/esm/...js` (e.g.
  `highcharts/esm/highstock.js`); EMA+SMA both register via
  `esm/indicators/indicators.js`; `time.useUTC` is gone (use `time.timezone`).
  Chart updates are imperative via ref — never route ticks through React props.
  Highcharts 12 keeps series data in a DataTable: `series.xData` is **undefined** — use
  `series.getColumn("x")`. Phone charts: `tooltip.followTouchMove` must be OFF or a finger
  can never pan (Pointer.pinch sets `initiated=false`); gestures live in `lib/chartTouch.ts`
  (`touch-action: pan-y`, pan/pinch/tap/double-tap, live-edge follow) — reuse it, don't re-derive.
- ib_async ≥ 2.0: `qualifyContractsAsync` returns `None` **in-slot** for
  failed contracts — always check before use. Canadian listings:
  `.TO` → `primaryExchange="TSE"`, `.V` → `"VENTURE"`, currency CAD.
- Sim engine is seedable (`ZARGAR_SIM_SEED`) — tests rely on
  `sim_tick_interval=0.03`, `sim_history_minutes=30` via
  `tests/conftest.make_test_config`.
- pydantic-settings precedence: real env vars beat `backend/.env`.
- Yahoo: the v7 `finance/quote` endpoint serves unauthenticated callers
  **hourly-frozen snapshots** (regularMarketTime pinned to the top of the
  hour) — cache-busting and crumbs don't help. The v8 `finance/chart` 1m bars
  ARE live (seconds old); the feed polls those per symbol. SnapTrade's own
  quotes endpoint requires userId/userSecret and rejects personal-key auth.
- Day change = regular-session price vs the PREVIOUS close (Yahoo chart meta
  `chartPreviousClose`/`regularMarketPrice`, carried on `Quote.prev_close` /
  `reg_price` / `session`), never today's first bar — brokers all quote it that
  way and a gap-up otherwise vanishes. Pre/after-hours moves show separately.
  Day sparklines/charts are seeded from Yahoo's real 1m session bars on
  `ensure_symbol` (not ticks-since-boot) and filtered to 09:30–16:00 ET.
- SnapTrade accounts hold cash in SEVERAL currencies at once (Webull CASH
  keeps a USD wallet inside a CAD account) — always sum ALL `/balances`
  entries FX-converted, never just the account-currency row.
- SnapTrade (personal auth): omit userId/userSecret; sign
  `{"content","path","query"}` as sorted-keys compact JSON, HMAC-SHA256,
  base64 in a `Signature` header (`SnapTradeClient._sign`). Accounts created
  after May 2026 get **410** from the legacy `/positions` and `/holdings`
  endpoints — use `/accounts/{id}/positions/all` (numbers arrive as strings,
  exchanges are MIC codes like XTSE, `instrument.kind` discriminates types,
  CDRs come pre-suffixed e.g. `AAPL.TO`).
- SnapTrade Connection Portal redeem tokens are session-bound: generate ONE
  re-auth URL at a time (`snaptrade_check --upgrade` enforces this) — a
  second URL from the same run dies when the first login completes.
- SnapTrade trading: soft limit 1 trade/sec/account (executor throttles);
  fills arrive by polling `recentOrders` — emit incremental deltas with
  deterministic exec ids or re-polls double-apply executions.
- Dry-run orders must NOT consume the rate/duplicate risk budget — the
  confirm dialog pre-flights every real-money order as a dry run first.
- The real-money confirm dialog triggers on `kind === "live"` portfolios
  only; sim/shadow/paper submit instantly.
- Yahoo v8 chart returns **HTTP 400** for a request window wholly in the future —
  `history.clip_request_window` ends every request at now; keep it that way.
  Walk-forward sweeps run symbols concurrently and score in a **process pool**
  (`technique.walkforward.workers`, 0 = auto; tests set 1 = thread) — the CPU half
  (`walkforward.compute_symbol_rows`) must stay pure/picklable. Sweep plans are built
  from `walkforward.plan_window()` = the same per-tf `SESSIONS_FOR_TF` windows
  `analyze()` fetches — change one, change both, or promoted runs stop matching their
  sweep rows (tests assert equality). A **plan sheet** (`start_plan_sheet`, Validation
  tab "Prepare the next session") is a sweep with `params.kind == "next"` whose rows are
  `result.pending` until `score_sheet` replays them — it mints no runs and calls no LLM.
- Technique/LLM: structured-output schemas must stay **flat** (nested models +
  enums → 400 "compiled grammar is too large"); signal extraction outgrew the
  budget entirely (nested 18-field list → "Schema is too complex" even with all
  enums flattened to str) — `signals/extraction.py` uses **prompted JSON +
  local pydantic validation** (enum vocab enforced by validators in
  `signals/schemas.py`), not `messages.parse`; Opus 5 defaults thinking display
  to `omitted` — pass `display: "summarized"` to stream it; never trust an
  image's extension, sniff the bytes (`technique/llm.py::sniff_media_type`);
  Yahoo 1m history ≈ 20 days back (8 days/request), 5m 60 d, 1h 2 y.
- Options chains come from CBOE's free delayed endpoint by default
  (`cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json` — greeks + IV
  included, no auth; Tradier needs a US address so it's optional via
  `options.provider` + `ZARGAR_TRADIER_TOKEN`). CBOE is US listings
  only — `.TO`/`.V` symbols have no chain there.
- Technique settings (`technique.*`, `llm.*`) are UI-editable.
- Execution exits are **reduce-only** (`OrderIntent(reduce_only=True)`): RiskGate
  runs a safety-only list so a stop/flatten is never blocked by an entry cap, the
  rate/duplicate window or the daily-loss halt; `risk.halt_allows_exits` (default
  on) lets the kill switch still close positions. Shared execution machinery lives
  in `zargar/execution/` (`SessionListener` loops + order index, pure `exits`
  decision/intent, `ManagedTrade`); `PlanArmer` subclasses `SessionListener`. New
  techniques reuse that layer instead of re-implementing order management.
- Armed plans default to the **options** instrument (just-OTM call via
  `technique.option_pick`, BUY LMT at ask, SELL at bid, P&L × 100, <3 contracts
  exit in full at TP2); tests that only need share fills must arm with
  `"instrument": "shares"`. Option quotes reach the risk gate only through
  `engine.quotes.on_quote()` (not a bare bus publish), and the sim executor
  needs a quote *after* its 120 ms latency to fill — publish twice.
- SnapTrade options (verified 2026-08-21, `snaptrade_options_check`): orders go
  to `POST /accounts/{id}/trading/options` with **space-padded 21-char OCC**
  symbols (`"F     260828C00014500"`), actions `BUY_TO_OPEN`… and **string**
  prices; preview via `…/trading/options/impact`. **Webull Canada supports it,
  Wealthsimple does not** (code 1156). Personal keys get 401 on SnapTrade's
  `optionsChain`/option-quote endpoints and 404 on `/optionsHoldings` — chains
  come from CBOE, option positions from `/positions/all` (`kind == "option"`),
  live contract last/bars from Yahoo v8 chart with the **unpadded** OCC symbol.
- Schema changes: `db.create_all` also ADDs missing columns on existing tables
  (additive only — NOT NULL columns are back-filled from the mapped default).
  Dropping/renaming a column is still manual.
- Every technique run carries `result.trace` (one record per decision, with a
  prose reason) and `config` (prompt/rulebook/code/process versions, thresholds,
  settings, `barsAssetId`). Add a `vp.note(...)` when you add a step to the
  pipeline; never strip the trace. `technique_runs`/`events` are never edited —
  reviews and replays are new rows.
- **Gap rules are judged on the 09:30 bar only** (`TriggerTracker`); a plan armed/restored
  after the open fetches the opening bars from history first (`_complete_opening_bars`),
  else the trigger runs `gap_unchecked`. Never evaluate a gap on "the first bar seen".
- **R2 is measured where the position exits** (`technique.rr_gate_target=auto` → TP2 for
  < 3 contracts); tests that encode the book's TP3 arithmetic pin `tp3` in their rig.
- Live 1m bars: `BarAggregator` holds a sampled bar ~5 s for the Alpaca exchange bar
  (`feed.exchange_bar_hold_seconds`); consumers get ONE bar per minute (`source: exchange`
  when corrected). The fire→critic→order chain runs off the bar loop (`_spawn_fire`);
  tests/manual feeds call `armer.on_bar()` which awaits `wait_fires()`.
- **Both sides are planned** (`technique.long_only` off): trigger kinds `bounce`/`breakout`/
  `wedge_break` (long, calls) and `reject`/`breakdown` (short, PUTS only — never share
  shorting). Everything price-relative (tracker, `outcome.simulate_plan`, `exits.plan_exit`,
  `quote_stop_breach`, option pick `min_strike`) takes the direction; keep mirrors in sync.
- Universe = `technique/universe.py`: core list (`technique.walkforward.symbols`, 117 liquid
  names) + `technique.universe.extra` + daily auto most-actives (price floor) − exclude;
  `service.universe()` / `GET /api/technique/universe`. Don't hand-edit the core in settings
  DEFAULTS — it is `CORE_UNIVERSE`.
- Stops exit on the bar CLOSE (`technique.stop_on_close`), the 0.25R quote breach is the
  crash brake; sizing is risk-based (`technique.arm.contracts`=0) with Friday/0DTE
  multipliers; 0DTE only before `technique.arm.avoid_0dte_after` (10:30).
- Pre-open (09:25 ET): `PlanArmer._preopen_check` judges plans against the pre-market print
  and may re-plan with `build_session_plan(reference_price=)`; a re-planned run's
  `referencePrice` is the tracker's prev_close for the gap rule.
- Auto mode never arms without a loss halt (`_ensure_loss_halt`, fallback
  `technique.arm.daily_loss_fallback`); the critic fails OPEN with a timeout + per-day
  budget (`technique.arm.critic_fail_budget`) that pauses the plan.
- Armed plans also run a ~2s **quote stop watch** (`technique.arm.quote_exit*`):
  exit-only, fires when the underlying's live quote is decisively through the stop
  (excess_r × risk beyond, N consecutive polls). Never add an entry path to
  `SessionListener.on_quote_watch` — sub-minute entries cannot be validated (no 5s history).
  The same loop also runs the **premium stop** (options bleeding past
  `technique.arm.premium_stop_pct`) and the **failed-exit watchdog** (market retry
  every 30s ×5, then alert). Armed-plan failures escalate through `PlanArmer._alert`
  (log + journal + WS toast + Telegram) and surface as `needsAttention` on the
  snapshot — wire new failure modes through those two, not bare log lines.
- **Armed plans can trade.** `technique/arming.py` modes: alert / proposal / auto. Auto mode
  places orders only via `OrderManager.place()` (RiskGate inside) and honours the kill
  switch; auto on a live/paper account needs `technique.arm.allow_live_auto`,
  `trading.mode=live` AND the per-arm `allowLive` acknowledgement. Order `source` is
  `technique` (the column is 12 chars). Exits are managed on closed 1m bars; everything is
  journaled under the plan run id (`GET /api/technique/armed/{id}/audit`).
- **R6 schedule is enforced** (`technique.enforce_session_windows`): a setup found
  outside 09:30–10:30 / 14:45–16:00 ET is watch-only; an as-of outside the session makes
  `analyze()` build a *plan* (`mode="plan"`, verdict `plan`) instead of a fill; scans and
  the backtester are window-gated. Plan triggers and live arming share
  `walkforward.TriggerTracker` — change one path, both change.
- Outcomes (`technique_outcomes`) are scored by `outcome.simulate_plan`, the same
  walk-forward the backtester uses — change one, change both. Yahoo 1m depth
  (~20 d) bounds how late a run can still be scored; the bars snapshot saved per
  run is what makes replay possible after that.
- Patching files from scripts on Windows: open with `encoding="utf-8"`
  (the default cp1252 silently corrupts em dashes / arrows).

## Testing conventions

- Integration tests drive the real `Engine` on the sim broker and the real
  API via `httpx.ASGITransport` (lifespan not run — engine started manually).
- LLM extraction is never called in tests: build `ExtractionResult` fixtures
  and call `signals_service.handle_extraction()` directly (see
  `tests/test_api_and_pipeline.py::canned_extraction`).
- Async predicate waits use `tests/conftest.wait_for` — no bare sleeps.
- UI verification: build, then Playwright against the served app
  (`/opt/pw-browsers` chromium in the dev container).
