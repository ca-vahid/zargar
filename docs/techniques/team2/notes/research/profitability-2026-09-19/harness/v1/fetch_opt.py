"""Read-only: real option 1m trade bars (OPRA prints aggregated by Alpaca) for every contract a replay file references.
usage: fetch_opt.py DATA replay.json [replay2.json ...]   -> DATA/opt/<OCC>.json (cached)"""
import asyncio, json, sys, pathlib, datetime as dt
import httpx
from zargar.config import get_config
DATA = pathlib.Path(sys.argv[1])
(DATA / "opt").mkdir(exist_ok=True)
URL = "https://data.alpaca.markets/v1beta1/options/bars"


def occ(sym, date, call, strike):
    d = dt.date.fromisoformat(date)
    return f"{sym}{d:%y%m%d}{'C' if call else 'P'}{int(round(strike * 1000)):08d}"


need = {}
for f in sys.argv[2:]:
    for r in json.load(open(f))["rows"]:
        for t in r.get("trades") or []:
            need[occ(r["symbol"], r["date"], t["call"], t["strike"])] = r["date"]


async def main():
    c = get_config()
    h = {"APCA-API-KEY-ID": c.alpaca_key_id, "APCA-API-SECRET-KEY": c.alpaca_secret}
    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=60) as http:
        async def one(o, date):
            p = DATA / "opt" / f"{o}.json"
            if p.exists():
                return
            async with sem:
                rows, token = [], None
                while True:
                    q = {"symbols": o, "timeframe": "1Min", "start": date + "T13:00:00Z", "end": date + "T21:00:00Z", "limit": 10000}
                    if token:
                        q["page_token"] = token
                    for attempt in range(4):
                        r = await http.get(URL, params=q, headers=h)
                        if r.status_code == 429:
                            await asyncio.sleep(2 + attempt * 2)
                            continue
                        break
                    if r.status_code >= 400:
                        print("ERR", o, r.status_code, r.text[:100])
                        return
                    d = r.json()
                    rows.extend((d.get("bars") or {}).get(o) or [])
                    token = d.get("next_page_token")
                    if not token:
                        break
                p.write_text(json.dumps(rows))
        await asyncio.gather(*(one(o, d) for o, d in need.items()))
    got = [json.loads((DATA / "opt" / f"{o}.json").read_text()) for o in need if (DATA / "opt" / f"{o}.json").exists()]
    print("contracts", len(need), "fetched", len(got), "empty", sum(1 for g in got if not g))


asyncio.run(main())
