# Automatic daily preparation

The Cartel desk prepares and arms options plans for the active workspace.
**Practice** uses the local sim account; **Live** uses an explicitly selected
live brokerage or broker-paper account. Each workspace has independent settings
and preparation results. Existing settings and records remain Practice-owned.
Under Settings, enable Daily preparation, choose the account, and save. Plans shows the daily
shortlist; Armed shows active execution and account risk. Scheduled jobs run at
20:20 and 08:45 ET on trading days. “Prepare now” on Plans starts
outside regular market hours. Preparation does not place an entry order;
the existing closed-bar entry controller executes qualifying armed plans.

Live starts disabled. It requires the preparation's live-execution and overnight
protection acknowledgements, the separate **Cartel live-auto permission**, Live
trading mode and a connected broker. The existing loss, instrument, quote and
order risk gates still apply. The permission control is explicitly labeled in
Live settings; saving a preparation policy never grants it implicitly. Phones
remain exit-only for enabling/running Live preparation under the existing policy.

Scheduled preparation and pending-contract retries use the active workspace at
dispatch. A mode change prevents an in-progress preparation from arming in its
former workspace, and prepared entries recheck workspace at submission. Existing
position management and exits continue. One preparation worker runs at a time;
requests for the other workspace are rejected rather than joining the wrong run.

The workflow discovers primary US stock/DR listings from TradingView's complete
paginated screener, using the selected Cartel price and capitalization floors.
It captures the publisher's complete US industry performance table directly.
SPY/QQQ alignment determines direction. Completed daily history supplies the
remaining listing, industry, relative-strength, daily and weekly setup gates.
Missing evidence blocks a candidate. A mixed market can legitimately produce
an empty shortlist.

Every supported price/capitalization-eligible listing is checked by default
(`scanAll=true`). A definite failure of the profile's required industry-ranking
gate is recorded before downloading history; unknown industry evidence is not
silently treated as a definite failure. Remaining names receive completed daily
history analysis. Discovery-volume order remains the documented shortlist priority.
Shortlist size (default five) never truncates universe evaluation. An optional
explicit resource cap (`scanAll=false`, `historyLimit`) remains available up to
10,000; older saved 200 limits apply only if the cap is enabled.

Each selected plan includes measured entry/stop geometry, target provenance,
same-time minute-volume history and an exit campaign. Chain data selects a draft
option expression; fresh execution quotes and Greeks, shared risk checks,
loss halts and write-ahead order handling still apply at entry. Missing contracts
are retried once a minute from 08:45 through the regular session while the
saved preparation evidence and current configuration remain valid.

## Explicit engineering defaults

- September 2026 screen and exit profile; closed 15-minute entry and gap retest.
- One-session entry window. Position management can continue for multiple days.
- Maximum premium 500 in account currency, capped again by the configured equity-risk percentage
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
unused automatic arms for the selected account before rebuilding. User-paused
plans, working submissions and held positions are preserved and count as
already managed. A failed refresh can leave no new arms; it does not restore an
obsolete shortlist. Disabling preparation stops its worker and future runs,
but does not disarm existing plans or close positions.

Requests coalesce into one worker. Progress and inputs persist in an owned
`TechniqueRun` with mode `preparation`, linked to analyses and plans. On restart,
interrupted runs are marked failed; existing arms restore through normal runtime
recovery. The next scheduled job or the Prepare now button starts a fresh preparation.
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

Settings storage: `techniques.options_cartel.preparation` retains Practice;
`techniques.options_cartel.preparation_live` holds Live. The preparation and run-list
APIs accept `workspace=practice|live`; preparation defaults to the active workspace
when omitted. Manual research remains shared; automatically prepared plans retain
their originating workspace. The same daily schedule dispatches only the active
workspace. Changing workspace does not cancel working orders or abandon positions.

## Progress, coverage and recovery (0.7.5)

Discovery reports received/total listings per page, then industry context, index
context, stock evaluation and option selection report their own operations.
Provider waits emit a heartbeat every ten seconds; normal UI polling is three
seconds while running. `processed` counts completed listing decisions;
`prefiltered` is definite industry rejection; `evaluated` counts completed history
analyses; `dataErrors` is separate. `notEvaluated` reports untouched listings and
`coverageComplete` requires all supported listings processed without data errors.
A cap or data failure yields partial coverage, not a claim that all candidates
were evaluated. Missing market alignment explicitly skips stock evaluation.

History calls are paced (default 0.25s minimum start interval), use the shared
provider's bounded retries and have an overall request deadline. Exhausted rate
limits stop the batch; three consecutive transport failures also stop it. The
worker owns and awaits cancellation of pending provider requests.

Saved completed daily history may be reused for twelve hours only when its
original observation precedes the new cutoff and its last session matches the
required completed session. Cache reuse retains the original observation and
source-run pointer; it does not make executable option quotes fresh. Minute
baselines are collected for shortlisted plans. Candidate queues retain IDs,
not every candidate's full bar arrays.

A failed/partial run with a complete discovery/industry snapshot may be resumed
for the same session, workspace and unchanged policy, within 24 hours. Resume
creates a linked run, preserves the original failed record and snapshot cutoff,
and reuses successful analyses. Children committed before a progress checkpoint
are recovered too. Discovery failures need a fresh run. New settings or expired
evidence require a fresh run. Existing arm/order checks prevent duplicate entries;
retired arms are not silently revived. Resume is an explicit action; startup marks
interrupted work and the UI offers Resume saved scan when eligible.

Contract diagnostics count the first failed filter per inspected row, record the
effective ask/debit ceiling and show provider errors separately. Search proceeds
through allowed expiries until an eligible nearest-DTE group is found or all
allowed dates are checked. No price, delta, liquidity or risk limits are relaxed.
The saved-plan table refreshes on published results/completion, and evidence rows
are paged to keep large runs usable on phones.

## Adjustable risk limit (0.7.8)

Equity at risk (%) on the technique Settings tab accepts values above zero
through 10 in both workspaces. New Practice configurations default to 10%; new
Live configurations default to 1%. Explicit saved percentages remain unchanged,
and the two workspaces retain independent values. Users with a saved 1% value
must change it and save to use 10%; deployment never silently raises it.

This is full option-premium allocation per setup, not a stop-loss estimate.
The separate premium budget still applies: on a hypothetical 10,000-equity book,
10% allows 1,000, but a 500 premium budget still caps the purchase at 500. Existing
contract-price/quantity limits, cash requirements, exposure and loss gates remain
in force. No change to Live acknowledgements or permission requirements.


## Mixed-market research (0.7.14)

Market alignment controls automatic arming separately from research coverage. If
SPY/QQQ are mixed or unknown, preparation still evaluates stock/setup evidence in
the configured research direction (bullish by default). Other stock, history,
industry and setup checks remain unchanged. Qualifying research candidates are
saved as analysis records with a market-blocked label, not executable plans.
No contract is selected and no arm/order is created. Pending activation explicitly
ignores these preparation snapshots; fresh preparation with aligned market evidence
is required before execution. Normal plan construction still rejects their failed
market screen, so manual plan creation cannot promote the saved research snapshot.

The Plans tab displays the completed-session date, close, EMA levels and alignment
for each index. Research-only candidate counts are distinct from executable setup
counts. A complete research run with a trading restriction is not an incomplete
scan; genuine data failures and optional-cap gaps remain visible. Historical runs
that skipped evaluation on a market block are no longer labeled as download failures.
A coverage-version change requires fresh preparation rather than resuming old scans.


## Bounded parallel history loading (0.7.16)

Settings expose a history batch window (default 25, range 1–50) and parallel fetches
(default 6, range 1–12). The batch window bounds queued/completed history buffers;
it is not a provider bulk endpoint or permission to send every request at once.
The shared provider's existing concurrency cap remains authoritative. Cartel's
request spacing is serialized across fetches (default 0.25 seconds, approximately
four request starts per second), so overlap removes response-wait serialization
without removing pacing. Cache hits bypass provider requests.

Only history reads overlap. The coordinator evaluates/persists in discovery order,
keeping shortlist ranking reproducible. Definite strict-industry exclusions and
resumed analyses do not prefetch. Checkpoint writes serialize to avoid stale progress
commits. Progress reports active fetches, prefetch completions and configured bounds.
Rate-limit exhaustion blocks new request starts; interruption cancels and awaits all
owned prefetch work. Already committed analyses remain resumable. At most the bounded
window of uncommitted histories needs fetching again after interruption.

An in-progress run is not hot-upgraded. Let it finish; deploy outside an active run
and use fresh preparation with the new version. Larger batches alone cannot bypass
the provider rate cap, and higher concurrency does not guarantee faster scans.


## Moderate Practice market experiment (0.7.18)

Strict remains the default. To opt in: select Practice, open Cartel Settings,
choose Market alignment = Moderate, save, and run fresh preparation outside regular
hours. Moderate uses completed daily 8/21/50 EMAs: bullish alignment needs at least
one index above all three and both indices strictly above their 50 EMA. An index
at/below its 50 EMA, missing/stale evidence, or neither index fully bullish does not
qualify for the bullish exception. Strict bearish alignment is unchanged. The
selected mode, effective direction, strict direction and measurements are saved.
This is an engineering Practice experiment, not an author-prescribed threshold.

Live preparation rejects Moderate configuration; arming and submission also reject
Moderate plans on Live/broker-paper books. Existing budgets, risk percentages,
contract constraints and entry checks are unchanged. Old research-only records
cannot be promoted; prepare new plans. Scheduled deduplication now compares policy
as well as session and age, so a changed policy is not skipped as already prepared.
Review results across sessions before considering further changes.
