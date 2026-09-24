# Options Cartel Practice: expanded-capital experiment

> Ended 2026-09-23 22:10 ET by user decision: Practice moved to `Options Cartel Practice 10k`
> (`297d8b39d1c4418199f24c2331b14c11`). This book never traded and is archived. See TRADING-RULES.

User authorized September 19: remove funding constraints that prevent the Practice
experiment; virtual money is not scarce. This supersedes the earlier recommendation
to keep the $500 budget and the shares-fallback proposal as the immediate next step.
The purpose is to test the method without the previous small-book affordability
restriction. More notional or bigger dollar P&L is not itself a better strategy.

## Applied through authenticated app APIs

Runtime v0.8.23, verified build b6e272acd1696c0dd1ae0c0acd56c634ad4bbf97.
Activation September 19 approximately 10:25 PT, after the unrelated shared restart
completed and restoration verified. This task did not restart the engine.

| Setting | Previous | Experiment |
|---|---:|---:|
| Dedicated sim book | Options Cartel Practice | Options Cartel Practice - Capital Experiment |
| Starting virtual cash | $10,000 | $1,000,000 |
| Purchase budget per plan | $500 | $25,000 |
| Maximum option ask | $5 ($500/contract) | $250 ($25,000/contract) |
| Focus capacity | 5 | 20 |
| Risk percentage | 10% | 10% |
| Maximum contracts per entry | 10 | 10 |

The new book ID is `e7b246c9e30d4dde93f4d91844cbc982`.
The old book `0b48ed48de2f4030b49942b52858356d` was verified to have no holdings
or working orders, then archived with equity $9,938.87. Nothing was deleted.
Its three unfilled waiting BBY/CNH/NOW arms were disarmed before routing changed;
a new preparation rebuilds valid arms with the new book and saved limits.

New preparation: `7095e32affcf456ba91c7d21b56662dc`, session September 21,
automatic Practice. Initial status running; append verified outcome below.

Only `techniques.options_cartel.default_portfolio` and the Practice preparation
setting changed. A before/after fingerprint of all other settings was equal.
Live settings, Team2, Tips and EM were not modified. No manual order was submitted.

## What this changes and what it measures

The previous eligible asks for NVT ($9.90), ULTA ($10.50) and NTNX ($11.00)
fit the new affordability ceiling. Their original refusal is addressed by this
capital change; a fresh preparation and valid entry are still required. Current
bid/ask, provider provenance, liquidity, market/stock setup, trigger confirmation,
identity, permissions, duplicate prevention and protective exits remain truthful.

This is generously funded, not mathematically unlimited. Platform per-position
notional remains $25,000, which matches the new budget; gross exposure and loss
checks remain. These are not expected to restrict the current small candidate set
in a $1m book. Record any remaining funding refusal explicitly; do not secretly
raise global limits affecting other techniques.

The old $10k results and new $1m results are different capital regimes. Preserve
both book IDs in reviews. Report actual fees, quantity, invested premium, return
on deployed capital, normalized outcomes and missed opportunities. Do not count
new virtual capital as profit or compare raw dollar gains without sizing context.
The method-lab protocol for the previous book remains immutable; the new book
gets its own policy/cohort records. Future-market evidence is not a completion
requirement for the earlier implementation goal.

## Readiness and rollback

Verify final preparation, each active arm's portfolio ID/mode/limits and remaining
refusal reasons. Quote/market gates can legitimately leave a candidate unarmed.
Do not claim that a larger account guarantees trades or profits.

For rollback, first inspect active positions and orders. Preserve their protective
management. Restore routing or retire the experiment only through the app workflow;
never archive a funded book with holdings as a shortcut. Historical records in the
old archived book remain readable by ID. The prior $500 policy is documented in
the Monday-action note and immutable old preparation records.

## Verified arming outcome

The run processed all 3,073 discovered stocks, found eight qualifying candidates,
and armed six: **BBY, CNH, NOW, ULTA, NTNX, NVT**. All six persisted arms are
mode=auto, plan_for=2026-09-21, portfolio_id=e7b246c9e30d4dde93f4d91844cbc982,
budget=25000, max_premium=250, max_units=10 and risk_pct=10.

| Symbol | New arm ID | Selected contract |
|---|---|---|
| BBY | 6a84b92f57de446a8d3754d2a7f73847 | BBY261120C00095000 |
| CNH | fc0e06a7b8dc0438d4092c24e643a8b9 | CNH261016C00012500 |
| NOW | 657f377d09335ac8319681cee121bea7 | NOW261030C00150000 |
| ULTA | efa63e0f2e4fdafc4f4ad939345852e2 | ULTA261016C00560000 |
| NTNX | 250c9f2703971911236ab7ec3d1e12d4 | NTNX261016C00060000 |
| NVT | 4bde0f517ae904dcf0aaf8651317c597 | NVT261120C00170000 |

This is an actual behavior change: ULTA/NTNX/NVT moved from awaiting_contract
under the old premium cap to armed in the experiment. It is not an entry, fill
or profit claim. SAIC and ASC remain blocked on historical-volume coverage (only
the closing 15-minute baseline is available; it is not an entry window). FISV
has a missing 2025-11-12 daily session. Do not treat these as funding failures.

At the arming verification, the run was still writing non-ordering research
records. The engine continues this work; the six saved arms already exist.
No funding refusal remains in the six-arm shortlist. Other techniques retained
nine Team2 arms and ten Tips arms immediately after the migration.
