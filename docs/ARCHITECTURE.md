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
| `signals/verification.py` | Deterministic checks vs live data: grounding, actionability, ticker resolves, halt, min price, spread, price ordering (fatal) — price deviation / past-target only **park** the signal (the tip technique keeps watching the level). |
| `signals/service.py` | Pipeline orchestration: ingest (text / screenshot→transcript) → extract → ground → dedupe (repeats bump `seen_count`) → persist → verify (verified / parked / failed) → propose + **shadow-execute** into the source's immediate book; per-source policies in `signals/sources.py`; two-book scorecards. |
| `approvals/proposals.py` | Proposal queue: sizing (% of equity), TTL expiry loop, approve/half/reject → order placement. |
| `approvals/telegram.py` | Long-polling bot: proposal cards with inline buttons, `/halt` `/resume` `/status`. Only the configured chat id may act. |
| `engine.py` | Wires everything; background tasks: quote consumer, bar persister, equity snapshotter (30 s), daily-loss monitor (auto-halt). |
| `api/app.py` | FastAPI factory — all REST routes. ⚠ no `from __future__ import annotations` here (breaks FastAPI's resolution of locally-scoped request models). |
| `api/ws.py` | WS hub: snapshot on connect, per-topic delta fan-out, quotes conflated to ~10 Hz. |
| `tools/ibkr_check.py` | Read-only IBKR connectivity self-test (`python -m zargar.tools.ibkr_check`). |

### Technique platform (2026-08-27, `docs/TECHNIQUE-PLATFORM-PLAN.md`)

One engine, many techniques. Three shared layers and a thin package per technique:

| Layer | Package | What lives there |
|---|---|---|
| Market structure | `zargar/marketstructure/` | Pure functions over bars, parameterised by `MarketRules` (never a technique's rulebook): levels/pivots/in-band touches (`levels`), `distance_pct`, volume vs its time-of-day baseline (`volume`), candles, trendlines/wedges (`structure`), the ET session clock (`sessions`), **`TriggerTracker`** — the touch/break/gap/volume/false-break/invalidation state machine shared by live, plan and sweep (`tracker`), `simulate_plan` (`outcome`), bars fetch (`history`). `zargar.technique.<module>` paths are shims. |
| Execution | `zargar/execution/` | The money path: `SessionListener` (1m bars + orders + heartbeat + quote watch), `exits` (pure decisions, reduce-only intents), `book.ManagedTrade`, **`positions.PositionManager`** — durable multi-day positions (phase 2b: policies-as-data via `policies.py`, multi-leg as a leg list, write-ahead + restored on boot, closed policy-tf-bar decisions RTH-only, quote crash brake, failed-exit watchdog, venue GTC stops for shares / app-managed-with-ack for options, assignment-aware pre-open reconciliation at 09:05 ET, `simulate.simulate_position` = the same evaluator over history, `sizing` risk/budget modes, chaos suite `tests/test_position_chaos.py`) — and **`planrunner.PlanRunner`** — arm/restore/persist, the off-loop fire chain, entry with retry, sizing, contract/premium caps, ladder/stop/flatten management, loss halt, quote-stop + premium-stop watch, failed-exit watchdog, alerts, audit, phone summary. Hooks a technique overrides: `rules`, `load_plan`, `load_baseline_bars`, `entry_windows_enforced`, `analyze_fire`, `reviewer_available`/`review_fire`, `record_fire`, `emit_proposal`, `after_fire`, `pick_contract`, `size_multiplier`, `preopen_due`/`preopen`, `arm_today`. The runner owns the reviewer's timeout, fail-open budget, veto cooldown, kill cap and re-arming; **hooks never journal** — the runner journals their results. |
| Research | `zargar/research/` + `zargar/technique/service.py` | Event-schema contracts (`research/events_contract.py` — every `Technique*`/`ManagedPosition*` journal kind is versioned; contract test + advisory runtime check) and the nightly feeds (`research/snapshots.py`: `option_chain_snapshots` at 16:30 ET — per-contract OI/IV/volume, not backfillable — and the tf=1d bar layer at 20:05). Runs/outcomes/reviews/replay/sweeps stay in `technique/service.py`, keyed by the `technique` column + free-form `tags`; the class moves into `research/` when technique #2 needs it. |
| Techniques | `zargar/techniques/` (registry + tip + flow) + `zargar/technique/` (EnhancedMarket) | `TechniqueInfo` registry (`GET /api/techniques`) lists three: **EM** (`technique/` — rulebook, setups, plans, prompts/schemas, vision, chat, `arming.PlanArmer(PlanRunner)`), **Tip** (`techniques/tip/` — plan/horizon/express + `runner.TipRunner(PlanRunner)`; intake stays in `signals/`; dual shadow books via `Portfolio.book`; filled entries hand off to the PositionManager), **Flow** (`techniques/flow/` — pure scan math + `FlowService` on the scheduler; context-only, never orders; `FlowContextServed` journals every delivery). |

Engine services added 2026-08-27: `scheduler.py` (named once-a-day ET jobs — techniques register
scans; journaled `ScheduledJobRan/Failed`, failure-alerted), `calendar_service.py`
(`engine.calendar`: earnings + ex-dividend, Yahoo v1, advisory), the 09:00 ET feed self-test in
`engine._feed_monitor`, bars hygiene at boot (bucket alignment enforced at write; 1d rows exempt),
and RiskGate's never-list (share shorting rejected everywhere; 0DTE only for EM) plus
per-technique/per-tag day-notional caps fed by `OrderIntent.technique_id`/`tags`.

Identity: `technique` column on `technique_runs/outcomes/sweeps/armed/setups` (DB default
`enhanced_market`), `OrderIntent.technique_id`, `ArmedPlan.technique`. Docs: `docs/PLATFORM-RULES.md`
(shared lessons) and `docs/techniques/<id>/` (the technique's spec, plans and `TRADING-RULES.md`).

**Team2 technique (2026-09-03, `docs/techniques/team2/`).** Fourth registered technique (`team2`): `techniques/team2/` = rules (a `MarketRules` superset snapshotted per plan), regime (13/48/200 EMA on 2m, extended hours), scenario (prior-day-zone bias + 15m-close confirmation), plan (nightly skeleton → 09:25 completion), premium (Black–Scholes 0DTE model, premium-targeted strike), `session.simulate_session` (the ONE pure read used live and in replay), `Team2Runner(PlanRunner)` (overrides the bar loop: re-runs the read on every 2m close and acts on new events through the shared fire/exit path) and `Team2Service` (plan runs, nightly + pre-open jobs, replay, sweep). API `/api/team2/*`; page `Team2Page`. Shared additions it brought: extended-hours bars + `aggregate`/`indicators`/`dailylevels`/`market_calendar` in `marketstructure/`, the nightly `ext_bars` and `vix_bars` research jobs, `options/pick.py`, `research/macro_calendar.py` (`engine.macro`), and the per-technique 0DTE policy in `RiskGate` (`techniques.<id>.zero_dte`).

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
| Shadow | TWO automatic per-source pretend books (`Portfolio.book`): **immediate** buys at tip time; **armed** waits for the level (morning `tip_shadow_arm` sweep) — the Tips scorecard compares them |
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
| `pages/` | `TradePage`, `InboxPage` = the **Tips** page (New tip composer · Tips · Sources scorecards · Inbox), `FlowPage` (Reads desk · Symbol Story · Brief), `PortfoliosPage` (equity curves), `JournalPage` (audit browser), `SettingsPage` (every runtime knob, watchlists, sources). |
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
