"""setup-target-v1 — a destination belongs to a setup, not to the day.

Implements `docs/techniques/team2/notes/research/2026-09-21-setup-target-resolution-spec.md`.
Pure: no I/O, no clock, no settings reads. Everything it uses is passed in, so a replay of the same
inputs returns the same record for ever.

The defect this exists for (2026-09-21): the day carries ONE global destination per side, and F81b
re-derives it to the pre-market extreme when the planned target has been overrun. That is a sound
destination for a setup whose source is a prior-day zone edge, and it is the *source* for a
pre-market breakout. SPY planned 762.95 -> re-derived to the pre-market high 767.26; the 10:00
breakout of 767.26 then carried 767.26 as its destination and every entry was refused.

The rule: enumerate the destinations known when the setup was confirmed, reject any that is not
strictly beyond the source, and take the NEAREST survivor. Nearest is what makes it safe - it can
never skip an intervening level to manufacture room, and relative to a free choice it can only ever
choose closer or equal, never farther. That is the asymmetry that separates it from the entry-time
re-planning variants this desk already rejected, which substitute a FARTHER level to unblock a
trade that was refused.
"""
from __future__ import annotations

SPEC_VERSION = "setup-target-v1"

# 2.1: what role the setup's own level plays. A destination is judged against this.
ROLE_BY_KIND = {
    "pm_break_up": "pm_extreme", "pm_break_down": "pm_extreme",
    "key_break_up": "key_level", "key_break_down": "key_level",
}

# 2.3: tie-break order when two candidates sit at the same distance.
ORIGIN_ORDER = ("pd_zone", "pm_extreme", "ladder", "planned")


def role_for(kind: str) -> str:
    """2.1 — the role the setup's source level plays. Scenario setups lean on a zone edge."""
    return ROLE_BY_KIND.get(str(kind), "zone_edge")


def _beyond(price: float, source: float, direction: str, tick: float) -> bool:
    """Strictly beyond the source, in the trade's direction, by more than one tick."""
    gap = (price - source) if direction == "long" else (source - price)
    return gap > max(float(tick), 0.0)


def candidates(*, source: float, direction: str, zones: dict | None = None,
               pm_high: float | None = None, pm_low: float | None = None,
               ladder: list | None = None, planned: float | None = None,
               input_ts: dict | None = None) -> list[dict]:
    """2.2 — every destination known at confirmation, each labelled with its origin.

    Ordering is by origin only here; distance ordering happens in `resolve`. `input_ts` maps an
    origin to the timestamp of the input it came from, so the record can show that nothing
    observed after the setup's confirmation entered the ladder.
    """
    long = direction == "long"
    ts = dict(input_ts or {})
    out: list[dict] = []

    def add(origin: str, price) -> None:
        if price is None:
            return
        try:
            p = float(price)
        except (TypeError, ValueError):
            return
        out.append({"origin": origin, "price": p, "inputTs": ts.get(origin)})

    z = zones or {}

    def edge(name: str, side: str):
        zn = z.get(name)
        if zn is None:
            return None
        return getattr(zn, side, None) if not isinstance(zn, dict) else zn.get(side)

    # the prior-day zone edge ahead: a long aims at the high zone, a short at the low zone
    add("pd_zone", edge("pdh", "bottom") if long else edge("pdl", "top"))
    add("pd_zone", edge("pdh", "top") if long else edge("pdl", "bottom"))
    # the pre-market extreme ahead — excluded when it IS the source, which is the whole defect
    add("pm_extreme", pm_high if long else pm_low)
    for lvl in (ladder or []):
        price = lvl.get("price") if isinstance(lvl, dict) else lvl
        add("ladder", price)
    add("planned", planned)
    return out


def resolve(*, source: float, direction: str, kind: str, tick: float = 0.01,
            actionable: float | None = None, **kw) -> dict:
    """2.3-2.7 — choose the destination, or refuse, and say exactly why for every candidate.

    Returns a record that is persisted whole: the source and its role, the full ladder with a
    verdict per candidate, the chosen destination, and the spec version. `actionable`, when given,
    additionally requires the destination to still be ahead of the live price (2.5); the production
    guards re-check that after awaited work and before submission, and are not replaced here.
    """
    role = role_for(kind)
    ladder = candidates(source=source, direction=direction, **kw)
    seen: set[float] = set()
    judged: list[dict] = []
    for c in ladder:
        p, why = float(c["price"]), None
        if round(p, 6) in seen:
            why = "duplicate"
        elif not _beyond(p, float(source), direction, tick):
            # 2.4 — the SPY/QQQ case: the destination is the level the setup just broke
            why = "not_distinct" if abs(p - float(source)) <= max(float(tick), 0.0) else "wrong_side"
        elif actionable is not None and not _beyond(p, float(actionable), direction, 0.0):
            why = "behind_price"                              # 2.5
        seen.add(round(p, 6))
        judged.append({**c, "accepted": why is None, "rejectedFor": why,
                       "distance": round(abs(p - float(source)), 6)})

    ok = [c for c in judged if c["accepted"]]
    # 2.3/2.6 — NEAREST first. A skipped level would have been nearer, so this cannot skip one.
    ok.sort(key=lambda c: (c["distance"], ORIGIN_ORDER.index(c["origin"])
                           if c["origin"] in ORIGIN_ORDER else 99, c["price"]))
    chosen = ok[0] if ok else None
    return {
        "version": SPEC_VERSION,
        "source": round(float(source), 6),
        "sourceRole": role,
        "direction": direction,
        "kind": str(kind),
        "tick": float(tick),
        "actionable": (round(float(actionable), 6) if actionable is not None else None),
        "ladder": judged,
        "target": (chosen["price"] if chosen else None),
        "targetOrigin": (chosen["origin"] if chosen else None),
        "targetInputTs": (chosen.get("inputTs") if chosen else None),
        # 2.7 — an explicit refusal, never a dropped or widened target
        "refused": chosen is None,
        "refusedFor": None if chosen else ("no candidate is distinct and beyond the source"
                                           if judged else "no destination candidates were known"),
    }


__all__ = ["resolve", "candidates", "role_for", "SPEC_VERSION", "ROLE_BY_KIND", "ORIGIN_ORDER"]
