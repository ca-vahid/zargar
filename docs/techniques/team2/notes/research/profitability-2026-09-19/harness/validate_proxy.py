"""Reconcile the pricing proxy with the desk's ACTUAL Practice fills (v2). Read-only. One row per MARKET leg: the same
contract/side/second filled in several books is one leg (the books are not independent cases).
usage: validate_proxy.py DATA fills.json OUT.json      (fills.json = harness/actual_fills.json, exported from `executions`)"""
import json, sys, pathlib, datetime as dt, statistics as st
import httpx
from zargar.config import get_config
DATA = pathlib.Path(sys.argv[1]); fills = json.load(open(sys.argv[2])); OUT = sys.argv[3]
MIN = 60_000
BARS = "https://data.alpaca.markets/v1beta1/options/bars"
TRADES = "https://data.alpaca.markets/v1beta1/options/trades"
c = get_config()
H = {"APCA-API-KEY-ID": c.alpaca_key_id, "APCA-API-SECRET-KEY": c.alpaca_secret}
http = httpx.Client(timeout=60)


def ms(iso):
    s = iso.replace("Z", "+00:00")
    if "." in s:
        head, tail = s.split(".", 1)
        frac, tz = tail[:-6], tail[-6:]
        s = f"{head}.{frac[:6]:0<6}{tz}"
    return int(dt.datetime.fromisoformat(s).timestamp() * 1000)


def iso(t):
    return dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def bars(o, date):
    p = DATA / "opt" / f"{o}.json"
    if not p.exists():
        r = http.get(BARS, params={"symbols": o, "timeframe": "1Min", "start": date + "T13:00:00Z", "end": date + "T21:00:00Z", "limit": 10000}, headers=H)
        p.write_text(json.dumps((r.json().get("bars") or {}).get(o) or []))
    return {ms(b["t"]): b for b in json.loads(p.read_text())}


def ticks(o, t):
    p = DATA / "ticks" / f"{o}_{t}.json"
    p.parent.mkdir(exist_ok=True)
    if not p.exists():
        r = http.get(TRADES, params={"symbols": o, "start": iso(t - 120_000), "end": iso(t + 120_000), "limit": 10000}, headers=H)
        p.write_text(json.dumps((r.json().get("trades") or {}).get(o) or []))
    return [(ms(x["t"]), float(x["p"]), int(x.get("s") or 0)) for x in json.loads(p.read_text())]


rows = []
for f in fills:
    o, t, side, px = f["occ"], f["tsMs"], f["side"], f["price"]
    b = bars(o, f["date"])
    T = (t // (2 * MIN)) * (2 * MIN) if f["decision"] == "bar_close" else None
    proxy = lag = obs = None
    if T is not None:
        for k in range(5):
            if T + k * MIN in b:
                proxy, lag = float(b[T + k * MIN]["o"]), k
                break
        for k in (1, 2):
            if T - k * MIN in b:
                obs = float(b[T - k * MIN]["c"])
                break
    tk = ticks(o, t)
    before = [x for x in tk if x[0] <= t]
    after = [x for x in tk if x[0] > t]
    rows.append({**f, "T": T, "proxyExec": proxy, "proxyLagMin": lag, "observedBeforeT": obs,
                 "signedErr": None if proxy is None else round(proxy - px, 4),
                 "adverseErr": None if proxy is None else round((proxy - px) if side == "BUY" else (px - proxy), 4),
                 "lastPrintBeforeFill": before[-1][1] if before else None, "secBefore": round((t - before[-1][0]) / 1000, 1) if before else None,
                 "firstPrintAfterFill": after[0][1] if after else None, "secAfter": round((after[0][0] - t) / 1000, 1) if after else None,
                 "printsWithin2min": len(tk), "fillSecAfterT": None if T is None else round((t - T) / 1000, 1)})
json.dump(rows, open(OUT, "w"), indent=1)


def summ(name, rs):
    e = [r["signedErr"] for r in rs if r["signedErr"] is not None]
    a = [r["adverseErr"] for r in rs if r["adverseErr"] is not None]
    if not e:
        print(f"{name}: no priced legs"); return
    print(f"{name}: legs {len(rs)} priced {len(e)} | signed proxy-fill mean {st.mean(e):+.4f} median {st.median(e):+.4f} min {min(e):+.3f} max {max(e):+.3f} | "
          f"abs mean {st.mean(abs(x) for x in e):.4f} max {max(abs(x) for x in e):.3f} | adverse-to-us mean {st.mean(a):+.4f} (positive = proxy WORSE than the fill)")


for r in rows:
    print(r["date"], r["occ"], r["side"], "qty", r["qty"], "books", r["books"], "fill", r["price"], "at +%ss" % r["fillSecAfterT"], "| proxy", r["proxyExec"],
          "lag", r["proxyLagMin"], "err", r["signedErr"], "| tick before", r["lastPrintBeforeFill"], r["secBefore"], "s; after", r["firstPrintAfterFill"], r["secAfter"], "s")
summ("ALL bar-close legs", [r for r in rows if r["T"] is not None])
summ("BUY (entries)", [r for r in rows if r["T"] is not None and r["side"] == "BUY"])
summ("SELL (exits)", [r for r in rows if r["T"] is not None and r["side"] == "SELL"])
summ("cohort v2 only (from 2026-09-11)", [r for r in rows if r["T"] is not None and r["date"] >= "2026-09-11"])
print("independent market opportunities (date x symbol):", len({(r["date"], r["occ"][:3]) for r in rows}), "| round trips:", len(rows) // 2, "| market legs:", len(rows),
      "| book fills behind them:", sum(r["books"] for r in rows))
