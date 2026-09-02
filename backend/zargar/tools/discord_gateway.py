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


TEXT_CHANNEL_TYPES = {0, 5, 15}     # text, announcement, forum
DM_CHANNEL_TYPES = {1, 3}           # dm, group dm


def build_catalog(ready_d: dict) -> dict:
    """READY payload -> the menu the UI shows. The user-account READY (verified
    2026-08-28) puts DM recipients in `recipient_ids` (names live in a top-level
    `users` array) and the guild name in `properties.name`, not `name`."""
    users = {str(u.get("id")): u for u in ready_d.get("users") or []}

    def uname(uid: str) -> tuple[str, bool]:
        u = users.get(str(uid)) or {}
        return (u.get("global_name") or u.get("username") or "unknown", bool(u.get("bot")))

    dms = []
    for ch in ready_d.get("private_channels") or []:
        if ch.get("is_spam"):
            continue
        rids = [str(x) for x in (ch.get("recipient_ids") or [])]
        if ch.get("type") == 3:                  # group DM
            name = ch.get("name") or ", ".join(uname(r)[0] for r in rids) or "group"
            is_bot = False
        else:
            name, is_bot = uname(rids[0]) if rids else ("unknown", False)
        dms.append({"channelId": str(ch.get("id")), "name": name, "isBot": is_bot,
                    "isRequest": bool(ch.get("is_message_request"))})
    guilds = []
    for g in ready_d.get("guilds") or []:
        props = g.get("properties") or {}
        gname = props.get("name") or g.get("name") or "server"
        raw = g.get("channels") or []
        # type 4 = category ("folder"); text channels point at one via parent_id.
        # Carrying the category name/order lets the UI mirror Discord's sidebar.
        cats = {str(c.get("id")): {"name": c.get("name") or "",
                                   "position": c.get("position", 0)}
                for c in raw if c.get("type") == 4}
        chans = []
        for c in raw:
            if c.get("type") not in TEXT_CHANNEL_TYPES:
                continue
            cat = cats.get(str(c.get("parent_id") or ""))
            chans.append({"channelId": str(c.get("id")), "name": c.get("name") or "?",
                          "position": c.get("position", 0),
                          "category": cat["name"] if cat else "",
                          "categoryPos": cat["position"] if cat else -1})
        # Discord order: uncategorized first, then categories by position,
        # channels by position inside each
        chans.sort(key=lambda c: (c["categoryPos"], c["category"].lower(),
                                  c["position"], c["name"]))
        if chans:
            guilds.append({"guildId": str(g.get("id")), "guildName": gname,
                           "channelCount": len(chans), "channels": chans})
    guilds.sort(key=lambda x: x["guildName"].lower())
    user = ready_d.get("user") or {}
    return {"user": {"id": str(user.get("id") or ""), "username": user.get("username")},
            "dms": sorted(dms, key=lambda d: d["name"].lower()), "guilds": guilds}


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


def mirror_record(msg: dict, source_name: str | None,
                  guild_name: str | None = None) -> dict:
    """One message -> the mirror row the app stores (full text + image URLs) —
    the source's own history the analyst can search ('bought NVDA' in the
    morning, 'sold 40%' in the afternoon are one story)."""
    author = msg.get("author") or {}
    return {"id": str(msg.get("id") or ""),
            "channelId": str(msg.get("channel_id") or ""),
            "source": source_name, "guild": guild_name,
            "author": describe_author(msg),
            "authorId": str(author.get("id") or "") or None,
            "isBot": bool(author.get("bot")),
            "text": flatten_message(msg),
            "images": collect_images(msg),
            "postedAt": str(msg.get("timestamp") or "")}


class Gateway:
    def __init__(self, token: str, api: str, session_token: str, log_path: Path,
                 *, ingest: bool, dump: bool, bots_only: bool,
                 author_id: str, channel_id: str, include_self: bool = False,
                 status_minutes: float = 15.0, all_dms: bool = False,
                 backfill: int = 25) -> None:
        self.token = token
        self.api = api
        self.session_token = session_token
        self.log_path = log_path
        self.ingest = ingest
        self.dump = dump
        self.bots_only = bots_only
        self.all_dms = all_dms
        self.author_id = author_id
        self.channel_id = channel_id
        self.include_self = include_self
        self.status_minutes = status_minutes
        self.user_id = ""
        self.seen_count = 0
        self._watch: dict[str, dict] = {}   # channelId -> watch entry (the allowlist)
        # EM method ingestion (docs/techniques/enhanced-market/INGESTION-PLAN.md): a
        # SEPARATE channel set forwarded to EM's inbox. Independent of the tip
        # allowlist above - a channel may be in both, and EM never changes tip behavior.
        self._em: dict[str, dict] = {}
        self._em_loaded = False
        self._watch_loaded = False
        self.backfill = max(0, int(backfill))   # per-channel history mirrored on startup
        self._backfilled_ids = ""               # watch fingerprint last backfilled
        self._http = None                   # shared client for catalog/watch calls
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
        poll = peek = None
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                self._http = http
                poll = asyncio.create_task(self._watch_loop(http, headers))
                peek = asyncio.create_task(self._peek_loop(http, headers))
                async for raw in ws:
                    await self._on_frame(json.loads(raw), http, headers)
        finally:
            hb.cancel()
            status.cancel()
            if poll:
                poll.cancel()
            if peek:
                peek.cancel()

    async def _peek_loop(self, http, headers) -> None:
        """Serve the UI's 'show last message' tests: poll the app for pending
        channel ids, fetch each channel's most recent message via Discord REST
        (read-only), and post the preview back."""
        while True:
            try:
                r = await http.get(f"{self.api}/api/tip/discord/peek-pending", headers=headers)
                cids = (r.json() or {}).get("channelIds") or [] if r.status_code == 200 else []
            except Exception:
                cids = []
            for cid in cids:
                res = await self._fetch_last_message(http, str(cid))
                try:
                    await http.post(f"{self.api}/api/tip/discord/peek-result",
                                    headers=headers, json={"channelId": str(cid), **res})
                except Exception:
                    pass
            # 'process last message as a tip' requests (ingest, not just preview)
            try:
                r = await http.get(f"{self.api}/api/tip/discord/process-pending", headers=headers)
                procs = (r.json() or {}).get("channelIds") or [] if r.status_code == 200 else []
            except Exception:
                procs = []
            for cid in procs:
                await self._process_channel(http, headers, str(cid))
            await asyncio.sleep(2.5)

    async def _fetch_last_message(self, http, channel_id: str) -> dict:
        try:
            r = await http.get(
                f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=1",
                headers={"Authorization": self.token}, timeout=20)
            if r.status_code == 403:
                return {"error": "no access to this channel"}
            if r.status_code != 200:
                return {"error": f"discord {r.status_code}"}
            msgs = r.json() or []
            if not msgs:
                return {"error": "no messages yet"}
            m = msgs[0]
            text = flatten_message(m)
            imgs = collect_images(m)
            if not text and imgs:
                text = f"[image] {imgs[0].split('/')[-1][:40]}"
            return {"text": text[:400], "author": describe_author(m),
                    "messageAt": str(m.get("timestamp") or "")}
        except Exception as exc:
            return {"error": str(exc)[:200]}

    async def _mirror(self, http, headers, records: list[dict]) -> None:
        """Best-effort: store messages in the app's mirror (the analyst's
        searchable source history)."""
        records = [r for r in records if r.get("id")]
        if not records:
            return
        try:
            await http.post(f"{self.api}/api/tip/discord/messages", headers=headers,
                            json={"messages": records})
        except Exception:
            pass

    async def _fetch_messages(self, http, cid: str, *, limit: int = 100,
                              before: str | None = None) -> list[dict]:
        url = f"https://discord.com/api/v10/channels/{cid}/messages?limit={min(100, limit)}"
        if before:
            url += f"&before={before}"
        try:
            r = await http.get(url, headers={"Authorization": self.token}, timeout=20)
            return r.json() if r.status_code == 200 else []
        except Exception:
            return []

    @staticmethod
    def _msg_age_days(msg: dict) -> float:
        try:
            ts = dt.datetime.fromisoformat(str(msg.get("timestamp") or "").replace("Z", "+00:00"))
            return (dt.datetime.now(dt.timezone.utc) - ts).total_seconds() / 86400
        except ValueError:
            return 0.0

    async def _onboard_channel(self, http, headers, cid: str, entry: dict,
                               days: int, st: dict) -> int:
        """Backfill one channel's history back `days` days (paginated, oldest
        continues from what the mirror already holds — never re-downloads)."""
        oldest_at = st.get("oldestAt")
        if oldest_at:
            try:
                oa = dt.datetime.fromisoformat(str(oldest_at).replace("Z", "+00:00"))
                if (dt.datetime.now(dt.timezone.utc) - oa).days >= days:
                    return 0                    # already covered that far back
            except ValueError:
                pass
        src = entry.get("sourceName") or "auto"
        guild = entry.get("guildName") or None
        before = st.get("oldestId")             # extend OLDER than what we hold
        total = 0
        for _page in range(40):                 # hard cap ~4000 msgs per channel
            msgs = await self._fetch_messages(http, cid, limit=100, before=before)
            if not msgs:
                break
            await self._mirror(http, headers,
                               [mirror_record(m, src, guild) for m in msgs])
            total += len(msgs)
            before = str(msgs[-1].get("id") or "")
            if self._msg_age_days(msgs[-1]) >= days or len(msgs) < 100 or not before:
                break
            await asyncio.sleep(1.0)            # gentle on the REST API
        return total

    async def _backfill_watched(self, http, headers) -> None:
        """Mirror history for every WATCHED channel once per run: channels with
        `onboardDays` get a paginated backfill that many days deep (<= 90,
        raised from 17 for the historical-tips experiment, KNOWLEDGE plan
        Phase 1); the rest get the recent --backfill messages as a baseline
        when the mirror holds nothing for them yet."""
        try:
            r = await http.get(f"{self.api}/api/tip/discord/mirror-stats", headers=headers)
            stats = r.json() if r.status_code == 200 else {}
        except Exception:
            stats = {}
        total = 0
        for cid, entry in list(self._watch.items()):
            st = stats.get(str(cid)) or {}
            days = min(90, max(0, int(entry.get("onboardDays") or 0)))
            if days > 0:
                n = await self._onboard_channel(http, headers, cid, entry, days, st)
                if n:
                    print(f"[gateway] onboarded {entry.get('sourceName') or cid}: "
                          f"{n} message(s), ~{days}d deep")
                total += n
            elif not st.get("count") and self.backfill > 0:
                msgs = await self._fetch_messages(http, cid, limit=self.backfill)
                if msgs:
                    await self._mirror(http, headers,
                                       [mirror_record(m, entry.get("sourceName") or "auto",
                                                      entry.get("guildName") or None)
                                        for m in msgs])
                    total += len(msgs)
            await asyncio.sleep(0.7)
        if total:
            print(f"[gateway] mirror updated: {total} message(s) across "
                  f"{len(self._watch)} watched channel(s)")

    async def _watch_loop(self, http, headers) -> None:
        """Poll the app for the watchlist (the allowlist). Empty = manual flags
        decide; non-empty = ingest only channels the user enabled in the UI."""
        while True:
            try:
                r = await http.get(f"{self.api}/api/tip/discord/watch", headers=headers)
                if r.status_code == 200:
                    entries = (r.json() or {}).get("watch") or []
                    self._watch = {str(e["channelId"]): e for e in entries
                                   if e.get("enabled") and e.get("channelId")}
                    if not self._watch_loaded:
                        self._watch_loaded = True
                        print(f"[gateway] watchlist: {len(self._watch)} source(s) enabled"
                              + ("" if self._watch else " (none yet — pick them in the app, "
                                 "Tips > Sources > Discord)"))
                    ids = ",".join(sorted(self._watch))
                    if self._watch and ids != self._backfilled_ids:
                        # first load AND whenever the user adds a source: onboard it
                        self._backfilled_ids = ids
                        asyncio.create_task(self._backfill_watched(http, headers))
            except Exception:
                pass
            # EM ingestion channel set (best-effort; the app owns the list)
            try:
                r = await http.get(f"{self.api}/api/technique/ingest/channels", headers=headers)
                if r.status_code == 200:
                    d = r.json() or {}
                    chans = d.get("channels") or [] if d.get("enabled", True) else []
                    self._em = {str(c["channelId"]): c for c in chans if c.get("channelId")}
                    if not self._em_loaded:
                        self._em_loaded = True
                        print(f"[gateway] EM ingestion: {len(self._em)} channel(s) forwarded to the method inbox")
            except Exception:
                pass
            await asyncio.sleep(30)

    async def _report_catalog(self, ready_d, http, headers) -> None:
        try:
            cat = build_catalog(ready_d)
            await http.post(f"{self.api}/api/tip/discord/catalog", headers=headers, json=cat)
            nch = sum(len(g["channels"]) for g in cat["guilds"])
            print(f"[gateway] reported catalog: {len(cat['dms'])} DM(s), "
                  f"{len(cat['guilds'])} server(s), {nch} channel(s) — pick sources in the app")
        except Exception as exc:
            print(f"[gateway] catalog report failed: {exc}")

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
                  f"({len(data['d'].get('private_channels') or [])} DM channels)")
            await self._report_catalog(data["d"], http, headers)
            print("[gateway] listening.")
            return
        if t != "MESSAGE_CREATE":
            return
        await self._on_message(data["d"], http, headers)

    def _match(self, msg: dict, is_dm: bool, author: dict, is_self: bool):
        """(should_ingest, source_name). The WATCHLIST is the allowlist; manual
        flags are testing overrides. Default (no flags, empty watchlist) matches
        nothing — personal DMs never leak in."""
        cid = str(msg.get("channel_id"))
        if self.channel_id:                       # explicit single-channel test
            return (cid == self.channel_id, "auto")
        if self.author_id:                        # explicit single-author test
            return (str(author.get("id")) == self.author_id, "auto")
        entry = self._watch.get(cid)              # the UI-chosen allowlist
        if entry:
            if entry.get("botsOnly") and not author.get("bot"):
                if not (self.include_self and is_self):
                    return (False, None)
            return (True, entry.get("sourceName") or "auto")
        if self.include_self and is_self and is_dm:   # DM-yourself self test
            return (True, "auto")
        if self.bots_only:                        # legacy: all bot DMs
            return (is_dm and bool(author.get("bot")), "auto")
        if self.all_dms:                          # legacy: every DM
            return (is_dm, "auto")
        return (False, None)                      # allowlist default: no match

    async def _on_message(self, msg: dict, http, headers) -> None:
        is_dm = msg.get("guild_id") is None          # DMs carry no guild
        author = msg.get("author") or {}
        is_self = bool(self.user_id and str(author.get("id")) == self.user_id)
        cid_em = str(msg.get("channel_id") or "")
        if cid_em in self._em:                    # EM method inbox (independent of tips)
            await self._em_forward(http, headers, msg, self._em[cid_em])
        matched, source_name = self._match(msg, is_dm, author, is_self)
        if not matched:
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
        # every matched message joins the mirror (the analyst's source history),
        # ingested or not — follow-ups like "sold 40%" rarely extract as tips
        entry = self._watch.get(str(msg.get("channel_id"))) or {}
        await self._mirror(http, headers,
                           [mirror_record(msg, source_name or entry.get("sourceName") or "auto",
                                          entry.get("guildName") or None)])
        # context channels (KNOWLEDGE plan C1): general-conversation rooms like
        # trading-floor are mirrored for search + digests but NEVER auto-intake —
        # chatter is not a tip
        if (entry.get("mode") or "tips") == "context":
            print("    -> context channel: mirrored only (no tip intake)")
            return
        if not self.ingest:
            return
        await self._ingest_message(http, headers, msg, source_name or "auto")

    async def _em_forward(self, http, headers, msg: dict, entry: dict) -> None:
        """EM method ingestion: post the message to EM's own inbox. Read-only
        toward Discord; never touches the tip mirror/intake. Failures print."""
        rec = mirror_record(msg, None, entry.get("guildName") or None)
        rec["channelName"] = entry.get("label") or ""
        # the video link often lives in an embed card or a video attachment, not the
        # text - surface every URL so EM's link detection sees it
        extra: list[str] = []
        for e in msg.get("embeds") or []:
            for u in (e.get("url"), (e.get("video") or {}).get("url"), (e.get("provider") or {}).get("url")):
                if u and u not in rec["text"] and u not in extra:
                    extra.append(str(u))
        for a in msg.get("attachments") or []:
            u = a.get("url") or ""
            if u and str(a.get("content_type") or "").startswith(("video/", "audio/")) and u not in extra:
                extra.append(str(u))
        if extra:
            rec["text"] = (rec["text"] + "\n" + "\n".join(extra)).strip()
        try:
            r = await http.post(f"{self.api}/api/technique/ingest/message", headers=headers,
                                json=rec, timeout=60)
            out = r.json() if r.status_code == 200 else {}
            tag = "dup" if out.get("duplicate") else f"{out.get('kind')}->{out.get('status')}"
            print(f"[{dt.datetime.now():%H:%M:%S}] EM #{rec['channelName'] or rec['channelId']}: "
                  f"{tag if r.status_code == 200 else 'HTTP ' + str(r.status_code)} "
                  f"{flatten_message(msg)[:80]!r}")
        except Exception as exc:
            print(f"    ! EM forward failed: {exc}")

    async def _ingest_message(self, http, headers, msg: dict, source_name: str) -> dict:
        """Post one message (text + first image, if any) to /api/ingest/manual —
        the shared path for live alerts AND 'process last message'. Returns a
        summary of what the pipeline did (for the process-result report)."""
        text = flatten_message(msg)
        images = collect_images(msg)
        image_data_url = await fetch_image_data_url(http, images[0]) if images else None
        if not text.strip() and image_data_url is None:
            print("    -> nothing to ingest (no text, no usable image)")
            return {"ok": False, "note": "nothing to ingest — the message has no text and no usable image"}
        try:
            body = {"text": text, "source_name": source_name or "auto",
                    "subject": f"discord: {describe_author(msg)}"}
            if image_data_url:
                body["imageDataUrl"] = image_data_url
            r = await http.post(f"{self.api}/api/ingest/manual", headers=headers,
                                json=body, timeout=200)
            out = r.json() if r.status_code == 200 else {"error": r.text[:200]}
            n = len(out.get("signals") or [])
            print(f"    -> ingest {r.status_code}: {n} signal(s) "
                  f"src={out.get('source') or '?'} {out.get('error') or ''}")
            sigs = []
            for item in (out.get("signals") or []):
                s = item.get("signal") or {}
                print(f"       {s.get('ticker')} {s.get('direction')} "
                      f"{s.get('instrument')} [{s.get('status')}] id={s.get('id', '')[:8]}")
                sigs.append({"id": s.get("id"), "ticker": s.get("ticker"),
                             "status": s.get("status"),
                             "analystRunId": ((s.get("extraction") or {})
                                              .get("analyst") or {}).get("runId")})
            if r.status_code != 200:
                return {"ok": False, "error": f"ingest {r.status_code}: {out.get('error') or ''}"}
            if n == 0:
                return {"ok": True, "signals": [], "intakeRunId": out.get("intakeRunId") or "",
                        "note": out.get("note") or "the message did not extract as a trade tip"}
            return {"ok": True, "signals": sigs, "intakeRunId": out.get("intakeRunId") or ""}
        except Exception as exc:
            print(f"    -> ingest failed: {exc}")
            return {"ok": False, "error": f"ingest failed: {str(exc)[:200]}"}

    async def _process_channel(self, http, headers, channel_id: str) -> None:
        """'Process last message as a tip': fetch a channel's most recent message
        via REST, run it through the pipeline (source from the watchlist), and
        REPORT the outcome back to the app — a message that isn't a tip must not
        look like silence (user, 2026-08-28)."""
        async def report(res: dict) -> None:
            try:
                await http.post(f"{self.api}/api/tip/discord/process-result",
                                headers=headers, json={"channelId": str(channel_id), **res})
            except Exception:
                pass
        try:
            r = await http.get(
                f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=1",
                headers={"Authorization": self.token}, timeout=20)
            msgs = r.json() if r.status_code == 200 else []
            if r.status_code == 403:
                print(f"    ! process: no access to {channel_id}")
                return await report({"ok": False, "error": "no access to this channel"})
            if r.status_code != 200:
                print(f"    ! process: discord {r.status_code} for {channel_id}")
                return await report({"ok": False, "error": f"discord {r.status_code}"})
        except Exception as exc:
            print(f"    ! process fetch failed: {exc}")
            return await report({"ok": False, "error": f"fetch failed: {str(exc)[:200]}"})
        if not msgs:
            print(f"    ! process: no messages in {channel_id}")
            return await report({"ok": False, "error": "no messages in this channel yet"})
        entry = self._watch.get(str(channel_id)) or {}
        src = entry.get("sourceName") or "auto"
        print(f"[{dt.datetime.now():%H:%M:%S}] processing last message of {channel_id} as {src}")
        await self._mirror(http, headers,
                           [mirror_record(msgs[0], src, entry.get("guildName") or None)])
        res = await self._ingest_message(http, headers, msgs[0], src)
        await report({"author": describe_author(msgs[0]),
                      "text": flatten_message(msgs[0])[:200], **res})


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--api", default=os.environ.get("ZARGAR_API", API_DEFAULT))
    p.add_argument("--token", default=os.environ.get("ZARGAR_DISCORD_TOKEN", ""))
    p.add_argument("--session", default=os.environ.get("ZARGAR_SESSION", ""))
    p.add_argument("--log", default="discord_dms.jsonl")
    p.add_argument("--ingest", action="store_true", help="post DMs to the app (default: dump only)")
    p.add_argument("--dump", action="store_true", help="explicit dump-only (no ingest)")
    p.add_argument("--all-dms", action="store_true",
                   help="ignore the watchlist and ingest every DM (testing)")
    p.add_argument("--from-bots-only", action="store_true",
                   help="ingest all bot-authored DMs (legacy; prefer the watchlist)")
    p.add_argument("--author-id", default="", help="only this author id")
    p.add_argument("--channel-id", default="", help="only this channel id (opts into a channel, not just DMs)")
    p.add_argument("--include-self", action="store_true",
                   help="also ingest DMs YOU send to yourself (end-to-end self test)")
    p.add_argument("--backfill", type=int, default=25,
                   help="mirror this many recent messages per WATCHED channel on startup (0 = off)")
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
                 status_minutes=a.status_minutes, all_dms=a.all_dms,
                 backfill=a.backfill)
    try:
        asyncio.run(gw.run())
    except KeyboardInterrupt:
        print("\n[gateway] stopped")


if __name__ == "__main__":
    main()
