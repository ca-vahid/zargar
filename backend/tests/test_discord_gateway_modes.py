"""Gateway channel modes (KNOWLEDGE plan C1): a `context` channel is mirrored
but NEVER auto-ingested as tips; a `tips` channel does both. Pure-logic tests —
the Gateway object is driven directly, network calls stubbed."""
import asyncio

from zargar.tools.discord_gateway import Gateway


def make_gateway(tmp_path, watch: dict) -> tuple[Gateway, list, list]:
    gw = Gateway("tok", "http://x", "sess", tmp_path / "log.jsonl",
                 ingest=True, dump=False, bots_only=False,
                 author_id="", channel_id="")
    gw._watch = watch
    mirrored: list = []
    ingested: list = []

    async def fake_mirror(http, headers, records):
        mirrored.extend(records)

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


def test_context_channel_mirrors_but_never_ingests(tmp_path):
    watch = {"c1": {"channelId": "c1", "sourceName": "trading-floor",
                    "guildName": "OWLS", "enabled": True, "mode": "context"}}
    gw, mirrored, ingested = make_gateway(tmp_path, watch)
    asyncio.run(gw._on_message(msg_for("c1"), None, {}))
    assert len(mirrored) == 1 and mirrored[0]["source"] == "trading-floor"
    assert ingested == []


def test_tips_channel_mirrors_and_ingests(tmp_path):
    watch = {"c2": {"channelId": "c2", "sourceName": "eva",
                    "guildName": "OWLS", "enabled": True}}   # no mode = tips
    gw, mirrored, ingested = make_gateway(tmp_path, watch)
    asyncio.run(gw._on_message(msg_for("c2"), None, {}))
    assert len(mirrored) == 1
    assert len(ingested) == 1 and ingested[0][1] == "eva"


def test_unwatched_channel_is_ignored(tmp_path):
    gw, mirrored, ingested = make_gateway(tmp_path, {})
    asyncio.run(gw._on_message(msg_for("c3"), None, {}))
    assert mirrored == [] and ingested == []
