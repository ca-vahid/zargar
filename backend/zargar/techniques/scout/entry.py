"""The preregistered entry-spread rule (PLAN 2.2, user-approved via the desk 2026-10-07) - pure.

A candidate's entry is attempted at 10:00 ET on its entry session. The spread gate (<= 0.5% of mid) is
judged on the LIVE quote at that moment. Wider (or no usable two-sided quote): re-check every 15 minutes
until 11:30 ET; still wider at the 11:30 attempt -> skipped with reason `spread` (`no_quote` when no
usable quote was ever seen). An attempt that only runs after the last slot's grace (the app was down)
is `window_missed` - never a late fill outside the window.

`decide()` is the whole rule; the service only supplies `now` and the quote.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .form4 import ET

ENTER, WAIT, RETRY, SKIP = "enter", "wait", "retry", "skip"


@dataclass(frozen=True)
class EntryRule:
    start: str = "10:00"
    end: str = "11:30"
    step_minutes: int = 15
    max_spread_pct: float = 0.5

    def slots(self) -> list[str]:
        h, m = (int(x) for x in self.start.split(":"))
        eh, em = (int(x) for x in self.end.split(":"))
        out, t, last = [], h * 60 + m, eh * 60 + em
        step = max(1, int(self.step_minutes))
        while t <= last:
            out.append(f"{t // 60:02d}:{t % 60:02d}")
            t += step
        return out


def _minutes(hhmm: str) -> int:
    h, m = (int(x) for x in hhmm.split(":"))
    return h * 60 + m


def spread_pct(bid: float | None, ask: float | None) -> float | None:
    """Quoted spread as % of mid; None when there is no usable two-sided quote."""
    if not bid or not ask or bid <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2.0
    return (ask - bid) / mid * 100.0


def decide(now: dt.datetime, entry_date: str, spread: float | None, rule: EntryRule,
           *, seen_quote: bool = False) -> tuple[str, str]:
    """(action, reason) for ONE attempt at `now` (ET) on a candidate whose entry session is `entry_date`.

    - before the entry session's first slot: WAIT
    - after the entry session (a later date): SKIP window_missed
    - inside the window: ENTER when the spread is <= the gate, else RETRY until the last slot, where it
      becomes SKIP spread (no_quote when no usable quote was ever seen)
    - after the last slot + one step of grace (the job ran late): SKIP window_missed
    """
    now = now.astimezone(ET)
    day = now.date().isoformat()
    if day < entry_date:
        return WAIT, f"entry session {entry_date} not reached"
    if day > entry_date:
        return SKIP, f"window_missed: entry session {entry_date} passed without an attempt in {rule.start}-{rule.end} ET"
    t = now.hour * 60 + now.minute
    first, last = _minutes(rule.start), _minutes(rule.end)
    if t < first:
        return WAIT, f"before the first attempt ({rule.start} ET)"
    if t > last + max(1, rule.step_minutes):
        return SKIP, f"window_missed: no attempt ran in {rule.start}-{rule.end} ET (now {now:%H:%M})"
    is_last = t >= last
    if spread is not None and spread <= rule.max_spread_pct:
        return ENTER, f"spread {spread:.3f}% <= {rule.max_spread_pct:g}% at {now:%H:%M} ET"
    if spread is None:
        why = "no usable two-sided quote"
        if is_last:
            return SKIP, ("spread" if seen_quote else "no_quote") + f": {why} at the last attempt ({rule.end} ET)"
        return RETRY, f"{why} at {now:%H:%M} ET - re-check in {rule.step_minutes} min"
    if is_last:
        return SKIP, f"spread: {spread:.3f}% > {rule.max_spread_pct:g}% at the last attempt ({rule.end} ET)"
    return RETRY, f"spread {spread:.3f}% > {rule.max_spread_pct:g}% at {now:%H:%M} ET - re-check in {rule.step_minutes} min"


def reason_code(reason: str) -> str:
    """The short code at the front of a SKIP reason (spread | no_quote | window_missed)."""
    return reason.split(":", 1)[0].strip()
