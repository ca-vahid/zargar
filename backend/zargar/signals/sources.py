"""Per-source policy for the tip technique.

Every tip source (a Discord room, a newsletter, the user pasting by hand) gets
a policy: how tips from it enter (wait for the level vs at tip time), how they
are sized and budgeted, which DTE window expresses them, and how far the
source has earned its way up the trust ladder (shadow -> alert -> proposal ->
auto). Platform defaults live at `techniques.tip.*`; per-source overrides in
the `techniques.tip.sources` dict. User decision 2026-08-27: entry defaults to
level_touch; tip_time must be earned by a positive scorecard.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

CONVICTION_RANK = {"commentary_only": 0, "implied": 1, "explicit_call": 2}
ENTRY_MODES = ("level_touch", "tip_time")
SOURCE_MODES = ("shadow", "alert", "proposal", "auto")


@dataclass(frozen=True)
class SourcePolicy:
    name: str
    entry: str = "level_touch"        # level_touch | tip_time (tip_time is earned)
    mode: str = "proposal"            # shadow | alert | proposal | auto
    risk_pct: float = 1.0             # of equity, sized off the stop distance
    budget_per_tip: float = 1000.0    # max $ committed to one tip (option debit / share notional)
    budget_open_max: float = 5000.0   # max $ open across this source's tips at once
    dte_min: int = 10                 # option expression window (never 0DTE)
    dte_max: int = 30
    horizon_sessions: int = 15        # tip expires unfilled/unresolved after N sessions
    min_conviction: str = "implied"   # below this: shadow-only, no proposal
    max_open_tips: int = 5

    def to_dict(self) -> dict:
        return asdict(self)

    def meets_conviction(self, confidence: str) -> bool:
        return CONVICTION_RANK.get(confidence, 0) >= CONVICTION_RANK.get(self.min_conviction, 1)


def resolve_policy(settings, source_name: str | None) -> SourcePolicy:
    """Platform defaults (`techniques.tip.*`) overlaid with the source's own
    entry in `techniques.tip.sources` (keyed by source name)."""
    name = source_name or "unknown"

    def base(key: str, fallback):
        v = settings.get(f"techniques.tip.{key}", fallback)
        return fallback if v is None else v

    overrides = settings.get("techniques.tip.sources") or {}
    o = overrides.get(name) or {}

    def pick(key: str, fallback):
        v = o.get(key)
        return base(key, fallback) if v is None else v

    entry = str(pick("entry", "level_touch"))
    mode = str(pick("mode", "proposal"))
    return SourcePolicy(
        name=name,
        entry=entry if entry in ENTRY_MODES else "level_touch",
        mode=mode if mode in SOURCE_MODES else "proposal",
        risk_pct=float(pick("risk_pct", 1.0)),
        budget_per_tip=float(pick("budget_per_tip", 1000.0)),
        budget_open_max=float(pick("budget_open_max", 5000.0)),
        dte_min=int(pick("dte_min", 10)),
        dte_max=int(pick("dte_max", 30)),
        horizon_sessions=int(pick("horizon_sessions", 15)),
        min_conviction=str(pick("min_conviction", "implied")),
        max_open_tips=int(pick("max_open_tips", 5)),
    )
