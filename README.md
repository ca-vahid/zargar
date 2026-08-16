# Zargar

Personal stock trading application connected to Interactive Brokers (IBKR).

Zargar is a single-user app built around three ideas:

1. **Fast manual execution** — see an opportunity, execute it immediately through an intuitive, real-time interface.
2. **Signal ingestion with verification** — automatically pull the latest ideas from subscribed newsletters, message boards, and email alerts; extract the actionable signal; verify it against live market data; and propose a trade for one-tap approval.
3. **Graduated automation** — start with human approval on everything, then promote trusted signal sources and rules to conditional auto-execution, always behind hard risk limits and a kill switch.

A **mock mode** runs the same pipeline without sending real orders, so every strategy and signal source can be evaluated on "what would have happened" before real money is at stake.

## Status

Research phase complete. See:

- [RESEARCH.md](./RESEARCH.md) — comprehensive technology and architecture research (IBKR API landscape, app architecture, charting, signal ingestion, safety guardrails).
- [DECISIONS.md](./DECISIONS.md) — the owner's confirmed decisions (stack, instruments, hosting, risk defaults) and the build order.
