"""SQLAlchemy ORM models.

The append-only `events` table is the source of truth / audit trail; most other
tables are projections that could be rebuilt from it. JSON columns use JSONB on
PostgreSQL and plain JSON elsewhere (tests can fall back to SQLite).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    aggregate_type: Mapped[str | None] = mapped_column(String(32))
    aggregate_id: Mapped[str | None] = mapped_column(String(64), index=True)
    portfolio_id: Mapped[str | None] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSONVariant, default=dict)


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16))  # live | paper | sim | shadow
    base_currency: Mapped[str] = mapped_column(String(8), default="USD")
    starting_cash: Mapped[float] = mapped_column(Float, default=0.0)
    cash: Mapped[float] = mapped_column(Float, default=0.0)
    source_name: Mapped[str | None] = mapped_column(String(128))  # for shadow portfolios
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BrokerageAccount(Base):
    """A real brokerage account reached through an aggregator (SnapTrade today).

    Links one external account to exactly one zargar portfolio; the sync
    service auto-provisions both on first sight of an account.
    """
    __tablename__ = "brokerage_accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # SnapTrade account UUID
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), unique=True, index=True)
    venue: Mapped[str] = mapped_column(String(16), default="snaptrade")
    connection_id: Mapped[str | None] = mapped_column(String(64))  # authorization id
    institution: Mapped[str | None] = mapped_column(String(64))    # "Wealthsimple" / "Webull"
    number: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(8), default="CAD")
    account_type: Mapped[str | None] = mapped_column(String(32))   # MARGIN / CASH / ...
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSONVariant, default=dict)  # raw balances etc.


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("symbol", "exchange", "sec_type", name="uq_instrument"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str | None] = mapped_column(String(256))
    exchange: Mapped[str] = mapped_column(String(16), default="SMART")
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    sec_type: Mapped[str] = mapped_column(String(8), default="STK")
    conid: Mapped[int | None] = mapped_column(Integer)  # IBKR contract id when known


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # client order id
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    sec_type: Mapped[str] = mapped_column(String(8), default="STK")
    side: Mapped[str] = mapped_column(String(4))
    qty: Mapped[float] = mapped_column(Float)
    order_type: Mapped[str] = mapped_column(String(8))
    limit_price: Mapped[float | None] = mapped_column(Float)
    stop_price: Mapped[float | None] = mapped_column(Float)
    tif: Mapped[str] = mapped_column(String(4), default="DAY")
    status: Mapped[str] = mapped_column(String(20), default="NEW", index=True)
    filled_qty: Mapped[float] = mapped_column(Float, default=0.0)
    avg_fill_price: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(12), default="manual")
    parent_id: Mapped[str | None] = mapped_column(String(64), index=True)  # bracket parent
    oca_group: Mapped[str | None] = mapped_column(String(64))
    broker_order_id: Mapped[str | None] = mapped_column(String(64))
    signal_id: Mapped[str | None] = mapped_column(String(64))
    proposal_id: Mapped[str | None] = mapped_column(String(64))
    reject_reason: Mapped[str | None] = mapped_column(Text)
    bracket: Mapped[dict | None] = mapped_column(JSONVariant)  # {takeProfit, stopLoss} config
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Execution(Base):
    __tablename__ = "executions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    portfolio_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(4))
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("portfolio_id", "symbol", "sec_type", name="uq_position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    sec_type: Mapped[str] = mapped_column(String(8), default="STK")
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    avg_cost: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class BarRow(Base):
    __tablename__ = "bars"
    __table_args__ = (
        UniqueConstraint("symbol", "tf", "ts", name="uq_bar"),
        Index("ix_bars_lookup", "symbol", "tf", "ts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32))
    tf: Mapped[str] = mapped_column(String(8))
    ts: Mapped[int] = mapped_column(BigInteger)  # bar open, epoch ms
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)


class EquityPoint(Base):
    __tablename__ = "equity_points"
    __table_args__ = (Index("ix_equity_lookup", "portfolio_id", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[str] = mapped_column(String(64))
    ts: Mapped[int] = mapped_column(BigInteger)  # epoch ms
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)


class RawContent(Base):
    __tablename__ = "raw_content"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(16))  # email | api | rss | manual
    source_name: Mapped[str | None] = mapped_column(String(128), index=True)
    sender: Mapped[str | None] = mapped_column(String(256))
    subject: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONVariant, default=dict)  # headers, auth results...
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    status: Mapped[str] = mapped_column(String(16), default="new")  # new | extracted | error | ignored


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    raw_content_id: Mapped[str | None] = mapped_column(ForeignKey("raw_content.id"), index=True)
    source_name: Mapped[str | None] = mapped_column(String(128), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    exchange_hint: Mapped[str | None] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(String(8))   # long | short
    action: Mapped[str] = mapped_column(String(16))     # open | add | trim | close | update_stop
    entry_price: Mapped[float | None] = mapped_column(Float)
    entry_type: Mapped[str] = mapped_column(String(16), default="unspecified")
    target_price: Mapped[float | None] = mapped_column(Float)
    stop_price: Mapped[float | None] = mapped_column(Float)
    timeframe: Mapped[str] = mapped_column(String(16), default="unspecified")
    thesis_summary: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(20), default="commentary_only")
    is_actionable: Mapped[bool] = mapped_column(Boolean, default=False)
    extraction: Mapped[dict] = mapped_column(JSONVariant, default=dict)  # full LLM output + grounding
    verification: Mapped[dict | None] = mapped_column(JSONVariant)      # check results
    status: Mapped[str] = mapped_column(String(20), default="extracted", index=True)
    # extracted | verified | verification_failed | proposed | dismissed
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    signal_id: Mapped[str | None] = mapped_column(ForeignKey("signals.id"), index=True)
    portfolio_id: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(32))
    sec_type: Mapped[str] = mapped_column(String(8), default="STK")
    side: Mapped[str] = mapped_column(String(4))
    qty: Mapped[float] = mapped_column(Float)
    order_type: Mapped[str] = mapped_column(String(8), default="LMT")
    limit_price: Mapped[float | None] = mapped_column(Float)
    bracket: Mapped[dict | None] = mapped_column(JSONVariant)
    rationale: Mapped[str | None] = mapped_column(Text)
    context: Mapped[dict] = mapped_column(JSONVariant, default=dict)  # verification summary, sizing math
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending | approved | rejected | expired | executed | failed
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    decided_via: Mapped[str | None] = mapped_column(String(16))  # app | telegram | auto
    order_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONVariant)  # always {"v": <actual value>}
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    symbols: Mapped[list] = mapped_column(JSONVariant, default=list)  # ordered list of symbols
