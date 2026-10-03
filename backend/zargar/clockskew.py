"""Host clock skew (2026-10-02, Tips review W1.6 / finding D5).

The host clock drifted ~1 s/day behind Discord (-10.5 s by 09-21) while the quote-age guard is 10 s, so every
age check and every latency number was off by the drift. This module MEASURES the skew - it never changes the
system time (enabling Windows time sync is a one-command user step, see docs/OPERATIONS.md) - at engine startup and
daily at `ops.clock_skew_at` (08:00 ET), against:

1. an NTP quorum (`ops.clock_skew_ntp_servers`, the median of `tools/clock_health.measure_ntp`, millisecond-grade)
   when the servers answer and agree, else
2. the HTTP `Date` header of a reliable host (`ops.clock_skew_references`, a HEAD request) - UDP 123 is often
   blocked, HTTPS is not.

Then:

- journal `ClockSkew {skewMs, reference, rttMs, thresholdMs, ok}` on every check;
- escalate a desk alert (toast + push + Telegram, `desk_alert.escalate`) when |skew| > `ops.clock_skew_alert_ms`;
- keep the last reading on `eng.clock_skew` for `/api/health` (`local.clockSkewMs`).

`skewMs` > 0 = the host clock is AHEAD of the reference. The `Date` header has one-second resolution (the server's
clock truncated), so the reference instant is taken as Date + 0.5 s and the local instant as the midpoint of the
request: the estimate is good to about +/-0.5 s plus half the round trip, which the 2 s threshold absorbs.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import logging
import time
from typing import Awaitable, Callable

from . import events as ev

log = logging.getLogger("zargar.clockskew")

DEFAULT_REFERENCES = ("https://www.google.com", "https://www.cloudflare.com")

# fetch(url) -> (local_send_epoch, local_recv_epoch, date_header or None); injectable for tests
Fetch = Callable[[str], Awaitable[tuple[float, float, str | None]]]


async def _http_head(url: str) -> tuple[float, float, str | None]:
    import httpx
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as http:
        t0 = time.time()
        r = await http.head(url, headers={"Cache-Control": "no-cache"})
        t1 = time.time()
    return t0, t1, r.headers.get("date")


def skew_from(t0: float, t1: float, date_header: str) -> tuple[float, float]:
    """Pure: (skew_ms, rtt_ms) from the local send/receive instants and the server's Date header."""
    server = email.utils.parsedate_to_datetime(date_header)
    if server.tzinfo is None:
        server = server.replace(tzinfo=dt.timezone.utc)
    ref = server.timestamp() + 0.5                       # Date truncates to the second
    local = (t0 + t1) / 2.0
    return round((local - ref) * 1000.0, 1), round((t1 - t0) * 1000.0, 1)


async def measure(references=DEFAULT_REFERENCES, *, fetch: Fetch | None = None) -> dict:
    """First reference that answers with a Date header wins. Never raises: {ok:False, error} when none answers."""
    fetch = fetch or _http_head
    errors: list[str] = []
    for url in references or DEFAULT_REFERENCES:
        try:
            t0, t1, date = await fetch(str(url))
        except Exception as exc:                          # noqa: BLE001 - a probe failure is a fact, not a crash
            errors.append(f"{url}: {type(exc).__name__}: {str(exc)[:120]}")
            continue
        if not date:
            errors.append(f"{url}: no Date header")
            continue
        try:
            skew_ms, rtt_ms = skew_from(t0, t1, date)
        except Exception as exc:                          # noqa: BLE001
            errors.append(f"{url}: unparseable Date {date!r}: {exc}")
            continue
        return {"ok": True, "skewMs": skew_ms, "rttMs": rtt_ms, "reference": str(url), "dateHeader": date,
                "at": dt.datetime.now(dt.timezone.utc).isoformat()}
    return {"ok": False, "skewMs": None, "reference": None, "errors": errors,
            "at": dt.datetime.now(dt.timezone.utc).isoformat()}


def from_ntp(q: dict) -> dict | None:
    """Pure: a `measure_ntp` quorum -> a skew reading (None when it is not trusted). NTP's offset is positive when
    the host is BEHIND; `skewMs` is positive when the host is AHEAD - the sign flips."""
    if not q or q.get("offsetMs") is None or not q.get("agreed", False):
        return None
    servers = [r.get("server") for r in (q.get("servers") or [])]
    return {"ok": True, "skewMs": round(-float(q["offsetMs"]), 1),
            "rttMs": round(float(q.get("worstUncertaintyMs") or 0) * 2, 1),
            "reference": f"ntp:{len(servers)} servers (median)", "ntpServers": servers,
            "at": dt.datetime.now(dt.timezone.utc).isoformat()}


async def check(eng, *, fetch: Fetch | None = None, ntp: Callable[[list], dict] | None = None,
                trigger: str = "scheduled") -> dict:
    """Measure, journal `ClockSkew`, store it on the engine and escalate above the threshold."""
    import asyncio
    settings = eng.settings
    refs = settings.get("ops.clock_skew_references", None) or DEFAULT_REFERENCES
    if isinstance(refs, str):
        refs = [r.strip() for r in refs.split(",") if r.strip()]
    threshold = float(settings.get("ops.clock_skew_alert_ms", 2000) or 0)
    m = None
    ntp_servers = list(settings.get("ops.clock_skew_ntp_servers", None) or [])
    ntp_note = None
    if ntp_servers:
        if ntp is None:
            from .tools.clock_health import measure_ntp
            ntp = measure_ntp
        try:
            q = await asyncio.to_thread(ntp, ntp_servers)
            m = from_ntp(q)
            if m is None:
                ntp_note = (q or {}).get("why") or "NTP quorum not trusted"
        except Exception as exc:                          # noqa: BLE001
            ntp_note = f"NTP probe failed: {type(exc).__name__}: {exc}"[:200]
    if m is None:
        m = await measure(refs, fetch=fetch)
        if ntp_note:
            m["ntpNote"] = ntp_note
    m["thresholdMs"] = threshold
    m["trigger"] = trigger
    m["alert"] = bool(m.get("ok") and threshold > 0 and abs(float(m["skewMs"])) > threshold)
    eng.clock_skew = m
    try:
        await eng.journal.append(ev.CLOCK_SKEW, {k: m.get(k) for k in ("ok", "skewMs", "rttMs", "reference",
                                                                       "thresholdMs", "alert", "trigger", "errors",
                                                                       "ntpServers", "ntpNote")
                                                 if m.get(k) is not None},
                                 aggregate_type="system", aggregate_id="clock")
    except Exception:
        log.warning("ClockSkew journal failed", exc_info=True)
    if m["alert"]:
        from .desk_alert import escalate
        ahead = "ahead of" if m["skewMs"] > 0 else "behind"
        text = (f"The host clock is {abs(m['skewMs']) / 1000:.1f} s {ahead} {m['reference']} "
                f"(alert above {threshold / 1000:.1f} s). Quote-age guards and latency numbers are off by this much - "
                "enable Windows time sync (docs/OPERATIONS.md, Host clock). The app never changes the system time.")
        log.warning("clock skew: %s", text)
        try:
            m["sent"] = await escalate(eng, "Host clock skew", text, tag="clock-skew", url="/dashboard")
        except Exception:
            log.warning("clock skew escalation failed", exc_info=True)
    elif m.get("ok"):
        log.info("clock skew %.0f ms vs %s (rtt %.0f ms)", m["skewMs"], m["reference"], m.get("rttMs") or 0)
    else:
        log.warning("clock skew probe failed: %s", "; ".join(m.get("errors") or []))
    return m


def register(eng) -> None:
    """Startup check (background task) + the daily job. Off when `ops.clock_skew_check` is false or the config
    disables the probe (tests)."""
    import asyncio
    if not bool(getattr(eng.config, "clock_skew_probe", True)):
        return
    if not bool(eng.settings.get("ops.clock_skew_check", True)):
        return

    async def _scheduled() -> dict:
        return await check(eng, trigger="scheduled")

    eng.scheduler.register("clock_skew_check", str(eng.settings.get("ops.clock_skew_at", "08:00")), _scheduled,
                           weekdays_only=False)
    eng._tasks.append(asyncio.create_task(check(eng, trigger="startup"), name="clock-skew-startup"))
