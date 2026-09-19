# Method lab implementation status

September 18, 2026. Development branch: `codex/cartel-method-lab` in the owned
`.cache/cartel-method-lab` checkout. Runtime remains on the previously verified
v0.8.20 release. This branch has not been merged, deployed or activated.

## Built in the current development pass

- Source-to-code matrix distinguishes archived author statements, mirrored
  statements, engineering definitions and platform safeguards.
- Separate typed, versioned shadow undercut/reclaim and 30-minute pivot readers.
  Complete chronology, support/targets frozen pre-open, no same-candle pivot
  breakout, data-gap reset, low-so-far stop and no historical entry on restart.
- Advisory ADR-normalized compression, EMA slopes and long-history features.
  Missing fundamentals/stage evidence stays unknown; no invented rating.
- Read-only immutable Practice records: context, baselines, ticks, signals,
  quote observations, price availability receipts and trial definition. New
  records cannot be production plans and are excluded from ordinary run lists.
- Disabled-by-default runtime collector, bounded warm-up/quote work, own task
  cancellation, separate 5m and 15m baselines, paired source timestamps and
  exact signal inputs. Baseline retries are capped at three per candidate/context.
- API and Settings/Validation component for inspection, with explicit source
  uncertainty and no trading activation control.
- Pure same-signal shares/options/pass adapter reusing campaign valuation.
  Missing quotes/fees remain unavailable; no stock-return substitution for options.
- Frozen one-challenger trial contract and a conservative review calculator.
  Minimum sample, paired population, exposure/drawdown, concentration and cost
  stress checks never grant execution authority. Multi-day exposure overlaps
  are counted, rather than booking every campaign on its entry date.

## Verification so far

The combined focused run passed 77 tests covering new mechanics, existing Cartel
runtime, economics and profitability collection. Production frontend build and
Ruff F passed. Further targeted changes made during causal review require the
next focused run before release. No test has touched the runtime database.

## Remaining implementation and acceptance

Receipt-accounting checkpoint: the forward model now uses price/quote receipt
ordering, displayed-size consumption, integer partial fills, separate option/share
fee rules, and known stop/EMA decisions. A stored DB-path regression verifies
separate option/share results and no orders. Trial reconciliation retains missing
pairs, and selection reports keep the same breakout control. The UI exposes
modeled fills and quote attempts. Carry-over observations continue without a new
daily cohort. Daily 16:10 ET reviews include a Friday weekly marker.

Source-backed shared correction: modern Alpaca CTA/UTP sizes are shares, effective
November 3, 2025; the old unconditional x100 conversion overstated equity depth.
Date/feed-scoped normalization and regression coverage are implemented. OPRA
option units and price-field timestamps are unaffected. Method-lab preparation
also works when the older profitability-research switch is off. Committed terminal
invalidations survive later data revisions.

## Current remaining work

1. Complete final lifecycle and source acceptance, including disabling an in-flight
   observation, bounded scheduled review, and first-cohort readiness.
2. Close user-facing documentation and release metadata; resolve current-main and
   runtime-only changes without altering another team's work.
3. Merge and deploy through the guarded path, verify exact build/restoration and
   enable only non-ordering Practice collection. Freeze a fresh trial before its
   first session; do not retrofit old records into a prospective cohort.
4. Collect future sessions. The declared minimum sample, economic improvement,
   drawdown/exposure checks and an activation verdict remain unproven. The source
   matrix keeps mirrored statements provisional and numerical choices experimental.

The seven-phase goal remains active. Built software, deployment readiness and
validated profitability are separate outcomes. This checkpoint does not narrow
that objective or claim that a trial has passed.

## Release acceptance checkpoint

v0.8.21 metadata and production UI build pass. The final focused backend run passed 119 tests in 202.39 seconds, including lifecycle, receipt accounting, trial reconciliation, workspace separation, existing Cartel behavior and the equity SIP size cutoff. Ruff F and diff checks pass. No profitability verdict or trading activation follows from these checks.
