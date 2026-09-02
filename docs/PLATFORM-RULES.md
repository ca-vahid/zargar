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

## 2. Findings (settled, with evidence)

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

## 3. Open questions the shared runtime is collecting data on

- **Reviewer net value** (EM 1.4 today): the runner's counters (kills, cooldown re-fires, failures)
  are per technique; a cross-technique tally is the capture-rate telemetry item.
- **Quote-stop breach parameters** (`quote_exit_excess_r` 0.25, `quote_exit_polls` 2): tuned on
  EM's 1m plans; a slower-timeframe technique may want wider.
- **Overnight holding** (plan §2.4): the default policy is `venue_stop_required`; whether
  app-managed holding is ever acceptable is undecided.

## 4. Change log of shared knobs (date · change · why · evidence)

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
