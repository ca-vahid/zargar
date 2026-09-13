"""Source-dated post-ignition research. This module cannot arm or place orders."""
from __future__ import annotations

import datetime as dt
import hashlib

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ...marketstructure.indicators import ema_series
from ...models import CartelIgnitionThesis
from .data import completed_daily

VERSION = 'post_ignition_2026_09_11:v1'
SOURCE = 'https://www.youtube.com/watch?v=7xSMgmLoqM8'


def detect(history, at):
    bars = completed_daily(history, at)
    if len(bars) < 55:
        return []
    closes = [b.close for b in bars]
    e8, e50 = ema_series(closes, 8), ema_series(closes, 50)
    out = []
    for i in range(max(50, len(bars)-40), len(bars)):
        event = bars[i]
        prior = bars[i-20:i]
        average = sum(b.volume for b in prior)/20
        avg10 = sum(b.volume for b in bars[i-10:i])/10
        adr = sum((b.high-b.low)/b.low*100 for b in prior)/20
        change = (event.close/bars[i-1].close-1)*100
        ratio = event.volume/average if average > 0 else 0
        if not (event.close > 5 and change > 5 and avg10 > 500_000 and adr > 2 and event.close > e50[i] and ratio >= 3):
            continue
        consolidation = bars[i+1:]
        age = len(consolidation)
        stage = 'ignition_verified' if age < 2 else 'consolidating'
        reasons = []
        level = stop = None
        if age > 15:
            stage = 'expired'
        elif any(b.close < event.low or b.close < b.open and b.volume > event.volume for b in consolidation):
            stage = 'invalidated'
        elif age >= 2:
            level, stop = max(b.high for b in consolidation), min(b.low for b in consolidation)
            quiet = sum(b.volume for b in consolidation)/age < event.volume*.5
            tight = (level-stop)/stop*100 <= 12
            near = abs(closes[-1]/e8[-1]-1)*100 <= 3
            rising = e8[-1] > e8[-2]
            for passed, reason in ((quiet,'Consolidation volume is not sufficiently below ignition'),(tight,'Consolidation range exceeds 12%'),(near,'Price is not within 3% of EMA8'),(rising,'EMA8 is not rising')):
                if not passed:
                    reasons.append(reason)
            if not reasons:
                stage = 'setup_ready'
        out.append({'id': hashlib.sha256(f'{VERSION}:{event.symbol}:{event.session}'.encode()).hexdigest(),
            'symbol': event.symbol, 'eventSession': event.session.isoformat(), 'asOf': at,
            'stage': stage, 'eventVolumeRatio': ratio, 'eventChangePct': change,
            'eventGapPct': (event.open/bars[i-1].close-1)*100,
            'consolidationSessions': age, 'trigger': level, 'invalidation': stop,
            'reasons': reasons, 'source': SOURCE, 'profile': VERSION, 'direction': 'long',
            'placesOrders': False, 'researchOnly': True, 'catalyst': 'unverified',
            'engineering': {'volumeAverageSessions':20,'minIgnitionMultiple':3,'minConsolidationSessions':2,
                'maxConsolidationSessions':15,'maxRangePct':12,'maxEmaDistancePct':3,'maxVolumeFraction':.5},
            'note': 'Developing research thesis, not an execution plan. Source numeric examples require calibration; no automatic promotion.'})
    return out


async def record(engine, history, at):
    rows = detect(history, at)
    async with engine.sf() as session, session.begin():
        for item in rows:
            args = {'id': item['id'], 'symbol': item['symbol'], 'event_session': item['eventSession'],
                    'as_of': at, 'stage': item['stage'], 'evidence': item, 'updated_at': dt.datetime.now(dt.UTC)}
            statement = insert(CartelIgnitionThesis).values(**args)
            await session.execute(statement.on_conflict_do_update(index_elements=['id'],
                set_={k:v for k,v in args.items() if k != 'id'}, where=CartelIgnitionThesis.as_of <= at))
    return rows


async def watchlist(engine, *, include_inactive=False):
    async with engine.sf() as session:
        query = select(CartelIgnitionThesis)
        if not include_inactive:
            query = query.where(CartelIgnitionThesis.stage.notin_(('expired', 'invalidated')))
        rows = (await session.scalars(query.order_by((CartelIgnitionThesis.stage == 'setup_ready').desc(), CartelIgnitionThesis.as_of.desc(), CartelIgnitionThesis.symbol).limit(200))).all()
    return {'profile': VERSION, 'researchOnly': True, 'placesOrders': False,
            'rows': [r.evidence for r in rows]}
