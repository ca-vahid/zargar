"""Tip technique — human-relayed tips as monitored plans.

docs/techniques/tip/PLAN.md. Intake/extraction lives in `zargar.signals`;
this package owns what makes a tip a *technique*: turning a verified or
parked signal into a one-trigger SessionPlan the shared runner can watch.
"""
from .plan import build_tip_plan  # noqa: F401
