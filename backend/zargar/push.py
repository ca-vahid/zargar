"""Web Push for phones (docs/MOBILE-PLAN.md Phase 7).

Subscriptions and the VAPID key pair live in the settings table (single user,
one app) so nothing new needs a migration. Sending happens off the event loop
(pywebpush is synchronous). Dead subscriptions (404/410) are pruned.

What gets pushed (subscribed off the bus, so the armer stays decoupled):
  technique.alert            critical/warning plan alerts (failed exit, loss halt, stale...)
  technique.armed events     fired · position_open · exit_fill · entry_rejected · exit_failed
  proposals (pending)        a proposal waiting for approval
  system.halt                kill switch engaged
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from . import bus as topics

log = logging.getLogger("zargar.push")

try:  # optional dependency — the app runs without push
    from pywebpush import WebPushException, webpush
    from py_vapid import Vapid
    HAVE_PUSH = True
except Exception:  # pragma: no cover
    webpush = None  # type: ignore
    WebPushException = Exception  # type: ignore
    Vapid = None  # type: ignore
    HAVE_PUSH = False

ARMED_EVENTS = {
    "fired": ("⚡ {symbol} fired", "{text}"),
    "position_open": ("● {symbol} position open", "{text}"),
    "exit_fill": ("✓ {symbol} exit filled", "{text}"),
    "entry_rejected": ("✗ {symbol} entry rejected", "{text}"),
    "exit_failed": ("‼ {symbol} exit FAILED", "{text}"),
}


class PushService:
    def __init__(self, engine) -> None:
        self.engine = engine
        self._tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------------ keys
    @property
    def available(self) -> bool:
        return HAVE_PUSH

    def _vapid(self) -> dict:
        s = self.engine.settings
        cur = s.get("mobile.vapid", {}) or {}
        if cur.get("private") and cur.get("public"):
            return cur
        if not HAVE_PUSH:
            return {}
        v = Vapid()
        v.generate_keys()
        import base64
        from cryptography.hazmat.primitives import serialization
        priv = v.private_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        raw = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        pub = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        cur = {"private": priv, "public": pub}
        asyncio.get_event_loop().create_task(s.set("mobile.vapid", cur, journal=False))
        return cur

    def public_key(self) -> str | None:
        return (self._vapid() or {}).get("public")

    # ------------------------------------------------------------ subscriptions
    def subscriptions(self) -> list[dict]:
        subs = self.engine.settings.get("mobile.push_subscriptions", []) or []
        return [x for x in subs if isinstance(x, dict) and x.get("endpoint")]

    async def subscribe(self, sub: dict, label: str = "") -> int:
        subs = [x for x in self.subscriptions() if x.get("endpoint") != sub.get("endpoint")]
        subs.append({**sub, "label": label})
        await self.engine.settings.set("mobile.push_subscriptions", subs, journal=False)
        return len(subs)

    async def unsubscribe(self, endpoint: str) -> int:
        subs = [x for x in self.subscriptions() if x.get("endpoint") != endpoint]
        await self.engine.settings.set("mobile.push_subscriptions", subs, journal=False)
        return len(subs)

    # ------------------------------------------------------------------ sending
    async def send(self, title: str, body: str, *, url: str = "/armed", tag: str | None = None,
                   level: str = "info") -> int:
        subs = self.subscriptions()
        if not subs or not HAVE_PUSH:
            return 0
        keys = self._vapid()
        payload = json.dumps({"title": title, "body": body[:400], "url": url, "tag": tag, "level": level})
        dead: list[str] = []

        def _one(sub: dict) -> bool:
            try:
                webpush(subscription_info={"endpoint": sub["endpoint"], "keys": sub.get("keys") or {}},
                        data=payload, vapid_private_key=keys["private"],
                        vapid_claims={"sub": "mailto:zargar@localhost"}, ttl=600)
                return True
            except WebPushException as exc:  # type: ignore[misc]
                code = getattr(getattr(exc, "response", None), "status_code", None)
                if code in (404, 410):
                    dead.append(sub["endpoint"])
                log.warning("push failed (%s): %s", code, exc)
                return False
            except Exception:
                log.warning("push failed", exc_info=True)
                return False

        loop = asyncio.get_running_loop()
        results = await asyncio.gather(*(loop.run_in_executor(None, _one, s) for s in subs))
        if dead:
            for ep in dead:
                await self.unsubscribe(ep)
        return sum(1 for r in results if r)

    # ------------------------------------------------------------------ bus taps
    async def start(self) -> None:
        if not HAVE_PUSH:
            log.info("pywebpush not installed — web push disabled")
            return
        self._tasks = [
            asyncio.create_task(self._technique_loop(), name="push-technique"),
            asyncio.create_task(self._proposal_loop(), name="push-proposals"),
            asyncio.create_task(self._system_loop(), name="push-system"),
        ]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t
        self._tasks = []

    def _enabled(self, kind: str) -> bool:
        kinds = self.engine.settings.get("mobile.push_kinds", None)
        if not kinds:
            return True
        return kind in kinds

    async def _technique_loop(self) -> None:
        async with self.engine.bus.subscription(topics.TECHNIQUE) as q:
            while True:
                msg: dict[str, Any] = await q.get()
                try:
                    kind = msg.get("kind")
                    if kind == "alert" and self._enabled("alert"):
                        await self.send("⚠ Zargar alert", str(msg.get("text") or ""),
                                        url=f"/armed/{msg.get('runId')}" if msg.get("runId") else "/armed",
                                        tag=f"alert-{msg.get('runId')}", level=str(msg.get("level") or "critical"))
                    elif kind == "armed" and msg.get("event") in ARMED_EVENTS and self._enabled("armed"):
                        ap = msg.get("armed") or {}
                        title, body = ARMED_EVENTS[msg["event"]]
                        await self.send(title.format(symbol=ap.get("symbol", "?")),
                                        body.format(text=ap.get("summary") or msg["event"].replace("_", " ")),
                                        url=f"/armed/{ap.get('runId')}", tag=f"armed-{ap.get('runId')}",
                                        level="critical" if msg["event"] == "exit_failed" else "info")
                except Exception:
                    log.warning("push technique handler failed", exc_info=True)

    async def _proposal_loop(self) -> None:
        async with self.engine.bus.subscription(topics.PROPOSALS) as q:
            while True:
                p = await q.get()
                try:
                    if p.get("status") == "pending" and self._enabled("proposal"):
                        await self.send(f"? Proposal: {p.get('side')} {p.get('qty')} {p.get('symbol')}",
                                        "waiting for your approval", url="/inbox", tag=f"proposal-{p.get('id')}")
                except Exception:
                    log.warning("push proposal handler failed", exc_info=True)

    async def _system_loop(self) -> None:
        async with self.engine.bus.subscription(topics.SYSTEM) as q:
            while True:
                m = await q.get()
                try:
                    if m.get("kind") == "halt" and m.get("engaged") and self._enabled("halt"):
                        await self.send("🛑 Kill switch engaged", str(m.get("reason") or ""), url="/armed",
                                        tag="halt", level="critical")
                except Exception:
                    log.warning("push system handler failed", exc_info=True)


def public_url(settings) -> str:
    """The origin phones reach the app at (Tailscale/HTTPS) — for deep links in
    Telegram messages. Empty = no links."""
    return str(settings.get("mobile.public_url", "") or "").rstrip("/")
