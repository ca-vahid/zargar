"""Process provenance for technique runs.

A run's verdict is only reviewable if we know *which version of the process*
produced it: the prompt, the rulebook, the thresholds/settings and the code.
`snapshot()` captures all of that at run start; `process_version()` is a short
fingerprint of the parts that change behaviour, so two runs can be compared
fairly and a review can say "this was fixed in <version>".
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path

from .rulebook import RULES, Thresholds


def _h(text: str, n: int = 12) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def prompt_version() -> str:
    from .schemas import SYSTEM_PROMPT
    return _h(SYSTEM_PROMPT)


def rulebook_version() -> str:
    return _h(json.dumps(RULES, sort_keys=True))


@lru_cache
def code_version() -> str:
    """Short git sha of the running tree, captured at import (process start) so
    a long-running server reports the code it is actually running, not whatever
    HEAD moved to later. `ZARGAR_GIT_SHA` wins (packaged deploys); otherwise ask
    git from the package directory; else 'unknown'."""
    env = os.environ.get("ZARGAR_GIT_SHA", "").strip()
    if env:
        return env[:12]
    try:
        out = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=Path(__file__).parent,
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            sha = out.stdout.strip()
            dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                                   cwd=Path(__file__).parent, capture_output=True, text=True, timeout=5)
            if dirty.returncode == 0 and dirty.stdout.strip():
                sha += "-dirty"
            return sha
    except Exception:
        pass
    return "unknown"


def thresholds_dict(t: Thresholds) -> dict:
    d = dataclasses.asdict(t)
    for k, v in list(d.items()):
        if isinstance(v, tuple):
            d[k] = list(v)
    return d


def process_version(*, thresholds: Thresholds, settings: dict, model: str, effort: str) -> str:
    """Fingerprint of everything that changes the verdict for the same bars."""
    blob = json.dumps({
        "prompt": prompt_version(), "rulebook": rulebook_version(), "code": code_version(),
        "thresholds": thresholds_dict(thresholds), "settings": settings,
        "model": model, "effort": effort,
    }, sort_keys=True, default=str)
    return _h(blob, 10)


def snapshot(*, thresholds: Thresholds, settings_all: dict, model: str, effort: str,
             thinking_display: str, max_passes: int, timeframes: list[str],
             parent_run_id: str | None = None, overrides: dict | None = None) -> dict:
    """Everything a reviewer needs to reproduce / compare the run."""
    settings = {k: v for k, v in settings_all.items()
                if k.startswith("technique.") or k.startswith("llm.")}
    return {
        "promptVersion": prompt_version(),
        "rulebookVersion": rulebook_version(),
        "codeVersion": code_version(),
        "processVersion": process_version(thresholds=thresholds, settings=settings,
                                          model=model, effort=effort),
        "thresholds": thresholds_dict(thresholds),
        "settings": settings,
        "model": model, "effort": effort, "thinkingDisplay": thinking_display,
        "maxPasses": max_passes, "timeframes": list(timeframes),
        "parentRunId": parent_run_id,
        "overrides": overrides or {},
    }


# Capture at import: the sha of the code this process loaded.
CODE_VERSION_AT_START = code_version()
