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

TIP = register(TechniqueInfo(
    id="tip", label="Tips", version="0.1", page="inbox", settings_prefix="techniques.tip.",
    tabs=("tips", "sources"),
    description="Human-relayed tips (Discord screenshot, newsletter, paste) become monitored plans: "
                "per-source entry policy (level-touch until tip-time is earned), budgets, and a "
                "shadow scorecard every source must clear before real money.",
))

TEAM2 = register(TechniqueInfo(
    id="team2", label="Team2", version="0.1", page="team2", settings_prefix="techniques.team2.",
    tabs=("plans", "armed", "history", "validation"),
    description="Casey/@Team2Trading's index day-trading method: prior-day high/low zones + pre-market "
                "range, 13/48/200 EMA regime on 2m, 15-minute-close confirmation, EMA13 pullback entries, "
                "0DTE premium-targeted contracts (~$0.50), one-candle stops, +50/+100% trims, flatten 15:45.",
))

FLOW = register(TechniqueInfo(
    id="flow", label="Flow", version="0.1", page="flow", settings_prefix="techniques.flow.",
    tabs=("reads",),
    description="Daily unusual-options-activity scan over the chains: Vol/OI, premium size, "
                "repeat hits with overnight OI confirmation. Context for Tips and EM — "
                "places no orders.",
))
