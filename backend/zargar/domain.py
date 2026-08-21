"""Shared domain enums and value objects."""
from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field


def new_id() -> str:
    return uuid.uuid4().hex


def now_ms() -> int:
    return int(time.time() * 1000)


class SecType(str, enum.Enum):
    STK = "STK"
    OPT = "OPT"
    ETF = "ETF"
    CASH = "CASH"


class OrderSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, enum.Enum):
    MKT = "MKT"
    LMT = "LMT"
    STP = "STP"
    STP_LMT = "STP_LMT"


class TimeInForce(str, enum.Enum):
    DAY = "DAY"
    GTC = "GTC"
    IOC = "IOC"


class OrderStatus(str, enum.Enum):
    NEW = "NEW"                    # intent created, not yet risk-checked
    REJECTED_RISK = "REJECTED_RISK"
    DRY_RUN = "DRY_RUN"            # accepted but routing disabled (dry-run mode)
    SUBMITTED = "SUBMITTED"        # sent to broker/sim
    ACCEPTED = "ACCEPTED"          # broker acknowledged / working
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"          # broker rejected
    EXPIRED = "EXPIRED"

    @property
    def is_terminal(self) -> bool:
        return self in (
            OrderStatus.REJECTED_RISK,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
            OrderStatus.DRY_RUN,
        )


class PortfolioKind(str, enum.Enum):
    LIVE = "live"      # real money via IBKR
    PAPER = "paper"    # IBKR paper account
    SIM = "sim"        # local fill simulator against (real or simulated) quotes
    SHADOW = "shadow"  # signal-only what-would-have-happened portfolio


class OrderSource(str, enum.Enum):
    MANUAL = "manual"
    SIGNAL = "signal"    # human-approved proposal
    AUTO = "auto"        # rules-gated auto-execution
    BRACKET = "bracket"  # child order created by the engine


@dataclass(slots=True)
class Quote:
    symbol: str
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    bid_size: int = 0
    ask_size: int = 0
    volume: int = 0
    halted: bool = False
    ts: int = field(default_factory=now_ms)
    # session context from real feeds (0 / "" when the feed doesn't know):
    prev_close: float = 0.0   # prior session close — THE day-change basis
    reg_price: float = 0.0    # regular-session price (differs from last pre/post)
    day_high: float = 0.0
    day_low: float = 0.0
    session: str = ""         # "pre" | "regular" | "post" | "closed"

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2
        return self.last

    @property
    def spread_pct(self) -> float:
        m = self.mid
        if m <= 0 or self.bid <= 0 or self.ask <= 0:
            return 999.0
        return (self.ask - self.bid) / m * 100.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "bid": round(self.bid, 4),
            "ask": round(self.ask, 4),
            "last": round(self.last, 4),
            "bidSize": self.bid_size,
            "askSize": self.ask_size,
            "volume": self.volume,
            "halted": self.halted,
            "ts": self.ts,
            "prevClose": round(self.prev_close, 4),
            "regPrice": round(self.reg_price, 4),
            "dayHigh": round(self.day_high, 4),
            "dayLow": round(self.day_low, 4),
            "session": self.session,
        }


@dataclass(slots=True)
class Bar:
    symbol: str
    tf: str          # "1m", "5m", ...
    ts: int          # bar open time, epoch ms
    open: float
    high: float
    low: float
    close: float
    volume: int = 0

    def to_row(self) -> list:
        return [self.ts, self.open, self.high, self.low, self.close, self.volume]
