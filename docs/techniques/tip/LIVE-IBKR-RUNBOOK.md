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
| At-level plans | arm on the book | arm in the bound book when its binding says `armAtLevel` (PAPER: its own `allowLiveAuto`; LIVE: also the master `techniques.tip.allow_live_auto`) |
| Both at once (0.8.59, W6) | - | **`techniques.tip.books`**: the analyst appraises each tip ONCE and every bound book gets its own card, sized by its own budget and caps. Practice keeps trading while paper/live trade. The top-bar Practice/LIVE switch is only a VIEW; real-order routing is the separate "Real orders on/off" switch beside HALT (`trading.mode`). |

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
   `ibkr.portfolio_id` = that book; `ibkr.cash_currency` = CAD (the paper account holds CAD; live will be USD);
   `techniques.tip.live_parity` = true; and bind BOTH books (Settings -> Tips technique -> Books):
   ```json
   "techniques.tip.books": [
     {"portfolioId": "<Tips Practice 09-28>", "role": "practice", "primary": true},
     {"portfolioId": "<Tips IBKR Paper>", "role": "live", "enabled": true, "allowLiveAuto": true,
      "budgetPerTip": 500, "capitalCap": 3000, "maxOpenPositions": 6, "armAtLevel": true}
   ]
   ```
   `techniques.tip.default_portfolio` stays on the Practice book (legacy fallback). Practice keeps its own budget.
3. **Real orders ON** (`trading.mode` = `live`; practice routing sends nothing to a paper/live book) - **the user's
   explicit go is required for this switch.** It does not let any desk auto-trade a live account: those need their own
   `allow_live_auto` switches, all off. The view switch can stay on Practice or LIVE - it changes nothing.
4. Watch the session: every entry's IBKR fill + commission, the venue GTC stop appearing in the gateway with the held
   quantity, a stop/target/mirror exit filling, the account sync matching the gateway, no duplicate fills after a
   gateway reconnect (pull the network for 30 s once).

**Paper passes when:** at least one entry and one exit filled at IBKR with matching quantities and commissions; the
venue stop rested at IBKR for the held quantity; the book's cash/positions equal the gateway's; no stuck "accepted"
order; the kill switch, pressed once, blocks a new entry.

## Paper week 2026-10-05..09 (user decision 10-05: paper all week, real money from the week of 10-12)

**10-05 result: PASSED** every criterion above - 5 IBKR fills (AAPL 5, CYRX 40, TSLA 1, MGM 8 bought; TSLA sold
381.39 on the analyst's mirror of the source's trim), venue GTC stops resting for every held quantity, the account sync
matching the gateway, no stuck order. Bugs it found, all fixed and deployed the same day:
- 0.9.02: the gateway lost IBKR's servers (notice 1100) and orders sat "submitted" - a lost server link is now
  "not connected" (orders refused visibly, `IbkrLinkLost` alert) until 1101/1102.
- 0.9.03: IBKR rejected bracket children priced off the tick (error 110) - prices round to the tick in the safe direction.
- 0.9.04: two positions (CYRX, MGM) adopted while their bracket children were still cancelling got NO venue stop - the
  watch loop now re-places a missing venue stop (re-placed by hand on 10-05 before the fix shipped).
- 0.9.06/0.9.07/0.9.08: 12-181 s event-loop freezes - armed-plan persist throttle, a real DB connection pool (no TLS
  to the local DB), stale exits cancelled before replacement, above-normal process priority.
- 0.9.09: Portfolios/Ledger in one display currency; IBKR shown like the other brokers; paper never added to real money.

**Before the live switch (the user):** the paper account bought US stocks with a CAD balance and IBKR simply went
NEGATIVE US$2,619.87 against the C$10,000 (a paper account allows it; `ibkr.convert_currencies=true` let the book see
the CAD). A real CASH account will not: **convert CAD to USD inside IBKR (or deposit USD)** before the first live
session - the live config below turns `convert_currencies` off, so only USD is spendable.

## Go-live (after a passing paper session; the user says "go")

1. The user logs IB Gateway into the **live** account (port **4001**); this desk sets `ZARGAR_IBKR_PORT=4001` in
   `backend/.env` and restarts through ZargarRestart (market closed).
2. Create `Tips IBKR Live` (kind `live`); `ibkr.portfolio_id` -> it; `ibkr.cash_currency` = USD; in the books list
   replace the paper binding with the live one (same caps; `allowLiveAuto` true on the binding).
3. **`techniques.tip.allow_live_auto` = true** - the user's explicit go (the master switch a kind=live account needs on
   top of its binding). **The Practice book keeps receiving every Tips idea** - same method, both books.
4. First day: watch every fill; any `needsAttention`, an unexplained fill or a stuck order -> kill switch, then explain.

## Live config (V1.8, Tips v0.9 - 2026-10-05)

Applied by this desk through the journaled `PATCH /api/settings` once the user says "go" (the market closed). The
numbers below are the v0.9 plan's; the user may pick inside the ranges.

1. **The live book:** create `Tips IBKR Live` with **kind `live`** (never `paper` - a paper-kind book skips the master
   live-auto switch and the real-money confirm dialog), base currency USD. Archive `Tips IBKR Paper` and `Live (IBKR)`
   (2d173f44) so no order can route to the real account from them.
2. **Sync + cash:** `ibkr.portfolio_id` = the live book; `ibkr.cash_currency` = `USD`; `ibkr.convert_currencies` =
   `false` (only USD is spendable - convert CAD to USD inside IBKR before the open); `ibkr.cash_account` = `true`
   (the good-faith guard applies; default).
3. **Per-book risk limits** (`risk.book_overrides`, keyed by the live book's id - Practice and the other desks keep the
   global numbers):
   ```json
   "risk.book_overrides": {"<Tips IBKR Live id>": {
     "risk.max_position_notional": 3500, "risk.daily_loss_halt_pct": 4, "risk.max_position_pct": 35}}
   ```
4. **`risk.require_market_hours` = `true`** (applies to live/paper books only; exits are exempt) - no pre-market DAY
   limits queued into the open.
5. **The binding** (`techniques.tip.books`): Practice stays primary; REMOVE the paper binding (two bindings on one
   gateway = double orders) and add the live one:
   ```json
   {"portfolioId": "<Tips IBKR Live id>", "role": "live", "enabled": true, "allowLiveAuto": true,
    "capitalCap": 3000, "maxOpenPositions": 3, "budgetPerTip": 900, "riskPct": 0.75, "armAtLevel": false}
   ```
   Ranges: `maxOpenPositions` 3-4, `budgetPerTip` 900-1000, `riskPct` 0.75-1. **`armAtLevel` may be turned on** once
   v0.9 V1.1 is deployed: an at-level fire on this book is then sized by the book's own budget / cap (incl. resting
   entries) / slots / risk % and trades shares only (journaled `TipArmedFireSized`); before V1.1 keep it `false`.
6. **Last:** `techniques.tip.allow_live_auto` = `true` - only on the user's explicit go, after steps 1-5 read back
   correctly from `GET /api/settings`.

What V1 changes underneath (for the first-day watch): a partially filled entry gets its stop at once
(`TipPartialFillAdopted`); a failed hand-off marks the card failed (`ProposalHandoffFailed`); a replacement stop waits
up to 5 s for IBKR's cancel confirmation (alert "cancel not confirmed" if it does not come); a reconnect replays fills
before the account sync; the cash right after a buy excludes the buy until IBKR's summary shows it
(`unreflectedBuys`); a trim/target/time exit of shares bought today with unsettled sale proceeds waits for the next
session (`TipGoodFaithDeferred`) - stops always go (`TipGoodFaithStopSent`).

## Rollback (any time)

- Stop new live entries now: the kill switch (HALT) or `techniques.tip.allow_live_auto` = false. Exits keep running
  (reduce-only exits are exempt from the mode gate and the halt).
- Back to Practice only: disable the live binding (Settings -> Tips books -> off) or "Real orders off"
  (`trading.mode` -> practice). Practice never stops.
- Disconnect IBKR entirely: `ZARGAR_BROKER=sim` + restart (open IBKR stops stay resting at IBKR - manage them in IBKR).
