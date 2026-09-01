# Zargar operations runbook

## Everyday commands

| Task | macOS/Linux | Windows |
|---|---|---|
| First-time setup | `./scripts/setup.sh` | `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1` |
| Start / safe restart | `./scripts/start.sh` → http://127.0.0.1:8420 | `powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Detach` |
| ...without the frontend rebuild | — | add `-NoBuild` (use when the tree doesn't build — a red build must never leave the desk dark) |
| Tail the server log | — | `scripts\logs.ps1` (Ctrl-C detaches, server unaffected) |
| Stop | Ctrl-C (Postgres keeps running in Docker) | close via start.ps1's restart guard — NEVER Stop-Process the :8420 server blind |
| Backend tests | `cd backend && .venv/bin/python -m pytest` | `cd backend; .venv\Scripts\python -m pytest` |
| ...parallel Claude sessions | set `ZARGAR_TEST_DATABASE_URL` to your OWN db on :5433 | same — the shared `zargar_test` is dropped per test |
| Frontend dev (hot reload) | `cd frontend && npm run dev` → :5173 | same |
| Frontend type-check/build | `cd frontend && npm run build` | same |
| Phone-UI gate (every UI change) | — | `$env:ZARGAR_SESSION=(python -m zargar.tools.mint_session).Trim()` from `backend/`, then `cd frontend; npm run mobile-audit` |
| Fire the morning report now | — | `POST /api/desk/morning/send` (scheduler does it at `desk.morning_at`, 08:25 ET) |
| SnapTrade status / re-auth | `python -m zargar.tools.snaptrade_check [--upgrade]` | same |
| IBKR self-test | `cd backend && .venv/bin/python -m zargar.tools.ibkr_check` | `.venv\Scripts\python -m zargar.tools.ibkr_check` |
| Soak report (real-money bar) | `python -m zargar.tools.soak_report` (also nightly at 17:30 ET) | same |
| DB shell | `docker compose exec db psql -U zargar` | same |
| DB backup | `docker compose exec db pg_dump -U zargar zargar > backup.sql` | same |

`start.ps1` refuses to restart while technique runs / armed plans are in flight
(`-Force` asks first); never restart while a knowledge-experiment batch runs.

## Configuration model — two layers

1. **Environment (`backend/.env`, `ZARGAR_*`)** — restart to change. Secrets and
   anything needed before the DB is up. Reference: [.env.example](../.env.example)
   (database URL, broker choice + gateway host/port, Anthropic key + model,
   ingest key, Telegram token/chat, host/port, auth token, frontend dist path,
   sim tick/seed/history).
2. **Runtime settings (Settings page / `PATCH /api/settings`)** — live, no
   restart, journaled. Trading mode, every risk cap, verification thresholds,
   proposal sizing/TTL, account regime, sources registry, all UI preferences.
   Full key list with defaults: `backend/zargar/settings_service.py`.

## Trading modes (top-bar selector = `trading.mode`)

Two modes since v0.3: **Practice | Live**.

| Mode | sim + shadow (research) books | live/paper accounts |
|---|---|---|
| `practice` | local fill engine | blocked (an implicitly-picked live account re-routes to sim) |
| `live` | local fill engine | real venues (SnapTrade today; IBKR when activated) |

Auto execution on a real account additionally needs the per-area allow-live
key (`techniques.tip.allow_live_auto` / `technique.arm.allow_live_auto`) AND,
for armed plans, the per-arm acknowledgement — three independent gates.

The kill switch (HALT button, `/halt` on Telegram, or automatic on the daily
loss limit) blocks **all** submission in every mode, survives restarts, and
must be released explicitly — exits still work (`risk.halt_allows_exits`).
Shadow research books are exempt from the daily-loss halt only (they are the
record; every other check applies).

## Integrations checklist

| Capability | What you set | Where |
|---|---|---|
| Real signal extraction | `ZARGAR_ANTHROPIC_API_KEY` (from [console.anthropic.com](https://console.anthropic.com)) | `.env`, restart |
| IBKR paper/live | Gateway running + logged in, `ZARGAR_BROKER=ibkr`, port `4002` | `.env`, restart — full guide: [IBKR_SETUP.md](./IBKR_SETUP.md) |
| Email ingestion | Deploy [infra/cloudflare-email-worker.js](../infra/cloudflare-email-worker.js); set `ZARGAR_INGEST_KEY` both sides; backend must be reachable from Cloudflare (Tailscale Funnel / cloudflared tunnel) | Cloudflare dashboard + `.env` |
| Telegram approvals | Bot token from @BotFather, your chat id from @userinfobot → `ZARGAR_TELEGRAM_BOT_TOKEN`, `ZARGAR_TELEGRAM_CHAT_ID`; then enable the toggle in Settings | `.env` + Settings |
| Remote access / auth | Google sign-in (`ZARGAR_GOOGLE_ALLOWED_EMAILS`; see [AUTH.md](./AUTH.md)) over Tailscale Serve/Funnel — [MOBILE-ACCESS.md](./MOBILE-ACCESS.md) has the phone handoff; `ZARGAR_AUTH_TOKEN` remains the static-token fallback for scripts (`zargar.tools.mint_session` mints a session for tooling) | `.env` + AUTH.md |

## Troubleshooting

| Symptom | Cause → fix |
|---|---|
| `setup` fails at Docker step | Docker Desktop not running. Start it, re-run. Or run your own Postgres 16 and `SKIP_DOCKER=1` + `ZARGAR_DATABASE_URL`. |
| Backend exits with `ConnectionRefusedError` at startup | Postgres not up yet — `docker compose up -d`, wait a few seconds, retry. |
| UI loads but everything says "waiting for quote…" | WS not connected (red dot top-right). Check the backend console; if `ZARGAR_AUTH_TOKEN` is set, enter it in Settings → API token. |
| Order rejected with a red toast | Working as intended — the toast lists the exact RiskGate checks that failed; raise the caps in Settings → Risk gate if intentional. |
| "no connected execution venue for 'paper'" | Gateway not running/connected. Run the self-test: `python -m zargar.tools.ibkr_check`. |
| Paste-in extraction says "extraction unavailable" | `ZARGAR_ANTHROPIC_API_KEY` not set. |
| Signal shows `verification failed` | Hover the status pill (or open Journal) — each failed check carries its reason (price deviation, spread, grounding…). Thresholds live in Settings → Signals & verification. |
| IBKR session drops daily / weekly 2FA | Expected gateway behavior — see notes in [IBKR_SETUP.md](./IBKR_SETUP.md). Sim keeps running; paper/live orders reject cleanly while disconnected. |
| Chart is blank for a new symbol | First watch of a symbol synthesizes history (sim) or needs a few ticks (IBKR delayed) — give it a few seconds. |
| Windows: `running scripts is disabled` | Use the commands as written (`-ExecutionPolicy Bypass -File …`). |

## Data & reset

* All state lives in the `zargar_pgdata` Docker volume. Full reset:
  `docker compose down -v && docker compose up -d` (new $10k sim portfolio,
  fresh journal).
* The `events` table is the audit trail — never edited or deleted by the app.
  Positions/orders are projections and could be rebuilt from it.
