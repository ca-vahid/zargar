"""PROF-03 (2026-09-15): overnight-hold comparison arithmetic and collection.
Research only - nothing here places an order or touches a position's exits."""
import datetime as dt

from zargar.techniques.tip import holdstudy as hs


def _row(**kw):
    base = {"id": "r1", "positionId": "p1", "arm": "carry", "symbol": "XYZ", "legSymbol": "XYZ260101C00100000", "secType": "OPT",
            "qty": 2, "entryPrice": 1.50, "multiplier": 100.0, "plannedRisk": 150.0, "dteAtSnapshot": 10,
            "precloseQuote": {"bid": 1.40, "ask": 1.50}, "precloseStatus": "fresh",
            "nextOpenQuote": {"bid": 1.80, "ask": 1.90}, "nextOpenStatus": "fresh"}
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
    opt = agg["setups"]["option:short(<=14d)"]
    assert opt["n"] == 1 and opt["insufficient"] == 1 and opt["pairedDiffR"] is not None
    shares = agg["setups"]["shares"]
    assert shares["n"] == 1 and shares["carryNet"] == -10.0 and shares["intradayNet"] == 10.0
    assert "no rule derived" in agg["disclaimer"] and "winner" not in json_dumps(agg)
    assert opt["managedKnown"] == 0 and opt["distinctPositions"] == 1 and "position-session" in agg["unit"]


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


async def test_preclose_snapshot_and_next_open_sample_touch_no_position(rig):
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
    # a timely observation: inside the pre-close window of a trading day (Tue 2026-09-15 15:50 ET)
    et = dt.timezone(dt.timedelta(hours=-4))
    preclose_at = dt.datetime(2026, 9, 15, 15, 50, tzinfo=et)
    n = await hs.snapshot_preclose(eng, now=preclose_at)
    assert n >= 1
    assert await hs.snapshot_preclose(eng, now=preclose_at) == 0, "a repeated capture is the same observation"
    async with eng.sf() as session:
        rows = (await session.execute(select(TipHoldSnapshotRow).where(TipHoldSnapshotRow.position_id == pos["id"]))).scalars().all()
    assert len(rows) == 1 and rows[0].arm == "carry" and rows[0].preclose_status == "fresh" and rows[0].next_open_status == "pending"
    assert rows[0].planned_risk and rows[0].planned_risk > 0 and rows[0].planned_risk_qty == 10.0 and rows[0].entry_qty == 10.0
    assert rows[0].observation_key == hs.observation_key("2026-09-15", pos["id"], "HOLDA", "carry")
    assert rows[0].expected_next_session == "2026-09-16" and rows[0].window["verdict"] == "inside"
    # too early on the expected session: nothing happens; inside the opening window: the first qualified quote
    assert await hs.sample_next_open(eng, now=dt.datetime(2026, 9, 16, 9, 20, tzinfo=et)) == 0
    m = await hs.sample_next_open(eng, now=dt.datetime(2026, 9, 16, 9, 36, tzinfo=et))
    assert m == 1
    async with eng.sf() as session:
        r = await session.get(TipHoldSnapshotRow, rows[0].id)
    assert r.next_open_status == "fresh" and r.next_open_quote and r.next_open_quote.get("bid")
    assert r.next_open_window["attempts"] == 1 and r.carry_outcome and r.carry_outcome["known"] is True \
        and r.carry_outcome["closedBeforeSample"] is False
    cmp_ = hs.compare_row(hs.row_dict(r))
    assert cmp_["adequate"] is True and cmp_["managedCarry"]["known"] is False
    assert len(await _orders(eng)) == before_orders and eng.position_manager.get(pos["id"]).state.stop == stop_before


async def _orders(eng):
    from sqlalchemy import select
    from zargar.models import Order
    async with eng.sf() as session:
        return list((await session.execute(select(Order))).scalars().all())


from .test_proposal_readiness import rig  # noqa: E402,F401
