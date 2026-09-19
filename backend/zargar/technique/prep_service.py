"""EM preparation-policy service glue (integrated plan B/A, 2026-09-18): loads saved runs, freezes the inputs of the
pure `preparation_policy.decide`, persists the decision ledger (resume / idempotence) and answers "which earlier model
veto does this ingestion plan supersede". Order-free: nothing here arms - callers arm through the normal arm path."""
from __future__ import annotations

import datetime as dt
import hashlib
import json

from sqlalchemy import select

from ..models import TechniquePrepDecision, TechniqueRun
from . import preparation_policy as pp

ORIGIN_OF_TRIGGER = {"promote": "batch", "sheet": "batch", "ingest": "ingest", "preopen_replan": "preopen_replan"}


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def input_key_for(run: dict, policy: dict, *, origin: str | None = None, source_hold: list | None = None, source_ids: list | None = None) -> str:
    """The causal identity of ONE preparation decision (IR-05). Everything that can change eligibility is in the key, so a
    cached decision can never outlive a new conflicting input:
      bars / as-of / thresholds / dataset      the plan's own inputs
      policy mode + version + grade floor + conditional-review mode
      origin                                   the path's authority differs under `baseline` (model review vs ingestion inline)
      analyst evidence                         the model review's verdict AND reasons (baseline selection depends on them)
      source holds + scenario / correction ids a new hold or a corrected scenario is a new decision"""
    cfg = run.get("config") or {}
    res = run.get("result") or {}
    plan = res.get("plan") or {}
    an = res.get("analysis") or {}
    reviewed = bool(an.get("verdict"))
    llm = run.get("llm") or {}
    analyst = _h({"verdict": an.get("verdict"), "reasons": an.get("noTradeReasons") or an.get("no_trade_reasons") or []}) if reviewed else "absent"
    sources = sorted([str(x) for x in (cfg.get("sourceRevisionIds") or [])] + [f"scenario:{x}" for x in (source_ids or [])]
                     + [f"hold:{x}" for x in (source_hold or [])])
    return pp.causal_input_key(
        symbol=run.get("symbol") or "", session=str(plan.get("planFor") or ""), as_of=run.get("asOf"),
        bars_hash=str(cfg.get("barsAssetId") or cfg.get("barsHash") or ""), source_hashes=sources,
        adjusted_data_id=str(cfg.get("datasetVersion") or ""), thresholds_hash=_h(cfg.get("thresholds") or {}),
        grade_policy=f"{policy.get('gradeFloor')}|{policy.get('preparationPolicy')}|{policy.get('conditionalReviewFix')}|origin={origin}|analyst={analyst}",
        policy_version=f"{pp.VERSION}+{pp.REVIEW_VERSION}",
        model=(llm.get("model") if reviewed else None), prompt_version=(str(cfg.get("promptVersion") or "") if reviewed else None),
        horizon=str(plan.get("horizon") or "session"))


async def prep_decide(svc, run_id: str, *, origin: str | None = None, persist: bool = False, run: dict | None = None,
                      source_hold: list | None = None, source_ids: list | None = None) -> dict:
    run = run or await svc.get_run(run_id)
    if run is None:
        raise KeyError(run_id)
    policy = pp.effective(svc.engine.settings.get)
    res = run.get("result") or {}
    plan = res.get("plan") or {}
    origin = origin or ORIGIN_OF_TRIGGER.get(str(run.get("trigger") or ""), str(run.get("trigger") or "manual"))
    key = input_key_for(run, policy, origin=origin, source_hold=source_hold, source_ids=source_ids)
    if persist:
        async with svc.engine.sf() as session:
            row = await session.get(TechniquePrepDecision, key)
            if row is not None and row.status == "done":
                return {**dict(row.payload or {}), "reused": True}
    d = pp.decide(symbol=run.get("symbol") or "", plan=plan, analysis=res.get("analysis"), policy=policy,
                  origin=origin,
                  source_hold=source_hold, run_id=run.get("id"), input_key=key)
    d["policy"] = policy
    if persist:
        now = dt.datetime.now(dt.timezone.utc)
        async with svc.engine.sf() as session:
            row = await session.get(TechniquePrepDecision, key, with_for_update=True)
            if row is None:
                session.add(TechniquePrepDecision(id=key, session=str(plan.get("planFor") or "")[:10], symbol=str(run.get("symbol") or ""), candidate_key=d["candidateKey"],
                                                  run_id=run.get("id"), origin=d["origin"], mode=d["mode"], status="done", attempts=1,
                                                  disposition=d["disposition"], payload=d, created_at=now, updated_at=now))
            else:
                row.status, row.attempts, row.payload, row.disposition, row.updated_at = "done", int(row.attempts or 0) + 1, d, d["disposition"], now
            await session.commit()
    return d


async def prep_select(svc, run_ids: list, *, persist: bool = False, origin: str | None = None, source_ids: list | None = None) -> dict:
    """ONE arm list for a set of candidate runs from ANY path. Candidates already armed (by candidate key) are skipped."""
    decisions = []
    for rid in run_ids or []:
        try:
            decisions.append(await prep_decide(svc, rid, persist=persist, origin=origin, source_ids=source_ids))
        except KeyError:
            decisions.append({"runId": rid, "disposition": "refused", "symbol": None, "candidateKey": None, "explanation": "run not found"})
    armed_keys = set()
    for a in svc.armed_plans(slim=False):
        if (a.get("technique") or "enhanced_market") != "enhanced_market" or a.get("status") not in ("armed", "paused"):
            continue
        armed_keys.add(pp.candidate_key(a.get("symbol") or "", a.get("plan") or {}))
    sel = pp.select(decisions, already_armed_keys=armed_keys)
    return {**sel, "policy": pp.effective(svc.engine.settings.get), "decisions": decisions}


async def superseded_model_veto(svc, symbol: str, plan_for: str | None, before: dt.datetime | None = None) -> dict | None:
    """Did an EARLIER model-reviewed run for this symbol/session say `no_setup`? Exposes where an ingestion plan supersedes
    a model-vetoed overnight plan (baseline behaviour is unchanged - this only makes it visible)."""
    async with svc.engine.sf() as session:
        q = select(TechniqueRun).where(TechniqueRun.symbol == symbol, TechniqueRun.technique == "enhanced_market",
                                       TechniqueRun.trigger.in_(("promote", "sheet")), TechniqueRun.status == "done")
        if before is not None:
            q = q.where(TechniqueRun.created_at < before)
        rows = (await session.execute(q.order_by(TechniqueRun.created_at.desc()).limit(6))).scalars().all()
    for r in rows:
        plan = (r.result or {}).get("plan") or {}
        if plan_for and str(plan.get("planFor") or "")[:10] != str(plan_for)[:10]:
            continue
        a = (r.result or {}).get("analysis") or {}
        if a.get("verdict") == "no_setup":
            return {"runId": r.id, "verdict": "no_setup", "createdAt": r.created_at.isoformat(),
                    "reasons": [str(x)[:200] for x in (a.get("noTradeReasons") or a.get("no_trade_reasons") or [])[:3]]}
        return None
    return None
