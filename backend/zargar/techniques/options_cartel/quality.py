"""Explicit engineering measures; never replace nearby resistance with invented room."""
def target_room(trigger, invalidation, first_target):
    risk = abs(trigger-invalidation)
    return {'firstTargetPct': abs(first_target-trigger)/trigger*100,
            'structuralTargetR': abs(first_target-trigger)/risk if risk else 0}


def ranking_evidence(saved, review):
    candidate = next(c for c in saved['result']['analysis']['candidates'] if c['setup'] == review.setup)
    room = target_room(candidate['trigger'], candidate['invalidation'], review.reviewed_targets[0])
    checks = saved['result']['analysis']['checks']
    rs = next((c.get('value') for c in checks if c['name'] == 'Relative strength versus benchmark'), 0) or 0
    sign = 1 if saved['config']['inputs']['direction'] == 'long' else -1
    return {'symbol': saved['symbol'], **room, 'directionalRelativeStrength': float(rs)*sign,
            'dailyVolume': saved['result']['screen']['metrics'].get('dailyVolume') or 0,
            'basis': 'Engineering ranking: structural first-target R, directional relative strength, then volume. Not predicted option return.'}


def quality_key(evidence, symbol):
    return (-evidence['structuralTargetR'], -evidence['directionalRelativeStrength'], -evidence['dailyVolume'], symbol)
