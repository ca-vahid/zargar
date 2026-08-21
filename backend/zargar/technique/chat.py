"""Conversational review surface (spec plan §5).

Threads hold both pipeline transcripts (kind="run") and free chats. Every turn,
tool call and tool result is persisted as a `chat_messages` row and streamed to
the UI over the `chat` bus topic as it happens. Images live in `chat_assets`
and are referenced from message blocks by id, so rows stay small and the same
bytes can be replayed to the model on later turns.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from sqlalchemy import func, select

from .. import bus as topics
from .. import events as ev
from ..domain import new_id
from ..models import ChatAsset, ChatMessage, ChatThread
from .llm import (
    blocks_to_json,
    image_block,
    json_to_api_blocks,
    make_client,
    sniff_media_type,
    stream_message,
)
from .schemas import SYSTEM_PROMPT
from .tools import CHAT_TOOL_GUIDE, TOOL_DEFS, ToolExecutor

log = logging.getLogger("zargar.technique.chat")

MAX_TOOL_ROUNDS = 12
FLUSH_MS = 70   # coalesce streaming deltas to keep the WS quiet


def thread_dict(t: ChatThread, *, message_count: int | None = None) -> dict:
    return {
        "id": t.id, "title": t.title, "kind": t.kind, "symbol": t.symbol, "runId": t.run_id,
        "archived": t.archived, "meta": t.meta or {},
        "createdAt": t.created_at.isoformat() if t.created_at else None,
        "updatedAt": t.updated_at.isoformat() if t.updated_at else None,
        "messageCount": message_count,
    }


def message_dict(m: ChatMessage) -> dict:
    return {
        "id": m.id, "threadId": m.thread_id, "seq": m.seq, "role": m.role,
        "blocks": m.blocks or [], "meta": m.meta or {},
        "createdAt": m.created_at.isoformat() if m.created_at else None,
    }


class _Coalescer:
    """Buffers thinking/text deltas per (pass) and flushes on a timer so the UI
    gets ~14 updates/sec instead of hundreds."""

    def __init__(self, publish) -> None:
        self._publish = publish
        self._buf: dict[str, str] = {}
        self._last = 0.0

    async def push(self, kind: str, text: str, base: dict) -> None:
        key = kind
        self._buf[key] = self._buf.get(key, "") + text
        self._base = base
        now = time.time() * 1000
        if now - self._last >= FLUSH_MS:
            await self.flush()

    async def flush(self) -> None:
        if not self._buf:
            return
        for kind, text in self._buf.items():
            await self._publish({**self._base, "type": kind, "text": text})
        self._buf.clear()
        self._last = time.time() * 1000


class ChatService:
    def __init__(self, engine, technique) -> None:
        self.engine = engine
        self.technique = technique
        self._client = None
        self._tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------ plumbing
    def _get_client(self):
        if self._client is None:
            self._client = make_client(self.technique.llm_config())
        return self._client

    def publish(self, thread_id: str, event: dict, *, run_id: str | None = None) -> None:
        self.engine.bus.publish(topics.CHAT, {"threadId": thread_id, "runId": run_id, "event": event})

    # ------------------------------------------------------------ threads
    async def create_thread(self, *, title: str = "", kind: str = "chat", symbol: str | None = None,
                            run_id: str | None = None, meta: dict | None = None) -> dict:
        row = ChatThread(id=new_id(), title=title or (f"{symbol} chat" if symbol else "New chat"),
                         kind=kind, symbol=(symbol or None), run_id=run_id, meta=meta or {})
        async with self.engine.sf() as session:
            session.add(row)
            await session.commit()
        d = thread_dict(row, message_count=0)
        await self.engine.journal.append(ev.CHAT_THREAD_CREATED, d, aggregate_type="chat",
                                         aggregate_id=row.id)
        self.publish(row.id, {"type": "thread", "thread": d})
        return d

    async def list_threads(self, *, limit: int = 100, include_archived: bool = False,
                           kind: str | None = None) -> list[dict]:
        async with self.engine.sf() as session:
            stmt = select(ChatThread).order_by(ChatThread.updated_at.desc()).limit(limit)
            if not include_archived:
                stmt = stmt.where(ChatThread.archived.is_(False))
            if kind:
                stmt = stmt.where(ChatThread.kind == kind)
            rows = (await session.execute(stmt)).scalars().all()
            counts = dict((await session.execute(
                select(ChatMessage.thread_id, func.count()).group_by(ChatMessage.thread_id))).all())
        return [thread_dict(t, message_count=int(counts.get(t.id, 0))) for t in rows]

    async def get_thread(self, thread_id: str) -> dict | None:
        async with self.engine.sf() as session:
            t = await session.get(ChatThread, thread_id)
            if t is None:
                return None
            msgs = (await session.execute(
                select(ChatMessage).where(ChatMessage.thread_id == thread_id)
                .order_by(ChatMessage.seq))).scalars().all()
        d = thread_dict(t, message_count=len(msgs))
        d["messages"] = [message_dict(m) for m in msgs]
        d["busy"] = thread_id in self._tasks and not self._tasks[thread_id].done()
        return d

    async def update_thread(self, thread_id: str, *, title: str | None = None,
                            archived: bool | None = None) -> dict | None:
        async with self.engine.sf() as session:
            t = await session.get(ChatThread, thread_id)
            if t is None:
                return None
            if title is not None:
                t.title = title[:200]
            if archived is not None:
                t.archived = bool(archived)
            await session.commit()
            d = thread_dict(t)
        self.publish(thread_id, {"type": "thread", "thread": d})
        return d

    async def search(self, q: str, *, limit: int = 50) -> list[dict]:
        """Substring search over message text blocks (single-user scale)."""
        q = (q or "").strip().lower()
        if not q:
            return []
        out: list[dict] = []
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(3000))).scalars().all()
        for m in rows:
            txt = " ".join(b.get("text", "") for b in (m.blocks or []) if b.get("type") == "text")
            if q in txt.lower():
                i = txt.lower().find(q)
                out.append({"threadId": m.thread_id, "messageId": m.id, "seq": m.seq, "role": m.role,
                            "snippet": txt[max(0, i - 80): i + 120],
                            "createdAt": m.created_at.isoformat() if m.created_at else None})
                if len(out) >= limit:
                    break
        return out

    # ------------------------------------------------------------ messages
    async def _next_seq(self, session, thread_id: str) -> int:
        cur = (await session.execute(
            select(func.max(ChatMessage.seq)).where(ChatMessage.thread_id == thread_id))).scalar()
        return int(cur or 0) + 1

    async def append_message(self, thread_id: str, role: str, blocks: list[dict],
                             meta: dict | None = None, *, publish: bool = True,
                             run_id: str | None = None) -> dict:
        async with self.engine.sf() as session:
            seq = await self._next_seq(session, thread_id)
            row = ChatMessage(id=new_id(), thread_id=thread_id, seq=seq, role=role,
                              blocks=blocks, meta=meta or {})
            session.add(row)
            t = await session.get(ChatThread, thread_id)
            if t is not None:
                t.updated_at = row.created_at or t.updated_at
            await session.commit()
            d = message_dict(row)
        if publish:
            self.publish(thread_id, {"type": "message", "message": d}, run_id=run_id)
        return d

    async def store_asset(self, data: bytes, media_type: str | None = None,
                          thread_id: str | None = None, meta: dict | None = None) -> str:
        mt = media_type or sniff_media_type(data)
        row = ChatAsset(id=new_id(), thread_id=thread_id, media_type=mt, data=data, meta=meta or {})
        async with self.engine.sf() as session:
            session.add(row)
            await session.commit()
        return row.id

    async def get_asset(self, asset_id: str) -> tuple[bytes, str] | None:
        async with self.engine.sf() as session:
            a = await session.get(ChatAsset, asset_id)
            if a is None:
                return None
            return a.data, a.media_type

    async def get_asset_bytes(self, asset_id: str) -> bytes | None:
        got = await self.get_asset(asset_id)
        return got[0] if got else None

    # ------------------------------------------------------------ sending
    async def send(self, thread_id: str, text: str, images: list[bytes] | None = None) -> dict:
        """Persist the user turn and start the agent loop in the background.
        Returns the stored user message; progress arrives over the `chat` topic."""
        if thread_id in self._tasks and not self._tasks[thread_id].done():
            raise RuntimeError("thread is busy — wait for the current reply or cancel it")
        blocks: list[dict] = []
        for data in images or []:
            mt = sniff_media_type(data)
            aid = await self.store_asset(data, mt, thread_id=thread_id)
            blocks.append({"type": "image_ref", "assetId": aid, "mediaType": mt})
        if text.strip():
            blocks.append({"type": "text", "text": text})
        if not blocks:
            raise ValueError("empty message")
        user_msg = await self.append_message(thread_id, "user", blocks)
        task = asyncio.create_task(self._agent_turn(thread_id), name=f"chat-{thread_id[:8]}")
        self._tasks[thread_id] = task
        return user_msg

    async def cancel(self, thread_id: str) -> bool:
        t = self._tasks.get(thread_id)
        if t and not t.done():
            t.cancel()
            return True
        return False

    def is_busy(self, thread_id: str) -> bool:
        t = self._tasks.get(thread_id)
        return bool(t and not t.done())

    async def _history_for_api(self, thread_id: str) -> list[dict]:
        """Stored messages → API messages. image_ref blocks are inflated from
        assets; UI-only blocks are dropped; consecutive same-role turns merged."""
        async with self.engine.sf() as session:
            msgs = (await session.execute(
                select(ChatMessage).where(ChatMessage.thread_id == thread_id)
                .order_by(ChatMessage.seq))).scalars().all()
        out: list[dict] = []
        for m in msgs:
            content: list[dict] = []
            for b in m.blocks or []:
                if b.get("type") == "image_ref" and b.get("assetId"):
                    got = await self.get_asset(b["assetId"])
                    if got:
                        content.append(image_block(got[0], got[1]))
                    continue
                if b.get("type") == "tool_result":
                    # tool_result content may itself hold image refs
                    inner = b.get("content")
                    if isinstance(inner, list):
                        fixed = []
                        for ib in inner:
                            if ib.get("type") == "image_ref" and ib.get("assetId"):
                                got = await self.get_asset(ib["assetId"])
                                if got:
                                    fixed.append(image_block(got[0], got[1]))
                            else:
                                fixed.append(ib)
                        b = {**b, "content": fixed}
                    content.append({k: v for k, v in b.items() if k != "meta"})
                    continue
                content.extend(json_to_api_blocks([b]))
            if not content:
                continue
            role = "assistant" if m.role == "assistant" else "user"
            if out and out[-1]["role"] == role:
                out[-1]["content"].extend(content)
            else:
                out.append({"role": role, "content": content})
        # The API requires the conversation to start with a user turn.
        while out and out[0]["role"] != "user":
            out.pop(0)
        return out

    def _system(self) -> list[dict]:
        return [{"type": "text", "text": SYSTEM_PROMPT + CHAT_TOOL_GUIDE,
                 "cache_control": {"type": "ephemeral"}}]

    async def _agent_turn(self, thread_id: str) -> None:
        cfg = self.technique.llm_config()
        if not cfg.available:
            await self.append_message(thread_id, "assistant", [{"type": "text", "text":
                "The Anthropic API key is not configured (ZARGAR_ANTHROPIC_API_KEY)."}],
                {"error": True})
            return
        client = self._get_client()
        executor = ToolExecutor(self.technique, lambda d, mt: self.store_asset(d, mt, thread_id),
                                thread_id=thread_id)
        co = _Coalescer(lambda e: self._apublish(thread_id, e))
        self.publish(thread_id, {"type": "turn_start"})
        try:
            for round_no in range(MAX_TOOL_ROUNDS):
                messages = await self._history_for_api(thread_id)
                base = {"round": round_no}

                async def on_event(e: dict) -> None:
                    t = e.get("type")
                    if t in ("thinking_delta", "text_delta"):
                        await co.push(t, e["text"], base)
                    else:
                        await co.flush()
                        self.publish(thread_id, {**base, **e})

                msg = await stream_message(client, cfg, on_event=on_event, system=self._system(),
                                           messages=messages, tools=TOOL_DEFS)
                await co.flush()
                blocks = blocks_to_json(msg.content)
                u = msg.usage
                meta = {"model": cfg.model, "effort": cfg.effort, "stopReason": msg.stop_reason,
                        "usage": {"input": u.input_tokens, "output": u.output_tokens,
                                  "cacheRead": getattr(u, "cache_read_input_tokens", 0) or 0,
                                  "cacheWrite": getattr(u, "cache_creation_input_tokens", 0) or 0}}
                await self.append_message(thread_id, "assistant", blocks, meta)

                if msg.stop_reason == "refusal":
                    await self.append_message(thread_id, "assistant", [{"type": "text", "text":
                        "The model declined to answer this request."}], {"error": True})
                    break
                tool_uses = [b for b in msg.content if getattr(b, "type", "") == "tool_use"]
                if msg.stop_reason != "tool_use" or not tool_uses:
                    break

                # execute every tool, return ALL results in one user message
                results: list[dict] = []
                for tu in tool_uses:
                    self.publish(thread_id, {"type": "tool_running", "id": tu.id, "name": tu.name,
                                             "input": tu.input})
                    content, tmeta = await executor.run(tu.name, tu.input or {})
                    await self.engine.journal.append(ev.CHAT_TOOL_CALLED, {
                        "threadId": thread_id, "tool": tu.name, "input": tu.input,
                        "meta": {k: v for k, v in tmeta.items() if k != "keyLevels"}},
                        aggregate_type="chat", aggregate_id=thread_id)
                    stored_content: Any = content
                    if isinstance(content, list):
                        # swap inline images for asset refs before persisting
                        stored_content = []
                        for b in content:
                            if b.get("type") == "image" and tmeta.get("assetId"):
                                stored_content.append({"type": "image_ref", "assetId": tmeta["assetId"],
                                                       "mediaType": b["source"]["media_type"]})
                            else:
                                stored_content.append(b)
                    results.append({"type": "tool_result", "tool_use_id": tu.id,
                                    "content": stored_content,
                                    **({"is_error": True} if tmeta.get("error") else {}),
                                    "meta": {"name": tu.name, **tmeta}})
                    self.publish(thread_id, {"type": "tool_done", "id": tu.id, "name": tu.name,
                                             "meta": tmeta,
                                             "preview": (content if isinstance(content, str)
                                                         else text_of_blocks(content))[:400]})
                await self.append_message(thread_id, "user", results, {"kind": "tool_results"})
            self.publish(thread_id, {"type": "turn_done"})
        except asyncio.CancelledError:
            await co.flush()
            await self.append_message(thread_id, "assistant", [{"type": "text", "text": "(cancelled)"}],
                                      {"cancelled": True})
            self.publish(thread_id, {"type": "turn_done", "cancelled": True})
            raise
        except Exception as exc:
            log.exception("chat turn failed")
            await co.flush()
            await self.append_message(thread_id, "assistant", [{"type": "text", "text":
                f"Error: {type(exc).__name__}: {exc}"}], {"error": True})
            self.publish(thread_id, {"type": "turn_done", "error": str(exc)})
        finally:
            self._tasks.pop(thread_id, None)

    async def _apublish(self, thread_id: str, event: dict) -> None:
        self.publish(thread_id, event)


def text_of_blocks(blocks: list[dict]) -> str:
    return " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")
