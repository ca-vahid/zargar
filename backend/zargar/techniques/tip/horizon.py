"""How long a tip may wait — pure date math, no I/O.

Tips are mostly short-dated options ideas (user, 2026-08-27): "NVDA 180c 9/19"
is dead at its expiry, and nearly dead a couple of days before it (theta).
So the wait-for-the-level window is bounded by THREE things, whichever is
tightest: the source policy's horizon, the tip's own stated horizon, and —
when the tip names an expiry or a DTE hint — the contract's life minus an
entry cutoff. The same bound also caps how long a filled position may be
held (the thesis expires with the contract, even when expressed in shares).
"""
from __future__ import annotations

import datetime as dt


def tip_expiry(expiry: str | None, dte_hint_days: int | None,
               received: dt.date) -> dt.date | None:
    """The date the tip's thesis dies: its stated contract expiry, else the
    received date + the DTE hint ('weeklies' ~5, 'next week' ~10). None when
    the tip named neither — the policy horizon alone bounds it then."""
    if expiry:
        try:
            return dt.date.fromisoformat(expiry)
        except ValueError:
            pass
    if dte_hint_days and dte_hint_days > 0:
        return received + dt.timedelta(days=int(dte_hint_days))
    return None


def sessions_between(start: dt.date, end: dt.date) -> int:
    """Trading sessions (weekdays; holidays not modelled) strictly after
    `start` up to and including `end`. 0 when end <= start."""
    if end <= start:
        return 0
    n = 0
    d = start
    while d < end:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def effective_wait_sessions(*, policy_horizon: int, tip_horizon: int | None,
                            expiry: dt.date | None, today: dt.date,
                            entry_cutoff_dte: int) -> int:
    """Sessions the tip may still WAIT for its level, from `today`.
    0 = too late: don't arm, expire the signal.

    - no expiry known: min(policy horizon, tip's own stated horizon)
    - expiry known: additionally capped at `entry_cutoff_dte` calendar days
      BEFORE expiry — entering a nearly-expired contract is buying pure theta.
    """
    n = int(policy_horizon)
    if tip_horizon and tip_horizon > 0:
        n = min(n, int(tip_horizon))
    if expiry is not None:
        last_entry_day = expiry - dt.timedelta(days=max(0, int(entry_cutoff_dte)))
        n = min(n, sessions_between(today, last_entry_day))
    return max(0, n)


def hold_sessions_cap(*, expiry: dt.date | None, today: dt.date,
                      fallback: int) -> int:
    """How many sessions a FILLED position may be held: to the thesis expiry
    (the contract's life) when known, else the fallback horizon. At least 1 —
    a position that exists gets at least the session it was opened in."""
    if expiry is None:
        return max(1, int(fallback))
    return max(1, sessions_between(today, expiry))
