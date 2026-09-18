"""Frozen, order-free Lane A replay over past Cartel preparation runs (revision 2, 2026-09-18).

Read-only. For one Practice book and one session at a time it:

1. selects the **preparation lineage**: every preparation run of that session, workspace and book,
   and within it the *original* run — the earliest run whose market read is known and that
   evaluated the universe (later resumes and pre-open retries are reported as **later recovery**,
   never merged into original-time eligibility);
2. takes the **complete population**: every frozen analysis run whose ``parent_run_id`` is the
   original run (one per discovered listing), not the preparation's own row statuses;
3. classifies each analysis against **Lane A's own gates** (direction, screen, context, base
   family, ceiling tests, confirmed target, distance floor) and records separately what the
   *old planner* did with it (its row status and shortlist status), so screen/context rejection,
   old-planner rejection, missing analysis and unavailable evidence are distinct;
4. for Lane A-qualified rows, classifies **hypothetical planning-time feasibility under stated
   assumptions**: the nightly chain snapshot of the previous exchange session (observed by the
   16:30 ET research job, so available to a nightly preparation), the preparation's **saved**
   contract limits, and the effective ask cap min(policy, budget/100, equity x risk%/100) with the
   book equity last persisted before the preparation ran. Snapshots have a date only, so this is
   labelled hypothetical, never historical affordability; older or missing snapshots are
   ``unknown_stale``.

    python -m zargar.tools.cartel_lane_a_eval --database-url ... --portfolio 0b48ed48... --start 2026-09-08 --end 2026-09-17 --out-dir <dir>

Nothing here arms, orders or changes a setting. A ``qualified`` row is a planning verdict; no entry,
fill or outcome is inferred from it.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
from collections import Counter

from ..marketstructure.market_calendar import previous_trading_day
from ..techniques.options_cartel.data import DailyBar
from ..techniques.options_cartel.lane_a import FeasibilityPolicy, LaneAParameters, effective_cap, feasibility_from_chain, lane_a_review

MARKET_GATE = "Market agrees with direction"
STAGE_ORDER = ("direction", "screen", "context", "base_family", "ceiling_tests", "confirmed_target", "distance_floor", "qualified",
               "missing_analysis", "unavailable_evidence")


def _load(v):
    return json.loads(v) if isinstance(v, str) else v


async def _connect(url: str):
    import asyncpg

    conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
    await conn.execute("set default_transaction_read_only = on")
    return conn


# ------------------------------------------------------------------- pure selection

def choose_original(runs: list[dict]) -> dict | None:
    """The original planning run of a session: earliest run with a known market read that evaluated listings.

    ``runs`` are dicts with ``id, createdAt, market, evaluated, rows`` (already restricted to one
    session, workspace and book, ordered by creation). Benchmark-wait runs and runs with an
    unknown market read are not candidates. Ties are impossible (ordered), so the earliest wins;
    later runs are lineage, not replacements.
    """
    for r in runs:
        if r.get("market") in ("long", "short", "mixed") and (r.get("evaluated") or 0) > 0 and r.get("rows"):
            return r
    return None


def classify_analysis(analysis: dict, screen: dict, direction: str, market_direction: str) -> tuple[str, list[str]]:
    """Lane A pre-stages that need no history: direction, screen (non-market gates), context."""
    if direction != "long" or market_direction != "long":
        return "direction", [f"direction={direction}, market={market_direction}"]
    failed_gates = [g.get("label") for g in screen.get("gates") or [] if g.get("status") != "pass" and g.get("label") != MARKET_GATE]
    if failed_gates:
        return "screen", failed_gates
    checks = analysis.get("checks") or []
    failed = [c.get("name") for c in checks if c.get("status") != "pass" and c.get("name") != "Market/universe screen"]
    if failed or not checks:
        return "context", failed or ["no checks recorded"]
    return "history", []


def old_planner_outcome(row_status: str | None, shortlist_status: str | None, context_passed: bool) -> str:
    """What the current planner did with the symbol, in classes the review asked for."""
    if row_status is None:
        return "not_in_preparation_rows"
    if row_status == "data_error":
        return "unavailable_evidence"
    if row_status == "filtered":
        return "old_planner_rejected" if context_passed else "screen_or_context_rejected"
    if row_status == "plan_blocked":
        return "old_planner_blocked"
    if row_status == "candidate":
        return f"old_planner_candidate:{shortlist_status or 'not_shortlisted'}"
    return row_status


# --------------------------------------------------------------------- data access

async def session_runs(conn, session: str, workspace: str, portfolio: str) -> list[dict]:
    rows = await conn.fetch(
        "select id, created_at, config, result from technique_runs where technique='options_cartel' and mode='preparation' and status='done' "
        "and result->>'session'=$1 and result->>'workspace'=$2 and result->>'portfolioId'=$3 order by created_at",
        session, workspace, portfolio)
    out = []
    for r in rows:
        res = _load(r["result"]) or {}
        market = (res.get("market") or {}).get("strictDirection") or (res.get("market") or {}).get("direction")
        out.append({"id": r["id"], "createdAt": str(r["created_at"]), "createdAtMs": int(r["created_at"].timestamp() * 1000),
                    "phase": res.get("phase"), "market": market, "moderate": (res.get("market") or {}).get("direction"),
                    "alignmentMode": (res.get("market") or {}).get("alignmentMode"), "evaluated": res.get("evaluated"), "armed": res.get("armed"),
                    "resumedFrom": res.get("resumedFrom"), "rows": res.get("rows") or [], "shortlist": res.get("shortlist") or [],
                    "config": _load(r["config"]) or {}, "denominator": {k: res.get(k) for k in ("discovered", "eligible", "evaluated", "qualifying", "candidatesChecked", "armed", "planErrors", "dataErrors")}})
    return out


async def population(conn, prep_id: str, cited_ids: list[str]) -> tuple[list[dict], dict]:
    """Every frozen analysis the original run evaluated or reused.

    A resumed run reuses analyses created by an earlier run of the same lineage (their
    ``parent_run_id`` is that earlier run), so the population is the union of analyses parented by
    the original run and analyses its rows cite. One analysis per symbol; a cited analysis wins
    over an uncited one because it is the one the run actually judged.
    """
    rows = await conn.fetch(
        "select id, symbol, as_of, created_at, parent_run_id, config->'inputs'->>'direction' direction, result->'screen' screen, result->'analysis' analysis "
        "from technique_runs where technique='options_cartel' and mode='analysis' and (parent_run_id=$1 or id = any($2::text[])) order by symbol, created_at",
        prep_id, cited_ids)
    cited = set(cited_ids)
    by_symbol: dict[str, dict] = {}
    for r in rows:
        entry = {"id": r["id"], "symbol": r["symbol"], "asOf": r["as_of"], "createdAt": str(r["created_at"]), "direction": r["direction"],
                 "parentRunId": r["parent_run_id"], "cited": r["id"] in cited, "reusedFromEarlierRun": r["parent_run_id"] != prep_id,
                 "screen": _load(r["screen"]) or {}, "analysis": _load(r["analysis"]) or {}}
        cur = by_symbol.get(r["symbol"])
        if cur is None or (entry["cited"] and not cur["cited"]):
            by_symbol[r["symbol"]] = entry
    out = sorted(by_symbol.values(), key=lambda e: e["symbol"])
    return out, {"total": len(out), "cited": sum(e["cited"] for e in out), "reusedFromEarlierRun": sum(e["reusedFromEarlierRun"] for e in out),
                 "parentedButUncited": sum(1 for e in out if not e["cited"])}


async def analysis_history(conn, analysis_id: str):
    r = await conn.fetchrow("select config from technique_runs where id=$1", analysis_id)
    cfg = _load(r["config"]) or {}
    inputs = cfg.get("inputs") or {}
    return [DailyBar.model_validate(b) for b in inputs.get("history") or []], inputs.get("as_of_ms"), cfg.get("inputSha256")


async def chain_on(conn, underlying: str, date: dt.date):
    rows = await conn.fetch("select occ, expiry, strike, option_type, delta, bid, ask, open_interest from option_chain_snapshots where underlying=$1 and date=$2",
                            underlying, date.isoformat())
    return [dict(r) for r in rows]


async def equity_before(conn, portfolio: str, at_ms: int):
    r = await conn.fetchrow("select ts, equity from equity_points where portfolio_id=$1 and ts <= $2::bigint order by ts desc limit 1", portfolio, at_ms)
    return (r["equity"], r["ts"]) if r else (None, None)


# ---------------------------------------------------------------------- evaluation

async def evaluate_session(conn, session: str, runs: list[dict], params: LaneAParameters, *, market_basis: str, portfolio: str) -> dict:
    original = choose_original(runs)
    lineage = [{k: r[k] for k in ("id", "createdAt", "phase", "market", "moderate", "armed", "resumedFrom")} for r in runs]
    if original is None:
        return {"session": session, "original": None, "lineage": lineage, "rows": [], "note": "No preparation run with a known market read evaluated this session."}
    market_direction = original["market"] if market_basis == "strict" else original["moderate"]
    saved_policy = (original["config"].get("policy") or {})
    contract_policy = saved_policy.get("contract_policy") or {}
    equity, equity_ts = await equity_before(conn, portfolio, original["createdAtMs"])
    cap = effective_cap(contract_policy.get("max_ask", 5.0), saved_policy.get("budget"), equity, saved_policy.get("risk_pct"))
    policy = FeasibilityPolicy(dte_min=contract_policy.get("dte_min", 21), dte_max=contract_policy.get("dte_max", 90), target_dte=contract_policy.get("target_dte", 45),
                               min_abs_delta=contract_policy.get("min_abs_delta", 0.25), max_spread_pct=contract_policy.get("max_spread_pct", 20.0),
                               min_open_interest=contract_policy.get("min_open_interest", 100), max_ask=cap["maxAsk"])
    first_session = dt.date.fromisoformat(session)
    snapshot_date = previous_trading_day(first_session)
    row_status = {}
    for x in original["rows"]:
        row_status.setdefault(x.get("symbol"), []).append(x.get("status"))
    shortlist = {s.get("symbol"): s.get("status") for s in original["shortlist"]}
    later = {}
    for r in runs:
        if r["id"] == original["id"] or r["createdAtMs"] <= original["createdAtMs"]:
            continue
        for s in r["shortlist"]:
            later.setdefault(s.get("symbol"), []).append({"run": r["id"][:8], "at": r["createdAt"][:19], "status": s.get("status")})
    cited_ids = [x.get("analysisId") for x in original["rows"] if x.get("analysisId")]
    analyses, population_stats = await population(conn, original["id"], cited_ids)
    covered = set()
    rows_out = []
    for a in analyses:
        covered.add(a["symbol"])
        context_passed = bool(a["analysis"].get("checks")) and all(c.get("status") == "pass" for c in a["analysis"].get("checks") or [])
        statuses = row_status.get(a["symbol"]) or []
        primary = "data_error" if statuses == ["data_error"] else next((s for s in ("candidate", "plan_blocked", "filtered") if s in statuses), statuses[0] if statuses else None)
        entry = {"symbol": a["symbol"], "analysisId": a["id"], "analysisCreatedAt": a["createdAt"], "direction": a["direction"],
                 "screenPassed": a["screen"].get("screenPassed"), "researchPassed": a["screen"].get("researchPassed"), "contextPassed": context_passed,
                 "oldPlanner": old_planner_outcome(primary, shortlist.get(a["symbol"]), context_passed), "oldPlannerRowStatuses": statuses,
                 "laterRecovery": later.get(a["symbol"])}
        stage, reasons = classify_analysis(a["analysis"], a["screen"], a["direction"], market_direction)
        if stage != "history":
            entry["laneA"] = {"stage": stage, "qualified": False, "reasons": reasons}
            rows_out.append(entry)
            continue
        history, as_of, sha = await analysis_history(conn, a["id"])
        entry["inputs"] = {"dailyBars": len(history), "inputSha256": sha, "analysisAsOf": dt.datetime.fromtimestamp((as_of or a["asOf"]) / 1000, tz=dt.timezone.utc).isoformat(),
                           "availability": f"frozen analysis run created {a['createdAt'][:19]}Z"}
        review = lane_a_review(a["analysis"], history, as_of_ms=as_of or a["asOf"], direction=a["direction"], market_direction=market_direction, parameters=params)
        entry["laneA"] = {k: review.get(k) for k in ("qualified", "stage", "reasons", "structuralR", "firstTargetPct", "experimental", "ceilingTests")}
        entry["laneACandidate"] = review.get("candidate")
        if review["qualified"]:
            chain = await chain_on(conn, a["symbol"], snapshot_date)
            if not chain:
                entry["feasibility"] = {"state": "unknown_stale", "observedAt": None, "snapshotDateRequired": snapshot_date.isoformat(),
                                        "note": "No nightly chain snapshot for the previous exchange session; planning-time quotes were not recorded."}
            else:
                fe = feasibility_from_chain(chain, direction="long", first_session=first_session, policy=policy, observed_at=snapshot_date.isoformat())
                fe["basis"] = ("hypothetical: nightly snapshot dated the previous session (research job ~16:30 ET), saved preparation limits, "
                               f"effective cap ${cap['maxAsk']:.2f} bound by {cap['binding']}")
                entry["feasibility"] = fe
        rows_out.append(entry)
    for symbol, statuses in row_status.items():
        if symbol in covered:
            continue
        stage = ("unavailable_evidence" if statuses == ["data_error"] else
                 "prefiltered" if statuses == ["prefiltered"] else "missing_analysis")
        rows_out.append({"symbol": symbol, "analysisId": None, "oldPlanner": old_planner_outcome(statuses[0], shortlist.get(symbol), False),
                         "oldPlannerRowStatuses": statuses, "laneA": {"stage": stage, "qualified": False, "reasons": [f"preparation row statuses {statuses}"]},
                         "laterRecovery": later.get(symbol)})
    stages = Counter(e["laneA"]["stage"] for e in rows_out)
    qualified = [e for e in rows_out if e["laneA"].get("qualified")]
    return {"session": session, "marketBasis": market_basis, "marketDirection": market_direction, "marketStrict": original["market"], "marketModerate": original["moderate"],
            "original": {k: original[k] for k in ("id", "createdAt", "phase", "market", "moderate", "alignmentMode", "armed", "denominator")},
            "lineage": lineage, "laterRecoverySymbols": len(later),
            "savedPolicy": {"budget": saved_policy.get("budget"), "riskPct": saved_policy.get("risk_pct"), "contract": contract_policy},
            "effectiveCap": {**cap, "equity": equity, "equityAt": dt.datetime.fromtimestamp(equity_ts / 1000, tz=dt.timezone.utc).isoformat() if equity_ts else None},
            "population": len(analyses), "populationStats": population_stats, "extraRows": len(rows_out) - len(analyses),
            "laneAStages": dict(stages), "laneAQualified": len(qualified),
            "experimentalMinRPasses": sum(1 for e in qualified if (e["laneA"].get("experimental") or {}).get("passes")),
            "oldPlanner": dict(Counter(e["oldPlanner"] for e in rows_out)),
            "feasibility": dict(Counter((e.get("feasibility") or {}).get("state") for e in qualified)),
            "rows": rows_out}


def render_markdown(report: dict) -> str:
    basis = report["marketBasis"]
    p = report["parameters"]
    lines = [f"# Lane A frozen replay — {report['start']} → {report['end']} (book {report['portfolio'][:8]}, {report['workspace']}, market basis: {basis})", "",
             ("Lane A's definition uses the **strict** market read. " if basis == "strict" else
              "**Information-only variant:** the preparation's Moderate read is used as the market direction, which is NOT Lane A's definition. ") +
             f"Generated {report['generatedAt']} by `zargar.tools.cartel_lane_a_eval` (read-only). Population = every frozen analysis run under the "
             f"session's original preparation run; the old planner's own row/shortlist statuses are reported beside Lane A's verdict, never used as the "
             f"denominator. Lane A parameters: base {p['base_sessions']} sessions, ceiling tests ≥ {p['min_ceiling_touches']} within {p['touch_tolerance_pct']}%, "
             f"confirmed pivots only, distance floor {p['min_target_distance_pct']}%, experimental planning R ≥ {p['experimental_min_planning_r']} **recorded, inactive**.", "",
             "Feasibility is **hypothetical under stated assumptions**: the nightly chain snapshot dated the previous exchange session (research job ~16:30 ET, "
             "date-only records), the preparation's saved contract limits, and the effective cap min(policy, budget/100, equity x risk%/100) with the book equity "
             "last persisted before the run. It is not historical affordability. A `qualified` row is a planning verdict, not an entry, fill or outcome.", "",
             "## Sessions", "",
             "| Session | Original run | Market strict / Moderate (used) | Population | Lane A stages | Qualified | Exp. 1.5R passes | Feasibility of qualified | Old planner armed | Later runs |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for s in report["sessions"]:
        if not s.get("original"):
            lines.append(f"| {s['session']} | — | — | — | — | — | — | — | — | {len(s['lineage'])} ({s['note']}) |")
            continue
        o = s["original"]
        ps = s["populationStats"]
        lines.append(f"| {s['session']} | `{o['id'][:8]}` {o['createdAt'][:16]}Z {o['phase']} | {s['marketStrict']} / {s['marketModerate']} ({s['marketDirection']}) | {s['population']} ({ps['reusedFromEarlierRun']} reused from earlier runs; +{s['extraRows']} rows without analysis) | "
                     f"{s['laneAStages']} | **{s['laneAQualified']}** | {s['experimentalMinRPasses']} | {s['feasibility'] or '—'} | {o['armed']} | {len(s['lineage']) - 1} |")
    lines += ["", "## Old planner outcome of the same population", "", "| Session | Classes |", "|---|---|"]
    for s in report["sessions"]:
        if s.get("original"):
            lines.append(f"| {s['session']} | {s['oldPlanner']} |")
    lines += ["", "## Lineage (all preparation runs per session; later runs are recovery, not original-time eligibility)", ""]
    for s in report["sessions"]:
        lines.append(f"- **{s['session']}**: " + "; ".join(f"`{r['id'][:8]}` {r['createdAt'][:16]}Z {r['phase']} market {r['market']}/{r['moderate']} armed {r['armed']}" + (f" (resumed from `{r['resumedFrom'][:8]}`)" if r.get('resumedFrom') else "") for r in s["lineage"]))
    lines += ["", "## Rows that reached the history stages (screen and context passed under Lane A)", ""]
    for s in report["sessions"]:
        if not s.get("original"):
            continue
        rows = [e for e in s["rows"] if e["laneA"]["stage"] in ("base_family", "ceiling_tests", "confirmed_target", "distance_floor", "qualified")]
        lines += [f"### {s['session']} — {len(rows)} rows; saved limits {s['savedPolicy']['contract']}; effective cap ${s['effectiveCap']['maxAsk']:.2f} ({s['effectiveCap']['binding']}; equity {s['effectiveCap']['equity']} at {s['effectiveCap']['equityAt']})", "",
                  "| Symbol | Old planner | Later recovery | Lane A stage | Ceiling tests | Lane A R / room% | Exp. 1.5R | Feasibility (snapshot date) | Failure sets | Note |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for e in rows:
            la = e["laneA"]; ct = la.get("ceilingTests") or {}; fe = e.get("feasibility") or {}; exp = la.get("experimental") or {}
            r = f"{la['structuralR']:.2f} / {la['firstTargetPct']:.2f}%" if la.get("structuralR") is not None else "—"
            later = ", ".join(f"{x['status']}@{x['at'][11:16]}" for x in (e.get("laterRecovery") or [])[:3]) or "—"
            note = (la.get("reasons") or [""])[0][:80] if not la.get("qualified") else ""
            lines.append(f"| {e['symbol']} | {e['oldPlanner']} | {later} | {la['stage']} | {ct.get('touches', '—')} | {r} | "
                         f"{'pass' if exp.get('passes') else 'fail' if exp.get('passes') is False else '—'} | {fe.get('state', '—')}{' (' + str(fe.get('observedAt')) + ')' if fe.get('observedAt') else ''} | "
                         f"{fe.get('failureSets', '') or ''} | {note} |")
        lines.append("")
    lines += ["## Reading", "",
              "- `direction`: not a strict-bullish session or not a long analysis — Lane A does not plan it.",
              "- `screen` / `context`: the existing (unchanged) gates failed in the frozen analysis; the failed gate or check is named.",
              "- `base_family`, `ceiling_tests`, `confirmed_target`, `distance_floor`: Lane A's own stages.",
              "- `missing_analysis` / `unavailable_evidence` / `prefiltered`: a preparation row with no frozen analysis run, a daily-history error, or a listing the (then strict) industry pre-filter excluded before any history was fetched.",
              "- Population = analyses parented by the original run plus analyses its rows cite (a resumed run reuses analyses an earlier run created); the reused count is shown per session.",
              "- Old planner classes: `old_planner_rejected` = context passed but the current automatic review filtered it; `old_planner_blocked` = plan_blocked; `old_planner_candidate:<shortlist status>`.",
              "- Later recovery lists shortlist statuses from later runs of the same session; it never changes the original-time verdict.",
              "- Feasibility `unknown_stale`: no nightly snapshot for the previous session; the row stays in the denominator and no later stage is inferred."]
    return "\n".join(lines) + "\n"


async def run(args) -> dict:
    conn = await _connect(args.database_url)
    try:
        params = LaneAParameters(experimental_min_planning_r=args.experimental_min_r)
        sessions_out = []
        dates = await conn.fetch(
            "select distinct result->>'session' s from technique_runs where technique='options_cartel' and mode='preparation' and status='done' "
            "and result->>'session' between $1 and $2 and result->>'workspace'=$3 and result->>'portfolioId'=$4 order by 1", args.start, args.end, args.workspace, args.portfolio)
        for d in dates:
            runs = await session_runs(conn, d["s"], args.workspace, args.portfolio)
            sessions_out.append(await evaluate_session(conn, d["s"], runs, params, market_basis=args.market_basis, portfolio=args.portfolio))
    finally:
        await conn.close()
    return {"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "start": args.start, "end": args.end,
            "workspace": args.workspace, "portfolio": args.portfolio, "marketBasis": args.market_basis,
            "parameters": params.model_dump(mode="json"), "sessions": sessions_out, "note": "Read-only frozen replay; no arm, order or setting was touched."}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--portfolio", default="0b48ed48de2f4030b49942b52858356d", help="Practice book id whose preparation lineage is replayed")
    parser.add_argument("--workspace", default="practice")
    parser.add_argument("--start", default="2026-09-08")
    parser.add_argument("--end", default="2026-09-17")
    parser.add_argument("--experimental-min-r", type=float, default=1.5)
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
            if s.get("original"):
                print(f"{s['session']} original {s['original']['id'][:8]} market {s['marketDirection']} population {s['population']} stages {s['laneAStages']} qualified {s['laneAQualified']} exp {s['experimentalMinRPasses']} feasibility {s['feasibility']} oldPlanner {s['oldPlanner']}")
            else:
                print(f"{s['session']} no original run ({len(s['lineage'])} runs)")


if __name__ == "__main__":
    main()
