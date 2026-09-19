"""EM integrated-review surface over the REAL app (integrated plan, 2026-09-18): the read-only routes for A-E, the order-free
forward candidate pass (persist + restart idempotence, nothing armed) and the defaults manifest. Real Postgres, real Engine
on the sim broker, real API via ASGITransport. The 09-18 author note is seeded from the captured fixture. No model calls."""
import datetime as dt
import json
import os

import httpx
import pytest
from sqlalchemy import select

from zargar.api.app import create_app
from zargar.domain import new_id
from zargar.engine import Engine
from zargar.models import (Event, TechniqueArmed, TechniqueBookSnapshot, TechniqueMethodNote, TechniqueRun, TechniqueSourceArtifact,
                           TechniqueSourceCandidate, TechniqueSourceRevision)
from zargar.technique import source_scenarios as ss
from zargar.technique.profit_capture import capture_book
from zargar.technique.service import attach_technique_layer

from .conftest import make_test_config

FX = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "em_source_notes_2026_09_18.json"), encoding="utf-8"))
AUTHOR = "ae7cfbc9010e4254bcdb714b821f7c79"
DAY = "2026-09-18"


def _ts(s):
    return dt.datetime.fromisoformat(str(s).replace(" ", "T", 1))


@pytest.fixture
async def rig(fresh_db):
    config = make_test_config()
    eng = Engine(config)
    await eng.start()
    await attach_technique_layer(eng)
    src = FX[AUTHOR]
    async with eng.sf() as s:
        s.add(TechniqueMethodNote(id=AUTHOR, message_id=src["note"]["messageId"], channel_id=src["note"]["channelId"], channel_name="watchlists", author="EnhancedMarket",
                                  kind="video", status="checked", text=src["revision"]["text"], images=[], posted_at=_ts(src["revision"]["publishedAt"]),
                                  transcript=src["transcript"]["text"], extraction=src["extraction"]["payload"], board_check=src["boardCheck"]))
        s.add(TechniqueSourceRevision(id=src["revision"]["id"], note_id=AUTHOR, revision=2, kind="edit", published_at=_ts(src["revision"]["publishedAt"]),
                                      received_at=_ts(src["revision"]["receivedAt"]), author_name="EnhancedMarket", text=src["revision"]["text"], attachments=[], content_hash="h"))
        s.add(TechniqueSourceArtifact(id=src["transcript"]["artifactId"], revision_id=src["revision"]["id"], note_id=AUTHOR, kind="transcript", input_hash="i", config_hash="c",
                                      payload={"text": src["transcript"]["text"]}, completed_at=_ts(src["transcript"]["completedAt"])))
        s.add(TechniqueSourceArtifact(id=src["extraction"]["artifactId"], revision_id=src["revision"]["id"], note_id=AUTHOR, kind="extraction", input_hash="i", config_hash="c",
                                      payload=src["extraction"]["payload"], completed_at=_ts(src["extraction"]["completedAt"])))
        for rid, p in FX["plans"].items():
            if p["symbol"] in ("AMD", "SPCX", "NVDA"):
                plan = {**p["plan"], "planFor": DAY, "triggers": [{**t, "entry": {"price": t.get("levelPrice")}} for t in p["plan"]["triggers"]]}
                s.add(TechniqueRun(id=rid, symbol=p["symbol"], trigger=p["trigger"], status="done", verdict="plan", result={"plan": plan, "analysis": None},
                                   config={"barsAssetId": "b", "thresholds": {}}, created_at=_ts(p["createdAt"])))
        s.add(Event(type="TechniqueFirstSale", aggregate_type="technique_run", aggregate_id="run-sbux", ts=dt.datetime(2026, 9, 18, 14, 0, tzinfo=dt.timezone.utc),
                    payload={"runId": "run-sbux", "symbol": "SBUX", "trigger": "d1", "direction": "short", "mode": "observe", "vehicle": {"instrument": "options", "quantity": 1.0},
                             "gate": {"rung": "tp2-full", "rRunnerEntry": 1.316, "minRiskReward": 3.0, "verdict": "fail", "reason": "first_sale_rr_below_min",
                                      "planTime": {"targetIndex": 2, "rr": 3.63}, "differsFromPlanTime": True}}))
        await s.commit()
    app = create_app(config, eng)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, eng
    await eng.technique.stop()
    await eng.stop()


async def test_manifest_shows_every_new_knob_at_its_safe_default(rig):
    client, _ = rig
    m = (await client.get("/api/technique/em/manifest")).json()
    eff = {k["key"].rsplit(".", 1)[-1]: (k["default"], k["effective"]) for k in m["knobs"]}
    assert eff["preparation_policy"] == ("baseline", "baseline") and eff["conditional_review_fix"] == ("report", "report") and eff["prep_audit_quota_pct"] == (0.0, 0.0)
    assert eff["book_snapshot_observe"] == (False, False) and eff["source_scenarios_observe"] == (False, False) and eff["source_candidates_observe"] == (False, False)
    assert eff["first_sale_rr_gate"] == ("off", "off") and m["policy"]["preparationPolicyVersion"] == "em-prep-policy-v1"
    assert m["observer"]["captured"] == 0, "the ED-04 recorder exists on the EM armer and has recorded nothing (OFF)"


async def test_source_table_lists_the_full_trigger_set_and_writes_nothing(rig):
    client, eng = rig
    r = await client.get("/api/technique/em/source-table", params={"date": DAY})
    assert r.status_code == 200
    t = r.json()
    by = {row["scenario"]["authorSupplied"]["symbolAsExtracted"]: row for row in t["rows"]}
    assert by["TSLA"]["scenario"]["symbol"]["status"] == "conflict" and by["MBGO"]["scenario"]["symbol"]["status"] == "unresolved" and by["TSLA"]["plans"] == []
    assert by["SPCX"]["plans"][0]["overall"] == "aligned_trigger_rejected_by_our_gates" and by["SPCX"]["plans"][0]["oppositeValidAtSameLevel"] == ["r2"]
    assert [x["trigger"] for x in by["NVDA"]["plans"][0]["triggers"]] == ["b1", "k1", "k2", "r1", "r2", "d1", "d2"]
    assert by["AMD"]["plans"][0]["prepDecision"]["disposition"] == "refused" and by["NVDA"]["stored"] is False
    assert {"GOOGL"} <= {a["symbol"] for a in t["avoid"]} and "unknown" in t["authorResult"]
    async with eng.sf() as s:
        assert (await s.execute(select(TechniqueSourceArtifact).where(TechniqueSourceArtifact.kind == "scenarios"))).scalars().all() == [], "a preview stores nothing"
    assert (await client.get("/api/technique/em/source-table", params={"date": "18-09-2026"})).status_code == 400


async def test_first_sale_prep_decision_and_profit_capture_routes(rig):
    client, eng = rig
    fs = (await client.get("/api/technique/em/first-sale", params={"date": DAY})).json()
    assert fs["mode"] == "off" and fs["rows"][0]["symbol"] == "SBUX" and fs["rows"][0]["rRunnerEntry"] == 1.316 and fs["rows"][0]["differsFromPlanTime"] is True
    rid = next(k for k, p in FX["plans"].items() if p["symbol"] == "AMD")
    d = (await client.get(f"/api/technique/em/runs/{rid}/prep-decision")).json()
    assert d["mode"] == "baseline" and d["modelReview"] == "absent" and d["disposition"] == "refused" and "explanation" in d
    assert (await client.get("/api/technique/em/runs/nope/prep-decision")).status_code == 404
    pc = (await client.get("/api/technique/em/profit-capture", params={"date": DAY})).json()
    assert pc["recorderOn"] is False and pc["capture"]["status"] == "no_snapshots" and "UNKNOWN" in pc["note"]
    pid = "book-x"
    await eng.settings.set("techniques.enhanced_market.default_portfolio", pid)
    from zargar.technique.profit_capture import build_ledger
    from zargar.technique.profit_capture_runtime import session_window
    sym = "SBUX261002P00095000"
    pos = {"runId": "r", "trigger": "d1", "tradeInstance": "E1", "symbol": sym, "underlying": "SBUX", "direction": "short", "instrument": "options", "multiplier": 100.0,
           "positionSide": "long", "original": 1, "remaining": 1, "pendingExit": 0, "avgFill": 1.05}
    now = int(dt.datetime(2026, 9, 18, 15, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
    ledger = build_ledger([{"orderId": "E1", "symbol": sym, "side": "BUY", "qty": 1, "price": 1.05, "commission": 1.04, "tsMs": now - 60_000}], window=session_window(DAY), as_of_ms=now)
    rec = capture_book(ids={"portfolioId": pid, "session": DAY, "build": "t"}, seq=1, now_ms=now, reason="periodic", causal=None, cash=9000.0, positions=[pos], instance="obs-t", ledger=ledger,
                       quotes={sym: {"symbol": sym, "bid": 0.9, "ask": 1.0, "last": 0.95, "bidSize": 5, "askSize": 5, "sizeUnit": "contracts", "source": "opra", "quoteTs": now - 500}}, fee_per_contract=1.04)
    async with eng.sf() as s:
        s.add(TechniqueBookSnapshot(id=rec["captureId"], portfolio_id=pid, session=DAY, seq=1, captured_at=dt.datetime.fromtimestamp(now / 1000, dt.timezone.utc), reason="periodic", scorable=True, payload=rec))
        await s.commit()
    pc2 = (await client.get("/api/technique/em/profit-capture", params={"date": DAY})).json()
    assert pc2["capture"]["status"] == "ok" and pc2["series"][0]["executable"] == -17.08 and pc2["series"][0]["displayed"] == -11.04, "bid-side estimate vs mid mark, side by side"


async def test_the_forward_candidate_pass_is_off_by_default_order_free_and_restart_idempotent(rig):
    client, eng = rig
    from zargar.technique import source_candidates_runtime as rt
    now = int(dt.datetime(2026, 9, 18, 14, 30, tzinfo=dt.timezone.utc).timestamp() * 1000)          # 10:30 ET on the session
    assert await rt.tick(eng.technique, now) == {"enabled": False}
    async with eng.sf() as s:
        src = await ss.source_for_note(s, AUTHOR)
        payload = ss.build_scenarios(src)
        await ss.store_scenarios(s, note_id=AUTHOR, revision_id=payload["revision"]["id"], payload=payload, completed_at="2026-09-18T13:21:00+00:00")
        await s.commit()
    cands = await rt.load_inputs(eng.technique, DAY)
    assert len(cands["payloads"]) == 1 and set(cands["plans"]) >= {"AMD", "SPCX", "NVDA"}
    from zargar.technique import source_candidate_policy as scp
    rows = scp.evaluate_session(payloads=cands["payloads"], plans_by_symbol=cands["plans"], bars_by_symbol=cands["bars"], baseline_by_symbol={}, session=DAY, upto_ts=now)
    n1 = await rt.persist(eng.technique, DAY, rows, now)
    n2 = await rt.persist(eng.technique, DAY, rows, now + 60_000)                                  # the same state a minute later / after a restart
    assert n1 == len(rows) > 0 and n2 == 0, "re-deriving the same state rewrites nothing and duplicates nothing"
    async with eng.sf() as s:
        stored = (await s.execute(select(TechniqueSourceCandidate))).scalars().all()
        armed = (await s.execute(select(TechniqueArmed))).scalars().all()
    assert len(stored) == len({r["candidateId"] for r in rows}) and armed == [], "candidates never arm"
    assert all(str((r.payload or {}).get("origin", "")).startswith("scenario:") for r in stored)
    disp = {r.symbol or r.id: r.disposition for r in stored}
    assert disp["AMD"] == "refused" and disp["SPCX"] == "refused"
    api = (await client.get("/api/technique/em/candidates", params={"date": DAY})).json()
    assert api["source"] == "forward" and {x["disposition"] for x in api["rows"]} <= set(scp.DISPOSITIONS) and all(x["orderFree"] for x in api["rows"])
    with pytest.raises(Exception):
        await eng.technique.arm_plan("sc1-does-not-exist", {})
