"""ED-04 `book-snapshot-v2` (integrated plan E; candidate review IR-02 + IR-03, 2026-09-19): pure capture with validated
provenance and book-wide depth allocation, the execution ledger, the bounded idempotent recorder, the runner boundary, and -
through the ACTUAL runtime collector and Postgres storage - restart / disarm / prior-session / duplicate-write cases.
No engine start, no orders, no model."""
import asyncio
import datetime as dt
import inspect
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from zargar.execution.planrunner import PlanRunner
from zargar.technique import profit_capture as pc
from zargar.technique import profit_capture_runtime as rt

NY = ZoneInfo("America/New_York")
DAY = "2026-09-17"
WINDOW = rt.session_window(DAY)


def ms(h, m, s=0, day=17):
    return int(dt.datetime(2026, 9, day, h, m, s, tzinfo=NY).timestamp() * 1000)


NOW = ms(10, 0)
IDS = {"portfolioId": "book", "session": DAY, "build": "abc", "baseline": "em-practice-baseline", "policy": {}}
SYM = "BMNR260925P00023000"


def _pos(sym=SYM, inst="options", remaining=4, pending=0, avg=1.00, original=4, ti="E1"):
    return {"runId": "r1", "trigger": "d1", "tradeInstance": ti, "symbol": sym, "underlying": sym[:4], "direction": "short", "instrument": inst,
            "multiplier": (100.0 if inst == "options" else 1.0), "positionSide": "long", "original": original, "remaining": remaining,
            "pendingExit": pending, "avgFill": avg}


def _q(bid, ask, bsz=10, asz=10, age=500, source="opra", sym=SYM, unit="contracts", now=NOW, **kw):
    return {"symbol": sym, "bid": bid, "ask": ask, "last": (bid + ask) / 2, "bidSize": bsz, "askSize": asz, "sizeUnit": unit, "source": source,
            "quoteTs": now - age, "receivedTs": now - 100, **kw}


def _ex(oid, sym, side, qty, px, fee, ts):
    return {"orderId": oid, "symbol": sym, "side": side, "qty": qty, "price": px, "commission": fee, "tsMs": ts}


ENTRY = [_ex("E1", SYM, "BUY", 4, 1.00, 4.16, ms(9, 40))]


def _book(positions, quotes, *, execs=ENTRY, now=NOW, **kw):
    base = dict(ids=IDS, seq=1, now_ms=now, reason="periodic", causal=None, cash=9000.0, positions=positions, quotes=quotes, fee_per_contract=1.04,
                instance="obs-1", ledger=pc.build_ledger(execs, window=WINDOW, as_of_ms=now))
    return pc.capture_book(**{**base, **kw})


# ----------------------------------------------------------------------------------------------------- pure capture
def test_a_midpoint_spike_is_not_executable_value_and_spread_is_never_deducted_twice():
    b = _book([_pos()], {SYM: _q(1.10, 1.90)})                                      # a wide book: mid 1.50
    p = b["positions"][0]
    assert p["mark"] == {"basis": "mid", "price": 1.5, "displayedUnrealized": 200.0}
    assert p["executable"]["status"] == "covered" and p["executable"]["price"] == 1.10
    assert p["executable"]["grossCovered"] == 40.0 and p["executable"]["feeModeled"] == 4.16 and p["executable"]["netCovered"] == 35.84
    assert b["book"]["realizedNet"] == -4.16 and b["book"]["displayedNet"] == 195.84 and b["book"]["executableTotalNet"] == 31.68 and b["book"]["scorable"] is True


def test_reviewer_reproduction_1_an_unknown_source_is_never_scorable():
    b = _book([_pos()], {SYM: _q(1.4, 1.5, source="")})
    assert "source_unknown" in b["positions"][0]["executable"]["reasons"] and b["book"]["scorable"] is False and b["book"]["executableTotalNet"] is None
    assert b["positions"][0]["quote"]["source"] is None, "an absent source stays absent - it is never relabelled"


def test_reviewer_reproduction_2_displayed_depth_is_spent_once_across_the_book():
    lots = [_pos(remaining=2, original=2, ti="E1"), _pos(remaining=2, original=2, ti="E2")]
    execs = [_ex("E1", SYM, "BUY", 2, 1.0, 2.08, ms(9, 40)), _ex("E2", SYM, "BUY", 2, 1.0, 2.08, ms(9, 41))]
    b = _book(lots, {SYM: _q(1.4, 1.5, bsz=2)}, execs=execs)
    a, c = b["positions"]
    assert (a["executable"]["status"], a["executable"]["coveredQty"]) == ("covered", 2.0), "deterministic: the first trade instance is served first"
    assert (c["executable"]["status"], c["executable"]["coveredQty"], c["executable"]["uncoveredQty"]) == ("partial", 0.0, 2.0)
    assert b["book"]["scorable"] is False and b["depthAllocation"] == [{"symbol": SYM, "side": "bid", "displayed": 2.0, "pendingReserved": 0.0, "unspent": 0.0}]
    enough = _book(lots, {SYM: _q(1.4, 1.5, bsz=4)}, execs=execs)
    assert enough["book"]["scorable"] is True and [p["executable"]["coveredQty"] for p in enough["positions"]] == [2.0, 2.0]
    pend = _book([_pos(remaining=2, original=2, pending=1, ti="E1"), _pos(remaining=2, original=2, ti="E2")], {SYM: _q(1.4, 1.5, bsz=3)}, execs=execs)
    assert pend["depthAllocation"][0]["pendingReserved"] == 1.0 and [p["executable"]["coveredQty"] for p in pend["positions"]] == [1.0, 1.0], "a pending exit consumes depth too"


@pytest.mark.parametrize("quote,reason", [
    (_q(1.4, 1.5, age=11_000), "stale_quote"),
    (_q(1.4, 1.5, source="chain"), "delayed_quote"),
    (_q(1.4, 1.5, source="derived:chain", transform="recenter-v1"), "derived_quote"),
    (_q(1.4, 1.5, source="somefeed"), "source_not_admissible"),
    (_q(1.4, 1.5, bsz=None), "size_unknown"),
    (_q(1.4, 1.5, bsz=0), "size_unknown"),
    (_q(1.4, 1.5, unit=None), "size_unit_unknown"),
    (_q(1.6, 1.5), "crossed_book"),
    (_q(0.0, 1.5), "one_sided_book"),
    (_q(float("nan"), 1.5), "non_finite_price"),
    (_q(1.4, 1.5, sym="OTHER260925P00023000"), "quote_identity_mismatch"),
    (_q(1.4, 1.5, session="post"), "outside_regular_session"),
    (_q(1.4, 1.5, halted=True), "halted"),
    ({**_q(1.4, 1.5), "quoteTs": 0}, "venue_quote_time_unknown"),
    ({**_q(1.4, 1.5), "quoteTs": NOW + 5000}, "venue_quote_time_in_future"),
    (None, "no_quote"),
])
def test_anything_short_of_validated_venue_evidence_is_unknown_and_never_makes_a_peak(quote, reason):
    b = _book([_pos()], {SYM: quote})
    e = b["positions"][0]["executable"]
    assert e["status"] == "unknown" and reason in e["reasons"] and e["netCovered"] is None and e["coveredQty"] == 0
    assert b["book"]["scorable"] is False and b["book"]["executableTotalNet"] is None
    assert pc.reduce_session([b])["peakExecutableNet"] is None


def test_pending_quantities_are_conserved_and_a_skewed_or_share_basket_needs_the_same_proof():
    p = _book([_pos(pending=3)], {SYM: _q(1.4, 1.5, bsz=50)})
    assert p["positions"][0]["quantities"] == {"original": 4.0, "remaining": 4.0, "pendingExit": 3.0, "reserved": 1.0}
    assert p["positions"][0]["executable"]["coveredQty"] == 1.0 and p["positions"][0]["mark"]["displayedUnrealized"] == 180.0 and p["book"]["scorable"] is False
    pos = [_pos(), _pos(sym="FSLR", inst="shares", remaining=25, original=25, avg=196.0, ti="E2")]
    execs = ENTRY + [_ex("E2", "FSLR", "BUY", 25, 196.0, 0.0, ms(9, 45))]
    fslr = lambda **kw: _q(197.0, 197.05, **{"bsz": 300, "source": "feed:HybridQuoteFeed", "sym": "FSLR", "unit": "shares", **kw})          # noqa: E731
    assert _book(pos, {SYM: _q(1.4, 1.5), "FSLR": fslr()}, execs=execs)["book"]["scorable"] is True
    skew = _book(pos, {SYM: _q(1.4, 1.5, age=200), "FSLR": fslr(age=7000)}, execs=execs)
    assert skew["book"]["scorable"] is False and skew["book"]["quoteSkewMs"] == 6800 and skew["book"]["coveredPartialNet"] > 0 and skew["book"]["executableTotalNet"] is None
    assert _book(pos, {SYM: _q(1.4, 1.5), "FSLR": fslr(bsz=None)}, execs=execs)["book"]["scorable"] is False
    assert _book(pos, {SYM: _q(1.4, 1.5), "FSLR": fslr(source="feed:YahooQuoteFeed")}, execs=execs)["book"]["scorable"] is False, "a feed with no venue bid/ask is never executable evidence"


# -------------------------------------------------------------------------------------------------- execution ledger
def test_the_ledger_is_executions_only_excludes_prior_sessions_and_keeps_per_trade_attribution():
    ex = [_ex("OLD", "AAPL", "BUY", 10, 100.0, 0.0, ms(10, 0, day=16)), _ex("OLDX", "AAPL", "SELL", 10, 90.0, 0.0, ms(11, 0, day=16)),   # yesterday: excluded
          _ex("E1", SYM, "BUY", 4, 1.00, 4.16, ms(9, 40)), _ex("X1", SYM, "SELL", 1, 1.50, 1.04, ms(9, 50)), _ex("X2", SYM, "SELL", 3, 0.60, 3.12, ms(10, 5)),
          _ex("E2", "FSLR", "BUY", 25, 196.0, 0.0, ms(9, 45))]
    mid = pc.build_ledger(ex, window=WINDOW, as_of_ms=ms(9, 55))
    assert mid["status"] == "restored" and mid["executions"] == 3 and mid["openQty"] == {SYM: 3.0, "FSLR": 25.0}
    assert mid["openTrades"]["E1"]["realizedGross"] == 50.0 and mid["realizedNet"] == round(50.0 - 5.20, 4)
    end = pc.build_ledger(ex, window=WINDOW)
    c = end["closedTrades"][0]
    assert (c["tradeInstance"], c["gross"], c["fees"], c["net"], c["orders"]) == ("E1", -70.0, 8.32, -78.32, ["E1", "X1", "X2"])
    assert end["fees"] == 8.32 and end["realizedNet"] == -78.32 and end["openQty"] == {"FSLR": 25.0}
    assert end["cashFlow"] == round(-400 - 4.16 + 150 - 1.04 + 180 - 3.12 - 4900, 4)
    bad = pc.build_ledger([_ex("X9", SYM, "SELL", 1, 1.0, 1.04, ms(9, 50))], window=WINDOW)
    assert bad["status"] == "unreconciled" and bad["errors"] == [f"sell_without_session_buy:{SYM}"]


def test_a_ledger_that_is_pending_wrong_or_inconsistent_with_the_held_quantity_is_never_scorable():
    pending = pc.capture_book(ids=IDS, seq=1, now_ms=NOW, reason="periodic", causal=None, cash=1.0, positions=[_pos()], quotes={SYM: _q(1.4, 1.5)}, fee_per_contract=1.04)
    assert pending["ledger"]["status"] == "pending" and pending["book"]["scorable"] is False and pending["book"]["realizedNet"] is None
    assert "ledger_pending" in pending["book"]["unscorableReasons"]
    done = pc.finalize_book(pending, pc.build_ledger(ENTRY, window=WINDOW, as_of_ms=NOW))
    assert done["book"]["scorable"] is True and done["book"]["realizedNet"] == -4.16
    lag = _book([_pos()], {SYM: _q(1.4, 1.5)}, execs=[])
    assert lag["book"]["scorable"] is False and any(r.startswith(f"ledger_position_mismatch:{SYM}") for r in lag["book"]["unscorableReasons"])
    assert _book([_pos()], {SYM: _q(1.4, 1.5)}, ledger={"status": "error"})["book"]["scorable"] is False


# ---------------------------------------------------------------------------------------------- the bounded recorder
def _observer(enabled=True, write=None, inputs=None, maxsize=256, cadence=30.0, clock=None, finalize="ledger"):
    clock = clock or [NOW]
    inputs = inputs if inputs is not None else (lambda: dict(ids=IDS, cash=9000.0, positions=[_pos()], quotes={SYM: _q(1.4, 1.5, now=clock[0])}, fee_per_contract=1.04))
    written, drops = [], []

    async def _w(rec):
        written.append(rec)

    async def _fin(rec):
        return pc.finalize_book(rec, pc.build_ledger(ENTRY, window=WINDOW, as_of_ms=rec["capturedAt"]))
    o = pc.ProfitCaptureObserver(enabled=lambda: enabled, collect=inputs, write=(write or _w), clock_ms=lambda: clock[0], cadence_s=lambda: cadence,
                                 finalize=(_fin if finalize == "ledger" else finalize), maxsize=maxsize, retry_sleep_s=0.0, on_drop=lambda why, rec: drops.append(why))
    return o, written, drops, clock


def test_off_by_default_records_nothing_and_collects_nothing():
    from zargar.settings_service import DEFAULTS
    assert DEFAULTS["techniques.enhanced_market.book_snapshot_observe"] is False
    o, _, _, _ = _observer(enabled=False, inputs=lambda: (_ for _ in ()).throw(AssertionError("must not collect")))
    assert o.snap("pre_stop") is None and o.stats["captured"] == 0


def test_snap_is_synchronous_the_ledger_is_attached_off_path_and_saturation_is_visible():
    gate = asyncio.Event()

    async def slow(rec):
        await gate.wait()

    async def run():
        o, _, drops, _ = _observer(write=slow, maxsize=2)
        assert not inspect.iscoroutinefunction(o.snap)
        recs = [o.snap("pre_stop", {"kind": "stop"}) for _ in range(5)]          # returns immediately, five times, with the writer blocked
        assert [r["seq"] for r in recs] == [1, 2, 3, 4, 5] and all(r["ledger"]["status"] == "pending" for r in recs), "phase 1 never touches the ledger"
        await asyncio.sleep(0)
        assert o.stats["droppedQueueFull"] >= 2 and drops[0] == "queue_full" and recs[-1]["recorder"]["droppedQueueFull"] >= 1
        gate.set()
        await o.wait_idle()
    asyncio.run(run())


def test_retries_keep_the_same_capture_id_and_a_failed_finalize_is_written_unscorable():
    ids = []

    async def bad(rec):
        ids.append(rec["captureId"])
        raise RuntimeError("db down")

    async def boom(rec):
        raise RuntimeError("ledger down")

    async def run():
        o, _, drops, _ = _observer(write=bad)
        o.snap("pre_target")
        await o.wait_idle()
        assert len(ids) == 3 and len(set(ids)) == 1 and o.stats["droppedWriteFailed"] == 1 and drops == ["write_failed:RuntimeError"]
        o2, written, _, _ = _observer(finalize=boom)
        o2.snap("fill")
        await o2.wait_idle()
        assert written[0]["ledger"]["status"] == "error" and written[0]["book"]["scorable"] is False and o2.stats["finalizeErrors"] == 1
        assert o.instance != o2.instance, "every observer instance (a restart) has its own identity"
    asyncio.run(run())


def test_periodic_cadence_restore_marker_and_flat_book_rules():
    async def run():
        o, written, _, clock = _observer()
        assert o.snap("periodic")["reason"] == "restore" and o.snap("periodic") is None
        clock[0] += 31_000
        assert o.snap("periodic")["reason"] == "periodic" and o.snap("pre_stop")["reason"] == "pre_stop"
        flat = lambda: dict(ids=IDS, cash=9000.0, positions=[], quotes={}, fee_per_contract=1.04)   # noqa: E731
        o2, w2, _, _ = _observer(inputs=flat)
        assert o2.snap("periodic") is None, "a flat book records nothing periodic"
        assert o2.snap("fill", {"kind": "stop"})["book"]["openPositions"] == 0
        await o.wait_idle(); await o2.wait_idle()
        assert written[0]["book"]["scorable"] is True and w2[0]["ledger"]["status"] == "restored"
        assert w2[0]["book"]["scorable"] is False, "the ledger still holds the BMNR lot the flat collector did not report - a mismatch, visibly"
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
    PlanRunner._book_snap(SimpleNamespace(), "pre_stop")
    boom = SimpleNamespace(_book_observer=SimpleNamespace(snap=lambda *a: (_ for _ in ()).throw(RuntimeError("x"))))
    PlanRunner._book_snap(boom, "pre_stop", SimpleNamespace(run_id="r", symbol="S"), SimpleNamespace(trigger_id="t"), "stop")
    from zargar.execution.planrunner import _book_snap_family
    assert [_book_snap_family(k) for k in ("tp1", "tp3", "stop", "flatten", "disarm", "scratch")] == ["target", "target", "stop", "flatten", "flatten", "protection"]
    col = inspect.getsource(rt.collect_inputs)
    assert "await" not in col and "sf(" not in col and "execute(" not in col, "the synchronous collector never touches the database"


# ------------------------------------------------------------------------------------------------------- reducer
def _series():
    x1 = _ex("X1", SYM, "SELL", 4, 1.20, 4.16, ms(10, 2))
    s1 = _book([_pos()], {SYM: _q(1.10, 1.90)}, seq=1, now=NOW)                                                       # displayed 195.84 / executable 31.68
    s2 = _book([_pos()], {SYM: _q(1.60, 1.70, now=NOW + 30_000)}, seq=2, now=NOW + 30_000)                             # executable peak 231.68
    s3 = _book([_pos()], {SYM: _q(2.40, 2.60, bsz=None, now=NOW + 60_000)}, seq=3, now=NOW + 60_000)                   # bigger mark, UNKNOWN depth
    s5 = _book([], {}, seq=5, now=ms(10, 3), reason="fill", execs=ENTRY + [x1], cash=9000.0 + 480 - 4.16)
    for s, st in zip((s1, s2, s3, s5), (0, 0, 0, 1)):
        s["recorder"] = {"droppedQueueFull": st, "droppedWriteFailed": 0}
    return [s3, s1, s5, s2]


def test_reducer_peaks_attribution_from_executions_gaps_duplicates_and_full_reconciliation():
    series = _series()
    r = pc.reduce_session(series + [series[0]], execution_net=71.68, execution_fees=8.32)
    assert r["duplicatesIgnored"] == 1 and r["snapshots"] == 4
    assert r["peakExecutableNet"]["value"] == 231.68 and r["peakExecutableNet"]["seq"] == 2, "the unknown-depth spike at seq 3 cannot be the executable peak"
    assert r["peakDisplayedNet"]["seq"] == 3 and r["givebackVsExecutablePeak"] == 160.0 and r["flatAtEnd"] is True and r["realizedNetFinal"] == 71.68
    assert r["coverage"]["scorable"] == 3 and r["coverage"]["unscorableReasons"] == {"unknown": 1} and r["coverage"]["recorderDrops"] == 1
    assert r["coverage"]["gaps"] == [{"at": ms(10, 3), "kind": "missing_samples", "from": 3, "to": 5, "missing": 1}]
    a = r["attributionAtExecutablePeak"][0]
    assert (a["tradeInstance"], a["netAtPeak"], a["finalNet"], a["giveback"], a["feesAfterPeak"]) == ("E1", 231.68, 71.68, 160.0, 4.16), "the closed trade comes from EXECUTIONS"
    rec = r["reconciliation"]
    assert rec["status"] == "ok" and rec["difference"] == 0.0 and rec["feesDifference"] == 0.0 and rec["sumOfClosedTrades"] == 71.68 and rec["cashMinusLedgerFlow"] == 0.0
    assert pc.reduce_session(series, execution_net=60.0, execution_fees=8.32)["reconciliation"]["status"] == "error_unexplained_difference"
    assert pc.reduce_session(series, execution_net=71.68, execution_fees=8.32, transfers=500.0)["reconciliation"]["status"] == "error_unexplained_difference", "a transfer is never a trading gain"
    assert pc.reduce_session([])["status"] == "no_snapshots"
    other = {**series[1], "recorderInstance": "obs-2", "captureId": "zzz", "seq": 1, "capturedAt": NOW + 45_000}
    assert any(g["kind"] == "recorder_restart" for g in pc.reduce_session(series + [other])["coverage"]["gaps"])


def test_paired_exit_consumer_join_is_strict_on_trade_identity_and_time():
    snaps = [_book([_pos()], {SYM: _q(1.10, 1.90)}, seq=1), _book([_pos()], {SYM: _q(1.60, 1.70, now=NOW + 30_000)}, seq=2, now=NOW + 30_000),
             _book([], {}, seq=3, now=ms(10, 3), reason="fill", execs=ENTRY + [_ex("X1", SYM, "SELL", 4, 1.2, 4.16, ms(10, 2))])]
    rows = [{"tradeInstance": "E1", "policy": "tp1-reclaim-runner-exit-v1", "signalTs": NOW + 31_000, "outcome": "compared", "dollarDelta": -12.0},
            {"tradeInstance": "OTHER", "signalTs": NOW + 31_000}, {"tradeInstance": "E1", "signalTs": NOW - 1}, {"tradeInstance": "E1", "signalTs": ms(10, 4)}]
    out = pc.summarize_paired(rows, snaps)
    ctx = [r["bookContext"] for r in out["rows"]]
    assert ctx[0]["seq"] == 2 and ctx[0]["status"] == "covered" and out["rows"][0]["dollarDelta"] == -12.0, "a sacrificed winner stays in the comparison"
    assert ctx[1] is None and ctx[2] is None and ctx[3] is None and out["withBookContext"] == 1


# ------------------------------------------------- the ACTUAL runtime collector + Postgres storage (IR-03 acceptance)
def _trade(ti, sym, *, filled, remaining, avg, inst="options"):
    return SimpleNamespace(trigger_id="d1", filled_qty=filled, remaining=remaining, pending_exit_qty=0, realized_pnl=123456.0, entry_order_id=ti, instrument=inst,
                           order_symbol=(sym if inst == "options" else None), direction="short", multiplier=(100.0 if inst == "options" else 1.0), avg_fill=avg)


CASH = [9000.0]


def _armer(sf, plans, quotes):
    settings = {rt.KNOB: True, "techniques.enhanced_market.default_portfolio": "book", "options.fee_per_contract": 0.99, "sim.reg_fee_per_contract": 0.05}

    def mk(rid, sym, trs, plan_for=DAY, pid="book"):
        return SimpleNamespace(run_id=rid, symbol=sym, plan_for=plan_for, config=SimpleNamespace(portfolio_id=pid), trades=dict(enumerate(trs)))
    return SimpleNamespace(_armed={k: mk(*v) for k, v in plans.items()},
                           engine=SimpleNamespace(sf=sf, feed=None, settings=SimpleNamespace(get=lambda k, d=None: settings.get(k, d)), quotes=SimpleNamespace(get=lambda s: quotes.get(s)),
                                                  positions=SimpleNamespace(portfolio=lambda pid: {"cash": CASH[0]})), rt=lambda k, d=None: d)


async def _seed(sf, rows, portfolio=False):
    from zargar.models import Execution, Order, Portfolio
    async with sf() as s:
        if portfolio:
            s.add(Portfolio(id="book", name="EM test", kind="sim", base_currency="USD", cash=10000.0))
            await s.flush()
        for oid, sym, side, qty, px, fee, ts in rows:
            s.add(Order(id=oid, portfolio_id="book", symbol=sym, sec_type=("OPT" if len(sym) > 6 else "STK"), side=side, qty=qty, order_type="MKT", status="FILLED"))
            await s.flush()
            s.add(Execution(id="x-" + oid, order_id=oid, portfolio_id="book", symbol=sym, side=side, qty=qty, price=px, commission=fee,
                            ts=dt.datetime.fromtimestamp(ts / 1000.0, dt.timezone.utc)))
        await s.commit()


@pytest.mark.usefixtures("fresh_db")
async def test_restart_disarm_prior_session_and_duplicate_writes_through_the_real_collector_and_storage(monkeypatch):
    from sqlalchemy import select
    from tests.conftest import TEST_DB_URL
    from zargar.db import make_engine, make_session_factory
    from zargar.models import TechniqueBookSnapshot
    eng = make_engine(TEST_DB_URL); sf = make_session_factory(eng)
    now = [ms(10, 30)]
    monkeypatch.setattr(rt.time, "time", lambda: now[0] / 1000.0)
    sbux, dram = "SBUX261002P00095000", "DRAM260921P00058000"
    await _seed(sf, [("P1", "AAPL", "BUY", 10, 100.0, 0.0, ms(10, 0, day=16)), ("P2", "AAPL", "SELL", 10, 90.0, 0.0, ms(11, 0, day=16)),     # PRIOR session: -100, must not count
                     ("A1", sbux, "BUY", 1, 1.05, 1.04, ms(9, 35)), ("A2", sbux, "SELL", 1, 0.23, 1.04, ms(9, 50)),                          # closed BEFORE the recorder started
                     ("B1", "FSLR", "BUY", 25, 196.0, 0.0, ms(9, 40)), ("B2", "FSLR", "SELL", 25, 194.111, 0.0, ms(10, 5)),                 # closed, its plan already DISARMED
                     ("C1", dram, "BUY", 4, 0.48, 4.16, ms(10, 20))], portfolio=True)                                                       # still open
    oq = SimpleNamespace(symbol=dram, bid=0.50, ask=0.55, last=0.52, bid_size=8, ask_size=9, source="opra", raw_source="", transform="", delayed=False,
                         source_ts=now[0] - 400, quote_ts=0, last_ts=0, ts=now[0] - 50, session="", halted=False)
    plans = {"a": ("a", "SBUX", [_trade("A1", sbux, filled=1, remaining=0, avg=1.05)]),                       # closed trade still in memory (its in-memory pnl is garbage on purpose)
             "old": ("old", "AAPL", [_trade("P1", "AAPL", filled=10, remaining=0, avg=100.0, inst="shares")], "2026-09-16"),   # PRIOR-session plan still in memory
             "c": ("c", "DRAM", [_trade("C1", dram, filled=4, remaining=4, avg=0.48)])}
    armer = _armer(sf, plans, {dram: oq})
    inp = rt.collect_inputs(armer, now[0])
    assert [p["tradeInstance"] for p in inp["positions"]] == ["C1"] and "realized_closed_net" not in inp, "realized results never come from memory"
    assert inp["quotes"][dram]["source"] == "opra" and inp["quotes"][dram]["quoteTs"] == now[0] - 400 and inp["quotes"][dram]["receivedTs"] == now[0] - 50
    obs = rt.build_observer(armer)
    first = obs.snap("periodic")
    await obs.wait_idle()
    # --- a RESTART: a new observer instance, the closed plan is gone from memory, one trade still open
    del armer._armed["a"]
    obs2 = rt.build_observer(armer)
    now[0] += 60_000
    oq.source_ts = now[0] - 300
    second = obs2.snap("periodic")
    await obs2.wait_idle()
    async with sf() as s:
        rows = (await s.execute(select(TechniqueBookSnapshot).order_by(TechniqueBookSnapshot.captured_at))).scalars().all()
    assert [r.reason for r in rows] == ["restore", "restore"] and rows[0].id == first["captureId"] and rows[1].id == second["captureId"]
    for r in rows:
        led = r.payload["ledger"]
        assert led["status"] == "restored" and led["executions"] == 5, "the prior session's two fills are outside the window"
        assert {c["tradeInstance"]: c["net"] for c in led["closedTrades"]} == {"A1": -84.08, "B1": -47.225}, "closed before the recorder started / already disarmed - recovered from executions"
        assert r.payload["book"]["realizedNet"] == round(-84.08 - 47.225 - 4.16, 4) and r.payload["book"]["feesPaid"] == 6.24 and r.scorable is True
    assert rows[0].payload["recorderInstance"] != rows[1].payload["recorderInstance"]
    red = pc.reduce_session([r.payload for r in rows])
    assert red["coverage"]["recorderInstances"] == 2 and any(g["kind"] == "recorder_restart" for g in red["coverage"]["gaps"])
    # --- an ambiguous acknowledgement: the SAME observation written again is acknowledged once
    await obs2._write(rows[1].payload); await obs2._write(rows[1].payload)
    async with sf() as s:
        assert len((await s.execute(select(TechniqueBookSnapshot))).scalars().all()) == 2
    # --- the flat endpoint reconciles to executions, per trade, fees once
    await _seed(sf, [("C2", dram, "SELL", 4, 0.24, 4.16, now[0] + 30_000)])
    armer._armed["c"].trades[0].remaining = 0
    CASH[0] += 4 * 0.24 * 100 - 4.16                       # the keeper's cash moves with the fill; a cash move the ledger cannot explain is an ERROR
    now[0] += 90_000
    end = obs2.snap("fill", {"kind": "stop", "runId": "c"})
    await obs2.wait_idle()
    async with sf() as s:
        payloads = [r.payload for r in (await s.execute(select(TechniqueBookSnapshot).order_by(TechniqueBookSnapshot.captured_at))).scalars().all()]
    assert end["captureId"] == payloads[-1]["captureId"] and payloads[-1]["book"]["openPositions"] == 0
    total_net, total_fees = round(-84.08 - 47.225 - 104.32, 4), round(2.08 + 0.0 + 8.32, 4)
    final = pc.reduce_session(payloads, execution_net=total_net, execution_fees=total_fees)
    assert final["realizedNetFinal"] == total_net and final["reconciliation"]["status"] == "ok" and final["reconciliation"]["feesDifference"] == 0.0
    assert {c["tradeInstance"]: c["net"] for c in final["closedTrades"]} == {"A1": -84.08, "B1": -47.225, "C1": -104.32}
    assert final["reconciliation"]["cashMinusLedgerFlow"] == 0.0
    CASH[0] += 250.0                                       # an unexplained deposit
    again = obs2.snap("fill", {"kind": "none"})
    await obs2.wait_idle()
    async with sf() as s:
        payloads2 = [r.payload for r in (await s.execute(select(TechniqueBookSnapshot).order_by(TechniqueBookSnapshot.captured_at))).scalars().all()]
    assert again is not None and pc.reduce_session(payloads2, execution_net=total_net, execution_fees=total_fees)["reconciliation"]["status"] == "error_unexplained_difference"
    assert pc.reduce_session(payloads2, execution_net=total_net, execution_fees=total_fees, transfers=250.0)["reconciliation"]["status"] == "ok", "a declared transfer is excluded, never a gain"
    peak = final["attributionAtExecutablePeak"][0]
    assert peak["tradeInstance"] == "C1" and peak["finalNet"] == -104.32 and peak["basis"].startswith("executions")
    await eng.dispose()
