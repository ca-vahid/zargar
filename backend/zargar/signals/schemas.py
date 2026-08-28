"""Pydantic schemas for LLM signal extraction (structured outputs).

Extraction v2 (2026-08-27, Tip technique plan §A1): the schema carries the
whole trade — instrument (shares/call/put), strike, expiry, multiple targets,
the thesis horizon and the catalyst — so a tip like "NVDA 180c 9/19" survives
extraction intact. The schema stays FLAT (no nested models beyond simple
lists) and — learned 2026-08-28 on the first real screenshot — NO Literal
enums either: six enums inside a nested list drew "Schema is too complex"
(400) from the API. Enum-ish fields are plain `str` in the schema (allowed
values in the description) and a local validator normalizes them after parse.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


def _norm(value: object, allowed: set[str], default: str) -> str:
    v = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return v if v in allowed else default


class TradeSignal(BaseModel):
    ticker: str = Field(description="The stock ticker symbol, exactly as written in the source")
    exchange_hint: Optional[str] = Field(
        default=None,
        description="Exchange if stated or clearly implied (e.g. NYSE, NASDAQ, TSX, TSXV)")
    direction: str = Field(description='"long" or "short"')
    action: str = Field(
        default="open", description='One of: "open", "add", "trim", "close", "update_stop"')
    instrument: str = Field(
        default="unspecified",
        description='What the source says to buy — one of: "shares", "call", "put", "either", '
                    '"unspecified". Options shorthand like \'180c\' or \'$150p\' '
                    'means call/put. "unspecified" when the source names only the stock.')
    strike: Optional[float] = Field(
        default=None,
        description="Option strike if stated (e.g. 180 from 'NVDA 180c'). Null for shares.")
    expiry: Optional[str] = Field(
        default=None,
        description="Option expiry as YYYY-MM-DD when the source states a date (e.g. '9/19' "
                    "in a US source this year -> 2026-09-19). Null when not stated.")
    dte_hint_days: Optional[int] = Field(
        default=None,
        description="Approximate days-to-expiry when the source says something like 'weeklies' "
                    "(~5), 'next week' (~10), 'monthlies' (~30) without an exact date.")
    entry_price: Optional[float] = Field(
        default=None,
        description="Suggested entry price for the UNDERLYING stock, if stated. NOT the "
                    "option's own price — that goes in `premium`.")
    premium: Optional[float] = Field(
        default=None,
        description="The OPTION CONTRACT's own price when the source quotes it — alert-room "
                    "grammar like 'NTR 82.5C 03/19/2027 Exp. At 4.60' or 'paid 1.20' means "
                    "premium 4.60 / 1.20. Null for share tips and when no contract price is "
                    "stated. Never put a premium in entry_price.")
    entry_type: str = Field(
        default="unspecified", description='One of: "market", "limit", "range", "unspecified"')
    target_price: Optional[float] = None
    target_prices: List[float] = Field(
        default_factory=list,
        description="ALL stated price targets in order (first = nearest). Repeat target_price "
                    "here if there is only one.")
    stop_price: Optional[float] = None
    timeframe: str = Field(
        default="unspecified",
        description='One of: "day_trade", "swing", "position", "long_term", "unspecified"')
    horizon_sessions: Optional[int] = Field(
        default=None,
        description="How many TRADING DAYS the thesis has to play out, if the source implies "
                    "one ('by Friday' -> count the days, 'over the next two weeks' -> 10).")
    catalyst: Optional[str] = Field(
        default=None,
        description="The named catalyst if any (earnings date, product launch, FDA date...). "
                    "One short phrase; null when none is stated.")
    thesis_summary: str = Field(description="At most two sentences paraphrasing the thesis")
    evidence_quotes: List[str] = Field(
        description="Verbatim snippets from the source text that support the ticker, direction, "
                    "and every price/strike you extracted. Copy exactly — these are verified "
                    "against the source and the signal is discarded if they do not appear in it.")
    confidence: str = Field(
        description='One of: "explicit_call" (author explicitly says act now), "implied" '
                    '(clearly bullish/bearish without a call), "commentary_only"')
    is_actionable: bool = Field(
        description="True only for a fresh, explicit call to act now. False for recaps of past "
                    "trades, performance reviews, marketing, or ambiguous commentary. If the "
                    "ticker or direction is ambiguous, set false rather than guessing.")

    # local normalization of the enum-ish strings (see module docstring: real
    # Literal enums in the schema draw a 400 from the structured-output grammar)
    @field_validator("direction", mode="before")
    @classmethod
    def _v_direction(cls, v: object) -> str:
        m = {"long": "long", "short": "short", "bullish": "long", "bearish": "short",
             "buy": "long", "sell": "short"}
        key = str(v or "").strip().lower()
        if key not in m:
            raise ValueError(f"direction must be long or short, got {v!r}")
        return m[key]

    @field_validator("action", mode="before")
    @classmethod
    def _v_action(cls, v: object) -> str:
        return _norm(v, {"open", "add", "trim", "close", "update_stop"}, "open")

    @field_validator("instrument", mode="before")
    @classmethod
    def _v_instrument(cls, v: object) -> str:
        return _norm(v, {"shares", "call", "put", "either", "unspecified"}, "unspecified")

    @field_validator("entry_type", mode="before")
    @classmethod
    def _v_entry_type(cls, v: object) -> str:
        return _norm(v, {"market", "limit", "range", "unspecified"}, "unspecified")

    @field_validator("timeframe", mode="before")
    @classmethod
    def _v_timeframe(cls, v: object) -> str:
        return _norm(v, {"day_trade", "swing", "position", "long_term", "unspecified"},
                     "unspecified")

    @field_validator("confidence", mode="before")
    @classmethod
    def _v_confidence(cls, v: object) -> str:
        return _norm(v, {"explicit_call", "implied", "commentary_only"}, "commentary_only")


class ExtractionResult(BaseModel):
    signals: List[TradeSignal] = Field(
        description="All trade signals present. Empty list when the content contains no signal.")
    source_type: str = Field(
        description='One of: "trade_alert", "newsletter_analysis", "portfolio_update", '
                    '"marketing", "other"')
    source_transcript: Optional[str] = Field(
        default=None,
        description="ONLY when the source is an image: a verbatim transcription of every piece "
                    "of text visible in it, in reading order. Evidence quotes must be copied "
                    "from this transcription. Null for text sources.")
    stated_at: Optional[str] = Field(
        default=None,
        description="WHEN the content itself shows it was posted or sent — a visible timestamp "
                    "on a post/screenshot ('11:05 AM · Jun 23, 2026'), an email date header, a "
                    "dateline. ISO 8601: 'YYYY-MM-DDTHH:MM' when the time is visible, else "
                    "'YYYY-MM-DD'. Null when the content shows no date — never guess.")
    source_hint: Optional[str] = Field(
        default=None,
        description="WHO/WHERE this content visibly came from, when the content itself shows it: "
                    "a Discord channel or server name, the poster's handle, a newsletter or "
                    "service name, an email sender. One short name, exactly as written "
                    "(e.g. 'TraderJoe', '#alpha-alerts', 'Motley Rich Daily'). Null when the "
                    "content carries no such attribution — never guess.")

    @field_validator("source_type", mode="before")
    @classmethod
    def _v_source_type(cls, v: object) -> str:
        return _norm(v, {"trade_alert", "newsletter_analysis", "portfolio_update",
                         "marketing", "other"}, "other")


EXTRACTION_SYSTEM_PROMPT = """You extract stock and option trade signals from newsletters, \
trade-alert emails, chat-room messages (Discord/Telegram style shorthand), and message-board \
posts for a personal trading assistant.

Most content contains NO actionable signal — marketing, performance recaps, and general \
commentary are common. Return an empty signals list for those; never manufacture a trade.

Rules:
- A recap of a past trade ("we bought NVDA at $95 last year") is NOT a fresh signal.
- A company mentioned only as a comparison or index constituent is NOT a signal.
- Do not infer a ticker from a company name unless the source states the ticker or the mapping \
is unambiguous; when inferring, the evidence quote must contain the company name you mapped.
- Every extracted price, strike and ticker must be backed by a verbatim quote in \
evidence_quotes, copied character-for-character from the source text.
- Alert-room bot grammar (Discord trade-alert services): "OPEN:" = action open, "CLOSE:"/"STC" \
= close, "TRIM" = trim, "Update:" usually references an earlier position (action per its text). \
"NTR 82.5C 03/19/2027 Exp. At 4.60" = NTR calls, strike 82.5, expiry 2027-03-19, premium 4.60 \
(the contract's price — put it in `premium`, never entry_price). Ignore boilerplate \
(disclaimers, "Informational purposes only", bot version lines) but transcribe it in \
source_transcript when reading a screenshot.
- Chat shorthand: "NVDA 180c 9/19" = NVDA calls, strike 180, expiry Sep 19 (instrument="call"); \
"150p" = puts at 150 (instrument="put", direction usually "short" on the stock unless it is a \
hedge); "BTO"/"STC" = buy to open / sell to close; a bare month/day date is this year unless \
that is already past, then next year. A put tip means direction="short" (bearish on the stock) \
with instrument="put" — never direction="long".
- If ticker or direction is ambiguous, set is_actionable=false rather than guessing.
- confidence is "explicit_call" only when the author explicitly says to buy/sell now, ideally \
with entry/stop/target; "implied" when clearly bullish/bearish without a call; otherwise \
"commentary_only".
- The message's received timestamp is provided; treat stale or undated calls with suspicion.
- If the content VISIBLY shows when it was posted or sent — a timestamp on the post, an email \
date, a dateline — put it in stated_at (ISO 8601). Freshness is checked downstream; a stale \
tip is replayed on history instead of traded. Never infer a date that is not shown.
- If the content VISIBLY shows where it came from — a channel name, a poster's username or \
avatar label in a screenshot, a newsletter masthead, a signature — put that name in \
source_hint exactly as written. Attribution builds the source's track record; never invent one.
"""
