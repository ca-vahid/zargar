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


_NUM_TOKEN = re.compile(r"\d+(?:\.\d+)?")


def _numeric_tokens(quotes: list[str]) -> set[float]:
    """Every number appearing in the grounded quotes, shorthand included:
    '$180', '180c', '1,250.50', '150p' all yield their numeric value."""
    out: set[float] = set()
    for tok in _NUM_TOKEN.findall(" ".join(quotes).replace(",", "")):
        try:
            out.add(float(tok))
        except ValueError:  # pragma: no cover - regex guarantees a float
            pass
    return out


def _price_evidenced(price: float | None, quotes: list[str]) -> bool:
    """A stated price must appear in at least one grounded quote — literally
    ('184.50') or as a shorthand token ('$184.50', '184.5c', '1,250'). Discord
    tips write '180c'; the literal-substring rule alone would fail exactly the
    messages the tip technique exists for."""
    if price is None:
        return True
    variants = {
        f"{price:g}", f"{price:.2f}", f"{price:.1f}", f"{price:.0f}",
        f"{price:,.2f}", f"{price:,.0f}",
    }
    joined = " ".join(quotes)
    if any(v in joined for v in variants):
        return True
    return any(abs(t - price) < 1e-9 for t in _numeric_tokens(quotes))


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
        "target_evidenced": _price_evidenced(signal.target_price, grounded_quotes)
        and all(_price_evidenced(t, grounded_quotes) for t in signal.target_prices),
        "stop_evidenced": _price_evidenced(signal.stop_price, grounded_quotes),
        "strike_evidenced": _price_evidenced(signal.strike, grounded_quotes),
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
                      received_at: str = "", image: bytes | None = None) -> ExtractionResult:
        """Text extraction, or screenshot extraction when `image` is given (the
        model transcribes the visible text into `source_transcript`, and the
        evidence quotes are grounded against that transcript downstream)."""
        if not self.available:
            raise RuntimeError("extraction unavailable: ZARGAR_ANTHROPIC_API_KEY not configured")
        client = self._get_client()
        header = (
            f"Source: {source_name or 'unknown'}\n"
            f"Subject: {subject or '(none)'}\n"
            f"Received: {received_at or 'unknown'}\n"
        )
        if image is not None:
            from ..technique.llm import image_block  # shared vision plumbing (sniffs media type)
            user_content: list | str = [
                image_block(image),
                {"type": "text", "text": header + (
                    "The content is the attached screenshot (the user's own chat/newsletter "
                    "client). First transcribe ALL visible text verbatim into "
                    "source_transcript, then extract signals from that transcription. "
                    "Evidence quotes must be copied character-for-character from your "
                    "transcription." + (f"\nUser note: {text}" if text.strip() else ""))},
            ]
        else:
            user_content = header + f"--- CONTENT START ---\n{text}\n--- CONTENT END ---"
        # Prompted JSON + local pydantic validation, NOT API structured outputs:
        # ExtractionResult (a nested 18-field list) exceeds the structured-output
        # grammar budget ("Schema is too complex", 2026-08-28) even with every
        # enum flattened to str. The schema lives in the prompt instead and the
        # model's own field descriptions do double duty as extraction guidance.
        import json as _json
        schema = _json.dumps(ExtractionResult.model_json_schema(), separators=(",", ":"))
        system = (EXTRACTION_SYSTEM_PROMPT
                  + "\n\nReply with ONLY one JSON object that validates against this JSON "
                    "Schema — no prose, no markdown fences:\n" + schema)
        messages: list = [{"role": "user", "content": user_content}]
        last_err = ""
        for attempt in range(2):
            response = await client.messages.create(
                model=self.model, max_tokens=16000, system=system, messages=messages)
            if response.stop_reason == "refusal":
                log.warning("extraction refused by safety classifier")
                return ExtractionResult(signals=[], source_type="other")
            raw = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
            try:
                return _parse_result_json(raw)
            except Exception as exc:           # invalid JSON / failed validation
                last_err = str(exc)
                log.warning("extraction JSON invalid (attempt %d): %s", attempt + 1, exc)
                messages = messages + [
                    {"role": "assistant", "content": raw[:8000]},
                    {"role": "user", "content":
                        f"That JSON failed validation: {last_err[:1500]}\n"
                        "Reply again with ONLY the corrected JSON object."}]
        log.warning("extraction returned unparseable output: %s", last_err)
        return ExtractionResult(signals=[], source_type="other")


def _parse_result_json(raw: str) -> ExtractionResult:
    """Model text -> ExtractionResult. Tolerates markdown fences and prose
    around the object; pydantic validation (incl. the enum normalizers in
    schemas.py) is the contract."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    i, j = s.find("{"), s.rfind("}")
    if i == -1 or j <= i:
        raise ValueError("no JSON object in response")
    return ExtractionResult.model_validate_json(s[i:j + 1])
