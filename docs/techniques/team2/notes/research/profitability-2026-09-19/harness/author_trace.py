"""Source-grounded author comparison (v2). For each documented author trade inside the data window:
(1) what his Webull card implies about his entry price (card % and card time are read from the image; the entry price is NEVER
    documented), and the minutes in which his contract actually traded at that implied price before the card;
(2) our read's full decision trail on that symbol up to the card time. Real prints only.
usage: author_trace.py DATA REPLAY.json"""
import json, sys, pathlib, datetime as dt
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
DATA = pathlib.Path(sys.argv[1]); rep = json.load(open(sys.argv[2]))
MIN = 60_000
# date, symbol, call, strike, card time ET, card open P&L %, alert facts read from the image
CASES = [
    ("2026-09-01", "IWM", False, 292, "12:34", 474.14, "card only; no entry alert, time or price in the image"),
    ("2026-09-03", "SPY", True, 770, "11:19", 536.99, "alert 'I'm taking SPY 770c' after 'Getting the 768.00 retest now' - message time not visible; earlier cards 771C +25.00% 09:52 and 770C +26.14% 10:24"),
    ("2026-09-09", "IWM", False, 293, "10:19", 141.77, "09:41 'I'm watching the 293p'; 'I'm getting IWM 293p' follows with no visible time"),
    ("2026-09-10", "IWM", False, 288, "14:10", 85.37, "'the 15 minute candle finally closed under our level. I'm watching those 288p now' then 'I'm taking IWM 288p' - no visible time; 14:12 'up 80%+ on these runners'"),
    ("2026-09-11", "SPY", True, 768, "10:00", 50.0, "09:46 'I'm taking SPY 768c' (timestamped alert); 10:00 'Up 50% get those trims' (alert text, not a card); day P&L +$801.66"),
]


def occ(sym, date, call, strike):
    x = dt.date.fromisoformat(date)
    return f"{sym}{x:%y%m%d}{'C' if call else 'P'}{int(round(strike * 1000)):08d}"


def ms(date, hm):
    return int(dt.datetime.fromisoformat(f"{date}T{hm}:00").replace(tzinfo=ET).timestamp() * 1000)


def hm(t):
    return dt.datetime.fromtimestamp(t / 1000, ET).strftime("%H:%M")


rows = {(r["date"], r["symbol"]): r for r in rep["rows"] if r["status"] == "ok"}
for date, sym, call, k, card, pct, facts in CASES:
    o = occ(sym, date, call, k)
    p = DATA / "opt" / f"{o}.json"
    bars = {int(dt.datetime.fromisoformat(b["t"].replace("Z", "+00:00")).timestamp() * 1000): b for b in (json.loads(p.read_text()) if p.exists() else [])}
    tc = ms(date, card)
    print(f"\n=== {date} {sym} {o}\n  IMAGE: {facts}\n  CARD: +{pct}% at {card} ET")
    cb = bars.get(tc) or bars.get(tc - MIN)
    if cb:
        lo_i, hi_i = cb["l"] / (1 + pct / 100), cb["h"] / (1 + pct / 100)
        print(f"  contract printed {cb['l']:.2f}-{cb['h']:.2f} in the card minute -> implied entry price {lo_i:.3f} to {hi_i:.3f} (if the card shows the whole position's open P&L)")
        hits = [t for t, b in sorted(bars.items()) if ms(date, '09:30') <= t < tc and b["l"] <= hi_i and b["h"] >= lo_i]
        if hits:
            runs, start, prev = [], hits[0], hits[0]
            for t in hits[1:]:
                if t - prev > MIN:
                    runs.append((start, prev)); start = t
                prev = t
            runs.append((start, prev))
            print("  minutes in which the contract traded inside that implied range before the card:", ", ".join(f"{hm(a)}-{hm(b)}" if a != b else hm(a) for a, b in runs[-10:]), f"(showing the last 10 of {len(runs)} runs)")
        else:
            print("  the contract never traded inside that implied range before the card (averaged entry, a different contract, or the card is not the whole position)")
    r = rows.get((date, sym))
    print(f"  OUR READ ({sym}): scenario={r.get('scenario')} dayType={r.get('dayType')} pmh={r.get('pmh')} pml={r.get('pml')} targets={r.get('targets')}")
    seen = set()
    for e in r["events"]:
        n = str(e.get("event", ""))
        if e.get("ts", 0) > tc + 2 * MIN or n in ("bar", "regime", "decision_inputs"):
            continue
        key = (n, str(e.get("setup")))
        if n.startswith("skip") and key in seen:
            continue
        seen.add(key)
        print(f"    {e.get('time')} {n:24s} {str(e.get('why'))[:170]}")
    for t in r["trades"]:
        if t["entryTs"] <= tc:
            pr = t.get("pricing") or {}
            print(f"    TRADE {t['setup']} in {hm(t['entryTs'])} K{t['strike']:.0f} observed {pr.get('observedPx')} exec {pr.get('execPx')} -> out {hm(t['exitTs'])} {t['pnlPct']:+.1f}% [{t['exitReason'][:60]}]")
