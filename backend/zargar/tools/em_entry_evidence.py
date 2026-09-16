"""EM after-close LLM entry evidence over FROZEN deterministic decisions (Delivery B, 2026-09-15; DE-03/04/05). Evidence only.

    python -m zargar.tools.em_entry_evidence run --date 2026-09-16 [--max 40] [--timeout 60] [--dry-run] [--force]
    python -m zargar.tools.em_entry_evidence report --date 2026-09-16

`run` reads the session's `TechniqueEntryDecision` events (every deterministic attempt, allowed or refused), skips the
ones that already have a COMPLETED `TechniqueEntryEvidence` record for the same evidence key (skipped / unavailable /
timed-out / failed attempts stay retryable - their history is kept), builds the frozen input ONLY from the decision's
own snapshot and frozen bars (a decision without them is `unavailable`, never rebuilt from mutable current rows),
renders chart/facts from those frozen bars, calls the existing critic prompt on an ISOLATED analysis copy - one call at
a time, a finite per-call timeout, a paid-call budget - and appends one `TechniqueEntryEvidence` event per decision
(`authority = evidence_only`). Row-local failures become explicit outcomes and the batch continues.

It opens no engine, no trading service, no order/arm/settings-write capability; settings are read through the
non-mutating `ReadOnlySettings` projection (never `SettingsService.load()`). Gated by
`techniques.enhanced_market.fire_evidence_mode = after_close`; `--force` bypasses that setting only - a session that has
not closed is refused either way (this is not an intraday worker).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def _ms(d: dt.date, hh: int, mm: int) -> int:
    return int(dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=NY).timestamp() * 1000)


def _session_bounds_utc(date: str) -> tuple[dt.datetime, dt.datetime]:
    """The requested New York session day [00:00, next 00:00) as UTC datetimes (a proper upper bound)."""
    d = dt.date.fromisoformat(date)
    lo = dt.datetime.fromtimestamp(_ms(d, 0, 0) / 1000, dt.timezone.utc)
    hi = dt.datetime.fromtimestamp(_ms(d + dt.timedelta(days=1), 0, 0) / 1000, dt.timezone.utc)
    return lo, hi


def session_closed(date: str, now: dt.datetime | None = None) -> bool:
    """True once the requested session's 16:00 ET close has passed (after-close eligibility)."""
    d = dt.date.fromisoformat(date)
    now = now or dt.datetime.now(dt.timezone.utc)
    return now.timestamp() * 1000 >= _ms(d, 16, 0)


async def _open():
    """Database handles and a READ-ONLY settings projection; the journal is only used to append evidence records."""
    from ..bus import Bus
    from ..config import get_config
    from ..db import make_engine, make_session_factory
    from ..events import Journal
    from ..settings_service import read_only_settings
    from sqlalchemy import text
    cfg = get_config()
    eng = make_engine(cfg.database_url)
    sf = make_session_factory(eng)
    journal = Journal(sf, Bus())
    async with sf() as session:
        try:
            await session.execute(text("set transaction read only"))
        except Exception:
            pass
        settings = await read_only_settings(session)
    return cfg, eng, sf, settings, journal


async def _decisions(sf, date: str) -> list[dict]:
    from sqlalchemy import select
    from ..models import Event
    lo, hi = _session_bounds_utc(date)
    async with sf() as session:
        rows = (await session.scalars(select(Event).where(Event.type == "TechniqueEntryDecision", Event.ts >= lo, Event.ts < hi).order_by(Event.ts))).all()
        done = (await session.scalars(select(Event).where(Event.type == "TechniqueEntryEvidence", Event.ts >= lo))).all()
    have = {(e.payload or {}).get("evidenceKey") for e in done if (e.payload or {}).get("reviewOutcome") == "completed"}
    out = []
    for r in rows:
        p = dict(r.payload or {}); p["_ts"] = r.ts; p["_have"] = have
        out.append(p)
    return out


async def _trigger_for(sf, run_id: str, trigger_id: str) -> dict:
    """Retrospective helper only: the CURRENT saved trigger. The run path never uses it to fabricate a frozen input;
    it exists so a labelled retrospective reconstruction can be built explicitly when a person asks for one."""
    from ..models import TechniqueRun
    async with sf() as session:
        run = await session.get(TechniqueRun, run_id)
    plan = ((run.result or {}).get("plan") if run else {}) or {}
    return next((t for t in (plan.get("triggers") or []) if t.get("id") == trigger_id), {})


def _render_frozen(frozen_bars: list[dict] | None, symbol: str, cutoff: int | None) -> tuple[dict, str]:
    """Chart + facts from the decision's OWN frozen bars (never a bar-table query)."""
    if not frozen_bars:
        return {}, "FROZEN EVIDENCE: no frozen bars were captured at decision time - no chart, no facts."
    try:
        from ..domain import Bar
        from ..technique.analysis import AnalysisRequest, compute_facts, facts_for_prompt
        from ..technique.render import render_chart
        from ..technique.rulebook import Thresholds
        bars = [Bar(symbol=symbol, tf="1m", ts=int(b["ts"]), open=b["open"], high=b["high"], low=b["low"], close=b["close"], volume=int(b.get("volume") or 0))
                for b in frozen_bars if cutoff is None or int(b["ts"]) + 60_000 <= cutoff]
        if not bars:
            return {}, "FROZEN EVIDENCE: frozen bars all after the signal close - no chart, no facts."
        req = AnalysisRequest(symbol=symbol, primary_tf="1m", context_tfs=(), thresholds=Thresholds())
        facts = compute_facts(req, {"1m": bars}, [])
        txt = facts_for_prompt(facts) + f"\n\nFROZEN EVIDENCE: {len(bars)} bars frozen at decision time, ending at the signal bar close {cutoff}; no later price, fill or outcome is available."
        png = render_chart(bars[-240:], title=f"{symbol} 1m (frozen)", tf="1m")
        return ({"1m": png} if png else {}), txt
    except Exception as exc:  # noqa: BLE001 - rendering failure is an evidence outcome, recorded in the facts text
        return {}, f"FROZEN EVIDENCE: chart/facts unavailable ({type(exc).__name__})"


async def run(date: str, *, max_calls: int, timeout_s: float, dry_run: bool, force: bool) -> dict:
    from ..technique.entry_evidence import EVIDENCE_VERSION, EvidenceResult, evidence_key, frozen_input, prompt_identity, run_evidence, validate_frozen
    from ..technique.llm import config_from_settings, make_client
    from ..technique.rulebook import Thresholds
    if not session_closed(date):
        return {"skipped": True, "reason": f"session {date} has not closed (16:00 ET) - after-close evidence only, --force does not override this"}
    cfg, eng, sf, settings, journal = await _open()
    try:
        mode = str(settings.get("techniques.enhanced_market.fire_evidence_mode", "off") or "off")
        if mode != "after_close" and not force:
            return {"skipped": True, "reason": f"fire_evidence_mode={mode} (use --force to run evidence anyway; it is evidence only)"}
        budget = int(settings.get("techniques.enhanced_market.fire_evidence_max_calls", max_calls) or max_calls)
        budget = min(budget, max_calls) if max_calls else budget
        per_timeout = float(settings.get("techniques.enhanced_market.fire_evidence_timeout_seconds", timeout_s) or timeout_s)
        per_timeout = min(per_timeout, float(timeout_s)) if timeout_s else per_timeout      # the CLI bound is always honoured
        llm = config_from_settings(getattr(cfg, "anthropic_api_key", None), settings.get)
        client = None
        if llm is not None and getattr(llm, "available", False) and not dry_run:
            client = make_client(llm)
        prompt_hash = prompt_identity(llm)
        model = str(getattr(llm, "model", "unknown") or "unknown")
        decisions = await _decisions(sf, date)
        report = {"date": date, "decisions": len(decisions), "evaluated": 0, "skipped": 0, "records": [], "budget": budget, "dryRun": dry_run,
                  "promptHash": prompt_hash, "model": model}
        calls = 0
        for p in decisions:
            enq = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
            started = enq
            try:
                frozen = frozen_input(p)                                       # DE-05: the decision's own snapshot only
                key = evidence_key(frozen, prompt_hash=prompt_hash, model=model)
                if key in p.get("_have", set()):
                    report["skipped"] += 1; continue
                if frozen.get("frozenSource") != "decision_snapshot":
                    res = EvidenceResult("unavailable", error="no frozen decision snapshot - not rebuilt from current rows")
                elif validate_frozen(frozen):
                    res = EvidenceResult("invalid", error=validate_frozen(frozen))
                elif calls >= budget:
                    res = EvidenceResult("budget_skipped", error=f"evidence budget {budget} exhausted")
                elif dry_run or client is None:
                    res = EvidenceResult("unavailable", error=("dry run" if dry_run else "no model client / key"))
                elif not p.get("frozenBars"):
                    res = EvidenceResult("unavailable", error="no frozen bars captured at decision time - no chart-based opinion is bought")
                else:
                    calls += 1                                                 # one provider attempt per row, no retries
                    images, facts_txt = _render_frozen(p.get("frozenBars"), str(frozen.get("symbol")), frozen.get("frozenAt"))
                    started = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
                    res = await run_evidence(frozen, client=client, llm=llm, thresholds=Thresholds(), images=images, facts_txt=facts_txt, timeout_s=per_timeout)
            except Exception as exc:  # noqa: BLE001 - a row-local failure is an evidence outcome; the batch continues
                frozen = {"runId": p.get("runId"), "symbol": p.get("symbol"), "trigger": p.get("trigger"), "decisionId": p.get("decisionId"),
                          "inputHash": p.get("inputHash"), "decisionVersion": p.get("decisionVersion"), "verdict": p.get("verdict"), "frozenSource": "missing"}
                res = EvidenceResult("invalid", error=f"row failed: {type(exc).__name__}: {exc}")
            now = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
            rec = res.to_record(frozen, prompt_hash=prompt_hash, model=model, enqueued_at=enq, started_at=started, completed_at=now)
            rec["barCutoff"] = frozen.get("frozenAt")
            if not dry_run:
                await journal.append("TechniqueEntryEvidence", rec, aggregate_type="technique_run", aggregate_id=str(frozen.get("runId")))
            report["evaluated"] += 1
            report["records"].append({k: rec.get(k) for k in ("symbol", "trigger", "decisionId", "reviewOutcome", "modelOpinion", "appVerdict", "disagreement", "elapsedMs", "frozenSource")})
        return report
    finally:
        await eng.dispose()


async def report(date: str) -> dict:
    from sqlalchemy import select
    from ..models import Event
    cfg, eng, sf, settings, journal = await _open()
    try:
        lo, hi = _session_bounds_utc(date)
        async with sf() as session:
            dec = (await session.scalars(select(Event).where(Event.type == "TechniqueEntryDecision", Event.ts >= lo, Event.ts < hi))).all()
            ids = {(e.payload or {}).get("decisionId") for e in dec}
            evd = (await session.scalars(select(Event).where(Event.type == "TechniqueEntryEvidence", Event.ts >= lo))).all()
        by = {}
        for e in evd:
            p = e.payload or {}
            if p.get("decisionId") in ids:                                     # later reviews of THIS session's decisions only
                by.setdefault(p.get("decisionId"), []).append(p)
        rows = []
        for e in dec:
            p = e.payload or {}
            ev = by.get(p.get("decisionId")) or []
            rows.append({"symbol": p.get("symbol"), "trigger": p.get("trigger"), "family": p.get("triggerFamily"), "appVerdict": p.get("verdict"),
                         "reasonCodes": p.get("reasonCodes"), "frozen": bool(p.get("snapshot")), "frozenBars": p.get("frozenBarsCount"),
                         "evidence": [{k: x.get(k) for k in ("reviewOutcome", "modelOpinion", "disagreement", "elapsedMs", "frozenSource")} for x in ev]})
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
