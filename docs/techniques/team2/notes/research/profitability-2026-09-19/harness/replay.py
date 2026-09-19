"""Offline Team2 replay on the local Alpaca SIP cache, priced on real option prints (v2). Pure functions only: no DB, no
runtime, no orders. Run with PYTHONPATH=<worktree>/backend (a script's own folder heads sys.path; without it the venv's
editable install imports the RUNNING checkout).

usage: replay.py DATA OUT START END [rule=value ...] [@touch=proxy|conservative|optimistic] [@offline=1] [@symbols=SPY,QQQ]
"""
import json, sys, math, hashlib, pathlib, subprocess, datetime as dt
import zargar
from zargar.domain import Bar
from zargar.settings_service import DEFAULTS
from zargar.marketstructure.aggregate import aggregate, bar_session, filter_session
from zargar.marketstructure.market_calendar import trading_days
from zargar.marketstructure.sessions import session_date
from zargar.techniques.team2.plan import build_skeleton, complete_plan
from zargar.techniques.team2.rules import Team2Rules, rules_from_settings
from zargar.techniques.team2.service import Team2Service
import zargar.techniques.team2.session as _sess

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import realmodel  # noqa: E402

DATA, OUT, START, END = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
ov, HARN = {}, {}
for a in sys.argv[5:]:
    k, _, v = a.partition("=")
    if k.startswith("@"):
        HARN[k[1:]] = v
    elif v in ("true", "false"):
        ov[k] = v == "true"
    else:
        try:
            ov[k] = int(v) if v.lstrip("-").isdigit() else float(v)
        except ValueError:
            ov[k] = v
# the runtime's effective Team2 settings on 2026-09-18 (settings table, read-only), over the code DEFAULTS
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


def sigma_for(date):                                   # unused by the real-print model; kept so the read's signature is unchanged
    prev = [d for d in vd if d < date]
    return vix[prev[-1]] / 100.0 if prev else 0.20


def parse(t):
    return int(dt.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() * 1000)


realmodel.CTX.update(data=DATA, touch_mode=HARN.get("touch", "proxy"), offline=HARN.get("offline") == "1")
if not realmodel.CTX["offline"]:
    import httpx
    from zargar.config import get_config
    _c = get_config()
    realmodel.CTX.update(http=httpx.Client(timeout=90), headers={"APCA-API-KEY-ID": _c.alpaca_key_id, "APCA-API-SECRET-KEY": _c.alpaca_secret})
(DATA / "opt").mkdir(exist_ok=True)
_sess.PremiumModel = realmodel.RealPremiumModel

rows, inputs = [], {}
for sym in (HARN.get("symbols") or "SPY,QQQ,IWM").split(","):
    fp = DATA / f"{sym}_1m.json"
    inputs[sym] = hashlib.sha256(fp.read_bytes()).hexdigest()
    raw = json.loads(fp.read_text())
    bars = [Bar(symbol=sym, tf="1m", ts=parse(r["t"]), open=r["o"], high=r["h"], low=r["l"], close=r["c"], volume=int(r["v"]),
                source="exchange", provider="alpaca") for r in raw]
    by_day = {}
    for b in bars:
        by_day.setdefault(session_date(b.ts), []).append(b)
    for d in trading_days(START, END):
        date = d.isoformat()
        today = by_day.get(date) or []
        rth = filter_session(today, "rth") if today else []
        if not rth:
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
        realmodel.CTX.update(symbol=sym, date=date, und={b.ts: {"h": b.high, "l": b.low} for b in today})
        n0 = len(realmodel.LOG)
        res = _sess.simulate_session(plan, today, rules, sigma=sigma_for(date), warmup_1m=warm).to_dict()
        log = realmodel.LOG[n0:]
        ent = {e["T"]: e for e in log if e["kind"] == "entry" and e.get("outcome") == "filled"}
        for t in res["trades"]:
            e = ent.get(t["entryTs"]) or {}
            t["pricing"] = {k: e.get(k) for k in ("observedPx", "observationTs", "observedAgeMin", "execPx", "executionTs", "execLagMin")}
            bad = [x for x in [t["pnlPct"]] + [l.get("premium") for l in t["exits"]] if isinstance(x, float) and math.isnan(x)]
            t["censored"] = bool(bad)
        rows.append({"symbol": sym, "date": date, "status": "ok", "dayType": plan.get("dayType"), "scenario": res["bias"].get("scenario"),
                     "trades": res["trades"], "setups": res["setups"], "summary": res["summary"], "events": res["events"],
                     "pricingLog": log, "rthBars": len(rth), "warmupSessions": wrep.get("sessionsUsed"), "warmupHash": wrep.get("hash"),
                     "pmh": plan.get("pmh"), "pml": plan.get("pml"), "zones": plan.get("zones"), "targets": plan.get("targets")})
try:
    commit = subprocess.run(["git", "-C", str(pathlib.Path(zargar.__file__).parent), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
except Exception:  # noqa: BLE001
    commit = None
meta = {"harness": "v2", "codeCommit": commit, "zargarPath": str(pathlib.Path(zargar.__file__).parent), "window": [START, END],
        "overrides": ov, "harnessOptions": HARN, "underlyingSha256": inputs, "pricing": "real_prints_v2",
        "conventions": {"selAgeMin": realmodel.SEL_AGE_MIN, "execWindowMin": realmodel.EXEC_WINDOW_MIN, "exitWindowMin": realmodel.EXIT_WINDOW_MIN,
                        "touchMode": realmodel.CTX["touch_mode"]}}
json.dump({"meta": meta, "rules": rules.to_dict(), "overrides": ov, "rows": rows}, open(OUT, "w"))
ok = [r for r in rows if r["status"] == "ok"]
tr = [t for r in ok for t in r["trades"]]
good = [t for t in tr if not t["censored"]]
print("symbol-days ok", len(ok), "other", len(rows) - len(ok), "trades", len(tr), "censored", len(tr) - len(good),
      "mean%", round(sum(t["pnlPct"] for t in good) / max(1, len(good)), 2), "fetched", realmodel.CTX["fetched"])
