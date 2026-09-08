"""Workspace identity and permissions for automatic Cartel preparation."""
from typing import Literal

from sqlalchemy import func

from ...models import TechniqueRun
from .accounts import default_practice_book
from .automatic_plans import PreparationPolicy

Workspace = Literal['practice', 'live']
SETTING = 'techniques.options_cartel.preparation'


def active_workspace(engine):
    return 'live' if engine.settings.get('trading.mode') == 'live' else 'practice'


def setting_key(workspace):
    if workspace not in ('practice', 'live'):
        raise ValueError('Unknown preparation workspace')
    return SETTING if workspace == 'practice' else SETTING+'_live'


def read_policy(engine, workspace=None):
    workspace = workspace or active_workspace(engine)
    values = {**engine.settings.get(setting_key(workspace), {}), 'workspace': workspace}
    if workspace == 'practice' and default_practice_book(engine):
        values['portfolio_id'] = default_practice_book(engine)
        values.pop('portfolioId', None)
    return PreparationPolicy.model_validate(values)


def workspace_filter(workspace):
    # Existing preparation records predate workspace metadata and belong to Practice.
    return func.coalesce(TechniqueRun.config['workspace'].as_string(), 'practice') == workspace


def require_execution_scope(engine, policy):
    if active_workspace(engine) != policy.workspace:
        raise ValueError('Preparation workspace changed; start again in the selected workspace')
    if policy.workspace == 'live' and (not policy.allow_live or not policy.overnight_ack
            or not engine.settings.get('techniques.options_cartel.allow_live_auto', False)):
        raise ValueError('Live preparation requires acknowledgements and the Cartel live-auto permission')
