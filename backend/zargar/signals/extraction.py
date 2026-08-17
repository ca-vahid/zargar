"""Claude-based signal extraction with quote-grounding validation.

The LLM proposes; deterministic code disposes. Every extracted field must be
backed by a verbatim evidence quote that actually appears in the source text —
signals failing that check are marked ungrounded and never become proposals.
"""
from __future__ import annotations

import logging
import re

from .schemas import EXTRACTION_SYSTEM_PROMPT, ExtractionResult, TradeSignal

log = logging.getLogger("zargar.extraction")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def quote_in_source(quote: str, source: str) -> bool:
    """Whitespace-insensitive containment check."""
    q, s = _normalize(quote), _normalize(source)
    return bool(q) and q in s


def _price_evidenced(price: float | None, quotes: list[str]) -> bool:
    """A stated price must literally appear in at least one grounded quote."""
    if price is None:
        return True
    variants = {
        f"{price:g}", f"{price:.2f}", f"{price:.1f}", f"{price:.0f}",
        f"{price:,.2f}", f"{price:,.0f}",
    }
    joined = " ".join(quotes)
    return any(v in joined for v in variants)


def ground_signal(signal: TradeSignal, source_text: str) -> dict:
    """Deterministic grounding verdict for one extracted signal."""
    grounded_quotes = [q for q in signal.evidence_quotes if quote_in_source(q, source_text)]
    failed_quotes = [q for q in signal.evidence_quotes if not quote_in_source(q, source_text)]
    checks = {
        "has_quotes": len(signal.evidence_quotes) > 0,
        "quotes_found": len(failed_quotes) == 0 and len(grounded_quotes) > 0,
        "ticker_evidenced": any(
            signal.ticker.upper() in q.upper() for q in grounded_quotes)
        or quote_in_source(signal.ticker, source_text),
        "entry_evidenced": _price_evidenced(signal.entry_price, grounded_quotes),
        "target_evidenced": _price_evidenced(signal.target_price, grounded_quotes),
        "stop_evidenced": _price_evidenced(signal.stop_price, grounded_quotes),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "failedQuotes": failed_quotes,
    }


class Extractor:
    """Wraps the Claude API call. Instantiated lazily so the app runs without a key
    (ingestion still stores raw content; extraction just reports unavailable)."""

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self.model = model
        self._client = None

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        return self._client

    async def extract(self, text: str, *, subject: str = "", source_name: str = "",
                      received_at: str = "") -> ExtractionResult:
        if not self.available:
            raise RuntimeError("extraction unavailable: ZARGAR_ANTHROPIC_API_KEY not configured")
        client = self._get_client()
        user_content = (
            f"Source: {source_name or 'unknown'}\n"
            f"Subject: {subject or '(none)'}\n"
            f"Received: {received_at or 'unknown'}\n"
            f"--- CONTENT START ---\n{text}\n--- CONTENT END ---"
        )
        response = await client.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=EXTRACTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            output_format=ExtractionResult,
        )
        if response.stop_reason == "refusal":
            log.warning("extraction refused by safety classifier")
            return ExtractionResult(signals=[], source_type="other")
        result = response.parsed_output
        if result is None:
            log.warning("extraction returned unparseable output")
            return ExtractionResult(signals=[], source_type="other")
        return result
