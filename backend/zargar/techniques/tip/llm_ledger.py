"""Durable per-call usage for the Tips intake reads that are NOT analyst runs (2026-09-23, cost lever 3).

Intake extraction and attachment transcription used to be measured only by the in-memory `llm_stats` rollup, so their
cost vanished on every restart and the desk's cost report could only give a lower bound. Every request attempt now
writes one `tip_llm_calls` row. A ledger failure is logged and swallowed: it can never fail an intake.

`ref` is bound by the caller with `bind_ref(content_id)` (a contextvar), so the extractor needs no new arguments.
"""
from __future__ import annotations

import contextvars
import logging

log = logging.getLogger("zargar.tip.llm_ledger")

_REF: contextvars.ContextVar[str | None] = contextvars.ContextVar("tip_llm_ref", default=None)


def bind_ref(ref: str | None):
    """Bind the raw content id for the calls made in this task; returns the token for `reset_ref`."""
    return _REF.set(str(ref) if ref else None)


def reset_ref(token) -> None:
    try:
        _REF.reset(token)
    except Exception:
        pass


def usage_fields(resp) -> dict:
    u = getattr(resp, "usage", None)
    g = (lambda k: int(getattr(u, k, 0) or 0)) if u is not None else (lambda k: 0)
    return {"input_tokens": g("input_tokens"), "output_tokens": g("output_tokens"),
            "cache_read_tokens": g("cache_read_input_tokens"), "cache_write_tokens": g("cache_creation_input_tokens")}


async def record(eng, *, stage: str, model: str, resp=None, stop_reason: str | None = None,
                 latency_ms: float | None = None, retried: bool = False, error: str | None = None) -> None:
    sf = getattr(eng, "sf", None)
    if sf is None:
        return
    try:
        from ...models import TipLlmCall
        row = TipLlmCall(stage=stage[:32], model=(model or "")[:64], ref=_REF.get(),
                         stop_reason=(stop_reason or (str(getattr(resp, "stop_reason", "") or "") or None) or None),
                         latency_ms=latency_ms, retried=bool(retried), error=(error or None) and error[:200],
                         **(usage_fields(resp) if resp is not None else {}))
        async with sf() as s:
            s.add(row)
            await s.commit()
    except Exception as exc:                      # never fail an intake over bookkeeping
        log.warning("tip_llm_calls write failed (%s): %s", stage, exc)
