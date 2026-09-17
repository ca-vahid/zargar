"""Team2 profitability diagnostics report (2026-09-16): which entry situations and contract choices offered better
AFTER-COST outcomes on a session, with observation counts and missing-data coverage.

Read-only. Reads the durable `TechniquePlanDiagnostic` rows (entry location, submission, attempt context, contract
candidates, follow-up observations) and the close scorecards (`TechniquePlanScored`, which carry the routing facts and
the unique-decision funnel) of every Team2 plan armed for the date, assembles one record per attempt and summarizes
them with `diagnostics.summarize_day`. Nothing here is a verdict: counts are small, unknown stays unknown, and no
threshold is chosen from this output — the review chooses.

    python -m zargar.tools.team2_diag_report --date 2026-09-17 [--json out.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from ..techniques.team2 import diagnostics as diag


def assemble(rows: list[dict]) -> list[dict]:
    """Journal rows ({type, payload}) -> per-attempt diagnostic records in the runner's own shape."""
    recs: dict[tuple, dict] = {}

    def rec_for(p: dict) -> dict:
        key = (str(p.get("runId")), str(p.get("trigger")))
        return recs.setdefault(key, {"runId": p.get("runId"), "symbol": p.get("symbol"), "trigger": p.get("trigger"),
                                     "setup": str(p.get("trigger") or "").split("#")[0], "observations": {}, "candidates": [],
                                     "entryLocation": {}, "attempt": {}, "routing": {}})

    strip = {"runId", "symbol", "kind", "trigger"}
    scored: list[dict] = []
    for r in rows:
        p = dict(r.get("payload") or {})
        if r.get("type") == "TechniquePlanScored":
            scored.append(p)
            continue
        if r.get("type") != "TechniquePlanDiagnostic":
            continue
        kind = p.get("kind")
        body = {k: v for k, v in p.items() if k not in strip}
        rec = rec_for(p)
        if kind in ("entry_location", "entry_submission"):
            rec["entryLocation"].update(body)
        elif kind == "attempt":
            rec["attempt"].update(body)
        elif kind == "decision_time":
            rec["decisionTime"] = body
        elif kind == "contract_candidates":
            rec.update({"candidates": body.get("candidates") or [], "quoteTs": body.get("quoteTs"), "shadow": bool(body.get("shadow")),
                        "refusal": body.get("refusal"), "selected": body.get("selected")})
        elif kind == "contract_observation":
            rec["observations"][str(body.get("horizon"))] = body
    for p in scored:
        for a in ((p.get("diagnostics") or {}).get("perAttempt") or []):
            key = (str(p.get("runId")), str(a.get("trigger")))
            if key in recs:
                recs[key]["routing"] = dict(a.get("actual") or {})
        for d in p.get("decisionTime") or []:
            key = (str(p.get("runId")), str(d.get("trigger")))
            if key in recs and "decisionTime" not in recs[key]:
                recs[key]["decisionTime"] = d
    return list(recs.values())


def render(date: str, summary: dict, scored: list[dict]) -> str:
    out = [f"Team2 diagnostics {date}: {summary['attempts']} attempt(s) ({summary['shadow']} shadow), {summary['filled']} filled; "
           f"observations {summary['coverage']['observed']} taken / {summary['coverage']['missing']} missing", ""]
    out.append("Entry situations (actual after-cost $ on filled attempts; selected contract ask-to-bid % after two commissions):")
    for s in summary["situations"]:
        sel = ", ".join(f"{h} {v['mean']:+.1f}% (n {v['n']}, missing {v['missing']})" if v["mean"] is not None else f"{h} n/a (missing {v['missing']})"
                        for h, v in (s.get("selectedAskToBidPct") or {}).items())
        out.append(f"  {s['situation']}={s['value']}: attempts {s['attempts']}, filled {s['filled']}, actual net "
                   f"{'n/a' if s['actualNetSum'] is None else f'{s['actualNetSum']:+.2f}'}; {sel or 'no observations'}")
    out.append("")
    out.append("Contract choice (selected vs alternatives the picker examined, ask-to-bid % after costs):")
    for h, v in summary["contractChoice"].items():
        out.append(f"  {h}: selected {v['selectedMeanPct'] if v['selectedMeanPct'] is not None else 'n/a'}% (n {v['selectedN']}); "
                   f"in-band alternatives {v['inBandAlternativesMeanPct'] if v['inBandAlternativesMeanPct'] is not None else 'n/a'}% (n {v['inBandAlternativesN']}); "
                   f"other {v['otherAlternativesMeanPct'] if v['otherAlternativesMeanPct'] is not None else 'n/a'}% (n {v['otherAlternativesN']}); "
                   f"an alternative beat the selected {v['alternativeBeatSelected']}/{v['compared']}")
    out.append("")
    out.append("Per attempt:")
    for a in summary["perAttempt"]:
        loc = (f"sameClose={a['sameCloseConfirmation']} movedAway={a['movedAway']} "
               f"dispAtr={a['submissionFromCloseAtr'] if a['submissionFromCloseAtr'] is not None else 'unknown'}")
        act = a["actual"]
        out.append(f"  {a['trigger']} [{'shadow ' + str(a['refusal']) if a['shadow'] else 'live'}] {a['attemptClass'] or '?'}"
                   f"{' after loss' if a['previousLost'] else ''}: {loc}; actual "
                   f"{'none' if not act.get('filledQty') else f'{act['filledQty']:g} @ {act['avgFill']} -> net {act['netPnl']}'}; "
                   f"coverage {a['coverage']['observed']}/{a['coverage']['observed'] + a['coverage']['missing']}")
        for c in a["candidates"]:
            outs = " ".join(f"{h}:{('%+.1f%%' % o['askToBidPct']) if o else '?'}" for h, o in c["outcomes"].items())
            out.append(f"      {'*' if c['selected'] else ' '} {c['symbol']} ask {c['entryAsk']} delta {c['delta']} "
                       f"{'in-band' if c['inBand'] else 'out'}: {outs}")
    if scored:
        out.append("")
        out.append("Close reports (unique decisions / raw rows):")
        for p in scored:
            out.append(f"  {p.get('symbol')}: skips {json.dumps(p.get('skips') or {})} rows {json.dumps(p.get('skipRows') or {})}; "
                       f"decision-time records {len(p.get('decisionTime') or [])}, corrected-history rows {len(p.get('rows') or [])}")
    out.append("")
    out.append(f"Labels: movedAway = underlying beyond the pullback close by > {summary['labels']['movedAwayAtr']} ATR at the order boundary; "
               f"fee {summary['labels']['feePerSide']}/side; shadow measurements — not filters.")
    return "\n".join(out)


async def main(args) -> int:
    from sqlalchemy import select
    from ..config import get_config
    from ..db import make_engine, make_session_factory
    from ..models import Event, TechniqueArmed
    cfg = get_config(); eng = make_engine(cfg.database_url); sf = make_session_factory(eng)
    async with sf() as session:
        armed = (await session.execute(select(TechniqueArmed).where(TechniqueArmed.technique == "team2", TechniqueArmed.plan_for == args.date))).scalars().all()
        run_ids = sorted({a.run_id for a in armed})
        rows = []
        if run_ids:
            evs = (await session.execute(select(Event).where(Event.aggregate_id.in_(run_ids),
                                                              Event.type.in_(["TechniquePlanDiagnostic", "TechniquePlanScored"]))
                                         .order_by(Event.id))).scalars().all()
            rows = [{"type": e.type, "payload": dict(e.payload or {})} for e in evs]
    await eng.dispose()
    recs = assemble(rows)
    scored = [r["payload"] for r in rows if r["type"] == "TechniquePlanScored"]
    fee = float(args.fee)
    summary = diag.summarize_day(recs, fee)
    print(render(args.date, summary, scored))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"date": args.date, "runs": run_ids, "summary": summary, "scored": scored}, f, indent=1, default=str)
        print(f"\nwritten {args.json}")
    return 0


def cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--date", required=True, help="the plan session (YYYY-MM-DD)")
    ap.add_argument("--fee", default=1.04, help="commission per contract per side used for after-cost outcomes")
    ap.add_argument("--json", default=None, help="also write the full summary as JSON")
    return asyncio.run(main(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(cli())
