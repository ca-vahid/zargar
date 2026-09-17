"""2026-09-17 EOD review item 4 (shadow only): target/stop room from the actual underlying quote, Greeks with provenance, a
labelled payoff estimate after commissions and spread, coverage reported separately for attempts / Greeks / follow-ups,
and gross vs net outcomes side by side. Nothing here filters an order; the risk counter's basis is unchanged."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

from zargar.execution.planrunner import Trade
from zargar.marketstructure.sessions import ET
from zargar.techniques.team2 import diagnostics as diag
from zargar.techniques.team2.runner import Team2Runner

from .test_team2_diagnostics import FakeOpts, chain, drain, fire_event, ms, read, rig


def test_target_room_and_payoff_estimate_are_labelled_and_stay_unknown_without_inputs():
    loc = {"direction": "long", "atr": 0.3145}
    room = diag.target_room(loc, 716.73, 716.76, 716.40, 716.76)
    assert room["targetRoomPoints"] == 0.03 and room["targetRoomAtr"] == 0.095 and room["stopRoomPoints"] == 0.33
    assert room["targetIsSourceLevel"] is True and room["targetToAnchorPoints"] == 0.0
    assert diag.target_room(loc, None, 716.76, 716.40, 716.0)["targetRoomPoints"] is None
    short = diag.target_room({"direction": "short", "atr": 0.5}, 100.0, 99.0, 100.6, 100.2)
    assert short["targetRoomPoints"] == 1.0 and short["stopRoomPoints"] == 0.6 and short["targetIsSourceLevel"] is False
    # the QQQ 717C: ask 0.69, bid 0.68, delta 0.461, 0.03 of room — the estimate cannot pay the commissions
    est = diag.payoff_estimate(0.69, 0.68, 0.461, 0.05, 0.03, 1.04)
    assert est["status"] == "estimate" and est["spreadAssumed"] == 0.01 and est["netPerContract"] < 0
    assert est["breakEvenMovePoints"] == round((2.08 / 100 + 0.01) / 0.461, 4) and "never an executable price" in est["assumptions"]
    big = diag.payoff_estimate(0.69, 0.68, 0.461, 0.05, 2.0, 1.04)
    assert big["netPerContract"] > 0 and big["estExitBid"] > 0.69
    # missing inputs: insufficient evidence, never a number
    assert diag.payoff_estimate(0.69, 0.68, None, None, 0.5, 1.04) == {"status": "insufficient evidence", "missing": ["delta"], "greeksSource": None}
    assert diag.payoff_estimate(0.69, 0.68, 0.4, None, None, 1.04)["missing"] == ["target room"]
    assert diag.payoff_estimate(0.0, None, 0.4, None, 0.5, 1.04)["missing"] == ["entry ask", "bid"]
    # PR204 review: a missing, zero or crossed bid is NOT a zero spread — insufficient evidence, never an optimistic number
    for bad in (None, 0.0, 0.8):
        r = diag.payoff_estimate(0.69, bad, 0.461, 0.05, 0.5, 1.04)
        assert r["status"] == "insufficient evidence" and ("bid" in r["missing"] or "valid spread (bid above ask)" in r["missing"])


async def test_submission_records_room_greeks_provenance_and_payoff(monkeypatch):
    opts = FakeOpts(chain(), {"SPY260914C00101000": (0.80, 0.82), "SPY260914C00102000": (0.44, 0.46)})
    runner, ap = rig(opts, quote_last=100.6)
    runner._fire_rest = AsyncMock()
    res = read()
    await runner._fire_from_event(ap, res.events[0], SimpleNamespace(close=100.95, ts=ms(9, 59)), res, halted=False, journal=True)
    tid = "scenario_1@09:45#1"
    trade = ap.trades[tid]
    assert getattr(trade, "_anchor", None) == 100.5
    rules = runner.rules_for(ap)
    otm = sorted([c for c in chain() if c["strike"] > 100.4], key=lambda c: c["strike"])
    qres = await runner._quote_examined(opts, otm, 100.4, "long", rules, "2026-09-14", dt.date(2026, 9, 14))
    runner._diag_candidates(ap, tid, qres, qres["pick"].symbol, 100.4, rules, chain(), opts)
    rec = runner._diag_of(ap.run_id)["attempts"][tid]
    sel = next(c for c in rec["candidates"] if c["selected"])
    assert sel["delta"] == 0.24 and sel["greeksSource"] == "chain" and sel["greeksProvider"] == "fake"
    await runner.entry_gate(ap, trade, "order")
    loc = rec["entryLocation"]
    assert loc["underlyingAtBoundary"] == 100.6 and loc["targetRoomPoints"] == 2.4 and loc["stopRoomPoints"] == 0.2
    assert loc["targetIsSourceLevel"] is False and loc["targetToAnchorPoints"] == 2.5
    est = loc["payoffEstimate"]
    assert est["status"] == "estimate" and est["deltaUsed"] == 0.24 and est["greeksSource"] == "chain" and est["netPerContract"] > 0
    await drain(runner)
    emitted = [c.args[1] for c in runner.engine.journal.append.await_args_list if c.args[0] == "TechniquePlanDiagnostic" and c.args[1]["kind"] == "entry_submission"]
    assert emitted and emitted[0]["payoffEstimate"]["status"] == "estimate"


def test_gross_and_net_are_reported_apart_and_coverage_is_split():
    fees = 33.28
    t = SimpleNamespace(status="closed", filled_qty=16, avg_fill=.69, order_symbol="OPT", realized_pnl=0.0, opened_ts=1, closed_ts=2,
                        exits=[{"orderId": "x", "status": "SUBMITTED", "filledQty": 16, "qty": 16, "price": .69}])
    r = Team2Runner._diag_routing(t, fees)
    assert r["grossPnl"] == 0.0 and r["fees"] == 33.28 and r["netPnl"] == -33.28 and r["grossBreakevenNetLoss"] is True
    attempts = [
        {"trigger": "a#1", "setup": "a", "candidates": [], "observations": {}, "routing": {}, "refusal": "contract_deferred (CBOE HTTP 429)"},
        {"trigger": "a#2", "setup": "a", "candidates": [{"symbol": "S", "selected": True, "inBand": True, "ask": .69, "mid": .685, "delta": .461, "greeksSource": "chain", "priceKnown": True},
                                                        {"symbol": "T", "selected": False, "inBand": True, "ask": .33, "mid": .325, "delta": None, "greeksSource": "none", "priceKnown": True}],
         "observations": {"2m": {"status": "observed", "quotes": {"S": {"bid": .63, "mid": .635}, "T": None}, "unknown": {"T": "no quote"}}},
         "routing": r, "entryLocation": {"targetRoomAtr": 0.095, "targetIsSourceLevel": True, "payoffEstimate": {"status": "estimate", "netPerContract": -1.9}}},
    ]
    day = diag.summarize_day(attempts, 1.04)
    cov = day["coverageDetail"]
    assert cov["attempts"] == {"total": 2, "withCandidates": 1, "withoutCandidates": [{"trigger": "a#1", "reason": "contract_deferred (CBOE HTTP 429)"}]}
    assert cov["greeks"] == {"candidates": 2, "withDelta": 1, "bySource": {"chain": 1, "none": 1}}
    assert cov["followUps"]["observed"] == 1 and cov["followUps"]["missing"] >= 1
    assert day["actualOutcomes"]["grossSum"] == 0.0 and day["actualOutcomes"]["netSum"] == -33.28 and day["actualOutcomes"]["grossBreakevenNetLoss"] == 1
    per = day["perAttempt"][1]
    assert per["targetIsSourceLevel"] is True and per["payoffEstimate"]["netPerContract"] == -1.9 and per["actual"]["grossBreakevenNetLoss"] is True
