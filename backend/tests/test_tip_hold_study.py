"""PROF-03 (2026-09-15): overnight-hold comparison arithmetic and collection.
Research only - nothing here places an order or touches a position's exits."""
import datetime as dt

from zargar.techniques.tip import holdstudy as hs


def _row(**kw):
    base = {"id": "r1", "positionId": "p1", "arm": "carry", "symbol": "XYZ", "legSymbol": "XYZ260101C00100000", "secType": "OPT",
            "qty": 2, "entryPrice": 1.50, "multiplier": 100.0, "plannedRisk": 150.0, "dteAtSnapshot": 10,
            "precloseQuote": {"bid": 1.40, "ask": 1.50}, "precloseStatus": "fresh",
            "nextOpenQuote": {"bid": 1.80, "ask": 1.90}, "nextOpenStatus": "fresh",
            "bookKind": "sim", "quarantined": False}
    base.update(kw)
    return base


def test_missing_or_unqualified_quote_is_insufficient_evidence():
    r = hs.compare_row(_row(nextOpenQuote=None, nextOpenStatus="missing"))
    assert r["adequate"] is False and "next-open" in r["reason"]
    r2 = hs.compare_row(_row(precloseStatus="ineligible"))
    assert r2["adequate"] is False and "pre-close" in r2["reason"] and "ineligible" in r2["reason"]
    r3 = hs.compare_row(_row(nextOpenStatus="stale"))
    assert r3["adequate"] is False


def test_paired_arms_use_only_the_two_contemporaneous_bids_no_hindsight_peak():
    # pre-close bid 1.40 vs next-open bid 1.80 on 2 contracts at 1.50, $1 fee per contract
    # HOLD142-03: the entry fee (allocated per contract) AND the exit fee are both paid: 2 x 2 x $1
    r = hs.compare_row(_row(), fee_per_contract=1.0)
    assert r["adequate"] and r["intradayExit"]["net"] == round((1.40 - 1.50) * 200 - 4, 2) == -24.0
    assert r["carryToNextOpen"]["net"] == round((1.80 - 1.50) * 200 - 4, 2) == 56.0
    assert r["costs"] == {"entry": 2.0, "exit": 2.0, "total": 4.0, "basis": "per contract per side",
                          "notes": ["regulatory per-contract charges not supplied (0)"]}
    assert r["carryMinusIntraday"] == 80.0 and r["carryToNextOpen"]["R"] == round(56 / 150, 2)
    # the risk denominator follows the SAMPLED size: 1 of 2 contracts left after a trim
    half = hs.compare_row(_row(qty=1, entryQty=2, plannedRiskQty=2), fee_per_contract=1.0)
    assert half["riskForSample"] == 75.0 and half["costs"]["total"] == 2.0
    assert half["carryToNextOpen"]["net"] == round(0.30 * 100 - 2, 2) and half["carryToNextOpen"]["R"] == round(28 / 75, 2)
    # carry is quote drift; the strategy's own result is known only when its exit closed the position first
    assert r["managedCarry"] == {"known": False, "note": "still open at the next-open sample - the strategy's result is not yet known"}
    stopped = hs.compare_row(_row(carryOutcome={"closedBeforeSample": True, "exitPrice": 1.20, "closedAt": "x", "reason": "stop"}),
                             fee_per_contract=1.0)
    assert stopped["managedCarry"]["known"] and stopped["managedCarry"]["net"] == round(-0.30 * 200 - 4, 2)
    assert stopped["carryToNextOpen"]["net"] == 56.0, "the quote-drift number is reported as such, never as the strategy's"
    assert "FIRST qualified bid" in r["note"]
    # a high print between the two observations is never used: only the two bids exist in the row
    assert set(r.keys()) >= {"intradayExit", "carryToNextOpen"} and "max" not in json_dumps(r).lower().replace("maxhold", "")


def json_dumps(x):
    import json
    return json.dumps(x)


def test_intraday_exit_arm_marks_a_sacrificed_next_day_winner():
    r = hs.compare_row(_row(arm="intraday_exit", exitPrice=1.55, nextOpenQuote={"bid": 2.00, "ask": 2.10}))
    assert r["managedCarry"] is None
    assert r["adequate"] and r["sacrificedWinner"] is True and r["intradayExit"]["price"] == 1.55
    r2 = hs.compare_row(_row(arm="intraday_exit", exitPrice=1.55, nextOpenQuote={"bid": 1.00, "ask": 1.10}))
    assert r2["sacrificedWinner"] is False


def test_aggregate_counts_insufficient_rows_and_picks_no_winner():
    rows = [hs.compare_row(_row(), fee_per_contract=1.0),
            hs.compare_row(_row(id="r2", nextOpenStatus="missing", nextOpenQuote=None)),
            hs.compare_row(_row(id="r3", secType="STK", legSymbol="XYZ", multiplier=1.0, qty=10, entryPrice=100.0,
                                plannedRisk=50.0, precloseQuote={"bid": 101.0}, nextOpenQuote={"bid": 99.0}))]
    agg = hs.aggregate(rows)
    opt = agg["setups"]["sim:option:short(<=14d)"]
    assert opt["n"] == 1 and opt["insufficient"] == 1 and opt["pairedDiffR"] is not None
    shares = agg["setups"]["sim:shares"]
    assert shares["n"] == 1 and shares["carryNet"] == -10.0 and shares["intradayNet"] == 10.0
    assert "no rule derived" in agg["disclaimer"] and "winner" not in json_dumps(agg)
    assert opt["managedKnown"] == 0 and opt["distinctPositions"] == 1 and "position-session" in agg["unit"]


def test_scope_provenance_is_never_assumed_practice():
    # HOLD-SCOPE-01/02: a quarantined shadow book is diagnostic, never adequate; missing provenance is unknown
    q = hs.compare_row(_row(bookKind="shadow", quarantined=True, quarantineReason="runaway short"))
    assert q["adequate"] is False and q["diagnosticOnly"] is True and q["eligibility"] == "quarantined" \
        and q["carryToNextOpen"]["net"] is not None
    att = hs.compare_row(_row(positionStatus="attention"))
    assert att["adequate"] is False and att["eligibility"] == "attention"
    unk = hs.compare_row(_row(quarantined=None))
    assert unk["adequate"] is False and unk["eligibility"] == "unknown"
    agg = hs.aggregate([hs.compare_row(_row()), q, att, unk])
    assert set(agg["setups"]) == {"sim:option:short(<=14d)", "shadow:option:short(<=14d)"}
    assert agg["setups"]["sim:option:short(<=14d)"]["n"] == 1 and agg["setups"]["sim:option:short(<=14d)"]["ineligible"] == 2
    assert agg["setups"]["shadow:option:short(<=14d)"]["n"] == 0 and agg["setups"]["shadow:option:short(<=14d)"]["ineligible"] == 1
    pooled = agg["pooledDiagnostic"]["option:short(<=14d)"]
    assert pooled["performance"] is False and "DIAGNOSTIC" in pooled["label"] and pooled["books"] == {"sim": 3, "shadow": 1}


def test_windows_follow_the_exchange_calendar():
    # a normal day closes 16:00 ET: the pre-close window is 15:45-16:00; Friday 2026-11-27 closes 13:00
    w = hs.preclose_window("2026-09-15")
    assert w["start"].endswith("T15:45:00-04:00") and w["end"].endswith("T16:00:00-04:00") and not w["earlyClose"]
    e = hs.preclose_window("2026-11-27")
    assert e["earlyClose"] and e["end"].endswith("T13:00:00-05:00") and e["start"].endswith("T12:45:00-05:00")
    assert hs.preclose_window("2026-09-19") is None and hs.preclose_window("2026-09-07") is None   # Saturday, Labor Day
    # the expected next session skips the weekend and the holiday
    assert hs.expected_next_session("2026-09-18") == "2026-09-21" and hs.expected_next_session("2026-09-04") == "2026-09-08"
    n = hs.next_open_window("2026-09-16")
    assert n["start"].endswith("T09:30:00-04:00") and n["end"].endswith("T09:45:00-04:00")
    tz = dt.timezone(dt.timedelta(hours=-4))
    assert hs.judge_window(dt.datetime(2026, 9, 15, 15, 30, tzinfo=tz), w) == "early"
    assert hs.judge_window(dt.datetime(2026, 9, 15, 15, 50, tzinfo=tz), w) == "inside"
    assert hs.judge_window(dt.datetime(2026, 9, 15, 16, 0, tzinfo=tz), w) == "late"
    assert hs.judge_window(dt.datetime(2026, 9, 15, 16, 0, tzinfo=tz), None) == "none"


def test_job_times_follow_the_exchange_calendar():
    # R147-01: the pre-close job runs relative to the EXCHANGE close, the next-open job at the window start
    assert hs.preclose_job_time("2026-09-15") == "15:50" and hs.preclose_job_time("2026-11-27") == "12:50"
    assert hs.preclose_job_time("2026-12-24", before_close_minutes=5) == "12:55"
    assert hs.next_open_job_time() == "09:30"
    from zargar.scheduler import Scheduler
    sch = Scheduler(engine=None)

    async def _noop():
        return 0
    sch.register("tip_hold_snapshot", lambda d: hs.preclose_job_time(d), _noop)
    sch.register("tip_hold_next_open", hs.next_open_job_time(), _noop)
    assert sch.resolve_at("tip_hold_snapshot", dt.date(2026, 11, 27)) == "12:50"
    assert sch.resolve_at("tip_hold_snapshot", dt.date(2026, 9, 16)) == "15:50"
    assert sch.resolve_at("tip_hold_next_open", dt.date(2026, 11, 27)) == "09:30"


async def test_preclose_snapshot_and_next_open_sample_touch_no_position(rig, monkeypatch):
    """On the real engine: an open Tips share position gets a carry snapshot with
    a qualified quote and a pending next-open sample; the next-open job fills
    it; the position's stop, exits and orders are untouched."""
    from sqlalchemy import select
    from zargar.models import Order, TipHoldSnapshotRow
    from .test_tip_geometry_wiring import _adopt_shares, _quote
    eng = rig
    q = await _quote(eng, "HOLDA")
    pos = await _adopt_shares(eng, "HOLDA", qty=10, stop=round(q.last * 0.95, 2))
    before_orders = len((await _orders(eng)))
    stop_before = eng.position_manager.get(pos["id"]).state.stop
    # a timely observation: inside the pre-close window of a trading day (Tue 2026-09-15 15:50 ET).
    # The real quote store stamps sampledAt with the wall clock; the pinned protocol clock
    # stands in for it here (the actual sample is 1 s after each pinned job start).
    et = dt.timezone(dt.timedelta(hours=-4))
    pin = {"t": None}
    real_snap = hs._snap

    def stamped(eng_, sym, **kw):
        q, st = real_snap(eng_, sym, **kw)
        if q is not None and pin["t"] is not None:
            q = {**q, "sampledAt": (pin["t"] + dt.timedelta(seconds=1)).isoformat()}
        return q, st
    monkeypatch.setattr(hs, "_snap", stamped)
    preclose_at = dt.datetime(2026, 9, 15, 15, 50, tzinfo=et)
    pin["t"] = preclose_at
    n = await hs.snapshot_preclose(eng, now=preclose_at)
    assert n >= 1
    assert await hs.snapshot_preclose(eng, now=preclose_at) == 0, "a repeated capture is the same observation"
    async with eng.sf() as session:
        rows = (await session.execute(select(TipHoldSnapshotRow).where(TipHoldSnapshotRow.position_id == pos["id"]))).scalars().all()
    assert len(rows) == 1 and rows[0].arm == "carry" and rows[0].preclose_status == "fresh" and rows[0].next_open_status == "pending"
    assert rows[0].planned_risk and rows[0].planned_risk > 0 and rows[0].planned_risk_qty == 10.0 and rows[0].entry_qty == 10.0
    assert rows[0].observation_key == hs.observation_key("2026-09-15", pos["id"], "HOLDA", "carry")
    assert rows[0].expected_next_session == "2026-09-16" and rows[0].window["verdict"] == "inside"
    assert rows[0].observed_at == preclose_at + dt.timedelta(seconds=1) and rows[0].window["jobStartedAt"] == preclose_at.isoformat()
    # too early on the expected session: nothing happens; inside the opening window: the first qualified quote
    pin["t"] = dt.datetime(2026, 9, 16, 9, 20, tzinfo=et)
    assert await hs.sample_next_open(eng, now=pin["t"]) == 0
    pin["t"] = dt.datetime(2026, 9, 16, 9, 36, tzinfo=et)
    m = await hs.sample_next_open(eng, now=pin["t"])
    assert m == 1
    async with eng.sf() as session:
        r = await session.get(TipHoldSnapshotRow, rows[0].id)
    assert r.next_open_status == "fresh" and r.next_open_quote and r.next_open_quote.get("bid")
    assert r.next_open_window["attempts"] == 1 and r.carry_outcome and r.carry_outcome["known"] is True \
        and r.carry_outcome["closedBeforeSample"] is False
    assert r.next_open_sampled_at == pin["t"] + dt.timedelta(seconds=1) and r.next_open_window["jobStartedAt"] == pin["t"].isoformat()
    cmp_ = hs.compare_row(hs.row_dict(r))
    assert cmp_["adequate"] is True and cmp_["managedCarry"]["known"] is False
    assert len(await _orders(eng)) == before_orders and eng.position_manager.get(pos["id"]).state.stop == stop_before
    assert rows[0].book_kind == "sim" and rows[0].portfolio_id == pos["portfolioId"]
    # a position that EXITED intraday is observed from the durable record (it has left manager memory)
    q2 = await _quote(eng, "HOLDB")
    pos2 = await _adopt_shares(eng, "HOLDB", qty=10, stop=round(q2.last * 0.95, 2))
    await eng.position_manager.close(pos2["id"], reason="test intraday exit")

    async def gone():
        return eng.position_manager.get(pos2["id"]) is None
    await wait_for(gone, timeout=10)
    # the exit happened at REAL time: observe on that date's pre-close window (a weekend
    # yields a recorded outside_window miss - still one observation, never repaired)
    close_day = dt.datetime.now(dt.timezone.utc).astimezone(et).date()
    n2 = await hs.snapshot_preclose(eng, now=dt.datetime.combine(close_day, dt.time(15, 50), tzinfo=et))
    assert n2 >= 1
    async with eng.sf() as session:
        ex = (await session.execute(select(TipHoldSnapshotRow).where(TipHoldSnapshotRow.position_id == pos2["id"]))).scalars().all()
    assert len(ex) == 1 and ex[0].arm == "intraday_exit" and ex[0].exit_price and ex[0].exit_price > 0 and ex[0].book_kind == "sim"
    assert ex[0].qty == 10.0 and ex[0].preclose_status in ("fresh", "stale", "ineligible", "missing", "outside_window", "late")


async def test_close_transition_is_capture_safe_at_the_persistence_boundary(rig, monkeypatch):
    """CAP187-01: a capture that runs exactly at the persistence boundary of a close (the
    manager is writing the closed state) still observes the exit - from memory, because
    the position is not dropped until the durable row carries it. Deterministic: the
    snapshot is invoked from inside the manager's own persist call for the closed
    transition, before the write happens."""
    from sqlalchemy import select
    from zargar.models import TipHoldSnapshotRow
    from .test_tip_geometry_wiring import _adopt_shares, _quote
    eng = rig
    mgr = eng.position_manager
    q = await _quote(eng, "HOLDC")
    pos = await _adopt_shares(eng, "HOLDC", qty=10, stop=round(q.last * 0.95, 2))
    et = dt.timezone(dt.timedelta(hours=-4))
    close_day = dt.datetime.now(dt.timezone.utc).astimezone(et).date()
    preclose_at = dt.datetime.combine(close_day, dt.time(15, 50), tzinfo=et)
    from zargar.models import ManagedPositionRow as ManagedPositionRow_
    real_persist = mgr._persist
    boundary: dict = {}

    async def persist_at_boundary(p):
        if p.id == pos["id"] and p.status == "closed" and "captured" not in boundary:
            # the boundary: closed in memory, durable row NOT yet written
            boundary["inMemory"] = mgr.get(p.id) is not None
            async with eng.sf() as session:
                row = await session.get(ManagedPositionRow_, p.id)
            boundary["durableStatus"] = row.status if row else None
            boundary["captured"] = await hs.snapshot_preclose(eng, now=preclose_at)
        await real_persist(p)
    monkeypatch.setattr(mgr, "_persist", persist_at_boundary)
    await mgr.close(pos["id"], reason="test boundary exit")

    async def gone():
        return mgr.get(pos["id"]) is None
    await wait_for(gone, timeout=10)
    assert boundary["inMemory"] is True and boundary["durableStatus"] != "closed"     # the boundary was real
    assert boundary["captured"] >= 1                                                  # and the capture saw the exit
    async with eng.sf() as session:
        ex = (await session.execute(select(TipHoldSnapshotRow).where(TipHoldSnapshotRow.position_id == pos["id"]))).scalars().all()
    assert len(ex) == 1 and ex[0].arm == "intraday_exit" and ex[0].exit_price and ex[0].exit_price > 0
    # after the boundary the durable record carries the close and a second capture adds nothing (one observation per key)
    async with eng.sf() as session:
        row = await session.get(ManagedPositionRow_, pos["id"])
    assert row.status == "closed" and (row.state or {}).get("closedMs")
    assert await hs.snapshot_preclose(eng, now=preclose_at) == 0


async def _orders(eng):
    from sqlalchemy import select
    from zargar.models import Order
    async with eng.sf() as session:
        return list((await session.execute(select(Order))).scalars().all())


from .test_proposal_readiness import rig  # noqa: E402,F401



async def test_slow_multi_row_capture_qualifies_only_rows_sampled_inside_the_window(review_engine, monkeypatch):
    """R147-01: a job that starts inside the window but whose later rows are
    sampled after the close keeps the early row qualified and marks the late
    row late - judged on each row's ACTUAL sample time."""
    from types import SimpleNamespace as NS
    from sqlalchemy import select
    from zargar.models import TipHoldSnapshotRow
    eng = review_engine
    pos = lambda i: {"id": f"position-{i}", "portfolioId": "practice", "technique": "tip", "status": "open",
                     "symbol": f"SYM{i}", "entry": 100, "direction": "long", "state": {"stop": 95},
                     "legs": [{"symbol": f"SYM{i}", "secType": "STK", "qty": 10, "avgFill": 100}],
                     "policy": {"stop": {"price": 95}, "time_stop_sessions": 5}, "tags": []}
    eng.position_manager = NS(positions=lambda: [pos(1), pos(2)])
    start = dt.datetime(2026, 9, 15, 19, 59, 30, tzinfo=dt.timezone.utc)           # 15:59:30 ET
    stamps = iter([start + dt.timedelta(seconds=10), start + dt.timedelta(seconds=40)])   # 15:59:40, 16:00:10

    def slow(*a, **kw):
        t = next(stamps)
        return ({"bid": 101, "ask": 102, "sampledAt": t.isoformat(), "sourceTs": int(t.timestamp() * 1000)}, "fresh")
    monkeypatch.setattr(hs, "_snap", slow)
    assert await hs.snapshot_preclose(eng, now=start) == 2
    async with eng.sf() as session:
        rows = {r.symbol: r for r in (await session.execute(select(TipHoldSnapshotRow))).scalars().all()}
    assert rows["SYM1"].preclose_status == "fresh" and rows["SYM1"].observed_at == start + dt.timedelta(seconds=10)
    assert rows["SYM2"].preclose_status == "late" and rows["SYM2"].observed_at == start + dt.timedelta(seconds=40)
    assert rows["SYM2"].preclose_quote is not None and "late, not protocol-qualified" in rows["SYM2"].gaps[-1]
    assert rows["SYM2"].window["jobStartedAt"] == start.isoformat() and rows["SYM2"].window["verdict"] == "late"
    assert hs.compare_row(hs.row_dict(rows["SYM2"]))["adequate"] is False


from .test_kfin_followup_boundaries_review import review_engine  # noqa: E402,F401

from .conftest import wait_for  # noqa: E402
