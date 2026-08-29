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
