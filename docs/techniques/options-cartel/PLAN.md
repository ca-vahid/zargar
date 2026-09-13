# Cartel work status and next changes

Updated 2026-09-13. [Current capabilities](DELIVERY-STATUS.md) and [operating guide](DAILY-PREPARATION.md) are authoritative for shipped behavior. The September 12 proposal was subsequently authorized and substantially implemented; its original acceptance wish list is not a declaration that every item is complete.

| Work package | Status | Next evidence or work |
|---|---|---|
| W0 evidence/fixtures | Friday diagnostics and boundary fixtures recorded | Expand date-matched author examples without hindsight |
| W1 provenance | Source classification survives Cartel serialization; execution/recovery checks implemented | Immutable provider revisions and exact historical decision-input reconstruction remain open |
| W2 history/baselines | Durable caches and incremental reads; requested 20-session baselines | Identity/adjustment/no-trade semantics and source comparisons |
| W3 jobs/speed | Ownership lease, cancellation, eligible auto-resume and checkpoint display | Faster aggregate resume and measured performance targets |
| W4–W5 ignition | Research theses plus selectable Practice detector/pilot | Calibrate fixed thresholds; richer catalyst and thesis-stage handling |
| W6 readiness/contracts | Coverage policy, reserves, capacity guards, rejection reasons and terminal invalidation | Provider completeness/latency evidence; maintain explicit query budgets |
| W7 experiments/economics | Stop/timeframe sweeps, whole-contract preview and existing recorded-quote valuation | Prospective evaluation, option-fill assumptions and graduation criteria |
| W8 reporting/release | Session review, source counts, updated Method chapters and deployment checks | Continue reconciling actual runtime and Git version; improve historical revision reporting |

Every future behavior change needs a concrete failing case or sourced hypothesis, immutable baseline inputs, appropriate boundary tests and a rollback path. Do not loosen unrelated gates to force entries. Keep pure research separate from active orders; never infer a profitable option result from underlying R or author marketing percentages.

For implementation history use [the original detailed delivery record](archive/PLAN-PRE-2026-09-13.md), [September 12 proposal](IMPLEMENTATION-PLAN-2026-09-12.md), [weekend findings](WEEKEND-REVIEW-2026-09-12.md) and [release scope](RELIABILITY-RELEASE-2026-09-12.md). The backlog above takes precedence over superseded pending/completed labels in those records.

Develop from current origin/main in an isolated owned branch; preserve all other desk work. Follow [AGENTS.md](../../../AGENTS.md). Test only zargar_test_codex sequentially. Build/version the integrated tree when bundled Method text changes; coordinate deployment separately from editing documentation.
