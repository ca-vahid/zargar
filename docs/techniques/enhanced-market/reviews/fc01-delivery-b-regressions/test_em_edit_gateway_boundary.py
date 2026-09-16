"""Delivery B's actual gateway envelope must mark EM updates for EM delivery.

Pure test: temporary gateway spool only, no network, database, or app runtime.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from zargar.tools.discord_gateway import Gateway


def test_em_channel_edit_reaches_em_through_the_real_envelope(tmp_path):
    gateway = Gateway("test-token", "http://unused", "test-session", tmp_path / "gateway.jsonl",
                      ingest=True, dump=False, bots_only=False, author_id="", channel_id="")
    gateway._em = {"em-channel": {"channelId": "em-channel", "label": "EM source"}}
    gateway._watch = {}
    gateway._queue = asyncio.Queue(10)
    gateway._seq = 40
    gateway._em_forward = AsyncMock(return_value=None)
    gateway._mirror = AsyncMock(return_value=True)
    gateway._enqueue("update", {
        "id": "123", "channel_id": "em-channel", "guild_id": "guild",
        "content": "MSFT long above 498.97", "edited_timestamp": "2026-09-14T13:21:00Z",
        "timestamp": "2026-09-14T13:20:00Z", "author": {"id": "author", "username": "EM"},
    })
    assert gateway._queue.qsize() == 1
    envelope = gateway._queue.get_nowait()
    assert envelope["kind"] == "update"
    http = SimpleNamespace(post=AsyncMock(return_value=SimpleNamespace(
        status_code=200, json=lambda: {"ok": True})))
    asyncio.run(gateway._process_envelope(http, {}, envelope))
    assert gateway._em_forward.await_count == 1, "The actual queued edit must be routed to EM"
    assert gateway._em_forward.await_args.kwargs.get("kind") == "update"


def test_em_gateway_sequence_is_the_receipt_sequence_not_the_later_worker_sequence(tmp_path):
    gateway = Gateway("test-token", "http://unused", "test-session", tmp_path / "gateway.jsonl",
                      ingest=True, dump=False, bots_only=False, author_id="", channel_id="")
    gateway._em = {"em-channel": {"channelId": "em-channel", "label": "EM source"}}
    gateway._watch = {}
    gateway._queue = asyncio.Queue(10)
    sent = []

    async def post(url, **kwargs):
        sent.append(kwargs["json"])
        return SimpleNamespace(status_code=200, json=lambda: {"kind": "post", "status": "new"})

    for sequence, message_id in [(40, "123"), (41, "124")]:
        gateway._seq = sequence
        gateway._enqueue("create", {
            "id": message_id, "channel_id": "em-channel", "guild_id": "guild",
            "content": "MSFT long above 498.97", "timestamp": "2026-09-14T13:20:00Z",
            "author": {"id": "author", "username": "EM"},
        })
    gateway._seq = 99  # More gateway frames arrive before the delivery worker catches up.
    assert gateway._queue.qsize() == 2
    http = SimpleNamespace(post=post)
    while not gateway._queue.empty():
        asyncio.run(gateway._process_envelope(http, {}, gateway._queue.get_nowait()))
    assert [row["gatewaySeq"] for row in sent] == [40, 41], (
        "Persist the receipt's ordering key in its envelope; worker-time _seq is a different event"
    )
