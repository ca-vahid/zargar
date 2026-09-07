"""The publisher's complete industry performance snapshot; no inferred weights."""
from __future__ import annotations

import httpx

from ...domain import now_ms
from .discovery import URL
from .industry import IndustrySnapshot

COLUMNS = ('name', 'description', 'Perf.W', 'Perf.1M', 'time', 'update_mode')


async def capture_industries(*, client=None, clock=now_ms):
    own = client is None
    client = client or httpx.AsyncClient(timeout=30.)
    body = {'filter': [{'left': 'description', 'operation': 'nempty'}], 'options': {'lang': 'en'},
        'symbols': {'query': {'types': ['industry']}, 'tickers': []}, 'columns': list(COLUMNS),
        'sort': {'sortBy': 'description', 'sortOrder': 'asc'}, 'range': [0, 500]}
    try:
        response = await client.post(URL, json=body)
        response.raise_for_status()
        payload = response.json()
    finally:
        if own:
            await client.aclose()
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
        raise ValueError('invalid industry publisher response')  # noqa: TRY004 - external data validation
    total, data = payload.get('totalCount'), payload['data']
    if not isinstance(total, int) or isinstance(total, bool) or not 1 <= total <= 500 or len(data) != total:
        raise ValueError('publisher industry universe is incomplete')
    rows, ids, modes = [], set(), set()
    for row in data:
        identity, values = row.get('s'), row.get('d')
        if not isinstance(identity, str) or not identity.startswith('INDUSTRY_US:') or identity in ids \
                or not isinstance(values, list) or len(values) != len(COLUMNS):
            raise ValueError('invalid or duplicate publisher industry identity')
        ids.add(identity)
        raw = dict(zip(COLUMNS, values))
        modes.add(raw['update_mode'])
        rows.append({'industry': raw['description'], 'weekPct': raw['Perf.W'], 'monthPct': raw['Perf.1M']})
    if modes != {'streaming'}:
        raise ValueError('industry publication update mode is not the expected streaming snapshot')
    observed = clock()
    snapshot = IndustrySnapshot(source=URL+' (US industry publication)', observed_at=observed,
        data_as_of_ms=None, freshness_basis='publisher_observation', expected_count=total,
        week_definition='Publisher Perf.W; consumed directly, not recomputed',
        month_definition='Publisher Perf.1M; consumed directly, not recomputed', rows=rows)
    return snapshot, {'query': body, 'publisherRows': data, 'observedAt': observed,
        'timestampPolicy': 'Current publisher snapshot; observation-aged context valid for at most 24 hours. Constituent data time is unknown.'}
