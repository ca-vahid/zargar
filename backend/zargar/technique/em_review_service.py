"""EM integrated-review read service (2026-09-18): the READ-ONLY queries behind the EM review surface - source scenarios
and their plan matches (A), the preparation policy and decisions (B), source candidates (C), first-sale records (D) and
the executable-profit capture (E). Nothing here writes, arms, journals or calls a model; previews are built on the fly
and never stored."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from ..models import (Event, TechniqueBookSnapshot, TechniqueMethodNote, TechniqueRun, TechniqueSourceArtifact,
                      TechniqueSourceCandidate)
from . import preparation_policy as pp
from . import source_candidate_policy as scp
from . import source_scenarios as ss
from .profit_capture import reduce_session

ET = ZoneInfo("America/New_York")
KNOBS = ("techniques.enhanced_market.preparation_policy", "techniques.enhanced_market.prep_grade_floor", "techniques.enhanced_market.conditional_review_fix",
         "techniques.enhanced_market.prep_audit_quota_pct", "techniques.enhanced_market.source_scenarios_observe",
         "techniques.enhanced_market.source_candidates_observe", "techniques.enhanced_market.first_sale_rr_gate",
         "techniques.enhanced_market.book_snapshot_observe", "techniques.enhanced_market.book_snapshot_seconds",
         "techniques.enhanced_market.fire_decision_mode", "techniques.enhanced_market.fire_evidence_mode",
         "techniques.enhanced_market.shadow_exit_observe", "techniques.enhanced_market.shadow_p02_candidate", "ingest.auto_arm", "techniques.enhanced_market.source_candidates_chain_fetch", "techniques.enhanced_market.pick_retry_after_429_s")


def _bounds(date: str) -> tuple[dt.datetime, dt.datetime, int, int]:
    d = dt.datetime.fromisoformat(date).replace(tzinfo=ET)
    a, b = d.replace(hour=0, minute=0), d.replace(hour=23, minute=59)
    return a.astimezone(dt.timezone.utc), b.astimezone(dt.timezone.utc), int(d.replace(hour=9, minute=30).timestamp() * 1000), int(d.replace(hour=16).timestamp() * 1000)


def manifest(svc) -> dict:
    """The live collection manifest: every integrated-delivery knob with its DEFAULT and its EFFECTIVE value."""
    from ..settings_service import DEFAULTS
    get = svc.engine.settings.get
    rows = [{"key": k, "default": DEFAULTS.get(k), "effective": get(k, DEFAULTS.get(k))} for k in KNOBS]
    return {"policy": pp.effective(get), "knobs": rows, "observer": getattr(getattr(svc.armer, "_book_observer", None), "stats", None),
            "modelPriceSource": {"setting": "llm.rates", "pricedModels": sorted((get("llm.rates", {}) or {}).keys())}}


async def _payloads(svc, date: str) -> list:
    """Stored scenario artifacts of the day when they exist; otherwise a read-only PREVIEW built on the fly (not stored)."""
    a, b, _, _ = _bounds(date)
    async with svc.engine.sf() as s:
        notes = (await s.execute(select(TechniqueMethodNote).where(TechniqueMethodNote.posted_at >= a, TechniqueMethodNote.posted_at <= b)
                                 .order_by(TechniqueMethodNote.posted_at))).scalars().all()
        out = []
        known = None
        for n in notes:
            arts = (await s.execute(select(TechniqueSourceArtifact).where(TechniqueSourceArtifact.note_id == n.id, TechniqueSourceArtifact.kind == "scenarios")
                                    .order_by(TechniqueSourceArtifact.created_at))).scalars().all()
            if arts:
                out.append({**dict(arts[-1].payload or {}), "stored": True, "artifactId": arts[-1].id, "boardCheck": n.board_check})
                continue
            src = await ss.source_for_note(s, n.id)
            if not src or not src.get("extraction"):
                continue
            if known is None:
                try:
                    known = set(await svc.universe())
                except Exception:                          # noqa: BLE001
                    known = set()
            out.append({**ss.build_scenarios(src, known_symbols=(known or None)), "stored": False, "artifactId": None, "boardCheck": n.board_check})
    return out


async def _plans(svc, date: str, symbols: list) -> dict:
    a, _, _, _ = _bounds(date)
    out: dict = {}
    async with svc.engine.sf() as s:
        for sym in symbols:
            runs = (await s.execute(select(TechniqueRun).where(TechniqueRun.symbol == sym, TechniqueRun.technique == "enhanced_market", TechniqueRun.status == "done",
                                                               TechniqueRun.created_at >= a - dt.timedelta(hours=20)).order_by(TechniqueRun.created_at))).scalars().all()
            out[sym] = [{"runId": r.id, "symbol": sym, "createdAt": r.created_at.isoformat(), "trigger": r.trigger, "plan": (r.result or {}).get("plan") or {},
                         "config": r.config or {}, "analysis": (r.result or {}).get("analysis")}
                        for r in runs if str(((r.result or {}).get("plan") or {}).get("planFor") or "")[:10] == date]
    return out


async def _gate_events(svc, run_ids: list) -> dict:
    if not run_ids:
        return {}
    async with svc.engine.sf() as s:
        evs = (await s.execute(select(Event).where(Event.aggregate_id.in_(run_ids), Event.type.in_(
            ("TechniquePlanArmed", "TechniquePlanTriggerSkipped", "TechniquePlanTriggerFired", "TechniquePlanDisarmed", "TechniquePlanPositionOpened", "TechniqueArmRefused")))
            .order_by(Event.ts))).scalars().all()
    out: dict = {}
    for e in evs:
        p = e.payload or {}
        out.setdefault(e.aggregate_id, []).append({"ts": e.ts.isoformat(), "type": e.type.replace("TechniquePlan", ""), "trigger": p.get("trigger"),
                                                   "reason": (p.get("reason") or p.get("why") or p.get("event"))})
    return out


async def source_table(svc, date: str) -> dict:
    """Source -> plan -> gate: one row per scenario branch, with EVERY trigger of every matched plan and the gate events."""
    payloads = await _payloads(svc, date)
    symbols = sorted({(sc.get("symbol") or {}).get("resolved") for p in payloads for sc in p.get("scenarios") or []} - {None})
    plans = await _plans(svc, date, symbols)
    events = await _gate_events(svc, [p["runId"] for v in plans.values() for p in v])
    policy = pp.effective(svc.engine.settings.get)
    rows = []
    for p in payloads:
        for sc in p.get("scenarios") or []:
            sym = (sc.get("symbol") or {}).get("resolved")
            matches = []
            for pl in plans.get(sym) or []:
                m = ss.match_plan(sc, p, pl["plan"], plan_built_at=pl["createdAt"], plan_origin=pl["trigger"])
                d = pp.decide(symbol=sym, plan=pl["plan"], analysis=pl.get("analysis"), policy=policy, origin=pl["trigger"], run_id=pl["runId"])
                matches.append({"runId": pl["runId"], "origin": pl["trigger"], "overall": m["overall"], "alignedTrigger": m["alignedTrigger"], "causal": m["causal"],
                                "oppositeValidAtSameLevel": m["oppositeValidAtSameLevel"], "triggers": m["triggers"],
                                "prepDecision": {"mode": d["mode"], "disposition": d["disposition"], "modelReview": d["modelReview"], "eligibleTriggers": d["eligibleTriggers"],
                                                 "rescued": d["conditionalFix"]["rescued"]},
                                "gateEvents": events.get(pl["runId"], []),
                                # computed on demand, read-only: where an ingestion plan stands although the overnight model review said no
                                "supersedesModelVeto": (next(({"runId": o["runId"], "createdAt": o["createdAt"],
                                                               "reasons": [str(x)[:200] for x in ((o.get("analysis") or {}).get("noTradeReasons") or [])[:3]]}
                                                              for o in reversed(plans.get(sym) or [])
                                                              if o["trigger"] in ("promote", "sheet") and (o.get("analysis") or {}).get("verdict") == "no_setup" and o["createdAt"] < pl["createdAt"]), None)
                                                        if pl["trigger"] == "ingest" else None)})
            rows.append({"author": (p.get("author") or {}).get("displayName"), "noteId": (p.get("note") or {}).get("id"), "stored": p.get("stored"),
                         "usableAt": ss.usable_at(sc, p), "postedAt": (p.get("times") or {}).get("sourcePostedAt"), "scenario": sc, "plans": matches})
    avoid = [{"author": (p.get("author") or {}).get("displayName"), **v} for p in payloads for v in p.get("avoid") or []]
    return {"date": date, "rows": rows, "avoid": avoid, "policy": policy,
            "authorResult": "unknown - no author entry/exit ledger exists in the captured material; platform P&L is not the author's result"}


async def candidates(svc, date: str) -> dict:
    """Persisted forward candidates when the evaluator ran; otherwise a read-only replay preview from stored bars."""
    async with svc.engine.sf() as s:
        rows = (await s.execute(select(TechniqueSourceCandidate).where(TechniqueSourceCandidate.session == date)
                                .order_by(TechniqueSourceCandidate.symbol))).scalars().all()
    if rows:
        return {"date": date, "source": "forward", "rows": [{**scp.table_row(dict(r.payload or {}), baseline=(r.payload or {}).get("baseline")),
                                                             "history": (r.payload or {}).get("history")} for r in rows]}
    payloads = await _payloads(svc, date)
    symbols = sorted({(sc.get("symbol") or {}).get("resolved") for p in payloads for sc in p.get("scenarios") or []} - {None})
    plans = await _plans(svc, date, symbols)
    _, _, o_ms, c_ms = _bounds(date)
    from ..marketstructure.outcome import rows_to_bars
    bars: dict = {}
    async with svc.engine.sf() as s:
        for sym in symbols:
            r = (await s.execute(text("select ts, open, high, low, close, volume from bars where symbol=:s and tf='1m' and ts >= :a and ts < :b order by ts"),
                                 {"s": sym, "a": o_ms, "b": c_ms})).mappings().all()
            bars[sym] = rows_to_bars(sym, "1m", [[x["ts"], x["open"], x["high"], x["low"], x["close"], x["volume"]] for x in r])
    events = await _gate_events(svc, [p["runId"] for v in plans.values() for p in v])
    baseline: dict = {}
    for sym, pls in plans.items():
        for pl in pls:
            kinds = {t.get("id"): t for t in pl["plan"].get("triggers") or []}
            for e in events.get(pl["runId"], []):
                if e["type"] == "TriggerSkipped" and e.get("reason") in ("invalidated", "gap_void", "gapped_past", "gapped_through", "exhausted"):
                    t = kinds.get(e.get("trigger")) or {}
                    baseline.setdefault(sym, []).append({"runId": pl["runId"], "trigger": e.get("trigger"), "status": e["reason"],
                                                         "direction": t.get("direction") or ("short" if t.get("kind") in ("reject", "breakdown") else "long"),
                                                         "ts": int(dt.datetime.fromisoformat(e["ts"]).timestamp() * 1000), "entry": (t.get("entry") or {}).get("price")})
    from .source_candidates_runtime import plan_context
    ctx = {sym: await plan_context(svc, pls[-1]) for sym, pls in plans.items() if pls}
    cands = scp.evaluate_session(payloads=payloads, plans_by_symbol=plans, bars_by_symbol=bars, baseline_by_symbol=baseline, session=date,
                                 thresholds_by_symbol={k: v[0] for k, v in ctx.items()}, profiles_by_symbol={k: v[1] for k, v in ctx.items()},
                                 prev_close_by_symbol={k: v[2] for k, v in ctx.items()})
    return {"date": date, "source": "replay_preview (not stored; each candidate is judged with its plan's own saved thresholds and volume profile)",
            "rows": [scp.table_row(c, baseline=c.get("baseline")) for c in cands]}


async def first_sale_rows(svc, date: str) -> dict:
    a, b, _, _ = _bounds(date)
    async with svc.engine.sf() as s:
        evs = (await s.execute(select(Event).where(Event.type == "TechniqueFirstSale", Event.ts >= a, Event.ts <= b).order_by(Event.ts))).scalars().all()
    rows = []
    for e in evs:
        p = e.payload or {}
        g, v = p.get("gate") or {}, p.get("vehicle") or {}
        rows.append({"ts": e.ts.isoformat(), "runId": p.get("runId"), "symbol": p.get("symbol"), "trigger": p.get("trigger"), "direction": p.get("direction"), "mode": p.get("mode"),
                     "instrument": v.get("instrument"), "quantity": v.get("quantity"), "rung": g.get("rung"), "rRunnerEntry": g.get("rRunnerEntry"),
                     "rAdmission": g.get("rAdmission"), "admissionEntry": g.get("admissionEntry"), "boundBasis": (g.get("admissionBasis") or {}).get("boundBasis"),
                     "disposition": p.get("disposition"), "stage": p.get("stage"), "firstProductionSale": (p.get("firstSale") or {}).get("rung"),
                     "missingEvidence": g.get("missingEvidence"),
                     "rObservedUnderlier": g.get("rObservedUnderlier"), "min": g.get("minRiskReward"), "verdict": g.get("verdict"), "reason": g.get("reason"),
                     "planTime": g.get("planTime"), "differsFromPlanTime": g.get("differsFromPlanTime"), "payoffProxy": p.get("payoffProxy"), "fees": p.get("fees")})
    return {"date": date, "mode": svc.engine.settings.get("techniques.enhanced_market.first_sale_rr_gate", "off"), "rows": rows}


async def profit_capture(svc, date: str) -> dict:
    from ..tools.em_profit_capture import execution_net
    a, b, _, _ = _bounds(date)
    s_get = svc.engine.settings.get
    pid = str(s_get("techniques.enhanced_market.default_portfolio", "") or s_get("technique.arm.default_portfolio", "") or "")
    async with svc.engine.sf() as s:
        snaps = (await s.execute(select(TechniqueBookSnapshot).where(TechniqueBookSnapshot.session == date, TechniqueBookSnapshot.portfolio_id == pid)
                                 .order_by(TechniqueBookSnapshot.captured_at, TechniqueBookSnapshot.seq))).scalars().all()
        ex = (await s.execute(text("select symbol, side, qty, price, commission from executions where portfolio_id=:p and ts >= :a and ts <= :b order by ts"),
                              {"p": pid, "a": a, "b": b})).mappings().all()
    exe = execution_net([dict(r) for r in ex])
    payloads = [dict(x.payload or {}) for x in snaps]
    red = reduce_session(payloads, execution_net=exe["net"], execution_fees=exe["fees"])
    series = [{"at": p["capturedAt"], "seq": p["seq"], "reason": p["reason"], "realized": p["book"]["realizedNet"], "displayed": p["book"].get("displayedNet"),
               "executable": p["book"].get("executableTotalNet"), "scorable": p["book"]["scorable"], "why": p["book"].get("unscorableReasons")} for p in payloads][-600:]
    return {"date": date, "book": pid, "recorderOn": bool(s_get("techniques.enhanced_market.book_snapshot_observe", False)), "execution": exe, "capture": red, "series": series,
            "note": "executable = hypothetical covered liquidation estimate, never a fill; no snapshots = UNKNOWN, never zero"}
