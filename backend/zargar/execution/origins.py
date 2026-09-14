"""Run origins the shared runner must recognise (no technique import here)."""
from __future__ import annotations

SCENARIO_PREFIX = "scenario:"


def scenario_origin(run: dict | None) -> str | None:
    """The `scenario:<id>` origin of a run when it is a source-informed candidate (EM Delivery B,
    2026-09-14): from `config.origin` or a `scenario:*` tag. Such a run is a research record - the runner
    refuses to arm it from every path until an activation decision adds an explicit allow-list."""
    if not run:
        return None
    origin = str(((run.get("config") or {}).get("origin")) or "")
    if origin.startswith(SCENARIO_PREFIX):
        return origin
    for t in run.get("tags") or []:
        if str(t).startswith(SCENARIO_PREFIX):
            return str(t)
    return None
