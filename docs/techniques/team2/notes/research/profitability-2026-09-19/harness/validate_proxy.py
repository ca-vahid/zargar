"""How close is 'the option minute bar at the decision minute' to our ACTUAL fills? Read-only."""
import asyncio, json, sys, pathlib, datetime as dt
import httpx
from zoneinfo import ZoneInfo
from zargar.config import get_config
ET = ZoneInfo("America/New_York")
DATA = pathlib.Path(sys.argv[1])
acts = json.load(open(DATA.parent / "actual.json"))
URL = "https://data.alpaca.markets/v1beta1/options/bars"


async def main():
    c = get_config()
    h = {"APCA-API-KEY-ID": c.alpaca_key_id, "APCA-API-SECRET-KEY": c.alpaca_secret}
    async with httpx.AsyncClient(timeout=60) as http:
        for o, date, hm, side, fill in acts:
            p = DATA / "opt" / f"{o}.json"
            if not p.exists():
                r = await http.get(URL, params={"symbols": o, "timeframe": "1Min", "start": date + "T13:00:00Z", "end": date + "T21:00:00Z", "limit": 10000}, headers=h)
                p.write_text(json.dumps((r.json().get("bars") or {}).get(o) or []))
            rows = {x["t"]: x for x in json.loads(p.read_text())}
            t = dt.datetime.fromisoformat(f"{date}T{hm}:00").replace(tzinfo=ET).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z")
            b = rows.get(t)
            print(o, hm, side, "fill", fill, "bar", None if not b else {k: b[k] for k in ("o", "h", "l", "c", "vw")},
                  "" if not b else f"fill-open={fill - b['o']:+.3f} fill-vw={fill - b['vw']:+.3f}")
asyncio.run(main())
