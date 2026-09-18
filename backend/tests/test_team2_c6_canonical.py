from dataclasses import replace
from types import SimpleNamespace
import pytest
from zargar.domain import Bar
from zargar.marketdata import persist_bars, load_bars, merge_exchange, hash_bars, BarAggregator
from zargar.bus import Bus
from zargar.db import make_engine, make_session_factory
from zargar.techniques.team2.tape import save_snapshot, load_snapshot
from .conftest import TEST_DB_URL
from .test_codex_team2_data_eod import rig, ms


def sample(provider='alpaca', close=100., volume=100):
    return Bar('SPY', '1m', ms(10, 0), 100., max(101., close), 99., close, volume,
               source='exchange', provider=provider)


@pytest.mark.parametrize('batch', [True, False])
async def test_provider_precedence_matches_memory_flush_and_db(fresh_db, batch):
    eng = make_engine(TEST_DB_URL); sf = make_session_factory(eng)
    try:
        a, y = sample(), sample('yahoo', 105.)
        if batch:
            await persist_bars(sf, [a, y])
        else:
            await persist_bars(sf, [a]); await persist_bars(sf, [y])
        rows = await load_bars(sf, 'SPY')
        assert rows == [a] and merge_exchange(a, y) == a
        await persist_bars(sf, [sample('alpaca', 102., 50)])
        assert (await load_bars(sf, 'SPY'))[0].volume == 50
        agg = BarAggregator(Bus()); agg.ingest_exchange_bar(a); agg.ingest_exchange_bar(y)
        assert agg.bars('SPY', include_forming=False) == [a]
    finally:
        await eng.dispose()


async def test_frozen_warmup_survives_bank_revision_and_hashes_provider(fresh_db):
    eng = make_engine(TEST_DB_URL); sf = make_session_factory(eng)
    try:
        a = sample()
        ident = await save_snapshot(sf, [a])
        assert await save_snapshot(sf, [a]) == ident
        await persist_bars(sf, [sample('alpaca', 105.)])
        assert await load_snapshot(sf, ident) == [a]
        assert hash_bars({'SPY': [a]}) != hash_bars({'SPY': [replace(a, provider='yahoo')]})
        with pytest.raises(ValueError, match='missing'):
            await load_snapshot(sf, 'absent')
    finally:
        await eng.dispose()


def test_private_tape_uses_identical_correction_policy():
    runner, ap = rig()
    runner._bars[ap.run_id] = [sample()]
    assert runner._merge_revision(ap, sample('yahoo', 105.)) is None
    runner.merge_bars(ap, [sample('alpaca', 102., 50)])
    assert runner._bars[ap.run_id][0].close == 102.
    assert runner._bars[ap.run_id][0].volume == 50


async def test_additive_provider_migration_preserves_existing_bar(fresh_db):
    from sqlalchemy import text
    from zargar.db import create_all
    eng = make_engine(TEST_DB_URL); sf = make_session_factory(eng)
    try:
        await persist_bars(sf, [sample()])
        async with eng.begin() as conn:
            await conn.execute(text('ALTER TABLE bars DROP COLUMN provider'))
        await create_all(eng)
        rows = await load_bars(sf, 'SPY')
        assert len(rows) == 1 and rows[0].close == 100. and rows[0].provider == ''
    finally:
        await eng.dispose()


async def test_live_loader_uses_same_frozen_warmup_after_bank_changes(fresh_db):
    from .test_team2_session import prev_day_bars
    from zargar.techniques.team2.service import Team2Service
    from zargar.techniques.team2.runner import Team2Runner
    eng = make_engine(TEST_DB_URL); sf = make_session_factory(eng)
    try:
        bars = [replace(b, source='exchange', provider='alpaca') for b in prev_day_bars()]
        warm, original = Team2Service.warmup_slice(bars, sessions=12)
        assert warm
        snap = await save_snapshot(sf, warm)
        await persist_bars(sf, [replace(b, high=b.high + 1) for b in bars])
        runner, ap = rig(); runner.engine.sf = sf
        ap.plan.update(inputProvider='alpaca', warmup={'snapshot': snap})
        await Team2Runner._load_warmup(runner, ap)
        assert runner._warm[ap.run_id] == warm
        assert ap.plan['warmup']['hash'] == original['hash']
        replay_warm = await load_snapshot(sf, snap)
        assert Team2Service.warmup_slice(replay_warm, sessions=12)[1]['hash'] == original['hash']
    finally:
        await eng.dispose()


@pytest.mark.parametrize('cash,expect_pause', [(9201., False), (9200., True)])
async def test_sampled_experiment_threshold_pauses_only_its_book(monkeypatch, cash, expect_pause):
    from unittest.mock import AsyncMock
    from zargar.techniques.team2.experiment_watch import sample_books, STATE_KEY
    import zargar.techniques.team2.experiment_watch as watch
    monkeypatch.setattr(watch, 'is_trading_day', lambda _: True)
    values = {'techniques.team2.experiments': {'enabled': True, 'control': 'control', 'books': [
        {'portfolioId': 'sizing', 'label': 'Sizing', 'role': 'sizing', 'overrides': {'size_full': .5}},
        {'portfolioId': 'c1', 'label': 'C1', 'role': 'c1', 'overrides': {'no_trade_zone': 'conjunction'}}]},
        STATE_KEY: {'startDate': '2000-01-01', 'books': {'sizing': {'startingEquity': 10000., 'highWater': 10000.},
                                                    'c1': {'startingEquity': 10000., 'highWater': 10000.}}}}
    settings = SimpleNamespace(get=lambda k,d=None: values.get(k,d), set=AsyncMock())
    engine = SimpleNamespace(settings=settings, positions=SimpleNamespace(
        portfolio=lambda pid: {'kind': 'sim', 'cash': cash if pid == 'sizing' else 10000.}, positions_list=lambda _: []),
        halt=SimpleNamespace(book_paused=lambda _: False), pause_book=AsyncMock(), journal=SimpleNamespace(append=AsyncMock()))
    result = await sample_books(engine)
    assert len(result['samples']) == 2
    assert engine.pause_book.await_count == int(expect_pause)
    if expect_pause:
        assert engine.pause_book.await_args.args[0] == 'sizing'
    settings.set.assert_awaited_once()
