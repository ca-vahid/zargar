"""Frozen, order-free Lane A replay over past Cartel preparation runs (2026-09-18).

Read-only. For each session it takes the original preparation run, every row that passed the
screen and context gates (only those can qualify under Lane A, whose context gates are the
existing ones), loads that row's frozen analysis run (checks, candidates, the daily history it
used, its as-of), evaluates the Lane A definition (``lane_a.lane_a_review``) with the inactive
1.5R experiment recorded, classifies planning-time contract feasibility from the newest chain
snapshot dated *before* the session (``unknown_stale`` when none exists), and reports the actual
outcome the current rules produced. Denominators come from the preparation run itself.

    python -m zargar.tools.cartel_lane_a_eval --database-url ... --start 2026-09-08 --end 2026-09-17 --out-dir <dir>

Nothing here arms, orders or changes a setting. Conclusions stop at the last supported stage:
a Lane A ``qualified`` row is a planning verdict, never an entry or an outcome.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
from collections import Counter

from ..techniques.options_cartel.data import DailyBar
from ..techniques.options_cartel.lane_a import FeasibilityPolicy, LaneAParameters, feasibility_from_chain, lane_a_review

NON_FILTERED = ("candidate", "plan_blocked", "data_error")


def _load(v):
    return json.loads(v) if isinstance(v, str) else v


async def _connect(url: str):
    import asyncpg

    conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
    await conn.execute("set default_transaction_read_only = on")
    return conn


async def session_preparations(conn, start: str, end: str) -> dict[str, dict]:
    """The most complete original preparation run per session.

    Several runs exist per session (benchmark waits, resumes, pre-open retries). The one that
    represents the session's planning is the run with a known market direction and the largest
    evaluated count; ties go to the earliest, so later resumes never replace the original.
    """
    rows = await conn.fetch(
        "select id, created_at, config, result from technique_runs where technique='options_cartel' and mode='preparation' "
        "and status='done' and result->>'session' between $1 and $2 and coalesce(result->>'phase','') <> 'waiting_for_benchmark' order by created_at",
        start, end)
    best: dict[str, tuple] = {}
    for r in rows:
        res = _load(r["result"]) or {}
        session = res.get("session")
        if not session:
            continue
        market = (res.get("market") or {}).get("strictDirection") or (res.get("market") or {}).get("direction")
        known = market in ("long", "short", "mixed")
        key = (1 if known else 0, len(res.get("rows") or []), -r["created_at"].timestamp())  # fullest run, earliest on ties
        if session not in best or key > best[session][0]:
            best[session] = (key, {"id": r["id"], "createdAt": str(r["created_at"]), "result": res, "config": _load(r["config"]) or {},
                                   "runsForSession": 0})
    for session in best:
        best[session][1]["runsForSession"] = sum(1 for r in rows if (_load(r["result"]) or {}).get("session") == session)
    return {s: v[1] for s, v in best.items()}


async def chain_before(conn, underlying: str, session: dt.date):
    """Newest nightly chain snapshot strictly before the session (dates are stored as ISO strings)."""
    date = await conn.fetchval("select max(date) from option_chain_snapshots where underlying=$1 and date < $2", underlying, session.isoformat())
    if date is None:
        return None, []
    rows = await conn.fetch("select occ, expiry, strike, option_type, delta, bid, ask, open_interest from option_chain_snapshots where underlying=$1 and date=$2", underlying, date)
    return str(date), [dict(r) for r in rows]


async def evaluate_session(conn, session: str, prep: dict, params: LaneAParameters, policy: FeasibilityPolicy, market_basis: str = "strict") -> dict:
    res = prep["result"]
    market = res.get("market") or {}
    strict = market.get("strictDirection") or market.get("direction")
    moderate = market.get("direction")
    market_direction = strict if market_basis == "strict" else moderate
    shortlist = {s.get("symbol"): s for s in res.get("shortlist") or []}
    # Older runs list a symbol twice (a `candidate` row with its analysisId and a `plan_blocked` row
    # without one). Merge per symbol; keep every status and the analysis id from whichever row has it.
    merged: dict[str, dict] = {}
    for x in res.get("rows") or []:
        if x.get("status") not in NON_FILTERED:
            continue
        m = merged.setdefault(x.get("symbol"), {"symbol": x.get("symbol"), "statuses": [], "reason": None, "analysisId": None})
        m["statuses"].append(x.get("status"))
        m["reason"] = m["reason"] or x.get("reason")
        m["analysisId"] = m["analysisId"] or x.get("analysisId")
    rows = list(merged.values())
    first_session = dt.date.fromisoformat(session)
    evaluated = []
    for row in rows:
        symbol = row.get("symbol")
        row["status"] = "data_error" if row["statuses"] == ["data_error"] else "/".join(dict.fromkeys(row["statuses"]))
        entry = {"symbol": symbol, "currentStatus": row["status"], "currentReason": (row.get("reason") or "")[:120],
                 "shortlistStatus": (shortlist.get(symbol) or {}).get("status"), "currentSetup": (shortlist.get(symbol) or {}).get("setup"),
                 "currentStructuralR": ((shortlist.get(symbol) or {}).get("ranking") or {}).get("structuralTargetR"),
                 "analysisId": row.get("analysisId")}
        if row.get("status") == "data_error":
            entry.update(laneA={"stage": "data_error", "qualified": False, "reasons": [f"Daily history error in preparation: {(row.get('reason') or '')[:100]}"]})
            evaluated.append(entry)
            continue
        analysis_run = await conn.fetchrow("select as_of, created_at, config, result from technique_runs where id=$1", row.get("analysisId")) if row.get("analysisId") else None
        if analysis_run is None:
            entry.update(laneA={"stage": "no_frozen_analysis", "qualified": False, "reasons": ["Analysis run not found; cannot evaluate without frozen inputs."]})
            evaluated.append(entry)
            continue
        cfg = _load(analysis_run["config"]) or {}
        result = _load(analysis_run["result"]) or {}
        inputs = cfg.get("inputs") or {}
        history = [DailyBar.model_validate(b) for b in inputs.get("history") or []]
        direction = inputs.get("direction") or result.get("analysis", {}).get("direction")
        as_of = inputs.get("as_of_ms") or analysis_run["as_of"]
        entry["inputs"] = {"analysisAsOf": dt.datetime.fromtimestamp(as_of / 1000, tz=dt.timezone.utc).isoformat(), "dailyBars": len(history),
                           "inputSha256": cfg.get("inputSha256"), "availability": "frozen analysis run created " + str(analysis_run["created_at"])}
        review = lane_a_review(result.get("analysis") or {}, history, as_of_ms=as_of, direction=direction, market_direction=market_direction, parameters=params)
        entry["laneA"] = {k: review.get(k) for k in ("qualified", "stage", "reasons", "structuralR", "firstTargetPct", "experimental", "ceilingTests")}
        entry["laneACandidate"] = review.get("candidate")
        if review["qualified"]:
            date, chain = await chain_before(conn, symbol, first_session)
            if date is None:
                entry["feasibility"] = {"state": "unknown_stale", "observedAt": None, "note": "No chain snapshot dated before the session; planning-time quotes were not recorded."}
            else:
                entry["feasibility"] = feasibility_from_chain(chain, direction="long", first_session=first_session, policy=policy, observed_at=date)
        evaluated.append(entry)
    stages = Counter((e["laneA"] or {}).get("stage") for e in evaluated)
    qualified = [e for e in evaluated if (e["laneA"] or {}).get("qualified")]
    return {"session": session, "preparationId": prep["id"], "preparationCreatedAt": prep["createdAt"], "runsForSession": prep.get("runsForSession"),
            "marketDirection": market_direction, "marketBasis": market_basis, "marketStrict": strict, "marketModerate": moderate,
            "alignmentMode": market.get("alignmentMode"),
            "denominator": {k: res.get(k) for k in ("discovered", "eligible", "evaluated", "qualifying", "candidatesChecked", "armed", "planErrors", "dataErrors")},
            "contextPassingRows": len(rows), "laneAStages": dict(stages), "laneAQualified": len(qualified),
            "experimentalMinRPasses": sum(1 for e in qualified if (e["laneA"]["experimental"] or {}).get("passes")),
            "feasibility": dict(Counter((e.get("feasibility") or {}).get("state") for e in qualified)),
            "rows": evaluated}


def render_markdown(report: dict) -> str:
    p = report["parameters"]
    basis = report["marketBasis"]
    lines = [f"# Lane A frozen replay — {report['start']} → {report['end']} (market basis: {basis})", "",
             ("Lane A's definition uses the **strict** read (both indices above their 8/21/50 EMAs). " if basis == "strict" else
              "**Variant for information only:** this run uses the preparation's Moderate read as the market direction, which is NOT Lane A's "
              "definition; it shows what the lane would have planned had the Practice Moderate experiment's direction been accepted. ") +
             "Both readings are recorded per session in the table.", "",
             f"Generated {report['generatedAt']} by `zargar.tools.cartel_lane_a_eval` (read-only) from the original preparation run of each "
             f"session and the frozen analysis runs it cited. Lane A parameters: base {p['base_sessions']} sessions, ceiling tests ≥ "
             f"{p['min_ceiling_touches']} within {p['touch_tolerance_pct']}%, confirmed pivots only, distance floor {p['min_target_distance_pct']}%, "
             f"experimental planning R ≥ {p['experimental_min_planning_r']} **recorded, inactive**. Feasibility from the newest chain snapshot dated before "
             f"the session with the effective cap ${report['feasibilityPolicy']['max_ask']:.2f}; `unknown_stale` where none exists.", "",
             "A `qualified` row is a planning verdict under Lane A's definition over frozen inputs. It is not an entry, a fill or an outcome; "
             "conclusions stop at the last supported stage. Only screen-and-context-passing rows can qualify (Lane A keeps those gates), so "
             "the rows below are the complete candidate set for the lane; the denominators are the preparation run's own counts.", "",
             "## Sessions", "",
             "| Session | Market strict / Moderate read | Discovered | Evaluated | Context-passing | Lane A qualified | Exp. 1.5R passes | Lane A stages | Feasibility of qualified | Current rules armed |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for s in report["sessions"]:
        d = s["denominator"]
        lines.append(f"| {s['session']} | {s['marketStrict']} / {s['marketModerate']} (used: {s['marketDirection']}) | {d.get('discovered')} | {d.get('evaluated')} | {s['contextPassingRows']} | "
                     f"**{s['laneAQualified']}** | {s['experimentalMinRPasses']} | {s['laneAStages']} | {s['feasibility'] or '—'} | {d.get('armed')} |")
    lines += ["", "## Rows (context-passing symbols per session)", ""]
    for s in report["sessions"]:
        lines += [f"### {s['session']} — market {s['marketDirection']}, preparation `{s['preparationId'][:8]}` (created {s['preparationCreatedAt'][:19]}Z; {s.get('runsForSession')} runs that session)", "",
                  "| Symbol | Current rules | Current setup / R | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (chain date) | Note |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for e in s["rows"]:
            la = e.get("laneA") or {}
            ct = (la.get("ceilingTests") or {})
            fe = e.get("feasibility") or {}
            exp = la.get("experimental") or {}
            r = f"{la['structuralR']:.2f} / {la['firstTargetPct']:.2f}%" if la.get("structuralR") is not None else "—"
            cur_r = f"{e['currentStructuralR']:.2f}" if isinstance(e.get("currentStructuralR"), (int, float)) else "—"
            note = (la.get("reasons") or [""])[0][:90] if not la.get("qualified") else (fe.get("note") or "")[:0]
            lines.append(f"| {e['symbol']} | {e['currentStatus']}{' → ' + e['shortlistStatus'] if e.get('shortlistStatus') else ''} | "
                         f"{e.get('currentSetup') or '—'} / {cur_r} | {la.get('stage')} | {ct.get('touches', '—')} | {r} | "
                         f"{'pass' if exp.get('passes') else 'fail' if exp.get('passes') is False else '—'} | "
                         f"{fe.get('state', '—')}{' (' + str(fe.get('observedAt')) + ')' if fe.get('observedAt') else ''} | {note} |")
        lines.append("")
    lines += ["## Reading", "",
              "- `direction` = the session was not strict-bullish or the row was a short candidate; Lane A does not plan it.",
              "- `context` / `base_family` = the existing gates or the `base` geometry did not pass in the frozen analysis.",
              "- `ceiling_tests` = the base ceiling was tested fewer than the required times (Lane A's one added source-backed requirement).",
              "- `confirmed_target` = no confirmed pivot above the trigger (the Fibonacci fallback is off in Lane A).",
              "- `distance_floor` = the existing 0.5% first-target floor; kept active.",
              "- Experimental 1.5R is recorded per qualified row and applied nowhere.",
              "- Feasibility `unknown_stale` means no dated chain observation exists for that name; the candidate stays in the denominator and no later stage is inferred."]
    return "\n".join(lines) + "\n"


async def run(args) -> dict:
    conn = await _connect(args.database_url)
    try:
        params = LaneAParameters(experimental_min_planning_r=args.experimental_min_r)
        policy = FeasibilityPolicy(max_ask=min(5.0, args.budget / 100))
        preps = await session_preparations(conn, args.start, args.end)
        sessions = []
        for session in sorted(preps):
            sessions.append(await evaluate_session(conn, session, preps[session], params, policy, market_basis=args.market_basis))
    finally:
        await conn.close()
    return {"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "start": args.start, "end": args.end,
            "marketBasis": args.market_basis,
            "parameters": params.model_dump(mode="json"), "feasibilityPolicy": policy.model_dump(mode="json"),
            "sessions": sessions, "note": "Read-only frozen replay; no arm, order or setting was touched."}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--start", default="2026-09-08")
    parser.add_argument("--end", default="2026-09-17")
    parser.add_argument("--experimental-min-r", type=float, default=1.5)
    parser.add_argument("--budget", type=float, default=500.0, help="premium budget used for the effective ask cap (equity cap not applied)")
    parser.add_argument("--market-basis", choices=("strict", "moderate"), default="strict",
                        help="strict = Lane A's definition; moderate = information-only variant using the preparation's Moderate read")
    parser.add_argument("--out-dir", default=None, help="write frozen-replay-<basis>.md/.json here")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = asyncio.run(run(args))
    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
        stem = f"frozen-replay-{args.market_basis}"
        with open(os.path.join(args.out_dir, stem + ".md"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render_markdown(report))
        slim = {**report, "sessions": [{**s, "rows": [{k: v for k, v in e.items() if k != "laneACandidate"} for e in s["rows"]]} for s in report["sessions"]]}
        with open(os.path.join(args.out_dir, stem + ".json"), "w", encoding="utf-8") as fh:
            json.dump(slim, fh, indent=1, default=str, sort_keys=True)
        print("written", os.path.join(args.out_dir, stem + ".md"))
    if args.json:
        json.dump(report, sys.stdout, indent=1, default=str)
    else:
        for s in report["sessions"]:
            print(f"{s['session']} market {s['marketDirection']} context-passing {s['contextPassingRows']} laneA qualified {s['laneAQualified']} stages {s['laneAStages']} feasibility {s['feasibility']}")


if __name__ == "__main__":
    main()
