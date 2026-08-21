"""Technique + chat API surface (no LLM calls — the key is empty in tests).

Covers: status/rules, persistence of threads/messages/assets, search, the
analyze endpoint failing closed without a key, the run/setup listing shape,
and the deterministic pieces (facts, grounding) through the service.
"""
import base64

import httpx
import pytest

from zargar.api.app import create_app
from zargar.engine import Engine
from zargar.technique.service import attach_technique_layer
from zargar.technique.grounding import ground_analysis
from zargar.technique.schemas import TechniqueAnalysis

from .conftest import make_test_config


@pytest.fixture
async def app_client(fresh_db):
    config = make_test_config()
    eng = Engine(config)
    await eng.start()
    await attach_technique_layer(eng)
    app = create_app(config, eng)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, eng
    await eng.technique.stop()
    await eng.stop()


def _png_bytes() -> bytes:
    """A tiny valid PNG (1x1) without pulling in PIL."""
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


async def test_status_and_rules(app_client):
    client, _ = app_client
    r = await client.get("/api/technique/status")
    assert r.status_code == 200
    s = r.json()
    assert s["llmAvailable"] is False          # no key in tests
    assert s["model"] == "claude-opus-5"
    assert s["effort"] == "high"
    assert s["thinkingDisplay"] == "summarized"
    assert s["runsToday"] == 0 and s["maxRunsPerDay"] == 40
    assert "T3.3d" in s["rules"]
    r = await client.get("/api/technique/rules")
    assert r.json()["R2"].startswith("Require R:R")


async def test_analyze_fails_closed_without_key(app_client):
    client, _ = app_client
    r = await client.post("/api/technique/analyze", json={"symbol": "AAPL"})
    assert r.status_code == 400
    assert "ANTHROPIC" in r.json()["detail"]
    r = await client.get("/api/technique/runs")
    assert r.json() == []


async def test_analyze_requires_symbol_or_image(app_client):
    client, eng = app_client
    # give it a key so we get past the availability check to validation
    eng.config.anthropic_api_key = "sk-test"
    r = await client.post("/api/technique/analyze", json={"symbol": ""})
    assert r.status_code == 400
    assert "symbol or image" in r.json()["detail"]


async def test_llm_settings_roundtrip(app_client):
    client, _ = app_client
    r = await client.patch("/api/settings", json={"llm.effort": "xhigh",
                                                  "llm.thinking_display": "omitted"})
    assert r.status_code == 200
    r = await client.get("/api/technique/status")
    assert r.json()["effort"] == "xhigh"
    assert r.json()["thinkingDisplay"] == "omitted"
    # bad value falls back to a safe default rather than breaking the pipeline
    await client.patch("/api/settings", json={"llm.effort": "ludicrous"})
    r = await client.get("/api/technique/status")
    assert r.json()["effort"] == "high"


async def test_chat_thread_lifecycle_and_search(app_client):
    client, eng = app_client
    r = await client.post("/api/chat/threads", json={"title": "SPY notes", "symbol": "SPY"})
    assert r.status_code == 200
    tid = r.json()["id"]
    assert r.json()["kind"] == "chat"

    # persist messages directly (the agent loop needs a key; persistence does not)
    await eng.chat.append_message(tid, "user", [{"type": "text", "text": "where is support on SPY?"}])
    await eng.chat.append_message(tid, "assistant", [{"type": "text", "text": "Support sits at 765.14 (T1.2)."}],
                                  {"usage": {"input": 10, "output": 5}})
    r = await client.get(f"/api/chat/threads/{tid}")
    t = r.json()
    assert t["messageCount"] == 2
    assert [m["seq"] for m in t["messages"]] == [1, 2]
    assert t["messages"][1]["meta"]["usage"]["output"] == 5
    assert t["busy"] is False

    r = await client.get("/api/chat/threads")
    assert any(x["id"] == tid for x in r.json())

    r = await client.get("/api/chat/search", params={"q": "765.14"})
    hits = r.json()
    assert hits and hits[0]["threadId"] == tid and "765.14" in hits[0]["snippet"]

    r = await client.patch(f"/api/chat/threads/{tid}", json={"title": "renamed", "archived": True})
    assert r.json()["title"] == "renamed" and r.json()["archived"] is True
    r = await client.get("/api/chat/threads")
    assert not any(x["id"] == tid for x in r.json())          # archived hidden by default
    r = await client.get("/api/chat/threads", params={"archived": "true"})
    assert any(x["id"] == tid for x in r.json())


async def test_chat_assets_roundtrip(app_client):
    client, eng = app_client
    r = await client.post("/api/chat/threads", json={"title": "img"})
    tid = r.json()["id"]
    png = _png_bytes()
    aid = await eng.chat.store_asset(png, None, thread_id=tid)    # media type sniffed
    r = await client.get(f"/api/chat/assets/{aid}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content == png
    r = await client.get("/api/chat/assets/nope")
    assert r.status_code == 404


async def test_chat_send_without_key_records_error_message(app_client):
    client, eng = app_client
    r = await client.post("/api/chat/threads", json={"title": "nokey"})
    tid = r.json()["id"]
    data_url = "data:image/png;base64," + base64.b64encode(_png_bytes()).decode()
    r = await client.post(f"/api/chat/threads/{tid}/messages",
                          json={"text": "hello", "images": [data_url]})
    assert r.status_code == 200
    # the agent turn runs in the background; it should finish quickly with an error row
    from .conftest import wait_for
    async def done():
        t = await eng.chat.get_thread(tid)
        return len(t["messages"]) >= 2 and t
    t = await wait_for(done, timeout=8)
    user_msg, reply = t["messages"][0], t["messages"][1]
    assert user_msg["role"] == "user"
    assert [b["type"] for b in user_msg["blocks"]] == ["image_ref", "text"]   # image stored as asset
    assert reply["meta"].get("error") is True
    assert "ZARGAR_ANTHROPIC_API_KEY" in reply["blocks"][0]["text"]


async def test_chat_send_rejects_bad_image(app_client):
    client, _ = app_client
    r = await client.post("/api/chat/threads", json={})
    tid = r.json()["id"]
    r = await client.post(f"/api/chat/threads/{tid}/messages",
                          json={"text": "x", "images": ["data:image/png;base64,AAAA"]})
    assert r.status_code == 400


async def test_chart_png_endpoint_on_sim_symbol(app_client):
    """The renderer path through the API. Yahoo is not reachable for sim
    symbols, so this asserts the failure is a clean 404 rather than a 500."""
    client, _ = app_client
    r = await client.get("/api/technique/chart/ZZZZNOPE", params={"tf": "5m"})
    assert r.status_code in (404, 400)


async def test_setups_and_runs_listing_empty(app_client):
    client, _ = app_client
    assert (await client.get("/api/technique/setups")).json() == []
    assert (await client.get("/api/technique/runs")).json() == []
    r = await client.get("/api/technique/runs/does-not-exist")
    assert r.status_code == 404


# --- grounding against a hand-built facts dict (pure) -----------------------

def _facts():
    return {
        "symbol": "TEST", "lastClose": 100.2, "primaryTf": "1m",
        "keyLevels": [{"price": 100.0, "kind": "support", "touches": 3, "sources": ["T1.3c"],
                       "position": "below", "effectiveKind": "support", "timeframes": ["1m"]},
                      {"price": 104.0, "kind": "resistance", "touches": 2, "sources": ["T1.3c"],
                       "position": "above", "effectiveKind": "resistance", "timeframes": ["1m"]}],
        "levels": {"1m": []},
        "bars": {"1m": [[i, 100.1, 100.4, 99.9, 100.2, 1000] for i in range(40)]},
        "volume": {"1m": {"belowFloor": False, "note": ""}},
        "wedge": {"1m": None},
        "session": {},
    }


def _analysis(**over) -> TechniqueAnalysis:
    base = dict(
        symbol="TEST", verdict="setup", setup_type="support_bounce", direction="long", trend="uptrend",
        levels=[{"price": 100.0, "kind": "support", "touches": 3, "note": "x"}],
        pattern_kind="none", pattern_present=False, pattern_widest_height=0.0,
        pattern_volume_declining=False, pattern_notes="",
        breakout_observed=False, breakout_verdict="none", breakout_level=0.0,
        breakout_volume_confirmed=False, breakout_decisive_candle=False, breakout_follow_through=False,
        breakout_holds_level=False, higher_tf_agrees=True,
        entry_price=100.0, entry_basis="at_level", entry_requires_confirmation=False,
        stop_price=99.5, stop_kind="mental", stop_reference="below_support",
        targets=[{"price": 101.6, "trim_pct": 30, "basis": "next_resistance"},
                 {"price": 103.0, "trim_pct": 40, "basis": "next_resistance"},
                 {"price": 104.0, "trim_pct": 15, "basis": "next_resistance"}],
        runner_pct=15.0, risk_reward=8.0, volume_verdict="ok (T2.9)", confidence=0.7,
        rules_fired=["T1.2", "T4.1", "R2"], no_trade_reasons=[],
        options_strike_guidance="just OTM", options_expiry_guidance="Friday", options_warnings=[],
        rationale="r")
    base.update(over)
    return TechniqueAnalysis.model_validate(base)


def test_grounding_passes_well_anchored_setup():
    g = ground_analysis(_analysis(), _facts())
    assert g["passed"], [c for c in g["checks"] if not c["passed"]]


def test_grounding_rejects_invented_level_and_entry():
    g = ground_analysis(_analysis(levels=[{"price": 97.37, "kind": "support", "touches": 2, "note": ""}],
                                  entry_price=97.37, stop_price=97.0), _facts())
    assert not g["passed"]
    names = [c["name"] for c in g["checks"] if not c["passed"]]
    assert any(n.startswith("level_97.37") for n in names)
    assert "entry_grounded" in names
    assert g["corrections"]


def test_grounding_rejects_rr_below_r2():
    g = ground_analysis(_analysis(targets=[{"price": 100.4, "trim_pct": 30, "basis": "next_resistance"}],
                                  risk_reward=0.8), _facts())
    assert not g["passed"]
    assert "rr_meets_R2" in [c["name"] for c in g["checks"] if not c["passed"]]


def test_grounding_rejects_unknown_rule_ids():
    g = ground_analysis(_analysis(rules_fired=["T1.2", "T9.9"]), _facts())
    assert "rule_ids_valid" in [c["name"] for c in g["checks"] if not c["passed"]]


def test_grounding_no_setup_needs_reasons():
    g = ground_analysis(_analysis(verdict="no_setup", entry_price=0.0, stop_price=0.0, targets=[],
                                  no_trade_reasons=[]), _facts())
    assert not g["passed"]
    g2 = ground_analysis(_analysis(verdict="no_setup", entry_price=0.0, stop_price=0.0, targets=[],
                                   no_trade_reasons=["R2 no room"]), _facts())
    assert g2["passed"]


def test_grounding_breakout_requires_confirmed_break():
    g = ground_analysis(_analysis(setup_type="breakout", entry_basis="on_break",
                                  entry_requires_confirmation=True, breakout_observed=True,
                                  breakout_verdict="fakeout"), _facts())
    assert "breakout_confirmed" in [c["name"] for c in g["checks"] if not c["passed"]]


def test_contract_shape_is_nested_and_camel():
    d = _analysis().to_contract()
    assert d["entry"]["requiresConfirmation"] is False
    assert d["stop"]["kind"] == "mental"
    assert d["targets"][0]["trimPct"] == 30
    assert d["breakout"]["verdict"] == "none"
    assert "rulesFired" in d and "noTradeReasons" in d
    d2 = _analysis(verdict="no_setup", entry_price=0.0, stop_price=0.0).to_contract()
    assert d2["entry"] is None and d2["stop"] is None
