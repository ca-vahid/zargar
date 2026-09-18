"""Claude-based signal extraction with quote-grounding validation.

The LLM proposes; deterministic code disposes. Every extracted field must be
backed by a verbatim evidence quote that actually appears in the source text —
signals failing that check are marked ungrounded and never become proposals.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .schemas import EXTRACTION_SYSTEM_PROMPT, ExtractionResult, TradeSignal

log = logging.getLogger("zargar.extraction")

# attachment coverage statuses (KFIN-07, 2026-09-14). Only PROCESSED carries
# evidence; every other status is explicit in the manifest and never quoted.
ATT_PROCESSED = "processed"
ATT_ABSENT = "absent"                    # listed on the message, no bytes ever reached intake
ATT_UNREADABLE = "unreadable"            # bytes arrived but are not an image we can decode
ATT_FAILED = "failed"                    # fetch or transcription failed (error recorded)
ATT_SKIPPED = "skipped-over-budget"      # beyond the attachment / size / vision-call budget
CAPTION_BLOCK = "caption"


@dataclass
class CorpusBlock:
    """One addressable piece of a message's evidence: the caption, or one
    attachment (by its stable id). `text` is empty unless the attachment was
    processed — an unprocessed image is never evidence."""
    id: str                      # "caption" | "attachment:<attachment id>"
    text: str
    n: int | None = None         # attachment ordinal (1-based), None for the caption
    total: int | None = None
    status: str = ATT_PROCESSED
    detail: str = ""

    @property
    def is_evidence(self) -> bool:
        return self.status == ATT_PROCESSED and bool(self.text.strip())


def attachment_block_id(attachment_id: str) -> str:
    return f"attachment:{attachment_id}"


def build_grounding_corpus(caption: str, attachments: list[dict]) -> tuple[str, list[CorpusBlock]]:
    """Caption + one block per attachment, in attachment order, each headed
    `--- attachment <n> of <total> … (id …) ---`. Returns the sectioned text
    the extractor/analyst read AND the block list deterministic grounding
    uses (grounding never matches a header line — only block bodies)."""
    blocks: list[CorpusBlock] = []
    parts: list[str] = []
    if caption.strip():
        blocks.append(CorpusBlock(id=CAPTION_BLOCK, text=caption))
        parts.append(caption)
    for idx, att in enumerate(attachments, start=1):
        i = int(att.get("n") or idx)                    # the message's own ordinal
        total = int(att.get("total") or len(attachments))
        aid = str(att.get("id") or i)
        status = str(att.get("status") or ATT_ABSENT)
        transcript = str(att.get("transcript") or "") if status == ATT_PROCESSED else ""
        detail = str(att.get("error") or att.get("reason") or "")
        blocks.append(CorpusBlock(id=attachment_block_id(aid), text=transcript, n=i,
                                  total=total, status=status, detail=detail))
        if status == ATT_PROCESSED:
            parts.append(f"--- attachment {i} of {total} processed (id {aid}) "
                         f"IMAGE TRANSCRIPT ---\n{transcript}")
        else:
            parts.append(f"--- attachment {i} of {total} {status} (id {aid}) "
                         f"NOT PROCESSED — no evidence"
                         + (f": {detail[:120]}" if detail else "") + " ---")
    return "\n".join(parts), blocks


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


def ground_signal(signal: TradeSignal, source_text: str,
                  blocks: list[CorpusBlock] | None = None) -> dict:
    """Deterministic grounding verdict for one extracted signal.

    With `blocks` (multi-attachment intake, KFIN-07) every quote is attributed
    to the FIRST evidence block that contains it — the caption, else an
    attachment by id — and the verdict records `quoteSources` (quote → block)
    and `evidenceBlocks`. Header lines and unprocessed attachments are not
    searched: a claim can only be grounded to text the desk actually read."""
    quote_sources: dict[str, str] = {}
    if blocks is not None:
        evidence = [b for b in blocks if b.is_evidence]
        for q in signal.evidence_quotes:
            for b in evidence:
                if quote_in_source(q, b.text):
                    quote_sources[q] = b.id
                    break
        grounded_quotes = [q for q in signal.evidence_quotes if q in quote_sources]
        failed_quotes = [q for q in signal.evidence_quotes if q not in quote_sources]
        ticker_in_source = any(quote_in_source(signal.ticker, b.text) for b in evidence)
    else:
        grounded_quotes = [q for q in signal.evidence_quotes if quote_in_source(q, source_text)]
        failed_quotes = [q for q in signal.evidence_quotes if not quote_in_source(q, source_text)]
        ticker_in_source = quote_in_source(signal.ticker, source_text)
    checks = {
        "has_quotes": len(signal.evidence_quotes) > 0,
        "quotes_found": len(failed_quotes) == 0 and len(grounded_quotes) > 0,
        "ticker_evidenced": any(
            signal.ticker.upper() in q.upper() for q in grounded_quotes)
        or ticker_in_source,
        "entry_evidenced": _price_evidenced(signal.entry_price, grounded_quotes),
        "target_evidenced": _price_evidenced(signal.target_price, grounded_quotes)
        and all(_price_evidenced(t, grounded_quotes) for t in signal.target_prices),
        "stop_evidenced": _price_evidenced(signal.stop_price, grounded_quotes),
        "strike_evidenced": _price_evidenced(signal.strike, grounded_quotes),
    }
    out = {
        "passed": all(checks.values()),
        "checks": checks,
        "failedQuotes": failed_quotes,
    }
    if blocks is not None:
        out["quoteSources"] = quote_sources
        out["evidenceBlocks"] = sorted(set(quote_sources.values()),
                                       key=lambda b: (b != CAPTION_BLOCK, b))
    return out


_CONFLICT_FIELDS = ("strike", "expiry", "premium", "entry_price", "target_price",
                    "stop_price")


def _field_value(signal: TradeSignal, field: str):
    v = getattr(signal, field, None)
    if v is None and field == "target_price" and signal.target_prices:
        v = signal.target_prices[0]
    return v


def detect_attachment_conflicts(signals: list[TradeSignal],
                                groundings: list[dict]) -> list[dict]:
    """Contradictory evidence across documents is RECORDED, never blended
    (KFIN-07): two signals for the same ticker/instrument/direction whose
    evidence comes from DIFFERENT blocks (caption vs attachment, or two
    attachments) and that disagree on a price, strike, premium or expiry are
    both marked `conflict` (grounding fails — needs review) instead of one
    of them being chosen. Mutates `groundings` in place; returns the
    conflict records."""
    conflicts: list[dict] = []
    for i in range(len(signals)):
        for j in range(i + 1, len(signals)):
            a, b = signals[i], signals[j]
            if (a.ticker.upper() != b.ticker.upper() or a.instrument != b.instrument
                    or a.direction != b.direction):
                continue
            ba = set(groundings[i].get("evidenceBlocks") or [])
            bb = set(groundings[j].get("evidenceBlocks") or [])
            if not ba or not bb or ba == bb:
                continue
            for field in _CONFLICT_FIELDS:
                va, vb = _field_value(a, field), _field_value(b, field)
                if va is None or vb is None or va == vb:
                    continue
                rec = {"ticker": a.ticker.upper(), "field": field,
                       "values": [{"blocks": sorted(ba), "value": va},
                                  {"blocks": sorted(bb), "value": vb}],
                       "signals": [i, j]}
                conflicts.append(rec)
                for k in (i, j):
                    groundings[k].setdefault("conflict", []).append(rec)
                    groundings[k]["checks"]["attachments_consistent"] = False
                    groundings[k]["passed"] = False
    return conflicts


TRANSCRIBE_PROMPT = (
    "Transcribe ALL text visible in this image verbatim, in reading order — tickers, "
    "prices, strikes, dates, order rows, chart labels, usernames, timestamps and "
    "boilerplate included. Reply with the transcription only: no commentary, no "
    "markdown, no summary. If the image contains no readable text reply with "
    "exactly: (no readable text)")


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

    async def transcribe(self, image: bytes, *, label: str = "",
                         is_retry: bool = False) -> str:
        """One VISION call: the verbatim transcription of one attachment (no
        extraction). Multi-image intake (KFIN-07) transcribes every processed
        attachment beyond the primary one this way, so each transcript is
        machine-bound to its attachment id — the model never decides which
        image a line came from. Raises on provider failure (the caller marks
        the attachment `failed`)."""
        if not self.available:
            raise RuntimeError("extraction unavailable: ZARGAR_ANTHROPIC_API_KEY not configured")
        from ..technique.llm import image_block
        client = self._get_client()
        import time as _time
        _t0 = _time.perf_counter()
        try:
            response = await client.messages.create(
                model=self.model, max_tokens=4000,
                messages=[{"role": "user", "content": [
                    image_block(image),
                    {"type": "text", "text": (f"This is {label}. " if label else "")
                                             + TRANSCRIBE_PROMPT}]}])
        except Exception as exc:
            try:
                from ..research import llm_stats
                llm_stats.record("transcribe", model=self.model,
                                 stop_reason=f"exception:{type(exc).__name__}"[:48],
                                 latency_ms=(_time.perf_counter() - _t0) * 1000.0,
                                 retried=is_retry)
            except Exception:
                pass
            raise
        try:
            from ..research import llm_stats
            llm_stats.record_response("transcribe", response, model=self.model,
                                      latency_ms=(_time.perf_counter() - _t0) * 1000.0,
                                      retried=is_retry)
        except Exception:
            pass
        if getattr(response, "stop_reason", None) == "refusal":
            raise RuntimeError("transcription refused by safety classifier")
        return "".join(b.text for b in response.content
                       if getattr(b, "type", "") == "text").strip()

    async def extract(self, text: str, *, subject: str = "", source_name: str = "",
                      received_at: str = "", image: bytes | None = None,
                      is_retry: bool = False, image_label: str = "",
                      attachments_text: str = "") -> ExtractionResult:
        """Text extraction, or screenshot extraction when `image` is given (the
        model transcribes the visible text into `source_transcript`, and the
        evidence quotes are grounded against that transcript downstream).
        `attachments_text` (KFIN-07): the already-transcribed OTHER attachments
        of the same message as `--- attachment n of N (id …) ---` blocks — a
        separate document each; the model quotes from whichever holds the
        evidence and never merges different values for one trade across them.
        `is_retry`: the caller re-invoking the SAME logical request after a
        transient failure — counted as a retry, not a new request (Codex M1)."""
        if not self.available:
            raise RuntimeError("extraction unavailable: ZARGAR_ANTHROPIC_API_KEY not configured")
        client = self._get_client()
        header = (
            f"Source: {source_name or 'unknown'}\n"
            f"Subject: {subject or '(none)'}\n"
            f"Received: {received_at or 'unknown'}\n"
        )
        docs_note = (
            "\nThe message has several documents (caption + attachments). Each is a "
            "separate document: quote evidence from the one that contains it and do NOT "
            "merge different values for the same trade from different documents — when "
            "two documents disagree (a different strike, price or expiry for the same "
            "ticker) emit one signal per document with that document's values.\n"
            if attachments_text.strip() else "")
        if image is not None:
            from ..technique.llm import image_block  # shared vision plumbing (sniffs media type)
            user_content: list | str = [
                image_block(image),
                {"type": "text", "text": header + (
                    "The content is the attached screenshot"
                    + (f" — {image_label}" if image_label else "")
                    + " (the user's own chat/newsletter "
                    "client). First transcribe ALL visible text verbatim into "
                    "source_transcript, then extract signals from that transcription. "
                    "Evidence quotes must be copied character-for-character from your "
                    "transcription"
                    + (", the caption or an attachment transcript below"
                       if attachments_text.strip() else "") + "."
                    + docs_note
                    + (f"\nUser note / caption: {text}" if text.strip() else "")
                    + (f"\n{attachments_text}" if attachments_text.strip() else ""))},
            ]
        else:
            body = text
            if attachments_text.strip():
                body = (text + "\n" if text.strip() else "") + attachments_text
            user_content = (header + docs_note
                            + f"--- CONTENT START ---\n{body}\n--- CONTENT END ---")
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
            import time as _time
            _t0 = _time.perf_counter()
            try:
                response = await client.messages.create(
                    model=self.model, max_tokens=16000, system=system, messages=messages)
            except Exception as exc:
                # a FAILED attempt is measured too (Codex M1) — the caller's
                # transient-retry loop re-enters with is_retry=True
                try:
                    from ..research import llm_stats
                    llm_stats.record("extraction", model=self.model,
                                     stop_reason=f"exception:{type(exc).__name__}"[:48],
                                     latency_ms=(_time.perf_counter() - _t0) * 1000.0,
                                     retried=attempt > 0 or is_retry)
                except Exception:
                    pass
                raise
            try:
                from ..research import llm_stats
                _u = getattr(response, "usage", None)
                _stop = getattr(response, "stop_reason", None)
                llm_stats.record("extraction", model=self.model,
                                 input_tokens=int(getattr(_u, "input_tokens", 0) or 0) if _u else 0,
                                 output_tokens=int(getattr(_u, "output_tokens", 0) or 0) if _u else 0,
                                 stop_reason=str(_stop) if _stop else None,
                                 latency_ms=(_time.perf_counter() - _t0) * 1000.0,
                                 retried=attempt > 0 or is_retry)
            except Exception:
                pass
            if response.stop_reason == "refusal":
                log.warning("extraction refused by safety classifier")
                return ExtractionResult(signals=[], source_type="other",
                                        outcome="refused",
                                        outcome_detail="refused by safety classifier")
            raw = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
            try:
                parsed = _parse_result_json(raw)
                # machine-owned outcome (Codex follow-up R3): a successful
                # parse IS "ok" — model-authored outcome/outcome_detail in the
                # JSON must never forge a refusal or failure classification
                parsed.outcome, parsed.outcome_detail = "ok", None
                return parsed
            except Exception as exc:           # invalid JSON / failed validation
                last_err = str(exc)
                log.warning("extraction JSON invalid (attempt %d): %s", attempt + 1, exc)
                messages = messages + [
                    {"role": "assistant", "content": raw[:8000]},
                    {"role": "user", "content":
                        f"That JSON failed validation: {last_err[:1500]}\n"
                        "Reply again with ONLY the corrected JSON object."}]
        try:
            from ..research import llm_stats
            # ANNOTATION only (Codex M1): both attempts were already counted
            # above — this marks their outcome, it is not a third request
            llm_stats.record("extraction", model=self.model, invalid_output=True,
                             annotation=True)
        except Exception:
            pass
        log.warning("extraction returned unparseable output: %s", last_err)
        # typed outcome (Codex audit 2026-09-08 finding 3): a malformed reply
        # must never masquerade as a genuine no-signal read — the caller marks
        # the content error so the recovery sweep retries it once
        return ExtractionResult(signals=[], source_type="other",
                                outcome="invalid_output",
                                outcome_detail=str(last_err)[:400])


def _parse_result_json(raw: str) -> ExtractionResult:
    """Model text -> ExtractionResult. Tolerates markdown fences and prose
    around the object; pydantic validation (incl. the enum normalizers in
    schemas.py) is the contract."""
    import re as _re
    # E17-F2-R2: fences are markers, not boundaries - strip them all and inspect the whole reply
    s = _re.sub(r"```[A-Za-z0-9_-]*", "\n", raw or "").strip()
    i = s.find("{")
    if i == -1:
        raise ValueError("validation: no JSON object in response")
    # E17-02: take the FIRST complete object (TSLA 2026-09-17: prose/junk after the object
    # made the first-{ .. last-} slice invalid, "trailing characters"); validation errors are typed
    import json as _json
    try:
        obj, end = _json.JSONDecoder().raw_decode(s, i)
    except ValueError as exc:
        raise ValueError(f"validation: invalid JSON ({exc})") from exc
    trailing = s[end:].strip()
    try:
        parsed = ExtractionResult.model_validate(obj)
    except Exception as exc:
        raise ValueError(f"validation: {str(exc)[:600]}") from exc
    # E17-F2: a SECOND schema-valid object ("Correction: ...") makes the reply ambiguous -
    # never "first object wins" for trading content; the caller's bounded re-ask says why.
    # Trailing prose and unrelated JSON that fails the schema stay harmless.
    dec, pos, extra, scanned = _json.JSONDecoder(), end, 0, 0
    while scanned < 20:
        k = s.find("{", pos)
        if k == -1:
            break
        scanned += 1
        try:
            obj2, end2 = dec.raw_decode(s, k)
        except ValueError:
            pos = k + 1
            continue
        pos = end2
        if isinstance(obj2, dict):
            try:
                ExtractionResult.model_validate(obj2)
                extra += 1
            except Exception:
                pass
    if extra:
        raise ValueError(f"ambiguity: {extra + 1} schema-valid extraction objects in one reply - reply with exactly ONE JSON object")
    if s.find("{", pos) != -1:
        # F2-R3: scan budget exhausted with unexamined JSON content - never certify uniqueness
        raise ValueError("ambiguity: scan limit reached with unexamined JSON content after the first object "
                         "- reply with exactly ONE JSON object and no other JSON")
    if trailing:
        log.info("extraction: %d trailing character(s) after the JSON object ignored", len(trailing))
    return parsed
