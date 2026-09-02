"""The LOTTO lane (user decision 2026-09-01): 0–3 DTE option tips.

Two of the desk's most active sources (MuggZone, tt) trade almost nothing but
1–3 DTE contracts, and the policy killed every one before the analyst even
judged it (entry cutoff, "never 0DTE", the never-hold-to-expiry floor) — on
the first live day their skipped lottos printed +18 %, +26 %, +31 % on their
own boards. So short-dated tips get their own small lane instead of a wall:

- identified at intake from the STATED contract (`is_lotto`), never inferred;
- tip-time ONLY: the stated contract verbatim (no expiry substitution), sized
  from `techniques.tip.lotto_budget`, entry_mode "now" — a lotto never waits
  for a level (a rule the analyst wrote itself on 2026-09-01);
- mandatory exit: flattened on expiry day at `techniques.tip.lotto_flatten_et`
  (the platform's "never hold to expiry" invariant, kept — restated as never
  hold THROUGH the close of expiry day); no new lotto entries after that time
  on a 0-DTE contract;
- everything else applies unchanged: analyst verdict gates, earned/explicit
  auto, RiskGate, the per-tip contract cap.
"""
from __future__ import annotations

import datetime as dt

from .horizon import tip_expiry


def lotto_max_dte(settings) -> int:
    if not bool(settings.get("techniques.tip.lotto_enabled", True)):
        return -1
    return int(settings.get("techniques.tip.lotto_max_dte", 3))


def is_lotto(signal_row, settings, today: dt.date | None = None) -> bool:
    """A stated option contract expiring within the lotto window."""
    inst = str(getattr(signal_row, "instrument", "") or "")
    if inst not in ("call", "put"):
        return False
    today = today or dt.date.today()
    created = getattr(signal_row, "created_at", None)
    expiry = tip_expiry(getattr(signal_row, "expiry", None),
                        getattr(signal_row, "dte_hint_days", None),
                        created.date() if created else today)
    if expiry is None:
        return False
    return 0 <= (expiry - today).days <= lotto_max_dte(settings)


def lotto_budget(settings, policy_budget: float) -> float:
    return min(float(settings.get("techniques.tip.lotto_budget", 1500.0)), float(policy_budget) * 3)


def flatten_time_et(settings) -> tuple[int, int]:
    raw = str(settings.get("techniques.tip.lotto_flatten_et", "15:45"))
    try:
        hh, mm = (int(x) for x in raw.split(":"))
        return hh, mm
    except ValueError:
        return 15, 45


def past_flatten_time(settings, now_et: dt.datetime) -> bool:
    hh, mm = flatten_time_et(settings)
    return now_et.hour * 60 + now_et.minute >= hh * 60 + mm
