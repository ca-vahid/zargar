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
    assert m["modelPriceSource"]["setting"] == "llm.rates"
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
    mcost = (await client.get("/api/technique/em/model-cost", params={"date": DAY})).json()
    assert mcost["cost"]["invoiceVerified"]["usd"] is None and mcost["cost"]["estimated"]["usd"] is None and mcost["cost"]["subscriptionAllocation"] is None,         "no invoice, no price, no allocation = UNKNOWN (None) on the wire - the panel prints 'unknown', never 0.00"
    assert "never subtracted" in mcost["neverNetted"] and mcost["runs"] >= 1
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
    from zargar.technique.profit_capture import resolve_links
    ledger = build_ledger([{"id": "x1", "orderId": "E1", "symbol": sym, "secType": "OPT", "side": "BUY", "qty": 1, "price": 1.05, "commission": 1.04, "tsMs": now - 60_000}],
                          window=session_window(DAY), as_of_ms=now, links=resolve_links([{"seq": 1, "runId": "r", "trigger": "d1", "stage": "entry", "orderId": "E1"}]))
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


async def test_forward_pricing_evidence_is_gathered_once_at_the_trigger_frozen_and_never_backfilled(rig, monkeypatch):
    """IR-05 through the runtime: a newly triggered candidate gets its pricing gates from CACHED evidence on the candidates'
    own task; a later pass carries the stored evaluation forward untouched; an old trigger is never back-filled; the chain
    read only happens behind its own knob (default off = contract gates unknown)."""
    client, eng = rig
    from zargar.domain import Quote
    from zargar.technique import source_candidates_runtime as rt
    fired = int(dt.datetime(2026, 9, 18, 14, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
    now = fired + 60_000 + 20_000
    cand = {"candidateId": "sc1-x", "variant": "source_continuation", "symbol": "AMD", "direction": "long", "disposition": "triggered", "firedTs": fired, "fillProxy": 552.0,
            "session": DAY, "geometry": {"entry": 551.42, "stop": 548.0, "targets": [556.0, 570.0, 580.0]}, "trigger": {"id": "k1", "kind": "breakout"}}
    eng.quotes.on_quote(Quote("AMD", bid=552.0, ask=552.05, last=552.02, ts=now, source="alpaca", quote_ts=now - 300, last_ts=now - 300))
    calls = []

    async def option_pick(*a, **kw):
        calls.append(kw)
        return {"available": False}
    monkeypatch.setattr(eng.technique, "option_pick", option_pick)
    await rt.attach_pricing(eng.technique, [cand], {}, now)
    pg = cand["pricingGates"]
    assert pg["evaluatedAt"] == now and pg["gates"]["firstSaleR"]["status"] == "unknown" and pg["gates"]["chase"]["status"] == "pass" and pg["gates"]["portfolio"]["status"] == "unknown" and pg["gates"]["contract"]["status"] == "unknown" and calls == [], "no chain read by default: the contract stays unknown"
    assert pg["overall"] == "unknown" and pg["orderFree"] is True
    later = dict(cand); later.pop("pricingGates")
    await rt.attach_pricing(eng.technique, [later], {"sc1-x": {"pricingGates": pg}}, now + 600_000)
    assert later["pricingGates"] is pg, "decided once at the trigger and carried forward - never recomputed on later evidence"
    old = {**cand, "candidateId": "sc1-old"}; old.pop("pricingGates")
    await rt.attach_pricing(eng.technique, [old], {}, now + 600_000)
    assert old["pricingGates"]["overall"] == "unknown" and "nothing is back-filled" in old["pricingGates"]["why"] and old["pricingGates"]["evaluatedAt"] is None
    await eng.settings.set(rt.CHAIN_KNOB, True)
    fresh = {**cand, "candidateId": "sc1-new"}; fresh.pop("pricingGates")
    await rt.attach_pricing(eng.technique, [fresh], {}, now)
    assert len(calls) == 1 and fresh["pricingGates"]["gates"]["contract"]["status"] == "unknown", "the configured research read ran once (background priority) and found nothing: still unknown"


# ---------------------------------------------------------------- final-completion goal section 3: causality through the real pipeline
def _utc(h, m):
    return dt.datetime(2026, 9, 18, h, m, tzinfo=dt.timezone.utc)


async def _store_revision(eng, *, rev_id, number, received, deleted=False, scenarios=True, completed=None):
    import copy
    src = copy.deepcopy(FX[AUTHOR])
    src["revision"].update({"id": rev_id, "revision": number, "receivedAt": received.isoformat(), "deleted": deleted})
    async with eng.sf() as s:
        if await s.get(TechniqueSourceRevision, rev_id) is None:
            s.add(TechniqueSourceRevision(id=rev_id, note_id=AUTHOR, revision=number, kind=("delete" if deleted else "edit"), deleted=deleted, published_at=_ts(src["revision"]["publishedAt"]),
                                          received_at=received, author_name="EnhancedMarket", text=("" if deleted else src["revision"]["text"]), attachments=[], content_hash=f"h{number}"))
        payload = None
        if scenarios and not deleted:
            payload = ss.build_scenarios(src)
            await ss.store_scenarios(s, note_id=AUTHOR, revision_id=rev_id, payload=payload, completed_at=(completed or received).isoformat())
        await s.commit()
    return payload


async def test_the_authoritative_revision_is_chosen_as_of_the_evaluation_and_a_withdrawn_source_keeps_its_history(rig):
    """Edit, correction-free replay, and delete/tombstone through the REAL loader, evaluator and storage. Identical updates create
    no revision at all (`test_em_source_revisions.py::test_revision_per_distinct_state_and_redelivery_is_a_receipt`)."""
    _client, eng = rig
    from zargar.technique import source_candidate_policy as scp
    from zargar.technique import source_candidates_runtime as rt
    ms = lambda d: int(d.timestamp() * 1000)                                               # noqa: E731
    rev2 = FX[AUTHOR]["revision"]["id"]
    p2 = await _store_revision(eng, rev_id=rev2, number=2, received=_ts(FX[AUTHOR]["revision"]["receivedAt"]), completed=_utc(13, 21))
    first = await rt.load_inputs(eng.technique, DAY, as_of_ms=ms(_utc(14, 0)))
    assert [p["revision"]["id"] for p in first["payloads"]] == [rev2] and first["withdrawn"] == {}
    rows = scp.evaluate_session(payloads=first["payloads"], plans_by_symbol=first["plans"], bars_by_symbol=first["bars"], baseline_by_symbol={}, session=DAY,
                                upto_ts=ms(_utc(14, 0)), context_by_run=first["contextByRun"])
    await rt.persist(eng.technique, DAY, rows, ms(_utc(14, 0)))
    assert any(r["disposition"] == "held_for_missing_evidence" and "evidence_names_MU_not_TSLA" in (r.get("reason") or "") for r in rows),         "the source HOLD set at ingestion reaches candidate creation through the real loader - not only a pure helper"
    ids2 = {sc["scenarioId"] for sc in p2["scenarios"]}
    # --- the author EDITS the message at 14:30 (revision 3): new scenario ids, the old revision is no longer independently actionable
    p3 = await _store_revision(eng, rev_id="rev-3-edit", number=3, received=_utc(14, 30))
    ids3 = {sc["scenarioId"] for sc in p3["scenarios"]}
    assert ids2.isdisjoint(ids3)
    replay = await rt.load_inputs(eng.technique, DAY, as_of_ms=ms(_utc(14, 10)))
    assert [p["revision"]["id"] for p in replay["payloads"]] == [rev2] and replay["withdrawn"] == {}, "a replay AS OF 14:10 does not know the 14:30 edit, although it now exists"
    after = await rt.load_inputs(eng.technique, DAY, as_of_ms=ms(_utc(14, 40)))
    assert [p["revision"]["id"] for p in after["payloads"]] == ["rev-3-edit"] and set(after["withdrawn"]) == ids2, "loading the newest artifact PER REVISION left both actionable; only the current one is"
    async with eng.sf() as s:
        before = {r.id: (r.disposition, dict(r.payload)) for r in (await s.execute(select(TechniqueSourceCandidate))).scalars().all()}
    n = await rt.withdraw(eng.technique, DAY, after["withdrawn"], ms(_utc(14, 40)))
    async with eng.sf() as s:
        now_rows = {r.id: r for r in (await s.execute(select(TechniqueSourceCandidate))).scalars().all()}
    terminal = {k for k, (d, _) in before.items() if d in scp.TERMINAL_DISPOSITIONS}
    assert terminal and all(now_rows[k].disposition == before[k][0] and now_rows[k].payload == before[k][1] for k in terminal), "historical decisions (AMD / SPCX refusals) are preserved untouched"
    open_before = set(before) - terminal
    assert n == len(open_before) and all(now_rows[k].disposition == "source_withdrawn" and now_rows[k].payload["history"][-1]["disposition"] == "source_withdrawn" for k in open_before)
    async with eng.sf() as s:
        assert (await s.execute(select(TechniqueArmed))).scalars().all() == [], "closing research eligibility never touches a production plan"
    # --- revision 4 has NO scenarios artifact yet (a worker is still reading it): nothing older becomes actionable in the meantime
    await _store_revision(eng, rev_id="rev-4-pending", number=4, received=_utc(14, 50), scenarios=False)
    pend = await rt.load_inputs(eng.technique, DAY, as_of_ms=ms(_utc(14, 55)))
    assert pend["payloads"] == [] and set(pend["withdrawn"]) == ids2 | ids3
    # --- the message is DELETED (tombstone revision 5)
    await _store_revision(eng, rev_id="rev-5-deleted", number=5, received=_utc(15, 0), deleted=True)
    gone = await rt.load_inputs(eng.technique, DAY, as_of_ms=ms(_utc(15, 5)))
    assert gone["payloads"] == [] and set(gone["withdrawn"].values()) == {"source deleted"}


async def test_a_born_candidate_is_frozen_two_ticks_a_restart_a_later_replan_and_duplicate_workers_change_nothing(rig):
    _client, eng = rig
    import asyncio
    import copy
    from zargar.technique import source_candidate_policy as scp
    from zargar.technique import source_candidates_runtime as rt
    ms = lambda d: int(d.timestamp() * 1000)                                               # noqa: E731
    await _store_revision(eng, rev_id=FX[AUTHOR]["revision"]["id"], number=2, received=_ts(FX[AUTHOR]["revision"]["receivedAt"]), completed=_utc(13, 21))
    inp = await rt.load_inputs(eng.technique, DAY, as_of_ms=ms(_utc(14, 0)))
    rows = scp.evaluate_session(payloads=inp["payloads"], plans_by_symbol=inp["plans"], bars_by_symbol=inp["bars"], baseline_by_symbol={}, session=DAY,
                                upto_ts=ms(_utc(14, 0)), context_by_run=inp["contextByRun"])
    born = [r for r in rows if r.get("definition")]
    assert born, "the fixture has candidates with app geometry (AMD / SPCX aligned triggers)"
    a, b = await asyncio.gather(rt.persist(eng.technique, DAY, rows, ms(_utc(14, 0))), rt.persist(eng.technique, DAY, copy.deepcopy(rows), ms(_utc(14, 0))))
    async with eng.sf() as s:
        stored = {r.id: dict(r.payload) for r in (await s.execute(select(TechniqueSourceCandidate))).scalars().all()}
    assert len(stored) == len({r["candidateId"] for r in rows}) and a + b == len(stored), "two workers persisting the same pass create each candidate ONCE"
    # a LATER same-session re-plan with different geometry exists now; a restart re-derives from storage
    sym = born[0]["symbol"]
    async with eng.sf() as s:
        base = (await s.execute(select(TechniqueRun).where(TechniqueRun.symbol == sym))).scalars().first()
        plan2 = copy.deepcopy(base.result["plan"])
        for t in plan2["triggers"]:
            if isinstance(t.get("stop"), dict) and t["stop"].get("price"):
                t["stop"]["price"] = float(t["stop"]["price"]) * 0.97
        s.add(TechniqueRun(id="replan-late", symbol=sym, trigger="preopen_replan", status="done", verdict="plan", result={"plan": plan2, "analysis": None},
                           config={"barsAssetId": "b2", "thresholds": {"min_risk_reward": 1.0}}, created_at=_utc(14, 20)))
        await s.commit()
    inp2 = await rt.load_inputs(eng.technique, DAY, as_of_ms=ms(_utc(14, 30)))
    assert "replan-late" in {p["runId"] for p in inp2["plans"][sym]} and "replan-late" in inp2["contextByRun"]
    fresh = scp.evaluate_session(payloads=inp2["payloads"], plans_by_symbol=inp2["plans"], bars_by_symbol=inp2["bars"], baseline_by_symbol={}, session=DAY,
                                 upto_ts=ms(_utc(14, 30)), context_by_run=inp2["contextByRun"])
    assert next(r for r in fresh if r["candidateId"] == born[0]["candidateId"])["planRunId"] != "replan-late", "even with NOTHING stored the birth plan is the one available at birth, not the latest"
    again = scp.evaluate_session(payloads=inp2["payloads"], plans_by_symbol=inp2["plans"], bars_by_symbol=inp2["bars"], baseline_by_symbol={}, session=DAY,
                                 upto_ts=ms(_utc(14, 30)), context_by_run=inp2["contextByRun"], frozen=stored)
    await rt.persist(eng.technique, DAY, again, ms(_utc(14, 30)))
    async with eng.sf() as s:
        stored2 = {r.id: dict(r.payload) for r in (await s.execute(select(TechniqueSourceCandidate))).scalars().all()}
    for c in born:
        assert stored2[c["candidateId"]]["definition"] == stored[c["candidateId"]]["definition"] and stored2[c["candidateId"]]["geometry"] == stored[c["candidateId"]]["geometry"]
        assert stored2[c["candidateId"]]["disposition"] == stored[c["candidateId"]]["disposition"], "a terminal candidate is never re-decided"
    # an adversarial tick that OFFERS a different definition for a born, non-terminal candidate is ignored and recorded
    live = next((dict(r) for r in rows if r.get("definition") and r["disposition"] not in scp.TERMINAL_DISPOSITIONS), None)
    if live is None:
        live = {**copy.deepcopy(born[0]), "candidateId": "sc1-live", "disposition": "waiting"}
        live["definition"] = scp.definition_of(live)
        await rt.persist(eng.technique, DAY, [live], ms(_utc(14, 31)))
    moved = copy.deepcopy(live)
    moved["geometry"] = {**moved["geometry"], "stop": float(moved["geometry"]["stop"]) * 0.9}
    moved["definition"] = scp.definition_of(moved)
    await rt.persist(eng.technique, DAY, [moved], ms(_utc(14, 32)))
    async with eng.sf() as s:
        row = (await s.get(TechniqueSourceCandidate, live["candidateId"])).payload
    assert row["geometry"]["stop"] == live["geometry"]["stop"] and row["definition"]["definitionHash"] == live["definition"]["definitionHash"]
    assert row["reinterpretationIgnored"]["offeredHash"] == moved["definition"]["definitionHash"], "the first child/candidate keeps its stop and targets; the newer interpretation is on the record, not applied"


# ---------------------------------------------------------------- final-completion goal section 6: recorder -> database -> reducer -> API
async def test_enabled_capture_runs_queue_database_reducer_and_api_with_restart_full_queue_ambiguous_write_and_a_flat_end(rig, monkeypatch):
    client, eng = rig
    from types import SimpleNamespace
    from zargar.domain import Quote
    from zargar.models import Execution, Order, Portfolio
    from zargar.technique import profit_capture_runtime as rt
    pid, sym = "em-chain-book", "SBUX261002P00095000"
    now = [int(dt.datetime(2026, 9, 18, 14, 30, tzinfo=dt.timezone.utc).timestamp() * 1000)]          # 10:30 ET, a regular session minute
    monkeypatch.setattr(rt.time, "time", lambda: now[0] / 1000.0)
    cash = [10_000.0 - 2 * 1.00 * 100 - 2.08]
    real_portfolio = eng.positions.portfolio
    monkeypatch.setattr(eng.positions, "portfolio", lambda p: ({"cash": cash[0], "kind": "sim"} if p == pid else real_portfolio(p)))

    async def fill(oid, side, qty, px, fee, ts, entry=None):
        at = dt.datetime.fromtimestamp(ts / 1000.0, dt.timezone.utc)
        async with eng.sf() as s:
            if await s.get(Portfolio, pid) is None:
                s.add(Portfolio(id=pid, name="EM chain", kind="sim", base_currency="USD", cash=10_000.0)); await s.flush()
            s.add(Order(id=oid, portfolio_id=pid, symbol=sym, sec_type="OPT", side=side, qty=qty, order_type="LMT", status="FILLED")); await s.flush()
            s.add(Execution(id="x-" + oid, order_id=oid, portfolio_id=pid, symbol=sym, side=side, qty=qty, price=px, commission=fee, ts=at))
            s.add(Event(type="OrderFill", aggregate_type="order", aggregate_id=oid, portfolio_id=pid, ts=at, payload={"executionId": "x-" + oid, "executedAt": ts}))
            s.add(Event(type="TechniquePlanOrderResult", aggregate_type="technique_run", aggregate_id="run-chain", portfolio_id=pid, ts=at,
                        payload={"runId": "run-chain", "symbol": "SBUX", "trigger": "d1", "stage": ("entry" if side == "BUY" else "exit:tp2"), "orderId": oid,
                                 "entryOrderId": entry, "status": "FILLED"}))
            await s.commit()
    await fill("E1", "BUY", 2, 1.00, 2.08, now[0] - 600_000)
    trade = SimpleNamespace(trigger_id="d1", entry_order_id="E1", order_symbol=sym, instrument="options", direction="short", multiplier=100.0, filled_qty=2.0, remaining=2.0,
                            pending_exit_qty=0.0, avg_fill=1.00)
    armer = eng.technique.armer
    armer._armed["run-chain"] = SimpleNamespace(run_id="run-chain", symbol="SBUX", plan_for=DAY, config=SimpleNamespace(portfolio_id=pid), trades={"d1": trade})

    def quote(bid, ask):
        eng.quotes.on_quote(Quote(sym, bid=bid, ask=ask, last=(bid + ask) / 2, bid_size=10, ask_size=10, ts=now[0] - 50, source="opra", source_ts=now[0] - 300))
    try:
        await eng.settings.set("techniques.enhanced_market.default_portfolio", pid)
        obs = rt.build_observer(armer)
        quote(1.40, 1.50)
        assert obs.snap("periodic") is None and obs.stats["captured"] == 0, "OFF on the real caller: nothing collected, nothing queued, no query"
        await eng.settings.set(rt.KNOB, True)
        # --- an AMBIGUOUS acknowledgement: the row commits, then the writer reports a failure; the retry must not insert a second observation
        real_write, calls = obs._write, []

        async def flaky(rec):
            calls.append(rec["captureId"])
            await real_write(rec)
            if len(calls) == 1:
                raise ConnectionError("acknowledgement lost after the commit")
        obs._write = flaky
        obs._retry_sleep = 0.0
        first = obs.snap("periodic")
        await obs.wait_idle()
        assert first["reason"] == "restore" and calls == [first["captureId"]] * 2 and obs.stats["retries"] == 1
        # --- a RESTART with a tiny queue: three event snapshots, no yield in between - one lands, two are dropped and COUNTED
        obs2 = rt.build_observer(armer)
        obs2._maxsize = 1
        now[0] += 30_000; quote(1.60, 1.70)
        burst = [obs2.snap("pre_target", {"kind": "tp2", "runId": "run-chain"}) for _ in range(3)]
        assert all(burst) and obs2.stats["droppedQueueFull"] == 2
        await obs2.wait_idle()
        # --- the closing fill: the book is FLAT, and the terminal event snapshot still lands
        await fill("X1", "SELL", 2, 1.30, 2.08, now[0] + 5_000, entry="E1")
        trade.remaining = 0.0
        cash[0] += 2 * 1.30 * 100 - 2.08
        now[0] += 30_000
        end = obs2.snap("fill", {"kind": "tp2", "runId": "run-chain"})
        await obs2.wait_idle()
        assert end["book"]["openPositions"] == 0 and obs2.snap("periodic") is None, "a flat book records nothing periodic; the closing EVENT did land"
        async with eng.sf() as s:
            rows = (await s.execute(select(TechniqueBookSnapshot).where(TechniqueBookSnapshot.portfolio_id == pid).order_by(TechniqueBookSnapshot.captured_at, TechniqueBookSnapshot.seq))).scalars().all()
        assert [r.reason for r in rows] == ["restore", "pre_target", "fill"] and len({r.id for r in rows}) == 3, "the ambiguous write stored ONE row"
        api = (await client.get("/api/technique/em/profit-capture", params={"date": DAY})).json()
        cap = api["capture"]
        assert api["recorderOn"] is True and cap["status"] == "ok" and cap["snapshots"] == 3 and cap["flatAtEnd"] is True
        assert cap["coverage"]["recorderInstances"] == 2 and cap["coverage"]["recorderDrops"] == 2 and any(g["kind"] == "recorder_restart" for g in cap["coverage"]["gaps"])
        assert cap["realizedNetFinal"] == round(2 * (1.30 - 1.00) * 100 - 4.16, 4) and cap["closedTrades"][0]["tradeInstance"] == "E1" and cap["closedTrades"][0]["trigger"] == "d1"
        assert cap["peakExecutableNet"]["value"] != cap["peakDisplayedNet"]["value"], "the marked peak and the executable peak are two numbers, both shown"
        assert cap["peakExecutableNet"]["value"] == round(2 * (1.60 - 1.00) * 100 - 2.08 - 2.08, 4), "bid side, exit fee modelled once, entry fee from the ledger"
        rec = cap["reconciliation"]
        assert rec["status"] == "ok" and rec["difference"] == 0.0 and rec["feesDifference"] == 0.0 and rec["cashMinusLedgerFlow"] == 0.0 and rec["comparisonsUnavailable"] == []
        assert cap["coverage"]["revisedByLateExecutions"] == [] and [x["scorable"] for x in api["series"]] == [True, True, True]
    finally:
        armer._armed.pop("run-chain", None)
