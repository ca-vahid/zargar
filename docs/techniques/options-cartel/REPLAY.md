# Campaign replay

Saved Cartel plans expose **Replay this campaign**. Choose stored engine bars
(which may be simulated) or the shared historical provider, a UTC cutoff,
original unit quantity and per-fill slippage in basis points. Each replay saves
a new owned research run with the original plan, exit campaign and input bars.
It does not arm, create orders, start the engine or alter the parent plan.

The evaluator uses Cartel's entry and exit decision functions. Completed-minute
decisions receive modeled fills at the next expected regular-session minute's
open. Missing minutes do not bridge to a later fill. The next session's open is
used for a decision at the prior close. Integral partial allocations and the
move to breakeven advance on modeled fills, not on a target signal.

Realized R weights every modeled exit by its fraction of original quantity,
divided by original entry-to-stop risk. Open R represents only remaining units.
These are underlying-price outcomes. Option-premium paths, fees, expiry,
resting limit-order execution and quote-based crash protection are not modeled;
this is not full execution parity or evidence of achievable option returns.

Missing tape produces an incomplete outcome. Missing daily history disables the
affected daily decisions and is reported. Provider depth restrictions still
apply, and stored bars do not retain per-bar feed identity. The replay preserves
its input snapshot so these limitations can be reviewed alongside the result.

Verification added: next-open causality, weighted partial returns, breakeven
after fills, missing entry/exit minutes, chase rejection, duplicate conflicts,
and API persistence with unchanged parent plans and zero orders. An entirely
absent earlier session also makes later entry outcomes unscorable.

On 2026-09-07 the replay/API suite passed 16 tests, including an injected
historical provider with persisted input snapshots. The expanded replay form
was inspected in Chrome; the expanded plan, option preferences and replay
controls passed all five mobile audit device profiles. Ruff and diff whitespace
checks passed. Real-provider data retrieval and browser submission/result
acceptance remain unverified; the running preview backend was not restarted.
Sweeps, complete source-example calibration and full premium-aware outcomes
remain separate unfinished work.

## Entry-rule comparisons

History exposes **Compare entry rules** for up to 20 campaign replay cases.
The API accepts up to eight named variants of volume multiple, minimum close
location and maximum chase R. Timeframes stay fixed because changing them
requires rebuilding the historical time-of-day volume baseline. Reviewed
levels, targets, exit schedules, quantities, slippage and tapes stay fixed.

Experiments persist input snapshots, a SHA-256 digest, effective entry policies
and every case result. Incomplete and open cases do not enter closed-return
averages. Different variants can close different subsets; inspect paired rows
before interpreting averages. Only one replay per parent plan is accepted.
Experiments never change live plans or create orders.

These selected-plan experiments retain selection bias. They do not replace
the still-required universe/date walk-forward scan, source-example calibration
or premium-aware outcomes. Comparison controls and results still need
browser/mobile acceptance.

Verification update (2026-09-07): the expanded comparison form passed all five
mobile layout profiles, and the production build and scoped Ruff passed.
Four sweep tests cover unchanged source plans, exclusion of incomplete cases,
input uniqueness and identical-variant paired returns. Paired mean delta R now
uses only cases closed with complete data in both the baseline and variant;
this excludes missed entries and remains distinct from portfolio returns.
Browser submission and rendered nonempty comparison results are still pending.

Verification update (2026-09-07): Chrome submitted a stored-bar replay and then
saved comparison `4bc64b7361114ff6adcc93bc0b193cbb`. The result rendered one
incomplete case in both variants with no scored return or paired delta. A
separate Playwright submission verified that cutoff `2026-05-05T20:00Z` persisted
exactly in replay `80a25a1e32f34d74bb877a482dfa4f38`. No orders, positions or active
arms were created. The refreshed backend now serves these routes. Rendering
filled campaign paths and real-provider campaign replay remain unverified.

## Recorded option-quote valuation

A saved underlying replay can now be valued through
`POST /api/options-cartel/runs/{runId}/premium-replay` using a matching call/put,
source description, per-contract fee and recorded quotes. Each quote carries
source and availability timestamps, bid, ask and delayed status. The valuation
uses only quotes available by each modeled fill time and within the requested
age limit. Conflicting duplicates are rejected; absent, stale, delayed, zero-bid
or expired-contract evidence cannot produce a total return.

Entry is valued at ask and exits at bid with the standard 100x multiplier. Entry
fees are allocated between closed and remaining contracts; remaining-position
marks do not invent future exit fees. Calls and puts are both long-premium
positions. Each result preserves the underlying schedule and supplied quotes as
a separate owned history record without modifying its parent or placing orders.

This is a conditional valuation of the underlying replay's fill schedule. It
still does not model quote depth, resting orders, expiry settlement or exits
triggered by option premium itself. It is not a full option execution simulator.
The quote-import UI is available on saved replay records, with a separate result
view showing premiums, allocations, fees and net returns. It requires explicit
UTC source/availability timestamps and delayed/halted flags for each row. Historical
quote-provider integration remains unfinished.
Seventeen focused valuation/replay tests passed, including real-database API
persistence, parent immutability and zero order creation. These changes postdate
the earlier 1,073-test full regression.

## Stored quote observations

The platform's existing option-chain snapshots are nightly and cannot establish
intraday option fills. Cartel now has its own `options_cartel_quotes` table and
explicit authenticated capture/read operations at
`/api/options-cartel/runs/{planId}/option-quotes/{contract}`. POST records only an
already-cached quote for the matching owned plan; GET reads observations.
Provider time, local confirmation time and observation time remain distinct.
Missing source time, zero liquidity, delayed status and halted status are not
silently repaired. These are raw observations, not executable-price approvals.

Thirteen quote-storage/valuation tests passed, including idempotency, time
provenance, missing/wrong/future quote rejection and zero orders. Opt-in continuous
recording is now connected to active Cartel option plans, with one background
sample batch at a time and a five-second minimum interval. The desk shows the
saved recording setting and latest batch/errors. Shutdown cancels and awaits the
recorder; it never blocks entry/exit tasks. The isolated preview schema/runtime
were refreshed and recording remains off. Saved replays now offer Use stored
plan quotes. The loader reads only their parent plan's matching contract and
decision window, preserves observation IDs and rejects oversized windows rather
than silently truncating them. An empty window saves an incomplete valuation.

The most recently available observation controls each valuation time, including
unusable observations. Missing provider time, halted/delayed state, crossed prices
or zero liquidity cannot be skipped to reuse an older favorable quote. This
policy is recorded as valuation version 2; old saved results remain unchanged.
Twenty-one focused observation/valuation tests passed, including a matching-plan
valuation and isolation from a second plan for the same underlying/contract.
