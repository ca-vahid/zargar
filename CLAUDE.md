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
cd backend && .venv/bin/python -m pytest tests/test_options_*.py tests/test_snaptrade_options.py  # options (stubbed CBOE/SnapTrade)
cd backend && .venv/bin/python -m zargar.tools.technique_review list --unreviewed   # review loop CLI (dump/score/review/diff/replay)
cd backend && .venv/bin/python -m zargar.tools.technique_review sweep --start 2026-07-01 --end 2026-08-20   # walk-forward sweep (deterministic)
```

Options trading: research + build plan + status in `docs/OPTIONS-PLAN.md`.
Code: `backend/zargar/options/` (occ symbology, chain providers, OptionsService),
`api/routes_options.py`, UI `frontend/src/pages/OptionsPage.tsx` +
`components/OptionChain.tsx` / `OptionTicket.tsx`. Internal option symbol =
**unpadded OCC** (`F260828C00014500`); `occ.to_snaptrade()` pads at the venue.

Technique pipeline (EnhancedMarket method): spec in `docs/TECHNIQUE-ENHANCEDMARKET.md`,
build plan + lessons in `docs/TECHNIQUE-PIPELINE-PLAN.md`, code in
`backend/zargar/technique/`, UI in `frontend/src/pages/TechniquePage.tsx`.
Review loop (trace, provenance, outcomes, reviews, replay, bundle):
`docs/TECHNIQUE-REVIEW-PLAN.md`; the `/technique-review` skill
(`.claude/skills/technique-review/`) audits one run end-to-end and plans the fix.
Session plans + walk-forward + live arming: `docs/TECHNIQUE-WALKFORWARD-PLAN.md`
(`technique/plans.py`, `walkforward.py`, `arming.py`; UI Validation tab).
**`docs/TRADING-RULES.md` is the living judgement log** — findings, open questions with
decision thresholds (e.g. is `gap_void_r=1.0` too strict), theories, and the change log
of every rule/parameter change. Update it whenever a session teaches something about
the METHOD (not the code); date every claim and cite its run/scorecard/sweep. Check its
"Rules under observation" before tuning any technique threshold.

Tests default to `postgresql+asyncpg://zargar@127.0.0.1:5433/zargar_test`
(override: `ZARGAR_TEST_DATABASE_URL`). Runtime default is port 5432 per
docker-compose.

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
  enums → 400 "compiled grammar is too large"); Opus 5 defaults thinking display
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
