"""Mixed caption/image evidence must survive ingestion. Fake extraction only."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.domain import new_id
from zargar.models import ChatAsset, RawContent
from zargar.signals.schemas import ExtractionResult

from .test_proposal_fresh_retry import rig as rig  # noqa: PLC0414


async def test_caption_remains_in_grounding_corpus_when_image_is_transcribed(rig, monkeypatch):
    asset_id, content_id = new_id(), new_id()
    caption = "Added NVDA today in a small allocation."
    transcript = "Broker account summary."
    async with rig.sf() as session:
        session.add(ChatAsset(id=asset_id, thread_id=None, media_type="image/png", data=b"offline-stub", meta={}))
        session.add(RawContent(id=content_id, source_type="manual", source_name="OfflineSource",
            body_text=caption, meta={"imageAssetId": asset_id}))
        await session.commit()
    rig.signals_service.extractor = NS(available=True, model="offline", extract=AsyncMock(
        return_value=ExtractionResult(signals=[], source_type="other", source_transcript=transcript)))
    handle = AsyncMock(return_value=[])
    monkeypatch.setattr(rig.signals_service, "handle_extraction", handle)
    monkeypatch.setattr(rig.signals_service, "_source_has_open_items", AsyncMock(return_value=False))
    await rig.signals_service.process_content(content_id)
    evidence = handle.call_args.kwargs["source_text"]
    assert caption in evidence and transcript in evidence, evidence


async def test_manifest_names_unprocessed_attachment_count(rig, monkeypatch):
    """Coverage manifest (Codex critique 4, 2026-09-11): intake processes the
    FIRST image only — the grounding corpus must say so instead of implying
    full coverage."""
    asset_id, content_id = new_id(), new_id()
    async with rig.sf() as session:
        session.add(ChatAsset(id=asset_id, thread_id=None, media_type="image/png",
                              data=b"offline-stub", meta={}))
        session.add(RawContent(id=content_id, source_type="manual",
                               source_name="OfflineSource", body_text="caption here",
                               meta={"imageAssetId": asset_id, "imageCount": 3}))
        await session.commit()
    rig.signals_service.extractor = NS(available=True, model="offline", extract=AsyncMock(
        return_value=ExtractionResult(signals=[], source_type="other",
                                      source_transcript="chart words")))
    handle = AsyncMock(return_value=[])
    monkeypatch.setattr(rig.signals_service, "handle_extraction", handle)
    monkeypatch.setattr(rig.signals_service, "_source_has_open_items",
                        AsyncMock(return_value=False))
    await rig.signals_service.process_content(content_id)
    evidence = handle.call_args.kwargs["source_text"]
    assert "attachment 1 of 3 processed" in evidence, evidence


async def test_truncated_reply_gets_a_bigger_repair_window():
    """RKLB run abd015d4 (2026-09-11): stops [tool_use, max_tokens, max_tokens]
    — the JSON never finished and the repair was starved at the same cap. A
    max_tokens stop must double the next turn's output room."""
    from zargar.techniques.tip import analyst
    from zargar.techniques.tip.analyst import run_agent_loop
    caps = []

    class _Client:
        class messages:
            @staticmethod
            async def create(**kw):
                caps.append(kw["max_tokens"])
                if len(caps) == 1:
                    return NS(stop_reason="max_tokens", usage=None,
                              content=[NS(type="text", text="truncated reasoning without JSO")])
                return NS(stop_reason="end_turn", usage=None,
                          content=[NS(type="text", text='{"verdict":"skip"}')])
    rec = NS(step=lambda *a, **k: None)
    state = {}
    import unittest.mock as _m
    with _m.patch.object(analyst, "_persist_run", AsyncMock()):
        # first pass returns the truncated text (no tool calls -> loop exits);
        # the caller's repair re-enters with the SAME state, where the recorded
        # max_tokens stop earns the doubled output window
        text1 = await run_agent_loop(NS(), _Client(), model="offline", system="s",
                                     header="h", rec=rec, run_id="offline", max_tools=2,
                                     tool_ctx={}, tools_used=[], state=state)
        assert "JSO" in text1 and caps == [3000]
        text2 = await run_agent_loop(NS(), _Client(), model="offline", system="s",
                                     header="h", rec=rec, run_id="offline", max_tools=2,
                                     tool_ctx={}, tools_used=[], state=state)
    assert text2 == '{"verdict":"skip"}'
    assert caps == [3000, 6000], caps
