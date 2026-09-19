"""first-sale-v2 (integrated plan D; candidate review IR-01 + IR-04, 2026-09-19).

R2 is measured to the GATE TARGET of the FINAL quantity, from the worse of the runner's entry and the VALIDATED current
executable underlying bound; the comparison is on the unrounded R; `enforce` fails closed (refuse / defer) and is
re-decided at final dispatch; research persistence never holds an entry; the default is OFF. SBUX 2026-09-18 (event
165135) stays the regression. Pure record cases, the runner's caller boundary on fakes, and REAL caller-boundary cases
through `_enter` -> OrderManager on the reviewers' dispatch rig (real Postgres, pinned weekday clock)."""
import asyncio
import inspect
from types import SimpleNamespace

import pytest

from tests.test_codex_em_final_dispatch_budget import CONTRACT, dispatch_rig  # noqa: F401 - the reviewers' rig, unchanged
from zargar.domain import OrderStatus, Quote, now_ms
from zargar.execution.planrunner import PlanRunner
from zargar.technique import first_sale as fs
from zargar.technique.arming import PlanArmer

NOW = 1_000_000


def _ev(price, *, spread=0.02, age=500, source="feed:HybridQuoteFeed", symbol="SBUX", **over):
    return {"symbol": symbol, "bid": round(price - spread, 4), "ask": price, "last": price, "quoteTs": NOW - age, "lastTs": NOW - age,
            "receivedTs": NOW - 100, "source": source, "halted": False, **over}


SBUX = dict(stage="order", symbol="SBUX", run_id="8a79a643", trigger_id="d1", family="breakdown", direction="short",
            session="2026-09-18", plan_entry=96.0907, runner_entry=95.335, stop=97.681,
            targets=[94.1689, 92.2471, 90.3253], instrument="options", multiplier=100.0,
            limit_price=1.05, single_exit="tp2", pinned_gate_target="auto", pin_source="run_config", min_rr=3.0,
            contract={"symbol": "SBUX261002P00095000", "delta": -0.45, "openInterest": 183}, option_quote={"bid": 1.0, "ask": 1.05, "bidSize": 12, "askSize": 9, "sourceTs": NOW - 100},
            fee_per_contract=1.04, stock_commission=0.0, plan_gate={"targetIndex": 2, "rr": 3.63, "min": 3.0}, mode="enforce", now_ms=NOW)


def _rec(**over):
    kw = {**SBUX, **over}
    kw.setdefault("qty", 1)
    kw.setdefault("affordable_qty", kw["qty"])
    if "underlier_evidence" not in kw:                     # a short is judged at the BID: bid 95.335 = the runner's entry
        kw["underlier_evidence"] = {**_ev(95.355), "bid": 95.335}
    return fs.build_record(**kw)


# ------------------------------------------------------------------------------------------------------ pure record
def test_sbux_one_contract_is_1_316r_at_tp2_and_fails_the_3r_rule():
    r = _rec(qty=1)
    g = r["gate"]
    assert (g["rung"], g["rungIndex"], g["rungBasis"]) == ("tp2-full", 1, "single_contract_exit")
    assert g["rAdmission"] == 1.316 and g["minRiskReward"] == 3.0 and g["verdict"] == "fail" and g["reason"] == "first_sale_rr_below_min"
    assert g["planTime"]["targetIndex"] == 2 and g["differsFromPlanTime"] is True, "plan time measured TP3; the position exits at TP2"
    d = fs.decide(r, "enforce")
    assert d["allow"] is False and d["disposition"] == "refused" and "1.316" in d["reason"] and "tp2-full" in d["reason"]
    assert fs.decide(r, "observe") == {"allow": True, "disposition": "observed_fail", "reason": None}


def test_reviewer_reproduction_the_current_executable_price_owns_admission_not_the_saved_entry():
    # IR-01: runner entry 100, underlier now 102, stop 99, TP2 103, one contract, minimum 3R
    kw = dict(direction="long", family="bounce", plan_entry=100, runner_entry=100, stop=99, targets=[101, 103, 105], symbol="X",
              contract=None, option_quote=None, plan_gate=None)
    r = _rec(**kw, underlier_evidence=_ev(102.0, symbol="X"))
    g = r["gate"]
    assert g["rRunnerEntry"] == 3.0 and g["rObservedUnderlier"] == 0.333 and g["admissionEntry"] == 102.0 and g["admissionBasis"]["boundBasis"] == "ask"
    assert g["rAdmission"] == 0.333 and g["verdict"] == "fail" and fs.decide(r, "enforce")["disposition"] == "refused"
    better = _rec(**kw, underlier_evidence=_ev(99.5, symbol="X"))                  # a cheaper underlier never inflates the admission past the managed entry
    assert better["gate"]["admissionEntry"] == 100 and better["gate"]["rAdmission"] == 3.0 and better["gate"]["verdict"] == "pass"
    short = _rec()                                                                # puts: the BID is the bound
    assert short["gate"]["admissionBasis"]["boundBasis"] == "bid" and short["underlying"]["validated"]["status"] == "valid"


def test_the_comparison_is_unrounded_2_9996_is_below_3():
    kw = dict(direction="long", family="bounce", plan_entry=100, runner_entry=100, stop=99, symbol="X", contract=None, option_quote=None, plan_gate=None,
              underlier_evidence=_ev(100.0, symbol="X"))
    near = _rec(**kw, targets=[101, 102.9996, 105])
    assert near["gate"]["rAdmission"] == 3.0 and near["gate"]["rAdmissionRaw"] < 3.0 and near["gate"]["verdict"] == "fail", "rounding is display only"
    assert _rec(**kw, targets=[101, 103.0, 105])["gate"]["verdict"] == "pass"
    assert fs.r_raw(direction="long", entry=100, stop=99, target=102.9996)[0] < 3.0 and fs.r_multiple(direction="long", entry=100, stop=99, target=102.9996)[0] == 3.0


@pytest.mark.parametrize("evidence,problem", [
    (None, "no_underlier_evidence"),
    (_ev(95.335, age=11_000), "stale_underlier"),
    (_ev(95.335, source=""), "source_unknown"),
    (_ev(95.335, source="derived:chain"), "source_not_executable"),
    (_ev(95.335, symbol="SBUY"), "symbol_mismatch"),
    ({**_ev(95.335), "quoteTs": 0, "lastTs": 0}, "venue_time_unknown"),
    ({**_ev(95.335), "quoteTs": NOW + 5000, "lastTs": NOW + 5000}, "venue_time_in_future"),
    (_ev(95.335, halted=True), "halted"),
])
def test_missing_stale_or_unprovenanced_underlier_is_unknown_observe_passes_it_enforce_defers(evidence, problem):
    r = _rec(underlier_evidence=evidence)
    assert r["gate"]["verdict"] == "unknown" and problem in r["underlying"]["validated"]["problems"] and r["underlying"]["observed"] is None
    assert fs.decide(r, "observe")["allow"] is True and fs.decide(r, "observe")["disposition"] == "observed_unknown"
    d = fs.decide(r, "enforce")
    assert d["allow"] is False and d["disposition"] == "deferred_missing_evidence" and "nothing sent" in d["reason"]


def test_a_print_is_the_bound_only_when_no_fresh_two_sided_quote_exists_and_a_receipt_time_is_never_evidence():
    only_last = {**_ev(95.30), "quoteTs": 0, "bid": 0.0, "ask": 0.0}
    v = fs.validate_underlier(only_last, symbol="SBUX", direction="short", now_ms=NOW)
    assert v["status"] == "valid" and v["basis"] == "last" and v["price"] == 95.30
    receipt_only = {**_ev(95.30), "quoteTs": 0, "lastTs": 0, "receivedTs": NOW - 10}
    assert fs.validate_underlier(receipt_only, symbol="SBUX", direction="short", now_ms=NOW)["status"] == "invalid"


@pytest.mark.parametrize("qty,instrument,rung,idx,first_rung", [
    (1, "options", "tp2-full", 1, "tp2-full"), (2, "options", "tp2-full", 1, "tp2-full"),
    (3, "options", "tp3", 2, "tp1-ladder"), (25, "shares", "tp3", 2, "tp1-ladder")])
def test_gate_target_and_first_production_sale_are_reported_apart_for_one_two_three_contracts_and_shares(qty, instrument, rung, idx, first_rung):
    r = _rec(qty=qty, instrument=instrument, multiplier=(100.0 if instrument == "options" else 1.0), limit_price=None)
    assert (r["gate"]["rung"], r["gate"]["rungIndex"]) == (rung, idx) and r["firstSale"]["rung"] == first_rung
    assert r["gate"]["rAdmission"] == (1.316 if idx == 1 else 2.135), "the multi-contract rule is unchanged: TP3, measured from the ACTUAL entry"
    assert "never gated" in r["firstSale"]["note"]


def test_shares_are_bounded_by_their_own_limit_and_a_changed_quantity_changes_the_gate():
    kw = dict(direction="long", family="bounce", plan_entry=100, runner_entry=100, stop=99, targets=[101, 103, 106], symbol="X", contract=None, option_quote=None,
              plan_gate=None, underlier_evidence=_ev(100.0, symbol="X"))
    sh = _rec(**kw, instrument="shares", multiplier=1.0, qty=50, limit_price=100.4)
    assert sh["gate"]["admissionEntry"] == 100.4 and sh["gate"]["rung"] == "tp3" and sh["gate"]["rAdmission"] == 4.0
    one, three = _rec(**kw, qty=1), _rec(**kw, qty=3)
    assert (one["gate"]["rung"], one["gate"]["verdict"]) == ("tp2-full", "pass") and (three["gate"]["rung"], three["gate"]["rAdmission"]) == ("tp3", 6.0)


def test_puts_are_signed_a_wrong_side_target_fails_and_the_pin_must_be_frozen():
    assert fs.r_raw(direction="short", entry=100, stop=102, target=94) == (3.0, None)
    assert fs.r_raw(direction="short", entry=100, stop=102, target=101)[1] == "target_wrong_side"
    assert fs.r_raw(direction="short", entry=100, stop=99, target=94) == (None, "stop_wrong_side")
    assert _rec(qty=1, targets=[94.0, 96.5, 90.0])["gate"]["reason"] == "target_wrong_side"
    pinned = _rec(qty=1, pinned_gate_target="tp3")
    assert pinned["gate"]["rung"] == "tp3" and pinned["gate"]["rungBasis"] == "pinned" and pinned["gate"]["pinSource"] == "run_config"
    unresolved = _rec(qty=1, pin_source="unresolved")
    assert unresolved["gate"]["verdict"] == "unknown" and "gate_pin_unresolved" in unresolved["gate"]["missingEvidence"], "a live legacy-key read never defines the policy"
    assert fs.decide(unresolved, "enforce")["disposition"] == "deferred_missing_evidence"


def test_modes_an_invalid_value_is_never_silently_off_and_errors_fail_closed_under_enforce():
    assert [fs.normalize_mode(x) for x in ("off", "OBSERVE", " enforce ", None, "enforced", "yes", "")] == ["off", "observe", "enforce", "off", "invalid", "invalid", "invalid"]
    bad = fs.decide(_rec(), "enforced")
    assert bad["allow"] is False and bad["disposition"] == "policy_error" and "never silently off" in bad["reason"]
    assert fs.decide(None, "enforce", error="boom")["disposition"] == "deferred_error" and fs.decide(None, "enforce")["allow"] is False
    assert fs.decide(None, "observe", error="boom") == {"allow": True, "disposition": "observed_error", "reason": None}
    assert fs.decide(None, "off")["allow"] is True


# ------------------------------------------------------------------------------------ the caller boundary in the runner
def _runner(mode, record, decide=fs.decide):
    published = []

    async def prepare(ap):
        return None
    me = SimpleNamespace(first_sale_policy=lambda ap: mode, first_sale_prepare=prepare,
                         first_sale_record=lambda ap, trade, qty, limit, m, stage="order": (record(m) if callable(record) else record),
                         first_sale_decide=lambda rec, m, err=None: decide(rec, m, error=err), first_sale_publish=lambda ap, rec: published.append(rec))
    me._first_sale_eval = lambda *a: PlanRunner._first_sale_eval(me, *a)
    return me, published


def _ap():
    return SimpleNamespace(run_id="run1", symbol="SBUX", config=SimpleNamespace(portfolio_id="book"))


def _boom(_m):
    raise RuntimeError("boom")


def test_base_runner_is_off_and_other_desks_run_no_first_sale_code():
    assert PlanRunner.first_sale_policy(SimpleNamespace(), _ap()) == "off" and PlanRunner.first_sale_final(SimpleNamespace(first_sale_policy=lambda ap: "off"), _ap(), None, 1, 1.0) is None
    me, pub = _runner("off", _boom)
    assert asyncio.run(PlanRunner._first_sale_check(me, _ap(), SimpleNamespace(timing={}, trigger_id="d1"), 1, 1.05)) is None and pub == []


def test_observe_is_never_authoritative_and_enforce_fails_closed_on_fail_unknown_and_error():
    trade = SimpleNamespace(timing={}, trigger_id="d1")
    me, pub = _runner("observe", lambda m: _rec(qty=1, mode=m))
    assert asyncio.run(PlanRunner._first_sale_check(me, _ap(), trade, 1, 1.05)) is None
    assert len(pub) == 1 and pub[0]["disposition"] == "observed_fail" and trade.timing["firstSale"]["rAdmission"] == 1.316
    me, _ = _runner("observe", _boom)
    assert asyncio.run(PlanRunner._first_sale_check(me, _ap(), trade, 1, 1.05)) is None, "observe: a hook error never touches the entry"
    me, pub = _runner("enforce", lambda m: _rec(qty=1, mode=m))
    assert asyncio.run(PlanRunner._first_sale_check(me, _ap(), trade, 1, 1.05)).startswith("first-sale gate: 1.316") and pub[0]["disposition"] == "refused"
    me, _ = _runner("enforce", lambda m: _rec(qty=1, mode=m, underlier_evidence=None))
    assert "missing or invalid" in asyncio.run(PlanRunner._first_sale_check(me, _ap(), trade, 1, 1.05)), "unknown evidence DEFERS under enforce"
    me, _ = _runner("enforce", _boom)
    assert "could not be built" in asyncio.run(PlanRunner._first_sale_check(me, _ap(), trade, 1, 1.05)), "a hook exception is a deferral, never a pass"
    me, _ = _runner("enforce", None)
    assert asyncio.run(PlanRunner._first_sale_check(me, _ap(), trade, 1, 1.05)) is not None, "a missing record is a deferral"
    me, _ = _runner("enforce", lambda m: _rec(mode=m), decide=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert "decision failed" in asyncio.run(PlanRunner._first_sale_check(me, _ap(), trade, 1, 1.05))
    me, _ = _runner("invalid", lambda m: _rec(mode=m))
    assert "never silently off" in asyncio.run(PlanRunner._first_sale_check(me, _ap(), trade, 1, 1.05))
    passing = lambda m: _rec(mode=m, direction="long", family="bounce", plan_entry=100, runner_entry=100, stop=99, targets=[101, 104, 106], symbol="X",   # noqa: E731
                             underlier_evidence=_ev(100.0, symbol="X"))
    me, _ = _runner("enforce", passing)
    assert asyncio.run(PlanRunner._first_sale_check(me, _ap(), trade, 1, 1.05)) is None


def test_the_check_is_entry_only_is_rechecked_in_the_final_guard_and_never_awaits_research_persistence():
    src = inspect.getsource(PlanRunner._enter)
    assert src.index("trade.qty = qty") < src.index("_first_sale_check") < src.index("OrderIntent(portfolio_id")
    guard = inspect.getsource(PlanRunner._entry_guard)
    assert "self.first_sale_final(ap, trade, qty, limit)" in guard and guard.index("first_sale_final") < guard.index("judge_entry_quote")
    check = inspect.getsource(PlanRunner._first_sale_check) + inspect.getsource(PlanRunner.first_sale_final) + inspect.getsource(PlanRunner._first_sale_eval)
    assert "journal.append" not in check and "await self.first_sale_publish" not in check, "the record goes to a bounded recorder - the entry never waits for it"
    assert not inspect.iscoroutinefunction(PlanRunner.first_sale_final)
    exit_src = inspect.getsource(PlanRunner._exit)
    assert "first_sale" not in exit_src and "before_submit" not in exit_src, "protective exits never meet the first-sale gate"
    from zargar import orders
    assert "before_submit is not None and not intent.reduce_only" in inspect.getsource(orders.OrderManager.place)


# ------------------------------------------------------------------------------------------------- EM's producer
def _armer(settings, quotes, feed=True):
    eng = SimpleNamespace(settings=SimpleNamespace(get=lambda k, d=None: settings.get(k, d)), quotes=SimpleNamespace(get=lambda s: quotes.get(s)),
                          positions=SimpleNamespace(portfolio=lambda pid: {"cash": 9800.0}), feed=(type("HybridQuoteFeed", (), {})() if feed else None))
    th = SimpleNamespace(min_risk_reward=3.0, rr_gate_target=2)
    return SimpleNamespace(engine=eng, technique=SimpleNamespace(thresholds=lambda: th))


def test_em_default_is_off_and_an_invalid_setting_is_invalid_not_off():
    from zargar.settings_service import DEFAULTS
    assert DEFAULTS["techniques.enhanced_market.first_sale_rr_gate"] == "off"
    assert PlanArmer.first_sale_policy(_armer({}, {}), None) == "off"
    assert PlanArmer.first_sale_policy(_armer({"techniques.enhanced_market.first_sale_rr_gate": "ENFORCE"}, {}), None) == "enforce"
    assert PlanArmer.first_sale_policy(_armer({"techniques.enhanced_market.first_sale_rr_gate": "yes"}, {}), None) == "invalid"
    assert not any(k.endswith("first_sale_rr_gate") and not k.startswith("techniques.enhanced_market.") for k in DEFAULTS)


def _producer_rig(uq, pins):
    oq = SimpleNamespace(symbol="SBUX261002P00095000", bid=1.0, ask=1.05, last=1.02, bid_size=12, ask_size=0, source_ts=now_ms() - 300, quote_ts=0, last_ts=0, ts=now_ms(),
                         source="opra", raw_source="", transform="", delayed=False, session="", halted=False)
    a = _armer({}, {"SBUX261002P00095000": oq, "SBUX": uq})
    a._fs_pins = pins
    ap = SimpleNamespace(run_id="run1", symbol="SBUX", plan_for="2026-09-18", trackers={},
                         plan={"triggers": [{"id": "d1", "entry": {"price": 96.0907, "basis": "on_break"}, "riskReward": 3.63, "riskRewardTp3": 3.63}]},
                         config=SimpleNamespace(single_contract_exit="tp2", portfolio_id="book", risk_pct=2.0, entry_fallback="shares"))
    trade = SimpleNamespace(trigger_id="d1", kind="breakdown", direction="short", entry=95.335, stop=97.681, targets=[94.1689, 92.2471, 90.3253],
                            instrument="options", order_symbol="SBUX261002P00095000", multiplier=100.0, contract={"symbol": "SBUX261002P00095000", "delta": -0.45},
                            timing={"vehicleRows": {"ts": 1, "rows": [{"symbol": "SBUX261002P00095000", "strike": 95, "delta": -0.45, "bid": 1.0, "ask": 1.05, "bidSize": 12, "askSize": 9, "openInterest": 183},
                                                                      {"symbol": "SBUX261002P00094000", "strike": 94, "delta": None, "bid": 0.7, "ask": 0.8}]}})
    return a, ap, trade


def test_em_producer_uses_validated_venue_evidence_the_frozen_pin_and_never_invents_a_source():
    t = now_ms()
    good = SimpleNamespace(symbol="SBUX", bid=95.335, ask=95.355, last=95.34, bid_size=300, ask_size=200, source="", quote_ts=t - 400, last_ts=t - 600, source_ts=0, ts=t,
                           raw_source="", transform="", delayed=False, session="regular", halted=False)
    a, ap, trade = _producer_rig(good, {"run1": {"pin": "auto", "source": "run_config", "planRrGateTarget": 2}})
    rec = PlanArmer.first_sale_record(a, ap, trade, 1, 1.05, "observe")
    assert rec["version"] == "first-sale-v2" and rec["gate"]["rAdmission"] == 1.316 and rec["gate"]["verdict"] == "fail" and rec["gate"]["pinSource"] == "run_config"
    assert rec["underlying"]["evidence"]["source"] == "feed:HybridQuoteFeed" and rec["underlying"]["validated"]["basis"] == "bid" and rec["underlying"]["planEntry"] == 96.0907
    assert rec["quote"]["askSize"] is None and rec["quote"]["source"] == "opra" and rec["gate"]["planTime"] == {"targetIndex": 2, "rr": 3.63, "rrTp3": 3.63, "min": 3.0}
    assert [r["status"] for r in rec["vehicleComparison"]["rows"]] == ["scored", "unknown", "not_permitted"] and rec["fees"]["roundTrip"] == 2.08
    yahoo_like = SimpleNamespace(**{**good.__dict__, "quote_ts": 0, "last_ts": 0})                       # synthetic bid/ask: no venue time -> no provenance is invented
    a, ap, trade = _producer_rig(yahoo_like, {"run1": {"pin": "auto", "source": "run_config", "planRrGateTarget": 2}})
    rec = PlanArmer.first_sale_record(a, ap, trade, 1, 1.05, "enforce")
    assert rec["underlying"]["evidence"]["source"] is None and rec["gate"]["verdict"] == "unknown" and fs.decide(rec, "enforce")["disposition"] == "deferred_missing_evidence"
    a, ap, trade = _producer_rig(good, {})                                                               # the frozen pin was never resolved
    assert PlanArmer.first_sale_record(a, ap, trade, 1, 1.05, "enforce")["gate"]["pinSource"] == "unresolved"
    a, ap, trade = _producer_rig(None, {"run1": {"pin": "auto", "source": "run_config", "planRrGateTarget": 2}})
    assert PlanArmer.first_sale_record(a, ap, trade, 1, 1.05, "enforce")["underlying"]["validated"]["problems"] == ["no_underlier_evidence"]


def test_the_frozen_pin_comes_from_the_run_config_bounded_and_cached():
    calls = []

    async def load_plan(rid):
        calls.append(rid)
        return {"config": {"settings": {"technique.rr_gate_target": "tp3"}, "thresholds": {"rr_gate_target": 2}}}
    me = SimpleNamespace(load_plan=load_plan)
    ap = SimpleNamespace(run_id="run9")

    async def go():
        await PlanArmer.first_sale_prepare(me, ap); await PlanArmer.first_sale_prepare(me, ap)
    asyncio.run(go())
    assert calls == ["run9"] and me.__dict__["_fs_pins"]["run9"] == {"pin": "tp3", "source": "run_config", "planRrGateTarget": 2}

    async def broken(rid):
        raise RuntimeError("db down")
    me2 = SimpleNamespace(load_plan=broken)
    asyncio.run(PlanArmer.first_sale_prepare(me2, ap))
    assert me2.__dict__["_fs_pins"]["run9"]["source"] == "unresolved"


# ------------------------------------------------------------- REAL caller boundary: _enter -> OrderManager (dispatch rig)
HOOD_TARGETS = [101.0, 103.6, 106.0]          # one contract -> TP2: (103.6 - 100.01) / (100.01 - 99) = 3.55R at the live ask


def _live_quote(price, stamp=None):
    stamp = stamp or now_ms()
    return Quote("HOOD", bid=round(price - 0.02, 2), ask=price, last=price, ts=stamp, source="alpaca", quote_ts=stamp, last_ts=stamp)


async def _rig(dispatch_rig, monkeypatch, mode, *, targets=HOOD_TARGETS, underlier=100.01):
    monkeypatch.setenv("ZARGAR_TEST_NOW", "2026-09-16T10:00:00-04:00")          # a Wednesday: the Friday x0.5 size multiplier is not the subject here
    rig = dispatch_rig
    await rig.engine.settings.set("techniques.enhanced_market.first_sale_rr_gate", mode)
    rig.trade.targets = list(targets)
    if underlier is not None:
        rig.engine.quotes.on_quote(_live_quote(underlier))

    async def reprice(contract):
        return contract
    rig.engine.options = SimpleNamespace(reprice=reprice)

    async def load_plan(rid):
        return {"config": {"settings": {"technique.rr_gate_target": "auto"}, "thresholds": {"rr_gate_target": 2}}}
    rig.runner.load_plan = load_plan
    return rig


async def test_default_off_reaches_the_venue_and_records_nothing(dispatch_rig, monkeypatch):
    rig = await _rig(dispatch_rig, monkeypatch, "off", targets=[101.0, 102.0, 103.0])   # 2R at TP2: would fail the gate, and is sent - baseline unchanged
    await rig.runner._enter(rig.ap, rig.trade, None, journal=True)
    assert rig.submit.await_count == 1 and "firstSale" not in rig.trade.timing and rig.runner.__dict__.get("_fs_recorder") is None


async def test_observe_with_a_blocked_research_writer_never_delays_or_refuses_the_entry(dispatch_rig, monkeypatch):
    rig = await _rig(dispatch_rig, monkeypatch, "observe", targets=[101.0, 102.0, 103.0])
    gate = asyncio.Event()
    real_append = rig.engine.journal.append

    async def append(type_, payload, **kw):
        if type_ == "TechniqueFirstSale":
            await gate.wait()                                                         # the research write hangs for ever
        return await real_append(type_, payload, **kw)
    monkeypatch.setattr(rig.engine.journal, "append", append)
    await asyncio.wait_for(rig.runner._enter(rig.ap, rig.trade, None, journal=True), timeout=5.0)
    assert rig.submit.await_count == 1, "a failing gate is only OBSERVED, and a hung research writer holds nothing"
    assert rig.trade.timing["firstSale"]["disposition"] == "observed_fail" and rig.runner._fs_recorder.stats["queued"] == 1 and rig.runner._fs_recorder.stats["written"] == 0
    gate.set()


async def test_enforce_passes_valid_evidence_and_refuses_durably_when_missing(dispatch_rig, monkeypatch):
    from sqlalchemy import select
    from zargar.models import Event
    rig = await _rig(dispatch_rig, monkeypatch, "enforce")
    await rig.runner._enter(rig.ap, rig.trade, None, journal=True)
    assert rig.submit.await_count == 1 and rig.trade.timing["firstSale"]["disposition"] == "passed" and rig.trade.timing["firstSaleDispatch"]["disposition"] == "passed"


async def test_enforce_defers_without_validated_underlier_evidence_and_journals_the_refusal(dispatch_rig, monkeypatch):
    from sqlalchemy import select
    from zargar.models import Event
    rig = await _rig(dispatch_rig, monkeypatch, "enforce", underlier=None)            # the rig's HOOD quote has no source and no venue time
    await rig.runner._enter(rig.ap, rig.trade, None, journal=True)
    assert rig.submit.await_count == 0 and rig.trade.status == "skipped" and "missing or invalid" in rig.trade.reason
    async with rig.engine.sf() as s:
        rows = (await s.execute(select(Event).where(Event.type == "TechniquePlanTriggerSkipped"))).scalars().all()
    assert len(rows) == 1 and rows[0].payload["stage"] == "first_sale" and rows[0].payload["detail"]["disposition"] == "deferred_missing_evidence", "the refusal evidence is on the durable path"


async def test_a_price_that_moves_between_the_check_and_the_dispatch_is_refused_at_the_final_guard(dispatch_rig, monkeypatch):
    rig = await _rig(dispatch_rig, monkeypatch, "enforce")
    original = rig.engine.risk.evaluate

    async def risk(intent, portfolio):
        verdict = await original(intent, portfolio)
        rig.engine.quotes.on_quote(_live_quote(102.0))                                # the underlying runs AFTER the first check, before the venue submit
        return verdict
    monkeypatch.setattr(rig.engine.risk, "evaluate", risk)
    await rig.runner._enter(rig.ap, rig.trade, None, journal=True)
    assert rig.trade.timing["firstSale"]["disposition"] == "passed" and rig.trade.timing["firstSaleDispatch"]["disposition"] == "refused"
    assert rig.submit.await_count == 0 and rig.trade.status == "skipped" and "first-sale gate" in rig.trade.reason, "a decision taken before the wait never authorises the changed price"


async def test_an_invalid_setting_refuses_entries_instead_of_silently_disabling_the_gate(dispatch_rig, monkeypatch):
    rig = await _rig(dispatch_rig, monkeypatch, "enforced")
    await rig.runner._enter(rig.ap, rig.trade, None, journal=True)
    assert rig.submit.await_count == 0 and "never silently off" in rig.trade.reason


# ------------------------------------------------------------------------------------------- vehicle comparison
def test_vehicle_comparison_keeps_unknowns_and_never_gates_on_friction_or_open_interest():
    setup = {"symbol": "DRAM", "direction": "short", "entry": 59.2, "stop": 59.9, "targets": [58.0833, 57.0, 56.0], "singleExit": "tp2"}
    rows = fs.compare_vehicles(setup=setup, contracts=[
        {"symbol": "DRAM260921P00058000", "strike": 58, "dte": 3, "delta": -0.35, "bid": 0.30, "ask": 0.36, "bidSize": 5, "askSize": 7, "openInterest": 88},
        {"symbol": "DRAM260921P00057000", "strike": 57, "dte": 3, "delta": None, "bid": 0.1, "ask": 0.2, "bidSize": 1, "askSize": 1},
        {"symbol": "DRAM260925P00058000", "strike": 58, "dte": 7, "delta": -0.4, "bid": 0, "ask": 0},
    ], share_quote=None, budget=750, risk_budget=100, fee_per_contract=1.04)["rows"]
    a, b, c, sh = rows
    assert a["status"] == "scored" and a["affordableQty"] == 4 and a["firstSaleRung"] == "tp1-ladder" and a["openInterest"] == 88
    assert a["overFrictionMarker"] is True and a["payoffProxyNet"] is not None, "the 8% marker is reported, never a refusal"
    assert b["status"] == "unknown" and "no_delta" in b["unknown"] and b["payoffProxyGross"] is None
    assert c["status"] == "unknown" and "no_two_sided_quote" in c["unknown"]
    assert sh["status"] == "not_permitted"
    longs = fs.compare_vehicles(setup={**setup, "direction": "long", "stop": 58.5, "targets": [60.3, 61, 62]}, contracts=[],
                                share_quote={"ask": 59.21, "askSize": 300}, budget=2000, risk_budget=100, fee_per_contract=1.04)["rows"]
    assert longs[0]["vehicle"] == "shares" and longs[0]["affordableQty"] == 33 and longs[0]["status"] == "scored"


# ------------------------------------------------------------------------- SKHY: one bounded re-pick after a provider 429
def _repick_rig(settings, last, picks):
    calls = []

    async def option_pick(sym, direction, **kw):
        calls.append(kw)
        return picks.pop(0)
    logs = []
    me = SimpleNamespace(engine=SimpleNamespace(settings=SimpleNamespace(get=lambda k, d=None: settings.get(k, d)),
                                                quotes=SimpleNamespace(get=lambda s: (SimpleNamespace(last=last) if last else None))),
                         technique=SimpleNamespace(option_pick=option_pick), _log=lambda ap, what, text, **kw: logs.append(what))
    trade = SimpleNamespace(trigger_id="r2", direction="short", entry=100.0, stop=101.0, timing={})
    return me, trade, calls, logs


RATE_LIMITED = {"available": False, "error": "CBOE HTTP 429 (rate limited; 2 retries)"}
KNOB = "techniques.enhanced_market.pick_retry_after_429_s"


def test_skhy_repick_is_off_by_default_bounded_to_one_attempt_and_never_chases(monkeypatch):
    import zargar.technique.arming as arming
    slept = []

    async def fake_sleep(s):
        slept.append(s)
    monkeypatch.setattr(arming.asyncio, "sleep", fake_sleep)
    ap = SimpleNamespace(symbol="SKHY")
    me, trade, calls, _ = _repick_rig({}, 99.9, [])
    assert asyncio.run(PlanArmer._repick_after_rate_limit(me, ap, trade, dict(RATE_LIMITED))) == RATE_LIMITED and calls == [] and slept == [], "OFF by default: baseline unchanged"
    me, trade, calls, logs = _repick_rig({KNOB: 60}, 99.9, [{"available": True, "symbol": "SKHY260925P00100000"}])
    out = asyncio.run(PlanArmer._repick_after_rate_limit(me, ap, trade, dict(RATE_LIMITED)))
    assert out["available"] and len(calls) == 1 and slept == [8.0] and trade.timing["pickRetryAfter429S"] == 8.0, "ONE retry, the wait capped at 8 s"
    assert calls[0]["spot"] == 99.9, "the re-pick prices off the CURRENT underlying"
    me, trade, calls, _ = _repick_rig({KNOB: 4}, 99.5, [{"available": True}])                  # a short that already fell 0.5R past its entry
    out = asyncio.run(PlanArmer._repick_after_rate_limit(me, ap, trade, dict(RATE_LIMITED)))
    assert not out.get("available") and "no chase" in out["error"] and calls == []
    me, trade, calls, _ = _repick_rig({KNOB: 4}, None, [{"available": True}])
    assert "cannot be re-checked" in asyncio.run(PlanArmer._repick_after_rate_limit(me, ap, trade, dict(RATE_LIMITED)))["error"] and calls == []
    me, trade, calls, _ = _repick_rig({KNOB: 4}, 99.9, [])
    other = {"available": False, "error": "no contract just OTM"}
    assert asyncio.run(PlanArmer._repick_after_rate_limit(me, ap, trade, other)) == other and calls == [], "only a provider rate limit is retried"
    from zargar.settings_service import DEFAULTS
    assert DEFAULTS[KNOB] == 0.0
