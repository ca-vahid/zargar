"""PR95 shared widening durability: exercise real helpers, no database/runtime."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from zargar.execution.policies import PolicyState
from zargar.execution.positions import Leg, Managed, PositionManager


@pytest.mark.parametrize("failure", ["database", "journal"])
async def test_widen_does_not_swallow_real_persistence_or_journal_failure(failure):
    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def get(self, *_args, **_kwargs):
            return NS()

        async def commit(self):
            if failure == "database":
                raise OSError("database unavailable")

    eng = NS(sf=Session, settings={}, bus=NS(publish=lambda *_args: None),
             journal=NS(append=AsyncMock(side_effect=(
                 OSError("journal unavailable") if failure == "journal" else None))))
    mgr = PositionManager(eng)
    position = Managed(
        id="tip-position", portfolio_id="practice", symbol="X", direction="long",
        technique="tip", policy={"stop": {"kind": "fixed", "price": 99.0}},
        legs=[Leg(symbol="X", sec_type="STK", qty=10.0, avg_fill=100.0)],
        entry=100.0, risk=1.0, state=PolicyState(stop=99.0), overnight="app_managed")
    mgr._pos[position.id] = position
    mgr._ensure_venue_stop = AsyncMock()
    try:
        await mgr.widen_stop(position.id, 97.0, reason="trim confirmed",
                             max_qty=10.0, unit_loss=3.0, budget=30.0)
    except OSError:
        pass
    assert position.state.stop == 99.0, (
        f"{failure} failed inside the real shared helper, but widening remained exposed")
    assert position.policy["stop"]["price"] == 99.0
    mgr._ensure_venue_stop.assert_not_awaited()
