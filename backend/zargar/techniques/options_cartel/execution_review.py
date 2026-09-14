"""Explicit review of unused automatic Practice arms after a policy-schema upgrade."""
from __future__ import annotations

import copy
import hashlib
import json

from sqlalchemy import select

from ...domain import now_ms
from ...models import ManagedPositionRow
from .automatic_plans import PreparationPolicy
from .execution import ExecutionInput
from .plans import CartelPlan
from .preparation import affordable_contract_policy, prepared_execution, publication_readiness
from .preparation_scope import read_policy, require_execution_scope


async def review_execution_limits(engine, run_id, *, client_kind='desktop', clock=now_ms):
    runtime = engine.cartel_observer
    row = await runtime.repository.load(run_id)
    if row is None:
        raise KeyError(run_id)
    prep = row['config'].get('preparation') or {}
    if not prep.get('runId') or prep.get('workspace', 'practice') != 'practice' or row['mode'] != 'auto':
        raise ValueError('Execution-limit review requires an automatic Practice preparation arm')
    if row['status'] != 'armed' or row['state'].get('phase') != 'waiting' or row['state'].get('attemptTag'):
        raise ValueError('Only an unused waiting arm can receive reviewed execution limits')
    async with engine.sf() as session:
        held = await session.scalar(select(ManagedPositionRow.id).where(
            ManagedPositionRow.technique == 'options_cartel',
            ManagedPositionRow.portfolio_id == row['portfolioId'],
            ManagedPositionRow.config['runId'].as_string() == run_id,
            ManagedPositionRow.status.notin_(('closed', 'archived'))))
    if held:
        raise ValueError('Held campaigns keep their original execution and exit policy')
    from .service import CartelService
    service = CartelService(engine)
    original = await service._load(prep['runId'])
    if original.mode != 'preparation' or original.config.get('workspace', 'practice') != 'practice':
        raise ValueError('Original Practice preparation policy is unavailable; prepare a new plan')
    policy = PreparationPolicy.model_validate(original.config['policy'])
    current = read_policy(engine, 'practice')
    require_execution_scope(engine, current)
    if not current.enabled:
        raise ValueError('Practice preparation is disabled')
    old = ExecutionInput.model_validate(row['config']['execution'])
    if old.contract_policy is not None:
        raise ValueError('This arm already has reviewed contract limits; the legacy upgrade cannot replace them')
    if old.instrument != 'options' or old.contract_symbol is None:
        raise ValueError('A selected option contract is required')
    # Review may restore missing authority, but cannot expand a saved debit limit.
    effective = policy.model_copy(update={'budget': min(old.budget, current.budget),
        'risk_pct': min(old.risk_pct, current.risk_pct), 'max_contracts': min(old.max_units, current.max_contracts)})
    contract = policy.contract_policy.model_copy(update={
        'max_ask': min(policy.contract_policy.max_ask, current.contract_policy.max_ask,
                       old.max_premium if old.max_premium is not None else float('inf')),
        'max_spread_pct': min(policy.contract_policy.max_spread_pct, current.contract_policy.max_spread_pct),
        'min_abs_delta': max(old.min_abs_delta, policy.contract_policy.min_abs_delta, current.contract_policy.min_abs_delta),
        'dte_min': max(policy.contract_policy.dte_min, current.contract_policy.dte_min),
        'dte_max': min(policy.contract_policy.dte_max, current.contract_policy.dte_max)})
    contract = contract.model_copy(update={
        'target_dte': max(contract.dte_min, min(contract.target_dte, contract.dte_max)),
        'target_abs_delta': max(contract.target_abs_delta, contract.min_abs_delta)})
    # model_copy skips validation; revalidate the combined interval before publication.
    contract = type(contract).model_validate(contract.model_dump())
    effective = effective.model_copy(update={'contract_policy': contract})
    selection = await affordable_contract_policy(engine, old.portfolio_id, effective)
    saved_plan = await service._load(run_id)
    plan = CartelPlan.model_validate(saved_plan.result['plan']['plan'])
    _, readiness = await publication_readiness(engine, plan, clock)
    if not readiness['ready']:
        raise ValueError('Plan is no longer ready: ' + '; '.join(readiness['reasons']))
    # Runtime.arm locks and refuses an intervening order attempt; paused arms must
    # also remain paused if another request changed them while history was loaded.
    latest = await runtime.repository.load(run_id)
    if latest['config'] != row['config'] or latest['status'] != 'armed' or latest['state'].get('phase') != 'waiting' \
            or latest['state'].get('attemptTag'):
        raise ValueError('Arm changed during review; refresh before trying again')
    config = copy.deepcopy(row['config'])
    config['execution'] = prepared_execution(effective, old.portfolio_id, old.contract_symbol, selection).model_dump()
    config['clientKind'] = client_kind
    config['preparation'].pop('leaseOwner', None)
    config['preparation']['executionReview'] = {'version': 1, 'reviewedAt': clock(), 'sourcePreparationId': original.id,
        'expectedConfigSha256': hashlib.sha256(json.dumps(row['config'], sort_keys=True).encode()).hexdigest(),
        'expectedPolicySha256': hashlib.sha256(json.dumps(current.model_dump(mode='json'), sort_keys=True).encode()).hexdigest(),
        'note': 'Explicit limit review; original contract, plan targets and exit campaign retained.'}
    if current != read_policy(engine, 'practice'):
        raise ValueError('Preparation settings changed during review; refresh before trying again')
    return await runtime.arm(run_id, config)
