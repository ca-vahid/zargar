"""Team2 pre-market input audit (2026-09-17 EOD review §5, GO for a source/derived-level audit). Read-only.

For every Team2 plan of a session: the FROZEN pre-market extremes (PMH/PML the plan traded on), the bar each came from
when the plan recorded it (`pmExtrema`, plans from v0.8.11), the bank's CURRENT pre-market extremes and their bars, and
the revision history of the contributing minutes from the plan's own journal (`bar_revised` / `bar_recovered` rows with
before/after). It reconciles, it never rewrites: a frozen value that differs from the bank is reported with the chain of
observations that produced it, so the decision the desk made stays as it was made.

    python -m zargar.tools.team2_pm_audit --date 2026-09-17 [--json out.json]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _hhmm(ts) -> str:
    try:
        return dt.datetime.fromtimestamp(int(ts) / 1000, ET).strftime("%H:%M")
    except (TypeError, ValueError, OSError):
        return "?"


def reconcile(symbol: str, plan: dict, bank_pre: list[dict], revisions: list[dict]) -> dict:
    """Pure: `plan` = the frozen plan dict; `bank_pre` = the bank's pre-market 1m rows for the date
    ({ts, open, high, low, close, volume, source}); `revisions` = the plan's journaled bar revisions
    ({ts_, before, after, source, at}). Returns the reconciliation record for one symbol."""
    frozen = {"pmh": plan.get("pmh"), "pml": plan.get("pml")}
    ext = plan.get("pmExtrema") if isinstance(plan.get("pmExtrema"), dict) else None
    bank = {"pmh": None, "pml": None, "pmhBar": None, "pmlBar": None, "bars": len(bank_pre),
            "sources": sorted({str(r.get("source") or "unknown") for r in bank_pre})}
    if bank_pre:
        hi = max(bank_pre, key=lambda r: float(r["high"]))
        lo = min(bank_pre, key=lambda r: float(r["low"]))
        bank.update({"pmh": float(hi["high"]), "pml": float(lo["low"]), "pmhBar": dict(hi), "pmlBar": dict(lo)})
    out = {"symbol": symbol, "frozen": frozen, "frozenSource": (ext or {}).get("inputs"), "frozenBars": {
        "pmh": ((ext or {}).get("pmh") or {}).get("bar"), "pml": ((ext or {}).get("pml") or {}).get("bar")},
        "bank": bank, "discrepancies": [], "contributingMinutes": {}}
    for side in ("pmh", "pml"):
        f, b = frozen.get(side), bank.get(side)
        if f is None or b is None:
            if f != b:
                out["discrepancies"].append({"side": side, "frozen": f, "bank": b, "note": "one side has no value"})
            continue
        if abs(float(f) - float(b)) > 0.005:
            out["discrepancies"].append({"side": side, "frozen": float(f), "bank": float(b), "points": round(float(f) - float(b), 4)})
    # the minutes that could have produced a frozen extreme: the recorded source bar (when the plan has one), else every
    # revised minute whose after-value equals the frozen extreme
    for side, field in (("pmh", "high"), ("pml", "low")):
        f = frozen.get(side)
        cands: list[dict] = []
        src_bar = out["frozenBars"].get(side)
        if src_bar and src_bar.get("ts") is not None:
            cands.append({"ts": int(src_bar["ts"]), "time": _hhmm(src_bar["ts"]), "how": "recorded source bar", "bar": src_bar})
        for r in revisions:
            aft = r.get("after") or []
            idx = 1 if field == "high" else 2
            try:
                val = float(aft[idx])
            except (TypeError, ValueError, IndexError):
                continue
            if f is not None and abs(val - float(f)) <= 0.005:
                cands.append({"ts": int(r.get("ts_")), "time": _hhmm(r.get("ts_")), "how": "a revision introduced this value",
                              "before": r.get("before"), "after": aft, "source": r.get("source"), "at": r.get("at")})
        chain_by_minute: dict = {}
        for c_ in cands:
            m = chain_by_minute.setdefault(c_["ts"], {"ts": c_["ts"], "time": c_["time"], "evidence": [], "bankRow": None, "revisions": []})
            m["evidence"].append(c_)
        for ts_, m in chain_by_minute.items():
            m["bankRow"] = next((dict(r) for r in bank_pre if int(r["ts"]) == ts_), None)
            m["revisions"] = [dict(r) for r in revisions if int(r.get("ts_") or -1) == ts_]
            if m["bankRow"] is not None and m["revisions"]:
                last = m["revisions"][-1].get("after") or []
                m["bankKeptTheCorrection"] = (len(last) >= 4 and abs(float(last[idx]) - float(m["bankRow"][field])) <= 0.005)
        out["contributingMinutes"][side] = list(chain_by_minute.values())
    return out


def render(date: str, recs: list[dict]) -> str:
    lines = [f"Team2 pre-market input audit {date}", ""]
    for r in recs:
        fz, bk = r["frozen"], r["bank"]
        lines.append(f"{r['symbol']}: frozen PMH/PML {fz['pmh']} / {fz['pml']}  |  bank now {bk['pmh']} / {bk['pml']} "
                     f"({bk['bars']} pre-market rows, provenance {','.join(bk['sources']) or '?'})")
        if r.get("frozenSource"):
            lines.append(f"   frozen inputs: {r['frozenSource'].get('bars')} bars, hash {r['frozenSource'].get('hash')}, sources {r['frozenSource'].get('sources')}")
        else:
            lines.append("   frozen inputs: not recorded by this plan (pre-v0.8.11) — the contributing minute is inferred from revisions")
        if not r["discrepancies"]:
            lines.append("   reconciled: frozen == bank")
        for d in r["discrepancies"]:
            lines.append(f"   DISCREPANCY {d['side'].upper()}: frozen {d['frozen']} vs bank {d['bank']} ({d.get('points', '?')} pts)")
            for m in r["contributingMinutes"].get(d["side"], []):
                lines.append(f"      minute {m['time']}: bank row {m['bankRow'] and [m['bankRow'].get(k) for k in ('open', 'high', 'low', 'close', 'volume', 'source')]}")
                for rev in m["revisions"]:
                    lines.append(f"         revision at {rev.get('at') or '?'}: {rev.get('before')} -> {rev.get('after')} (source {rev.get('source')})")
                if "bankKeptTheCorrection" in m:
                    lines.append(f"         bank kept the correction: {m['bankKeptTheCorrection']}")
        lines.append("")
    lines.append("Read-only reconciliation. The plan's frozen values are the decision's inputs and are never rewritten here.")
    return "\n".join(lines)


async def main(args) -> int:
    from sqlalchemy import select
    from ..config import get_config
    from ..db import make_engine, make_session_factory
    from ..models import BarRow, Event, TechniqueArmed, TechniqueRun
    cfg = get_config(); eng = make_engine(cfg.database_url); sf = make_session_factory(eng)
    day = dt.date.fromisoformat(args.date)
    t0 = int(dt.datetime.combine(day, dt.time(4, 0), ET).timestamp() * 1000)
    t1 = int(dt.datetime.combine(day, dt.time(9, 30), ET).timestamp() * 1000)
    recs = []
    async with sf() as session:
        armed = (await session.execute(select(TechniqueArmed).where(TechniqueArmed.technique == "team2", TechniqueArmed.plan_for == args.date))).scalars().all()
        for a in armed:
            run = (await session.execute(select(TechniqueRun).where(TechniqueRun.id == a.run_id))).scalars().first()
            plan = ((run.result or {}).get("plan") if run is not None else None) or {}
            rows = (await session.execute(select(BarRow).where(BarRow.symbol == a.symbol, BarRow.tf == "1m", BarRow.ts >= t0, BarRow.ts < t1))).scalars().all()
            bank = [{"ts": r.ts, "open": r.open, "high": r.high, "low": r.low, "close": r.close, "volume": r.volume, "source": r.source} for r in rows]
            evs = (await session.execute(select(Event).where(Event.aggregate_id == a.run_id, Event.type == "TechniquePlanRead").order_by(Event.id))).scalars().all()
            revs = []
            for e in evs:
                p = dict(e.payload or {})
                if p.get("event") in ("bar_revised", "bar_recovered") and p.get("ts_") is not None:
                    revs.append({"ts_": p.get("ts_"), "before": p.get("before"), "after": p.get("after"), "source": p.get("source"),
                                 "at": (e.ts.astimezone(ET).strftime("%H:%M:%S") if e.ts else None)})
            recs.append(reconcile(a.symbol, plan, bank, revs))
    await eng.dispose()
    print(render(args.date, recs))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"date": args.date, "plans": recs}, f, indent=1, default=str)
        print(f"\nwritten {args.json}")
    return 0


def cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--date", required=True)
    ap.add_argument("--json", default=None)
    return asyncio.run(main(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(cli())
