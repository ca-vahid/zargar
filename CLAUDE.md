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
cd backend && .venv/bin/python -m pytest tests/test_technique_*.py       # technique pipeline (no LLM calls)
cd backend && .venv/bin/python -m zargar.tools.technique_review list --unreviewed   # review loop CLI (dump/score/review/diff/replay)
```

Technique pipeline (EnhancedMarket method): spec in `docs/TECHNIQUE-ENHANCEDMARKET.md`,
build plan + lessons in `docs/TECHNIQUE-PIPELINE-PLAN.md`, code in
`backend/zargar/technique/`, UI in `frontend/src/pages/TechniquePage.tsx`.
Review loop (trace, provenance, outcomes, reviews, replay, bundle):
`docs/TECHNIQUE-REVIEW-PLAN.md`; the `/technique-review` skill
(`.claude/skills/technique-review/`) audits one run end-to-end and plans the fix.

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
- Technique/LLM: structured-output schemas must stay **flat** (nested models +
  enums → 400 "compiled grammar is too large"); Opus 5 defaults thinking display
  to `omitted` — pass `display: "summarized"` to stream it; never trust an
  image's extension, sniff the bytes (`technique/llm.py::sniff_media_type`);
  Yahoo 1m history ≈ 20 days back (8 days/request), 5m 60 d, 1h 2 y.
- Options chains come from CBOE's free delayed endpoint by default
  (`cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json` — greeks + IV
  included, no auth; Tradier needs a US address so it's optional via
  `technique.options.provider` + `ZARGAR_TRADIER_TOKEN`). CBOE is US listings
  only — `.TO`/`.V` symbols have no chain there.
- Technique settings (`technique.*`, `llm.*`) are UI-editable.
- Schema changes: `db.create_all` also ADDs missing columns on existing tables
  (additive only — NOT NULL columns are back-filled from the mapped default).
  Dropping/renaming a column is still manual.
- Every technique run carries `result.trace` (one record per decision, with a
  prose reason) and `config` (prompt/rulebook/code/process versions, thresholds,
  settings, `barsAssetId`). Add a `vp.note(...)` when you add a step to the
  pipeline; never strip the trace. `technique_runs`/`events` are never edited —
  reviews and replays are new rows.
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
