"""Input and coverage manifest for one replay file (v2). usage: manifest.py DATA REPLAY.json OUT.json"""
import json, sys, hashlib, pathlib, collections, datetime as dt
DATA = pathlib.Path(sys.argv[1]); d = json.load(open(sys.argv[2])); OUT = sys.argv[3]
opt = DATA / "opt"
files = sorted(opt.glob("*.json"))
h = hashlib.sha256()
empty = []
for p in files:
    b = p.read_bytes()
    h.update(p.name.encode()); h.update(hashlib.sha256(b).digest())
    if len(b) <= 2:
        empty.append(p.stem)
rows = d["rows"]
ok = [r for r in rows if r["status"] == "ok"]
cov = []
outcomes = collections.Counter()
lag = collections.Counter()
age = collections.Counter()
unknown = collections.Counter()
short_days = []
for r in ok:
    log = r.get("pricingLog") or []
    ent = [e for e in log if e["kind"] == "entry"]
    oc = collections.Counter(e["outcome"] for e in ent)
    outcomes.update(oc)
    for e in ent:
        if e["outcome"] == "filled":
            lag[e["execLagMin"]] += 1
            age[e["observedAgeMin"]] += 1
    uk = collections.Counter(e["kind"] for e in log if e["kind"] != "entry")
    unknown.update(uk)
    if r["rthBars"] < 385:
        short_days.append([r["date"], r["symbol"], r["rthBars"]])
    skips = collections.Counter(str(e.get("event")) for e in r["events"] if str(e.get("event", "")).startswith("skip"))
    cov.append({"date": r["date"], "symbol": r["symbol"], "rthBars": r["rthBars"], "warmupSessions": r["warmupSessions"], "warmupHash": r.get("warmupHash"),
                "scenario": r.get("scenario"), "dayType": r.get("dayType"), "trades": len(r["trades"]),
                "censoredTrades": sum(1 for t in r["trades"] if t.get("censored")), "entryAttempts": dict(oc), "unknownMarks": dict(uk),
                "readRefusals": dict(skips),
                "class": "traded" if r["trades"] else ("priced_refusal_only" if oc and not oc.get("filled") else "no_trade_decision")})
cls = collections.Counter(c["class"] for c in cov)
man = {"replay": pathlib.Path(sys.argv[2]).name, "meta": d.get("meta"), "effectiveRules": d["rules"],
       "provider": "Alpaca market data: /v2/stocks/bars feed=sip adjustment=raw 1Min (extended hours included); /v1beta1/options/bars 1Min (OPRA trade prints)",
       "calendar": "zargar.marketstructure.market_calendar.trading_days; sessions by zargar.marketstructure.sessions.session_date (America/New_York)",
       "warmup": "12 valid prior sessions via Team2Service.warmup_slice (the live rule F99); hash per symbol-day in `coverage`",
       "underlyingFiles": {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(DATA.glob("*_1m.json"))},
       "vixFile": {"sha256": hashlib.sha256((DATA / "vix1d.csv").read_bytes()).hexdigest(), "note": "not used by the real-print model"},
       "optionCache": {"contracts": len(files), "setSha256": h.hexdigest(), "contractsWithNoPrintsAllDay": len(empty),
                       "note": "a contract with no prints may be unlisted OR listed and untraded: prints cannot tell these apart"},
       "symbolDays": {"total": len(rows), "ok": len(ok), "byStatus": dict(collections.Counter(r["status"] for r in rows)), "byClass": dict(cls)},
       "entryAttemptOutcomes": dict(outcomes), "executionLagMinutes": dict(lag), "selectionPrintAgeMinutes": dict(age),
       "unknownMarks": dict(unknown), "sessionsWithShortRth": short_days, "coverage": cov}
json.dump(man, open(OUT, "w"), indent=1)
print(json.dumps({k: man[k] for k in ("symbolDays", "entryAttemptOutcomes", "executionLagMinutes", "selectionPrintAgeMinutes", "unknownMarks", "optionCache")}, indent=1))
print("short RTH sessions:", short_days[:12])
