"""Intake liveness (EOD-01, 2026-09-14): is the Discord pipe delivering, not
merely "is the app healthy"? Combines the gateway's own status file
(`gateway_status.json`, written every 30 s next to its cursors) with the
mirror's watermarks per watched channel. A quiet channel and a stuck pipe
look the same in the mirror alone; the gateway's frame clock separates them.
`monitor_loop` journals `TipIntakeStalled` once per stall (and the recovery)
and pushes a desk alert, RTH-weighted: only 04:00–20:00 ET on trading days."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from pathlib import Path

log = logging.getLogger("zargar.tip.intake_liveness")

STATUS_FILE = "gateway_status.json"
STALE_STATUS_S = 120        # the gateway writes every 30 s; 2 min = the process is gone or hung
STALE_FRAME_S = 240         # no frame for 4 min on a "connected" socket = stuck pipe


def _parse(ts: str | None) -> dt.datetime | None:
    if not ts:
        return None
    try:
        t = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def read_status(base: Path | None = None) -> dict | None:
    p = (base or Path.cwd()) / STATUS_FILE
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


async def liveness(eng, *, base: Path | None = None, now: dt.datetime | None = None) -> dict:
    """The liveness verdict: {ok, state, reasons, gateway, channels, checkedAt}."""
    now = now or dt.datetime.now(dt.timezone.utc)
    st = read_status(base)
    reasons: list[str] = []
    warnings: list[str] = []        # history worth showing, never a CURRENT stall verdict
    gw: dict = {}
    if st is None:
        reasons.append("no gateway status file — the gateway is not running from this checkout or has never written one")
        state = "unknown"
    else:
        written = _parse(st.get("at"))
        age = (now - written).total_seconds() if written else None
        frame = _parse(st.get("lastFrameAt"))
        frame_age = (now - frame).total_seconds() if frame else None
        gw = {"pid": st.get("pid"), "state": st.get("state"), "statusAgeS": round(age, 1) if age is not None else None,
              "frameAgeS": round(frame_age, 1) if frame_age is not None else None,
              "connectedAt": st.get("connectedAt"), "lastMessageAt": st.get("lastMessageAt"),
              "reconnects": st.get("reconnects"), "idleReconnects": st.get("idleReconnects"),
              "recovering": st.get("recovering"), "ledger": st.get("ledger"), "watched": st.get("watched")}
        if age is None or age > STALE_STATUS_S:
            reasons.append(f"gateway status file is {age:.0f}s old — the gateway process is hung or gone" if age else
                           "gateway status file has no timestamp")
        if st.get("state") not in ("connected",):
            reasons.append(f"gateway state is {st.get('state')!r}: {st.get('note') or ''}".strip())
        elif frame_age is not None and frame_age > STALE_FRAME_S:
            reasons.append(f"connected but no frame from Discord for {frame_age:.0f}s — stuck pipe")
        led = st.get("ledger") or {}
        if led.get("pending"):
            reasons.append(f"{led['pending']} envelope(s) pending delivery to the app")
        state = "stalled" if reasons else "live"
    # mirror watermarks per watched tips channel (last received vs last posted)
    channels: list[dict] = []
    try:
        from sqlalchemy import func, select
        from ...models import DiscordMessage
        watch = list(eng.settings.get("techniques.tip.discord.watch") or [])
        ids = [str(w.get("id") or w.get("channelId") or "") for w in watch if isinstance(w, dict)]
        async with eng.sf() as session:
            rows = (await session.execute(
                select(DiscordMessage.channel_id, DiscordMessage.source_name,
                       func.max(DiscordMessage.posted_at), func.max(DiscordMessage.received_at),
                       func.max(DiscordMessage.received_at - DiscordMessage.posted_at))
                .where(DiscordMessage.received_at > now - dt.timedelta(hours=24))
                .group_by(DiscordMessage.channel_id, DiscordMessage.source_name))).all()
        for cid, source, posted, received, worst in rows:
            lag = (received - posted).total_seconds() if received and posted else None
            channels.append({"channelId": str(cid), "source": source, "watched": str(cid) in ids,
                             "lastPostedAt": posted.isoformat() if posted else None,
                             "lastReceivedAt": received.isoformat() if received else None,
                             "lastLagS": round(lag, 1) if lag is not None else None,
                             "worstLag24hS": round(worst.total_seconds(), 1) if worst else None})
        late = [c for c in channels if c["watched"] and (c["worstLag24hS"] or 0) > 900]
        if late:
            # a past delay is a fact to show, not evidence that the pipe is stuck NOW
            # (the day after a 4 h gap would otherwise read "stalled" until the
            # window rolled off and journal a false TipIntakeStalled at 04:00 ET)
            warnings.append(f"{len(late)} watched channel(s) delivered a message more than 15 min after it was posted in the last 24 h")
    except Exception as exc:
        reasons.append(f"mirror watermarks unavailable: {exc}")
    ok = not reasons
    return {"ok": ok, "state": ("live" if ok else (state if st is None else "stalled")),
            "reasons": reasons, "warnings": warnings, "gateway": gw, "channels": channels,
            "checkedAt": now.isoformat()}


def _in_window(now: dt.datetime) -> bool:
    from zoneinfo import ZoneInfo
    from ...marketstructure.market_calendar import is_trading_day
    t = now.astimezone(ZoneInfo("America/New_York"))
    return is_trading_day(t.date()) and 4 * 60 <= t.hour * 60 + t.minute < 20 * 60


async def monitor_loop(eng, *, interval_s: float = 120.0) -> None:
    """Journal `TipIntakeStalled` when the pipe stalls inside the intake window
    (once per stall, with the reasons) and `TipIntakeRecovered` when it clears;
    push a desk alert through the engine's alert path when available."""
    from ... import events as ev
    stalled = False
    await asyncio.sleep(60)
    while True:
        try:
            now = dt.datetime.now(dt.timezone.utc)
            if _in_window(now):
                v = await liveness(eng, now=now)
                if not v["ok"] and not stalled:
                    stalled = True
                    await eng.journal.append(getattr(ev, "TIP_INTAKE_STALLED", "TipIntakeStalled"),
                                             {"reasons": v["reasons"], "gateway": v["gateway"]},
                                             aggregate_type="technique", aggregate_id="tip")
                    log.warning("tips intake STALLED: %s", "; ".join(v["reasons"]))
                    alert = getattr(eng, "alert", None)
                    if callable(alert):
                        try:
                            await alert("Tips intake stalled", "; ".join(v["reasons"])[:400])
                        except Exception:
                            pass
                elif v["ok"] and stalled:
                    stalled = False
                    await eng.journal.append(getattr(ev, "TIP_INTAKE_RECOVERED", "TipIntakeRecovered"),
                                             {"gateway": v["gateway"]}, aggregate_type="technique", aggregate_id="tip")
                    log.info("tips intake recovered")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("intake liveness check failed")
        await asyncio.sleep(interval_s)
