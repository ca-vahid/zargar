"""W1.2 / W2.1 / W2.2 / W2.4 (2026-10-02 Tips review): one feasibility authority, fit-or-reshape before a budget
skip, the prompt contract (re-ask once), prefetch + seeded context. Offline: sim feed, a fake chain provider, a
scripted analyst client - no provider call, no network."""
import datetime as dt
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from zargar.domain import new_id
from zargar.engine import Engine
from zargar.models import Event, Signal
from zargar.options import occ as occ_mod
from zargar.signals.schemas import TradeSignal
from zargar.signals.service import attach_signal_layer
from zargar.techniques.tip import alternatives as alt
from zargar.techniques.tip import geometry as geo
from zargar.techniques.tip import prefetch as pf

from .conftest import make_test_config, wait_for
from .test_analyst_evidence import FakeChain
from .test_tip_express import row as chain_row
from .test_tip_kfin09_experiments import _Scripted, _text, _tool


class _S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


# ------------------------------------------------------------------ pure: the authority
def test_fit_expression_is_the_gates_arithmetic_and_sizes_at_the_final_stop():
    """The 9 'take -> refused' cases: the analyst sized at its DECLARED stop, the gate at the FINALIZED one."""
    s = _S()
    plan = {"underlyingStop": 99.9, "targets": [104.0], "fractions": [1.0]}      # 0.1% stop: inside the width floor
    final, fit = geo.fit_expression(direction="long", vehicle="shares", entry_ref=100.0, exit_plan=plan, bars=[],
                                    settings=s, premium=100.0, budget=0.5)
    assert fit["originalStop"] == 99.9 and fit["finalStop"] == 99.25 and fit["repairs"]
    assert fit["unitLoss"] == 0.75 and fit["qtyByRisk"] == 0 and "no quantity" in fit["reason"]
    # at the declared stop the old analyst arithmetic said 5 shares fit - the gate never would
    assert int(0.5 / 0.1) == 5
    _f2, rp = geo.plan_risk(mode="enforce", direction="long", vehicle="shares", entry_ref=100.0, exit_plan=plan,
                            bars=[], settings=s, limit=100.0, qty_requested=10, budget=0.5, budget_source="test")
    assert rp.finalStop == fit["finalStop"] and rp.unitLoss == fit["unitLoss"] and rp.qty == 0
    assert rp.reviewClass == "budget" and rp.repairs == fit["repairs"]
    # an option: delta-linear at the FINAL stop, floor and thesis checks identical on both sides
    _f3, fo = geo.fit_expression(direction="long", vehicle="option", entry_ref=100.0, exit_plan=plan, bars=[],
                                 settings=s, premium=2.0, multiplier=100.0, option_type="call", delta=0.5, budget=60.0)
    _f4, ro = geo.plan_risk(mode="enforce", direction="long", vehicle="option", entry_ref=100.0, exit_plan=plan,
                            bars=[], settings=s, limit=2.0, qty_requested=3, multiplier=100.0, option_type="call",
                            delta=0.5, budget=60.0, budget_source="test")
    assert fo["unitLoss"] == ro.unitLoss == 50.0 and fo["qtyByRisk"] == 1 and ro.qty == 1


def test_fitting_stop_is_a_diagnostic_with_admissibility():
    s = _S()
    d = geo.fitting_stop(direction="long", vehicle="shares", entry_ref=100.0, exit_plan={}, bars=[], settings=s,
                         budget=0.5)
    assert d["available"] and d["stop"] == 99.5 and d["admissible"] is False and "re-placed" in d["why"]
    ok = geo.fitting_stop(direction="long", vehicle="option", entry_ref=100.0, exit_plan={}, bars=[], settings=s,
                          premium=1.0, multiplier=100.0, delta=0.5, budget=100.0)
    assert ok["available"] and ok["stop"] == 98.0 and ok["admissible"] is True
    floor = geo.fitting_stop(direction="long", vehicle="option", entry_ref=100.0, exit_plan={}, bars=[], settings=s,
                             premium=8.0, multiplier=100.0, delta=0.5, budget=100.0)
    assert floor["available"] is False and "floor" in floor["reason"]


# ------------------------------------------------------------------ pure: the prompt contract
def test_reask_reason_only_for_budget_skips_of_verified_priced_btos():
    tip = {"action": "open", "premium": 2.5, "entryPrice": None}
    ok_v = {"passed": True}
    skip = {"verdict": "skip", "rationale": "one contract risks $140 against the $90 budget"}
    assert alt.reask_reason(skip, tip=tip, verification=ok_v, offered=None) == "budget/size skip without find_alternatives"
    # not a budget reason / not verified / not priced / a take -> stands
    assert alt.reask_reason({"verdict": "skip", "rationale": "hedge leg, not standalone"}, tip=tip, verification=ok_v,
                            offered=None) is None
    assert alt.reask_reason(skip, tip=tip, verification={"passed": False, "park": True}, offered=None) is None
    assert alt.reask_reason(skip, tip={"action": "open"}, verification=ok_v, offered=None) is None
    assert alt.reask_reason({**skip, "verdict": "take"}, tip=tip, verification=ok_v, offered=None) is None
    offered = {"alternatives": [{"id": "alt1"}, {"id": "alt2"}]}
    assert "alt2" in alt.reask_reason({**skip, "alternativesConsidered": [{"id": "alt1", "reason": "caps the move"}]},
                                      tip=tip, verification=ok_v, offered=offered)
    full = {**skip, "alternativesConsidered": [{"id": "alt1", "reason": "caps the move"},
                                               {"id": "alt2", "reason": "needs a 6% move in 3 days"}]}
    assert alt.reask_reason(full, tip=tip, verification=ok_v, offered=offered) is None
    assert alt.reask_reason(skip, tip=tip, verification=ok_v, offered={"alternatives": []}) is None


def test_match_and_apply_choice_carry_the_vehicle_as_a_normal_take():
    offered = {"version": "alternatives-v1", "original": {"contract": "TEST261016C00100000"},
               "alternatives": [
                   {"id": "alt1", "kind": "strike", "contract": "TEST261016C00105000", "qty": 2, "finalStop": 97.0,
                    "vehicle": {"instrument": "option", "contract": "TEST261016C00105000", "contract_label": "x",
                                "limit_price": 1.1, "quantity": 2}},
                   {"id": "alt2", "kind": "vertical", "longStrike": 100.0, "shortStrike": 110.0, "label": "v",
                    "vehicle": {"legs": [{"action": "buy", "type": "call", "strike": 100.0},
                                         {"action": "sell", "type": "call", "strike": 110.0}],
                                "legs_expiry": "2026-10-16", "limit_price": 0.9, "quantity": 3}},
                   {"id": "alt3", "kind": "shares", "qty": 40, "vehicle": {"instrument": "shares", "contract": None,
                                                                           "limit_price": 100.2, "quantity": 40}}]}
    op = {"verdict": "take", "alternativeChosen": "alt1", "contract": "TEST261016C00105000", "quantity": 5}
    ch = alt.match_choice(offered, op)
    assert ch["id"] == "alt1"
    out = alt.apply_choice(op, ch, offered)
    assert out["contract"] == "TEST261016C00105000" and out["quantity"] == 2 and out["limit_price"] == 1.1
    assert out["reshapedFrom"] == "TEST261016C00100000" and out["underlying_stop"] == 97.0
    sh = alt.apply_choice({"verdict": "take", "instrument": "shares"},
                          alt.match_choice(offered, {"verdict": "take", "instrument": "shares"}), offered)
    assert sh["instrument"] == "shares" and sh["contract"] is None and sh["quantity"] == 40
    v = alt.match_choice(offered, {"verdict": "take", "legs": [{"strike": 110}, {"strike": 100}]})
    vo = alt.apply_choice({"verdict": "take"}, v, offered)
    assert len(vo["legs"]) == 2 and vo["legs_expiry"] == "2026-10-16" and vo["contract"] is None


def test_analyst_takes_shares_is_long_only():
    from zargar.approvals.proposals import analyst_takes_shares
    assert analyst_takes_shares({"verdict": "take", "instrument": "shares"}, "long")
    assert not analyst_takes_shares({"verdict": "take", "instrument": "shares"}, "short")
    assert not analyst_takes_shares({"verdict": "take", "instrument": "option"}, "long")
    assert not analyst_takes_shares({"verdict": "skip", "instrument": "shares"}, "long")


def test_fill_band_and_liquidity_rule():
    fb = alt.fill_band(bid=1.0, ask=1.1, last=None, settings=_S(), is_option=True)
    assert fb["limit"] == 1.1 and fb["withinCollar"] and fb["low"] < 1.05 < fb["high"]
    assert alt.liquidity_problem({"bid": 0, "ask": 1}) and "one-sided" in alt.liquidity_problem({"bid": 0, "ask": 1})
    assert "spread" in alt.liquidity_problem({"bid": 1, "ask": 2, "spreadPct": 66.0, "openInterest": 900})
    assert "open interest" in alt.liquidity_problem({"bid": 1, "ask": 1.05, "spreadPct": 4.9, "openInterest": 5})
    assert alt.liquidity_problem({"bid": 1, "ask": 1.05, "spreadPct": 4.9, "openInterest": 500}) is None


# ------------------------------------------------------------------ engine rig
SYM = "NVDA"                                   # a fixed sim seed price (128)


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    await eng.ensure_symbol(SYM)
    await wait_for(lambda: eng.quotes.get(SYM) is not None and eng.quotes.get(SYM).last > 0, timeout=5)
    pid = next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")
    await eng.settings.set("techniques.tip.default_portfolio", pid, journal=False)
    await eng.settings.set("techniques.tip.geometry_gate", "enforce", journal=False)
    await eng.settings.set("techniques.tip.budget_per_tip", 5000.0, journal=False)

    async def _no_refresh(sym):            # never reach a real-time source from a test
        return eng.quotes.get(sym.upper())
    eng.options.refresh_now = _no_refresh
    yield eng
    await eng.stop()


def _k(x: float) -> float:
    return round(x, 2)


def _setup_chain(eng, P: float):
    """Stated ATM call (delta .5, expensive) + two further-OTM strikes + a later expiry; strikes on a 0.5 grid."""
    e1 = (dt.date.today() + dt.timedelta(days=14)).isoformat()
    e2 = (dt.date.today() + dt.timedelta(days=45)).isoformat()
    k0, k1, k2 = _k(P), _k(P * 1.02), _k(P * 1.04)
    a0, a1, a2 = round(0.03 * P, 2), round(0.02 * P, 2), round(0.01 * P, 2)
    rows = [chain_row(k0, expiry=e1, bid=round(a0 * 0.96, 2), ask=a0, delta=0.5, underlying=SYM),
            chain_row(k1, expiry=e1, bid=round(a1 * 0.96, 2), ask=a1, delta=0.3, underlying=SYM),
            chain_row(k2, expiry=e1, bid=round(a2 * 0.96, 2), ask=a2, delta=0.2, underlying=SYM),
            chain_row(k0, expiry=e2, bid=round(0.05 * P * 0.96, 2), ask=round(0.05 * P, 2), delta=0.55, underlying=SYM)]
    eng.options.use_client(FakeChain(spot=P, expiries=(e1, e2), rows=rows))
    stated = occ_mod.make(SYM, e1, "C", k0).symbol
    return stated, {"k0": k0, "k1": k1, "k2": k2, "a0": a0, "a1": a1, "a2": a2, "e1": e1, "e2": e2}


async def _option_tip(eng, stated: str, *, stop: float, target: float, source="AltSrc", premium=None):
    o = occ_mod.parse(stated)
    row = Signal(id=new_id(), source_name=source, ticker=SYM, direction="long", action="open", instrument="call",
                 strike=float(o.strike), expiry=o.expiry.isoformat(), premium=premium, entry_price=None,
                 target_price=target, stop_price=stop, status="verified", extraction={}, thesis_summary="w2 test",
                 confidence="explicit_call", is_actionable=True)
    sig = TradeSignal(ticker=SYM, direction="long", instrument="call", strike=float(o.strike),
                      expiry=o.expiry.isoformat(), premium=premium, target_price=target, stop_price=stop,
                      thesis_summary="w2 test", confidence="explicit_call", evidence_quotes=["w2 test"],
                      is_actionable=True)
    async with eng.sf() as session:
        session.add(row)
        await session.commit()
    return row, sig


async def _events(eng, kind: str) -> list[dict]:
    async with eng.sf() as session:
        return list((await session.execute(select(Event.payload).where(Event.type == kind)
                                           .order_by(Event.id))).scalars().all())


async def test_check_feasibility_shows_the_qty_and_stop_the_gate_will_allow(rig):
    """W1.2 parity on the real engine: the analyst tool and the proposal-time gate agree on stop, unit and qty."""
    from zargar.techniques.tip.analyst import _run_tool
    eng = rig
    P = float(eng.quotes.get(SYM).last)
    stated, k = _setup_chain(eng, P)
    await eng.settings.set("techniques.tip.risk_budget_per_tip", round(1.5 * P, 2), journal=False)
    await eng.options.chain(SYM, k["e1"])                      # the analyst's get_chain populates the snapshots
    stop = round(P * 0.98, 2)
    ctx = {"ticker": SYM, "budgetPerTip": 5000.0, "source": "AltSrc"}
    out = await _run_tool(eng, "check_feasibility", {"contract": stated, "limit": k["a0"], "underlying_stop": stop},
                          ctx=ctx)
    assert out["authority"] == "fit-v1" and out["finalStop"] == stop and out["feasible"] is True
    row, sig = await _option_tip(eng, stated, stop=stop, target=round(P * 1.06, 2))
    row.extraction = {"analyst": {"verdict": "take", "instrument": "option", "contract": stated,
                                  "limit_price": k["a0"], "quantity": 9, "underlying_stop": stop,
                                  "exit_targets": [round(P * 1.06, 2)], "exit_fractions": [1.0]}}
    pdict = await eng.proposals.create_from_signal(row, sig, {})
    rp = pdict["context"]["riskPlan"]
    assert rp["enforced"] and not rp.get("reviewRequired"), rp
    assert rp["finalStop"] == out["finalStop"]
    assert abs(rp["unitLoss"] - out["unitRisk"]) / out["unitRisk"] < 0.10       # sim tick drift only
    assert pdict["qty"] == out["qty"] == rp["qty"]


async def test_find_alternatives_offers_fitting_reshapes_and_the_proposal_trades_them(rig):
    from zargar.techniques.tip.analyst import _run_tool
    eng = rig
    P = float(eng.quotes.get(SYM).last)
    stated, k = _setup_chain(eng, P)
    B = round(0.9 * P, 2)                                       # stated: 1.0P per contract -> does not fit
    await eng.settings.set("techniques.tip.risk_budget_per_tip", B, journal=False)
    stop = round(P * 0.98, 2)
    ctx = {"ticker": SYM, "budgetPerTip": 5000.0, "source": "AltSrc", "tip": {"direction": "long"}}
    feas = await _run_tool(eng, "check_feasibility", {"contract": stated, "limit": k["a0"], "underlying_stop": stop},
                           ctx=ctx)
    # qty 0 points at find_alternatives AND pre-attaches them (no extra turn)
    assert feas["qty"] == 0 and "alternatives" in feas["next"]
    assert feas.get("alternatives") and ctx.get("alternativesOffered")
    res = await _run_tool(eng, "find_alternatives", {"contract": stated, "underlying_stop": stop,
                                                     "exit_targets": [round(P * 1.06, 2)]}, ctx=ctx)
    full = ctx["alternativesOffered"]
    assert full["original"]["contract"] == stated and full["original"]["fits"] is False
    kinds = {a["kind"] for a in full["alternatives"]}
    assert {"strike", "shares"} <= kinds, (kinds, full["notFitting"], full["unavailable"])
    # review H4 (2026-10-04): a vertical is sized by its whole net debit (defined risk), the same arithmetic as the
    # proposal gate - here one spread costs more than the risk budget, so it is offered as NOT fitting
    vall = [a for a in full["alternatives"] + full["notFitting"] if a["kind"] == "vertical"]
    assert vall and all(a["kind"] != "vertical" or a["qty"] * a["netDebit"] * 100 <= B + 1e-6
                        for a in full["alternatives"])
    assert any(a["kind"] == "expiry" for a in full["notFitting"]), "the later expiry costs more risk: offered, not fitting"
    for a in full["alternatives"]:
        assert a["qty"] >= 1 and a["plannedRisk"] <= B + 1e-6 and a["vehicle"]["quantity"] == a["qty"]
        assert a["payoff"] and a["fillBand"] and a.get("breakEven") is not None
    v = vall[0]
    assert v["venueDependent"] and v["maxLoss"] == round(max(v["qty"], 1) * v["netDebit"] * 100, 2) and v["maxGain"] > 0
    # the model-facing rendition keeps every deciding number and stays inside the tool-result budget
    assert len(json.dumps(res, default=str)) < 12000 and res["alternatives"][0]["id"] == "alt1"
    # the proposal path trades a chosen cheaper strike EXACTLY at the size the alternative showed
    strike_alt = next(a for a in full["alternatives"] if a["kind"] == "strike")
    row, sig = await _option_tip(eng, stated, stop=stop, target=round(P * 1.06, 2))
    take = alt.apply_choice({"verdict": "take", "alternativeChosen": strike_alt["id"], "underlying_stop": stop,
                             "exit_targets": [round(P * 1.06, 2)], "exit_fractions": [1.0]}, strike_alt, full)
    row.extraction = {"analyst": take}
    pdict = await eng.proposals.create_from_signal(row, sig, {})
    assert pdict["symbol"] == strike_alt["contract"] and pdict["secType"] == "OPT"
    assert pdict["qty"] == strike_alt["qty"] and not pdict["context"].get("reviewRequired")
    # ... and the shares alternative of an OPTION tip is proposed as shares (the analyst's pick wins)
    sh = next(a for a in full["alternatives"] if a["kind"] == "shares")
    row2, sig2 = await _option_tip(eng, stated, stop=stop, target=round(P * 1.06, 2), source="AltSrc2")
    row2.extraction = {"analyst": alt.apply_choice({"verdict": "take", "underlying_stop": stop,
                                                    "exit_targets": [round(P * 1.06, 2)]}, sh, full),
                       "shadowExpression": {"vehicle": "option", "contract": stated, "ask": k["a0"], "contracts": 1}}
    p2 = await eng.proposals.create_from_signal(row2, sig2, {})
    assert p2["secType"] == "STK" and p2["symbol"] == SYM and p2["qty"] >= 1
    assert p2["qty"] * p2["context"]["riskPlan"]["unitLoss"] <= B + 1e-6


async def test_a_live_shares_only_book_is_offered_shares_only(rig):
    eng = rig
    P = float(eng.quotes.get(SYM).last)
    stated, _k_ = _setup_chain(eng, P)
    await eng.settings.set("techniques.tip.risk_budget_per_tip", round(0.9 * P, 2), journal=False)
    pid = eng.settings.get("techniques.tip.default_portfolio")
    orig = eng.positions.portfolio

    def as_live(p):
        d = orig(p)
        return {**d, "kind": "paper", "venue": "ibkr"} if (d and p == pid) else d
    eng.positions.portfolio = as_live
    try:
        out = await alt.find_alternatives(eng, {"contract": stated, "underlying_stop": round(P * 0.98, 2)},
                                          {"ticker": SYM, "budgetPerTip": 5000.0})
    finally:
        eng.positions.portfolio = orig
    assert out["book"]["sharesOnly"] and "shares only" in out["book"]["sharesOnlyReason"]
    assert [a["kind"] for a in out["alternatives"]] == ["shares"]
    assert not out["notFitting"]


async def test_budget_skip_is_reasked_once_and_the_take_carries_reshaped_from(rig):
    """W2.2 end to end: the analyst skips for budget without alternatives -> the desk builds them and re-asks
    once in the SAME run -> the take of alt1 rides the opinion with reshapedFrom + TipAlternativesOffered."""
    from zargar.signals.sources import resolve_policy
    from zargar.techniques.tip.analyst import analyze_tip
    eng = rig
    P = float(eng.quotes.get(SYM).last)
    stated, k = _setup_chain(eng, P)
    await eng.settings.set("techniques.tip.risk_budget_per_tip", round(0.9 * P, 2), journal=False)
    stop, target = round(P * 0.98, 2), round(P * 1.06, 2)
    row, _sig = await _option_tip(eng, stated, stop=stop, target=target, premium=k["a0"])
    skip = json.dumps({"verdict": "skip", "rationale": "one contract risks more than the risk budget allows",
                       "confidence": 0.5})
    take = json.dumps({"verdict": "take", "alternativeChosen": "alt1", "instrument": "option",
                       "rationale": "the cheaper strike keeps the thesis inside the budget", "confidence": 0.55,
                       "underlying_stop": stop, "exit_targets": [target], "exit_fractions": [1.0],
                       "max_hold_sessions": 5,
                       "alternativesConsidered": [{"id": "alt1", "decision": "chosen", "reason": "fits, same expiry"}]})
    client = _Scripted([_text(skip), _text(take)])
    out = await analyze_tip(eng, row, {"passed": True}, resolve_policy(eng.settings, "AltSrc"), client=client)
    assert out["verdict"] == "take" and out["budgetReask"]["outcome"] == "take"
    assert out["reshapedFrom"] == stated and out["alternativeChosen"] == "alt1"
    assert out["contract"] and out["contract"] != stated and out["quantity"] >= 1
    # the re-ask carried the desk-built alternatives in the SAME transcript (no tool turn needed)
    last_user = client.requests[-1]["messages"][-1]["content"]
    assert "find_alternatives" in last_user and "alt1" in last_user
    offered = await _events(eng, "TipAlternativesOffered")
    assert offered and offered[-1]["chosen"] == "alt1" and offered[-1]["reshapedFrom"] == stated
    assert offered[-1]["alternatives"] and offered[-1]["considered"][0]["id"] == "alt1"


async def test_a_considered_skip_is_not_reasked(rig):
    from zargar.signals.sources import resolve_policy
    from zargar.techniques.tip.analyst import analyze_tip
    eng = rig
    P = float(eng.quotes.get(SYM).last)
    stated, k = _setup_chain(eng, P)
    await eng.settings.set("techniques.tip.risk_budget_per_tip", round(0.9 * P, 2), journal=False)
    stop = round(P * 0.98, 2)
    row, _sig = await _option_tip(eng, stated, stop=stop, target=round(P * 1.06, 2), premium=k["a0"])
    # the model calls find_alternatives itself, then skips with a reason per fitting id
    fa = _tool("find_alternatives", {"contract": stated, "underlying_stop": stop, "exit_targets": [round(P * 1.06, 2)]})
    client = _Scripted([fa, _text("{}")])         # placeholder, replaced once the ids are known
    import zargar.techniques.tip.alternatives as _a
    real = _a.find_alternatives

    async def spy(eng_, args, ctx):
        res = await real(eng_, args, ctx)
        considered = [{"id": a["id"], "decision": "rejected", "reason": "the tape is rolling over"}
                      for a in res["alternatives"]]
        client._responses[-1] = _text(json.dumps({"verdict": "skip", "rationale": "over budget; alternatives weighed",
                                                  "confidence": 0.4, "alternativesConsidered": considered}))
        return res
    _a.find_alternatives = spy
    try:
        out = await analyze_tip(eng, row, {"passed": True}, resolve_policy(eng.settings, "AltSrc"), client=client)
    finally:
        _a.find_alternatives = real
    assert out["verdict"] == "skip" and "budgetReask" not in out and len(client.requests) == 2
    ev = await _events(eng, "TipAlternativesOffered")
    assert ev and ev[-1]["chosen"] is None and len(ev[-1]["considered"]) == len(ev[-1]["alternatives"]) - len(
        [a for a in ev[-1]["alternatives"] if not a.get("fits")])


async def test_prefetch_seeds_the_header_with_earnings_on_every_appraisal(rig, monkeypatch):
    from zargar.signals.sources import resolve_policy
    from zargar.techniques.tip import review_context
    from zargar.techniques.tip.analyst import analyze_tip
    eng = rig
    P = float(eng.quotes.get(SYM).last)
    stated, k = _setup_chain(eng, P)
    row, _sig = await _option_tip(eng, stated, stop=round(P * 0.98, 2), target=round(P * 1.06, 2), premium=k["a0"])
    # offline feed: the earnings line is still present, labelled unknown
    client = _Scripted([_text(json.dumps({"verdict": "skip", "rationale": "tape", "confidence": 0.3}))])
    await eng.settings.set("techniques.tip.frozen_capture_context", True, journal=False)
    out = await analyze_tip(eng, row, {"passed": False}, resolve_policy(eng.settings, "AltSrc"), client=client)
    header = client.requests[0]["messages"][0]["content"]
    assert pf.SEED_MARK in header and "- earnings: unknown" in header
    assert header.index(pf.SEED_MARK) < header.index("YOUR TRADING RULES")
    assert out["prefetch"]["earnings"]["status"] == "unknown" and "quote" in out["prefetch"]["fetched"]
    assert "chain" in out["prefetch"]["fetched"], "an injected chain provider is prefetched even offline"
    # the per-run block sits AFTER the cached rulebook block when the stable-first order is on
    blocks = review_context.stable_first_blocks(header)
    assert isinstance(blocks, list) and "YOUR TRADING RULES" in blocks[0]["text"]
    assert pf.SEED_MARK not in blocks[0]["text"] and pf.SEED_MARK in blocks[-1]["text"]
    # the frozen manifest carries it: the exact rebuild keeps it verbatim, the reconstructed one re-inserts it
    from zargar.models import TipAnalystRun
    from zargar.techniques.tip import frozen
    async with eng.sf() as session:
        run = await session.get(TipAnalystRun, out["runId"])
    man = next(s_["contextManifest"] for s_ in run.trace if s_.get("kind") == "context")
    assert man["seededText"] and man["seededText"] in man["header"]
    h_exact, _g = frozen._rebuild_header(man, rules_text="R", notes_text="N")
    assert man["seededText"] in h_exact
    h_rec, gaps = frozen._rebuild_header({**man, "exact": False}, rules_text="R", notes_text="N")
    assert man["seededText"] in h_rec and gaps
    # online: a known earnings date + a bars summary (fetchers stubbed - no network in tests)
    monkeypatch.setattr(pf, "_network_ok", lambda eng_: True)

    class _Cal:
        async def days_to_earnings(self, sym):
            return 9
    monkeypatch.setattr(eng, "calendar", _Cal(), raising=False)
    from zargar.domain import Bar

    async def _bars(sym, tf, sessions=5, **kw):
        return [Bar(symbol=sym, tf="1h", ts=1_790_000_000_000 + i * 3_600_000, open=P, high=P + 1, low=P - 1,
                    close=P + 0.5, volume=1000) for i in range(10)]
    monkeypatch.setattr("zargar.marketstructure.history.fetch_recent", _bars)
    monkeypatch.setattr("zargar.marketstructure.history.fetch_window", lambda *a, **k: _empty())
    client2 = _Scripted([_text(json.dumps({"verdict": "skip", "rationale": "tape", "confidence": 0.3}))])
    out2 = await analyze_tip(eng, row, {"passed": False}, resolve_policy(eng.settings, "AltSrc"), client=client2)
    h2 = client2.requests[0]["messages"][0]["content"]
    assert "- earnings: in 9 day(s)" in h2 and '"atr1h"' in h2
    assert out2["prefetch"]["earnings"] == {"status": "known", "daysToEarnings": 9}


async def _empty():
    return []


async def test_gate_refits_once_on_refreshed_evidence_then_refuses_on_the_record(rig, monkeypatch):
    """W1.2 at the gate: a plan refused ONLY for size gets one re-fit; a quantity that fits now proceeds resized,
    none -> refused as before, with the diagnostic fitting stop on the journal."""
    eng = rig
    q = eng.quotes.get(SYM)
    px = float(q.last)
    await eng.settings.set("techniques.tip.risk_budget_per_tip", 0.01, journal=False)        # nothing fits
    row = Signal(id=new_id(), source_name="RefitSrc", ticker=SYM, direction="long", action="open",
                 instrument="shares", entry_price=px, target_price=round(px * 1.06, 2),
                 stop_price=round(px * 0.985, 2), status="verified", extraction={}, thesis_summary="refit",
                 confidence="explicit_call")
    sig = TradeSignal(ticker=SYM, direction="long", instrument="shares", entry_price=px,
                      target_price=row.target_price, stop_price=row.stop_price, thesis_summary="refit",
                      confidence="explicit_call", evidence_quotes=["refit"], is_actionable=True)
    async with eng.sf() as session:
        session.add(row)
        await session.commit()
    p1 = await eng.proposals.create_from_signal(row, sig, {})
    assert p1["context"]["reviewRequired"] and "no quantity" in p1["context"]["reviewRequired"]
    ev = (await _events(eng, "TipGeometryRefit"))[-1]
    assert ev["outcome"] == "no_fit" and ev["attempt"] == 1 and ev["fittingStop"]["available"]
    assert ev["fittingStop"]["note"].startswith("diagnostic")
    # the quote "moves" between the first computation and the re-fit: the budget now covers the risk
    svc = eng.proposals
    real = svc._compute_risk_plan
    calls = {"n": 0}

    async def moved(**kw):
        calls["n"] += 1
        if calls["n"] == 2:
            await eng.settings.set("techniques.tip.risk_budget_per_tip", 10_000.0, journal=False)
        return await real(**kw)
    monkeypatch.setattr(svc, "_compute_risk_plan", moved)
    await eng.settings.set("techniques.tip.risk_budget_per_tip", 0.01, journal=False)
    row2 = Signal(**{c: getattr(row, c) for c in ("source_name", "ticker", "direction", "action", "instrument",
                                                  "entry_price", "target_price", "stop_price", "status",
                                                  "thesis_summary", "confidence")}, id=new_id(), extraction={})
    async with eng.sf() as session:
        session.add(row2)
        await session.commit()
    p2 = await eng.proposals.create_from_signal(row2, sig, {})
    assert calls["n"] == 2 and not p2["context"].get("reviewRequired") and p2["qty"] >= 1
    ev2 = (await _events(eng, "TipGeometryRefit"))[-1]
    assert ev2["outcome"] == "resized" and ev2["after"]["qty"] >= 1 and ev2["before"]["qty"] == 0
    assert any("re-fit once" in d for d in p2["context"]["riskPlan"]["decisions"])


def test_prefetch_record_and_seed_block_never_drop_earnings():
    pre = {"version": "prefetch-v1", "ticker": "X", "ms": 5, "items": {
        "quote": {"ok": False, "error": "timed out after 6s"}, "chain": {"ok": True, "value": {"note": "no expiry"}},
        "bars": {"ok": True, "value": {"note": "offline"}}, "positions": {"ok": True, "value": {"positions": []}},
        "earnings": {"ok": True, "value": {"daysToEarnings": None, "status": "none known"}}}}
    blk = pf.seed_block(pre, fetched_at="2026-10-02 10:00 ET")
    assert blk.startswith(pf.SEED_MARK) and "- earnings: no upcoming date known" in blk
    assert "timed out" in blk and blk.endswith("\n")
    rec = pf.record(pre)
    assert rec["failed"] == {"quote": "timed out after 6s"} and rec["fetched"] == ["positions", "earnings"]
    assert pf.bars_summary([])["note"] == "no bars"
    b = [SimpleNamespace(ts=1_790_000_000_000 + i * 3_600_000, open=10, high=11, low=9, close=10.5) for i in range(3)]
    sm = pf.bars_summary(b)
    assert sm["rangeHigh"] == 11 and sm["rangeLow"] == 9 and sm["atr1h"] > 0
