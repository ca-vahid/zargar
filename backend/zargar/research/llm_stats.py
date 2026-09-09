"""Shared LLM usage collector (Codex audit finding 10 + the model-choice caveat).

Intake extraction, appraisals, reviews, digests and retros run OUTSIDE the
PlanRunner hooks, so their cost/latency never reached `TechniqueHookStats`.
This collector accumulates per-stage counters in memory and flushes ONE
`TechniqueHookStats` journal row per (technique, ET day) with an `llm` field —
extra fields are allowed by the event contract, consumers ignore what they
don't know. Retries are counted as attempts within one logical request, never
double-counted as requests in the daily rollup.

The audit's rule: collect request counts, tokens, stop reasons, retries,
invalid-output rates and latency BEFORE arguing about cheaper models.
"""
from __future__ import annotations

import datetime as dt
import logging
import time
from zoneinfo import ZoneInfo

log = logging.getLogger("zargar.research.llm_stats")

_ET = ZoneInfo("America/New_York")

# (technique, day) -> stage -> counters
_ACC: dict[tuple[str, str], dict[str, dict]] = {}


def _day() -> str:
    return dt.datetime.now(_ET).strftime("%Y-%m-%d")


def record(stage: str, *, model: str = "", input_tokens: int = 0,
           output_tokens: int = 0, stop_reason: str | None = None,
           latency_ms: float | None = None, retried: bool = False,
           invalid_output: bool = False, annotation: bool = False,
           technique: str = "tip") -> None:
    """One provider response (or one failed attempt). Semantics (Codex review
    M1, 2026-09-09): `requests` counts FIRST attempts of a logical request,
    `retries` counts subsequent attempts of the same logical request (provider
    errors / malformed-output re-asks — an ordinary tool-use turn is neither),
    and `annotation=True` marks an outcome (e.g. final invalid_output) on
    attempts ALREADY counted — it increments no request/retry."""
    key = (technique, _day())
    st = _ACC.setdefault(key, {}).setdefault(stage, {
        "requests": 0, "retries": 0, "inputTokens": 0, "outputTokens": 0,
        "invalidOutputs": 0, "stops": {}, "totalMs": 0.0, "maxMs": 0.0,
        "models": {}})
    if annotation:
        pass
    elif retried:
        st["retries"] += 1
    else:
        st["requests"] += 1
    st["inputTokens"] += int(input_tokens or 0)
    st["outputTokens"] += int(output_tokens or 0)
    if invalid_output:
        st["invalidOutputs"] += 1
    if stop_reason:
        st["stops"][str(stop_reason)] = st["stops"].get(str(stop_reason), 0) + 1
    if model:
        st["models"][model] = st["models"].get(model, 0) + 1
    if latency_ms is not None:
        st["totalMs"] = round(st["totalMs"] + float(latency_ms), 1)
        st["maxMs"] = round(max(st["maxMs"], float(latency_ms)), 1)


def record_response(stage: str, resp, *, model: str = "",
                    latency_ms: float | None = None, retried: bool = False,
                    technique: str = "tip") -> None:
    """Convenience for standalone call sites (digest, audits, experiment
    review — Codex review M1): record one provider response object."""
    u = getattr(resp, "usage", None)
    stop = getattr(resp, "stop_reason", None)
    record(stage, model=model,
           input_tokens=int(getattr(u, "input_tokens", 0) or 0) if u else 0,
           output_tokens=int(getattr(u, "output_tokens", 0) or 0) if u else 0,
           stop_reason=str(stop) if stop else None,
           latency_ms=latency_ms, retried=retried, technique=technique)


class timed:
    """`with llm_stats.timed() as t:` … pass t.ms to record()."""

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = (time.perf_counter() - self._t0) * 1000.0
        return False

    @property
    def ms_so_far(self) -> float:
        return (time.perf_counter() - self._t0) * 1000.0


# frozen batches awaiting a confirmed journal write: (technique, day) -> list
# of complete payloads. Contents AND batchId are fixed at freeze time (Codex
# review A4, 2026-09-09) — an ambiguous outcome (commit + lost ACK) retries
# the SAME payload with the SAME batchId, so consumers can deduplicate;
# counts recorded during a retry accumulate separately in _ACC.
_PENDING: dict[tuple[str, str], list[dict]] = {}


async def flush(eng, *, technique: str = "tip") -> int:
    """Journal + clear every accumulated day for `technique` (the current day
    included — the nightly job runs after the close; a restart mid-day loses
    only what was recorded since the last flush — disclosed, the collector is
    memory-only by design). Flushing FREEZES the accumulation into a pending
    batch (stable contents + batchId) BEFORE any write; a failed or ambiguous
    write retains that exact batch for the next flush (Codex M2 + A4)."""
    from ..domain import new_id
    from .. import events as ev
    # freeze current accumulation first — identity fixed before any attempt
    for key in [k for k in list(_ACC) if k[0] == technique]:
        stages = _ACC.pop(key, None)
        if stages:
            _PENDING.setdefault(key, []).append({
                "technique": key[0], "date": key[1], "batchId": new_id(),
                "hooks": {},                    # runner hooks journal their own row
                "llm": stages})
    flushed = 0
    for key in [k for k in list(_PENDING) if k[0] == technique]:
        remaining: list[dict] = []
        for payload in _PENDING[key]:
            try:
                await eng.journal.append(ev.TECHNIQUE_HOOK_STATS, payload)
                flushed += 1
            except Exception:
                log.exception("llm stats flush failed for %s — batch %s retained "
                              "verbatim for retry", key, payload["batchId"])
                remaining.append(payload)
        if remaining:
            _PENDING[key] = remaining
        else:
            _PENDING.pop(key, None)
    return flushed
