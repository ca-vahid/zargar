from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.leader_context import research_protocol, summarize_leaders


def test_group_observations_keep_failed_setups_and_missing_coverage_distinct():
    discovery = {'rows': [{'symbol': s, 'industry': 'Group'} for s in ('A', 'B', 'C', 'MISSING')]}
    rows = [{'symbol': s, 'status': 'filtered', 'leaderEvidence': {'symbol': s, 'asOfMs': 100,
             'directionalRelativeStrength': rs, 'dailyDollarVolume': 500, 'trendStatus': 'pass',
             'screenPassed': False, 'volumeVsPrior20': 2}} for s, rs in [('A', 5), ('B', -2), ('C', None)]]
    result = summarize_leaders(rows, discovery, 100)
    group = result['groups'][0]
    assert (group['discovered'], group['evaluated'], group['strengthKnown']) == (4, 3, 2)
    assert group['medianRelativeStrength'] == 1.5
    assert group['positiveRelativeStrength'] == 1
    assert group['qualified'] == 0
    assert result['advisoryOnly']
    assert [r['status'] for r in rows] == ['filtered']*3


def test_future_or_other_snapshot_observations_do_not_enter_advisory():
    discovery = {'rows': [{'symbol': 'A', 'industry': 'Group'}]}
    result = summarize_leaders([{'symbol': 'A', 'leaderEvidence': {'asOfMs': 101}}], discovery, 100)
    assert result['evaluated'] == 0
    assert result['groups'][0]['medianRelativeStrength'] is None


def test_frozen_cohort_changes_with_policy_or_code_not_outcomes():
    policy = PreparationPolicy()
    first = research_protocol(policy, code_version='v1')
    assert first == research_protocol(policy, code_version='v1')
    assert first['cohortId'] != research_protocol(policy.model_copy(update={'risk_pct': 5}), code_version='v1')['cohortId']
    assert first['cohortId'] != research_protocol(policy, code_version='v2')['cohortId']
    assert first['checkpointSessions'] == 20
    assert 'No automatic promotion' in first['promotion']
