"""Regression preserved from the EOD audit: simulated fills need eligible evidence.

No Engine, database, broker connection, subscriptions, settings or orders are
created outside a single in-memory SimExecutor. This does not identify the
actual quote used for the September 14 APA fill.
"""
from __future__ import annotations

import asyncio
import json

from zargar.brokers import sim as sim_module
from zargar.brokers.base import BrokerOrder
from zargar.brokers.sim import SimExecutor, _Working
from zargar.domain import OrderSide, OrderType, Quote

NOW = 1789404623478


async def observed_fill(source: str, age_ms: int):
    executor = SimExecutor(latency_ms=0)
    reports = []

    async def capture(report):
        reports.append(report)

    executor.on_report = capture
    order = BrokerOrder(id="in-memory-only", symbol="APA261016C00045000", sec_type="OPT",
        side=OrderSide.SELL, qty=1, order_type=OrderType.MKT)
    executor._working[order.id] = _Working(order=order, eligible_at=NOW-1)
    quote = Quote(symbol=order.symbol, bid=2.71, ask=3.05, bid_size=100, ask_size=100,
        ts=NOW, source=source, source_ts=NOW-age_ms)
    old_clock = sim_module.now_ms
    try:
        sim_module.now_ms = lambda: NOW
        await executor.on_quote(quote)
    finally:
        sim_module.now_ms = old_clock
    fills = [r for r in reports if r.kind == "fill"]
    return {"source": source, "sourceAgeMs": age_ms, "delayed": quote.delayed,
        "fills": [{"quantity": r.fill_qty, "price": r.fill_price} for r in fills],
        "stillWorking": executor.working_count}


async def test_stale_opra_cannot_manufacture_a_simulated_option_fill():
    observed = await observed_fill("opra", 36_272)
    assert observed["fills"] == [], f"Stale source evidence filled the order: {observed}"


async def test_delayed_chain_cannot_manufacture_a_simulated_option_fill():
    observed = await observed_fill("chain", 900_000)
    assert observed["fills"] == [], f"Delayed source evidence filled the order: {observed}"


async def main():
    control = await observed_fill("opra", 0)
    assert control["fills"] == [{"quantity": 1, "price": 2.7095}], control
    print(json.dumps({"freshPositiveControl": control}))
    failures = []
    for regression in (test_stale_opra_cannot_manufacture_a_simulated_option_fill,
                       test_delayed_chain_cannot_manufacture_a_simulated_option_fill):
        try:
            await regression()
        except AssertionError as exc:
            failures.append(str(exc))
            print(json.dumps({"regression": regression.__name__, "status": "FAIL", "evidence": str(exc)}))
    assert not failures, "Quote-evidence acceptance regressions reproduced; no APA fill-source attribution is implied."


if __name__ == "__main__":
    asyncio.run(main())

import pytest


@pytest.mark.parametrize('overrides', [
    {'source':'','source_ts':0}, {'source':'chain','source_ts':NOW},
    {'source_ts':NOW+1}, {'ts':NOW-15001}, {'bid':0}, {'bid':4,'ask':3}, {'bid':float('nan')},
])
async def test_invalid_quote_keeps_protective_order_until_fresh_evidence(monkeypatch, overrides):
    monkeypatch.setattr(sim_module,'now_ms',lambda:NOW)
    executor=SimExecutor(latency_ms=0); reports=[]
    async def capture(report): reports.append(report)
    executor.on_report=capture
    order=BrokerOrder(id='protective',symbol='APA261016C00045000',sec_type='OPT',side=OrderSide.SELL,qty=1,order_type=OrderType.MKT)
    await executor.submit(order)
    values={'symbol':order.symbol,'bid':2.71,'ask':3.05,'bid_size':100,'ask_size':100,'source':'opra','source_ts':NOW,'ts':NOW}
    await executor.on_quote(Quote(**{**values,**overrides}))
    assert executor.working_count==1 and not any(r.kind=='fill' for r in reports)
    await executor.on_quote(Quote(**values))
    fills=[r for r in reports if r.kind=='fill']
    assert len(fills)==1 and executor.working_count==0
    assert fills[0].evidence['sourceAt']==NOW and fills[0].evidence['bid']==2.71

async def test_synthetic_feed_requires_explicit_mode(monkeypatch):
    monkeypatch.setattr(sim_module,'now_ms',lambda:NOW)
    order=BrokerOrder(id='synthetic',symbol='APA261016C00045000',sec_type='OPT',side=OrderSide.BUY,qty=1,order_type=OrderType.MKT)
    quote=Quote(symbol=order.symbol,bid=2,ask=3,ts=NOW)
    assert SimExecutor().quote_rejection(order,quote,NOW)
    assert SimExecutor(synthetic_quotes=True).quote_rejection(order,quote,NOW) is None

async def test_fill_evidence_committed_with_execution(engine):
    from sqlalchemy import select

    from zargar.models import ExecutionEvidence
    from zargar.orders import OrderIntent

    from .conftest import wait_for
    from .test_engine_flow import sim_portfolio, wait_quote
    pid=sim_portfolio(engine)['id']; await wait_quote(engine,'AAPL')
    await engine.orders.place(OrderIntent(portfolio_id=pid,symbol='AAPL',side='BUY',qty=1,order_type='MKT'))
    async def stored():
        async with engine.sf() as session:
            return await session.scalar(select(ExecutionEvidence))
    await wait_for(stored)
    receipt=await stored()
    assert receipt.evidence['policy']=='sim_fill_v1'
    assert receipt.evidence['syntheticMode'] is True
