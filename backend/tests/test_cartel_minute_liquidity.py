"""C0 (2026-09-27): the minute-liquidity screen - measure, default, and the preparation exclusion."""
from sqlalchemy import func, select

from zargar.models import TechniqueArmed
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.preparation import SETTING, run_preparation
from zargar.techniques.options_cartel.prepare import minute_liquidity
from zargar.techniques.options_cartel.runtime import CartelRuntime

from .test_options_cartel_preparation import inputs


def test_ratio_pools_every_baseline_session():
    baseline = {"minuteCoverage": {"2026-09-24": {"present": 390, "expected": 390}, "2026-09-25": {"present": 351, "expected": 390}}}
    got = minute_liquidity(baseline)
    assert got["sessions"] == 2 and got["present"] == 741 and abs(got["ratio"]-.95) < 1e-9


def test_no_sessions_is_zero_and_the_screen_defaults_off():
    assert minute_liquidity({})["ratio"] == 0.0
    assert PreparationPolicy().min_minute_coverage == 0
    assert PreparationPolicy.model_validate({"minMinuteCoverage": .97}).min_minute_coverage == .97


async def test_thin_trading_name_is_excluded_not_retried(engine):
    at, providers = inputs()
    full = providers['fetch']

    async def sparse(symbol, tf, start, end, *, client):
        bars = await full(symbol, tf, start, end, client=client)
        return bars if tf == '1d' else [b for i, b in enumerate(bars) if i % 2 == 0]  # trades in half the minutes
    providers['fetch'] = sparse
    runtime = CartelRuntime(engine); runtime.clock = lambda: at
    engine.cartel_observer = runtime
    policy = PreparationPolicy(risk_pct=1, enabled=True, history_limit=10, min_minute_coverage=.97)
    await engine.settings.set(SETTING, policy.model_dump(mode='json'))
    try:
        result = await run_preparation(engine, policy, clock=lambda: at, **providers)
        row = result['result']['shortlist'][0]
        assert row['status'] == 'thin_trading' and abs(row['minuteLiquidity']['ratio']-.5) < .01, row
        assert result['result']['armed'] == 0 and result['result']['planErrors'] == 0
        async with engine.sf() as session:
            assert await session.scalar(select(func.count()).select_from(TechniqueArmed)) == 0
    finally:
        await runtime.stop()
