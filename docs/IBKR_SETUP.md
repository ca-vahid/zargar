# Connecting Zargar to your IBKR account

Zargar talks to IBKR through **IB Gateway** (or TWS) running on the same
machine. You log into the gateway yourself with your IBKR credentials — Zargar
never sees or stores them; it only connects to the gateway's local API socket.

Start with the **paper account**. Do not point Zargar at live until paper has
worked for a while.

## 1. Get your paper trading account

1. Log in to [IBKR Client Portal](https://www.interactivebrokers.com/portal).
2. Head icon (top right) → **Settings** → **Account Settings** → in the
   *Configuration* section find **Paper Trading Account** → request/open it.
3. Note the paper username (usually your live username with a `d`/`D` prefixed
   or appended) and set its password there.
4. On the same page, enable **“Share real-time market data with paper trading
   account”** if offered — otherwise paper only gets delayed data.
   (Live and paper can’t consume the same data feed at the same moment.)

## 2. Install and log in to IB Gateway

1. Download **IB Gateway** (stable) from IBKR:
   <https://www.interactivebrokers.com/en/trading/ibgateway-stable.php>
2. Install, launch, choose **IB API** (not FIX), select **Paper Trading**,
   and log in with the **paper** username/password. Complete 2FA if prompted.

## 3. Enable API access in the gateway

In IB Gateway: **Configure → Settings → API → Settings**

| Setting | Value |
|---|---|
| Enable ActiveX and Socket Clients | ✔ checked |
| Read-Only API | ✘ **unchecked** (Zargar must place orders) |
| Socket port | `4002` (gateway paper default) |
| Trusted IPs | add `127.0.0.1` |
| Download open orders on connection | ✔ checked |

Click OK. (Ports: gateway paper `4002`, gateway live `4001`, TWS paper `7497`,
TWS live `7496`.)

## 4. Verify with the self-test

From the `zargar/backend` directory:

```bash
# install the IBKR extra once
.venv/bin/pip install -e ".[ibkr]"          # Windows: .venv\Scripts\pip install -e ".[ibkr]"

# run the read-only connectivity check
.venv/bin/python -m zargar.tools.ibkr_check                 # Windows: .venv\Scripts\python -m zargar.tools.ibkr_check
```

Expected output: server version, your `D…` paper account id, account balances,
and delayed/live quotes for AAPL and SHOP.TO. The tool never places orders,
and it prints a targeted fix for every common failure (wrong port, API not
enabled, no market data).

## 5. Point Zargar at the gateway

Edit `backend/.env`:

```
ZARGAR_BROKER=ibkr
ZARGAR_IBKR_HOST=127.0.0.1
ZARGAR_IBKR_PORT=4002
```

Restart Zargar (`scripts/start.sh` / `scripts\start.ps1`), then switch the
top-bar mode from **Simulation** to **Paper (IBKR)**. Orders placed on the
*Live (IBKR)* portfolio remain blocked until you explicitly switch the mode to
LIVE — and the RiskGate still applies everywhere.

## Notes & gotchas

- **One login per username.** Logging into Client Portal or mobile with the
  same username kicks the gateway session. Long-term: create a second username
  for the API (Client Portal → Settings → Users & Access Rights).
- **Daily restart.** IB Gateway restarts daily (configure the auto-restart
  time in *Configure → Lock and Exit*); with auto-restart you re-enter 2FA
  about once a week. Zargar’s sim portfolios keep working while the gateway is
  down; paper/live orders are rejected with a clear “no connected venue” error.
- **Canadian symbols** use the `.TO` suffix in Zargar (e.g. `SHOP.TO`,
  `TD.TO`); TSX Venture uses `.V`.
- **Market data:** without subscriptions you get delayed quotes (fine for
  testing). For real-time NBBO on US stocks subscribe to the non-professional
  US Securities Snapshot and Futures Value Bundle in Client Portal → Settings →
  Market Data Subscriptions; add Canadian bundles for TSX.
