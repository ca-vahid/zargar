# Platform rules — what holds for every technique

*The shared judgement log. Started 2026-08-27 when the app became a multi-technique platform
(`TECHNIQUE-PLATFORM-PLAN.md`). A technique's own log lives in `docs/techniques/<id>/TRADING-RULES.md`
(EM: `techniques/enhanced-market/TRADING-RULES.md`, numbering unchanged). Every entry here cites the
technique run that taught it; every new technique reads this file before its first live day.*

How to use it: §1 are invariants — a change to one is a design change, not a tuning. §2 are settled
findings with evidence. §3 are open questions the shared runtime is collecting data on. §4 is the
change log of **shared** knobs (today `technique.arm.*` / `feed.*` / `risk.*`; phase 3 renames the
runtime ones to `execution.*`).

## 1. Invariants (the runner core is deliberately un-hookable here)

1. **Every order goes through `OrderManager.place()` → `RiskGate.evaluate()`.** No technique gets
   another path; the kill switch is honoured before any submission. Exits are **reduce-only** and a
   halt, a cap or the rate window can never trap them (`risk.halt_allows_exits`).
2. **Journal every decision** (`events`, append-only). **Hooks do not journal** — the runner journals
   hook *results*, so the event shapes (`TECHNIQUE_PLAN_*`) stay uniform and the review tooling
   (audits, CLI, day panels) keeps working for every technique.
3. **Money paths are write-ahead**: the intent is persisted before routing; an unknown outcome is
   reconciled against the venue, never resubmitted blindly.
4. **One tracker for live / plan / sweep** (`marketstructure.tracker.TriggerTracker`, parameterised by
   `MarketRules`) with parity tests — sweep rows equal promoted runs, live equals replay.
5. **The live-persisted record beats replay on restore** (`replay_divergence` / `phantom_dropped`;
   pre-seed state snapshot). Replay rebuilds state; it is not truth.
6. **Backend restarts only mid-day or after the close**, never inside a prime window; `start.ps1`
   refuses while runs are in flight. (A 15:53 ET restart on 08-26 was a violation — logged so it is
   not repeated.)
7. **R6.5 stays runner-core:** no technique can opt into pre/after-market *entries* by forgetting a
   hook — `in_session` gating in `_on_bar` is not a hook. Exits keep working on quotes at any time.
8. **Sub-minute is for exits only.** Entries confirm on the closed bar of the trigger timeframe
   (there is no history to validate sub-minute entries); the quote stop watch and the premium stop
   may be fast *because* reduce-only cannot hurt.
9. **Gap rules are judged on the session's opening bar only** (`gap_unchecked` otherwise); a plan
   armed after the open completes its opening bars from history first (`_complete_opening_bars`).
10. **Auto mode never runs without a loss halt** (`_ensure_loss_halt`; fallback
    `technique.arm.daily_loss_fallback`, alerted loudly).
11. **Every method change is logged** under the technique's own heading; every shared change here.
12. **Technique knowledge stores are per-technique** (2026-08-30, user requirement): `tip_notes`
    belongs to the tips desk only; EM's rulebook/prompts/chart-read knowledge belongs to EM only.
    No cross-injection, no cross-reads, ever — changing one analyst's knowledge must never affect
    the other. Enforced by `tests/test_platform_separation.py` (static source scan, both
    directions). Shared *mechanics* (LLM client, plan dataclasses, option picking, market data)
    stay shared; *knowledge* never does.
13. **Out-of-band experiments never touch money or scores** (2026-08-30): a signal tagged
    `extraction.experiment` is FORCED onto the replayed path (no books, no proposals, no arming),
    skips dedupe in both directions and is excluded from source scorecards — evidence for review
    only (`signals.service.experiment_tag`, KNOWLEDGE plan §E).
14. **Money is never priced on a delayed quote** (2026-09-02, the GOOGL 340C audit). Every
    `Quote` carries `source`/`source_ts`; a chain-sourced (~15-min-delayed) option quote is a
    *width and a fallback*, never a level: with a real-time source configured (`options.
    quotes_source=alpaca` + keys) `RiskGate.quote_fresh` fails CLOSED on it for entries, the
    premium tick-watch ignores it, an armed plan never market-sells on its `bid=0`, and picks
    are re-priced on the NBBO (`OptionsService.reprice`) before sizing, limits or the
    never-chase rule read them. Exits stay reduce-only and never wait on a quote. The UI
    badges any contract priced off the chain as `delayed` on every money screen.
15. **One Practice book per technique** (2026-09-08, user decision): `techniques.<id>.default_portfolio` routes each
    technique's fills; the old shared Practice book is archived and never a fallback (detail in the 2026-09-08 change-log entry).
16. **A recomputed read never re-acts** (2026-09-08): a technique that recomputes its whole session read every bar
    recognises acted-on events by content fingerprint, logs `read_rewritten` once when history moves, and captures
    point-in-time inputs (IV) on the plan + run so replay uses the stamped value (detail in the 2026-09-08 entry).
17. **The shared `bars` table holds market data only, with provenance** (F75, 2026-09-09). Every row carries
   `source` (exchange | sampled | sim | unknown); writes go through `persist_bars`, which drops bars outside a
   market minute, refuses `sim` rows unless the caller allows them (tests), and upserts by precedence
   (exchange > sampled | unknown > sim; exchange refreshes exchange). A consumer that reads history for a decision
   validates sessions (Team2: `techniques/team2/history.py`) and cites a CONTENT-hash dataset version
   (`marketdata.dataset_version`). Suspect rows are quarantined with the originals preserved
   (`bars_quarantine`), never deleted outright; flatness flags, an operator classifies.
18. **Every restart goes through one door** (2026-09-09). `scripts/restart.ps1` (and `start.ps1` under it) asks `/api/ops/restart-check`
   what a restart would interrupt across EVERY technique (open trades, working entries/exits, venue orders IN
   FLIGHT, analyst reads) and refuses unless `-Force`; RESTING venue orders (durable-position stops, resting limits)
   never block - the sim book and a live venue keep them - but must be found again by id afterwards; after a detached restart it compares armed plans, open trades,
   pending exits and resting/in-flight orders BY ID with the state before (restoration check, `logs/restore-mismatch-*.json`
   on a mismatch). Assistants restart via the scheduler's `ZargarRestart` task (same door, same refusal);
   `ZargarRestartOverride` (= `restart.ps1 -Force`) exists for emergencies and is logged as an override. Task
   scripts are ASCII (Windows PowerShell 5.1). "No open positions" is not a restart test.

## 2. Findings (settled, with evidence)

### technique_outcomes.plan_source widened 24 → 48 — 2026-09-08

`score_run` on a tip-triggered plan writes `plan_source="trigger:tip-<12hex>-<n>"`
(26+ chars) and every insert failed StringDataRightTruncation, retrying at each
startup (user-visible startup error, run b1ddda0b). Column widened in models.py
AND `ALTER TABLE technique_outcomes ALTER COLUMN plan_source TYPE varchar(48)`
applied manually to the live DB (create_all never widens). Any desk creating a
fresh DB gets 48 from the model.

### Deploys must wait for health: scripts\restart.ps1 — 2026-09-08

Three market-hours outages in three sessions (09-04 ×2, 09-08 14:24–14:35 ET)
were deploys that stopped the app and walked away before it answered again; a
dead app manages no exits. Separately, intake windows stacked 9 deep because an
unelevated restart cannot stop elevated windows (silent access-denied).
`scripts\restart.ps1` is the one deploy path for EVERY desk: stop (reporting
what it could not kill), start.ps1 -Detach, then BLOCK on /api/health (exit 4
if it never answers, exit 5 on version mismatch with -Expect). Do not hand-roll
stop/start in session recipes any more.

### Cartel dedicated Practice-book compatibility — 2026-09-08 reset

Cartel consumes `techniques.options_cartel.default_portfolio` as its authoritative
Practice destination, including when preparation retained a legacy shared-book
selection. A configured missing/archived book never falls back to another book.
Arming and entry validation enforce this boundary; archived-book arms are not
restored. Live accounts remain separately selected. This consumes the reset's
per-technique/archival contract without merging another desk's implementation.
See [dedicated-book integration](techniques/options-cartel/DEDICATED-BOOK.md).

### Cartel preparation coverage/recovery — 2026-09-07

Preparation completion must distinguish successful checks, definite early
rejections, data failures and unprocessed listings. Its optional resource cap
does not limit default market coverage or relax trading gates. Recovery reuses
the original snapshot only within its validity window and unchanged policy;
it creates a linked run and preserves completed records. Cached history retains
its original observation and cannot establish executable quote freshness.
See [preparation review](techniques/options-cartel/PREPARATION-REVIEW.md).

### Cartel preparation workspace separation — 2026-09-07

User requirement: Practice and Live preparation have separate settings, account
selection and results. Legacy preparation settings/records belong to Practice;
the new Live policy starts disabled. Scheduled dispatch follows `trading.mode`,
and automatic prepared entries recheck workspace, account kind and existing
live permissions before submission. Switching workspace never turns a Practice
plan into a live plan. Held-position protection remains independent of the view.
Tests: `test_options_cartel_preparation_workspaces.py` and scoped API tests.
This extends the earlier Practice-only preparation boundary below.

### 2026-09-07 — Cartel automatic Practice preparation

Cartel owns its discovery/review policy and schedules preparation separately from
shared execution. Preparation may arm only `sim` portfolios, with auto mode and
live permission false; existing risk, closed-bar entry, write-ahead submission
and position protection remain mandatory. Its context snapshot receipt-time
policy does not relax executable quote freshness. Only unused automatic plans
are replaced on refresh; working orders, user-paused plans and held positions
are preserved. See [daily preparation](techniques/options-cartel/DAILY-PREPARATION.md)
and `test_options_cartel_preparation.py` for lifecycle evidence.

- **2026-09-07 · Cartel's money runtime uses independent fire and reconciliation
  tasks.** Order DTOs now include technique/tags, and SessionListener has an
  overridable order-interest predicate (the default remains its existing id index).
  This lets Cartel observe an order before its submission response returns.
  The controller releases its reservation mutex before broker I/O; partial fills
  can be protected while that I/O is pending. Caller cancellation does not cancel
  the background order task. Disarm cancels pending entry exposure but preserves
  managed exits; explicit flatten persists its intent across late fills/restart.
  Cartel publishes a display-only trigger projection for the shared Armed page,
  including its own confirmation wording and durable-management metadata. The
  shared UI does not substitute EM's timing/flatten wording for those fields.
  Unknown distances/marks render as unavailable. Other runners retain their prior
  order-interest and execution behavior. Tests: `test_options_cartel_runtime.py`.

- **2026-09-07 · Prior-risk-mark recovery preserves data and source identity.**
  Cartel recovery inserts only missing daily bars for the requested completed
  exchange session; a concurrent insert wins without being overwritten. Source
  compatibility is per symbol, not per connection: real OPRA contracts may coexist
  with a simulated stock feed, but simulated marks are not replaced with real
  historical prices. `TechniqueCartelRiskMarksRecovered` is a version-1 audit event
  covering the portfolio, session, source, recovered/preserved symbols and gaps.
  A copied quote snapshot keeps risk reports tied to their requested cutoff while
  historical data is fetched; the entry path separately refreshes its clock.

- **2026-09-07 · Daily technique P&L must not count prior-day gains again.** Cartel
  uses today's execution cash flows and recorded fees, plus current marked value,
  minus carried inventory at the preceding session's close. Option marks belong
  to the contract, with the 100x multiplier. Incomplete execution totals/costs,
  missing marks or inventory mismatches make the report unavailable, not zero.
  Its optional day-loss guard compares this price/fee P&L at current FX against
  current book equity and latches an observed breach in a versioned
  `TechniqueCartelLossHalt` event. FX translation remains outside this technique
  attribution; the book loss guard remains independent. OrderManager now preserves
  `ExecReport.ts` in Execution.ts rather than replacing it with database receipt
  time. Adapters that supply only receipt time still need venue-time normalization
  for exact broker-day attribution. Existing records are not rewritten.

- **2026-09-06 · Entry identity must distinguish entry orders from their descendants.**
  Cartel exit orders retain entry-lineage tags. A tag-only association therefore
  sees both the BUY and its SELL exits. Cartel entry recovery/readiness now matches
  the owned BUY; duplicate BUY submissions remain ambiguous. Its read-only readiness
  gate uses persisted order/position evidence, scoped to the book and underlying,
  to block new Cartel exposure until statuses, fills and costs agree. It installs
  no global halt and leaves protective exit routing independent. Other techniques'
  entry policies and knowledge are unchanged. Evidence: `test_options_cartel_readiness.py`.

- **2026-09-06 · Cartel primary exits wait for verified cancellation.** The opt-in
  adapter now owns a persisted close request and applies actual cumulative fills
  before replacing a venue stop or submitting a forced close. Working profit
  orders and venue stops share the held-quantity budget. Its pending quantity
  does not disappear on an arbitrary TTL or an unknown submission error.
  PositionManager supplies a common `_submit_exit` write-ahead/RiskGate route for
  the adapter's stop and ordinary exits, passes close arguments to its adapter,
  and lets that adapter handle bounded retries. Non-adapter policies retain their
  existing cancellation path. `ManagedPositionExitCancellationRequested` is a
  registered version-1 event with position, symbol, order id and attempt number.
  Cartel-specific tests cover optimistic cancellation responses, cancellation-time
  fills, stop resizing, shared exit quantity, lost responses, restart and rejected
  stop retry limits. This does not authorize interactive or live activation.

- **2026-09-06 · Residual exits reconcile their write-ahead attempts.** Adapter
  exits now persist an attempt tag and exact intent before `OrderManager.place`.
  Optional adapter close/watch hooks let Cartel residual positions reconcile
  that tag to the actual order before retrying. The manager remains the sole
  order router via `_close_leg` and RiskGate. Unknown outcomes and still-working
  orders never become retry permission merely because the generic exit TTL
  elapsed; only confirmed terminal attempts retry, at 30-second intervals with
  a five-attempt cap. Original campaigns and their pending exits are unchanged
  when a separately attributed late-fill residual is closed. No other policy
  opts into these hooks. Evidence: `test_options_cartel_residuals.py`, including
  lost responses, restart, a terminal cancelled order with fills, and an unknown
  submission through both manual close and the quote-watch path.

- **2026-09-06 · Opt-in position adapters serialize mutable fill state.** Cartel's
  provisional partial-entry protection can receive another entry fill while an
  exit callback is persisting. `execution.serialization` supplies a per-position
  reentrant guard for adapter policies; PositionManager persistence, close,
  venue-stop maintenance, minute decisions and order updates use it. Nested
  immediate fills remain legal; unrelated callbacks wait. Cartel quantity
  reconciliation and history recovery take the same guard. Policies without an
  adapter retain their existing path. Evidence: Cartel's concurrent entry-growth
  / exit-fill test pauses persistence, delivers an exit, then verifies the
  persisted remaining quantity and campaign accounting. This is serialization,
  not proof of venue cancellation acknowledgement or complete partial-entry
  recovery; those remain Cartel activation requirements.

- **2026-08-30 · A quote source must be judged per SYMBOL, never per connection.**
  The hybrid feed demoted Yahoo to context whenever the Alpaca socket was up and the
  symbol was subscribed — but a subscribed name that never PRINTS (weekend, halted,
  never traded since boot) then has no quote at all, and every consumer (blotter,
  equity, drift check) silently falls back to avg cost: TQQQ showed −0.00% unrealized
  all of 2026-08-30 while the broker said +122%. Fix: `AlpacaQuoteFeed.streaming(sym)`
  (a print within 120s) gates the demotion, and `sync_portfolio_state` now carries the
  broker's own mark as the no-quote fallback (`pos["mark"]`, quote → mark → avg cost).
  Tests: `test_snaptrade_sync.py::test_broker_mark_prices_positions_without_quotes`,
  `::test_alpaca_streaming_is_per_symbol`.

- **2026-08-25 · Data quality reaches into every layer** (EM ZS phantom touch, GOLD). Yahoo 429
  throttling caused 180 s bar stalls, a phantom touch, volume reading 0.0× at fire time and late
  fires. Fixed by Alpaca full-SIP streaming + Alpaca-first history; Yahoo is the visible fallback
  (`data: fallback` pill, `FeedDegraded` / `FeedRecovered` journal events). **Volume gates require
  the consolidated tape — never run a volume-gated technique on an IEX-only feed.** 08-26: the SIP
  entitlement lapsed for 45 min; the stream re-authenticates by itself when it returns.
- **2026-08-25 · Restart recovery must never rewrite live history** (GOLD phantom fire). See
  invariant 5; the fix is the pre-seed state snapshot and the divergence events.
- **2026-08-26 · Live 1m bars need the exchange bar** (EM A7). The sampled bar is held ~5 s for the
  Alpaca exchange bar (`feed.exchange_bar_hold_seconds`); consumers get one bar per minute,
  `source: exchange` when corrected. The 5 s is deliberate latency.
- **2026-08-26 · The fire chain runs off the bar loop** (EM A8). A slow reviewer must never delay
  another plan's stop: the trade is minted synchronously, the chain is a task, the chain re-checks
  the plan is still armed before sending, and disarm waits for in-flight chains (never cancels
  mid-order).
- **2026-08-26 · A reviewer fails OPEN, loudly, with a budget** (EM A8; the original developer's
  condition). Timeout (`technique.arm.critic_timeout_seconds`) + per-day failure budget
  (`critic_fail_budget`) → the failure that exhausts it sends nothing and pauses the plan. Veto
  cooldown and the kill cap are runner behaviour (`refire_cooldown_minutes`, `critic_kills_per_day`).
- **2026-08-26 · An expression can fall back** (EM 1.6; SNOW +1.89R untaken to a spread skip). When
  the preferred vehicle is blocked (wide spread / elevated IV / no contract / premium caps) the
  runner may express the same idea in shares (`entry_fallback`), never for a short.
- **2026-08-26 · Silent no-halt is a bug class** (36/37 auto plans without a loss halt). Any
  protection that can silently not apply must alert and badge (`needsAttention`), not log.
- **2026-08-27 · Touches are in-band; a pre-entry close through the stop invalidates** (EM, LITE b1
  10× phantom fires, MSTR mirror). A long bounce "touched" whenever price was anywhere below the
  level and refired every cooldown at a fantasy fill. Now: a touch is a bar whose extreme reaches the
  band *and* whose close holds; `bar.close` through the stop before entry is terminal
  (`invalidated`). A `bar.close < stop` comparison must never be the reviewer's job.
- **2026-08-27 · The vetting layer must be auditable by replay** (EM include-invalid sweep). Every
  gate that removes a trigger must be replayable with the gate off, so the gate's own value is
  measurable (the counterfactual). Post-extraction check for every runner change.
- **2026-08-27 · The fill can never be better than the level** (fill ≥ level guard in the tracker
  for breaks; mirrored for shorts).
- **2026-08-29 · Every PlanRunner must register in `engine.plan_runners`** (the phantom armed tip).
  The armed HUB — `/api/technique/armed` + summary/detail/exit/mode/pause/resume/stop-all, the
  `/api/health` restart-guard count — aggregates `engine.plan_runners`; the WS deltas already come
  from every runner (`PlanRunner._publish`). The tip runner wasn't registered, so its armed plan
  arrived by WS and was erased by every REST refresh: the Armed badge said 1 while the page said 0,
  and a restart guard would not have counted it. A new technique's attach function must register
  its runner in `engine.plan_runners` (and `engine.techniques`, where a runner is its own `.armer`)
  or its plans are invisible to the hub and unprotected across restarts.
- **2026-08-31 · Exits must be idempotent under re-delivered bars and slow fills** (AAPL +4 → −4
  naked short, Practice sim, first live-market Monday). The ~5 s exchange-corrected 1m bar re-closed
  a 5m window while the time-stop's SELL was still unfilled (sim fill ~68 s); `on_minute_bar`'s
  stale-tf fallback re-ran the policy and a second full-size reduce-only SELL flipped the position
  past flat — reduce-only checks the *current* qty, and both orders were submitted before either
  filled. Fix in `PositionManager`: (a) a raw-bar-ts decide dedupe per position (a re-delivered
  minute never re-runs the policy); (b) leg-level in-flight exit accounting — total outstanding
  exits never exceed the leg, later ladder rungs stay legal, an unfilled record past
  `execution.exit_inflight_ttl_seconds` (900) stops suppressing so a zombie order can't block
  getting flat; (c) a `force_market` stop cancels resting exits first and supersedes them. Chaos
  test `test_redelivered_bar_and_slow_fill_never_double_exit`. Any future exit path MUST go through
  `_close_leg` to inherit the accounting.

- **2026-09-01 · The duplicate-order guard was DEAD for three days** (found by its own
  test while building POST-SOAK). The 2026-08-29 per-portfolio keying changed the check's
  key but not `note_submission`'s — the two never matched, so nothing was ever a
  duplicate. Un-breaking it exposed two follow-on truths, now code: **a terminally
  REJECTED order is not exposure** — it frees its duplicate-window slot
  (`RiskGate.forget_submission`, wired into the REJECTED transitions) so deliberate
  resubmits (spread-fallback legs, watchdog retries) pass; and **a failed native-mleg
  submit must REJECT its leg rows**, not strand them SUBMITTED (they blocked the
  sequencing fallback's identical long leg). Lesson: when a guard's key changes, grep
  BOTH sides of the key — and a safety check whose test is failing is a siren, not noise.
- **2026-09-01 · The close is bar-driven with a 16:05 clock fallback — and it works**
  (POST-SOAK 1.1 forensics): 08-31 processed 45 expiries + 2 multi-day rolls at
  16:00:00 ET exactly. Residual gap: a restart inside the close window skips both
  triggers — covered by `PlanRunner.roll_stale()` + the 09:00 `roll_watchdog` job
  (loops across weekend gaps; alerts what it rescues). Boot-roll still covers restores.
- **2026-09-01 · Intake recovery: every drop is either correct or retried**
  (`signals.recovery_sweep`, POST-SOAK Phase 4): cold-quote parks re-verify when the
  feed warms (promotions NEVER self-approve from the sweep — the fail-closed and
  earned-auto gates live in intake); error content retries exactly once, meta-marked
  BEFORE the attempt so it can never loop.

- **2026-09-01 · "Never hold to expiry" means never THROUGH the close of expiry day** (the
  tips lotto lane, user decision). The DTE floor (`execution.min_dte`, close at DTE ≤ N) stays
  the platform default for every policy. A policy that declares `expiry_day_flatten_et`
  (tips: `techniques.tip.lotto_flatten_et`, 15:45) may hold INTO expiry day and is flattened
  at that time by the bar-driven decision AND a clock-driven net in the manager's quote
  watch (`kind: dte`). Per-position, opt-in, journaled — EM's behaviour is unchanged.
  Evidence: on the first live day the policy killed every 1–3 DTE tip from two sources
  whose whole style is short-dated, while their own boards printed +18/+26/+31 %.
- **2026-09-01 · Arming a plan whose last session has closed is now REFUSED at the runner.**
  A finished analyst batch stayed on screen after the close; "Arm 22 confirmed" armed 22
  runs built for the session that had just ended. The runner did expire them within
  seconds (no exposure), but that cost 44 journal events, a restore wave, and an Armed
  page reading "Live 26" against a badge of 4. `PlanRunner.arm()` now rejects a plan
  whose `expiresSession` is before the next tradeable session (same arithmetic as
  `restore()`, "now" from the test-pinnable clock) with a ValueError the API surfaces
  as 400; `restore()` is never gated. Escape hatch `execution.arm_expired_plans`
  (replays/tests; the EM rigs set it because their synthetic market ends days ago).
  UI: the batch panel marks such runs `expired`; the Armed page's Live list counts
  armed/paused only.

- **2026-09-02 · A restart orphaned a working entry: three recovery gaps, closed.** NOW r1
  fired 09:31, the sim BUY LMT was ACCEPTED; the server restarted at 10:04. After
  restore the trade was `working` with (1) `fire_bar_index=None`, so the "entry window
  elapsed - do not chase" cancel never ran; (2) the contract's quote stream gone (Yahoo
  had polled it once, nothing re-watched it), so nothing could fill it; (3) the sim
  executor's book empty, so `OrderManager.cancel` found nothing to cancel and returned
  the order unchanged - ACCEPTED forever, plan "in trade" on a phantom, its other
  trigger blocked. Fixes: the entry-window check falls back to wall-clock minutes since
  the fire; restore re-watches each working/open trade's order symbol; `SimExecutor.cancel`
  returns whether it held the order and the manager transitions unheld open orders to
  CANCELLED with a reason. Ops workaround until deployed: disarm + re-arm the plan.
  Fourth gap, found the same afternoon: the sim executor's book is in-memory, so a restart
  silently dropped EVERY resting sim order - protective stops on tip shadow shares (GOOGL, MU),
  bracket exits, and three market buys that had never filled. `OrderManager.restore_sim_book()`
  now runs at engine start: resting stops/limits/brackets go back into the book without a new
  'accepted' event; market orders still open after 60 s are cancelled ("lost in a restart, not
  chased") rather than filled at whatever prints next. Journaled as `SimBookRestored`.

- **2026-09-02 · Counterfactual ledger for bug-missed trades (user decision).** When a
  bug costs a trade, the fired order is replayed AFTER the fix through the runner's own
  exit rules on the real 1m bars (underlying for stop/targets, the contract's prints for
  fill/exit prices) and recorded in `technique_counterfactuals` + a `TechniqueCounterfactual`
  event (`execution/counterfactual.py`; `POST /api/technique/runs/{id}/counterfactual`;
  CLI `technique_review counterfactual`). INVARIANT: a counterfactual is never a fill in
  any portfolio - Practice/live books stay what actually happened, so the execution
  scorecard, the daily-loss halt and practice-to-live graduation are never contaminated.
  The Armed page shows the ledger apart from the real results ("Missed by a bug").

- **2026-09-02 · A restart also left a MANAGED position's stop blind.** The RKLB tip position
  (stop 59.80 on the underlying, premium stop 55 %) was restored at 11:1x but nothing
  re-subscribed `RKLB` — `quotes.get("RKLB")` was None and its last 15m bar was 10:59, so the
  bar-close stop and the 0.25R quote crash-brake could not fire (only the premium stop, fed by
  the contract's own Yahoo poll, still worked). The same hole existed on `adopt()`: a
  position adopted from a fill relied on whoever placed the order having watched the
  underlying. Fix: `PositionManager.adopt()` and `restore()` call `engine.ensure_symbol` for
  the underlying AND every leg (chaos test `test_restore_and_adopt_resubscribe_the_underlying`).
  Rule: any component that judges an exit on a symbol's bars/quotes owns that symbol's
  subscription — never assume the entry path left it watched.

- **2026-09-02 · A contract the live feed never prints is unfillable in practice.** eva's
  MU/AAPL/TSLA 14-Sep calls (a real Monday expiry, OI 39) were bought by the research
  book at 09:21 as MKT orders; Yahoo served no prints for them, and `OptionsService._apply`
  published the chain quote exactly once (at `track()`, before the order existed) then only
  refreshed the overlay — the sim's post-latency fill never saw a print and the orders sat
  2 h until the sim-book restore cancelled them. Fix: when the feed has been quiet on a
  tracked contract for `FEED_QUIET_SECONDS` (60), each refresh publishes the chain quote as
  a fresh print (fills, premium stop and the risk gate's freshness clock all run on it).
  Test: `test_options_service.py::test_quiet_feed_republishes_the_chain_quote`.

- **2026-09-02 · A delayed chain band must never price a practice fill when the tape has moved.**
  GOOGL 0DTE 340C: the live tape printed 0.47–0.76 at 12:00–12:05 while the ~15-min-delayed
  CBOE overlay still said 0.12/0.13; the practice book "bought" 20 at 0.13 (`quote_fresh` passed —
  the overlay re-stamps `ts`), the position showed +230 % on a fantasy basis and the 50 %
  premium stop, measured from 0.13, could never fire while the contract fell from a REAL 0.55
  to 0.22. Fix: `QuoteCache` keeps the chain's own last trade as the overlay's anchor; a live
  print outside the band that differs from that anchor re-centres the band on the print with
  the chain's spread width (`_apply_overlay`). Rule: bid/ask from a delayed source are a
  *width*, not a *level*, once the tape has printed past them. Test:
  `test_options_service.py::test_contract_quote_is_published_and_overlaid`.

- **2026-09-02 · The delayed chain was the root of a CLASS of gaps, not one bad fill** (user
  question "why CBOE when we pay for Alpaca?"; probe: Algo Trader Plus serves OPRA — NBBO
  ~1 s old, snapshots with greeks/IV). The options layer was built 2026-08-21 on CBOE; Alpaca
  arrived 08-25 for stocks and options were never rewired. Audit of every consumer (ranked):
  (1) `quote_fresh` blind — `set_overlay` re-stamped `ts` on every delayed refresh, so the
  gate, the premium tick-watch, the armed-plan premium stop and the "premium stop is blind"
  alert could never see a 15-min-old quote; (2) every dollar cap (per-order premium, %-equity,
  notional, gross, day) computed on the delayed mid — under-counting by the delay ratio (4.6×
  on GOOGL); (3) sim fills on the delayed ask, corrupting the books that EARN live auto;
  (4) armed plans market-sold on a stale `bid=0` (thin contract, delayed row = "nobody's
  paying"); (5) sizing + entry limit read the PICK's delayed ask (a $1,500 budget / 0.13 =
  115 contracts); (6) premium stop/trim on a delayed mark; (7) `skip_wide_spread` /
  `skip_elevated_iv` hard gates on 15-min-old spread/IV; (8) proposals skip `ensure_symbol`
  and "improve" the limit from a stale ask → approved orders that cannot fill; (9) shadow books
  sized on the delayed ask, filled on real quotes (biased trust bar); (10–15) exit limits at a
  delayed bid, plan loss-halt on delayed marks, equity/ledger `riding`/`unexplained` absorbing
  the delay, no `delayed` badge outside the chain screens, expiry settlement at a delayed spot.
  Clean: counterfactual ledger, tip replay, outcome scoring (contract 1m bars), Flow + nightly
  OI snapshots (post-close). **Built the same day:** `AlpacaOptionsData` (OPRA quotes/trades,
  `options.quotes_source`), `OptionsService._refresh_live` (2 s batch, overlay + whole quote,
  `served_live`, 60 s back-off on refusal), `Quote.source/source_ts` + `QuoteCache.
  source_age_seconds`, `quote_fresh` fail-closed (invariant 14), `reprice()` after every pick
  (EM armer, tip runner, shadow books), `_live_ask` for proposals/approvals, the `bid=0`
  hardening, premium tick-watch requires a real-time print, `LivePrice` badge. **Still open
  (chain path):** (7) the T5.3/T5.4 skip gates still judge the chain's spread/IV at pick time
  (re-evaluate on the NBBO after `reprice`); chain browser/greeks/OI stay CBOE until the Alpaca
  snapshots provider (phase 2: `/v1beta1/options/snapshots/{underlying}` + `/v2/options/
  contracts` for OI); expiry settlement spot; brokerage-synced option positions that nothing
  tracks mark off the broker's own mark (correct) or the chain (badged).

- **2026-09-02 · Premium-based exits need the quote loop, not the bar loop** (policy keys
  `premium_ladder`, `premium_floor_after_trim`, `premium_watch`; `policies.evaluate_premium` is
  the single evaluator for both paths). A 0DTE contract triples and gives it all back inside one
  15m bar; an underlying-price ladder never sees it. The tips lotto lane sets all three; other
  techniques opt in per policy. Chaos test
  `test_premium_watch_takes_lotto_profit_on_the_quote_loop`.

- **2026-09-03 · A collar rejection when the market moved TOWARD us is a missed trade, not
  protection.** PLTR 9/4 175P: the fire priced its entry at the 09:34 pick (2.14); seconds later
  the live mid was 1.97, `price_collar` refused, and the plan wore "r2: fire produced nothing"
  all day — for a put that had become CHEAPER. The runner now retries the entry ONCE at the
  live ask when that ask is below the refused limit (cheaper is never a chase; dearer stays
  refused, T4.1). One retry per fire, journaled `entry_reprice`. The Armed card's attention
  panel also stops offering "Sell now (market)" when nothing is held — an entry refusal is a
  heads-up, not an action. Test: `test_collar_rejection_retries_once_when_the_market_came_cheaper`.

- **2026-09-03 · The entry limit was a beat stale: re-priced on the live NBBO right before the
  order.** PLTR r2 fired 09:33; the critic pass took ~60 s; the order went out at 09:34 with the
  pick's ask (2.14) as its limit while the live mid was 1.97 - the RiskGate price collar (5% of
  mid) refused it and the plan reported "fire produced nothing": a silent missed entry, third of
  its class this week. `PlanRunner` now calls `OptionsService.reprice()` immediately before
  computing the option entry limit, so the limit is the market's ask at submit time; the
  never-chase cap (ARM-GAPS C1) still guards an ask that ran away upward. Rule of thumb for
  every money path: the price you send must be read AFTER the last slow step (critic, sizing,
  hooks), never carried from the fire.

- **2026-09-04 · Winners are banked by design (the monetize campaign + roll-up).** Research
  decision (two independent tracks converged — Leung & Zhang's optimal-stopping proof that
  take-profit AND trail together dominate either alone; Bhansali/LongTail's monetize-half-at-a-
  multiple with its regime findings; practitioner house-money and ratchet rules; Boyer & Vorkink
  on the negative drift of held long options). Shared policy keys: `monetize` (sell
  `take_fraction` at `take_at_pct`, ratchet floors `[[50,15],[100,50],[200,120]]` extending
  +100/+100 beyond, DTE ≤ 7 tightens half a rung, IV-ratio ≥ 1.3 tightens half a rung, ≤ 2 DTE
  chases peak−25pp) and `rollup` (delta ≥ 0.75 or extrinsic ≤ 10% → roll to ~0.35Δ same expiry
  ONLY when the credit ≥ the original debit — the position becomes unlosable; failed replacement
  buy = flat and paid, never limbo; max 2). Floors are judged against the PERSISTED peak (a
  fresh high can never stop out on its own mark), evaluated on the 2 s quote loop, real-time
  quotes required. `PolicyState.premium_peak` records per-position contract MFE — calibrate the
  thresholds from our own fills at ≥50 closed positions, coarse grids only (Bailey/López de
  Prado overfitting warning). Tests: `test_position_policies.py` monetize block,
  `test_position_chaos.py::test_monetize_take_and_ratchet_floor_on_the_quote_loop`,
  `::test_rollup_banks_a_credit_and_keeps_convexity`, `::test_rollup_failed_buy_leaves_us_flat_and_paid`.

- **2026-09-04 · Real-time greeks for tracked contracts** (Alpaca snapshots, phase 2): delta/IV
  merge onto the tracked snapshot every ~30 s (`greeksLive`), beating the ~15-min chain row —
  the roll-up trigger and the monetize IV-tighten read them; OI stays the chain's (T+1 anyway).

- **2026-09-04 · An expiry settlement is a TRADE and must live in the trade ledger** (shadow-book
  audit, user request "our shadow numbers are what we learn from"). `settle_expired` credited
  cash + realized P&L via `apply_fill` but wrote NO order/execution row — META 9/2 590C settled
  +$5,985 into muggzone's armed book invisibly: the cash identity broke and the round trip never
  reached the Ledger or any executions-based analytic. Fix: `_record_settlement` writes a FILLED
  `source="settle"` order + execution at intrinsic (no RiskGate — bookkeeping of an exchange
  lifecycle event, not a submission); the 5 historical settlements were backfilled FROM their own
  `OptionExpired` events. Audit results otherwise: 16/17 sim+shadow books balance to the cent on
  raw flows (Practice's $7.57 residual = the journaled 08-31/09-01 manual corrections, whose
  equity-level identity holds at unexplained 0); positions == execution flows everywhere; no
  unsettled expiries; ONE option fill >20% off its contract's own bar across every shadow book
  (a $0.15-vs-$0.11 micro-option) — the delayed-fill contamination class is otherwise absent
  from the learning record. Test: `test_expired_practice_position_settles_at_intrinsic` asserts
  the settle order + execution. Flagged for decision, not changed: immediate shadow books go
  deeply negative on cash (eva −$80k on a $10k start) because they buy EVERY tip by design.

- **2026-09-04 · An AUTO daily-loss halt spares the shadow learning record.** Practice tripped
  its -8% breaker at 09:38 (BBAI premium stop + the open's marks) and the global kill switch
  then rejected a RESEARCH-book entry at 09:58 — a tilt-guard for real money was blinding the
  instrument that collects evidence. `HaltState` now carries its `source`; `kill_switch` passes
  for `kind == "shadow"` portfolios when the halt is `source == "auto"` (the breaker). A MANUAL
  halt (app button / Telegram) still stops every book — halt means halt when a human says it.
  Reduce-only exits were and remain unblockable either way. Test:
  `test_riskgate.py::test_auto_halt_spares_the_shadow_record_manual_blocks_all`.

- **2026-09-04 · Three shared-runtime findings from the Friday audit.** (1) A restart
  re-attaching a plan journaled `TechniquePlanArmed` with `restored: true`: the Team2 deploy
  restarts produced 1,597 of the day's 1,669 "armed" events. Restores now journal
  `TechniquePlanRestored` (own contract, no config blob); nothing consumed the flag. (2) The
  sim executor has no cash check: two share tips (ZURA 702, SOFI 236) plus a 0DTE lane took the
  Practice book to **-$5,021 cash** while EM sizes off the same book. New RiskGate check
  `cash_available` (kind `sim`, BUY, non-reduce-only; `risk.sim_require_cash`, default on):
  a buy must fit the cash on hand, as every real venue would insist. Shadow/research books
  are exempt. (3) INVARIANT candidate for the desks: one Practice book is now shared by
  three techniques (EM, tips, Team2), so a technique's day P&L can no longer be read off the
  book - use the per-plan `realizedPnl` / scorecards, or give each technique its own
  Practice book (`Portfolio.book` exists). Decision left to the user.
- **2026-09-04 · The premium pre-check in `planrunner` compared premium against CASH, not equity.**
  `PlanRunner._enter`'s options pre-check (the one that exists so a plan can fall back to shares
  *before* the RiskGate rejects an order) read
  `pf = positions.portfolio(pid); eq = pf.get("equity") or pf.get("cash")`. `positions.portfolio()`
  returns the cached portfolio row — id / name / kind / cash / baseCurrency — which carries **no
  `equity` key**; equity is the async `positions.equity(pid)`. So the pre-check always fell through
  to cash and refused every option entry in a book that is merely fully invested. It was therefore
  strictly stricter than the RiskGate it mirrors (`risk.py` l.263 uses `await positions.equity(...)`),
  and silently: the message even says "equity". Cost Team2 its first auto order (2026-09-04 11:08 ET,
  SPY 768P, premium $1,014 vs a Practice book with $8,618 equity and −$267 cash; the gate would have
  passed it at 50%). Fixed to await the real equity — one line, no behaviour added, the RiskGate is
  still the authority. Team2 F22. Two deliberate non-changes, flagged for decision: the pre-check has
  no `kind == "shadow"` exemption (the RiskGate has had one since 2026-09-01, so shadow books with
  negative cash are blocked from options on this path), and nothing on this path checks buying power,
  so a fully-invested book can now be sized into an order it could not fund at a real broker.

- **2026-09-05 · A same-evening history fetch carried a phantom bar stamped at the close.** Yahoo
  answers `includePrePost=false` with a trailing bucket at 16:00 (the closing print) on the
  evening of the session; a next-day fetch of the same window does not have it. DELL 2026-09-03:
  the 20:54 batch plan saw a one-print 1h bar at 16:00, the ATR-based stop buffer shrank, the
  reject trigger's stop (3.23) fell under 2x the 1m ATR and R3.2 invalidated it; the same plan
  built from a next-day fetch (or the walk-forward replay) had the stop at 4.28, the trigger
  valid, and it fired 09:39 for +2.55R. Fix: `history.clip_to_rth` in `fetch_window` for
  `session="rth"` - intraday bars outside 09:30 <= t < 16:00 ET are dropped at the source
  (`fetch_session` already did this; the analyze/plan path used `fetch_window` unclipped).
  Evidence: run f80b7ebd bars snapshot (1h stamps ... 15:30, 16:00) vs fresh fetch; sweep
  21a3a2f8 row DELL; fresh `plan DELL --as-of 2026-09-03` = run a27ff13f. Yahoo also revised
  7 of 390 1m bars by more than a cent overnight (late prints) - unavoidable, small.

- **2026-09-07 · One Practice book per technique (user decision, reset from 2026-09-08).** The
  shared "Practice" book was overdrawn to -$5,021 by two $5,000 tip buys sized under the
  ambitious practice limits (budget_per_tip $5,000, gross exposure 300%, no cash check) while EM
  and Team2 traded in the same book. From 09-08 FOUR books, $10,000 each ($40,000 total, user
  decision 09-07): `EM Practice` (045d8c35), `Tips Practice` (4611946d), `Team2 Practice`
  (b9dcd8db), `Options Cartel Practice`; Flow is context-only and has no book. Routing by
  `techniques.<id>.default_portfolio`
  (EM also `technique.arm.default_portfolio`; tips runner/proposals and EM arm-today read the
  technique key before `trading.default_portfolio`). The old book is renamed
  "Practice (archived 2026-09-07)" and flagged `Portfolio.archived` (new column; `POST
  /api/portfolios/{id}/archive`): out of every list and total, its holdings out of the positions
  list, its managed positions marked `archived` (never restored), its resting orders cancelled at
  restart. Nothing is deleted; journal, runs, outcomes, reviews and the counterfactual ledger are
  untouched. `trading.default_portfolio` is now EMPTY: manual tickets ask which book (no guessing). Settings tightened the same
  night: `techniques.tip.budget_per_tip` 5000 -> 2000, `risk.max_gross_exposure_pct` 300 -> 100,
  `risk.sim_require_cash` stays on. INVARIANT 15: a technique's orders land only in its own book;
  a shared book is never a fallback for a technique that has one.

## 3. Open questions the shared runtime is collecting data on

- **The post-close record of a plan built on an earlier session** (Team2 F67, 2026-09-08, no code
  change — a proposal for the user). `technique/service.py::armed_history` orders by `created_at`
  and the Armed > History page asks for 50 rows, so a technique that builds its plans the PREVIOUS
  session loses its day to whatever was built today: all three of Team2's 2026-09-08 plans (built
  Friday 17:34 ET) were absent from the page, whose day header still read "42 plan(s) · 10 fired ·
  0.00 realized". Ordering by `plan_for` is not enough (within a day Team2's rows are still the
  oldest by build time) — it wants a bigger window or a `planFor`/technique filter. Second half:
  that table's Realized column renders `state.realizedPnl`, which is GROSS — QQQ read −18.00 while
  the book moved −65.84 (23 contracts × 2 legs × $1.04 of commissions); the net number is already on
  the same row as `state.scorecard.realizedPnl`, and shared halts have been net since Team2 F32.
  Team2 works around both on its own page for now (`Team2Service.runs()` carries the day's grade).

- **Reviewer net value** (EM 1.4 today): the runner's counters (kills, cooldown re-fires, failures)
  are per technique; a cross-technique tally is the capture-rate telemetry item.
- **Quote-stop breach parameters** (`quote_exit_excess_r` 0.25, `quote_exit_polls` 2): tuned on
  EM's 1m plans; a slower-timeframe technique may want wider.
- **Overnight holding** (plan §2.4): the default policy is `venue_stop_required`; whether
  app-managed holding is ever acceptable is undecided.

## 4. Change log of shared knobs (date · change · why · evidence)

- 2026-09-10 · **A verification `npm run build` is also a UI deploy — the version chip can report a release the
  engine is not running** (Team2 watch run 51, finding F94; nothing changed, this is a policy question for
  whoever owns `scripts/start.ps1`). Facts: the running engine is the 01:29 ET boot on **v0.7.36** (F89 — it is
  elevated, so no assistant task can restart it), `frontend/dist` was rebuilt at 10:12 ET while verifying an
  unrelated backend fix, and the running server serves `dist` off disk — so the login page and top-bar chip
  read **v0.7.38** against a 0.7.36 API. The frontend half of a change deployed itself with no restart, no
  `/api/ops/restart-check`, and no journal entry, while the backend half stayed queued. Harmless today (both
  commits are backend-only, so there is no contract mismatch), but a frontend change that needs a new endpoint
  would go live against an engine that does not serve it, and the version chip would say the deploy succeeded.
  Two consequences worth adopting: (1) **`/api/health` is the only truth about what the engine is running** —
  desk logs and watch runs should cite it, never the chip; (2) verification builds should write to a scratch
  dist, or `dist` should be published as part of the restart rather than as a side effect of `npm run build`.
  Evidence: `/api/health` 0.7.36 vs the served bundle's 0.7.38 and `frontend/dist/index.html` mtime 10:12 ET,
  2026-09-10; detail in `docs/techniques/team2/TRADING-RULES.md` F94.

- 2026-09-09 · **Codex review of PRs 33–45 (a3885a9): ten findings, twelve reproducible regressions — all fixed in
  v0.7.32 (the Team2 watch job released 0.7.30 and 0.7.31 in between), the regression file adopted verbatim as `tests/test_codex_f75_regressions.py`** (packet:
  `docs/techniques/team2/notes/research/2026-09-09-pr33-45-review.md` in the Codex checkout). R1 readiness: an
  order/position inventory failure is a blocker (`inventoryError`), a fire chain in flight (`trades[*].status ==
  fired` in a money mode, or any `ArmedPlan.fire_tasks` entry) is a blocker (`firing`), and the three restart scripts
  refuse — instead of "proceeding on the health check alone" — when no readiness answer comes back, unless `-Force`;
  `POST /api/ops/quiesce` (self-expiring, 5 min) suspends NEW money-mode fire chains (`_fire_rest` skips them as
  `quiesced_skip`; exits and alert reads untouched) and the scripts call it before capturing state, releasing it on a
  refusal. R2 restoration: managed positions are compared by id; one that shows up CLOSED afterwards is `explained`,
  one that vanished fails; counts-only states fail on a lower open count; working entries join the comparison. R3:
  `ingest_exchange_bar` inserts a recovered minute BETWEEN existing bars (and before the first) instead of dropping
  it. R4: `marketdata.merge_exchange` is the ONE policy for two venue observations of a minute — newer OHLC; a newer
  volume of 0 is incomplete and the known volume stands; any other newer volume (lower included) is a correction —
  applied in memory, in the persist batch and in the upsert (GREATEST is gone; `DATA_RULES_VERSION` bumped to
  2026-09-09b). R5: `fetch_window_ex` names the provider; `bars_repair backfill` zeroes a day's print-less sampled
  volumes only when ALPACA covered that session (≥ 300 regular-session bars), never on a Yahoo fallback or a
  partial answer (`coveredDays`/`uncoveredDays` in the result); the historical Yahoo parser no longer turns a
  missing volume into 0. R6: `apply_quarantine` locks the ids (`FOR UPDATE`), archives the CURRENT rows column for
  column, verifies, and deletes in the same transaction; a correction after selection is archived, one during the
  lock lands as a fresh live row. R7: the sweep runs `validate_sessions` on every symbol's tape before choosing
  previous sessions, pivots, warm-up and scoring, and reports `coverage`. R8: sweeps and plans hash the bars they
  actually hold (`marketdata.hash_bars`, same bytes as `dataset_version`), not a separate table read. R9:
  `BarAggregator.seed` no longer pretends the cumulative counter was 0 (a 10M session total became one minute's
  volume). R10: no usable history → no plan, not a TypeError. **Retained-evidence check on the three runtime
  quarantine batches** (the review could not verify them): `7f6269da4e71` (closed days) has zero live rows at its
  minutes — no venue bar exists on a closed day, so no correction could have been in flight; `bfa00d50b550` and
  `a9116e809b6e` (sim blocks) have 15,641 live EXCHANGE rows at their minutes, all written by the Alpaca backfill
  AFTER the batches committed (16:36/17:06 vs 17:13–17:18 UTC) and none by the live engine (it writes today's
  minutes only) — the R6 interleaving had no writer to race against on 2026-09-09.
- 2026-09-09 · **F75 repair EXECUTED on the runtime DB (12:38–13:18 ET) — the record.** Pre-repair identity (Team2
  symbols, 2026-08-14..09-09): `0155fbe4247ee049…`, 67,780 rows. Quarantine batches in `bars_quarantine` (copied, verified
  row-for-row, then deleted; never deleted from): `7f6269da4e71` = 316,603 rows / 439 symbol-sessions on non-trading days
  (weekends 08-15/16, 08-22/23, 08-29/30, 09-05/06, Labor Day 09-07; up to 128 symbols on 09-07); `bfa00d50b550` = SPY
  08-14..08-19 sim block, 4,424 rows; `a9116e809b6e` = the rest of the sim-era watchlist (AAPL, AMD, MSFT, NVDA, TSLA,
  SHOP.TO, TD.TO) 08-14..08-19, 30,969 rows — identified by their 720 overnight (00:00–03:59 ET) rows per day, which no
  real feed writes; QQQ/IWM 08-17..19 have none and were kept. Backfill from Alpaca SIP (`bars_repair backfill`, 214
  servable symbols; 192 option contracts / .TO / index symbols skipped): pass 1 (08-14..09-09) fetched 1,605,836 bars,
  changed 373,675, ADDED 1,240,400 (the table only ever held RTH-ish samples; the venue tape is 04:00–20:00), zeroed
  42,109 volumes on quote-sampled rows in minutes the venue has no bar for (no bar = no prints); pass 2 (08-14..08-21,
  after the clip defect below) fetched 742,162, added 555,684. FINAL identities: Team2 symbols `a00ecad1ef7fddd3…`
  (55,219 rows), all symbols `532d793203dfd9b2…` (2,880,732 rows), both in `bars_dataset_versions`. Team2 audit after:
  no flags; whole table: `thin_rth` 2, `outlier_range` 20 (real large-move days — CRDO/HPE/MRNA/DKS earnings-type
  sessions; flags, not classifications), `volume_spike` 10. Two defects found by running it: (a) `clip_request_window`
  applied Yahoo's 20-day 1m depth to Alpaca requests, so pass 1 silently started at 08-20 (fixed: the clamp is
  Yahoo-only; Alpaca is clamped to now); (b) `volume_spike` flagged 253 venue-only sessions whose 09:30/16:00 auction
  minute is legitimately a quarter of a thin name's day (fixed: auction minutes and venue bars are not spikes).
  Limitation kept on record: the calendar gate is NYSE; a `.TO` symbol on a Canadian-only holiday still forms flat
  bars and loses real bars on a US-only holiday — those symbols are portfolio context, not technique inputs. **For
  the EM and Cartel desks:** every stored-bar calibration since 08-14 should be re-derived on `532d793203dfd9b2…`;
  the table also now carries the full extended-hours tape, which RTH consumers must keep clipping.
- 2026-09-09 · **F75 repair — the shared `bars` table was partly synthetic, and its writers were live code.** Facts, from
  the runtime DB (406 symbols, 1.42M 1m rows): (1) SPY 2026-08-14 22:15 → 08-19 (7,300 rows, 24-hour bars, RTH ranges up
  to 769–1459) is the SIM quote feed's random walk, persisted by the bar persister while the app ran on the sim feed
  before the paid feed was wired (+ `synthesize_history` seeding two days for any symbol with no bars); (2) one-price
  "sessions" on 08-15/16, 08-22/23, 08-29/30, 09-05/06 and Labor Day 09-07 across up to 128 symbols (51k rows on 09-07
  alone) are the bar aggregator forming a bar from every quote with no calendar gate while the app ran on CLOSED days —
  the row spans show exactly when it was up (Sat 09-05 all day, Sun to 10:39, Mon from 13:47); 2026-09-05 is a Saturday
  (the watch job had called it a trading Friday); (3) exchange corrections replaced sampled bars in memory but the DB
  write was `on_conflict_do_nothing`, so the sampled bar survived on disk — every replay/sweep read the uncorrected
  minute. Built: `Bar.source` + `bars.source` (additive column, legacy rows `unknown`), precedence upsert (exchange >
  sampled|unknown > sim; exchange refreshes exchange; one row per key per statement — a sampled bar and its correction
  share a flush), calendar gate (`market_calendar.is_market_minute`: trading day, 04:00–20:00 ET, 17:00 on early
  closes) in BOTH the aggregator (real feeds) and `persist_bars`, sim isolation (`AppConfig.persist_sim_bars`, tests on,
  runtime off), `bars_quarantine` + `bars_dataset_versions` tables, `zargar.tools.bars_repair` (audit / quarantine /
  backfill / version), `marketdata.dataset_version` (sha256 over scope + rules + every (symbol, ts, OHLCV, source)
  row — a volume fix with the same row count is a new version). Volume: F78 below. Tests: `tests/test_bars_integrity.py`,
  `tests/test_bars_repair.py`. Repair record (what was quarantined/backfilled, hashes before/after): the Team2 desk
  section in `docs/techniques/team2/notes/market-watch.md` 2026-09-09 evening.
- 2026-09-09 · **F79/F80 (Team2 watch 12:40 ET, shared) — FIXED v0.7.29 (deployed 12:54 ET), verified by the watch at
  13:05 ET.** F79: Yahoo's poll re-emits its last 30 completed minutes as exchange bars; the freshest ones carry
  volume `null` until Yahoo fills it in, `_parse_completed_bars` turned that into 0, and with source precedence the
  zero-volume "correction" overwrote Alpaca's true bar (SPY 12:08/12:09 ET; every streamed symbol 11:58–12:09). Now a
  minute without volume is provisional and never emitted; exchange-over-exchange keeps the newer OHLC but never lowers
  volume (`GREATEST`); legacy `unknown` ranks BELOW `sampled` (no provenance loses to a live bar). F80: the minute
  forming when a process dies never reached the table (QQQ/IWM 11:25 ET after the 11:26 boot) — the hybrid feed had no
  day seeding at all (only the Yahoo-only feed fetched today's bars); now `Engine.seed_today_exchange_bars` re-reads
  today's completed minutes from Alpaca history for the streamed symbols AFTER start, paced (semaphore 4), through
  `ingest_exchange_bar` (memory + persister by provenance) — 31 symbols / 13,389 bars / 0 failures at the 12:54 boot.
  It runs after start on purpose: 400 symbols of history inside `start()` would outlast the watchdog's 180 s lock.
- 2026-09-10 · **The restart door is closed: the running engine is ELEVATED and every Zargar task is `Limited`.**
  The 01:29 ET boot (pid 29812, owner `LENOVO-INTEL\vispe`, created 22:28:58 PT on 09-09) runs at high
  integrity: its `CommandLine` is unreadable from a Limited process and `Stop-Process` returns **Access is
  denied**. `ZargarRestart` fired cleanly at 09:40 ET, `restart-check` said `safe: true`, and
  `restart.ps1` aborted at `start.ps1:152` on that denial — transcript in
  `logs/restart-20260910-064016.log`, `LastTaskResult 1`. **Nothing was killed, so there was no outage**,
  but no assistant on any desk can deploy until the process is replaced. All four tasks
  (`ZargarRestart`, `ZargarRestartOverride`, `ZargarUnelevatedStart`, `ZargarWatchdog`) have
  `RunLevel = Limited`, so `-Force` does not help either — this is an elevation refusal, not a readiness
  refusal. This is exactly the failure mode the 2026-09-05 "the server must run UNELEVATED" decision
  exists to prevent; whichever desk booted at 01:29 ET did it from an elevated shell. **Recovery is the
  user's:** `scripts\stop.ps1` from the elevated terminal that owns the process, then any desk's
  `ZargarRestart`. Deliberately NOT worked around here — registering a `RunLevel Highest` task would
  deploy, but it would leave the next engine elevated too and re-close the door. Worth a guard:
  `start.ps1` could refuse to launch when `IsInRole(Administrator)`, and `restart.ps1` could report
  "the running engine is elevated - stop it from the shell that owns it" instead of a raw Stop-Process
  error. (Found by the Team2 market watch, run 49.)
- 2026-09-09 · **Deploy-day findings on the restart door (five restarts, all through `ZargarRestart`).** (1) A stray
  carriage return in a comment made Windows PowerShell 5.1 treat the rest of the line as a command: `restart.ps1` exited
  1 before its first step and nothing restarted — task scripts are ASCII AND CRLF-clean (write them with explicit
  newlines). (2) `& start.ps1 @args2` with an ARRAY passed `-Detach` positionally under 5.1: the engine ran in the task
  console's foreground, `restart.ps1` never reached its health wait or restoration check, and the task stayed
  "Running" (267009) so a second `schtasks /Run` was silently ignored — a hashtable splat fixes it; a stuck instance
  needs `schtasks /End` (which kills the engine) before the door works again. (3) The stop step matched processes by
  COMMAND LINE alone and killed an assistant's PowerShell session whose command text merely mentioned the engine
  module (twice); it matches process name + command line now, and pwsh windows only when running the two helper
  scripts with `-File`. (4) Helper workers are launcher/child PAIRS (`python -m …` spawns the worker) — two rows per
  helper are normal; "deduping" them kills both (done once, restored by the next restart). (5) Evidence lines now in
  every transcript (`logs/restart-<ts>.log`): `Restore check OK: armed 74/74, openTrades 0/0, pendingExits 0/0,
  restingOrders 10/10, inflightOrders 0/0`. (6) An unknown `/api/*` path used to fall through to the SPA index (200
  HTML), which the scripts read as an unsafe answer on an older engine — now a 404, and the scripts treat a non-JSON
  answer as "check unavailable".
- 2026-09-09 · **Worktree hazard.** Another session switched THIS desk's worktree onto its own branch twice while a
  batch was in progress; two commits landed on other desks' branches and PR #43 shipped only docs under a code title.
  Rule: `git branch --show-current` before every commit, and verify a PR's file list (`gh pr view N --json files`)
  before merging it.
- 2026-09-09 · **F78 (shared; the Team2 watch job's F77 of 12:05 ET is a different finding) — bar volume was the difference of a re-seeded counter.** `BarAggregator.on_quote`
  differenced `Quote.volume`, which since F19 (09-04) is Yahoo's session total re-seeded every context poll plus prints
  since the seed; a re-seed jump landed in one bar (SPY 2026-09-08 09:3x: 43,496,831 shares in a minute; the day summed to
  352M vs ~40M real) and the first quote after a `seed()` painted Friday's 33M onto Saturday's flat bar. Now: Alpaca
  prints accumulate `Quote.trade_size` per emission and the aggregator SUMS them for Alpaca-streamed symbols
  (`volume_from_prints`); the cumulative path treats a counter that goes DOWN as 0 (session roll / re-seed), never a
  clamp-to-jump. Historical repair = exchange backfill by provenance (above). **Consumers of bar volume, assessed
  2026-09-09:** EM — `marketstructure/volume.py` relative-volume + profile via `technique/analysis|walkforward` (stored
  1m rows: AFFECTED for sweeps/backtests on 08-20..09-09; live gates saw the exchange bar in memory within ~5 s);
  Options Cartel — confirmation-volume baselines / entry / replay read stored minutes (`prepare.py`, `entry.py`,
  `replay.py`, `preparation_readiness.py`: AFFECTED for anything computed from stored bars in that window; PR 13's
  "complete confirmation-volume baselines" should be re-derived after the backfill); Flow — option-chain volume and
  quote-level stock volume (NOT bar rows; the quote-level session volume carries F19's re-seed semantics but is a
  session total, not a per-minute delta — unaffected by F78); Tips, Team2 — no bar-volume reads. The desks that own
  EM/Cartel decide whether to re-run their calibrations on the post-backfill dataset version.
- 2026-09-09 · **Restart coordination is app-wide now** (Invariant 18). `zargar/ops.py` (`restart_state`,
  `readiness_from_state`, `compare_states`) + `api/routes_ops.py` (`GET /api/ops/restart-check`, `GET /api/ops/state`,
  `POST /api/ops/restore-check`; loopback-only like /api/health's local block; the check is journaled as
  `OpsRestartCheck`). `scripts/restart.ps1` (the deploy door; exit 2 refused, 6 restoration mismatch) and `scripts/start.ps1`
  (exit 2 refused) both refuse when not safe unless `-Force`, and compare the state after a detached start with the
  state before; the `ZargarRestart` task runs `restart.ps1`, `ZargarRestartOverride` runs `restart.ps1 -Force`
  (`install-watchdog.ps1` refreshes both - the task had a baked `-Expect 0.7.22`, a dead deploy for any other
  version); `watchdog.ps1 -Force [-Override]` carries the same checks. Why: the tips desk's 11:07 ET restart on 2026-09-09 landed while Team2
  was live in auto — it happened to be flat, and "no open trades" was the only test anyone had. Tests:
  `tests/test_ops_restart.py`.
- 2026-09-08 · **Hosting: the engine must not live in an assistant's process tree.** Root cause of the 14:24:01 ET outage
  (and two earlier ones): the Windows Application log shows `CoworkVMService` "Claude VM Service stopped" at 11:24:01 PT
  during the Claude desktop package update 1.49585; the engine had been started from that tree by `start.ps1 -Detach` and
  died with it; the user's one-shot `ZargarUnelevatedStart` task brought it back 8 minutes later. Now: `scripts/watchdog.ps1`
  (health-check `/api/health`, `-Force` restarts) registered by `scripts/install-watchdog.ps1` as user tasks **`ZargarWatchdog`**
  (every 3 min: start only if :8420 is silent; an age-based lock in `logs/watchdog.lock` keeps it to one start per
  3 minutes so a tick cannot pile onto a restart in progress; `ZargarWatchdogLogon` needs an ELEVATED shell to register
  and is best-effort) and **`ZargarRestart`** (on demand:
  `schtasks /Run /TN ZargarRestart` — the deploy path, so the new process is owned by the scheduler). Rule: assistants
  deploy through `ZargarRestart` (from PowerShell — Git Bash rewrites `/Run` into a path), never by running `start.ps1`
  from their own shell; never `Stop-Process` :8420. Verified 2026-09-08 16:54 ET: engine pid's parent chain ends in the
  scheduler, not `claude.exe`; a full restart took 30 s; the tick that landed during it exited 0.
  Log: `backend/zargar-8420.log` rotates 50 MB × 10, `httpx` at WARNING, start/stop lines with pid (F69).
  **Windowless tick (2026-09-08 evening):** the plain `powershell -File` task action allocated a visible console every
  3 minutes (a cmd window flashing on the desktop — unusable). `ZargarWatchdog`/`ZargarWatchdogLogon` now run through
  `wscript.exe //B //Nologo C:\ProgramData\Zargar\run-hidden.vbs <watchdog.ps1>` (source `scripts/run-hidden.vbs`,
  copied by the installer; `install-watchdog.ps1 -ScriptsDir` registers against another checkout; the installer
  no longer re-creates an existing `ZargarRestart`, which desks re-point at `restart.ps1 -Expect`). `ZargarRestart`
  stays visible on purpose. Re-run the installer after changing either script. Lesson: an assistant's shell sees a
  VIRTUALIZED user profile (`%LOCALAPPDATA%` writes never reach the real disk — a task pointed there fails with
  result 1 and no output) and cannot launch `schtasks.exe`; use the `*-ScheduledTask` cmdlets and machine-wide paths.
- 2026-09-08 · **Invariant 16 — a recomputed read never re-acts.** A technique that recomputes its whole session read
  every bar (Team2 `simulate_session`) must recognise acted-on events by a content fingerprint (ts · event · setup ·
  touch · why), never by list position, and must log once (`read_rewritten`) when earlier fingerprints disappear. Any
  input the read consumes that can move intraday (IV, a corrected bar, a level) must be captured point-in-time and
  stamped on the plan + run (`plan.sigma`), and replay must use the stamped value. `tests/test_team2_integrity.py`.
- 2026-09-08 · **`PlanRunner.target_breach(tr, last)` hook (exit-only)** on the ~2 s quote watch, after the premium stop and
  before the quote stop: a technique may declare the plan target hit on a FRESH underlying print (Team2 F50). Semantics:
  requires `fresh` (quote age ≤ `quote_exit_max_age`) and no pending exit (`pending_exit_qty`); sells `tr.remaining` via
  `_exit(..., "tp3", force_market=False)` = reduce-only LIMIT at the contract's fresh bid; a partial fill reduces
  `remaining` and the next poll re-checks; a resting unfilled limit is re-priced by the technique's stale-exit pass and
  the failed-exit watchdog (market after 30 s × 5); after a restart the trade is restored with its exits and the same
  poll applies. The base runner keeps managing targets on closed bars; the hook defaults to None. Never an entry path.
- 2026-09-08 · `TechniquePlanRead` registered in `research/events_contract.py`
  (required: runId, symbol, trigger, event, reason) and
  `test_every_journaled_kind_has_a_contract` widened to scan `zargar/techniques/**`
  as well as `zargar/technique/` and `zargar/execution/`. Why: a kind journaled by a
  per-technique package (Team2's structural read events, F28) was outside the test's
  scan, so it shipped shapeless and logged an advisory `unregistered Technique event
  kind` warning on every read event. `TechniquePlanRead` is the only such kind today.
  Advisory logging only — no journaled shape, hook or money path changed.
  Evidence: Team2 TRADING-RULES F52; tests `test_platform_phase3.py` (70 passed with
  the Team2 suite).

- 2026-09-06 · Opt-in adapter adoption supports deterministic `positionId`
  identities (existing ids are rejected rather than overwritten). Adapter-backed
  persistence/journal failures propagate; initial adoption enters the in-memory
  manager only after a successful durable save. Non-adapter adoption retains its
  prior path. Cartel's terminal-entry helper validates actual fills and holdings,
  locks arming state and serializes allocation to prevent duplicate adoption.
  Tests: `test_options_cartel_adoption.py`, including injected save failure/retry.

- 2026-09-06 · `TechniqueCartelContractSelection` contract records Cartel's
  reviewed selection policy, eligible/rejected candidates and bounded-search
  coverage. Reuses shared chain/reprice/snapshot interfaces; no order submission
  or existing technique selection policy is changed.

- 2026-09-06 · OptionsService snapshots gain additive `greeksFieldAsOf` metadata.
  Only non-null fields actually returned by the live Greeks provider get new
  observation timestamps. Quote-only refreshes and delayed-chain merges preserve
  them. Cartel uses delta's own observation age for its source-backed 0.25 floor;
  existing consumers keep their prior values/behavior. Tests:
  `test_options_greeks_freshness.py`, Cartel execution tests and options-service suite.

- 2026-09-06 · `ManagedPositionHistoryRecovered` contract added for explicit
  Cartel daily-data restoration. Restoring source data never alters actual fills
  or creates orders; missed closes remain identified separately. Conflicting
  existing observations and future/rewound history are rejected. Tests:
  `test_options_cartel_recovery.py`. Other techniques' history paths unchanged.

- 2026-09-06 · PositionManager gains explicit opt-in policy adapters: registered
  validation/update validation, minute-bar decisions and after-fill callbacks.
  Only policies declaring an adapter matching their technique use this path;
  all existing policies retain the previous behavior. Generic policy replacement
  cannot remove/swap a held position's adapter or rewrite its campaign state.
  Missing adapters alert and retain basic stop/expiry protection. Cartel's adapter
  routes every exit through existing close/reduce-only/in-flight accounting;
  after confirmed fills it synchronizes campaign quantities and re-sizes share
  GTC stops even when the stop price is unchanged. Source tests are in
  `test_options_cartel_position_adapter.py`, including a real OrderManager/sim trim.

- 2026-09-06 · Cartel adds the `TechniqueCartelStateChanged` versioned journal
  contract for its own transactional armed-state repository. Existing tables
  are reused with technique ownership checks; parent-plan row locks serialize
  creation, armed-row locks serialize trigger/attempt claims. No running broker
  or existing technique behavior is changed. Eleven PostgreSQL tests verify
  cross-instance races and ambiguous crash recovery (`test_options_cartel_state.py`).

- 2026-09-06 · Cartel preflight adds own `enabled`, `paused`, `allow_live_auto`
  settings (auto live off) and a versioned `TechniqueCartelPreflight` journal
  contract. Uses shared sizing helpers and RiskGate directly; no order submission.
  Requires fresh quotes/FX and explicit option/overnight/account choices. Actual
  execution integration remains separate. Tests: `test_options_cartel_execution.py`
  and Cartel API tests. Existing technique defaults and money paths unchanged.

- 2026-09-06 · Options Cartel registered as a fifth technique, with its own
  research/plan page and route. Registry test widened only for the new identity.
  Mobile More selection now follows registry pages excluding primary tabs;
  existing technique navigation remains equivalent. No Cartel execution runner
  or new trading behavior is enabled. Frontend build and Cartel device audit
  passed; all verification uses the separate Codex database and port.

- 2026-09-06 · Options Cartel research API added under `/api/options-cartel`.
  Uses the existing `TechniqueRun`/`TechniqueReview` schema with explicit
  `technique=options_cartel` ownership checks and existing `TechniqueRunCompleted`
  / `TechniqueReviewAdded` journal contracts. Analyses, reviewed plans and entry
  replays create separate rows; completed parent runs remain immutable. Route
  attachment starts no engine, broker, scheduler or execution runner and changes
  no existing technique behavior. Evidence: `tests/test_options_cartel_api.py`
  (PostgreSQL/ASGI ownership/authentication/provenance/no-orders tests).

- 2026-09-04 · **`risk.sim_require_cash` (new, default on)** - RiskGate check `cash_available`:
  a BUY in a `sim` book must cost no more than the cash on hand (reduce-only exits, shadow and
  research books exempt). Why: the Practice book reached -$5,021 cash on 2026-09-04 with no gate
  refusing it; every real venue would. Evidence: orders ZURA 702 @ 6.00, SOFI 236 @ 18.22,
  Practice cash after = -5,020.52. Off switch exists for a deliberate margin experiment.
  **2026-09-07 23:20 ET - decision needed:** the Practice book still holds ZURA 702 / SOFI 236 with
  cash -$5,021, so with this check ON every EM option entry on 09-08 is refused. The desk did not
  flip it (a safety knob is the user's call): either turn `risk.sim_require_cash` off until the
  book is repaired, close the two share tips, or credit the sim book.

- 2026-09-01 · **`execution.arm_expired_plans` (new, default off)** — the runner refuses to arm
  a plan whose last session already closed; replays/tests set it on. Why: 22 stale runs armed
  after the close and expired on arrival (finding above). Evidence: journal 2026-09-01 23:5x ET.

- 2026-08-29 · **Ambitious practice posture** (user decision, active dev):
  risk caps raised live — position notional 25k / 50% / gross 300%, option
  premium 50% / $10k / 50 contracts, 30 orders/min, daily-loss halt 8%,
  spread cap 20%; tip budgets 2,500 per tip / 15k open / 10 open tips / 10%
  max risk; loss-halt fallback $500. Discord intake: `botsOnly=false` on all
  nine monitored sources (human posters count). Code DEFAULTS unchanged
  (conservative fresh-install); the pre-live re-tightening is
  `docs/NEXT-GAPS-PLAN.md` §0/R3. Kill switch, never-list, reduce-only exits
  untouched.
- 2026-08-29 · **Native multi-leg spreads** (NEXT-GAPS M): `OrderManager.place_spread`
  is the ONE sanctioned combined-order path — write-ahead per-leg rows, a single
  `RiskGate.evaluate_spread` verdict on the structure's max loss, `Executor.submit_mleg`
  (sim + SnapTrade legs-array). It carries `place()`'s full guarantees; never submit a
  spread around it. Venue opt-in per account via `options.mleg_accounts`; every native
  failure falls back to the verified leg-sequencing.
- 2026-08-29 · **ARM-GAPS engine batch** (tips gap-closure, clusters A–F): MULTI-DAY
  plans on the shared runner — `plan_horizon(run, plan)` hook (base single-session),
  `ArmedPlan.horizon_sessions/sessions_used/expires_session/risk_warning`,
  `_roll_session` at the close (revivable trigger statuses re-watch; `invalidated` and
  consumed fires stay dead), boot-roll in `restore()` (the `plan_for` COLUMN stays
  authoritative), `on_plan_horizon_expired`/`on_plan_expired_offline` hooks. New events:
  `TechniquePlanRolled`, `TipSpreadLegFailed`, `TipLaneGraded`. New hooks:
  `entry_limit_cap` (never-chase), `emit_proposal` now alerts on failure;
  `Trade.handoff_pending` interlocks fills against the session flatten. Tip-scoped
  knobs beat EM-named legacy keys (`techniques.tip.enforce_session_windows` /
  `options_enabled` / `max_risk_pct`); `windowOpenNow` and the plan summary judge
  against the TRIGGER'S OWN windows, not EM's prime clock. `dailyLossLimit` on a
  rolled multi-day plan is a whole-life loss cap (documented, conservative).

- 2026-08-27 · **Phase 3 engine batch** (techniques-research P0s): settings resolver
  `techniques.<id>.<key>` → `execution.<key>` (31 aliased runner keys, journal-continuous
  migration); event-schema contracts + `TechniqueHookStats` daily roll-up; `tags` on
  runs/outcomes/orders; `risk.max_day_notional_per_technique/_tag`; **never-list hardened**
  (share shorting rejected everywhere, `risk.allow_short` ignored; 0DTE rejected for every
  technique except `enhanced_market`); engine scheduler + nightly `option_chain_snapshots`
  (OI/IV history — not backfillable) + tf=1d bar layer; `engine.calendar` (earnings/ex-div v1,
  advisory); per-technique pause `/api/techniques/{id}/pause` (exits exempt, HALT untouched);
  bars hygiene (bucket alignment at write, stub cleanup at boot — 1d rows exempt).
- 2026-08-27 · **Phase 2b: the durable position manager** — policies-as-data + `PositionManager`
  (multi-leg, write-ahead, restart-proof, RTH-closed-bar decisions, crash brake, watchdog, venue GTC
  stops for shares, app-managed-with-ack for options overnight, assignment-aware pre-open
  reconciliation with unexplained-drift symbol halts) + `simulate_position` (same evaluator; premium
  path explicitly unsimulated) + sizing modes. Chaos suite = 14 green scenarios incl. live-vs-sim
  parity. New shared knobs: `execution.min_dte` (floor techniques may only raise),
  `execution.reconcile_at`. New event kinds: `ManagedPosition*` (contracts registered).
- 2026-08-27 · Venue probes (read-only impact previews): Webull CA accepts SELL_TO_OPEN, native
  2-leg spreads, and GTC on options; venue-side option STOP unproven (503); Wealthsimple 1156.
- 2026-08-27 · **Order-pipeline deadlock fixed** (`orders.py`, latent since day one, found by the
  tip-runner sim rig): a fully-filled bracket PARENT spawned its children while `on_report` still
  held `_report_lock`; the child's `submit` emits its "accepted" report synchronously (sim — and
  any venue that acks in-band), re-entering `on_report` on the same non-reentrant lock. The task
  froze silently (position effects commit before the deadlock point, so tests that only checked
  positions passed) and every later exec report queued behind the poisoned lock — engine-wide.
  Fix: `_apply_fill` returns the parent; `on_report` spawns bracket children AFTER releasing the
  lock. Only the signals/shadow path used OrderManager brackets, which is why three weeks of EM
  live days never hit it.
- 2026-08-27 · **Runner is now truly multi-technique** (`planrunner.py`, found building tip #2):
  `restore()` re-arms only rows whose `technique` matches the runner (an unfiltered restore would
  re-arm another technique's plans through the wrong hooks), and `_persist` stamps
  `technique=TECHNIQUE_ID` on new `technique_armed` rows instead of relying on the EM column
  default. Tracker: `volume_floor_mult <= 0` now means "no volume confirmation required" on the
  touch path (the §2.1 promise; EM's floor is 0.5 — unaffected, parity suites green).
- 2026-08-28 · **Run rules snapshots are a PARITY requirement, not bookkeeping** (techniques
  team, found building Tip T3): the outcome scorer replays every plan run with
  `run.config.thresholds`; a run minted without the snapshot replays under the DEFAULT
  technique's rules — a tip plan was about to be re-judged under EM's volume floor and
  prime-only windows, contradicting its own live tracker. Rule: **every runner that mints plan
  runs must snapshot its `rules()` into `config.thresholds`** (TipRunner does; EM always did via
  its provenance snapshot). Also: `SignalService` gained source auto-detection
  (`ExtractionResult.source_hint` → `_resolve_source`, punctuation/case-insensitive match
  against known sources; explicit names never overridden) and the Tips page was rebuilt
  (tabs, hero composer, sidebar's duplicate "Signals" entry removed — Techniques ▸ Tips is
  the one home).
- 2026-08-27 · **Flow UI shipped + context deliveries journaled** (techniques team,
  docs/techniques/flow/UI-PLAN.md): new event kind `FlowContextServed` (aggregate_id = the
  symbol) — every context line served to a consumer (tip verification, EM analyze) is journaled
  with the refId, which is what the Symbol Story's "where this read went" panel reads. EM's
  `analyze()` now receives the flow line as an informational note (recorded in run provenance as
  `config.flowContext`, never a rule). Universe gains a **flow layer** (provenance "flow":
  score ≥ `techniques.flow.universe_score_min` on 2 of the last 3 scan days). Reads persist the
  scan-time `spot`. First real-scan calibration findings recorded in UI-PLAN §3a (default
  thresholds flag 42/56 symbols, mostly 1-DTE noise — tune before trusting scores).
- 2026-08-27 · **`ArmConfig.premium_budget`** (techniques team, for Tip Phase B): per-plan $
  cap on options premium, applied in `_size_contracts` after risk sizing (floors at 1 contract
  with a warning when a single premium exceeds the budget; RiskGate premium caps backstop;
  fixed `contracts` still wins). 0 = off; EM plans unaffected.
- 2026-08-27 · **Tip consumes Phase 2b + dual shadow books** (techniques team, user decisions):
  `Portfolio.book` column splits each source's shadow record into an **immediate** book (buy at
  tip time) and an **armed** book (wait for the level; the `tip_shadow_arm` scheduler job
  auto-arms every open level-touch tip there each morning, budget-sized) — one tip, two books,
  never blended; `tipTimeEarned` on the scorecard is the earned-entry evidence. Options tips are
  expiry-bounded end to end (`techniques.tip.entry_cutoff_dte`; `horizon.py`; signals expire as
  `SignalExpiredUnfilled` when the level never comes). Filled tip entries HAND OFF from the
  session runner to `PositionManager.adopt` (ladder 50/50 + structure trail after +1R + thesis-
  expiry time stop + earnings flatten; venue GTC stop for shares) — the first consumer of 2b. new non-Technique
  event kinds `SignalParked` (price-position checks failed → parked, not killed), `SignalSeenAgain`
  (dedupe attach), `FlowScanCompleted` (daily flow scan summary); new table `flow_reads` (Flow's
  daily per-symbol verdicts — chain data stays in `option_chain_snapshots`, single writer: the
  research feed; Flow reads it with a scoring-only live fallback); `flow_scan` job on the engine
  scheduler at `techniques.flow.scan_at` (16:45, after chain snapshots); tip shadow orders carry
  `technique_id="tip"` + `tags=["source:<name>"]` so the per-tag day-notional cap sees them;
  settings families `techniques.tip.*` / `techniques.flow.*` in DEFAULTS. Verification signals
  now carry advisory `flowContext` / `calendarContext` lines (informational, never checks).
  Overnight default for long options → app_managed-with-acknowledgement (see plan §9).

- 2026-08-25 · Alpaca full-SIP stream + Alpaca-first history; feed-down alerting · Yahoo 429 incident.
- 2026-08-26 · `feed.exchange_bar_hold_seconds`=5 (A7) · exchange bars never reached the armer.
- 2026-08-26 · `technique.arm.critic_timeout_seconds`=25, `critic_fail_budget`=3 (A8) · fail-open
  with a budget replaces a silent stall.
- 2026-08-26 · `technique.arm.daily_loss_fallback`=100 (A2) · silent no-halt.
- 2026-08-26 · `technique.arm.contracts`=0 (risk-sized), `max_contracts`=10, `friday_size_mult`=0.5,
  `avoid_0dte_after`=10:30 (D2) · user decision; re-tighten before real money.
- 2026-08-26 · `technique.stop_on_close`=true (D3) · the runtime judges stops on the closed bar,
  the quote breach stays the brake.
- 2026-08-27 · **Settled (user + EM team): `technique.arm.midday_trading` is EM-only, never a
  platform key** — audited: read in exactly one place, EM's `entry_windows_enforced()` hook; the
  runner never sees it. If technique #2 wants a schedule experiment it gets its own key.
- 2026-08-27 · **Settled (user + EM team): veto/critic budgets are platform defaults with
  per-technique override** — phase-3 resolution `techniques.<id>.<key>` → `execution.<key>` for
  every runner-read key; old `technique.*` names become deprecated aliases with `SettingChanged`
  journal continuity. Spec in the platform plan §8.4.
- 2026-08-27 · Clock-driven session close (EM team #1): expiry + scorecard at 16:05 ET by the
  clock (`PlanRunner._end_session`), never dependent on the 15:59 bar · 08-26 unscored plans.
- 2026-08-27 · Daily 09:00 ET feed self-test (EM team #2): REST bar fetch + WS auth, journal
  `FeedSelfTestPassed/Failed`, critical alert + Telegram on failure · 08-26 silent lapse.
- 2026-08-27 · Replay outputs carry plan-side validity; `sweepVersion` hashes `marketstructure/`
  (EM team #8/#9) · gate-audit mistallies; attributable parity diffs.
- 2026-08-27 · Platform phases 0–2: `marketstructure` library, technique registry + `technique`
  identity column, `OrderIntent.technique_id`, `execution/planrunner.py` (generic runner) with EM as
  `PlanArmer(PlanRunner)` hooks · `docs/TECHNIQUE-PLATFORM-PLAN.md`; parity suites green.
- 2026-08-29 · **Scheduler "once per ET day" survives restarts** (flow team): each job hydrates
  `last_day` from the journal's `ScheduledJobRan` rows on its first tick after boot — an evening
  of redeploys no longer re-runs nightly jobs. Evidence: 08-28 flow scan ran 4× (20:25→21:28 ET);
  the cold-boot re-runs had no quotes → spot 0 → zero flags, and overwrote the good 20:25 scan.
  A genuinely missed job (engine down at its time, no journal row for the day) still runs late.
  Flow also armored itself: put-call-parity spot from the chain when quotes are cold
  (`scan.spot_from_chain`), a spot-less re-scan never overwrites an existing read
  (`noSpot`/`keptExisting` in the scan journal), weekend "Scan now" rolls back to Friday, and a
  boot task re-scans the latest day if it carries the degraded signature (scores w/o flags/spot).
- 2026-09-03 · **Team2 desk, shared-engine additions (PLAN §3b E1–E7; all additive, RTH behaviour
  unchanged for every existing technique):**
  - `marketstructure/history.fetch_window(..., session="rth"|"ext")` + `fetch_extended_session` —
    the 04:00–20:00 ET tape (Yahoo `includePrePost`, Alpaca unfiltered) for pre-market levels and
    extended-hours indicators; default stays `rth` and the cache key carries the session.
  - `marketstructure/aggregate.py` — wall-clock 1m→2m/5m/15m aggregation (a missing minute never
    shifts the grid), `bar_session` (pre/rth/post/closed), `filter_session`, `closed_bars`.
  - `marketstructure/market_calendar.py` — NYSE holidays + 13:00 early closes (rule-based);
    **`sessions.session_bounds` now closes at 13:00 on half days and `next_session_date` skips
    holidays** — every clock-driven session close honours the real calendar.
  - `marketstructure/indicators.py` (EMA series/state, stack, fan), `marketstructure/dailylevels.py`
    (prior-day zones wick→next body, pre-market range, session extremes).
  - Nightly research jobs `ext_bars` (04:00–20:00 1m bars for `research.ext_bars.symbols`, 20:10 ET)
    and `vix_bars` (`^VIX`, `^VIX1D`, `^VIX9D` daily closes) into the bars table.
  - `research/macro_calendar.py` — `engine.macro`, a MANUAL FOMC/CPI/NFP list
    (`research.macro_events`) behind a stable read API; a fetched source is a placeholder.
  - `options/pick.select_by_premium` — premium-targeted strike selection (first OTM strike whose
    ask ≤ target, floor-guarded), returning EM's `ContractPick` shape; EM's just-OTM picker untouched.
  - **RiskGate never-list, per-technique 0DTE policy (user decision 2026-09-03):** a technique may
    open 0DTE for ITSELF via `techniques.<id>.zero_dte = {enabled, last_entry_et, flatten_et,
    max_contracts, premium_cap}`; entries refused after `last_entry_et`, everything after
    `flatten_et` (reduce-only exits never reach the check), per-order contract + premium caps.
    Without a policy the hard reject stands; EM's and the tips lotto lane's paths are unchanged.
    Rationale: different techniques have different rules — Team2 IS a 0DTE method (METHOD §7b).
- 2026-09-03 · `tests/test_platform_phase0.py::test_registry_lists_enhanced_market` expectation widened to
  include `team2` (the registry gained a fourth technique; EM stays first). This is the one intended way
  that guarantee changes — a new `TechniqueInfo` registration, nothing else.
- 2026-09-04 · `marketdata.persist_bars` inserts in chunks of 2,000 rows (asyncpg's 32,767-parameter cap;
  the first 20-day extended-hours bank failed on it). Found by running the Team2 bank for real.
- 2026-09-04 · **F19 fixed — `Quote.day_high` / `day_low` / `volume` are session-to-date, not process-to-date**
  (`brokers/alpaca.py`). The Alpaca adapter used to start every symbol's range/volume at zero when the
  process started and only widen from live prints; Yahoo's session values were an `or` fallback that one
  tick discarded, and a process left running overnight carried yesterday's numbers into today (SPY after
  the 10:36 restart: dayHigh 771.29 vs 772.87 real, volume 317k). Now: `absorb_context` SEEDS the running
  high/low from Yahoo's regular-session values and re-bases the volume (`vol_seed` + prints since), only
  once Yahoo's session is `regular`/`post` (its pre-market meta still shows the prior session); live prints
  widen the range and add volume only during 09:30–16:00 ET on weekdays; a new ET session resets
  everything. Pre/post moves stay separate via `session`. No decision path reads these fields (verified:
  only the UI types), so no technique behaviour changed. `tests/test_alpaca_feed.py`. Second half, same day:
  the Yahoo quote's `volume` was the LAST 1m bar's volume, not the session total, so the seed was wrong —
  `yahoo._parse_chart` now reports meta `regularMarketVolume` (fallback: the sum of the chart's bars).
- 2026-09-04 · `PlanRunner.set_mode` (and `POST /api/technique/armed/{id}/mode`) also accepts `premiumBudget` and
  `riskPct` so an armed plan's sizing can change in place for its NEXT entry — no re-arm (a re-arm resets the
  read's seen-events and, in auto mode, would re-act on the day's earlier fires). Open trades keep their fills.
- 2026-09-04 · Post-close audit, shared-engine changes (default-neutral for EM/tips unless noted): the ~2 s premium
  stop and `_trade_unrealized` use an option quote only when it is FRESH real-time (`stale_seconds`, not
  `delayed`) — a stale positive bid could market-sell a live position; `disarm()` parks a retired plan's net
  P&L in `_retired_pnl[(day, portfolio)]` so `_maybe_technique_loss_halt` cannot loosen after a disarm;
  `Trade.to_dict`/`_restore_trades` carry `isAdd`/`targetKind`/`livePct`; `set_mode` re-derives the loss halt
  on a budget change too; `execution.premium_stop_basis`, `execution.premium_stop_min_ticks` and
  `execution.fee_per_contract` have DEFAULTS so any technique may set its own; `armed_summary` ORs
  `windowOpenNow` across runners and reports `windowOpenBy`; `Trade.stop` for Team2 is the entry's line
  minus one ATR (the quote watch is a crash brake, not the rule); Alpaca skips Yahoo's 09:30 context poll
  for the day range. Team2-only: `_reprice_stuck_exits` every RTH minute and a clock flatten at
  `flatten_min` + on `_end_session` — techniques that override `_on_bar` MUST re-provide the stale-exit
  re-price and a flatten of their own; `_manage` is not inherited by an override (invariant).
- 2026-09-04 · **`PlanRunner.disarm` no longer orphans an in-flight flatten** (F40): a disarmed plan whose exits
  are still working moves to `_closing`; `on_order_update` consults it, and `_persist` drops it once every
  exit has settled (`closing_settled`). Before, the fill arrived ~2 s after `_armed.pop` and was lost —
  the plan's record said "open, 18 left" forever while the book was flat. Applies to EM/tips too.
- 2026-09-04 · `OptionsService.refresh_tracked` drops contracts past expiry from the OPRA batch (F44); the
  nightly `research.snapshot_chains` sweep is paced (`research.chain_snapshots.delay_s`, `retries`) and
  retries CBOE 429s with backoff, reporting `rateLimitedRetries` and warning when > 20% of the universe
  failed (F45: 185 429s in three minutes had halved Flow's universe for five sessions).
- 2026-09-04 · `PlanRunner._score_execution` is a hook a technique may override (Team2 does: its read has no
  TriggerTrackers, so the shared scorecard was structurally empty — F43); a technique may also score on its
  own disarm path.
- 2026-09-04 · Shared-engine changes from the Team2 watch findings (all default-neutral for EM/tips):
  `events.TECHNIQUE_PLAN_READ` (a structural read is not a skip — F28); `exits.premium_stop_breach` takes a
  `basis` price and a `min_ticks` floor, and PlanRunner resolves `premium_stop_basis` (bid | mid, default bid)
  and `premium_stop_min_ticks` (default 0) per technique via `rt()` (F30 — Team2 uses mid + 3 ticks); both
  loss halts read realised P&L NET of commissions (`_fees_paid`, F32); an auto entry whose premium-stop risk
  exceeds what is left of `daily_loss_limit` is refused before routing (`skip_loss_budget`, F33); the
  premium-targeted picker `options/pick.select_by_premium` gained `mode="closest"` (F36; the legacy walk is
  `first_under`). `techniques.<id>.premium_stop_basis` / `premium_stop_min_ticks` are the knobs.
- 2026-09-07 · **The loss ladder, as one table** (user decision; the numbers nest — a technique always hits its own
  wall before the book's, and the book breaker is the catastrophe stop above any single budget):

  | layer | key | practice value | before real money |
  |---|---|---|---|
  | Team2 day-loss pause | `techniques.team2.daily_loss_halt_pct` | 10% | 3–4% |
  | EM day-loss pause | `techniques.enhanced_market.daily_loss_halt_pct` | 10% | 3–4% |
  | Tips day-loss pause | `techniques.tip.daily_loss_halt_pct` | 10% | 3–4% |
  | Options Cartel | `techniques.options_cartel.daily_loss_halt_pct` | 0 (off — its author relies on the book) | its author's call |
  | Book breaker (per portfolio) | `risk.daily_loss_halt_pct`, scope `portfolio` | 15% | 8–10% |
  | Global kill switch | HALT button / Telegram | manual | manual |

  Rule: book breaker > max(technique budgets) and < their sum. Per-plan dollar halts sit under all of it.
- 2026-09-04 · **Halts now come in three scopes** (built the same afternoon; was: one global switch that a
  Practice-book loss from one technique engaged for every technique on every book, re-engaging on release):
  1. **Global kill switch** — the HALT button, Telegram `/halt`, or the daily-loss breaker when
     `risk.daily_loss_halt_scope=global`. Unchanged: stops every new buy everywhere; exits still pass.
  2. **Per-book halt** — `risk.daily_loss_halt_scope=portfolio` (the new default): the daily-loss breaker
     halts ONLY the losing book (`HaltState.books`, `Engine.engage_book_halt`, journal `BookHaltEngaged`),
     RiskGate refuses entries on it (`book_halt`; reduce-only exits pass under `risk.halt_allows_exits`),
     every other book keeps trading. Auto-released at the next ET session, or `POST
     /api/portfolios/{pid}/resume`. Shadow books never halt (the learning record keeps collecting).
  3. **Per-technique, per-book halt** — `techniques.<id>.daily_loss_halt_pct` (→ `execution.daily_loss_halt_pct`,
     0 = off): `PlanRunner._maybe_technique_loss_halt` PAUSES all of that technique's plans on the book
     once its realised + open-at-bid loss across them crosses the % of the book's equity (journal
     `TechniqueLossHalt`, event `technique_loss_halt`). Resume per plan, or the plans expire with the day.
  Runners ask `engine.trading_halted(portfolio_id)` before a fire — never `halt.engaged` directly. The
  per-plan dollar loss halt (`_maybe_loss_halt`) is unchanged and sits below both. Rationale: the unit of
  a daily-loss rule is the book the money sits in; the unit of "this method is having a bad day" is the
  technique. The old behaviour is one setting away (`scope=global`). `tests/test_book_halt.py`.
- 2026-09-04 · `execution.planrunner.Trade` gained three technique-owned annotations: `is_add` (a scale-in that
  rides the same contract as its base trade — Team2 X5), `live_pct` (the contract's fee-adjusted premium % from
  its own fresh bid) and `target_kind` (planned level vs running high/low of day). Defaults keep EM/tips
  byte-identical. Pattern for scale-ins on the shared runner: a SECOND Trade through the ordinary fire chain
  (RiskGate inside, never-chase cap) — never a quantity edit on a live Trade, never a bare executor call.
  Premium-% trims in Team2 money modes are judged on the contract's live real-time bid before the model's
  forecast (delayed chain rows never drive money — same line as the premium stop, 2026-09-02).

### Cartel scheduled jobs (2026-09-07)

Cartel attachment registers only its three options_cartel_* names on the existing
scheduler (09:05/20:10 recovery, 20:15 research). New owned settings are
techniques.options_cartel.scan_enabled, scan_symbols, scan_profile,
scan_direction and recovery_enabled. Both switches default false. Recovery
selects only held Cartel adapter positions and can lead to managed reduce-only
catch-up exits; nightly scans save research and never arm. Other techniques'
job registrations, defaults and scheduler once-per-day semantics are unchanged.

### Optional Markdown links for Cartel documentation (2026-09-07)

The shared Markdown renderer accepts an optional renderLink callback. Its default
rendering behavior remains unchanged for other techniques. Cartel opts in for
its bundled method library, routing known chapter names internally and allowing
only HTTP(S) external links; unsupported protocols remain plain text. No raw
HTML is inserted and no arbitrary filesystem path is served by the backend.

### Existing loss-halt contract and test scope (2026-09-07)

Registered TechniqueLossHalt version 1 with the shared runner's existing payload
fields: technique, portfolioId, lossToday, equity, pct, plans. This adds missing
schema coverage; emission and trading behavior are unchanged. The daily-loss
regression now checks both configured portfolio and global scopes, including
unrelated-book behavior. The default remains portfolio; no risk setting or
other technique's trading rule was changed.

### Service task ownership during shutdown (2026-09-07)

A focused PostgreSQL test reproduced TechniqueService.stop returning while its
startup restore still held a table lock. The service now retains restore and
orphan-sweep task handles, cancels and awaits its research/sheet/startup tasks,
then stops the armer. This is lifecycle cleanup only: no method thresholds,
entry/exit rules, portfolios or routing settings changed. The test verifies the
transaction is released by acquiring an exclusive table lock after shutdown.
The observed full-suite stale connection remains documented separately; this
reproducer establishes the underlying cleanup defect, not a retroactive clean
result for that run.

### Shared quote-summary transport (2026-09-07)

EventCalendar exposes its existing anonymous Yahoo quote-summary request/refresh
mechanics for other read-only consumers. Calendar parsing and caching still use
calendarEvents; Cartel requests price/assetProfile separately and normalizes its
own dated fundamentals evidence. No broker credentials are involved, no industry
mapping is inferred, and provider session tokens are excluded from captured data.
The calendar/platform regression selection passed with the shared transport.

### Cartel option observations (2026-09-07)

Added `options_cartel_quotes` as a Cartel-owned append-only observation table,
separate from nightly option-chain research. Capture is an explicit authenticated
Cartel plan operation using an existing QuoteCache entry. It does not subscribe,
request broker data, arm, place orders or change another technique's rules.
Provider `source_ts` is preserved independently of local confirmation and capture
times; missing provider time remains null. Delayed/halted flags, sizes, source
and feed mode are retained. Repeating the identical observation is idempotent.
The standard metadata creation path provisions this additive table; tests use
only zargar_test_codex. Interactive database provisioning/preview acceptance is
still pending. No continuous recorder is enabled by this change.

Continuous recording follow-up: CartelRuntime now samples only selected option
contracts on active Cartel proposal/auto plans (including paused/closing state).
`techniques.options_cartel.record_option_quotes` defaults false. One background
batch at a time and a five-second minimum interval prevent a queued tick backlog;
shutdown cancels and awaits the recorder independently of order tasks. Errors
surface through the recorder status and do not interrupt execution. The desk has
an explicit save/refresh control. The additive table was provisioned only in
zargar_dev_codex after verifying empty execution state. Recording remains off in
the interactive preview. Other techniques and runtime databases were untouched.


### Cartel readiness and coverage review — 2026-09-08

Cartel's new preparation readiness checks precede its existing arming and common
order/risk path. Bounded recovered minute history seeds only its own plan, with the
new observation cutoff intact. No historical crossing is replayed as an order.
Decision explanations survive recovery and are journaled as Cartel state changes.
ETF coverage, industry interpretation and research variants are Cartel-owned;
other techniques, book routing, loss guards and protective exits are unchanged.
Details: techniques/options-cartel/FIDELITY-REVIEW-2026-09-08.md.


### Per-technique LLM run caps count only that technique's runs — 2026-09-09

`technique.max_runs_per_day` is EM's LLM budget, but `TechniqueService.runs_today()` counted
every row in `technique_runs` since UTC midnight. On 2026-09-08 the Options Cartel desk's
nightly scan wrote 5,557 deterministic runs at 23:00 ET (trigger `manual`, no model calls)
and EM's evening review of the 09-09 sheet (119 setups) was refused with "daily run cap
reached (600)"; no EM plan was armed for the session until the user was told. Fix: the count
is scoped to `technique == "enhanced_market"` (test
`test_daily_run_cap_counts_only_this_techniques_runs`). Rule for every desk: a cap that
bounds spend is scoped to the technique that spends; shared tables are not shared budgets.
The cap itself is a user knob - the desk does not raise it on its own.

### Cartel market-blocked research — 2026-09-08 (0.7.14)

Preparation may retain research candidates while its market gate blocks trading.
Their screen/plan context remains failed: research eligibility is a separate field,
not an override of the trading gate. They are stored as analysis records, never
submitted to contract selection, plan arming or the pending-contract activator.
Fresh aligned preparation is required. No common risk or execution rule is relaxed.


### The deploy task must be ASCII and must hold the watchdog off — 2026-09-09

Two engine-hosting findings from the first `schtasks /Run /TN ZargarRestart` deploy
(2026-09-09 01:17-01:30 ET, the EM desk deploying the run-cap fix):

1. **The task ran nothing.** `ZargarRestart` now invokes `scripts\restart.ps1` under Windows
   PowerShell 5.1, which reads a BOM-less UTF-8 file as ANSI; the em dash inside a string
   literal made the whole file a parse error ("The string is missing the terminator", exit 1,
   red text in a console that closed itself). The engine kept running on the old code. Rule:
   scripts that a scheduled task runs are ASCII only (comments included - a mangled comment is
   harmless, a mangled string literal is a dead deploy). `restart.ps1` is ASCII now; the other
   scripts carry non-ASCII only in comments and run under pwsh 7 (UTF-8 by default).
2. **The watchdog started a second engine inside the restart.** The engine is silent on
   /api/health for ~45 s while it restores; the 3-minute `ZargarWatchdog` tick landed in that
   window and ran `start.ps1 -Detach` again. Two engines ran restore, sim-book restore and every
   scheduler on one database for four minutes; health did not answer for two of them; the
   duplicate exited only when uvicorn failed to bind :8420. Fix: `restart.ps1` stamps
   `logs\watchdog.lock` before it stops anything - the watchdog already skips a tick while that
   lock is younger than 180 s. Symptom to recognise next time: two `python -m zargar.main` pairs
   in the process list, `process starting` twice in the log, one `engine started`.

Also observed: the Task Scheduler reports `ZargarRestart` as still running (267009) for as
long as the detached engine it started lives - that is the job object, not a hung script.


### Twelve market-hours restarts and a bar-delivery stall — 2026-09-09 (EM desk, EOD)

Evidence from `backend/zargar-8420.log` and the events table. The engine restarted at 10:14,
10:47, 11:06, 11:26, 12:26, 12:31, 12:33, 12:36, 12:54, 14:11, 15:33 and 16:09 ET - every one a
desk deploy (PR merges #33-#47, 0.7.22 -> 0.7.33), four of them inside ten minutes at 15:26-15:36
ET. Each restart re-armed 54 EM plans plus Tips/Team2/Cartel, re-read opening bars, reset entry
windows and dropped whatever fire -> critic -> order chain was in flight; the 15:35 ET restore
check reported an armed-list MISMATCH. Separately, at 15:10 ET **49 EM plans journaled "stale
bars"** (no closed bar for 180 s) while the `bars` table shows 180 symbols persisting 1-minute bars
straight through the close - the bars were written but stopped reaching the plan runner around
15:07 ET (the Alpaca stream dropped at 15:15 ET and reconnected; the 14:11 ET deploy was 0.7.29,
F79/F80 bar provenance). Between the stall and the restart burst, EM's prime_close window
(14:45-16:00) was effectively not traded.

User decision (2026-09-09 20:50 ET): **deploys during market hours are allowed - this is an
active app - but a deploy must lose nothing except the restart seconds, and the count should be
3-4 a day, not twelve.** What already delivers that (0.7.30, deployed 15:26 ET the same day, so
most of today's twelve restarts ran without it): `restart.ps1`/`start.ps1` call
`POST /api/ops/quiesce` (no NEW fire chains for 5 min), `GET /api/ops/restart-check` (refuses
while a fire chain, an in-flight order or an unknown inventory is pending, unless `-Force`),
capture `GET /api/ops/state`, and after the start `POST /api/ops/restore-check` compares armed
plans, open trades, working entries, pending exits, resting orders and managed positions by id.
On the EM side a restored plan re-reads today's bars (interior minutes recovered from history),
replays them into the trackers with `journal=False`, then applies the live-persisted record
over the replay (statuses, fired timestamps, critic kills, refire cooldowns, trades); the sim
book and managed positions are restored separately. The one residual loss is by design: a level
touch that happens INSIDE the restart gap is not fired late (acting on it a minute later would
be chasing) - the trigger keeps waiting for the next touch. Rule for every desk: deploy through
`ZargarRestart`, never `-Force` during the session unless the readiness reasons are understood,
batch merges into as few restarts as possible, and treat a `restore check MISMATCH` line as an
incident to explain the same day (15:35 ET today is unexplained).
Still proposed:
2. **A restart is a journaled event with a reason** (`ScheduledRestart` payload: version, desk,
   why) so the review can attribute lost state.
3. **Bars written are bars delivered**: the feed desk should add a watchdog line when persisted
   1-minute bars advance while `PlanRunner.last_bar_ts` does not (the "stale bars" journal is the
   symptom, 49 at once is the signature).


### Shared knob: `execution.critic_mode` — 2026-09-09 (EM desk)

`PlanRunner._fire_rest` reads `critic_mode` through `rt()`: `veto` (default, unchanged behaviour
for every technique), `momentum_only` (a reviewer "no" on a `bounce`/`reject` trigger is advisory:
logged as `critic_advisory`, `Trade.critic_advisory=True`, the entry proceeds; breakout/breakdown/
wedge_break are still vetoed), `advisory` (never blocks). The verdict is journaled on the
TriggerFired event either way. EM sets `techniques.enhanced_market.critic_mode=momentum_only`
(TRADING-RULES §5 2026-09-09); Tips/Team2/Cartel are untouched.


### Cartel preparation and history provenance — 2026-09-10

Shared history accepts an optional `refresh=True` to bypass its response cache;
existing callers retain their current cache behavior. Cartel uses it only for
one stale SPY/QQQ retry. Preparation preserves existing campaigns and counts
armed, paused, closing and held campaigns before adding automatic arms. This
changes no shared execution or risk thresholds. Regression coverage is in
`test_options_cartel_preparation_safety.py`.
