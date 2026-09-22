"""F4 (2026-09-21 brief): explicit Practice entry-cadence experiment with a matched control.

``breakout_15m_v1`` is the incumbent (15-minute closed-candle confirmation). ``breakout_5m_v1`` is
the same rule set on 5-minute candles with its own historical baseline. Exactly ONE cadence executes
per plan/book: the executing plan is the arm; the control is a pure read of the same tape under the
other cadence, stored beside the arm's state, stamped with an id that ``consume_locked`` can never
accept, and it never reaches ``reserve_submission``. Today's 5m NTNX signal is evidence that cadence
changes eligibility, not that 5m is profitable; this module records, it does not decide.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .entry import read_entry
from .plans import CartelPlan
from .service import WireModel

CADENCE_MINUTES = {"breakout_15m_v1": 15, "breakout_5m_v1": 5}
CONTROL_OF = {"breakout_5m_v1": "breakout_15m_v1", "breakout_15m_v1": None}
CONTROL_VERSION = "cartel-cadence-control-v1"
MAX_CONTROL_SIGNALS = 20


class VolumeExperiment(WireModel):
    """Predeclared volume-multiple grid for REPLAY only. Never applied to a live entry read."""
    version: Literal["off", "grid_v1"] = "off"
    multiples: tuple[float, ...] = (0.9, 1.0, 1.2, 1.5)

    @model_validator(mode="after")
    def bounded(self):
        if any(not 0 < m <= 100 for m in self.multiples) or len(set(self.multiples)) != len(self.multiples):
            raise ValueError("volume grid multiples must be distinct and within (0, 100]")
        return self


def cadence_minutes(cadence: str) -> int:
    if cadence not in CADENCE_MINUTES:
        raise ValueError(f"unknown entry cadence {cadence!r}")
    return CADENCE_MINUTES[cadence]


def control_cadence(cadence: str) -> str | None:
    return CONTROL_OF.get(cadence)


def control_config(cadence: str, baseline: dict, as_of_ms: int) -> dict | None:
    """The arm-config block for the matched control: cadence, its INDEPENDENT baseline, provenance."""
    control = control_cadence(cadence)
    if control is None:
        return None
    if baseline.get("timeframeMinutes") != cadence_minutes(control):
        raise ValueError("control baseline timeframe does not match the control cadence")
    return {"version": CONTROL_VERSION, "executing": cadence, "control": control,
            "controlTimeframeMinutes": cadence_minutes(control), "controlBaseline": {str(k): v for k, v in baseline["baselines"].items()},
            "controlBaselineAsOf": as_of_ms, "controlSampleCounts": {str(k): v for k, v in baseline.get("sampleCounts", {}).items()},
            "placesOrders": False, "note": "Matched control: same plan geometry and tape, other cadence, own baseline; observation only."}


def control_plan(plan: CartelPlan, config: dict) -> CartelPlan:
    minutes = int(config["controlTimeframeMinutes"])
    baseline = {int(k): float(v) for k, v in (config.get("controlBaseline") or {}).items()}
    return plan.model_copy(update={"entry": plan.entry.model_copy(update={"timeframe_minutes": minutes}),
                                   "volume_baseline": baseline, "baseline_as_of": min(plan.baseline_as_of, int(config.get("controlBaselineAsOf", plan.baseline_as_of))),
                                   "cadence_version": config["control"]})


def control_signal_id(plan_id: str, cadence: str, end: int) -> str:
    # Deliberately NOT ``<plan>:entry:<end>``: ArmRepository.consume_locked refuses this shape.
    return f"{plan_id}:control:{cadence}:{end}"


def read_control(plan: CartelPlan, config: dict, tape, now: int, *, entry_after, verified_intervals=None, previous=None) -> dict:
    """Pure read of the control cadence over the arm's tape. Returns the new control state."""
    if not config or not config.get("control"):
        return previous or {}
    shadow = control_plan(plan, config)
    previous = previous or {}
    cutoff = max(entry_after or 0, previous.get("observeAfter") or 0)
    observation = read_entry(shadow, tape, now, entry_after=cutoff, verified_intervals=verified_intervals)
    signals = list(previous.get("signals", []))
    signal = observation.get("signal")
    observe_after = cutoff
    if signal:
        stamped = {**signal, "id": control_signal_id(plan.id, config["control"], signal["at"]), "cadence": config["control"],
                   "researchOnly": True, "placesOrders": False, "observedAt": now}
        if all(s["id"] != stamped["id"] for s in signals):
            signals.append(stamped)
        signals = signals[-MAX_CONTROL_SIGNALS:]
        observe_after = max(observe_after, signal["at"])   # a later read cannot re-emit the same candle
    from .preparation_readiness import retain_decisions
    return {"version": CONTROL_VERSION, "cadence": config["control"], "timeframeMinutes": shadow.entry.timeframe_minutes,
            "status": observation.get("status"), "signals": signals, "firstSignalAt": signals[0]["at"] if signals else None,
            "decisionHistory": retain_decisions(previous.get("decisionHistory", []), observation),
            "observeAfter": observe_after, "lastReadAt": now, "placesOrders": False, "researchOnly": True}


def control_summary(config: dict | None, control_state: dict | None, cutoff: int) -> dict | None:
    """Session-review view: what the non-ordering control would have confirmed, and nothing more."""
    if not config or not config.get("control"):
        return None
    state = control_state or {}
    decisions = [d for d in state.get("decisionHistory", []) if d.get("at", 0) <= cutoff]
    signals = [s for s in state.get("signals", []) if s.get("at", 0) <= cutoff]
    counts = {}
    for d in decisions:
        counts[d.get("decision")] = counts.get(d.get("decision"), 0)+1
    return {"executing": config.get("executing"), "control": config.get("control"), "controlTimeframeMinutes": config.get("controlTimeframeMinutes"),
            "subscriptionError": state.get("subscriptionError"), "subscriptionFailedAt": state.get("subscriptionFailedAt"),
            "controlSignals": len(signals), "controlFirstSignalAt": signals[0]["at"] if signals else None,
            "controlFirstSignal": {k: signals[0].get(k) for k in ("at", "referencePrice", "stop", "volumeRatio", "closeLocation")} if signals else None,
            "controlDecisionCounts": counts, "controlBaselineSlots": len(config.get("controlBaseline") or {}),
            "placesOrders": False, "actualFills": "see the executing row; the control has no orders, fills or modeled P&L",
            "note": "A control confirmation is a matched observation on the same tape, not a missed profit."}


def volume_grid_variants(experiment: VolumeExperiment, executing_cadence: str) -> list[dict]:
    """Sweep variants for the predeclared grid (replay only; inactive when version is off)."""
    if experiment.version == "off":
        return []
    return [{"name": f"volume_{m:g}x_{executing_cadence}", "timeframe_minutes": cadence_minutes(executing_cadence), "volume_multiple": m}
            for m in experiment.multiples]
