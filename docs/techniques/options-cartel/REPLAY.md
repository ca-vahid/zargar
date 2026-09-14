# Replay, comparisons and session evidence

Reviewed 2026-09-13. Research output never grants arming permission or edits the original plan.

Quantity defaults to original confirmed fills when known, otherwise a current fresh budget/equity estimate, otherwise one explicitly hypothetical unit. Explicit overrides remain hypothetical. A 100-unit percentage ladder cannot be divided down to represent a one-contract campaign. Saved replay records include quantity provenance and reachable exit allocations. Stored premium valuation uses bounded pages across long quote windows and preserves gap markers; it no longer rejects merely because 40,000 observations were recorded. See [the current evidence protocol](READINESS-2026-09-13.md).

## Underlying campaign replay

Saved plans expose Replay this campaign. Select stored bars or the shared historical provider, a UTC cutoff, modeled unit quantity and slippage. The replay saves its input snapshot and uses the Cartel entry/exit evaluators. Decisions use completed data; modeled fills use the next expected regular-session minute open. Missing tape is not bridged to a convenient later fill. Valid held-position daily-close exits can use the next session open; this does not allow new entries at the closing bell.

Realized/open R describe modeled **underlying-price** exposure, weighted by original units and entry-to-stop risk. They are not option premiums or actual account returns. This replay does not fully model option decay/expiry, fees, resting limit fills or quote-based protection.

New replay minute snapshots retain source classification; older six-number snapshots remain unknown. Source-aware plans and timeframe baseline rebuilds preserve their quality policy. Current stored/recovered bars can differ from the live decision's original observations. The current tape/hash plus retained decision measurements is not an immutable provider-revision ledger capable of reconstructing every past input.

## Paired entry-rule comparisons

History can compare up to 20 distinct plan-replay cases and eight named variants. The typed API supports timeframe (5/15/30m), breakout/retest mode, stop mode, volume multiple, close location and chase distance. A changed timeframe rebuilds its volume baseline from saved historical minute inputs; missing inputs/coverage cannot be silently scored. Existing plan levels, exits, quantities and tapes are preserved.

All cases and effective policies are stored. Incomplete/open cases are excluded from closed-return means, and paired differences use common complete closed cases. Inspect exclusions and sample selection: these selected-plan sweeps are not a universe-wide unbiased walk-forward, and a good hindsight variant is not automatically promoted.

## Recorded option-quote valuation

Premium replay is a separate research path. It requires a matching contract, compatible recorded observations, source/timing evidence and explicit fee assumptions. Stored observations are scoped to the plan and contract. Unavailable, delayed, halted, crossed or otherwise unusable observations cannot be skipped merely to reuse an older favorable quote. Missing quote history remains unscorable.

The recorder and stored-quote valuation endpoints are implemented. They do not retroactively create a historical quote archive, replace executable quote checks or prove achievable fills. See `premium_replay.py`, `quote_observations.py` and their tests for exact supported valuation rules.

## Session review and record review

The Plans page's Session review is read-only. It shows account/session-scoped recorded decisions, source counts and order/fill counts; it does not calculate hypothetical option profits. A data-limited category records a limitation, not proof that the missing data caused a profitable trade to be missed. Use the account risk/P&L report for actual recorded trading performance.

Record reviews can annotate setup, execution, data and outcome concerns. Keep actor attribution, as-of time, method version and uncertainty explicit. Do not combine an author's peak-trim percentage with our realized portfolio result.

Implementation: `replay.py`, `replay_service.py`, `sweeps.py`, `premium_replay.py`, `quote_observations.py`, `session_review.py`. Historical test counts are in dated release/deployment records; [current limits](DELIVERY-STATUS.md) govern new work.
