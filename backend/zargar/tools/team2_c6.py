"""C6 scoped Alpaca backfill + input evidence. No engine, orders, outcomes or setting writes.

Run from the authorized runtime backend after schema deployment. Default is read-only.
--apply archives before-images then upserts SPY/QQQ/IWM only. Historical plans stay untouched.
"""
import argparse
import asyncio
import datetime as dt
import json
from collections import Counter
from pathlib import Path
import httpx
from ..config import get_config
from ..db import create_all, make_engine, make_session_factory
from ..marketdata import load_bars, persist_bars, hash_bars
from ..marketstructure.history import _alpaca_window, set_alpaca_credentials
from ..marketstructure.sessions import ET, session_date
from ..marketstructure.aggregate import aggregate, bar_session
from ..techniques.team2.service import Team2Service
from ..techniques.team2.rules import Team2Rules
from ..techniques.team2.regime import RegimeReader
from ..techniques.team2.tape import save_snapshot, load_snapshot


def indicator_trace(bars):
    reader = RegimeReader(Team2Rules())
    return {b.ts: reader.update(b).to_dict() for b in aggregate(bars, 2)}


async def run(args):
    cfg = get_config()
    eng = make_engine(cfg.database_url); sf = make_session_factory(eng)
    start = int(dt.datetime.fromisoformat(args.start).replace(tzinfo=ET).timestamp() * 1000)
    end = int((dt.datetime.fromisoformat(args.end).replace(tzinfo=ET) + dt.timedelta(days=1)).timestamp() * 1000)
    now_et = dt.datetime.now(ET)
    if args.end > now_et.date().isoformat() or (args.end == now_et.date().isoformat() and now_et.hour < 20):
        raise ValueError("C6 repair requires completed dates only")
    out = {"start": args.start, "end": args.end, "apply": args.apply, "symbols": {}, "scope": "inputs/indicators only; no C2 outcomes"}
    by_symbol = {}
    try:
        if args.migrate:
            if not args.apply:
                raise ValueError('--migrate requires explicit --apply')
            await create_all(eng)
        if args.apply:
            if not cfg.alpaca_key_id or not cfg.alpaca_secret:
                raise ValueError("Alpaca credentials absent; no fallback permitted")
            set_alpaca_credentials(cfg.alpaca_key_id, cfg.alpaca_secret)
        async with httpx.AsyncClient() as http:
            for symbol in ('SPY', 'QQQ', 'IWM'):
                before = [b for b in await load_bars(sf, symbol, limit=100000) if start <= b.ts < end]
                archive = None
                if args.apply:
                    fetched = await _alpaca_window(symbol, '1m', start // 1000, end // 1000, http, session='ext')
                    if not fetched or any(b.provider != 'alpaca' for b in fetched):
                        raise ValueError(f"{symbol}: no confirmed Alpaca rows")
                    # Keep only valid market minutes; no synthesis of print-less minutes.
                    from ..marketstructure.market_calendar import is_market_minute
                    fetched = [b for b in fetched if start <= b.ts < end and is_market_minute(b.ts)]
                    _, validation = Team2Service.warmup_slice(fetched, sessions=12)
                    if len(validation['sessionsUsed']) != 12:
                        raise ValueError(f"{symbol}: insufficient fetched history")
                    archive = await save_snapshot(sf, before)
                    if await load_snapshot(sf, archive) != before:
                        raise ValueError("before-image verification failed")
                    await persist_bars(sf, fetched)
                rows = [b for b in await load_bars(sf, symbol, limit=100000) if start <= b.ts < end]
                canonical = [b for b in rows if b.provider == 'alpaca']
                by_symbol[symbol] = canonical
                warm, rep = Team2Service.warmup_slice(canonical, sessions=12)
                snap = await save_snapshot(sf, warm) if args.apply else None
                restored = await load_snapshot(sf, snap) if snap else warm
                old = {b.ts: b for b in before}
                diffs = [b.ts for b in canonical if b.ts in old and b.to_row() != old[b.ts].to_row()]
                before_trace, after_trace = indicator_trace(before), indicator_trace(canonical)
                indicators = [ts for ts in after_trace if ts in before_trace and after_trace[ts] != before_trace[ts]]
                out['symbols'][symbol] = {
                    'rows': len(canonical), 'providers': dict(Counter(b.provider or 'unknown' for b in rows)),
                    'excludedNoncanonical': len(rows) - len(canonical), 'archive': archive,
                    'sessions': dict(Counter(session_date(b.ts) for b in canonical)),
                    'rth': dict(Counter(session_date(b.ts) for b in canonical if bar_session(b.ts) == 'rth')),
                    'warmup': rep, 'warmupSnapshot': snap,
                    'restoredHashMatch': hash_bars({symbol: warm}) == hash_bars({symbol: restored}),
                    'indicatorParity': indicator_trace(warm) == indicator_trace(restored),
                    'changedMinutes': len(diffs), 'changedMinuteExamples': diffs[:30],
                    'changedIndicatorBuckets': len(indicators),
                    'firstIndicatorDifference': ({'ts': indicators[0], 'before': before_trace[indicators[0]],
                                                  'canonical': after_trace[indicators[0]]} if indicators else None)}
        out['dataset'] = hash_bars(by_symbol, start=args.start, end=args.end)
        out['inputsReady'] = all(x['rows'] and len(x['warmup']['sessionsUsed']) == 12 and x['restoredHashMatch']
                                 and x['indicatorParity'] for x in out['symbols'].values())
        Path(args.out).write_text(json.dumps(out, indent=2), encoding='utf-8')
        print(json.dumps({'inputsReady': out['inputsReady'], 'dataset': out['dataset'],
                          'symbols': {k: {'rows': v['rows'], 'changedMinutes': v['changedMinutes'],
                                         'excludedNoncanonical': v['excludedNoncanonical']} for k,v in out['symbols'].items()}}))
    finally:
        await eng.dispose()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', default='2026-08-03'); p.add_argument('--end', required=True)
    p.add_argument('--apply', action='store_true'); p.add_argument('--out', required=True)
    p.add_argument('--migrate', action='store_true', help='apply established additive schema migration before repair')
    asyncio.run(run(p.parse_args()))
