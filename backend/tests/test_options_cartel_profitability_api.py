"""The research read surface never turns on Live or writes a trading request."""
from unittest.mock import AsyncMock

from tests import test_options_cartel_api as api_tests

client = api_tests.client


async def test_profitability_api_is_authenticated_and_validates_session(client, monkeypatch):
    from zargar.techniques.options_cartel import profitability_research
    c, _ = client
    reader = AsyncMock(return_value={'rows': [], 'placesOrders': False})
    monkeypatch.setattr(profitability_research, 'status', reader)
    bad_auth = await c.get('/api/options-cartel/profitability-research', headers={'Authorization': 'Bearer wrong'})
    assert bad_auth.status_code == 401
    for day in ('not-a-date', '2026-02-30', '20260916'):
        response = await c.get('/api/options-cartel/profitability-research', params={'day': day})
        assert response.status_code == 400, response.text
    reader.assert_not_awaited()


async def test_profitability_api_live_is_an_empty_non_executing_view(client, monkeypatch):
    from zargar.techniques.options_cartel import profitability_research
    c, _ = client
    reader = AsyncMock()
    monkeypatch.setattr(profitability_research, 'status', reader)
    response = await c.get('/api/options-cartel/profitability-research?workspace=live')
    assert response.status_code == 200
    assert response.json() == {'enabled': False, 'phase': 'practice_only', 'rows': [], 'contexts': [],
                              'placesOrders': False, 'automaticPermissionChanged': False}
    reader.assert_not_awaited()


async def test_profitability_api_uses_cartel_practice_book_and_exact_date(client, monkeypatch):
    from zargar.techniques.options_cartel import profitability_research
    from zargar.techniques.options_cartel.preparation_scope import read_policy
    c, engine = client
    reader = AsyncMock(return_value={'rows': [], 'placesOrders': False, 'session': '2026-09-16'})
    monkeypatch.setattr(profitability_research, 'status', reader)
    response = await c.get('/api/options-cartel/profitability-research?workspace=practice&day=2026-09-16')
    assert response.status_code == 200
    assert response.json()['placesOrders'] is False
    reader.assert_awaited_once_with(engine, '2026-09-16', read_policy(engine, 'practice').portfolio_id)


async def test_internal_research_does_not_crowd_history_or_leak_into_live(client):
    from zargar.models import TechniqueRun
    c, engine = client
    async with engine.sf() as session, session.begin():
        for mode in ('profit_context', 'profit_watch', 'profit_quote'):
            session.add(TechniqueRun(id=mode, technique='options_cartel', symbol='MULTI', mode=mode,
                status='done', as_of=1, config={'workspace': 'practice', 'portfolioId': 'cartel'},
                result={'placesOrders': False}))
    ordinary = await c.get('/api/options-cartel/runs?workspace=practice')
    assert ordinary.status_code == 200 and ordinary.json() == []
    explicit = await c.get('/api/options-cartel/runs?workspace=practice&mode=profit_watch')
    assert [row['runId'] for row in explicit.json()] == ['profit_watch']
    live = await c.get('/api/options-cartel/runs?workspace=live&mode=profit_watch')
    assert live.status_code == 200 and live.json() == []
