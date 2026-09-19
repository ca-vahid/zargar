"""Offline Team2 replay on the local Alpaca SIP cache. Pure functions only: no DB, no runtime, no orders.
usage: replay.py DATA OUT START END [key=value ...]"""
import json, sys, pathlib, datetime as dt
from zargar.domain import Bar
from zargar.settings_service import DEFAULTS
from zargar.marketstructure.aggregate import aggregate, bar_session, filter_session
from zargar.marketstructure.market_calendar import trading_days
from zargar.marketstructure.sessions import session_date
from zargar.techniques.team2.plan import build_skeleton, complete_plan
from zargar.techniques.team2.rules import Team2Rules, rules_from_settings
from zargar.techniques.team2.session import simulate_session
from zargar.techniques.team2.service import Team2Service

DATA, OUT, START, END = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
ov = {}
REAL = "--real" in sys.argv
HARN = {}
args = [a for a in sys.argv[5:] if a != "--real"]
for a in list(args):
    if a.startswith("@"):                      # harness-only options (never rules): @itm_steps=2 @symbols=SPY,QQQ
        k, _, v = a[1:].partition("=")
        HARN[k] = v
        args.remove(a)
for it in args:
    k, _, v = it.partition("=")
    if v in ("true", "false"):
        ov[k] = v == "true"
    else:
        try:
            ov[k] = int(v) if v.lstrip("-").isdigit() else float(v)
        except ValueError:
            ov[k] = v
RUNTIME = {"techniques.team2.budget_per_trade": 2000.0, "techniques.team2.risk_pct": 6.0, "techniques.team2.max_risk_pct": 6.0,
           "techniques.team2.target_replan": "structure", "techniques.team2.daily_loss_halt_pct": 10.0}


class S:
    def get(self, k, d=None):
        return RUNTIME.get(k, DEFAULTS.get(k, d))


base = rules_from_settings(S())
rules = Team2Rules.from_dict({**base.to_dict(), **ov}) if ov else base
vix = {}
for line in (DATA / "vix1d.csv").read_text().split():
    t, c = line.split(",")
    vix[session_date(int(t))] = float(c)
vd = sorted(vix)


def sigma_for(date):
    prev = [d for d in vd if d < date]
    return vix[prev[-1]] / 100.0 if prev else 0.20


def parse(t):
    return int(dt.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() * 1000)


if REAL:
    import httpx
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    import realmodel
    import zargar.techniques.team2.session as _sess
    from zargar.config import get_config
    _c = get_config()
    realmodel.CTX.update(data=DATA, http=httpx.Client(timeout=90),
                         headers={"APCA-API-KEY-ID": _c.alpaca_key_id, "APCA-API-SECRET-KEY": _c.alpaca_secret})
    if HARN.get("itm_steps"):
        realmodel.CTX["itm_steps"] = int(HARN["itm_steps"])
    (DATA / "opt").mkdir(exist_ok=True)
    _sess.PremiumModel = realmodel.RealPremiumModel
rows = []
for sym in (HARN.get("symbols") or "SPY,QQQ,IWM").split(","):
    raw = json.loads((DATA / f"{sym}_1m.json").read_text())
    bars = [Bar(symbol=sym, tf="1m", ts=parse(r["t"]), open=r["o"], high=r["h"], low=r["l"], close=r["c"], volume=int(r["v"]),
                source="exchange", provider="alpaca") for r in raw]
    by_day = {}
    for b in bars:
        by_day.setdefault(session_date(b.ts), []).append(b)
    for d in trading_days(START, END):
        date = d.isoformat()
        today = by_day.get(date) or []
        if not today or not filter_session(today, "rth"):
            rows.append({"symbol": sym, "date": date, "status": "no_bars"})
            continue
        pd_ = sorted(k for k in by_day if k < date)[-max(rules.warmup_sessions, rules.target_lookback_sessions + 2):]
        prior = [b for k in pd_ for b in by_day[k]]
        warm, wrep = Team2Service.warmup_slice(prior, sessions=rules.warmup_sessions)
        fifteen = [b for b in aggregate(prior, 15) if bar_session(b.ts) == "rth"] if prior else []
        sk = build_skeleton(sym, date, fifteen, rules, prev_bars_1m=prior)
        if sk is None:
            rows.append({"symbol": sym, "date": date, "status": "no_prev_session"})
            continue
        plan = complete_plan({**sk, "planFor": date}, today)
        if REAL:
            realmodel.CTX.update(symbol=sym, date=date, und={b.ts: {"h": b.high, "l": b.low} for b in today})
        res = simulate_session(plan, today, rules, sigma=sigma_for(date), warmup_1m=warm).to_dict()
        rows.append({"symbol": sym, "date": date, "status": "ok", "dayType": plan.get("dayType"), "scenario": res["bias"].get("scenario"),
                     "bias": res["bias"], "trades": res["trades"], "setups": res["setups"], "summary": res["summary"],
                     "events": res["events"], "warmup": {"sessionsUsed": wrep.get("sessionsUsed")},
                     "sigma": sigma_for(date), "pmh": plan.get("pmh"), "pml": plan.get("pml"),
                     "zones": plan.get("zones"), "targets": plan.get("targets"), "pricing": "real_prints" if REAL else "bs_flat_iv"})
json.dump({"rules": rules.to_dict(), "overrides": ov, "rows": rows}, open(OUT, "w"))
ok = [r for r in rows if r["status"] == "ok"]
tr = [t for r in ok for t in r["trades"]]
print("symbol-days ok", len(ok), "other", len(rows) - len(ok), "trades", len(tr), "wins", sum(t["win"] for t in tr),
      "sumPct", round(sum(t["pnlPct"] for t in tr), 1))
