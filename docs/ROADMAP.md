# Zargar — plan & next steps

## Where things stand (v0.1, on this branch)

| Area | Status |
|---|---|
| Engine: event journal, settings service, pub/sub, Postgres | ✅ done, tested |
| Sim market + local fill engine (mock ladder rungs 1–2) | ✅ done, tested |
| RiskGate + kill switch + daily-loss auto-halt | ✅ done, tested |
| Manual trading UI (chart, ticket, blotter) | ✅ done, verified E2E |
| Signal pipeline: email/manual → Claude extraction → grounding → verification → proposals | ✅ done, tested (extraction stubbed in CI; real calls need API key) |
| Shadow portfolios per source (ladder rung 3) | ✅ done, tested |
| Approvals: in-app + Telegram bot | ✅ built (Telegram formatting/commands unit-testable; live bot needs your token) |
| IBKR adapter (ib_async 2.1.0) + connectivity self-test + setup guide | ✅ built, API-surface-verified — **not yet run against a real gateway** |
| Rich settings UI, watchlists, sources registry, themes | ✅ done |
| Docs: architecture, operations, IBKR setup, this roadmap | ✅ done |

## Your next steps (in order — each unlocks the next)

1. **Run it locally** (15 min): follow the README *Run it on your computer*
   section. Play in Simulation: place orders, trip the risk gate, halt/resume.
2. **Add your Anthropic API key** (5 min): `ZARGAR_ANTHROPIC_API_KEY` in
   `backend/.env`, restart, then paste a real newsletter into
   *Signals → Test the pipeline*. Watch extraction → verification → proposal →
   shadow portfolio. Tune verification thresholds in Settings to your sources.
3. **Request your IBKR paper account** (10 min + ~24 h wait):
   [docs/IBKR_SETUP.md](./IBKR_SETUP.md) — do this early, provisioning takes a
   day. Meanwhile confirm in Client Portal whether your account is IBKR Canada
   or IBKR LLC and margin vs cash → set *Settings → Account regime*.
4. **Connect the gateway** (30 min): install IB Gateway, log in (paper), run
   `python -m zargar.tools.ibkr_check`, flip `.env` to `ZARGAR_BROKER=ibkr`,
   switch mode to *Paper*, and place a small paper order end-to-end.
5. **Telegram approvals** (10 min): bot via @BotFather → token + your chat id
   into `.env`, enable the toggle in Settings, approve a proposal from your phone.
6. **Email ingestion** (1–2 h): pick a subdomain/address on your personal
   domain → Cloudflare Email Routing → deploy
   [infra/cloudflare-email-worker.js](../infra/cloudflare-email-worker.js) →
   expose the backend to Cloudflare (cloudflared tunnel or Tailscale Funnel)
   with `ZARGAR_INGEST_KEY` set → re-subscribe one newsletter as a pilot.
   Register the sender in *Settings → Signal sources*.
7. **Marinate** (2–4 weeks): trade manually in sim/paper, approve/reject real
   proposals, let shadow portfolios accumulate per-source track records.
   Everything is journaled for later analysis.

## Development roadmap (what to build next)

### v0.2 — Trust & tooling (highest value next)
- **Per-source scorecards** from shadow-portfolio history: win rate, avg
  return, slippage vs alert price, max drawdown; surfaced on the Portfolios
  and Signals pages. This is the evidence base for automation.
- **Rules-gated auto-execution**: deterministic policy per source
  (`auto if source trusted AND confidence == explicit_call AND notional ≤ cap
  AND spread/earnings checks pass`), post-trade Telegram veto ("Executed —
  tap to flatten"), all behind the existing `signals.auto_execute_enabled`
  master switch. The RiskGate already applies to auto orders.
- **DB migrations** (alembic) before any schema change — today the schema is
  `create_all`-only.

### v0.3 — Options
- Synthetic option chain in the sim + chain browser UI (expiry/strike grid),
  single-leg tickets; IBKR option contracts (`Option(...)`) in the adapter.
  Risk rules (premium cap, no naked shorts) and the 100× multiplier already exist.

### v0.4 — Account regime guards
- Day-trade round-trip counter with warnings (until IBKR's post-2026 PDT
  policy is confirmed for your account's domicile).
- CRA superficial-loss / IRS wash-sale flagging: warn on loss-realizing sale +
  re-entry within 30/31 days (data is already in `executions`).

### v0.5 — Always-on
- Move the stack to a small VPS or home server (systemd units provided),
  Tailscale + `ZARGAR_AUTH_TOKEN` everywhere, dockerized IB Gateway
  (gnzsnz/ib-gateway-docker) with weekly-2FA auto-restart, Litestream-style
  Postgres backups. Until then, ingestion/automation only run while your PC is on.

### Backlog / ideas
- Verification upgrades: earnings-calendar proximity (Finnhub), multi-source
  corroboration scoring, ADV-based sizing cap.
- Order chart overlays (entries/exits/brackets drawn on the price chart) and
  chart-click limit placement.
- Position-detail drawer with per-trade history; P&L calendar.
- Native notifications (ntfy) as a Telegram alternative.
- Journal export (CSV) for taxes.

## Known limitations (honest list)

- IBKR adapter has been verified against the ib_async 2.1.0 API surface but
  **not yet exercised against a live gateway** — expect to shake out small
  issues on first paper connect (the self-test is the tool for that).
- Trailing stops are simulated/typed but not exposed in the UI ticket.
- Sim market runs 24/7 with synthetic prices — great for development, not for
  judging strategy P&L. Paper via IBKR is the realism rung.
- Single-user by design; auth is a single bearer token.
- No schema migrations yet — wipe (`docker compose down -v`) or hand-migrate
  on model changes until alembic lands.

## Continuing with Claude Code

The repo carries a `CLAUDE.md` with build/test commands, architecture
pointers, and project conventions — open the repo in Claude Code on your
machine and it picks up all context automatically. Good first prompts:
*"build the per-source scorecards from v0.2 of docs/ROADMAP.md"* or
*"add alembic migrations"*.
