"""Actual compact-route requests with siblings and effective budget overrides."""
import pytest
from zargar.techniques.tip import recap, frozen
from .test_tip_kfin09_experiments import rig, _run, _Scripted, _text, _opinion, canned  # noqa: F401


@pytest.mark.parametrize("case", ["siblings", "tool_budget"])
async def test_actual_candidate_request_parity_boundaries(rig, monkeypatch, case):
    eng = rig
    await eng.settings.set("techniques.tip.frozen_capture_context", True, journal=False)
    await eng.settings.set("techniques.tip.recap_route", "compact", journal=False)
    await eng.settings.set("techniques.tip.recap_max_tools", 1 if case == "tool_budget" else 2, journal=False)
    read = {"version": recap.CLASSIFIER_VERSION, "category": "recap", "route": "compact",
            "confidence": 0.87, "reasons": [], "features": {}}
    monkeypatch.setattr(recap, "classify", lambda *a, **kw: read)
    eng.signals_service._analyst_client = _Scripted([_text(_opinion("skip"))])
    extraction = canned()
    if case == "siblings":
        extraction.signals.extend([extraction.signals[0].model_copy(deep=True) for _ in range(2)])
    out = await _run(eng, extraction, source="ActualParity")
    bundle = await frozen.capture_bundle(eng.sf, signal_id=out[0]["signal"]["id"], settings=eng.settings)
    man = bundle["manifest"]
    assert man["headerMode"] == "compact"
    kv = frozen.variant_knowledge(bundle, "recap_candidate")
    assert kv["available"] and kv["parity"]["status"] == "production-request"
    if case == "siblings":
        assert man["siblings"] and man["header"].count("COMPACT ROUTE:") == 1
        rebuilt, _ = frozen._rebuild_header(man, rules_text=kv["rulesText"], notes_text=kv["notesText"],
            history_records=kv["historyRecords"], prefix=kv["prefix"])
        assert rebuilt == man["header"], "multi-branch replay changes prefix order and duplicates the compact instruction"
    else:
        assert kv["maxTools"] == man["maxTools"], "production-request parity claimed with a different effective tool budget"
