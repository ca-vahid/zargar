"""Retro runs — the analyst reviews its own closed positions (ANALYST.md §2.4).

Every closed tip position gets one retro (kind='retro' TipAnalystRun): the
position's full record (fills, trims, exit reasons, realized P&L) against the
entry-time opinion, the original tip and the analyst's own rules. Lessons go
to the shared notes; durable HOW-I-TRADE lessons update the rules (scope
`rule`). Nightly sweep = scheduler job `tip_retro`; positions retro exactly
once (tag `retro-done`, set only on success so failures retry tomorrow).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from .analyst import (
    TIMEOUT_S,
    TOOLS,
    _persist_run,
    _Recorder,
    _rules_text,
    run_agent_loop,
)

log = logging.getLogger("zargar.tip.retro")


class RetroOpinion(BaseModel):
    grade: str = Field(description='"good_call" | "bad_call" | "good_process_bad_luck" '
                                   '| "bad_process_good_luck"')
    what_worked: str = Field(default="", description="1-2 sentences")
    what_didnt: str = Field(default="", description="1-2 sentences")
    rule_update: Optional[str] = Field(
        default=None, description="The rule you saved/refined via save_note scope "
                                  "'rule' (restated here); null when nothing durable")
    confidence: float = Field(default=0.5)


RETRO_SYSTEM = """You are the tips desk trader reviewing YOUR OWN closed position — \
the retro that makes you better. You are handed the position's full record (fills, \
trims, exit reasons, realized P&L, sessions held), the opinion you wrote when you \
opened it, the original tip, and YOUR TRADING RULES.

Judge process, not just outcome:
- A winner from a bad process is "bad_process_good_luck" — say what was reckless.
- A loser from a sound process is "good_process_bad_luck" — do not overcorrect.
- Compare the EXIT CAMPAIGN you planned with what actually happened: did the trims \
land, did the stop/premium stop do its job, was the time box right?
- Check the source: did their framing (hedge, trim call, conviction) match reality? \
save_note source-scoped lessons. search_messages shows what they said around the trade; \
when a message is marked [images: <id>], view_image it — the chart they posted is part \
of the record.
- When the lesson is durable and about HOW YOU TRADE (sizing, liquidity, exits, \
patience), save_note it with scope "rule" — refine or replace an existing rule rather \
than duplicating it. Cite this position as the evidence. Not every retro earns a rule.

Use at most a few tool calls (metered). Then reply with ONLY one JSON object matching \
this schema — no prose, no markdown fences:
"""


async def retro_position(eng, row: dict, *, client=None) -> dict | None:
    """One closed tip position -> a kind='retro' TipAnalystRun. `row` is the
    managed_positions row projection (id/symbol/tags/config/state/legs).
    Fail-open; returns the retro opinion dict or None."""
    from ...domain import new_id
    from ...models import TipAnalystRun

    s = eng.settings
    api_key = getattr(eng.config, "anthropic_api_key", "")
    if client is None and not api_key:
        return None
    if client is None:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
    model = str(s.get("techniques.tip.analyst_model") or "") or eng.config.extraction_model
    max_tools = int(s.get("techniques.tip.analyst_max_tools", 8))

    cfg = row.get("config") or {}
    st = row.get("state") or {}
    source = next((t.split(":", 1)[1] for t in (row.get("tags") or [])
                   if str(t).startswith("source:")), None)
    entry_run_id = cfg.get("runId")
    entry_opinion, tip, signal_id = {}, {}, None
    if entry_run_id:
        async with eng.sf() as session:
            er = await session.get(TipAnalystRun, entry_run_id)
        if er is not None:
            entry_opinion, tip, signal_id = er.opinion or {}, er.tip or {}, er.signal_id

    sessions_held = max(0, len(st.get("sessionsSeen") or []) - 1)
    run_id = new_id()
    async with eng.sf() as session:
        session.add(TipAnalystRun(
            id=run_id, signal_id=signal_id, ticker=row.get("symbol") or "?",
            source=source, status="running", kind="retro", model=model,
            tools=[t["name"] for t in TOOLS],
            tip={"positionId": row.get("id"), "realizedPnl": st.get("realizedPnl"),
                 "sessionsHeld": sessions_held, **({"tip": tip} if tip else {})}))
        await session.commit()
    rec = _Recorder(eng, run_id)
    rules_txt, rules_n = await _rules_text(eng)
    pnl = float(st.get("realizedPnl") or 0)
    rec.step("start", f"Retro on closed position {str(row.get('id', ''))[:8]} "
             f"{row.get('symbol')} — realized {pnl:+.2f} over {sessions_held} session(s). "
             f"{rules_n or 'starter'} rule(s) in hand.",
             positionId=row.get("id"), rules=rules_n)

    position_txt = json.dumps({
        "symbol": row.get("symbol"), "direction": cfg.get("direction"),
        "entryUnderlying": cfg.get("entry"), "risk": cfg.get("risk"),
        "entryMark": cfg.get("entryMark"), "policy": cfg.get("policy"),
        "legs": row.get("legs"), "realizedPnl": pnl,
        "sessionsSeen": st.get("sessionsSeen"),
        "exits": (st.get("exits") or [])[-20:],
        "events": (st.get("events") or [])[-30:],
    }, default=str)[:6000]
    header = (f"Today (ET): {dt.datetime.now(dt.timezone(dt.timedelta(hours=-4))):%Y-%m-%d %H:%M}\n"
              f"CLOSED POSITION:\n{position_txt}\n\n"
              f"YOUR ENTRY-TIME OPINION: {json.dumps(entry_opinion, default=str)[:2500] or '(none recorded)'}\n"
              f"THE ORIGINAL TIP: {json.dumps(tip, default=str)[:1500] or '(unknown)'}\n"
              f"YOUR TRADING RULES (self-maintained):\n{rules_txt}")
    system = RETRO_SYSTEM + json.dumps(RetroOpinion.model_json_schema(), separators=(",", ":"))
    tools_used: list[dict] = []
    tool_ctx = {"ticker": row.get("symbol"), "source": source,
                "signal_id": signal_id, "run_id": run_id}
    try:
        text = await asyncio.wait_for(run_agent_loop(
            eng, client, model=model, system=system, header=header, rec=rec,
            run_id=run_id, max_tools=max_tools, tool_ctx=tool_ctx,
            tools_used=tools_used), timeout=TIMEOUT_S)
        if text is None:
            raise ValueError("no retro produced (loop exhausted)")
        i, j = text.find("{"), text.rfind("}")
        op = RetroOpinion.model_validate_json(text[i:j + 1])
    except Exception as exc:
        log.warning("tip retro failed for %s: %s", row.get("id"), exc)
        rec.step("error", f"Retro failed: {exc}")
        await _persist_run(eng, run_id, status="failed", rec=rec, error=str(exc)[:500])
        return None
    result = {"verdict": op.grade, "grade": op.grade, "whatWorked": op.what_worked,
              "whatDidnt": op.what_didnt, "ruleUpdate": op.rule_update,
              "confidence": op.confidence, "model": model, "toolsUsed": tools_used,
              "positionId": row.get("id"), "runId": run_id}
    rec.step("final", f"Retro: {op.grade.replace('_', ' ').upper()}."
             + (f" Worked: {op.what_worked}" if op.what_worked else "")
             + (f" Didn't: {op.what_didnt}" if op.what_didnt else "")
             + (f" Rule updated: {op.rule_update}" if op.rule_update else ""),
             opinion=result)
    await _persist_run(eng, run_id, status="done", rec=rec, opinion=result)
    return result


async def run_tip_retros(eng, *, client=None, limit: int = 5) -> dict:
    """The nightly sweep (scheduler job `tip_retro`): retro every closed tip
    position that has not had one, oldest first, tagging each `retro-done`."""
    from sqlalchemy import select as _sel

    from ...models import ManagedPositionRow

    if not bool(eng.settings.get("techniques.tip.retro_enabled", True)):
        return {"skipped": "techniques.tip.retro_enabled off"}
    async with eng.sf() as session:
        rows = (await session.execute(
            _sel(ManagedPositionRow)
            .where(ManagedPositionRow.technique == "tip",
                   ManagedPositionRow.status == "closed")
            .order_by(ManagedPositionRow.updated_at.asc()).limit(50))).scalars().all()
        todo = [{"id": r.id, "symbol": r.symbol, "tags": list(r.tags or []),
                 "config": r.config or {}, "state": r.state or {},
                 "legs": r.legs or []}
                for r in rows if "retro-done" not in (r.tags or [])][:limit]
    done = failed = 0
    for row in todo:
        res = await retro_position(eng, row, client=client)
        if res is None:
            failed += 1
            continue                    # retry tomorrow — the tag is only set on success
        done += 1
        async with eng.sf() as session:
            db = await session.get(ManagedPositionRow, row["id"])
            if db is not None:
                db.tags = list(db.tags or []) + ["retro-done"]
                await session.commit()
    return {"retros": done, "failed": failed, "pending": max(0, len(todo) - done - failed)}


async def grade_lanes(eng, *, limit: int = 25) -> dict:
    """ARM-GAPS D7: grade the analyst's now-vs-at_level choice once a tip
    RESOLVES (expired, dismissed, or its position closed). Deterministic — the
    shadow books already hold the counterfactual: the immediate book bought at
    tip time, the armed book waited for the level. Compares their realized $
    from the orders each book actually placed for the signal, journals
    `TipLaneGraded`, and saves a lane note the analyst reads."""
    import contextlib as _ctx

    from sqlalchemy import select as _sel

    from ... import events as ev
    from ...models import Event, Order, Signal

    async with eng.sf() as session:
        decided = (await session.execute(
            _sel(Event).where(Event.type == ev.TIP_LANE_DECIDED)
            .order_by(Event.id.desc()).limit(400))).scalars().all()
        graded_rows = (await session.execute(
            _sel(Event.payload).where(Event.type == ev.TIP_LANE_GRADED))).scalars().all()
    graded = {str((p or {}).get("signalId")) for p in graded_rows}
    todo: dict[str, str] = {}
    for e in decided:
        p = e.payload or {}
        sid, lane = str(p.get("signalId") or ""), str(p.get("lane") or "")
        if sid and lane in ("arm", "proposal") and sid not in graded and sid not in todo:
            todo[sid] = lane

    runner = getattr(eng, "tip_runner", None)
    mgr = getattr(eng, "position_manager", None)
    out = {"graded": 0, "skipped": 0}
    for sid, lane in list(todo.items())[:limit]:
        async with eng.sf() as session:
            sig = await session.get(Signal, sid)
        if sig is None:
            out["skipped"] += 1
            continue
        resolved = sig.status in ("expired", "dismissed")
        if not resolved and runner is not None and mgr is not None:
            with _ctx.suppress(Exception):
                run_ids = {r["id"] for r in await runner.runs_for_signal(sid)}
                resolved = any(p.get("runId") in run_ids and p.get("status") == "closed"
                               for p in mgr.positions())
        if not resolved:
            out["skipped"] += 1
            continue

        async with eng.sf() as session:
            orows = (await session.execute(
                _sel(Order).where(Order.signal_id == sid))).scalars().all()

        def book_pnl(book: str) -> float | None:
            rows = []
            for o in orows:
                pf = eng.positions.portfolio(o.portfolio_id) or {}
                if pf.get("book") != book:
                    continue
                if o.status not in ("FILLED", "PARTIALLY_FILLED"):
                    continue
                px, q = float(o.avg_fill_price or 0), float(o.filled_qty or 0)
                if px <= 0 or q <= 0:
                    continue
                rows.append(o)
            if not rows:
                return 0.0            # the book simply never traded this tip
            if not (any(o.side == "BUY" for o in rows) and any(o.side == "SELL" for o in rows)):
                return None           # still open — not comparable yet
            pnl = 0.0
            for o in rows:
                mult = 100.0 if o.sec_type == "OPT" else 1.0
                pnl += float(o.avg_fill_price) * float(o.filled_qty) * mult \
                    * (1 if o.side == "SELL" else -1)
            return round(pnl, 2)

        imm, armed_pnl = book_pnl("immediate"), book_pnl("armed")
        verdict = "insufficient"
        if imm is not None and armed_pnl is not None:
            verdict = ("now_better" if imm > armed_pnl + 1e-6
                       else "at_level_better" if armed_pnl > imm + 1e-6 else "even")
        await eng.journal.append(ev.TIP_LANE_GRADED, {
            "signalId": sid, "ticker": sig.ticker, "source": sig.source_name,
            "lane": lane, "immediatePnl": imm, "armedPnl": armed_pnl,
            "verdict": verdict}, aggregate_type="signal", aggregate_id=sid)
        if verdict != "insufficient" and getattr(eng, "signals_service", None) is not None:
            with _ctx.suppress(Exception):
                await eng.signals_service.add_tip_note(
                    f"source:{sig.source_name or 'unknown'}",
                    f"LANE GRADE: {sig.ticker} — the desk chose '{lane}'; buying at tip time "
                    f"made ${imm:+,.0f} vs waiting for the level ${armed_pnl:+,.0f} → "
                    f"{verdict.replace('_', ' ')}.",
                    author="lane-grader", signal_id=sid)
        out["graded"] += 1
    return out


UNFILLED_RETRO_SYSTEM = """You are the tips desk trader reviewing tips that EXPIRED \
UNFILLED — the level never came before the contract/horizon died. The misses teach too: \
were these levels ever realistic? Is this source stating entries too far from the market? \
Should the desk have taken some at tip time instead of waiting?

You are handed the expired tips from ONE source, the source's scorecard, and YOUR \
TRADING RULES. Look for a PATTERN across the batch, not per-tip noise. save_note a \
source-scoped lesson when there is one; update a rule (scope "rule") only for a durable \
HOW-I-TRADE lesson with the evidence. Not every batch earns either.

Use at most a few tool calls (metered). Then reply with ONLY one JSON object matching \
this schema — no prose, no markdown fences:
"""


async def run_unfilled_retros(eng, *, client=None, limit: int = 3) -> dict:
    """ARM-GAPS D8: the misses reach the rulebook — one batched retro run per
    source per sweep over recently EXPIRED (never-filled) tips; each signal is
    marked so it is reviewed exactly once."""
    from sqlalchemy import select as _sel

    from ...domain import new_id
    from ...models import Signal, TipAnalystRun

    if not bool(eng.settings.get("techniques.tip.retro_enabled", True)):
        return {"skipped": "techniques.tip.retro_enabled off"}
    api_key = getattr(eng.config, "anthropic_api_key", "")
    if client is None and not api_key:
        return {"skipped": "no analyst client"}
    if client is None:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
    model = str(eng.settings.get("techniques.tip.analyst_model") or "") or eng.config.extraction_model
    max_tools = int(eng.settings.get("techniques.tip.analyst_max_tools", 8))

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=14)
    async with eng.sf() as session:
        rows = (await session.execute(
            _sel(Signal).where(Signal.status == "expired",
                               Signal.created_at >= cutoff)
            .order_by(Signal.created_at.asc()).limit(100))).scalars().all()
    by_source: dict[str, list] = {}
    for r in rows:
        if (r.extraction or {}).get("unfilledRetro"):
            continue
        by_source.setdefault(r.source_name or "unknown", []).append(r)
    ran = 0
    for source, sigs in list(by_source.items())[:limit]:
        sigs = sigs[:8]
        run_id = new_id()
        async with eng.sf() as session:
            session.add(TipAnalystRun(
                id=run_id, signal_id=sigs[0].id, ticker=sigs[0].ticker, source=source,
                status="running", kind="retro", model=model,
                tools=[t["name"] for t in TOOLS],
                tip={"unfilledBatch": [{"ticker": s.ticker, "direction": s.direction,
                                        "entry": s.entry_price, "seen": s.seen_count}
                                       for s in sigs]}))
            await session.commit()
        rec = _Recorder(eng, run_id)
        rules_txt, _n = await _rules_text(eng)
        rec.step("start", f"Unfilled-tips retro for {source}: {len(sigs)} tip(s) expired "
                          f"without the level ever coming.", source=source)
        tips_txt = json.dumps([{
            "ticker": s.ticker, "direction": s.direction, "entry": s.entry_price,
            "stop": s.stop_price, "target": s.target_price, "strike": s.strike,
            "expiry": s.expiry, "seenCount": s.seen_count,
            "stated": (s.created_at.isoformat()[:16] if s.created_at else None)}
            for s in sigs], default=str)[:4000]
        header = (f"Today (ET): {dt.datetime.now(dt.timezone(dt.timedelta(hours=-4))):%Y-%m-%d %H:%M}\n"
                  f"SOURCE: {source}\nEXPIRED-UNFILLED TIPS (the level never came):\n{tips_txt}\n\n"
                  f"YOUR TRADING RULES (self-maintained):\n{rules_txt}")
        system = UNFILLED_RETRO_SYSTEM + json.dumps(RetroOpinion.model_json_schema(),
                                                    separators=(",", ":"))
        tools_used: list[dict] = []
        try:
            text = await asyncio.wait_for(run_agent_loop(
                eng, client, model=model, system=system, header=header, rec=rec,
                run_id=run_id, max_tools=max_tools,
                tool_ctx={"ticker": sigs[0].ticker, "source": source,
                          "signal_id": sigs[0].id, "run_id": run_id},
                tools_used=tools_used), timeout=TIMEOUT_S)
            if text is None:
                raise ValueError("no retro produced (loop exhausted)")
            op = RetroOpinion.model_validate_json(text[text.find("{"):text.rfind("}") + 1])
        except Exception as exc:
            log.warning("unfilled retro failed for %s: %s", source, exc)
            rec.step("error", f"Unfilled retro failed: {exc}")
            await _persist_run(eng, run_id, status="failed", rec=rec, error=str(exc)[:500])
            continue
        result = {"verdict": op.grade, "grade": op.grade, "whatWorked": op.what_worked,
                  "whatDidnt": op.what_didnt, "ruleUpdate": op.rule_update,
                  "confidence": op.confidence, "model": model, "toolsUsed": tools_used,
                  "unfilledBatch": len(sigs), "runId": run_id}
        rec.step("final", f"Unfilled retro ({source}): {op.grade.replace('_', ' ')}."
                 + (f" {op.what_didnt}" if op.what_didnt else ""), opinion=result)
        await _persist_run(eng, run_id, status="done", rec=rec, opinion=result)
        async with eng.sf() as session:
            for s in sigs:
                db = await session.get(Signal, s.id)
                if db is not None:
                    db.extraction = {**(db.extraction or {}), "unfilledRetro": run_id}
            await session.commit()
        ran += 1
    return {"unfilledRetros": ran}


async def nightly_tip_review(eng, *, client=None) -> dict:
    """The nightly sweep (scheduler job `tip_retro`): position retros, then the
    unfilled-tips batch retros, then the deterministic lane grading."""
    out = await run_tip_retros(eng, client=client)
    try:
        out["unfilled"] = await run_unfilled_retros(eng, client=client)
    except Exception:
        log.exception("unfilled retro sweep failed")
    try:
        out["lanes"] = await grade_lanes(eng)
    except Exception:
        log.exception("lane grading failed")
    return out
