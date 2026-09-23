"""Which model and effort each Tips call uses (2026-09-23, cost levers).

Tips-scoped knobs, all journaled settings:
  * `techniques.tip.analyst_model`    appraise / intake review / retro / digest ("" = the engine's extraction_model)
  * `techniques.tip.extraction_model` intake extraction + attachment transcription ("" = the engine's extraction_model)
  * `techniques.tip.analyst_effort` / `techniques.tip.extraction_effort`  low | medium | high | xhigh | max | "" (model
    default). Opus 5 defaults to `high`; Opus 5.5 defaults to `medium`, so pinning `high` keeps the analyst's depth
    unchanged across the model switch. Sent as `output_config.effort`; never sent to a model that has no effort ladder.
"""
from __future__ import annotations

EFFORTS = ("low", "medium", "high", "xhigh", "max")
_NO_EFFORT_PREFIXES = ("claude-haiku", "claude-3", "offline")


def _get(settings, key: str, default=""):
    try:
        return settings.get(key, default) if settings is not None else default
    except Exception:
        return default


def analyst_model(settings, config) -> str:
    return str(_get(settings, "techniques.tip.analyst_model") or "") or str(getattr(config, "extraction_model", "") or "")


def extraction_model(settings, default: str) -> str:
    return str(_get(settings, "techniques.tip.extraction_model") or "") or default


def effort_kw(settings, key: str, model: str) -> dict:
    """`{"output_config": {"effort": e}}` or `{}` - merged into a messages.create call."""
    e = str(_get(settings, key) or "").strip().lower()
    if e not in EFFORTS or not model or str(model).startswith(_NO_EFFORT_PREFIXES):
        return {}
    return {"output_config": {"effort": e}}
