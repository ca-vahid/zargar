from types import SimpleNamespace

import pytest

from zargar.models import Portfolio, TechniqueRun
from zargar.techniques.options_cartel.accounts import DEFAULT_BOOK, validate_account
from zargar.techniques.options_cartel.preparation import (
    preparation_portfolio,
    preparation_status,
    run_preparation,
)
from zargar.techniques.options_cartel.preparation_scope import read_policy, setting_key
from zargar.techniques.options_cartel.runtime import CartelRuntime

from .test_options_cartel_preparation import inputs


async def test_dedicated_book_overrides_legacy_selection_and_no_fallback(engine):
    async with engine.sf() as session, session.begin():
        session.add(Portfolio(id='cartel-own', name='Options Cartel Practice', kind='sim', base_currency='USD', cash=10000))
        session.add(Portfolio(id='other-desk', name='Other Practice', kind='sim', base_currency='USD', cash=10000))
    await engine.positions.load()
    await engine.settings.set(setting_key('practice'), {'portfolio_id':'other-desk', 'enabled':True})
    await engine.settings.set(DEFAULT_BOOK, 'cartel-own')
    await engine.settings.load()  # The shared override resolver already recognizes the key.
    assert read_policy(engine, 'practice').portfolio_id == 'cartel-own'
    assert read_policy(engine, 'live').portfolio_id is None
    assert await preparation_portfolio(engine) == 'cartel-own'
    with pytest.raises(ValueError, match='dedicated'):
        await preparation_portfolio(engine, 'other-desk')
    await engine.settings.set(DEFAULT_BOOK, 'missing-book')
    with pytest.raises(ValueError, match='account'):
        await preparation_portfolio(engine)


async def test_preparation_uses_dedicated_book_without_moving_history(engine):
    at, providers = inputs()
    runtime = engine.cartel_observer = CartelRuntime(engine); runtime.clock = lambda: at
    await engine.settings.set(setting_key('practice'), {'enabled':True})
    try:
        first = await run_preparation(engine, read_policy(engine), clock=lambda: at, **providers)
        async with engine.sf() as session, session.begin():
            session.add(Portfolio(id='cartel-own', name='Options Cartel Practice', kind='sim', base_currency='USD', cash=10000))
        await engine.positions.load()
        await engine.settings.set(DEFAULT_BOOK, 'cartel-own')
        assert (await preparation_status(engine))['latest'] is None
        second = await run_preparation(engine, read_policy(engine), clock=lambda: at, **providers)
        assert second['result']['portfolioId'] == 'cartel-own'
        assert second['result']['armed'] == 1
        async with engine.sf() as session:
            original = await session.get(TechniqueRun, first['runId'])
            assert original.result['portfolioId'] != 'cartel-own'
    finally:
        await runtime.stop()


def test_archive_flag_and_technique_mapping_guard_all_new_arms():
    books = {'old': {'id':'old', 'kind':'sim', 'archived':True}, 'own':{'id':'own', 'kind':'sim'}}
    engine = SimpleNamespace(settings={DEFAULT_BOOK:'own'}, positions=SimpleNamespace(portfolio=books.get))
    with pytest.raises(ValueError, match='Archived'):
        validate_account(engine, SimpleNamespace(id='old', kind='sim'))
    with pytest.raises(ValueError, match='dedicated'):
        validate_account(engine, {'id':'other', 'kind':'sim'})
    validate_account(engine, books['own'])
    validate_account(engine, {'id':'broker', 'kind':'live'})
    with pytest.raises(ValueError, match='Archived'):
        validate_account(engine, SimpleNamespace(id='db-archived', kind='sim', archived=True))


async def test_reading_archived_arm_does_not_restore_it(engine, monkeypatch):
    runtime = CartelRuntime(engine)
    async def load(_):
        return {'portfolioId':'archived-book'}
    monkeypatch.setattr(runtime.repository, 'load', load)
    monkeypatch.setattr(engine.positions, 'portfolio', lambda _: {'id':'archived-book','kind':'sim','archived':True})
    assert await runtime.load_detail('old-plan') is None
    assert not runtime.rows
    with pytest.raises(ValueError, match='Archived'):
        runtime.controller._entry_conditions({}, None, SimpleNamespace(portfolio_id='archived-book'))
