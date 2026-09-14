"""A scaled-in position (several same-symbol legs) must close FLAT with exactly
one exit per leg, and a reduce-only exit must never take the venue book through
zero. Regression for APLD 2026-09-14 (shadow book "ab"): the second leg's stop
fill was applied to the first, already-flat leg and flipped it back open, so the
quote-stop watch re-fired every tick — 3,282 exits, 37,625 shares short."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.domain import Quote
from zargar.execution.positions import Leg, Managed, PositionManager


def _pos():
    return Managed(id="apld", portfolio_id="shadow-ab", symbol="APLD", direction="long",
                   technique="tip", policy={"stop": {"kind": "fixed", "price": 25.568}},
                   entry=26.995, risk=2.18,
                   legs=[Leg("APLD", "STK", 35, avg_fill=28.03, entry_order_id="e1", origin="adoption"),
                         Leg("APLD", "STK", 35, avg_fill=25.96, entry_order_id="e2", origin="adoption")])


def _rig(venue_qty):
    book = {"APLD": float(venue_qty)}
    placed = []
    n = {"i": 0}

    async def place(intent):
        n["i"] += 1
        oid = f"o{n['i']}"
        placed.append(intent)
        book["APLD"] += intent.qty if intent.side == "BUY" else -intent.qty     # the sim fills at once
        return {"id": oid, "status": "FILLED", "filledQty": intent.qty, "avgFillPrice": 24.64,
                "symbol": intent.symbol}

    eng = NS(settings={},
             quotes=NS(get=lambda s: Quote(symbol=s, bid=24.6, ask=24.7, last=24.65, ts=0)),
             orders=NS(place=place, cancel=AsyncMock()),
             positions=NS(positions_list=lambda pid: [{"symbol": "APLD", "qty": book["APLD"]}]))
    m = PositionManager(eng)
    m._persist = AsyncMock()
    m._journal = AsyncMock()
    m._alert = AsyncMock()
    return m, placed, book


async def test_two_same_symbol_legs_close_flat_with_one_exit_each():
    m, placed, book = _rig(70)
    p = _pos()
    m._pos[p.id] = p
    out = await m.close(p.id, fraction=1.0, kind="stop", force_market=True, reason="quote breach")
    assert len(placed) == 2 and all(i.side == "SELL" and i.qty == 35 for i in placed)
    assert [l.qty for l in p.legs] == [0.0, 0.0], "both legs reduced toward flat, none flipped open"
    assert p.status == "closed" and book["APLD"] == 0.0 and out["status"] == "closed"
    assert p.id not in m._pos
    # nothing is left to re-fire: a second close is a no-op
    assert await m.close(p.id, fraction=1.0, kind="stop", force_market=True, reason="again") is None
    assert len(placed) == 2


async def test_partial_fill_spills_across_legs_without_overshoot():
    m, placed, book = _rig(70)
    p = _pos()
    m._pos[p.id] = p
    m._order_index = {"x": p.id}
    p.exits.append({"kind": "stop", "leg": "APLD", "qty": 50.0, "orderId": "x", "status": "ACCEPTED",
                    "filledQty": 0.0, "price": None, "ts": 0, "reason": "t"})
    await m.on_order_update({"id": "x", "status": "PARTIALLY_FILLED", "filledQty": 50.0,
                             "avgFillPrice": 24.6, "symbol": "APLD"})
    assert [l.qty for l in p.legs] == [0.0, 20.0]
    assert p.status != "closed" and not p.attention


async def test_exit_fill_beyond_open_legs_is_flagged_not_applied():
    m, placed, book = _rig(70)
    p = _pos()
    m._pos[p.id] = p
    m._order_index = {"x": p.id}
    p.exits.append({"kind": "stop", "leg": "APLD", "qty": 90.0, "orderId": "x", "status": "ACCEPTED",
                    "filledQty": 0.0, "price": None, "ts": 0, "reason": "t"})
    await m.on_order_update({"id": "x", "status": "FILLED", "filledQty": 90.0,
                             "avgFillPrice": 24.6, "symbol": "APLD"})
    assert [l.qty for l in p.legs] == [0.0, 0.0], "legs stop at flat"
    assert any("exceeded the open legs by 20" in a for a in p.attention)
    assert m._alert.await_count == 1


async def test_reduce_only_exit_never_sells_what_the_venue_does_not_hold():
    """The restored runaway position: legs say 35+35, the venue already holds
    -37,625. No order may be placed; the record closes on attention."""
    m, placed, book = _rig(-37625)
    p = _pos()
    m._pos[p.id] = p
    out = await m.close(p.id, fraction=1.0, kind="stop", force_market=True, reason="quote breach")
    assert placed == [] and book["APLD"] == -37625.0
    assert p.status == "closed" and [l.qty for l in p.legs] == [0.0, 0.0]
    assert any("venue already held nothing to reduce" in a for a in p.attention)
    assert out["status"] == "closed"


async def test_exit_clamped_to_the_venue_quantity():
    m, placed, book = _rig(50)          # the venue holds 50 of the 70 we think we have
    p = _pos()
    m._pos[p.id] = p
    await m.close(p.id, fraction=1.0, kind="stop", force_market=True, reason="quote breach")
    assert [i.qty for i in placed] == [35.0, 15.0] and book["APLD"] == 0.0
    assert p.status == "closed"


async def test_unknown_venue_line_never_blocks_a_protective_exit():
    m, placed, book = _rig(70)
    m.engine.positions = NS(positions_list=lambda pid: [])          # nothing known about APLD
    p = _pos()
    m._pos[p.id] = p
    await m.close(p.id, fraction=1.0, kind="stop", force_market=True, reason="quote breach")
    assert len(placed) == 2 and p.status == "closed"
