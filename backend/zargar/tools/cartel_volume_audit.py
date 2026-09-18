"""Read-only SIP reconstruction. No database, settings, arms or trading imports.

python -m zargar.tools.cartel_volume_audit --env-file <runtime backend .env> --out-dir <evidence directory>
All network evidence is collected before comparisons; partial responses never pass parity.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
from pathlib import Path

import httpx

from ..config import AppConfig
from ..techniques.options_cartel.volume_reconstruction import compare
from .cartel_evidence import session_window


async def pages(client, url, params, key, max_pages):
    rows, hashes, tokens = [], [], set()
    for _ in range(max_pages):
        response = await client.get(url, params=params)
        response.raise_for_status()
        hashes.append(hashlib.sha256(response.content).hexdigest())
        body = response.json()
        if key not in body:
            raise ValueError(f'Missing {key} in provider response')
        rows.extend(body[key] or [])
        token = body.get('next_page_token')
        if not token:
            return rows, hashes, True
        if token in tokens:
            raise ValueError('Repeated pagination token')
        tokens.add(token)
        params = {**params, 'page_token': token}
        await asyncio.sleep(.05)
    return rows, hashes, False


async def audit(client, symbol, day, max_pages):
    opens, closes = session_window(day)
    iso = lambda ms: dt.datetime.fromtimestamp(ms/1000, dt.timezone.utc).isoformat().replace('+00:00','Z')
    request = {'start': iso(opens), 'end': iso(closes), 'feed': 'sip', 'limit': 10000, 'sort': 'asc'}
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    url = f'https://data.alpaca.markets/v2/stocks/{symbol}'
    bars, bh, bc = await pages(client, url+'/bars', {**request, 'timeframe': '1Min', 'adjustment': 'raw'}, 'bars', max_pages)
    trades, th, tc = await pages(client, url+'/trades', request, 'trades', max_pages)
    result = compare(trades, bars, opens, closes)
    if not bc or not tc:
        result['verdict'] = 'incomplete_evidence'
    return {**result, 'symbol': symbol, 'session': day, 'request': request, 'startedAt': started,
            'completedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'barsComplete': bc, 'tradesComplete': tc,
            'returnedTrades': len(trades), 'barPageHashes': bh, 'tradePageHashes': th,
            'note': 'Offline provider comparison only. No reconstructed data enters the trading engine. Historical tape is final-as-observed, not decision-time evidence.'}


async def run(args):
    cfg = AppConfig(_env_file=args.env_file) if args.env_file else AppConfig()
    if not cfg.alpaca_key_id or not cfg.alpaca_secret:
        raise ValueError('Alpaca credentials not configured')
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    headers = {'APCA-API-KEY-ID': cfg.alpaca_key_id, 'APCA-API-SECRET-KEY': cfg.alpaca_secret}
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        for case in args.case or ['PLAB:2026-09-16','LZB:2026-09-16','PWR:2026-09-17','AAPL:2026-09-17']:
            symbol, day = case.split(':')
            if not symbol.isalnum():
                raise ValueError('Use a simple stock symbol')
            try:
                report = await audit(client,symbol,day,args.max_pages)
            except (httpx.HTTPError, ValueError) as exc:
                report = {'symbol': symbol, 'session': day, 'verdict': 'incomplete_evidence', 'error': type(exc).__name__}
            path = out/f'provider-parity-{symbol}-{day}.json'
            path.write_text(json.dumps(report,sort_keys=True,default=str,separators=(',', ':'))+'\n',encoding='utf-8')
            print(symbol, day, report['verdict'], 'mismatches',report.get('mismatchCount'),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file')
    parser.add_argument('--out-dir',required=True)
    parser.add_argument('--case',action='append')
    parser.add_argument('--max-pages',type=int,default=250)
    args = parser.parse_args()
    if not 1 <= args.max_pages <= 1000:
        parser.error('max-pages must be between 1 and 1000')
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
