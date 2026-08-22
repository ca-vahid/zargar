"""Shared execution layer — the technique-agnostic machinery for turning a
signal into managed orders.

A "technique" (EnhancedMarket today; others later) produces *what* to trade —
levels, triggers, a plan. Everything after that is the same regardless of the
technique: listen to live 1-minute bars and order updates, place the entry
through the one order path (RiskGate), then manage the position out — stop,
scale-out ladder, flatten before the close — with **reduce-only** exits that a
kill switch or loss-halt can never trap. This package holds that machinery so a
new technique reuses it instead of re-implementing the risky part.

- `SessionListener` — subscribes to BARS(1m) + ORDERS + a 60 s heartbeat and
  dispatches to subclass hooks; owns the order-id → owner index. `PlanArmer`
  (technique arming) is the first subclass.
- `exits` — pure exit-decision + reduce-only intent building (stop / 30-40-15
  ladder / single-contract / flatten), unit-tested without a broker.
- `book` — `ManagedTrade`, the lifecycle record shared by the listener and the
  exit planner.
"""
from .book import EXIT_LADDER, ManagedTrade
from .exits import ExitDecision, plan_exit, reduce_only_exit_intent
from .listener import SessionListener

__all__ = [
    "SessionListener", "ManagedTrade", "EXIT_LADDER",
    "ExitDecision", "plan_exit", "reduce_only_exit_intent",
]
