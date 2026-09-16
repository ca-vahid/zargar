"""EM after-close LLM entry evidence over FROZEN deterministic decisions (Delivery B, 2026-09-15). Evidence only.

    python -m zargar.tools.em_entry_evidence run --date 2026-09-16 [--max 40] [--timeout 60] [--dry-run]
    python -m zargar.tools.em_entry_evidence report --date 2026-09-16

`run` reads the session's `TechniqueEntryDecision` events (every deterministic attempt, allowed or refused), skips the
ones that already have a `TechniqueEntryEvidence` record for the same evidence key, renders the chart and facts from
STORED bars at or before each decision's signal-bar close (never later bars, fills or outcomes), calls the existing
critic prompt on an ISOLATED analysis copy - one call at a time, a per-call timeout and a paid-call budget - and
appends one `TechniqueEntryEvidence` event per decision (`authority = evidence_only`). It opens no engine, no trading
service, no order/arm/settings-write capability: a failed, timed-out or budget-skipped call is an evidence outcome.
Gated by `techniques.enhanced_market.fire_evidence_mode = after_close` (`--force` runs it regardless, still evidence only).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import sys
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def _ms(d: dt.date, hh: int, mm: int) -> int:
    return int(dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=NY).timestamp() * 1000)


async def _open():
    from ..bus import Bus
    from ..config import get_config
    from ..db import make_engine, make_session_factory
    from ..events import Journal
    from ..settings_service import SettingsService
    cfg = get_config()
    eng = make_engine(cfg.database_url)
    sf = make_session_factory(eng)
    bus = Bus()
    journal = Journal(sf, bus)
    settings = SettingsService(sf, bus, journal)
    await settings.load()
    return cfg, eng, sf, settings, journal


async def _decisions(sf, date: str) -> list[dict]:
    from sqlalchemy import select
    from ..models import Event
    d = dt.date.fromisoformat(date)
    lo = dt.datetime.fromtimestamp(_ms(d, 0, 0) / 1000, dt.timezone.utc); hi = dt.datetime.fromtimestamp(_ms(d, 23, 59) / 1000, dt.timezone.utc)
    async with sf() as session:
        rows = (await session.scalars(select(Event).where(Event.type == "TechniqueEntryDecision", Event.ts >= lo, Event.ts <= hi).order_by(Event.ts))).all()
        done = (await session.scalars(select(Event).where(Event.type == "TechniqueEntryEvidence", Event.ts >= lo))).all()
    have = {(e.payload or {}).get("evidenceKey") for e in done}
    out = []
    for r in rows:
        p = dict(r.payload or {}); p["_ts"] = r.ts; p["_have"] = have
        out.append(p)
    return out


async def _trigger_for(sf, run_id: str, trigger_id: str) -> dict:
    from ..models import TechniqueRun
    async with sf() as session:
        run = await session.get(TechniqueRun, run_id)
    plan = ((run.result or {}).get("plan") if run else {}) or {}
    return next((t for t in (plan.get("triggers") or []) if t.get("id") == trigger_id), {})


async def _bars_upto(sf, symbol: str, cutoff_ms: int, limit: int = 600) -> list:
    from sqlalchemy import select
    from ..domain import Bar
    from ..models import Bar as BarRow
    async with sf() as session:
        rows = (await session.scalars(select(BarRow).where(BarRow.symbol == symbol, BarRow.tf == "1m", BarRow.ts + 60_000 <= cutoff_ms)
                                      .order_by(BarRow.ts.desc()).limit(limit))).all()
    return [Bar(symbol=symbol, tf="1m", ts=int(b.ts), open=b.open, high=b.high, low=b.low, close=b.close, volume=int(b.volume or 0)) for b in reversed(rows)]


async def run(date: str, *, max_calls: int, timeout_s: float, dry_run: bool, force: bool) -> dict:
    from ..technique.entry_evidence import EVIDENCE_VERSION, EvidenceResult, evidence_key, frozen_input, run_evidence
    from ..technique.llm import make_client
    from ..technique.rulebook import Thresholds
    cfg, eng, sf, settings, journal = await _open()
    try:
        mode = str(settings.get("techniques.enhanced_market.fire_evidence_mode", "off") or "off")
        if mode != "after_close" and not force:
            return {"skipped": True, "reason": f"fire_evidence_mode={mode} (use --force to run evidence anyway; it is evidence only)"}
        budget = int(settings.get("techniques.enhanced_market.fire_evidence_max_calls", max_calls) or max_calls)
        budget = min(budget, max_calls) if max_calls else budget
        per_timeout = float(settings.get("techniques.enhanced_market.fire_evidence_timeout_seconds", timeout_s) or timeout_s)
        from ..technique.llm import config_from_settings
        llm = config_from_settings(getattr(cfg, "anthropic_api_key", None), settings.get)   # the same resolution the technique uses
        client = None
        if llm is not None and getattr(llm, "available", False) and not dry_run:
            client = make_client(llm)
        prompt_hash = hashlib.sha256(EVIDENCE_VERSION.encode()).hexdigest()[:12]
        model = str(getattr(llm, "model", "unknown") or "unknown")
        decisions = await _decisions(sf, date)
        report = {"date": date, "decisions": len(decisions), "evaluated": 0, "skipped": 0, "records": [], "budget": budget, "dryRun": dry_run}
        calls = 0
        for p in decisions:
            trig = await _trigger_for(sf, p.get("runId"), p.get("trigger"))
            frozen = frozen_input(p, trig)
            key = evidence_key(frozen, prompt_hash=prompt_hash, model=model)
            if key in p["_have"]:
                report["skipped"] += 1; continue
            enq = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
            if calls >= budget:
                res = EvidenceResult("budget_skipped", error=f"evidence budget {budget} exhausted")
            elif dry_run or client is None:
                res = EvidenceResult("unavailable", error=("dry run" if dry_run else "no model client / key"))
            else:
                calls += 1
                cutoff = int(frozen.get("frozenAt") or 0)
                bars = await _bars_upto(sf, str(frozen.get("symbol")), cutoff) if cutoff else []
                images, facts_txt = {}, ""
                try:
                    from ..technique.analysis import AnalysisRequest, compute_facts, facts_for_prompt
                    from ..technique.render import render_chart
                    if bars:
                        req = AnalysisRequest(symbol=str(frozen["symbol"]), primary_tf="1m", context_tfs=(), thresholds=Thresholds())
                        facts = compute_facts(req, {"1m": bars}, [])
                        facts_txt = facts_for_prompt(facts) + f"\n\nFROZEN EVIDENCE: bars end at the signal bar close {cutoff}; no later price, fill or outcome is available."
                        png = render_chart(bars[-240:], title=f"{frozen['symbol']} 1m (frozen)", tf="1m")
                        images = {"1m": png} if png else {}
                except Exception as exc:  # noqa: BLE001 - rendering failure is an evidence outcome
                    facts_txt = f"FROZEN EVIDENCE: chart/facts unavailable ({type(exc).__name__})"
                res = await run_evidence(frozen, client=client, llm=llm, thresholds=Thresholds(), images=images, facts_txt=facts_txt, timeout_s=per_timeout)
            now = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
            rec = res.to_record(frozen, prompt_hash=prompt_hash, model=model, enqueued_at=enq, started_at=enq, completed_at=now)
            rec["barCutoff"] = frozen.get("frozenAt")
            if not dry_run:
                await journal.append("TechniqueEntryEvidence", rec, aggregate_type="technique_run", aggregate_id=str(frozen.get("runId")))
            report["evaluated"] += 1
            report["records"].append({k: rec.get(k) for k in ("symbol", "trigger", "decisionId", "reviewOutcome", "modelOpinion", "appVerdict", "disagreement", "elapsedMs")})
        return report
    finally:
        await eng.dispose()


async def report(date: str) -> dict:
    from sqlalchemy import select
    from ..models import Event
    cfg, eng, sf, settings, journal = await _open()
    try:
        d = dt.date.fromisoformat(date)
        lo = dt.datetime.fromtimestamp(_ms(d, 0, 0) / 1000, dt.timezone.utc)
        async with sf() as session:
            dec = (await session.scalars(select(Event).where(Event.type == "TechniqueEntryDecision", Event.ts >= lo))).all()
            evd = (await session.scalars(select(Event).where(Event.type == "TechniqueEntryEvidence", Event.ts >= lo))).all()
        by = {}
        for e in evd:
            p = e.payload or {}; by.setdefault(p.get("decisionId"), []).append(p)
        rows = []
        for e in dec:
            p = e.payload or {}
            ev = by.get(p.get("decisionId")) or []
            rows.append({"symbol": p.get("symbol"), "trigger": p.get("trigger"), "family": p.get("triggerFamily"), "appVerdict": p.get("verdict"),
                         "reasonCodes": p.get("reasonCodes"), "evidence": [{k: x.get(k) for k in ("reviewOutcome", "modelOpinion", "disagreement", "elapsedMs")} for x in ev]})
        cov = sum(1 for r in rows if any(x.get("reviewOutcome") == "completed" for x in r["evidence"]))
        return {"date": date, "decisions": len(rows), "withCompletedEvidence": cov, "rows": rows,
                "note": "LLM evidence only; no trading effect. Coverage before any win-rate claim; disagreement is not proof either evaluator is better."}
    finally:
        await eng.dispose()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--date", required=True); r.add_argument("--max", type=int, default=40); r.add_argument("--timeout", type=float, default=60.0)
    r.add_argument("--dry-run", action="store_true"); r.add_argument("--force", action="store_true")
    q = sub.add_parser("report"); q.add_argument("--date", required=True)
    a = ap.parse_args(argv)
    out = asyncio.run(run(a.date, max_calls=a.max, timeout_s=a.timeout, dry_run=a.dry_run, force=a.force) if a.cmd == "run" else report(a.date))
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
