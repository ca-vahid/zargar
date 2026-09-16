"""Equity series downsampling.

2026-09-14: the chart asked for ~320 samples out of ~6,000 and got every Nth
one, so a real intraday spike (EM Practice touched 11,335 at 09:35) was in the
window on one load and gone on the next — and the high/low readout under the
chart printed whichever samples happened to survive.
"""
import random

import pytest

from zargar.models import EquityPoint, Portfolio
from zargar.portfolio import _decimate


def _series(n: int = 5000) -> list[list]:
    rnd = random.Random(7)
    pts = [[i * 30_000, 10_000 + rnd.random() * 10] for i in range(n)]
    if n > 1234:
        pts[1234][1] = 11_335.02      # the spike that went missing
    if n > 4321:
        pts[4321][1] = 9_010.00       # and a trough
    elif n > 900:
        pts[900][1] = 9_010.00
    return pts


def test_decimation_keeps_the_range():
    pts = _series()
    for budget in (60, 320, 720):
        out = _decimate(pts, budget)
        ys = [p[1] for p in out]
        assert max(ys) == 11_335.02, f"budget {budget} lost the high"
        assert min(ys) == 9_010.00, f"budget {budget} lost the low"


def test_decimation_keeps_time_order_and_both_ends():
    pts = _series()
    out = _decimate(pts, 320)
    assert out[0] == pts[0]
    assert out[-1] == pts[-1]                      # the live point is never dropped
    assert [p[0] for p in out] == sorted(p[0] for p in out)


def test_decimation_respects_the_budget():
    pts = _series()
    for budget in (60, 320, 720):
        # min/max decimation emits up to two per bucket, so the budget is a
        # target, not a ceiling — but it must stay in the same neighbourhood
        assert len(_decimate(pts, budget)) <= budget + 2


def test_decimation_is_a_no_op_under_budget():
    pts = _series(50)
    assert _decimate(pts, 320) is pts
    assert _decimate(pts, 0) is pts


@pytest.mark.asyncio
async def test_equity_series_returns_the_spike_at_any_budget(engine):
    """End to end: the API must not hide a move the book actually made."""
    pid = "eqser01"
    async with engine.sf() as session:
        session.add(Portfolio(id=pid, name="Series", kind="sim",
                              cash=10_000.0, starting_cash=10_000.0, base_currency="USD"))
        for ts, eq in _series(2000):
            session.add(EquityPoint(portfolio_id=pid, ts=ts, equity=eq, cash=eq))
        await session.commit()
    await engine.positions.load()

    for budget in (60, 320):
        out = await engine.positions.equity_series(pid, limit=200_000, points=budget)
        assert max(p[1] for p in out) == pytest.approx(11_335.02)
        assert min(p[1] for p in out) == pytest.approx(9_010.00)
