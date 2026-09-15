"""Entry-variant cohort CLI (KFIN-09) - standalone, reads the DB directly,
never touches the running app, never places anything.

    python -m zargar.tools.tip_entry_cohort report [--since 2026-09-15] [--json out.json]
    python -m zargar.tools.tip_entry_cohort rows   [--since 2026-09-15]

`report` recomputes every variant's result book from the recorded cohort rows
under the CURRENT budget/fee/fill assumptions (identical across variants),
then prints the denominator (every eligible idea by decision), each variant's
adequate / insufficient / filled counts and the disclaimer. It never prints a
P&L. The delayed-sample catch-up (`sample_due`) needs the live quote store, so
it runs inside the app, not here; rows still pending show as such.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys


async def _open():
    from ..bus import Bus
    from ..config import get_config
    from ..db import make_engine, make_session_factory
    from ..events import Journal
    from ..settings_service import SettingsService
    cfg = get_config()
    eng = make_engine(cfg.database_url)
    sf = make_session_factory(eng)
    bus = Bus()
    settings = SettingsService(sf, bus, Journal(sf, bus))
    await settings.load()
    return eng, sf, settings


def _since(s: str) -> dt.datetime | None:
    if not s:
        return None
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def print_report(rep: dict) -> None:
    den = rep["denominator"]
    print(f"cohort since {rep.get('since') or 'the beginning'}: {den['ideas']} eligible idea(s)")
    for k, n in sorted(den["byDecision"].items(), key=lambda kv: -kv[1]):
        print(f"  {k:<20} {n}")
    print(f"quote at decision: {den['quoteStatus']} · delayed sample: {den['delayedStatus']} · "
          f"post time known: {den['postTimeKnown']} · source premium known: {den['sourcePremiumKnown']}")
    a = rep["assumptions"]
    print(f"assumptions (identical for every variant): option budget ${a['optionBudget']:,.0f}, "
          f"max {a['maxContracts']} contracts, fee ${a['feePerContract']:.2f}/contract, "
          f"delay {a['delayMinutes']:g} min, cap {a['premiumCap']:g}x, quote max age {a['quoteMaxAgeSeconds']:g}s; "
          f"fill = {a['fill']}")
    for v, d in rep["variants"].items():
        print(f"  {d['book']:<20} rows={d['rows']} adequate={d['adequate']} insufficient={d['insufficient']} "
              f"filled={d['filled']} no-fill={d['noFill']}")
        for why, n in sorted(d["insufficientReasons"].items(), key=lambda kv: -kv[1]):
            print(f"      insufficient: {why} x{n}")
    print(f"evidence: adequate rows {rep['evidence']['adequateRows']} · insufficient rows "
          f"{rep['evidence']['insufficientRows']}")
    print(f"\n{rep['disclaimer']}")


async def run(a) -> int:
    from ..techniques.tip import cohort
    eng, sf, settings = await _open()
    try:
        since = _since(a.since)
        if a.cmd == "rows":
            rep = await cohort.cohort_report(sf, settings, since=since, recompute=False)
            for r in rep["rows"]:
                q = r.get("quoteAtDecision") or {}
                print(f"{(r['decidedAt'] or '')[:19]} {r['ticker']:<6} {r['decision']:<18} "
                      f"src={r['sourceInstrument'].get('occ') or r['sourceInstrument'].get('instrument')} "
                      f"prem={r['sourcePremium']} quote={r['quoteStatus']}"
                      f"{' ask=' + str(q.get('ask')) + ' src=' + str(q.get('source')) if q else ''} "
                      f"delayed={r['delayedStatus']} gaps={len(r['gaps'])} id={r['id'][:8]}")
            return 0
        rep = await cohort.cohort_report(sf, settings, since=since, recompute=True)
        print_report(rep)
        if a.json:
            with open(a.json, "w", encoding="utf-8") as f:
                json.dump(rep, f, indent=2, default=str)
            print(f"written: {a.json}")
        return 0
    finally:
        await eng.dispose()


def main() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["report", "rows"])
    ap.add_argument("--since", default="")
    ap.add_argument("--json", default="")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
