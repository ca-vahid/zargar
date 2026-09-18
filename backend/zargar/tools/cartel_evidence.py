"""Read-only Options Cartel evidence reconstruction from the runtime database.

Every database connection opens with ``default_transaction_read_only = on``; the tool never
writes to the database. It reconstructs, from persisted records only, what preparation saw,
what an armed plan decided, why a preflight refused, and what the minute tape looked like.
Output is a summary (identifiers, timestamps, derived numbers), never a bulk dump. It supports
``docs/techniques/options-cartel/reviews/2026-09-17-proposal/``.

    python -m zargar.tools.cartel_evidence plan e2e12438418bc82ff34c3b2c5a7f365b
    python -m zargar.tools.cartel_evidence preparation bc78bc51f42a46568b255568ff052428
    python -m zargar.tools.cartel_evidence replay e2e12438418bc82ff34c3b2c5a7f365b
    python -m zargar.tools.cartel_evidence buckets QS 2026-09-16 --plan e2e12438418bc82ff34c3b2c5a7f365b
    python -m zargar.tools.cartel_evidence coverage PLAB
    python -m zargar.tools.cartel_evidence quotes e2e12438418bc82ff34c3b2c5a7f365b
    python -m zargar.tools.cartel_evidence latency --since 2026-09-08
    python -m zargar.tools.cartel_evidence alpaca-minutes PLAB 2026-09-16 --env-file ../backend/.env

Two tapes exist for a plan and are never blended:

* the **final arm tape**: ``technique_armed.state.minutes`` as last saved on the arm (only for
  armed plans, only the last observed session) — not what the observer saw at each decision;
* the **stored tape**: the shared ``bars`` table as it stands *now*. Stored rows carry no
  receipt time, so a minute that is ``exchange`` today may have been ``sampled`` or absent when
  the decision was made. ``replay`` runs the engine's own ``read_entry`` over each tape.

Minute classes: ``exchange`` (venue bar), ``sampled-only`` (quote-derived bar without a venue
bar; its volume is a Yahoo cumulative-volume delta, not proof of trades), ``absent`` (no row).
Nothing is called an empty or no-trade minute from bar data alone; journaled decisions stay the
authority for what happened. ``alpaca-minutes`` is the
one command that consults the provider's trade tape (read-only market data, not the runtime).

Sessions use the exchange calendar (``marketstructure.sessions.session_bounds``, early closes
included) and the America/New_York zone; nothing is fixed to EDT or 390 minutes.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from collections import Counter, defaultdict

MINUTE = 60_000
CONFIRMATION_MAX_AGE_MS = 120_000  # observer.on_minute_bar drops bars older than this


def _load(value):
    return json.loads(value) if isinstance(value, str) else value


def _et():
    from ..marketstructure.sessions import ET

    return ET


def utc(ms) -> str:
    if not isinstance(ms, (int, float)):
        return str(ms)
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def et(ms) -> str:
    if not isinstance(ms, (int, float)):
        return str(ms)
    return dt.datetime.fromtimestamp(ms / 1000, _et()).strftime("%Y-%m-%d %H:%M ET")


def et_date(ms) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, _et()).strftime("%Y-%m-%d")


def session_window(session: str) -> tuple[int, int]:
    """(open_ms, close_ms) from the exchange calendar; raises for a non-trading date."""
    from ..marketstructure.market_calendar import is_trading_day
    from ..marketstructure.sessions import session_bounds

    if not is_trading_day(session):
        raise SystemExit(f"{session} is not an exchange session")
    return session_bounds(session)


def classify_minutes(rows: list[dict], opens: int, closes: int) -> dict[int, dict]:
    """One entry per session minute: the preferred row (exchange over sampled) and its class."""
    by_minute: dict[int, dict] = {}
    for r in rows:
        cur = by_minute.get(r["ts"])
        if cur is None or (r["source"] == "exchange" and cur["source"] != "exchange"):
            by_minute[r["ts"]] = dict(r)
    out = {}
    for ts in range(opens, closes, MINUTE):
        row = by_minute.get(ts)
        if row is None:
            out[ts] = {"ts": ts, "class": "absent"}
        else:
            out[ts] = {**row, "class": "exchange" if row["source"] == "exchange" else "sampled-only"}
    return out


def bucketize(rows: list[dict], opens: int, closes: int, step_minutes: int = 15, *, require_exchange: bool = True) -> list[dict]:
    """Descriptive aggregation of stored 1m rows into buckets.

    Mirrors production's *state* rule: a bucket that is incomplete, or (when exchange bars are
    required) contains a non-exchange minute, is ``partial`` — it reports what is known (OHLC and
    volume of the present minutes, which minutes are missing) but never a crossing, and it resets
    the crossing state so the next complete bucket compares against its own open. This is a
    display of the tape, not a reproduction of the engine's decision (see ``replay``).
    """
    classes = classify_minutes(rows, opens, closes)
    out = []
    step = step_minutes * MINUTE
    for k, b0 in enumerate(range(opens, closes, step)):
        mins = [classes[b0 + j * MINUTE] for j in range(step_minutes) if b0 + j * MINUTE < closes]
        present = [m for m in mins if m["class"] != "absent"]
        counts = Counter(m["class"] for m in mins)
        untrusted = counts.get("sampled-only", 0) if require_exchange else 0
        partial = len(present) < len(mins) or untrusted > 0
        entry = {"slot": k, "start": b0, "expectedMinutes": len(mins), "n": len(present), "classes": dict(counts), "partial": partial,
                 "missingMinutes": [et(m["ts"])[11:16] for m in mins if m["class"] == "absent"],
                 "untrustedMinutes": [et(m["ts"])[11:16] for m in mins if m["class"] == "sampled-only"] if require_exchange else []}
        if present:
            high = max(m["high"] for m in present)
            low = min(m["low"] for m in present)
            close = present[-1]["close"]
            entry.update({"open": present[0]["open"], "high": high, "low": low, "close": close,
                          "volume": int(sum(m["volume"] for m in present)),
                          "closeLocationLong": (close - low) / (high - low) if high > low else None,
                          "closeLocationShort": (high - close) / (high - low) if high > low else None})
        out.append(entry)
    return out


def annotate_display_crossings(table: list[dict], plan: dict) -> None:
    """Descriptive crossing over complete, trusted buckets only, with production's reset rule."""
    sign = 1 if plan["direction"] == "long" else -1
    baseline = {int(k): v for k, v in (plan.get("volume_baseline") or {}).items()}
    previous = None
    for b in table:
        if b["partial"] or b["n"] == 0:
            previous = None  # production resets previous_close on missing/untrusted buckets
            b["crossedDisplay"] = None
            continue
        before = previous if previous is not None else b["open"]
        b["crossedDisplay"] = (before - plan["trigger"]) * sign <= 0 < (b["close"] - plan["trigger"]) * sign
        base = baseline.get(b["slot"])
        b["baseline"] = base
        b["volumeRatio"] = b["volume"] / base if base else None
        b["closeLocation"] = b["closeLocationLong"] if sign == 1 else b["closeLocationShort"]
        b["targetPassed"] = (b["close"] - plan["targets"][0]) * sign >= 0
        previous = b["close"]


async def _connect(url: str):
    import asyncpg

    dsn = url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    await conn.execute("set default_transaction_read_only = on")
    return conn


async def _plan_row(conn, run_id: str):
    run = await conn.fetchrow("select id, symbol, mode, status, verdict, as_of, created_at, parent_run_id, result from technique_runs where id=$1", run_id)
    if run is None:
        raise SystemExit(f"no technique_runs row for {run_id}")
    return run, (_load(run["result"]) or {})


async def _stored_rows(conn, symbol: str, opens: int, closes: int):
    rows = await conn.fetch("select ts, open, high, low, close, volume, source from bars where symbol=$1 and tf='1m' and ts >= $2::bigint and ts < $3::bigint order by ts",
                            symbol, opens, closes)
    return [dict(r) for r in rows]


# ----------------------------------------------------------------------------- plan

async def plan_report(conn, run_id: str) -> dict:
    run, result = await _plan_row(conn, run_id)
    arm = await conn.fetchrow("select * from technique_armed where run_id=$1", run_id)
    plan = (result.get("plan") or {}).get("plan") or {}
    report: dict = {
        "runId": run_id, "symbol": run["symbol"], "createdAt": str(run["created_at"]), "parentRunId": run["parent_run_id"],
        "plan": {k: plan.get(k) for k in ("setup", "direction", "trigger", "invalidation", "targets", "first_session", "last_session", "created_at")},
        "entryPolicy": plan.get("entry"), "review": result.get("review"),
        "baselineSlots": len(plan.get("volume_baseline") or {}), "baselineAsOf": utc(plan.get("baseline_as_of")),
    }
    order_ids: set[str] = set()
    position_ids: set[str] = set()
    if arm:
        state = _load(arm["state"]) or {}
        config = _load(arm["config"]) or {}
        last = state.get("lastExecutionResult") or {}
        for oid in (state.get("orderId"), last.get("orderId")):
            if oid:
                order_ids.add(oid)
        adoption = last.get("adoption") or {}
        if adoption.get("positionId"):
            position_ids.add(adoption["positionId"])
        position_ids.update(adoption.get("residualPositionIds") or [])
        if state.get("managedPositionId"):
            position_ids.add(state["managedPositionId"])
        tape = state.get("minutes") or {}
        report["armed"] = {
            "status": arm["status"], "mode": arm["mode"], "planFor": arm["plan_for"], "portfolioId": arm["portfolio_id"],
            "createdAt": str(arm["created_at"]), "updatedAt": str(arm["updated_at"]),
            "phase": state.get("phase"), "expiresAt": utc(state.get("expiresAt")),
            "validUntil": utc((config.get("preparation") or {}).get("validUntil")),
            "observeAfter": utc(state.get("observeAfter")), "lastMinute": utc(state.get("lastMinute")),
            "contract": (config.get("execution") or {}).get("contract_symbol"),
            "contractPolicy": (config.get("execution") or {}).get("contract_policy"),
            "budget": (config.get("execution") or {}).get("budget"), "riskPct": (config.get("execution") or {}).get("risk_pct"),
            "finalArmTapeDay": state.get("day"), "finalArmTapeMinutes": len(tape),
            "finalArmTapeSources": dict(Counter((v[6] if len(v) > 6 else "unknown") for v in tape.values())),
            "decisions": [{"at": utc(d.get("at")), "decision": d.get("decision"), "reason": d.get("reason"), "measurements": d.get("measurements")}
                          for d in state.get("decisionHistory") or []],
            "signalHistory": state.get("signalHistory"),
            "lastExecutionResult": {k: v for k, v in last.items() if k != "report"},
        }
    # Attribution by identity only: orders carrying this plan's tag or recorded by the arm,
    # managed positions named by the adoption record, exit orders named by those positions,
    # and events whose aggregate is one of those ids. No symbol or text matching.
    orders = await conn.fetch(
        "select id, symbol, portfolio_id, side, qty, order_type, limit_price, status, filled_qty, avg_fill_price, created_at, updated_at "
        "from orders where technique='options_cartel' and (tags::jsonb ? $1 or id = any($2::text[])) order by created_at",
        f"cartel_run:{run_id}", list(order_ids))
    order_ids.update(o["id"] for o in orders)
    positions = await conn.fetch("select id, status, portfolio_id, created_at, updated_at, state from managed_positions where id = any($1::text[]) order by created_at",
                                 list(position_ids)) if position_ids else []
    exit_orders = [x["orderId"] for m in positions for x in (_load(m["state"]) or {}).get("exits", []) if x.get("orderId")]
    if exit_orders:
        extra = await conn.fetch(
            "select id, symbol, portfolio_id, side, qty, order_type, limit_price, status, filled_qty, avg_fill_price, created_at, updated_at "
            "from orders where id = any($1::text[]) order by created_at", exit_orders)
        orders = list(orders) + [o for o in extra if o["id"] not in order_ids]
        order_ids.update(exit_orders)
    aggregates = [run_id, *order_ids, *position_ids]
    events = await conn.fetch("select ts, type, aggregate_id, payload from events where aggregate_id = any($1::text[]) order by ts", aggregates)
    trail = []
    for e in events:
        p = _load(e["payload"]) or {}
        if e["type"] == "TechniqueCartelPreflight":
            rep = p.get("report") or {}
            failed = [c["name"] for c in rep.get("checks", []) if not c.get("passed")]
            risk = rep.get("risk") or {}
            ex = rep.get("expression") or {}
            spread = None
            if isinstance(ex.get("bid"), (int, float)) and isinstance(ex.get("ask"), (int, float)) and ex.get("quantity"):
                cents = ex["ask"] - ex["bid"]
                spread = {"cents": round(cents * 100, 1), "pctOfMid": round(cents / ((ex["ask"] + ex["bid"]) / 2) * 100, 1),
                          "usdPerContract": round(cents * 100, 2), "usdForQuantity": round(cents * 100 * ex["quantity"], 2)}
            trail.append({"ts": str(e["ts"]), "type": e["type"], "passed": rep.get("passed"), "failedChecks": failed,
                          "riskPassed": risk.get("passed"), "expression": ex, "spreadCost": spread,
                          "riskDetails": [c for c in risk.get("checks", []) if c.get("detail")]})
        elif e["type"] == "TechniqueCartelStateChanged":
            last = p.get("lastDecision") or {}
            trail.append({"ts": str(e["ts"]), "type": e["type"], "action": p.get("action"), "status": p.get("status"),
                          "phase": p.get("phase"), "lastDecision": last.get("decision"), "decisionAt": utc(last.get("at")) if last else None})
        else:
            trail.append({"ts": str(e["ts"]), "type": e["type"], "aggregate": e["aggregate_id"],
                          "payload": {k: p.get(k) for k in ("id", "status", "symbol", "qty", "limitPrice", "avgFillPrice", "verdict", "mode", "kind", "reason") if k in p}})
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
                             "readinessCheckedAt": utc(readiness.get("checkedAt")) if readiness.get("checkedAt") else None,
                             "contractAudit": {k: audit.get(k) for k in ("eligible", "expiriesChecked", "lowestOtherwiseEligibleAsk", "effectiveMaxAsk")},
                             "rejectedContracts": [(c.get("symbol"), c.get("ask"), c.get("reasons")) for c in (audit.get("rejectedCandidates") or [])[:6]]})
            prev = key
    report["attempts"] = {"count": len(attempts), "timeline": timeline}
    report["orders"] = [{k: (str(o[k]) if k in ("created_at", "updated_at") else o[k]) for k in ("id", "symbol", "portfolio_id", "side", "qty", "order_type", "limit_price", "status", "filled_qty", "avg_fill_price", "created_at", "updated_at")} for o in orders]
    report["managedPositions"] = [{"id": m["id"], "status": m["status"], "portfolioId": m["portfolio_id"], "createdAt": str(m["created_at"]), "updatedAt": str(m["updated_at"]),
                                   "closeReason": (_load(m["state"]) or {}).get("closeReason"), "realizedPnl": (_load(m["state"]) or {}).get("realizedPnl"),
                                   "exits": [{k: x.get(k) for k in ("kind", "qty", "price", "status", "ts", "orderId")} for x in (_load(m["state"]) or {}).get("exits", [])]}
                                  for m in positions]
    return report


def print_plan(rep: dict) -> None:
    p = rep["plan"]
    print(f"PLAN {rep['runId']} {rep['symbol']} created {rep['createdAt']} parent {rep['parentRunId']}")
    print(f"  {p['setup']} {p['direction']} trigger {p['trigger']} invalidation {p['invalidation']} targets {p['targets']} sessions {p['first_session']}..{p['last_session']}")
    if p.get("trigger") and p.get("invalidation") and p.get("targets"):
        sign = 1 if p["direction"] == "long" else -1
        risk = abs(p["trigger"] - p["invalidation"])
        room = (p["targets"][0] - p["trigger"]) * sign
        print(f"  structural (planning inputs, trigger-to-reviewed-invalidation basis): risk {risk:.4f} first-target room {room:.4f} ({room / p['trigger'] * 100:.2f}%) R {room / risk if risk else float('nan'):.3f}")
    print(f"  review: {json.dumps(rep.get('review'))[:300]}")
    print(f"  entry policy: {json.dumps(rep.get('entryPolicy'))}  baseline slots {rep['baselineSlots']} as of {rep['baselineAsOf']}")
    arm = rep.get("armed")
    if arm:
        print(f"  ARMED {arm['status']} mode {arm['mode']} for {arm['planFor']} book {arm['portfolioId'][:8]} contract {arm['contract']} budget {arm['budget']} risk% {arm['riskPct']} validUntil {arm['validUntil']} expiresAt {arm['expiresAt']}")
        print(f"    final arm tape (last saved, not decision-time): day {arm["finalArmTapeDay"]} minutes {arm["finalArmTapeMinutes"]} sources {arm["finalArmTapeSources"]} lastMinute {arm['lastMinute']} observeAfter {arm['observeAfter']}")
        for d in arm["decisions"]:
            m = d.get("measurements") or {}
            extra = f" volx{m.get('volumeRatio'):.2f} loc {m.get('closeLocation'):.2f} R {m.get('firstTargetR'):.2f}" if m and m.get("volumeRatio") is not None else ""
            print(f"    bucket-end {d['at']} {d['decision']}: {d['reason']}{extra}")
        for s in arm.get("signalHistory") or []:
            print(f"    signal bucket-end {utc(s.get('at'))} ref {s.get('referencePrice')} stop {s.get('stop')} risk {s.get('risk')} volx{s.get('volumeRatio'):.2f} loc {s.get('closeLocation'):.2f}")
        if arm.get("lastExecutionResult"):
            print(f"    last execution result: {json.dumps(arm['lastExecutionResult'])[:300]}")
    else:
        print("  never armed (no technique_armed row; no arm tape exists)")
    print(f"  EVENTS {len(rep['events'])} (journal ts = when recorded; decisionAt = the bucket end it judged; attributed by plan/order/position id)")
    for e in rep["events"]:
        if e["type"] == "TechniqueCartelPreflight":
            ex = e.get("expression") or {}
            print(f"    {e['ts'][:23]} PREFLIGHT passed={e['passed']} failed={e['failedChecks']} qty {ex.get('quantity')} bid {ex.get('bid')} ask {ex.get('ask')} delta {ex.get('delta')} spreadCost={e.get('spreadCost')}")
        elif e["type"] == "TechniqueCartelStateChanged":
            if e["action"] in ("observation_recovered", "history_gap_repaired"):
                continue
            print(f"    {e['ts'][:23]} {e['action']} status={e['status']} phase={e['phase']} last={e['lastDecision']} decisionAt={e['decisionAt']}")
        else:
            print(f"    {e['ts'][:23]} {e['type']} [{(e.get('aggregate') or '')[:8]}] {e['payload']}")
    print(f"  ATTEMPTS {rep['attempts']['count']} (deduplicated transitions; 'at' = attempt time; readiness@ = the tape cutoff it judged)")
    for t in rep["attempts"]["timeline"]:
        print(f"    {t['at']} prep {t['preparationId'][:8]} {t['status']} | {t['reason'] or ''} | readiness@{t['readinessCheckedAt']} {t['readinessReasons']} terminal {t['terminalStatus']} | contracts {t['contractAudit']} rejected {t['rejectedContracts'][:4]}")
    for o in rep["orders"]:
        print(f"  ORDER {o['id'][:8]} book {o['portfolio_id'][:8]} {o['side']} {o['qty']} {o['symbol']} {o['order_type']} lmt {o['limit_price']} -> {o['status']} filled {o['filled_qty']} @ {o['avg_fill_price']} ({o['created_at'][:19]} .. {o['updated_at'][:19]})")
    for m in rep["managedPositions"]:
        print(f"  MANAGED {m['id']} book {m['portfolioId'][:8]} {m['status']} {m['createdAt'][:19]}..{m['updatedAt'][:19]} close={m['closeReason']} realized={m['realizedPnl']} exits={m['exits']}")


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
                            "attemptedAt": utc(x.get("attemptedAt")) if x.get("attemptedAt") else None,
                            "available": vc.get("available"), "expected": vc.get("expected"), "missingSlots": vc.get("missing"),
                            "usable": len(vc.get("usableEntryPeriods") or []), "historicalSessions": vc.get("historicalSessions"),
                            "openingSlotSamples": [counts.get(str(i)) for i in range(4)], "minSamples": vc.get("minSamples")})
    shortlist = [{k: s.get(k) for k in ("symbol", "status", "setup", "reason", "planId")} | {"structuralTargetR": (s.get("ranking") or {}).get("structuralTargetR"),
                 "firstTargetPct": (s.get("ranking") or {}).get("firstTargetPct"), "attemptedAt": utc(s.get("attemptedAt")) if s.get("attemptedAt") else None}
                 for s in r.get("shortlist") or []]
    market = r.get("market") or {}
    return {"runId": run_id, "status": run["status"], "createdAt": str(run["created_at"]), "finishedAt": str(run["finished_at"]),
            "logicalStartedAt": utc(r.get("logicalStartedAt")), "marketInputsAsOf": utc(market.get("asOfMs")),
            "session": r.get("session"), "workspace": r.get("workspace"), "phase": r.get("phase"), "resumedFrom": r.get("resumedFrom"),
            "recovery": r.get("recovery"), "market": {k: market.get(k) for k in ("direction", "alignmentMode", "strictDirection")},
            "funnel": {"discovered": r.get("discovered"), "eligible": r.get("eligible"), "evaluated": r.get("evaluated"),
                       "qualifying": r.get("qualifying"), "candidatesChecked": r.get("candidatesChecked"), "candidateCheckLimit": r.get("candidateCheckLimit"),
                       "armed": r.get("armed"), "planErrors": r.get("planErrors"), "dataErrors": r.get("dataErrors"), "rowStatuses": dict(statuses)},
            "retained": r.get("retainedPlans"), "replaced": r.get("replacedPlans"), "shortlist": shortlist, "blocked": blocked,
            "message": r.get("message"),
            "note": "Times: createdAt/finishedAt are the run; logicalStartedAt is the resumed chain's origin; marketInputsAsOf is when the benchmark "
                    "history was read. Per-symbol history and chain observation times live on each analysis row (collection.historyObservedAt) and "
                    "shortlist item (attemptedAt); none of them equals the run's created_at."}


def print_preparation(rep: dict) -> None:
    print(f"PREPARATION {rep['runId']} {rep['status']} {rep['createdAt'][:19]}..{rep['finishedAt'][:19]} session {rep['session']} {rep['workspace']} phase {rep['phase']} resumedFrom {rep['resumedFrom']}")
    print(f"  logical start {rep['logicalStartedAt']}; market inputs as of {rep['marketInputsAsOf']}; market {rep['market']}; recovery {rep['recovery']}")
    print(f"  {rep['note']}")
    print(f"  funnel {rep['funnel']}")
    print(f"  retained {rep['retained']} replaced {rep['replaced']}")
    for s in rep["shortlist"]:
        print(f"  shortlist {s['symbol']:6s} {s['status']:18s} {s['setup'] or '':16s} R {s['structuralTargetR']} room% {s['firstTargetPct']} plan {s['planId']} attempted {s['attemptedAt']} {s['reason'] or ''}")
    for b in rep["blocked"]:
        print(f"  blocked   {b['symbol']:6s} {b['status']:12s} available {b['available']}/{b['expected']} usable {b['usable']} opening-slot samples {b['openingSlotSamples']} (min {b['minSamples']}) sessions {b['historicalSessions']} attempted {b['attemptedAt']} | {b['reason']}")
    print(f"  message: {rep['message']}")


# -------------------------------------------------------------------------- buckets

async def buckets_report(conn, symbol: str, session: str, plan_id: str | None, step: int) -> dict:
    opens, closes = session_window(session)
    rows = await _stored_rows(conn, symbol, opens, closes)
    plan = None
    require_exchange = True
    if plan_id:
        _, result = await _plan_row(conn, plan_id)
        plan = (result.get("plan") or {}).get("plan")
        require_exchange = bool(((plan or {}).get("entry") or {}).get("require_exchange_bars", True))
    table = bucketize(rows, opens, closes, step, require_exchange=require_exchange)
    classes = Counter(m["class"] for m in classify_minutes(rows, opens, closes).values())
    if plan:
        annotate_display_crossings(table, plan)
    return {"symbol": symbol, "session": session, "stepMinutes": step, "sessionMinutes": (closes - opens) // MINUTE, "storedRows": len(rows),
            "minuteClasses": dict(classes), "plan": plan_id, "trigger": plan.get("trigger") if plan else None, "direction": plan.get("direction") if plan else None,
            "note": "Descriptive view of the stored tape as it stands now (no receipt times). Partial buckets show known values and the missing/"
                    "untrusted minutes; they carry no crossing and reset the crossing state, as production does. Use `replay` for the engine's decision.",
            "buckets": table}


def print_buckets(rep: dict) -> None:
    print(f"BUCKETS {rep['symbol']} {rep['session']} {rep['stepMinutes']}m ({rep['sessionMinutes']}-minute session) from {rep['storedRows']} stored rows; minute classes {rep['minuteClasses']}; plan {rep['plan']} trigger {rep['trigger']} {rep['direction'] or ''}")
    print(f"  {rep['note']}")
    print("  start(ET) ex sm ab   open     high     low      close    volume    | cross? volxbase closeLoc targetPassed | partial detail")
    for b in rep["buckets"]:
        c = b["classes"]
        start = et(b["start"])[11:16]
        if b["n"] == 0:
            print(f"  {start} {c.get('exchange', 0):2d} {c.get('sampled-only', 0):2d} {c.get('absent', 0):2d}   (no minutes)")
            continue
        extra = ""
        if "crossedDisplay" in b and b["crossedDisplay"] is not None:
            vr = f"{b['volumeRatio']:.2f}" if b["volumeRatio"] is not None else "n/a"
            loc = f"{b['closeLocation']:.2f}" if b["closeLocation"] is not None else "n/a"
            extra = f"| {'CROSS' if b['crossedDisplay'] else '     '} {vr:>6} {loc:>6} {'passed' if b['targetPassed'] else ''}"
        elif b["partial"]:
            extra = "| partial: no crossing judged " + (f"missing {b['missingMinutes']} " if b["missingMinutes"] else "") + (f"untrusted {b['untrustedMinutes']}" if b["untrustedMinutes"] else "")
        print(f"  {start} {c.get('exchange', 0):2d} {c.get('sampled-only', 0):2d} {c.get('absent', 0):2d} {b['open']:8.3f} {b['high']:8.3f} {b['low']:8.3f} {b['close']:8.3f} {b['volume']:9d} {extra}")


# --------------------------------------------------------------------------- replay

def _bars_from_rows(symbol: str, rows: list[dict]):
    from ..domain import Bar

    return [Bar(symbol, "1m", r["ts"], r["open"], r["high"], r["low"], r["close"], r["volume"], source=r["source"]) for r in rows]


def _partial_evidence(trace_entry: dict, tape_by_ts: dict, plan, opens: int) -> dict | None:
    """Known measurements for a missing-data refusal, with the missing fields named explicitly."""
    if trace_entry.get("decision") not in ("missing_bucket", "untrusted_confirmation"):
        return None
    step = plan.entry.timeframe_minutes * MINUTE
    end = trace_entry["at"]
    start = end - step
    present = [tape_by_ts[t] for t in range(start, end, MINUTE) if t in tape_by_ts]
    missing = [et(t)[11:16] for t in range(start, end, MINUTE) if t not in tape_by_ts]
    untrusted = [et(b.ts)[11:16] for b in present if b.source != "exchange"]
    known = {"minutesPresent": len(present), "minutesMissing": missing, "minutesUntrusted": untrusted}
    if present:
        known.update({"partialHigh": max(b.high for b in present), "partialLow": min(b.low for b in present),
                      "lastKnownClose": present[-1].close, "partialVolume": int(sum(b.volume for b in present)),
                      "slotBaseline": plan.volume_baseline.get((start - opens) // step)})
    known["notComputed"] = ["crossing", "closeLocation", "volumeRatio", "sessionExtreme"]
    return known


def compare_minute_values(a: dict[int, tuple], b: dict[int, tuple]) -> dict:
    """Per-minute comparison of two tapes' (open, high, low, close, volume, source) tuples."""
    keys = set(a) | set(b)
    only_a = sorted(k for k in keys if k not in b)
    only_b = sorted(k for k in keys if k not in a)
    both = [k for k in keys if k in a and k in b]
    source_diff = sorted(k for k in both if a[k][5] != b[k][5])
    value_diff = sorted(k for k in both if a[k][:5] != b[k][:5])
    volume_diff = sorted(k for k in both if a[k][4] != b[k][4])
    return {"minutesCompared": len(both), "onlyInFirst": len(only_a), "onlyInSecond": len(only_b),
            "sourceLabelDiffers": len(source_diff), "priceOrVolumeDiffers": len(value_diff), "volumeDiffers": len(volume_diff),
            "examples": [{"minute": et(k)[11:16], "first": a[k][:5], "second": b[k][:5]} for k in value_diff[:5]]}


async def replay_report(conn, run_id: str, session: str | None) -> dict:
    """Journaled decisions (authoritative) beside two replays of ``read_entry`` that are *not* reconstructions.

    * ``journaled``: the decisions the observer actually made, with the live measurements it
      recorded. This is what happened.
    * ``finalArmTapeReplay``: ``read_entry`` over the arm's *final saved* minutes with its *final*
      ``observeAfter``. The observer ran incrementally on a growing tape and its ``observeAfter``
      moved (e.g. after a signal expired), so this replay can suppress or alter decisions that
      were made earlier; it is a consistency check, not a reconstruction.
    * ``storedTapeReplay``: ``read_entry`` over the shared ``bars`` table as it stands now with
      ``entry_after=None``. Stored rows may have been revised after the decision and carry no
      receipt time.

    Exact reconstruction of a decision needs the input values, their availability time and the
    cutoff at that decision; where those are not persisted the report says so.
    """
    from ..techniques.options_cartel.data_quality import unpack
    from ..techniques.options_cartel.entry import read_entry
    from ..techniques.options_cartel.plans import CartelPlan

    run, result = await _plan_row(conn, run_id)
    plan = CartelPlan.model_validate(result["plan"]["plan"])
    arm = await conn.fetchrow("select state from technique_armed where run_id=$1", run_id)
    state = (_load(arm["state"]) or {}) if arm else {}
    session = session or state.get("day") or plan.first_session.isoformat()
    opens, closes = session_window(session)
    out: dict = {"runId": run_id, "symbol": plan.symbol, "session": session, "trigger": plan.trigger, "direction": plan.direction,
                 "invalidation": plan.invalidation, "firstTarget": plan.targets[0], "entry": plan.entry.model_dump(),
                 "createdAt": utc(plan.created_at),
                 "reconstruction": "Journaled decisions are authoritative. Neither replay is a decision-time reconstruction: per-decision "
                                   "input values, availability times and cutoffs are not persisted for this plan."}
    journaled = [{"at": utc(d.get("at")), "decision": d.get("decision"), "reason": d.get("reason"), "measurements": d.get("measurements")}
                 for d in state.get("decisionHistory") or []]
    out["journaled"] = {"decisions": journaled, "signalHistory": state.get("signalHistory") or [],
                        "note": "From technique_armed.state.decisionHistory/signalHistory (journaled as TechniqueCartelStateChanged). Measurements are the live values."}

    def render(decision, tape):
        by_ts = {b.ts: b for b in tape}
        return {"status": decision["status"], "signal": decision["signal"],
                "trace": [{"at": utc(t.get("at")), "decision": t.get("decision"), "reason": t.get("reason"), "measurements": t.get("measurements"),
                           "partialEvidence": _partial_evidence(t, by_ts, plan, opens)} for t in decision["trace"]]}

    def tuples(tape):
        return {b.ts: (b.open, b.high, b.low, b.close, b.volume, b.source) for b in tape}

    minutes = state.get("minutes") or {}
    arm_tape = []
    if arm and state.get("day") == session and minutes:
        arm_tape = [unpack(plan.symbol, v) for v in minutes.values()]
        decision = read_entry(plan, arm_tape, closes, entry_after=state.get("observeAfter", state.get("armedAt")))
        out["finalArmTapeReplay"] = {"minutes": len(arm_tape), "sources": dict(Counter(b.source for b in arm_tape)),
                                     "observeAfterUsed": utc(state.get("observeAfter")), "lastMinute": utc(state.get("lastMinute")),
                                     **render(decision, arm_tape),
                                     "note": "read_entry over the arm's FINAL saved minutes with its FINAL observeAfter; a consistency check, not what the observer saw at each decision."}
    else:
        out["finalArmTapeReplay"] = None
    rows = await _stored_rows(conn, plan.symbol, opens, closes)
    classes = classify_minutes(rows, opens, closes)
    preferred = [dict(m) for m in classes.values() if m["class"] != "absent"]
    stored_bars = _bars_from_rows(plan.symbol, preferred)
    stored = read_entry(plan, stored_bars, closes, entry_after=None)
    out["storedTapeReplay"] = {"minutes": len(preferred), "classes": dict(Counter(m["class"] for m in classes.values())), **render(stored, stored_bars),
                               "note": "read_entry over the shared bars table as it stands now, entry_after=None. Rows may have been revised after the decision (exchange-over-exchange refresh); no receipt times."}
    out["tapeComparison"] = compare_minute_values(tuples(arm_tape), tuples(stored_bars)) if arm_tape else None
    # Decision-by-decision comparison at matching bucket ends (journaled vs each replay).
    def index(trace):
        return {(t["at"], t["decision"]): t for t in trace}
    comparisons = []
    for label in ("finalArmTapeReplay", "storedTapeReplay"):
        rep = out.get(label)
        if not rep:
            continue
        idx = index(rep["trace"])
        for j in journaled:
            match = idx.get((j["at"], j["decision"]))
            jm, rm = j.get("measurements") or {}, (match or {}).get("measurements") or {}
            comparisons.append({"replay": label, "at": j["at"], "decision": j["decision"], "reproduced": match is not None,
                                "liveVolumeRatio": jm.get("volumeRatio"), "replayVolumeRatio": rm.get("volumeRatio"),
                                "liveCloseLocation": jm.get("closeLocation"), "replayCloseLocation": rm.get("closeLocation")})
        for s in state.get("signalHistory") or []:
            rs = rep.get("signal") or {}
            comparisons.append({"replay": label, "at": utc(s.get("at")), "decision": "signal", "reproduced": bool(rs) and rs.get("at") == s.get("at"),
                                "liveVolumeRatio": s.get("volumeRatio"), "replayVolumeRatio": rs.get("volumeRatio") if rs else None,
                                "liveCloseLocation": s.get("closeLocation"), "replayCloseLocation": rs.get("closeLocation") if rs else None})
    out["decisionComparison"] = comparisons
    return out


def _fmt(v):
    return f"{v:.2f}" if isinstance(v, (int, float)) else "n/a"


def print_replay(rep: dict) -> None:
    print(f"REPLAY {rep['runId']} {rep['symbol']} {rep['session']} {rep['direction']} trigger {rep['trigger']} invalidation {rep['invalidation']} target1 {rep['firstTarget']} plan created {rep['createdAt']}")
    print(f"  {rep['reconstruction']}")
    j = rep["journaled"]
    print(f"  JOURNALED (authoritative): {len(j['decisions'])} decisions, {len(j['signalHistory'])} signals")
    for d in j["decisions"]:
        m = d.get("measurements") or {}
        extra = f" volx{_fmt(m.get('volumeRatio'))} loc {_fmt(m.get('closeLocation'))} R {_fmt(m.get('firstTargetR'))}" if m else ""
        print(f"    bucket-end {d['at']} {d['decision']}: {d['reason']}{extra}")
    for s in j["signalHistory"]:
        print(f"    signal bucket-end {utc(s.get('at'))} ref {s.get('referencePrice')} stop {s.get('stop')} volx{_fmt(s.get('volumeRatio'))} loc {_fmt(s.get('closeLocation'))}")
    for label in ("finalArmTapeReplay", "storedTapeReplay"):
        t = rep.get(label)
        if not t:
            print(f"  {label}: none")
            continue
        print(f"  {label}: status {t['status']} minutes {t['minutes']} {t.get('sources') or t.get('classes')}")
        print(f"    {t['note']}")
        for x in t["trace"]:
            m = x.get("measurements") or {}
            extra = f" volx{_fmt(m.get('volumeRatio'))} loc {_fmt(m.get('closeLocation'))} R {_fmt(m.get('firstTargetR'))}" if m and m.get("volumeRatio") is not None else ""
            pe = x.get("partialEvidence")
            partial = f" | known: {json.dumps(pe)}" if pe else ""
            print(f"    bucket-end {x['at']} {x['decision']}: {x['reason']}{extra}{partial}")
        if t["signal"]:
            s = t["signal"]
            print(f"    SIGNAL at {utc(s['at'])} ref {s['referencePrice']} stop {s['stop']} risk {s['risk']:.4f} volx{s['volumeRatio']:.2f} loc {s['closeLocation']:.2f}")
    c = rep.get("tapeComparison")
    if c:
        print(f"  final arm tape vs stored tape: {c['minutesCompared']} minutes compared; source label differs {c['sourceLabelDiffers']}; price/volume differs {c['priceOrVolumeDiffers']} (volume {c['volumeDiffers']}); only-in-arm {c['onlyInFirst']} only-in-stored {c['onlyInSecond']}")
        for e in c["examples"]:
            print(f"    {e['minute']} arm {e['first']} stored {e['second']}")
    print("  decision comparison (journaled vs replay):")
    for x in rep["decisionComparison"]:
        print(f"    {x['replay']:20s} {x['at']} {x['decision']:24s} reproduced={x['reproduced']} live volx{_fmt(x['liveVolumeRatio'])}/loc {_fmt(x['liveCloseLocation'])} replay volx{_fmt(x['replayVolumeRatio'])}/loc {_fmt(x['replayCloseLocation'])}")


# ------------------------------------------------------------------------- coverage

async def coverage_report(conn, symbol: str) -> dict:
    rows = await conn.fetch("select timeframe, observed_at, start_ms, end_ms, payload from cartel_history_cache where symbol=$1 order by timeframe, observed_at desc", symbol)
    daily: dict[str, int] = {}
    daily_source = None
    for r in rows:  # newest 1d cache row only; never let an older row overwrite it
        if r["timeframe"] == "1d":
            p = _load(r["payload"]) or {}
            for b in p.get("bars") or []:
                daily.setdefault(et_date(b[0]), b[5])
            daily_source = utc(r["observed_at"])
            break
    out: dict = {"symbol": symbol, "dailyVolumeFrom": daily_source, "caches": []}
    for r in rows:
        p = _load(r["payload"]) or {}
        bars = p.get("bars") or []
        entry = {"timeframe": r["timeframe"], "observedAt": utc(r["observed_at"]), "start": utc(r["start_ms"]), "end": utc(r["end_ms"]),
                 "provider": p.get("provider"), "provenance": p.get("provenance"), "bars": len(bars)}
        if r["timeframe"] == "1m" and bars:
            per: dict[str, list] = defaultdict(lambda: [0, 0, set()])
            for b in bars:
                d = et_date(b[0])
                per[d][0] += 1
                per[d][1] += b[5] or 0
                per[d][2].add(b[6])
            sessions = []
            for d in sorted(per):
                try:
                    o, c = session_window(d)
                    expected = (c - o) // MINUTE
                except SystemExit:
                    expected = None
                sessions.append({"session": d, "minutesReturned": per[d][0], "sessionMinutes": expected,
                                 "minutesAbsent": (expected - per[d][0]) if expected is not None else None,
                                 "minuteVolume": per[d][1], "dailyVolume": daily.get(d),
                                 "ratioPct": round(per[d][1] / daily[d] * 100, 1) if daily.get(d) else None, "sources": sorted(x for x in per[d][2] if x)})
            entry["sessions"] = sessions
        out["caches"].append(entry)
    out["note"] = ("minutesAbsent = session minutes (exchange calendar) with no bar in the provider response. Whether an absent minute had no trades, "
                   "trades without an eligible bar, or was lost in transfer is unverified from this table (noTradeIntervalsVerified=false); use alpaca-minutes. "
                   "The minute/daily volume ratio compares two providers' volume bases and is descriptive only.")
    return out


def print_coverage(rep: dict) -> None:
    print(f"COVERAGE {rep['symbol']}: {len(rep['caches'])} cache rows; daily volume from the newest 1d cache row observed {rep['dailyVolumeFrom']}")
    print(f"  {rep['note']}")
    for c in rep["caches"]:
        print(f"  tf {c['timeframe']} observed {c['observedAt']} range {c['start'][:10]}..{c['end']} provider {c['provider']} bars {c['bars']}")
        print(f"     provenance {json.dumps(c['provenance'])}")
        for s in c.get("sessions") or []:
            print(f"     {s['session']} returned {s['minutesReturned']:3d}/{s['sessionMinutes']} absent {s['minutesAbsent']} minute-volume {s['minuteVolume']:>10} daily {s['dailyVolume'] or '?':>10} ratio {s['ratioPct'] if s['ratioPct'] is not None else 'n/a'}% {s['sources']}")


# --------------------------------------------------------------------------- quotes

async def quotes_report(conn, run_id: str) -> dict:
    rows = await conn.fetch(
        "select contract, (available_at/900000)*900000 b, count(*) n, avg(bid) bid, avg(ask) ask, avg(ask-bid) cents, "
        "min((ask-bid)/nullif((ask+bid)/2,0))*100 minsp, avg((ask-bid)/nullif((ask+bid)/2,0))*100 avgsp, max((ask-bid)/nullif((ask+bid)/2,0))*100 maxsp, "
        "min(bid_size) minbs, max(bid_size) maxbs, min(ask_size) minas, max(ask_size) maxas "
        "from options_cartel_quotes where run_id=$1 group by contract, b order by contract, b", run_id)
    total = await conn.fetchval("select count(*) from options_cartel_quotes where run_id=$1", run_id)
    return {"runId": run_id, "observations": total,
            "note": "Spread three ways: percent of mid (the saved limit's basis), dollars per contract (spread x 100) and, in `plan`, dollars for the "
                    "preflight quantity. Buying at ask and selling at bid immediately costs the full spread before fees. Sizes are min..max per bucket.",
            "buckets": [{"contract": r["contract"], "start": utc(r["b"]), "n": r["n"], "bid": round(r["bid"], 3), "ask": round(r["ask"], 3),
                         "spreadCents": round(r["cents"] * 100, 1), "spreadUsdPerContract": round(r["cents"] * 100, 2),
                         "spreadPctMin": round(r["minsp"], 1), "spreadPctAvg": round(r["avgsp"], 1), "spreadPctMax": round(r["maxsp"], 1),
                         "bidSize": [r["minbs"], r["maxbs"]], "askSize": [r["minas"], r["maxas"]]} for r in rows]}


def print_quotes(rep: dict) -> None:
    print(f"QUOTES for plan {rep['runId']}: {rep['observations']} observations, per 15-minute bucket (UTC)")
    print(f"  {rep['note']}")
    for b in rep["buckets"]:
        print(f"  {b['contract']} {b['start'][5:16]} n={b['n']:3d} bid {b['bid']:.3f} ask {b['ask']:.3f} spread {b['spreadCents']:.1f}c = ${b['spreadUsdPerContract']:.2f}/contract, {b['spreadPctAvg']}% of mid (min {b['spreadPctMin']} max {b['spreadPctMax']}) sizes bid {b['bidSize']} ask {b['askSize']}")


# -------------------------------------------------------------------------- latency

async def latency_report(conn, since: str) -> dict:
    """Journal time minus bucket end for every Cartel entry decision: how late confirmations were judged."""
    since_dt = dt.datetime.fromisoformat(since).replace(tzinfo=dt.timezone.utc)
    rows = await conn.fetch(
        "select ts, payload from events where type='TechniqueCartelStateChanged' and ts >= $1 and payload->>'action' = 'entry_decision' order by ts",
        since_dt)
    samples = []
    for r in rows:
        p = _load(r["payload"]) or {}
        last = p.get("lastDecision") or {}
        at = last.get("at")
        if not isinstance(at, (int, float)):
            continue
        delay = r["ts"].timestamp() * 1000 - at
        samples.append({"ts": str(r["ts"]), "runId": p.get("runId"), "symbol": p.get("symbol"), "decision": last.get("decision"), "bucketEnd": utc(at), "delayMs": int(delay)})
    delays = sorted(s["delayMs"] for s in samples)
    pct = lambda q: delays[min(len(delays) - 1, int(q * len(delays)))] if delays else None
    stalls = await conn.fetch("select ts, payload from events where type='OpsRestartCheck' and ts >= $1 order by ts", since_dt)
    return {"since": since, "entryDecisions": len(samples),
            "delayMs": {"min": delays[0] if delays else None, "p50": pct(.5), "p90": pct(.9), "max": delays[-1] if delays else None},
            "overAcceptance": [s for s in samples if s["delayMs"] > CONFIRMATION_MAX_AGE_MS],
            "slowest": sorted(samples, key=lambda s: -s["delayMs"])[:8],
            "note": f"A decision is journaled after the bucket's last minute closes and the bar reaches the observer; the observer drops bars older than "
                    f"{CONFIRMATION_MAX_AGE_MS // 1000}s, so a dropped bar produces no decision at all and is invisible here (D4 proposes counting them). "
                    f"OpsRestartCheck rows since {since}: {len(stalls)} (restart-door checks, context only)."}


def print_latency(rep: dict) -> None:
    print(f"LATENCY since {rep['since']}: {rep['entryDecisions']} entry decisions; journal-minus-bucket-end ms {rep['delayMs']}")
    print(f"  {rep['note']}")
    print(f"  over the {CONFIRMATION_MAX_AGE_MS // 1000}s acceptance window: {len(rep['overAcceptance'])}")
    for s in rep["slowest"]:
        print(f"    {s['ts'][:23]} {s['symbol']:6s} {s['decision']:24s} bucket-end {s['bucketEnd']} +{s['delayMs']} ms")


# --------------------------------------------------------------------- alpaca probe

ODD_LOT_CONDITION = "I"  # SIP sale condition for an odd-lot trade; interpretation of other codes is left to the provider's documented rules


def trades_in_minute(trades: list[dict], start_ms: int, end_ms: int) -> list[dict]:
    """Keep only trades with ``start_ms <= timestamp < end_ms``.

    The provider's ``end`` request parameter is inclusive, so a trade stamped exactly at the
    next minute boundary comes back and must be dropped here. Timestamps are parsed to
    millisecond precision (nanoseconds truncated), which keeps a trade at 09:31:00.000000500
    on the 09:31 side of the boundary.
    """
    from ..brokers.alpaca import parse_rfc3339_ms

    kept = []
    for t in trades:
        ts = t.get("t")
        if not isinstance(ts, str):
            continue
        ms = parse_rfc3339_ms(ts)
        if start_ms <= ms < end_ms:
            kept.append(t)
    return kept


def classify_absent_minute(trades: list[dict], *, pagination_complete: bool, error: str | None, bars_complete: bool) -> str:
    """One of verified_no_trades | trades_without_bar | incomplete_evidence.

    A minute can only be certified absent if the *bar* pagination was complete; otherwise the
    bar may simply not have been fetched, and the class is ``incomplete_evidence`` regardless
    of what the trade tape says.
    """
    if not bars_complete or error or not pagination_complete:
        return "incomplete_evidence"
    return "verified_no_trades" if not trades else "trades_without_bar"


def trade_statistics(trades: list[dict]) -> dict:
    sizes = [int(t.get("s") or 0) for t in trades]
    conditions = Counter(c for t in trades for c in (t.get("c") or []))
    odd_lot_flagged = sum(1 for t in trades if ODD_LOT_CONDITION in (t.get("c") or []))
    return {"trades": len(trades), "sharesTraded": int(sum(sizes)),
            "sizeMin": min(sizes) if sizes else None, "sizeMax": max(sizes) if sizes else None,
            "tradesUnder100Shares": sum(1 for s in sizes if s < 100),
            "conditions": dict(conditions.most_common(8)),
            "oddLotConditionOnEveryTrade": bool(trades) and odd_lot_flagged == len(trades),
            "tradesWithOddLotCondition": odd_lot_flagged}


async def alpaca_minutes_report(symbol: str, session: str, env_file: str | None, limit: int, artifact_dir: str | None) -> dict:
    """D1 probe: for session minutes with no SIP 1Min bar, ask the SIP trade tape what happened.

    Read-only market-data requests; no runtime, database or settings involved. Every interval
    records its request bounds, response counts, conditions, a sha256 of the response body and
    its own verification completion time. Unprobed absent minutes are ``unknown``. A compact,
    credential-free artifact is written to ``artifact_dir`` when given.
    """
    import hashlib
    import os

    import httpx

    from ..config import AppConfig

    cfg = AppConfig(_env_file=env_file) if env_file else AppConfig()
    if not (cfg.alpaca_key_id and cfg.alpaca_secret):
        raise SystemExit("Alpaca credentials are not configured (ZARGAR_ALPACA_KEY_ID / ZARGAR_ALPACA_SECRET, or --env-file)")
    headers = {"APCA-API-KEY-ID": cfg.alpaca_key_id, "APCA-API-SECRET-KEY": cfg.alpaca_secret}
    opens, closes = session_window(session)
    iso = lambda ms: dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_iso = lambda: dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    out: dict = {"symbol": symbol, "session": session, "feed": "sip", "startedAt": now_iso(), "sessionMinutes": (closes - opens) // MINUTE,
                 "toolVersion": "cartel_evidence.alpaca-minutes/2"}
    from ..brokers.alpaca import parse_rfc3339_ms

    async with httpx.AsyncClient(timeout=30) as http:
        params = {"timeframe": "1Min", "start": iso(opens), "end": iso(closes), "limit": 10000, "feed": "sip", "adjustment": "raw"}
        bars, pages, token, bar_hashes = {}, 0, None, []
        bar_error = None
        while True:
            if token:
                params["page_token"] = token
            r = await http.get(f"https://data.alpaca.markets/v2/stocks/{symbol}/bars", params=params, headers=headers)
            pages += 1
            if r.status_code >= 400:
                bar_error = f"HTTP {r.status_code}: {r.text[:160]}"
                break
            bar_hashes.append(hashlib.sha256(r.content).hexdigest())
            data = r.json()
            for row in data.get("bars") or []:
                ts = parse_rfc3339_ms(str(row["t"]))
                if opens <= ts < closes:
                    bars[ts] = {"v": int(row.get("v") or 0), "n": row.get("n")}
            token = data.get("next_page_token")
            if not token or pages >= 20:
                break
        bars_complete = bar_error is None and token is None
        absent = [ts for ts in range(opens, closes, MINUTE) if ts not in bars]
        out["bars"] = {"request": {"start": iso(opens), "end": iso(closes), "timeframe": "1Min", "feed": "sip", "adjustment": "raw"},
                       "minutesWithBar": len(bars), "minutesAbsent": len(absent), "pages": pages, "paginationComplete": token is None,
                       "error": bar_error, "complete": bars_complete, "responseSha256": bar_hashes, "completedAt": now_iso(),
                       "barVolumeSum": int(sum(b["v"] for b in bars.values())), "barTradeCountSum": int(sum((b["n"] or 0) for b in bars.values()))}
        probes = []
        for ts in absent[:limit]:
            tparams = {"start": iso(ts), "end": iso(ts + MINUTE), "limit": 10000, "feed": "sip"}
            raw, tpages, ttoken, error, hashes = [], 0, None, None, []
            while True:
                if ttoken:
                    tparams["page_token"] = ttoken
                tr = await http.get(f"https://data.alpaca.markets/v2/stocks/{symbol}/trades", params=tparams, headers=headers)
                tpages += 1
                if tr.status_code >= 400:
                    error = f"HTTP {tr.status_code}: {tr.text[:120]}"
                    break
                hashes.append(hashlib.sha256(tr.content).hexdigest())
                tdata = tr.json()
                raw.extend(tdata.get("trades") or [])
                ttoken = tdata.get("next_page_token")
                if not ttoken or tpages >= 10:
                    break
            inside = trades_in_minute(raw, ts, ts + MINUTE)
            klass = classify_absent_minute(inside, pagination_complete=ttoken is None, error=error, bars_complete=bars_complete)
            stats = trade_statistics(inside)
            probes.append({"minute": et(ts)[11:16], "minuteStartMs": ts, "request": {"start": iso(ts), "end": iso(ts + MINUTE), "feed": "sip"},
                           "returnedTrades": len(raw), "tradesInsideBoundary": len(inside), "droppedAtBoundary": len(raw) - len(inside),
                           "class": klass, **stats, "pages": tpages, "paginationComplete": ttoken is None, "error": error,
                           "responseSha256": hashes, "verifiedAt": now_iso()})
        out["probes"] = probes
        out["unprobedAbsentMinutes"] = [et(ts)[11:16] for ts in absent[limit:]]
        summary = Counter(p["class"] for p in probes)
        summary["unknown"] = len(absent) - len(probes)
        out["probeSummary"] = dict(summary)
        out["probeSharesWithoutBar"] = int(sum(p["sharesTraded"] for p in probes if p["class"] == "trades_without_bar"))
        out["boundaryDropsTotal"] = int(sum(p["droppedAtBoundary"] for p in probes))
        out["completedAt"] = now_iso()
        out["note"] = ("Interval boundaries enforced locally as [start, end) because the provider's end parameter is inclusive. Conditions are "
                       "reported, not interpreted: whether a condition excludes a trade from the provider's minute bar is the provider's documented "
                       "rule. A trades_without_bar minute is never an exchange bar; verified_no_trades would be a distinct source label carrying "
                       "its verification time. Unprobed absent minutes are unknown.")
    if artifact_dir:
        os.makedirs(artifact_dir, exist_ok=True)
        path = os.path.join(artifact_dir, f"alpaca-minutes-{symbol}-{session}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, sort_keys=True)
        out["artifact"] = path
    return out


def print_alpaca_minutes(rep: dict) -> None:
    b = rep["bars"]
    print(f"ALPACA-MINUTES {rep['symbol']} {rep['session']} feed {rep['feed']} started {rep['startedAt']} completed {rep['completedAt']}: {b['minutesWithBar']}/{rep['sessionMinutes']} minutes have a SIP 1Min bar, {b['minutesAbsent']} absent; bar pages {b['pages']} complete {b['complete']}; bar volume sum {b['barVolumeSum']} trades-in-bars {b['barTradeCountSum']}")
    print(f"  probed {len(rep['probes'])} absent minutes: {rep['probeSummary']} (unknown = unprobed); shares in trades_without_bar minutes {rep['probeSharesWithoutBar']}; trades dropped at the [start,end) boundary {rep['boundaryDropsTotal']}")
    print(f"  {rep['note']}")
    if rep.get("artifact"):
        print(f"  artifact: {rep['artifact']}")
    for p in rep["probes"]:
        print(f"    {p['minute']} {p['class']:22s} returned {p['returnedTrades']:3d} inside {p['tradesInsideBoundary']:3d} shares {p['sharesTraded']:6d} sizes {p['sizeMin']}..{p['sizeMax']} <100sh {p['tradesUnder100Shares']} oddLotCondAll {p['oddLotConditionOnEveryTrade']} conditions {p['conditions']} verified {p['verifiedAt'][11:23]} {p['error'] or ''}")


# ------------------------------------------------------------------------------ cli

async def _run(args) -> None:
    if args.command == "alpaca-minutes":
        rep, printer = await alpaca_minutes_report(args.symbol, args.session, args.env_file, args.limit, args.artifact_dir), print_alpaca_minutes
    else:
        from ..config import AppConfig

        url = args.database_url or (AppConfig(_env_file=args.env_file) if args.env_file else AppConfig()).database_url
        conn = await _connect(url)
        try:
            if args.command == "plan":
                rep, printer = await plan_report(conn, args.run_id), print_plan
            elif args.command == "preparation":
                rep, printer = await preparation_report(conn, args.run_id), print_preparation
            elif args.command == "buckets":
                rep, printer = await buckets_report(conn, args.symbol, args.session, args.plan, args.step), print_buckets
            elif args.command == "replay":
                rep, printer = await replay_report(conn, args.run_id, args.session), print_replay
            elif args.command == "coverage":
                rep, printer = await coverage_report(conn, args.symbol), print_coverage
            elif args.command == "latency":
                rep, printer = await latency_report(conn, args.since), print_latency
            else:
                rep, printer = await quotes_report(conn, args.run_id), print_quotes
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
    parser.add_argument("--env-file", default=None, help="read ZARGAR_* settings (database URL, Alpaca keys) from this .env instead of the process environment")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan", help="plan geometry, armed decisions, preflights (with spread cost), attempts, orders and positions attributed by id")
    p.add_argument("run_id")
    p = sub.add_parser("preparation", help="funnel counts, shortlist and blocked candidates of one preparation run, with input times")
    p.add_argument("run_id")
    p = sub.add_parser("buckets", help="descriptive buckets from the stored tape (exchange/sampled-only/absent, partial buckets named)")
    p.add_argument("symbol")
    p.add_argument("session", help="YYYY-MM-DD (ET, exchange session)")
    p.add_argument("--plan", default=None, help="plan run id: adds descriptive crossing over complete trusted buckets")
    p.add_argument("--step", type=int, default=15)
    p = sub.add_parser("replay", help="journaled decisions (authoritative) beside final-arm-tape and stored-tape read_entry replays")
    p.add_argument("run_id")
    p.add_argument("--session", default=None)
    p = sub.add_parser("coverage", help="cached history provenance and per-session returned/absent minutes (exchange calendar)")
    p.add_argument("symbol")
    p = sub.add_parser("quotes", help="recorded option quote spreads for a plan (percent, cents, dollars)")
    p.add_argument("run_id")
    p = sub.add_parser("latency", help="journal-minus-bucket-end delay of every Cartel entry decision")
    p.add_argument("--since", default="2026-09-08")
    p = sub.add_parser("alpaca-minutes", help="D1 probe: SIP 1Min bars vs SIP trades for the absent minutes of one session (market data only)")
    p.add_argument("symbol")
    p.add_argument("session")
    p.add_argument("--limit", type=int, default=40, help="max absent minutes to probe; the rest are reported as unknown")
    p.add_argument("--artifact-dir", default=None, help="write a compact credential-free JSON artifact here")
    args = parser.parse_args(argv)
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
