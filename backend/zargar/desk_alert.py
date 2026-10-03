"""Desk escalation (2026-10-02, Tips review W1.6 / W3.4): one call that reaches the user wherever they are -
a desk toast (the `technique` topic's `alert`, the same message `PositionManager._alert` publishes), a web
push and a Telegram message. Each channel is best-effort and independent; the caller journals the decision.

The bus alert is marked `pushed` so `PushService._technique_loop` does not send the same push twice."""
from __future__ import annotations

import contextlib
import html
import logging

from . import bus as topics

log = logging.getLogger("zargar.desk_alert")


async def escalate(eng, title: str, text: str, *, tag: str, level: str = "critical", url: str = "/") -> dict:
    """Toast + push + Telegram. Returns which channels accepted the message (for the journal row)."""
    sent = {"toast": False, "push": False, "telegram": False}
    with contextlib.suppress(Exception):
        eng.bus.publish(topics.TECHNIQUE, {"kind": "alert", "level": level, "text": f"{title}: {text}"[:600],
                                           "tag": tag, "pushed": True})
        sent["toast"] = True
    push = getattr(eng, "push", None)
    if push is not None:
        try:
            n = await push.send(title, text[:400], url=url, tag=tag, level=level)
            sent["push"] = bool(n)
        except Exception:
            log.warning("escalation push failed (%s)", tag, exc_info=True)
    tg = getattr(eng, "telegram", None)
    if tg is not None:
        try:
            await tg.send(f"{'⚠' if level == 'critical' else 'ℹ'} <b>{html.escape(title)}</b>\n{html.escape(text[:1500])}")
            sent["telegram"] = True
        except Exception:
            log.warning("escalation telegram failed (%s)", tag, exc_info=True)
    return sent
