"""Read-only: fetch SIP 1m bars (extended hours included) for SPY/QQQ/IWM from Alpaca into local JSON. No DB, no runtime."""
import asyncio, json, sys, pathlib, datetime as dt
import httpx
from zargar.config import get_config
OUT = pathlib.Path(sys.argv[1]); START, END = sys.argv[2], sys.argv[3]
URL = "https://data.alpaca.markets/v2/stocks/bars"
async def main():
    c = get_config()
    h = {"APCA-API-KEY-ID": c.alpaca_key_id, "APCA-API-SECRET-KEY": c.alpaca_secret}
    async with httpx.AsyncClient(timeout=60) as http:
        for sym in ("SPY", "QQQ", "IWM"):
            rows, token = [], None
            while True:
                p = {"symbols": sym, "timeframe": "1Min", "start": START + "T00:00:00Z", "end": END + "T23:59:59Z",
                     "limit": 10000, "adjustment": "raw", "feed": "sip"}
                if token: p["page_token"] = token
                r = await http.get(URL, params=p, headers=h)
                r.raise_for_status()
                d = r.json()
                rows.extend((d.get("bars") or {}).get(sym) or [])
                token = d.get("next_page_token")
                if not token: break
            (OUT / f"{sym}_1m.json").write_text(json.dumps(rows))
            print(sym, len(rows), rows[0]["t"], rows[-1]["t"])
asyncio.run(main())
