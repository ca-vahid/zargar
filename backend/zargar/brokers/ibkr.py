"""IBKR broker adapter: executor (and optional quote feed) over ib_async -> IB Gateway/TWS.

Activated with ZARGAR_BROKER=ibkr. Requires `pip install zargar[ibkr]` and a running IB Gateway (paper: port 4002,
live: 4001) with API access enabled - the user logs into the gateway; the app never sees credentials.

Hardened for real money (2026-10-02, live go-live on IBKR):
- EXECUTOR ONLY by default: `quotes=False` keeps the app's market-data feed (Alpaca/Yahoo) for every desk; IBKR's own
  data (delayed without a subscription) is opt-in.
- Order errors from the gateway (`errorEvent`) reject the order instead of leaving it "accepted" forever.
- Fills carry the real commission: a fill waits briefly for its `commissionReportEvent`, then is emitted once with a
  deterministic exec id (`ibkr:<execId>`) - re-delivered or caught-up executions are never applied twice.
- A dropped gateway connection reconnects with backoff; after every (re)connect the adapter catches up: open orders
  are re-bound by their `orderRef` (our order id) and today's executions are replayed through the same dedupe.
- STK only: an option / multi-leg order is rejected here (there is no IBKR option path).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from ..domain import OrderSide, OrderType, Quote, now_ms
from .base import BrokerOrder, ExecReport, Executor, QuoteFeed

log = logging.getLogger("zargar.ibkr")
# every awaited gateway request is bounded: during IBKR's nightly maintenance a request can never answer (2026-10-05)
REQUEST_TIMEOUT_S = 30.0

# Order errors: ib_async already turns a non-warning order error into status Cancelled (and treats 105/110/321/399/...
# as WARNINGS on a still-live order). So the error event is only RECORDED; the order's own status decides - Cancelled
# with an error in its log (and no cancel requested by us) = rejected, Inactive = rejected.
COMMISSION_WAIT_S = 4.0
RECONNECT_BACKOFF_S = (1, 2, 5, 10, 30)


def _contract_for(symbol: str, sec_type: str):
    from ib_async import Stock
    if symbol.endswith(".TO"):
        return Stock(symbol.removesuffix(".TO"), "SMART", "CAD", primaryExchange="TSE")
    if symbol.endswith(".V"):
        return Stock(symbol.removesuffix(".V"), "SMART", "CAD", primaryExchange="VENTURE")
    return Stock(symbol, "SMART", "USD")


def exec_id_for(ib_exec_id: str) -> str:
    """Deterministic execution id: the same IBKR execution always maps to the same row (dedupe key)."""
    return f"ibkr:{ib_exec_id}"


def error_from_log(trade) -> str | None:
    """The last gateway error recorded on an ib_async trade (TradeLogEntry.errorCode != 0), as text."""
    for entry in reversed(list(getattr(trade, "log", None) or [])):
        code = int(getattr(entry, "errorCode", 0) or 0)
        if code and not (2100 <= code < 2200):
            return f"IBKR {code}: {getattr(entry, 'message', '')}"[:300]
    return None



def to_tick(price: float, direction: str) -> float:
    """US stock minimum tick: $0.01 at/above $1, $0.0001 below. Rounded `up` or `down` to the tick."""
    import decimal
    p = decimal.Decimal(str(price))
    tick = decimal.Decimal("0.01") if p >= 1 else decimal.Decimal("0.0001")
    q = (p / tick).to_integral_value(rounding=decimal.ROUND_CEILING if direction == "up" else decimal.ROUND_FLOOR)
    return float(q * tick)


class IBKRBroker(QuoteFeed, Executor):
    """Executor (and optional feed) for IBKR live/paper portfolios."""

    def __init__(self, host: str, port: int, client_id: int, on_quote, *, quotes: bool = False,
                 exec_seen: Callable[[str], Awaitable[bool]] | None = None,
                 on_state: Callable[[str, dict], Awaitable[None]] | None = None, ib_factory=None) -> None:
        Executor.__init__(self)
        self._host = host
        self._port = port
        self._client_id = client_id
        self._on_quote = on_quote
        self._quotes = bool(quotes)
        self._exec_seen = exec_seen
        self._on_state = on_state
        self._ib_factory = ib_factory
        self._ib = None
        self._tickers: dict[str, object] = {}
        self._trades: dict[str, object] = {}       # our order id -> ib trade
        self._last_error: dict[str, str] = {}      # our order id -> last gateway error text
        self._emitted: set[str] = set()            # exec ids emitted by this process
        self._pending: dict[str, tuple] = {}       # ib execId -> (trade, fill) waiting for its commission
        self._stopping = False
        self._reconnect_task: asyncio.Task | None = None
        self._cancel_requested: set[str] = set()   # our order ids we asked IBKR to cancel
        # V1.2 (2026-10-05): False from a (re)connect until the execution catch-up has run - an account sync before
        # it would level-set to IBKR's numbers and the replayed fills would then count a second time
        self.caught_up = False

    # ------------------------------------------------------------- connection
    def account_kind(self) -> str | None:
        """'paper' when every managed account is an IBKR paper account (DU...), 'live' when none is, None unknown
        (review B2, 2026-10-04: which money trades must never depend on the gateway port alone)."""
        try:
            accts = [str(a) for a in (self._ib.managedAccounts() or [])] if self._ib is not None else []
        except Exception:                                  # noqa: BLE001
            return None
        if not accts:
            return None
        if all(a.upper().startswith("DU") for a in accts):
            return "paper"
        if not any(a.upper().startswith("DU") for a in accts):
            return "live"
        return None

    @property
    def connected(self) -> bool:
        # 2026-10-05: the API socket to the gateway can stay up while the GATEWAY has lost IBKR's servers (notice 1100,
        # 00:17 ET to 10:18 ET+ that morning): orders sat "submitted" and the account sync re-read cached numbers.
        # A lost server link is NOT connected - new orders are refused visibly until IBKR restores it (1101/1102).
        return bool(self._ib and self._ib.isConnected()) and not getattr(self, "_link_down", False)

    def _new_ib(self):
        if self._ib_factory is not None:
            return self._ib_factory()
        from ib_async import IB
        return IB()

    async def start(self) -> None:
        """Connect once; on failure the adapter keeps retrying in the background (the app boots without a gateway
        and starts routing the moment one is logged in)."""
        self._stopping = False
        try:
            await self._connect()
        except Exception as exc:  # noqa: BLE001 - the gateway may simply not be running yet
            log.warning("IBKR connect failed (%s) - retrying in the background", exc)
            self._schedule_reconnect()

    async def _connect(self) -> None:
        self.caught_up = False
        ib = self._new_ib()
        await ib.connectAsync(self._host, self._port, clientId=self._client_id, timeout=10)
        self._ib = ib
        if self._quotes:
            ib.reqMarketDataType(3)   # delayed data fallback for unsubscribed instruments
            ib.pendingTickersEvent += self._on_pending_tickers
        ib.orderStatusEvent += self._on_order_status
        ib.execDetailsEvent += self._on_exec_details
        ib.commissionReportEvent += self._on_commission
        ib.errorEvent += self._on_error
        ib.disconnectedEvent += self._on_disconnected
        log.info("connected to IBKR at %s:%s (client %s, quotes %s)", self._host, self._port, self._client_id,
                 "on" if self._quotes else "off")
        await self._notify("connected", {"host": self._host, "port": self._port,
                                         "accounts": list(getattr(ib, "managedAccounts", lambda: [])() or [])})
        # V1.2 (2026-10-05, review R1 M1): replay the executions FIRST, then let the account sync level-set - a fill
        # made during the outage is applied once (catch-up), never on top of a sync that already contains it
        out = await self.catch_up()
        self.caught_up = True
        await self._notify("ready", {"replayed": int((out or {}).get("replayed") or 0)})

    def _on_disconnected(self) -> None:
        self.caught_up = False
        if self._stopping:
            return
        log.warning("IBKR gateway disconnected - reconnecting")
        asyncio.ensure_future(self._notify("disconnected", {}))
        self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.ensure_future(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        i = 0
        while not self._stopping and not self.connected:
            await asyncio.sleep(RECONNECT_BACKOFF_S[min(i, len(RECONNECT_BACKOFF_S) - 1)])
            i += 1
            try:
                await self._connect()
            except Exception as exc:  # noqa: BLE001
                if i in (1, 5) or i % 20 == 0:
                    log.warning("IBKR reconnect attempt %d failed: %s", i, exc)

    async def stop(self) -> None:
        self._stopping = True
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()

    async def _notify(self, kind: str, data: dict) -> None:
        if self._on_state is not None:
            try:
                await self._on_state(kind, data)
            except Exception:  # pragma: no cover - journaling is best-effort
                log.debug("ibkr state callback failed", exc_info=True)

    # ------------------------------------------------------------- catch-up
    async def catch_up(self) -> dict:
        """Re-bind open orders by orderRef and replay today's executions (deduped)."""
        out = {"openOrders": 0, "replayed": 0}
        if not self.connected:
            return out
        try:
            for t in list(self._ib.openTrades() or []):
                oid = self._order_id_for(t.order)
                if oid:
                    self._trades[oid] = t
                    out["openOrders"] += 1
            # bounded (2026-10-05): during IBKR's nightly maintenance a request can simply never answer
            fills = await asyncio.wait_for(self._ib.reqExecutionsAsync(), timeout=REQUEST_TIMEOUT_S)
            for f in fills or []:
                ref = getattr(getattr(f, "execution", None), "orderRef", None) or None
                if not ref:
                    continue
                if await self._emit_fill(ref, f, from_catch_up=True):
                    out["replayed"] += 1
        except Exception:  # noqa: BLE001
            log.exception("IBKR catch-up failed")
        if out["replayed"]:
            await self._notify("caught_up", out)
        return out

    # ------------------------------------------------------------- quotes (opt-in)
    async def watch(self, symbol: str) -> None:
        symbol = symbol.upper()
        if not self._quotes or symbol in self._tickers or not self.connected:
            return
        contract = _contract_for(symbol, "STK")
        qualified = await self._ib.qualifyContractsAsync(contract)
        if not qualified or qualified[0] is None:       # ib_async >= 2.0: failures come back None in-slot
            log.warning("could not qualify contract for %s — no quotes", symbol)
            return
        ticker = self._ib.reqMktData(qualified[0], "", False, False)
        ticker.zargar_symbol = symbol
        self._tickers[symbol] = ticker

    def _on_pending_tickers(self, tickers) -> None:
        for t in tickers:
            symbol = getattr(t, "zargar_symbol", None)
            if not symbol:
                continue

            def _num(v):
                return float(v) if v is not None and v == v else 0.0

            self._on_quote(Quote(
                symbol=symbol, bid=_num(t.bid), ask=_num(t.ask), last=_num(t.last) or _num(t.close),
                bid_size=int(_num(t.bidSize)), ask_size=int(_num(t.askSize)), volume=int(_num(t.volume)),
                halted=bool(getattr(t, "halted", 0) or 0), ts=now_ms()))

    # ------------------------------------------------------------- executor
    async def submit(self, order: BrokerOrder) -> None:
        if str(order.sec_type).upper() != "STK":
            await self.emit(ExecReport(kind="rejected", order_id=order.id,
                                       reason=f"IBKR adapter trades shares only - {order.sec_type} refused"))
            return
        if not self.connected:
            await self.emit(ExecReport(kind="rejected", order_id=order.id, reason="IBKR gateway not connected"))
            return
        from ib_async import LimitOrder, MarketOrder, Order as IbOrder, StopOrder

        contract = _contract_for(order.symbol, order.sec_type)
        qualified = await self._ib.qualifyContractsAsync(contract)
        if not qualified or qualified[0] is None:
            await self.emit(ExecReport(kind="rejected", order_id=order.id,
                                       reason=f"IBKR could not resolve contract for {order.symbol}"))
            return
        contract = qualified[0]
        action = "BUY" if order.side == OrderSide.BUY else "SELL"
        # 2026-10-05: IBKR rejects prices off the minimum tick (error 110 on a 320.435 bracket stop). Limits round in
        # our favour (buy down, sell up); stops round toward the market (sell stop up, buy stop down) - never looser.
        if order.limit_price is not None:
            order.limit_price = to_tick(order.limit_price, "down" if action == "BUY" else "up")
        if order.stop_price is not None:
            order.stop_price = to_tick(order.stop_price, "up" if action == "SELL" else "down")
        if order.order_type == OrderType.MKT:
            ib_order = MarketOrder(action, order.qty)
        elif order.order_type == OrderType.LMT:
            ib_order = LimitOrder(action, order.qty, order.limit_price)
        elif order.order_type == OrderType.STP:
            ib_order = StopOrder(action, order.qty, order.stop_price)
        else:  # STP_LMT
            ib_order = IbOrder(orderType="STP LMT", action=action, totalQuantity=order.qty,
                               lmtPrice=order.limit_price, auxPrice=order.stop_price)
        ib_order.tif = order.tif.value
        ib_order.outsideRth = bool(getattr(order, "outside_rth", False))   # default: the regular session only
        ib_order.orderRef = order.id                   # ties fills back to our client order id (and survives restarts)
        if order.oca_group:
            ib_order.ocaGroup = order.oca_group
            ib_order.ocaType = 1
        trade = self._ib.placeOrder(contract, ib_order)
        self._trades[order.id] = trade
        await self.emit(ExecReport(kind="accepted", order_id=order.id))

    async def cancel(self, order_id: str):
        trade = self._trades.get(order_id)
        if trade is None and self.connected:
            for t in list(self._ib.openTrades() or []):         # after a restart: find it by our orderRef
                if self._order_id_for(t.order) == order_id:
                    trade = t
                    self._trades[order_id] = t
                    break
        if trade is None:
            return False
        self._cancel_requested.add(order_id)
        self._ib.cancelOrder(trade.order)
        return True

    def _order_id_for(self, ib_order) -> str | None:
        return getattr(ib_order, "orderRef", None) or None

    def _oid_for_req(self, req_id: int) -> str | None:
        for oid, t in self._trades.items():
            if getattr(getattr(t, "order", None), "orderId", None) == req_id:
                return oid
        return None

    def _on_error(self, req_id, error_code, error_string, contract=None) -> None:
        oid = self._oid_for_req(req_id) if req_id is not None and int(req_id) > 0 else None
        if oid is None:
            code = int(error_code)
            if code in (1100, 2110):                 # the gateway lost IBKR's servers (2110: TWS <-> server broken)
                if not getattr(self, "_link_down", False):
                    self._link_down = True
                    log.warning("IBKR server link LOST (%s): %s - new orders refused until restored", code, error_string)
                    asyncio.ensure_future(self._notify("link_lost", {"code": code, "message": str(error_string)[:200]}))
                return
            if code in (1101, 1102):                 # restored (1101: data lost - resubscribe; 1102: data kept)
                if getattr(self, "_link_down", False):
                    self._link_down = False
                    log.warning("IBKR server link RESTORED (%s): %s", code, error_string)
                    asyncio.ensure_future(self._notify("link_restored", {"code": code, "message": str(error_string)[:200]}))
                return
            if code < 2100 or code > 2199:      # 21xx are connectivity/info notices
                log.info("IBKR notice %s: %s", error_code, error_string)
            return
        self._last_error[oid] = f"IBKR {error_code}: {error_string}"[:300]
        log.warning("IBKR message on order %s: %s %s", oid[:8], error_code, error_string)

    def _on_order_status(self, trade) -> None:
        oid = self._order_id_for(trade.order)
        if not oid:
            return
        self._trades.setdefault(oid, trade)
        status = trade.orderStatus.status
        err = error_from_log(trade) or self._last_error.get(oid)
        if status in ("Cancelled", "ApiCancelled"):
            if oid in self._cancel_requested or not err:
                asyncio.ensure_future(self.emit(ExecReport(kind="cancelled", order_id=oid, reason=err or status)))
            else:                                   # the venue killed an order we did not cancel: a rejection
                asyncio.ensure_future(self.emit(ExecReport(kind="rejected", order_id=oid, reason=err)))
        elif status == "Inactive":
            asyncio.ensure_future(self.emit(ExecReport(kind="rejected", order_id=oid, reason=err or "inactive")))

    # ------------------------------------------------------------- fills
    def _on_exec_details(self, trade, fill) -> None:
        oid = self._order_id_for(trade.order)
        if not oid:
            return
        ib_id = fill.execution.execId
        if self._commission_of(fill) is not None:
            asyncio.ensure_future(self._emit_fill(oid, fill))
            return
        self._pending[ib_id] = (oid, fill)
        asyncio.ensure_future(self._flush_after(ib_id))

    def _on_commission(self, trade, fill, report) -> None:
        ib_id = fill.execution.execId
        item = self._pending.pop(ib_id, None)
        oid = (item[0] if item else None) or self._order_id_for(trade.order)
        if oid:
            asyncio.ensure_future(self._emit_fill(oid, fill))

    async def _flush_after(self, ib_id: str) -> None:
        await asyncio.sleep(COMMISSION_WAIT_S)
        item = self._pending.pop(ib_id, None)
        if item is not None:                       # no commission report in time: emit, commission marked unknown
            await self._emit_fill(item[0], item[1], commission_unknown=True)

    @staticmethod
    def _commission_of(fill) -> float | None:
        rep = getattr(fill, "commissionReport", None)
        c = getattr(rep, "commission", None) if rep is not None else None
        if c is None or c != c or (getattr(rep, "execId", "") or "") == "":
            return None
        return float(c)

    async def _emit_fill(self, oid: str, fill, *, from_catch_up: bool = False, commission_unknown: bool = False) -> bool:
        ib_id = fill.execution.execId
        xid = exec_id_for(ib_id)
        if xid in self._emitted:
            return False
        if self.on_report is None:                 # nobody to apply it yet (boot order): leave it for the next catch-up
            return False
        if self._exec_seen is not None:
            try:
                if await self._exec_seen(xid):
                    self._emitted.add(xid)
                    return False
            except Exception:  # noqa: BLE001 - a failed lookup must not double-apply: skip, the next catch-up retries
                log.warning("IBKR exec dedupe lookup failed for %s - not applied now", xid)
                return False
        self._emitted.add(xid)
        commission = self._commission_of(fill)
        await self.emit(ExecReport(
            kind="fill", order_id=oid, exec_id=xid,
            fill_qty=float(fill.execution.shares), fill_price=float(fill.execution.price),
            commission=float(commission or 0.0),
            evidence={"venue": "ibkr", "ibExecId": ib_id, "account": getattr(fill.execution, "acctNumber", None),
                      **({"commission": "unknown"} if commission is None or commission_unknown else {}),
                      **({"replayed": True} if from_catch_up else {})}))
        return True

    # ------------------------------------------------------------- account
    async def account_state(self, *, cash_currency: str = "USD") -> dict | None:
        """{cash, cashByCurrency, positions:[{symbol, secType, qty, avgCost, currency}], account} or None."""
        if not self.connected:
            return None
        try:
            rows = await asyncio.wait_for(self._ib.accountSummaryAsync(), timeout=REQUEST_TIMEOUT_S)
        except asyncio.TimeoutError:
            log.warning("IBKR account summary did not answer within %ss - sync skipped this pass", REQUEST_TIMEOUT_S)
            return None
        by_cur: dict[str, float] = {}
        settled = None
        account = None
        for r in rows or []:
            account = account or getattr(r, "account", None)
            # per-currency cash: "CashBalance", or "$LEDGER-CashBalance" when the gateway's "Use $LEDGER- prefix for
            # per-currency keys" is on (IB Gateway default; seen on the paper account 2026-10-02)
            if r.tag in ("CashBalance", "$LEDGER-CashBalance") and r.currency and r.currency != "BASE":
                try:
                    by_cur[r.currency] = by_cur.get(r.currency, 0.0) + float(r.value)
                except (TypeError, ValueError):
                    pass
            if r.tag in ("SettledCash", "$LEDGER-SettledCash") and r.currency == cash_currency:
                try:
                    settled = float(r.value)
                except (TypeError, ValueError):
                    pass
        positions = []
        for p in self._ib.positions() or []:
            c = p.contract
            if getattr(c, "secType", "") != "STK":
                continue
            sym = c.symbol + (".TO" if getattr(c, "primaryExchange", "") == "TSE" else "")
            positions.append({"symbol": sym, "secType": "STK", "qty": float(p.position),
                              "avgCost": float(p.avgCost), "currency": getattr(c, "currency", None)})
        cash = by_cur.get(cash_currency, 0.0)
        return {"account": account, "cash": cash, "settledCash": settled, "cashByCurrency": by_cur,
                "positions": positions}
