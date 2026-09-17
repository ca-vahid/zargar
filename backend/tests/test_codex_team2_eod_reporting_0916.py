"""Sep16 close-summary defects: synthetic records only, no DB/network/orders.
Counts are unique decisions, with price revisions retained as evidence versions.
"""
from zargar.execution.planrunner import PlanRunner
from .test_codex_team2_data_eod import rig,ms


def clean():
    runner,ap=rig()
    runner._last_sim[ap.run_id]={'trades':[],'bias':{}}
    return runner,ap


def test_bar_revision_volume_cannot_erase_an_earlier_refusal_from_the_close():
    runner,ap=clean()
    PlanRunner._log(runner,ap,'max_concurrent_skip','another position is open',
                    trigger='pm_break_up@09:30#1',ts=ms(10,2))
    assert runner._score_execution(ap)['skips'].get('max_concurrent_skip')==1
    for n in range(401):
        PlanRunner._log(runner,ap,'bar_revised','updated minute',ts=ms(11,0)+n)
    assert len(ap.events)==400
    assert runner._score_execution(ap)['skips'].get('max_concurrent_skip',0)==1, 'close summary lost a real refusal to the display-event cap'


def test_revised_price_on_same_refused_candidate_is_one_decision():
    runner,ap=clean()
    for price in ('760.37','760.38'):
        PlanRunner._log(runner,ap,'skip_no_trade_zone',f'entry {price} sits inside the pre-market range',
                        trigger='scenario_1@11:00',setup='scenario_1@11:00',touch=1,ts=ms(11,18))
    assert runner._score_execution(ap)['skips']['skip_no_trade_zone']==1, 'one candidate is counted twice after its price is revised'


def test_distinct_refusal_times_remain_distinct():
    runner,ap=clean()
    for minute in (18,22):
        PlanRunner._log(runner,ap,'skip_no_trade_zone','entry inside pre-market range',
                        trigger='scenario_1@11:00',setup='scenario_1@11:00',touch=1,ts=ms(11,minute))
    assert runner._score_execution(ap)['skips']['skip_no_trade_zone']==2
