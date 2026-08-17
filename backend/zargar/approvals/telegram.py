"""Telegram bot: proposal notifications with inline Approve / Half / Reject buttons,
plus kill-switch commands (/halt, /resume, /status).

Implemented with plain httpx long-polling — no framework dependency. Disabled unless
ZARGAR_TELEGRAM_BOT_TOKEN + ZARGAR_TELEGRAM_CHAT_ID are configured and the
telegram.enabled setting is on.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging

import httpx

from .. import bus as topics

log = logging.getLogger("zargar.telegram")


def format_proposal_message(p: dict) -> str:
    lines = [
        f"📈 <b>Trade proposal</b> — {p['symbol']}",
        f"{p['side']} {p['qty']:g} @ {p['orderType']}"
        + (f" {p['limitPrice']}" if p.get("limitPrice") else ""),
    ]
    ctx = p.get("context") or {}
    if ctx.get("sourceName"):
        lines.append(f"Source: {ctx['sourceName']} ({ctx.get('confidence', '?')})")
    prices = ctx.get("signalPrices") or {}
    parts = [f"{k}: {v}" for k, v in
             (("entry", prices.get("entry")), ("target", prices.get("target")),
              ("stop", prices.get("stop"))) if v]
    if parts:
        lines.append(" · ".join(parts))
    if p.get("rationale"):
        lines.append(f"<i>{p['rationale'][:300]}</i>")
    verification = (ctx.get("verification") or {}).get("checks", [])
    failed = [c["name"] for c in verification if not c.get("passed")]
    lines.append("✅ all checks passed" if not failed else f"⚠️ failed: {', '.join(failed)}")
    if p.get("expiresAt"):
        lines.append(f"Expires: {p['expiresAt'][11:19]} UTC")
    return "\n".join(lines)


def proposal_keyboard(proposal_id: str) -> dict:
    return {"inline_keyboard": [[
        {"text": "✅ Approve", "callback_data": f"approve:{proposal_id}"},
        {"text": "½ Half size", "callback_data": f"half:{proposal_id}"},
        {"text": "❌ Reject", "callback_data": f"reject:{proposal_id}"},
    ]]}


def parse_callback(data: str) -> tuple[str, str] | None:
    if ":" not in data:
        return None
    action, _, pid = data.partition(":")
    if action not in ("approve", "half", "reject") or not pid:
        return None
    return action, pid


class TelegramBot:
    def __init__(self, engine, token: str, chat_id: str) -> None:
        self.engine = engine
        self._token = token
        self._chat_id = str(chat_id)
        self._base = f"https://api.telegram.org/bot{token}"
        self._client: httpx.AsyncClient | None = None
        self._tasks: list[asyncio.Task] = []
        self._offset = 0

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=65)
        self._tasks = [
            asyncio.create_task(self._poll_loop(), name="telegram-poll"),
            asyncio.create_task(self._proposal_notifier(), name="telegram-proposals"),
        ]
        log.info("telegram bot started")

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        self._tasks = []
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------- outbound
    async def send(self, text: str, reply_markup: dict | None = None) -> None:
        assert self._client is not None
        payload = {"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            await self._client.post(f"{self._base}/sendMessage", json=payload)
        except httpx.HTTPError:
            log.warning("telegram send failed", exc_info=True)

    async def _proposal_notifier(self) -> None:
        async with self.engine.bus.subscription(topics.PROPOSALS) as q:
            while True:
                p = await q.get()
                if p.get("status") == "pending":
                    await self.send(format_proposal_message(p), proposal_keyboard(p["id"]))
                elif p.get("status") in ("executed", "failed", "expired"):
                    await self.send(f"Proposal {p['symbol']} → <b>{p['status']}</b>")

    # ------------------------------------------------------------- inbound
    async def _poll_loop(self) -> None:
        assert self._client is not None
        while True:
            try:
                resp = await self._client.get(
                    f"{self._base}/getUpdates",
                    params={"timeout": 50, "offset": self._offset + 1})
                for update in resp.json().get("result", []):
                    self._offset = max(self._offset, update["update_id"])
                    await self._handle_update(update)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("telegram poll error", exc_info=True)
                await asyncio.sleep(5)

    async def _handle_update(self, update: dict) -> None:
        if "callback_query" in update:
            cq = update["callback_query"]
            if str(cq.get("message", {}).get("chat", {}).get("id")) != self._chat_id:
                return  # only the configured chat may act
            parsed = parse_callback(cq.get("data", ""))
            if parsed:
                action, pid = parsed
                await self._decide(action, pid)
            with contextlib.suppress(httpx.HTTPError):
                await self._client.post(f"{self._base}/answerCallbackQuery",
                                        json={"callback_query_id": cq["id"]})
            return
        msg = update.get("message") or {}
        if str(msg.get("chat", {}).get("id")) != self._chat_id:
            return
        text = (msg.get("text") or "").strip()
        if text.startswith("/halt"):
            reason = text.removeprefix("/halt").strip() or "telegram halt"
            await self.engine.engage_halt(reason, source="telegram")
            await self.send("🛑 <b>Kill switch engaged.</b> All order submission blocked.")
        elif text.startswith("/resume"):
            await self.engine.release_halt(source="telegram")
            await self.send("▶️ Kill switch released.")
        elif text.startswith("/status"):
            await self.send(await self._status_text())

    async def _decide(self, action: str, proposal_id: str) -> None:
        try:
            if action == "reject":
                await self.engine.proposals.reject(proposal_id, via="telegram")
                await self.send("❌ Rejected.")
            else:
                result = await self.engine.proposals.approve(
                    proposal_id, via="telegram", half=(action == "half"))
                order = result["order"]
                await self.send(
                    f"✅ Approved{' (half size)' if action == 'half' else ''} — "
                    f"order {order.get('status', '?')}")
        except ValueError as exc:
            await self.send(f"⚠️ {exc}")

    async def _status_text(self) -> str:
        eng = self.engine
        lines = ["<b>Zargar status</b>"]
        halt = eng.halt.to_dict()
        lines.append("🛑 HALTED: " + halt["reason"] if halt["engaged"] else "🟢 trading enabled")
        lines.append(f"mode: {eng.settings.get('trading.mode')}")
        for p in eng.positions.portfolios():
            eq = await eng.positions.equity(p["id"])
            lines.append(f"{p['name']}: ${eq:,.2f}")
        pending = await eng.proposals.list_pending() if eng.proposals else []
        lines.append(f"pending proposals: {len(pending)}")
        return "\n".join(lines)


async def attach_telegram(engine) -> None:
    config = engine.config
    if not (config.telegram_bot_token and config.telegram_chat_id
            and engine.settings.get("telegram.enabled")):
        return
    if getattr(engine, "telegram", None):
        return
    engine.telegram = TelegramBot(engine, config.telegram_bot_token, config.telegram_chat_id)
    await engine.telegram.start()
