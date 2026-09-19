"""EM preparation-policy service glue (integrated plan B/A, 2026-09-18): loads saved runs, freezes the inputs of the
pure `preparation_policy.decide`, persists the decision ledger (resume / idempotence) and answers "which earlier model
veto does this ingestion plan supersede". Order-free: nothing here arms - callers arm through the normal arm path."""
from __future__ import annotations

import datetime as dt
import hashlib
import json

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from ..models import TechniqueArmed, TechniquePrepDecision, TechniqueRun
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
      source holds + scenario / correction ids a new hold or a corrected scenario is a new decision
      plan geometry + reference price          the EFFECTIVE plan: two plans on the same bars (a pre-open re-plan on another reference
                                               price, a re-read under other rules) never share one approval"""
    cfg = run.get("config") or {}
    res = run.get("result") or {}
    plan = res.get("plan") or {}
    an = res.get("analysis") or {}
    reviewed = bool(an.get("verdict"))
    llm = run.get("llm") or {}
    analyst = _h({"verdict": an.get("verdict"), "reasons": an.get("noTradeReasons") or an.get("no_trade_reasons") or []}) if reviewed else "absent"
    geometry = _h({"ref": plan.get("referencePrice"), "lastClose": plan.get("lastClose"), "builtFromMs": plan.get("builtFromMs"),
                   "triggers": [[t.get("id"), t.get("kind"), t.get("direction"), t.get("valid"), (t.get("entry") or {}).get("price"),
                                 ((t.get("stop") or {}).get("price") if isinstance(t.get("stop"), dict) else t.get("stop")),
                                 [x.get("price") if isinstance(x, dict) else x for x in t.get("targets") or []], (t.get("assessment") or {}).get("grade")]
                                for t in plan.get("triggers") or []]})
    sources = sorted([str(x) for x in (cfg.get("sourceRevisionIds") or [])] + [f"scenario:{x}" for x in (source_ids or [])]
                     + [f"hold:{x}" for x in (source_hold or [])] + [f"plan:{geometry}"])
    return pp.causal_input_key(
        symbol=run.get("symbol") or "", session=str(plan.get("planFor") or ""), as_of=run.get("asOf"),
        bars_hash=str(cfg.get("barsAssetId") or cfg.get("barsHash") or ""), source_hashes=sources,
        adjusted_data_id=str(cfg.get("datasetVersion") or ""), thresholds_hash=_h(cfg.get("thresholds") or {}),
        grade_policy=f"{policy.get('gradeFloor')}|{policy.get('preparationPolicy')}|{policy.get('conditionalReviewFix')}|origin={origin}|analyst={analyst}"
                     + (f"|experiment={(policy.get('experiment') or {}).get('bundleHash')}@{(policy.get('experiment') or {}).get('portfolioId')}" if policy.get("experiment") else ""),
        policy_version=f"{pp.VERSION}+{pp.REVIEW_VERSION}",
        model=(llm.get("model") if reviewed else None), prompt_version=(str(cfg.get("promptVersion") or "") if reviewed else None),
        horizon=str(plan.get("horizon") or "session"))


async def prep_decide(svc, run_id: str, *, origin: str | None = None, persist: bool = False, run: dict | None = None,
                      source_hold: list | None = None, source_ids: list | None = None, policy: dict | None = None) -> dict:
    """`policy` = the effective policy of the BOOK the decision is for (the experiment resolves it per book); default =
    the technique-wide policy. The policy's mode, fix, floor and experiment identity are part of the decision key."""
    run = run or await svc.get_run(run_id)
    if run is None:
        raise KeyError(run_id)
    policy = policy or pp.effective(svc.engine.settings.get)
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
            try:
                await session.commit()
            except IntegrityError:                         # another worker decided the SAME inputs first: one row, the same decision - idempotent
                await session.rollback()
                async with svc.engine.sf() as again:
                    row = await again.get(TechniquePrepDecision, key)
                if row is not None:
                    return {**dict(row.payload or {}), "reused": True, "racedWith": "concurrent_decision"}
                raise
    return d


ARM_LOCK_TIMEOUT_S = 20.0


def _lock_id(candidate_key: str) -> int:
    return int(hashlib.sha256(("em-prep-arm:" + str(candidate_key)).encode("utf-8")).hexdigest()[:15], 16)


async def armed_candidate_in_db(svc, symbol: str, candidate_key: str, portfolio_id: str | None = None) -> str | None:
    """The run id of an ARMED / PAUSED EM plan in the DATABASE with this candidate key (never the process memory: another
    worker, or this one before a restart, may have armed it). With `portfolio_id` the check is for THAT book only: the
    same candidate armed in the baseline book never blocks, and is never blocked by, the experimental book."""
    async with svc.engine.sf() as session:
        q = select(TechniqueArmed.run_id, TechniqueRun.result).join(TechniqueRun, TechniqueRun.id == TechniqueArmed.run_id) \
            .where(TechniqueArmed.symbol == symbol, TechniqueArmed.technique == "enhanced_market", TechniqueArmed.status.in_(("armed", "paused")))
        if portfolio_id:
            q = q.where(TechniqueArmed.portfolio_id == str(portfolio_id))
        rows = (await session.execute(q)).all()
    for rid, result in rows:
        if pp.candidate_key(symbol, (result or {}).get("plan") or {}) == candidate_key:
            return rid
    return None


async def prep_arm(svc, run_id: str, *, arm, origin: str | None = None, source_hold: list | None = None, source_ids: list | None = None,
                   run: dict | None = None, policy: dict | None = None, portfolio_id: str | None = None) -> dict:
    """ONE arm per candidate ACROSS workers and restarts. The decision is made by the one owner (`prep_decide`); the arm runs
    under a Postgres advisory lock on the candidate key, after re-checking the DATABASE for an armed plan with that key. A
    second worker waits, then finds the first one's row and skips; a restart after the commit but before the acknowledgement
    finds the committed row and skips. `arm` = the coroutine function that performs the arm (the existing stable arm
    identity - the run id - is untouched). Returns {armed, why, decision, armedRunId?, result?}.
    LOCK SAFETY (owner review 2026-09-19): the lock is TRANSACTION-scoped (`pg_advisory_xact_lock`) on the holder session's open
    transaction, so it is released by the rollback that ALWAYS ends that session - a cancelled task, a failed release or the
    pool's reset-on-return can never leave a pooled connection holding it. The wait is bounded by `SET LOCAL lock_timeout`;
    a worker that cannot get the lock in time arms nothing and says so."""
    d = await prep_decide(svc, run_id, origin=origin, persist=True, run=run, source_hold=source_hold, source_ids=source_ids, policy=policy)
    if d.get("disposition") != "eligible":
        return {"armed": False, "why": d.get("disposition") or "not_eligible", "decision": d}
    key, lock = d["candidateKey"], _lock_id(f"{d['candidateKey']}@{portfolio_id or ''}")
    async with svc.engine.sf() as holder:                  # the lock lives in THIS session's transaction and dies with it (commit, rollback, cancel, pool reset)
        try:
            await holder.execute(text(f"set local lock_timeout = '{int(ARM_LOCK_TIMEOUT_S * 1000)}ms'"))
            await holder.execute(text("select pg_advisory_xact_lock(:k)"), {"k": lock})
        except DBAPIError as exc:
            await holder.rollback()
            state = str(getattr(getattr(exc, "orig", None), "sqlstate", "") or getattr(getattr(exc, "orig", None), "pgcode", "") or "")
            if state == "55P03" or "lock timeout" in str(exc).lower():   # lock_not_available: another worker is still arming this candidate
                return {"armed": False, "why": "arm_lock_timeout", "decision": d, "detail": state or type(exc).__name__}
            return {"armed": False, "why": "arm_lock_error", "decision": d, "detail": f"{state} {type(exc).__name__}".strip()[:80]}   # a database failure is not called contention; nothing is armed either way
        existing = await armed_candidate_in_db(svc, str(d.get("symbol") or ""), key, portfolio_id)
        if existing:
            return {"armed": False, "why": ("already_armed" if existing == run_id else "duplicate_of_armed_candidate"), "armedRunId": existing, "decision": d}
        return {"armed": True, "why": None, "decision": d, "result": await arm()}


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
