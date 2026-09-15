"""Gateway channel modes (KNOWLEDGE plan C1): a `context` channel is mirrored
but NEVER auto-ingested as tips; a `tips` channel does both; an unwatched
channel is ignored. Pure-logic tests — the Gateway object is driven through
its real envelope path (`_enqueue` -> ledger + queue -> `_deliver`), the way
the socket worker delivers a MESSAGE_CREATE; network calls are stubbed.
(The pre-envelope `_on_message` entry point these tests once called was
removed with the durable ledger, 2026-09-09.)"""
import asyncio

from zargar.tools.discord_gateway import Gateway


def make_gateway(tmp_path, watch: dict) -> tuple[Gateway, list, list]:
    gw = Gateway("tok", "http://x", "sess", tmp_path / "log.jsonl",
                 ingest=True, dump=False, bots_only=False,
                 author_id="", channel_id="")
    gw._watch = watch
    gw._queue = asyncio.Queue(10)
    mirrored: list = []
    ingested: list = []

    async def fake_mirror(http, headers, records):
        mirrored.extend(records)
        return True

    async def fake_ingest(http, headers, msg, source_name):
        ingested.append((msg, source_name))
        return {"ok": True}

    gw._mirror = fake_mirror
    gw._ingest_message = fake_ingest
    return gw, mirrored, ingested


def msg_for(channel_id: str) -> dict:
    return {"id": "111", "channel_id": channel_id, "guild_id": "9",
            "author": {"id": "42", "username": "chatter", "bot": False},
            "content": "SPY looking heavy into the close", "attachments": [],
            "embeds": [], "timestamp": "2026-08-30T14:00:00+00:00"}


async def deliver_one(gw: Gateway) -> bool:
    """Receive-path enqueue already happened; run the worker's single delivery
    attempt on the envelope it produced. Returns the ACK verdict."""
    env = gw._queue.get_nowait()
    return await gw._deliver(None, {}, env)


async def test_context_channel_mirrors_but_never_ingests(tmp_path):
    watch = {"c1": {"channelId": "c1", "sourceName": "trading-floor",
                    "guildName": "OWLS", "enabled": True, "mode": "context"}}
    gw, mirrored, ingested = make_gateway(tmp_path, watch)
    gw._enqueue("create", msg_for("c1"))
    assert await deliver_one(gw) is True                  # mirrored-only still ACKs
    assert len(mirrored) == 1 and mirrored[0]["source"] == "trading-floor"
    assert ingested == []
    assert gw._store.counts() == (0, 0)                   # ledger entry acknowledged


async def test_tips_channel_mirrors_and_ingests(tmp_path):
    watch = {"c2": {"channelId": "c2", "sourceName": "eva",
                    "guildName": "OWLS", "enabled": True}}   # no mode = tips
    gw, mirrored, ingested = make_gateway(tmp_path, watch)
    gw._enqueue("create", msg_for("c2"))
    assert await deliver_one(gw) is True
    assert len(mirrored) == 1
    assert len(ingested) == 1 and ingested[0][1] == "eva"
    assert gw._store.counts() == (0, 0)


async def test_unwatched_channel_is_ignored(tmp_path):
    gw, mirrored, ingested = make_gateway(tmp_path, {})
    gw._enqueue("create", msg_for("c3"))
    assert gw._queue.empty()                              # never enveloped
    assert gw._store.counts() == (0, 0)                   # never accepted into the ledger
    assert mirrored == [] and ingested == []
