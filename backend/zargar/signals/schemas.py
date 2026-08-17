"""Pydantic schemas for LLM signal extraction (structured outputs)."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class TradeSignal(BaseModel):
    ticker: str = Field(description="The stock ticker symbol, exactly as written in the source")
    exchange_hint: Optional[str] = Field(
        default=None,
        description="Exchange if stated or clearly implied (e.g. NYSE, NASDAQ, TSX, TSXV)")
    direction: Literal["long", "short"]
    action: Literal["open", "add", "trim", "close", "update_stop"]
    entry_price: Optional[float] = Field(default=None, description="Suggested entry price if stated")
    entry_type: Literal["market", "limit", "range", "unspecified"] = "unspecified"
    target_price: Optional[float] = None
    stop_price: Optional[float] = None
    timeframe: Literal["day_trade", "swing", "position", "long_term", "unspecified"] = "unspecified"
    thesis_summary: str = Field(description="At most two sentences paraphrasing the thesis")
    evidence_quotes: List[str] = Field(
        description="Verbatim snippets from the source text that support the ticker, direction, "
                    "and every price you extracted. Copy exactly — these are verified against "
                    "the source and the signal is discarded if they do not appear in it.")
    confidence: Literal["explicit_call", "implied", "commentary_only"]
    is_actionable: bool = Field(
        description="True only for a fresh, explicit call to act now. False for recaps of past "
                    "trades, performance reviews, marketing, or ambiguous commentary. If the "
                    "ticker or direction is ambiguous, set false rather than guessing.")


class ExtractionResult(BaseModel):
    signals: List[TradeSignal] = Field(
        description="All trade signals present. Empty list when the content contains no signal.")
    source_type: Literal[
        "trade_alert", "newsletter_analysis", "portfolio_update", "marketing", "other"]


EXTRACTION_SYSTEM_PROMPT = """You extract stock trade signals from newsletters, trade-alert \
emails, and message-board posts for a personal trading assistant.

Most content contains NO actionable signal — marketing, performance recaps, and general \
commentary are common. Return an empty signals list for those; never manufacture a trade.

Rules:
- A recap of a past trade ("we bought NVDA at $95 last year") is NOT a fresh signal.
- A company mentioned only as a comparison or index constituent is NOT a signal.
- Do not infer a ticker from a company name unless the source states the ticker or the mapping \
is unambiguous; when inferring, the evidence quote must contain the company name you mapped.
- Every extracted price and ticker must be backed by a verbatim quote in evidence_quotes, \
copied character-for-character from the source text.
- If ticker or direction is ambiguous, set is_actionable=false rather than guessing.
- confidence is "explicit_call" only when the author explicitly says to buy/sell now, ideally \
with entry/stop/target; "implied" when clearly bullish/bearish without a call; otherwise \
"commentary_only".
- The message's received timestamp is provided; treat stale or undated calls with suspicion.
"""
