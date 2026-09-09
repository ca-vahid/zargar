"""Corrected-stack crash/acknowledgment boundaries. No live I/O.

Codex follow-up review 2026-09-09 (test_stack_followup.py), split per owning
branch: A1–A3 live here on the gateway PR; A4 (llm_stats batch identity) lives
in test_stack_followup_measurement.py on the measurement PR, because
zargar.research.llm_stats does not exist on this branch. Test bodies are
verbatim from the reviewer's file."""
import datetime as dt
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.domain import new_id
from zargar.models import RawContent
from zargar.tools.discord_gateway import GatewayStore

from .test_gateway_envelope import _gateway, _msg
from .test_gateway_envelope import rig as rig  # noqa: PLC0414


def test_ack_old_revision_does_not_erase_newer_pending_revision(tmp_path):
    store = GatewayStore(tmp_path)
    old = {"kind": "update", "cid": "c1", "mid": "111",
           "msg": {"edited_timestamp": "2026-09-09T10:00:00Z", "content": "old"}}
    new = {**old, "msg": {"edited_timestamp": "2026-09-09T11:00:00Z", "content": "new"}}
    store.accept(old)
    store.accept(new)  # arrives while old revision is being delivered
    store.ack(old)
    restored = GatewayStore(tmp_path).drain_spool()
    assert any(r["msg"]["content"] == "new" for r in restored), restored


def test_compaction_failure_keeps_preexisting_ledger(tmp_path, monkeypatch):
    store = GatewayStore(tmp_path)
    store.accept({"kind": "create", "cid": "c1", "mid": "111"})
    write_text = Path.write_text

    def interrupted_write(path, data, **kwargs):
        if path == store.spool_path:
            # Simulates interruption after write_text has truncated the live file.
            with path.open("w", encoding="utf-8"):
                pass
            raise OSError("interrupted compaction")
        return write_text(path, data, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "write_text", interrupted_write)
        store._compact()
    restored = GatewayStore(tmp_path).drain_spool()
    assert len(restored) == 1, restored


async def test_recent_abandoned_claim_is_not_acknowledged_as_completed(rig, tmp_path):
    mid = "111"
    raw = RawContent(id=new_id(), source_type="manual", source_name="src1", body_text="offline",
        meta={"messageId": mid, "claimedAt": dt.datetime.now(dt.UTC).isoformat()})
    async with rig.sf() as session:
        session.add(raw)
        await session.commit()  # prior process then hard-killed before extraction
    rig.signals_service.process_content = AsyncMock(return_value={"status": "extracted"})

    class Http:
        async def post(self, url, *, headers, json, **kwargs):
            if url.endswith("/api/ingest/manual"):
                out = await rig.signals_service.ingest_manual(json["text"],
                    source_name=json["source_name"], message_id=json["messageId"],
                    posted_at=json["postedAt"])
                return NS(status_code=200, json=lambda: out)
            return NS(status_code=200, json=lambda: {"stored": 1})

    gateway = _gateway(tmp_path)
    gateway._enqueue("create", _msg(mid=mid))
    await gateway._deliver(Http(), {}, gateway._queue.get_nowait())
    async with rig.sf() as session:
        row = await session.get(RawContent, raw.id)
    assert row.status != "new" or gateway._store.counts()[0] > 0, (
        row.status, gateway._store.counts(), gateway._store.cursors)
