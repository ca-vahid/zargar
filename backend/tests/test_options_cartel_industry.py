import pytest

from zargar.techniques.options_cartel.industry import IndustrySnapshot, read_industry


def snapshot(values):
    return IndustrySnapshot(source='synthetic complete universe', observed_at=2000, data_as_of_ms=1000,
        expected_count=len(values), week_definition='provider 1W', month_definition='provider 1M',
        rows=[{'industry': name, 'weekPct': week, 'monthPct': month} for name, week, month in values])


def test_tie_across_top_boundary_stays_unknown():
    data = snapshot([('A', 5, 5), ('B', 4, 4), ('C', 4, 4)])
    result = read_industry(data, 'B', at=2000, top_n=2)
    assert result['status'] == 'unknown'
    assert result['weekRank'] == {'best': 2, 'worst': 3}
    assert read_industry(data, 'A', at=2000, top_n=2)['status'] == 'pass'


def test_missing_values_expand_rank_uncertainty_instead_of_becoming_zero():
    data = snapshot([('A', 5, 5), ('B', None, None)])
    result = read_industry(data, 'A', at=2000, top_n=1)
    assert result['status'] == 'unknown' and result['monthRank']['worst'] == 2
    assert read_industry(data, 'B', at=2000)['weekRank'] is None


def test_bearish_ranking_reverses_performance_order_and_requires_both_periods():
    data = snapshot([('A', 5, -5), ('B', -5, -4), ('C', -3, -3)])
    assert read_industry(data, 'B', at=2000, direction='short', top_n=2)['status'] == 'pass'
    assert read_industry(data, 'A', at=2000, direction='short', top_n=2)['status'] == 'fail'


def test_observation_time_and_underlying_data_age_are_separate_gates():
    data = snapshot([('A', 5, 5)])
    assert read_industry(data, 'A', at=1500)['status'] == 'unknown'
    assert read_industry(data, 'A', at=8*86_400_000)['status'] == 'unknown'
    assert read_industry(data, 'missing', at=2000)['status'] == 'unknown'


def test_incomplete_or_duplicate_universe_is_rejected():
    body = snapshot([('A', 5, 5)]).model_dump()
    with pytest.raises(ValueError):
        IndustrySnapshot.model_validate({**body, 'expected_count': 2})
    with pytest.raises(ValueError):
        snapshot([('A', 5, 5), (' a ', 4, 4)])


def test_unknown_data_timestamp_can_be_saved_but_cannot_establish_rank_eligibility():
    data = snapshot([('A', 5, 5)]).model_copy(update={'data_as_of_ms': None})
    assert read_industry(data, 'A', at=2000)['status'] == 'unknown'


def test_descriptive_ranks_do_not_establish_freshness_or_remove_tie_uncertainty():
    from zargar.techniques.options_cartel.industry import captured_ranks
    data = snapshot([('A', 5, 1), ('B', 5, 2), ('C', None, 3)]).model_copy(update={'data_as_of_ms': None})
    ranks = captured_ranks(data)
    assert ranks['A']['bullish']['weekRank'] == {'best': 1, 'worst': 3}
    assert ranks['A']['bullish']['monthRank'] == {'best': 3, 'worst': 3}
    assert read_industry(data, 'A', at=2000)['status'] == 'unknown'


async def test_capture_review_ranks_do_not_rewrite_saved_evidence(engine):
    from zargar.techniques.options_cartel.industry import save_snapshot
    from zargar.techniques.options_cartel.service import CartelService
    service = CartelService(engine)
    data = snapshot([('A', 5, 5)]).model_copy(update={'data_as_of_ms': None})
    saved = await save_snapshot(service, data, now_ms=2000)
    assert saved['result']['rows'][0]['capturedRanks']['bullish']['weekRank'] == {'best': 1, 'worst': 1}
    raw = await service._load(saved['runId'])
    assert 'capturedRanks' not in raw.result['rows'][0]
    assert raw.result['rows'][0]['bullish']['status'] == 'unknown'
