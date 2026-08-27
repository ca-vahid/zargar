"""The technique registry and the descriptor every technique publishes.

Phase 0 of the platform plan: identity only. The behavioural protocol (plan,
trigger_rules, express, exit_policy, critic, score) arrives with phase 2.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TechniqueInfo:
    id: str                        # stable key: DB column, settings prefix, API path, order meta
    label: str                     # what the UI calls it
    version: str                   # goes into run provenance
    page: str                      # UI page the technique lives on (until the shell is generic)
    settings_prefix: str           # where its knobs live
    tabs: tuple[str, ...]          # UI tabs it wants
    description: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "version": self.version, "page": self.page,
                "settingsPrefix": self.settings_prefix, "tabs": list(self.tabs), "description": self.description}


_REGISTRY: dict[str, TechniqueInfo] = {}


def register(info: TechniqueInfo) -> TechniqueInfo:
    _REGISTRY[info.id] = info
    return info


def get_technique(tid: str) -> TechniqueInfo | None:
    return _REGISTRY.get(tid)


def all_techniques() -> list[TechniqueInfo]:
    return list(_REGISTRY.values())


ENHANCED_MARKET = register(TechniqueInfo(
    id="enhanced_market", label="EM Options", version="1", page="technique", settings_prefix="technique.",
    tabs=("validation", "analyse", "chat", "history", "backtest"),
    description="EnhancedMarket method: support/resistance bounces, breakouts and their short mirrors, "
                "expressed with just-OTM weeklies / 0DTE in the two prime windows.",
))
