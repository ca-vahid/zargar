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
   scripts are ASCII (Windows PowerShell 5.1). "No open positions" is not a restart test. Door details since 2026-09-15:
   the engine runs UNELEVATED and `start.ps1` refuses an elevated shell (exit 8; assistant shells ARE elevated) — an
   engine booted elevated is stopped only by the user's elevated `stop.ps1`; `restart.ps1` writes its transcript BEFORE
   taking the deployment lease and waits up to 300 s for a held one (exit 7 names the owner); a build already equal to
   HEAD exits 0; the restoration comparison is SKIPPED when the pre-stop inventory capture times out — the deployer
   compares armed / resting / managed counts by hand.
19. **A source's own-book narration is research, never permission** (KFIN-08, 2026-09-14). A source enrolled in
   `techniques.tip.mk_ownbook_sources` (Meet Kevin) narrates its OWN trades; "I bought / added / sold half" from it is
   classified (`techniques/tip/ownbook.py`: own_open / own_exit / recap / hypothetical / third_party, deterministic text
   first, extraction `actor`/`activity` second) and in `shadow` mode routed to a DEDICATED shadow book (`kind=shadow`,
   `book=ownbook`) BEFORE the immediate book, the analyst, any proposal or armed plan - `techniques.tip.allow_live_auto`
   and the Practice gates are never consulted because that path is never entered. A disclosure without a grounded price
   (shares) / contract (strike + expiry) or without a qualified quote at the decision stays `ownbook_unresolved`
   (journaled `TipOwnBookClassified`, nothing back-filled); recaps, hypotheticals, other people's screenshots and exits
   with nothing to reduce are `ownbook_context` and never open. Grading (`GET /api/tip/ownbook/{source}`) uses the quote
   at the decision + our own fill inside the DECLARED cohort (`mk_ownbook_cohort`); the `mk_ownbook_min_*` criteria are
   reported, never acted on - promotion is a human verdict with no calendar deadline. Default mode `off`; guard tests in
   `tests/test_tip_ownbook.py`.

21. **One day anchor, durable, and every "today" figure measures from it** (2026-09-14).
   This ET day's opening equity is `PositionKeeper.day_start_equity(pid)`: the last PERSISTED
   equity point before 04:00 ET (the previous session's close - the basis every broker quotes a
   day change on, and the one `CLAUDE.md` already states for prices), else the day's first
   sample, else live equity once quotes are real. It is published as `dayStart` next to `equity`
   on `/api/portfolios`, the engine snapshot and every 30 s portfolio push, so no client derives
   its own. Nothing may measure "today" from a chart array - those are session-filtered, thinned
   and flat-collapsed, and the baseline moved on every reload. The anchor was previously
   in-memory only and seeded with "equity the first time we looked today", so a mid-session
   restart re-based the day at the restart price and the daily-loss halt forgot an existing
   drawdown. A broker sync is a LEVEL-SET and shifts the anchor by exactly what it level-set:
   cash that moved plus holdings that appeared or vanished, valued at the book's own mark -
   never by `equity_after - equity_before` (that difference also carries a currency
   correction, a broker mark replacing a fallback, or a tick between the two reads; 95 syncs
   of it manufactured +1,560 of anchor on a C$4,000 book, 2026-09-15). Every shift is journaled
   as `DayAnchorShifted` {day, delta, cashDelta, holdingsDelta} and a process that starts
   mid-day replays them onto the persisted point. Tests: `tests/test_day_start_equity.py`.
22. **A position is valued on a market, not on a print** (2026-09-14). An OPTION marks at the mid
   of a two-sided quote (`bid > 0 and ask >= bid`); a lone `last` is the fallback for a one-sided
   book, then the broker's sync mark, then avg cost. Shares are unchanged - an equity print IS
   the valuation. One definition (`PositionKeeper._mark`) serves both the displayed P&L and the
   equity the risk halt reads, so they cannot diverge. Callers that hold a LOT rather than a
   position (the Ledger's FIFO lots) use `PositionKeeper.mark_price(symbol, sec_type)` - the same
   rule - never a quote field of their own. Thin contracts otherwise write permanent
   fiction into `equity_points`. Tests: `tests/test_position_marking.py`, `tests/test_ledger_day_move.py`.
23. **Downsampling preserves range** (2026-09-14). `equity_series(points=N)` and any client
   thinning keep each bucket's min and max in time order (`portfolio._decimate`), never every
   Nth sample - a real intraday extreme must not depend on where the bucket boundaries fell.
   Tests: `tests/test_equity_series.py`.

## 2. Findings (settled, with evidence)

### Cartel final-dispatch entry authority — 2026-09-13

OrderManager.place accepts an optional server-only synchronous before_submit guard,
called after the last SUBMITTED persistence and immediately before executor dispatch.
Cartel uses it to recheck saved contract limits/current underlying geometry after all
order-manager waits. Failure is a known, journaled REJECTED_RISK with no executor call;
it is not an ambiguous broker response. Callbacks are never serialized in order DTOs.
Reduce-only exits bypass entry-only guards; other callers retain their existing path.
Regression evidence: test_options_cartel_contract_integrity.py mutates quotes/delta
during risk evaluation and the submission transition, and checks protective exits.

Cartel's explicit legacy-arm review is a guarded configuration revision: only unused
automatic Practice arms; config and current policy must still match under the row lock.
Held campaigns retain their snapshots. Preparation capacity joins managed positions by
their actual config.runId, never a nonexistent model column, and reserves unlinked holdings.

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

- **2026-09-16 · Cartel Practice contract reselection retains execution authority.**
  One bounded spread-only search may change only an automatically prepared sim
  arm's contract identity before any submission reservation. Saved limits and
  signal freshness remain authoritative; the controller reruns full preflight,
  reconciliation and final dispatch checks. Other techniques, Live and proposal
  approvals do not use this path. Research entry variants remain non-executable.


- **2026-09-16 · Reviewed source and process identity remain separate.** Integrating
  a desk's previously deployed branch into main preserves the launch-bound build
  helper. A tolerant health response with build `unknown` prevents a missing-helper
  500 but is not verified deployment identity. Preserve unrelated dirty research
  files for their owner; do not commit or discard them to satisfy a clean-source
  guard. Cartel's current handoff documents full-artifact and restoration checks.


- **2026-09-15 · Cartel profitability research has no trading authority.** The
  Practice collection switch and bounded pool controls live under
  `techniques.options_cartel.profitability_research`. Source/policy-frozen research
  contexts and observations use separate non-plan run modes; they never become
  executable arms, approvals or orders. The authenticated research read endpoint
  is account-scoped and empty in Live. Candidate rankings, bearish cohorts and
  exit comparisons do not modify the production market gate or existing saved
  campaigns. See [the protocol](techniques/options-cartel/PROFITABILITY-RESEARCH.md).

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
  technique. The old behaviour is one setting away (`scope=global`). `tests/test_book_halt.py`. **A fourth scope
  since 2026-09-15: the per-book PAUSE** (`HaltState.pauses`, `engine.pause_book`) — no day boundary, survives restart,
  released only explicitly, independent of the three above; `tests/test_book_pause.py` and the entry below.
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



### Shared exit knob: scratch rule — 2026-09-10 (EM desk, T-14)

`MarketRules.scratch_r` / `scratch_trim` (default 0 = off). When a filled trade is `scratch_r` R in
favour and no target has been hit, `exits.plan_exit` returns a `scratch` decision: the runner sells
`scratch_trim` of the position (0 when the position cannot be split - a single contract keeps its
size and only earns the breakeven stop), moves `trade.stop` to the entry and persists
`trade.scratched`. `outcome.simulate_plan` mirrors it (`scratch_r=`, outcome `scratched`), so
sweeps and live behave the same - change one, change both. Every technique reads it through its
`rules()`; only EM plans to turn it on, after its sweep (TRADING-RULES T-14).

### Team2 picker gates and the EM scorer boundary — 2026-09-10 (Team2 desk, evening; v0.7.43)

Codex's Thursday investigation (`C:/Cursor/zargar-codex/docs/techniques/team2/notes/research/2026-09-10-thursday-investigation.md`,
probes adopted verbatim as `backend/tests/test_codex_thursday_picker.py`) confirmed two entry-path defects and two
inconsistencies; all four are fixed in this release, Team2-only except one line:

- **Listed contracts are the ladder.** `techniques/team2/premium.otm_ladder` walks the venue's listed strikes when the
  plan carries `listedStrikes` (the runner stamps today's chain listing at the first bar); the synthetic grid is the
  stated fallback (`strikeSource: grid`). History has no as-of listings, so sweeps say `grid`.
- **The series that fills decides.** `Team2Runner.pick_contract` re-prices the nearest `quote_candidates` listed
  contracts on the live NBBO (`OptionsService.reprice`) BEFORE the premium band is judged; the delayed chain only
  bounds the quote requests. Refusals name every candidate examined and which series spoke. No change to
  `options/pick.select_by_premium` or to EM's picker.
- **One warm-up rule** (`Team2Service.warmup_slice`, last `warmup_sessions` valid sessions) for live/replay/sweep,
  stamped by content hash on the plan (`plan.warmup`); replay reports `warmup.match`.
- **EM's outcome scorer scores EM's runs only** — `TechniqueService.score_pending` gained
  `TechniqueRun.technique == "enhanced_market"` (one line in `zargar/technique/service.py`). It had been adopting
  every `team2` and `tip` plan run (F107). EM's owner decides what to do with the rows already written; this desk
  changed nothing else in EM.
- **Not changed:** near-ITM/ATM eligibility (OTM-only stands until the user decides), the model band, `strike_step`
  as a knob (now fallback-only), any shared risk threshold.
- **Operational (F89, still open):** the engine serving 0.7.42 was started ELEVATED at 18:21 PT on 2026-09-10 with five
  managed positions and ten resting orders app-wide; the Limited `ZargarRestart` task cannot own it. The handoff is
  the user's: `scripts\stop.ps1` from the elevated terminal after the readiness check says clear, then
  `schtasks /Run /TN ZargarRestart`. Codex is right that `stop.ps1`'s own check is narrower than the restart door —
  run `GET /api/ops/restart-check` first and do not stop with open managed positions in a money mode.

### Team2 contract authority — 2026-09-10 late (v0.7.45, Codex PR #57 review)

Codex reviewed v0.7.43 and showed the model and the delayed chain still vetoed ahead of fresh pricing. On the Team2
live path the contract authority is now the live NBBO alone: the read fires on a model proxy when nothing models in
band (`plan.contractAuthority = quotes`), `Team2Runner.pick_contract` selects on NO delayed price (listed OTM contracts
nearest spot, quoted live one by one, early stop on a fresh ask under the floor), and a contract without a live quote
is never eligible — `contract_deferred` vs `contract_refused` are distinct verdicts with `examined`. Sweeps and history
keep the model gate and state it. Nothing shared changed: `options/pick.select_by_premium` and `OptionsService.reprice`
are unmodified; EM's picker untouched. `test_codex_pr57_review.py` is Codex's regression file verbatim.

### Journal kind `TechniquePlanContract` — 2026-09-10 late (Team2 desk, v0.7.46)

One new event kind in `events.py`: a technique's contract verdict (`picked | deferred | refused`) with every contract it
quoted (`examined`: strike, delayed ask, live bid/ask, series, eligibility), journaled under the plan run. Team2 writes it
from `pick_contract`; other techniques may adopt it, none is changed. Team2 also journals `listing`, `warmup`,
`model_out_of_band` and `target_replanned` as `TechniquePlanRead`. Rationale: the user's cohort-v2 instruction — the
candidate → quote → order → fill → exit trail must be on the append-only record, not only in the plan's capped
in-memory events.


### Shared knobs from EM's C1-C5 (2026-09-12) — all default off / EM-only

`MarketRules`: `gap_day_pct` / `gap_day_wait_minutes` / `gap_day_continuation` (the tracker judges a
gap day on the symbol's own open vs previous close and holds entries for N minutes; a gapped
bounce/reject may re-aim as a continuation break), `scratch_only_far_tp1` / `far_tp1_r` (the scratch
rule only when TP1 is far), `range_break` / `range_break_bars` / `range_break_max_range_mult` (a
break out of an N-bar squeeze fires on the break close, volume floor only). `exits.plan_exit` and
`outcome.simulate_plan` take the scratch knobs - change one, change both. `technique/options.py::
pick_for_setup(retry_wide=, max_spread_pct=)` tries the next strike out and the next expiry when
the just-OTM strike's spread is wide and keeps the tightest (`pickRetry` on the pick). EM-only:
`technique.universe.option_liquidity` (nightly `em_option_liquidity` job at 16:40 ET from the
chain snapshots; `max_spread_pct` 12, `min_oi` 500), `technique.universe.untradeable` (shares |
skip | ignore, applied in `TechniqueService.arm_plan`), `techniques.enhanced_market.entry_fallback
= shares`, `technique.arm.preopen_keep_triggers` (the re-plan carries the evening triggers as
`e_<id>`). Tips/Team2/Cartel are untouched.


### A burst of LLM runs wedges /api/health and the watchdog restarts the engine — 2026-09-13 (EM desk)

Second occurrence (first 2026-09-09 21:31 ET): 102 `walkforward/{sheet}/promote` reads submitted
within a minute; `/api/health` stopped answering within 3 s; `ZargarWatchdog` read DOWN, `start.ps1`
first refused (exit 2, runs in flight) then on the next tick stopped the engine (pid 172936) and
started a new one, killing every read. Nothing in the engine limits concurrent technique runs.
Rules: (1) callers submit by the engine's in-flight count (`local.techniqueRunning` < 8), which the
EM desk's batch now does; (2) proposed platform fix - an engine-side semaphore on concurrent LLM
runs (`technique.max_concurrent_runs`, default 8) so a UI "Check & arm" on 100 rows cannot do the
same; (3) the watchdog should require two consecutive silent ticks before it restarts a process
that is still alive (a slow engine is not a dead one).

### Cartel source quality and preparation ownership — 2026-09-12

Cartel uses an additive, source-bearing minute representation; shared Bar.to_row()
remains six values. New Cartel plans can require exchange-quality entry/stop
history; legacy unknown source is not relabelled. Corrections are context-only
and cannot revive a consumed entry. Existing positions retain protective exits.
Additive cartel_history_cache, cartel_ignition_theses and cartel_preparation_leases
tables are created through the existing schema path. Capacity uses a portfolio-keyed
advisory lock; preparation has a renewable lease checked before new arming.
Native daily batching is opt-in with its provider-day completion semantics and a
separate cache. No other desk switches provider or loses its shared API behavior.
See options-cartel/RELIABILITY-RELEASE-2026-09-12.md for scope and limits.

### Request: one tape for Team2 (F119, C6) — 2026-09-13 (Team2 desk → platform owners)

The other team's review of the week-37 plan made this a prerequisite: every Team2 sweep, replay and parity check scores
Yahoo's 1m bars while the live desk trades Alpaca's stream (F119: both stamped `source: exchange`, last writer wins,
QQQ differs on 40 % of minutes). No Team2 rule change will be activated on the strength of a sweep-vs-live comparison
until one tape exists. Requested, as F119 option (a): a per-venue provenance value (`exchange:alpaca` /
`exchange:yahoo`, or a `venue` column) and Alpaca-over-Yahoo precedence in `marketdata.merge_exchange` /
`persist_bars` for streamed symbols, Yahoo filling only minutes Alpaca did not supply. Shared engine, platform's call;
Team2 will re-run the frozen-input sweeps on the canonical tape once it lands and record the new dataset hash.

### Shared execution changes from the Tips desk — 2026-09-10 → 09-13 (v0.7.44–0.7.54)

These live in `zargar/execution/positions.py` and affect EVERY technique's
managed positions; per-technique overrides resolve via `rt()` as usual.

- **Premium exits demand fresh, sane evidence.** Bar-path premium decisions
  use `_fresh_net_mark`: delayed/chain sources refused, quotes older than
  `execution.premium_mark_max_age_seconds` (90) refused, provenance appended
  to the exit reason (`[mark: opra 1s old bid=…]`). Tick-path premium stops
  (bleed AND ratchet floor) additionally need TWO DISTINCT fresh
  observations (source-timestamp identity — a re-polled cached quote never
  confirms) within `execution.premium_stop_confirm_window_seconds` (45);
  recovery resets, window expiry restarts. Underlying stop / expiry / DTE /
  reduce-only paths are untouched. Why: SPCX market-exited on an hour-stale
  0.97 mark while trading 2.02 (2026-09-10); DAL on a 1-second flash print
  that vanished before the fill (2026-09-11). Chaos-suite ratchet-floor
  cases now encode the two-observation contract.
- **FILLED exits are terminal in `_inflight_exit_qty`** — a venue-normalized
  fractional request (2.5 → filled 2) no longer strands a phantom remainder
  that blocks a position from going flat; terminal fills persist their
  normalized qty (`requestedQty` keeps the original).
- **`desk.ledger` exit reasons join by portfolio identity** — a same-time
  decision in another book renders "reason unmatched", never borrowed (a
  shadow plan's TP1 had been displayed beside a Practice option loss).
- **Tip-scoped, listed for awareness:** one bounded quote-freshness retry on
  REJECTED_RISK "quote age" for AUTO tip proposals on sim books only
  (`ProposalRetried` journaled; never manual, never live);
  `OptionsService.refresh_now()` (public, forces a real observation —
  `reprice()` re-reads the cache for served contracts); journal-only
  `TipEntryStudy` NBBO sampler; analyst per-turn output cap
  `techniques.tip.analyst_max_output_tokens` with doubled-room truncation
  repair.

### Premium-stop confirmation v2 — the SHARED contract (2026-09-13, Tips desk; applies to every technique's managed option positions)

`PositionManager` premium stops (bleed and ratchet floor) fire only on TWO
observations of the option evidence set that are FRESH (source age ≤
`execution.premium_mark_max_age_seconds`), DISTINCT and FORWARD-ordered,
paired inside `execution.premium_stop_confirm_window_seconds` (45):

- identity is the FULL per-leg `{symbol: source_ts}` set — a changed leg set
  (partial fill / roll) restarts the sighting rather than pairing unlike
  evidence; absent identity never confirms;
- an out-of-order packet (any leg's source time behind the sighting's) is
  quarantined, not confirmation;
- the state is ONE across bar and tick paths — an underlying candle close is
  not a second option observation;
- recovery, any non-stop premium outcome, and position closure reset the
  pending sighting; a window expiry restarts it (logged
  `premium_stop_pending_expired`);
- the window bounds which observations may PAIR — it does NOT guarantee an
  exit within 45s when no qualifying second quote arrives (degraded data =
  visible standdown, never a blind exit);
- untouched: underlying-price stops, expiry/DTE flatten, reduce-only and
  every non-premium decision (a real underlying stop exits even while a
  premium confirmation is pending — covered by an independent test).

Affects EM, Tips, Team2 and Cartel wherever their positions run premium
policies through the shared manager; per-technique knobs resolve via `rt()`.
Independent reviewer reproductions live in
`backend/tests/test_premium_confirmation_review.py`.

### Existing Team2 contract-event registration — 2026-09-13

The integration check found TechniquePlanContract was emitted but absent from the
central event registry. Registered its existing v1 producer's common fields only;
optional stage/error/selected-contract fields remain optional. No Team2 strategy,
producer payload or risk setting changed. The journal registry invariant passes.

### Shared positions additions from the Tips desk: `Managed.extras`, `set_extras`, `widen_stop` — 2026-09-14 (geometry rev 2, branch `claude/tips-geometry-rev2`, review before merge)

- `Managed.extras` (persisted in `config.extras`, on `to_dict()` as `extras`):
  technique-owned facts on a durable position — the tips desk keeps the
  pre-entry `riskPlan` and a post-fill `geometryException` state machine there.
  The policy evaluator never reads it; other techniques may use their own keys.
- `PositionManager.set_extras(pid, patch)`: merge + persist, no journal of its own.
- `PositionManager.widen_stop(pid, new_stop, *, reason)`: the ONE way a live stop
  gets WIDER. `set_policy` still only tightens (`state.stop` moves only in the
  protective direction); `widen_stop` is refused on adapter positions and when the
  stop is not actually wider, logs `stop_widened`, journals
  `ManagedPositionPolicyChanged` with a `widened {from, to, reason}` block and
  re-arms the venue stop. A caller must have EARNED the widen (tips: the
  trim-first sequence confirmed its trim). Invariant: no other code path widens
  `state.stop`.
- `TipGeometryRepaired` gains `phase` values `pre-entry | submit | post-fill |
  post-fill-exception | post-fill-legacy`; the registered required fields are
  unchanged (`proposalId` stays nullable).
- Default behaviour is UNCHANGED for every technique: the gate knob
  `techniques.tip.geometry_gate` ships as `shadow` (compute + journal only).

### Shared position additions from the Tips desk, round 2 — 2026-09-14 (readiness review of PR #91 / #93; combined tree PR #95)

- `PositionManager.widen_stop(pid, new_stop, *, reason, max_qty=None, unit_loss=None, budget=None)`
  runs under the ordinary `position_guard` for EVERY position (not only adapters), re-reads the
  actual remaining quantity and status, refuses when a protective exit (stop / premium_stop /
  quote_stop / venue_stop / bleed) is in flight, when the remaining quantity exceeds `max_qty`
  or when `remaining x unit_loss > budget` (one cent of rounding slack), PERSISTS the transition
  before exposing the wider stop, and reverts the in-memory + persisted stop on a persistence or
  journal failure. Caller assurances are never trusted.
- `PositionManager.close(..., evidence: dict | None = None)`: an optional STRUCTURED evidence
  record that rides on the exit records the close creates (`confirmation` for a premium stop,
  `evidence` otherwise). The bar and tick premium-stop paths pass
  `_premium_confirmation_record(p)` — `{confirmed, observations: [{at, sourceTs}, {sourceTs}], mark}`
  derived from the confirmation-v2 state. Prose in the exit reason is not evidence.
- Exit records gain `filledTs` (the fill's arrival on `on_order_update`), distinct from `ts`
  (the intent's time). Consumers that need actual execution times read the `executions` table
  first (`techniques/tip/integrity._fill_times`) and fall back to `filledTs`, never to `ts`.
- Both additions are additive and default-neutral for EM, Team2 and Cartel.

### Shared position changes, round 3 — 2026-09-14 (PR #95 final-pass corrections C95-01/03/04)

- `serialization.serialized_adapter` now serializes TIPS positions as well as opt-in adapters
  (the per-position guard is reentrant per task). Reason: `widen_stop` — the one
  exposure-increasing mutator — holds that guard, so the fill/close/policy mutators of the
  same Tips position must hold it too. EM / Team2 / Cartel legacy positions are unchanged.
- `PositionManager.widen_stop` has a STRICT durability contract: `_persist_candidate` writes
  the row with the candidate policy/stop without touching the in-memory position and raises
  on failure; the journal write raises; the wider stop is exposed only after both succeed. An
  unknown durable outcome is recorded in `extras.widenUncertain` and repaired to the tight
  stop by the Tips reconcile at restore. The legacy `_persist` / `_journal` (which swallow
  errors for non-adapter positions) are NOT used on this path and are otherwise unchanged.
- `PositionManager.close(..., attempt_tag=)` → `_close_leg` → `_submit_exit`: an optional
  durable attempt identity that rides on the venue order's `tags` and the exit record's
  `attemptTag` (adapters keep minting their own `managed_exit:` tag). Consumers recover an
  accepted order through that identity instead of assuming a missing local id means "not
  accepted".
- `_confirm_premium_stop` freezes the accepted observation pair at confirmation; the exit
  receipt's `confirmation` record is that immutable pair (C95-01). Contract unchanged: no leg's
  source time moves backward, at least one advances.
- `options/occ.contract_multiplier(symbol)`: 100 only for a standard OCC symbol; adjusted /
  unparseable contracts → `None` (unknown metadata; the tips geometry gate review-gates it).

### Tips activation in Practice — 2026-09-14 (v0.7.67 = main `b368e7e`, PR #95)

- `techniques.tip.geometry_gate`: `shadow` → **`enforce`**; `techniques.tip.entry_pause_mode`:
  `clock` → **`integrity`** (journaled `SettingChanged` 05:15:32Z; previous values were the
  defaults, no stored override existed). Practice only: `_geometry_scope` refuses a plan for any
  non-sim book; `techniques.tip.allow_live_auto` stays off, `trading.mode` practice.
- Shared-engine pieces that shipped with it (all logged in rounds 2–3 above): strict
  `Managed.set_extras(strict=True)` / `_persist_candidate`, `serialized_adapter` guarding tips
  positions, `close(attempt_tag=)` on the exit intent, `occ.contract_multiplier`, the
  `evidence:` note scope, event contracts `TipExecutionIncident` / `TipFastStopDiagnostic`.
- Rollback is the same PATCH back to `shadow`/`clock`; it never clears an incident row and never
  touches a position's stop — a rollback that needs those must release incidents on evidence
  (or a labeled override) and let `reconcile_geometry_exceptions` finish open exceptions.
- Knowledge: the two disputed kill-switch/geometry rules were released and superseded by the
  consolidation batches (receipts `consolidation-geometry-2026-09-14`,
  `consolidation-killswitch-2026-09-14`); the analyst's rulebook now states the incident-based
  policy in the same words the code enforces.

### Runaway stop loop on a scaled-in position — 2026-09-14 (v0.7.68, PR #98)

- **What happened:** APLD on the `🌟｜ab` ARMED SHADOW book (research, no money) held two
  same-symbol legs (35 adopted 09-09, 35 scaled in 09-10). At 04:00 ET the pre-market quote
  breached the stop; `close()` submitted one SELL per leg, but `on_order_update` attributed
  every fill to the FIRST leg by symbol — the second leg's fill flipped the first (already
  flat) leg back to +35, `open_legs` never emptied, `_mark_closed` never ran, and the quote
  watch re-fired every ~4 s: 3,282 stop exits, the book 37,625 shares short by the 08:23 ET
  pre-open tick (40,600 by the 08:34 deploy). The `🌟｜eva` shadow book's TSLA record (we
  hold 7, venue −5) is the same family from an earlier day, caught by reconcile as attention.
- **Fix (execution/positions.py):** an exit fill reduces every open leg of that symbol TOWARD
  FLAT and never past zero (a fill beyond the open legs is flagged, not applied); and a
  reduce-only exit never sells what the venue does not hold — when the venue line is flat or
  on the other side the stale leg is marked flat (or shrunk to the venue line) and a record
  whose legs were all stale closes on attention instead of looping. An UNKNOWN venue line
  (never seen / lagging live poll) never blocks a protective exit. Tests:
  `tests/test_exit_leg_attribution.py` (6, incl. the restored runaway record).
- **Invariant 20 — a reduce-only exit never takes the venue book through zero.** The
  in-flight guard (`_inflight_exit_qty`) is per symbol and the leg reduction must be too;
  any code that adds a leg for a symbol the position already holds (scale-in, partial-fill
  adoption, assignment) inherits this. Sim executors fill anything, so the invariant lives in
  the manager, not the venue.
- **Why the pre-open tick mattered:** no alert fired — every exit was a "successful" fill.
  The desk sweep now prints fills by book/symbol; a fill count out of proportion to the
  number of positions is the signal. The shadow books keep the short (research P&L only);
  resetting them is the user's call.

### The board showed red on a green morning — 2026-09-14 (Dashboard, v0.7.70)

- **Report (user):** "this morning even though i was up in total, i kept seeing red chart in
  color (for the total) ... i would refresh and it would go green and over and over", and "the
  rate of the refresh is too low. i kept updating the page to see new numbers."
- **Cause, two halves that compounded.** (1) The headline balance came from the store, which the
  30 s `portfolio` push keeps current; the MOVE beside it came from `sessionMove(pts)`, derived
  from the equity chart's own array. Nothing refetched that array — `useAsync` is fetch-on-mount
  — so a board opened during a dip was pinned to that dip's reading all morning while the number
  beside it climbed. Reloading refetched and the colour changed; reloading again during the next
  dip changed it back. (2) Even fresh, the baseline was wrong: `pts` is session-filtered,
  flat-collapsed and thinned, so "the first sample whose ET day is today" was whichever sample
  survived thinning, and the multi-book sum seeded each book's carry-forward with its first
  sample IN THE WINDOW — a sliding window that changed the early total as it slid.
- **Evidence.** Replayed today's session from `equity_points` (`scratchpad/replay.py`): the
  hero's own math went RED at 09:30 (−26.93) and GREEN by 10:00 (+101.02) off a 38,697.29
  anchor. Live, the move's "now" (38,807.71) and the headline (38,756.23) were $51 apart —
  two clocks, one panel.
- **Fix.** Invariants 21 and 23 above; the client follows the 30 s push (`store.equityTicks`)
  and re-pulls history every 5 minutes instead of once. The hero and the curve now read the
  same two numbers, and both match `/api/portfolios`.
- **Found on the way.** Two INTC 0DTE calls bought at $1.00 were marked near $7 by a single
  print at 09:35: +$1,406 (+14%) of equity for one sample, persisted, and it set the whole
  vertical range of the day's chart. That number feeds `daily_loss_pct` — the same print in the
  other direction halts a book that never lost anything. Invariant 22.


### Reviewer packet 2026-09-14, Delivery A — shared-runner corrections (EM desk)

Response: `docs/techniques/enhanced-market/reviews/DELIVERY-A-RESPONSE-2026-09-14.md`. Shared-runner changes,
all techniques: (FIX-01) `_enter` sets `trade.instrument` and `trade.multiplier` as one final decision - a
shares fallback is x1, options x100; HPQ 09-14 booked -$719.30 on a -$7.19 share trade and false-halted;
repair tool `tools/em_reconcile_fallback.py` (dry-run manifest, idempotent apply, `TechniqueTradeCorrected`
events, never edits originals, never resumes plans). (FIX-02) `exits.plan_exit` walks several rungs reached
in one bar for the one/two-contract full-exit policy. (FIX-03) options are re-priced on the NBBO BEFORE
sizing; the risk budget is a bound - zero contracts is a journaled `size_zero` skip; the old one-contract
floor is the opt-in knob `execution.min_one_contract` (default off; the tip technique's premium-budget floor
is unchanged). (FIX-05) `Trade.critic / critic_advisory / errors / retries` survive restore; new
`critic_disposition` (allowed | advisory | vetoed | timeout-allowed | error-allowed | not-run) persisted and
journaled on TriggerFired with `criticMode`. (FIX-11 policy) `quote_exit_polls` counts DISTINCT quote
observations by source timestamp - the same cached print cannot confirm a stop twice. Invariant added: **the
multiplier belongs to the instrument that was actually ordered, never to the instrument that was requested.**


### Reviewer re-review 2026-09-14 (DA-01..08) — shared-runner follow-ups (EM desk)

`_admit_option_entry` is the ONE admission function for option entries (warning skips, premium caps,
remaining daily-loss budget) and runs on the pick and again on the final price/quantity before dispatch;
method quality re-judgement is the hook `rejudge_contract` (generic: spread only via
`execution.spread_warn_pct`; EM: T5.4 + T5.3). `_manage` never advances a rung while an exit is pending.
Quote-stop confirmation is forward-only (source timestamp strictly newer). `execution.min_one_contract`
is registered with per-desk values (Tips/Team2/Cartel True = unchanged behaviour, EM False). `/api/health`
carries `build` (short commit SHA). Repair tool contract: receipt journaled before commit, one row
transition per plan, replay = `already_applied`, live rows skipped unless `--include-live` after quiescing.


### Reviewer follow-up 2026-09-14 (FA-01..05) — shared-runner and repair contracts (EM desk)

FA-01: entries pass a SYNCHRONOUS final guard (`PlanRunner._entry_guard`, via `OrderManager.place(before_submit=)`)
after the manager's last await and before `executor.submit`, on every attempt incl. the collar retry; it
re-judges the remaining daily loss budget and cached contract quality over the runner's own state and never
resizes (a changed quantity/price is a fresh submission). Rule for every desk that places entries through the
runner: state that can change during the order's awaits is judged in `before_submit`, not before them.
FA-02..04 (repair tools): repaired state and audit receipts are written in ONE transaction (`Event` rows staged
in the caller's session, row locked, hash re-checked); corrected values come from the Order/Execution ledger,
never from the projection; ownership is validated before any read; `--include-live` verifies nothing.
FA-05: a promotion's identity is the sweep's saved resolved thresholds + overlay + process version, never
"same overlay". Build identity: `zargar.BUILD` bound at import (full SHA, `-dirty`), on `/api/health.build`.

### Reviewer closure 2026-09-14 (FC-01) — the final entry guard judges the CURRENT quote (EM desk)

Rule for every desk placing entries through the runner: `before_submit` evidence is the quote cache NOW, not
a dict captured before the awaits. `PlanRunner._entry_guard` reads `engine.quotes.get(order_symbol)` and asks
the technique's pure synchronous hook `judge_entry_quote(ap, trade, contract, quote)` (`execution/entry_quality.py`:
two-sided uncrossed book, fresher than `execution.premium_mark_max_age_seconds`, spread within the technique's
limit when the arm skips wide spreads - generic `execution.spread_warn_pct`, EM T5.4 10%). FC-02 (same day): NO quote =
refusal; a delayed chain row = refusal when a real-time option source is configured; the freshness limit is the
ENTRY policy `risk.stale_quote_seconds`, never an exit-mark age; the captured warning list admits nothing. The repair tool `tools/em_reconcile_fallback.py` has one
code path (real session, row lock, receipts staged in the same transaction); fake-session test doubles are
historical reproductions, never production evidence (`tests/test_em_reconcile_real_session.py`).


### Order-free scenario candidates — 2026-09-14 (EM Delivery B, shared-runner boundary)

A run whose `config.origin` or tag starts with `scenario:` is a research record: `PlanRunner.arm` journals
`TechniqueArmRefused` (contract: runId, symbol, origin, reason) and raises, on EVERY path - API, restore,
retry, auto-arm - independent of settings, until an activation decision adds an explicit allow-list. The
check is `execution/origins.py::scenario_origin` (no technique import in the runner). EM's three new tables
(`technique_source_revisions` / `_artifacts` / `_jobs`) are EM-only (`technique/source_revisions.py`); the
gateway now forwards EM-channel EDITS to EM's inbox (`kind=update`) - the tips mirror/intake path is unchanged.


### Restart safety after the 17:37 health-500 incident — 2026-09-14 (EM desk, shared scripts/restart.ps1)

A process that ANSWERS /api/health with an HTTP error is a live, unhealthy engine, not an absent one: restart.ps1
now keeps the entry pause, before-inventory and readiness safeguards in that case (only a refused connection means
"no process"); it PERSISTS the before-inventory by id (`logs/restart-inventory-<ts>.json`) and reports `restoration`
= ok | mismatch | skipped-no-baseline on the deployment receipt (never inferred from counts alone); and it probes the
TARGET checkout (`python -c "import zargar, zargar.api.app; zargar.build_sha()"`) BEFORE stopping the running
process - a post-start file rewrite is not a loaded fix (exit 8; -Force is an override). Open for the watchdog
owner: bound repeated restarts of an unchanged deterministic import/health failure with an incident record.
Gateway: `MESSAGE_DELETE` on EM channels becomes an EM tombstone revision (`TechniqueSourceRevised`); the tips
mirror/intake never receives deletions; deletions never touch positions, exits or arms.


### Arm authorization boundary — 2026-09-14 (EM desk, shared runner, optional)

`PlanRunner.arm(run_id, config, authorize=None)` (forwarded by `TechniqueService.arm_plan`): an optional awaitable
awaited after every earlier await and immediately before the FIRST arm mutation. A caller whose authority can lapse
during the awaited preparation (EM's source-board attempt: its fenced lease and the source revision) raises there and
nothing is registered or persisted. No behaviour change for callers that pass nothing. Never used as a cleanup hook:
a refused arm disarms or flattens nothing.


### Order-free measurement hooks — 2026-09-15 (EM desk; shared runner, observation only)

`TechniqueTargetDistance` (target-distance-v1, journaled at fire and fill, never gates) is scoped per technique since
2026-09-15: `execution.target_distance_diagnostic=false` for every desk, `techniques.enhanced_market.target_distance_diagnostic=true`
- the Tips desk asked that its aggregates carry no EM research record after the shared runner journaled it on Tips fills.
`PlanRunner.on_quote_watch` CAPTURES (pure, no awaits) the first fresh underlying observation at or beyond a trade's
next production rung with the same-contract NBBO and hands it to a bounded background recorder that journals
`TechniqueExitShadow` (shadow-exit-v1) - research I/O never runs ahead of the premium/quote stops; drops are counted
and logged. OFF by default for every desk (`execution.shadow_exit_observe=false`); a technique opts in with
`techniques.<id>.shadow_exit_observe=true` and then only its default (Practice) book is observed. `TechniqueTargetDistance` (target-distance-v1) is journaled at
fill and embedded in TriggerFired - a diagnostic that never rejects, resizes or retargets. Both contracts are in
`research/events_contract.py`. Any desk may read them; none may act on them.


### Session findings — 2026-09-14 (first enforce/integrity day; v0.7.68 → 0.7.71)

- **Bar DELIVERY stalls (3×):** 13:09–13:13, 13:23–13:27 and 15:26–15:29 ET every armed
  plan on every desk logged "stale bars" (180 s guard) — 44, 43 and 47 warnings — while the
  bars table has EVERY minute for SPY (all `exchange`). Delivery to the runners lagged and
  caught up; nothing was lost, quotes never went stale, exits (quote-based) were unaffected.
  Open: instrument the aggregator's delivery latency (bar ts → dispatch ts) so the next stall
  is measured, not inferred from 130 warning rows. Not tips-specific — platform.
- **Two desks restarted within two minutes (11:45 and 11:50 ET):** this desk's gate cleared
  and fired `ZargarRestart`; the Armed desk had converged the running checkout to 0.7.71 and
  fired its own. The app was dark ~2 min and came back on 0.7.71 (which contained both
  desks' changes because the checkout is shared). The readiness check cannot see another
  desk's INTENT to restart. Convention until a lock exists: before triggering, check the
  task's LastRunTime and `git log -1` of the running checkout; if either moved in the last
  5 minutes, wait a tick.
- **Concurrent deploy blocked a fix for 2 h 10 m:** the `restart-check` refused from 09:33
  to 11:45 because of one managed EM trade (INTC b1). A tips fix waited that long while the
  defect kept opening incidents. That is the gate working as designed; the cost is real and
  the answer is not to weaken the gate but to keep new-control rollouts OFF the open when
  the fix loop is untested (lesson for the next activation: shadow for a session first, even
  when the reviewer signs off).

### Tips EOD review fixes — 2026-09-14 evening (v0.7.73, `reviews/2026-09-14-eod-response.md`)

- **Invariant 21 — the intake pipe proves liveness.** `gateway_status.json` (every 30 s) + the
  gateway's idle watchdog (no frame for 180 s → reconnect) + `GET /api/tip/intake/liveness` +
  `TipIntakeStalled`/`TipIntakeRecovered`. "API health ok" never implied delivery: 26 RTH
  messages arrived after the close on 2026-09-14 with the app healthy throughout.
- **Invariant 22 — a model cannot self-certify policy.** Under propose-only maintenance every
  analyst-written `rule` is born `needs_human` (a proposal), never supersedes a live rule and is
  rendered as PENDING REVIEW; only a person (dispute release / reviewed batch) makes it operative.
- **Invariant 23 — a Practice option fill needs an eligible session** (`sim.option_session_open`,
  09:30–16:00 ET on a trading day; `AppConfig.sim_option_sessions`, tests off). A fill at 04:01 ET
  is not market evidence.
- **Shared engine:** sim fill handling left the quote→bars critical path (bounded ordered queue);
  the position watchdog runs per-position steps (a blocked position never stalls another's
  protective retry; `execution.watch_pass_timeout_seconds` 5). Restart readiness counts running
  Tips paid work (`tipRuns`, `tipRunsStale`). Research books can be quarantined
  (`Portfolio.quarantined`, `POST /api/portfolios/{id}/quarantine`) — quarantined lanes grade nothing.
- **Deploy-intent lease (not built):** until one exists, a desk checks the `ZargarRestart` task's
  LastRunTime and the running checkout's `git log -1` before triggering; if either moved in the
  last 5 minutes, wait a tick (the 11:45/11:50 collision).

### Restart: exclusive deploy lease and a verified entry pause — 2026-09-14 (R4 of the EOD handoff; v0.7.73)

The restart door (invariant 18) gained two guarantees the other team showed were missing: `restart.ps1` takes an
EXCLUSIVE deploy lease (`logs\deploy.lock`, created atomically, owner = host:pid:time, stale after 600 s, released only
by its owner; nested `start.ps1` inherits it via `ZARGAR_DEPLOY_LEASE`), and the entry pause is VERIFIED — the quiesce
POST must answer `quiesced=true` AND `/api/ops/state` must read `quiesced=true` before the inventory is captured. A
pause that is not confirmed refuses the ordinary path (exit 2); `-Force` / the watchdog's `-Override` remain the
journaled exceptions. The watchdog skips its tick while a deploy holds the lease, so it cannot start a second engine
during a restore. Refusals and the restore mismatch path release the lease. Scripts stay ASCII-clean where they were
(start.ps1 keeps its three pre-existing non-ASCII bytes) and CRLF. Not exercised destructively against the shared
runtime; verified by PowerShell parse and by the next coordinated deploy's transcript.


### Cartel EOD correctness release — 2026-09-14 (v0.7.74)

- SimExecutor requires finite positive uncrossed prices and receipt/source freshness (15s).
  Option fills require OPRA/IBKR identity; only explicit sim quote-source mode permits synthetic
  observations. Stale/delayed evidence leaves the order working and emits SimFillWaiting once
  per changed reason. Real-broker protective routing is unchanged.
- ExecutionEvidence is inserted in the execution transaction. OrderFill carries execution ID,
  executor timestamp and evidence; legacy fills retain unknown provenance. Do not claim a
  research sampler's nearby quote was the exact fill source.
- All deployment/restart work uses scripts/deployment-lock.ps1. The Windows OS mutex covers
  the authorized runtime directory across processes, releases after owner death, and permits
  a same-owner nested restart. scripts/deploy.ps1 requires a reviewed full target commit,
  clean runtime, fast-forward integration and matching post-build source before guarded restart.
  It records owner, commit/version, phase, artifact hash and verification time. It adds no force
  override. Desks must acquire this lease BEFORE changing/building the runtime checkout.
- Restart inventory now includes Cartel arms and actual entry tasks; held swing positions
  remain covered by the shared managed inventory. A proposal waiting for approval alone is
  not an in-flight order.
- Bounded BarDeliveryHealth events preserve per-consumer queue/close latency and handler
  timing outside the trading callback. /api/ops/delivery-health is authenticated. These
  measurements distinguish dispatch delay from stored-history completeness; they do not
  infer missing venue prints or authorize retrospective entries.


v0.7.74 convergence: restart, deploy, start and watchdog now share deployment-lock.ps1.
The OS mutex owns the critical section and the existing deploy.lock marker remains the
cross-version ownership record. An inherited token is honored only for the current owner
or an explicitly nested descendant verified through process ancestry; an environment token
alone cannot bypass ownership. Dead local marker owners can be recovered; live owners are
not stolen on an age threshold. The R4 acknowledged-and-read-back quiesce requirement remains.
Foreground manual start releases ownership at process handoff while preserving the existing
watchdog startup grace period; detached deployment holds it through health/restore checks.

### Dark app at 16:22 PT 2026-09-14 (after hours; ~2.5 minutes) — a conflict resolution broke the build

Merging main v0.7.73 into the running checkout (which carried the watch job's unmerged 0.7.72) produced a changelog
conflict; the Team2 desk's resolver concatenated the two release blocks and dropped the `]},` that closed the first.
`restart.ps1` stopped the engine, then `start.ps1`'s frontend build failed on the TypeScript error and the restart
exited 1 — with the new deploy lease still held, so the watchdog would have deferred for up to 10 minutes. Fixed by
hand within ~2.5 minutes (block closed, lease removed, task re-run; v0.7.73 healthy, three Team2 plans for 09-15
armed). Two rules from it: (1) `restart.ps1` releases the lease on EVERY failure exit and a lease whose owner
process is gone is stale for both the next deploy and the watchdog — landed by the Cartel desk's
`scripts/deployment-lock.ps1` convergence in v0.7.74 (OS mutex, dead-owner recovery, finally-released), which
supersedes the Team2 desk's file-lease draft; (2) a merge into the running
checkout must be built (`node scripts/check-release.mjs && npx tsc -b`) BEFORE the restart task is started — the
door does not protect against a broken build because the stop happens before the build. The watch job's Team2
commits (F123, F126, 0.7.72) had never been merged to main; they are brought to main with this change so the running
checkout and main agree again.

### Dashboard vs Ledger "today" - 2026-09-14 (v0.7.75)

- **Report (user):** "the daily numbers don't really match. see dashboard vs ledger for today" -
  Dashboard +429.97, Ledger TODAY +145.07, and a "+4.00 unexplained" pill.
- **The pill was a marking mismatch (mine).** Since 0.7.70 the book marks an option at the mid
  (invariant 22); `desk.ledger()` still valued open lots at `q.last`. (mid - last) x qty x 100 over
  the three open lots = +3.00 (T) + 1.00 (HIMS) = 4.00 exactly. Fixed with `mark_price()`.
- **The headline gap is two definitions, both correct.** EM (+364.49) and Cartel (-61.13) agree on
  both screens to the cent. The whole +284.90 difference is Tips: the ledger's day row books a
  trip's ENTIRE gain on the day it closes (APLD -210.33 over four days), the Dashboard counts
  only today's mark-to-market slice plus the day's move on lots still open. The ledger payload
  now carries `dayStart`/`dayMove` (invariant 21's anchor) and its TODAY tile shows that number,
  with "closed . trips . open & carried" as the sub-line. Per-day rows keep realized-on-close.
- **Merge lesson (deploy outage, ~10 min).** Resolving the five version-file conflicts as "take
  HEAD" dropped the EM desk's new `build_sha()` from `zargar/__init__.py`; `/api/health` imports
  it, so every health call returned 500 while the engine itself ran fine - `restart.ps1` gave up
  at 30 s and the watchdog held off. Rule: a conflicted file that the OTHER side extended is
  resolved from THEIR content with the version line re-set, and `from zargar import __version__,
  build_sha` is part of the import smoke before any restart. `restart.ps1`'s 30 s health wait is
  too short for a boot that restores this many plans (2-3 min today, twice) - it reports a
  failure for a start that succeeds.
### Shared runner: technique state extras and one entry gate — 2026-09-14 (Team2 EOD follow-up; v0.7.76)

Two hooks on `PlanRunner`, default no-ops, both technique-resolved: `state_extras(ap) -> dict` is merged into the armed
state on EVERY `_persist` and `restore_extras(ap, state)` runs while re-arming a restored plan BEFORE the seed replay
(a technique's durable overlay must exist before its first resumed read); `entry_gate(ap, trade, stage) -> reason | None`
is asked at `pre_order` (after the contract pick and the review, before the mode branch), `order` (after sizing,
immediately before the intent is written) and `retry` (the collar re-price). A reason skips the trade
(`entry_gate_refused`, journaled as TechniquePlanTriggerSkipped, persisted); a hook that raises REFUSES (fail closed on
a money path). Exits and cancels never pass through it. EM and Tips inherit the no-ops — their behaviour is unchanged
(`tests/test_technique_arm*`, `test_tip_runner*`, `test_position_*`, `test_platform_*` green). Team2 uses them for the
refused-fire overlay + decision watermark (R1/R3) and the wall-clock session/cutoff rule at the order boundary (R2).

### Delivery telemetry finished + deployment lease hardened — 2026-09-14 (Tips desk, KFIN-03/04, branch `claude/kfin-03-04`)

**KFIN-03 (`zargar/delivery_health.py`).** The bar-delivery telemetry now has ONE bounded writer per engine that drains a
per-consumer dirty set (one entry per consumer, first-dirty order — a consumer re-dirtying while it waits keeps its
place, so a busy sink can never starve another consumer) and keeps draining after the active write finishes: a snapshot
marked dirty while the sink was blocked is flushed WITHOUT another market event (the reviewer's regression
`tests/test_tip_completion_boundaries.py::test_delivery_writer_retains_other_consumers_without_another_bar` is adopted
verbatim). Every bar consumer — `SessionListener._bar_loop` (EM/Tips/Team2 armers) and `PositionManager._bar_loop` —
wraps its handler in `delivery_health.handling(...)`, a SYNC context manager that records the start and, in
`__exit__`/`finally`, the outcome (`handled` / `failed` + `lastFailure` / `cancelled`), so a hung or failing handler stays
diagnosable: `GET /api/ops/delivery-health` shows `inFlight` + `inFlightAgeMs` per consumer, `subscriberDrops` (the
bus now counts drops per topic and per live queue: `Bus.drops(q)` / `Bus.drop_counts()`), and the writer's own backlog;
`/api/health` (local) carries a one-line `delivery` summary. Trading callbacks never await the journal (the telemetry
is synchronous; the writer is the only task, and there is at most one). Engine stop calls
`delivery_health.shutdown(engine, timeout=2s)`: a stuck sink is cancelled and the unflushed count reported, never
awaited indefinitely. Tests: `tests/test_delivery_health.py` (blocked sink + three consumers, failed/cancelled/blocked
handlers, bounded shutdown, callback independence).

**KFIN-04 (`scripts/deployment-lock.ps1` + the four doors; `zargar/ops.py`, `zargar/runtime.py`).** Same lease, same
mutex/marker scheme — hardened, not replaced. (1) A restart handoff now verifies CLEAN REVIEWED SOURCE
(`Test-ZargarReviewedSource`: HEAD = the reviewed target, nothing modified or untracked, and no gitignored `.py/.js/.ts/
.css/.html` inside `backend/zargar`, `frontend/src`, `frontend/public`) AND a SHA-256 manifest of the COMPLETE built
artifact (`Get-ZargarArtifactManifest`: every file under `frontend/dist`, manifest hash over the sorted list) — a
modified `dist/assets/*.js` with an unchanged `dist/index.html` is refused, as is a dirty backend file; a legacy handoff
with only `artifactSha256` is refused ("carries no artifact manifest"). Hashing is .NET (`Get-FileHash` is a module
function 5.1 cannot find under an inherited pwsh-7 `PSModulePath`). (2) Receipts are TERMINAL: `deploy.ps1` writes
`failed` / `deferred` (+ `detail`) on every exit path and `restart.ps1`'s `Leave` records the phase for every non-zero exit
(2 = deferred, else failed; the pending handoff is kept and flagged `handoffPending`) — nothing stays `building` /
`restarting`. (3) ONE runtime identity: `start.ps1` (the door under the task, a shell and the watchdog) writes
`logs/runtime-identity.json` (HEAD, clean verdict, artifact manifest, the five script hashes, caller from
`ZARGAR_DEPLOY_CALLER`) before launching; `restart.ps1` copies it into the receipt and refuses a verified receipt when the
launched artifact differs from the handoff; the watchdog logs it. A plain restart writes phase `restarted` (never
`verified` — that word drives the duplicate-skip rule and belongs to a reviewed handoff). Ownership tests
(`tests/test_deployment_lock.py`, under `powershell.exe` 5.1): nested child vs foreign child, dead owner + hard-killed
owner (abandoned mutex recovered) + unidentified marker (never removed), pending/expired handoff, exception cleanup,
duplicate request in one process, manifest refusals, shared identity/receipt, terminal phases.

**Readiness (`ops.restart_state`).** The two-hour Tips-run cutoff is gone: age is not proof a paid job is dead. A
`TipAnalystRun` now carries `owner` (= `runtime.runtime_id()`, `host:pid:boot-token`, stamped by the column default)
and `heartbeat_at` (refreshed by `_Recorder.step`, throttled to one bounded write per 30 s per run); every run is bound to
the asyncio task that carries it (`analyst.register_run` from `_Recorder.__init__` and both rule-audit cycles;
`release_run` on the terminal persist). Readiness counts a running row when its task is alive in this process (however
old), or when its heartbeat/creation is within 15 min (registration in flight, or another runtime alive); a row THIS
process owns with no live task and no heartbeat is reconciled on the record (`failed`, "lost by its owner process …",
reported as `tipRunsReconciled`); another runtime's silent row is reported as `tipRunsStale` and never rewritten here.
Boot reconciliation (`reconcile_stale_runs(older_than_s=0)`) is unchanged. Tests: `tests/test_ops_tip_run_liveness.py`;
`test_tip_eod_20260914_restart.py` and `test_ops_restart.py` stay green.

Pre-existing failures observed (identical on origin/main `561a859`, verified from a clean export of main):
`test_position_chaos.py::test_failed_exit_watchdog_retries_then_alerts` (grouped run only) and
`test_technique_arming.py::test_auto_options_one_contract_lifecycle` (also alone) — not touched by this branch.
### Orders: an unanswered venue hand-off is an unknown outcome; retries are new orders — 2026-09-14 (Team2 review E/F; v0.7.78)

`OrderManager.place` now raises `SubmitUncertain(order_id, cause)` when `executor.submit` raises: the order was written
ahead and handed to the venue, and the answer never arrived — that is NOT "not sent". The shared `PlanRunner._place_with_retry`
treats it (and a timeout at the terminal attempt) as an UNKNOWN outcome: the trade stays `submitting` with
`Trade.submit_uncertain` (persisted, restored), the order id is registered so later fills route back, an alert is raised,
and it is never retried as a fresh order. Only a confirmed zero-fill (rejected / cancelled unfilled) is a failure. The
same loop judges every transport RETRY of a money-mode entry through `entry_gate` (stage `retry`) and composes the new
synchronous `entry_guard_predicate` hook into OrderManager's `before_submit`, so a technique's time rule runs after the
manager's last await, immediately before the venue hand-off; a refusal there is a skipped opportunity
(`entry_gate_refused`, `decisionTs`), never a strategy refusal. Exits and cancels are untouched. `before_submit` is
carried through every attempt (the EM desk's FA-01 on their branch does the same with their quote/budget guard — the two
compose when their branch merges; the retry-loop signature is identical). EM inherits the uncertain-outcome handling:
a terminal timeout on an entry is no longer marked `failed`. Tips override `_place_with_retry` and are unchanged.

### Orders: uncertainty is resolved by the venue's report, live and at restore — 2026-09-14 (Team2 review F; v0.7.80)

`Trade.submit_uncertain` (v0.7.78) is now CLEARED only on authoritative evidence: `on_order_update` resolves it on any
venue-sourced report of the entry order (fill, partial, rejected, cancelled, expired — `entry_reconciled`, journaled) before
the ordinary bookkeeping runs, so a confirmed zero-fill becomes an ordinary failed/cancelled entry and a fill stays
managed; `_restore_trades` judges a still-uncertain entry against the persisted `orders` row through the same callback
(`_reconcile_uncertain_from_row`) — a terminal or filled row is authoritative, an in-flight or missing row keeps the
uncertainty (never cleared on absence, a local timeout or a cancel request). Duplicate reports are idempotent; a cancel
after a partial keeps the cumulative fill. Shared behaviour (EM inherits it; Tips override the retry loop).

### Orders: a terminal report is classified by its cumulative fill — 2026-09-14 (Team2 review F; v0.7.81)

`PlanRunner.on_order_update` used the runner's local `filled_qty` to decide whether a CANCELLED / EXPIRED / REJECTED
entry report was a zero fill — after a missed partial-fill callback (a dropped delivery, a restart) a cancel carrying
`filledQty=1` became a "cancelled, nothing filled" entry, and a technique could exempt it from its read. The terminal
branch now books the report's cumulative fill first (`_apply_entry_fill`, the same helper the fill branch uses: never
regresses a larger local figure, opens the position once, persists, publishes) and classifies afterwards; the restore
path inherits it because `_reconcile_uncertain_from_row` goes through the same callback. Shared behaviour (every
technique's entries); no threshold changed.

### Orders: a terminal report's cumulative fill is booked for any entry trade — 2026-09-14 (Team2 review F; v0.7.82)

The v0.7.81 booking ran only for entries still `submitting`/`working`; an entry an earlier partial had already opened
ignored a cancel that reported more contracts. `on_order_update` now books the terminal report's cumulative fill for
ANY entry trade (`_apply_entry_fill`: never regresses, opens once, nets against booked exits) and classifies only the
entries that were still submitting/working. Shared behaviour; no threshold changed.

### 2026-09-15 - execution-review policy is a runner hook (deterministic-entry-v1)

`PlanRunner.fire_review_policy(ap)` -> `legacy` (the awaited reviewer branch, unchanged for Tips / Team2 / Cartel) or
`deterministic` (the technique's `fire_decision(ap, tid, tr, trade, attempt_id=)` hook returns a versioned decision
dict; the runner journals `TechniqueEntryDecision`, refuses on `refuse`/`defer` with its own disposition, and continues
into the UNCHANGED `_enter` chain on `allow`). Any other value refuses the entry with a policy error - never a silent
model fallback. Generic defaults keep every other desk exactly as before; only EM overrides the hook from its own
`techniques.enhanced_market.fire_decision_mode`. There is deliberately NO `execution.fire_decision_mode` default.
Invariant: no model output may mutate an executed decision, sizing input, setup validity, proposal, stop, cooldown or
plan state after the fact; optional evidence (`TechniqueEntryEvidence`, `authority=evidence_only`) is append-only over a
frozen snapshot and is produced by an after-close command that opens no trading service. Trade records carry
`decision`, `decisionDisposition` and `timing` (bar / received / decided / quoteReady / admission / submit) so the
boundaries can be measured separately from provider and venue latency.


- **2026-09-15 (Tips desk) — sim option fills need venue identity; tests must publish it.** Since
  `12491f2` (2026-09-14) `SimExecutor.quote_rejection` fills an OPT order only on a quote whose
  `source` is `opra`/`ibkr` with a fresh `source_ts`; a `chain`/delayed quote is "resting, not
  filled" (`SimFillWaiting`). The chain overlay installed by `OptionsService._apply` re-stamps every
  incoming contract quote `chain` unless an `opra` overlay replaced it (what the OPRA research feed
  does). A test that expects a sim option fill must therefore publish through
  `quotes.set_overlay(sym, ..., source="opra", source_ts=now)` + `on_quote` (see
  `tests/test_tip_runner.py::_opt_quote`); a bare `Quote(...)` for a tracked contract never fills.
  Four Tips runner tests had been failing since that commit for this reason (not time-of-day);
  Practice fills in the runtime were never affected (37 option fills 2026-09-13/14).

- **2026-09-15 (Tips desk, shared code) — `ProposalService.approve()` flips status under a row lock.**
  The pending -> approved transition is now `SELECT ... FOR UPDATE` with the pending/expiry check
  repeated inside the same transaction: a duplicate click, a Telegram tap racing the app, or a
  click racing the TTL gets "proposal is approved/expired, not pending" instead of a second order.
  Every desk's proposals get this; nothing else in the non-Tips path changed
  (`tests/test_proposal_readiness.py::test_non_tip_proposals_keep_the_old_approval_path`). Tips
  cards additionally carry `context.readiness` (typed blockers, final plan, fingerprint) and a
  human approval revalidates first — see `docs/techniques/tip/README.md` "Approval cards".

- **2026-09-16 (Tips desk, ops) - the watchdog launches the checkout AS IT STANDS; a converged checkout must be launch-ready at every instant.**
  At 10:40 ET the watchdog restarted a DOWN engine from `C:/Cursor/zargar` and got 0.7.96 (merged, not yet
  deployed) - and a `/api/health` 500, because a conflict resolution had dropped the runtime-branch-only
  `build_sha` helper from `backend/zargar/__init__.py` that the runtime branch's `api/app.py` imports.
  A health import failure is a RESTART LOOP (start, 180 s, kill, start) during trading hours, and each
  restart kills the helper windows. Rules: (1) after ANY merge into the running checkout, run
  `python -c "import zargar.api.app"` and `node frontend/scripts/check-release.mjs` before leaving it;
  (2) never resolve a conflict in a runtime-only file with `--theirs`/`--ours` blindly - diff the runtime
  side for helpers main does not carry (`build_sha`, EM build helper); (3) a helper the health route
  depends on belongs on main, or the route tolerates its absence (start-path owner's call); (4) "merged,
  not deployed" is a fiction while the watchdog can launch the checkout - treat every convergence as a
  possible deploy.
  *EM desk follow-up, same day:* the engine the watchdog judged DOWN at 07:40:09 PT was logging normally until
  07:39:59 and showed no shutdown or traceback - a single 4 s probe timed out under load and a LIVE engine was
  killed; a second identical timeout was observed at 08:56 PT with health answering in 20 ms before and after.
  `/api/health` now answers `build=unknown` instead of a 500 when `zargar.build_sha` is absent (EM branch, PR #174,
  which also puts the helper on `main`). The probe policy (confirm DOWN with a second probe before any kill) is the
  start-path owner's decision; until it changes, every load stall longer than 4 s is a restart risk in RTH.
- **2026-09-16 evening (EM desk) - the event-loop stall is real, measured, and now instrumented; the single-probe
  watchdog killed a live engine FIVE times today.** Evidence (engine log gaps with no line at all, followed by an
  Alpaca "no close frame" reconnect): 07:40 PT ~4 s, 08:56 ~10 s, 17:17 (unknown length, engine killed), 17:42-17:45
  183 s, 17:52-17:54 141 s (killed at 17:55 mid-batch). The long ones coincide with technique-run load (Cartel
  research 17:39; the EM review batch from 17:47 with 9 reads in flight, system CPU 100%). Confirmed on the loop:
  `technique/render.py::render_chart` (matplotlib, 0.3-2 s per PNG) was called synchronously at every vision pass
  (`technique/service.py` two sites) and the legacy fire critic (`technique/arming.py`) - now `render_chart_async`
  on ONE worker thread (matplotlib is not thread-safe; renders are serialised, not parallelised). Model calls were
  already async. Whether rendering explains a 141-183 s silence is NOT proven - a stall that long is either one
  blocking call or a starved main thread - so the engine now carries a **loop stall watch** (`zargar/loopwatch.py`,
  `ops.loop_stall_seconds` default 2 s): a daemon thread that captures the loop thread's stack while the loop is
  blocked, logs the stall length on resume, and reports `loopStalls` / `lastStall` / `eventLoopLagMs` in
  `/api/health.local.delivery`. The next stall names its call site. Diagnostic only; never cancels or restarts.
  **Watchdog classification (proposal on the EM branch, `scripts/watchdog.ps1`, start-path owner's call):** before any
  kill, a second probe 15 s later, then process + engine-log freshness; alive-and-logging with health late is logged
  as STALL and left alone for one tick, and becomes DOWN only when it persists into the next tick or the process /
  log are gone. `-ProbeOnly` classifies without acting. Parse-checked; exercised once against the worktree (probe
  path). Not deployed; the runtime keeps the current single-probe script until the owner adopts it.
  **Provider rate limits (CBOE):** callers now declare a priority (`options/chain.py::cboe_priority`): `entry` (a
  live option pick) and `position` (a held contract's mark / exit read) retry a 429 briefly and are never held back;
  `background` (enrichment, the nightly liquidity screen, research) fails fast on a 429 and skips requests for a
  cooldown (`options.cboe_cooldown_seconds`, 20 s) so the burst that trips the limit is not fed by work that can wait.
  Freshness checks (`risk.stale_quote_seconds`, delayed-row refusal) and every risk limit are untouched. Tests:
  `test_em_loop_stall_watch.py`, `test_em_render_offloop.py`, `test_em_cboe_priority_cooldown.py`,
  `test_em_cboe_rate_limit_retry.py`.
  *PFU-01 (review 2026-09-17) - the first watchdog proposal was HELD: two failed probes still let a live-but-unhealthy
  engine reach `start.ps1` without readiness / quiescence / before-inventory.* Reworked at `47275c3f8ff02c857b46b431e71b3300ec0eea67` as a PURE module
  `scripts/watchdog-classify.ps1` (`Get-EngineClassification`: healthy | live-unhealthy | absent over probe results,
  the engine process bound to THIS runtime - the pid the engine stamps in `logs/engine.pid`, venv path only as fallback,
  identity logged - the engine log's freshness and a TIME-based stall marker: persisted only when >= 180 s and <= 600 s
  old, older = unrelated and reset, ANY successful probe clears it, `-ReadOnly` never writes). Policy in
  `scripts/watchdog.ps1`: probes are 2-of-3 with 12 s timeouts; `live-unhealthy` REFUSES ordinary recovery (exit 2),
  escalates ONCE per stall marker (Telegram from `backend/.env` + a log line naming the human next step:
  `ZargarRestartOverride`), and only the explicit override replaces a live engine; `absent` (no bound process or stale
  log) takes the existing DOWN path; `-ProbeOnly` classifies without touching state. Acceptance
  `scripts/tests/watchdog-classify.tests.ps1` 8/8 (mocked classification, no restart). Start-path owner (Tips desk)
  agrees with the direction; integration into the shared protocol WAITS for the user's decision. Not deployed.
- **2026-09-15 (Tips desk, shared scheduler) - a job may be scheduled RELATIVE to the exchange calendar.**
  `Scheduler.register(name, at_et, fn)` now also accepts `at_et` as a callable of the ET date
  returning "HH:MM" for that day (`resolve_at(name, day)`; `status()` shows today's resolved time and
  `calendarRelative`). Fixed "HH:MM" jobs are unchanged. First user: the Tips hold study's pre-close
  capture, which must run before an EARLY close (12:50 on a 13:00 day) - a fixed 15:50 silently
  missed those sessions (R147-01). Once-per-day, journal hydration and the running-task guard apply
  to calendar-relative jobs exactly as before.
- **2026-09-15 (Tips desk, shared db) - `create_all` also creates declared indexes an existing table lacks.**
  `db._ensure_columns_sync` added missing COLUMNS to live tables but never their declared indexes,
  so a UNIQUE index on a column added after the table's first creation (the hold study's
  observation identity, HOLD142-02) would only ever exist on fresh databases. It now creates any
  index in `table.indexes` whose name the live table lacks and whose columns exist (or were just
  added) - additive only, never dropped or altered here; logged with the added columns.
- **2026-09-15 (Tips desk, shared execution) - ONE exit authority: adoption releases the entry's bracket.**
  A share tip proposal carries a bracket (the finalized stop + first target, geometry rev 2) so the
  fill is protected until the manager adopts it; the OrderManager spawns the two GTC children on the
  full fill. Adoption then added the manager's own venue stop and ladder WITHOUT cancelling the
  children: Tips Practice held 7 MRNA with a bracket stop (7 @ 134.3674), a venue stop (7 @ 134.37)
  and a bracket target (7 @ 149.70) all resting beside a 35/35/30 ladder - the stop would have sold
  14 against 7 held (the RKT short, one bug class over), the target 7 + the trim. Fix
  (`PositionManager._release_bracket_children`): `adopt`, `append_leg` and `restore` cancel every
  working `source=bracket` order whose parent is one of the position's entry orders BEFORE the venue
  stop is placed (journal `ManagedPositionBracketReleased` phase adopt/scale_in/restore; a failed
  cancel is an attention alert, never silent); the OrderManager asks `bracket_guard`
  (`owns_entry_order`) before spawning children, so the completing fill of a partially adopted entry
  journals `OrderBracketSkipped` instead. Adapter positions (Options Cartel) run their own venue
  orders and are untouched. Tests: `tests/test_position_bracket_release.py`. The MRNA children were
  cancelled by hand at 15:22 ET (orders a2089582, 564dd417) before the fix shipped.
- **2026-09-15 (Tips desk, shared execution) - the venue GTC stop must follow the held quantity.**
  `PositionManager._ensure_venue_stop` re-placed the resting stop only when its PRICE changed; a
  trim reduced the leg but the venue kept the pre-trim size (RKT: 148 resting on 89 held; the
  stop filled 148 at 11:17 ET and left the Tips Practice book short 59). Two restarts earlier
  that morning had also dropped the stop's order id from the exit index (restore re-registered
  only `state.exits`), so the fill never reached the position and it stayed open at 89. Fix:
  `venueStopQty` is persisted, a price OR quantity mismatch cancels/replaces, every partial exit
  fill re-runs `_ensure_venue_stop`, and restore re-registers `venueStopOrderId`. The exit path's
  venue clamp (a leg is marked flat when the venue holds nothing on that side) is what kept the
  phantom from selling again. Reconciled by hand the same day: reduce-only BUY 59 in Practice
  (order `4bfd05bd`, -$9.16 on the excess short) and the managed position closed through the
  clamped path with no order. Test: `tests/test_position_venue_stop_resize.py`.

### The door, made usable by every desk — 2026-09-15 (Team2 desk; scripts only, no engine change)

What happened: the user stopped an ELEVATED engine (started 13:36 PT by a desk's `deploy.ps1` from an elevated
assistant shell — the 2026-09-10 failure mode again; two door runs at 14:52 and 14:53 had died on `Stop-Process`
"Access is denied") with the elevated `stop.ps1`, then fired `ZargarRestart` — and "nothing happened": the task
exited 1 with NO transcript because the watchdog's 3-minute tick had already found the engine down and held the
deploy lease while it built and started the engine itself (which came up healthy on the checkout's HEAD, v0.7.89).
`restart.ps1` took the lease BEFORE starting its transcript and the lease refused instantly (`WaitOne(0)`).

Changes (all ASCII, CRLF): (1) `restart.ps1` starts its transcript before anything can refuse, so a run that does not
restart always leaves `logs/restart-<ts>.log` saying why (exit 7 for a held lease); (2) `Enter-ZargarDeployment`
gained `-WaitSeconds` — the restart door waits up to 5 minutes for another door (the watchdog mid-start, another
desk's deploy) and a refusal names the owner (`host:pid`, alive/gone); (3) a restart that finds the engine healthy on
HEAD (`/api/health.build` == `git rev-parse HEAD`) reports "already running this checkout" and exits 0 instead of
bouncing it again; (4) `start.ps1` enforces the 2026-09-05 decision — the server runs UNELEVATED: an elevated shell is
refused with exit 8 before anything is stopped (assistant shells ARE elevated on this machine; `-AllowElevated` is the
deliberate override), and a `Stop-Process` denial now says what it is and what to do (exit 3). The scheduled tasks stay
`RunLevel Limited` on purpose — a `Highest` task would deploy today and re-close the door tomorrow (09-10 record);
the tasks were flipped to `Highest` for four minutes during this work and flipped back before any engine started.

How to restart, any desk: `Start-ScheduledTask -TaskName ZargarRestart` after `/api/ops/restart-check` is `safe`;
if the engine was started elevated (a desk's shell), the user runs `scripts\stop.ps1` from an elevated terminal, the
watchdog or the task brings it back unelevated within three minutes, and from then on the task can always replace
it. Never `start.ps1` / `deploy.ps1` from an assistant shell — it is elevated here and the guard now refuses it.

### Per-book pause — 2026-09-15 (Team2 desk, for the sizing experiment's loss stop; v0.7.90)

A third kill-switch scope beside the global switch and the per-book daily-loss halt: `HaltState.pauses`
(`engine.pause_book(pid, reason, label)` / `release_book_pause`, `POST /api/portfolios/{id}/pause` and `/unpause`,
journaled `BookPaused` / `BookPauseReleased`, `pausedBooks` in `/api/ops/state`). Semantics: every NEW entry and add on
that book is refused — runners through `engine.trading_halted(pid)` (which now reports the pause with its label) and
the RiskGate through the `book_pause` check — while reduce-only exits pass under `risk.halt_allows_exits`, every other
book keeps trading, and unlike a book halt it has NO day: `HaltState.restore` brings it back after a restart regardless
of the date and the session roll never releases it. Releasing it touches nothing else, and releasing the global
switch or the book halt never releases it. The record snapshots the Team2 sizing settings at pause time; the pause
changes no setting. Tests: `tests/test_book_pause.py`. Nothing is paused by this release.

### LIVE read -24% on a -2% day - 2026-09-15 (Dashboard, v0.7.91)

- **Report (user):** "when i change from practice to live, the numbers are inaccurate. says i lost
  close to 24 percent today"; also the chart coloured opposite to its header, and the book picker
  only drove the curve.
- **Three causes, reconciled to the cent.** (1) The client's live marking (`useLiveEquity`) summed a
  position's value in the INSTRUMENT's currency into a CAD book: Webull's SPCX (US$8,609) went in
  raw, so the board's "now" for the real accounts was 20,402 against an anchor of 26,986 - 4,505 of
  the "loss" was FX. (2) `dayMove` and the summed curve added a CAD book and a USD book without
  conversion. (3) Wealthsimple Personal's anchor: persisted 4,096.92, in-memory 5,657.56 - the
  15-minute sync shift (`equity_after - equity_before`) leaked marking/currency differences into
  the anchor all day (+1,560), read as -28% on that book. Webull's -447 was real.
- **Fix.** Invariant 21 (level-set definition, journaled shifts, replay on restart). Client: every
  book is converted at today's USD/CAD before any sum - live marking (`makeRate`, same
  `USDCAD=X` the server's `FxService` reads; a book that cannot be converted keeps the server's
  equity), the day move, the curve's weights - and the footer says "in CAD at today's FX". An
  account that cannot be priced is named in the tooltip. Verified in the browser mid-fix: -7.70%
  (FX fixed, old anchor still drifted) -> after the anchor rebuild, the real day.
- **Chart colour.** The curve coloured itself against the window's FIRST sample (04:00 ET) while its
  header measures from the previous close - a green "+US$220 today" over a red line whenever the
  window opened above the close. One number now decides both.
- **Picker.** `store.dashBook` is the board's selection: the curve's select and the headline's
  account chips both set it; the headline shows that book's total and move. Empty accounts fold
  into one "+N empty" chip and stay out of the picker; same-named accounts get their currency.
- **Known simplification.** History is converted at TODAY's rate (no FX series per day); the
  footer says so. The USD/CAD move within a day is ~0.3%, below what the board resolves.
### Team2 parallel Practice experiments — 2026-09-15 (technique-scoped; v0.7.93)

Team2 can now run several Practice books at once with ONE rule difference each (`techniques.team2.experiments`; the
whitelist is `size_full` / `no_trade_zone`, anything else is refused). What changed in shared terms: the Team2 runner's
desk-wide loss cap and concurrency cap are per BOOK (`losses_across_plans(portfolio_id=)`,
`open_positions_across_plans(portfolio_id=)`), each plan carries its book's rules (`rules_for(ap)`, stamped on the run)
and label, `nightly_plans` mints one plan per (symbol, book) and refuses a non-Practice book for an experiment. No engine
change; the per-book pause (v0.7.90) is the experiments' breach action. Nothing is enabled by this release.

### Settings: a read-only load — 2026-09-15 (Team2 receipt; v0.7.94)

`SettingsService.load()` migrates legacy keys (writes + journal) on first sight. A tool that must not write sets the
`readonly` attribute on SettingsService before `load()`; the migration is skipped in memory (values still resolve).
Used by `zargar.tools.team2_receipt` (review of 41ec565: the receipt claimed READ-ONLY while calling `load`).

### A closed durable position leaves manager memory — 2026-09-16 (Tips hold study; PR #184)

`PositionManager.positions()` is the OPEN book: a position popped from memory the moment it closes. Anything that
must observe same-session closes (the Tips hold study's `intraday_exit` arm, any end-of-day report) reads the
durable `managed_positions` record (`status=closed`, `state.closedMs` on the session date) and adapts it through
the manager's own row reader — never the in-memory map. Evidence: the first `holdstudy-v2` pre-close capture
(15:50 ET) recorded 2 carry rows and 0 intraday exits while Tips Practice had closed T (13:15), SLV (15:00) and
GOOGL Oct-16 360C (15:30) that session; the three are counted MISSING in the study, not hand-sampled. Every
observation now also carries `portfolio_id` + `book_kind` so Practice (sim) and shadow observations are reported
apart. Reporting note: the desk ledger's per-day trips are that day's closed lots; `state.realizedPnl` on the
position is lifetime (T showed +$131.96 lifetime against +$3.64 on the day).

### "sim fill handling failed" during a feed blip is a resting order waiting, not a lost fill — 2026-09-16

During the 15:29 ET feed blip the sim executor logged "sim fill handling failed for INTC"; the journal shows
`SimFillWaiting` (uncrossed / stale-receipt quote) on bracket SELL 19 INTC LMT 106 resting on the Tips shadow
book for source eva — status ACCEPTED, filled 0, zero `executions` rows. Before treating such a line as an
unreconciled fill or an unprotected position, check `executions` (fee column is `commission`) and the order's
status; a resting limit that could not be judged simply waits for the next admissible quote.

### A durable position is persisted BEFORE it leaves memory — 2026-09-16 (CAP187-01; PR after #187)

`PositionManager._mark_closed` used to pop the position from `_pos` and then write the closed row. In that
interval the close existed nowhere a reader could see it: not in `positions()` (popped) and not in
`managed_positions` (not yet written). The Tips hold study's intraday-exit capture hit exactly that gap
(its integration test failed twice). Rule: any transition that removes a durable object from memory writes
the durable state first and drops the memory entry after (in a `finally`), so an observer always finds the
object in one of the two places. Evidence: `tests/test_tip_hold_study.py::test_close_transition_is_capture_safe_at_the_persistence_boundary`
invokes a capture from inside the manager's own persist call for the closed transition and records the exit.

### The display buffer is never the record — a runner's decision funnel comes from its own ledger — 2026-09-16 (Team2 EOD review P2; v0.8.01)

`PlanRunner._log` keeps the last 400 events for the UI. On 2026-09-16 the journal wrote 1,848 bar revisions for three Team2 plans
and the close summaries lost IWM's concurrency refusal and SPY's desk-cap refusal to that cap, while a re-quoted price counted
one candidate twice. Rule: a bounded display buffer never determines performance attribution. `_log` now calls the hook
`note_decision(ap, rec)` (default no-op) with every record as written; a technique that reports a decision funnel keeps its OWN
ledger there under a stable identity (event, setup, SOURCE minute — pass `sourceTs` for runner-side refusals), keeps revisions of
the same candidate as versions, persists it through `state_extras` and rebuilds it from the journal's skip/contract rows after a
restart (journal names normalized). Raw row counts are reported apart from unique decisions. Team2:
`techniques/team2/diagnostics.py`, `tests/test_codex_team2_eod_reporting_0916.py` (their packet), `tests/test_team2_diagnostics.py`.

Beside it, `TechniquePlanDiagnostic` is the event kind for SHADOW measurements (Team2 2026-09-16: entry location, attempt context,
contract candidates with follow-up quotes at fixed horizons and at the exit, decision-time records). A diagnostic row is never a
decision input: it is written by fire-and-forget tasks, tolerates a missing options service, keeps a missing quote UNKNOWN, and is
switched by `techniques.<id>.diagnostics`. Decision-time evidence (what the desk knew, with input identity) is journaled apart
from corrected-history evidence (the read recomputed on the final tape) — a scorecard labels which is which.

### A live engine whose API socket died is not an absent engine — the watchdog spawned duplicates — 2026-09-16 21:29 ET (Team2 desk observation)

The 17:59 PDT engine's `:8420` accept loop died (`OSError [WinError 64]` on the listening socket, engine log 18:29:49 PDT) while
the process kept running its loops. The watchdog read "no answer on :8420" as DOWN and ran `start.ps1 -Detach` without stopping
the first process; its replacement died within a minute (free RAM was 0.8–1.1 GB of 31 GB: WSL 6.5 GB, twelve Claude processes
3.8 GB, Edge/Chrome 3.5 GB), and it tried again twice — for ~15 minutes two, then three `zargar.main` processes shared the DB,
all paged out, none answering. The door fixed it: `restart.ps1` (the `ZargarRestart` task) stops EVERY `zargar.main` process
before starting one; a refused connection makes it skip the readiness section as "no process", so no override was needed.
Rules: (1) the watchdog must stop every `zargar.main` process before it starts one (today it only checked the port);
(2) "no answer on :8420" is a reachability fact, not a process fact — enumerate the processes before deciding; (3) an assistant
does not run heavy test suites while free RAM is under ~2 GB (two of this desk's background pytest runs were killed by the
memory guard the same evening); (4) a duplicate engine is stopped through the door, never by hand. Evidence:
`logs/watchdog.log` 18:31–18:46 PDT, `logs/restart-20260916-184851.log` (restore 14/14, resting 26/26, managed 2/2).

### Simulated share fills and stop triggers happen only in the regular session, on a plausible quote — 2026-09-17 (F-HOLD-01)

The sim executor triggered a GTC share stop on ANY quote and priced the fill off it. At 03:59:54 ET on 2026-09-17 the
quarantined ab shadow book's AFRM stop (65.00) "filled" 27 sh @ 44.991 on a pre-market placeholder book — bid 45.00 /
ask 75.00, sizes 50k / 70k, no source — while the stock traded 72-74. Practice books share the executor. Two guards,
both knobs wired from config (`sim_stock_sessions` True, `sim_max_spread_pct` 0.05) and OFF at the constructor so
direct test rigs keep the old any-hour behaviour (the suites' `make_test_config` turns the session gate off, as it
does for options): (1) a share order not flagged `outside_rth` fills and a share stop triggers only inside
`regular_session_open` — the same 09:30-16:00 ET / early-close window options already use (EOD-05); outside it the
order RESTS with a journaled `fill_waiting` reason, the stop keeps protecting and fills on the first plausible in-session
quote; (2) a share quote whose spread exceeds 5% of mid cannot price a fill or trigger a stop (`fill_waiting`: "Quote
spread implausible …"). Options are untouched (wide books are normal there; their identity/session rules stand).
Evidence + tests: `tests/test_sim_share_session_and_spread.py` (5) reproduce the AFRM event with a pinned clock. Also
seen while testing: `tests/test_sim_fill_evidence.py::test_fill_evidence_committed_with_execution` fails on main as it
stands (expects `syntheticMode` True; the engine fixture no longer runs on synthetic quotes) — pre-existing, not from
this change; owner of the quote-source default to confirm.

### A locally transformed price never keeps venue provenance — 2026-09-17 (E17-01)

`QuoteCache._apply_overlay` recentred an overlay's band on any incoming `last` outside it and left `source`/`source_ts`
untouched, so a real-time OPRA band (1.90/2.00) bent toward a 15-minute-old chart print (0.70) became 0.65/0.75 "opra,
fresh" and the sim priced a Practice fill at 0.75 (MRNA Sep-18 165C, 10:04:54 ET; +$112.92 four seconds later when the
real band returned - audit `docs/techniques/tip/reviews/2026-09-17-mrna-quote-audit.md`). Rules: (1) a venue identity
(`opra`, `ibkr`) is never recentred - a slower feed's print is kept as a print; (2) a delayed-chain estimate may be
recentred (the 2026-09-02 GOOGL 0DTE lesson) but is then DERIVED: `Quote.raw_bid/raw_ask/raw_source/raw_source_ts`
hold the parents, `source = "derived:<raw>"`, `transform = "recenter-v1"`, `Quote.delayed` is true; (3) money gates and
the sim refuse transformed quotes and the fill evidence records `transform` + `raw*`. A freshness check can never
authenticate a locally changed price. Tests: `tests/test_sep17_quote_provenance_review.py` (reviewer, verbatim) +
`tests/test_quote_provenance_e17.py`. Pre-existing on main, unrelated: `test_options_service.py::test_option_order_practice_roundtrip`
times out waiting for a Practice option fill off the delayed chain quote (refused since the OPRA-identity rule of
2026-09-14) - owner of that test to re-express it on an OPRA quote.

### 2026-09-18 (EM desk) - simulator option spread guard (OFF) and lazy charts for deterministic re-plans

- `brokers/sim.py` `max_option_spread_pct` / config `sim_max_option_spread_pct` (default 0.0 = off): when on, an OPENING option
  order (`option_action` BUY_TO_OPEN / SELL_TO_OPEN, derived by the order manager from the book's position - ED-01) cannot be
  priced by a quote whose spread exceeds the cap (spread / mid); the order rests with a journaled `fill_waiting` reason and
  fills on the next plausible book. Closing / reducing orders (…_TO_CLOSE) and orders of unknown intent are NEVER capped and
  keep every existing quote-quality check. Executor-wide: every Practice book, every desk. Shares keep F-HOLD-01's own `sim_max_spread_pct`. Evidence:
  ORCL 148C 2026-09-17, limit 2.29 filled at 1.12 on an OPRA snapshot 0.76/1.12 the contract never traded at. This is a
  simulator EVIDENCE guard (what counts as a market), not a cancel/reprice policy, and it is never applied to exits by this
  knob. It complements E17-01 (0.8.11: a recentred quote is `derived:` and refused) - the ORCL book was most likely that
  transform; an aberrant but untransformed book is what this cap catches. Activation and the cap value are a user decision. Tests: `tests/test_em_sim_option_spread.py`.
- `technique/service.py`: a plan run with `trigger == "preopen_replan"` and no vision pass renders no charts (no model or
  person reads them at 09:25 ET; the UI renders on demand). Every other run is unchanged. Test in `test_technique_walkforward.py`.

### 2026-09-17 late (EM desk) - P-06 reclaim observation: a new observation-only path under an existing knob

`PlanRunner._reclaim_signal` (closed-bar handler) + the `tp1-reclaim` rung in `_shadow_capture` (quote watch) run whenever
`techniques.enhanced_market.shadow_exit_observe` is on (it is, user decision 2026-09-15). They journal `TechniqueExitShadow`
rows only - no order, no exit, no setting - through the bounded non-blocking shadow recorder, so protective decisions never
wait on them. "Settings unchanged" therefore means "no behaviour change", not "no new code path": the path is disclosed here.
The trade state gains one persisted field (`reclaimSignal`, nullable; additive). Other desks' runners are unaffected unless
their own `shadow_exit_observe` resolves true (Tips/Team2: `execution.shadow_exit_observe` default - unchanged).
### Exchange corrections reach the private tape but not the bank — 2026-09-17 (Team2 desk observation; for the platform owners)

Team2's 09:25 plan completion reads the runner's private 1m tape. On 2026-09-17 that tape accepted exchange CORRECTIONS of
pre-market minutes (via `Engine._ingest_exchange_bars` → `BarAggregator.ingest_exchange_bar` → publish → `Team2Runner._merge_revision`,
journaled `bar_revised`) while the `bars` table kept the FIRST observation of each minute: SPY 07:46 corrected at 08:02:09 ET to
760.12/760.2369/**660.65**/760.2285 (same volume 615; a dropped digit is a hypothesis), IWM 04:00 corrected twice to a 283.92 low, QQQ
08:34 high 716.78 → 716.76. Later corrections carry float32-shaped values (716.760009765625). The PRODUCER is unresolved: in hybrid
mode both the Alpaca stream and `YahooQuoteFeed` (chart polls with `includePrePost=true`, completed bars via `on_bars`) reach
`_ingest_exchange_bars` stamped `exchange`, so the label, the arrival time and the float shape do not identify it. Consequences: two
tapes for one session (C6), and a suspicious correction becomes a decision input (SPY's frozen PML 660.65 vs the bank's 757.53).
Questions for the owners of `marketdata`: which adapter and request delivered each correction (correlated producer/request/write
evidence), why the bank and the private tape diverged, and whether a correction that moves a bar's low 100 points on unchanged volume
should be quarantined at intake. Read-only evidence:
`python -m zargar.tools.team2_pm_audit --date 2026-09-17`; note `docs/techniques/team2/notes/research/2026-09-17-premarket-input-reconciliation.md`.
No plan or bar was rewritten.

### A price is as fresh as ITS OWN venue time, never as the quote's receipt time — 2026-09-17 (Team2 PR #204 r2; shared `Quote` fields)

`Quote.ts` is when the app received/re-stamped the object. A feed that emits on every bid/ask message re-emits the previous
`last` under a new `ts`, so aging `last` by `ts` called a ten-minute-old print fresh (review r2 of PR #204). `Quote` now carries
`last_ts` (venue time of the print or bar that set `last`) and `quote_ts` (venue time of the current bid/ask); the Alpaca
trade/quote/bar handlers and the Yahoo chart poll stamp them (0 = unknown). Rule for every consumer that judges a price's age:
read the field's own time, treat 0 as no evidence, never fall back to `ts`; for options the NBBO's `source_ts` is the bid/ask
evidence (its contract, F-2026-09-02). Team2's `_fresh_underlying` is the reference implementation (last by `last_ts`, else the
midpoint by `quote_ts`/`source_ts`, else unavailable).

### Cartel decision evidence — 2026-09-18

Cartel commits distinct decision occurrences, immutable input-context references and journal evidence atomically with its arm update. Two additive tables preserve original inputs independently of mutable tapes. These records grant no trading permission; existing account, quote, risk and protective-exit behavior is unchanged. See `techniques/options-cartel/DIAGNOSTICS-2026-09-18.md`.

### C6 provider identity and frozen Team2 inputs - 2026-09-18

Bar.provider identifies Alpaca or Yahoo independently of source=exchange. Alpaca bars cannot be overwritten by Yahoo or unidentified observations; one policy applies to memory, batch and SQL. Within-provider corrections retain the existing zero-volume rule; cross-provider replacement never borrows volume. Additive schema preserves existing rows as unknown provider. Dataset hashes include provider. Archives precede the scoped Team2 backfill. Team2 canonical plans pin immutable warm-up snapshots across restart/replay and reject noncanonical input bars. Other techniques' settings and orders remain untouched. Details: techniques/team2/notes/research/2026-09-18-c6-release.md.

### History performance without changing trading evidence — 2026-09-18

Shared session timestamp arithmetic is memoized by date plus the resolved close time (early-close policy remains authoritative). Shared Yahoo history accepts an optional rate-limit callback; existing concurrency and retries remain unchanged. Only the Cartel caller uses it to slow its own request pacing after 429. See Cartel PREPARATION-PERFORMANCE.md for measured pilot results and end-to-end limits.

### Cartel provider non-emission — 2026-09-18

Opt-in Cartel Practice interval verification retains positive, complete SIP trade evidence for minutes with no price-eligible trade and no emitted native bar. Proofs are separate from bars and saved in decision-context v2. Real gaps, incomplete responses and Live/paper accounts remain strict; recovery advances observation cutoff and never creates historical entries. Existing risk and exit paths are unchanged. See techniques/options-cartel/VERIFIED-INTERVALS.md.
