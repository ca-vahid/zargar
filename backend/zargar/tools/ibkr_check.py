"""IBKR connectivity self-test.

Run after logging into IB Gateway (or TWS) on this machine:

    .venv/bin/python -m zargar.tools.ibkr_check                # gateway paper, port 4002
    .venv/bin/python -m zargar.tools.ibkr_check --port 7497    # TWS paper
    .venv/bin/python -m zargar.tools.ibkr_check --port 4001    # gateway LIVE

Read-only: connects, reports account + market data health, never places orders.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import sys

GREEN = "\033[1;32m✓\033[0m"
RED = "\033[1;31m✗\033[0m"
WARN = "\033[1;33m!\033[0m"


def num(v) -> float:
    try:
        f = float(v)
        return 0.0 if math.isnan(f) else f
    except (TypeError, ValueError):
        return 0.0


async def run(host: str, port: int, client_id: int, symbols: list[str]) -> int:
    from ib_async import IB, Stock

    from ..brokers.ibkr import _contract_for

    ib = IB()
    print(f"Connecting to {host}:{port} (clientId {client_id}) …")
    try:
        await ib.connectAsync(host, port, clientId=client_id, timeout=15)
    except ConnectionRefusedError:
        print(f"{RED} Connection refused — is IB Gateway/TWS running and is {port} the right port?")
        print("   gateway paper=4002  gateway live=4001  TWS paper=7497  TWS live=7496")
        return 1
    except asyncio.TimeoutError:
        print(f"{RED} Connected to the socket but the API handshake timed out.")
        print("   In Gateway/TWS: Configure → API → Settings →")
        print("   ✔ Enable ActiveX and Socket Clients   ✘ Read-Only API")
        print("   and add 127.0.0.1 to Trusted IPs (or accept the popup).")
        return 1
    except Exception as exc:
        print(f"{RED} Connection failed: {exc}")
        return 1

    try:
        print(f"{GREEN} Connected — server version {ib.client.serverVersion()}")
        accounts = ib.managedAccounts()
        print(f"{GREEN} Managed accounts: {', '.join(accounts) or '(none)'}")
        if accounts and accounts[0].startswith("D"):
            print(f"{GREEN} Paper account detected ({accounts[0]})")
        elif accounts:
            print(f"{WARN} This looks like a LIVE account ({accounts[0]}) — be careful.")

        rows = await ib.accountSummaryAsync()
        want = {"NetLiquidation", "TotalCashValue", "BuyingPower", "AvailableFunds"}
        for row in rows:
            if row.tag in want:
                print(f"   {row.tag:>16}: {num(row.value):,.2f} {row.currency}")

        positions = ib.positions()
        print(f"{GREEN} Positions: {len(positions)}")
        open_trades = ib.openTrades()
        print(f"{GREEN} Open orders: {len(open_trades)}")

        # market data (fall back to delayed for unsubscribed instruments)
        ib.reqMarketDataType(3)
        for symbol in symbols:
            contract = _contract_for(symbol, "STK")
            qualified = await ib.qualifyContractsAsync(contract)
            if not qualified:
                print(f"{RED} {symbol}: contract did not qualify")
                continue
            ticker = ib.reqMktData(qualified[0], "", False, False)
            for _ in range(20):  # up to ~6s for first tick
                await asyncio.sleep(0.3)
                if num(ticker.last) or num(ticker.close) or num(ticker.bid):
                    break
            last = num(ticker.last) or num(ticker.close)
            kind = {1: "live", 2: "frozen", 3: "delayed", 4: "delayed-frozen"}.get(
                ticker.marketDataType, "?")
            if last:
                print(f"{GREEN} {symbol}: last {last:,.2f} "
                      f"(bid {num(ticker.bid):,.2f} / ask {num(ticker.ask):,.2f}, {kind} data)")
            else:
                print(f"{WARN} {symbol}: no ticks received — check market data "
                      f"subscriptions/paper-sharing for this username")
            ib.cancelMktData(qualified[0])

        print(f"\n{GREEN} All good. Point Zargar at this gateway:")
        print(f"   backend/.env → ZARGAR_BROKER=ibkr  ZARGAR_IBKR_PORT={port}")
        print("   then restart and switch the top-bar mode to Paper.")
        return 0
    finally:
        ib.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Zargar ↔ IBKR connectivity check")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4002)
    parser.add_argument("--client-id", type=int, default=91)
    parser.add_argument("--symbols", default="AAPL,SHOP.TO",
                        help="comma-separated test symbols")
    args = parser.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    try:
        code = asyncio.run(run(args.host, args.port, args.client_id, symbols))
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    main()
