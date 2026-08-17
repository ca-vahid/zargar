"""IBKR broker adapter: quote feed + executor over ib_async → IB Gateway/TWS.

Not used in development (the sim provides both roles); activated with
ZARGAR_BROKER=ibkr. Requires `pip install zargar[ibkr]` and a running
IB Gateway (paper: port 4002, live: 4001) with API access enabled.
"""
from __future__ import annotations

import asyncio
import logging

from ..domain import OrderSide, OrderType, Quote, now_ms
from .base import BrokerOrder, ExecReport, Executor, QuoteFeed

log = logging.getLogger("zargar.ibkr")


def _contract_for(symbol: str, sec_type: str):
    from ib_async import Stock
    if symbol.endswith(".TO"):
        return Stock(symbol.removesuffix(".TO"), "SMART", "CAD", primaryExchange="TSE")
    if symbol.endswith(".V"):
        return Stock(symbol.removesuffix(".V"), "SMART", "CAD", primaryExchange="VENTURE")
    return Stock(symbol, "SMART", "USD")


class IBKRBroker(QuoteFeed, Executor):
    """Single object serving as both feed and executor for paper/live portfolios."""

    def __init__(self, host: str, port: int, client_id: int, on_quote) -> None:
        Executor.__init__(self)
        self._host = host
        self._port = port
        self._client_id = client_id
        self._on_quote = on_quote
        self._ib = None
        self._tickers: dict[str, object] = {}
        self._trades: dict[str, object] = {}  # client order id -> ib trade

    @property
    def connected(self) -> bool:
        return bool(self._ib and self._ib.isConnected())

    async def start(self) -> None:
        from ib_async import IB
        self._ib = IB()
        await self._ib.connectAsync(self._host, self._port, clientId=self._client_id, timeout=10)
        # delayed data fallback for unsubscribed instruments
        self._ib.reqMarketDataType(3)
        self._ib.pendingTickersEvent += self._on_pending_tickers
        self._ib.orderStatusEvent += self._on_order_status
        self._ib.execDetailsEvent += self._on_exec_details
        log.info("connected to IBKR at %s:%s", self._host, self._port)

    async def stop(self) -> None:
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()

    async def watch(self, symbol: str) -> None:
        symbol = symbol.upper()
        if symbol in self._tickers or not self.connected:
            return
        contract = _contract_for(symbol, "STK")
        # ib_async >= 2.0: failed qualifications come back as None in-slot
        qualified = await self._ib.qualifyContractsAsync(contract)
        if not qualified or qualified[0] is None:
            log.warning("could not qualify contract for %s — no quotes", symbol)
            return
        contract = qualified[0]
        ticker = self._ib.reqMktData(contract, "", False, False)
        ticker.zargar_symbol = symbol  # tag for the tick handler
        self._tickers[symbol] = ticker

    def _on_pending_tickers(self, tickers) -> None:
        for t in tickers:
            symbol = getattr(t, "zargar_symbol", None)
            if not symbol:
                continue

            def _num(v):
                return float(v) if v is not None and v == v else 0.0

            self._on_quote(Quote(
                symbol=symbol,
                bid=_num(t.bid), ask=_num(t.ask), last=_num(t.last) or _num(t.close),
                bid_size=int(_num(t.bidSize)), ask_size=int(_num(t.askSize)),
                volume=int(_num(t.volume)),
                halted=bool(getattr(t, "halted", 0) or 0),
                ts=now_ms(),
            ))

    # ------------------------------------------------------------- executor
    async def submit(self, order: BrokerOrder) -> None:
        from ib_async import LimitOrder, MarketOrder, Order as IbOrder, StopOrder

        contract = _contract_for(order.symbol, order.sec_type)
        qualified = await self._ib.qualifyContractsAsync(contract)
        if not qualified or qualified[0] is None:
            await self.emit(ExecReport(
                kind="rejected", order_id=order.id,
                reason=f"IBKR could not resolve contract for {order.symbol}"))
            return
        contract = qualified[0]
        action = "BUY" if order.side == OrderSide.BUY else "SELL"
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
        ib_order.orderRef = order.id  # ties fills back to our client order id
        if order.oca_group:
            ib_order.ocaGroup = order.oca_group
            ib_order.ocaType = 1
        trade = self._ib.placeOrder(contract, ib_order)
        self._trades[order.id] = trade
        await self.emit(ExecReport(kind="accepted", order_id=order.id))

    async def cancel(self, order_id: str) -> None:
        trade = self._trades.get(order_id)
        if trade is not None:
            self._ib.cancelOrder(trade.order)

    def _order_id_for(self, ib_order) -> str | None:
        return getattr(ib_order, "orderRef", None) or None

    def _on_order_status(self, trade) -> None:
        oid = self._order_id_for(trade.order)
        if not oid:
            return
        status = trade.orderStatus.status
        if status in ("Cancelled", "ApiCancelled"):
            asyncio.ensure_future(self.emit(
                ExecReport(kind="cancelled", order_id=oid, reason=status)))
        elif status == "Inactive":
            asyncio.ensure_future(self.emit(
                ExecReport(kind="rejected", order_id=oid, reason="inactive")))

    def _on_exec_details(self, trade, fill) -> None:
        oid = self._order_id_for(trade.order)
        if not oid:
            return
        commission = 0.0
        if fill.commissionReport and fill.commissionReport.commission == fill.commissionReport.commission:
            commission = float(fill.commissionReport.commission)
        asyncio.ensure_future(self.emit(ExecReport(
            kind="fill", order_id=oid,
            fill_qty=float(fill.execution.shares),
            fill_price=float(fill.execution.price),
            commission=commission,
        )))
