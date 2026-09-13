"""Cartel-only, backward-compatible candle provenance. Shared Bar.to_row stays unchanged."""
from __future__ import annotations

import hashlib
import json

from ...domain import Bar

RANK = {'': 0, 'unknown': 0, 'sampled': 1, 'sim': 2, 'exchange': 3}


def pack(bar):
    return [*bar.to_row(), bar.source or 'unknown']


def unpack(symbol, values):
    return Bar(symbol, '1m', *values[:6], source=values[6] if len(values) > 6 else 'unknown')


def trusted(bar, *, simulation=False):
    return bar.source == 'exchange' or simulation and bar.source == 'sim'


def merge(minutes, bar):
    """Upgrade provenance, preserve equal-quality first observation; never downgrade.

    Provider corrections with equal provenance require an explicit revision-aware
    repair, rather than silently rewriting a decision's input.
    """
    key = str(bar.ts)
    old = minutes.get(key)
    if old is None or RANK.get(bar.source, 0) > RANK.get(old[6] if len(old) > 6 else '', 0):
        minutes[key] = pack(bar)
        return True
    return False


def evidence(minutes):
    ordered = sorted(minutes.values(), key=lambda x: x[0])
    counts = {}
    for v in ordered:
        source = v[6] if len(v) > 6 else 'unknown'
        counts[source] = counts.get(source, 0)+1
    return {'schemaVersion': 2, 'sourceCounts': counts,
            'inputHash': hashlib.sha256(json.dumps(ordered, separators=(',', ':')).encode()).hexdigest()}
