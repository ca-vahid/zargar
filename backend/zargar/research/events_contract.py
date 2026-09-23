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
    "SimFillWaiting": {"version": 1, "required": ("reason", "evidence")},
    "BarDeliveryHealth": {"version": 1, "required": ("consumer", "lastAt", "samples")},
    "TechniqueCartelContractSelection": {"version": 1, "required": ("runId", "symbol", "report")},
    "ManagedPositionHistoryRecovered": {"version": 1, "required": ("positionId", "source", "asOfMs", "addedSessions", "missedCloses")},
    "TechniqueCartelStateChanged": {"version": 1, "required": ("runId", "symbol", "action", "status", "phase")},
    "TechniqueCartelPreflight": {"version": 1, "required": ("runId", "symbol", "portfolioId", "report")},
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
    "TechniqueTradeCorrected": {"version": 1, "required": ("runId", "trigger", "fix", "old", "new")},   # FIX-01 reconciliation (2026-09-14)
    "TechniqueArmRefused":    {"version": 1, "required": ("runId", "symbol", "origin", "reason")},
    "TechniqueSourceRevised": {"version": 1, "required": ("noteId", "revision", "kind", "outcome")},
    "TechniqueEntryDecision": {"version": 1, "required": ("runId", "symbol", "trigger", "decisionId", "decisionMode", "decisionVersion", "verdict", "reasonCodes", "inputHash", "checks")},   # deterministic-entry-v1: the app decides; allow = eligible for the existing order checks, never a fill
    "TechniqueEntryEvidence": {"version": 1, "required": ("runId", "symbol", "trigger", "decisionId", "inputHash", "reviewOutcome", "authority"), "nullable": ("modelOpinion", "modelConfidence", "error")},   # evidence_only: no path back to trading
    "TechniqueExitShadow":    {"version": 1, "required": ("runId", "symbol", "trigger", "rung", "target", "version", "disposition")},   # STRATEGY-PROPOSAL 2026-09-14 §2a shadow-exit-v1: observation only, never an order
    "TechniqueExperimentPrepared": {"version": 1, "required": ("planFor", "eligible", "minted", "armed", "modelCalls")},   # em-experiment-v1 (2026-09-19)
    "TechniqueExitQuote": {"version": 1, "required": ("runId", "symbol", "trigger", "kind", "exitOrderId", "version")},   # exit-quote-v1 (2026-09-22): research record; nothing reads it on a money path
    "TechniqueAdmissionAlarm": {"version": 1, "required": ("kind", "book", "cause", "version", "text")},   # admission-health-v1 (2026-09-21): alarm + recovery; `isGate` is always false
    "TechniqueFirstSale":     {"version": 1, "required": ("runId", "symbol", "trigger", "stage", "mode", "version", "gate", "vehicle")},   # first-sale-v1 (2026-09-18): R where the FINAL quantity exits; refuses an entry only under `enforce`
    "TechniqueTargetDistance": {"version": 1, "required": ("runId", "symbol", "trigger", "stage", "fullExitRung", "distanceR", "version")},   # diagnostic flag; never rejects, resizes or retargets   # Delivery B next PR: a source revision landed (edit / delete / restore); positions and exits are never touched by it   # Delivery B order-free boundary (2026-09-14): scenario candidates never arm
    "TechniquePlanRestored":  {"version": 1, "required": ("runId", "symbol", "planFor", "portfolio")},   # restart re-attach; never counted as an arm
    "TechniquePlanDisarmed":  {"version": 1, "required": ("runId", "symbol", "reason")},
    "TechniquePlanRolled":    {"version": 1, "required": ("runId", "symbol", "from", "to")},   # multi-day plan advanced to its next session (ARM-GAPS A2/A4); was journaled without a contract
    "FlowSweep":              {"version": 1, "required": ("underlying", "occ", "ts", "windowBuys", "cumulative", "volOi", "method")},   # research/optiontrades.py (live detector, phase 2)
    "TechniqueCounterfactual": {"version": 1, "required": ("runId", "symbol", "trigger", "reason", "status", "pnl")},   # a trade the app missed through a bug, reconstructed after the fix (execution/counterfactual.py) - never a portfolio fill
    "TechniquePlanPaused":    {"version": 1, "required": ("runId", "symbol")},
    "TechniquePlanResumed":   {"version": 1, "required": ("runId", "symbol")},
    "TechniquePlanModeChanged": {"version": 1, "required": ("runId", "symbol", "from", "to")},
    "TechniquePlanTriggerFired": {"version": 1,
                                  "required": ("runId", "symbol", "trigger", "kind", "window", "entry", "stop", "mode"),
                                  "nullable": ("fill", "critic", "setupId")},
    "TechniquePlanTriggerSkipped": {"version": 1, "required": ("runId", "symbol", "trigger", "event")},
    "TechniquePlanRead":      {"version": 1, "required": ("runId", "symbol", "trigger", "event", "reason")},   # F28/F52: a structural read event (scenario, PM break, retest, late touch) journaled by a technique package, not the runner
    # Team2 F108: all picker paths share these fields, including early deferrals.
    # Contract/price/expiry and stage/error details depend on the verdict.
    "TechniquePlanContract": {"version": 1, "required": (
        "runId", "symbol", "event", "reason", "trigger", "verdict", "examined", "direction")},
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
    "TechniquePlanDiagnostic": {"version": 1, "required": ("runId", "symbol", "kind")},   # Team2 shadow diagnostics (2026-09-16): observation only, never a decision input
    "TechniquePlanPreopen":   {"version": 1, "required": ("runId", "symbol", "planFor", "premarket", "triggers", "replan")},
    "TechniquePlanReplanned": {"version": 1, "required": ("runId", "parentRunId", "symbol", "planFor")},
    "TechniqueHookStats":     {"version": 1, "required": ("technique", "date", "hooks")},
    "TechniqueLossHalt":      {"version": 1,
                               "required": ("technique", "portfolioId", "lossToday", "equity", "pct", "plans")},
    # --- durable positions (phase 2b; produced ONLY by execution/positions.py) ---
    "ManagedPositionOpened":  {"version": 1, "required": ("positionId", "technique", "symbol", "portfolioId", "legs", "policy")},
    "ManagedPositionAdopted": {"version": 1, "required": ("positionId", "technique", "symbol", "portfolioId", "legs", "policy")},
    "TechniqueCartelLossHalt": {"version": 1, "required": ("technique", "portfolioId", "day", "asOfMs", "pnl", "pct", "equity", "limit", "report")},
    "TechniqueCartelRiskMarksRecovered": {"version": 1, "required": ("portfolioId", "session", "source", "recovered", "preserved", "unavailable")},
    "ManagedPositionExit":    {"version": 1, "required": ("positionId", "symbol", "kind", "leg", "qty", "reduceOnly")},
    "ManagedPositionExitCancellationRequested": {"version": 1, "required": ("positionId", "symbol", "orderId", "attempt")},
    "ManagedPositionClosed":  {"version": 1, "required": ("positionId", "symbol", "realizedPnl", "reason")},
    "ManagedPositionPolicyChanged": {"version": 1, "required": ("positionId", "symbol", "policy")},
    "ManagedPositionReconciled": {"version": 1, "required": ("positions",)},
    "ManagedPositionAttention": {"version": 1, "required": ("positionId", "symbol", "error")},
    "ManagedPositionScaledIn": {"version": 1, "required": ("positionId", "symbol")},
    "ManagedPositionBracketReleased": {"version": 1, "required": ("positionId", "symbol", "portfolioId", "phase", "orders")},
    "TipFillVsQuote": {"version": 1, "required": ("proposalId", "orderId", "fillPrice", "fillQty")},
    "TipReviewGate": {"version": 1, "required": ("version", "mode", "path", "decision", "applied", "reason", "tickers", "matched", "intakeRunId")},   # review-gate-v1: skips a review only under enforce
    "SignalColdParkRecheck": {"version": 1, "required": ("signalId", "ticker", "waitedS")},
    "TipIntakeReplayed": {"version": 1, "required": ("contentId", "attempt", "max", "reason")},   # S21-07: bounded manual replay   # 2026-09-19: a cold-quote park re-verified on its first real quote
    "TipRecapClassified": {"version": 1, "required": ("category", "confidence", "recommendedRoute", "route", "knob")},
    "OrderBracketSkipped": {"version": 1, "required": ("reason",)},
    "ManagedPositionRolledUp": {"version": 1, "required": ("positionId", "symbol", "from", "to", "qty", "creditPerContract")},
    "TipGeometryRepaired": {"version": 2, "required": ("proposalId", "underlying", "entryRef", "repairs"),
                            "nullable": ("proposalId",)},   # v2 2026-09-08: armed-lane repairs carry runId/trigger, no proposal
    "TipAutoPaused": {"version": 1, "required": ("reason",)},
    "TipExecutionIncident": {"version": 1, "required": ("id", "action")},        # KB-06
    "TipFastStopDiagnostic": {"version": 1, "required": ("positionId", "verdict")},
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
