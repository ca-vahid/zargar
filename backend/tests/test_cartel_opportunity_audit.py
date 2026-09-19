from zargar.tools.cartel_opportunity_audit import distance, price_evidence, selections
from zargar.marketstructure.sessions import session_bounds


def test_distance_uses_only_prior_completed_sessions_and_direction():
    c={'trigger':110,'direction':'long','daily':[{'session':'2026-09-17','close':100},
        {'session':'2026-09-18','close':150}]}
    assert round(distance(c,'2026-09-18'),6)==10
    c.update(trigger=90,direction='short')
    assert round(distance(c,'2026-09-18'),6)==10
    assert distance({**c,'daily':[]},'2026-09-18') is None


def test_price_touches_exclude_sampled_and_other_sessions():
    o,c=session_bounds('2026-09-18')
    bars=[[o,10,12,9,11,1,'sampled'],[o+60000,10,10,9,9.5,1,'exchange'],
          [c,10,20,10,20,1,'exchange']]
    r=price_evidence({'trigger':11,'direction':'long'},bars,'2026-09-18')
    assert r['observedLevelTouch'] is False and r['nativeMinutes']==1 and r['high']==10
    assert price_evidence({'trigger':11,'direction':'long'},[],'2026-09-18')['observedLevelTouch'] is None


def test_rankings_do_not_read_future_outcomes_and_do_not_prefer_already_broken():
    rows=[{'symbol':s,'distancePct':d,'structuralR':r,'relativeStrength':1,'dailyVolume':100,
           'dollarVolume':v,'price':{'observedLevelTouch':False}} for s,d,r,v in
          [('A',2,3,100),('B',1,2,300),('C',-1,1,200)]]
    before=selections(rows,1)
    for r in rows: r['price']['observedLevelTouch']=True
    assert selections(rows,1)==before=={'saved_quality':['A'],'nearest_unbroken':['B'],'liquid_first':['B']}


def test_prospective_rankings_ignore_unclosed_daily_and_keep_unknown_out():
    from zargar.techniques.options_cartel.research_economics import compare_rankings
    cutoff=session_bounds('2026-09-17')[1]
    candidates=[{'id':'a','symbol':'A','direction':'long','sourceAt':cutoff,'trigger':101,
        'daily':[{'symbol':'A','session':day,'open':price,'high':price,'low':price,'close':price,'volume':100}
                 for day,price in [('2026-09-17',100),('2026-09-18',200)]],
        'leaderEvidence':{'dailyDollarVolume':10000}}, {'id':'b','symbol':'B'}]
    result=compare_rankings(candidates)
    assert result['opportunityComparisons']['nearestUnbrokenIds']==['a']
    assert result['opportunityComparisons']['liquidFirstIds']==['a']
    assert round(result['candidates'][0]['triggerDistancePct'],6)==1
