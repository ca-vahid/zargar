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
           invalid_output: bool = False, technique: str = "tip") -> None:
    """One provider response (or one failed attempt). `retried` marks attempts
    after the first within the same logical request."""
    key = (technique, _day())
    st = _ACC.setdefault(key, {}).setdefault(stage, {
        "requests": 0, "retries": 0, "inputTokens": 0, "outputTokens": 0,
        "invalidOutputs": 0, "stops": {}, "totalMs": 0.0, "maxMs": 0.0,
        "models": {}})
    if retried:
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


async def flush(eng, *, technique: str = "tip") -> int:
    """Journal + clear every accumulated day for `technique` (the current day
    included — the nightly job runs after the close; a restart mid-day flushes
    a partial row and the consumer sums rows per day)."""
    from .. import events as ev
    flushed = 0
    for key in [k for k in list(_ACC) if k[0] == technique]:
        stages = _ACC.pop(key, None)
        if not stages:
            continue
        try:
            await eng.journal.append(ev.TECHNIQUE_HOOK_STATS, {
                "technique": key[0], "date": key[1],
                "hooks": {},                    # runner hooks journal their own row
                "llm": stages})
            flushed += 1
        except Exception:
            log.exception("llm stats flush failed for %s", key)
    return flushed
