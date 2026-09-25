"""Shares sizing respects the book's own position caps (2026-09-15): a risk-%-sized share entry is sized DOWN to what
`risk.max_position_notional` / `risk.max_position_pct` / the gross-exposure room admit instead of being sent for a
certain RiskGate refusal (WDC/INTU/AMAT on 09-15: 89-100 shares of a $330-420 name on a $10k Practice book). The gate
stays the authority. No DB, no engine start."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from zargar.execution.planrunner import ArmConfig, ArmedPlan, PlanRunner


def rig(settings, equity=10190.0, gross=600.0, kind="sim"):
    engine = SimpleNamespace(settings=settings, journal=SimpleNamespace(append=AsyncMock()),
                             positions=SimpleNamespace(equity=AsyncMock(return_value=equity), gross_exposure=AsyncMock(return_value=gross),
                                                       portfolio=Mock(return_value={"id": "p", "kind": kind})))
    r = PlanRunner(engine); r._log = Mock()
    ap = ArmedPlan(run_id="cap-run", symbol="INTU", plan={}, plan_for="2026-09-15",
                   config=ArmConfig(portfolio_id="p", mode="auto", instrument="shares"), trackers={}, armed_at=0)
    return r, ap


def test_cap_is_the_tightest_of_notional_equity_share_and_gross_room():
    r, ap = rig({"risk.max_position_notional": 25000.0, "risk.max_position_pct": 50.0, "risk.max_gross_exposure_pct": 100.0})
    qty, basis = asyncio.run(r._shares_position_cap(ap, 330.2))
    assert qty == int(10190 * 0.5 // 330.2) == 15 and "risk.max_position_pct" in basis
    r, ap = rig({"risk.max_position_notional": 25000.0, "risk.max_position_pct": 50.0, "risk.max_gross_exposure_pct": 100.0}, gross=9000.0)
    qty, basis = asyncio.run(r._shares_position_cap(ap, 330.2))
    assert qty == int((10190 - 9000) // 330.2) == 3 and "risk.max_gross_exposure_pct" in basis
    r, ap = rig({"risk.max_position_notional": 1000.0, "risk.max_position_pct": 50.0, "risk.max_gross_exposure_pct": 100.0})
    qty, basis = asyncio.run(r._shares_position_cap(ap, 330.2))
    assert qty == 3 and "risk.max_position_notional" in basis


def test_cap_below_one_share_or_unknown_equity_never_raises():
    r, ap = rig({"risk.max_position_notional": 25000.0, "risk.max_position_pct": 50.0}, equity=0.0)
    qty, basis = asyncio.run(r._shares_position_cap(ap, 6000.0))
    assert qty == 4 and "risk.max_position_notional" in basis          # no equity: only the $ cap applies
    r, ap = rig({"risk.max_position_notional": 25000.0, "risk.max_position_pct": 50.0})
    qty, _ = asyncio.run(r._shares_position_cap(ap, 6000.0))
    assert qty == 0                                                    # the caller skips with a journaled reason
    r, ap = rig({})
    r.engine.positions.equity = AsyncMock(side_effect=RuntimeError("no keeper"))
    assert asyncio.run(r._shares_position_cap(ap, 100.0)) == (None, "")   # diagnostic failure: the gate decides


def test_research_shadow_books_keep_only_the_dollar_cap_like_the_gate():
    r, ap = rig({"risk.max_position_notional": 25000.0, "risk.max_position_pct": 50.0, "risk.max_gross_exposure_pct": 100.0}, kind="shadow")
    qty, basis = asyncio.run(r._shares_position_cap(ap, 330.2))
    assert qty == int(25000 // 330.2) == 75 and "risk.max_position_notional" in basis   # no equity-share cap on a shadow book



def test_the_cap_reference_is_the_higher_of_limit_and_mid():
    """2026-09-24 HOOD: sized at the 120.60 limit, valued by the gate at a higher mid -> 50.2% vs the 50% cap."""
    r, ap = rig({})
    r.engine.quotes = SimpleNamespace(get=lambda sym: SimpleNamespace(bid=121.00, ask=121.16))
    assert r._cap_reference(ap, 120.60) == 121.08
    r.engine.quotes = SimpleNamespace(get=lambda sym: SimpleNamespace(bid=119.0, ask=119.2))
    assert r._cap_reference(ap, 120.60) == 120.60, "a mid below the limit never loosens the cap"
    r.engine.quotes = SimpleNamespace(get=lambda sym: None)
    assert r._cap_reference(ap, 120.60) == 120.60, "no quote: the limit, as before"
