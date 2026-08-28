"""EXPERIMENTAL Discord gateway DM listener (user token) — POC intake tap.

⚠️  NOT ToS-sanctioned. Automating a *user* account (a "self-bot") violates
Discord's Terms; the risk is to THIS account (Discord may ban it if self-bot
activity is detected). The user opted into this experiment knowingly, on their
own laptop, for their own DMs from rooms they joined. Boundary that still
holds: this is READ-ONLY — it opens a gateway socket, sends the mandatory
IDENTIFY + heartbeats, and listens. It never sends a message, reaction, typing
event, or any other write as you. Auto-EXECUTION of alerts stays gated in the
pipeline (RiskGate never-list unchanged). See docs/techniques/tip/INTAKE-PLAN.md.

Why a bare socket (not discord.py-self / discum): minimal footprint. A full
self-bot library polls many REST endpoints (guild sync, member chunks, read
states) that are exactly what detection watches for. This sends the two frames
the protocol requires and otherwise only receives.

Token: set ZARGAR_DISCORD_TOKEN (your user token). NEVER commit it, never log
it. It is your account password-equivalent. Get it from the Discord web client:
DevTools > Network > any request > Request Headers > `authorization`.

Usage (from backend/):
  # learn the shape first — dump every DM to JSONL, ingest nothing:
  ZARGAR_DISCORD_TOKEN=... .venv/Scripts/python -m zargar.tools.discord_gateway --dump
  # then ingest DMs (optionally only from a bot/author/channel):
  ZARGAR_DISCORD_TOKEN=... .venv/Scripts/python -m zargar.tools.discord_gateway \
      --from-bots-only --ingest
  ZARGAR_SESSION=$(python -m zargar.tools.mint_session)   # if the app has auth on
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import random
import sys
import time
from pathlib import Path

GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
API_DEFAULT = "http://127.0.0.1:8420"

OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11


def _identify(token: str) -> dict:
    # user-account IDENTIFY: token + client properties, NO intents (intents are
    # bot-only). Properties mimic a desktop web client.
    return {"op": OP_IDENTIFY, "d": {
        "token": token,
        "capabilities": 16381,
        "properties": {
            "os": "Windows", "browser": "Chrome", "device": "",
            "system_locale": "en-US",
            "browser_user_agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/125.0.0.0 Safari/537.36"),
            "browser_version": "125.0.0.0", "os_version": "10",
            "referrer": "", "referring_domain": "",
            "release_channel": "stable", "client_build_number": 300000,
        },
        "presence": {"status": "online", "since": 0, "activities": [], "afk": False},
        "compress": False,
    }}


IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
MAX_IMAGE_BYTES = 8 * 1024 * 1024      # the ingest endpoint decodes this inline


def collect_images(msg: dict) -> list[str]:
    """Image URLs on a message: real attachments first, then embed images.

    Alert rooms often post a CHART with little or no text (user, 2026-08-28) —
    those must reach the vision transcription path, not ingest as empty text."""
    urls: list[str] = []
    for att in msg.get("attachments") or []:
        ct = str(att.get("content_type") or "")
        name = str(att.get("filename") or "").lower()
        if ct.startswith("image/") or name.endswith(IMAGE_EXT):
            u = att.get("url") or att.get("proxy_url")
            if u:
                urls.append(str(u))
    for e in msg.get("embeds") or []:
        for key in ("image", "thumbnail"):
            u = (e.get(key) or {}).get("url") or (e.get(key) or {}).get("proxy_url")
            if u:
                urls.append(str(u))
    seen, out = set(), []
    for u in urls:                      # dedupe, keep order
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


async def fetch_image_data_url(http, url: str) -> str | None:
    """Discord CDN URL -> data: URL for /api/ingest/manual. CDN links are
    signed but public; no Authorization header is sent (and none is needed)."""
    import base64
    try:
        r = await http.get(url, timeout=30)
        if r.status_code != 200:
            print(f"    ! image fetch {r.status_code} for {url[:70]}")
            return None
        blob = r.content
        if len(blob) > MAX_IMAGE_BYTES:
            print(f"    ! image too large ({len(blob) // 1024}kB) — skipped")
            return None
        # media type from the response; the app re-sniffs the bytes anyway
        ct = (r.headers.get("content-type") or "image/png").split(";")[0].strip()
        if not ct.startswith("image/"):
            ct = "image/png"
        return f"data:{ct};base64,{base64.b64encode(blob).decode('ascii')}"
    except Exception as exc:
        print(f"    ! image fetch failed: {exc}")
        return None


def flatten_message(msg: dict) -> str:
    """A DM message → plain text the extractor can read: content plus every
    embed's title/description/fields/footer (alert bots put the trade in an
    embed, not the content)."""
    parts: list[str] = []
    if msg.get("content"):
        parts.append(str(msg["content"]))
    for e in msg.get("embeds") or []:
        if e.get("author", {}).get("name"):
            parts.append(str(e["author"]["name"]))
        if e.get("title"):
            parts.append(str(e["title"]))
        if e.get("description"):
            parts.append(str(e["description"]))
        for f in e.get("fields") or []:
            nm, val = f.get("name", ""), f.get("value", "")
            parts.append(f"{nm}: {val}".strip(": ").strip())
        if e.get("footer", {}).get("text"):
            parts.append(str(e["footer"]["text"]))
    return "\n".join(p for p in parts if p.strip())


def describe_author(msg: dict) -> str:
    a = msg.get("author") or {}
    name = a.get("global_name") or a.get("username") or "unknown"
    return f"{name}{' [bot]' if a.get('bot') else ''}"


class Gateway:
    def __init__(self, token: str, api: str, session_token: str, log_path: Path,
                 *, ingest: bool, dump: bool, bots_only: bool,
                 author_id: str, channel_id: str, include_self: bool = False,
                 status_minutes: float = 15.0) -> None:
        self.token = token
        self.api = api
        self.session_token = session_token
        self.log_path = log_path
        self.ingest = ingest
        self.dump = dump
        self.bots_only = bots_only
        self.author_id = author_id
        self.channel_id = channel_id
        self.include_self = include_self
        self.status_minutes = status_minutes
        self.user_id = ""
        self.seen_count = 0
        self._seq: int | None = None
        self._hb_interval = 41.25
        self._acked = True
        self._started = time.time()

    async def run(self) -> None:
        import websockets
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(GATEWAY, max_size=8 * 1024 * 1024) as ws:
                    await self._session(ws)
                backoff = 1.0
            except Exception as exc:
                print(f"[gateway] disconnected: {exc}; reconnecting in {backoff:.0f}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _session(self, ws) -> None:
        import httpx
        hello = json.loads(await ws.recv())
        if hello.get("op") != OP_HELLO:
            raise RuntimeError(f"expected HELLO, got op {hello.get('op')}")
        self._hb_interval = hello["d"]["heartbeat_interval"] / 1000.0
        self._acked = True
        hb = asyncio.create_task(self._heartbeat(ws))
        status = asyncio.create_task(self._status_loop())
        await ws.send(json.dumps(_identify(self.token)))
        print(f"[gateway] connected; heartbeat every {self._hb_interval:.1f}s; "
              f"{'DUMP only' if not self.ingest else 'ingesting to ' + self.api}")
        headers = {"Authorization": f"Bearer {self.session_token}"} if self.session_token else {}
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                async for raw in ws:
                    await self._on_frame(json.loads(raw), http, headers)
        finally:
            hb.cancel()
            status.cancel()

    async def _status_loop(self) -> None:
        """Periodic proof-of-life so a quiet window is distinguishable from a
        dead one ('is it working?' — user, 2026-08-28)."""
        if self.status_minutes <= 0:
            return
        while True:
            await asyncio.sleep(self.status_minutes * 60)
            mins = (time.time() - self._started) / 60
            print(f"[{dt.datetime.now():%H:%M:%S}] listening ({mins:.0f} min up, "
                  f"{self.seen_count} matching DM(s) so far)")

    async def _heartbeat(self, ws) -> None:
        # jittered first beat per the docs, then every interval; drop the link
        # if a beat goes un-ACKed (zombied connection)
        await asyncio.sleep(self._hb_interval * random.random())
        while True:
            if not self._acked:
                print("[gateway] heartbeat not ACKed — forcing reconnect")
                await ws.close(code=4000)
                return
            self._acked = False
            await ws.send(json.dumps({"op": OP_HEARTBEAT, "d": self._seq}))
            await asyncio.sleep(self._hb_interval)

    async def _on_frame(self, data: dict, http, headers) -> None:
        op = data.get("op")
        if data.get("s") is not None:
            self._seq = data["s"]
        if op == OP_HEARTBEAT_ACK:
            self._acked = True
            return
        if op == OP_HEARTBEAT:
            self._acked = True  # server asked us to beat now; loop will
            return
        if op in (OP_RECONNECT, OP_INVALID_SESSION):
            raise RuntimeError(f"server asked to reconnect (op {op})")
        if op != OP_DISPATCH:
            return
        t = data.get("t")
        if t == "READY":
            u = (data["d"].get("user") or {})
            self.user_id = str(u.get("id") or "")
            print(f"[gateway] READY as {u.get('username')} "
                  f"({len(data['d'].get('private_channels') or [])} DM channels) — "
                  f"{'bot DMs only' if self.bots_only else 'all DMs'}"
                  f"{'; self-DMs included (test mode)' if self.include_self else ''}")
            print("[gateway] listening. Send yourself a DM (with --include-self) "
                  "or wait for an alert.")
            return
        if t != "MESSAGE_CREATE":
            return
        await self._on_message(data["d"], http, headers)

    async def _on_message(self, msg: dict, http, headers) -> None:
        is_dm = msg.get("guild_id") is None          # DMs carry no guild
        author = msg.get("author") or {}
        is_self = self.user_id and str(author.get("id")) == self.user_id
        # filters
        if self.channel_id and str(msg.get("channel_id")) != self.channel_id:
            return
        if self.author_id and str(author.get("id")) != self.author_id:
            return
        if self.bots_only and not author.get("bot"):
            # your own DMs pass when --include-self: that is the self-test path
            # (DM yourself an alert and watch it flow end to end)
            if not (self.include_self and is_self and is_dm):
                return
        if not self.channel_id and not is_dm:
            # default scope is DMs only (that is the sanctioned-ish alert path);
            # a channel filter opts into one specific channel deliberately
            return
        text = flatten_message(msg)
        images = collect_images(msg)
        self.seen_count += 1
        rec = {"at": dt.datetime.now(dt.timezone.utc).isoformat(),
               "channelId": msg.get("channel_id"), "isDM": is_dm,
               "author": describe_author(msg), "authorId": author.get("id"),
               "text": text, "images": images, "self": bool(is_self)}
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        shape = f"{len(text)} chars" + (f" + {len(images)} image(s)" if images else "")
        print(f"[{dt.datetime.now():%H:%M:%S}] DM from {rec['author']} ({shape}): "
              f"{text[:110]!r}")
        if not self.ingest:
            return
        # an image-only alert (a chart, no words) is still a tip — send the
        # picture through the vision transcription path
        image_data_url = None
        if images:
            image_data_url = await fetch_image_data_url(http, images[0])
            if len(images) > 1:
                print(f"    ! {len(images)} images; only the first is ingested")
        if not text.strip() and image_data_url is None:
            print("    -> nothing to ingest (no text, no usable image)")
            return
        try:
            body = {"text": text, "source_name": "auto",
                    "subject": f"discord dm: {describe_author(msg)}"}
            if image_data_url:
                body["imageDataUrl"] = image_data_url
            r = await http.post(f"{self.api}/api/ingest/manual", headers=headers,
                                json=body, timeout=180)
            out = r.json() if r.status_code == 200 else {"error": r.text[:200]}
            n = len(out.get("signals") or [])
            print(f"    -> ingest {r.status_code}: {n} signal(s) "
                  f"src={out.get('source') or '?'} {out.get('error') or ''}")
            for item in (out.get("signals") or []):
                s = item.get("signal") or {}
                print(f"       {s.get('ticker')} {s.get('direction')} "
                      f"{s.get('instrument')} strike={s.get('strike')} "
                      f"exp={s.get('expiry')} prem={s.get('premium')} "
                      f"[{s.get('status')}] id={s.get('id', '')[:8]}")
        except Exception as exc:
            print(f"    -> ingest failed: {exc}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--api", default=os.environ.get("ZARGAR_API", API_DEFAULT))
    p.add_argument("--token", default=os.environ.get("ZARGAR_DISCORD_TOKEN", ""))
    p.add_argument("--session", default=os.environ.get("ZARGAR_SESSION", ""))
    p.add_argument("--log", default="discord_dms.jsonl")
    p.add_argument("--ingest", action="store_true", help="post DMs to the app (default: dump only)")
    p.add_argument("--dump", action="store_true", help="explicit dump-only (no ingest)")
    p.add_argument("--from-bots-only", action="store_true",
                   help="ingest only DMs authored by a bot (alert relays)")
    p.add_argument("--author-id", default="", help="only this author id")
    p.add_argument("--channel-id", default="", help="only this channel id (opts into a channel, not just DMs)")
    p.add_argument("--include-self", action="store_true",
                   help="also ingest DMs YOU send to yourself (end-to-end self test)")
    p.add_argument("--status-minutes", type=float, default=15.0,
                   help="proof-of-life line every N minutes (0 = off)")
    p.add_argument("--no-auto-token", action="store_true",
                   help="do NOT auto-grab the token from the local Discord app")
    a = p.parse_args()
    if not a.token and not a.no_auto_token:
        try:
            from .discord_token import grab_token
            a.token = grab_token()
            print("[gateway] token auto-grabbed from the local Discord app")
        except Exception as exc:
            print(f"[gateway] could not auto-grab token ({exc})")
    if not a.token:
        print("No token: set ZARGAR_DISCORD_TOKEN, or let it auto-grab from the "
              "local Discord app (drop --no-auto-token).")
        sys.exit(2)
    gw = Gateway(a.token, a.api, a.session, Path(a.log),
                 ingest=a.ingest and not a.dump, dump=a.dump,
                 bots_only=a.from_bots_only, author_id=a.author_id,
                 channel_id=a.channel_id, include_self=a.include_self,
                 status_minutes=a.status_minutes)
    try:
        asyncio.run(gw.run())
    except KeyboardInterrupt:
        print("\n[gateway] stopped")


if __name__ == "__main__":
    main()
