import pytest
from zargar.techniques.tip.analyst import parse_single_object, AnalystOpinion, ReviewOpinion
from zargar.signals.extraction import _parse_result_json

@pytest.mark.parametrize('kind', ['analyst', 'review', 'extraction'])
def test_scan_limit_never_certifies_uniqueness_with_unexamined_remainder(kind):
    if kind == 'analyst':
        parse = lambda s: parse_single_object(s, AnalystOpinion)
        first = '{"verdict":"skip","rationale":"x","confidence":0.5,"invalidation":"x"}'
        second = first.replace('"skip"', '"take"')
    elif kind == 'review':
        parse = lambda s: parse_single_object(s, ReviewOpinion)
        first = '{"headline":"first","details":"","watch":[],"missed_tip":null,"confidence":0.4}'
        second = first.replace('first', 'correction')
    else:
        parse = _parse_result_json
        first = '{"signals":[],"source_type":"other"}'
        second = first.replace('other', 'trade_alert')
    parse(first)
    parse(second)
    with pytest.raises(ValueError):
        parse(first + ' {"unrelated":1}' * 20 + '\nCorrection:\n' + second)
