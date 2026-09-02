"""EM ingestion, the unattended-morning behaviors (INGESTION-PLAN "morning flow"):
a still-live broadcast is DEFERRED (no attempt spent) until it ends, then taken
whole - or partially after the max wait; the same link re-posted within a day
is one video; only setup material earns a board check; the day's view keeps the
video brief primary with follow-ups listed, never replaced; the gateway surfaces
embed / attachment URLs so link detection sees them. EM-only."""
import asyncio

from .test_technique_walkforward import rig  # noqa: F401 - the technique rig fixture
from zargar.tools.discord_gateway import Gateway

VIDEO = {"id": "m-video", "channelId": "1126325195301462117", "channelName": "em-alerts", "author": "EnhancedMarket",
         "text": "TOP SETUPS live https://x.com/i/broadcasts/1DxLdZekNdRxm", "images": [], "postedAt": "2026-09-02T13:01:00+00:00"}


async def test_live_broadcast_is_deferred_without_spending_attempts(rig):
    ing = rig.svc.ingest
    await rig.eng.settings.set("techniques.enhanced_market.ingest.transcribe_max_attempts", 2, journal=False)
    await rig.eng.settings.set("techniques.enhanced_market.ingest.live_recheck_seconds", 60, journal=False)
    d = await ing.store_message(dict(VIDEO))
    # five deferrals would have exhausted a 2-attempt budget if they counted as failures
    for i in range(5):
        r = await ing.store_transcript(d["id"], deferred=True, error="broadcast still live")
        assert r["status"] == "pending_transcript" and r["meta"]["deferrals"] == i + 1
        assert int(r["meta"].get("attempts") or 0) == 0
    assert r["meta"]["firstSeenLiveAt"] and r["meta"]["nextCheckAt"]
    # hidden from the worker until nextCheckAt (60 s away)
    assert all(p["id"] != d["id"] for p in await ing.pending())
    # ... and offered again, flagged for a partial take, once the max wait has passed
    await rig.eng.settings.set("techniques.enhanced_market.ingest.live_max_wait_minutes", 0, journal=False)
    await rig.eng.settings.set("techniques.enhanced_market.ingest.live_recheck_seconds", 0, journal=False)
    r = await ing.store_transcript(d["id"], deferred=True, error="still live")   # re-stamps nextCheckAt = now
    pend = [p for p in await ing.pending() if p["id"] == d["id"]]
    assert pend and pend[0]["forcePartial"] is True and pend[0]["deferrals"] == 6


async def test_same_link_reposted_is_one_video(rig):
    ing = rig.svc.ingest
    first = await ing.store_message(dict(VIDEO))
    echo = await ing.store_message({**VIDEO, "id": "m-echo", "author": "AlertsBot", "text": "pinned: https://x.com/i/broadcasts/1DxLdZekNdRxm"})
    assert echo["duplicate"] is False and echo["status"] == "duplicate" and echo["meta"]["duplicateOf"] == first["id"]
    ids = [p["id"] for p in await ing.pending()]
    assert first["id"] in ids and echo["id"] not in ids


async def test_only_setup_material_gets_a_board_check_and_today_view_keeps_the_brief(rig, monkeypatch):
    ing = rig.svc.ingest
    calls = []

    async def fake_llm(source, body):
        material = "recap" if "recap" in body else "setups_brief"
        return {"material": material, "summary": f"{material} summary", "stance": "neutral",
                "symbols": ["TEST"], "board": ["TEST | long | trigger: hold | target: next | note: -"],
                "claims": [], "vetoes": []}

    async def fake_check(note_id):
        calls.append(note_id)
        return {"id": note_id}

    monkeypatch.setattr(ing, "_llm_extract", fake_llm)
    monkeypatch.setattr(ing, "board_check", fake_check)
    video = await ing.store_message(dict(VIDEO))
    await ing.store_transcript(video["id"], transcript="[0:01] TEST holds the level, looks good")
    await asyncio.sleep(0.3)                          # the spawned extract task
    recap = await ing.store_message({**VIDEO, "id": "m-recap", "text": "recap of yesterday's trades: " + "x" * 80})
    await asyncio.sleep(0.3)
    assert calls == [video["id"]]                     # the recap was extracted but never plan-checked
    view = await ing.today_board()
    assert view["today"] is True and view["note"]["id"] == video["id"]      # the brief stays primary
    assert [o["id"] for o in view["others"]] == [recap["id"]]
    assert view["others"][0]["extraction"]["material"] == "recap"


def test_gateway_surfaces_embed_and_attachment_urls(tmp_path):
    gw = Gateway("tok", "http://x", "sess", tmp_path / "log.jsonl",
                 ingest=True, dump=False, bots_only=False, author_id="", channel_id="")
    gw._em = {"em1": {"channelId": "em1", "label": "em-alerts"}}
    posted = []

    class FakeResp:
        status_code = 200

        def json(self):
            return {"kind": "video", "status": "pending_transcript"}

    class FakeHttp:
        async def post(self, url, headers=None, json=None, timeout=None):
            posted.append((url, json))
            return FakeResp()

    msg = {"id": "77", "channel_id": "em1", "guild_id": "g", "author": {"id": "1", "username": "em", "bot": True},
           "content": "Live now!", "attachments": [{"url": "https://cdn.example/clip.mp4", "content_type": "video/mp4"}],
           "embeds": [{"title": "TOP SETUPS", "url": "https://x.com/i/broadcasts/1abc"}],
           "timestamp": "2026-09-02T13:00:00+00:00"}
    asyncio.run(gw._em_forward(FakeHttp(), {}, msg, gw._em["em1"]))
    assert posted and posted[0][0].endswith("/api/technique/ingest/message")
    text = posted[0][1]["text"]
    assert "https://x.com/i/broadcasts/1abc" in text and "https://cdn.example/clip.mp4" in text
    assert posted[0][1]["channelName"] == "em-alerts"
