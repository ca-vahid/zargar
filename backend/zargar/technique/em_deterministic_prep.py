"""EM deterministic preparation of the BASELINE book (`em-deterministic-prep-v1`, 2026-09-23, user decision: "EM fully
deterministic").

Why. The only real money EM spent was the nightly paid model review of the next session's sheet: $1,104 of EM's $1,109 over
2026-08-21..09-23 at list price, with no demonstrated edge behind it (TRADING-RULES §5 2026-09-22). The experimental book
had prepared with rules only - zero model calls - since 2026-09-19. This gives the baseline book the same path:

  * once the NEXT session's graded sheet exists (built at 16:15 ET, `technique.sheet.auto`), every row goes through the one
    eligibility owner (`preparation_policy.decide` with no analysis, i.e. the grade floor and the deterministic rules);
  * an eligible row mints ONE plan run (`analyze(..., with_vision=False)`: no model pass, charts on demand) and arms it into
    the baseline book through the normal arm path (`prep_arm` - advisory-locked, one arm per candidate, RiskGate on every
    order as always);
  * restart-safe and idempotent: a run already minted for (symbol, session) is reused; an armed candidate is never re-armed.

It runs only while the technique-wide `techniques.enhanced_market.preparation_policy` is `deterministic`. With it off,
nothing here does anything and the paid evening batch (scripts/em-evening-batch.py, `paid_review`) is the baseline's
preparation, as before. The experimental book keeps its own loop (`em_experiment.prepare`) and its own tags.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging

from sqlalchemy import select

from .. import events as ev
from ..models import TechniqueRun
from . import preparation_policy as pp

log = logging.getLogger("zargar.technique.em_deterministic_prep")

VERSION = "em-deterministic-prep-v1"
TRIGGER = "prepare"          # the baseline's deterministic plan runs; `prep_service.ORIGIN_OF_TRIGGER` maps it to the batch origin
_PREPARED: set = set()
_PREPARING: dict = {}


def enabled(get) -> bool:
    return pp.effective(get)["preparationPolicy"] == "deterministic"


def baseline_book(get) -> str | None:
    return (get("techniques.enhanced_market.default_portfolio", None) or get("technique.arm.default_portfolio", None) or None)


async def _existing_run(svc, symbol: str, plan_for: str) -> dict | None:
    async with svc.engine.sf() as s:
        runs = (await s.execute(select(TechniqueRun).where(TechniqueRun.symbol == symbol, TechniqueRun.trigger == TRIGGER,
                                                           TechniqueRun.status == "done", TechniqueRun.technique == "enhanced_market")
                                .order_by(TechniqueRun.created_at.desc()).limit(8))).scalars().all()
    for r in runs:
        if str(((r.result or {}).get("plan") or {}).get("planFor") or "")[:10] == plan_for:
            return {"id": r.id}
    return None


async def _already_prepared(svc, plan_for: str) -> bool:
    async with svc.engine.sf() as s:
        rows = (await s.execute(select(TechniqueRun.result).where(TechniqueRun.trigger == TRIGGER, TechniqueRun.technique == "enhanced_market")
                                .order_by(TechniqueRun.created_at.desc()).limit(400))).scalars().all()
    return any(str(((res or {}).get("plan") or {}).get("planFor") or "")[:10] == plan_for for res in rows)


async def prepare(svc, plan_for: str, *, limit: int | None = None) -> dict:
    """Deterministic preparation of ONE session for the baseline book. Zero model calls. Idempotent."""
    from ..marketstructure.sessions import session_bounds
    from .em_experiment import _sheet
    from .prep_service import prep_arm
    get = svc.engine.settings.get
    out = {"version": VERSION, "planFor": plan_for, "sheet": None, "rows": 0, "eligible": 0, "minted": 0, "reusedRuns": 0, "armed": 0,
           "alreadyArmed": 0, "skipped": {}, "errors": [], "armedRuns": [], "modelCalls": 0}
    if not enabled(get):
        out["errors"].append("preparation_policy is not deterministic")
        return out
    pid = baseline_book(get)
    book = svc.engine.positions.portfolio(pid) if pid else None
    if not book:
        out["errors"].append("no baseline book configured (techniques.enhanced_market.default_portfolio)")
        return out
    sw, rows = await _sheet(svc, plan_for)
    if sw is None:
        out["errors"].append(f"no finished plan sheet for {plan_for}")
        return out
    out["sheet"], out["rows"] = sw.id, len(rows)
    params = sw.params or {}
    policy = pp.effective(get)
    thresholds = {**dict(params.get("thresholds") or {}), **dict(params.get("overrides") or {})} or None

    def skip(why):
        out["skipped"][why] = out["skipped"].get(why, 0) + 1
    for row in rows[: (limit or len(rows))]:
        try:
            d = pp.decide(symbol=row.symbol, plan=dict(row.plan or {}), analysis=None, policy=policy, origin="batch")
            if d.get("disposition") != "eligible":
                skip(str(d.get("disposition") or "not_eligible"))
                continue
            out["eligible"] += 1
            run = await _existing_run(svc, row.symbol, plan_for)
            if run is None:
                _, close_ms = session_bounds(row.session)
                run = await svc.analyze(row.symbol, as_of_ms=close_ms + 1, primary_tf=params.get("triggerTf"), trigger=TRIGGER, plan=True,
                                        with_vision=False, wait=True, thresholds_override=thresholds)
                out["minted"] += 1
            else:
                out["reusedRuns"] += 1
            rid = run["id"]
            res = await prep_arm(svc, rid, origin="batch", policy=policy, portfolio_id=pid,
                                 arm=lambda _rid=rid: svc.arm_plan(_rid, {"portfolioId": pid, "mode": "auto"}, _prep_checked=True))
            if res["armed"]:
                out["armed"] += 1
                out["armedRuns"].append({"runId": rid, "symbol": row.symbol, "triggers": (res["decision"] or {}).get("eligibleTriggers")})
            elif res["why"] in ("already_armed", "duplicate_of_armed_candidate"):
                out["alreadyArmed"] += 1
            else:
                skip("after_mint:" + str(res["why"]))
        except Exception as exc:                           # noqa: BLE001 - one symbol never stops the preparation
            out["errors"].append(f"{row.symbol}: {type(exc).__name__}: {exc}"[:200])
    return out


async def auto_prepare(svc, now_ms: int) -> str | None:
    """Once the NEXT session's sheet exists and the baseline has no deterministic plan for it, run `prepare` ONCE in the
    background (single flight; `prepare` is idempotent, so a crash mid-way is finished by the next pass)."""
    from ..marketstructure import sessions as _sessions
    from .em_experiment import _sheet
    get = svc.engine.settings.get
    if not enabled(get) or not baseline_book(get):
        return None
    plan_for = _sessions.next_session_date(int(now_ms))
    if plan_for in _PREPARED or plan_for in _PREPARING:
        return None
    sw, _rows = await _sheet(svc, plan_for)
    if sw is None:
        return None
    if await _already_prepared(svc, plan_for):
        _PREPARED.add(plan_for)
        return None

    async def _run():
        try:
            out = await prepare(svc, plan_for)
            log.info("deterministic prep: %s - eligible %s, minted %s, armed %s, errors %s", plan_for, out["eligible"], out["minted"], out["armed"], len(out["errors"]))
            with contextlib.suppress(Exception):
                pid = baseline_book(get)
                await svc.engine.journal.append(ev.TECHNIQUE_PREPARED, {k: out.get(k) for k in ("version", "planFor", "sheet", "rows", "eligible", "minted", "reusedRuns",
                                                                                                "armed", "alreadyArmed", "skipped", "modelCalls")} | {"errors": out["errors"][:10]},
                                                aggregate_type="portfolio", aggregate_id=pid, portfolio_id=pid)
            if not out["errors"] or out["armed"] or out["alreadyArmed"]:
                _PREPARED.add(plan_for)
        except Exception:                                  # noqa: BLE001
            log.exception("deterministic prep of %s failed", plan_for)
        finally:
            _PREPARING.pop(plan_for, None)
    _PREPARING[plan_for] = asyncio.create_task(_run(), name="em-deterministic-prep")
    return plan_for
