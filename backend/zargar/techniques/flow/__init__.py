"""Flow technique — daily unusual-options-activity scan as context.

docs/techniques/flow/PLAN.md. v1 places no orders: the scan flags contracts
(Vol/OI, premium size, near-dated OTM footprint), confirms yesterday's flags
against today's open-interest delta, tracks repeat hits across days, and
surfaces a per-symbol read for the Tip technique and EM. The nightly snapshot
rows are the walk-forward's future dataset — they cannot be backfilled.
"""
from .scan import FlowThresholds, aggregate_symbol, build_read, confirm_oi, flag_contracts  # noqa: F401
