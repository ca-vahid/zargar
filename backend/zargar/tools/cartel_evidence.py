"""Read-only Options Cartel evidence reconstruction from the runtime database.

Every connection opens with ``default_transaction_read_only = on``; the tool never
writes. It reconstructs, from persisted records only, what preparation saw, what an
armed plan decided, why a preflight refused, and what the stored minute tape looked
like. Output is a summary — identifiers, timestamps and derived numbers — never a
bulk dump. Use it to reproduce the 2026-09-17 proposal package
(``docs/techniques/options-cartel/reviews/2026-09-17-proposal/``).

    python -m zargar.tools.cartel_evidence plan e2e12438418bc82ff34c3b2c5a7f365b
    python -m zargar.tools.cartel_evidence preparation bc78bc51f42a46568b255568ff052428
    python -m zargar.tools.cartel_evidence buckets QS 2026-09-16 --plan e2e12438418bc82ff34c3b2c5a7f365b
    python -m zargar.tools.cartel_evidence coverage PLAB
    python -m zargar.tools.cartel_evidence quotes e2e12438418bc82ff34c3b2c5a7f365b

``--database-url`` overrides ``ZARGAR_DATABASE_URL``; ``--json`` emits machine-readable
output instead of text.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

MINUTE = 60_000
ET_OFFSET_HOURS = 4  # EDT; the sessions examined (September 2026) are all in daylight time
RTH_OPEN_UTC = timedelta(hours=9 + ET_OFFSET_HOURS, minutes=30)
RTH_MINUTES = 390


def _load(value):
    return json.loads(value) if isinstance(value, str) else value


def utc(ms: int | None) -> str:
    if not isinstance(ms, (int, float)):
        return str(ms)
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def et(ms: int | None) -> str:
    if not isinstance(ms, (int, float)):
        return str(ms)
    return (datetime.fromtimestamp(ms / 1000, tz=timezone.utc) - timedelta(hours=ET_OFFSET_HOURS)).strftime("%m-%d %H:%M ET")


def session_open_ms(session: str) -> int:
    day = datetime.strptime(session, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int((day + RTH_OPEN_UTC).timestamp() * 1000)


def bucketize(rows: list[dict], opens: int, step_minutes: int = 15, minutes: int = RTH_MINUTES) -> list[dict]:
    """Aggregate stored 1m rows into closed buckets, preferring an exchange row per minute.

    ``rows`` carry ``ts, open, high, low, close, volume, source``. A minute with both a
    sampled and an exchange row keeps the exchange one. Buckets with no minute are
    reported with ``n == 0`` so gaps stay visible.
    """
    by_minute: dict[int, dict] = {}
    for r in rows:
        cur = by_minute.get(r["ts"])
        if cur is None or (r["source"] == "exchange" and cur["source"] != "exchange"):
            by_minute[r["ts"]] = r
    out = []
    step = step_minutes * MINUTE
    for k in range(minutes // step_minutes):
        b0 = opens + k * step
        mins = [by_minute[t] for t in sorted(by_minute) if b0 <= t < b0 + step]
        if not mins:
            out.append({"slot": k, "start": b0, "n": 0})
            continue
        high = max(m["high"] for m in mins)
        low = min(m["low"] for m in mins)
        close = mins[-1]["close"]
        out.append({"slot": k, "start": b0, "n": len(mins), "exchange": sum(1 for m in mins if m["source"] == "exchange"),
                    "open": mins[0]["open"], "high": high, "low": low, "close": close,
                    "volume": int(sum(m["volume"] for m in mins)),
                    "closeLocationLong": (close - low) / (high - low) if high > low else None,
                    "closeLocationShort": (high - close) / (high - low) if high > low else None})
    return out


async def _connect(url: str):
    import asyncpg

    dsn = url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    await conn.execute("set default_transaction_read_only = on")
    return conn


# ----------------------------------------------------------------------------- plan

async def plan_report(conn, run_id: str) -> dict:
    arm = await conn.fetchrow("select * from technique_armed where run_id=$1", run_id)
    run = await conn.fetchrow("select id, symbol, mode, status, verdict, as_of, created_at, parent_run_id, result from technique_runs where id=$1", run_id)
    if run is None:
        raise SystemExit(f"no technique_runs row for {run_id}")
    result = _load(run["result"]) or {}
    plan = (result.get("plan") or {}).get("plan") or {}
    report: dict = {
        "runId": run_id, "symbol": run["symbol"], "createdAt": str(run["created_at"]), "parentRunId": run["parent_run_id"],
        "plan": {k: plan.get(k) for k in ("setup", "direction", "trigger", "invalidation", "targets", "first_session", "last_session", "created_at")},
        "entryPolicy": plan.get("entry"),
        "review": result.get("review"),
        "baselineSlots": len(plan.get("volume_baseline") or {}),
    }
    if arm:
        state = _load(arm["state"]) or {}
        config = _load(arm["config"]) or {}
        report["armed"] = {
            "status": arm["status"], "mode": arm["mode"], "planFor": arm["plan_for"], "portfolioId": arm["portfolio_id"],
            "createdAt": str(arm["created_at"]), "updatedAt": str(arm["updated_at"]),
            "phase": state.get("phase"), "expiresAt": utc(state.get("expiresAt")),
            "validUntil": utc((config.get("preparation") or {}).get("validUntil")),
            "contract": (config.get("execution") or {}).get("contract_symbol"),
            "contractPolicy": (config.get("execution") or {}).get("contract_policy"),
            "budget": (config.get("execution") or {}).get("budget"), "riskPct": (config.get("execution") or {}).get("risk_pct"),
            "sourceCounts": (state.get("dataEvidence") or {}).get("sourceCounts"),
            "decisions": [{"at": utc(d.get("at")), "decision": d.get("decision"), "reason": d.get("reason"),
                           "measurements": d.get("measurements")} for d in state.get("decisionHistory") or []],
            "signalHistory": state.get("signalHistory"),
            "lastExecutionResult": {k: v for k, v in (state.get("lastExecutionResult") or {}).items() if k != "report"},
        }
    events = await conn.fetch(
        "select ts, type, payload from events where aggregate_id=$1 or payload::text like $2 order by ts", run_id, f"%{run_id}%")
    trail = []
    for e in events:
        p = _load(e["payload"]) or {}
        if e["type"] == "TechniqueCartelPreflight":
            rep = p.get("report") or {}
            failed = [c["name"] for c in rep.get("checks", []) if not c.get("passed")]
            risk = rep.get("risk") or {}
            trail.append({"ts": str(e["ts"]), "type": e["type"], "passed": rep.get("passed"), "failedChecks": failed,
                          "riskPassed": risk.get("passed"), "expression": rep.get("expression"),
                          "riskDetails": [c for c in risk.get("checks", []) if c.get("detail")]})
        elif e["type"] == "TechniqueCartelStateChanged":
            last = p.get("lastDecision") or {}
            trail.append({"ts": str(e["ts"]), "type": e["type"], "action": p.get("action"), "status": p.get("status"),
                          "phase": p.get("phase"), "lastDecision": last.get("decision")})
        else:
            trail.append({"ts": str(e["ts"]), "type": e["type"], "payload": {k: p.get(k) for k in ("id", "status", "symbol", "qty", "limitPrice", "avgFillPrice", "verdict", "mode") if k in p}})
    report["events"] = trail
    attempts = await conn.fetch("select preparation_id, at, evidence from cartel_preparation_attempts where plan_id=$1 order by at", run_id)
    timeline, prev = [], None
    for a in attempts:
        ev = _load(a["evidence"]) or {}
        readiness = ev.get("lastReadiness") or {}
        audit = ((ev.get("selection") or {}).get("audit")) or {}
        key = (ev.get("status"), tuple(readiness.get("reasons") or []), readiness.get("terminalStatus"), audit.get("eligible"), audit.get("lowestOtherwiseEligibleAsk"))
        if key != prev:
            timeline.append({"at": utc(a["at"]), "preparationId": a["preparation_id"], "status": ev.get("status"), "reason": ev.get("reason"),
                             "readinessReasons": readiness.get("reasons"), "terminalStatus": readiness.get("terminalStatus"),
                             "contractAudit": {k: audit.get(k) for k in ("eligible", "expiriesChecked", "lowestOtherwiseEligibleAsk", "effectiveMaxAsk")},
                             "rejectedContracts": [(c.get("symbol"), c.get("ask"), c.get("reasons")) for c in (audit.get("rejectedCandidates") or [])[:6]]})
            prev = key
    report["attempts"] = {"count": len(attempts), "timeline": timeline}
    symbol = run["symbol"]
    orders = await conn.fetch("select id, symbol, side, qty, order_type, limit_price, status, filled_qty, avg_fill_price, created_at, updated_at from orders where technique='options_cartel' and symbol like $1 order by created_at", f"{symbol}%")
    report["orders"] = [dict(o, created_at=str(o["created_at"]), updated_at=str(o["updated_at"])) for o in orders]
    managed = await conn.fetch("select id, status, created_at, updated_at, state from managed_positions where technique='options_cartel' and symbol like $1 order by created_at", f"{symbol}%")
    report["managedPositions"] = [{"id": m["id"], "status": m["status"], "createdAt": str(m["created_at"]), "updatedAt": str(m["updated_at"]),
                                   "closeReason": (_load(m["state"]) or {}).get("closeReason"), "realizedPnl": (_load(m["state"]) or {}).get("realizedPnl"),
                                   "exits": [{k: x.get(k) for k in ("kind", "qty", "price", "status", "ts")} for x in (_load(m["state"]) or {}).get("exits", [])]}
                                  for m in managed]
    return report


def print_plan(rep: dict) -> None:
    p = rep["plan"]
    print(f"PLAN {rep['runId']} {rep['symbol']} created {rep['createdAt']} parent {rep['parentRunId']}")
    print(f"  {p['setup']} {p['direction']} trigger {p['trigger']} invalidation {p['invalidation']} targets {p['targets']} sessions {p['first_session']}..{p['last_session']}")
    if p.get("trigger") and p.get("invalidation") and p.get("targets"):
        sign = 1 if p["direction"] == "long" else -1
        risk = abs(p["trigger"] - p["invalidation"])
        room = (p["targets"][0] - p["trigger"]) * sign
        print(f"  structural: risk {risk:.4f} first-target room {room:.4f} ({room / p['trigger'] * 100:.2f}%) R {room / risk if risk else float('nan'):.3f}")
    print(f"  review: {json.dumps(rep.get('review'))[:300]}")
    print(f"  entry policy: {json.dumps(rep.get('entryPolicy'))}  baseline slots {rep['baselineSlots']}")
    arm = rep.get("armed")
    if arm:
        print(f"  ARMED {arm['status']} mode {arm['mode']} for {arm['planFor']} contract {arm['contract']} budget {arm['budget']} risk% {arm['riskPct']} validUntil {arm['validUntil']} expiresAt {arm['expiresAt']} tape sources {arm['sourceCounts']}")
        for d in arm["decisions"]:
            m = d.get("measurements") or {}
            extra = f" volx{m.get('volumeRatio'):.2f} loc {m.get('closeLocation'):.2f} R {m.get('firstTargetR'):.2f}" if m else ""
            print(f"    {d['at']} {d['decision']}: {d['reason']}{extra}")
        for s in arm.get("signalHistory") or []:
            print(f"    signal {utc(s.get('at'))} ref {s.get('referencePrice')} stop {s.get('stop')} risk {s.get('risk')} volx{s.get('volumeRatio'):.2f} loc {s.get('closeLocation'):.2f}")
        if arm.get("lastExecutionResult"):
            print(f"    last execution result: {json.dumps(arm['lastExecutionResult'])[:300]}")
    else:
        print("  never armed (no technique_armed row)")
    print(f"  EVENTS {len(rep['events'])}")
    for e in rep["events"]:
        if e["type"] == "TechniqueCartelPreflight":
            ex = e.get("expression") or {}
            print(f"    {e['ts'][:23]} PREFLIGHT passed={e['passed']} failed={e['failedChecks']} qty {ex.get('quantity')} bid {ex.get('bid')} ask {ex.get('ask')} delta {ex.get('delta')} riskDetails={e['riskDetails']}")
        elif e["type"] == "TechniqueCartelStateChanged":
            if e["action"] in ("observation_recovered", "history_gap_repaired"):
                continue
            print(f"    {e['ts'][:23]} {e['action']} status={e['status']} phase={e['phase']} last={e['lastDecision']}")
        else:
            print(f"    {e['ts'][:23]} {e['type']} {e['payload']}")
    print(f"  ATTEMPTS {rep['attempts']['count']} (deduplicated transitions)")
    for t in rep["attempts"]["timeline"]:
        print(f"    {t['at']} prep {t['preparationId'][:8]} {t['status']} | {t['reason'] or ''} | readiness {t['readinessReasons']} terminal {t['terminalStatus']} | contracts {t['contractAudit']} rejected {t['rejectedContracts'][:4]}")
    for o in rep["orders"]:
        print(f"  ORDER {o['id'][:8]} {o['side']} {o['qty']} {o['symbol']} {o['order_type']} lmt {o['limit_price']} -> {o['status']} filled {o['filled_qty']} @ {o['avg_fill_price']} ({o['created_at'][:19]} .. {o['updated_at'][:19]})")
    for m in rep["managedPositions"]:
        print(f"  MANAGED {m['id']} {m['status']} {m['createdAt'][:19]}..{m['updatedAt'][:19]} close={m['closeReason']} realized={m['realizedPnl']} exits={m['exits']}")


# ---------------------------------------------------------------------- preparation

async def preparation_report(conn, run_id: str) -> dict:
    run = await conn.fetchrow("select id, status, created_at, finished_at, result from technique_runs where id=$1 and mode='preparation'", run_id)
    if run is None:
        raise SystemExit(f"no preparation run {run_id}")
    r = _load(run["result"]) or {}
    rows = r.get("rows") or []
    statuses = Counter(x.get("status") for x in rows)
    blocked = []
    for x in rows:
        if x.get("status") in ("plan_blocked", "data_error"):
            vc = x.get("volumeCoverage") or {}
            counts = vc.get("sampleCounts") or {}
            blocked.append({"symbol": x.get("symbol"), "status": x.get("status"), "reason": (x.get("reason") or "")[:160],
                            "available": vc.get("available"), "expected": vc.get("expected"), "missingSlots": vc.get("missing"),
                            "usable": len(vc.get("usableEntryPeriods") or []), "historicalSessions": vc.get("historicalSessions"),
                            "openingSlotSamples": [counts.get(str(i)) for i in range(4)], "minSamples": vc.get("minSamples")})
    shortlist = [{k: s.get(k) for k in ("symbol", "status", "setup", "reason", "planId")} | {"structuralTargetR": (s.get("ranking") or {}).get("structuralTargetR"),
                 "firstTargetPct": (s.get("ranking") or {}).get("firstTargetPct")} for s in r.get("shortlist") or []]
    market = r.get("market") or {}
    return {"runId": run_id, "status": run["status"], "createdAt": str(run["created_at"]), "finishedAt": str(run["finished_at"]),
            "session": r.get("session"), "workspace": r.get("workspace"), "phase": r.get("phase"), "resumedFrom": r.get("resumedFrom"),
            "recovery": r.get("recovery"), "market": {k: market.get(k) for k in ("direction", "alignmentMode", "strictDirection")},
            "funnel": {"discovered": r.get("discovered"), "eligible": r.get("eligible"), "evaluated": r.get("evaluated"),
                       "qualifying": r.get("qualifying"), "candidatesChecked": r.get("candidatesChecked"), "candidateCheckLimit": r.get("candidateCheckLimit"),
                       "armed": r.get("armed"), "planErrors": r.get("planErrors"), "dataErrors": r.get("dataErrors"), "rowStatuses": dict(statuses)},
            "retained": r.get("retainedPlans"), "replaced": r.get("replacedPlans"), "shortlist": shortlist, "blocked": blocked,
            "message": r.get("message")}


def print_preparation(rep: dict) -> None:
    print(f"PREPARATION {rep['runId']} {rep['status']} {rep['createdAt'][:19]}..{rep['finishedAt'][:19]} session {rep['session']} {rep['workspace']} phase {rep['phase']} resumedFrom {rep['resumedFrom']}")
    print(f"  market {rep['market']} recovery {rep['recovery']}")
    print(f"  funnel {rep['funnel']}")
    print(f"  retained {rep['retained']} replaced {rep['replaced']}")
    for s in rep["shortlist"]:
        print(f"  shortlist {s['symbol']:6s} {s['status']:18s} {s['setup'] or '':16s} R {s['structuralTargetR']} room% {s['firstTargetPct']} plan {s['planId']} {s['reason'] or ''}")
    for b in rep["blocked"]:
        print(f"  blocked   {b['symbol']:6s} {b['status']:12s} available {b['available']}/{b['expected']} usable {b['usable']} opening-slot samples {b['openingSlotSamples']} (min {b['minSamples']}) sessions {b['historicalSessions']} | {b['reason']}")
    print(f"  message: {rep['message']}")


# -------------------------------------------------------------------------- buckets

async def buckets_report(conn, symbol: str, session: str, plan_id: str | None, step: int) -> dict:
    opens = session_open_ms(session)
    closes = opens + RTH_MINUTES * MINUTE
    rows = await conn.fetch("select ts, open, high, low, close, volume, source from bars where symbol=$1 and tf='1m' and ts >= $2::bigint and ts < $3::bigint order by ts",
                            symbol, opens, closes)
    table = bucketize([dict(r) for r in rows], opens, step)
    plan = None
    if plan_id:
        run = await conn.fetchrow("select result from technique_runs where id=$1", plan_id)
        plan = ((_load(run["result"]) or {}).get("plan") or {}).get("plan") if run else None
    if plan:
        sign = 1 if plan["direction"] == "long" else -1
        baseline = {int(k): v for k, v in (plan.get("volume_baseline") or {}).items()}
        previous = None
        for b in table:
            if b["n"] == 0:
                previous = None
                continue
            before = previous if previous is not None else b["open"]
            b["crossed"] = (before - plan["trigger"]) * sign <= 0 < (b["close"] - plan["trigger"]) * sign
            base = baseline.get(b["slot"])
            b["baseline"] = base
            b["volumeRatio"] = b["volume"] / base if base else None
            b["closeLocation"] = b["closeLocationLong"] if sign == 1 else b["closeLocationShort"]
            b["targetPassed"] = (b["close"] - plan["targets"][0]) * sign >= 0
            previous = b["close"]
    return {"symbol": symbol, "session": session, "stepMinutes": step, "rawRows": len(rows), "plan": plan_id,
            "trigger": plan.get("trigger") if plan else None, "direction": plan.get("direction") if plan else None, "buckets": table}


def print_buckets(rep: dict) -> None:
    print(f"BUCKETS {rep['symbol']} {rep['session']} {rep['stepMinutes']}m from {rep['rawRows']} stored 1m rows; plan {rep['plan']} trigger {rep['trigger']} {rep['direction'] or ''}")
    print("  start(ET) n  ex   open     high     low      close    volume    | crossed volxbase  closeLoc targetPassed")
    for b in rep["buckets"]:
        if b["n"] == 0:
            print(f"  {et(b['start'])[6:11]}  0")
            continue
        extra = ""
        if "crossed" in b:
            vr = f"{b['volumeRatio']:.2f}" if b["volumeRatio"] is not None else "n/a"
            loc = f"{b['closeLocation']:.2f}" if b["closeLocation"] is not None else "n/a"
            extra = f"| {'CROSS' if b['crossed'] else '     '} {vr:>6} {loc:>6} {'passed' if b['targetPassed'] else ''}"
        print(f"  {et(b['start'])[6:11]} {b['n']:2d} {b['exchange']:2d} {b['open']:8.3f} {b['high']:8.3f} {b['low']:8.3f} {b['close']:8.3f} {b['volume']:9d} {extra}")


# ------------------------------------------------------------------------- coverage

async def coverage_report(conn, symbol: str) -> dict:
    rows = await conn.fetch("select timeframe, observed_at, start_ms, end_ms, payload from cartel_history_cache where symbol=$1 order by timeframe, observed_at desc", symbol)
    daily: dict[str, int] = {}
    out: dict = {"symbol": symbol, "caches": []}
    for r in rows:
        p = _load(r["payload"]) or {}
        bars = p.get("bars") or []
        entry = {"timeframe": r["timeframe"], "observedAt": utc(r["observed_at"]), "start": utc(r["start_ms"]), "end": utc(r["end_ms"]),
                 "provider": p.get("provider"), "provenance": p.get("provenance"), "bars": len(bars)}
        if r["timeframe"] == "1d":
            for b in bars:
                daily[et(b[0])[:5]] = b[5]
        if r["timeframe"] == "1m" and bars:
            per: dict[str, list] = defaultdict(lambda: [0, 0, set()])
            for b in bars:
                d = et(b[0])[:5]
                per[d][0] += 1
                per[d][1] += b[5] or 0
                per[d][2].add(b[6])
            entry["sessions"] = [{"session": d, "minutes": per[d][0], "minuteVolume": per[d][1], "dailyVolume": daily.get(d),
                                  "ratioPct": round(per[d][1] / daily[d] * 100, 1) if daily.get(d) else None, "sources": sorted(x for x in per[d][2] if x)}
                                 for d in sorted(per)]
        out["caches"].append(entry)
    return out


def print_coverage(rep: dict) -> None:
    print(f"COVERAGE {rep['symbol']}: {len(rep['caches'])} cache rows")
    for c in rep["caches"]:
        print(f"  tf {c['timeframe']} observed {c['observedAt']} range {c['start'][:10]}..{c['end']} provider {c['provider']} bars {c['bars']}")
        print(f"     provenance {json.dumps(c['provenance'])}")
        for s in c.get("sessions") or []:
            print(f"     {s['session']} minutes {s['minutes']:3d}/390 minute-volume {s['minuteVolume']:>10} daily {s['dailyVolume'] or '?':>10} ratio {s['ratioPct'] if s['ratioPct'] is not None else 'n/a'}% {s['sources']}")


# --------------------------------------------------------------------------- quotes

async def quotes_report(conn, run_id: str) -> dict:
    rows = await conn.fetch(
        "select contract, (available_at/900000)*900000 b, count(*) n, avg(bid) bid, avg(ask) ask, "
        "min((ask-bid)/nullif((ask+bid)/2,0))*100 minsp, avg((ask-bid)/nullif((ask+bid)/2,0))*100 avgsp, max((ask-bid)/nullif((ask+bid)/2,0))*100 maxsp, "
        "min(bid_size) minbs, max(bid_size) maxbs, min(ask_size) minas, max(ask_size) maxas "
        "from options_cartel_quotes where run_id=$1 group by contract, b order by contract, b", run_id)
    total = await conn.fetchval("select count(*) from options_cartel_quotes where run_id=$1", run_id)
    return {"runId": run_id, "observations": total,
            "buckets": [{"contract": r["contract"], "start": utc(r["b"]), "n": r["n"], "bid": round(r["bid"], 3), "ask": round(r["ask"], 3),
                         "spreadPctMin": round(r["minsp"], 1), "spreadPctAvg": round(r["avgsp"], 1), "spreadPctMax": round(r["maxsp"], 1),
                         "bidSize": [r["minbs"], r["maxbs"]], "askSize": [r["minas"], r["maxas"]]} for r in rows]}


def print_quotes(rep: dict) -> None:
    print(f"QUOTES for plan {rep['runId']}: {rep['observations']} observations (mid-basis spread %, per 15-minute bucket, UTC)")
    for b in rep["buckets"]:
        print(f"  {b['contract']} {b['start'][5:16]} n={b['n']:3d} bid {b['bid']:.3f} ask {b['ask']:.3f} spread min {b['spreadPctMin']} avg {b['spreadPctAvg']} max {b['spreadPctMax']} sizes bid {b['bidSize']} ask {b['askSize']}")


# ------------------------------------------------------------------------------ cli

async def _run(args) -> None:
    from ..config import AppConfig

    url = args.database_url or AppConfig().database_url
    conn = await _connect(url)
    try:
        if args.command == "plan":
            rep = await plan_report(conn, args.run_id)
            printer = print_plan
        elif args.command == "preparation":
            rep = await preparation_report(conn, args.run_id)
            printer = print_preparation
        elif args.command == "buckets":
            rep = await buckets_report(conn, args.symbol, args.session, args.plan, args.step)
            printer = print_buckets
        elif args.command == "coverage":
            rep = await coverage_report(conn, args.symbol)
            printer = print_coverage
        else:
            rep = await quotes_report(conn, args.run_id)
            printer = print_quotes
    finally:
        await conn.close()
    if args.json:
        json.dump(rep, sys.stdout, indent=1, default=str)
        print()
    else:
        printer(rep)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan", help="plan geometry, armed decisions, preflights, attempts, orders")
    p.add_argument("run_id")
    p = sub.add_parser("preparation", help="funnel counts, shortlist and blocked candidates of one preparation run")
    p.add_argument("run_id")
    p = sub.add_parser("buckets", help="closed buckets from stored 1m bars for a symbol/session")
    p.add_argument("symbol")
    p.add_argument("session", help="YYYY-MM-DD (ET)")
    p.add_argument("--plan", default=None, help="plan run id: adds crossing, baseline ratio and close location")
    p.add_argument("--step", type=int, default=15)
    p = sub.add_parser("coverage", help="cached history provenance and per-session minute coverage")
    p.add_argument("symbol")
    p = sub.add_parser("quotes", help="recorded option quote spreads for a plan")
    p.add_argument("run_id")
    args = parser.parse_args(argv)
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
