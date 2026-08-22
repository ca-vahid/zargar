"""Broker abstractions.

Two separate concerns:
  - QuoteFeed: where market data comes from (sim generator or IBKR).
  - Executor: where orders go (local fill simulator or IBKR).

The OrderManager talks only to these interfaces, so live/paper/sim/shadow
portfolios share one code path and differ only in routing.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from ..domain import OrderSide, OrderType, TimeInForce, new_id, now_ms


@dataclass(slots=True)
class BrokerOrder:
    """The order as handed to an executor (already risk-approved)."""
    id: str
    symbol: str
    sec_type: str
    side: OrderSide
    qty: float
    order_type: OrderType
    limit_price: float | None = None
    stop_price: float | None = None
    tif: TimeInForce = TimeInForce.DAY
    outside_rth: bool = False
    oca_group: str | None = None
    parent_id: str | None = None
    portfolio_id: str | None = None  # lets account-scoped venues (SnapTrade) resolve the account
    option_action: str | None = None  # OPT only: BUY_TO_OPEN | BUY_TO_CLOSE | SELL_TO_OPEN | SELL_TO_CLOSE


@dataclass(slots=True)
class ExecReport:
    """Executor → OrderManager callback payload."""
    kind: str            # accepted | fill | cancelled | rejected | expired
    order_id: str
    ts: int = field(default_factory=now_ms)
    fill_qty: float = 0.0
    fill_price: float = 0.0
    commission: float = 0.0
    reason: str = ""
    exec_id: str = field(default_factory=new_id)


ReportCallback = Callable[[ExecReport], Awaitable[None]]


class Executor(abc.ABC):
    """An order execution venue."""

    def __init__(self) -> None:
        self.on_report: ReportCallback | None = None

    async def emit(self, report: ExecReport) -> None:
        if self.on_report is not None:
            await self.on_report(report)

    @abc.abstractmethod
    async def submit(self, order: BrokerOrder) -> None: ...

    @abc.abstractmethod
    async def cancel(self, order_id: str) -> None: ...

    @property
    @abc.abstractmethod
    def connected(self) -> bool: ...


class QuoteFeed(abc.ABC):
    @abc.abstractmethod
    async def start(self) -> None: ...

    @abc.abstractmethod
    async def stop(self) -> None: ...

    @abc.abstractmethod
    async def watch(self, symbol: str) -> None:
        """Ensure quotes stream for a symbol."""

    @property
    @abc.abstractmethod
    def connected(self) -> bool: ...
