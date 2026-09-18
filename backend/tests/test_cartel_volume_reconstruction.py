from zargar.tools.cartel_evidence import session_window
from zargar.techniques.options_cartel.volume_reconstruction import compare, eligibility, reconstruct, trade_timestamp_ns


def trade(t, size=10, conditions=None, price=10, tape='C'):
    return {'t': t, 'p': price, 's': size, 'c': conditions or ['@'], 'z': tape}


def test_matrix_is_field_specific_and_combines_conditions():
    assert eligibility('C', ['@', 'I']) == (False, False, True)
    assert eligibility('A', ['B']) == (False, False, True)
    assert eligibility('C', ['B']) == (True, True, True)
    assert eligibility('C', ['@', 'M']) == (False, False, False)


def test_suppressed_odd_lot_volume_is_not_emitted_or_double_counted():
    o,c = session_window('2026-09-17')
    trades = [trade('2026-09-17T13:30:00Z', conditions=['I']),
              trade('2026-09-17T13:31:00Z', 100), trade('2026-09-17T13:31:01Z', 10, ['I'])]
    bars = [{'t': '2026-09-17T13:31:00Z', 'o': 10, 'h': 10, 'l': 10, 'c': 10, 'v': 110}]
    report = compare(trades, bars, o,c)
    assert report['verdict'] == 'provider_parity'
    assert report['eligibleTradeVolume'] == 120
    assert report['suppressedEligibleVolume'] == 10
    assert report['reconstructedEmittedVolume'] == 110


def test_early_close_boundaries_and_nanosecond_order():
    o,c = session_window('2026-11-27')
    rows = [trade('2026-11-27T17:59:59.999999999Z', 100, price=11),
            trade('2026-11-27T17:59:59.999999998Z', 100, price=10),
            trade('2026-11-27T18:00:00Z', 100, price=99)]
    report = reconstruct(rows,o,c)
    assert (c-o)//60000 == 210 and report['outsideBoundary'] == 1
    last = report['bars'][c-60000]
    assert last['o'] == 10 and last['c'] == 11 and last['v'] == 200
    assert trade_timestamp_ns(rows[0]['t']) - trade_timestamp_ns(rows[1]['t']) == 1


def test_unknown_conditions_and_volume_discrepancy_fail_parity():
    o,c = session_window('2026-09-17')
    unknown = compare([trade('2026-09-17T13:30:00Z', conditions=['?'])], [],o,c)
    assert unknown['verdict'] == 'unmapped_conditions'
    bars = [{'t': '2026-09-17T13:30:00Z', 'o': 10, 'h': 10, 'l': 10, 'c': 10, 'v': 11}]
    report = compare([trade('2026-09-17T13:30:00Z')], bars,o,c)
    assert report['verdict'] == 'mismatch' and report['mismatches'][0]['fields'] == ['v']
