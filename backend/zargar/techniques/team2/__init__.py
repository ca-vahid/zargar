"""Team2 technique — Casey/@Team2Trading's SPY/QQQ/IWM 0DTE day-trading method.

Desk docs: `docs/techniques/team2/` (METHOD.md = the rules with L/B/E/C/T/S/X/Z/V numbers,
PLAN.md = decisions + build phases, TRADING-RULES.md = the judgement log). This package owns
ONLY the technique's judgement: its rules, the regime/scenario reads, plan construction, the
premium model and the pure session simulation. Money paths stay in `zargar/execution/`;
bar primitives live in `zargar/marketstructure/`.
"""
from .rules import Team2Rules, rules_from_settings

TECHNIQUE_ID = "team2"

__all__ = ["TECHNIQUE_ID", "Team2Rules", "rules_from_settings"]
