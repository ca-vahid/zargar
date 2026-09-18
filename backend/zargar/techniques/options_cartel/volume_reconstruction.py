"""Offline provider parity; never imported by trading/arming paths.

Frozen Alpaca market-data FAQ matrix, retrieved 2026-09-18:
https://docs.alpaca.markets/us/docs/market-data-faq#how-are-bars-aggregated
Rules apply separately to open/close, high/low and volume, per tape and condition.
Unknown conditions fail the comparison rather than silently becoming regular trades.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
import calendar
import datetime as dt
import re

def trade_timestamp_ns(value: str) -> int:
    match = re.fullmatch(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z', value)
    if not match:
        raise ValueError(f'Unsupported SIP timestamp: {value!r}')
    seconds = calendar.timegm(dt.datetime.strptime(match[1], '%Y-%m-%dT%H:%M:%S').timetuple())
    return seconds * 1_000_000_000 + int((match[2] or '').ljust(9, '0'))

VERSION = 'alpaca-minute-eligibility-v1'
SOURCE = 'https://docs.alpaca.markets/us/docs/market-data-faq#how-are-bars-aggregated'
PRICE_TOLERANCE = Decimal('0.000001')  # fixed before collecting results; volume tolerance is zero


def eligibility(tape: str, conditions: list[str]) -> tuple[bool, bool, bool]:
    """Minute-only rules: (open/close, high/low, volume). No daily-rule reuse."""
    if tape not in ('A', 'B', 'C', 'O') or not conditions:
        raise ValueError(f'Unknown tape/conditions: {tape!r}/{conditions!r}')
    rules = []
    for condition in conditions:
        if (condition == ' ' and tape in 'AB') or (condition == '@' and tape in 'CO'):
            rule = (True, True, True)
        elif condition in ('C', 'H', 'I', 'N', 'P', 'R', 'U'):
            rule = (False, False, True)
        elif condition == 'B' and tape in 'ABC':
            rule = (tape == 'C', tape == 'C', True)
        elif condition == 'W' and tape in 'CO':
            rule = (False, False, True)
        elif condition in ('G', 'V', 'Z', '4', '7') and tape in 'ABC':
            rule = (False, False, True)
        elif condition in ('M', 'Q', '9') and tape in 'ABC':
            rule = (False, False, False)
        elif condition in ('A', 'D', 'Y') and tape == 'C':
            rule = (True, True, True)
        elif condition == 'E' and tape in 'AB':
            rule = (True, True, True)
        elif condition in ('F', 'K', 'L', 'O', 'T', 'X', '5', '6') and tape in 'ABC':
            rule = (True, True, True)
        else:
            raise ValueError(f'Unmapped condition {condition!r} on tape {tape!r}')
        rules.append(rule)
    return tuple(all(r[i] for r in rules) for i in range(3))


def reconstruct(trades: list[dict], opens: int, closes: int) -> dict:
    """Consume a complete, timestamp-sorted SIP response. Bounds are UTC milliseconds."""
    buckets, unknown, seen = {}, Counter(), set()
    duplicates = outside = 0
    for t in sorted(trades, key=lambda x: trade_timestamp_ns(x['t'])):
        ns = trade_timestamp_ns(t['t'])
        if not opens * 1_000_000 <= ns < closes * 1_000_000:
            outside += 1
            continue
        identity = (t.get('z'), t.get('x'), t.get('i'), ns)
        if t.get('i') is not None and identity in seen:
            duplicates += 1
            continue
        seen.add(identity)
        minute = ns // 60_000_000_000 * 60_000
        b = buckets.setdefault(minute, {'o': None, 'h': None, 'l': None, 'c': None, 'v': 0, 'n': 0})
        try:
            oc, hl, vol = eligibility(t.get('z'), t.get('c') or [])
        except ValueError as exc:
            unknown[str(exc)] += 1
            continue
        p, size = Decimal(str(t['p'])), int(t['s'])
        if p <= 0 or size <= 0:
            unknown['nonpositive price/size'] += 1
            continue
        if oc:
            if b['o'] is None:
                b['o'] = p
            b['c'] = p
        if hl:
            b['h'] = max(b['h'], p) if b['h'] is not None else p
            b['l'] = min(b['l'], p) if b['l'] is not None else p
        if vol:
            b['v'] += size
            b['n'] += 1
    emitted = {ts: b for ts, b in buckets.items() if all(b[k] for k in ('o', 'h', 'l', 'c', 'v'))}
    return {'bars': emitted, 'eligibleVolume': sum(b['v'] for b in buckets.values()),
            'suppressedVolume': sum(b['v'] for ts, b in buckets.items() if ts not in emitted),
            'unknown': dict(unknown), 'duplicates': duplicates, 'outsideBoundary': outside}


def compare(trades: list[dict], provider_bars: list[dict], opens: int, closes: int) -> dict:
    result = reconstruct(trades, opens, closes)
    expected = {trade_timestamp_ns(b['t']) // 1_000_000: b for b in provider_bars
                if opens * 1_000_000 <= trade_timestamp_ns(b['t']) < closes * 1_000_000}
    mismatches = []
    for ts in sorted(set(expected) | set(result['bars'])):
        actual, provider = result['bars'].get(ts), expected.get(ts)
        if actual is None or provider is None:
            mismatches.append({'minuteMs': ts, 'reason': 'emission', 'reconstructed': actual, 'provider': provider})
            continue
        fields = [k for k in ('o', 'h', 'l', 'c') if abs(actual[k] - Decimal(str(provider[k]))) > PRICE_TOLERANCE]
        if actual['v'] != provider['v']:
            fields.append('v')
        if fields:
            mismatches.append({'minuteMs': ts, 'fields': fields, 'reconstructed': actual,
                               'provider': {k: provider[k] for k in ('o', 'h', 'l', 'c', 'v')}})
    return {'version': VERSION, 'source': SOURCE, 'sessionMinutes': (closes-opens)//60000,
            'priceTolerance': str(PRICE_TOLERANCE), 'volumeTolerance': 0,
            'verdict': 'unmapped_conditions' if result['unknown'] else 'mismatch' if mismatches else 'provider_parity',
            'providerBars': len(expected), 'reconstructedBars': len(result['bars']),
            'providerEmittedVolume': sum(b['v'] for b in expected.values()),
            'reconstructedEmittedVolume': sum(b['v'] for b in result['bars'].values()),
            'eligibleTradeVolume': result['eligibleVolume'], 'suppressedEligibleVolume': result['suppressedVolume'],
            'unknown': result['unknown'], 'duplicates': result['duplicates'], 'outsideBoundary': result['outsideBoundary'],
            'mismatchCount': len(mismatches), 'mismatches': mismatches}
