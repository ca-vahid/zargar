"""Saved automatic contract limits survive planning and final slow entry work."""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from zargar.domain import OrderStatus, Quote
from zargar.models import Event, Order, TechniqueArmed
from zargar.orders import OrderIntent
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.contracts import ContractSelectionInput
from zargar.techniques.options_cartel.controller import CartelEntryController
from zargar.techniques.options_cartel.execution import ExecutionInput, contract_entry_checks
from zargar.techniques.options_cartel.preparation import prepared_execution
from zargar.techniques.options_cartel.runtime import CartelRuntime

from .test_options_cartel_controller import setup
from .test_options_cartel_entry import OPEN, plan
from .test_options_cartel_state import repo as repo  # noqa: PLC0414

CONTRACT = 'HOOD270521C00050000'


def selection_policy(**changes):
    return ContractSelectionInput(dte_min=2, dte_max=730, target_dte=300,
        target_abs_delta=.6, min_abs_delta=.5, max_ask=1.2, max_spread_pct=10,
        min_open_interest=100, **changes)


def rig():
    policy = PreparationPolicy(contract_policy=selection_policy())
    spec = prepared_execution(policy, 'pf', CONTRACT, policy.contract_policy)
    quote = Quote(CONTRACT, bid=.99, ask=1, last=1, source='opra', ts=OPEN)
    snapshot = {'greeks': {'delta': .6}, 'greeksFieldAsOf': {'delta': OPEN}}
    engine = SimpleNamespace(quotes=SimpleNamespace(get=lambda _: quote), settings={},
        options=SimpleNamespace(snapshot_cached=lambda _: snapshot))
    return engine, quote, snapshot, spec


def test_automatic_execution_snapshots_effective_selection_limits():
    policy = PreparationPolicy(contract_policy=selection_policy())
    effective = policy.contract_policy.model_copy(update={'max_ask': .8})
    spec = prepared_execution(policy, 'pf', CONTRACT, effective)
    restored = ExecutionInput.model_validate(spec.model_dump(mode='json', by_alias=True))
    assert restored.contract_policy == effective
    assert restored.max_premium == .8 and restored.min_abs_delta == .5
    assert restored.allow_live is False and restored.overnight_ack is True
    assert restored.contract_policy.min_open_interest == 100  # selection evidence, not fake fresh OI


@pytest.mark.parametrize('change,failed', [
    ('premium', 'entry_contract_premium'), ('spread', 'entry_contract_spread'),
    ('delta', 'entry_contract_delta'), ('stale_delta', 'entry_contract_delta'),
    ('dte', 'entry_contract_dte'), ('stale_quote', 'entry_contract_quote'),
])
def test_final_observations_must_still_meet_saved_policy(change, failed):
    engine, quote, snapshot, spec = rig()
    assert all(c['passed'] for c in contract_entry_checks(engine, plan(), spec, OPEN))
    if change == 'premium':
        quote.bid, quote.ask = 1.24, 1.25
    elif change == 'spread':
        quote.bid = .7
    elif change == 'delta':
        snapshot['greeks']['delta'] = .3
    elif change == 'stale_delta':
        snapshot['greeksFieldAsOf']['delta'] = OPEN-120001
    elif change == 'stale_quote':
        quote.ts = OPEN-10001
    else:
        spec.contract_policy = spec.contract_policy.model_copy(update={'dte_max': 90, 'target_dte': 45})
    failures = {c['name'] for c in contract_entry_checks(engine, plan(), spec, OPEN) if not c['passed']}
    assert failed in failures


async def option_controller(repo, monkeypatch):
    controller, _ = await setup(repo, monkeypatch)
    policy = PreparationPolicy(contract_policy=selection_policy())
    spec = prepared_execution(policy, 'pf', CONTRACT, policy.contract_policy)
    async with repo.engine.sf() as session, session.begin():
        row = await session.get(TechniqueArmed, 'r1')
        row.config = {**row.config, 'execution': spec.model_dump()}
    monkeypatch.setattr('zargar.risk.is_us_market_hours', lambda *args, **kwargs: True)
    monkeypatch.setattr(repo.engine.quotes, 'source_age_seconds', lambda _: 0.)
    repo.engine.options = SimpleNamespace(snapshot_cached=lambda _: {
        'greeks': {'delta': .6}, 'greeksFieldAsOf': {'delta': controller.clock()}})
    repo.engine.quotes.on_quote(Quote(CONTRACT, bid=.99, ask=1, last=1, source='opra', ts=controller.clock()))
    return controller


async def test_final_reconciliation_cannot_submit_a_newly_wide_limit_order(repo, monkeypatch):
    controller = await option_controller(repo, monkeypatch)
    original = controller._reconciled
    calls = 0

    async def widen(*args):
        nonlocal calls
        await original(*args)
        calls += 1
        if calls == 2:  # after durable reservation and the last slow reconciliation
            repo.engine.quotes.on_quote(Quote(CONTRACT, bid=.7, ask=1, last=1,
                source='opra', ts=controller.clock()))

    monkeypatch.setattr(controller, '_reconciled', widen)
    try:
        result = await controller.submit('r1')
        assert result['status'] == 'pre_submit_rejected', result
        assert 'spread' in result['reason']
        assert (await repo.load('r1'))['state']['submissionAborted']
        async with repo.engine.sf() as session:
            assert not (await session.scalars(select(Order))).all()
    finally:
        await repo.engine.position_manager.stop()


async def test_saved_limits_allow_an_eligible_current_contract(repo, monkeypatch):
    controller = await option_controller(repo, monkeypatch)
    try:
        result = await controller.submit('r1')
        assert result['status'] == 'working', result
        async with repo.engine.sf() as session:
            orders = (await session.scalars(select(Order))).all()
            assert len(orders) == 1 and orders[0].symbol == CONTRACT
            assert orders[0].limit_price == 1 and orders[0].order_type == 'LMT'
    finally:
        await repo.engine.position_manager.stop()


async def test_execution_review_changed_during_last_reconciliation_is_not_stale_authority(repo, monkeypatch):
    controller = await option_controller(repo, monkeypatch)
    original = controller._reconciled
    calls = 0

    async def tighten(*args):
        nonlocal calls
        await original(*args)
        calls += 1
        if calls == 2:
            async with repo.engine.sf() as session, session.begin():
                row = await session.get(TechniqueArmed, 'r1')
                row.config = {**row.config, 'execution': {**row.config['execution'], 'max_premium': .8}}

    monkeypatch.setattr(controller, '_reconciled', tighten)
    try:
        result = await controller.submit('r1')
        assert result['status'] == 'pre_submit_rejected'
        assert 'limits changed' in result['reason']
        async with repo.engine.sf() as session:
            assert not (await session.scalars(select(Order))).all()
    finally:
        await repo.engine.position_manager.stop()


async def test_legacy_automatic_arm_needs_explicit_contract_review_before_entry(repo, monkeypatch):
    controller = await option_controller(repo, monkeypatch)
    async with repo.engine.sf() as session, session.begin():
        row = await session.get(TechniqueArmed, 'r1')
        execution = {**row.config['execution']}
        execution.pop('contract_policy')
        row.config = {**row.config, 'execution': execution,
            'preparation': {'workspace': 'practice', 'validUntil': OPEN+390*60000}}
    try:
        with pytest.raises(ValueError, match='explicitly review and rearm'):
            await controller.submit('r1')
        assert not (await repo.load('r1'))['state'].get('attemptTag')
        async with repo.engine.sf() as session:
            assert not (await session.scalars(select(Order))).all()
    finally:
        await repo.engine.position_manager.stop()


@pytest.mark.parametrize('stage', ['risk', 'submitted'])
@pytest.mark.parametrize('change', ['delta', 'spread', 'underlying'])
async def test_order_submission_rechecks_after_its_own_last_await(repo, monkeypatch, stage, change):
    controller = await option_controller(repo, monkeypatch)
    engine = repo.engine
    delta = [.6]
    engine.options = SimpleNamespace(snapshot_cached=lambda _: {
        'greeks': {'delta': delta[0]}, 'greeksFieldAsOf': {'delta': controller.clock()}})
    submitted = []

    async def forbidden(order):
        submitted.append(order)
        raise AssertionError('Invalidated entry reached executor.submit')

    monkeypatch.setattr(engine.sim_executor, 'submit', forbidden)

    def mutate():
        if change == 'delta':
            delta[0] = .3
        elif change == 'spread':
            engine.quotes.on_quote(Quote(CONTRACT, bid=.7, ask=1, last=1,
                source='opra', ts=controller.clock()))
        else:
            engine.quotes.on_quote(Quote('HOOD', bid=48.19, ask=48.21, last=48.2, ts=controller.clock()))

    if stage == 'risk':
        original = engine.risk.evaluate
        calls = 0

        async def risk(*args, **kwargs):
            nonlocal calls
            result = await original(*args, **kwargs)
            calls += 1
            if calls == 2:  # preflight passes; OrderManager's own risk await changes the evidence
                mutate()
            return result

        monkeypatch.setattr(engine.risk, 'evaluate', risk)
    else:
        original = engine.orders._transition

        async def transition(oid, status, *args, **kwargs):
            result = await original(oid, status, *args, **kwargs)
            if status == OrderStatus.SUBMITTED:
                mutate()
            return result

        monkeypatch.setattr(engine.orders, '_transition', transition)
    try:
        result = await controller.submit('r1')
        assert result['status'] == 'closed_unfilled', result
        assert submitted == []
        state = (await repo.load('r1'))['state']
        assert 'before_submit' not in state['intent']
        async with engine.sf() as session:
            orders = (await session.scalars(select(Order))).all()
            assert len(orders) == 1
            order = orders[0]
            assert order.id == state['orderId'] and state['attemptTag'] in order.tags
            assert order.status == 'REJECTED_RISK' and order.filled_qty == 0
            assert 'Pre-submit validation failed' in order.reject_reason
            rejection = await session.scalar(select(Event).where(Event.aggregate_id == order.id,
                Event.type == 'OrderRejected'))
            assert rejection.payload['beforeSubmitRejected'] is True
        restored = CartelEntryController(engine)
        restored.clock = controller.clock
        assert (await restored.submit('r1'))['status'] == 'closed_unfilled'
        assert submitted == []
        async with engine.sf() as session:
            assert len((await session.scalars(select(Order))).all()) == 1
    finally:
        await engine.position_manager.stop()


async def test_order_manager_refuses_an_asynchronous_final_guard(repo, monkeypatch):
    await option_controller(repo, monkeypatch)
    called = []

    async def async_guard():
        called.append('awaited')

    async def forbidden(order):
        called.append('submitted')

    monkeypatch.setattr(repo.engine.sim_executor, 'submit', forbidden)
    try:
        result = await repo.engine.orders.place(OrderIntent(portfolio_id='pf', symbol=CONTRACT,
            sec_type='OPT', side='BUY', qty=1, order_type='LMT', limit_price=1), before_submit=async_guard)
        assert result['status'] == 'REJECTED_RISK'
        assert 'must be synchronous' in result['rejectReason']
        assert called == []
    finally:
        await repo.engine.position_manager.stop()


async def test_reduce_only_exit_bypasses_an_entry_final_guard(repo, monkeypatch):
    controller = await option_controller(repo, monkeypatch)
    engine = repo.engine
    try:
        await engine.orders.place(OrderIntent(portfolio_id='pf', symbol=CONTRACT,
            sec_type='OPT', side='BUY', qty=1, order_type='LMT', limit_price=1))
        quote = Quote(CONTRACT, bid=.98, ask=.99, last=.99, source='opra', ts=controller.clock())
        engine.quotes.on_quote(quote)
        await engine.sim_executor.on_quote(quote)
        assert engine.positions.position_qty('pf', CONTRACT, 'OPT') == 1
        calls = []

        def guard():
            calls.append('guard')
            raise ValueError('entry policy must not trap protection')

        result = await engine.orders.place(OrderIntent(portfolio_id='pf', symbol=CONTRACT,
            sec_type='OPT', side='SELL', qty=1, order_type='LMT', limit_price=.98, reduce_only=True),
            before_submit=guard)
        assert result['status'] == 'SUBMITTED' and calls == []
        await engine.sim_executor.on_quote(quote)
        assert engine.positions.position_qty('pf', CONTRACT, 'OPT') == 0
    finally:
        await engine.position_manager.stop()


@pytest.mark.parametrize('change', ['pause', 'disarm', 'settings', 'missing', 'signal', 'phase_only'])
async def test_dispatch_uses_current_owner_authority_but_reserved_phase(repo, monkeypatch, change):
    controller = await option_controller(repo, monkeypatch)
    engine = repo.engine
    runtime = engine.cartel_observer = CartelRuntime(engine)
    runtime.controller = controller
    runtime.clock = controller.clock
    await runtime._remember(await repo.load('r1'))
    monkeypatch.setattr(runtime, '_publish', lambda _: None)
    # Exercise the actual pause/disarm persistence+cache update without racing
    # the independent cancellation task against this deliberate pre-submit hold.
    monkeypatch.setattr(runtime, '_schedule_poll', lambda _: None)
    submitted = []

    async def executor_submit(order):
        submitted.append(order)

    monkeypatch.setattr(engine.sim_executor, 'submit', executor_submit)
    original = engine.orders._transition

    async def transition(oid, status, *args, **kwargs):
        prior_result = await original(oid, status, *args, **kwargs)
        if status == OrderStatus.SUBMITTED:
            if change == 'pause':
                await runtime.pause('r1')
            elif change == 'disarm':
                await runtime.disarm('r1')
            elif change == 'missing':
                runtime.rows.pop('r1')
            else:
                async with engine.sf() as session, session.begin():
                    row = await session.get(TechniqueArmed, 'r1')
                    if change == 'settings':
                        row.config = {**row.config, 'execution': {**row.config['execution'], 'max_premium': .8}}
                    elif change == 'signal':
                        row.state = {**row.state, 'signal': {**row.state['signal'], 'id': 'changed-signal'}}
                    else:
                        row.state = {**row.state, 'phase': 'working'}
                    runtime.rows['r1'] = repo.view(row)
        return prior_result  # an old transition result must not restore authority

    monkeypatch.setattr(engine.orders, '_transition', transition)
    try:
        result = await controller.submit('r1')
        if change == 'phase_only':
            assert result['status'] == 'working' and len(submitted) == 1
        else:
            assert result['status'] == 'closed_unfilled', result
            assert submitted == []
        async with engine.sf() as session:
            orders = (await session.scalars(select(Order))).all()
            assert len(orders) == 1
            assert orders[0].status == ('SUBMITTED' if change == 'phase_only' else 'REJECTED_RISK')
            if change != 'phase_only':
                assert 'Pre-submit validation failed' in orders[0].reject_reason
    finally:
        await runtime.stop()
        await engine.position_manager.stop()
