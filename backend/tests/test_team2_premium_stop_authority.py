"""F129 — a pricing model never independently sells the desk's contract.

2026-09-21, Team2 C1 Conjunction: the desk bought 35 IWM 286 calls at $0.33 at 10:36:13 ET and was
market-sold at $0.2899 at 10:40:03 for −$140.35 gross, −$213.15 after fees. The exit journal said
"premium stop: -32% ≤ −25% (P1/D13)". That −32% was the MODEL's: its proxy contract was marked
$0.1794 at entry and $0.1391 at the exit (a `model_out_of_band` read at 10:36:00 says the modelled
pick was outside the premium band while the live picker still filled). The contract the desk held
had moved 0.33 → 0.2899: about −12%, inside the configured −25% stop. `_exit_from_event` checked
the contract's live premium before a modelled trim, but not before a modelled premium stop.

These are the acceptance cases for the fix. They are written against the runner as it runs, with a
real engine and real quotes; the exits are captured rather than routed.
"""
from __future__ import annotations

import pytest

from zargar.domain import Quote
from zargar.execution.planrunner import Trade
from zargar.marketdata import persist_bars
from zargar.marketstructure import filter_session

from .test_team2_runner import rig  # noqa: F401 - the engine fixture
from .test_team2_session import DAY, prev_day_bars, trend_day

SYM = "SPY260904C00573000"
# the incident's own numbers, on the contract the desk actually held
PAID, EXIT_BID, EXIT_ASK = 0.33, 0.2899, 0.30
MODEL_STOP = {"event": "exit", "why": "premium stop: -32% ≤ −25% (P1/D13)", "fraction": 1.0,
              "pnlPct": -32.0, "premium": 0.1391, "avgPremium": 0.1794, "ts": 2}
CANDLE_STOP = {"event": "exit", "why": "2m close 571.00 through the EMA13 571.20 (S1 one-candle stop)",
               "fraction": 1.0, "pnlPct": -32.0, "ts": 3}


async def desk(rig, monkeypatch, *, qty: float = 35.0, paid: float = PAID):
    """An armed Team2 plan holding one real option position, with `_exit` captured."""
    eng, _sim = rig
    prev = prev_day_bars()
    today, _ = trend_day(prev)
    await persist_bars(eng.sf, prev)
    await persist_bars(eng.sf, filter_session(today, "pre"))
    out = await eng.team2.nightly_plans(DAY.isoformat(), arm=True)
    run_id = out["armed"][0]
    runner = eng.team2_runner
    ap = runner.get(run_id)
    calls: list[dict] = []

    async def fake_exit(ap_, tr, kind, qty_, *, journal, force_market=False, reason="", authority=None):
        calls.append({"kind": kind, "qty": qty_, "reason": reason, "authority": authority,
                      "forceMarket": force_market})
        tr.remaining -= qty_
        tr.exits.append({"kind": kind, "qty": qty_, "status": "FILLED", "filledQty": qty_})

    monkeypatch.setattr(runner, "_exit", fake_exit)
    tr = Trade(trigger_id="scenario_1@09:30#1", kind="scenario_1", fired_ts=1, window="team2", entry=570.0,
               stop=569.0, targets=[575.0], status="open", setup_id="scenario_1@09:30", filled_qty=qty,
               remaining=qty, avg_fill=paid, instrument="options", order_symbol=SYM, multiplier=100.0)
    tr.contract = {"symbol": SYM, "bid": 0.30, "ask": 0.33, "_sizeMult": 1.0, "_bucket": "small"}
    tr.contract_attempted = True
    ap.trades[tr.trigger_id] = tr
    runner._last_sim[run_id] = {"openPosition": {"setup": tr.setup_id}}
    return eng, runner, ap, tr, calls, run_id


def quote(eng, bid, ask, *, symbol=SYM):
    eng.quotes.on_quote(Quote(symbol=symbol, bid=bid, ask=ask, last=(bid + ask) / 2))


# ------------------------------------------------------------------ (a) the incident itself
async def test_a_model_premium_stop_alone_never_sells_the_contract(rig, monkeypatch):
    """The model's proxy breached its stop; the held contract did not. Nothing is sold."""
    eng, runner, ap, tr, calls, _ = await desk(rig, monkeypatch)
    quote(eng, EXIT_BID, EXIT_ASK)                      # 0.2899/0.30 against 0.33 paid: about −12%
    await runner._exit_from_event(ap, MODEL_STOP, journal=True)
    assert calls == [], "a modelled premium stop must not force the sale"
    assert tr.remaining == 35 and tr.status == "open"
    note = next(e for e in ap.events if e["event"] == "premium_stop_not_live")
    a = note["authority"]
    assert a["confirmed"] is False and a["decidedBy"] == "held_contract"
    assert a["fillBasis"] == pytest.approx(PAID)        # the fill the desk actually paid
    assert a["thresholdPct"] == pytest.approx(25.0)     # the configured stop, unchanged
    assert a["quote"]["usable"] is True and a["quote"]["basis"] == "mid"
    assert a["quote"]["sourceTs"] and a["livePrice"] == pytest.approx((EXIT_BID + EXIT_ASK) / 2)
    assert a["returnPct"] == pytest.approx(-11.0, abs=1.0)
    assert a["model"]["pnlPct"] == -32.0 and a["model"]["avgPremium"] == 0.1794   # diagnostics, kept apart


# ------------------------------------------------------------------ (b) protection still acts
async def test_b_the_held_contract_breaching_the_stop_still_exits(rig, monkeypatch):
    """The model is happy; the contract has bled past the configured stop. The desk still sells."""
    eng, runner, ap, tr, calls, _ = await desk(rig, monkeypatch)
    quote(eng, 0.20, 0.21)                              # mid 0.205 vs 0.33 paid: −38%, past −25%
    await runner._exit_from_event(ap, {**MODEL_STOP, "pnlPct": -4.0}, journal=True)
    assert len(calls) == 1 and calls[0]["kind"] == "stop" and calls[0]["qty"] == 35
    assert calls[0]["forceMarket"] is True
    a = calls[0]["authority"]
    assert a["confirmed"] is True and a["decidedBy"] == "held_contract"
    assert "premium stop" in calls[0]["reason"] and "0.33 paid" in calls[0]["reason"]
    assert a["fillBasis"] == pytest.approx(PAID) and a["thresholdPct"] == pytest.approx(25.0)
    assert a["returnPct"] == pytest.approx(-37.9, abs=0.5) and a["quote"]["sourceTs"]


async def test_b2_the_live_quote_watch_premium_stop_is_untouched(rig, monkeypatch):
    """The 2 s protective watch is the premium stop's home; it keeps its own authority and its
    forward-confirmation rule."""
    import time as _time
    eng, runner, ap, tr, calls, _ = await desk(rig, monkeypatch)
    eng.quotes.on_quote(Quote(symbol=ap.symbol, bid=569.9, ask=570.1, last=570.0))
    base = int(_time.time() * 1000)
    for n in range(3):                                  # `quote_exit_polls` DISTINCT observations
        eng.quotes.on_quote(Quote(symbol=SYM, bid=0.20, ask=0.21, last=0.205,
                                  ts=base + n, source="opra", source_ts=base + n))
        await runner.on_quote_watch()
    assert calls and calls[-1]["kind"] == "stop"
    a = calls[-1]["authority"]
    assert a["decidedBy"] == "live_quote_watch" and a["confirmed"] is True
    assert a["fillBasis"] == pytest.approx(PAID) and a["quote"]["usable"] is True


# ------------------------------------------------------------------ (c) the structural stop
async def test_c_the_structural_candle_stop_still_fires_and_is_attributed(rig, monkeypatch):
    """The S1 candle stop reads the underlying, which the model and the desk share. It is allowed,
    and the journal says which authority took the position out."""
    eng, runner, ap, tr, calls, _ = await desk(rig, monkeypatch)
    quote(eng, EXIT_BID, EXIT_ASK)                      # the premium is NOT through the stop
    await runner._exit_from_event(ap, CANDLE_STOP, journal=True)
    assert len(calls) == 1 and calls[0]["kind"] == "stop" and calls[0]["qty"] == 35
    assert "one-candle stop" in calls[0]["reason"]
    assert calls[0]["authority"]["decidedBy"] == "model_structural"
    assert not any(e["event"] == "premium_stop_not_live" for e in ap.events)


async def test_c2_the_model_closing_its_proxy_leaves_present_time_structure_in_charge(rig, monkeypatch):
    """After a deferred premium stop the model holds nothing while the desk still does. The G guard
    judges S1 on the CURRENT close and issues the stop now — protection, occupancy and the position
    all survive the disagreement."""
    from types import SimpleNamespace

    from zargar.domain import Bar
    eng, runner, ap, tr, calls, run_id = await desk(rig, monkeypatch)
    quote(eng, EXIT_BID, EXIT_ASK)
    await runner._exit_from_event(ap, MODEL_STOP, journal=True)
    assert calls == [] and tr.remaining == 35
    res = SimpleNamespace(open_position=None, regime_last={"ema13": 571.20}, setups=[])
    bar = Bar(symbol=ap.symbol, tf="1m", ts=1, open=571.3, high=571.4, low=570.9, close=571.00, volume=1)
    await runner._guard_orphaned_positions(ap, res, bar, journal=True)
    assert len(calls) == 1 and calls[0]["kind"] == "stop"
    assert calls[0]["authority"]["decidedBy"] == "present_time_structural"
    assert calls[0]["authority"]["line"] == "EMA13"


# ------------------------------------------------------------------ (d) missing and stale quotes
@pytest.mark.parametrize("case", ["missing", "stale", "delayed"])
async def test_d_no_valid_quote_means_no_model_priced_sale(rig, monkeypatch, case):
    """The existing quote-validity policy decides, and a model price is never substituted for a
    quote the desk does not have."""
    import time as _time
    eng, runner, ap, tr, calls, _ = await desk(rig, monkeypatch)
    if case == "stale":
        old = int(_time.time() * 1000) - 10 * 60 * 1000
        eng.quotes.on_quote(Quote(symbol=SYM, bid=EXIT_BID, ask=EXIT_ASK, last=EXIT_BID, ts=old))
    elif case == "delayed":
        eng.quotes.on_quote(Quote(symbol=SYM, bid=0.01, ask=0.02, last=0.01, source="chain"))
    await runner._exit_from_event(ap, MODEL_STOP, journal=True)
    assert calls == [] and tr.remaining == 35
    a = next(e for e in ap.events if e["event"] == "premium_stop_not_live")["authority"]
    assert a["confirmed"] is False and a["quote"]["usable"] is False and a["livePrice"] is None
    assert a["model"]["premium"] == 0.1391                     # the model's price is recorded, not used


async def test_d2_a_fresh_real_time_quote_with_no_bid_is_a_total_bleed(rig, monkeypatch):
    """Unchanged policy: nobody paying anything IS the worst bleed, not a data gap."""
    eng, runner, ap, tr, calls, _ = await desk(rig, monkeypatch)
    eng.quotes.on_quote(Quote(symbol=SYM, bid=0.0, ask=0.0, last=0.0))
    await runner._exit_from_event(ap, MODEL_STOP, journal=True)
    assert len(calls) == 1 and calls[0]["kind"] == "stop"
    assert calls[0]["authority"]["confirmed"] is True


# ------------------------------------------------------------------ (e) restart
async def test_e_the_disagreement_survives_a_restart_with_protection_intact(rig, monkeypatch):
    """The book is durable; the model's proxy is not. After a restore the position is still held,
    still protected, and a repeat of the same modelled stop still cannot sell it."""
    eng, runner, ap, tr, calls, run_id = await desk(rig, monkeypatch)
    quote(eng, EXIT_BID, EXIT_ASK)
    await runner._exit_from_event(ap, MODEL_STOP, journal=True)
    assert calls == []
    await runner._persist(ap)
    # the restart: the in-memory plan is gone and everything the desk knows comes back off the
    # persisted row, exactly as `restore()` re-arms it after a boot
    from zargar.execution.planrunner import ArmConfig
    from zargar.models import TechniqueArmed
    async with eng.sf() as session:
        row = await session.get(TechniqueArmed, run_id)
        cfg, state = dict(row.config or {}), dict(row.state or {})
    runner._armed.pop(run_id, None)
    assert runner.get(run_id) is None
    await runner.arm(run_id, ArmConfig.from_dict(cfg), restored=True, prior_state=state)
    ap2 = runner.get(run_id)
    tr2 = ap2.trades[tr.trigger_id]
    assert tr2.status == "open" and tr2.remaining == 35 and tr2.avg_fill == pytest.approx(PAID)
    calls2: list[dict] = []

    async def fake_exit(ap_, t, kind, qty_, *, journal, force_market=False, reason="", authority=None):
        calls2.append({"kind": kind, "qty": qty_, "authority": authority})
        t.remaining -= qty_

    monkeypatch.setattr(runner, "_exit", fake_exit)
    runner._last_sim[run_id] = {"openPosition": {"setup": tr.setup_id}}
    quote(eng, EXIT_BID, EXIT_ASK)
    await runner._exit_from_event(ap2, {**MODEL_STOP, "ts": 9}, journal=True)
    assert calls2 == []                                    # still the model's number, still not ours
    quote(eng, 0.20, 0.21)                                 # the contract really bleeds: protection acts
    await runner._exit_from_event(ap2, {**MODEL_STOP, "ts": 10}, journal=True)
    assert len(calls2) == 1 and calls2[0]["kind"] == "stop"
    assert calls2[0]["authority"]["decidedBy"] == "held_contract"


# ------------------------------------------------------------------ (f) partials, trims/adds, duplicates
async def test_f_partial_fills_and_trims_keep_the_quantity_and_the_cost_basis(rig, monkeypatch):
    """A partially filled, partly trimmed position is judged on what it actually paid for what it
    actually still holds — and a repeated model event never sells twice."""
    eng, runner, ap, tr, calls, _ = await desk(rig, monkeypatch, qty=20.0, paid=0.40)
    tr.remaining = 12.0                                   # 8 sold on the live first trim
    tr.trims_done = 1
    quote(eng, 0.33, 0.35)                                # mid 0.34 vs 0.40 paid: −15%, inside −25%
    await runner._exit_from_event(ap, MODEL_STOP, journal=True)
    assert calls == [] and tr.remaining == 12
    a = next(e for e in ap.events if e["event"] == "premium_stop_not_live")["authority"]
    assert a["fillBasis"] == pytest.approx(0.40)          # the cost basis, not the trimmed proceeds
    quote(eng, 0.25, 0.26)                                # mid 0.255 vs 0.40: −36%, past the stop
    await runner._exit_from_event(ap, {**MODEL_STOP, "ts": 5}, journal=True)
    assert len(calls) == 1 and calls[0]["qty"] == 12      # the REMAINING quantity, not the original
    await runner._exit_from_event(ap, {**MODEL_STOP, "ts": 6}, journal=True)
    assert len(calls) == 1, "a duplicate model event must not sell an already-closed position"


async def test_f2_an_add_never_re_fills_room_the_desk_did_not_free(rig, monkeypatch):
    """X5 is trim-and-add. When the live trim was deferred the book is still whole, so the model's
    re-up would add size the method never describes."""
    from zargar.domain import Bar
    eng, runner, ap, tr, calls, _ = await desk(rig, monkeypatch, qty=9.0, paid=0.40)
    ap.config.mode = "auto"
    bar = Bar(symbol=ap.symbol, tf="1m", ts=1, open=570.0, high=570.5, low=569.8, close=570.2, volume=1)
    add = {"event": "add", "why": "re-up on the EMA13 hold (X5)", "fraction": 1 / 3, "adds": 1,
           "setup": tr.setup_id, "ts": 4, "spot": 570.2}
    await runner._add_from_event(ap, add, bar, halted=False, journal=True)
    assert f"{tr.trigger_id}+add1" not in ap.trades
    assert any(e["event"] == "add_no_room" for e in ap.events)


# ------------------------------------------------------------------ (g) nothing else moved
async def test_g_targets_flatten_and_trims_are_unchanged(rig, monkeypatch):
    """The target, the flatten and the live trim deferral keep working exactly as before, and each
    exit now says which authority produced it."""
    eng, runner, ap, tr, calls, _ = await desk(rig, monkeypatch, qty=6.0, paid=0.50)
    quote(eng, 0.55, 0.57)                                # +10% live: below the +50% first trim
    await runner._exit_from_event(ap, {"event": "trim", "why": "+53% ≥ +50% — first trim (V2)",
                                       "fraction": 1 / 3, "pnlPct": 53.0, "ts": 2}, journal=True)
    assert calls == [] and any(e["event"] == "trim_deferred_live" for e in ap.events)
    await runner._exit_from_event(ap, {"event": "exit", "why": "target 575.00 (planned level) touched — "
                                       "sell at target (X3/V11)", "fraction": 1.0, "pnlPct": 60.0, "ts": 3},
                                  journal=True)
    assert calls[-1]["kind"] == "tp3" and calls[-1]["authority"]["decidedBy"] == "model_tp3"
    assert calls[-1]["forceMarket"] is False
    tr.remaining = 6.0
    await runner._exit_from_event(ap, {"event": "exit", "why": "flatten: 0DTE flatten time reached (C3/D-1)",
                                       "fraction": 1.0, "ts": 4}, journal=True)
    assert calls[-1]["kind"] == "flatten" and calls[-1]["authority"]["decidedBy"] == "model_flatten"
    assert calls[-1]["forceMarket"] is True
