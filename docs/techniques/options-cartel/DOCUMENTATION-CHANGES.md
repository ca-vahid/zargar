# Cartel documentation changes

## 2026-09-18 — cleared diagnostics and order-free Lane A evaluation

- D3/D4/D5 diagnostics built without changing any decision, gate or protection: refusal measurements and bucket input hashes in `read_entry`, a bounded dropped-bar registry with per-plan journaling, the profitability collector off the event loop, spread cost on preflight records.
- Pure Lane A reviewer and feasibility classifier (`lane_a.py`) plus the read-only frozen replay (`cartel_lane_a_eval.py`); results in `reviews/2026-09-17-proposal/lane-a/`: strict basis 0 qualifiers in 09-08 → 09-17, Moderate variant 10 qualifiers all below the inactive 1.5R experiment. Nothing wired into preparation, arming or entry.

## 2026-09-18 — Lane A proposal revision 3 (P1 evidence fixes; no behaviour change)

- Evidence tool: trade-tape probe enforces [start, end) minute boundaries locally, records per-interval verification times, classifies by reported conditions with size statistics separate, treats incomplete bar pagination and unprobed minutes as non-certifying, writes credential-free artifacts (`reviews/2026-09-17-proposal/evidence/`). Replay renamed to final-arm-tape; journaled decisions are the authority; per-minute value comparison added.
- Probe rerun: PLAB 44/44, LZB 55/55, PWR 17/17 absent minutes had trades (odd-lot dominated), zero boundary drops. New finding: stored bars are revised after decisions (most minutes differ in value from the arm's saved minutes). Proposal: coexistence contract (`lane_a_focus` default 0, fallback, pending never reserves), D1 as an offline versioned volume comparison, execution unchanged.

## 2026-09-18 — Lane A proposal revision 2 (review corrections; no behaviour change)

- Evidence tool corrected per review: attribution by plan/order/position id, production-consistent partial-bucket handling, engine `read_entry` replay over decision-time and stored tapes, exchange-calendar sessions, spread in cents/dollars, `latency` and the read-only `alpaca-minutes` D1 probe.
- D1 probe result recorded: every probed absent SIP minute (PLAB, LZB 09-16; PWR 09-17) had odd-lot trades — none was a no-trade minute. Proposal revised: 1.5R inactive experimental filter, provisional retryable feasibility, causal snapshot per input, legacy controls separated from Lane A examples, coexistence via `lane_a_focus`, causal stop observations.

## 2026-09-17 — Lane A proposal package (review pending, no behaviour change)

- Added `reviews/2026-09-17-proposal/` (bottleneck reconstruction from runtime records, executable funnel map, rule matrix, Lane A proposal with acceptance criteria and incremental plan) and the read-only `zargar.tools.cartel_evidence` reproduction tool.
- Repairs the evidence gap for 2026-09-16/17 (QS spread refusal, TTWO/PWR contract affordability and target status, APTV no-setup, coverage-blocked candidates). No setting, arm, order or runtime process changed.

## 2026-09-16 — end-of-day follow-through

- Documented Practice-only spread reselection, unchanged saved limits and full revalidation.
- Added overnight baseline readiness and explicit stock-only entry challenger definitions.
- Daily review now exposes dated preflight refusals; source limits and unpriced outcomes remain explicit.


## 2026-09-16 — current operations and research consolidated

- Refreshed operating, capability, work-plan, release, replay and traceability guides against the integrated code.
- Replaced obsolete deployment/symbol/test snapshots in current guides with links to dated evidence; historical reports remain intact.
- Added status interpretation, future-session gaps, source-quality distinctions, fair retries, primary-short versus additional bearish-proxy counts and funding limitations.
- Updated shared architecture and agent guidance for research isolation and reviewed deployment identity.


## 2026-09-15 — profitability research protocol

- Added the prospective pool, selection, bearish, campaign-target, exit and conditional
  expression study definitions, including cash/option evidence and holdout requirements.
- Added operating instructions and a bundled Method chapter; linked preparation, rules
  and the September 15 findings without rewriting that historical review.
- Retained execution permission, sizing and whole-unit boundaries. Research comparisons
  do not claim improved profitability or automatically promote a strategy.

## 2026-09-13 — final review corrections

- Added the final review and current correctness/Practice protocol, including source-versus-engineering boundaries.
- Updated preparation, replay and delivery guidance for final-dispatch limits, target causality, pending invalidation, legacy arm review and provider identity.
- Documented quantity-specific exits, quote gaps/deduplication, paged premium valuation and advisory cohort limitations. No profitability or automatic Live-graduation claim.

## 2026-09-13 — current guidance consolidated

- Replaced contradictory README, preparation, delivery status, release handoff and traceability text with code-checked current guidance.
- Archived the old detailed delivery plan/status/traceability/handoff with adjusted links and explicit historical labels. Removed obsolete preview PIDs and superseded instructions from current entry points.
- Added the ignition chapter: actual stages, fixed detector thresholds, research-versus-pilot distinction, data limits and source coverage.
- Corrected refresh preservation, first-session expiry, five-day legacy cache fallback, four-day/matching-session resume eligibility, automatic recovery/cancellation and native-provider opt-in semantics.
- Corrected replay timeframe/stop support and source preservation. Documented the limits of tape hashes/source classification rather than claiming a complete immutable revision ledger.
- Updated S30/video/ledger coverage; replaced unresolved-transcript and review-approval statements that subsequent work superseded.
- Separated implemented, partial and unvalidated work. Dated deployment/test outcomes remain dated, including the original full-suite failures and later passing affected groups.
- Updated the in-app Method chapter links and shared project pointers. No backend trading logic, account settings, orders or runtime processes changed in this documentation task.

Application release metadata changes only to publish the bundled Method-library text; a running app requires a later frontend rebuild/deployment to display it. This document does not claim such a deployment occurred.
