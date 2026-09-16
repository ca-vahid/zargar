"""TMR-01 (2026-09-16): VERIFIED event context for the Tips desk - advisory only.

The shared manual macro calendar (`research.macro_events`, `research/macro_calendar.py`,
Team2's placeholder) is a list of dates with no provenance and, on 2026-09-16, empty. A
Tips decision needs to know three things about a scheduled macro event: that it is
REAL (an official source, verified at a known time), WHEN it is (exact ET/UTC, time until
it), and whether the calendar even COVERS the date (unknown coverage is not "no event").

This module keeps a Tips-scoped, provenance-carrying list (`techniques.tip.verified_events`)
beside the shared list and answers `event_context(now, as_of=...)`:

- entries carry `verifiedAt` (when a person/desk read the official page) and `url`; a
  historical replay asks with `as_of` and only sees entries verified BEFORE that instant
  (a fact first learned later never reaches an earlier decision);
- `coverageThrough` on the Tips list says how far the official calendar was checked; a
  date inside coverage with no entry is "no scheduled event known", a date beyond it is
  "unknown coverage";
- the shared list is read too (source "shared-manual", no verification time) and reported
  separately - never merged into a verified claim.

Nothing here places, blocks, sizes or times an order. It labels.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
CONTEXT_VERSION = "event-context-v1"

# The desk's own verified entries (DEFAULT; overridable via settings). Verified 2026-09-15
# ~23:35 ET against the Federal Reserve calendar page: two-day meeting September 15-16,
# statement 2:00 p.m. ET on the 16th, press conference 2:30 p.m. ET.
DEFAULT_VERIFIED_EVENTS = {
    "coverageThrough": "2026-09-18",
    "events": [
        {"date": "2026-09-16", "time": "14:00", "kind": "fomc", "name": "FOMC statement",
         "url": "https://www.federalreserve.gov/newsevents/2026-september.htm",
         "verifiedAt": "2026-09-16T03:35:00+00:00", "verifiedBy": "tips-desk"},
        {"date": "2026-09-16", "time": "14:30", "kind": "fomc", "name": "FOMC press conference",
         "url": "https://www.federalreserve.gov/newsevents/2026-september.htm",
         "verifiedAt": "2026-09-16T03:35:00+00:00", "verifiedBy": "tips-desk"},
    ],
}


def _parse_ts(x) -> dt.datetime | None:
    if x is None:
        return None
    if isinstance(x, dt.datetime):
        return x if x.tzinfo else x.replace(tzinfo=dt.timezone.utc)
    try:
        t = dt.datetime.fromisoformat(str(x))
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def event_instant(e: dict) -> dt.datetime | None:
    """The event's instant in ET from its date + HH:MM (ET); None without a time."""
    try:
        d = dt.date.fromisoformat(str(e.get("date")))
    except Exception:
        return None
    t = e.get("time")
    if not t:
        return None
    hh, mm = (int(x) for x in str(t).split(":")[:2])
    return dt.datetime.combine(d, dt.time(hh, mm), tzinfo=ET)


def _fmt_delta(seconds: float) -> str:
    s = int(abs(seconds))
    h, rem = divmod(s, 3600)
    m = rem // 60
    sign = "-" if seconds >= 0 else "+"
    return f"T{sign}{h}h{m:02d}m" if h else f"T{sign}{m}m"


def _describe(e: dict, now: dt.datetime) -> dict:
    inst = event_instant(e)
    out = {"date": e.get("date"), "time": e.get("time"), "kind": e.get("kind"), "name": e.get("name"),
           "url": e.get("url"), "verifiedAt": e.get("verifiedAt"), "verifiedBy": e.get("verifiedBy"),
           "source": e.get("source") or "tips-verified",
           "et": inst.isoformat() if inst else None,
           "utc": inst.astimezone(dt.timezone.utc).isoformat() if inst else None}
    if inst is not None:
        secs = (inst - now).total_seconds()
        out["secondsUntil"] = round(secs)
        out["phase"] = "before" if secs > 0 else "after"
        out["timeUntil"] = _fmt_delta(secs)
    else:
        out["secondsUntil"] = None
        out["phase"] = "unknown-time"
        out["timeUntil"] = None
    return out


def event_context(*, now: dt.datetime, verified: dict | None, shared: list[dict] | None = None,
                  as_of: dt.datetime | None = None, session: str | None = None) -> dict:
    """The label for a decision taken at `now` (aware datetime). `verified` is the
    Tips list ({coverageThrough, events}); `shared` the research.macro_events rows.
    `as_of` (default `now`) is the knowledge cut: entries verified after it are
    invisible, as are entries with no verification time."""
    now = now if now.tzinfo else now.replace(tzinfo=dt.timezone.utc)
    cut = as_of if as_of is not None else now
    cut = cut if cut.tzinfo else cut.replace(tzinfo=dt.timezone.utc)
    sess = session or now.astimezone(ET).date().isoformat()
    verified = verified or {}
    cov = verified.get("coverageThrough")
    covered = bool(cov) and sess <= str(cov)
    visible = []
    hidden = 0
    for e in verified.get("events") or []:
        vt = _parse_ts(e.get("verifiedAt"))
        if vt is None or vt > cut:
            hidden += 1
            continue
        if str(e.get("date")) == sess:
            visible.append(_describe(e, now))
    shared_rows = [{"date": e.get("date"), "time": e.get("time"), "kind": e.get("kind"), "name": e.get("name"),
                    "source": "shared-manual", "verifiedAt": None} for e in (shared or []) if str(e.get("date")) == sess]
    if visible:
        coverage = "verified"
        status = "event-day"
    elif covered:
        coverage = "verified"
        status = "no-scheduled-event"
    else:
        coverage = "unknown"
        status = "unknown"
    nxt = next((v for v in sorted(visible, key=lambda v: v.get("secondsUntil") if v.get("secondsUntil") is not None else 1e12)
                if v.get("phase") == "before"), None)
    label = (", ".join(f"{v['name']} {v['date']} {v['time']} ET ({v['timeUntil']})" for v in visible)
             if visible else ("no scheduled macro event on the verified calendar" if covered
                              else "macro calendar coverage UNKNOWN for this date - not 'no event'"))
    return {"version": CONTEXT_VERSION, "session": sess, "asOf": now.isoformat(), "knowledgeCut": cut.isoformat(),
            "coverage": coverage, "coverageThrough": cov, "status": status, "events": visible,
            "nextEvent": nxt, "hiddenByKnowledgeCut": hidden, "sharedCalendar": shared_rows,
            "label": label, "advisory": "label only - places, blocks, sizes or times no order"}


def header_line(ctx: dict) -> str:
    """One line for the analyst header / desk report."""
    if ctx.get("status") == "event-day":
        parts = []
        for v in ctx.get("events") or []:
            parts.append(f"{v['name']} {v['time']} ET ({v['phase']}, {v['timeUntil']})")
        src = next((v.get("url") for v in ctx.get("events") or [] if v.get("url")), None)
        vat = next((v.get("verifiedAt") for v in ctx.get("events") or [] if v.get("verifiedAt")), None)
        return (f"EVENT CONTEXT ({ctx['session']}): " + "; ".join(parts)
                + (f" - official calendar {src}" if src else "") + (f", verified {vat}" if vat else "")
                + ". Awareness only: keep exact quote/decision times; no automatic no-trade rule.")
    if ctx.get("status") == "no-scheduled-event":
        return f"EVENT CONTEXT ({ctx['session']}): no scheduled macro event on the verified calendar (checked through {ctx.get('coverageThrough')})."
    return f"EVENT CONTEXT ({ctx['session']}): macro calendar coverage UNKNOWN for this date - treat as unverified, not as 'no event'."


def load_verified(settings) -> dict:
    try:
        v = settings.get("techniques.tip.verified_events", None)
    except Exception:
        v = None
    if isinstance(v, dict) and v.get("events") is not None:
        return v
    return DEFAULT_VERIFIED_EVENTS


def load_shared(settings) -> list[dict]:
    try:
        rows = settings.get("research.macro_events", []) or []
    except Exception:
        rows = []
    return [r for r in rows if isinstance(r, dict)]


def context_for(eng, *, now: dt.datetime | None = None, as_of: dt.datetime | None = None,
                session: str | None = None) -> dict:
    """Engine convenience: the label from the live settings."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return event_context(now=now, verified=load_verified(eng.settings), shared=load_shared(eng.settings),
                         as_of=as_of, session=session)
