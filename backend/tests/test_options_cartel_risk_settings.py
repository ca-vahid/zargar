from types import SimpleNamespace

import pytest

from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.preparation import affordable_contract_policy
from zargar.techniques.options_cartel.preparation_scope import read_policy, setting_key

from .test_options_cartel_api import client  # noqa: F401 - shared authenticated API fixture


def test_workspace_defaults_and_saved_risk_are_independent():
    engine = SimpleNamespace(settings={})
    assert read_policy(engine, 'practice').risk_pct == 10
    assert read_policy(engine, 'live').risk_pct == 1
    engine.settings[setting_key('practice')] = {'risk_pct': 2}
    engine.settings[setting_key('live')] = {'riskPct': 3}
    assert read_policy(engine, 'practice').risk_pct == 2
    assert read_policy(engine, 'live').risk_pct == 3


@pytest.mark.parametrize('workspace', ['practice', 'live'])
def test_both_workspaces_accept_ten_and_reject_more(workspace):
    assert PreparationPolicy(workspace=workspace, riskPct=10).risk_pct == 10
    for value in (0, -1, 10.01):
        with pytest.raises(ValueError):
            PreparationPolicy(workspace=workspace, riskPct=value)


async def test_api_saves_ten_in_each_workspace_without_enabling_live(client):  # noqa: F811 - pytest fixture
    c, _ = client
    for workspace in ('practice', 'live'):
        before = (await c.get(f'/api/options-cartel/preparation?workspace={workspace}')).json()
        saved = await c.post(f'/api/options-cartel/preparation/config?workspace={workspace}',
                             json={**before['configuration'], 'riskPct': 10})
        assert saved.status_code == 200, saved.text
        assert saved.json()['configuration']['riskPct'] == 10
        assert saved.json()['configuration']['enabled'] is False
        assert saved.json()['liveAutoAllowed'] is False
    invalid = await c.post('/api/options-cartel/preparation/config?workspace=live',
                           json={'workspace':'live', 'riskPct':10.01})
    assert invalid.status_code == 422


async def test_premium_budget_still_caps_risk_allowance():
    async def equity(_):
        return 10000
    engine = SimpleNamespace(positions=SimpleNamespace(portfolio=lambda _: {'baseCurrency':'USD'},
        equity=equity, fx=SimpleNamespace(rate=lambda *_: 1)))
    policy = PreparationPolicy(risk_pct=10, budget=500)
    policy = policy.model_copy(update={'contract_policy': policy.contract_policy.model_copy(update={'max_ask':20})})
    assert (await affordable_contract_policy(engine, 'practice', policy)).max_ask == 5
    assert (await affordable_contract_policy(engine, 'practice', policy.model_copy(update={'budget':1000}))).max_ask == 10
