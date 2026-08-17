# Zargar

Personal stock trading application connected to Interactive Brokers (IBKR).

Zargar is a single-user app built around three ideas:

1. **Fast manual execution** — see an opportunity, execute it immediately through an intuitive, real-time interface.
2. **Signal ingestion with verification** — automatically pull the latest ideas from subscribed newsletters, message boards, and email alerts; extract the actionable signal; verify it against live market data; and propose a trade for one-tap approval.
3. **Graduated automation** — start with human approval on everything, then promote trusted signal sources and rules to conditional auto-execution, always behind hard risk limits and a kill switch.

A **mock mode** runs the same pipeline without sending real orders, so every strategy and signal source can be evaluated on "what would have happened" before real money is at stake.

## Run it on your computer

Everything runs fully simulated out of the box — synthetic market feed, local
fill engine, synthesized chart history. No IBKR account or API keys needed.

**Prerequisites** (one-time installs): [Git](https://git-scm.com),
[Docker Desktop](https://www.docker.com/products/docker-desktop/) (running),
[Python 3.11+](https://python.org) (Windows: tick “Add to PATH”),
[Node.js 20+](https://nodejs.org).

**Windows (PowerShell):**

```powershell
git clone https://github.com/ca-vahid/zargar.git
cd zargar
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1   # one time
powershell -ExecutionPolicy Bypass -File scripts\start.ps1   # every time
```

**macOS / Linux:**

```bash
git clone https://github.com/ca-vahid/zargar.git
cd zargar
./scripts/setup.sh     # one time
./scripts/start.sh     # every time
```

Then open **http://127.0.0.1:8420** — one process serves the engine, the API,
and the UI. Stop with Ctrl-C (Postgres keeps running in Docker; data persists).

<details>
<summary>Manual steps / frontend dev mode (hot reload)</summary>

```bash
docker compose up -d                        # database only

cd backend
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp ../.env.example .env                     # optional; defaults work
.venv/bin/python -m zargar.main             # engine + API on :8420

cd ../frontend
npm install
npm run dev                                 # UI on :5173 with hot reload, proxies to :8420
```

Backend tests (needs the Postgres from docker compose, or set
`ZARGAR_TEST_DATABASE_URL`): `cd backend && .venv/bin/python -m pytest`
</details>

### Going beyond simulation

- **IBKR paper/live**: run IB Gateway (e.g. [gnzsnz/ib-gateway-docker](https://github.com/gnzsnz/ib-gateway-docker)),
  `pip install -e ".[ibkr]"`, set `ZARGAR_BROKER=ibkr` + ports in `.env`, and switch
  the trading mode to *paper* in the top bar.
- **Signal extraction**: set `ZARGAR_ANTHROPIC_API_KEY`; then paste newsletter text in
  *Signals → Test the pipeline*, or wire the email webhook.
- **Email ingestion**: deploy [infra/cloudflare-email-worker.js](./infra/cloudflare-email-worker.js)
  on Cloudflare Email Routing and point it at `/api/ingest/email`.
- **Telegram approvals**: set `ZARGAR_TELEGRAM_BOT_TOKEN` + `ZARGAR_TELEGRAM_CHAT_ID`
  and enable the toggle in Settings.

## Documents

- [RESEARCH.md](./RESEARCH.md) — comprehensive technology and architecture research (IBKR API landscape, app architecture, charting, signal ingestion, safety guardrails).
- [DECISIONS.md](./DECISIONS.md) — the owner's confirmed decisions (stack, instruments, hosting, risk defaults) and the build order.
