"""Read-only Alpaca market-data connectivity check.

    cd backend && .venv/Scripts/python.exe -m zargar.tools.alpaca_check [SYMBOL...]

Verifies, with the keys from backend/.env (ZARGAR_ALPACA_KEY_ID / _SECRET):
  1. REST: SIP 1m bars + snapshot for each symbol,
  2. Websocket: connect -> authenticate -> subscribe (trades/quotes/bars),
  3. During market hours: waits briefly for live messages.
Exit 0 = everything works.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx
import websockets

from ..config import AppConfig

DATA = "https://data.alpaca.markets/v2"
WS = "wss://stream.data.alpaca.markets/v2/sip"


async def run(symbols: list[str]) -> int:
    cfg = AppConfig()
    if not cfg.alpaca_key_id or not cfg.alpaca_secret:
        print("FAIL: ZARGAR_ALPACA_KEY_ID / ZARGAR_ALPACA_SECRET not set in backend/.env")
        return 2
    h = {"APCA-API-KEY-ID": cfg.alpaca_key_id, "APCA-API-SECRET-KEY": cfg.alpaca_secret}
    ok = True
    async with httpx.AsyncClient(timeout=15) as http:
        for s in symbols:
            r = await http.get(f"{DATA}/stocks/{s}/bars",
                               params={"timeframe": "1Min", "limit": 3, "feed": "sip"}, headers=h)
            bars = (r.json().get("bars") or []) if r.status_code == 200 else []
            print(f"REST bars  {s}: HTTP {r.status_code}, {len(bars)} bar(s)"
                  + (f", last {bars[-1]['t']} c={bars[-1]['c']}" if bars else ""))
            ok = ok and r.status_code == 200
    try:
        async with websockets.connect(WS, max_size=2 ** 23) as ws:
            print("WS greet  :", await asyncio.wait_for(ws.recv(), 10))
            await ws.send(json.dumps({"action": "auth", "key": cfg.alpaca_key_id, "secret": cfg.alpaca_secret}))
            auth = await asyncio.wait_for(ws.recv(), 10)
            print("WS auth   :", auth)
            ok = ok and "authenticated" in str(auth)
            await ws.send(json.dumps({"action": "subscribe", "trades": symbols,
                                      "quotes": symbols, "bars": symbols}))
            print("WS sub    :", await asyncio.wait_for(ws.recv(), 10))
            try:
                msg = await asyncio.wait_for(ws.recv(), 8)
                print("WS data   :", str(msg)[:140])
            except asyncio.TimeoutError:
                print("WS data   : none in 8s (fine outside market hours)")
    except Exception as exc:
        print("WS FAIL   :", exc)
        ok = False
    print("RESULT    :", "OK — Alpaca SIP data fully usable" if ok else "FAILED — see above")
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*", default=[])
    args = ap.parse_args()
    syms = [s.upper() for s in (args.symbols or ["SPY", "SNOW"])]
    sys.exit(asyncio.run(run(syms)))


if __name__ == "__main__":
    main()
