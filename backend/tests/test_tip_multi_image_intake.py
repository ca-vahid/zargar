"""Multi-image intake (KFIN-07, 2026-09-14): stable attachment ids and order,
per-image coverage status + transcript, per-block grounding (caption or ONE
attachment id), explicit conflicts (recorded, never blended), explicit
missing/failed/over-budget images, dedupe + revision policy. No LLM call is
ever made: the extractor is a stub that returns canned transcripts/results."""
import base64
from types import SimpleNamespace as NS

import httpx
from sqlalchemy import select

from zargar.api.app import create_app
from zargar.domain import new_id
from zargar.models import ChatAsset, Event, RawContent, Signal
from zargar.signals.extraction import (
    ATT_ABSENT, ATT_FAILED, ATT_PROCESSED, ATT_SKIPPED, ATT_UNREADABLE,
    build_grounding_corpus, detect_attachment_conflicts, ground_signal)
from zargar.signals.schemas import ExtractionResult, TradeSignal
from zargar.tools.discord_gateway import (
    MAX_INGEST_ATTACHMENTS, Gateway, collect_attachments, collect_images,
    fetch_attachments_for_ingest)

from .conftest import make_test_config
from .test_api_and_pipeline import wait_quote
from .test_proposal_fresh_retry import rig as rig  # noqa: PLC0414

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64          # sniffs as image/png
CHART = "SPY daily chart — support 640, resistance 655"
TICKET = "BTO AAPL 230c 10/17 @ 2.10"
CAPTION = "AAPL setup for the week"


def _sig(strike: float, quotes: list[str], premium: float = 2.10) -> TradeSignal:
    return TradeSignal(ticker="AAPL", direction="long", action="open", instrument="call",
                       strike=strike, premium=premium, expiry="2026-10-17",
                       thesis_summary="Calls.", evidence_quotes=quotes,
                       confidence="explicit_call", is_actionable=True)


class _Extractor:
    """Canned transcripts keyed by attachment id; the primary image's
    transcript rides the extraction read (as the real call does)."""
    available = True
    model = "offline"

    def __init__(self, transcripts: dict[str, str], result: ExtractionResult,
                 fail: set[str] = frozenset()):
        self.transcripts, self.result, self.fail = transcripts, result, set(fail)
        self.extract_calls: list[dict] = []
        self.transcribe_calls: list[str] = []

    @staticmethod
    def _aid(label: str) -> str:
        return label.split("(id ")[1].rstrip(")") if "(id " in label else label

    async def transcribe(self, image, *, label="", is_retry=False):
        self.transcribe_calls.append(label)
        aid = self._aid(label)
        if aid in self.fail:
            raise RuntimeError("vision provider exploded")
        return self.transcripts[aid]

    async def extract(self, text, **kw):
        self.extract_calls.append({"text": text, **kw})
        r = self.result.model_copy(deep=True)
        if kw.get("image") is not None:
            aid = self._aid(kw.get("image_label") or "") or next(iter(self.transcripts))
            r.source_transcript = self.transcripts.get(aid)
        return r


async def _events(rig, kind: str, content_id: str) -> list[Event]:
    async with rig.sf() as session:
        return list((await session.execute(
            select(Event).where(Event.type == kind, Event.aggregate_id == content_id)
        )).scalars())


async def _fast(rig):
    await rig.settings.set("techniques.tip.quote_wait_seconds", 0.5)
    await rig.settings.set("verification.max_price_deviation_pct", 100.0)
    await wait_quote(rig, "AAPL")


# ------------------------------------------------------------- pure grounding
def test_evidence_only_in_image_two_grounds_to_attachment_two():
    text, blocks = build_grounding_corpus(CAPTION, [
        {"id": "1001", "status": ATT_PROCESSED, "transcript": CHART},
        {"id": "1002", "status": ATT_PROCESSED, "transcript": TICKET}])
    assert "--- attachment 1 of 2 processed (id 1001)" in text
    assert "--- attachment 2 of 2 processed (id 1002)" in text
    g = ground_signal(_sig(230.0, [TICKET]), text, blocks)
    assert g["passed"] and g["checks"]["strike_evidenced"]
    assert g["quoteSources"] == {TICKET: "attachment:1002"}
    assert g["evidenceBlocks"] == ["attachment:1002"]


def test_caption_and_attachment_evidence_coexist():
    text, blocks = build_grounding_corpus(CAPTION, [
        {"id": "1001", "status": ATT_PROCESSED, "transcript": TICKET}])
    g = ground_signal(_sig(230.0, [CAPTION, TICKET]), text, blocks)
    assert g["passed"]
    assert g["quoteSources"] == {CAPTION: "caption", TICKET: "attachment:1001"}
    assert g["evidenceBlocks"] == ["caption", "attachment:1001"]


def test_unprocessed_attachment_is_never_evidence():
    """A quote that only matches an unprocessed block (or its header line)
    stays ungrounded — the manifest says so, the corpus does not pretend."""
    text, blocks = build_grounding_corpus("", [
        {"id": "1001", "status": ATT_PROCESSED, "transcript": CHART},
        {"id": "1002", "status": ATT_FAILED, "error": "image fetch HTTP 404",
         "transcript": TICKET}])           # a stale transcript on a failed entry is ignored
    assert TICKET not in text and "attachment 2 of 2 failed (id 1002) NOT PROCESSED" in text
    g = ground_signal(_sig(230.0, [TICKET]), text, blocks)
    assert not g["passed"] and g["failedQuotes"] == [TICKET] and g["evidenceBlocks"] == []
    g2 = ground_signal(_sig(230.0, ["attachment 2 of 2 failed"]), text, blocks)
    assert not g2["passed"]                # header lines are not evidence either


def test_conflicting_documents_are_flagged_not_chosen():
    text, blocks = build_grounding_corpus("", [
        {"id": "1001", "status": ATT_PROCESSED, "transcript": TICKET},
        {"id": "1002", "status": ATT_PROCESSED, "transcript": "BTO AAPL 240c 10/17 @ 1.50"}])
    sigs = [_sig(230.0, [TICKET]), _sig(240.0, ["BTO AAPL 240c 10/17 @ 1.50"], premium=1.50)]
    gs = [ground_signal(s, text, blocks) for s in sigs]
    assert all(g["passed"] for g in gs)
    conflicts = detect_attachment_conflicts(sigs, gs)
    assert [c["field"] for c in conflicts] == ["strike", "premium"]
    assert conflicts[0]["values"] == [{"blocks": ["attachment:1001"], "value": 230.0},
                                      {"blocks": ["attachment:1002"], "value": 240.0}]
    assert all(not g["passed"] and g["checks"]["attachments_consistent"] is False
               and g["conflict"] for g in gs)
    # the same values in two documents (a re-posted screenshot) is not a conflict
    same = [_sig(230.0, [TICKET]), _sig(230.0, ["BTO AAPL 230c"])]
    text2, blocks2 = build_grounding_corpus("", [
        {"id": "1", "status": ATT_PROCESSED, "transcript": TICKET},
        {"id": "2", "status": ATT_PROCESSED, "transcript": "BTO AAPL 230c"}])
    gs2 = [ground_signal(s, text2, blocks2) for s in same]
    assert detect_attachment_conflicts(same, gs2) == [] and all(g["passed"] for g in gs2)


# ------------------------------------------------------------- intake path
async def test_second_image_ticker_grounds_to_attachment_two_through_intake(rig):
    await _fast(rig)
    svc = rig.signals_service
    svc.extractor = _Extractor({"1001": CHART, "1002": TICKET},
                               ExtractionResult(signals=[_sig(230.0, [CAPTION, TICKET])],
                                                source_type="trade_alert"))
    out = await svc.ingest_manual(
        CAPTION, source_name="OfflineSource", message_id="mi-1",
        posted_at="2026-09-14T14:00:00+00:00",
        attachments=[{"id": "1001", "filename": "chart.png", "data": PNG},
                     {"id": "1002", "filename": "ticket.png", "data": PNG}])
    assert out["status"] == "extracted" and len(out["signals"]) == 1
    # one paid read for the primary image + one transcription for image two
    assert len(svc.extractor.extract_calls) == 1
    assert svc.extractor.transcribe_calls == ["attachment 2 of 2 (id 1002)"]
    call = svc.extractor.extract_calls[0]
    assert call["image_label"] == "attachment 1 of 2 (id 1001)"
    assert "--- attachment 2 of 2 processed (id 1002)" in call["attachments_text"]
    assert TICKET in call["attachments_text"]
    g = out["signals"][0]["signal"]["extraction"]["grounding"]
    assert g["passed"]
    assert g["quoteSources"] == {CAPTION: "caption", TICKET: "attachment:1002"}
    assert g["evidenceBlocks"] == ["caption", "attachment:1002"]
    async with rig.sf() as session:
        row = await session.get(RawContent, out["contentId"])
    manifest = row.meta["attachments"]
    assert [(a["id"], a["n"], a["status"]) for a in manifest] == [
        ("1001", 1, ATT_PROCESSED), ("1002", 2, ATT_PROCESSED)]
    assert manifest[0]["transcript"] == CHART and manifest[1]["transcript"] == TICKET
    assert row.meta["visionCalls"] == 2 and row.meta["imageCount"] == 2
    evs = await _events(rig, "TipAttachmentsProcessed", out["contentId"])
    assert len(evs) == 1 and [a["status"] for a in evs[0].payload["attachments"]] == [
        ATT_PROCESSED, ATT_PROCESSED]


async def test_contradictory_images_stay_explicit_no_blended_claim(rig):
    await _fast(rig)
    svc = rig.signals_service
    other = "BTO AAPL 240c 10/17 @ 1.50"
    svc.extractor = _Extractor(
        {"2001": TICKET, "2002": other},
        ExtractionResult(signals=[_sig(230.0, [TICKET]), _sig(240.0, [other], premium=1.50)],
                         source_type="trade_alert"))
    out = await svc.ingest_manual(
        "", source_name="OfflineSource", message_id="mi-2",
        attachments=[{"id": "2001", "data": PNG}, {"id": "2002", "data": PNG}])
    assert out["status"] == "extracted" and len(out["signals"]) == 2
    for item in out["signals"]:
        sig = item["signal"]
        g = sig["extraction"]["grounding"]
        assert g["conflict"] and g["passed"] is False
        assert sig["status"] == "verification_failed"
        failed = [c["name"] for c in sig["verification"]["checks"] if not c["passed"]]
        assert "attachments_consistent" in failed
        assert item["proposal"] is None and not item.get("duplicateOf")
    strikes = sorted(i["signal"]["strike"] for i in out["signals"])
    assert strikes == [230.0, 240.0]           # both readings kept, neither chosen
    evs = await _events(rig, "TipAttachmentConflict", out["contentId"])
    assert {e.payload["field"] for e in evs} == {"strike", "premium"}
    assert evs[0].payload["values"][0]["blocks"] == ["attachment:2001"]
    assert evs[0].payload["values"][1]["blocks"] == ["attachment:2002"]


async def test_missing_failed_unreadable_and_over_budget_images_stay_explicit(rig):
    await _fast(rig)
    await rig.settings.set("techniques.tip.intake_max_images", 2)
    svc = rig.signals_service
    svc.extractor = _Extractor({"3001": TICKET, "3005": CHART},
                               ExtractionResult(signals=[_sig(230.0, [TICKET])],
                                                source_type="trade_alert"),
                               fail={"3005"})
    out = await svc.ingest_manual(
        "caption", source_name="OfflineSource", message_id="mi-3",
        attachments=[
            {"id": "3001", "data": PNG},                                  # processed (primary)
            {"id": "3002", "status": "failed", "error": "image fetch HTTP 404"},  # gateway failure
            {"id": "3003"},                                               # never delivered
            {"id": "3004", "data": b"this is not an image at all"},      # undecodable bytes
            {"id": "3005", "data": PNG},                                  # transcription blows up
            {"id": "3006", "data": PNG},                                  # beyond intake_max_images
        ])
    assert out["status"] == "extracted"
    async with rig.sf() as session:
        row = await session.get(RawContent, out["contentId"])
    manifest = row.meta["attachments"]
    assert [(a["id"], a["status"]) for a in manifest] == [
        ("3001", ATT_PROCESSED), ("3002", ATT_FAILED), ("3003", ATT_ABSENT),
        ("3004", ATT_UNREADABLE), ("3005", ATT_FAILED), ("3006", ATT_SKIPPED)]
    assert manifest[1]["error"] == "image fetch HTTP 404"
    assert "transcription failed" in manifest[4]["error"]
    assert "intake_max_images=2" in manifest[5]["error"]
    assert "unsupported image format" in manifest[3]["error"]
    assert all(not a.get("transcript") for a in manifest[1:])
    # only two images were ever stored; the rest never became assets
    async with rig.sf() as session:
        stored = list((await session.execute(select(ChatAsset.meta))).scalars())
    assert sorted(m.get("attachmentId") for m in stored if m.get("kind") == "tip_screenshot") == [
        "3001", "3005"]
    corpus = svc.extractor.extract_calls[0]["attachments_text"]
    for line in ("attachment 2 of 6 failed (id 3002) NOT PROCESSED",
                 "attachment 3 of 6 absent (id 3003) NOT PROCESSED",
                 "attachment 4 of 6 unreadable (id 3004) NOT PROCESSED",
                 "attachment 5 of 6 failed (id 3005) NOT PROCESSED",
                 "attachment 6 of 6 skipped-over-budget (id 3006) NOT PROCESSED"):
        assert line in corpus, corpus
    assert CHART not in corpus                  # the failed transcription is not evidence
    g = out["signals"][0]["signal"]["extraction"]["grounding"]
    assert g["passed"] and g["evidenceBlocks"] == ["attachment:3001"]


async def test_vision_call_budget_bounds_paid_transcriptions(rig):
    await _fast(rig)
    await rig.settings.set("techniques.tip.intake_vision_calls_per_message", 2)
    svc = rig.signals_service
    svc.extractor = _Extractor({"4001": CHART, "4002": TICKET, "4003": "x", "4004": "y"},
                               ExtractionResult(signals=[], source_type="other"))
    out = await svc.ingest_manual(
        "four charts", source_name="OfflineSource", message_id="mi-4",
        attachments=[{"id": str(4000 + i), "data": PNG} for i in range(1, 5)])
    assert out["status"] == "extracted"
    assert len(svc.extractor.extract_calls) == 1
    assert svc.extractor.transcribe_calls == ["attachment 2 of 4 (id 4002)"]
    async with rig.sf() as session:
        row = await session.get(RawContent, out["contentId"])
    assert [a["status"] for a in row.meta["attachments"]] == [
        ATT_PROCESSED, ATT_PROCESSED, ATT_SKIPPED, ATT_SKIPPED]
    assert "intake_vision_calls_per_message=2" in row.meta["attachments"][2]["error"]
    assert row.meta["visionCalls"] == 2


async def test_duplicate_delivery_does_not_repeat_extraction_or_transcription(rig):
    await _fast(rig)
    svc = rig.signals_service
    svc.extractor = _Extractor({"5001": CHART, "5002": TICKET},
                               ExtractionResult(signals=[_sig(230.0, [TICKET])],
                                                source_type="trade_alert"))
    atts = [{"id": "5001", "data": PNG}, {"id": "5002", "data": PNG}]
    out1 = await svc.ingest_manual("dup me", source_name="OfflineSource",
                                   message_id="mi-5", attachments=atts)
    assert out1["status"] == "extracted"
    out2 = await svc.ingest_manual("dup me", source_name="OfflineSource",
                                   message_id="mi-5", attachments=atts)
    assert out2["duplicate"] is True and out2["contentId"] == out1["contentId"]
    assert len(svc.extractor.extract_calls) == 1
    assert len(svc.extractor.transcribe_calls) == 1
    async with rig.sf() as session:
        n_assets = len([m for m in (await session.execute(select(ChatAsset.meta))).scalars()
                        if m.get("attachmentId") in ("5001", "5002")])
        n_content = len(list((await session.execute(select(RawContent.id).where(
            RawContent.meta.op('->>')('messageId') == "mi-5"))).scalars()))
    assert n_assets == 2 and n_content == 1       # the repeat stored nothing


async def test_edit_of_a_multi_image_message_is_a_revision_never_reextracted(rig):
    await _fast(rig)
    svc = rig.signals_service
    svc.extractor = _Extractor({"6001": CHART, "6002": TICKET},
                               ExtractionResult(signals=[_sig(230.0, [TICKET])],
                                                source_type="trade_alert"))
    out = await svc.ingest_manual("v1", source_name="OfflineSource", message_id="mi-6",
                                  attachments=[{"id": "6001", "data": PNG},
                                               {"id": "6002", "data": PNG}])
    before = (len(svc.extractor.extract_calls), len(svc.extractor.transcribe_calls))
    r = await svc.discord_message_edited("mi-6", edited_at="2026-09-14T15:00:00+00:00",
                                         text="v2 — actually 240c")
    assert r == {"ok": True, "ingested": True}
    assert (len(svc.extractor.extract_calls), len(svc.extractor.transcribe_calls)) == before
    async with rig.sf() as session:
        row = await session.get(RawContent, out["contentId"])
        sig_rows = list((await session.execute(select(Signal).where(
            Signal.raw_content_id == out["contentId"]))).scalars())
    assert row.meta["revisedAt"] == "2026-09-14T15:00:00+00:00"
    assert row.meta["revisionPreview"].startswith("v2")
    assert [a["status"] for a in row.meta["attachments"]] == [ATT_PROCESSED, ATT_PROCESSED]
    assert len(sig_rows) == 1 and sig_rows[0].strike == 230.0     # the record did not move
    assert len(await _events(rig, "TipMessageRevised", out["contentId"])) == 1
    # a repeat of the same revision is idempotent
    assert (await svc.discord_message_edited("mi-6", edited_at="2026-09-14T15:00:00+00:00",
                                             text="v2"))["duplicate"] is True


async def test_legacy_single_image_row_keeps_working_and_lists_the_rest_absent(rig):
    """A row from before the manifest (imageAssetId + imageCount) processes as
    attachment img-1 with the undelivered images explicit as absent."""
    await _fast(rig)
    svc = rig.signals_service
    asset_id, content_id = new_id(), new_id()
    async with rig.sf() as session:
        session.add(ChatAsset(id=asset_id, thread_id=None, media_type="image/png", data=PNG,
                              meta={}))
        session.add(RawContent(id=content_id, source_type="manual", source_name="OfflineSource",
                               body_text="caption", meta={"imageAssetId": asset_id,
                                                          "imageCount": 3}))
        await session.commit()
    svc.extractor = _Extractor({"img-1": TICKET},
                               ExtractionResult(signals=[_sig(230.0, [TICKET])],
                                                source_type="trade_alert"))
    out = await svc.process_content(content_id)
    assert out["status"] == "extracted" and svc.extractor.transcribe_calls == []
    async with rig.sf() as session:
        row = await session.get(RawContent, content_id)
    assert [(a["id"], a["status"]) for a in row.meta["attachments"]] == [
        ("img-1", ATT_PROCESSED), ("img-2", ATT_ABSENT), ("img-3", ATT_ABSENT)]
    g = out["signals"][0]["signal"]["extraction"]["grounding"]
    assert g["evidenceBlocks"] == ["attachment:img-1"]


# ------------------------------------------------------------- API route
async def test_ingest_route_accepts_attachments_and_marks_undecodable_ones(fresh_db):
    from zargar.engine import Engine
    from zargar.signals.service import attach_signal_layer
    config = make_test_config()
    eng = Engine(config)
    await eng.start()
    try:
        await attach_signal_layer(eng)
        await _fast(eng)
        eng.signals_service.extractor = _Extractor(
            {"7001": TICKET}, ExtractionResult(signals=[], source_type="other"))
        app = create_app(config, eng)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test") as client:
            r = await client.post("/api/ingest/manual", json={
                "text": "", "source_name": "OfflineSource", "messageId": "mi-7",
                "attachments": [
                    {"id": "7001", "filename": "a.png", "contentType": "image/png",
                     "dataUrl": "data:image/png;base64," + base64.b64encode(PNG).decode()},
                    {"id": "7002", "filename": "b.png", "contentType": "image/png",
                     "dataUrl": "data:image/png;base64,AAAA"},
                    {"id": "7003", "status": "failed", "error": "image fetch HTTP 403"}]})
        assert r.status_code == 200, r.text
        body = r.json()
        async with eng.sf() as session:
            row = await session.get(RawContent, body["contentId"])
        assert [(a["id"], a["status"]) for a in row.meta["attachments"]] == [
            ("7001", ATT_PROCESSED), ("7002", ATT_UNREADABLE), ("7003", ATT_FAILED)]
        assert row.meta["attachments"][2]["error"] == "image fetch HTTP 403"
    finally:
        await eng.stop()


# ------------------------------------------------------------- gateway side
def _msg(**over) -> dict:
    base = {"id": "900", "channel_id": "c1", "content": "look",
            "author": {"id": "u1", "username": "src"}, "timestamp": "2026-09-14T13:00:00+00:00",
            "attachments": [
                {"id": "a1", "filename": "one.png", "content_type": "image/png",
                 "url": "https://cdn/one.png", "size": 10},
                {"id": "v1", "filename": "clip.mp4", "content_type": "video/mp4",
                 "url": "https://cdn/clip.mp4", "size": 999},
                {"id": "a2", "filename": "two.jpg", "content_type": "image/jpeg",
                 "url": "https://cdn/two.jpg", "size": 20}],
            "embeds": [{"image": {"url": "https://cdn/embed.png"}}]}
    base.update(over)
    return base


def test_collect_attachments_keeps_stable_ids_and_message_order():
    atts = collect_attachments(_msg())
    assert [(a["id"], a["kind"]) for a in atts] == [
        ("a1", "attachment"), ("a2", "attachment"), ("embed-1-image", "embed")]
    assert collect_images(_msg()) == ["https://cdn/one.png", "https://cdn/two.jpg",
                                      "https://cdn/embed.png"]


class _Http:
    """200 for *.png/*.jpg, 404 for 'missing', exception for 'boom', oversize for 'huge'."""
    def __init__(self):
        self.posted: list[dict] = []

    async def get(self, url, timeout=None):
        if "missing" in url:
            return NS(status_code=404, content=b"", headers={})
        if "boom" in url:
            raise RuntimeError("connection reset")
        if "huge" in url:
            return NS(status_code=200, content=b"\x00" * (8 * 1024 * 1024 + 1),
                      headers={"content-type": "image/png"})
        return NS(status_code=200, content=PNG, headers={"content-type": "image/png"})

    async def post(self, url, headers=None, json=None, timeout=None):
        self.posted.append({"url": url, "json": json})
        return NS(status_code=200, json=lambda: {"contentId": "c", "status": "extracted",
                                                  "signals": [], "intakeRunId": "r"})


async def test_fetch_attachments_for_ingest_records_every_outcome():
    atts = [{"id": str(i), "url": u, "filename": "", "contentType": "", "bytes": 0}
            for i, u in enumerate([
                "https://cdn/ok.png", "https://cdn/missing.png", "https://cdn/boom.png",
                "https://cdn/huge.png"] + [f"https://cdn/{k}.png" for k in range(20)], start=1)]
    out = await fetch_attachments_for_ingest(_Http(), atts)
    assert len(out) == len(atts)                     # nothing dropped
    assert out[0].get("dataUrl", "").startswith("data:image/png;base64,") and "status" not in out[0]
    assert out[1]["status"] == "failed" and out[1]["error"] == "image fetch HTTP 404"
    assert out[2]["status"] == "failed" and "connection reset" in out[2]["error"]
    assert out[3]["status"] == "skipped-over-budget" and "exceeds" in out[3]["error"]
    beyond = out[MAX_INGEST_ATTACHMENTS:]
    assert beyond and all(a["status"] == "skipped-over-budget" and "dataUrl" not in a
                          for a in beyond)


async def test_gateway_posts_the_whole_attachment_set(tmp_path):
    gw = Gateway("tok", "http://x", "", tmp_path / "dms.jsonl", ingest=True, dump=False,
                 bots_only=False, author_id="", channel_id="")
    http = _Http()
    msg = _msg(attachments=[
        {"id": "a1", "filename": "one.png", "content_type": "image/png",
         "url": "https://cdn/one.png", "size": 10},
        {"id": "a2", "filename": "missing.png", "content_type": "image/png",
         "url": "https://cdn/missing.png", "size": 10}], embeds=[])
    out = await gw._ingest_message(http, {}, msg, "src1")
    assert out["ok"]
    body = http.posted[0]["json"]
    assert body["messageId"] == "900" and body["imageCount"] == 2
    assert [a["id"] for a in body["attachments"]] == ["a1", "a2"]
    assert body["attachments"][0]["dataUrl"].startswith("data:image/png")
    assert body["attachments"][1]["status"] == "failed"
    assert all("url" not in a for a in body["attachments"])
    # images listed but none fetchable + no text: the manifest is still delivered
    http2 = _Http()
    msg2 = _msg(content="", attachments=[
        {"id": "a9", "filename": "missing.png", "content_type": "image/png",
         "url": "https://cdn/missing.png", "size": 10}], embeds=[])
    assert (await gw._ingest_message(http2, {}, msg2, "src1"))["ok"]
    assert http2.posted[0]["json"]["attachments"][0]["status"] == "failed"
    # nothing at all (sticker-only) stays terminal without a POST
    http3 = _Http()
    assert (await gw._ingest_message(http3, {}, _msg(content="", attachments=[], embeds=[]),
                                     "src1"))["ok"]
    assert http3.posted == []
