"""Unpaid checks against real history formatting and bundle capture."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from zargar.techniques.tip import analyst, recap, frozen
from .test_tip_kfin09_experiments import rig, _run, _Scripted, _text, _opinion, canned  # noqa: F401


async def test_candidate_retains_twelve_multiline_history_records():
    records = [{"id": str(i), "postedAt": "2026-09-16T13:00:00+00:00", "author": "source",
                "text": f"record {i} first line\nrecord {i} second line", "images": []} for i in range(12)]
    eng = NS(signals_service=NS(discord_search_messages=AsyncMock(return_value=records)))
    production_history = await analyst._source_history(eng, "eva", hours=24, limit=12)
    candidate = recap.build_candidate_context(rules=[], notes=[], history_text=production_history,
        ticker="SPX", source="eva", confidence=0.87)
    assert candidate["historyText"] == production_history, "replay truncates twelve lines, not the twelve records production supplies"


async def test_actual_capture_retains_candidate_confidence(rig, monkeypatch):
    eng = rig
    await eng.settings.set("techniques.tip.frozen_capture_context", True, journal=False)
    await eng.settings.set("techniques.tip.recap_route", "off", journal=False)
    read = {"category": "recap", "route": "compact", "confidence": 0.87, "reasons": [], "features": {}}
    monkeypatch.setattr(recap, "classify", lambda *a, **kw: read)
    eng.signals_service._analyst_client = _Scripted([_text(_opinion("skip"))])
    out = await _run(eng, canned(), source="ParitySource")
    signal = out[0]["signal"]
    assert signal["extraction"]["analyst"]["recapRead"]["confidence"] == 0.87
    bundle = await frozen.capture_bundle(eng.sf, signal_id=signal["id"], settings=eng.settings)
    variant = frozen.variant_knowledge(bundle, "recap_candidate")
    assert variant["available"]
    assert "confidence 0.87" in variant["prefix"], "bundle capture lost the actual classifier input and replay silently substituted zero"
