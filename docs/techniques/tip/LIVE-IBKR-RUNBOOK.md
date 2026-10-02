# Tips on IBKR - real-money go-live runbook (user decision 2026-10-02)

**Decision (user, 2026-10-02):** Tips only, automatic exactly like the Practice book, on the user's IBKR **cash**
account, **$3,000** limit, no other books (Wealthsimple / Webull stay as they are; EM, Team2 and Options Cartel stay on
Practice). Paper first: one clean IBKR-paper session before the gateway is switched to the live account.

**What is known going in (stated to the user):** no Tips cohort has a demonstrated after-cost edge yet (Practice since
09-08: -$1,797 after model cost; the fresh start, three sessions in, is roughly flat). The pre-live gates in
`docs/PRE-LIVE-PROFILE.md` are not met (soak report "still soaking"; no Alpaca-paper overnight pass; no source has
cleared the trust bar). The user chose to go live anyway with a hard cap; this runbook makes that as safe as the app can.

## What the app does on the live book (0.8.58)

| | Practice book | IBKR live / paper book |
|---|---|---|
| Vehicle | shares-first (shorts = puts) | **shares only** (`techniques.tip.live_shares_only`): a short idea or an option/spread vehicle is refused on the record |
| Policy | shares-first, substitution, geometry gate, source-exit mirror | the same, via `techniques.tip.live_parity` (IBKR books only - never SnapTrade) |
| Money | the book's cash | **settled USD** synced from IBKR (`ibkr.portfolio_id`, `ibkr.cash_currency=USD`); CAD is not converted |
| Cap | slot cap 7, glide budget | + **`techniques.tip.live_capital_cap` = 3000**: open tip cost basis never exceeds $3,000 |
| Auto | analyst "take" self-approves | the same on PAPER; on LIVE it also needs `techniques.tip.allow_live_auto`; "skip"/"watch" cards wait (not declined) |
| Daily loss | per-book halt `risk.daily_loss_halt_pct` 3% | same: ~$90/day on $3,000 halts new buys on that book only |
| Stops | venue GTC stop | venue GTC stop at IBKR (regular session only), quantity = held |
| At-level plans | arm on the book | do NOT arm on live (needs `technique.arm.allow_live_auto`, shared with EM - left off); immediate entries only |

IBKR adapter (`brokers/ibkr.py`): executor only (the app's Alpaca/Yahoo feed keeps serving every desk), shares only,
orderRef = our order id, venue rejections reported with IBKR's own error text, fills carry the real commission and a
deterministic exec id (`ibkr:<execId>`, never applied twice), reconnect with backoff, catch-up of open orders and today's
executions after every (re)connect. Tests: `tests/test_ibkr_adapter.py`.

## The user's steps (only you can do these)

1. **IB Gateway (paper first):** Launch IB Gateway (stable) -> IB API -> **Paper Trading** -> log in with the paper
   (DU...) user + 2FA. Configure -> Settings -> API -> Settings: *Enable ActiveX and Socket Clients* ON, *Read-Only API*
   OFF, socket port **4002**, trusted IP 127.0.0.1, *Download open orders on connection* ON (`docs/IBKR_SETUP.md` §3).
2. **Keep the gateway logged in** during market hours (IBKR logs gateways out daily; enable auto-restart in the gateway
   settings).
3. **Live account, before the live switch:** confirm it is a CASH account; **convert CAD to USD inside IBKR** (the app
   never converts currency); the book spends settled USD only.
4. **Memory:** keep at least ~3 GB free on this machine during market hours (the app froze twice this week below 1 GB).

## Monday 10-05 - paper session (this desk, after the gateway is logged in)

1. Confirm the connection: `/api/health` -> `ibkrConnected: true`; journal `BrokerConnected` (accounts: DU...).
2. Create the book `Tips IBKR Paper` (kind `paper`, venue ibkr) and set, through the journaled `PATCH /api/settings`:
   `ibkr.portfolio_id` = that book; `techniques.tip.live_parity` = true; `techniques.tip.live_capital_cap` = 3000;
   `techniques.tip.budget_per_tip` = 500 (PRE-LIVE-PROFILE); `techniques.tip.default_portfolio` = that book.
3. **`trading.mode` = `live`** (practice mode routes only to simulated books; a paper book needs `live`) - **the user's
   explicit go is required for this switch.** It does not let any desk auto-trade a live account: those need their own
   `allow_live_auto` switches, all off.
4. Watch the session: every entry's IBKR fill + commission, the venue GTC stop appearing in the gateway with the held
   quantity, a stop/target/mirror exit filling, the account sync matching the gateway, no duplicate fills after a
   gateway reconnect (pull the network for 30 s once).

**Paper passes when:** at least one entry and one exit filled at IBKR with matching quantities and commissions; the
venue stop rested at IBKR for the held quantity; the book's cash/positions equal the gateway's; no stuck "accepted"
order; the kill switch, pressed once, blocks a new entry.

## Go-live (after a passing paper session; the user says "go")

1. The user logs IB Gateway into the **live** account (port **4001**); this desk sets `ZARGAR_IBKR_PORT=4001` in
   `backend/.env` and restarts through ZargarRestart (market closed).
2. Create `Tips IBKR Live` (kind `live`); `ibkr.portfolio_id` and `techniques.tip.default_portfolio` -> it.
3. **`techniques.tip.allow_live_auto` = true** - the user's explicit go. The Practice book stops receiving Tips ideas.
4. First day: watch every fill; any `needsAttention`, an unexplained fill or a stuck order -> kill switch, then explain.

## Rollback (any time)

- Stop new live entries now: the kill switch (HALT) or `techniques.tip.allow_live_auto` = false. Exits keep running
  (reduce-only exits are exempt from the mode gate and the halt).
- Back to Practice: `techniques.tip.default_portfolio` -> `Tips Practice 09-28`, `trading.mode` -> practice.
- Disconnect IBKR entirely: `ZARGAR_BROKER=sim` + restart (open IBKR stops stay resting at IBKR - manage them in IBKR).
