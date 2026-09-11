"""Codex Thursday follow-up (2026-09-10): the two picker gates, warm-up parity (F99) and the EM scorer boundary (F107).

Gate 1 (F104): the model's premium gate walks the venue's LISTED strikes when the plan carries a listing, else the
synthetic grid — and the read says which. Gate 2 (F105): a delayed chain ask never conclusively vetoes a candidate;
the nearest listed contracts are re-priced on the live NBBO before any refusal, and the refusal names what it examined.
"""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

from zargar.marketdata import persist_bars
from zargar.marketstructure import aggregate, filter_session
from zargar.marketstructure.sessions import ET
from zargar.techniques.team2.plan import build_skeleton, complete_plan
from zargar.techniques.team2.premium import PremiumModel, otm_ladder
from zargar.techniques.team2.rules import Team2Rules
from zargar.techniques.team2.runner import Team2Runner
from zargar.techniques.team2.session import simulate_session

from .test_team2_integrity import drift_day
from .test_team2_runner import rig  # noqa: F401
from .test_team2_session import DAY, PREV, make_rules, path_1m, prev_day_bars, trend_day

TS_1404 = int(dt.datetime(2026, 9, 10, 14, 4, tzinfo=ET).timestamp() * 1000)


# ---------------------------------------------------------------- gate 1: the listing is the ladder
def test_the_listed_half_strike_is_examined_and_picked():
    # IWM 2026-09-10 14:04: spot 287.76, sigma 0.2111 — the $1 grid tests 287 (under the floor) and stops;
    # the venue lists 287.5, which models inside the band
    model = PremiumModel(sigma=0.2111)
    grid = model.pick_strike(287.76, TS_1404, "short", target_premium=0.6, premium_floor=0.2, step=1.0)
    listed = model.pick_strike(287.76, TS_1404, "short", target_premium=0.6, premium_floor=0.2, step=1.0,
                               strikes=[285.0, 285.5, 286.0, 286.5, 287.0, 287.5, 288.0, 288.5, 289.0])
    assert grid is None
    assert listed is not None and listed[0] == 287.5 and 0.2 <= listed[1] <= 0.9


def test_the_ladder_is_the_listing_when_given_and_otm_only():
    assert otm_ladder(287.76, False, strikes=[286, 287.5, 288, 287, 289]) == [287.5, 287.0, 286.0]
    assert otm_ladder(287.76, True, strikes=[286, 287.5, 288, 287, 289]) == [288.0, 289.0]
    assert otm_ladder(287.76, False, step=1.0, max_steps=3) == [287.0, 286.0, 285.0]
    assert otm_ladder(287.76, True, strikes=[286.0]) == []            # nothing listed OTM: an empty walk, not a guess
    near = PremiumModel(sigma=0.2).nearest_otm(287.76, TS_1404, "long", strikes=[286.0])
    assert near is None


def _read(listing: dict | None, **rule_kw):
    rules = make_rules(**rule_kw)
    prev = prev_day_bars()
    today = path_1m(DAY, (4, 0), (20, 0), drift_day)
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(prev, 15), rules), today)
    if listing is not None:
        plan["listedStrikes"] = listing
    return simulate_session(plan, today, rules, sigma=0.2, warmup_1m=prev)


def test_the_read_says_which_ladder_it_walked():
    grid = _read(None)
    fires = [e for e in grid.events if e["event"] == "fire"]
    assert fires and all(e.get("strikeSource") == "grid" for e in fires)
    assert all("synthetic grid" in e["why"] for e in fires)
    # the same day with the venue's half-strike listing stamped on the plan: at least as many entries, all "listed"
    ks = [k / 2 for k in range(2 * 540, 2 * 600)]
    listed = _read({"expiry": DAY.isoformat(), "strikes": ks, "source": "chain"})
    lf = [e for e in listed.events if e["event"] == "fire"]
    assert len(lf) >= len(fires) and all(e.get("strikeSource") == "listed" for e in lf)
    assert all(e["strike"] in ks for e in lf)
    # a refusal names the ladder too
    refused = _read({"expiry": DAY.isoformat(), "strikes": ks, "source": "chain"}, target_premium=0.10, premium_floor=0.20)
    skips = [e for e in refused.events if e["event"] == "skip_no_contract"]
    assert skips and all(e.get("strikeSource") == "listed" and "listed strikes" in e["why"] for e in skips)


def test_under_quotes_authority_the_model_is_a_proxy_not_a_veto():
    ks = [k / 2 for k in range(2 * 540, 2 * 600)]
    listing = {"expiry": DAY.isoformat(), "strikes": ks, "source": "chain"}
    # a band nothing models in: the model path refuses, the quotes path fires on the nearest OTM proxy and says so
    grid = _read(listing, target_premium=0.10, premium_floor=0.20)
    assert not [e for e in grid.events if e["event"] == "fire"]
    assert [e for e in grid.events if e["event"] == "skip_no_contract"]
    prev = prev_day_bars()
    today = path_1m(DAY, (4, 0), (20, 0), drift_day)
    rules = make_rules(target_premium=0.10, premium_floor=0.20)
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(prev, 15), rules), today)
    plan["listedStrikes"], plan["contractAuthority"] = listing, "quotes"
    res = simulate_session(plan, today, rules, sigma=0.2, warmup_1m=prev)
    fires = [e for e in res.events if e["event"] == "fire"]
    assert fires and all(e["modelBand"] == "out" and e["contractAuthority"] == "quotes" and e["strike"] in ks for e in fires)
    assert [e for e in res.events if e["event"] == "model_out_of_band"]
    assert not [e for e in res.events if e["event"] == "skip_no_contract"]


# ---------------------------------------------------------------- gate 2: fresh quotes before any refusal
def row(strike, ask, *, expiry, kind="put"):
    return {"symbol": f"IWM{expiry:%y%m%d}{'P' if kind == 'put' else 'C'}{int(strike * 1000):08d}",
            "underlying": "IWM", "option_type": kind, "strike": strike,
            "bid": round(max(0.01, ask - 0.01), 2), "ask": ask, "volume": 33008,
            "open_interest": 717, "greeks": {"delta": -0.385, "mid_iv": 0.2111}}


def _runner(chain, fresh_prices: dict[float, tuple[float, float]] | None, *, spot=287.76, **rule_kw):
    today = dt.datetime.now(ET).date()
    provider = SimpleNamespace(expirations=AsyncMock(return_value=[today.isoformat()]),
                               chain=AsyncMock(return_value=[row(k, a, expiry=today) for k, a in chain]))

    async def fresh(candidate):
        k = float(candidate["strike"])
        if fresh_prices and k in fresh_prices:
            bid, ask = fresh_prices[k]
            candidate.update(ask=ask, bid=bid, priced="opra")
        else:
            candidate["priced"] = "chain"
        return candidate
    options = SimpleNamespace(provider=lambda: provider, reprice=AsyncMock(side_effect=fresh))
    runner = Team2Runner.__new__(Team2Runner)
    runner.engine = SimpleNamespace(options=options, quotes=SimpleNamespace(get=lambda symbol: SimpleNamespace(last=spot)))
    runner.rules = lambda: make_rules(**rule_kw)
    runner._logged = []
    runner._log = lambda ap, kind, msg, **kw: runner._logged.append((kind, msg, kw))
    trade = SimpleNamespace(entry=spot, direction="short", errors=[], trigger_id="probe")
    return runner, trade, options


async def test_a_delayed_ask_under_the_floor_does_not_veto_before_the_live_quote():
    # F105: CBOE 287.5P ask 0.19 (one cent under the floor); OPRA says 0.20/0.21 -> the contract is taken
    runner, trade, options = _runner([(287.5, 0.19), (287.0, 0.10), (286.5, 0.05)], {287.5: (0.20, 0.21)})
    c = await runner.pick_contract(SimpleNamespace(symbol="IWM"), trade)
    assert c is not None and c["strike"] == 287.5 and c["ask"] == 0.21 and c["priced"] == "opra", trade.errors
    assert options.reprice.await_count >= 1
    kind, msg, kw = runner._logged[-1]
    assert kind == "contract" and kw["priced"] == "opra" and any(x["strike"] == 287.5 and x["delayedAsk"] == 0.19 for x in kw["examined"])


async def test_a_live_quote_under_the_floor_refuses_even_when_the_chain_was_in_band():
    runner, trade, options = _runner([(287.5, 0.24), (287.0, 0.10)], {287.5: (0.15, 0.16), 287.0: (0.08, 0.09)})
    c = await runner.pick_contract(SimpleNamespace(symbol="IWM"), trade)
    assert c is None
    assert "examined 287.5 ask 0.16 (opra, chain 0.24)" in trade.errors[-1], trade.errors
    kind, msg, kw = runner._logged[-1]
    assert kind == "contract_refused" and len(kw["examined"]) == 1 and kw["listed"] == 2   # the walk stops on a fresh ask under the floor


async def test_no_delayed_price_is_read_and_the_walk_is_nearest_spot_first():
    # F108: a delayed ask of $0.05 (far under the floor) must not keep the contract from a live quote
    runner, trade, options = _runner([(287.5, 0.05), (287.0, 0.04)], {287.5: (0.20, 0.21), 287.0: (0.09, 0.10)})
    c = await runner.pick_contract(SimpleNamespace(symbol="IWM"), trade)
    assert c is not None and c["strike"] == 287.5 and c["priced"] == "opra", trade.errors
    kind, msg, kw = runner._logged[-1]
    assert [x["strike"] for x in kw["examined"]] == [287.5, 287.0]         # nearest spot first, not delayed-ask order


async def test_the_quote_bound_defers_instead_of_refusing_the_unexamined():
    chain = [(287.5, 1.5), (287.0, 1.2), (286.5, 1.0), (286.0, 0.9), (285.5, 0.7), (285.0, 0.6), (284.5, 0.5), (284.0, 0.4)]
    fresh = {k: (a + 0.9, a + 1.0) for k, a in chain}                        # everything quoted live ABOVE the band
    runner, trade, options = _runner(chain, fresh, quote_candidates=3)
    assert await runner.pick_contract(SimpleNamespace(symbol="IWM"), trade) is None
    kind, msg, kw = runner._logged[-1]
    assert kind == "contract_deferred" and kw["unexamined"] == 5 and options.reprice.await_count == 3
    assert "5 listed contract(s) further out not examined" in trade.errors[-1]


async def test_a_fresh_ask_under_the_floor_ends_the_walk_as_a_refusal():
    chain = [(287.5, 0.30), (287.0, 0.20), (286.5, 0.10), (286.0, 0.05)]
    fresh = {287.5: (0.14, 0.15), 287.0: (0.08, 0.09), 286.5: (0.04, 0.05), 286.0: (0.02, 0.03)}
    runner, trade, options = _runner(chain, fresh)
    assert await runner.pick_contract(SimpleNamespace(symbol="IWM"), trade) is None
    kind, msg, kw = runner._logged[-1]
    assert kind == "contract_refused" and options.reprice.await_count == 1 and kw["unexamined"] == 0


async def test_no_live_quote_means_deferred_never_a_chain_priced_fill():
    runner, trade, options = _runner([(287.5, 0.60)], None)                   # reprice never serves OPRA
    assert await runner.pick_contract(SimpleNamespace(symbol="IWM"), trade) is None
    kind, msg, kw = runner._logged[-1]
    assert kind == "contract_deferred" and kw["unpriced"] == 1 and "no live quote" in trade.errors[-1]
    # the explicit opt-out (require_fresh_quote=False) is the only way the delayed chain prices a fill, and it says so
    runner, trade, options = _runner([(287.5, 0.60)], None, require_fresh_quote=False)
    c = await runner.pick_contract(SimpleNamespace(symbol="IWM"), trade)
    assert c is not None and c["priced"] == "chain" and c["ask"] == 0.60


async def test_nothing_listed_otm_is_a_named_refusal_not_a_crash():
    runner, trade, options = _runner([(288.0, 0.45), (288.5, 0.70)], None)
    assert await runner.pick_contract(SimpleNamespace(symbol="IWM"), trade) is None
    assert "no OTM contract listed" in trade.errors[-1] and options.reprice.await_count == 0


async def test_the_contract_verdict_is_journaled_with_every_candidate():
    # cohort v2 trail: the verdict and its examined list go to the append-only journal under the plan run
    for chain, fresh, verdict in (([(287.5, 0.19)], {287.5: (0.20, 0.21)}, "picked"),
                                  ([(287.5, 0.60)], None, "deferred"),
                                  ([(287.5, 0.30)], {287.5: (0.14, 0.15)}, "refused")):
        runner, trade, options = _runner(chain, fresh)
        runner.engine.journal = SimpleNamespace(append=AsyncMock())
        await runner.pick_contract(SimpleNamespace(symbol="IWM", run_id="run-1"), trade)
        calls = [c for c in runner.engine.journal.append.await_args_list if c.args[0] == "TechniquePlanContract"]
        assert len(calls) == 1, verdict
        payload = calls[0].args[1]
        assert payload["verdict"] == verdict and payload["runId"] == "run-1" and payload["examined"][0]["strike"] == 287.5
        assert calls[0].kwargs == {"aggregate_type": "technique_run", "aggregate_id": "run-1"}


async def test_a_failed_journal_write_is_recorded_as_a_trail_gap():
    runner, trade, options = _runner([(287.5, 0.19)], {287.5: (0.20, 0.21)})
    runner._trail_gaps = {}
    runner.engine.journal = SimpleNamespace(append=AsyncMock(side_effect=RuntimeError("db down")))
    alerts = []

    async def _alert(ap, text, **kw):
        alerts.append(text)
    runner._alert = _alert
    ap = SimpleNamespace(symbol="IWM", run_id="run-2")
    c = await runner.pick_contract(ap, trade)
    assert c is not None                                              # the trade is not blocked by the record
    gaps = runner.trail_gaps("run-2")
    assert len(gaps) == 1 and gaps[0]["event"] == "contract_picked" and "db down" in gaps[0]["error"]
    assert [k for k, m, kw in runner._logged if k == "trail_gap"] and len(alerts) == 1
    assert runner.trail_gaps("run-9") == []


async def test_early_picker_exits_still_record_a_verdict():
    runner, trade, options = _runner([(287.5, 0.19)], {287.5: (0.20, 0.21)})
    runner.engine.journal = SimpleNamespace(append=AsyncMock())
    ap = SimpleNamespace(symbol="IWM", run_id="run-3")
    options.provider().expirations = AsyncMock(return_value=[])              # no same-day expiry listed
    assert await runner.pick_contract(ap, trade) is None
    p = [c.args[1] for c in runner.engine.journal.append.await_args_list if c.args[0] == "TechniquePlanContract"]
    assert len(p) == 1 and p[0]["verdict"] == "deferred" and p[0]["stage"] == "expiry"
    runner.engine.options = None
    runner.engine.journal.append.reset_mock()
    trade.errors.clear()
    assert await runner.pick_contract(ap, trade) is None
    p = [c.args[1] for c in runner.engine.journal.append.await_args_list if c.args[0] == "TechniquePlanContract"]
    assert len(p) == 1 and p[0]["stage"] == "service"


# ---------------------------------------------------------------- the runner stamps the listing on the plan
async def test_the_runner_stamps_todays_listing_and_the_read_walks_it(rig, monkeypatch):
    eng, sim = rig
    prev = prev_day_bars()
    today, _ = trend_day(prev)
    await persist_bars(eng.sf, prev)
    await persist_bars(eng.sf, filter_session(today, "pre"))
    today_iso = dt.datetime.now(ET).date().isoformat()
    ks = [k / 2 for k in range(2 * 540, 2 * 600)]

    async def _exps(self, symbol):
        return [today_iso]

    async def _chain(self, symbol, expiry):
        return [row(k, 0.3, expiry=dt.date.fromisoformat(expiry)) for k in ks]
    monkeypatch.setattr(eng.options.provider().__class__, "expirations", _exps)
    monkeypatch.setattr(eng.options.provider().__class__, "chain", _chain)
    out = await eng.team2.nightly_plans(DAY.isoformat(), arm=True)
    ap = eng.team2_runner.get(out["armed"][0])
    await eng.team2.preopen_complete()
    for b in filter_session(today, "rth")[:2]:
        await eng.team2_runner.on_bar(ap.run_id, b)
    listing = ap.plan.get("listedStrikes") or {}
    assert listing.get("expiry") == today_iso and listing.get("count") == len(ks) and listing["strikes"][0] == 540.0
    assert [e for e in ap.events if e["event"] == "listing"]
    audit = await eng.team2_runner.audit(ap.run_id)
    kinds = {(a["type"], a["payload"].get("event")) for a in audit}
    assert ("TechniquePlanRead", "listing") in kinds and ("TechniquePlanRead", "warmup") in kinds
    # the stamped plan replays on the same listing
    rep = await eng.team2.replay(ap.run_id)
    assert rep["strikeSource"] == "listed"
    assert ap.plan.get("contractAuthority") == "quotes"


async def test_a_failed_listing_fetch_is_said_once_and_the_read_runs_on_the_grid(rig):
    eng, sim = rig                                                      # the rig's chain stub returns []
    prev = prev_day_bars()
    today, _ = trend_day(prev)
    await persist_bars(eng.sf, prev)
    await persist_bars(eng.sf, filter_session(today, "pre"))
    out = await eng.team2.nightly_plans(DAY.isoformat(), arm=True)
    ap = eng.team2_runner.get(out["armed"][0])
    await eng.team2.preopen_complete()
    for b in filter_session(today, "rth")[:4]:
        await eng.team2_runner.on_bar(ap.run_id, b)
    assert "listedStrikes" not in ap.plan
    assert len([e for e in ap.events if e["event"] == "listing_unavailable"]) == 1
    fires = [e for e in ap.events if e["event"] == "fired"] or []
    sim_ = eng.team2_runner._last_sim.get(ap.run_id) or {}
    assert all(e.get("strikeSource") == "grid" for e in sim_.get("events", []) if e["event"] == "fire")


# ---------------------------------------------------------------- F99: one warm-up slice on every path
async def test_live_replay_and_sweep_seed_from_the_same_warmup(rig):
    eng, sim = rig
    prev = prev_day_bars()
    today, _ = trend_day(prev)
    await persist_bars(eng.sf, prev)
    await persist_bars(eng.sf, filter_session(today, "pre"))
    out = await eng.team2.nightly_plans(DAY.isoformat(), arm=True)
    ap = eng.team2_runner.get(out["armed"][0])
    await eng.team2.preopen_complete()
    for b in filter_session(today, "rth")[:2]:
        await eng.team2_runner.on_bar(ap.run_id, b)
    live = ap.plan.get("warmup") or {}
    assert live.get("hash") and live["sessionsUsed"] == [PREV.isoformat()]
    assert [e for e in ap.events if e["event"] == "warmup"]
    warm, rep = await eng.team2.warmup_for("SPY", DAY.isoformat())
    assert rep["hash"] == live["hash"] and len(warm) == live["rows"]
    await persist_bars(eng.sf, filter_session(today, "rth"))
    await eng.team2.stamp_run(ap)
    rep_ = await eng.team2.replay(ap.run_id)
    assert rep_["warmup"]["match"] is True and rep_["warmup"]["hash"] == live["hash"]
    sw = await eng.team2.sweep(DAY.isoformat(), DAY.isoformat(), symbols=["SPY"], sigma=0.2)
    ok = [r for r in sw["rows"] if r["status"] == "ok"]
    assert ok and ok[0]["warmup"]["hash"] == live["hash"] and ok[0]["strikeSource"] == "grid"
    assert sw["summary"]["strikeSource"] == "grid" and "listing" in sw["summary"]["strikeSourceNote"]


# ---------------------------------------------------------------- F107: EM scores EM's runs only
async def test_em_outcome_scorer_ignores_other_techniques_runs(rig):
    eng, sim = rig
    from zargar.domain import new_id
    from zargar.models import TechniqueRun
    from zargar.technique.service import TechniqueService
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)
    t2 = TechniqueRun(id=new_id(), technique="team2", tags=[], symbol="SPY", as_of=int(old.timestamp() * 1000),
                      primary_tf="2m", mode="plan", trigger="scan", status="done", verdict="plan", setup_type="team2",
                      confidence=None, grounded=True, facts={}, result={"plan": {}}, images={}, usage={}, llm={},
                      config={"technique": "team2"}, created_at=old)
    async with eng.sf() as s:
        s.add(t2)
        await s.commit()
    svc = TechniqueService(eng)
    res = await svc.score_pending()
    assert t2.id not in res["scored"] and all(f["runId"] != t2.id for f in res["failed"])
