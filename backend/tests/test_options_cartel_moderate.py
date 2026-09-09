import pytest
from sqlalchemy import select

from zargar.models import Portfolio, TechniqueRun
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.preparation import SETTING, run_preparation
from zargar.techniques.options_cartel.rules import CartelRules
from zargar.techniques.options_cartel.runtime import CartelRuntime
from zargar.techniques.options_cartel.screen import market_regime

from .test_options_cartel_preparation import inputs
from .test_options_cartel_prepare import input_data


@pytest.mark.parametrize('spy,qqq,expected', [(101,110,'long'),(110,101,'long'),(100,110,'mixed'),
    (99,110,'mixed'),(101,101,'mixed'),(99,99,'short'),(110,110,'long')])
def test_moderate_requires_one_strong_index_and_both_above_50(monkeypatch, spy, qqq, expected):
    from zargar.techniques.options_cartel import screen
    data = input_data()
    indices = {sym:[b.model_copy(update={'open':price,'close':price,'high':price+1,'low':price-1}) for b in bars]
               for (sym,bars),price in zip(data['indices'].items(), [spy,qqq])}
    monkeypatch.setattr(screen, '_emas', lambda bars, periods:{p:{8:105,21:103,50:100}[p] for p in periods})
    read = market_regime(indices, CartelRules(market_alignment='moderate'), data['as_of_ms'])
    assert read['direction'] == expected
    assert read['alignmentMode'] == 'moderate'
    if spy == 101 and qqq == 110:
        assert read['strictDirection'] == 'mixed'
        assert market_regime(indices, CartelRules(), data['as_of_ms'])['direction'] == 'mixed'
    indices['QQQ'] = []
    assert market_regime(indices, CartelRules(market_alignment='moderate'), data['as_of_ms'])['direction'] == 'unknown'


def test_live_configuration_cannot_select_moderate_and_legacy_defaults_stay_strict():
    assert PreparationPolicy().market_alignment == 'strict'
    assert CartelRules.model_validate({}).market_alignment == 'strict'
    with pytest.raises(ValueError, match='Practice-only'):
        PreparationPolicy(workspace='live', market_alignment='moderate')


@pytest.mark.parametrize('mode,arms', [('strict',0),('moderate',1)])
async def test_preparation_uses_and_freezes_selected_market_mode(engine, monkeypatch, mode, arms):
    from zargar.techniques.options_cartel import screen
    at, providers = inputs()
    original = screen._emas
    def emas(bars, periods):
        if bars and bars[0].symbol == 'SPY':
            return {p:bars[-1].close+(2 if p in (8,21) else -10) for p in periods}
        return original(bars, periods)
    monkeypatch.setattr(screen, '_emas', emas)
    runtime = engine.cartel_observer = CartelRuntime(engine); runtime.clock = lambda: at
    policy = PreparationPolicy(enabled=True,risk_pct=1,market_alignment=mode,request_interval_seconds=0)
    await engine.settings.set(SETTING,policy.model_dump(mode='json'))
    try:
        result = (await run_preparation(engine,policy,clock=lambda:at,**providers))['result']
        assert result['armed'] == arms, result
        assert result['market']['alignmentMode'] == mode
        assert result['armingBlocked'] == (mode == 'strict')
        if arms:
            async with engine.sf() as session:
                record = await session.scalar(select(TechniqueRun).where(TechniqueRun.mode=='plan'))
                assert record.result['plan']['plan']['rules']['market_alignment'] == 'moderate'
            async with engine.sf() as session, session.begin():
                session.add(Portfolio(id='moderate-live',name='Live fixture',kind='live',base_currency='USD',cash=10000))
            await engine.positions.load()
            spec = {**runtime.rows[record.id]['config']['execution'], 'portfolio_id':'moderate-live', 'allow_live':True}
            with pytest.raises(ValueError, match='Practice-only'):
                await runtime.arm(record.id, {'mode':'auto','portfolioId':'moderate-live','execution':spec})
    finally:
        await runtime.stop()
