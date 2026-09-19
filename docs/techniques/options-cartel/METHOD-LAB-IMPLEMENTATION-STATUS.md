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

## Deployment and first prospective cohort

v0.8.21 deployed at 2026-09-19 04:33Z, build
`b16079f3072a3559810a3aa3ac0d034eb6ce10e4`. The guarded receipt verified
19/19 arms, 6/6 managed positions and 28/28 resting orders restored. The engine
was unquiesced with zero failed handlers or bus drops. Team2 settings and roster
fingerprints were unchanged. Only Practice method-lab collection was enabled;
no challenger was activated for orders.

Monday September 21 preparation `1e41aa05b76745e49984bf7d62edf529` processed
3,072 symbols: 3,071 evaluated, one data error, eight qualifying and three armed
(BBY, CNH, NOW) through the existing strategy. Research context
`5c4a5bc16448efddb605e3ef47bf17ff` froze eight candidates. Five baselines were
ready and SAIC, ULTA and ASC had partial coverage at the post-preparation check.
Missing baseline slots remain refusals; bounded pre-open warm-up can retry.

Trial `fb2fc7723dbcfdf4292cf96417738c79` compares breakout_5m_v1 with
undercut_reclaim_5m_v1 from September 21. Its protocol hash is
`3d1393fec87d3ffff2d2420adc4f6840a2acfab299645454680c0e746ab4aa03`.
The minimum remains 20 sessions, 30 closed outcomes per variant and two regimes,
plus after-cost improvement, exposure and drawdown checks. These are future
evidence requirements, not a passed profitability verdict.

The live smoke found future observation windows incorrectly labeled incomplete.
v0.8.22 corrects this to awaiting_sessions before the first open, with zero
future observation debt. After open, real missing evidence stays incomplete.

## Current remaining work

Collect prospective sessions and review the declared acceptance gates. Resolve
provisional source statements without changing frozen protocols retrospectively.
The seven-phase goal remains active; software delivery and validated profitability
are separate outcomes. Signed-in visual inspection remains unverified (the local
browser required login); the production build and authenticated API were checked.

## Release acceptance checkpoint

v0.8.21 metadata and production UI build pass. The final focused backend run passed 119 tests in 202.39 seconds, including lifecycle, receipt accounting, trial reconciliation, workspace separation, existing Cartel behavior and the equity SIP size cutoff. Ruff F and diff checks pass. No profitability verdict or trading activation follows from these checks.
