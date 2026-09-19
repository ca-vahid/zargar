"""The agreed 30-minute Practice experiment review, independent of agent availability.

Sampled peak-to-trough thresholds, not guaranteed loss limits. Protective exits remain active.
"""
import asyncio
import datetime as dt
from ...marketstructure.sessions import ET
from ...marketstructure.market_calendar import is_trading_day
from .rules import validate_experiments

STATE_KEY = 'techniques.team2.experiment_observation'
THRESHOLDS = {'sizing': 800., 'c1': 1000.}


async def sample_books(engine):
    lock = getattr(engine, '_team2_observation_lock', None)
    if lock is None:
        lock = engine._team2_observation_lock = asyncio.Lock()
    async with lock:
        state = dict(engine.settings.get(STATE_KEY, {}) or {})
        now = dt.datetime.now(ET)
        if not state.get('startDate') or now.date().isoformat() < state['startDate'] or not is_trading_day(now.date()):
            return {'skipped': 'not started'}
        config = validate_experiments(engine.settings)
        if not config['enabled'] or config['errors']:
            return {'skipped': 'disabled or invalid'}
        samples = []
        books = dict(state.get('books') or {})
        for book in config['books']:
            pid, role = book['portfolioId'], book['role']
            p = engine.positions.portfolio(pid)
            if not p or p.get('kind') != 'sim' or pid not in books:
                continue
            eq, missing = float(p['cash']), []
            for pos in engine.positions.positions_list(pid):
                qty = float(pos['qty'])
                if not qty:
                    continue
                q = engine.quotes.get(pos['symbol'])
                ts = int(getattr(q, 'source_ts', 0) or 0) if q else 0
                age = now.timestamp() * 1000 - ts
                if (not q or getattr(q, 'delayed', True) or not ts or not 0 <= age <= 180_000
                        or q.bid <= 0 or q.ask < q.bid or qty < 0 or pos.get('currency', 'USD') != 'USD'):
                    missing.append(pos['symbol']); continue
                eq += qty * q.bid * (100 if pos['secType'] == 'OPT' else 1)
            previous = dict(books[pid])
            rec = {'portfolioId': pid, 'role': role, 'at': now.isoformat(), 'markingBasis': 'fresh bid; cash includes fees',
                   'threshold': THRESHOLDS[role], 'missingMarks': missing, 'startingEquity': previous['startingEquity']}
            if not missing:
                high = max(float(previous.get('highWater', previous['startingEquity'])), eq)
                drawdown = high - eq
                rec.update(equity=eq, highWater=high, drawdown=drawdown)
                if drawdown >= THRESHOLDS[role] and not engine.halt.book_paused(pid):
                    await engine.pause_book(pid, f'Team2 experiment sampled drawdown ${drawdown:.2f}',
                                            source='team2', label=book['label'])
                books[pid] = {**previous, **rec}
            rec['paused'] = engine.halt.book_paused(pid)
            await engine.journal.append('Team2ExperimentSample', rec, aggregate_type='portfolio', aggregate_id=pid)
            samples.append(rec)
        state['books'] = books
        await engine.settings.set(STATE_KEY, state)
        return {'samples': samples}
