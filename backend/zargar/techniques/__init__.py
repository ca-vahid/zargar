"""Technique registry — one engine, many techniques (docs/TECHNIQUE-PLATFORM-PLAN.md).

A technique is *what* to trade: it produces plans (data) and a few policies. The
shared layers (`marketstructure`, `execution`, research) do everything else.
"""
from .base import ENHANCED_MARKET, TechniqueInfo, all_techniques, get_technique, register

__all__ = ["ENHANCED_MARKET", "TechniqueInfo", "all_techniques", "get_technique", "register"]
