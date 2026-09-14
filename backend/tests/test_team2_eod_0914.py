"""EOD 2026-09-14 handoff fixtures beyond the reviewers' packet: R1 the read drops the proxy of a live-refused fire,
R2 the cutoff is re-checked after quoting, R3 a corrected minute is merged and recorded, R5 the scorecard keeps the
attempt and its decisive verdict."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

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
    assert card["funnel"] == {"attempts": 1, "filled": 0, "policyRefused": 1, "transientDeferred": 0, "picked": 0, "bookLosses": 0}
    assert card["actualFires"] == 0 and card["skips"] == {}
