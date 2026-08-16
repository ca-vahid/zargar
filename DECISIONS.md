# Zargar — Decisions

*Owner Q&A held 2026-08-16. These decisions override the generic recommendations in [RESEARCH.md](./RESEARCH.md) where they differ.*

## Confirmed decisions

### 1. Hosting & runtime
- **Runs on the owner's computer for now** — no VPS/home server yet.
- **Only the database is dockerized.** The trading engine and web app run natively (no docker rebuild on every dev change).
- **Database: PostgreSQL** (owner preference; replaces the SQLite recommendation). Runs in Docker via `docker compose up db`. The event-sourced journal + projections design from RESEARCH.md §8 carries over unchanged to Postgres.
- Consequence, stated plainly: automated signal ingestion and rule-based execution only run while the computer is on. The architecture keeps the engine a standalone daemon so the whole stack can move to a VPS later without restructuring.

### 2. Instruments
- **US stocks & ETFs, Canadian stocks (TSX/TSXV), and options — both US and Canadian.**
- Implications:
  - Market data: US bundle (~$10/mo, waivable) + Canadian equities bundle + **OPRA** (US options) + **Montreal Exchange** (Canadian options) subscriptions on the API username. Enumerate exact SKUs/prices during setup.
  - Ticker disambiguation is mandatory in the verification layer (same symbol on TSX vs NYSE).
  - Options add: chain browsing, strike/expiry pickers, multi-leg orders, greeks display. **Phasing:** stock trading MVP first; options as the immediately following phase — but the data model (contracts, not just symbols) is designed for options from day one.
  - Fill simulator: stocks simulated with the touch+slippage model; options fills simulated conservatively (mid-to-worse with spread haircut) given wide spreads.

### 3. Signal sources
Owner uses **all channels**: email newsletters/alerts, Discord rooms, websites/message boards, X/Twitter feeds, and some sources that offer **direct API access**.
- **Email is the primary ingestion bus** (see RESEARCH.md §6). Owner **has a personal domain** and will re-subscribe sources to a dedicated address → **Cloudflare Email Routing + Email Worker** webhook into the engine.
- Source-adapter architecture: every source type normalizes into the same `RawContent` record before extraction, so adapters can be added one at a time:
  1. `email` (Cloudflare inbound webhook) — first
  2. `api` (per-source pollers for sources with real APIs) — second
  3. `rss` (free Substack/blogs as publish triggers)
  4. `discord` / `web` / `x` — case-by-case; compliant options preferred (email/SMS mirrors); ToS-gray readers only with the owner's explicit sign-off per source.
- Owner to provide the concrete list of subscriptions when we build the adapters.

### 4. Approvals
- **Telegram bot + in-app pending queue** (both).
- Telegram: proposal card with thesis, verification summary, chart snapshot; inline Approve / Reject / Half-size buttons; also the kill-switch command channel (`/halt`, `/status`).
- In-app: pending-proposals panel with the same actions and full audit detail; TTL expiry on all proposals.

### 5. Charting
- License confirmed: **Highcharts Stock (or Suite)** — full candlestick/indicator/Stock Tools scope is available. Use the new official `@highcharts/react` wrapper.

### 6. Risk calibration
- Initial funding **under $10k** → starter defaults (all user-editable in settings):
  - Max position: 10% of equity per symbol (notional cap ~$1,000 initially).
  - Max total gross exposure: 100% of equity (no leverage by default).
  - Daily loss halt: 3% of equity → soft halt until manually re-armed next day.
  - Options: max premium at risk per trade 5% of equity; no naked short options in v1.
  - Order-rate limit: 10 orders/min → auto-halt.
- Small account + options + illiquid newsletter picks = the liquidity/spread filter (RESEARCH.md §6e) stays strict.

### 7. IBKR account regime
- Domicile/type **unconfirmed** ("not sure"). The rules engine ships with a **config switch** (`account_regime: ca | us`) covering:
  - Day-trade counting/warnings (until IBKR's post-2026-PDT policy is confirmed for the account).
  - Tax-loss flagging: CRA superficial-loss vs IRS wash-sale windows.
- **Owner action item:** check Client Portal → account details (IBKR Canada vs IBKR LLC; margin vs cash) and set the switch.

## Owner action items (before/while build starts)

1. Confirm IBKR account domicile and type (margin vs cash) in Client Portal.
2. Create the **second username** for API access (Client Portal → Users & Access Rights) — prevents desktop logins from kicking the bot.
3. Request the **paper trading account** if not already enabled; enable market-data sharing with paper.
4. Market-data subscriptions on the API username: US Securities bundle, Canadian equities, OPRA, Montreal Exchange.
5. Pick the subdomain/address for signal ingestion (e.g., `signals@<personal-domain>`) — Cloudflare Email Routing setup is part of the build.
6. Create a Telegram bot via @BotFather when we reach the approvals milestone (2-minute task; we'll walk through it).

## Revised build order (from RESEARCH.md §10, adjusted)

1. **Foundation:** repo scaffolding; `docker-compose.yml` for Postgres only; Python engine skeleton (ib_async → IB Gateway paper, quote streaming, event journal in Postgres); Vite/React SPA shell + first Highcharts Stock chart over live paper data.
2. **Manual trading MVP (stocks, US+CA):** order ticket (market/limit/bracket), positions/orders/P&L, RiskGate with the §6 defaults, kill switch.
3. **Mock ladder:** dry-run mode, local fill simulator, shadow portfolios.
4. **Options:** chains, strike/expiry picker, single-leg then multi-leg orders through the same RiskGate.
5. **Signal ingestion:** Cloudflare email worker → extraction (Claude structured outputs + quote-grounding) → verification → pending-proposal queue.
6. **Approvals:** Telegram bot + in-app queue, full audit trail.
7. **Live money, small caps on;** then per-source trust stats → rules-gated auto-execution.
