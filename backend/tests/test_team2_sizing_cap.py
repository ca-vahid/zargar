"""F127 (2026-09-15): the sizer honours the technique's 0DTE policy cap instead of handing the RiskGate a refusal."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from zargar.execution.planrunner import ArmConfig, ArmedPlan, Trade
from zargar.techniques.team2.runner import Team2Runner


def _rig(settings):
    eng = SimpleNamespace(settings=settings, journal=SimpleNamespace(append=AsyncMock()), trading_halted=lambda _: False,
                          positions=SimpleNamespace(equity=AsyncMock(return_value=9934.16)))
    runner = Team2Runner(eng)
    runner._log = Mock()
    cfg = ArmConfig(portfolio_id="p", mode="auto", instrument="options", use_critic=False, risk_pct=6.0, premium_budget=2000.0, max_contracts=50, contracts=None)   # the live plans carry contracts=None (risk sizing)
    ap = ArmedPlan(run_id="size", symbol="IWM", plan_for="2026-09-15", plan={}, config=cfg, trackers={}, armed_at=0)
    trade = Trade(trigger_id="pm_break_down@10:30#2", kind="pm_break_down", direction="short", fired_ts=1, window="team2", entry=284.9,
                  stop=285.5, targets=[283.0], instrument="options")
    return runner, ap, trade


BASE = {"techniques.team2.premium_stop_pct": 25.0, "techniques.team2.min_one_contract": True, "techniques.team2.dte_policy": "0dte"}


@pytest.mark.parametrize("policy, expected", [
    ({"enabled": True, "max_contracts": 40, "premium_cap": 2000.0, "flatten_et": "15:45", "last_entry_et": "15:30"}, 40),   # today's IWM case
    ({"enabled": False, "max_contracts": 40}, 50),                                                                        # policy off: the risk cap
    (None, 50),                                                                                                           # no policy
    ({"enabled": True, "max_contracts": 80}, 50),                                                                         # a looser policy never raises the risk cap
])
async def test_the_sizer_clamps_to_the_0dte_policy_cap(policy, expected):
    settings = dict(BASE)
    if policy is not None:
        settings["techniques.team2.zero_dte"] = policy
    runner, ap, trade = _rig(settings)
    n = await runner._size_contracts(ap, trade, {"symbol": "IWM260915P00284000", "ask": 0.33, "bid": 0.32, "_sizeMult": 1.0, "_bucket": "full"})
    # 6% of $9,934 = $596 at risk / ($33 x 25% = $8.25 per contract) = 72 -> budget $2,000 // $33 = 60 -> caps
    assert n == expected


async def test_a_small_size_multiplier_still_lands_under_the_policy_cap_and_min_one_holds():
    runner, ap, trade = _rig({**BASE, "techniques.team2.zero_dte": {"enabled": True, "max_contracts": 40}})
    n = await runner._size_contracts(ap, trade, {"symbol": "IWM260915P00284000", "ask": 0.33, "_sizeMult": 0.5, "_bucket": "small"})
    assert n == 36                                                   # int(72 x 0.5) = 36 < 40: the multiplier, not the cap, decides
    n = await runner._size_contracts(ap, trade, {"symbol": "IWM260915P00284000", "ask": 9.0, "_sizeMult": 1.0, "_bucket": "full"})
    assert n == 2                                                    # a dear contract: risk says 2 ($596 / $225), the $2,000 budget says 2 - the cap never binds
