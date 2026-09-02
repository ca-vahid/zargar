"""EM method ingestion (INGESTION-PLAN.md): gateway forwards ONLY the EM channel
set to EM's inbox without touching the tip path; the service dedupes, detects
video links, hands them to the worker, turns transcripts into an extraction
(LLM stubbed) and a deterministic board check; the API wires it. EM-only."""
import asyncio

import pytest

from .test_technique_walkforward import rig  # noqa: F401 - the technique rig fixture (tests is a package)
from zargar.tools.discord_gateway import Gateway


# ----------------------------------------------------------------- gateway routing
def _gw(tmp_path, em: dict, tip_watch: dict):
    gw = Gateway("tok", "http://x", "sess", tmp_path / "log.jsonl",
                 ingest=True, dump=False, bots_only=False, author_id="", channel_id="")
    gw._watch = tip_watch
    gw._em = em
    fwd, mirrored, ingested = [], [], []

    async def fake_fwd(http, headers, msg, entry):
        fwd.append((msg["id"], entry.get("label")))

    async def fake_mirror(http, headers, records):
        mirrored.extend(records)

    async def fake_ingest(http, headers, msg, source_name):
        ingested.append(source_name)
        return {"ok": True}

    gw._em_forward = fake_fwd
    gw._mirror = fake_mirror
    gw._ingest_message = fake_ingest
    return gw, fwd, mirrored, ingested


def _msg(cid: str, text: str = "watch NVDA below 216.21") -> dict:
    return {"id": "555", "channel_id": cid, "guild_id": "836435995854897193",
            "author": {"id": "1", "username": "em", "bot": False}, "content": text,
            "attachments": [], "embeds": [], "timestamp": "2026-09-01T13:00:00+00:00"}


def test_em_channel_forwards_to_em_inbox_and_never_touches_tips(tmp_path):
    em = {"em1": {"channelId": "em1", "label": "em-alerts"}}
    gw, fwd, mirrored, ingested = _gw(tmp_path, em, tip_watch={})
    asyncio.run(gw._on_message(_msg("em1"), None, {}))
    assert fwd == [("555", "em-alerts")]
    assert mirrored == [] and ingested == []          # not a tip channel: tip path untouched


def test_channel_in_both_sets_feeds_both_independently(tmp_path):
    em = {"c9": {"channelId": "c9", "label": "watchlists"}}
    tip = {"c9": {"channelId": "c9", "sourceName": "eva", "enabled": True}}
    gw, fwd, mirrored, ingested = _gw(tmp_path, em, tip)
    asyncio.run(gw._on_message(_msg("c9"), None, {}))
    assert len(fwd) == 1 and len(mirrored) == 1 and ingested == ["eva"]


def test_non_em_channel_is_not_forwarded(tmp_path):
    gw, fwd, _, _ = _gw(tmp_path, {"em1": {"channelId": "em1"}}, {})
    asyncio.run(gw._on_message(_msg("other"), None, {}))
    assert fwd == []


# ----------------------------------------------------------------- service + API
VIDEO_MSG = {"id": "900001", "channelId": "1126325195301462117", "channelName": "em-alerts",
             "author": "EnhancedMarket", "text": "TOP SETUPS live now https://x.com/i/broadcasts/1DxLdZekNdRxm",
             "images": [], "postedAt": "2026-09-01T13:02:00+00:00"}


async def test_video_message_becomes_pending_note_and_dedupes(rig):
    ing = rig.svc.ingest
    d = await ing.store_message(dict(VIDEO_MSG))
    assert d["kind"] == "video" and d["status"] == "pending_transcript" and d["duplicate"] is False
    assert d["mediaUrl"] == "https://x.com/i/broadcasts/1DxLdZekNdRxm"
    again = await ing.store_message(dict(VIDEO_MSG))
    assert again["duplicate"] is True and again["id"] == d["id"]
    pend = await ing.pending()
    assert [p["id"] for p in pend] == [d["id"]] and pend[0]["mediaUrl"] == d["mediaUrl"]


async def test_transcript_drives_extraction_and_board_check(rig, monkeypatch):
    ing = rig.svc.ingest
    await rig.eng.settings.set("techniques.enhanced_market.ingest.auto_extract", False, journal=False)
    d = await ing.store_message(dict(VIDEO_MSG))

    async def fake_llm(source, body):
        assert "TEST" in body
        return {"summary": "gap down, cautious", "stance": "cautious",
                "symbols": ["TEST", "$SPX", "the", "ZZZZ"],     # noise gets cleaned
                "board": ["TEST | long | trigger: hold the level | target: next zone | note: contracts ok"],
                "claims": ["enters continuation on a break of the prior-day low"], "vetoes": ["earnings gaps"]}
    monkeypatch.setattr(ing, "_llm_extract", fake_llm)

    t = await ing.store_transcript(d["id"], transcript="[0:01] TEST looks good above the level", meta={"model": "small"})
    assert t["status"] == "transcribed" and t["meta"]["model"] == "small"
    e = await ing.extract(d["id"])
    assert e["status"] == "extracted"
    assert e["extraction"]["symbols"] == ["TEST", "ZZZZ"]        # SPX and 'the' dropped
    assert e["extraction"]["claims"] == ["enters continuation on a break of the prior-day low"]

    # the rig serves synthetic bars for ANY symbol, so make ZZZZ's plan come back
    # with only R2-rejected triggers - the branch that explains "why not" to the user
    real_analyze = ing.technique.analyze

    async def analyze_or_reject(sym, **kw):
        if sym != "ZZZZ":
            return await real_analyze(sym, **kw)
        return {"id": "zzzz-run", "result": {"plan": {"triggers": [
            {"id": "d1", "kind": "breakdown", "valid": False, "levelPrice": 216.21, "riskReward": 0.68,
             "noTradeReasons": ["R2 reward:risk 0.68 to TP3 below 3.0"]}]}}}
    monkeypatch.setattr(ing.technique, "analyze", analyze_or_reject)

    b = await ing.board_check(d["id"])
    rows = {r["symbol"]: r for r in b["boardCheck"]["rows"]}
    assert b["status"] == "checked" and b["boardCheck"]["counts"] == {"armed": 0, "new": 1, "rejected": 1, "error": 0}
    # TEST has a valid plan in the synthetic market -> a fresh run the user can arm
    assert rows["TEST"]["status"] == "new" and rows["TEST"]["runId"] and rows["TEST"]["grade"]
    # ZZZZ: our gates said no, and the row says which trigger and why (the R2 story)
    assert rows["ZZZZ"]["status"] == "rejected" and "R2" in rows["ZZZZ"]["reason"] and "216.21" in rows["ZZZZ"]["reason"]
    latest = await ing.latest_board()
    assert latest["id"] == d["id"]


async def test_transcribe_failures_retry_then_fail_loudly(rig):
    ing = rig.svc.ingest
    await rig.eng.settings.set("techniques.enhanced_market.ingest.transcribe_max_attempts", 2, journal=False)
    d = await ing.store_message({**VIDEO_MSG, "id": "900002"})
    r1 = await ing.store_transcript(d["id"], error="still live")
    assert r1["status"] == "pending_transcript" and r1["meta"]["attempts"] == 1
    r2 = await ing.store_transcript(d["id"], error="still live")
    assert r2["status"] == "failed" and r2["error"] == "still live"
    assert await ing.pending() == [] or all(p["id"] != d["id"] for p in await ing.pending())


async def test_ingest_api_round_trip(rig):
    c = rig.client
    ch = (await c.get("/api/technique/ingest/channels")).json()
    assert ch["enabled"] is True and any(x["label"] == "em-alerts" for x in ch["channels"])
    r = await c.post("/api/technique/ingest/message", json={**VIDEO_MSG, "id": "900003"})
    assert r.status_code == 200 and r.json()["status"] == "pending_transcript"
    nid = r.json()["id"]
    pend = (await c.get("/api/technique/ingest/pending")).json()["notes"]
    assert any(p["id"] == nid for p in pend)
    notes = (await c.get("/api/technique/ingest/notes?limit=5")).json()
    assert notes and notes[0]["id"] == nid
    one = (await c.get(f"/api/technique/ingest/notes/{nid}")).json()
    assert one["kind"] == "video"
    miss = await c.post("/api/technique/ingest/transcript", json={"noteId": "nope", "transcript": "x"})
    assert miss.status_code == 404
