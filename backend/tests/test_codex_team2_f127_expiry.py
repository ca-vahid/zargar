"""A 0DTE clamp must not lower size for a selected longer-dated contract.
Pure sizer call with synthetic contract and mocked equity; no DB/orders.
"""
import datetime as dt
from zargar.marketstructure.sessions import ET
from .test_team2_sizing_cap import _rig, BASE


async def test_longer_dated_contract_keeps_existing_cap_despite_default_dte_policy():
    runner, ap, trade = _rig({**BASE, 'techniques.team2.zero_dte': {'enabled':True,'max_contracts':40}})
    tomorrow=dt.datetime.now(ET).date()+dt.timedelta(days=1)
    selected={'symbol':f'IWM{tomorrow:%y%m%d}P00284000','expiry':tomorrow.isoformat(),
              'ask':.33,'bid':.32,'_sizeMult':1.0,'_bucket':'full'}
    count=await runner._size_contracts(ap,trade,selected)
    assert count==50, '0DTE-only bound was applied to a selected contract expiring tomorrow'
