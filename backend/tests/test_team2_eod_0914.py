"""EOD 2026-09-14 handoff fixtures beyond the reviewers' packet: R1 the read drops the proxy of a live-refused fire,
R2 the cutoff is re-checked after quoting, R3 a corrected minute is merged and recorded, R5 the scorecard keeps the
attempt and its decisive verdict."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from zargar.domain import Bar
from zargar.execution.planrunner import ArmConfig, ArmedPlan, Trade
from zargar.marketstructure import aggregate
from zargar.marketstructure.sessions import ET
from zargar.techniques.team2.plan import build_skeleton, complete_plan
from zargar.techniques.team2.rules import Team2Rules
from zargar.techniques.team2.runner import Team2Runner
from zargar.techniques.team2.session import simulate_session

from .test_team2_integrity import drift_day
from .test_team2_picker_gates import _runner as _picker_runner
from .test_team2_session import DAY, make_rules, path_1m, prev_day_bars


# ---------------------------------------------------------------- R1: no proxy for a live-refused fire
def _read(refused: list[str] | None):
    rules = make_rules()
    prev = prev_day_bars()
    today = path_1m(DAY, (4, 0), (20, 0), drift_day)
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(prev, 15), rules, prev_bars_1m=prev), today)
    plan["contractAuthority"] = "quotes"
    if refused is not None:
        plan["executionRefused"] = refused
    return simulate_session(plan, today, rules, sigma=0.2, warmup_1m=prev)


def test_a_live_refused_fire_opens_no_model_position_and_the_fire_event_is_unchanged():
    base = _read(None)
    fires = [e for e in base.events if e["event"] == "fire"]
    assert fires and base.to_dict()["trades"]
    tid = f"{fires[0]['setup']}#{fires[0]['touch']}"
    res = _read([tid])
    f2 = [e for e in res.events if e["event"] == "fire"]
    assert f2 and f2[0]["ts"] == fires[0]["ts"] and f2[0]["why"] == fires[0]["why"]      # same fingerprint: never re-acted
    assert f2[0]["unfilledLive"] is True
    assert [e for e in res.events if e["event"] == "fire_unfilled_live"]
    d = res.to_dict()
    # no proxy position for that fire: no trade, no model loss from it, the setup's entries not counted
    assert not [t for t in d["trades"] if t["setup"] == fires[0]["setup"] and t["entryTs"] == fires[0]["ts"]]
    setup = next(s for s in d["setups"] if s["id"] == fires[0]["setup"])
    assert setup["attempts"] >= 1 and setup["entries"] == 0 and setup["touches"] >= 1      # the touch is still spent (F61)


# ---------------------------------------------------------------- R2: cutoff re-checked after quoting
async def test_the_cutoff_is_rechecked_after_the_quotes_come_back(monkeypatch):
    import zargar.techniques.team2.runner as module
    runner, trade, options = _picker_runner([(287.5, 0.19)], {287.5: (0.20, 0.21)})
    runner.engine.journal = SimpleNamespace(append=AsyncMock())
    today = dt.datetime.now(ET).date()
    ap = SimpleNamespace(symbol="IWM", run_id="run-cut", plan={}, plan_for=today.isoformat())
    late = dt.datetime.combine(today, dt.time(15, 31), tzinfo=ET).timestamp()
    monkeypatch.setattr(module.time, "time", lambda: late)
    assert await runner.pick_contract(ap, trade) is None
    kind, msg, kw = runner._logged[-1]
    assert kind == "contract_deferred" and kw["stage"] == "cutoff" and "cutoff passed while quoting" in trade.errors[-1]
    assert ap.plan["executionRefused"] == ["probe"]


def test_stale_signal_is_recorded_with_source_and_decision_times(monkeypatch):
    import zargar.techniques.team2.runner as module
    runner = Team2Runner.__new__(Team2Runner)
    rules = Team2Rules()
    day = dt.date.today()
    ap = SimpleNamespace(plan_for=day.isoformat())
    src = int(dt.datetime.combine(day, dt.time(12, 0), tzinfo=ET).timestamp() * 1000)
    monkeypatch.setattr(module.time, "time", lambda: src / 1000 + 60)
    assert runner._stale_signal(ap, {"ts": src}, rules) is None                      # one minute old, fine
    monkeypatch.setattr(module.time, "time", lambda: src / 1000 + 5 * 60)
    rec = runner._stale_signal(ap, {"ts": src}, rules)
    assert rec and rec["sourceTs"] == src and rec["ageMs"] == 5 * 60_000 and "recovered" in rec["why"]
    ap2 = SimpleNamespace(plan_for=(day - dt.timedelta(days=1)).isoformat())
    monkeypatch.setattr(module.time, "time", lambda: src / 1000 + 60)
    assert "not this session" in runner._stale_signal(ap2, {"ts": src}, rules)["why"]


# ---------------------------------------------------------------- R3: revisions are merged and recorded
def _rig():
    eng = SimpleNamespace(settings={}, journal=SimpleNamespace(append=AsyncMock()), trading_halted=lambda _: False, quiesce_until_ms=0)
    runner = Team2Runner(eng)
    runner._log = Mock()
    ap = ArmedPlan(run_id="rev", symbol="SPY", plan_for="2026-09-14", plan={"zones": {"present": True}, "openSource": "rth_open"},
                   config=ArmConfig(portfolio_id="p", mode="auto", instrument="options", use_critic=False), trackers={}, armed_at=0)
    runner._armed[ap.run_id] = ap
    return runner, ap


def _bar(h, m, close, source="exchange"):
    ts = int(dt.datetime(2026, 9, 14, h, m, tzinfo=ET).timestamp() * 1000)
    return Bar("SPY", "1m", ts, close, close + 0.1, close - 0.1, close, 100, source)


def test_a_corrected_minute_replaces_the_stored_one_and_a_hole_is_inserted_in_order():
    runner, ap = _rig()
    b0, b2 = _bar(10, 0, 100.0), _bar(10, 2, 102.0)
    runner._bars[ap.run_id] = [b0, b2]
    ap.last_bar_ts, ap.bar_index = b2.ts, 2
    runner._merge_revision(ap, _bar(10, 0, 101.0))
    runner._merge_revision(ap, _bar(10, 1, 100.5))
    runner._merge_revision(ap, _bar(10, 2, 102.0))                                  # identical: nothing to record
    tape = [(b.ts, b.close) for b in runner._bars[ap.run_id]]
    assert tape == [(b0.ts, 101.0), (_bar(10, 1, 0).ts, 100.5), (b2.ts, 102.0)]
    kinds = [c.args[1] for c in runner._log.call_args_list]
    assert kinds == ["bar_revised", "bar_recovered"]
    assert ap.bar_index == 2 and ap.last_bar_ts == b2.ts                          # the revision is not a new bar


# ---------------------------------------------------------------- R5: the scorecard keeps the attempt and its verdict
def test_scorecard_row_carries_the_refused_attempt_and_its_decisive_reason():
    runner, ap = _rig()
    runner._contract_verdicts[ap.run_id] = [
        {"event": "contract_refused", "trigger": "scenario_1@13:00#1", "verdict": "refused", "reason": "no call between $0.20 and $0.90 ... examined 290 ask 0.13 (opra, chain 0.10)",
         "examined": [{"strike": 290.0, "ask": 0.13, "bid": 0.12, "priced": "opra", "delayedAsk": 0.10, "eligible": True}]}]
    t = Trade(trigger_id="scenario_1@13:00#1", kind="scenario_1", direction="long", fired_ts=1, window="team2", entry=289.06, stop=288.5,
              targets=[], instrument="options", status="failed", reason="no option contract available (see errors)")
    t.setup_id = "scenario_1@13:00"
    ap.trades[t.trigger_id] = t
    runner._last_sim[ap.run_id] = {"trades": [{"setup": "scenario_1@13:00", "entryTs": 1, "entryKind": "ema", "strike": 290.0,
                                               "entryPremium": 0.0233, "pnlPct": -126.71, "exitReason": "stop", "win": False}], "bias": {}}
    runner._fees_paid = lambda tr: 0.0
    card = runner._score_execution(ap)
    row = card["rows"][0]
    assert row["status"] == "failed" and row["trigger"] == t.trigger_id and row["note"].startswith("attempted, not filled")
    assert row["attempt"]["attemptKind"] == "policy_refusal" and "examined 290 ask 0.13" in row["attempt"]["decisiveReason"]
    assert {k: card["funnel"][k] for k in ("attempts", "filled", "policyRefused", "transientDeferred", "picked", "bookLosses")} == \
        {"attempts": 1, "filled": 0, "policyRefused": 1, "transientDeferred": 0, "picked": 0, "bookLosses": 0}
    assert card["funnel"]["verdicts"] == 1 and card["funnel"]["journalOnly"] == 0
    assert card["actualFires"] == 0 and card["skips"] == {}


# ================================================================ follow-up review (A-D), 2026-09-14
from .test_codex_team2_data_eod import bar as _rbar, ms as _ms, rig as _rrig   # noqa: E402  (the reviewer's rig, reused)


def _result(events):
    setups = [{"id": "scenario_1@09:45", "kind": "scenario_1", "direction": "long", "target": 104.0}]
    return SimpleNamespace(events=events, setups=setups, to_dict=lambda: {"events": events, "setups": setups, "summary": {}})


def _fire(h, m, touch=1):
    return {"event": "fire", "ts": _ms(h, m), "setup": "scenario_1@09:45", "touch": touch, "spot": 101.0, "target": 104.0,
            "targetKind": "plan", "regime": {"stack": "bull", "atr": 1}, "entryKind": "ema", "why": "fixture", "sizeMult": 1}


# ---------------------------------------------------------------- A: the execution overlay is durable and complete
def test_a_zero_fill_outcomes_ride_the_ordinary_persist_and_come_back_on_restore():
    runner, ap = _rrig()
    cancelled = Trade(trigger_id="scenario_1@09:45#1", kind="scenario_1", direction="long", fired_ts=_ms(9, 46), window="team2",
                      entry=100, stop=99, targets=[104], status="cancelled", reason="entry_capped: cancelled unfilled",
                      entry_order_id="o-1", filled_qty=0)
    working = Trade(trigger_id="scenario_1@09:45#2", kind="scenario_1", direction="long", fired_ts=_ms(10, 0), window="team2",
                    entry=100, stop=99, targets=[104], status="working", entry_order_id="o-2", filled_qty=0)
    partial = Trade(trigger_id="scenario_1@09:45#3", kind="scenario_1", direction="long", fired_ts=_ms(10, 10), window="team2",
                    entry=100, stop=99, targets=[104], status="open", entry_order_id="o-3", filled_qty=1, qty=3)
    for t in (cancelled, working, partial):
        t.setup_id = "scenario_1@09:45"
        ap.trades[t.trigger_id] = t
    runner._decision_wm[ap.run_id] = _ms(10, 12)
    extras = runner.state_extras(ap)                       # what `_persist` writes on EVERY save
    assert extras["executionRefused"] == ["scenario_1@09:45#1"], "only the terminal zero-fill outcome is exempt"
    assert extras["decisionWatermark"] == _ms(10, 12)
    # a fresh process: the plan comes back from the run without the overlay, the state brings it back
    runner2, ap2 = _rrig()
    assert "executionRefused" not in ap2.plan
    runner2.restore_extras(ap2, extras)
    assert ap2.plan["executionRefused"] == ["scenario_1@09:45#1"] and runner2._decision_wm[ap2.run_id] == _ms(10, 12)


async def test_a_stale_and_capacity_refusals_exempt_the_proxy_too(monkeypatch):
    import zargar.techniques.team2.runner as module
    runner, ap = _rrig()
    monkeypatch.setattr(module.time, "time", lambda: _ms(15, 32) / 1000)
    await runner._fire_from_event(ap, _fire(15, 28), _rbar(15, 27), _result([]), halted=False, journal=True)
    assert ap.plan["executionRefused"] == ["scenario_1@09:45#1"] and not ap.trades


async def test_a_reload_keeps_a_deferral_that_was_later_picked_out_of_the_exemption():
    runner, ap = _rrig()
    rows = [{"trigger": "scenario_1@09:45#1", "event": "contract_deferred", "verdict": "deferred", "reason": "no fresh quote"},
            {"trigger": "scenario_1@09:45#1", "event": "contract_picked", "verdict": "picked", "reason": "SPY 102C 0.50"},
            {"trigger": "scenario_1@09:45#2", "event": "contract_refused", "verdict": "refused", "reason": "below the floor"}]
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [SimpleNamespace(payload=r) for r in rows]))))

    class Context:
        async def __aenter__(self): return session
        async def __aexit__(self, *args): return False
    runner.engine.sf = Context
    assert await runner.load_contract_verdicts() == 3
    assert ap.plan["executionRefused"] == ["scenario_1@09:45#2"], "the LAST verdict decides; the picked fire keeps its position"


# ---------------------------------------------------------------- B: one gate at the order boundary
@pytest.mark.parametrize("minute, entered", [(20, 1), (31, 0)])
async def test_b_the_shared_fire_chain_refuses_a_new_order_after_the_cutoff(monkeypatch, minute, entered):
    import zargar.techniques.team2.runner as module
    import zargar.execution.planrunner as shared
    runner, ap = _rrig()
    monkeypatch.setattr(module.time, "time", lambda: _ms(15, minute) / 1000)
    monkeypatch.setattr(shared, "now_ms", lambda: _ms(15, minute))
    trade = Trade(trigger_id="scenario_1@09:45#1", kind="scenario_1", direction="long", fired_ts=_ms(15, 18), window="team2",
                  entry=100, stop=99, targets=[104], instrument="options", contract={"symbol": "SPY260914C00102000", "ask": .5},
                  order_symbol="SPY260914C00102000")
    trade.contract_attempted = True                      # a cached contract: the picker never runs for it
    trade.setup_id = "scenario_1@09:45"
    ap.trades[trade.trigger_id] = trade
    runner._enter = AsyncMock()
    stub = SimpleNamespace(kind="scenario_1", direction="long", fill_price=100, entry=100, stop=99, fire_event=_fire(15, 18),
                           trigger={"targets": [{"price": 104}]}, status="fired")
    await runner._fire_rest(ap, trade.trigger_id, stub, _rbar(15, minute - 1), 1, trade, journal=True)
    assert runner._enter.await_count == entered
    if not entered:
        assert trade.status == "skipped" and "cutoff" in trade.reason
        kinds = [c.args[1].get("event") for c in runner.engine.journal.append.call_args_list]
        assert "entry_gate_refused" in kinds
        assert runner.state_extras(ap)["executionRefused"] == [trade.trigger_id]


async def test_b_the_order_stage_and_the_retry_are_gated_on_the_same_clock(monkeypatch):
    import zargar.techniques.team2.runner as module
    runner, ap = _rrig()
    trade = Trade(trigger_id="scenario_1@09:45#1", kind="scenario_1", direction="long", fired_ts=_ms(15, 29), window="team2",
                  entry=100, stop=99, targets=[104], instrument="options")
    monkeypatch.setattr(module.time, "time", lambda: _ms(15, 29) / 1000 + 50)
    assert await runner._entry_gated(ap, trade, "order") is None
    monkeypatch.setattr(module.time, "time", lambda: _ms(15, 30) / 1000 + 1)     # the cutoff crossed while sizing
    why = await runner._entry_gated(ap, trade, "order")
    assert why and "(order)" in why and "15:30" in why
    assert await runner._entry_gated(ap, trade, "retry"), "a collar re-price after the cutoff is not sent either"
    ap.config = ArmConfig(portfolio_id="p", mode="alert", instrument="options", use_critic=False)
    assert await runner._entry_gated(ap, trade, "order") is None, "alert plans send nothing; the gate does not apply"


# ---------------------------------------------------------------- C: the decision watermark
async def test_c_a_present_time_signal_still_fires_after_a_revision(monkeypatch):
    import zargar.techniques.team2.runner as module
    import zargar.execution.planrunner as shared
    runner, ap = _rrig()
    clock = [_ms(10, 2)]
    monkeypatch.setattr(module.time, "time", lambda: clock[0] / 1000)
    monkeypatch.setattr(shared, "now_ms", lambda: clock[0])
    monkeypatch.setattr(module, "simulate_session", lambda plan, bars, *a, **k: _result([_fire(10, 4)] if any(b.ts == _ms(10, 3) for b in bars) else []))
    runner.pick_contract = AsyncMock(return_value={"symbol": "SPY260914C00102000", "ask": .5})
    runner._enter = AsyncMock()
    await runner.on_minute_bar("SPY", _rbar(10, 1, 100))          # decision at 10:02, nothing
    clock[0] = _ms(10, 3)
    await runner.on_minute_bar("SPY", _rbar(10, 1, 101))          # a correction of 10:01
    clock[0] = _ms(10, 4)
    await runner.on_minute_bar("SPY", _rbar(10, 3, 101))          # decision at 10:04: a fire closing NOW
    await runner.wait_fires(ap.run_id)
    assert runner._enter.await_count == 1, "a signal established at the current close is causal and acts"
    assert runner._decision_wm[ap.run_id] == _ms(10, 4)


async def test_c_a_revision_that_creates_a_past_exit_is_recorded_not_acted_on(monkeypatch):
    import zargar.techniques.team2.runner as module
    import zargar.execution.planrunner as shared
    runner, ap = _rrig()
    clock = [_ms(10, 2)]
    monkeypatch.setattr(module.time, "time", lambda: clock[0] / 1000)
    monkeypatch.setattr(shared, "now_ms", lambda: clock[0])
    past_exit = {"event": "exit", "ts": _ms(10, 2), "setup": "scenario_1@09:45", "fraction": 1.0, "pnlPct": -40.0,
                 "why": "stop on the corrected 10:01 close"}

    def read(plan, bars, *a, **k):
        return _result([past_exit] if any(b.ts == _ms(10, 1) and b.close == 98 for b in bars) else [])
    monkeypatch.setattr(module, "simulate_session", read)
    runner._exit_from_event = AsyncMock()
    open_trade = Trade(trigger_id="scenario_1@09:45#1", kind="scenario_1", direction="long", fired_ts=_ms(9, 46), window="team2",
                       entry=100, stop=99, targets=[104], status="open", filled_qty=2, remaining=2, instrument="options")
    open_trade.setup_id = "scenario_1@09:45"
    ap.trades[open_trade.trigger_id] = open_trade
    await runner.on_minute_bar("SPY", _rbar(10, 1, 100))
    clock[0] = _ms(10, 3)
    await runner.on_minute_bar("SPY", _rbar(10, 1, 98))            # the correction introduces a 10:02 stop
    clock[0] = _ms(10, 4)
    await runner.on_minute_bar("SPY", _rbar(10, 3, 98))
    assert runner._exit_from_event.await_count == 0, "a historical exit instruction is not a present-time order"
    journaled = [c.args[1] for c in runner.engine.journal.append.call_args_list if c.args[1].get("event") == "backdated_signal_skip"]
    assert len(journaled) == 1 and journaled[0]["instruction"] == "exit" and journaled[0]["judgedAt"] == _ms(10, 2)
    assert open_trade.status == "open", "the position stays under present-time management (live trims, target breach, flatten)"


async def test_c_revisions_are_journaled_once_and_a_duplicate_delivery_writes_nothing():
    runner, ap = _rrig()
    runner._bars[ap.run_id] = [_rbar(10, 0, 100), _rbar(10, 2, 102)]
    ap.last_bar_ts, ap.bar_index = _ms(10, 2), 2
    runner._decision_wm[ap.run_id] = _ms(10, 2)
    await runner.on_minute_bar("SPY", _rbar(10, 0, 101))           # corrected
    await runner.on_minute_bar("SPY", _rbar(10, 0, 101))           # the same correction again
    await runner.on_minute_bar("SPY", _rbar(10, 1, 100.5))         # a recovered hole
    rows = [c.args[1] for c in runner.engine.journal.append.call_args_list]
    kinds = [r.get("event") for r in rows]
    assert kinds == ["bar_revised", "bar_recovered"], kinds
    assert rows[0]["before"] == [100, 100.1, 99.9, 100, 100] and rows[0]["after"][3] == 101 and rows[0]["decisionWatermark"] == _ms(10, 2)
    assert [b.close for b in runner._bars[ap.run_id]] == [101, 100.5, 102]


# ---------------------------------------------------------------- D: the funnel reconciles from durable verdicts
def test_d_a_deferral_then_a_pick_and_fill_is_one_opportunity_with_two_verdicts():
    runner, ap = _rrig()
    runner._fees_paid = lambda tr: 0.0
    runner._last_sim[ap.run_id] = {"trades": [{"setup": "scenario_1@09:45", "entryTs": _ms(9, 46), "pnlPct": 30.0, "win": True}], "bias": {}}
    runner._contract_verdicts[ap.run_id] = [
        {"trigger": "scenario_1@09:45#1", "event": "contract_deferred", "verdict": "deferred", "reason": "no fresh quote yet"},
        {"trigger": "scenario_1@09:45#1", "event": "contract_picked", "verdict": "picked", "reason": "SPY 102C 0.50", "ask": .5, "bid": .48},
        {"trigger": "scenario_1@09:45#2", "event": "contract_refused", "verdict": "refused", "reason": "below the floor"},
        {"trigger": "scenario_1@09:45#2", "event": "contract_refused", "verdict": "refused", "reason": "below the floor"},   # delivered twice
    ]
    filled = Trade(trigger_id="scenario_1@09:45#1", kind="scenario_1", direction="long", fired_ts=_ms(9, 46), window="team2",
                   entry=100, stop=99, targets=[104], status="closed", filled_qty=2, avg_fill=.5, realized_pnl=40.0,
                   instrument="options", order_symbol="SPY260914C00102000")
    filled.setup_id = "scenario_1@09:45"
    ap.trades[filled.trigger_id] = filled                        # the refused #2 has NO projection (crash before persist)
    card = runner._score_execution(ap)
    f = card["funnel"]
    assert (f["attempts"], f["filled"], f["policyRefused"], f["transientDeferred"], f["picked"], f["verdicts"], f["journalOnly"]) == (2, 1, 1, 0, 1, 4, 1)
    rows = {r["trigger"]: r for r in card["rows"]}
    assert rows["scenario_1@09:45#1"]["status"] == "closed" and rows["scenario_1@09:45#1"]["realizedPnl"] == 40.0
    jo = rows["scenario_1@09:45#2"]
    assert jo["attempt"]["evidence"] == "journal-only" and jo["attempt"]["attemptKind"] == "policy_refusal" and jo["attempt"]["verdictCount"] == 2
    assert jo["note"].startswith("journaled verdict without a trade projection")
    assert card["matched"] == 1 and len(card["rows"]) == 2


# ================================================================ v0.7.76 acceptance review (E, F, G), 2026-09-14
def _sub_trade(ap, status="submitting"):
    t = Trade(trigger_id="scenario_1@14:45#1", kind="scenario_1", window="team2", direction="long", fired_ts=_ms(15, 28),
              entry=100, stop=99, targets=[104], status=status, instrument="options", filled_qty=0)
    t.setup_id = "scenario_1@14:45"
    ap.trades[t.trigger_id] = t
    return t


@pytest.mark.parametrize("cross_cutoff, expected_calls", [(False, 2), (True, 1)])
async def test_e_transport_retry_is_judged_on_the_wall_clock_without_fa01(monkeypatch, cross_cutoff, expected_calls):
    """The same boundary as the reviewer's first case, with a plain guard callable (no FA-01 on this checkout)."""
    import zargar.techniques.team2.runner as module
    import zargar.execution.planrunner as shared
    runner, ap = _rrig()
    t = _sub_trade(ap)
    clock = [_ms(15, 29) + 59_000]
    monkeypatch.setattr(module.time, "time", lambda: clock[0] / 1000)
    monkeypatch.setattr(shared, "now_ms", lambda: clock[0])
    attempts = []

    async def place(intent, *, before_submit=None):
        if before_submit:
            before_submit()
        attempts.append(clock[0])
        if len(attempts) == 1:
            raise ConnectionError("temporarily unavailable before submission")
        return {"id": "synthetic-order", "status": "SUBMITTED"}

    async def delay(_s):
        clock[0] = _ms(15, 30) + 1000 if cross_cutoff else _ms(15, 29) + 59_500
    monkeypatch.setattr(shared.asyncio, "sleep", delay)
    runner.engine.orders = SimpleNamespace(place=place)
    assert await runner.entry_gate(ap, t, "order") is None
    await runner._place_with_retry(ap, t, SimpleNamespace(), stage="entry", before_submit=lambda: None)
    assert len(attempts) == expected_calls
    if cross_cutoff:
        assert t.status == "skipped" and "cutoff" in t.reason
        rows = [c.args[1] for c in runner.engine.journal.append.call_args_list if c.args[1].get("event") == "entry_gate_refused"]
        assert rows and rows[0]["stage"] == "retry" and rows[0]["decisionTs"] == _ms(15, 30) + 1000
        assert runner.state_extras(ap)["executionRefused"] == [t.trigger_id], "a timed-out opportunity: skipped, no proxy"


async def test_e_the_cutoff_crossed_inside_the_order_manager_refuses_before_the_venue(monkeypatch):
    """OrderManager runs `before_submit` after its LAST await: the composed Team2 predicate refuses there."""
    import zargar.techniques.team2.runner as module
    runner, ap = _rrig()
    t = _sub_trade(ap)
    clock = [_ms(15, 29) + 58_000]
    monkeypatch.setattr(module.time, "time", lambda: clock[0] / 1000)
    sent = []

    async def place(intent, *, before_submit=None):
        clock[0] = _ms(15, 30) + 200                       # the manager's own awaits crossed the cutoff
        try:
            before_submit()
        except Exception as exc:                            # what OrderManager does: REJECTED_RISK, never a venue call
            return {"id": "o-1", "status": "REJECTED_RISK", "rejectReason": f"Pre-submit validation failed: {exc}"}
        sent.append(1)
        return {"id": "o-1", "status": "SUBMITTED"}
    runner.engine.orders = SimpleNamespace(place=place)
    res = await runner._place_with_retry(ap, t, SimpleNamespace(), stage="entry")
    assert not sent and res["status"] == "REJECTED_RISK" and "entry gate:" in res["rejectReason"] and "cutoff" in res["rejectReason"]


async def test_e_a_session_date_change_refuses_the_retry_and_an_exit_still_goes_out(monkeypatch):
    import zargar.techniques.team2.runner as module
    import zargar.execution.planrunner as shared
    runner, ap = _rrig()
    t = _sub_trade(ap)
    clock = [_ms(15, 20)]
    monkeypatch.setattr(module.time, "time", lambda: clock[0] / 1000)
    monkeypatch.setattr(shared, "now_ms", lambda: clock[0])
    calls = []

    async def place(intent, *, before_submit=None):
        if before_submit:
            before_submit()
        calls.append(getattr(intent, "reduce_only", False))
        if len(calls) == 1:
            raise ConnectionError("connection reset")
        return {"id": "o", "status": "SUBMITTED"}

    async def delay(_s):
        clock[0] = _ms(15, 20) + 86_400_000                 # the retry lands on the next session date
    monkeypatch.setattr(shared.asyncio, "sleep", delay)
    runner.engine.orders = SimpleNamespace(place=place)
    assert await runner._place_with_retry(ap, t, SimpleNamespace(reduce_only=False), stage="entry") is None
    assert len(calls) == 1 and t.status == "skipped" and "not the plan's session" in t.reason
    # a protective exit after the cutoff / on another date is never gated
    clock[0] = _ms(15, 40)
    ex = Trade(trigger_id="x", kind="scenario_1", window="team2", direction="long", fired_ts=_ms(10, 0), entry=100, stop=99, targets=[104],
               status="open", instrument="options", filled_qty=2, remaining=2)
    assert (await runner._place_with_retry(ap, ex, SimpleNamespace(reduce_only=True), stage="exit"))["status"] == "SUBMITTED"


async def test_f_a_venue_handoff_without_an_answer_keeps_the_order_identity_and_the_exposure():
    from zargar.orders import SubmitUncertain
    runner, ap = _rrig()
    t = _sub_trade(ap)
    ap.config.max_retries = 3
    runner._alert = AsyncMock()
    runner.engine.orders = SimpleNamespace(place=AsyncMock(side_effect=SubmitUncertain("ord-77", TimeoutError("no ACK after send"))))
    assert await runner._place_with_retry(ap, t, SimpleNamespace(), stage="entry") is None
    assert runner.engine.orders.place.await_count == 1, "an ambiguous submission is never retried as a fresh order"
    assert t.status == "submitting" and t.submit_uncertain and t.entry_order_id == "ord-77"
    assert runner._order_index.get("ord-77") == (ap.run_id, t.trigger_id), "fills for that order still find the trade"
    assert runner._alert.await_count == 1
    extras = runner.state_extras(ap)
    assert t.trigger_id not in extras["executionRefused"]
    # persisted and restored as uncertain — a restart never turns it into a zero fill
    d = t.to_dict()
    assert d["submitUncertain"] is True
    runner2, ap2 = _rrig()
    await runner2._restore_trades(ap2, state={"trades": [d]})
    assert ap2.trades[t.trigger_id].submit_uncertain and ap2.trades[t.trigger_id].status == "submitting"
    assert t.trigger_id not in runner2.state_extras(ap2)["executionRefused"]


def test_f_fill_evidence_withdraws_a_stored_exemption_and_a_confirmed_rejection_keeps_it():
    runner, ap = _rrig()
    t = _sub_trade(ap, status="failed")
    assert runner.state_extras(ap)["executionRefused"] == [t.trigger_id]
    t.status, t.filled_qty = "open", 1.0                    # a late partial fill arrives for the "failed" entry
    assert runner.state_extras(ap)["executionRefused"] == [], "the overlay reconciles on evidence; it is not append-only"
    t.status, t.filled_qty = "rejected", 0.0
    t.reason = "venue confirmed rejection; no fill"
    assert runner.state_extras(ap)["executionRefused"] == [t.trigger_id]


async def test_g_a_held_position_the_model_no_longer_holds_still_gets_the_present_time_candle_stop(monkeypatch):
    """The reviewer's control: an actual held position, a suppressed historical model exit, then a present-time
    method stop (S1: the 2m close through the EMA13) issued NOW."""
    import zargar.techniques.team2.runner as module
    import zargar.execution.planrunner as shared
    runner, ap = _rrig()
    clock = [_ms(10, 2)]
    monkeypatch.setattr(module.time, "time", lambda: clock[0] / 1000)
    monkeypatch.setattr(shared, "now_ms", lambda: clock[0])
    past_exit = {"event": "exit", "ts": _ms(10, 2), "setup": "scenario_1@09:45", "fraction": 1.0, "pnlPct": -40.0,
                 "why": "stop on the corrected 10:01 close"}

    def read(plan, bars, *a, **k):
        revised = any(b.ts == _ms(10, 1) and b.close == 98 for b in bars)
        r = _result([past_exit] if revised else [])
        r.open_position = None if revised else {"setup": "scenario_1@09:45", "entryKind": "ema"}
        r.regime_last = {"ema13": 99.5, "ema48": 99.0, "ema200": 98.0, "stack": "bull"}
        return r
    monkeypatch.setattr(module, "simulate_session", read)
    runner._exit = AsyncMock()
    held = Trade(trigger_id="scenario_1@09:45#1", kind="scenario_1", direction="long", fired_ts=_ms(9, 46), window="team2",
                 entry=100, stop=98.5, targets=[104], status="open", filled_qty=2, remaining=2, instrument="options")
    held.setup_id, held._entry_kind = "scenario_1@09:45", "ema"
    ap.trades[held.trigger_id] = held
    await runner.on_minute_bar("SPY", _rbar(10, 1, 100))          # decision at 10:02: model holds, close above EMA13 — nothing
    assert runner._exit.await_count == 0
    clock[0] = _ms(10, 3)
    await runner.on_minute_bar("SPY", _rbar(10, 1, 98))            # the correction: the model's position is now closed at 10:02
    clock[0] = _ms(10, 4)
    await runner.on_minute_bar("SPY", _rbar(10, 3, 99.8))          # decision at 10:04: close 99.8 ABOVE the EMA13 99.5 — hold
    assert runner._exit.await_count == 0, "the suppressed historical exit is not replayed and no stop is due yet"
    clock[0] = _ms(10, 6)
    await runner.on_minute_bar("SPY", _rbar(10, 5, 99.2))          # decision at 10:06: 2m close 99.2 through the EMA13 — stop NOW
    assert runner._exit.await_count == 1
    args, kw = runner._exit.call_args
    assert args[1] is held and args[2] == "stop" and args[3] == 2 and kw["force_market"] and "present-time S1" in kw["reason"]
    rows = [c.args[1] for c in runner.engine.journal.append.call_args_list if c.args[1].get("event") == "orphan_stop"]
    assert rows and rows[0]["decisionTs"] == _ms(10, 6) and rows[0]["close"] == 99.2 and rows[0]["guard"] == 99.5


async def test_g_the_model_s_own_held_position_is_left_to_the_model(monkeypatch):
    import zargar.techniques.team2.runner as module
    import zargar.execution.planrunner as shared
    runner, ap = _rrig()
    clock = [_ms(10, 2)]
    monkeypatch.setattr(module.time, "time", lambda: clock[0] / 1000)
    monkeypatch.setattr(shared, "now_ms", lambda: clock[0])
    r = _result([]); r.open_position = {"setup": "scenario_1@09:45"}; r.regime_last = {"ema13": 99.5}
    monkeypatch.setattr(module, "simulate_session", lambda *a, **k: r)
    runner._exit = AsyncMock()
    held = Trade(trigger_id="scenario_1@09:45#1", kind="scenario_1", direction="long", fired_ts=_ms(9, 46), window="team2",
                 entry=100, stop=98.5, targets=[104], status="open", filled_qty=2, remaining=2, instrument="options")
    held.setup_id, held._entry_kind = "scenario_1@09:45", "ema"
    ap.trades[held.trigger_id] = held
    await runner.on_minute_bar("SPY", _rbar(10, 1, 99.0))          # through the EMA13, but the MODEL holds it: its own exit rules speak
    assert runner._exit.await_count == 0
