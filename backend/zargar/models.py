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


# --- technique pipeline (docs/techniques/enhanced-market/PIPELINE-PLAN.md) --------------------

class TechniqueRun(Base):
    """One analysis run. Created at start, completed once; never edited after
    `status` leaves `running`."""
    __tablename__ = "technique_runs"
    technique: Mapped[str] = mapped_column(String(32), default="enhanced_market", server_default="enhanced_market", index=True)

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

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("technique_runs.id"), index=True)
    setup_id: Mapped[str | None] = mapped_column(String(64))
    plan_source: Mapped[str] = mapped_column(String(24))          # analysis | candidate
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
