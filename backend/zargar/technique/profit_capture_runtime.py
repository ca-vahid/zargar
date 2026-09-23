"""ED-04 runtime glue (EM-only; `book-snapshot-v2`, IR-02 / IR-03): builds the `ProfitCaptureObserver` for the EM armer.

SYNCHRONOUS half (`collect_inputs`, called from the runner): in-memory state only - this session's held positions, the
quote cache's evidence (nothing relabelled), the keeper's cash. No database, no network, no model.

ASYNCHRONOUS half (the recorder's own task, never a trading path): `SessionLedger.as_of` reads the book's EXECUTIONS of
the session and builds the realized ledger as of each record's capture time - so realized totals and per-trade
attribution survive a restart, a disarm and a late recorder start, and prior-session fills are excluded by the window.
The write is idempotent by the record's `captureId`."""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .profit_capture import ProfitCaptureObserver, build_ledger, finalize_book, resolve_links
from .research_recorder import feed_identity, quote_evidence

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
KNOB = "techniques.enhanced_market.book_snapshot_observe"
CADENCE = "techniques.enhanced_market.book_snapshot_seconds"


def session_of(now_ms: int) -> str:
    return dt.datetime.fromtimestamp(now_ms / 1000.0, ET).date().isoformat()


def session_supported(session: str) -> bool:
    """The exchange calendar decides (holidays, weekends): a day that is not a trading session is HELD, never scored."""
    from ..marketstructure.market_calendar import is_trading_day
    try:
        return bool(is_trading_day(session))
    except Exception:                                     # noqa: BLE001
        return False


def session_window(session: str) -> tuple[int, int]:
    """[04:00, 20:00) ET of the session day (zone-aware, so DST is exact): every fill of THIS session, none of a prior
    one. A shortened session closes early INSIDE this window, so its fills are all included."""
    d = dt.date.fromisoformat(session)
    a = dt.datetime(d.year, d.month, d.day, 4, 0, tzinfo=ET)
    return int(a.timestamp() * 1000), int((a + dt.timedelta(hours=16)).timestamp() * 1000)


def book_id(settings) -> str:
    return str(settings.get("techniques.enhanced_market.default_portfolio", "") or settings.get("technique.arm.default_portfolio", "") or "")


def collect_inputs(armer, now_ms: int, pid: str | None = None) -> dict | None:
    """Positions HELD NOW in the EM Practice book by plans of THIS session (a plan of a prior session still in memory is
    not this session's trade; were it still held it would surface as a ledger/position mismatch - unscorable, visibly).
    Realized results are NOT collected here: they come from executions (`SessionLedger`)."""
    s = armer.engine.settings
    pid = str(pid or book_id(s))
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


LEDGER_SQL = """select e.id, e.order_id, e.symbol, e.side, e.qty, e.price, e.commission, e.ts, o.sec_type,
                       (select min(j.ts) from events j where j.type = 'OrderFill' and j.aggregate_id = e.order_id
                                                         and j.payload->>'executionId' = e.id) as observed_at
                from executions e join orders o on o.id = e.order_id
                where e.portfolio_id = :p and e.ts >= :a and e.ts < :b order by e.ts, e.id"""
LINKS_SQL = """select id, payload from events where type = 'TechniquePlanOrderResult' and portfolio_id = :p and ts >= :a and ts < :c order by id"""


class SessionLedger:
    """The session's executions of ONE book, read on the recorder's task. BOUNDED EXPLICIT RECONCILIATION (R2-01): every
    call re-reads the WHOLE session window of this one book (tens of rows) with the orders' security types, the journal's
    ingestion time of each fill and the plan runner's order links. There is no execution-time cursor, so a fill that
    arrives late with an OLDER occurrence time can never be skipped. The ledger for a record is rebuilt (pure) as of that
    record's capture time; `readAt` says when it was read. A failed read = `status: error` = unscorable - never a guess."""

    def __init__(self, sf, clock=None):
        self._sf = sf
        self._clock = clock or (lambda: int(time.time() * 1000))
        self.restored = False
        self.reads = 0

    async def read(self, pid: str, session: str) -> tuple[list, dict]:
        lo, hi = session_window(session)
        a, b = (dt.datetime.fromtimestamp(x / 1000.0, dt.timezone.utc) for x in (lo, hi))
        async with self._sf() as s:
            got = (await s.execute(text(LEDGER_SQL), {"p": pid, "a": a, "b": b})).mappings().all()
            evs = (await s.execute(text(LINKS_SQL), {"p": pid, "a": a - dt.timedelta(hours=1), "c": b + dt.timedelta(hours=1)})).mappings().all()
        rows = [{"id": r["id"], "orderId": r["order_id"], "symbol": r["symbol"], "secType": r["sec_type"], "side": r["side"], "qty": float(r["qty"]),
                 "price": float(r["price"]), "commission": float(r["commission"] or 0.0), "tsMs": int(r["ts"].timestamp() * 1000),
                 "observedAtMs": (int(r["observed_at"].timestamp() * 1000) if r["observed_at"] is not None else None)} for r in got]
        order_events = []
        for e in evs:
            p = e["payload"] if isinstance(e["payload"], dict) else json.loads(e["payload"] or "{}")
            order_events.append({"seq": int(e["id"]), "runId": p.get("runId"), "trigger": p.get("trigger"), "stage": p.get("stage"),
                                 "orderId": p.get("orderId"), "entryOrderId": p.get("entryOrderId")})
        self.reads += 1
        return rows, resolve_links(order_events)

    async def as_of(self, pid: str, session: str, as_of_ms: int) -> dict:
        rows, links = await self.read(pid, session)
        self.restored = True
        return build_ledger(rows, window=session_window(session), as_of_ms=as_of_ms, links=links,
                            session_supported=session_supported(session), read_at_ms=self._clock())


class BookObservers:
    """One `ProfitCaptureObserver` per EM book that may be captured: the technique's default (baseline) book under the
    technique-wide knob, and the experimental book under ITS override. Books never share a recorder, a sequence, a ledger
    or a capture id. `snap` stays synchronous and cheap; an event snapshot goes only to the book of the plan that caused it."""

    def __init__(self, armer):
        self._armer = armer
        self._obs: dict = {}

    def books(self) -> list:
        from .em_experiment import config
        s = self._armer.engine.settings
        out = [book_id(s)]
        c = config(s.get)
        if c["enabled"]:
            out.append(c["portfolioId"])
        return [p for i, p in enumerate(out) if p and p not in out[:i]]

    def observer(self, pid: str) -> ProfitCaptureObserver:
        if pid not in self._obs:
            self._obs[pid] = build_observer(self._armer, pid)
        return self._obs[pid]

    def snap(self, reason: str, causal: dict | None = None):
        only = None
        rid = (causal or {}).get("runId")
        if rid:
            ap = getattr(self._armer, "_armed", {}).get(rid)
            only = str(ap.config.portfolio_id) if ap is not None else None
        last = None
        for pid in self.books():
            if only and pid != only:
                continue
            last = self.observer(pid).snap(reason, causal) or last
        return last

    @property
    def stats(self) -> dict:
        keys = ("captured", "written", "droppedQueueFull", "droppedWriteFailed", "captureErrors", "retries", "finalizeErrors")
        out = {k: sum(int(o.stats.get(k, 0)) for o in self._obs.values()) for k in keys}
        out["byBook"] = {pid: dict(o.stats) for pid, o in self._obs.items()}
        return out

    async def wait_idle(self) -> None:
        for o in list(self._obs.values()):
            await o.wait_idle()


def build_book_observers(armer) -> BookObservers:
    return BookObservers(armer)


def build_observer(armer, pid: str | None = None) -> ProfitCaptureObserver:
    from .em_experiment import book_policy
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
        enabled=lambda: bool(book_policy(armer.engine.settings.get, (pid or book_id(armer.engine.settings)), "book_snapshot_observe", False)),
        collect=lambda: collect_inputs(armer, clock(), pid),
        write=write, finalize=finalize, clock_ms=clock,
        cadence_s=lambda: float(armer.engine.settings.get(CADENCE, 30.0) or 30.0), on_drop=on_drop)
