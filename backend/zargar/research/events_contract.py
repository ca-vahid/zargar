"""Event-schema contracts (EM team #3, platform plan §8).

With N techniques journaling through the shared runner, payload shapes are an
API: the review tooling (audits, the CLI, the day panels) reads them. Every
`Technique*` journal kind is registered here with a version and the fields a
consumer may rely on. The runner journals hook *results*, so techniques cannot
invent shapes — but runner changes can drift, which is what the contract test
(`tests/test_platform_phase3.py::test_every_journaled_kind_has_a_contract` and
friends) catches.

Rules:
- Bump `version` when a required field is added/renamed/removed; note it in
  `docs/PLATFORM-RULES.md` §4 (the shapes are consumed outside this repo tree).
- `required` fields must be present (may be null only if listed in `nullable`).
- Extra fields are always allowed — consumers must ignore what they don't know.
- Validation is advisory at runtime (a warning, never a failed trade) and strict
  in the contract tests.
"""
from __future__ import annotations

import logging

log = logging.getLogger("zargar.research.events")

# kind -> {"version", "required": (fields...), "nullable": (fields...)}
CONTRACTS: dict[str, dict] = {
    # --- research: runs / setups / outcomes / reviews / sweeps -------------
    "TechniqueRunStarted":    {"version": 1, "required": ("runId", "symbol")},
    "TechniqueRunCompleted":  {"version": 1, "required": ("runId", "symbol")},
    "TechniqueRunFailed":     {"version": 1, "required": ("runId", "symbol", "error")},
    "TechniqueRunReplayed":   {"version": 1, "required": ("runId",)},
    "TechniqueSetupEmitted":  {"version": 1, "required": ("runId", "symbol")},
    "TechniqueGroundingFailed": {"version": 1, "required": ("runId",)},
    "TechniqueOutcomeScored": {"version": 1, "required": ("runId", "symbol")},
    "TechniqueReviewAdded":   {"version": 1, "required": ("runId",)},
    "TechniqueScan":          {"version": 1, "required": ()},
    "TechniqueSweepStarted":  {"version": 1, "required": ("sweepId",)},
    "TechniqueSweepCompleted": {"version": 1, "required": ("sweepId",)},
    # --- the armed runner (shapes produced ONLY by execution/planrunner.py) -
    "TechniquePlanArmed":     {"version": 1, "required": ("runId", "symbol", "planFor", "config", "portfolio")},
    "TechniquePlanDisarmed":  {"version": 1, "required": ("runId", "symbol", "reason")},
    "TechniquePlanRolled":    {"version": 1, "required": ("runId", "symbol", "from", "to")},   # multi-day plan advanced to its next session (ARM-GAPS A2/A4); was journaled without a contract
    "TechniqueCounterfactual": {"version": 1, "required": ("runId", "symbol", "trigger", "reason", "status", "pnl")},   # a trade the app missed through a bug, reconstructed after the fix (execution/counterfactual.py) - never a portfolio fill
    "TechniquePlanPaused":    {"version": 1, "required": ("runId", "symbol")},
    "TechniquePlanResumed":   {"version": 1, "required": ("runId", "symbol")},
    "TechniquePlanModeChanged": {"version": 1, "required": ("runId", "symbol", "from", "to")},
    "TechniquePlanTriggerFired": {"version": 1,
                                  "required": ("runId", "symbol", "trigger", "kind", "window", "entry", "stop", "mode"),
                                  "nullable": ("fill", "critic", "setupId")},
    "TechniquePlanTriggerSkipped": {"version": 1, "required": ("runId", "symbol", "trigger", "event")},
    "TechniquePlanOrderIntent": {"version": 1,
                                 "required": ("runId", "symbol", "orderSymbol", "secType", "trigger",
                                              "side", "qty", "portfolioId")},
    "TechniquePlanOrderResult": {"version": 1, "required": ("runId", "symbol", "trigger", "stage", "status"),
                                 "nullable": ("orderId", "reason")},
    "TechniquePlanPositionOpened": {"version": 1, "required": ("runId", "symbol", "trigger", "qty", "avgFill")},
    "TechniquePlanPositionClosed": {"version": 1, "required": ("runId", "symbol", "trigger", "realizedPnl")},
    "TechniquePlanExit":      {"version": 1, "required": ("runId", "symbol", "trigger", "kind", "qty", "reduceOnly")},
    "TechniquePlanError":     {"version": 1, "required": ("runId", "symbol", "stage", "error")},
    "TechniquePlanScored":    {"version": 1, "required": ("runId", "symbol", "planFor", "rows")},
    "TechniquePlanPreopen":   {"version": 1, "required": ("runId", "symbol", "planFor", "premarket", "triggers", "replan")},
    "TechniquePlanReplanned": {"version": 1, "required": ("runId", "parentRunId", "symbol", "planFor")},
    "TechniqueHookStats":     {"version": 1, "required": ("technique", "date", "hooks")},
    # --- durable positions (phase 2b; produced ONLY by execution/positions.py) ---
    "ManagedPositionOpened":  {"version": 1, "required": ("positionId", "technique", "symbol", "portfolioId", "legs", "policy")},
    "ManagedPositionAdopted": {"version": 1, "required": ("positionId", "technique", "symbol", "portfolioId", "legs", "policy")},
    "ManagedPositionExit":    {"version": 1, "required": ("positionId", "symbol", "kind", "leg", "qty", "reduceOnly")},
    "ManagedPositionClosed":  {"version": 1, "required": ("positionId", "symbol", "realizedPnl", "reason")},
    "ManagedPositionPolicyChanged": {"version": 1, "required": ("positionId", "symbol", "policy")},
    "ManagedPositionReconciled": {"version": 1, "required": ("positions",)},
    "ManagedPositionAttention": {"version": 1, "required": ("positionId", "symbol", "error")},
    "ManagedPositionScaledIn": {"version": 1, "required": ("positionId", "symbol")},
    "ManagedPositionRolledUp": {"version": 1, "required": ("positionId", "symbol", "from", "to", "qty", "creditPerContract")},
}


def validate(kind: str, payload: dict) -> list[str]:
    """Missing required fields for a registered kind; [] when fine or unregistered
    non-Technique kind. An unregistered Technique* kind is itself a violation."""
    c = CONTRACTS.get(kind)
    if c is None:
        return [f"unregistered Technique event kind: {kind}"] if kind.startswith("Technique") else []
    nullable = set(c.get("nullable") or ())
    missing = [f for f in c["required"] if f not in payload and f not in nullable]
    return [f"{kind} v{c['version']}: missing required field {f!r}" for f in missing]


def check(kind: str, payload: dict) -> None:
    """Advisory runtime check: log a warning, never raise — a shape drift must
    never block a trade; the contract test is the hard gate."""
    for problem in validate(kind, payload or {}):
        log.warning("event contract: %s", problem)
