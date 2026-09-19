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
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .runtime import runtime_id as _runtime_id

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
    # shadow portfolios keep TWO books per source (user decision 2026-08-27):
    # "immediate" = buy the moment the tip verifies (the source's raw quality);
    # "armed" = what the app actually does (wait for the level, managed exits).
    # NULL = immediate (rows from before the split) or not a shadow portfolio.
    book: Mapped[str | None] = mapped_column(String(12))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # 2026-09-07 (user): a retired book. Kept with its positions, orders and history for the
    # audit trail, but out of every list and total - the Practice reset gave each technique
    # its own book and the old shared one must not count toward the $40k.
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # EOD-09 (2026-09-14): a research book whose results are CORRUPTED (the APLD
    # same-symbol-leg runaway left `ab` 40,600 shares short) is quarantined: its
    # executions stay as evidence, but lane comparisons and source confidence
    # never read it until a person reconciles and clears the flag.
    quarantined: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    quarantine_note: Mapped[str | None] = mapped_column(String(400))
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
    technique: Mapped[str | None] = mapped_column(String(32), index=True)   # registry id when source=technique
    tags: Mapped[list] = mapped_column(JSONVariant, default=list, server_default='[]')           # e.g. ["source:discord-x"] (EM team B2/B3)
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


class CartelDecisionContext(Base):
    """Content-addressed, append-only Cartel decision inputs; never a live tape."""
    __tablename__ = "cartel_decision_contexts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONVariant)


class CartelDecisionBundle(Base):
    """One immutable observation occurrence, not an overwriteable bucket projection."""
    __tablename__ = "cartel_decision_bundles"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    portfolio_id: Mapped[str] = mapped_column(String(64), index=True)
    bucket_end: Mapped[int] = mapped_column(BigInteger, index=True)
    observed_at: Mapped[int] = mapped_column(BigInteger)
    context_id: Mapped[str] = mapped_column(ForeignKey("cartel_decision_contexts.id"))
    payload: Mapped[dict] = mapped_column(JSONVariant)


class CartelPreparationAttempt(Base):
    """Append-only candidate recovery/selection evidence, independent of UI projections."""
    __tablename__ = "cartel_preparation_attempts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    preparation_id: Mapped[str] = mapped_column(String(64), index=True)
    plan_id: Mapped[str | None] = mapped_column(String(64), index=True)
    portfolio_id: Mapped[str] = mapped_column(String(64), index=True)
    at: Mapped[int] = mapped_column(BigInteger, index=True)
    evidence: Mapped[dict] = mapped_column(JSONVariant)


class ExecutionEvidence(Base):
    """Exact executor observation committed with its fill; legacy fills remain unknown."""
    __tablename__ = "execution_evidence"
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id"), primary_key=True)
    evidence: Mapped[dict] = mapped_column(JSONVariant)


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
    # F75 (2026-09-09): where the row came from — exchange | sampled | sim | unknown (legacy rows)
    source: Mapped[str] = mapped_column(String(12), default="unknown")
    provider: Mapped[str] = mapped_column(String(16), default="")


class Team2TapeSnapshot(Base):
    """Content-addressed immutable warm-up/archive inputs; no trading outcomes."""
    __tablename__ = "team2_tape_snapshots"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONVariant, default=dict)


class BarQuarantineRow(Base):
    """Rows removed from `bars` by `zargar.tools.bars_repair quarantine` — preserved verbatim with the
    original id, the reason and a batch id. Never deleted from (F75: preserve before modifying)."""
    __tablename__ = "bars_quarantine"
    __table_args__ = (Index("ix_bars_quarantine_lookup", "symbol", "tf", "ts"), Index("ix_bars_quarantine_batch", "batch"))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    orig_id: Mapped[int] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(32))
    tf: Mapped[str] = mapped_column(String(8))
    ts: Mapped[int] = mapped_column(BigInteger)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)
    source: Mapped[str] = mapped_column(String(12), default="unknown")
    provider: Mapped[str] = mapped_column(String(16), default="")
    reason: Mapped[str] = mapped_column(String(40))
    batch: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(String(200), default="")
    quarantined_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BarsDatasetVersion(Base):
    """A content hash of a slice of `bars` (+ the data-processing rules) — the identity a sweep or a
    plan cites so a rerun can say whether it ran on the same data (F75: row counts are not a version)."""
    __tablename__ = "bars_dataset_versions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)          # sha256 hex
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    scope: Mapped[dict] = mapped_column(JSONVariant, default=dict)          # symbols, tf, start, end, rules
    rows: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(String(200), default="")


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
    # --- extraction v2 (tip technique): the whole trade, not just the stock ---
    instrument: Mapped[str] = mapped_column(String(12), default="unspecified")  # shares|call|put|either|unspecified
    strike: Mapped[float | None] = mapped_column(Float)
    premium: Mapped[float | None] = mapped_column(Float)            # the CONTRACT's stated price ("At 4.60")
    expiry: Mapped[str | None] = mapped_column(String(10))          # YYYY-MM-DD when stated
    dte_hint_days: Mapped[int | None] = mapped_column(Integer)
    horizon_sessions: Mapped[int | None] = mapped_column(Integer)
    catalyst: Mapped[str | None] = mapped_column(String(256))
    dedupe_key: Mapped[str | None] = mapped_column(String(64), index=True)
    seen_count: Mapped[int] = mapped_column(Integer, default=1)     # repeat mentions attach here
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    thesis_summary: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(20), default="commentary_only")
    is_actionable: Mapped[bool] = mapped_column(Boolean, default=False)
    extraction: Mapped[dict] = mapped_column(JSONVariant, default=dict)  # full LLM output + grounding
    verification: Mapped[dict | None] = mapped_column(JSONVariant)      # check results
    status: Mapped[str] = mapped_column(String(20), default="extracted", index=True)
    # extracted | verified | parked | verification_failed | proposed | dismissed
    # parked = live checks failed only on price position (deviation / past target):
    # the tip technique watches for the level instead of killing the signal
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


# --- technique pipeline (docs/techniques/enhanced-market/PIPELINE-PLAN.md) --------------------

class ManagedPositionRow(Base):
    """A durable (multi-day) managed position — platform plan phase 2b. Legs are a
    child LIST (multi-leg-ready); `config` holds the policy/overnight/entry data;
    `state` is the write-ahead runtime projection. Never deleted; closed rows are
    the history the scorecards read."""
    __tablename__ = "managed_positions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    technique: Mapped[str] = mapped_column(String(32), default="generic", server_default="generic", index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    portfolio_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # opening|open|closing|closed|attention
    tags: Mapped[list] = mapped_column(JSONVariant, default=list, server_default='[]')
    config: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    legs: Mapped[list] = mapped_column(JSONVariant, default=list)
    state: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CartelOptionQuote(Base):
    """Append-only observations for Cartel replay, separate from daily chain data."""
    __tablename__ = 'options_cartel_quotes'
    __table_args__ = (Index('ix_cartel_quote_lookup', 'run_id', 'contract', 'available_at'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('technique_runs.id'))
    contract: Mapped[str] = mapped_column(String(32))
    source_at: Mapped[int | None] = mapped_column(BigInteger)
    available_at: Mapped[int] = mapped_column(BigInteger)
    confirmed_at: Mapped[int] = mapped_column(BigInteger)
    bid: Mapped[float] = mapped_column(Float)
    ask: Mapped[float] = mapped_column(Float)
    bid_size: Mapped[int] = mapped_column(BigInteger)
    ask_size: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(64))
    feed_mode: Mapped[str] = mapped_column(String(32))
    delayed: Mapped[bool] = mapped_column(Boolean)
    halted: Mapped[bool] = mapped_column(Boolean)


class OptionChainSnapshot(Base):
    """One nightly row per (date, contract): volume, OI, IV, bid/ask/mid (research
    B5, 2026-08-27). OI history cannot be backfilled from any source, which is why
    this table exists; the Flow repeat-hit signal and IV-percentile gates read it."""
    __tablename__ = "option_chain_snapshots"
    __table_args__ = (
        UniqueConstraint("date", "occ", name="uq_chain_snapshot"),
        Index("ix_chain_snapshot_underlying", "underlying", "date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(10))            # ET date of the snapshot
    occ: Mapped[str] = mapped_column(String(21))             # unpadded OCC contract symbol
    underlying: Mapped[str] = mapped_column(String(32))
    expiry: Mapped[str | None] = mapped_column(String(10))
    strike: Mapped[float | None] = mapped_column(Float)
    option_type: Mapped[str | None] = mapped_column(String(4))
    volume: Mapped[int] = mapped_column(BigInteger, default=0)
    open_interest: Mapped[int] = mapped_column(BigInteger, default=0)
    iv: Mapped[float | None] = mapped_column(Float)
    delta: Mapped[float | None] = mapped_column(Float)
    bid: Mapped[float | None] = mapped_column(Float)
    ask: Mapped[float | None] = mapped_column(Float)
    mid: Mapped[float | None] = mapped_column(Float)
    last: Mapped[float | None] = mapped_column(Float)


class TechniqueRun(Base):
    """One analysis run. Created at start, completed once; never edited after
    `status` leaves `running`."""
    __tablename__ = "technique_runs"
    technique: Mapped[str] = mapped_column(String(32), default="enhanced_market", server_default="enhanced_market", index=True)
    tags: Mapped[list] = mapped_column(JSONVariant, default=list, server_default='[]')   # free-form, e.g. source:xyz — scorecards group by tag

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str | None] = mapped_column(ForeignKey("chat_threads.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    as_of: Mapped[int | None] = mapped_column(BigInteger)        # epoch ms analysed, null = live
    primary_tf: Mapped[str] = mapped_column(String(8), default="1m")
    mode: Mapped[str] = mapped_column(String(16), default="full")  # full | image_only
    trigger: Mapped[str] = mapped_column(String(16), default="manual")  # manual | scan | chat
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    # running | done | failed
    verdict: Mapped[str | None] = mapped_column(String(16), index=True)   # setup | no_setup
    setup_type: Mapped[str | None] = mapped_column(String(24))
    confidence: Mapped[float | None] = mapped_column(Float)
    grounded: Mapped[bool | None] = mapped_column(Boolean)
    facts: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    result: Mapped[dict] = mapped_column(JSONVariant, default=dict)       # PipelineResult.to_dict()
    images: Mapped[dict] = mapped_column(JSONVariant, default=dict)       # tf -> asset id
    usage: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    llm: Mapped[dict] = mapped_column(JSONVariant, default=dict)          # model, effort, display
    # Provenance snapshot taken when the run starts: thresholds, technique.* /
    # llm.* settings, prompt/rulebook/code versions, bars-snapshot asset id.
    # Lets a review tie a verdict to the exact process version that produced it.
    config: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    # Set when this run is a replay of an earlier one (same symbol/as_of, maybe
    # different thresholds/prompt) so the two can be diffed.
    parent_run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class TechniqueOutcome(Base):
    """What price actually did after a run — the "facts of the matter" a review
    compares the verdict against. One row per (run, plan_source): the emitted
    analysis plan and, when the run declined, the deterministic candidate it
    rejected (so missed trades are measurable too). Re-scored while `partial`."""
    __tablename__ = "technique_outcomes"
    technique: Mapped[str] = mapped_column(String(32), default="enhanced_market", server_default="enhanced_market", index=True)
    tags: Mapped[list] = mapped_column(JSONVariant, default=list, server_default='[]')   # free-form, e.g. source:xyz — scorecards group by tag

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("technique_runs.id"), index=True)
    setup_id: Mapped[str | None] = mapped_column(String(64))
    plan_source: Mapped[str] = mapped_column(String(48))          # analysis | candidate | trigger:<id> (tip trigger ids overflow 24 — 2026-09-08)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending | partial | scored | unscorable
    horizon_bars: Mapped[int] = mapped_column(Integer, default=60)
    plan: Mapped[dict] = mapped_column(JSONVariant, default=dict)   # entry/stop/targets scored
    outcome: Mapped[str | None] = mapped_column(String(16))        # not_filled|stopped|tp1..3|horizon
    r_multiple: Mapped[float | None] = mapped_column(Float)
    mfe_r: Mapped[float | None] = mapped_column(Float)             # max favourable excursion, in R
    mae_r: Mapped[float | None] = mapped_column(Float)             # max adverse excursion, in R
    bars_held: Mapped[int | None] = mapped_column(Integer)
    bars_after: Mapped[int] = mapped_column(Integer, default=0)    # bars available after as_of
    path: Mapped[dict] = mapped_column(JSONVariant, default=dict)   # {+5,+15,+30,+60: {high,low,close}}
    bars_asset_id: Mapped[str | None] = mapped_column(String(64))  # chat_assets row with the after-bars
    note: Mapped[str | None] = mapped_column(Text)
    scored_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class TechniqueReview(Base):
    """A human/Claude review of one run: what was expected, whether the verdict
    held up, which pipeline stage is to blame, and the planned fix. Append-only:
    a run can be reviewed more than once (e.g. before and after a fix)."""
    __tablename__ = "technique_reviews"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("technique_runs.id"), index=True)
    reviewer: Mapped[str] = mapped_column(String(16), default="user")   # user | claude
    expected_verdict: Mapped[str | None] = mapped_column(String(16))    # setup | no_setup
    expected_setup_type: Mapped[str | None] = mapped_column(String(24))
    expected_plan: Mapped[dict] = mapped_column(JSONVariant, default=dict)  # {entry, stop, targets?}
    expectation_note: Mapped[str] = mapped_column(Text, default="")
    review_verdict: Mapped[str] = mapped_column(String(24), index=True)
    # correct | wrong_verdict | wrong_levels | wrong_plan | late | data_issue | unclear
    root_cause_stage: Mapped[str | None] = mapped_column(String(24), index=True)
    # data | detectors | facts_prompt | pass_context | pass_pattern | pass_entry |
    # critic | grounding | options | thresholds | other
    notes: Mapped[str] = mapped_column(Text, default="")
    actions: Mapped[list] = mapped_column(JSONVariant, default=list)   # [{desc, file?, status}]
    process_version: Mapped[dict] = mapped_column(JSONVariant, default=dict)  # copied from run.config
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class TechniqueSweep(Base):
    """One walk-forward sweep: build a session plan at every close in [start, end]
    for each symbol and score it on the next session. Rows live in
    `technique_walkforward`; `summary` is `walkforward.aggregate()` over them."""
    __tablename__ = "technique_sweeps"
    technique: Mapped[str] = mapped_column(String(32), default="enhanced_market", server_default="enhanced_market", index=True)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), default="")
    symbols: Mapped[list] = mapped_column(JSONVariant, default=list)
    start: Mapped[str] = mapped_column(String(10))
    end: Mapped[str] = mapped_column(String(10))
    params: Mapped[dict] = mapped_column(JSONVariant, default=dict)   # structureTfs, triggerTf, thresholds, ...
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)   # running | done | failed
    progress: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    summary: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class TechniqueWalkforward(Base):
    """One (sweep, symbol, plan session) row: the plan built at that close and how
    the next session scored it. Light by design — promote a row to a full plan
    run (`TechniqueService.promote`) for a deep review."""
    __tablename__ = "technique_walkforward"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sweep_id: Mapped[str] = mapped_column(ForeignKey("technique_sweeps.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    session: Mapped[str] = mapped_column(String(10), index=True)      # plan built at this session's close
    plan_for: Mapped[str | None] = mapped_column(String(10))
    plan: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    result: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    promoted_run_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_technique_walkforward_sweep_sym_sess", TechniqueWalkforward.sweep_id,
      TechniqueWalkforward.symbol, TechniqueWalkforward.session, unique=True)


class TechniqueArmed(Base):
    """An armed session plan: which account it trades in, in which mode, and
    its live state (trackers, trades, last events). Kept so a restart re-arms
    today's plans and the dashboard can show history. `events` (journal) holds
    the full audit trail; this row is the projection."""
    __tablename__ = "technique_armed"
    technique: Mapped[str] = mapped_column(String(32), default="enhanced_market", server_default="enhanced_market", index=True)

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    plan_for: Mapped[str] = mapped_column(String(10), index=True)
    portfolio_id: Mapped[str] = mapped_column(String(64), index=True)
    mode: Mapped[str] = mapped_column(String(16), default="proposal")      # alert | proposal | auto
    config: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="armed", index=True)  # armed | paused | expired | disarmed
    state: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TechniqueSetup(Base):
    """A setup emitted by a run (valid or not; invalid ones keep their reasons)."""
    __tablename__ = "technique_setups"
    technique: Mapped[str] = mapped_column(String(32), default="enhanced_market", server_default="enhanced_market", index=True)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("technique_runs.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    setup_type: Mapped[str] = mapped_column(String(24))
    direction: Mapped[str] = mapped_column(String(8))
    entry: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    targets: Mapped[list] = mapped_column(JSONVariant, default=list)
    risk_reward: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    valid: Mapped[bool] = mapped_column(Boolean, default=False)
    rules: Mapped[list] = mapped_column(JSONVariant, default=list)
    no_trade_reasons: Mapped[list] = mapped_column(JSONVariant, default=list)
    options: Mapped[dict | None] = mapped_column(JSONVariant)
    proposal_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    # open | proposed | expired | dismissed
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ChatThread(Base):
    __tablename__ = "chat_threads"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    kind: Mapped[str] = mapped_column(String(16), default="chat")   # chat | run
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ChatMessage(Base):
    """Every turn, pipeline pass, tool call and tool result. Never updated."""
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("chat_threads.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(16))       # user | assistant
    blocks: Mapped[list] = mapped_column(JSONVariant, default=list)   # API content blocks (JSON)
    meta: Mapped[dict] = mapped_column(JSONVariant, default=dict)     # pass, usage, model, tool info
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ChatAsset(Base):
    """Binary attachments (chart PNGs, pasted screenshots) referenced by id
    from message blocks so the JSON rows stay small."""
    __tablename__ = "chat_assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str | None] = mapped_column(String(64), index=True)
    media_type: Mapped[str] = mapped_column(String(32))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    meta: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_chat_messages_thread_seq", ChatMessage.thread_id, ChatMessage.seq, unique=True)


class FlowRead(Base):
    """The Flow technique's daily verdict per symbol — flagged contracts,
    aggregates, repeat-hit state and the plain-language reasons. Context for
    Tip verification and EM reads; never an order path in v1. Chain data
    itself lives in `option_chain_snapshots` (the research feed, single
    writer) — Flow reads it, never writes it."""
    __tablename__ = "flow_reads"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    lean: Mapped[str] = mapped_column(String(8), default="none")    # bull | bear | mixed | none
    read: Mapped[dict] = mapped_column(JSONVariant, default=dict)   # flags, aggregates, reasons
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


Index("ix_flow_reads_day_symbol", FlowRead.day, FlowRead.symbol, unique=True)


class TipAnalystRun(Base):
    """One Tips-analyst appraisal, with its full play-by-play so a run can be
    reviewed and the process tuned. `trace` is the ordered record of every
    step (llm turn, tool call, tool result, note, final). Streamed live on the
    `tip_analyst` bus topic while running; never edited after `status` leaves
    running. Copyable `id` is the reference."""
    __tablename__ = "tip_analyst_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    signal_id: Mapped[str | None] = mapped_column(String(64), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(64), index=True)  # the intake run that spawned this appraisal
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)  # running|done|failed
    kind: Mapped[str] = mapped_column(String(12), default="appraise")  # appraise|intake
    verdict: Mapped[str | None] = mapped_column(String(16))     # take|watch|skip|review
    model: Mapped[str | None] = mapped_column(String(64))
    tools: Mapped[list] = mapped_column(JSONVariant, default=list)    # tool names available
    trace: Mapped[list] = mapped_column(JSONVariant, default=list)    # ordered steps
    opinion: Mapped[dict] = mapped_column(JSONVariant, default=dict)  # the AnalystOpinion dump
    tip: Mapped[dict] = mapped_column(JSONVariant, default=dict)      # the tip snapshot analysed
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # KFIN-04 (2026-09-14): process ownership — the runtime that started the run (`runtime.runtime_id()`,
    # host:pid:boot-token) and the last time its task said it was alive. Restart readiness judges a
    # "running" row by its owner's live task / heartbeat, never by the row's age alone.
    owner: Mapped[str | None] = mapped_column(String(96), default=_runtime_id)
    heartbeat_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class DiscordMessage(Base):
    """Mirror of every message the gateway saw in a MONITORED channel — the
    source's own history ("bought NVDA" in the morning, "sold 40%" in the
    afternoon are one story). The analyst queries it (search_messages tool) to
    cross-reference follow-ups against tips and open positions. Text is the
    flattened content+embeds; images are CDN URLs (signed, may expire — the
    ingested copy, if any, holds the transcription). Pruned to
    `techniques.tip.mirror_max_messages`, oldest first."""
    __tablename__ = "discord_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)   # discord message id
    channel_id: Mapped[str] = mapped_column(String(32), index=True)
    source_name: Mapped[str | None] = mapped_column(String(128), index=True)
    guild_name: Mapped[str | None] = mapped_column(String(128))
    author: Mapped[str] = mapped_column(String(128), default="")
    author_id: Mapped[str | None] = mapped_column(String(32))
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    text: Mapped[str] = mapped_column(Text, default="")
    images: Mapped[list] = mapped_column(JSONVariant, default=list)          # original CDN URLs
    local_images: Mapped[list] = mapped_column(JSONVariant, default=list)    # filenames in discord_media/
    posted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    edited_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))  # newest revision seen (gateway envelope, 2026-09-09)
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TipNote(Base):
    """Shared tips knowledge — durable notes that outlive one run. A tip often
    carries context that matters LATER ("this SPY put is downside protection for
    my Oct-Dec calls"): the analyst saves it here (save_note tool) and every
    later run is handed the notes matching its tip's ticker/source, plus the
    general ones, before it starts. The user can add/delete notes in the UI.
    Scope is a single string: "general", "source:<name>", "ticker:<SYM>" or
    "signal:<id>" (per-tip detail)."""
    __tablename__ = "tip_notes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(160), index=True, default="general")
    text: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(80), default="user")  # "user" | "analyst:<run8>"
    signal_id: Mapped[str | None] = mapped_column(String(64), index=True)
    run_id: Mapped[str | None] = mapped_column(String(64))
    # rule lifecycle (NEXT-GAPS A8): an audit SUPERSEDES, never deletes — the
    # id of the refined rule (or "expired:<run8>"); superseded rules are
    # excluded from the analyst's injection but stay as history
    superseded_by: Mapped[str | None] = mapped_column(String(80))
    # a contradiction the audit surfaced — resolving it is a HUMAN click
    needs_human: Mapped[bool] = mapped_column(Boolean, default=False)
    # knowledge lifecycle (KNOWLEDGE plan B1/B5, FinMem-style layered retention):
    # NULL = never expires (rules/general, audit-gated); expiry is QUERY-TIME —
    # an expired note simply stops being injected/listed (kept as history, like
    # superseded). Citation refresh: participating in a completed live appraisal
    # extends valid_until by the scope's TTL.
    valid_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_cited_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    supplied_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # times INJECTED (Codex finding 7: supplied != used)
    last_supplied_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    cited_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # immutable-revision lifecycle (KB-03, 2026-09-13): every mutation of the
    # fields above snapshots the PRIOR state into tip_note_revisions first;
    # revised_at = last mutation, revision_no = current revision. A historical
    # (as_of) read resolves the revision that was KNOWN at that moment.
    revised_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    revision_no: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # KB-04: a core rule is mandatory in every rulebook selection — a flood of
    # newer case reports can never silently push it out of the analyst's context
    core: Mapped[bool] = mapped_column(Boolean, default=False)
    # R63-02: a delete is a tombstone that keeps the note's replacement link —
    # `superseded_by` stays what it was (or "deleted:user" for a live note);
    # this stamp is the deletion itself, snapshotted like every transition
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class TipNoteRevision(Base):
    """Immutable prior states of a tip note (KB-03). One row per mutation of
    text/scope/expiry/supersession/flag: the state that was KNOWN from
    `known_from` until `known_until` (the mutation instant). Never edited,
    never deleted — the historical truth an as_of read reconstructs. Legacy
    mutations made before this table existed have no row: such history is
    labeled unavailable, never backdated."""
    __tablename__ = "tip_note_revisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    note_id: Mapped[str] = mapped_column(String(64), index=True)
    revision_no: Mapped[int] = mapped_column(Integer, default=1)
    known_from: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    known_until: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    scope: Mapped[str] = mapped_column(String(160))
    text: Mapped[str] = mapped_column(Text)
    valid_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by: Mapped[str | None] = mapped_column(String(80))
    needs_human: Mapped[bool] = mapped_column(Boolean, default=False)
    core: Mapped[bool] = mapped_column(Boolean, default=False)          # decision-relevant: projected too
    reason: Mapped[str] = mapped_column(String(40), default="edit")   # edit|supersede|pin|refresh|flag|delete


class TipFrozenBundle(Base):
    """KFIN-09 (2026-09-14): an IMMUTABLE case bundle for the frozen knowledge
    comparison - the message content, the tool outputs the original run saw,
    the rule/note set with ids + revisions, model + settings and the exact
    context manifest. The id is derived from the canonical content hash, so a
    re-capture of unchanged evidence returns the same bundle; a row is never
    edited. Replays read ONLY the bundle: missing inputs stay missing."""
    __tablename__ = "tip_frozen_bundles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    signal_id: Mapped[str | None] = mapped_column(String(64), index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    bundle: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class TipFrozenReplay(Base):
    """One replay of a frozen bundle under one knowledge variant: the report
    (decision, grounding, protections, no-verdict, latency, tokens, tool
    calls served/missing, notes the model WANTED to save - never written).
    Insert-only evidence; never a note, an order or a book."""
    __tablename__ = "tip_frozen_replays"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    bundle_id: Mapped[str] = mapped_column(String(64), index=True)
    variant: Mapped[str] = mapped_column(String(32), index=True)
    report_hash: Mapped[str] = mapped_column(String(64))
    report: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class TipEntryCohortRow(Base):
    """KFIN-09 entry-variant COHORT: one row per eligible IDEA - every
    extracted actionable open/add signal at its intake decision, including
    skips, declines, blocked/review-gated cards, shadows, parks and
    verification failures (not only proposals). Times are kept separate
    (source post, receipt, decision); the quote at decision carries its own
    freshness + provenance; the delayed sample is a LATER observation and is
    labeled so - "unknown at alert" stays unknown."""
    __tablename__ = "tip_entry_cohort"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(64), index=True)
    content_id: Mapped[str | None] = mapped_column(String(64), index=True)
    source: Mapped[str | None] = mapped_column(String(128), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(16))
    decision_kind: Mapped[str] = mapped_column(String(16), default="intake")   # intake | redecision
    posted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    source_instrument: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    proposed_instrument: Mapped[dict | None] = mapped_column(JSONVariant)
    source_premium: Mapped[float | None] = mapped_column(Float)
    quote_symbol: Mapped[str | None] = mapped_column(String(32))
    quote_at_decision: Mapped[dict | None] = mapped_column(JSONVariant)
    quote_status: Mapped[str] = mapped_column(String(16), default="missing")   # fresh | stale | missing
    delayed_sample: Mapped[dict | None] = mapped_column(JSONVariant)
    delayed_status: Mapped[str] = mapped_column(String(16), default="unknown")  # pending | sampled | unknown | missed
    delayed_due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    gaps: Mapped[list] = mapped_column(JSONVariant, default=list)
    event_context: Mapped[dict | None] = mapped_column(JSONVariant)   # TMR-01: verified event label at decision
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class TipHoldSnapshotRow(Base):
    """PROF-03 (2026-09-15) overnight-hold study: one pre-close snapshot per
    open Tips position (arm `carry`) or per Tips position that exited intraday
    that session (arm `intraday_exit`), with the exact leg's qualified pre-close
    quote, the declared horizon/exits, planned risk and costs; the next
    session's first qualified quote is sampled separately. Research evidence
    only - never a position, an order or a policy change."""
    __tablename__ = "tip_hold_snapshots"
    # HOLD142-02: ONE observation per (study version, session, position, leg, arm)
    __table_args__ = (Index("ix_tip_hold_observation_key", "observation_key", unique=True),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    observation_key: Mapped[str | None] = mapped_column(String(200))
    study_version: Mapped[str | None] = mapped_column(String(24))
    position_id: Mapped[str] = mapped_column(String(64), index=True)
    session_date: Mapped[str] = mapped_column(String(10), index=True)
    arm: Mapped[str] = mapped_column(String(16), index=True)            # carry | intraday_exit
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    leg_symbol: Mapped[str] = mapped_column(String(32))
    sec_type: Mapped[str] = mapped_column(String(8))
    qty: Mapped[float] = mapped_column(Float)
    entry_qty: Mapped[float | None] = mapped_column(Float)          # the entry's full size (fee allocation)
    entry_price: Mapped[float] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(8), default="long")
    source: Mapped[str | None] = mapped_column(String(128))
    horizon: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    exits_policy: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    planned_risk: Mapped[float | None] = mapped_column(Float)
    planned_risk_qty: Mapped[float | None] = mapped_column(Float)   # the size the planned risk was for
    fees: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    # HOLD142-01: the protocol windows and the actual observation times
    observed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    window: Mapped[dict | None] = mapped_column(JSONVariant)
    expected_next_session: Mapped[str | None] = mapped_column(String(10))
    next_open_window: Mapped[dict | None] = mapped_column(JSONVariant)
    # HOLD142-03: what the position's own management did before the next-open sample
    carry_outcome: Mapped[dict | None] = mapped_column(JSONVariant)
    portfolio_id: Mapped[str | None] = mapped_column(String(64))     # 2026-09-16: the book the observation belongs to
    book_kind: Mapped[str | None] = mapped_column(String(12))        # sim (Practice) | shadow | live - reported apart
    # HOLD-SCOPE-02 (2026-09-16): the book's status AT CAPTURE - quarantined / archived / the
    # position's status - so a quarantined or unreconciled book is graded diagnostic, never adequate
    book_status: Mapped[dict | None] = mapped_column(JSONVariant)
    preclose_quote: Mapped[dict | None] = mapped_column(JSONVariant)
    preclose_status: Mapped[str] = mapped_column(String(16), default="missing")
    exit_price: Mapped[float | None] = mapped_column(Float)
    next_open_quote: Mapped[dict | None] = mapped_column(JSONVariant)
    next_open_status: Mapped[str] = mapped_column(String(16), default="pending")
    next_open_sampled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    gaps: Mapped[list] = mapped_column(JSONVariant, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class TipEntryVariantResult(Base):
    """One entry variant's SEPARATE result book for one cohort row
    (book = "variant:<name>"): the simulated fill under the shared budget /
    fee / fill assumptions, or the reason the evidence is insufficient.
    Never a Portfolio, never a P&L claim."""
    __tablename__ = "tip_entry_variant_results"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)     # "<cohort id>:<variant>"
    cohort_id: Mapped[str] = mapped_column(String(64), index=True)
    variant: Mapped[str] = mapped_column(String(32), index=True)
    book: Mapped[str] = mapped_column(String(48), index=True)
    adequate: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TipExecutionIncident(Base):
    """KB-06 (2026-09-14): an execution-integrity INCIDENT — persisted evidence
    that the automated entry path produced or acted on something the desk
    cannot trust. Opened by structured evidence, scoped to what it implicates,
    honoured at final admission by every automated entry path, released only
    by a cause-specific validation at the incident's current revision. Never
    cleared by a clock, a restart or a date rollover."""
    __tablename__ = "tip_execution_incidents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    opened_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)   # open | resolved
    kind: Mapped[str] = mapped_column(String(16))                                   # integrity | hold
    cause: Mapped[str] = mapped_column(String(48))
    scope: Mapped[dict] = mapped_column(JSONVariant, default=dict)      # {technique, portfolioId, entryPath?, symbol?}
    evidence: Mapped[list] = mapped_column(JSONVariant, default=list)   # references only: {kind, id, note, at, ...}
    release_criteria: Mapped[str] = mapped_column(Text, default="")
    why: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)           # bumps on every evidence append
    resolver: Mapped[str | None] = mapped_column(String(80))
    resolution: Mapped[dict] = mapped_column(JSONVariant, default=dict)


class TipKnowledgeCycle(Base):
    """R63-04: one bounded knowledge-audit CYCLE — the eligible scope set at
    cycle start plus per-scope progress (pending / done / failed / dropped,
    attempts, backoff). A run audits pending work only; the cycle completes
    when nothing is pending, which is what lets the maintenance watermark
    advance in propose-only mode instead of paying for the same groups daily."""
    __tablename__ = "tip_knowledge_cycles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="open")        # open | done
    eligible: Mapped[dict] = mapped_column(JSONVariant, default=dict)       # scope -> {notes, addedAt}
    progress: Mapped[dict] = mapped_column(JSONVariant, default=dict)       # scope -> {status, attempts, ...}
    discovered: Mapped[list] = mapped_column(JSONVariant, default=list)     # scopes that became eligible mid-cycle


class TipKnowledgeBatch(Base):
    """The durable receipt of one audit batch (KB-02-A): written in the SAME
    transaction as the note mutations it describes, keyed by the batch id
    (unique identity — never a recency-limited scan). `status` proposed =
    validated but not applied (propose-only mode); applied = mutations
    committed. `payload_hash` guards a reused id with a different payload.
    The journal event is published AFTER commit and is not the source of
    truth for idempotency."""
    __tablename__ = "tip_knowledge_batches"

    id: Mapped[str] = mapped_column(String(240), primary_key=True)      # "<run_id>:<scope>"
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    scope: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16), default="proposed")  # proposed | applied | rejected
    payload_hash: Mapped[str] = mapped_column(String(40))
    proposal: Mapped[dict] = mapped_column(JSONVariant, default=dict)    # accepted/rejected + expected revisions
    applied: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    applied_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class TechniqueMethodNote(Base):
    """EM method ingestion (docs/techniques/enhanced-market/INGESTION-PLAN.md):
    one note per captured item from the author's channels — a watch-list post,
    a chart, or the pre-trading video (link -> transcript). `extraction` holds
    the LLM read (summary, board, claims, vetoes) and `board_check` what OUR
    pipeline made of the named symbols (armed / new plan / rejected + reason).
    This table is the durable memory of the method's evolution; TRADING-RULES
    stays the judgement log. EM-only: `technique` is always enhanced_market."""
    __tablename__ = "technique_method_notes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    technique: Mapped[str] = mapped_column(String(32), default="enhanced_market", server_default="enhanced_market", index=True)
    message_id: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)   # discord message id (dedupe)
    channel_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    channel_name: Mapped[str] = mapped_column(String(128), default="")
    author: Mapped[str] = mapped_column(String(128), default="")
    kind: Mapped[str] = mapped_column(String(16), default="post", index=True)      # post | chart | video
    status: Mapped[str] = mapped_column(String(24), default="new", index=True)     # new | pending_transcript | transcribed | extracted | checked | failed
    text: Mapped[str] = mapped_column(Text, default="")
    images: Mapped[list] = mapped_column(JSONVariant, default=list)
    media_url: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text)
    extraction: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    board_check: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    meta: Mapped[dict] = mapped_column(JSONVariant, default=dict)                  # attempts, lastError, model, durationSeconds
    error: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TechniqueSourceRevision(Base):
    """Delivery B (2026-09-14): one IMMUTABLE observation of an EM source message's state - a distinct
    accepted state per row (create | edit | delete | restore); identical redelivery is not a revision.
    Identity, author, timestamps, verbatim text, attachment set, content hash, supersedes. No transcript,
    no usability here (those are artifacts). EM-only (`technique/source_revisions.py`)."""
    __tablename__ = "technique_source_revisions"
    __table_args__ = (UniqueConstraint("note_id", "revision", name="uq_source_revision"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    note_id: Mapped[str] = mapped_column(String(64), index=True)          # technique_method_notes.id (the message identity)
    technique: Mapped[str] = mapped_column(String(32), default="enhanced_market", server_default="enhanced_market", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(16), default="create")        # create | edit | delete | restore
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    source_edited_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))   # Discord edited_timestamp (ordering)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    gateway_seq: Mapped[int | None] = mapped_column(BigInteger)             # gateway sequence (tie-break)
    author_id: Mapped[str | None] = mapped_column(String(32))
    author_name: Mapped[str] = mapped_column(String(128), default="")
    channel_id: Mapped[str] = mapped_column(String(32), default="")
    channel_name: Mapped[str] = mapped_column(String(128), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    attachments: Mapped[list] = mapped_column(JSONVariant, default=list)   # attachment URLs (hashes when fetched)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    supersedes: Mapped[str | None] = mapped_column(String(64))


class TechniqueSourceArtifact(Base):
    """Delivery B: an APPEND-ONLY derived output of one revision (transcript | extraction | scenarios),
    keyed by (revision, kind, input hash, config hash) = the idempotent output key (`id`). `completed_at`
    is the availability fact; NULL = unknown (legacy backfill), never derived from `updated_at`."""
    __tablename__ = "technique_source_artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)          # artifact_key(...)
    revision_id: Mapped[str] = mapped_column(String(64), index=True)
    note_id: Mapped[str] = mapped_column(String(64), index=True)
    technique: Mapped[str] = mapped_column(String(32), default="enhanced_market", server_default="enhanced_market")
    kind: Mapped[str] = mapped_column(String(16), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    config_hash: Mapped[str] = mapped_column(String(64), default="")
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    payload: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TechniqueSourceJob(Base):
    """Delivery B: MUTABLE progress for one revision - stage, lease, FENCE TOKEN (a worker commits only
    while its token is current), per-item checkpoints, outcome (in_progress | retryable | permanent | done)."""
    __tablename__ = "technique_source_jobs"
    __table_args__ = (UniqueConstraint("revision_id", name="uq_source_job_revision"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    note_id: Mapped[str] = mapped_column(String(64), index=True)
    revision_id: Mapped[str] = mapped_column(String(64))
    technique: Mapped[str] = mapped_column(String(32), default="enhanced_market", server_default="enhanced_market")
    stage: Mapped[str] = mapped_column(String(24), default="received", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    fence_token: Mapped[int] = mapped_column(Integer, default=0)
    checkpoint: Mapped[list] = mapped_column(JSONVariant, default=list)    # completed item keys
    outcome: Mapped[str] = mapped_column(String(16), default="in_progress", index=True)
    next_due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TechniquePrepDecision(Base):
    """em-prep-policy-v1 (2026-09-18): one preparation eligibility decision per CAUSAL INPUT key - the resume ledger of a
    preparation batch (done work is reused, a changed input is a new row, only failed reads retry). Order-free: a row
    here never arms anything by itself."""
    __tablename__ = "technique_prep_decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)               # causal input key
    technique: Mapped[str] = mapped_column(String(32), default="enhanced_market", server_default="enhanced_market")
    session: Mapped[str] = mapped_column(String(10), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    candidate_key: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    origin: Mapped[str] = mapped_column(String(24), default="batch")
    mode: Mapped[str] = mapped_column(String(24), default="baseline")
    status: Mapped[str] = mapped_column(String(16), default="done")             # done | failed
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    disposition: Mapped[str] = mapped_column(String(32), default="")
    payload: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TechniqueBookSnapshot(Base):
    """ED-04 (`book-snapshot-v1`, 2026-09-18): APPEND-ONLY EM book observations - realized / displayed / covered
    executable, side by side. Written only by the EM recorder behind `techniques.enhanced_market.book_snapshot_observe`
    (default OFF). Research evidence: never read by an order, exit or risk path; never edited."""
    __tablename__ = "technique_book_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    technique: Mapped[str] = mapped_column(String(32), default="enhanced_market", server_default="enhanced_market")
    portfolio_id: Mapped[str] = mapped_column(String(64), index=True)
    session: Mapped[str] = mapped_column(String(10), index=True)               # ET trading date
    seq: Mapped[int] = mapped_column(Integer, default=0)
    captured_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    reason: Mapped[str] = mapped_column(String(24), default="periodic")
    causal_run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    build: Mapped[str] = mapped_column(String(64), default="")
    scorable: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TechniqueCounterfactual(Base):
    """A trade the app MISSED through a bug (a restart stranded the entry, a
    crashed loop, a dead quote stream), reconstructed after the fix by replaying
    the fired order through the runner's own exit rules on the real bars
    (`execution/counterfactual.py`). It is a ledger of what the METHOD would
    have earned - never a fill in any portfolio: Practice stays what actually
    happened (PLATFORM-RULES 2026-09-02). Technique-agnostic."""
    __tablename__ = "technique_counterfactuals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    technique: Mapped[str] = mapped_column(String(32), default="enhanced_market", server_default="enhanced_market", index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    trigger_id: Mapped[str] = mapped_column(String(64), default="")
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    session: Mapped[str] = mapped_column(String(10), index=True)                  # ET date the trade belonged to
    reason: Mapped[str] = mapped_column(Text, default="")                          # the bug, in one sentence
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # win | loss | scratch | not_filled | open | error
    result: Mapped[dict] = mapped_column(JSONVariant, default=dict)                # fill, exits, pnl, r, price sources
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class FlowSweep(Base):
    """A sweep: the minute a rolling window of buyer-initiated option volume,
    on a session already trading a multiple of open interest, qualified
    (`research/optiontrades.py`, FLOW-CONFIRMATION-PLAN phase 0). One row per
    contract per qualifying minute; `method` says whether buys were classified
    on the live NBBO or by the historical tick test."""
    __tablename__ = "flow_sweeps"
    __table_args__ = (UniqueConstraint("occ", "minute_ts", name="uq_flow_sweep_occ_minute"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    underlying: Mapped[str] = mapped_column(String(32), index=True)
    occ: Mapped[str] = mapped_column(String(32), index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)          # ET session date
    minute_ts: Mapped[int] = mapped_column(BigInteger)                 # epoch ms of the qualifying minute
    window_contracts: Mapped[int] = mapped_column(Integer, default=0)
    window_buys: Mapped[int] = mapped_column(Integer, default=0)
    cumulative: Mapped[int] = mapped_column(Integer, default=0)
    oi: Mapped[int] = mapped_column(Integer, default=0)
    vol_oi: Mapped[float] = mapped_column(Float, default=0.0)
    big_prints: Mapped[int] = mapped_column(Integer, default=0)
    notional: Mapped[float] = mapped_column(Float, default=0.0)
    method: Mapped[str] = mapped_column(String(8), default="tick")      # tick | nbbo
    source: Mapped[str] = mapped_column(String(16), default="alpaca")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CartelHistoryCache(Base):
    """Replaceable research cache; immutable decisions retain their own input snapshots."""
    __tablename__ = 'cartel_history_cache'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    observed_at: Mapped[int] = mapped_column(BigInteger)
    start_ms: Mapped[int] = mapped_column(BigInteger)
    end_ms: Mapped[int] = mapped_column(BigInteger)
    payload: Mapped[dict] = mapped_column(JSONVariant, default=dict)


class CartelIgnitionThesis(Base):
    __tablename__ = 'cartel_ignition_theses'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    event_session: Mapped[str] = mapped_column(String(10), index=True)
    as_of: Mapped[int] = mapped_column(BigInteger)
    stage: Mapped[str] = mapped_column(String(24), index=True)
    evidence: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CartelPreparationLease(Base):
    __tablename__ = 'cartel_preparation_leases'
    workspace: Mapped[str] = mapped_column(String(16), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int] = mapped_column(BigInteger)
