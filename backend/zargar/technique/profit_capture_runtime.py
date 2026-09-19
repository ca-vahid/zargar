"""ED-04 runtime glue (EM-only): builds the `ProfitCaptureObserver` for the EM armer - what to collect from the live
runner, where to write. Kept apart from `profit_capture.py` so the record and the reducer stay pure and testable.

Collection reads in-memory state only (the runner's trades, the quote cache, the keeper's cash): no network, no model,
no extra data fetch. The write is one INSERT into `technique_book_snapshots` on the recorder's own task."""
from __future__ import annotations

import datetime as dt
import logging
import time
from zoneinfo import ZoneInfo

from ..domain import new_id
from .profit_capture import ProfitCaptureObserver

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
KNOB = "techniques.enhanced_market.book_snapshot_observe"
CADENCE = "techniques.enhanced_market.book_snapshot_seconds"


def quote_dict(q) -> dict | None:
    """The quote cache's row as the record's plain dict - identity and freshness travel with the prices."""
    if q is None:
        return None
    src = str(getattr(q, "source", "") or "")
    return {"bid": float(getattr(q, "bid", 0) or 0), "ask": float(getattr(q, "ask", 0) or 0), "last": float(getattr(q, "last", 0) or 0),
            "bidSize": (int(getattr(q, "bid_size", 0) or 0) or None), "askSize": (int(getattr(q, "ask_size", 0) or 0) or None),
            "source": src or "feed", "rawSource": getattr(q, "raw_source", "") or None, "transform": getattr(q, "transform", "") or None,
            "delayed": bool(getattr(q, "delayed", False)),
            # the venue time of the BID/ASK: options carry it in source_ts, shares in quote_ts (PR #204 r2); never `ts` (receipt)
            "sourceTs": int(getattr(q, "source_ts", 0) or getattr(q, "quote_ts", 0) or 0),
            "receivedTs": int(getattr(q, "ts", 0) or 0), "session": getattr(q, "session", "") or None, "feed": src or "feed"}


def session_of(now_ms: int) -> str:
    return dt.datetime.fromtimestamp(now_ms / 1000.0, ET).date().isoformat()


def collect_inputs(armer, closed_cache: dict, now_ms: int) -> dict | None:
    s = armer.engine.settings
    pid = str(s.get("techniques.enhanced_market.default_portfolio", "") or s.get("technique.arm.default_portfolio", "") or "")
    if not pid:
        return None
    session = session_of(now_ms)
    if closed_cache.get("_session") != session:
        closed_cache.clear()
        closed_cache["_session"] = session
    positions, quotes = [], {}
    for ap in list(getattr(armer, "_armed", {}).values()):
        if str(ap.config.portfolio_id) != pid:
            continue
        for tr in ap.trades.values():
            if float(tr.filled_qty or 0) <= 0:
                continue
            key = (ap.run_id, tr.trigger_id, str(tr.entry_order_id or ""))
            fees = float(armer._fees_paid(tr))
            if float(tr.remaining or 0) <= 1e-9:
                closed_cache[key] = (float(tr.realized_pnl or 0.0) - fees, fees)
                continue
            closed_cache.pop(key, None)
            held = tr.order_symbol if (tr.instrument == "options" and tr.order_symbol) else ap.symbol
            positions.append({"runId": ap.run_id, "trigger": tr.trigger_id, "tradeInstance": str(tr.entry_order_id or ""),
                              "symbol": held, "underlying": ap.symbol, "direction": tr.direction, "instrument": tr.instrument,
                              "multiplier": float(tr.multiplier or 1.0), "positionSide": "long",       # EM only ever BUYS to open
                              "original": float(tr.filled_qty), "remaining": float(tr.remaining), "pendingExit": float(tr.pending_exit_qty),
                              "avgFill": tr.avg_fill, "realizedGross": float(tr.realized_pnl or 0.0), "feesPaid": fees})
            quotes[held] = quote_dict(armer.engine.quotes.get(held))
    closed = [v for k, v in closed_cache.items() if k != "_session"]
    book = None
    try:
        book = armer.engine.positions.portfolio(pid)
    except Exception:                                     # noqa: BLE001
        book = None
    per = float(armer.rt("fee_per_contract", 0.0) or 0.0) or (float(s.get("options.fee_per_contract", 0.0) or 0.0) + float(s.get("sim.reg_fee_per_contract", 0.0) or 0.0))
    try:
        from .. import build_sha
        build = build_sha()
    except Exception:                                     # noqa: BLE001
        build = ""
    return {"ids": {"portfolioId": pid, "session": session, "build": build, "baseline": "em-practice-baseline",
                    "policy": {"fireDecisionMode": s.get("techniques.enhanced_market.fire_decision_mode", None),
                               "firstSaleGate": s.get("techniques.enhanced_market.first_sale_rr_gate", None),
                               "preparationPolicy": s.get("techniques.enhanced_market.preparation_policy", None),
                               "shadowExitObserve": s.get("techniques.enhanced_market.shadow_exit_observe", None)}},
            "cash": (book or {}).get("cash"), "realized_closed_net": sum(v[0] for v in closed), "fees_closed": sum(v[1] for v in closed),
            "positions": positions, "quotes": quotes, "fee_per_contract": per, "stock_fee": float(s.get("sim.stock_commission", 0.0) or 0.0)}


def build_observer(armer) -> ProfitCaptureObserver:
    closed_cache: dict = {}
    clock = lambda: int(time.time() * 1000)               # noqa: E731

    async def write(rec: dict) -> None:
        from ..models import TechniqueBookSnapshot
        ids = rec.get("ids") or {}
        async with armer.engine.sf() as session:
            session.add(TechniqueBookSnapshot(
                id=new_id(), portfolio_id=str(ids.get("portfolioId") or ""), session=str(ids.get("session") or ""), seq=int(rec.get("seq") or 0),
                captured_at=dt.datetime.fromtimestamp(int(rec["capturedAt"]) / 1000.0, dt.timezone.utc), reason=str(rec.get("reason") or "")[:24],
                causal_run_id=((rec.get("causal") or {}).get("runId")), build=str(ids.get("build") or "")[:64],
                scorable=bool((rec.get("book") or {}).get("scorable")), payload=rec))
            await session.commit()

    def on_drop(why: str, rec: dict) -> None:
        log.warning("EM book snapshot dropped (%s) seq=%s reason=%s", why, rec.get("seq"), rec.get("reason"))

    return ProfitCaptureObserver(
        enabled=lambda: bool(armer.engine.settings.get(KNOB, False)),
        collect=lambda: collect_inputs(armer, closed_cache, clock()),
        write=write, clock_ms=clock,
        cadence_s=lambda: float(armer.engine.settings.get(CADENCE, 30.0) or 30.0), on_drop=on_drop)
