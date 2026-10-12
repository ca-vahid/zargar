"""Alerts feed (`GET /api/alerts`): the app's recent alert-like journal events as one list.

Until now an alert reached a client only as a live WebSocket `technique` message (`kind: "alert"`)
or a push - a client that was not connected at that moment never saw it. The feed is a READ-ONLY
view over the append-only `events` table: it writes nothing and adds no journal types.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select

from . import events as ev
from .models import Event, Order

# The journal types that mean "the app raised its hand". One row each, written where the alert
# is raised (so the feed needs no new journal writes):
ALERT_EVENT_TYPES: tuple[str, ...] = (
    ev.TECHNIQUE_PLAN_ERROR,        # PlanRunner._alert: an armed plan's failure/attention (carries its level)
    "ManagedPositionAttention",     # PositionManager._alert: a held position needs a person
    "TipCardAlert",                 # a Tips approval card is still waiting for a human
    ev.TIP_EXECUTION_INCIDENT,      # automated tip entries paused (only opened / extended / release_refused)
    ev.TIP_SPREAD_LEG_FAILED,       # spread short leg died and the rollback failed - naked long
    ev.TIP_INTAKE_STALLED,          # the Discord intake pipe went quiet inside its window
    ev.TIP_INTAKE_PAGED,            # ...and that stall was escalated (or recovered)
    "HostMemoryLow",                # the host is nearly out of memory
    ev.BROKER_DISCONNECTED,         # a venue connection dropped / needs re-authorization
    ev.BROKER_SUBMIT_UNKNOWN,       # an order's submit outcome is unknown (being reconciled)
    ev.KILL_SWITCH_ENGAGED,         # global halt
    ev.BOOK_HALT_ENGAGED,           # one book's daily-loss halt
    ev.BOOK_PAUSED,                 # one book explicitly paused
    ev.TECHNIQUE_LOSS_HALT,         # one technique paused on one book for the day
    ev.ORDER_REJECTED,              # an order refused by the risk gate or the venue (research books excluded)
)

MAX_LIMIT = 200
BODY_MAX = 300
_INCIDENT_ACTIONS = ("opened", "extended", "release_refused")   # the rest are bookkeeping, not alerts


def _clip(text: Any, n: int = BODY_MAX) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _level(raw: Any, default: str = "error") -> str:
    v = str(raw or "").lower()
    if v in ("critical", "error"):
        return "error"
    if v in ("warning", "warn"):
        return "warning"
    if v == "info":
        return "info"
    return default


def _ts(value: dt.datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc).isoformat()


def alert_item(event_id: Any, ts: dt.datetime | None, type_: str, payload: dict | None,
               *, order: dict | None = None) -> dict | None:
    """Map one journal row to a feed item, or None when the row is not an alert
    (an incident's bookkeeping action). Pure - `order` is the rejected order's own row."""
    p = payload if isinstance(payload, dict) else {}
    symbol = p.get("symbol") or None
    level, title, body, url = "error", type_, "", None
    book = p.get("name") or p.get("portfolioId") or "a book"

    if type_ == ev.TECHNIQUE_PLAN_ERROR:
        level = _level(p.get("level"))
        title = f"{symbol or 'Plan'}: armed plan alert"
        body = p.get("error")
        url = f"/armed/{p['runId']}" if p.get("runId") else "/armed"
    elif type_ == "ManagedPositionAttention":
        level = _level(p.get("level"))
        title = f"{symbol or 'Position'}: position needs attention"
        body = p.get("error")
        url = "/armed"
    elif type_ == "TipCardAlert":
        level, title, body, url = "warning", f"{symbol or 'Tips'}: card needs you", p.get("text"), "/inbox"
    elif type_ == ev.TIP_EXECUTION_INCIDENT:
        action = p.get("action")
        if action not in _INCIDENT_ACTIONS:
            return None
        symbol = (p.get("scope") or {}).get("symbol") or None
        title = {"opened": "Tip entries paused: execution incident",
                 "extended": "Execution incident: more evidence",
                 "release_refused": "Execution incident: release refused"}[action]
        body = p.get("detail") if action == "release_refused" else (p.get("why") or p.get("cause"))
        url = "/inbox"
    elif type_ == ev.TIP_SPREAD_LEG_FAILED:
        symbol = p.get("underlying") or p.get("legSymbol") or None
        title = f"{symbol or 'Spread'}: spread leg failed - long leg is naked"
        body = f"{p.get('why') or ''} ({p.get('qty')} x {p.get('legSymbol')})"
        url = "/inbox"
    elif type_ == ev.TIP_INTAKE_STALLED:
        level, title, url = "warning", "Tips intake stalled", "/inbox"
        body = "; ".join(str(r) for r in (p.get("reasons") or []))
    elif type_ == ev.TIP_INTAKE_PAGED:
        recovered = p.get("phase") == "recovered"
        level = "info" if recovered else "error"
        title = "Tips intake recovered" if recovered else "Tips intake stalled - paged"
        idle = float(p.get("maxIdleSeconds" if recovered else "idleSeconds") or 0) / 60
        body = f"idle {idle:.0f} min (threshold {p.get('thresholdMinutes')} min)"
        url = "/inbox"
    elif type_ == "HostMemoryLow":
        title = "Host memory low"
        body = f"{p.get('freeGb')} GB free (threshold {p.get('thresholdGb')} GB)"
        url = "/"
    elif type_ == ev.BROKER_DISCONNECTED:
        who = p.get("connection") or p.get("broker") or "broker"
        title, body, url = f"Broker disconnected: {who}", p.get("error"), "/"
    elif type_ == ev.BROKER_SUBMIT_UNKNOWN:
        symbol = (order or {}).get("symbol") or None
        title = f"{symbol or 'Order'}: submit outcome unknown"
        body, url = p.get("error"), "/"
    elif type_ == ev.KILL_SWITCH_ENGAGED:
        title, url = "Kill switch engaged", "/armed"
        body = f"{p.get('reason') or ''} (by {p.get('source') or '?'})"
    elif type_ == ev.BOOK_HALT_ENGAGED:
        title, body, url = f"Book halted: {book}", p.get("reason"), "/armed"
    elif type_ == ev.BOOK_PAUSED:
        level, title, body, url = "warning", f"Book paused: {book}", p.get("reason"), "/armed"
    elif type_ == ev.TECHNIQUE_LOSS_HALT:
        title = f"Technique loss halt: {p.get('technique') or '?'}"
        body = f"lost {p.get('lossToday')} today ({p.get('pct')}% limit) - paused for the day"
        url = "/armed"
    elif type_ == ev.ORDER_REJECTED:
        o = order or {}
        symbol = o.get("symbol") or None
        level = "warning"
        what = " ".join(str(x) for x in (o.get("side"), o.get("qty"), symbol) if x not in (None, ""))
        title = f"Order rejected: {what}" if what else "Order rejected"
        body, url = p.get("reason"), "/"
    else:   # a type added to ALERT_EVENT_TYPES without a mapping still renders
        level = _level(p.get("level"))
        body = p.get("text") or p.get("error") or p.get("reason")

    return {"id": str(event_id), "ts": _ts(ts), "kind": type_, "level": level, "title": _clip(title, 120),
            "body": _clip(body), "symbol": symbol, "url": url}


async def recent_alerts(eng, limit: int = 50) -> list[dict]:
    """The newest `limit` alert items, newest first (limit capped at MAX_LIMIT)."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    out: list[dict] = []
    before: int | None = None
    page = max(100, limit * 2)
    async with eng.sf() as session:
        # Some rows are filtered after the read (incident bookkeeping, research-book rejects),
        # so read by pages until the list is full or the journal runs out (bounded: 5 pages).
        for _ in range(5):
            stmt = select(Event).where(Event.type.in_(ALERT_EVENT_TYPES)).order_by(Event.id.desc()).limit(page)
            if before is not None:
                stmt = stmt.where(Event.id < before)
            rows = (await session.execute(stmt)).scalars().all()
            if not rows:
                break
            before = rows[-1].id
            order_ids = [e.aggregate_id for e in rows
                         if e.type in (ev.ORDER_REJECTED, ev.BROKER_SUBMIT_UNKNOWN) and e.aggregate_id]
            orders: dict[str, dict] = {}
            if order_ids:
                for o in (await session.execute(select(Order).where(Order.id.in_(order_ids)))).scalars().all():
                    orders[o.id] = {"symbol": o.symbol, "side": o.side, "qty": f"{float(o.qty):g}"}
            for e in rows:
                if e.type == ev.ORDER_REJECTED and _research_book(eng, e.portfolio_id):
                    continue            # research books never page a human
                item = alert_item(e.id, e.ts, e.type, e.payload, order=orders.get(e.aggregate_id or ""))
                if item is not None:
                    out.append(item)
                    if len(out) >= limit:
                        return out
            if len(rows) < page:
                break
    return out


def _research_book(eng, portfolio_id: str | None) -> bool:
    if not portfolio_id:
        return False
    try:
        pf = eng.positions.portfolio(portfolio_id) or {}
    except Exception:
        return False
    return pf.get("kind") == "shadow" or bool(pf.get("book"))
