"""Real PostgreSQL/ASGI research flow; no engine start, feeds or order placement."""
import httpx
import pytest
from sqlalchemy import func, select

from zargar.api.app import create_app
from zargar.engine import Engine
from zargar.models import Event, Order, Portfolio, TechniqueRun
from zargar.techniques.options_cartel.exits import ExitCampaign
from zargar.techniques.options_cartel.plans import CartelPlan
from zargar.techniques.options_cartel.service import ResearchInput

from .conftest import make_test_config
from .test_options_cartel_prepare import input_data


def research_payload():
    args = input_data()
    return ResearchInput.model_validate({
        "history": [b.model_dump(mode="json") for b in args["history"]],
        "indices": {s: [b.model_dump(mode="json") for b in bs] for s, bs in args["indices"].items()},
        "facts": args["facts"].model_dump(mode="json"), "rules": args["rules"].model_dump(mode="json"),
        "parameters": args["parameters"].model_dump(mode="json"), "asOfMs": args["as_of_ms"],
        "dataSource": "synthetic test corpus", "direction": "long",
        "minuteHistory": [{"symbol": b.symbol, "ts": b.ts, "open": b.open, "high": b.high,
                           "low": b.low, "close": b.close, "volume": b.volume} for b in args["minute_history"]],
    }).model_dump(mode="json", by_alias=True)


@pytest.fixture
async def client(fresh_db):
    config = make_test_config(auth_token="cartel-test-token")
    engine = Engine(config)
    app = create_app(config, engine)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 headers={"Authorization": "Bearer cartel-test-token"}) as c:
        yield c, engine
    await engine.db.dispose()


def plan_payload():
    return {"setup": "base", "horizonSessions": 3, "reviewedTargets": [170, 180],
            "reviewNote": "Reviewed test geometry", "targetSource": "synthetic fixture",
            "entryPolicy": {"timeframe_minutes": 5},
            "exitCampaign": ExitCampaign.for_profile("june_2026", [170, 180]).model_dump(mode="json")}


async def test_authenticated_research_plan_replay_review_and_restore(client):
    c, engine = client
    r = await c.post("/api/options-cartel/analyze", json=research_payload())
    assert r.status_code == 200, r.text
    research = r.json()
    assert research["verdict"] == "setup" and research["technique"] == "options_cartel"
    rid = research["runId"]
    r = await c.post(f"/api/options-cartel/runs/{rid}/plan", json=plan_payload())
    assert r.status_code == 200, r.text
    prepared = r.json()
    assert prepared["parentRunId"] == rid and prepared["mode"] == "plan"
    pid = prepared["runId"]
    plan = CartelPlan.model_validate(prepared["result"]["plan"]["plan"])
    from zargar.marketstructure.sessions import session_bounds
    opens, _ = session_bounds(plan.first_session.isoformat())
    minutes = [{"symbol": "TEST", "ts": opens+i*60_000, "open": 146.5, "high": 147.3,
                "low": 146.5, "close": 147.2, "volume": 200} for i in range(5)]
    replay = await c.post(f"/api/options-cartel/runs/{pid}/replay",
                          json={"minutes": minutes, "asOfMs": opens+5*60_000, "dataSource": "test tape"})
    assert replay.status_code == 200, replay.text
    assert replay.json()["result"]["entryRead"]["status"] == "triggered"
    assert replay.json()["result"]["placesOrders"] is False
    review = await c.post(f"/api/options-cartel/runs/{pid}/reviews",
                          json={"verdict": "correct", "stage": "entry", "notes": "Confirmed synthetic geometry"})
    assert review.status_code == 200
    from zargar.techniques.options_cartel.service import CartelService
    restored = await CartelService(engine).detail(pid)
    assert restored["result"] == prepared["result"] and len(restored["reviews"]) == 1
    assert (await c.get(f"/api/options-cartel/runs/{rid}")).json()["result"] == research["result"]
    listed = (await c.get("/api/options-cartel/runs")).json()
    assert len(listed) == 3
    async with engine.sf() as session:
        assert await session.scalar(select(func.count()).select_from(Order)) == 0
        events = (await session.scalars(select(Event).where(Event.aggregate_id == pid))).all()
        assert {e.type for e in events} == {"TechniqueRunCompleted", "TechniqueReviewAdded"}
        assert all(e.payload["technique"] == "options_cartel" for e in events)
    assert not engine.started


async def test_foreign_technique_records_are_inaccessible_and_never_modified(client):
    c, engine = client
    async with engine.sf() as session:
        session.add(TechniqueRun(id="foreign", technique="team2", symbol="SPY", mode="analysis",
                                 status="done", result={"sentinel": "preserve"}, config={}))
        await session.commit()
    assert (await c.get("/api/options-cartel/runs/foreign")).status_code == 404
    for path, payload in [("plan", plan_payload()),
                          ("replay", {"minutes": [], "asOfMs": 0, "dataSource": "test"}),
                          ("replay-campaign", {}),
                          ("reviews", {"verdict": "correct", "stage": "data", "notes": "test"})]:
        assert (await c.post(f"/api/options-cartel/runs/foreign/{path}", json=payload)).status_code == 404
    assert (await c.get("/api/options-cartel/runs")).json() == []
    async with engine.sf() as session:
        assert (await session.get(TechniqueRun, "foreign")).result == {"sentinel": "preserve"}


async def test_authentication_and_invalid_body_boundaries(client):
    c, _ = client
    assert (await c.get("/api/options-cartel/runs", headers={"Authorization": ""})).status_code == 401
    body = research_payload()
    body["direction"] = "anything"
    assert (await c.post("/api/options-cartel/analyze", json=body)).status_code == 422
    assert (await c.get("/api/options-cartel/runs?limit=10000")).status_code == 422
    assert (await c.post("/api/options-cartel/runs/missing/preflight", json={"portfolioId": "x", "budget": 100})).status_code == 404


async def test_campaign_targets_must_match_plan_and_parent_is_immutable(client):
    c, _ = client
    research = (await c.post("/api/options-cartel/analyze", json=research_payload())).json()
    payload = plan_payload()
    payload["exitCampaign"] = ExitCampaign.for_profile("june_2026", [110, 120]).model_dump(mode="json")
    response = await c.post(f"/api/options-cartel/runs/{research['runId']}/plan", json=payload)
    assert response.status_code == 400 and "target levels" in response.text
    assert len((await c.get("/api/options-cartel/runs")).json()) == 1


async def test_collection_endpoint_persists_coverage_and_missing_metadata(client, monkeypatch):
    from zargar.techniques.options_cartel import collect

    from .test_options_cartel_collect import provider

    c, engine = client
    fetch, at, _ = provider()
    original = collect.collect_inputs

    async def collected(body):
        return await original(body, fetch=fetch, now_ms=at)

    monkeypatch.setattr(collect, "collect_inputs", collected)
    response = await c.post("/api/options-cartel/collect", json={"symbol": "TEST", "asOfMs": at})
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["verdict"] == "watch_only"
    assert row["result"]["collection"]["counts"]["daily"]["TEST"] == 80
    assert row["result"]["collection"]["warnings"]
    detail = (await c.get(f"/api/options-cartel/runs/{row['runId']}")).json()
    assert detail["config"]["inputs"]["facts"]["market_cap"] is None
    assert detail["result"]["collection"] == row["result"]["collection"]
    assert not engine.started


async def test_preflight_reports_expired_plan_and_journals_without_orders(client):
    from zargar.research.events_contract import CONTRACTS

    c, engine = client
    async with engine.sf() as session:
        session.add(Portfolio(id="preflight-pf", name="Preflight test", kind="sim", base_currency="USD",
                              cash=10000, starting_cash=10000))
        await session.commit()
    await engine.positions.load()
    analysis = (await c.post("/api/options-cartel/analyze", json=research_payload())).json()
    plan = (await c.post(f"/api/options-cartel/runs/{analysis['runId']}/plan", json=plan_payload())).json()
    response = await c.post(f"/api/options-cartel/runs/{plan['runId']}/preflight",
                            json={"portfolioId": "preflight-pf", "instrument": "shares", "budget": 1000})
    assert response.status_code == 200, response.text
    assert not response.json()["passed"] and response.json()["placesOrders"] is False
    assert not next(g for g in response.json()["checks"] if g["name"] == "plan_horizon")["passed"]
    async with engine.sf() as session:
        event = await session.scalar(select(Event).where(Event.type == "TechniqueCartelPreflight"))
        assert event.aggregate_id == plan["runId"]
        assert set(CONTRACTS[event.type]["required"]) <= set(event.payload)
        assert await session.scalar(select(func.count()).select_from(Order)) == 0


async def test_contract_selection_is_owned_journaled_and_nonexecuting(client, monkeypatch):
    from zargar.api import routes_options_cartel as routes

    c, engine = client
    analysis = (await c.post("/api/options-cartel/analyze", json=research_payload())).json()
    plan = (await c.post(f"/api/options-cartel/runs/{analysis['runId']}/plan", json=plan_payload())).json()

    async def selected_contract(_, owned_plan, policy):
        return {"runId": owned_plan.id, "selected": None, "candidates": [], "placesOrders": False,
                "policy": policy.model_dump(mode="json")}

    monkeypatch.setattr(routes, "select_contract", selected_contract)
    body = {"dteMin": 20, "dteMax": 60, "targetDte": 30, "targetAbsDelta": .5,
            "maxAsk": 3, "maxSpreadPct": 10}
    response = await c.post(f"/api/options-cartel/runs/{plan['runId']}/contracts", json=body)
    assert response.status_code == 200 and response.json()["placesOrders"] is False
    assert (await c.post("/api/options-cartel/runs/foreign/contracts", json=body)).status_code == 404
    async with engine.sf() as session:
        event = await session.scalar(select(Event).where(Event.type == "TechniqueCartelContractSelection"))
        assert event.aggregate_id == plan["runId"] and event.payload["report"]["selected"] is None
        assert await session.scalar(select(func.count()).select_from(Order)) == 0

async def test_campaign_replay_persists_missing_data_without_mutating_plan_or_orders(client):
    c, engine = client
    analysis = (await c.post('/api/options-cartel/analyze', json=research_payload())).json()
    prepared = (await c.post(f"/api/options-cartel/runs/{analysis['runId']}/plan", json=plan_payload())).json()
    pid = prepared['runId']
    from zargar.marketstructure.sessions import session_bounds
    plan = CartelPlan.model_validate(prepared['result']['plan']['plan'])
    _, closes = session_bounds(plan.last_session.isoformat())
    response = await c.post(f'/api/options-cartel/runs/{pid}/replay-campaign',
                            json={'source': 'stored', 'asOfMs': closes})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['parentRunId'] == pid and saved['mode'] == 'replay'
    assert saved['result']['status'] == 'missing_data'
    assert saved['result']['fills'] == []
    assert saved['result']['placesOrders'] is False
    assert saved['config']['planSnapshot'] == prepared['result']['plan']
    experiment = await c.post('/api/options-cartel/sweeps', json={
        'replayIds': [saved['runId']], 'variants': [{'name': 'Tighter chase', 'maxChaseR': .25}]})
    assert experiment.status_code == 200, experiment.text
    sweep = experiment.json()
    assert sweep['mode'] == 'sweep' and sweep['result']['placesOrders'] is False
    assert all(s['incomplete'] == 1 and s['meanClosedR'] is None for s in sweep['result']['summaries'])
    assert sweep['config']['snapshots'][0]['runId'] == saved['runId']
    assert len(sweep['config']['inputSha256']) == 64
    assert (await c.get(f'/api/options-cartel/runs/{pid}')).json()['result'] == prepared['result']
    async with engine.sf() as session:
        assert await session.scalar(select(func.count()).select_from(Order)) == 0
    assert not engine.started


async def test_provider_campaign_replay_snapshots_supplied_history(client):
    from zargar.domain import Bar
    from zargar.marketstructure.sessions import session_bounds
    from zargar.techniques.options_cartel.replay_service import CampaignReplayRequest, replay_from_history
    from zargar.techniques.options_cartel.service import CartelService

    c, engine = client
    analysis = (await c.post('/api/options-cartel/analyze', json=research_payload())).json()
    prepared = (await c.post(f"/api/options-cartel/runs/{analysis['runId']}/plan", json=plan_payload())).json()
    plan = CartelPlan.model_validate(prepared['result']['plan']['plan'])
    opens, _ = session_bounds(plan.first_session.isoformat())
    bars = [Bar('TEST', '1m', opens+i*60_000, 146.5, 147.3, 146.5, 147.2, 200) for i in range(5)]
    bars += [Bar('TEST', '1m', opens+5*60_000, 147.2, 148., 147., 147.5, 200)]
    calls = []

    async def provider(symbol, tf, start, end, *, client):
        assert not client.is_closed
        calls.append((symbol, tf, start, end))
        return bars if tf == '1m' else []

    cutoff = opens+6*60_000
    saved = await replay_from_history(CartelService(engine), prepared['runId'],
        CampaignReplayRequest(source='provider', as_of_ms=cutoff), fetch=provider, now_ms=cutoff)
    assert [call[1] for call in calls] == ['1m', '1d']
    assert all(call[2:] == (opens, cutoff) for call in calls)
    assert saved['result']['status'] == 'open'
    assert saved['result']['fills'][0]['at'] == opens+5*60_000
    assert saved['config']['minutes'] == [b.to_row() for b in bars]
    assert saved['config']['daily'] == prepared['config']['inputs']['history']
    async with engine.sf() as session:
        assert await session.scalar(select(func.count()).select_from(Order)) == 0


async def test_focus_scan_preserves_successful_analyses_and_symbol_failures(client):
    from zargar.techniques.options_cartel.scans import ScanRequest, retry_scan, scan_focus_list
    from zargar.techniques.options_cartel.service import CartelService

    _, engine = client
    inputs = ResearchInput.model_validate(research_payload())
    calls = []

    async def collect(body, *, now_ms):
        calls.append(body)
        assert body.as_of_ms == now_ms == inputs.as_of_ms
        if body.symbol == 'FAIL':
            raise ValueError('history unavailable')
        return inputs, {'warnings': ['synthetic scan fixture']}

    saved = await scan_focus_list(CartelService(engine), ScanRequest(symbols=['TEST', 'FAIL']),
                                  collect=collect, now_ms=inputs.as_of_ms)
    assert saved['mode'] == 'scan' and saved['verdict'] == 'partial'
    assert saved['result']['placesOrders'] is False
    assert saved['result']['summary'] == {'requested': 2, 'qualified': 1, 'dataErrors': 1, 'completed': 2}
    rows = saved['result']['rows']
    assert [row['symbol'] for row in rows] == ['TEST', 'FAIL']
    assert rows[1]['error'] == 'history unavailable'
    child = await CartelService(engine).detail(rows[0]['runId'])
    assert child['mode'] == 'analysis' and child['symbol'] == 'TEST'
    assert child['parentRunId'] == saved['runId']
    assert len(calls) == 2
    retried = []

    async def recovered(body, *, now_ms):
        retried.append(body.symbol)
        assert body.as_of_ms == inputs.as_of_ms and now_ms == inputs.as_of_ms+86_400_000
        updated = inputs.model_copy(update={
            'history': [b.model_copy(update={'symbol': body.symbol}) for b in inputs.history],
            'facts': inputs.facts.model_copy(update={'symbol': body.symbol}),
            'minute_history': [b.model_copy(update={'symbol': body.symbol}) for b in inputs.minute_history]})
        return updated, {'warnings': []}

    retry = await retry_scan(CartelService(engine), saved['runId'], collect=recovered,
                             now_ms=inputs.as_of_ms+86_400_000)
    assert retried == ['FAIL'] and retry['parentRunId'] == saved['runId']
    assert retry['asOfMs'] == saved['asOfMs']
    assert retry['result']['rows'][0]['runId'] == rows[0]['runId']
    assert retry['result']['rows'][0]['reused'] is True
    assert retry['result']['summary']['dataErrors'] == 0
    assert (await CartelService(engine).detail(saved['runId']))['result'] == saved['result']
    with pytest.raises(ValueError, match='no unresolved'):
        await retry_scan(CartelService(engine), retry['runId'], collect=recovered)
    async with engine.sf() as session:
        assert await session.scalar(select(func.count()).select_from(Order)) == 0
    assert not engine.started


async def test_scan_rejects_duplicate_symbols_and_future_cutoffs(client):
    c, _ = client
    response = await c.post('/api/options-cartel/scans', json={'symbols': ['TEST', ' test ']})
    assert response.status_code == 422
    response = await c.post('/api/options-cartel/scans', json={'symbols': ['TEST'], 'asOfMs': 9999999999999})
    assert response.status_code == 400


async def test_schedule_configuration_validates_and_saves_only_owned_settings(client):
    c, engine = client
    old = engine.settings.get('techniques.team2.enabled')
    default = (await c.get('/api/options-cartel/schedule')).json()['configuration']
    assert not default['scanEnabled'] and not default['recoveryEnabled']
    invalid = await c.post('/api/options-cartel/schedule', json={**default, 'scanEnabled': True})
    assert invalid.status_code == 422
    response = await c.post('/api/options-cartel/schedule', json={**default,
        'scanSymbols': [' mu ', 'HOOD'], 'scanEnabled': True})
    assert response.status_code == 200, response.text
    assert response.json()['configuration']['scanSymbols'] == ['MU', 'HOOD']
    assert engine.settings.get('techniques.team2.enabled') == old
    assert not engine.started
    async with engine.sf() as session:
        assert await session.scalar(select(func.count()).select_from(Order)) == 0


async def test_saved_chart_excludes_future_candles_without_rewriting_inputs(client):
    import datetime as dt

    from zargar.marketstructure.market_calendar import next_trading_day

    c, _ = client
    payload = research_payload()
    original_count = len(payload['history'])
    last = payload['history'][-1]
    future = {**last, 'session': next_trading_day(dt.date.fromisoformat(last['session'])).isoformat()}
    payload['history'].append(future)
    response = await c.post('/api/options-cartel/analyze', json=payload)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert len(saved['chart']['daily']) == original_count
    assert len(saved['config']['inputs']['history']) == original_count+1
    restored = (await c.get(f"/api/options-cartel/runs/{saved['runId']}")).json()
    assert restored['chart'] == saved['chart']


async def test_cancelled_scan_retains_completed_symbol_and_marks_interrupted(client):
    import asyncio

    from zargar.techniques.options_cartel.scans import ScanRequest, scan_focus_list
    from zargar.techniques.options_cartel.service import CartelService

    _, engine = client
    inputs = ResearchInput.model_validate(research_payload())
    blocked = asyncio.Event()

    async def collect(body, *, now_ms):
        if body.symbol == 'WAIT':
            blocked.set()
            await asyncio.Event().wait()
        return inputs, {'warnings': []}

    task = asyncio.create_task(scan_focus_list(CartelService(engine), ScanRequest(symbols=['TEST', 'WAIT']),
                                             collect=collect, now_ms=inputs.as_of_ms))
    async def completed_one():
        await blocked.wait()
        while True:
            async with engine.sf() as session:
                row = await session.scalar(select(TechniqueRun).where(TechniqueRun.mode == 'scan'))
                if row and row.result['summary']['completed'] == 1:
                    return row.id
            await asyncio.sleep(.01)

    try:
        rid = await asyncio.wait_for(completed_one(), timeout=10)
        from zargar.techniques.options_cartel.scan_recovery import recover_interrupted_scans
        assert await recover_interrupted_scans(engine) == []
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        saved = await CartelService(engine).detail(rid)
        assert saved['status'] == 'failed' and saved['verdict'] == 'interrupted'
        assert saved['result']['summary']['completed'] == 1
        assert saved['result']['rows'][0]['runId']
        assert saved['result']['rows'][1]['status'] == 'pending'
        assert not engine._cartel_scan_tasks
        async with engine.sf() as session:
            assert await session.scalar(select(func.count()).select_from(Order)) == 0
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_scan_endpoint_returns_202_and_progress_can_be_polled(client, monkeypatch):
    import asyncio

    from zargar.techniques.options_cartel import scan_tasks
    from zargar.techniques.options_cartel.scans import scan_focus_list

    c, engine = client
    inputs = ResearchInput.model_validate(research_payload())
    release = asyncio.Event()

    async def collect(body, *, now_ms):
        await release.wait()
        return inputs, {'warnings': []}

    async def controlled(service, body, **kwargs):
        return await scan_focus_list(service, body, collect=collect, **kwargs)

    monkeypatch.setattr(scan_tasks, 'scan_focus_list', controlled)
    try:
        response = await c.post('/api/options-cartel/scans', json={'symbols': ['TEST'], 'asOfMs': inputs.as_of_ms})
        assert response.status_code == 202, response.text
        rid = response.json()['runId']
        assert (await c.get(f'/api/options-cartel/runs/{rid}')).json()['status'] == 'running'
        release.set()
        await asyncio.gather(*list(engine._cartel_background_scans))
        assert (await c.get(f'/api/options-cartel/runs/{rid}')).json()['status'] == 'done'
    finally:
        await scan_tasks.stop_background_scans(engine)


async def test_industry_snapshot_is_persisted_as_owned_research_without_orders(client):
    from tests.test_options_cartel_industry import snapshot

    c, engine = client
    body = snapshot([('Semiconductors', 5., 10.), ('Banks', -1., 2.)])
    response = await c.post('/api/options-cartel/industry-snapshots', json=body.model_dump(mode='json', by_alias=True))
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['mode'] == 'industry' and saved['technique'] == 'options_cartel'
    assert saved['result']['count'] == 2 and saved['result']['placesOrders'] is False
    listed = (await c.get('/api/options-cartel/runs?mode=industry')).json()
    assert [row['runId'] for row in listed] == [saved['runId']]
    assert len(saved['config']['inputSha256']) == 64
    assert (await c.get(f"/api/options-cartel/runs/{saved['runId']}")).json()['config']['inputs'] == body.model_dump(mode='json')
    async with engine.sf() as session:
        assert await session.scalar(select(func.count()).select_from(Order)) == 0


async def test_analysis_uses_owned_rank_snapshot_without_refreshing_stock_facts(client):
    c, _ = client
    payload = research_payload()
    at = payload['asOfMs']
    response = await c.post('/api/options-cartel/industry-snapshots', json={
        'source': 'synthetic rank capture', 'observedAt': at, 'dataAsOfMs': at,
        'expectedCount': 2, 'weekDefinition': 'provider 1W', 'monthDefinition': 'provider 1M',
        'rows': [{'industry': 'Semiconductors', 'weekPct': 5, 'monthPct': 10},
                 {'industry': 'Banks', 'weekPct': 1, 'monthPct': 2}]})
    assert response.status_code == 200, response.text
    payload['industrySnapshotId'] = response.json()['runId']
    payload['facts'].update(industry='Semiconductors', weekRank=99, monthRank=99)
    payload['rules'].update(require_industry_rank=True, industry_top_n=1)
    response = await c.post('/api/options-cartel/analyze', json=payload)
    assert response.status_code == 200, response.text
    saved = response.json()
    facts = saved['config']['inputs']['facts']
    assert facts['week_rank'] == facts['month_rank'] == 1
    assert facts['source'] == payload['facts']['source'] and facts['observed_at'] == at
    assert facts['rank_source'] == 'synthetic rank capture'
    assert saved['result']['screen']['screenPassed']
    payload['facts']['observedAt'] = at-8*86_400_000
    old = (await c.post('/api/options-cartel/analyze', json=payload)).json()
    assert not old['result']['screen']['screenPassed']
    assert old['config']['inputs']['facts']['observed_at'] == at-8*86_400_000
