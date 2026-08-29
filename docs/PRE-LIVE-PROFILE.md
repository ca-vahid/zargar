# The pre-live profile (NEXT-GAPS R3)

*Written 2026-08-29, while the practice runtime deliberately runs the AMBITIOUS
active-dev limits (NEXT-GAPS-PLAN §0). This document is the other half of that
decision: the exact discipline settings that come back BEFORE the first real
tip trade, and the objective trigger for applying them. The gate is the
scorecard, not a feeling.*

## When this profile applies

Apply it when ALL of these hold — checked by tools, not vibes:

1. `python -m zargar.tools.soak_report` says **READY** (≥14 days span, ≥10
   clean multi-day rolls, ≥5 handoffs incl. a partial, 0 unexplained critical
   alerts, retros + lane grades accumulating).
2. The **Alpaca-paper overnight pass** is done: one options position held
   overnight app-managed on Alpaca paper, exits fired next session per policy
   (BUILDING-A-TECHNIQUE §2b).
3. At least one source shows **`barCleared` on the ARMED book** with
   `barBasis: "expectancyR"` (Tips → Sources scorecards — i.e. judged on
   scored R, not raw P&L).

## The settings (PATCH /api/settings, or Settings UI)

```json
{
  "risk.max_position_notional": 2000.0,
  "risk.max_position_pct": 10.0,
  "risk.max_gross_exposure_pct": 100.0,
  "risk.max_option_premium_pct": 10.0,
  "risk.max_option_premium_notional": 1000.0,
  "risk.max_option_contracts": 5,
  "risk.max_orders_per_minute": 10,
  "risk.daily_loss_halt_pct": 2.0,
  "risk.max_option_spread_pct": 10.0,
  "techniques.tip.budget_per_tip": 500.0,
  "techniques.tip.budget_open_max": 1500.0,
  "techniques.tip.max_open_tips": 3,
  "techniques.tip.max_risk_pct": 2.0,
  "technique.max_risk_pct": 2.0,
  "execution.daily_loss_fallback": 100.0
}
```

Stricter than the old defaults on purpose: the FIRST live period is about
verifying the machinery with real fills, not about returns.

## First-live rules (R4 — one at a time)

- One source only (the one that cleared the bar), smallest size.
- `techniques.tip.allow_live_auto` stays **OFF** — a human approves every
  proposal.
- The first live position gets its retro reviewed BEFORE the second trade.
- Any `needsAttention` on a live position pauses new live entries until
  explained.

## Never part of any profile

The kill switch, the never-list (no share shorting, no naked writing, 0DTE
rules), reduce-only exits and write-ahead ordering are identity, not settings.
