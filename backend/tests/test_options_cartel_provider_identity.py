"""Provider switching must not turn another dataset into a cache hit."""
import pytest

from zargar.models import TechniqueRun
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.collect import normalize_daily
from zargar.techniques.options_cartel.preparation_io import PreparationHistory

from .test_options_cartel_preparation import inputs


async def seed_analysis(engine, bars, at, source):
    async with engine.sf() as session, session.begin():
        session.add(TechniqueRun(id='saved-provider-analysis', technique='options_cartel', symbol='SPY',
            mode='analysis', status='done', as_of=at,
            config={'inputs': {'history': [b.model_dump(mode='json') for b in bars]}},
            result={'collection': {'historyCacheVersion': 1, 'historyThrough': bars[-1].session.isoformat(),
                'historyObservedAt': at, 'historySource': source}}))


@pytest.mark.parametrize('source', ['alpaca:sip:raw:daily:v1', 'different:daily-yahoo-rth',
                                   'Shared historical provider; completed daily bars only'])
async def test_non_native_reader_does_not_reuse_other_or_unknown_dataset(engine, source):
    at, providers = inputs()
    calls = []

    async def fetch(*args, **kwargs):
        calls.append(args)
        return await providers['fetch'](*args, **kwargs)

    async def report(**kwargs):
        pass

    raw = await providers['fetch']('SPY', '1d', 0, at, client=None)
    await seed_analysis(engine, normalize_daily(raw, 'SPY', at), at, source)
    reader = PreparationHistory(engine, fetch, report, PreparationPolicy(request_interval_seconds=0), lambda: at)
    _, provenance = await reader.daily('SPY', at, None)
    assert len(calls) == 1
    assert provenance['historySource'] == reader.provider_key
    assert provenance['historyReusedFrom'] is None
    _, again = await reader.daily('SPY', at, None)
    assert len(calls) == 1
    assert again['historyReusedFrom'] == 'durable_cache'


async def test_same_provider_analysis_remains_reusable(engine):
    at, providers = inputs()

    async def forbidden(*args, **kwargs):
        pytest.fail('compatible saved analysis should avoid the provider request')

    async def report(**kwargs):
        pass

    reader = PreparationHistory(engine, forbidden, report, PreparationPolicy(), lambda: at)
    bars = normalize_daily(await providers['fetch']('SPY', '1d', 0, at, client=None), 'SPY', at)
    await seed_analysis(engine, bars, at, reader.provider_key)
    values, meta = await reader.daily('SPY', at, None)
    assert values == bars
    assert meta['historyReusedFrom'] == 'saved-provider-analysis'


@pytest.mark.parametrize('code', [401, 403])
async def test_native_batch_denial_changes_dataset_before_loading_each_symbol(engine, monkeypatch, code):
    from zargar.techniques.options_cartel import preparation_io as module
    at, providers = inputs()
    native_calls, fallback_calls = [], []

    async def denied(symbols, *args, **kwargs):
        native_calls.append(symbols)
        raise module.HistoryError(f'HTTP {code}')

    async def fetch(*args, **kwargs):
        fallback_calls.append(args[0])
        return await providers['fetch'](*args, **kwargs)

    async def report(**kwargs):
        pass

    monkeypatch.setattr(module, 'fetch_daily_batch', denied)
    reader = PreparationHistory(engine, fetch, report,
        PreparationPolicy(request_interval_seconds=0, history_batch_size=1), lambda: at)
    reader.native_batch = True
    reader.provider_key = 'alpaca:sip:raw:daily:v1'
    bars = normalize_daily(await providers['fetch']('SPY', '1d', 0, at, client=None), 'SPY', at)
    await seed_analysis(engine, bars, at, reader.provider_key)
    outcomes = []
    async with reader.prefetch([{'symbol': 'SPY'}, {'symbol': 'QQQ'}], at, None, skip=lambda _: False) as rows:
        async for _, value in rows:
            assert not isinstance(value, Exception), value
            outcomes.append(value)
    assert len(native_calls) == 1
    assert fallback_calls == ['SPY', 'QQQ']
    assert not reader.native_batch
    assert all(meta['historySource'] == reader.fallback_provider_key for _, meta in outcomes)


async def test_native_reader_rejects_non_native_analysis(engine, monkeypatch):
    from zargar.techniques.options_cartel import preparation_io as module
    at, providers = inputs()
    calls = []
    raw = await providers['fetch']('SPY', '1d', 0, at, client=None)

    async def native(symbols, *args, **kwargs):
        calls.extend(symbols)
        return {'SPY': raw}

    async def report(**kwargs):
        pass

    monkeypatch.setattr(module, 'fetch_daily_batch', native)
    reader = PreparationHistory(engine, providers['fetch'], report, PreparationPolicy(), lambda: at)
    await seed_analysis(engine, normalize_daily(raw, 'SPY', at), at, reader.provider_key)
    reader.native_batch = True
    reader.provider_key = 'alpaca:sip:raw:daily:v1'
    _, meta = await reader.daily('SPY', at, None)
    assert calls == ['SPY']
    assert meta['historySource'] == reader.provider_key
