"""em-experiment-v1 (2026-09-19): the dedicated experimental Practice book. Focused acceptance of the user's direction
`2026-09-19-ACTIVE-EXPERIMENTAL-PRACTICE-ROLLOUT.md`: sim-only routing, book-scoped settings and budgets, the baseline
unchanged, duplicate-safe preparation and promotion, confirmed-fill P-06 quantities with stop-first precedence, restart
restoration, and an eligible source candidate that REALLY reaches simulated order placement while the same research object
cannot arm through any ordinary path. Real engine on the sim broker, real API, real Postgres. No model calls."""
import asyncio
import copy
import datetime as dt

import pytest
from sqlalchemy import select

from zargar.domain import Bar
from zargar.models import Order, TechniqueArmed, TechniqueRun, TechniqueSourceCandidate
from zargar.technique import em_experiment as xp
from zargar.technique.arming import ArmConfig
from zargar.technique.rulebook import session_bounds

from .conftest import wait_for
from .test_technique_arming import _feed_until, _plan_run, _quote, rig  # noqa: F401  (rig is a fixture)


# ------------------------------------------------------------------------------------------------------- pure boundary
def _get(settings):
    return lambda k, d=None: settings.get(k, d)


def test_policy_is_resolved_per_book_and_an_invalid_setting_enables_nothing():
    s = {xp.KEY: {"enabled": True, "portfolioId": "XP", "overrides": dict(xp.BUNDLE)}, "techniques.enhanced_market.first_sale_rr_gate": "off",
         "techniques.enhanced_market.preparation_policy": "baseline"}
    g = _get(s)
    assert xp.config(g)["enabled"] and xp.book_policy(g, "XP", "first_sale_rr_gate", "off") == "enforce"
    assert xp.book_policy(g, "BASE", "first_sale_rr_gate", "off") == "off" and xp.book_policy(g, None, "first_sale_rr_gate", "off") == "off", "the baseline book reads the technique-wide setting"
    assert xp.book_policy(g, "XP", "runner_protection", "off") == "execute" and xp.book_policy(g, "BASE", "runner_protection", "off") == "off"
    assert xp.prep_policy(g, "XP")["preparationPolicy"] == "deterministic" and xp.prep_policy(g, "XP")["conditionalReviewFix"] == "apply"
    assert xp.prep_policy(g, "BASE")["preparationPolicy"] == "baseline" and "experiment" not in xp.prep_policy(g, "BASE")
    bad = _get({xp.KEY: {"enabled": True, "portfolioId": "XP", "overrides": {"first_sale_rr_gate": "yolo", "size_full": 2}}})
    c = xp.config(bad)
    assert c["enabled"] is False and len(c["errors"]) == 2 and xp.book_policy(bad, "XP", "first_sale_rr_gate", "off") == "off", "an invalid experiment enables NOTHING"
    assert xp.config(_get({}))["enabled"] is False and xp.run_tags(_get({})) == []


def test_the_boundary_is_two_way_and_sim_only():
    g = _get({xp.KEY: {"enabled": True, "portfolioId": "XP", "overrides": dict(xp.BUNDLE)}})
    tagged, plain = {"tags": xp.run_tags(g)}, {"tags": ["ingest"]}
    sim, live = {"kind": "sim"}, {"kind": "live"}
    assert xp.arm_refusal(g, tagged, "XP", sim) is None and xp.arm_refusal(g, plain, "BASE", sim) is None
    assert "only in the experimental" in xp.arm_refusal(g, tagged, "BASE", sim), "an experimental plan never reaches the baseline book"
    assert "accepts only plans minted for the experiment" in xp.arm_refusal(g, plain, "XP", sim), "an ordinary plan never reaches the experimental book"
    assert "must be a sim" in xp.arm_refusal(g, tagged, "XP", live), "never a live or paper account"
    off = _get({xp.KEY: {"enabled": False, "portfolioId": "XP"}})
    assert "not enabled" in xp.arm_refusal(off, tagged, "XP", sim) and xp.arm_refusal(off, plain, "XP", sim) is None
    assert xp.run_book({"tags": [xp.TAG + "v", xp.BOOK_TAG + "OTHER"]}) == "OTHER" and "only in the experimental" in xp.arm_refusal(g, {"tags": [xp.TAG + "v", xp.BOOK_TAG + "OTHER"]}, "XP", sim)


def test_executable_plan_never_fabricates_and_never_replays_history():
    now = int(dt.datetime(2026, 9, 21, 14, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
    trig = {"id": "k1", "kind": "breakout", "direction": "long", "levelPrice": 100.0, "valid": True, "entry": {"price": 100.0}, "stop": {"price": 99.0},
            "targets": [{"price": 103.0}, {"price": 104.0}], "origin": "scenario:s1", "assessment": {"grade": "A", "score": 90}}
    d = {"candidateId": "sc1-x", "variant": "source_continuation", "symbol": "X", "session": "2026-09-21", "trigger": trig, "expiresTs": now + 3_600_000, "scenarioId": "s1",
         "definitionHash": "h", "revisionId": "rev", "author": "EnhancedMarket"}
    cand = {"candidateId": "sc1-x", "disposition": "waiting", "definition": d}
    plan, why = xp.executable_plan(cand, {"referencePrice": 99.5}, now_ms=now, stamp_={"version": "v"})
    assert why is None and plan["triggers"][0]["promotedFrom"] == "sc1-x" and "origin" not in plan["triggers"][0] and plan["eligibleFromTs"] == now // 60_000 * 60_000
    assert plan["expiresTs"] == now + 3_600_000 and plan["promotion"]["scenarioId"] == "s1" and plan["promotion"]["author"] == "EnhancedMarket"
    assert json_same(cand["definition"]["trigger"], trig), "the order-free definition is never mutated"
    for bad, word in (({**cand, "disposition": "triggered"}, "not live"), ({**cand, "disposition": "source_withdrawn"}, "not live"),
                      ({**cand, "definition": {**d, "expiresTs": now - 1}}, "outside the source horizon"),
                      ({**cand, "definition": {**d, "session": "2026-09-18"}}, "historical candidates are never replayed"),
                      ({**cand, "definition": {**d, "trigger": {**trig, "stop": None}}}, "never fabricated"),
                      ({**cand, "definition": {**d, "trigger": {**trig, "targets": []}}}, "never fabricated"),
                      ({**cand, "definition": {**d, "eligibleFromTs": now + 60_000}}, "not yet eligible")):
        p, w = xp.executable_plan(bad, {}, now_ms=now, stamp_={})
        assert p is None and word in w, (word, w)


def json_same(a, b):
    import json
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ------------------------------------------------------------------------------------------------------ the real engine
async def _launch(rig, **overrides):
    book = (await rig.client.post("/api/portfolios", json={"name": "EM Experimental", "kind": "sim", "starting_cash": float(rig.sim["cash"])})).json()
    await rig.eng.settings.set("techniques.enhanced_market.default_portfolio", rig.sim["id"], journal=False)
    # this rig has options switched off, so the runtime arm defaults (the SAME ones the baseline arms with) are shares here
    for k, v in (("instrument", "shares"), ("risk_pct", 1.0), ("max_qty", 50), ("slippage_pct", 1.0)):
        await rig.eng.settings.set(f"execution.{k}", v, journal=False)
    await rig.eng.settings.set(xp.KEY, {"enabled": True, "portfolioId": book["id"], "label": "EM Experimental", "version": xp.VERSION,
                                        "overrides": {**xp.BUNDLE, "first_sale_rr_gate": "off", **overrides}}, journal=False)
    return book


async def _xp_run(rig):
    close_ts = session_bounds(rig.days[3].isoformat())[1]
    return await rig.svc.analyze("TEST", as_of_ms=close_ts, wait=True, trigger="experiment", tags=xp.run_tags(rig.eng.settings.get))


def _trade(rig, run_id, kind="bounce"):
    d = rig.svc.armer.detail(run_id) or {}
    return next((t for t in d.get("trades", []) if t["kind"] == kind), {})


async def _open(rig, run, pid, *, max_qty=50):
    body = {"mode": "auto", "instrument": "shares", "portfolioId": pid, "riskPct": 1.0, "maxQty": max_qty, "slippagePct": 1.0}
    armed = await rig.svc.arm_plan(run["id"], body)
    bars = rig.sessions[armed["planFor"]]
    b1 = next(t for t in armed["triggers"] if t["kind"] == "bounce")

    async def q(bar):
        await _quote(rig, bar.close)
    _snap, i = await _feed_until(rig, run["id"], bars, lambda s: any(t["kind"] == "bounce" for t in s["trades"]), quote_fn=q)
    await _quote(rig, b1["entry"])
    await wait_for(lambda: _trade(rig, run["id"]).get("status") == "open", timeout=5)
    return armed, bars, b1, i


async def test_routing_is_sim_only_book_scoped_and_the_baseline_is_unchanged(rig):
    base_cash0 = float(rig.eng.positions.portfolio(rig.sim["id"])["cash"])
    book = await _launch(rig, first_sale_rr_gate="enforce")
    base_run, xp_run = await _plan_run(rig), await _xp_run(rig)
    with pytest.raises(ValueError, match="accepts only plans minted for the experiment"):
        await rig.svc.arm_plan(base_run["id"], {"mode": "auto", "instrument": "shares", "portfolioId": book["id"]})
    with pytest.raises(ValueError, match="only in the experimental Practice book"):
        await rig.svc.arm_plan(xp_run["id"], {"mode": "auto", "instrument": "shares", "portfolioId": rig.sim["id"]})
    await rig.eng.settings.set(xp.KEY, {**rig.eng.settings.get(xp.KEY), "overrides": {**xp.BUNDLE, "first_sale_rr_gate": "off"}}, journal=False)
    await _open(rig, base_run, rig.sim["id"])
    await _open(rig, xp_run, book["id"])
    armer = rig.svc.armer
    ap_base, ap_xp = armer._armed[base_run["id"]], armer._armed[xp_run["id"]]
    await rig.eng.settings.set(xp.KEY, {**rig.eng.settings.get(xp.KEY), "overrides": dict(xp.BUNDLE)}, journal=False)
    assert (armer.first_sale_policy(ap_base), armer.first_sale_policy(ap_xp)) == ("off", "enforce"), "two books, two first-sale policies, at the same time"
    assert (armer.runner_protection_policy(ap_base), armer.runner_protection_policy(ap_xp)) == ("off", "execute")
    assert armer.order_tags(ap_base) == [] and armer.order_tags(ap_xp) == xp.run_tags(rig.eng.settings.get)
    assert not armer._shadow_enabled(ap_base) and not armer._shadow_enabled(ap_xp), "the observation knob is off in this rig: off everywhere"
    await rig.eng.settings.set("techniques.enhanced_market.shadow_exit_observe", True, journal=False)
    assert armer._shadow_enabled(ap_base) and armer._shadow_enabled(ap_xp), "with the established knob on, P-02 stays a paired OBSERVATION in BOTH books"
    async with rig.eng.sf() as s:
        orders = (await s.execute(select(Order).where(Order.side == "BUY", Order.status == "FILLED"))).scalars().all()
    by_book = {o.portfolio_id: o for o in orders}
    assert set(by_book) == {rig.sim["id"], book["id"]} and by_book[book["id"]].tags == xp.run_tags(rig.eng.settings.get) and by_book[rig.sim["id"]].tags == []
    assert rig.eng.positions.portfolio(book["id"])["kind"] == "sim"
    pos = {pid: rig.eng.positions.position_qty(pid, "TEST", "STK") for pid in (rig.sim["id"], book["id"])}
    assert pos[rig.sim["id"]] > 0 and pos[book["id"]] > 0, "each book holds ITS OWN position: neither consumed the other's capacity or blocked its arm"
    assert rig.eng.positions.portfolio(book["id"])["cash"] < float(book["cash"]) and rig.eng.positions.portfolio(rig.sim["id"])["cash"] < base_cash0
    # rollback = a book-scoped pause: entries stop in THIS book, its position stays managed, the baseline is untouched
    r = await rig.client.post(f"/api/portfolios/{book['id']}/pause", json={"reason": "experiment rollback", "label": "em-experiment"})
    assert r.status_code == 200 and rig.eng.risk._halt.book_paused(book["id"]) and not rig.eng.risk._halt.book_paused(rig.sim["id"])


async def test_p06_is_an_executed_exit_in_the_experimental_book_only_with_conserved_quantity_and_stop_first(rig):
    book = await _launch(rig)
    base_run, xp_run = await _plan_run(rig), await _xp_run(rig)
    outcome = {}
    for name, run, pid in (("baseline", base_run, rig.sim["id"]), ("experiment", xp_run, book["id"])):
        _armed, bars, b1, i = await _open(rig, run, pid)
        entry, stop, tp1 = b1["entry"], b1["stop"], b1["targets"][0]
        filled = _trade(rig, run["id"])["filledQty"]
        await _quote(rig, tp1)
        await rig.svc.armer.on_bar(run["id"], Bar(symbol="TEST", tf="1m", ts=bars[i].ts, open=entry, high=tp1 + 0.05, low=entry, close=tp1 + 0.02, volume=1000))
        await _quote(rig, tp1)
        await wait_for(lambda r=run: any(e["kind"] == "tp1" and e.get("filledQty") for e in _trade(rig, r["id"]).get("exits", [])), timeout=5)
        t = _trade(rig, run["id"])
        tp1_qty, remaining = t["exits"][0]["filledQty"], t["remaining"]
        assert tp1_qty > 0 and remaining == filled - tp1_qty
        back = round((entry + tp1) / 2, 4)                                     # closes back through TP1, well above the stop
        await _quote(rig, back)
        await rig.svc.armer.on_bar(run["id"], Bar(symbol="TEST", tf="1m", ts=bars[i + 1].ts, open=tp1, high=tp1, low=back - 0.01, close=back, volume=1000))
        await _quote(rig, back)
        if name == "experiment":
            await wait_for(lambda r=run: _trade(rig, r["id"]).get("status") == "closed", timeout=5)
        outcome[name] = (_trade(rig, run["id"]), filled, tp1_qty, stop)
    t, filled, tp1_qty, _ = outcome["baseline"]
    assert [e["kind"] for e in t["exits"]] == ["tp1"] and t["status"] == "open", "the baseline book keeps the production ladder - P-06 stays an observation there"
    t, filled, tp1_qty, _ = outcome["experiment"]
    kinds = [e["kind"] for e in t["exits"]]
    assert kinds == ["tp1", "runner_protect"] and t["remaining"] == 0
    assert t["exits"][1]["qty"] == filled - tp1_qty and sum(e["filledQty"] for e in t["exits"]) == filled, "confirmed-fill quantities are conserved: nothing sold twice, nothing left"
    async with rig.eng.sf() as s:
        sells = (await s.execute(select(Order).where(Order.portfolio_id == book["id"], Order.side == "SELL"))).scalars().all()
    assert len(sells) == 2 and all(xp.TAG + xp.VERSION in (o.tags or []) for o in sells)


async def test_a_stop_goes_first_and_no_tp1_fill_means_no_runner_protection(rig):
    book = await _launch(rig)
    run = await _xp_run(rig)
    _armed, bars, b1, i = await _open(rig, run, book["id"])
    entry, stop, tp1 = b1["entry"], b1["stop"], b1["targets"][0]
    below = round(entry - 0.01, 4)                                                # below TP1 but NO TP1 fill has happened: nothing to protect
    await _quote(rig, below)
    await rig.svc.armer.on_bar(run["id"], Bar(symbol="TEST", tf="1m", ts=bars[i].ts, open=entry, high=entry, low=below, close=below, volume=1000))
    assert _trade(rig, run["id"])["exits"] == []
    await _quote(rig, tp1)
    await rig.svc.armer.on_bar(run["id"], Bar(symbol="TEST", tf="1m", ts=bars[i + 1].ts, open=entry, high=tp1 + 0.05, low=entry, close=tp1 + 0.02, volume=1000))
    await _quote(rig, tp1)
    await wait_for(lambda: any(e["kind"] == "tp1" and e.get("filledQty") for e in _trade(rig, run["id"]).get("exits", [])), timeout=5)
    await _quote(rig, stop - 0.02)                                                # this bar closes back through TP1 AND through the stop: the STOP owns it
    await rig.svc.armer.on_bar(run["id"], Bar(symbol="TEST", tf="1m", ts=bars[i + 2].ts, open=tp1, high=tp1, low=stop - 0.05, close=stop - 0.02, volume=1000))
    await _quote(rig, stop - 0.02)
    await wait_for(lambda: _trade(rig, run["id"]).get("status") == "closed", timeout=5)
    kinds = [e["kind"] for e in _trade(rig, run["id"])["exits"]]
    assert kinds == ["tp1", "stop"] and "runner_protect" not in kinds, "protective-exit precedence: the production stop is never displaced"


async def test_a_promoted_source_candidate_really_trades_in_the_experimental_book_and_the_research_object_never_arms(rig, monkeypatch):
    book = await _launch(rig)
    parent = await _plan_run(rig)
    plan = parent["result"]["plan"]
    day = plan["planFor"]
    bars = rig.sessions[day]
    now = int(bars[0].ts) + 30_000
    trig = copy.deepcopy(next(t for t in plan["triggers"] if t["kind"] == "bounce" and t["valid"]))
    trig["origin"] = "scenario:scn-1"
    definition = {"version": "source-continuation-v1", "variant": "source_continuation", "candidateId": "sc1-live", "scenarioId": "scn-1", "revisionId": "rev-2",
                  "noteId": "note-1", "author": "EnhancedMarket", "branchKey": "br1-x", "origin": "scenario:scn-1", "orderFree": True, "session": day, "symbol": "TEST",
                  "direction": "long", "trigger": trig, "geometry": {"entry": trig["entry"]["price"]}, "expiresTs": session_bounds(day)[1], "planRunId": parent["id"],
                  "definitionHash": "defhash"}
    async with rig.eng.sf() as s:
        s.add(TechniqueSourceCandidate(id="sc1-live", session=day, symbol="TEST", scenario_id="scn-1", variant="source_continuation", disposition="waiting",
                                       payload={"candidateId": "sc1-live", "disposition": "waiting", "definition": definition}))
        # the SAME research object as an ordinary plan run: the order-free boundary refuses it everywhere
        s.add(TechniqueRun(id="research-run", symbol="TEST", technique="enhanced_market", mode="plan", trigger="ingest", status="done", verdict="plan",
                           result={"plan": {**plan, "triggers": [trig]}}, config={**parent["config"], "origin": "scenario:scn-1"}))
        await s.commit()
    for pid in (rig.sim["id"], book["id"]):
        with pytest.raises(ValueError, match="order-free scenario candidate"):
            await rig.svc.arm_plan("research-run", {"mode": "auto", "instrument": "shares", "portfolioId": pid})
    a, b = await asyncio.gather(xp.promote_candidates(rig.svc, now), xp.promote_candidates(rig.svc, now))
    promoted = a["promoted"] + b["promoted"]
    assert len(promoted) == 1 and promoted[0]["candidateId"] == "sc1-live", (a, b)
    rid = promoted[0]["runId"]
    assert rid == xp.promoted_run_id("sc1-live", book["id"]) and (await xp.promote_candidates(rig.svc, now + 60_000))["promoted"] == [], "promoted ONCE: later ticks and restarts find the claim"
    ap = rig.svc.armer._armed[rid]
    assert str(ap.config.portfolio_id) == book["id"] and ap.plan["promotion"]["scenarioId"] == "scn-1" and ap.plan["promotion"]["definitionHash"] == "defhash"
    assert rig.svc.armer.seed_from_ts(ap) == now // 60_000 * 60_000, "a plan born intraday never replays bars from before its birth"
    with pytest.raises(ValueError, match="only in the experimental Practice book"):
        await rig.svc.arm_plan(await _clone(rig, rid), {"mode": "auto", "portfolioId": rig.sim["id"]})
    # it TRADES: the production tracker fires it, the order is placed and filled in the experimental sim book

    async def q(bar):
        await _quote(rig, bar.close)
    await _feed_until(rig, rid, bars, lambda s: any(t["kind"] == "bounce" for t in s["trades"]), quote_fn=q)
    await _quote(rig, trig["entry"]["price"])
    await wait_for(lambda: _trade(rig, rid).get("status") == "open", timeout=5)
    async with rig.eng.sf() as s:
        buys = (await s.execute(select(Order).where(Order.side == "BUY"))).scalars().all()
        armed_rows = (await s.execute(select(TechniqueArmed))).scalars().all()
    assert [(o.portfolio_id, o.status) for o in buys] == [(book["id"], "FILLED")] and xp.TAG + xp.VERSION in buys[0].tags, "a REAL simulated order, in the experimental book only"
    assert [(r.run_id, r.portfolio_id) for r in armed_rows] == [(rid, book["id"])] and rig.eng.positions.position_qty(rig.sim["id"], "TEST", "STK") == 0
    # restart restoration, even with the experiment switched off meanwhile: the open position keeps its plan and its exits
    await rig.svc.armer._persist(rig.svc.armer._armed[rid])
    async with rig.eng.sf() as s:
        row = await s.get(TechniqueArmed, rid)
    await rig.eng.settings.set(xp.KEY, {"enabled": False, "portfolioId": book["id"]}, journal=False)
    rig.svc.armer._armed.pop(rid)
    await rig.svc.armer.arm(rid, ArmConfig.from_dict(row.config or {}), restored=True, prior_state=dict(row.state or {}))
    restored = rig.svc.armer._armed[rid]
    assert str(restored.config.portfolio_id) == book["id"] and [t.status for t in restored.trades.values()] == ["open"], [t.status for t in restored.trades.values()]
    with pytest.raises(ValueError, match="the experiment is not enabled"):
        await rig.svc.arm_plan(await _clone(rig, rid), {"mode": "auto", "portfolioId": book["id"]})


async def _clone(rig, rid):
    async with rig.eng.sf() as s:
        src = await s.get(TechniqueRun, rid)
        new = "clone-" + rid[:20]
        if await s.get(TechniqueRun, new) is None:
            s.add(TechniqueRun(id=new, symbol=src.symbol, technique="enhanced_market", mode="plan", trigger="experiment", status="done", verdict="plan",
                               tags=list(src.tags or []), result=copy.deepcopy(dict(src.result or {})), config={k: v for k, v in (src.config or {}).items() if k != "origin"}))
            await s.commit()
    return new


async def test_preparation_is_deterministic_duplicate_safe_and_independent_of_the_baseline_arm(rig, monkeypatch):
    from zargar.technique import service as svc_mod
    book = await _launch(rig)
    monkeypatch.setattr(svc_mod, "last_completed_session", lambda now_ms=None: rig.days[3].isoformat())
    await rig.eng.settings.set("technique.walkforward.workers", 1, journal=False)
    sheet = await rig.svc.start_plan_sheet(["TEST"], label="sheet", wait=True)
    plan_for = sheet["params"]["planFor"]
    base = await rig.svc.promote(sheet["id"], "TEST", sheet["rows"][0]["session"], with_vision=False)
    await rig.svc.arm_plan(base["id"], {"mode": "auto", "instrument": "shares", "portfolioId": rig.sim["id"]})          # the BASELINE arms its own run in its own book
    first = await xp.prepare(rig.svc, plan_for)
    assert first["errors"] == [] and (first["rows"], first["eligible"], first["minted"], first["armed"], first["modelCalls"]) == (1, 1, 1, 1, 0), first
    again, third = await asyncio.gather(xp.prepare(rig.svc, plan_for), xp.prepare(rig.svc, plan_for))
    for r in (again, third):
        assert (r["minted"], r["armed"], r["alreadyArmed"], r["reusedRuns"]) == (0, 0, 1, 1), "a second / concurrent / post-restart preparation mints and arms NOTHING new"
    async with rig.eng.sf() as s:
        rows = (await s.execute(select(TechniqueArmed).where(TechniqueArmed.status == "armed"))).scalars().all()
        runs = (await s.execute(select(TechniqueRun).where(TechniqueRun.trigger == "experiment"))).scalars().all()
    assert sorted((r.portfolio_id, r.run_id == base["id"]) for r in rows) == sorted([(rig.sim["id"], True), (book["id"], False)]), \
        "the same candidate is armed once PER BOOK: the baseline arm neither blocks nor is blocked"
    assert len(runs) == 1 and set(xp.run_tags(rig.eng.settings.get)) <= set(runs[0].tags) and not (runs[0].result or {}).get("passes"), "zero model passes"
    st = (await rig.client.get("/api/technique/em/experiment")).json()
    assert st["config"]["enabled"] and st["armedRows"] == 1 and st["book"]["kind"] == "sim" and st["stamp"]["policyVersions"]["runnerProtection"] == "tp1-reclaim-runner-exit-v1"
    await rig.eng.settings.set(xp.KEY, {"enabled": False}, journal=False)
    off = await xp.prepare(rig.svc, plan_for)
    assert off["armed"] == 0 and "experiment not enabled" in off["errors"][0]


async def test_one_requalified_child_is_promoted_once_with_its_frozen_geometry(rig):
    book = await _launch(rig)
    parent = await _plan_run(rig)
    plan = parent["result"]["plan"]
    day = plan["planFor"]
    now = int(rig.sessions[day][20].ts) + 5_000
    child_trig = {"id": "rq1-child", "kind": "breakout", "direction": "long", "levelPrice": 101.4, "valid": True, "riskReward": 3.4, "setupType": "requalification",
                  "entry": {"price": 101.4, "basis": "on_break"}, "stop": {"price": 101.0, "reference": "fresh pivot"}, "targets": [{"price": 102.8, "basis": "author"}],
                  "origin": "scenario:scn-9"}
    definition = {"version": "requalification-v1", "variant": "requalification", "candidateId": "rq1-child", "childId": "rq1-child", "parentScenarioId": "scn-9", "branchKey": "br1-9",
                  "origin": "scenario:scn-9", "session": day, "symbol": "TEST", "direction": "long", "trigger": child_trig, "geometry": {"entry": 101.4, "stop": 101.0, "targets": [102.8]},
                  "eligibleFromTs": now - 120_000, "expiresTs": session_bounds(day)[1], "contextRunId": parent["id"], "definitionHash": "childhash"}
    async with rig.eng.sf() as s:
        s.add(TechniqueSourceCandidate(id="rq1-child", session=day, symbol="TEST", scenario_id="scn-9", variant="requalification", disposition="requalification_eligible",
                                       payload={"candidateId": "rq1-child", "disposition": "requalification_eligible", "definition": definition}))
        await s.commit()
    first = await xp.promote_candidates(rig.svc, now)
    assert [p["variant"] for p in first["promoted"]] == ["requalification"] and first["errors"] == []
    assert (await xp.promote_candidates(rig.svc, now + 60_000))["promoted"] == [], "ONE child, promoted ONCE"
    ap = rig.svc.armer._armed[first["promoted"][0]["runId"]]
    t = ap.plan["triggers"][0]
    assert (t["entry"]["price"], t["stop"]["price"], [x["price"] for x in t["targets"]]) == (101.4, 101.0, [102.8]), "the child's frozen geometry, never a rebuilt one"
    assert "requalification-v1" in ap.plan["promotion"]["eligibilityBasis"] and ap.plan["promotion"]["branchKey"] == "br1-9" and str(ap.config.portfolio_id) == book["id"]
    assert list(ap.trackers) == ["rq1-child"] and rig.svc.armer.seed_from_ts(ap) == now // 60_000 * 60_000
    # past its source horizon, with no open trade, the promoted plan is disarmed - the experiment never extends an idea
    assert await xp.expire_promoted(rig.svc, session_bounds(day)[1] + 1) == 1 and first["promoted"][0]["runId"] not in rig.svc.armer._armed
