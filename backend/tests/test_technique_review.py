"""Technique review loop: trace + provenance on every run, bars snapshot,
outcome scoring, reviews, bundle export, replay + diff, additive migration,
and the CLI. No network, no real LLM: the Anthropic client is faked and the
Yahoo fetchers are monkeypatched with synthetic bars.
"""
from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import os
import subprocess
import sys
import zipfile
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text

from zargar.api.app import create_app
from zargar.domain import Bar
from zargar.engine import Engine
from zargar.technique import service as service_mod
from zargar.technique.analysis import AnalysisRequest, compute_facts
from zargar.technique.outcome import path_summary, simulate_plan
from zargar.technique.schemas import CriticVerdict, PassNotes, TechniqueAnalysis
from zargar.technique.service import attach_technique_layer

from .conftest import TEST_DB_URL, make_test_config

MIN = 60_000
ET = dt.timezone(dt.timedelta(hours=-4))


# --- synthetic market ------------------------------------------------------------------------

def _session_bars(day: dt.date, *, minutes: int = 390, lo: float = 100.0, hi: float = 104.0,
                  period: int = 40, symbol: str = "TEST", tf: str = "1m", phase: int = 0) -> list[Bar]:
    """One RTH session of 1m bars tracing a triangle wave between lo and hi so
    the level detector sees repeated touches of both."""
    start = dt.datetime(day.year, day.month, day.day, 9, 30, tzinfo=ET)
    out: list[Bar] = []
    prev = lo
    for i in range(minutes):
        k = (i + phase) % period
        frac = k / (period / 2) if k < period / 2 else 2 - k / (period / 2)
        px = round(lo + (hi - lo) * frac, 2)
        o, c = prev, px
        h = max(o, c) + 0.02
        l = min(o, c) - 0.02
        ts = int((start + dt.timedelta(minutes=i)).timestamp() * 1000)
        out.append(Bar(symbol=symbol, tf=tf, ts=ts, open=o, high=round(h, 2), low=round(l, 2), close=c,
                       volume=900 + (i * 37) % 400))
        prev = px
    return out


def _resample(bars: list[Bar], minutes: int, tf: str) -> list[Bar]:
    out: list[Bar] = []
    for i in range(0, len(bars), minutes):
        seg = bars[i:i + minutes]
        out.append(Bar(symbol=seg[0].symbol, tf=tf, ts=seg[0].ts, open=seg[0].open,
                       high=max(b.high for b in seg), low=min(b.low for b in seg), close=seg[-1].close,
                       volume=sum(b.volume for b in seg)))
    return out


def _market(as_of_ms: int) -> dict[str, list[Bar]]:
    """Two sessions ending at as_of (which sits mid-session on the second day,
    at a trough so a bounce candidate exists)."""
    d = dt.datetime.fromtimestamp(as_of_ms / 1000, ET).date()
    prev = d - dt.timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= dt.timedelta(days=1)
    bars = _session_bars(prev) + _session_bars(d)
    bars = [b for b in bars if b.ts <= as_of_ms]
    return {"1m": bars, "5m": _resample(bars, 5, "5m"), "1h": _resample(bars, 60, "1h")}


def _after_bars(as_of_ms: int, plan: dict, n: int = 70) -> list[Bar]:
    """Bars after as_of: dip through the entry, then rally past every target,
    never touching the stop."""
    entry = plan["entry"]["price"]
    stop = plan["stop"]["price"]
    top = max(t["price"] for t in plan["targets"]) + 0.5
    out: list[Bar] = []
    px = entry + 0.1
    for i in range(n):
        ts = as_of_ms + (i + 1) * MIN
        if i < 3:
            lo, hi, c = entry - 0.05, entry + 0.15, entry + 0.05
        else:
            frac = min(1.0, (i - 3) / 30)
            c = entry + (top - entry) * frac
            lo, hi = max(stop + 0.05, c - 0.1), c + 0.1
        out.append(Bar(symbol="TEST", tf="1m", ts=ts, open=px, high=round(hi, 2), low=round(lo, 2),
                       close=round(c, 2), volume=1000))
        px = c
    return out


def _as_of() -> int:
    """14:10 ET (a trough of the triangle wave: minute 280 = 7 full periods) on the
    most recent weekday that is at least 3 days old."""
    d = dt.datetime.now(ET).date() - dt.timedelta(days=3)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return int(dt.datetime(d.year, d.month, d.day, 14, 10, tzinfo=ET).timestamp() * 1000)


# --- fake Anthropic client ----------------------------------------------------------------

class _Stream:
    def __init__(self, msg):
        self.msg = msg

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    async def get_final_message(self):
        return self.msg


class FakeMessages:
    def __init__(self, script):
        self.script = script
        self.calls: list[dict] = []

    def stream(self, **params):
        self.calls.append(params)
        parsed = self.script(params)
        usage = SimpleNamespace(input_tokens=1200, output_tokens=300, cache_read_input_tokens=800,
                                cache_creation_input_tokens=0)
        content = [SimpleNamespace(type="thinking", thinking="let me look at the levels…", signature="sig"),
                   SimpleNamespace(type="text", text=json.dumps(parsed.model_dump()) if parsed else "…")]
        msg = SimpleNamespace(content=content, usage=usage, stop_reason="end_turn", parsed_output=parsed)
        return _Stream(msg)


class FakeClient:
    def __init__(self, script):
        self.messages = FakeMessages(script)


def _analysis_from_plan(plan: dict, *, verdict: str = "setup", level_price: float,
                        resistance: float | None = None) -> TechniqueAnalysis:
    levels = [{"price": level_price, "kind": "support", "touches": 3, "note": "tested"}]
    if resistance:
        levels.append({"price": resistance, "kind": "resistance", "touches": 2, "note": "cap"})
    base = dict(
        symbol="TEST", verdict=verdict, setup_type="support_bounce" if verdict == "setup" else "none",
        direction="long" if verdict == "setup" else "none", trend="sideways", levels=levels,
        pattern_kind="none", pattern_present=False, pattern_widest_height=0.0,
        pattern_volume_declining=False, pattern_notes="",
        breakout_observed=False, breakout_verdict="none", breakout_level=0.0,
        breakout_volume_confirmed=False, breakout_decisive_candle=False, breakout_follow_through=False,
        breakout_holds_level=False, higher_tf_agrees=True,
        entry_price=plan["entry"]["price"] if verdict == "setup" else 0.0, entry_basis="at_level",
        entry_requires_confirmation=False,
        stop_price=plan["stop"]["price"] if verdict == "setup" else 0.0, stop_kind="mental",
        stop_reference="below_support",
        targets=([{"price": t["price"], "trim_pct": p, "basis": "next_resistance"}
                  for t, p in zip(plan["targets"], (30, 40, 15))] if verdict == "setup" else []),
        runner_pct=15.0, risk_reward=float(plan.get("riskReward") or 0), volume_verdict="ok (T2.9)",
        confidence=0.7, rules_fired=["T1.2", "T4.1", "R2"],
        no_trade_reasons=[] if verdict == "setup" else ["R2 no room to the next resistance"],
        options_strike_guidance="just OTM", options_expiry_guidance="Friday", options_warnings=[],
        rationale="Bounce at the tested support (T1.2, T4.1); R:R clears R2.")
    return TechniqueAnalysis.model_validate(base)


def _script_for(plan: dict, level_price: float, resistance: float | None, *, kill: bool = False):
    def script(params):
        fmt = params.get("output_format")
        if fmt is PassNotes:
            return PassNotes(observations=["range between the two levels"], candidate_levels=[level_price],
                             pattern_hypothesis="consolidation", trend="sideways", concerns=[])
        if fmt is CriticVerdict:
            return CriticVerdict(kill=kill, fakeout_risk="low",
                                 violations=(["T3.3d no volume"] if kill else []), adjustments=[],
                                 confidence_adjustment=(-0.3 if kill else 0.05), summary="ok" if kill is False else "kill")
        if fmt is TechniqueAnalysis:
            return _analysis_from_plan(plan, level_price=level_price, resistance=resistance)
        return None
    return script


# --- fixture: app + engine + faked data -------------------------------------------------------

@pytest.fixture
async def rig(fresh_db, monkeypatch):
    config = make_test_config(anthropic_api_key="sk-test")
    eng = Engine(config)
    await eng.start()
    await attach_technique_layer(eng)
    await eng.settings.set("technique.options.enabled", False, journal=False)   # no CBOE calls
    app = create_app(config, eng)
    transport = httpx.ASGITransport(app=app)

    as_of = _as_of()
    market = _market(as_of)
    req = AnalysisRequest(symbol="TEST", as_of_ms=as_of, primary_tf="1m", thresholds=eng.technique.thresholds())
    facts = compute_facts(req, market, [])
    cand = (facts.get("candidateSetups") or [None])[0]
    assert cand is not None, "synthetic market must yield a bounce candidate"
    plan = {"entry": {"price": cand["entry"]["price"], "basis": "at_level"},
            "stop": {"price": cand["stop"]["price"]},
            "targets": [{"price": t["price"]} for t in cand["targets"]],
            "riskReward": cand["riskReward"], "setupType": "support_bounce"}
    level_price = cand["levelPrice"] or cand["entry"]["price"]
    res_level = next((lv["price"] for lv in facts["keyLevels"] if lv["effectiveKind"] == "resistance"), None)

    async def fake_gather(req_):
        return {k: [b for b in v if req_.as_of_ms is None or b.ts <= req_.as_of_ms]
                for k, v in market.items()}, ["synthetic bars"]

    after = _after_bars(as_of, plan)

    async def fake_after(symbol, tf, as_of_ms, *, horizon, entry_window, max_days=10):
        return after[:horizon + entry_window + 2]

    monkeypatch.setattr(service_mod, "gather_bars", fake_gather)
    monkeypatch.setattr(service_mod, "fetch_after", fake_after)
    fake = FakeClient(_script_for(plan, level_price, res_level))
    monkeypatch.setattr(eng.technique, "_get_client", lambda: fake)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(client=client, eng=eng, svc=eng.technique, as_of=as_of, plan=plan,
                              facts=facts, fake=fake, market=market, level=level_price)
    await eng.technique.stop()
    await eng.stop()


# --- simulate_plan unit tests -------------------------------------------------------------------

def _mk(ts, o, h, l, c):
    return Bar(symbol="T", tf="1m", ts=ts, open=o, high=h, low=l, close=c, volume=1)


def _plan(entry=100.0, stop=99.0, targets=(101.0, 102.0, 103.0), basis="at_level"):
    return {"setupType": "support_bounce", "entry": {"price": entry, "basis": basis},
            "stop": {"price": stop}, "targets": [{"price": t} for t in targets]}


def test_simulate_plan_fills_then_hits_all_targets():
    bars = [_mk(0, 100.5, 100.6, 100.4, 100.5), _mk(1, 100.3, 100.4, 99.9, 100.1),
            _mk(2, 100.1, 101.2, 100.0, 101.1), _mk(3, 101.1, 102.3, 101.0, 102.2),
            _mk(4, 102.2, 103.4, 102.1, 103.3), _mk(5, 103.3, 103.5, 103.2, 103.4)]
    r = simulate_plan(bars, 0, _plan(), entry_window=3, horizon=10)
    assert r["filled"] and r["fillIndex"] == 1 and r["outcome"] == "tp3"
    assert r["rMultiple"] > 1.5 and r["mfeR"] >= 3.0 and r["maeR"] == 0.0
    assert r["hits"] == [2, 3, 4]
    assert r["resolved"] is False            # horizon (10 bars) not reached — runner still riding


def test_simulate_plan_stop_wins_inside_one_bar():
    bars = [_mk(0, 100.5, 100.6, 100.4, 100.5), _mk(1, 100.3, 100.4, 99.9, 100.1),
            _mk(2, 100.1, 101.5, 98.9, 99.0)]
    r = simulate_plan(bars, 0, _plan(), entry_window=3, horizon=10)
    assert r["outcome"] == "stopped" and r["rMultiple"] == pytest.approx(-1.0) and r["resolved"]


def test_simulate_plan_not_filled_and_partial_states():
    bars = [_mk(i, 100.5, 100.6, 100.4, 100.5) for i in range(3)]
    r = simulate_plan(bars, 0, _plan(), entry_window=5, horizon=10)
    assert r["outcome"] == "not_filled" and not r["resolved"]          # window still open
    r2 = simulate_plan(bars + [_mk(i, 100.5, 100.6, 100.4, 100.5) for i in range(3, 8)], 0, _plan(),
                       entry_window=5, horizon=10)
    assert r2["outcome"] == "not_filled" and r2["resolved"]


def test_simulate_plan_on_break_fills_at_start_and_horizon_resolves():
    bars = [_mk(i, 100.0, 100.4, 99.8, 100.2) for i in range(8)]
    r = simulate_plan(bars, 0, _plan(basis="on_break"), entry_window=3, horizon=5)
    assert r["filled"] and r["fillIndex"] == 0 and r["outcome"] == "horizon" and r["resolved"]
    assert r["barsHeld"] == 5


def test_simulate_plan_invalid_plan():
    r = simulate_plan([_mk(0, 1, 1, 1, 1)], 0, _plan(entry=100, stop=101), entry_window=3, horizon=5)
    assert r["outcome"] == "not_filled" and r["resolved"] and "invalid" in r["note"]


def test_path_summary_offsets():
    bars = [_mk(i, 100, 100 + i * 0.1, 99.5, 100 + i * 0.1) for i in range(40)]
    p = path_summary(bars, 100.0)
    assert "+5" in p and "+15" in p and "+30" in p and "+60" not in p
    assert p["+30"]["closePct"] == pytest.approx(2.9, abs=0.01)


# --- full pipeline with trace, provenance, snapshot, outcome ----------------------------------

async def test_run_records_trace_config_snapshot_and_outcome(rig):
    run = await rig.svc.analyze("TEST", as_of_ms=rig.as_of, primary_tf="1m", wait=True)
    assert run["status"] == "done", run.get("error")
    assert run["verdict"] == "setup"
    assert run["grounded"] is True, [c for c in run["result"]["grounding"]["checks"] if not c["passed"]]

    # provenance
    cfg = run["config"]
    for k in ("promptVersion", "rulebookVersion", "codeVersion", "processVersion", "thresholds", "settings",
              "model", "effort", "maxPasses", "timeframes", "barsAssetId"):
        assert k in cfg, k
    assert cfg["thresholds"]["min_risk_reward"] == 3.0
    assert cfg["settings"]["technique.min_risk_reward"] == 3.0 and "llm.effort" in cfg["settings"]
    assert run["processVersion"] == cfg["processVersion"]

    # trace: ordered, every stage present, reasons are prose
    trace = run["result"]["trace"]
    stages = [t["stage"] for t in trace]
    for st in ("run", "data", "loop", "context", "pattern", "entry", "critic", "grounding", "options",
               "setup", "proposal"):
        assert st in stages, st
    assert [t["seq"] for t in trace] == list(range(1, len(trace) + 1))
    steps = {(t["stage"], t["step"]) for t in trace}
    assert ("data", "snapshot_saved") in steps and ("critic", "survive") in steps
    assert ("loop", "stop") in steps and ("setup", "persist") in steps and ("proposal", "skipped") in steps
    draft = next(t for t in trace if t["step"] == "draft")
    assert draft["detail"]["verdict"] == "setup" and draft["detail"]["entry"] == rig.plan["entry"]["price"]
    assert all(isinstance(t["reason"], str) and t["reason"] for t in trace)

    # bars snapshot round-trips
    snap = await rig.svc.load_bars_snapshot(run["id"])
    assert set(snap) == {"1m", "5m", "1h"} and len(snap["1m"]) == len(rig.market["1m"])

    # transcript persisted with thinking + parsed output per pass
    thread = await rig.eng.chat.get_thread(run["threadId"])
    passes = [m for m in thread["messages"] if m["meta"].get("kind") == "pipeline_response"]
    assert [m["meta"]["pass"] for m in passes] == ["context", "pattern", "entry", "critic"]
    assert passes[2]["meta"]["parsed"]["verdict"] == "setup"
    assert any(b["type"] == "thinking" for b in passes[0]["blocks"])

    # outcome was scored immediately (backdated run) against the after-bars
    outs = run["outcomes"]
    assert len(outs) == 1 and outs[0]["planSource"] == "analysis"
    o = outs[0]
    assert o["status"] == "scored" and o["outcome"] == "tp3" and o["rMultiple"] > 0
    assert o["mfeR"] > 0 and o["maeR"] >= 0 and o["barsAfter"] > 0 and o["path"]["+30"]
    # journal carries the run events incl. outcome
    r = await rig.client.get("/api/events", params={"aggregate_id": run["id"], "limit": 50})
    types = [e["type"] for e in r.json()]
    assert "TechniqueRunStarted" in types and "TechniqueRunCompleted" in types
    assert "TechniqueOutcomeScored" in types and "TechniqueSetupEmitted" not in types  # setup has own aggregate
    done = next(e for e in r.json() if e["type"] == "TechniqueRunCompleted")
    assert done["payload"]["traceSteps"] == len(trace) and done["payload"]["processVersion"]


async def test_run_api_listing_filters_reviews_bundle_replay_and_diff(rig, tmp_path):
    run = await rig.svc.analyze("TEST", as_of_ms=rig.as_of, primary_tf="1m", wait=True)
    rid = run["id"]
    c = rig.client

    # listing carries outcome + review summaries and supports filters
    rows = (await c.get("/api/technique/runs")).json()
    assert rows[0]["id"] == rid and rows[0]["outcomes"][0]["outcome"] == "tp3"
    assert rows[0]["reviewCount"] == 0 and rows[0]["lastReview"] is None and rows[0]["traceSteps"] > 5
    assert (await c.get("/api/technique/runs", params={"reviewed": "true"})).json() == []
    assert len((await c.get("/api/technique/runs", params={"reviewed": "false"})).json()) == 1
    assert len((await c.get("/api/technique/runs", params={"outcome": "win"})).json()) == 1
    assert (await c.get("/api/technique/runs", params={"outcome": "loss"})).json() == []
    assert len((await c.get("/api/technique/runs", params={"outcome": "tp3"})).json()) == 1

    # taxonomy + review validation
    tax = (await c.get("/api/technique/review/taxonomy")).json()
    assert "wrong_verdict" in tax["reviewVerdicts"] and "pass_entry" in tax["rootCauseStages"]
    bad = await c.post(f"/api/technique/runs/{rid}/reviews", json={"reviewVerdict": "meh"})
    assert bad.status_code == 400
    r = await c.post(f"/api/technique/runs/{rid}/reviews", json={
        "reviewVerdict": "wrong_plan", "rootCauseStage": "pass_entry", "expectedVerdict": "setup",
        "expectedSetupType": "support_bounce", "expectedPlan": {"entry": 100.0, "stop": 99.6},
        "expectationNote": "entry should sit on the exact level", "notes": "stop too wide",
        "actions": [{"desc": "tighten stop reference in SYSTEM_PROMPT", "file": "technique/schemas.py"},
                    "add grounding check for stop distance"]})
    assert r.status_code == 200, r.text
    rev = r.json()
    assert rev["reviewVerdict"] == "wrong_plan" and rev["processVersion"]["processVersion"] == run["processVersion"]
    assert rev["actions"][1]["desc"] == "add grounding check for stop distance" and rev["actions"][1]["status"] == "planned"
    got = (await c.get(f"/api/technique/runs/{rid}")).json()
    assert len(got["reviews"]) == 1 and got["reviews"][0]["id"] == rev["id"]
    rows = (await c.get("/api/technique/runs", params={"reviewed": "true"})).json()
    assert rows[0]["lastReview"]["reviewVerdict"] == "wrong_plan"
    assert len((await c.get("/api/technique/runs", params={"reviewVerdict": "wrong_plan"})).json()) == 1
    assert len((await c.get("/api/technique/reviews")).json()) == 1
    # the review is also visible in the run's chat thread and in the journal
    thread = await rig.eng.chat.get_thread(run["threadId"])
    assert any(m["meta"].get("kind") == "review" for m in thread["messages"])
    ev = (await c.get("/api/events", params={"type": "TechniqueReviewAdded"})).json()
    assert ev and ev[0]["payload"]["runId"] == rid

    # bundle: zip via API and files on disk
    z = await c.get(f"/api/technique/runs/{rid}/bundle")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    for f in ("run.json", "facts.json", "trace.md", "transcript.md", "transcript.json", "grounding.json",
              "outcome.json", "journal.json", "README.md", "bars/1m.json", "bars/5m.json", "bars/after.json",
              "images/1m.png", "images/annotated.png"):
        assert f"{rid}/{f}" in names, f
    from zargar.technique.bundle import write_bundle
    root = await write_bundle(rig.svc, rid, tmp_path)
    trace_md = (root / "trace.md").read_text(encoding="utf-8")
    assert "| stage | step | reason |" in trace_md and "snapshot_saved" in trace_md
    tr = (root / "transcript.md").read_text(encoding="utf-8")
    assert "pass **entry**" in tr and "parsed (structured output)" in tr and "(thinking)" in tr
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "wrong_plan" in readme and "tp3" in readme
    bars_1m = json.loads((root / "bars" / "1m.json").read_text())
    assert len(bars_1m) == len(rig.market["1m"]) and len(bars_1m[0]) == 6
    jb = (await c.get(f"/api/technique/runs/{rid}/bundle", params={"format": "json"})).json()
    assert jb["run"]["id"] == rid and jb["thread"]["id"] == run["threadId"] and jb["events"]

    # replay with a threshold override, from the snapshot, linked to the parent
    rep = await c.post(f"/api/technique/runs/{rid}/replay",
                       json={"thresholds": {"min_risk_reward": 2.0}, "wait": True, "note": "after fix"})
    assert rep.status_code == 200, rep.text
    child = rep.json()
    assert child["parentRunId"] == rid and child["status"] == "done" and child["trigger"] == "replay"
    assert child["config"]["overrides"] == {"thresholds": {"min_risk_reward": 2.0}, "barsFromSnapshot": True}
    assert child["config"]["thresholds"]["min_risk_reward"] == 2.0
    assert child["processVersion"] != run["processVersion"]
    assert ("data", "snapshot") in {(t["stage"], t["step"]) for t in child["result"]["trace"]}
    assert child["asOf"] == run["asOf"]
    parent = (await c.get(f"/api/technique/runs/{rid}")).json()
    assert [x["id"] for x in parent["replays"]] == [child["id"]]
    bad = await c.post(f"/api/technique/runs/{rid}/replay", json={"thresholds": {"nope": 1}})
    assert bad.status_code == 400
    d = (await c.get(f"/api/technique/runs/{rid}/diff/{child['id']}")).json()
    assert d["sameInputs"] is True and d["thresholds"]["min_risk_reward"] == {"a": 3.0, "b": 2.0}
    assert "processVersion" in d["versions"] and d["analysis"] == {}      # same fake model → same plan
    ev = (await c.get("/api/events", params={"type": "TechniqueRunReplayed"})).json()
    assert ev and ev[0]["payload"]["runId"] == child["id"] and ev[0]["payload"]["parentRunId"] == rid

    # manual re-score is idempotent and the pending sweep finds nothing left
    again = (await c.post(f"/api/technique/runs/{rid}/score")).json()
    assert len(again) == 1 and again[0]["outcome"] == "tp3"
    sweep = (await c.post("/api/technique/outcomes/score")).json()
    assert sweep["scored"] == [] and sweep["failed"] == []


async def test_no_setup_run_scores_rejected_candidate_and_market_path(rig, monkeypatch):
    # make the model decline; the candidate (same geometry) should be scored as what was missed
    def script(params):
        fmt = params.get("output_format")
        if fmt is PassNotes:
            return PassNotes(observations=[], candidate_levels=[], pattern_hypothesis="none",
                             trend="sideways", concerns=["chop"])
        if fmt is TechniqueAnalysis:
            return _analysis_from_plan(rig.plan, verdict="no_setup", level_price=rig.level)
        return None
    rig.fake.messages.script = script
    run = await rig.svc.analyze("TEST", as_of_ms=rig.as_of, primary_tf="1m", wait=True)
    assert run["verdict"] == "no_setup" and run["status"] == "done"
    steps = {(t["stage"], t["step"]) for t in run["result"]["trace"]}
    assert ("critic", "skipped") in steps and ("options", "skipped") in steps
    outs = run["outcomes"]
    assert [o["planSource"] for o in outs] == ["candidate"]
    assert outs[0]["outcome"] == "tp3" and outs[0]["rMultiple"] > 0     # the trade it declined worked
    rows = (await rig.client.get("/api/technique/runs", params={"outcome": "win"})).json()
    assert rows and rows[0]["id"] == run["id"]


async def test_critic_kill_is_traced(rig):
    rig.fake.messages.script = _script_for(rig.plan, rig.level, None, kill=True)
    run = await rig.svc.analyze("TEST", as_of_ms=rig.as_of, primary_tf="1m", wait=True)
    assert run["verdict"] == "no_setup"
    kill = next(t for t in run["result"]["trace"] if t["step"] == "kill")
    assert kill["stage"] == "critic" and kill["detail"]["confidenceBefore"] > kill["detail"]["confidenceAfter"]
    assert any(r.startswith("CRITIC:") for r in run["result"]["analysis"]["noTradeReasons"])


async def test_failed_run_keeps_partial_trace(rig, monkeypatch):
    async def boom(req_):
        return {}, ["Yahoo HTTP 404"]
    monkeypatch.setattr(service_mod, "gather_bars", boom)
    run = await rig.svc.analyze("NOPE", as_of_ms=rig.as_of, primary_tf="1m", wait=True)
    assert run["status"] == "failed" and "no bars" in run["error"]
    trace = run["result"]["trace"]
    assert [t["step"] for t in trace][:2] == ["start", "fetch"]
    assert trace[-1]["step"] == "failed" and "no bars" in trace[-1]["reason"]
    assert ("data", "abort") in {(t["stage"], t["step"]) for t in trace}


# --- additive migration ------------------------------------------------------------------------

async def test_create_all_adds_missing_columns(fresh_db):
    from zargar.db import create_all, make_engine
    eng = make_engine(TEST_DB_URL)
    async with eng.begin() as conn:
        await conn.execute(text("ALTER TABLE technique_runs DROP COLUMN config"))
        await conn.execute(text("ALTER TABLE technique_runs DROP COLUMN parent_run_id"))
        await conn.execute(text(
            "INSERT INTO technique_runs (id, symbol, primary_tf, mode, trigger, status, facts, result, images, "
            "usage, llm, created_at) VALUES ('old1', 'AAPL', '1m', 'full', 'manual', 'done', '{}', '{}', '{}', "
            "'{}', '{}', now())"))
    await create_all(eng)
    await create_all(eng)          # idempotent
    async with eng.begin() as conn:
        row = (await conn.execute(text("SELECT config, parent_run_id FROM technique_runs WHERE id='old1'"))).one()
        assert row[0] == {} and row[1] is None
        nn = (await conn.execute(text(
            "SELECT is_nullable FROM information_schema.columns WHERE table_name='technique_runs' "
            "AND column_name='config'"))).scalar()
        assert nn == "NO"
    await eng.dispose()


# --- CLI ------------------------------------------------------------------------------------------

def _cli(*args, env_extra=None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["ZARGAR_REVIEW_DATABASE_URL"] = TEST_DB_URL
    env["PYTHONUTF8"] = "1"
    env.update(env_extra or {})
    return subprocess.run([sys.executable, "-m", "zargar.tools.technique_review", *args],
                          capture_output=True, text=True, env=env, timeout=120,
                          cwd=os.path.dirname(os.path.dirname(__file__)))


async def test_cli_list_show_dump_review_diff(rig, tmp_path):
    run = await rig.svc.analyze("TEST", as_of_ms=rig.as_of, primary_tf="1m", wait=True)
    rid = run["id"]
    p = _cli("--json", "taxonomy")
    assert p.returncode == 0 and "wrong_verdict" in json.loads(p.stdout)["reviewVerdicts"]
    p = _cli("--json", "list", "--unreviewed")
    assert p.returncode == 0, p.stderr
    rows = json.loads(p.stdout)
    assert rows and rows[0]["id"] == rid and rows[0]["outcomes"][0]["outcome"] == "tp3"
    p = _cli("list")
    assert p.returncode == 0 and rid[:10] in p.stdout and "A:tp3" in p.stdout
    p = _cli("show", rid)
    assert p.returncode == 0 and "## Trace" in p.stdout and "snapshot_saved" in p.stdout
    p = _cli("--json", "dump", rid, "--out", str(tmp_path))
    assert p.returncode == 0, p.stderr
    files = json.loads(p.stdout)["files"]
    assert "trace.md" in files and "bars/1m.json" in files and "images/annotated.png" in files
    p = _cli("review", rid, "--verdict", "correct", "--expected", "setup", "--note", "looks right",
             "--action", "none", "--reviewer", "claude")
    assert p.returncode == 0, p.stderr
    p = _cli("--json", "reviews", rid)
    revs = json.loads(p.stdout)
    assert len(revs) == 1 and revs[0]["reviewer"] == "claude" and revs[0]["actions"][0]["desc"] == "none"
    p = _cli("review", rid, "--verdict", "bogus")
    assert p.returncode != 0
    p = _cli("--json", "replay-facts", rid)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["detectorsUnchanged"] is True
    p = _cli("--json", "replay-facts", rid, "--set", "min_touches=5")
    assert p.returncode == 0 and json.loads(p.stdout)["overrides"] == {"min_touches": 5}
    # (`score` via the CLI would hit Yahoo for real bars; the scoring path is covered through the API)
    p = _cli("dump", "does-not-exist", "--out", str(tmp_path))
    assert p.returncode == 1


async def test_chat_tools_get_run_and_record_review(rig):
    from zargar.technique.tools import ToolExecutor
    run = await rig.svc.analyze("TEST", as_of_ms=rig.as_of, primary_tf="1m", wait=True)
    ex = ToolExecutor(rig.svc, lambda d, mt: rig.eng.chat.store_asset(d, mt), thread_id=run["threadId"])
    content, meta = await ex.run("get_run", {"run_id": run["id"][:10]})       # prefix resolves
    got = json.loads(content)
    assert got["id"] == run["id"] and got["verdict"] == "setup" and got["trace"] and got["outcomes"]
    content, meta = await ex.run("record_review", {"run_id": "this run", "review_verdict": "wrong_plan",
                                                   "root_cause_stage": "pass_entry", "expected_verdict": "setup",
                                                   "expected_entry": 100.0, "notes": "stop too wide",
                                                   "actions": ["tighten the stop buffer"]})
    # an unknown id falls back to the thread's own run
    rec = json.loads(content)
    assert rec["recorded"] and rec["runId"] == run["id"]
    full = (await rig.client.get(f"/api/technique/runs/{run['id']}")).json()
    assert full["reviews"][0]["reviewVerdict"] == "wrong_plan" and full["reviews"][0]["actions"][0]["desc"] == "tighten the stop buffer"
    content, meta = await ex.run("record_review", {"run_id": run["id"], "review_verdict": "nope"})
    assert meta.get("error") and "review not recorded" in content
