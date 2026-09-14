"""Dated industry/leader observations for prospective research, never order authority."""
from __future__ import annotations

import hashlib
import json
import math
from statistics import median

from .data import DailyBar, completed_daily

VERSION = 'cartel-leader-context-1'


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def leader_evidence(saved):
    inputs, result = saved['config']['inputs'], saved['result']
    bars = completed_daily([DailyBar.model_validate(b) for b in inputs['history']], inputs['as_of_ms'])
    if not bars:
        return None
    checks = result['analysis'].get('checks', [])
    strength = next((c.get('value') for c in checks if c.get('name') == 'Relative strength versus benchmark'), None)
    sign = 1 if inputs['direction'] == 'long' else -1
    prior_volume = [b.volume for b in bars[-21:-1]]
    mean = sum(prior_volume)/len(prior_volume) if len(prior_volume) == 20 else None
    trend = next((g['status'] for g in result['screen']['gates'] if g.get('id') == 'M2'
                  or g.get('label') == 'Stock on direction side of selected EMAs'), 'unknown')
    return {'version': VERSION, 'symbol': saved['symbol'], 'asOfMs': inputs['as_of_ms'],
        'session': bars[-1].session.isoformat(), 'industry': inputs['facts'].get('industry') or 'Unclassified',
        'listingSource': inputs['data_source'],
        'historySource': result.get('collection', {}).get('historySource'),
        'historyObservedAt': result.get('collection', {}).get('historyObservedAt'),
        'direction': inputs['direction'], 'trendStatus': trend,
        'directionalRelativeStrength': strength*sign if finite(strength) else None,
        'dailyDollarVolume': bars[-1].close*bars[-1].volume,
        'volumeVsPrior20': bars[-1].volume/mean if mean and mean > 0 else None,
        'screenPassed': result['screen'].get('screenPassed') is True,
        'contractionStatus': next((c['status'] for c in checks if c.get('name') == 'Volume dries up in consolidation'), 'unknown'),
        'advisoryOnly': True}


def summarize_leaders(rows, discovery, at):
    """Keep every evaluated name in the denominator, even when setup gates fail."""
    members = {r['symbol']: r.get('industry') or 'Unclassified' for r in discovery.get('rows', [])}
    measured = {r['symbol']: r['leaderEvidence'] for r in rows if r.get('leaderEvidence')
                and r['leaderEvidence']['asOfMs'] == at and r['symbol'] in members}
    groups = []
    for group in sorted(set(members.values())):
        symbols = [s for s, industry in members.items() if industry == group]
        reads = [measured[s] for s in symbols if s in measured]
        strengths = [r['directionalRelativeStrength'] for r in reads if finite(r.get('directionalRelativeStrength'))]
        leaders = sorted(reads, key=lambda r: (-(r['directionalRelativeStrength'] if finite(r.get('directionalRelativeStrength')) else -math.inf),
                                              -r['dailyDollarVolume'], r['symbol']))
        groups.append({'industry': group, 'discovered': len(symbols), 'evaluated': len(reads),
            'trendPassed': sum(r['trendStatus'] == 'pass' for r in reads),
            'positiveRelativeStrength': sum(v > 0 for v in strengths), 'strengthKnown': len(strengths),
            'medianRelativeStrength': median(strengths) if strengths else None,
            'aboveAverageVolume': sum(finite(r.get('volumeVsPrior20')) and r['volumeVsPrior20'] > 1 for r in reads),
            'qualified': sum(r['screenPassed'] for r in reads), 'leaders': [r['symbol'] for r in leaders[:5]]})
    # Rank sufficiently measured groups for inspection, not the executable shortlist.
    groups.sort(key=lambda r: (-(r['medianRelativeStrength'] if r['strengthKnown'] >= 3 else -math.inf),
                               -r['evaluated'], r['industry']))
    return {'version': VERSION, 'asOfMs': at, 'advisoryOnly': True, 'discovered': len(members),
        'evaluated': len(measured), 'groups': groups,
        'basis': 'Industry membership is a theme proxy. Medians and participation describe evaluated listings only; missing histories are not failures. Groups with fewer than three strength observations are unranked. No order or ranking permission is granted.'}


def research_protocol(policy, *, code_version):
    snapshot = policy.model_dump(mode='json')
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'version': 'cartel-prospective-1', 'cohortId': f'{code_version}:{digest[:16]}',
        'policySha256': digest, 'codeVersion': code_version, 'checkpointSessions': 20,
        'allocationPolicy': snapshot.get('exit_allocation_policy', 'legacy'),
        'promotion': 'Preparation-policy cohort only; retained campaigns belong to their original preparation. No automatic promotion. Twenty sessions is a collection checkpoint, not proof of edge.',
        'denominator': 'All discovered listings, exclusions, pending contracts, signals, refusals, no-fills, fills and exits.',
        'valuation': 'Exact funded whole contracts and contemporaneous bid/ask evidence; missing quotes remain unknown.'}
