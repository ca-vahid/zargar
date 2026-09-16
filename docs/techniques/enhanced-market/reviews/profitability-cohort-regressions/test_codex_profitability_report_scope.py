from zargar.tools.em_profitability import payoff_to_tp1, summarize


def test_put_delta_can_produce_a_positive_downside_payoff_proxy():
    assert payoff_to_tp1(-0.5, 100.0, 95.0, 1.0) == 250.0, 'A valid negative put delta is not missing evidence'


def test_economics_table_keeps_refused_intents_with_unknown_quotes():
    refused = {'symbol': 'WDC', 'trigger': 'b1', 'cohort': None,
               'refusal': 'position cap', 'underlyingProxy': 'unresolved',
               'roomBin': 'unknown', 'friction': None, 'intendedQty': 89.0}
    result = summarize({'trades': [], 'refused': [refused]})
    assert any(row['symbol'] == 'WDC' for row in result['p03']), 'Unscorable refused intents must remain visible in contract economics'
