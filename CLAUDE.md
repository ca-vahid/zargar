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
```

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

## Testing conventions

- Integration tests drive the real `Engine` on the sim broker and the real
  API via `httpx.ASGITransport` (lifespan not run — engine started manually).
- LLM extraction is never called in tests: build `ExtractionResult` fixtures
  and call `signals_service.handle_extraction()` directly (see
  `tests/test_api_and_pipeline.py::canned_extraction`).
- Async predicate waits use `tests/conftest.wait_for` — no bare sleeps.
- UI verification: build, then Playwright against the served app
  (`/opt/pw-browsers` chromium in the dev container).
