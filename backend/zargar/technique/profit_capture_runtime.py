"""ED-04 runtime glue (EM-only; `book-snapshot-v2`, IR-02 / IR-03): builds the `ProfitCaptureObserver` for the EM armer.

SYNCHRONOUS half (`collect_inputs`, called from the runner): in-memory state only - this session's held positions, the
quote cache's evidence (nothing relabelled), the keeper's cash. No database, no network, no model.

ASYNCHRONOUS half (the recorder's own task, never a trading path): `SessionLedger.as_of` reads the book's EXECUTIONS of
the session and builds the realized ledger as of each record's capture time - so realized totals and per-trade
attribution survive a restart, a disarm and a late recorder start, and prior-session fills are excluded by the window.
The write is idempotent by the record's `captureId`."""
from __future__ import annotations

import datetime as dt
import logging
import time
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .profit_capture import ProfitCaptureObserver, build_ledger, finalize_book
from .research_recorder import feed_identity, quote_evidence

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
KNOB = "techniques.enhanced_market.book_snapshot_observe"
CADENCE = "techniques.enhanced_market.book_snapshot_seconds"


def session_of(now_ms: int) -> str:
    return dt.datetime.fromtimestamp(now_ms / 1000.0, ET).date().isoformat()


def session_window(session: str) -> tuple[int, int]:
    """[04:00, 20:00) ET of the session day: every fill of THIS session, none of a prior one."""
    d = dt.date.fromisoformat(session)
    a = dt.datetime(d.year, d.month, d.day, 4, 0, tzinfo=ET)
    return int(a.timestamp() * 1000), int((a + dt.timedelta(hours=16)).timestamp() * 1000)


def book_id(settings) -> str:
    return str(settings.get("techniques.enhanced_market.default_portfolio", "") or settings.get("technique.arm.default_portfolio", "") or "")


def collect_inputs(armer, now_ms: int) -> dict | None:
    """Positions HELD NOW in the EM Practice book by plans of THIS session (a plan of a prior session still in memory is
    not this session's trade; were it still held it would surface as a ledger/position mismatch - unscorable, visibly).
    Realized results are NOT collected here: they come from executions (`SessionLedger`)."""
    s = armer.engine.settings
    pid = book_id(s)
    if not pid:
        return None
    session = session_of(now_ms)
    feed = feed_identity(armer.engine)
    positions, quotes = [], {}
    for ap in list(getattr(armer, "_armed", {}).values()):
        if str(ap.config.portfolio_id) != pid or str(getattr(ap, "plan_for", "") or "")[:10] != session:
            continue
        for tr in ap.trades.values():
            if float(tr.filled_qty or 0) <= 0 or float(tr.remaining or 0) <= 1e-9:
                continue
            is_opt = tr.instrument == "options" and bool(tr.order_symbol)
            held = tr.order_symbol if is_opt else ap.symbol
            positions.append({"runId": ap.run_id, "trigger": tr.trigger_id, "tradeInstance": str(tr.entry_order_id or ""),
                              "symbol": held, "underlying": ap.symbol, "direction": tr.direction, "instrument": tr.instrument,
                              "multiplier": float(tr.multiplier or 1.0), "positionSide": "long",       # EM only ever BUYS to open
                              "original": float(tr.filled_qty), "remaining": float(tr.remaining), "pendingExit": float(tr.pending_exit_qty),
                              "avgFill": tr.avg_fill})
            if held not in quotes:
                quotes[held] = quote_evidence(armer.engine.quotes.get(held), symbol=held, is_option=is_opt, feed=feed)
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
            "cash": (book or {}).get("cash"), "positions": positions, "quotes": quotes, "fee_per_contract": per,
            "stock_fee": float(s.get("sim.stock_commission", 0.0) or 0.0)}


class SessionLedger:
    """The session's executions of ONE book, read on the recorder's task. A bounded incremental projection: only rows newer
    than the last one seen are fetched after the first restore; the ledger for a record is rebuilt (pure) as of that
    record's capture time. A failed read = `status: error` = unscorable, visibly - never a guess."""

    def __init__(self, sf):
        self._sf = sf
        self._session: str | None = None
        self._pid: str | None = None
        self._rows: list = []
        self._seen: set = set()
        self.restored = False

    async def as_of(self, pid: str, session: str, as_of_ms: int) -> dict:
        if (pid, session) != (self._pid, self._session):
            self._pid, self._session, self._rows, self._seen, self.restored = pid, session, [], set(), False
        lo, hi = session_window(session)
        since = max([lo] + [int(r["tsMs"]) for r in self._rows]) if self._rows else lo
        async with self._sf() as s:
            got = (await s.execute(text("""select id, order_id, symbol, side, qty, price, commission, ts from executions
                                           where portfolio_id = :p and ts >= :a and ts < :b order by ts"""),
                                   {"p": pid, "a": dt.datetime.fromtimestamp(since / 1000.0, dt.timezone.utc),
                                    "b": dt.datetime.fromtimestamp(hi / 1000.0, dt.timezone.utc)})).mappings().all()
        for r in got:
            if r["id"] in self._seen:
                continue
            self._seen.add(r["id"])
            self._rows.append({"orderId": r["order_id"], "symbol": r["symbol"], "side": r["side"], "qty": float(r["qty"]), "price": float(r["price"]),
                               "commission": float(r["commission"] or 0.0), "tsMs": int(r["ts"].timestamp() * 1000)})
        self.restored = True
        return build_ledger(self._rows, window=(lo, hi), as_of_ms=as_of_ms)


def build_observer(armer) -> ProfitCaptureObserver:
    clock = lambda: int(time.time() * 1000)               # noqa: E731
    ledger = SessionLedger(armer.engine.sf)

    async def finalize(rec: dict) -> dict:
        ids = rec.get("ids") or {}
        return finalize_book(rec, await ledger.as_of(str(ids.get("portfolioId") or ""), str(ids.get("session") or ""), int(rec["capturedAt"])))

    async def write(rec: dict) -> None:
        from ..models import TechniqueBookSnapshot
        ids = rec.get("ids") or {}
        async with armer.engine.sf() as session:
            if await session.get(TechniqueBookSnapshot, rec["captureId"]) is not None:
                return                                    # already acknowledged (an ambiguous earlier commit): exactly one row
            session.add(TechniqueBookSnapshot(
                id=rec["captureId"], portfolio_id=str(ids.get("portfolioId") or ""), session=str(ids.get("session") or ""), seq=int(rec.get("seq") or 0),
                captured_at=dt.datetime.fromtimestamp(int(rec["capturedAt"]) / 1000.0, dt.timezone.utc), reason=str(rec.get("reason") or "")[:24],
                causal_run_id=((rec.get("causal") or {}).get("runId")), build=str(ids.get("build") or "")[:64],
                scorable=bool((rec.get("book") or {}).get("scorable")), payload=rec))
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                async with armer.engine.sf() as again:    # a racing duplicate is the same observation - acknowledged once
                    if await again.get(TechniqueBookSnapshot, rec["captureId"]) is not None:
                        return
                raise

    def on_drop(why: str, rec: dict) -> None:
        log.warning("EM book snapshot dropped (%s) seq=%s reason=%s", why, rec.get("seq"), rec.get("reason"))

    return ProfitCaptureObserver(
        enabled=lambda: bool(armer.engine.settings.get(KNOB, False)),
        collect=lambda: collect_inputs(armer, clock()),
        write=write, finalize=finalize, clock_ms=clock,
        cadence_s=lambda: float(armer.engine.settings.get(CADENCE, 30.0) or 30.0), on_drop=on_drop)
