"""Gateway envelope (Codex audit finding 2, GATEWAY-PLAN.md): durable message
identity, hot receive path, per-channel ordering, cursors/spool, revisions."""
import asyncio
import datetime as dt
import json
from pathlib import Path

import pytest

from zargar.domain import new_id
from zargar.engine import Engine
from zargar.models import DiscordMessage, RawContent
from zargar.signals.schemas import ExtractionResult
from zargar.signals.service import attach_signal_layer
from zargar.tools.discord_gateway import Gateway, GatewayStore, mirror_record

from .conftest import make_test_config


# ---------------------------------------------------------------- store
def test_cursor_advances_monotonically_and_persists(tmp_path):
    st = GatewayStore(tmp_path)
    st.advance("c1", "100")
    st.advance("c1", "50")            # never backward
    st.advance("c1", "200")
    assert GatewayStore(tmp_path).cursors == {"c1": "200"}


def test_spool_drain_keeps_dead_entries(tmp_path):
    st = GatewayStore(tmp_path)
    st.spool({"cid": "c1", "mid": "1", "attempts": 0}, "app down")
    st.spool({"cid": "c1", "mid": "2", "attempts": GatewayStore.MAX_ATTEMPTS - 1}, "app down")
    retry = st.drain_spool()
    assert [r["mid"] for r in retry] == ["1"]          # the dead one stays on disk
    left = [json.loads(x) for x in st.spool_path.read_text(encoding="utf-8").splitlines()]
    assert len(left) == 1 and left[0]["mid"] == "2" and left[0]["dead"] is True
    assert st.drain_spool() == []                       # dead entries never replay


# ---------------------------------------------------------------- enqueue
def _gateway(tmp_path) -> Gateway:
    gw = Gateway("tok", "http://x", "", tmp_path / "dms.jsonl",
                 ingest=True, dump=False, bots_only=False,
                 author_id="", channel_id="")
    gw._watch = {"c1": {"channelId": "c1", "enabled": True, "sourceName": "src1",
                        "botsOnly": False}}
    gw._queue = asyncio.Queue(2)
    return gw


def _msg(mid="111", cid="c1", text="BUY TEST", edited=None):
    m = {"id": mid, "channel_id": cid, "guild_id": "g", "content": text,
         "timestamp": "2026-09-09T10:00:00+00:00",
         "author": {"id": "a1", "username": "alice", "bot": True}}
    if edited:
        m["edited_timestamp"] = edited
    return m


async def test_enqueue_is_nonblocking_and_carries_identity(tmp_path):
    gw = _gateway(tmp_path)
    gw._enqueue("create", _msg())
    env = gw._queue.get_nowait()
    assert env["kind"] == "create" and env["mid"] == "111" and env["cid"] == "c1"
    assert env["source"] == "src1"
    # unmatched channel: nothing enqueued, nothing spooled
    gw._enqueue("create", _msg(cid="unwatched"))
    assert gw._queue.empty()
    # a FULL queue spools instead of blocking the receive path
    gw._queue.put_nowait({}), gw._queue.put_nowait({})
    gw._enqueue("create", _msg(mid="112"))
    assert gw._dropped == 1
    spooled = gw._store.drain_spool()
    assert spooled and spooled[0]["mid"] == "112"


async def test_update_envelopes_only_for_watched_channels(tmp_path):
    gw = _gateway(tmp_path)
    gw._enqueue("update", _msg(mid="113", edited="2026-09-09T11:00:00+00:00"))
    assert gw._queue.get_nowait()["kind"] == "update"
    gw._enqueue("update", _msg(mid="114", cid="unwatched"))
    assert gw._queue.empty()


async def test_per_channel_ordering_across_workers(tmp_path):
    gw = _gateway(tmp_path)
    gw._queue = asyncio.Queue(10)
    done: list[str] = []

    async def fake_process(http, headers, env):
        if env["mid"] == "1":
            await asyncio.sleep(0.1)        # slow first message
        done.append(f"{env['cid']}:{env['mid']}")
    gw._process_envelope = fake_process
    for mid, cid in (("1", "c1"), ("2", "c1"), ("3", "c2")):
        gw._queue.put_nowait({"cid": cid, "mid": mid, "attempts": 0})
    workers = [asyncio.create_task(gw._worker(None, {})) for _ in range(2)]
    await gw._queue.join()
    for w in workers:
        w.cancel()
    assert done.index("c1:1") < done.index("c1:2")      # in-channel order held
    assert done.index("c2:3") < done.index("c1:2")      # other channels not blocked


# ---------------------------------------------------------------- app side
class _CountingExtractor:
    available = True
    model = "fake"

    def __init__(self):
        self.calls = 0

    async def extract(self, text, **kw):
        self.calls += 1
        return ExtractionResult(signals=[], source_type="commentary")


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    yield eng
    await eng.stop()


async def test_message_id_dedupes_before_extraction(rig):
    svc = rig.signals_service
    svc.extractor = _CountingExtractor()
    out1 = await svc.ingest_manual("BUY TEST now", source_name="src1",
                                   message_id="m-777",
                                   posted_at="2026-09-09T10:00:00+00:00")
    assert not out1.get("duplicate") and svc.extractor.calls == 1
    out2 = await svc.ingest_manual("BUY TEST now", source_name="src1",
                                   message_id="m-777")
    assert out2["duplicate"] is True and svc.extractor.calls == 1   # no second LLM call
    async with rig.sf() as session:
        row = await session.get(RawContent, out1["contentId"])
    assert row.meta.get("messageId") == "m-777"
    assert row.meta.get("postedAt") == "2026-09-09T10:00:00+00:00"


async def test_mirror_upserts_newer_revisions_only(rig):
    svc = rig.signals_service
    rec = mirror_record(_msg(text="original"), "src1")
    assert await svc.discord_store_messages([rec]) == 1
    edited = mirror_record(_msg(text="CORRECTED strike 105",
                                edited="2026-09-09T11:00:00+00:00"), "src1")
    assert await svc.discord_store_messages([edited]) == 1
    async with rig.sf() as session:
        row = await session.get(DiscordMessage, "111")
    assert "CORRECTED" in row.text and row.edited_at is not None
    stale = mirror_record(_msg(text="old text",
                               edited="2026-09-09T10:30:00+00:00"), "src1")
    assert await svc.discord_store_messages([stale]) == 0           # older: ignored
    async with rig.sf() as session:
        row = await session.get(DiscordMessage, "111")
    assert "CORRECTED" in row.text


async def test_edit_is_journaled_never_reextracted(rig):
    from sqlalchemy import select
    from zargar.models import Event
    svc = rig.signals_service
    svc.extractor = _CountingExtractor()
    out = await svc.ingest_manual("BUY TEST", source_name="src1", message_id="m-888")
    assert svc.extractor.calls == 1
    res = await svc.discord_message_edited("m-888", edited_at="2026-09-09T11:00:00+00:00",
                                           text="BUY TEST — corrected stop 95")
    assert res["ok"] and res["ingested"] is True
    assert svc.extractor.calls == 1                     # POLICY: no re-extraction
    async with rig.sf() as session:
        row = await session.get(RawContent, out["contentId"])
        evs = (await session.execute(select(Event).where(
            Event.type == "TipMessageRevised"))).scalars().all()
    assert row.meta.get("revisedAt") == "2026-09-09T11:00:00+00:00"
    assert evs and evs[-1].payload.get("messageId") == "m-888"
