"""Team2 profitability diagnostics (2026-09-16, review team GO): SHADOW measurements and the repaired close report.

Pure helpers on synthetic records, then the runner wired with an in-memory engine (no DB, no network, no orders):
the ledger survives the display buffer and a restart, entry location / attempt context / contract candidates are
recorded at the fire and the pick, follow-up quotes are taken at their horizons with missing observations kept
UNKNOWN, a candidate refused before the picker is quoted in the shadow, and no order decision changes.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from zargar.domain import Bar
from zargar.execution.planrunner import ArmConfig, ArmedPlan, PlanRunner, Trade
from zargar.marketstructure.sessions import ET
from zargar.techniques.team2 import diagnostics as diag
from zargar.techniques.team2.rules import Team2Rules
from zargar.techniques.team2.runner import Team2Runner
from zargar.tools.team2_diag_report import assemble

DAY = "2026-09-14"


def ms(h, m, s=0):
    return int(dt.datetime(2026, 9, 14, h, m, s, tzinfo=ET).timestamp() * 1000)


def bar(h, m, close=100.0, high=None, low=None, symbol="SPY"):
    return Bar(symbol=symbol, tf="1m", ts=ms(h, 0) + m * 60_000, open=close, high=high if high is not None else close + .1,
               low=low if low is not None else close - .1, close=close, volume=100, source="exchange")


def now_ms():
    return int(time.time() * 1000)


class FakeOpts:
    """The options service surface the diagnostics touch: chain rows, live re-pricing, cached Greeks. Every live quote
    carries a SOURCE timestamp (fresh unless `stale_ms` says otherwise) — the diagnostics refuse quotes without one."""

    def __init__(self, chain, live):
        self.chain_rows, self.live, self.calls = chain, dict(live), []
        self.stale_ms = 0

    def quote(self, sym):
        if sym not in self.live:
            return None
        bid, ask = self.live[sym]
        return SimpleNamespace(bid=bid, ask=ask, last=(bid + ask) / 2, ts=now_ms() - self.stale_ms)

    def provider(self):
        return SimpleNamespace(chain=AsyncMock(return_value=self.chain_rows), name="fake")

    async def reprice(self, c):
        sym = c["symbol"]
        self.calls.append(sym)
        if sym in self.live:
            bid, ask = self.live[sym]
            c.update({"bid": bid, "ask": ask, "priced": "opra"})
        else:
            c["priced"] = "chain"
        return c

    def snapshot_cached(self, sym):
        row = next((r for r in self.chain_rows if r["symbol"] == sym), None)
        return dict(row, greeksLive=False) if row else None


def chain(spot=100.0):
    rows = []
    for k in (101, 102, 103, 104):
        rows.append({"symbol": f"SPY260914C{k * 1000:08d}", "strike": float(k), "option_type": "call", "ask": 0.5, "bid": 0.4,
                     "greeks": {"delta": round(0.4 - 0.08 * (k - 100), 3), "theta": -0.1, "mid_iv": 0.3}})
    return rows


def rig(opts=None, quote_last=100.4):
    q = SimpleNamespace(last=quote_last, ts=ms(10, 0), bid=quote_last - .01, ask=quote_last + .01)

    def get_quote(sym):
        if sym == "SPY":
            return q
        return opts.quote(sym) if opts is not None else None
    eng = SimpleNamespace(settings={}, journal=SimpleNamespace(append=AsyncMock()), trading_halted=lambda _: False,
                          quiesce_until_ms=0, quotes=SimpleNamespace(get=get_quote), options=opts)
    runner = Team2Runner(eng)
    runner.rules = lambda: replace(Team2Rules(), losses_desk_wide=False)
    for name in ("_load_warmup", "_ensure_listing", "_persist", "_clock_flatten", "_reprice_stuck_exits", "_manage_live_trims"):
        setattr(runner, name, AsyncMock())
    runner._publish = Mock()
    runner._stale_signal = lambda *a, **k: None
    runner._expiry_for = AsyncMock(return_value=("2026-09-14", None))
    ap = ArmedPlan(run_id="diag-run", symbol="SPY", plan_for=DAY, plan={"zones": {"present": True}, "openSource": "rth_open"},
                   config=ArmConfig(portfolio_id="practice", mode="auto", instrument="options", use_critic=False), trackers={}, armed_at=0)
    runner._armed[ap.run_id] = ap
    runner._bars[ap.run_id] = [bar(9, 30 + i, 100.0 + i * .05) for i in range(30)]       # 09:30..09:59
    return runner, ap


def fire_event(ts, setup="scenario_1@09:45", touch=1, spot=100.9, why="pullback to the EMA13"):
    return {"event": "fire", "ts": ts, "time": "10:00", "setup": setup, "touch": touch, "spot": spot, "target": 103.0, "targetKind": "plan",
            "regime": {"stack": "bull", "atr": 0.5, "ema13": spot}, "entryKind": "ema", "why": why, "sizeMult": 0.5, "bucket": "small"}


def read(setups=None):
    ev = fire_event(ms(10, 0))
    st = setups or [{"id": "scenario_1@09:45", "kind": "scenario_1", "direction": "long", "anchor": 100.5, "target": 103.0,
                     "confirmedTs": ms(9, 45)}]
    return SimpleNamespace(events=[ev], setups=st, to_dict=lambda: {"events": [ev], "setups": st, "summary": {}})


async def drain(runner):
    tasks = list(runner.__dict__.get("_diag_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


# ---------------------------------------------------------------- the ledger (EOD review P2)
def test_ledger_identity_versions_and_aliases():
    led = {}
    a = diag.note_decision(led, {"event": "skip_no_trade_zone", "text": "entry 760.37 inside", "setup": "s@11:00", "touch": 1, "ts": ms(11, 18)})
    b = diag.note_decision(led, {"event": "skip_no_trade_zone", "text": "entry 760.38 inside", "setup": "s@11:00", "touch": 1, "ts": ms(11, 18)})
    assert a is b and a["rows"] == 2 and [v["text"] for v in a["versions"]] == ["entry 760.38 inside"]
    diag.note_decision(led, {"event": "skip_no_trade_zone", "text": "entry 761 inside", "setup": "s@11:00", "touch": 1, "ts": ms(11, 22)})
    assert diag.unique_counts(led) == {"skip_no_trade_zone": 2} and diag.row_counts(led) == {"skip_no_trade_zone": 3}
    # the runner-side refusal keyed on its SOURCE minute; its journal twin under the journal's name merges into it
    diag.note_decision(led, {"event": "max_concurrent_skip", "text": "holds 1", "trigger": "pm@09:30#1", "ts": ms(10, 2, 30), "sourceTs": ms(10, 2)})
    e = diag.note_journal_row(led, {"event": "max_concurrent_positions", "trigger": "pm@09:30#1", "ts": ms(10, 2), "reason": "holds 1"})
    assert e["rows"] == 1 and e["sources"] == ["log", "journal"] and diag.unique_counts(led)["max_concurrent_skip"] == 1
    # a journal-only decision (the log never persisted) is one decision with zero log rows
    j = diag.note_journal_row(led, {"event": "skip_loss_cap_desk", "trigger": "pm@09:30#2", "ts": ms(11, 54), "reason": "two losses"})
    assert j["rows"] == 0 and j["sources"] == ["journal"]
    assert not diag.is_decision("bar_revised") and not diag.is_decision("fired") and diag.is_decision("contract_refused")
    # state round trip
    back = diag.ledger_from_state(json.loads(json.dumps(diag.ledger_state(led))))
    assert diag.unique_counts(back) == diag.unique_counts(led) and diag.row_counts(back) == diag.row_counts(led)
    view = diag.decisions_view(led)
    assert view[0]["event"] == "max_concurrent_skip" and view[-1]["revisions"] == []


def test_runner_ledger_survives_the_display_buffer_and_a_restart():
    runner, ap = rig()
    PlanRunner._log(runner, ap, "max_concurrent_skip", "another position is open", trigger="pm_break_up@09:30#1", sourceTs=ms(10, 2))
    for n in range(500):
        PlanRunner._log(runner, ap, "bar_revised", "updated minute", ts=ms(11, 0) + n)
    assert len(ap.events) == 400
    runner._last_sim[ap.run_id] = {"trades": [], "bias": {}}
    sc = runner._score_execution(ap)
    assert sc["skips"] == {"max_concurrent_skip": 1} and sc["skipRows"] == {"max_concurrent_skip": 1}
    state = runner.state_extras(ap)
    json.dumps(state)                                                         # rides the persisted armed state
    fresh, ap2 = rig()
    fresh.restore_extras(ap2, state)
    fresh._last_sim[ap2.run_id] = {"trades": [], "bias": {}}
    assert fresh._score_execution(ap2)["skips"] == {"max_concurrent_skip": 1}
    # the legacy fallback (no ledger persisted) still de-duplicates the buffer by the same rule
    legacy, ap3 = rig()
    ap3.events += [{"event": "skip_engulfing", "setup": "s@10:00", "ts": ms(10, 10), "text": "a"},
                   {"event": "skip_engulfing", "setup": "s@10:00", "ts": ms(10, 10), "text": "b"}]
    legacy._last_sim[ap3.run_id] = {"trades": [], "bias": {}}
    assert legacy._score_execution(ap3)["skips"] == {"skip_engulfing": 1}


# ---------------------------------------------------------------- entry location / attempts / economics (pure)
def test_entry_location_flags_same_close_and_displacement():
    bars = [bar(9, 58, 100.7, high=100.9, low=100.3), bar(9, 59, 100.85, high=100.95, low=100.6)]
    setup = {"id": "scenario_1@09:45", "direction": "long", "anchor": 100.5, "confirmedTs": ms(9, 45)}
    loc = diag.entry_location(fire_event(ms(10, 0)), setup, bars)
    assert loc["sameCloseConfirmation"] is True and loc["confirmationCloseTs"] == ms(10, 0) and loc["minutesSinceConfirmation"] == 0
    assert loc["pullbackCandle"] == {"open": 100.7, "high": 100.95, "low": 100.3, "close": 100.85, "minutes": 2}
    assert loc["closeFromLevelAtr"] == 0.7 and loc["closeFromEntryLineAtr"] == -0.1        # 0.35 / 0.5 ATR beyond the level
    later = diag.entry_location(fire_event(ms(10, 6)), setup, [bar(10, 4, 100.7), bar(10, 5, 100.8)])
    assert later["sameCloseConfirmation"] is False and later["minutesSinceConfirmation"] == 6
    disp = diag.submission_displacement(loc, 101.05, ms(10, 0, 12), ms(10, 0, 11))
    assert disp["submissionFromCloseAtr"] == 0.4 and disp["movedAway"] is True and disp["submissionFromLevelAtr"] == 1.1
    still = diag.submission_displacement(loc, 100.9, ms(10, 0, 12))
    assert still["movedAway"] is False and still["submission"]["secondsAfterClose"] == 12.0
    unknown = diag.submission_displacement(loc, None, ms(10, 0, 12))
    assert unknown["movedAway"] is None and unknown["submissionFromCloseAtr"] is None
    # a short: distances flip sign
    short = diag.entry_location({**fire_event(ms(10, 0)), "spot": 99.5, "regime": {"stack": "bear", "atr": 0.5}},
                                {"direction": "short", "anchor": 99.7, "confirmedTs": ms(9, 45)}, [bar(9, 58, 99.6), bar(9, 59, 99.4)])
    assert short["closeFromLevelAtr"] == 0.6 and short["direction"] == "short"


def test_attempt_context_first_vs_subsequent_after_a_loss():
    fees = lambda t: 2.08 * float(t.filled_qty or 0)
    first = Trade(trigger_id="s@09:45#1", kind="scenario_1", fired_ts=ms(10, 0), window="team2", entry=100.9, stop=100.4, targets=[103.0],
                  status="closed", setup_id="s@09:45", filled_qty=23, avg_fill=0.51, realized_pnl=-322.23, closed_ts=ms(10, 3), instrument="options")
    ctx1 = diag.attempt_context("s@09:45", "s@09:45#1", ms(10, 0), [first], fees)
    assert ctx1["class"] == "first" and ctx1["attemptIndex"] == 1 and ctx1["previous"] is None and ctx1["previousLost"] is None
    bars = [bar(9, 50 + i, 100 + i * .1, high=100 + i * .1 + .1) for i in range(20)]        # 09:50..10:09 rising
    ctx2 = diag.attempt_context("s@09:45", "s@09:45#2", ms(10, 8), [first], fees, bars, "long")
    assert ctx2["class"] == "subsequent" and ctx2["entryIndex"] == 2 and ctx2["previousLost"] is True
    assert ctx2["previous"]["netPnl"] == -370.07 and ctx2["minutesSincePreviousExit"] == 5.0
    assert ctx2["freshEvidence"]["newExtremeSincePrevious"] is True and ctx2["freshEvidence"]["barsSincePreviousEntry"] == 8
    unfilled = Trade(trigger_id="s@09:45#1", kind="scenario_1", fired_ts=ms(10, 0), window="team2", entry=100.9, stop=100.4, targets=[],
                     status="skipped", setup_id="s@09:45", instrument="options")
    ctx3 = diag.attempt_context("s@09:45", "s@09:45#2", ms(10, 8), [unfilled], fees)
    assert ctx3["class"] == "first" and ctx3["attemptIndex"] == 2 and ctx3["priorAttempts"][0]["outcome"] == "unfilled"


def test_after_cost_and_observations_keep_unknown_unknown():
    o = diag.after_cost(0.51, 0.505, 0.37, 0.375, 1.04)
    assert o["askToBidNet"] == -16.08 and o["askToBidPct"] == -31.53 and o["midToMidNet"] == -15.08
    assert diag.after_cost(0.51, None, None, 0.4, 1.04)["askToBidNet"] is None
    obs = diag.observation("2m", ms(10, 2), ms(10, 2, 3), {"A": {"bid": 0.4, "ask": 0.42, "priced": "opra", "quoteTs": ms(10, 2, 2)},
                                                          "B": {"bid": 0.3, "ask": 0.32, "priced": "chain", "quoteTs": ms(10, 2, 2)}, "C": None})
    assert obs["status"] == "observed" and obs["quotes"]["A"]["mid"] == 0.41 and obs["quotes"]["B"] is None and obs["quotes"]["C"] is None
    assert obs["unknown"] == {"B": "not live (chain)", "C": "no quote"} and obs["quotes"]["A"]["ageMs"] == 1000
    late = diag.observation("5m", ms(10, 5), ms(10, 7), {"A": {"bid": 0.4, "ask": 0.42, "priced": "opra"}})
    assert late["status"] == "unknown" and "120s after due" in late["reason"] and late["quotes"] == {}
    rec = {"trigger": "s#1", "setup": "s", "candidates": [{"symbol": "A", "strike": 101.0, "ask": 0.5, "mid": 0.45, "selected": True, "inBand": True, "delta": 0.3},
                                                          {"symbol": "B", "strike": 102.0, "ask": 0.3, "mid": 0.28, "selected": False, "inBand": True, "delta": 0.2}],
           "observations": {"2m": obs, "5m": late}, "routing": {"filledQty": 10, "avgFill": 0.5, "netPnl": -50.0, "status": "closed", "exitPrice": 0.44},
           "entryLocation": {"sameCloseConfirmation": True, "movedAway": False}, "attempt": {"class": "first", "previousLost": None}}
    s = diag.summarize_attempt(rec, 1.04)
    assert s["candidates"][0]["outcomes"]["2m"]["askToBidPct"] == -24.16 and s["candidates"][1]["outcomes"]["2m"] is None
    assert s["candidates"][0]["outcomes"]["5m"] is None and s["coverage"] == {"observed": 1, "missing": 7, "horizons": ["2m", "5m", "10m", "exit"]}
    day = diag.summarize_day([rec], 1.04)
    assert day["attempts"] == 1 and day["filled"] == 1 and day["coverage"] == {"observed": 1, "missing": 7}
    same = next(x for x in day["situations"] if x["situation"] == "sameCloseConfirmation" and x["value"] is True)
    assert same["filled"] == 1 and same["actualNetSum"] == -50.0 and same["selectedAskToBidPct"]["2m"] == {"mean": -24.16, "n": 1, "missing": 0}
    assert day["contractChoice"]["2m"]["selectedN"] == 1 and day["contractChoice"]["2m"]["compared"] == 0
    assert day["labels"]["movedAwayAtr"] == 0.25


# ---------------------------------------------------------------- the runner wired (no orders change)
async def test_fire_records_entry_location_attempts_and_decision_time_without_touching_the_order_path():
    runner, ap = rig()
    runner._fire_rest = AsyncMock()                       # the order chain is the shared runner's; the diagnostics run before it
    res = read()
    await runner._fire_from_event(ap, res.events[0], runner._bars[ap.run_id][-1], res, halted=False, journal=True)
    await drain(runner)
    tid = "scenario_1@09:45#1"
    assert tid in ap.trades and ap.trades[tid].status == "fired" and runner._fire_rest.await_count == 1
    rec = runner._diag_of(ap.run_id)["attempts"][tid]
    assert rec["entryLocation"]["sameCloseConfirmation"] is True and rec["entryLocation"]["setupLevel"] == 100.5
    assert rec["attempt"]["class"] == "first" and rec["decisionTime"]["inputs"]["tapeHash"].endswith(":30")
    assert rec["decisionTime"]["inputs"]["rulesHash"] and rec["decisionTime"]["signalTs"] == ms(10, 0)
    kinds = [c.args[1]["kind"] for c in runner.engine.journal.append.await_args_list if c.args[0] == "TechniquePlanDiagnostic"]
    assert kinds == ["entry_location", "attempt", "decision_time"]
    # the order boundary snapshots the underlying and returns exactly the gate's own verdict
    verdict = await runner.entry_gate(ap, ap.trades[tid], "order")
    assert verdict == runner._entry_time_refusal(ap, "order")
    assert rec["entryLocation"]["submission"]["underlying"] == 100.4 and rec["entryLocation"]["movedAway"] is False
    # a second fire into the same setup after the first lost is a SUBSEQUENT attempt after a loss
    t = ap.trades[tid]
    t.status, t.filled_qty, t.avg_fill, t.realized_pnl, t.closed_ts = "closed", 23, 0.51, -322.23, ms(10, 3)
    ev2 = fire_event(ms(10, 8), touch=2, spot=101.2)
    res2 = SimpleNamespace(events=[ev2], setups=res.setups)
    await runner._fire_from_event(ap, ev2, runner._bars[ap.run_id][-1], res2, halted=False, journal=True)
    rec2 = runner._diag_of(ap.run_id)["attempts"]["scenario_1@09:45#2"]
    assert rec2["attempt"]["class"] == "subsequent" and rec2["attempt"]["previousLost"] is True and rec2["entryLocation"]["sameCloseConfirmation"] is False
    # diagnostics off: nothing recorded, the fire is unchanged
    ap.trades["scenario_1@09:45#2"].status = "closed"
    runner.engine.settings = {"techniques.team2.diagnostics": False}
    ev3 = fire_event(ms(10, 16), touch=3)
    await runner._fire_from_event(ap, ev3, runner._bars[ap.run_id][-1], SimpleNamespace(events=[ev3], setups=res.setups), halted=False, journal=True)
    assert "scenario_1@09:45#3" in ap.trades and "scenario_1@09:45#3" not in runner._diag_of(ap.run_id)["attempts"]


async def test_candidates_are_followed_at_horizons_and_the_exit_with_missing_quotes_unknown(monkeypatch):
    opts = FakeOpts(chain(), {"SPY260914C00101000": (0.80, 0.82), "SPY260914C00102000": (0.44, 0.46), "SPY260914C00103000": (0.30, 0.31)})
    runner, ap = rig(opts)
    tid = "scenario_1@09:45#1"
    trade = Trade(trigger_id=tid, kind="scenario_1", fired_ts=ms(10, 0), window="team2", entry=100.9, stop=100.4, targets=[103.0],
                  setup_id="scenario_1@09:45", instrument="options", multiplier=100.0, direction="long")
    ap.trades[tid] = trade
    rules = runner.rules_for(ap)
    otm = sorted([c for c in chain() if c["strike"] > 100.4], key=lambda c: c["strike"])
    qres = await runner._quote_examined(opts, otm, 100.4, "long", rules, "2026-09-14", dt.date(2026, 9, 14))
    assert qres["pick"] is not None and qres["pick"].symbol == "SPY260914C00102000" and qres["unpriced"] == 1
    runner._diag_candidates(ap, tid, qres, qres["pick"].symbol, 100.4, rules, chain(), opts)
    await drain(runner)
    rec = runner._diag_of(ap.run_id)["attempts"][tid]
    sel = next(c for c in rec["candidates"] if c["selected"])
    assert sel["symbol"] == "SPY260914C00102000" and sel["ask"] == 0.46 and sel["delta"] == 0.24 and sel["inBand"] is True
    assert [c["eligible"] for c in rec["candidates"]] == [True, True, True, False]      # the 104 had no live quote
    pend = runner._diag_of(ap.run_id)["pending"]
    assert [p["horizon"] for p in pend] == ["2m", "5m", "10m", "exit"] and pend[3]["dueTs"] is None
    # nothing is due yet
    await runner._diag_tick(); await drain(runner)
    assert rec["observations"] == {}
    # the 2m horizon comes due; the 103 has lost its live quote (unknown), the 104 never had one
    opts.live.pop("SPY260914C00103000")
    opts.live["SPY260914C00102000"] = (0.50, 0.52)
    pend[0]["dueTs"] = int(dt.datetime.now(ET).timestamp() * 1000) - 1000
    await runner._diag_tick(); await drain(runner)
    o2 = rec["observations"]["2m"]
    assert o2["status"] == "observed" and o2["quotes"]["SPY260914C00102000"]["bid"] == 0.50 and o2["quotes"]["SPY260914C00103000"] is None
    assert pend[0]["status"] == "done" and pend[1]["status"] == "pending"
    # the position closes: the exit observation becomes due at the close and is taken
    trade.status, trade.filled_qty, trade.remaining, trade.avg_fill, trade.realized_pnl = "closed", 10.0, 0.0, 0.46, 40.0
    trade.closed_ts = int(dt.datetime.now(ET).timestamp() * 1000) - 500
    trade.exits.append({"kind": "stop", "qty": 10, "orderId": "x1", "status": "FILLED", "filledQty": 10, "price": 0.50})
    await runner._diag_tick(); await drain(runner)
    assert "exit" in rec["observations"] and rec["routing"]["exitPrice"] == 0.5 and rec["routing"]["netPnl"] == 40.0
    # a horizon missed by more than the tolerance is UNKNOWN, never back-dated
    pend[1]["dueTs"] = int(dt.datetime.now(ET).timestamp() * 1000) - 200_000
    await runner._diag_tick(); await drain(runner)
    assert rec["observations"]["5m"]["status"] == "unknown"
    runner._last_sim[ap.run_id] = {"trades": [], "bias": {}}
    sc = runner._score_execution(ap)
    d = sc["diagnostics"]
    s = d["perAttempt"][0]
    sel_s = next(c for c in s["candidates"] if c["selected"])
    assert sel_s["outcomes"]["2m"]["askToBidNet"] == 1.92 and sel_s["outcomes"]["5m"] is None and sel_s["outcomes"]["exit"]["askToBidPct"] == 4.17
    assert s["coverage"]["missing"] >= 4 and d["contractChoice"]["2m"]["compared"] == 1
    assert s["actual"] == {"filledQty": 10.0, "avgFill": 0.46, "netPnl": 40.0, "exitPrice": 0.5, "status": "closed"}
    # the persisted state carries the schedule and comes back (an in-flight observation is re-queued)
    state = runner.state_extras(ap)
    json.dumps(state)
    fresh, ap2 = rig(opts)
    fresh.restore_extras(ap2, state)
    assert fresh._diag_of(ap2.run_id)["attempts"][tid]["observations"]["2m"]["status"] == "observed"
    assert [p["status"] for p in fresh._diag_of(ap2.run_id)["pending"]] == ["done", "done", "pending", "done"]


async def test_a_candidate_refused_by_the_concurrency_cap_is_quoted_in_the_shadow_only():
    opts = FakeOpts(chain(), {"SPY260914C00101000": (0.80, 0.82), "SPY260914C00102000": (0.44, 0.46)})
    runner, ap = rig(opts)
    other = ArmedPlan(run_id="other-run", symbol="QQQ", plan_for=DAY, plan={"zones": {"present": True}}, config=ap.config, trackers={}, armed_at=0)
    other.trades["q#1"] = Trade(trigger_id="q#1", kind="scenario_1", fired_ts=ms(9, 50), window="team2", entry=1.0, stop=0.9, targets=[],
                                status="open", setup_id="q", filled_qty=5, remaining=5, instrument="options")
    runner._armed[other.run_id] = other
    runner._fire_rest = AsyncMock()
    res = read()
    await runner._fire_from_event(ap, res.events[0], runner._bars[ap.run_id][-1], res, halted=False, journal=True)
    await drain(runner)
    tid = "scenario_1@09:45#1"
    assert tid not in ap.trades and runner._fire_rest.await_count == 0                  # the refusal stands
    assert tid in (ap.plan.get("executionRefused") or [])
    rec = runner._diag_of(ap.run_id)["attempts"][tid]
    assert rec["shadow"] is True and rec["refusal"] == "max_concurrent_skip" and rec["selected"] == "SPY260914C00102000"
    assert rec["entryLocation"]["sameCloseConfirmation"] is True
    assert [p["horizon"] for p in runner._diag_of(ap.run_id)["pending"]] == ["2m", "5m", "10m"]     # no exit: no position
    assert not runner.__dict__.get("_contract_verdicts", {}).get(ap.run_id)             # no verdict was written
    runner._last_sim[ap.run_id] = {"trades": [], "bias": {}}
    sc = runner._score_execution(ap)
    assert sc["skips"] == {"max_concurrent_skip": 1} and sc["diagnostics"]["shadow"] == 1
    assert sc["decisions"][0]["ts"] == ms(10, 0)                                         # keyed on the SOURCE minute


def test_report_assembles_journal_rows_into_attempt_records():
    rows = [
        {"type": "TechniquePlanDiagnostic", "payload": {"runId": "r1", "symbol": "SPY", "kind": "entry_location", "trigger": "s#1", "sameCloseConfirmation": True, "atr": 0.5}},
        {"type": "TechniquePlanDiagnostic", "payload": {"runId": "r1", "symbol": "SPY", "kind": "entry_submission", "trigger": "s#1", "movedAway": False, "submissionFromCloseAtr": 0.1}},
        {"type": "TechniquePlanDiagnostic", "payload": {"runId": "r1", "symbol": "SPY", "kind": "attempt", "trigger": "s#1", "class": "first", "previousLost": None}},
        {"type": "TechniquePlanDiagnostic", "payload": {"runId": "r1", "symbol": "SPY", "kind": "contract_candidates", "trigger": "s#1", "shadow": False, "selected": "A",
                                                        "candidates": [{"symbol": "A", "strike": 101.0, "ask": 0.5, "mid": 0.45, "selected": True, "inBand": True, "delta": 0.3}]}},
        {"type": "TechniquePlanDiagnostic", "payload": {"runId": "r1", "symbol": "SPY", "kind": "contract_observation", "trigger": "s#1", "horizon": "2m", "status": "observed",
                                                        "quotes": {"A": {"bid": 0.55, "ask": 0.57, "mid": 0.56}}}},
        {"type": "TechniquePlanScored", "payload": {"runId": "r1", "symbol": "SPY", "diagnostics": {"perAttempt": [{"trigger": "s#1", "actual": {"filledQty": 10, "avgFill": 0.5, "netPnl": 30.0, "status": "closed", "exitPrice": 0.55}}]}}},
    ]
    recs = assemble(rows)
    assert len(recs) == 1 and recs[0]["entryLocation"]["movedAway"] is False and recs[0]["routing"]["netPnl"] == 30.0
    day = diag.summarize_day(recs, 1.04)
    assert day["filled"] == 1 and day["perAttempt"][0]["candidates"][0]["outcomes"]["2m"]["askToBidNet"] == 2.92


# ---------------------------------------------------------------- 2026-09-16 review D1/D2/D3 (shadow boundaries)
def test_quote_freshness_and_sanity_decide_an_observation():
    due = ms(10, 2)
    fresh = {"bid": .6, "ask": .61, "priced": "opra", "quoteTs": due - 2_000}
    ok = diag.observation("2m", due, due, {"OPT": fresh})
    assert ok["status"] == "observed" and ok["quotes"]["OPT"]["ageMs"] == 2000              # on-time fresh control
    stale = diag.observation("2m", due, due, {"OPT": {**fresh, "quoteTs": due - 120_000}})
    assert stale["status"] == "unknown" and stale["quotes"]["OPT"] is None and "stale quote (120s" in stale["unknown"]["OPT"]
    no_ts = diag.observation("2m", due, due, {"OPT": {"bid": .6, "ask": .61, "priced": "opra"}})
    assert no_ts["quotes"]["OPT"] is None and no_ts["unknown"]["OPT"] == "no source timestamp"
    crossed = diag.observation("2m", due, due, {"OPT": {**fresh, "bid": .7}})
    assert crossed["quotes"]["OPT"] is None and crossed["unknown"]["OPT"] == "crossed quote"
    no_bid = diag.observation("2m", due, due, {"OPT": {**fresh, "bid": 0}})
    assert no_bid["unknown"]["OPT"] == "no bid"
    outage = diag.observation("2m", due, due, {}, unknown={"OPT": "options service unavailable"})
    assert outage["status"] == "unknown" and outage["quotes"] == {"OPT": None} and outage["unknown"]["OPT"] == "options service unavailable"
    late = diag.observation("2m", due, due + 200_000, {"OPT": {**fresh, "quoteTs": due + 199_000}})
    assert late["status"] == "unknown" and late["quotes"] == {} and "after due" in late["reason"]
    # a stale unchanged quote must never read as the contract losing only its commission
    rec = {"trigger": "s#1", "candidates": [{"symbol": "OPT", "selected": True, "inBand": True, "ask": .61, "mid": .605, "priceKnown": True}],
           "observations": {"2m": stale}, "routing": {}}
    a = diag.summarize_attempt(rec, 1.04)
    assert a["candidates"][0]["outcomes"]["2m"] is None and "stale quote" in a["candidates"][0]["unknown"]["2m"]


def test_unknown_entry_prices_never_enter_a_return_or_a_comparison():
    obs = {"2m": {"status": "observed", "quotes": {"sel": {"bid": .6, "mid": .605}, "alt": {"bid": .4, "mid": .405}}, "unknown": {}}}
    # the SELECTED entry is unknown: no return anywhere for it, alternatives still stand on their own
    rec = {"trigger": "s#1", "candidates": [{"symbol": "sel", "selected": True, "inBand": True, "ask": 0.0, "mid": None, "priceKnown": False, "priceUnknownReason": "no ask"},
                                            {"symbol": "alt", "selected": False, "inBand": True, "ask": .35, "mid": .34, "priceKnown": True}],
           "observations": obs, "routing": {"filledQty": 10, "netPnl": -20.0, "status": "closed"}}
    day = diag.summarize_day([rec], 1.04)
    row = day["perAttempt"][0]
    assert row["candidates"][0]["outcomes"]["2m"] is None and row["candidates"][0]["unknown"]["2m"] == "entry price unknown (no ask)"
    assert row["candidates"][1]["outcomes"]["2m"]["askToBidPct"] == 8.34
    assert day["contractChoice"]["2m"]["selectedN"] == 0 and day["contractChoice"]["2m"]["compared"] == 0 and day["contractChoice"]["2m"]["inBandAlternativesN"] == 1
    same = [x for x in day["situations"] if x["situation"] == "attemptClass"][0]
    assert same["filled"] == 1 and same["actualNetSum"] == -20.0
    assert same["selectedAskToBidPct"]["2m"] == {"mean": None, "n": 0, "missing": 1}      # the unknown is COUNTED as missing, never averaged
    # no candidates at all
    empty = diag.summarize_day([{"trigger": "s#2", "candidates": [], "observations": {}, "routing": {}}], 1.04)
    assert empty["attempts"] == 1 and empty["coverage"] == {"observed": 0, "missing": 0} and empty["contractChoice"] == {}
    # mixed known / unknown alternatives: only the known one is compared
    mixed = {"trigger": "s#3", "candidates": [{"symbol": "sel", "selected": True, "inBand": True, "ask": .5, "mid": .495, "priceKnown": True},
                                              {"symbol": "u", "selected": False, "inBand": False, "ask": 0.0, "mid": None, "priceKnown": False},
                                              {"symbol": "k", "selected": False, "inBand": True, "ask": .3, "mid": .29, "priceKnown": True}],
             "observations": {"2m": {"status": "observed", "quotes": {"sel": {"bid": .6, "mid": .605}, "u": {"bid": .4, "mid": .405}, "k": {"bid": .4, "mid": .405}}, "unknown": {}}},
             "routing": {}}
    d2 = diag.summarize_day([mixed], 1.04)
    assert d2["contractChoice"]["2m"]["compared"] == 1 and d2["contractChoice"]["2m"]["alternativeBeatSelected"] == 1
    assert d2["labels"]["candidates"].startswith("HYPOTHETICAL") and d2["labels"]["actual"].startswith("book fills")


async def test_a_diagnostic_summary_fault_cannot_interrupt_scoring_or_session_close(monkeypatch):
    runner, ap = rig()
    runner._last_sim[ap.run_id] = {"trades": [], "bias": {}}
    runner.disarm = AsyncMock(return_value=True)
    tid = "scenario_1@09:45#1"
    ap.trades[tid] = Trade(trigger_id=tid, kind="scenario_1", fired_ts=ms(10, 0), window="team2", entry=100.9, stop=100.4, targets=[],
                           status="closed", setup_id="scenario_1@09:45", filled_qty=10, avg_fill=0.5, realized_pnl=40.0, instrument="options",
                           order_symbol="SPY260914C00101000", multiplier=100.0)
    runner._diag_of(ap.run_id)["attempts"][tid] = {"trigger": tid, "candidates": [{"symbol": "x", "selected": True, "ask": .5}], "observations": {}}

    def boom(*a, **k):
        raise RuntimeError("synthetic summary fault")
    monkeypatch.setattr(diag, "summarize_day", boom)
    await runner._end_session(ap, journal=True)
    runner.disarm.assert_awaited_once()
    sc = ap.scorecard
    assert sc["actualFires"] == 1 and sc["realizedPnl"] <= sc["realizedPnlGross"] == 40.0      # core accounting intact
    assert sc["diagnostics"]["status"] == "error" and "synthetic summary fault" in sc["diagnostics"]["error"]
    assert sc["skips"] == {} and sc["correctedHistory"] is True


def test_exit_price_is_weighted_by_confirmed_fills_only():
    def trade(exits):
        return SimpleNamespace(status="closed", filled_qty=10, avg_fill=.5, order_symbol="OPT", realized_pnl=100.0, opened_ts=1, closed_ts=2, exits=exits)
    # partial exits at different prices, the stale SUBMITTED status notwithstanding
    r = Team2Runner._diag_routing(trade([{"orderId": "a", "status": "SUBMITTED", "filledQty": 4, "qty": 4, "price": .8},
                                         {"orderId": "b", "status": "FILLED", "filledQty": 6, "qty": 6, "price": .6}]), 20.8)
    assert r["exitPrice"] == .68 and r["exitFilledQty"] == 10 and r["exitPriceUnknown"] is False and r["netPnl"] == 79.2
    # an unfilled submitted exit is not a fill; the requested qty is never inferred
    r2 = Team2Runner._diag_routing(trade([{"orderId": "a", "status": "SUBMITTED", "filledQty": 0, "qty": 10, "price": .8}]), 0)
    assert r2["exitPrice"] is None and r2["exitFilledQty"] == 0 and r2["exitPriceUnknown"] is False
    # duplicate updates of one order count once (the last wins)
    r3 = Team2Runner._diag_routing(trade([{"orderId": "a", "status": "SUBMITTED", "filledQty": 4, "qty": 10, "price": .8},
                                          {"orderId": "a", "status": "FILLED", "filledQty": 10, "qty": 10, "price": .8}]), 0)
    assert r3["exitPrice"] == .8 and r3["exitFilledQty"] == 10
    # a confirmed fill without a price is UNKNOWN, not zero
    r4 = Team2Runner._diag_routing(trade([{"orderId": "a", "status": "FILLED", "filledQty": 10, "qty": 10, "price": None}]), 0)
    assert r4["exitPrice"] is None and r4["exitPriceUnknown"] is True and r4["exitFilledQty"] == 10


async def test_follow_up_collection_is_bounded_and_refreshes_rather_than_reusing_the_entry_quote():
    rows = []
    live = {}
    for k in range(101, 109):
        sym = f"SPY260914C{k * 1000:08d}"
        rows.append({"symbol": sym, "strike": float(k), "option_type": "call", "ask": 0.5, "bid": 0.4, "greeks": {"delta": 0.2}})
        live[sym] = (0.4, 0.42)
    opts = FakeOpts(rows, live)
    runner, ap = rig(opts)
    tid = "scenario_1@09:45#1"
    ap.trades[tid] = Trade(trigger_id=tid, kind="scenario_1", fired_ts=ms(10, 0), window="team2", entry=100.9, stop=100.4, targets=[103.0],
                           setup_id="scenario_1@09:45", instrument="options", multiplier=100.0, direction="long")
    rules = runner.rules_for(ap)
    otm = sorted(rows, key=lambda c: c["strike"])
    rules = type(rules)(**{**rules.to_dict(), "quote_candidates": 8}) if hasattr(rules, "to_dict") else rules
    qres = await runner._quote_examined(opts, otm, 100.4, "long", rules, "2026-09-14", dt.date(2026, 9, 14))
    runner._diag_candidates(ap, tid, qres, qres["pick"].symbol if qres["pick"] else None, 100.4, rules, rows, opts)
    await drain(runner)
    rec = runner._diag_of(ap.run_id)["attempts"][tid]
    assert len(rec["candidates"]) == 8 and sum(1 for c in rec["candidates"] if c["followed"]) == 6
    assert all(c["priceKnown"] and c["quoteTs"] is not None and c["collectedTs"] >= c["quoteTs"] for c in rec["candidates"])
    # the cached entry quote is two minutes old at the follow-up: it is NOT the two-minute observation
    opts.stale_ms = 125_000
    pend = runner._diag_of(ap.run_id)["pending"]
    pend[0]["dueTs"] = now_ms() - 1000
    await runner._diag_tick(); await drain(runner)
    o = rec["observations"]["2m"]
    assert o["status"] == "unknown" and all(v is None for v in o["quotes"].values())
    followed = [c["symbol"] for c in rec["candidates"] if c["followed"]]
    assert all("stale quote" in o["unknown"][sym] for sym in followed)
    assert all(o["unknown"][c["symbol"]] == "not followed (collection bounded)" for c in rec["candidates"] if not c["followed"])
    # fresh again: the next horizon is observed, and the summary counts exactly the followed contracts
    opts.stale_ms = 0
    pend[1]["dueTs"] = now_ms() - 1000
    await runner._diag_tick(); await drain(runner)
    o5 = rec["observations"]["5m"]
    assert o5["status"] == "observed" and sum(1 for v in o5["quotes"].values() if v) == 6
    runner._last_sim[ap.run_id] = {"trades": [], "bias": {}}
    sc = runner._score_execution(ap)
    per = sc["diagnostics"]["perAttempt"][0]
    assert per["coverage"]["observed"] == 6 and sc["diagnostics"]["labels"]["maxFollowed"] == 6

