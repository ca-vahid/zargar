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

1. Wire stored signals/quote paths/price receipts through economic valuation and
   the paired multi-session trial review, including held campaigns across dates.
   Do not promote a modeled next-open schedule as a contemporaneous fill.
2. Reconcile quote capture capacity/deadlines, missing quote reasons and exit
   displayed-size evidence. An option quote observation is not an executed trade.
3. Add UI results for complete versus missing economic observations and the
   review gate; distinguish the primary challenger from diagnostic models.
4. Complete lifecycle regressions: mid-flight stop/disable, late quotes,
   restart/deduplication, incomplete baseline retry, foreign/Live scope and
   overlapping modeled positions. Inspect the final causal path end to end.
5. Finish source-example calibration where original dated evidence can be
   obtained. Provisional interpretations remain explicitly experimental.
6. Prepare a versioned release with docs, focused tests, build and rollback;
   preserve runtime-only changes and coordinate deployment/restore with Team2.
7. Freeze the first prospective trial before its first session and collect real
   evidence. Economic improvement, sufficient sample and an activation verdict
   cannot be certified from implementation tests or the current short history.

Active goal remains the complete seven-phase plan. This status is a checkpoint,
not a redefinition of completion or a claim that the trial has passed.
