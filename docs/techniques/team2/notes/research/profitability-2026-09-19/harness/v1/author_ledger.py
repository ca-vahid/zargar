"""Opportunity ledger vs the author's DOCUMENTED trades inside the data window. Real prints only.
usage: author_ledger.py DATA replay.json"""
import json, sys, pathlib, datetime as dt, collections
import httpx
from zoneinfo import ZoneInfo
from zargar.config import get_config
ET = ZoneInfo("America/New_York")
DATA = pathlib.Path(sys.argv[1]); rep = json.load(open(sys.argv[2]))
URL = "https://data.alpaca.markets/v1beta1/options/bars"
# (date, symbol, call?, strike, entry HH:MM or None, exit HH:MM or None, what he documented)
AUTHOR = [
    ("2026-07-14", "SPY", True, 624, None, None, "SPY 624C @0.50, EMA13 pullbacks after PMH break, adds; exit n/f"),
    ("2026-09-01", "IWM", False, 292, None, "12:34", "IWM 292P card +474%, sold 12:34; entry time n/f"),
    ("2026-09-03", "SPY", True, 770, "11:00", "11:19", "third attempt SPY 770C ~11:00, sold 11:19 'over 500%'; two earlier attempts stopped"),
    ("2026-09-09", "IWM", False, 293, "09:41", None, "IWM 293P at the 09:41 retest of 3-day support; +141.77%"),
    ("2026-09-10", "IWM", False, 288, "14:00", None, "IWM 288P ~14:00 after ~5h wait; +85/+100%"),
    ("2026-09-11", "SPY", True, 768, "09:46", None, "SPY 768C at the 09:46 2m close; +50% trim, runners stopped; +$801"),
    ("2026-09-18", "IWM", False, 283, "09:48", None, "CHART ONLY (no execution): EMA13 pullback ~09:46-09:52; contract is OUR 283P for reference"),
]


def occ(sym, date, call, strike):
    x = dt.date.fromisoformat(date)
    return f"{sym}{x:%y%m%d}{'C' if call else 'P'}{int(round(strike * 1000)):08d}"


def ms(date, hm):
    return int(dt.datetime.fromisoformat(f"{date}T{hm}:00").replace(tzinfo=ET).timestamp() * 1000)


def hm(t):
    return dt.datetime.fromtimestamp(t / 1000, ET).strftime("%H:%M")


c = get_config()
H = {"APCA-API-KEY-ID": c.alpaca_key_id, "APCA-API-SECRET-KEY": c.alpaca_secret}
http = httpx.Client(timeout=60)
rows = {(r["date"], r["symbol"]): r for r in rep["rows"] if r["status"] == "ok"}
for date, sym, call, k, t_in, t_out, doc in AUTHOR:
    o = occ(sym, date, call, k)
    p = DATA / "opt" / f"{o}.json"
    if not p.exists():
        r = http.get(URL, params={"symbols": o, "timeframe": "1Min", "start": date + "T13:00:00Z", "end": date + "T21:00:00Z", "limit": 10000}, headers=H)
        p.write_text(json.dumps((r.json().get("bars") or {}).get(o) or []))
    bars = {int(dt.datetime.fromisoformat(b["t"].replace("Z", "+00:00")).timestamp() * 1000): b for b in json.loads(p.read_text())}
    print(f"\n=== {date} {sym}  AUTHOR: {doc}")
    if t_in:
        e = ms(date, t_in)
        b0 = next((bars[e + i * 60000] for i in range(3) if e + i * 60000 in bars), None)
        if b0:
            end = ms(date, t_out) if t_out else ms(date, "15:45")
            after = [(t, b) for t, b in sorted(bars.items()) if e <= t <= end]
            hi_t, hi = max(after, key=lambda x: x[1]["h"])
            lo_before_hi = min(b["l"] for t, b in after if t <= hi_t)
            print(f"  his contract {o}: print at {t_in} = {b0['o']:.2f}; best print until {hm(end)} = {hi['h']:.2f} at {hm(hi_t)} "
                  f"({100 * (hi['h'] - b0['o']) / b0['o']:+.0f}%); worst print before that best = {lo_before_hi:.2f} ({100 * (lo_before_hi - b0['o']) / b0['o']:+.0f}%)")
    else:
        day = sorted(bars.items())
        if day:
            print(f"  his contract {o}: session prints low {min(b['l'] for _, b in day):.2f} / high {max(b['h'] for _, b in day):.2f} (entry time not documented)")
    r = rows.get((date, sym))
    if not r:
        print("  OURS: no replay row"); continue
    print(f"  OURS ({sym} replay, real prints): scenario={r.get('scenario')} dayType={r.get('dayType')} trades={len(r['trades'])}")
    for t in r["trades"]:
        print(f"    trade {t['setup']} {t['direction']} in {hm(t['entryTs'])} K{t['strike']:.0f} @{t['entryPremium']:.2f} -> out {hm(t['exitTs'])} {t['pnlPct']:+.1f}%  [{t['exitReason'][:70]}]")
    sk = collections.Counter()
    first = {}
    for ev in r["events"]:
        n = str(ev.get("event", ""))
        if n.startswith("skip"):
            sk[n] += 1
            first.setdefault(n, (ev.get("time"), str(ev.get("why"))[:110]))
    for n, cnt in sk.most_common(6):
        print(f"    {n} x{cnt}  first {first[n][0]}: {first[n][1]}")
    conf = [(ev.get("time"), ev.get("event"), str(ev.get("why"))[:100]) for ev in r["events"] if str(ev.get("event", "")).startswith(("confirm", "setup", "scenario", "bias"))][:5]
    for x in conf:
        print("    ", x)
