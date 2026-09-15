"""Order-free forward measurement (STRATEGY-PROPOSAL-2026-09-14, revised): the shadow exit observer records a
fresh target observation with the same-contract NBBO and never orders; the target-distance diagnostic records
at fire and fill and never gates; the source-candidate evaluator applies the frozen definition and keeps unknowns.
No DB, no engine start, no network."""
import asyncio
import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from zargar.domain import Quote
from zargar.execution.planrunner import ArmConfig, ArmedPlan, PlanRunner, Trade
from zargar.tools.em_source_candidates import VERSION, evaluate_candidate

ET = dt.timezone(dt.timedelta(hours=-4))
NOW = 1_800_000_000_000


def runner(quotes, settings=None):
    engine = SimpleNamespace(settings=settings or {}, quotes=quotes, journal=SimpleNamespace(append=AsyncMock()),
                             positions=SimpleNamespace(equity=AsyncMock(return_value=10000.0)), options=None)
    r = PlanRunner(engine)
    r._log, r._publish, r._persist, r._alert = Mock(), Mock(), AsyncMock(), AsyncMock()
    r._exit = AsyncMock()
    return r


class Quotes(dict):
    def get(self, k, default=None):
        return dict.get(self, k, default)


def plan(**cfg):
    return ArmedPlan(run_id="shadow-run", symbol="X", plan={"builtFromSession": "2026-09-14"}, plan_for="2026-09-15",
                     config=ArmConfig(portfolio_id="p", mode="auto", single_contract_exit="tp2", **cfg), trackers={}, armed_at=0)


def trade(**kw):
    base = dict(trigger_id="b1", kind="bounce", direction="long", fired_ts=1, window="prime_open", entry=100.0, stop=99.0,
                targets=[101.0, 102.0, 103.0], instrument="options", multiplier=100.0, status="open", remaining=2.0,
                filled_qty=2.0, avg_fill=1.0, order_symbol="X260918C00101000")
    return Trade(**{**base, **kw})


def test_shadow_records_once_per_rung_with_the_contract_nbbo_and_never_orders():
    q = Quotes({"X": Quote("X", bid=101.99, ask=102.01, last=102.0, ts=NOW, source="", source_ts=NOW),
                "X260918C00101000": Quote("X260918C00101000", bid=1.9, ask=2.0, last=1.95, bid_size=40, ask_size=30, ts=NOW, source="opra", source_ts=NOW)})
    r = runner(q)
    ap = plan(); tr = trade(); ap.trades["b1"] = tr; r._armed["shadow-run"] = ap
    import time as _t
    _t_now = _t.time
    r.engine.settings = {}
    async def run_pass():
        await r._shadow_target_pass(ap, [tr], q["X"], NOW, 0.25)
        await r._shadow_target_pass(ap, [tr], q["X"], NOW + 500, 0.25)     # the same print again: not a new observation
    asyncio.run(run_pass())
    calls = [c for c in r.engine.journal.append.await_args_list if c.args[0] == "TechniqueExitShadow"]
    assert len(calls) == 1, "one record per trade per rung"
    p = calls[0].args[1]
    assert p["rung"] == "tp2-full" and p["target"] == 102.0 and p["disposition"] == "observed" and p["version"] == "shadow-exit-v1"
    assert p["contract"]["bid"] == 1.9 and p["contract"]["bidSize"] == 40 and p["contract"]["source"] == "opra"
    assert p["modeled"]["scorable"] is True and p["modeled"]["coveredQty"] == 2.0 and p["modeled"]["unresolvedQty"] == 0.0
    assert r._exit.await_count == 0, "observation only: no exit was sent"


def test_shadow_ignores_stale_or_delayed_observations_and_marks_unscorable_contract_quotes():
    stale = Quotes({"X": Quote("X", bid=101.99, ask=102.01, last=102.0, ts=NOW, source="", source_ts=NOW - 30_000)})
    r = runner(stale); ap = plan(); tr = trade(); ap.trades["b1"] = tr
    asyncio.run(r._shadow_target_pass(ap, [tr], stale["X"], NOW, 0.25))
    assert r.engine.journal.append.await_count == 0, "a 30 s old observation is not fresh"
    # fresh underlying, but the contract has only a delayed chain row: recorded as unscorable with the remainder unresolved
    q = Quotes({"X": Quote("X", bid=101.99, ask=102.01, last=102.0, ts=NOW, source="", source_ts=NOW),
                "X260918C00101000": Quote("X260918C00101000", bid=1.9, ask=2.0, last=1.95, ts=NOW, source="chain", source_ts=NOW - 900_000)})
    r = runner(q); ap = plan(); tr = trade(); ap.trades["b1"] = tr
    asyncio.run(r._shadow_target_pass(ap, [tr], q["X"], NOW, 0.25))
    p = r.engine.journal.append.await_args.args[1]
    assert p["modeled"]["scorable"] is False and p["modeled"]["unresolvedQty"] == 2.0 and p["contract"]["delayed"] is True


def test_shadow_stop_first_when_the_same_observation_breaches_the_stop_and_ladder_rung_for_three_plus():
    # a short whose observation is through BOTH the stop side... use a long with a partial: 3 contracts -> ladder rung tp1
    q = Quotes({"X": Quote("X", bid=100.99, ask=101.01, last=101.0, ts=NOW, source="", source_ts=NOW),
                "X260918C00101000": Quote("X260918C00101000", bid=1.5, ask=1.6, last=1.55, bid_size=1, ask_size=5, ts=NOW, source="opra", source_ts=NOW)})
    r = runner(q); ap = plan(); tr = trade(remaining=3.0, filled_qty=3.0); ap.trades["b1"] = tr
    asyncio.run(r._shadow_target_pass(ap, [tr], q["X"], NOW, 0.25))
    p = r.engine.journal.append.await_args.args[1]
    assert p["rung"] == "tp1-ladder" and p["target"] == 101.0
    assert p["quantities"]["proposedExit"] == 1.0, "the production TP1 trim of a 3-contract ladder is round(3 x 0.30) = 1"
    assert p["modeled"]["coveredQty"] == 1.0 and p["modeled"]["unresolvedQty"] == 0.0, "displayed size 1 covers the proposed trim"
    # a bigger trim than the displayed size leaves the remainder unresolved
    q2 = Quotes({"X": q["X"], "X260918C00101000": Quote("X260918C00101000", bid=1.5, ask=1.6, last=1.55, bid_size=2, ask_size=5, ts=NOW, source="opra", source_ts=NOW)})
    r2 = runner(q2); ap2 = plan(); tr2 = trade(remaining=10.0, filled_qty=10.0); ap2.trades["b1"] = tr2
    asyncio.run(r2._shadow_target_pass(ap2, [tr2], q2["X"], NOW, 0.25))
    p2 = r2.engine.journal.append.await_args.args[1]
    assert p2["quantities"]["proposedExit"] == 3.0 and p2["modeled"]["coveredQty"] == 2.0 and p2["modeled"]["unresolvedQty"] == 1.0
    # a pending exit on the same rung is recorded as such
    r = runner(q); ap = plan(); tr = trade(remaining=3.0, filled_qty=3.0, exits=[{"orderId": "e", "kind": "tp1", "qty": 1, "filledQty": 0, "status": "SUBMITTED"}])
    ap.trades["b1"] = tr
    asyncio.run(r._shadow_target_pass(ap, [tr], q["X"], NOW, 0.25))
    assert r.engine.journal.append.await_args.args[1]["disposition"] == "pending_exit"


def test_target_distance_is_a_diagnostic_at_fire_and_fill():
    r = runner(Quotes()); ap = plan()
    d = r._target_distance(ap, trade(), stage="fire", qty=None)
    assert d["quantityKnown"] is False and d["underlyingObservedEntry"] is None and d["optionPremiumFill"] is None
    assert d["nextRung"] == "tp1-ladder" and d["nextRungDistanceR"] == 1.0 and d["fullExitRung"] == "tp3-runner" and d["distanceR"] == 3.0
    d2 = r._target_distance(ap, trade(), stage="fill", qty=2.0)
    assert d2["nextRung"] == "tp2-full" and d2["fullExitRung"] == "tp2-full" and d2["distanceR"] == 2.0 and d2["quantityKnown"] is True
    assert d2["optionPremiumFill"] == 1.0 and d2["underlyingIntended"]["entry"] == 100.0 and d2["version"] == "target-distance-v1"
    sh = r._target_distance(ap, trade(instrument="shares", remaining=100, filled_qty=100), stage="fill", qty=100)
    assert sh["nextRung"] == "tp1-ladder" and sh["nextRungDistanceR"] == 1.0 and sh["optionPremiumFill"] is None


# ----------------------------------------------------------------- source-continuation-v1 on synthetic bars
def _bars(closes, day="2026-09-15", start=(9, 30), spread=0.3):
    out = []
    d = dt.date.fromisoformat(day)
    t0 = dt.datetime(d.year, d.month, d.day, start[0], start[1], tzinfo=ET)
    for i, c in enumerate(closes):
        ts = int((t0 + dt.timedelta(minutes=i)).timestamp() * 1000)
        o = closes[i - 1] if i else c
        out.append({"ts": ts, "open": o, "high": max(o, c) + spread, "low": min(o, c) - spread, "close": c})
    return out


ROW = {"date": "2026-09-15", "symbol": "T", "direction": "long", "level": 100.0, "target": 106.0,
       "availableAt": "2026-09-15T09:20:00-04:00"}


def test_candidate_no_bars_is_unknown_and_early_cross_never_enters():
    assert evaluate_candidate([], ROW)["outcome"] == "unknown"
    # the level is crossed at 09:31 (before the opening range is complete) and never closed above afterwards
    bars = _bars([99.0, 100.4, 99.2, 99.0, 98.8] + [99.0] * 130)
    res = evaluate_candidate(bars, ROW)
    assert res["observations"][0]["event"] == "early_cross" and res["outcome"] == "never_confirmed"
    assert res["stop"] == min(b["low"] for b in bars[:5]) and res["version"] == VERSION


def test_candidate_confirmed_close_gated_by_rr_but_path_still_recorded():
    # opening range 98.7..99.3 (stop ~98.7); confirmed close 100.5 at 09:40 -> next open 100.5; risk ~1.8; target 106 = 3.05R -> passes
    closes = [99.0, 99.1, 99.2, 99.0, 99.1, 99.5, 99.6, 99.8, 99.9, 99.95, 100.5] + [101.0, 102.0, 103.0, 104.0, 105.0, 106.5] + [104.0] * 60
    res = evaluate_candidate(_bars(closes), ROW)
    assert res["entry"]["basis"] == "next-open-proxy" and res["outcome"] == "target" and res["path"]["end"] == "target"
    # a nearer target fails the 3R gate: gated, with the path kept for the record
    res2 = evaluate_candidate(_bars(closes), {**ROW, "target": 103.0})
    assert res2["outcome"] == "gated" and res2["path"]["end"] == "target" and res2["rewardToRisk"] < 3


def test_candidate_no_chase_waits_for_one_retest_then_stop_and_flatten_paths():
    # confirming close far above the level: next open beyond the cap -> wait for a retest, then re-enter on the next confirming close
    closes = [99.0, 99.1, 99.2, 99.0, 99.1, 101.5, 101.6, 100.05, 100.4] + [100.6] * 20 + [98.0] + [97.9] * 30
    res = evaluate_candidate(_bars(closes), ROW)
    events = [o["event"] for o in res["observations"]]
    assert "no_chase_wait_retest" in events and "retest" in events
    assert res["outcome"] in ("gated", "stopped") and res["path"]["end"] == "stopped"
    # flattened at the baseline clock when nothing terminal happens
    closes = [99.0, 99.1, 99.2, 99.0, 99.1, 100.3] + [100.4] * 400
    res = evaluate_candidate(_bars(closes), {**ROW, "target": 150.0})
    assert res["path"]["end"] == "flattened" and res["path"]["at"] == "15:55"


def test_target_distance_diagnostic_is_scoped_to_the_technique_knob():
    """Tips desk request 2026-09-15: another desk's aggregates carry no EM research record. The runtime resolves
    `techniques.<id>.target_distance_diagnostic` -> `execution.target_distance_diagnostic` (False); EM's is True."""
    from zargar.settings_service import DEFAULTS
    assert DEFAULTS["execution.target_distance_diagnostic"] is False
    assert DEFAULTS["techniques.enhanced_market.target_distance_diagnostic"] is True
    r = runner(Quotes())
    assert r._target_distance_enabled() is True                      # bare rig: code default
    r.rt = lambda key, default=None: False if key == "target_distance_diagnostic" else default
    assert r._target_distance_enabled() is False

