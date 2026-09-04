"""Macro event calendar — PLACEHOLDER (2026-09-03, Team2 desk).

FOMC decisions, CPI, NFP and similar releases make index price action choppy; a technique
may want to size down or skip those days (`techniques.<id>.avoid_event_days`). There is no
free, reliable machine-readable source wired yet, so v0 is a MANUAL list in settings:

    research.macro_events = [
        {"date": "2026-09-17", "name": "FOMC decision", "kind": "fomc", "time": "14:00"},
        {"date": "2026-09-11", "name": "CPI", "kind": "cpi", "time": "08:30"},
    ]

`MacroCalendar.events_on(date)` / `is_event_day(date)` read that list; `describe()` tells the
UI what the source is. When a real source is added (a fetched ICS/JSON feed, or the FOMC
schedule scraped once a year), implement `refresh()` and keep the same read API — callers
never see the difference. Never a firing trigger: an event day is a risk flag, like the
earnings calendar (BUILDING-A-TECHNIQUE §1).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

KINDS = ("fomc", "cpi", "nfp", "pce", "gdp", "opex", "other")


@dataclass(frozen=True)
class MacroEvent:
    date: str           # YYYY-MM-DD (ET)
    name: str
    kind: str = "other"
    time: str | None = None   # HH:MM ET when known

    def to_dict(self) -> dict:
        return {"date": self.date, "name": self.name, "kind": self.kind, "time": self.time}


class MacroCalendar:
    """Read-only view over `research.macro_events` (settings). Source: manual (v0)."""

    SOURCE = "manual"

    def __init__(self, settings) -> None:
        self._settings = settings

    def _events(self) -> list[MacroEvent]:
        raw = self._settings.get("research.macro_events", []) or []
        out: list[MacroEvent] = []
        for row in raw:
            try:
                d = str(row.get("date"))
                dt.date.fromisoformat(d)
            except Exception:
                continue
            kind = str(row.get("kind") or "other").lower()
            out.append(MacroEvent(date=d, name=str(row.get("name") or kind.upper()),
                                  kind=kind if kind in KINDS else "other",
                                  time=(str(row["time"]) if row.get("time") else None)))
        return sorted(out, key=lambda e: (e.date, e.time or ""))

    def events_on(self, date: dt.date | str) -> list[MacroEvent]:
        d = date.isoformat() if isinstance(date, dt.date) else str(date)
        return [e for e in self._events() if e.date == d]

    def is_event_day(self, date: dt.date | str, kinds: tuple[str, ...] | None = None) -> bool:
        evs = self.events_on(date)
        if kinds:
            evs = [e for e in evs if e.kind in kinds]
        return bool(evs)

    def upcoming(self, start: dt.date | str, days: int = 14) -> list[MacroEvent]:
        a = dt.date.fromisoformat(start) if isinstance(start, str) else start
        b = a + dt.timedelta(days=days)
        return [e for e in self._events() if a.isoformat() <= e.date <= b.isoformat()]

    async def refresh(self) -> dict:
        """Placeholder for a fetched source. Returns what a future implementation should
        report so the desk report can show it."""
        return {"source": self.SOURCE, "events": len(self._events()), "fetched": False,
                "note": "manual list in research.macro_events; no remote source wired"}

    def describe(self) -> dict:
        evs = self._events()
        return {"source": self.SOURCE, "events": len(evs), "kinds": sorted({e.kind for e in evs}),
                "next": evs[0].to_dict() if evs else None}


__all__ = ["MacroCalendar", "MacroEvent", "KINDS"]
