"""Shared research layer (platform plan phase 3) — what every technique's runs,
outcomes, reviews and sweeps have in common.

Today this package holds the event-schema contracts (`events_contract`) and the
record serializers (`records`). The `TechniqueService` orchestration class stays
in `zargar/technique/service.py` until a second technique exists — its generic
halves are already keyed by the `technique` column and `tags`, so splitting the
class is a rename, not a redesign (see the plan §3, phase 3 note).
"""
from .events_contract import CONTRACTS, check, validate

__all__ = ["CONTRACTS", "check", "validate"]
