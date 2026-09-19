"""ED-04 `book-snapshot-v1` (integrated plan E, 2026-09-18): pure capture, the bounded recorder, the runner boundary,
the runtime collector and the offline reducer. Acceptance rows "Portfolio capture" + the paired-exit consumer join.
One real-Postgres case writes the EM-owned table; everything else is pure. No engine start, no orders."""
import asyncio
import inspect
from types import SimpleNamespace

import pytest

from zargar.execution.planrunner import PlanRunner
from zargar.technique import profit_capture as pc
from zargar.technique import profit_capture_runtime as rt

NOW = 1_800_000_000_000
IDS = {"portfolioId": "book", "session": "2026-09-18", "build": "abc", "baseline": "em-practice-baseline", "policy": {}}


def _pos(sym="BMNR260925P00023000", inst="options", remaining=4, pending=0, avg=1.00, original=4, realized=0.0, fees=4.16, ti="E1"):
    return {"runId": "r1", "trigger": "d1", "tradeInstance": ti, "symbol": sym, "underlying": sym[:4], "direction": "short", "instrument": inst,
            "multiplier": (100.0 if inst == "options" else 1.0), "positionSide": "long", "original": original, "remaining": remaining,
            "pendingExit": pending, "avgFill": avg, "realizedGross": realized, "feesPaid": fees}


def _q(bid, ask, bsz=10, asz=10, age=500, source="opra", **kw):
    return {"bid": bid, "ask": ask, "last": (bid + ask) / 2, "bidSize": bsz, "askSize": asz, "source": source, "sourceTs": NOW - age, "receivedTs": NOW - 100, **kw}


def _book(positions, quotes, **kw):
    base = dict(ids=IDS, seq=1, now_ms=NOW, reason="periodic", causal=None, cash=9000.0, realized_closed_net=0.0, fees_closed=0.0,
                positions=positions, quotes=quotes, fee_per_contract=1.04)
    return pc.capture_book(**{**base, **kw})


# ----------------------------------------------------------------------------------------------------- pure capture
def test_a_midpoint_spike_is_not_executable_value_and_spread_is_never_deducted_twice():
    b = _book([_pos()], {"BMNR260925P00023000": _q(1.10, 1.90)})                    # a wide book: mid 1.50
    p = b["positions"][0]
    assert p["mark"] == {"basis": "mid", "price": 1.5, "displayedUnrealized": 200.0}
    assert p["executable"]["status"] == "covered" and p["executable"]["price"] == 1.10
    assert p["executable"]["grossCovered"] == 40.0 and p["executable"]["feeModeled"] == 4.16 and p["executable"]["netCovered"] == 35.84
    assert b["book"]["displayedNet"] == 195.84 and b["book"]["executableTotalNet"] == 31.68 and b["book"]["scorable"] is True
    assert b["book"]["realizedNet"] == -4.16, "the entry fees already paid are realized, exactly once"


@pytest.mark.parametrize("quote,reason", [
    (_q(1.4, 1.5, age=11_000), "stale_quote"),
    (_q(1.4, 1.5, source="chain"), "delayed_quote"),
    (_q(1.4, 1.5, source="derived:chain", transform="recenter-v1"), "derived_quote"),
    (_q(1.4, 1.5, bsz=None), "size_unknown"),
    (_q(1.4, 1.5, bsz=0), "size_unknown"),
    (_q(1.6, 1.5), "crossed_book"),
    (_q(0.0, 1.5), "one_sided_book"),
    ({"bid": 1.4, "ask": 1.5, "bidSize": 5, "askSize": 5, "source": "opra", "sourceTs": 0}, "source_time_unknown"),
    (None, "no_quote"),
])
def test_a_stale_delayed_derived_or_unknown_size_quote_is_unknown_and_never_scorable(quote, reason):
    b = _book([_pos()], {"BMNR260925P00023000": quote})
    e = b["positions"][0]["executable"]
    assert e["status"] == "unknown" and reason in e["reasons"] and e["netCovered"] is None and e["coveredQty"] == 0
    assert b["book"]["scorable"] is False and b["book"]["executableNetCovered"] is None and b["book"]["executableTotalNet"] is None
    red = pc.reduce_session([b])
    assert red["peakExecutableNet"] is None, "an unknown quote can never make a high-water mark"


def test_pending_and_partial_quantities_are_conserved_and_never_sold_twice():
    p = pc.capture_position(_pos(remaining=4, pending=3), _q(1.4, 1.5, bsz=50), now_ms=NOW, exit_fee_per_unit=1.04)
    assert p["quantities"] == {"original": 4.0, "remaining": 4.0, "pendingExit": 3.0, "reserved": 1.0}
    assert p["executable"]["coveredQty"] == 1.0 and p["executable"]["grossCovered"] == 40.0, "only the uncommitted contract is sellable"
    assert p["mark"]["displayedUnrealized"] == 180.0, "the mark still values everything held"
    b = _book([_pos(remaining=4, pending=3)], {"BMNR260925P00023000": _q(1.4, 1.5, bsz=50)})
    assert b["book"]["scorable"] is False and any("pending_exit_reserved" in r for r in b["book"]["unscorableReasons"])
    thin = pc.capture_position(_pos(remaining=4), _q(1.4, 1.5, bsz=3), now_ms=NOW, exit_fee_per_unit=1.04)
    assert thin["executable"]["status"] == "partial" and thin["executable"]["coveredQty"] == 3 and thin["executable"]["uncoveredQty"] == 1
    allp = pc.capture_position(_pos(remaining=4, pending=4), None, now_ms=NOW, exit_fee_per_unit=1.04)
    assert allp["executable"]["status"] == "pending_only" and allp["executable"]["reasons"] == []


def test_a_skewed_basket_is_unscorable_and_shares_need_depth_and_feed_provenance_too():
    pos = [_pos(), _pos(sym="FSLR", inst="shares", remaining=25, original=25, avg=196.0, fees=0.0, ti="E2")]
    ok = _book(pos, {"BMNR260925P00023000": _q(1.4, 1.5), "FSLR": _q(197.0, 197.05, bsz=300, source="alpaca")})
    assert ok["book"]["scorable"] is True and ok["book"]["quoteSkewMs"] == 0
    skew = _book(pos, {"BMNR260925P00023000": _q(1.4, 1.5, age=200), "FSLR": _q(197.0, 197.05, bsz=300, age=7000, source="alpaca")})
    assert skew["book"]["scorable"] is False and skew["book"]["quoteSkewMs"] == 6800 and "quote_time_skew_6800ms" in skew["book"]["unscorableReasons"]
    assert skew["book"]["coveredPartialNet"] > 0 and skew["book"]["executableTotalNet"] is None, "a partial basket is not a total"
    nodepth = _book(pos, {"BMNR260925P00023000": _q(1.4, 1.5), "FSLR": _q(197.0, 197.05, bsz=None, source="alpaca")})
    assert nodepth["book"]["scorable"] is False


# ---------------------------------------------------------------------------------------------- the bounded recorder
def _observer(enabled=True, write=None, inputs=None, maxsize=256, cadence=30.0, clock=None):
    clock = clock or [NOW]
    inputs = inputs if inputs is not None else (lambda: dict(ids=IDS, cash=9000.0, realized_closed_net=0.0, fees_closed=0.0, positions=[_pos()],
                                                             quotes={"BMNR260925P00023000": _q(1.4, 1.5)}, fee_per_contract=1.04))
    written, drops = [], []

    async def _w(rec):
        written.append(rec)
    o = pc.ProfitCaptureObserver(enabled=lambda: enabled, collect=inputs, write=(write or _w), clock_ms=lambda: clock[0],
                                 cadence_s=lambda: cadence, maxsize=maxsize, retry_sleep_s=0.0, on_drop=lambda why, rec: drops.append(why))
    return o, written, drops, clock


def test_off_by_default_records_nothing_and_collects_nothing():
    from zargar.settings_service import DEFAULTS
    assert DEFAULTS["techniques.enhanced_market.book_snapshot_observe"] is False
    assert not any(k.endswith("book_snapshot_observe") and not k.startswith("techniques.enhanced_market.") for k in DEFAULTS)
    o, written, _, _ = _observer(enabled=False, inputs=lambda: (_ for _ in ()).throw(AssertionError("must not collect")))
    assert o.snap("pre_stop") is None and o.stats["captured"] == 0


def test_snap_is_synchronous_and_a_slow_or_failing_writer_never_delays_the_caller():
    gate = asyncio.Event()

    async def slow(rec):
        await gate.wait()

    async def run():
        o, _, drops, _ = _observer(write=slow, maxsize=2)
        assert not inspect.iscoroutinefunction(o.snap)
        recs = [o.snap("pre_stop", {"kind": "stop"}) for _ in range(5)]          # returns immediately, five times, with the writer blocked
        assert all(r is not None for r in recs) and [r["seq"] for r in recs] == [1, 2, 3, 4, 5]
        await asyncio.sleep(0)
        assert o.stats["droppedQueueFull"] >= 2 and drops and drops[0] == "queue_full", "saturation is visible, never silent"
        assert recs[-1]["recorder"]["droppedQueueFull"] >= 1, "the NEXT record carries the drop counter into the evidence"
        gate.set()
        await o.wait_idle()
    asyncio.run(run())


def test_failed_writes_retry_with_original_timing_then_drop_visibly():
    calls = []

    async def bad(rec):
        calls.append(rec["capturedAt"])
        raise RuntimeError("db down")

    async def run():
        o, _, drops, clock = _observer(write=bad)
        o.snap("pre_target")
        clock[0] += 60_000
        await o.wait_idle()
        assert calls == [NOW, NOW, NOW] and o.stats["droppedWriteFailed"] == 1 and o.stats["retries"] == 2 and drops == ["write_failed:RuntimeError"]
    asyncio.run(run())


def test_periodic_cadence_restore_marker_and_flat_book_rules():
    async def run():
        o, written, _, clock = _observer()
        a = o.snap("periodic")
        assert a["reason"] == "restore", "the first sample after a (re)start is an explicit gap marker"
        assert o.snap("periodic") is None, "inside the cadence"
        clock[0] += 31_000
        assert o.snap("periodic")["reason"] == "periodic"
        assert o.snap("pre_stop")["reason"] == "pre_stop", "event snapshots ignore the cadence"
        flat = lambda: dict(ids=IDS, cash=9000.0, realized_closed_net=-84.1, fees_closed=2.08, positions=[], quotes={}, fee_per_contract=1.04)   # noqa: E731
        o2, _, _, c2 = _observer(inputs=flat)
        assert o2.snap("periodic") is None, "a flat book records nothing periodic"
        end = o2.snap("fill", {"kind": "stop"})
        assert end["book"]["openPositions"] == 0 and end["book"]["realizedNet"] == -84.1 and end["book"]["scorable"] is True
        await o.wait_idle(); await o2.wait_idle()
    asyncio.run(run())


def test_a_collector_error_never_raises_into_the_runner():
    o, _, _, _ = _observer(inputs=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert o.snap("pre_stop") is None and o.stats["captureErrors"] == 1


# ------------------------------------------------------------------------------------------------ runner boundary
def test_the_runner_calls_are_sync_never_awaited_and_bracket_the_exit_before_the_order():
    src = inspect.getsource(PlanRunner)
    assert "await self._book_snap" not in src and not inspect.iscoroutinefunction(PlanRunner._book_snap)
    ex = inspect.getsource(PlanRunner._exit)
    assert ex.index('self._book_snap(f"pre_') < ex.index("reduce_only_exit_intent(") < ex.index("_place_with_retry") < ex.index('self._book_snap(f"post_')
    # no observer (every other desk) = nothing happens; a raising observer is swallowed
    PlanRunner._book_snap(SimpleNamespace(), "pre_stop")
    boom = SimpleNamespace(_book_observer=SimpleNamespace(snap=lambda *a: (_ for _ in ()).throw(RuntimeError("x"))))
    PlanRunner._book_snap(boom, "pre_stop", SimpleNamespace(run_id="r", symbol="S"), SimpleNamespace(trigger_id="t"), "stop")
    from zargar.execution.planrunner import _book_snap_family
    assert [_book_snap_family(k) for k in ("tp1", "tp3", "stop", "flatten", "disarm", "scratch")] == ["target", "target", "stop", "flatten", "flatten", "protection"]


def test_runtime_collector_reads_memory_only_and_conserves_closed_trades():
    oq = SimpleNamespace(bid=0.24, ask=0.30, last=0.27, bid_size=8, ask_size=9, source="opra", raw_source="", transform="", delayed=False, source_ts=NOW - 400, quote_ts=0, ts=NOW - 50, session="regular")
    open_tr = SimpleNamespace(trigger_id="d1", filled_qty=4, remaining=4, pending_exit_qty=0, realized_pnl=0.0, entry_order_id="E1", instrument="options",
                              order_symbol="DRAM260921P00058000", direction="short", multiplier=100.0, avg_fill=0.50)
    closed_tr = SimpleNamespace(trigger_id="d1", filled_qty=1, remaining=0, pending_exit_qty=0, realized_pnl=-82.0, entry_order_id="E2", instrument="options",
                                order_symbol="SBUX261002P00095000", direction="short", multiplier=100.0, avg_fill=1.05)
    unfilled = SimpleNamespace(trigger_id="b1", filled_qty=0, remaining=0, pending_exit_qty=0, realized_pnl=0.0, entry_order_id=None, instrument="shares", order_symbol=None, direction="long", multiplier=1.0, avg_fill=None)
    mk = lambda rid, sym, trs, pid="book": SimpleNamespace(run_id=rid, symbol=sym, config=SimpleNamespace(portfolio_id=pid), trades={i: t for i, t in enumerate(trs)})   # noqa: E731
    settings = {"techniques.enhanced_market.default_portfolio": "book", "options.fee_per_contract": 0.99, "sim.reg_fee_per_contract": 0.05}
    armer = SimpleNamespace(_armed={"a": mk("a", "DRAM", [open_tr]), "b": mk("b", "SBUX", [closed_tr, unfilled]), "c": mk("c", "TIPX", [open_tr], pid="other-desk")},
                            engine=SimpleNamespace(settings=SimpleNamespace(get=lambda k, d=None: settings.get(k, d)),
                                                   quotes=SimpleNamespace(get=lambda s: oq if s.startswith("DRAM") else None),
                                                   positions=SimpleNamespace(portfolio=lambda pid: {"cash": 9600.0})),
                            rt=lambda k, d=None: d, _fees_paid=lambda tr: 1.04 * (tr.filled_qty + (tr.filled_qty - tr.remaining)))
    cache = {}
    inp = rt.collect_inputs(armer, cache, NOW)
    assert [p["tradeInstance"] for p in inp["positions"]] == ["E1"], "another desk's book and unfilled/closed trades are not positions"
    assert inp["realized_closed_net"] == pytest.approx(-84.08) and inp["fees_closed"] == pytest.approx(2.08) and inp["cash"] == 9600.0
    assert inp["quotes"]["DRAM260921P00058000"]["sourceTs"] == NOW - 400 and inp["quotes"]["DRAM260921P00058000"]["receivedTs"] == NOW - 50
    rec = pc.capture_book(seq=1, now_ms=NOW, reason="periodic", causal=None, **inp)
    assert rec["book"]["scorable"] is True and rec["book"]["realizedNet"] == pytest.approx(-88.24), "closed net + the open trade's entry fees"
    del armer._armed["b"]                                                     # the closed plan leaves the runner: its realized result is kept for the session
    assert rt.collect_inputs(armer, cache, NOW)["realized_closed_net"] == pytest.approx(-84.08)


# ------------------------------------------------------------------------------------------------------- reducer
def _series():
    sym = "BMNR260925P00023000"
    s1 = _book([_pos()], {sym: _q(1.10, 1.90)}, seq=1, now_ms=NOW)                                   # displayed 195.84 / executable 31.68
    s2 = _book([_pos()], {sym: _q(1.60, 1.70, age=-29_500)}, seq=2, now_ms=NOW + 30_000)                          # executable peak: 240 - 4.16 - 4.16 = 231.68
    s3 = _book([_pos()], {sym: _q(2.40, 2.60, bsz=None, age=-59_500)}, seq=3, now_ms=NOW + 60_000)                # a bigger displayed number with UNKNOWN depth
    s5 = _book([], {}, seq=5, now_ms=NOW + 120_000, reason="fill", realized_closed_net=71.68, fees_closed=8.32)
    for s, st in zip((s1, s2, s3, s5), (0, 0, 0, 1)):
        s["recorder"] = {"droppedQueueFull": st, "droppedWriteFailed": 0}
    return [s3, s1, s5, s2]


def test_reducer_peaks_giveback_coverage_gaps_and_reconciliation():
    r = pc.reduce_session(_series(), execution_net=71.68)
    assert r["peakExecutableNet"]["value"] == 231.68 and r["peakExecutableNet"]["seq"] == 2, "the unknown-depth spike at seq 3 cannot be the executable peak"
    assert r["peakDisplayedNet"]["seq"] == 3 and r["peakDisplayedNet"]["value"] > 500
    assert r["givebackVsExecutablePeak"] == 160.0 and r["flatAtEnd"] is True and r["realizedNetFinal"] == 71.68
    assert r["coverage"]["scorable"] == 3 and r["coverage"]["unscorable"] == 1 and r["coverage"]["unscorableReasons"] == {"unknown": 1}
    assert r["coverage"]["gaps"] == [{"at": NOW + 120_000, "kind": "missing_samples", "from": 3, "to": 5, "missing": 1}] and r["coverage"]["recorderDrops"] == 1
    assert r["reconciliation"]["status"] == "ok"
    bad = pc.reduce_session(_series(), execution_net=60.0)
    assert bad["reconciliation"]["status"] == "error_unexplained_difference" and bad["reconciliation"]["difference"] == 11.68
    a = r["attributionAtExecutablePeak"][0]
    assert a["tradeInstance"] == "E1" and a["netAtPeak"] == 231.68 and a["finalNet"] is None, "a position that left the capture before its close is unknown, not reconstructed"
    assert pc.reduce_session([])["status"] == "no_snapshots"
    open_end = pc.reduce_session(_series()[:1] + _series()[1:2], execution_net=10.0)
    assert open_end["givebackVsExecutablePeak"] is None and open_end["reconciliation"]["status"] == "not_flat_at_last_snapshot"


def test_paired_exit_consumer_join_is_strict_on_trade_identity_and_time():
    snaps = sorted(_series(), key=lambda s: s["seq"])
    rows = [{"tradeInstance": "E1", "policy": "tp1-reclaim-runner-exit-v1", "signalTs": NOW + 31_000, "outcome": "scored", "dollarDelta": 12.0},
            {"tradeInstance": "OTHER", "policy": "tp1-reclaim-runner-exit-v1", "signalTs": NOW + 31_000, "outcome": "scored", "dollarDelta": 5.0},
            {"tradeInstance": "E1", "policy": "tp1-reclaim-runner-exit-v1", "signalTs": NOW - 1, "outcome": "scored", "dollarDelta": 1.0},
            {"tradeInstance": "E1", "policy": "small-position-exit-v1", "signalTs": NOW + 130_000, "outcome": "scored", "dollarDelta": 9.0}]
    out = pc.summarize_paired(rows, snaps)
    ctx = [r["bookContext"] for r in out["rows"]]
    assert ctx[0]["seq"] == 2 and ctx[0]["status"] == "covered" and ctx[0]["bookScorable"] is True
    assert ctx[1] is None, "a wrong trade instance never borrows another trade's book context"
    assert ctx[2] is None, "no snapshot at or before the signal = unknown"
    assert ctx[3] is None, "after the baseline position closed there is no position to liquidate - nothing is computed"
    assert out["withBookContext"] == 1 and out["total"] == 4


# ---------------------------------------------------------------------------------------- EM-owned table (Postgres)
@pytest.mark.usefixtures("fresh_db")
async def test_the_recorder_writes_the_em_owned_table():
    from sqlalchemy import select
    from tests.conftest import TEST_DB_URL
    from zargar.db import make_engine, make_session_factory
    from zargar.models import TechniqueBookSnapshot
    eng = make_engine(TEST_DB_URL)
    sf = make_session_factory(eng)
    settings = {rt.KNOB: True, "techniques.enhanced_market.default_portfolio": "book"}
    armer = SimpleNamespace(_armed={}, engine=SimpleNamespace(sf=sf, settings=SimpleNamespace(get=lambda k, d=None: settings.get(k, d)), quotes=SimpleNamespace(get=lambda s: None),
                                                              positions=SimpleNamespace(portfolio=lambda pid: {"cash": 1.0})), rt=lambda k, d=None: d, _fees_paid=lambda tr: 0.0)
    obs = rt.build_observer(armer)
    assert obs.snap("periodic") is None
    rec = obs.snap("fill", {"kind": "stop", "runId": "run-1"})
    await obs.wait_idle()
    async with sf() as s:
        rows = (await s.execute(select(TechniqueBookSnapshot))).scalars().all()
    assert len(rows) == 1 and rows[0].reason == "fill" and rows[0].causal_run_id == "run-1" and rows[0].payload["version"] == "book-snapshot-v1"
    assert rows[0].portfolio_id == "book" and rows[0].seq == rec["seq"] and rows[0].scorable is True
    await eng.dispose()


# ---------------------------------------------------------- P-06 consumer: the sacrificed winner stays, fees reconcile
def test_p06_consumer_keeps_the_sacrificed_winner_and_reconciles_actual_fees_into_the_book_join():
    import datetime as dt
    from zoneinfo import ZoneInfo
    from zargar.tools.em_profitability import runner_protection
    ny = ZoneInfo("America/New_York")
    ms = lambda h, m, s=0: int(dt.datetime(2026, 9, 17, h, m, s, tzinfo=ny).timestamp() * 1000)          # noqa: E731
    bar = lambda ts, o, h, l, c: {"ts": ts, "open": o, "high": h, "low": l, "close": c}                  # noqa: E731
    ex = lambda oid, ts, q, px, fee: {"order_id": oid, "side": "SELL", "qty": q, "price": px, "commission": fee, "ts": ts}   # noqa: E731
    bars = [bar(ms(9, 31), 23.6, 23.62, 23.3, 23.34), bar(ms(9, 32), 23.35, 23.6, 23.33, 23.55), bar(ms(9, 33), 23.54, 23.7, 23.5, 23.65)]
    bars += [bar(ms(9, 34) + i * 60000, 23.4, 23.45, 22.6, 22.7) for i in range(30)]                     # the runner went on to WIN for production
    exits = [{"kind": "tp1", "orderId": "o-tp1", "qty": 1}, {"kind": "tp2", "orderId": "o-tp2", "qty": 3}]
    execs = [ex("o-tp1", ms(9, 32, 1), 1, 0.80, 1.04), ex("o-tp2", ms(9, 53, 26), 3, 1.60, 3.12)]        # production sold the runner at 1.60
    sym, inst = "BMNR260925P00023000", "ENTRY-1"
    obs = [{"rung": "tp1-reclaim", "tradeInstance": inst, "observedAt": ms(9, 33, 2), "disposition": "observed", "contract": {"symbol": sym, "sourceTs": ms(9, 33, 1), "bid": 0.78, "ask": 0.83},
            "signal": {"barTs": ms(9, 32)}, "modeled": {"scorable": True, "bid": 0.78, "coveredQty": 3}}]
    r = runner_protection("short", 23.3548, 23.5906, 23.7501, exits, execs, bars, ms(16, 0), observations=obs, filled_qty=4, multiplier=100.0, instrument="options",
                          avg_fill=0.86, entry_fee_per_unit=1.04, fee_side=1.04, entry_order_id=inst, contract_symbol=sym, opened_ts=ms(9, 31), closed_ts=ms(9, 53, 26))
    prod = 3 * ((1.60 - 0.86) * 100 - 1.04) - 3.12                                                      # actual fees: entry per unit + the real exit commission
    assert r["outcome"] == "compared" and r["productionRealized"] == round(prod, 2) and r["dollarDelta"] < 0, "the alternative SACRIFICED a winner - the row stays in the comparison"
    snap = _book([_pos(sym=sym, remaining=3, original=4, avg=0.86, realized=-6.0, fees=5.20, ti=inst)], {sym: {**_q(0.78, 0.83), "sourceTs": ms(9, 32, 59)}}, now_ms=ms(9, 33, 0), seq=7)   # captured AT the signal, never after it
    joined = pc.summarize_paired([{"tradeInstance": inst, "policy": r["policy"], "signalTs": r["signalTs"], "outcome": r["outcome"], "dollarDelta": r["dollarDelta"]}], [snap])
    ctx = joined["rows"][0]["bookContext"]
    assert joined["withBookContext"] == 1 and ctx["seq"] == 7 and ctx["status"] == "covered" and joined["rows"][0]["dollarDelta"] == r["dollarDelta"]
    assert ctx["netCovered"] == round(3 * ((0.78 - 0.86) * 100) - 3 * 1.04, 4), "the book's covered estimate uses the SAME bid and the modeled exit fee once"
