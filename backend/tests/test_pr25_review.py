"""Independent PR25 blockers; scripted I/O, isolated test database only."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.models import DiscordMessage
from zargar.tools.discord_gateway import GatewayStore, mirror_record

from .test_gateway_envelope import _gateway, _msg
from .test_gateway_envelope import rig as rig  # noqa: PLC0414


async def test_email_ingest_still_processes(rig, monkeypatch):
    process = AsyncMock(return_value={"status": "extracted"})
    monkeypatch.setattr(rig.signals_service, "process_content", process)
    result = await rig.signals_service.ingest_email({"from": "offline@example.test", "text": "offline"})
    assert result["status"] == "extracted" and process.await_count == 1


async def test_authoritative_timestamp_reaches_processing(rig, monkeypatch):
    process = AsyncMock(return_value={"status": "extracted"})
    monkeypatch.setattr(rig.signals_service, "process_content", process)
    posted = "2026-09-01T14:00:00+00:00"
    await rig.signals_service.ingest_manual("offline", message_id="time-1", posted_at=posted)
    assert process.call_args.kwargs.get("stated_at") == posted


def test_retry_remains_durable_until_acknowledged(tmp_path):
    store = GatewayStore(tmp_path)
    store.spool({"cid": "c1", "mid": "100", "attempts": 0}, "offline")
    assert store.drain_spool()  # handed to worker, but no ACK yet
    assert GatewayStore(tmp_path).drain_spool(), "Restart before ACK must not erase delivery"


async def test_accepted_queue_message_is_durable(tmp_path):
    gateway = _gateway(tmp_path)
    gateway._enqueue("create", _msg())
    assert GatewayStore(tmp_path).drain_spool(), "Accepted work needs a durable record before crash"


async def test_em_http_failure_does_not_advance_cursor(tmp_path):
    gateway = _gateway(tmp_path)
    gateway._em = {"em-only": {"channelId": "em-only"}}
    msg = _msg(cid="em-only")
    gateway._enqueue("create", msg)
    envelope = gateway._queue.get_nowait()
    http = NS(post=AsyncMock(return_value=NS(status_code=503, json=dict)))
    try:
        await gateway._process_envelope(http, {}, envelope)
    except RuntimeError:
        pass
    assert "em-only" not in gateway._store.cursors, gateway._store.cursors


async def test_partial_edit_preserves_absent_content(rig):
    await rig.signals_service.discord_store_messages([mirror_record(_msg(text="original"), "src1")])
    partial = {"id": "111", "channel_id": "c1", "embeds": [],
               "edited_timestamp": "2026-09-09T11:00:00+00:00"}
    await rig.signals_service.discord_store_messages([mirror_record(partial, "src1")])
    async with rig.sf() as session:
        row = await session.get(DiscordMessage, "111")
    assert row.text == "original", row.text
