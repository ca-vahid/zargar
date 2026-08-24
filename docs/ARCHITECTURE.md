# Zargar architecture

One Python process runs the trading engine, the REST/WebSocket API, and (in the
default setup) serves the built UI. PostgreSQL is the only external service.

```
                       ┌──────────────────────────────────────────────┐
                       │  backend (one asyncio process, port 8420)    │
 IB Gateway ──TCP──▶   │  brokers/ibkr.py     ┐                       │
 (paper/live, opt.)    │                      ├─▶ QuoteCache ─▶ Bus ──┼─▶ WS hub ─▶ React SPA
                       │  brokers/sim.py  ────┘      │                │   (conflated ~10 Hz)
 Cloudflare Email ─▶   │  signals/ingest ─▶ extraction ─▶ verification│
 worker (webhook)      │        │                 (Claude API)        │
                       │        ▼                                     │
 Telegram ◀──────────▶ │  proposals ─▶ OrderManager ─▶ RiskGate ─▶ Executor (sim | ibkr)
                       │        │            │
                       │        ▼            ▼
                       │  Journal (events table)   PositionKeeper (positions/cash/equity)
                       └──────────────┬───────────────────────────────┘
                                      ▼
                                PostgreSQL 16 (Docker)
```

## Backend map (`backend/zargar/`)

| Module | Responsibility |
|---|---|
| `config.py` | Process-level config from env / `.env` (`ZARGAR_*`). Things needed before the DB is up. |
| `settings_service.py` | **Runtime-tunable settings** (dot-keys over typed defaults), persisted in DB, edited live from the UI, journaled on change. |
| `domain.py` | Enums + value objects: `OrderSide/Type/Status`, `PortfolioKind`, `Quote`, `Bar`. |
| `bus.py` | In-process async pub/sub. Topics: `quotes, events, orders, executions, positions, portfolio, proposals, signals, system, bars`. Slow subscribers drop oldest — the UI can never stall trading. |
| `models.py` | SQLAlchemy ORM. `events` is append-only source of truth; `orders/positions/…` are projections. JSONB on Postgres. |
| `events.py` | `Journal.append()` — writes an event row + publishes it. Every decision lands here; quotes do not. |
| `marketdata.py` | `QuoteCache` (latest quote + staleness), `BarAggregator` (1m bars from quotes, resampled to 5m/15m/1h on read), bar persistence. |
| `brokers/base.py` | The two interfaces: `QuoteFeed` (where market data comes from) and `Executor` (where orders go), plus `BrokerOrder`/`ExecReport`. |
| `brokers/sim.py` | `SimQuoteFeed` — deterministic-seedable random-walk market with synthesized history; `SimExecutor` — conservative fill engine (opposite-touch + slippage + size impact, limit-cross fills, stop triggers, OCA groups, simulated latency). |
| `brokers/ibkr.py` | `IBKRBroker` — ib_async adapter (feed + executor in one). `.TO`/`.V` suffixes map to TSX/TSXV. `orderRef` carries our client order id. |
| `risk.py` | `RiskGate.evaluate()` — the mandatory pre-trade pipeline (see below) + `HaltState` (kill switch, persisted across restarts). |
| `orders.py` | `OrderManager` — write-ahead intents, risk gate, mode-based routing, lifecycle from `ExecReport`s, bracket-children spawning, projections. Option orders: derived open/close action (`derive_option_action`), close-qty guard, venue capability gate (`option_gate`). |
| `options/occ.py` | OCC symbology — canonical **unpadded** OCC (`F260828C00014500`), SnapTrade's padded form at the venue boundary, display names, DTE. |
| `options/chain.py` | Chain providers (CBOE free delayed default, Tradier optional) → normalized rows with greeks/IV. |
| `options/service.py` | `OptionsService` — expiries/strike ladder/contract snapshots, contract quotes (Yahoo live `last` + chain bid/ask via `QuoteCache.set_overlay`; on the sim feed it publishes whole quotes), SnapTrade options capability cache (allowlist + live impact verdicts), expiry settlement for practice portfolios. |
| `api/routes_options.py` | `/api/options/{und}/expiries`, `/chain?expiry=`, `/quote/{occ}`, `/impact`, `/capabilities`, `/expiring`. |
| `portfolio.py` | `PositionKeeper` — avg-cost positions, realized/unrealized P&L, cash, equity, daily-loss %, equity snapshots. Options use a 100× multiplier. |
| `signals/schemas.py` | Pydantic schemas for Claude structured extraction + the extraction system prompt. |
| `signals/extraction.py` | Claude call (`messages.parse`) + **quote grounding**: every extracted ticker/price must be backed by a verbatim quote found in the source, verified in code. |
| `signals/verification.py` | Deterministic checks vs live data: grounding, actionability, ticker resolves, halt, min price, spread, price deviation, past-target, price ordering. |
| `signals/service.py` | Pipeline orchestration: ingest → extract → ground → persist → verify → propose + **shadow-execute** into a per-source shadow portfolio. |
| `approvals/proposals.py` | Proposal queue: sizing (% of equity), TTL expiry loop, approve/half/reject → order placement. |
| `approvals/telegram.py` | Long-polling bot: proposal cards with inline buttons, `/halt` `/resume` `/status`. Only the configured chat id may act. |
| `engine.py` | Wires everything; background tasks: quote consumer, bar persister, equity snapshotter (30 s), daily-loss monitor (auto-halt). |
| `api/app.py` | FastAPI factory — all REST routes. ⚠ no `from __future__ import annotations` here (breaks FastAPI's resolution of locally-scoped request models). |
| `api/ws.py` | WS hub: snapshot on connect, per-topic delta fan-out, quotes conflated to ~10 Hz. |
| `tools/ibkr_check.py` | Read-only IBKR connectivity self-test (`python -m zargar.tools.ibkr_check`). |

### Order lifecycle

```
OrderIntent (API/proposal) ─▶ Order row NEW + journal OrderIntentCreated
  ─▶ RiskGate (journal RiskCheckPassed/Failed) ── fail ─▶ REJECTED_RISK
  ─▶ routing gate (trading.mode × portfolio.kind) ─▶ DRY_RUN | rejected | Executor
  ─▶ SUBMITTED ─▶ accepted/fill/cancel/reject ExecReports
  ─▶ Execution rows, PositionKeeper.apply_fill, journal, bus
  └─ full fill + bracket spec ─▶ child LMT (take-profit) + STP (stop-loss) in one OCA group
```

Routing gate: `dry_run` routes nothing; `sim` routes sim+shadow portfolios;
`paper` adds paper; `live` adds live. Sim/shadow route to `SimExecutor`,
paper/live to `IBKRBroker`.

**RiskGate checks** (each journaled): kill switch, quote freshness, instrument
halt, price collar (options: vs mid with a tick floor), short-selling rule,
options rules (enabled, premium cap % and $, no naked shorts, valid OCC, not
expired / 0DTE toggle, contracts per order, spread cap for market orders), max
position notional & % equity, max gross exposure (reducing orders bypass the
caps), order rate, duplicate window, daily loss limit, market hours (live/paper
optional; always enforced for options).

### Signal pipeline

```
email webhook / manual paste ─▶ raw_content row + ContentReceived
  ─▶ Claude extraction (structured output, claude-opus-5)
  ─▶ ground_signal(): every evidence quote must appear verbatim in the source;
     every price must appear in a grounded quote  → hallucinations die here
  ─▶ verify_signal(): deterministic checks vs QuoteCache + settings thresholds
  ─▶ verified ─▶ proposal (sized, TTL) + shadow-portfolio market order
              └▶ failed  ─▶ signal stored as verification_failed (auditable)
```

Shadow portfolios (`Shadow: <source>`, $10k virtual) trade **every** verified
signal regardless of your decision — the per-source track record that later
justifies auto-execution.

### The mock ladder

| Rung | Mechanism |
|---|---|
| Dry run | `trading.mode=dry_run` or per-order flag — validated + journaled, never routed |
| Simulation | `SimExecutor` fills against live quotes (sim feed today; IBKR feed when connected) |
| Shadow | Automatic per-source portfolios on verified signals |
| IBKR paper | `ZARGAR_BROKER=ibkr` + mode `paper` |

## Wire formats

REST responses and WS messages use camelCase. WS protocol (`/ws`):

* server → client: `{"t": "snapshot", d}` on connect, then
  `quotes` (array, conflated), `order`, `execution`, `position`, `portfolio`,
  `proposal`, `signal`, `system` (halt/setting/broker), `event` (journal),
  `bar` (`{symbol, tf, bar: [ts,o,h,l,c,v]}`).
* client → server: `{"t":"watch","symbol":…}`, `{"t":"ping"}`.

Auth: if `ZARGAR_AUTH_TOKEN` is set, REST needs `Authorization: Bearer …` and
WS needs `?token=…`. The inbound email webhook uses `X-Zargar-Ingest-Key`
(`ZARGAR_INGEST_KEY`) instead.

## Database

`events` (append-only journal) • `portfolios` • `orders` • `executions` •
`positions` • `bars` (1m history) • `equity_points` • `raw_content` •
`signals` • `proposals` • `settings` • `watchlists` • `instruments`.
Schema is created with `create_all` on startup (no migrations yet — see
ROADMAP).

## Frontend map (`frontend/src/`)

| File | Responsibility |
|---|---|
| `store.ts` | One Zustand store: snapshot state + delta appliers + toasts. ⚠ selectors must return **stable references** (derive filtered arrays with `useMemo`, never `.filter()` inside a selector — causes React error #185). |
| `lib/ws.ts` | WS client with reconnect/backoff; `onBar()` listener registry; `watchSymbol()`. |
| `lib/api.ts` | Fetch wrapper + typed endpoints; bearer token from localStorage. |
| `components/StockChart.tsx` | Highcharts Stock via **imperative ref** — React renders once; ticks update the forming candle with `point.update()`, closed 1m bars append via `onBar`. ⚠ Highcharts v12 imports come from `highcharts/esm/...js`; EMA/SMA both live in `esm/indicators/indicators.js`. |
| `components/OrderTicket.tsx` | Side/qty/type/tif/bracket/dry-run; shows failed risk checks inline. |
| `pages/OptionsPage.tsx`, `components/OptionChain.tsx`, `components/OptionTicket.tsx` | Options: underlying header → expiry strip → strike ladder (calls / strike / puts, centred on ATM) → single-leg option ticket (greeks strip, derived open/close, fees, max loss, breakeven, broker preview, confirm dialog). Deep links `/options/SPY`, `/options/SPY/<expiry>`, `/options/c/<OCC>`. `lib/occ.ts` mirrors the backend symbology. |
| `components/Blotter.tsx` | Positions / open orders / history / fills tabs. |
| `pages/` | `TradePage`, `InboxPage` (proposals+signals+pipeline tester), `PortfoliosPage` (equity curves), `JournalPage` (audit browser), `SettingsPage` (every runtime knob, watchlists, sources). |
| `styles.css` | Design tokens: dark default + light theme, user-set accent, density; market colors `--up/--down`; categorical `--series-1..8`. |

## Testing

* Backend: `pytest` against **real Postgres** (port 5433 locally in dev
  container, or `ZARGAR_TEST_DATABASE_URL`). 64 tests: risk gate, fill engine,
  bar aggregation, quote grounding, verification, engine order flow, API +
  full pipeline (extraction stubbed with canned results — no API key needed).
* Frontend: `npm run build` (tsc + vite) is the gate; end-to-end verified with
  Playwright driving the real served app.


## Workspaces (2026-08-23)

`trading.mode` is a **workspace**, not just a routing gate. Practice = the in-app
simulator (`sim` + `shadow` books); Live = real venues (`live` accounts and
broker-hosted `paper` accounts — IBKR paper trades on IBKR's systems with their
numbers, so it belongs to Live, greyed until the gateway connects). Switching the
workspace (top bar, next to HALT) both flips the order-routing gate (unchanged:
practice mode rejects orders to real accounts in `orders.py`) and scopes every
account-shaped view: top-bar money, Dashboard (net worth, provider cards, recent
activity, equity curve), Portfolios, the Blotter, account pickers
(`AccountSelect`), the Arm dialog's account list, and the Armed dashboard
(cards, KPIs, history). The Technique research surfaces (analyses, plans,
validation, sheets) are shared — they are account-free. Armed plans in the
hidden workspace are never silent: the top bar and the Armed tab show an
"N armed in <other>" notice. Single source of truth:
`frontend/src/lib/workspace.ts` (`workspaceOf`, `useWorkspace`,
`useWorkspacePortfolios`, `useWorkspaceFilter`).
