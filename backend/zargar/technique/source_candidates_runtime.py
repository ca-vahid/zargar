"""EM source-candidate forward evaluator (integrated plan C, 2026-09-18). ORDER-FREE, default OFF
(`techniques.enhanced_market.source_candidates_observe`).

Once a minute during the regular session it re-derives every candidate of TODAY's scenario artifacts from closed bars
(`source_candidate_policy.evaluate_session` - the same pure evaluator the replay tool uses) and upserts one row per
candidate in `technique_source_candidates`. State is a pure function of (definition, closed bars), so a restart
resumes by re-deriving: nothing is skipped, nothing is counted twice, and no candidate is ever created by a path that
could arm it (origin `scenario:*` - the runner refuses it). Reads: scenario artifacts, today's saved ingest / batch
plans, the `bars` table, the armer's BASELINE tracker states (read-only). No chain fetch, no model, no order."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from ..marketstructure.outcome import rows_to_bars
from ..models import TechniqueRun, TechniqueSourceArtifact, TechniqueSourceCandidate
from . import source_candidate_policy as scp

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
KNOB = "techniques.enhanced_market.source_candidates_observe"
MAX_CANDIDATES = 40


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def baseline_states(armer) -> dict:
    """The BASELINE trackers' states per symbol - read-only views, never the tracker objects themselves."""
    out: dict = {}
    for ap in list(getattr(armer, "_armed", {}).values()):
        for tid, tr in (getattr(ap, "trackers", None) or {}).items():
            if not (tr.trigger or {}).get("valid", True):
                continue
            ev = tr.events[-1] if tr.events else {}
            out.setdefault(ap.symbol, []).append({"runId": ap.run_id, "trigger": tid, "direction": tr.direction, "status": tr.status,
                                                  "ts": ev.get("ts"), "entry": float(tr.entry)})
    return out


async def load_inputs(svc, session_day: str) -> dict:
    day0 = dt.datetime.fromisoformat(session_day).replace(tzinfo=ET)
    o_ms, c_ms = int(day0.replace(hour=9, minute=30).timestamp() * 1000), int(day0.replace(hour=16).timestamp() * 1000)
    async with svc.engine.sf() as s:
        arts = (await s.execute(select(TechniqueSourceArtifact).where(TechniqueSourceArtifact.kind == "scenarios",
                                                                      TechniqueSourceArtifact.completed_at >= day0.astimezone(dt.timezone.utc) - dt.timedelta(hours=6))
                                .order_by(TechniqueSourceArtifact.completed_at))).scalars().all()
        newest: dict = {}
        for a in arts:                                     # newest artifact per revision wins (a correction supersedes its base)
            newest[a.revision_id] = a
        payloads = [dict(a.payload or {}) for a in newest.values()]
        symbols = sorted({(sc.get("symbol") or {}).get("resolved") for p in payloads for sc in p.get("scenarios") or []} - {None})
        plans, bars = {}, {}
        for sym in symbols:
            runs = (await s.execute(select(TechniqueRun).where(TechniqueRun.symbol == sym, TechniqueRun.technique == "enhanced_market", TechniqueRun.status == "done",
                                                               TechniqueRun.created_at >= day0.astimezone(dt.timezone.utc) - dt.timedelta(hours=20))
                                    .order_by(TechniqueRun.created_at))).scalars().all()
            plans[sym] = [{"runId": r.id, "createdAt": r.created_at.isoformat(), "trigger": r.trigger, "plan": (r.result or {}).get("plan") or {}}
                          for r in runs if str(((r.result or {}).get("plan") or {}).get("planFor") or "")[:10] == session_day]
            rows = (await s.execute(text("select ts, open, high, low, close, volume from bars where symbol=:s and tf='1m' and ts >= :a and ts < :b order by ts"),
                                    {"s": sym, "a": o_ms, "b": c_ms})).mappings().all()
            bars[sym] = rows_to_bars(sym, "1m", [[r["ts"], r["open"], r["high"], r["low"], r["close"], r["volume"]] for r in rows])
    return {"payloads": payloads, "plans": plans, "bars": bars}


async def tick(svc, now_ms: int) -> dict:
    """One evaluation pass. Returns counts; never raises into the caller's loop."""
    if not bool(svc.engine.settings.get(KNOB, False)):
        return {"enabled": False}
    now = dt.datetime.fromtimestamp(now_ms / 1000.0, ET)
    if now.weekday() >= 5 or not ((9, 30) <= (now.hour, now.minute) < (16, 5)):
        return {"enabled": True, "rth": False}
    session_day = now.date().isoformat()
    inp = await load_inputs(svc, session_day)
    cands = scp.evaluate_session(payloads=inp["payloads"], plans_by_symbol=inp["plans"], bars_by_symbol=inp["bars"],
                                 baseline_by_symbol=baseline_states(svc.armer), session=session_day, upto_ts=now_ms)[:MAX_CANDIDATES]
    changed = await persist(svc, session_day, cands, now_ms)
    return {"enabled": True, "rth": True, "candidates": len(cands), "changed": changed}


async def persist(svc, session_day: str, cands: list, now_ms: int) -> int:
    """Upsert by candidate id; a row is rewritten only when its state changed, and every transition is kept in
    `payload.history` (at, disposition) - the record of WHEN the app knew what."""
    changed = 0
    now = dt.datetime.fromtimestamp(now_ms / 1000.0, dt.timezone.utc)
    async with svc.engine.sf() as s:
        for c in cands:
            cid = str(c.get("candidateId"))
            slim = {k: v for k, v in c.items() if k not in ("trackerEvents",)}
            sh = _h({k: slim.get(k) for k in ("disposition", "reason", "firedTs", "geometry", "structure")})   # never the bar counter: a quiet minute rewrites nothing
            row = await s.get(TechniqueSourceCandidate, cid, with_for_update=True)
            if row is None:
                s.add(TechniqueSourceCandidate(id=cid, session=session_day, symbol=str(c.get("symbol") or ""), scenario_id=str(c.get("scenarioId") or c.get("parentScenarioId") or ""),
                                               variant=str(c.get("variant") or ""), disposition=str(c.get("disposition") or ""), state_hash=sh,
                                               payload={**slim, "history": [{"at": now_ms, "disposition": c.get("disposition")}]}, created_at=now, updated_at=now))
                changed += 1
            elif row.state_hash != sh:
                hist = list((row.payload or {}).get("history") or [])
                if not hist or hist[-1].get("disposition") != c.get("disposition"):
                    hist.append({"at": now_ms, "disposition": c.get("disposition")})
                row.payload, row.disposition, row.state_hash, row.updated_at = {**slim, "history": hist}, str(c.get("disposition") or ""), sh, now
                changed += 1
        await s.commit()
    return changed


async def list_candidates(svc, session_day: str) -> list:
    async with svc.engine.sf() as s:
        rows = (await s.execute(select(TechniqueSourceCandidate).where(TechniqueSourceCandidate.session == session_day)
                                .order_by(TechniqueSourceCandidate.symbol, TechniqueSourceCandidate.variant))).scalars().all()
    return [{**scp.table_row(dict(r.payload or {}), baseline=(r.payload or {}).get("baseline")), "history": (r.payload or {}).get("history"),
             "updatedAt": r.updated_at.isoformat() if r.updated_at else None} for r in rows]
