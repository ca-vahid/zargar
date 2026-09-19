import datetime as dt

from zargar.marketstructure.market_calendar import is_trading_day
from zargar.marketstructure.sessions import session_bounds
from zargar.techniques.options_cartel.data import DailyBar
from zargar.techniques.options_cartel.lab_features import selection_features, compression_order


def history():
    out=[];day=dt.date(2026,3,2)
    while len(out)<25:
        if is_trading_day(day):
            out.append(DailyBar(symbol='TEST',session=day,open=100,high=101,low=99,close=100,volume=1000))
        day+=dt.timedelta(days=1)
    return out


def test_uncompleted_daily_bar_cannot_change_frozen_features():
    bars=history();at=session_bounds(bars[-2].session.isoformat())[1]
    assert selection_features(bars,at)==selection_features(bars[:-1],at)
    result=selection_features(bars,at)
    assert result['baseRangeAdr']==1
    assert result['revenueGrowth']=='unknown_not_supplied' and result['sma200'] is None
    assert result['emas']['50'] is None


def test_missing_history_is_unknown_and_ranking_preserves_it_as_unranked():
    features=selection_features([],0)
    assert features['adr20Pct'] is None
    rows=[{'id':'unknown','symbol':'U','labFeatures':features},
          {'id':'known','symbol':'K','labFeatures':{'recent5RangeAdr':1}}]
    assert compression_order(rows)==['known']
