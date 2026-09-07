# Focus-list scanning

The Cartel desk accepts up to 20 unique US equity symbols. A scan applies one
source profile, direction and fixed data cutoff to the whole list, using the
same collection and analysis functions as single-symbol research. At most two
symbol collections run concurrently. Each successful analysis is saved and can
be opened to review gates, candidates and targets before preparing a plan.

The parent scan record is created before collection and preserves the requested
universe, cutoff, supplied evidence and pending symbols. Each completed symbol
updates its analysis ID, failure or qualifying result under a row lock. Child
analyses also retain the parent ID, including when interruption happens between
analysis persistence and the parent progress update.
A provider failure leaves that symbol explicitly unavailable and preserves
successful siblings. No scan creates a plan, arms a signal or places orders.

The desk's candidate evidence applies only to its matching symbol. The API can
accept separate facts for every requested symbol. Missing facts are never
borrowed from another symbol or inferred from price bars. September industry
qualification still requires source-dated weekly and monthly ranks.

This is a user-selected universe. Broad universe discovery, historical industry
snapshots and walk-forward plan construction remain unfinished. Normal request
cancellation cancels and awaits outstanding symbol tasks, preserves completed
results and marks the parent interrupted. Startup reconciles running Cartel scan
rows without live local task handles, recovering uniquely matching completed
child analyses at the original cutoff. Complete result sets can finish; unresolved
symbols remain pending in an interrupted record. Other techniques and finished
scans are untouched. This uses the platform's single-engine-per-database invariant.
Finished/interrupted records offer Retry unresolved symbols: pending and failed
data collections run again at the original cutoff with the original evidence.
Completed analyses are retained and labeled; the retry is a new scan linked to
the original. The earlier record is unchanged. Missing old provider history can
still fail visibly. Running scans and scans with no unresolved symbols cannot
be retried. Manual scan/retry submissions now return HTTP 202 after the running
record is persisted. The selected scan polls progress until terminal status;
leaving the page does not cancel its worker. At most three manual background
scans run concurrently. Runtime shutdown cancels and awaits only those tracked
workers, preserving interrupted progress; it does not cancel the shared scheduler
task. Scheduled scans continue to await their results through the scheduler.
Browser submission and mobile acceptance of the new scan form remain pending.

Verification update (2026-09-07): the isolated preview was refreshed only after
verifying its owned process, sim configuration, blank integration credentials
and empty execution state. A Chrome submission for MU and HOOD completed via
the shared historical provider and saved scan `ccd63254d60243d79c71c88dd86bc65d`.
Both child analyses were watch-only with explicit missing market-cap/industry
evidence. Post-submission checks found zero orders, managed positions and active
arms. Provider retrieval is verified for this request, not all symbols/dates.

The desk passed all five mobile audit profiles after increasing the industry
source link's touch target to 44px in mobile.css. Production build passed. The
preview launcher PID is recorded in `.cache/cartel-preview.pid`; verify listener
ownership again before future restarts. No shared-runtime process was stopped.

## Scheduled work

Cartel runtime attachment registers three names on the shared scheduler:
`options_cartel_preopen_recovery` at 09:05 ET, `options_cartel_close_recovery`
at 20:10 ET and `options_cartel_nightly_scan` at 20:15 ET. Recovery and scanning
are separately opt-in and default off. The desk's schedule form saves the owned
symbol universe, profile/direction and switches through a validated endpoint.

The shared scheduler supplies its existing once-per-ET-day journal markers and
weekday behavior. A scan additionally skips exchange holidays. Disabled or empty
jobs return a status; enabling one after its daily tick does not rerun it that
day. Late startup uses the shared scheduler's existing catch-up timing. Jobs
report individual collection/recovery failures in their recorded results.

Runtime shutdown unregisters only these three Cartel jobs. Retained callbacks
return a stopping status, and recovery checks again after history-fetch I/O
before applying data. This does not cancel an unknown order outcome or stop
another technique's scheduled work.

Recovery considers only open Cartel positions using its own adapter, skips
residual positions and fetches completed underlying daily history. Conflicts
are rejected rather than overwriting persisted candles. Validated recovery may
prepare a catch-up batch which the position watch loop executes at current
prices. This can close held positions across accounts; it is not research-only.

Scheduled scans do not yet collect fundamental/industry snapshots, select an
entire-market universe or arm plans. Job progress and retry behavior follow the
shared scheduler; durable resumable per-symbol scan jobs remain unfinished.
The schedule form and its runtime attachment still need browser/mobile acceptance.

Schedule status now loads each Cartel job's latest persisted success/failure
event, including partial per-position recovery outcomes. The desk displays these
results instead of relying only on resettable in-memory failure counters. A
completed scheduler invocation can therefore visibly retain unavailable data or
catch-up review requirements after restart. API tests and frontend builds must
run sequentially when test app construction uses frontend/dist: Vite replaces
its assets directory during a build.

Schedule UI acceptance (2026-09-07): after verifying sim configuration, blank
integration keys and zero orders/positions/active arms, only the owned Codex
preview was refreshed. Chrome displayed all three registered jobs; Save schedule
preserved `scanEnabled=false`, `recoveryEnabled=false` and an empty symbol list.
The expanded schedule form passed all five mobile audit profiles. Actual timed
execution with enabled jobs and populated outcomes remains an operational gate;
the verification did not enable recovery or scans. Current preview launcher
identity remains recorded in `.cache/cartel-preview.pid`.
