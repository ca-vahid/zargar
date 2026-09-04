"""Team2 walk-forward sweep / replay CLI (talks to the running app's API).

    cd backend
    .venv/bin/python -m zargar.tools.team2_sweep sweep --start 2026-08-20 --end 2026-09-03 [--symbols SPY,QQQ] \
        [--set pullback_max_touches=3 --set target_premium=0.5] [--sigma 0.2] [--json out.json]
    .venv/bin/python -m zargar.tools.team2_sweep replay <run_id> [--set key=value ...]
    .venv/bin/python -m zargar.tools.team2_sweep runs [--limit 20]
    .venv/bin/python -m zargar.tools.team2_sweep plan-now [--date 2026-09-04] [--no-arm]

Auth: ZARGAR_SESSION (a session token from `python -m zargar.tools.mint_session`) or ZARGAR_TOKEN.
The sweep reads the BANKED extended-hours bars (research.ext_bars); days without bars show as
`no_bars` — the bank grows nightly, Yahoo only ever backfills ~20 sessions.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

API_DEFAULT = os.environ.get("ZARGAR_API", "http://127.0.0.1:8420")


def _headers() -> dict:
    tok = os.environ.get("ZARGAR_SESSION") or os.environ.get("ZARGAR_TOKEN") or ""
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _parse_sets(items: list[str] | None) -> dict:
    out: dict = {}
    for it in items or []:
        k, _, v = it.partition("=")
        k = k.strip()
        v = v.strip()
        if v.lower() in ("true", "false"):
            out[k] = v.lower() == "true"
        else:
            try:
                out[k] = int(v) if v.isdigit() else float(v)
            except ValueError:
                out[k] = v
    return out


def _print_sweep(res: dict) -> None:
    s = res["summary"]
    print(f"Team2 sweep {res['start']} → {res['end']} on {', '.join(res['symbols'])}  (code {s['codeVersion']})")
    if s["overrides"]:
        print("  variant:", ", ".join(f"{k}={v}" for k, v in s["overrides"].items()))
    print(f"  days with bars: {s['days']}   without: {s['noData']}")
    print(f"  trades: {s['trades']}  wins: {s['wins']}  win rate: {s['winRate']}  "
          f"sum premium %: {s['pnlPctSum']}  avg win: {s['avgWinPct']}  avg loss: {s['avgLossPct']}")
    for title, grp in (("by setup", s["byScenario"]), ("by entry kind", s["byKind"]), ("by bucket", s["byBucket"]),
                       ("early (<10:00)", s["early"])):
        if grp:
            print(f"  {title}:")
            for k, g in sorted(grp.items()):
                wr = round(g["wins"] / g["trades"], 2) if g["trades"] else None
                print(f"    {k:<22} trades {g['trades']:>3}  wins {g['wins']:>3}  wr {wr}  sum% {g['pnlPctSum']}")
    for r in res["rows"]:
        if r["status"] != "ok":
            continue
        for t in r["trades"]:
            print(f"  {r['symbol']} {r['date']} {t['setup']:<24} {t['direction']:<5} {t['entryKind']:<5} "
                  f"strike {t['strike']:g} prem {t['entryPremium']:.2f} → {t['pnlPct']:>7.1f}%  {t['exitReason'][:60]}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--api", default=API_DEFAULT)
    sub = p.add_subparsers(dest="cmd", required=True)
    sw = sub.add_parser("sweep")
    sw.add_argument("--start", required=True)
    sw.add_argument("--end", required=True)
    sw.add_argument("--symbols", default="")
    sw.add_argument("--set", action="append", default=[])
    sw.add_argument("--sigma", type=float, default=None)
    sw.add_argument("--json", default="")
    rp = sub.add_parser("replay")
    rp.add_argument("run_id")
    rp.add_argument("--set", action="append", default=[])
    rs = sub.add_parser("runs")
    rs.add_argument("--limit", type=int, default=20)
    pn = sub.add_parser("plan-now")
    pn.add_argument("--date", default=None)
    pn.add_argument("--no-arm", action="store_true")
    a = p.parse_args()
    with httpx.Client(base_url=a.api, headers=_headers(), timeout=600) as http:
        if a.cmd == "sweep":
            body = {"start": a.start, "end": a.end, "overrides": _parse_sets(a.set) or None, "sigma": a.sigma,
                    "symbols": [s for s in a.symbols.split(",") if s] or None}
            r = http.post("/api/team2/sweep", json=body)
            r.raise_for_status()
            res = r.json()
            _print_sweep(res)
            if a.json:
                with open(a.json, "w", encoding="utf-8") as f:
                    json.dump(res, f, indent=1)
                print("saved", a.json)
        elif a.cmd == "replay":
            r = http.post(f"/api/team2/runs/{a.run_id}/replay", json={"overrides": _parse_sets(a.set) or None})
            r.raise_for_status()
            res = r.json()["result"]
            print(json.dumps(res["summary"], indent=1))
            for e in res["events"]:
                print(f"  {e['time']} {e['event']:<24} {e['why']}")
        elif a.cmd == "runs":
            r = http.get("/api/team2/runs", params={"limit": a.limit})
            r.raise_for_status()
            for row in r.json():
                print(f"{row['runId'][:8]} {row['symbol']:<4} {row['planFor']}  armed={row['armed']}  {row['sheet']}")
        elif a.cmd == "plan-now":
            r = http.post("/api/team2/plan-now", json={"date": a.date, "arm": not a.no_arm})
            r.raise_for_status()
            print(json.dumps(r.json(), indent=1))


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        print(f"HTTP {exc.response.status_code}: {exc.response.text[:300]}", file=sys.stderr)
        sys.exit(1)
