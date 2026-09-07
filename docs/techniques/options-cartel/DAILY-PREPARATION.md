# Automatic daily preparation

The Cartel desk can prepare and arm options plans for a local **Practice (sim)**
portfolio. Broker paper and live portfolios are rejected. On the desk, enable
Daily preparation, choose the Practice account, and save. Scheduled jobs run at
20:20 and 08:45 ET on trading days. “Save and prepare next session now” starts
outside regular market hours. Preparation does not place an entry order;
the existing closed-bar entry controller executes qualifying armed plans.

The workflow discovers primary US stock/DR listings from TradingView's complete
paginated screener, using the selected Cartel price and capitalization floors.
It captures the publisher's complete US industry performance table directly.
SPY/QQQ alignment determines direction. Completed daily history supplies the
remaining listing, industry, relative-strength, daily and weekly setup gates.
Missing evidence blocks a candidate. A mixed market can legitimately produce
an empty shortlist.

Detailed history is evaluated in descending listing-volume order, with an
explicit default budget of 200 symbols. Discovery is broader than this budget;
the result records the count not evaluated. Default shortlist size is five.
Each selected plan includes measured entry/stop geometry, target provenance,
same-time minute-volume history and an exit campaign. Chain data selects a draft
option expression; fresh execution quotes and Greeks, shared risk checks,
loss halts and write-ahead order handling still apply at entry. Missing contracts
are retried once a minute from 08:45 through the regular session while the
saved preparation evidence and current configuration remain valid.

## Explicit engineering defaults

- September 2026 screen and exit profile; closed 15-minute entry and gap retest.
- One-session entry window. Position management can continue for multiple days.
- Maximum premium 500 in account currency, capped again by 1% of current equity
  using **full premium debit** as risk, and at most ten contracts.
- Draft options: 21–90 DTE, target 45 DTE, target absolute delta 0.5,
  minimum absolute delta 0.25, maximum ask $5, spread 20%, open interest 100.
- September exit allocations: 25%, 25%, 20%, 20%, 10%.
- Confirmed historical pivot targets first. If absent, optional engineering
  Fibonacci anchors use the directional extreme of up to 60 completed sessions
  preceding the measured base, to the trigger; extensions 1.272/1.618/2.0.

These allocations, contract preferences and automatic anchor selection are
configuration choices, not claims about exact author instructions. The typed
configuration API exposes the full policy; the desk exposes routine controls.
Manual research and source-version tools remain available separately.

## Freshness, refresh and recovery

The industry adapter consumes published performance directly; it does not
reconstruct constituent weights. The publication lacks constituent timestamps.
Its explicit `publisher_observation` policy ages context from receipt for at
most 24 hours while leaving `dataAsOfMs` unknown. Manual/provider-time snapshots
retain their existing missing-time rejection. This policy never makes delayed
stock or option prices executable.

Automatic arms expire for new entries no later than 24 hours after preparation
or the plan's last-session close, whichever comes first. Each fresh run disarms
unused automatic arms for that Practice account before rebuilding. User-paused
plans, working submissions and held positions are preserved and count as
already managed. A failed refresh can leave no new arms; it does not restore an
obsolete shortlist. Disabling preparation stops its worker and future runs,
but does not disarm existing plans or close positions.

Requests coalesce into one worker. Progress and inputs persist in an owned
`TechniqueRun` with mode `preparation`, linked to analyses and plans. On restart,
interrupted runs are marked failed; existing arms restore through normal runtime
recovery. The next scheduled job or the desk button starts a fresh preparation.
The daily scheduler records job dispatch separately from preparation completion.

## Data verification

On September 7, 2026 the read-only adapter retrieved 3,089/3,089 listings
(3,088 supported, one explicitly excluded) and 129/129 published industries.
These are observations, not permanent universe-size assumptions. Partial pages,
duplicate identities, changing totals and unexpected industry update modes fail
closed. Provider availability can prevent completion and appears in the run.

Implementation: `discovery.py`, `industry_feed.py`, `automatic_plans.py`,
`preparation.py`; authenticated `/api/options-cartel/preparation` status,
`/preparation/config` settings and `/preparation/run` submission.
