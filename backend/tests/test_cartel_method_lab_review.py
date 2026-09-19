from types import SimpleNamespace
from unittest.mock import AsyncMock

from zargar.techniques.options_cartel.method_lab_observer import collect,pending_quotes
from zargar.techniques.options_cartel.method_lab_review import report
from . import test_options_cartel_profitability_research as prior
from .test_cartel_method_lab_observer import prepared

research=prior.research


async def test_missing_quotes_stay_unknown_in_reconciled_report(research,monkeypatch):
    rig=research;context=await prepared(rig)
    runtime=SimpleNamespace(engine=rig.engine,clock=lambda:prior.OPEN-500,stopping=False)
    await collect(runtime)
    runtime.clock=lambda:prior.OPEN+320000
    monkeypatch.setattr('zargar.techniques.options_cartel.method_lab_observer.observe_contract',
        AsyncMock(return_value={'status':'unavailable','observedAt':runtime.clock()}))
    await collect(runtime)
    runtime.clock=lambda:prior.OPEN+430000
    await pending_quotes(runtime,context,rig.policy)
    result=await report(rig.engine,context,runtime.clock())
    assert result['rows'][0]['quoteDisposition']=='deadline_missed'
    assert result['rows'][0]['models'] is None and result['rows'][0]['trialEligible'] is False
    assert result['trialReview']['status']=='pending_receipt_reconciliation'
    assert result['activationAllowed'] is False and result['placesOrders'] is False


async def test_review_before_signal_time_cannot_see_future_results(research,monkeypatch):
    rig=research;context=await prepared(rig)
    runtime=SimpleNamespace(engine=rig.engine,clock=lambda:prior.OPEN-500,stopping=False)
    await collect(runtime)
    runtime.clock=lambda:prior.OPEN+320000
    monkeypatch.setattr('zargar.techniques.options_cartel.method_lab_observer.observe_contract',
        AsyncMock(return_value={'status':'unavailable','observedAt':runtime.clock()}))
    await collect(runtime)
    result=await report(rig.engine,context,prior.OPEN+300000)
    assert result['rows']==[] and result['trialObservationsIncluded']==0
