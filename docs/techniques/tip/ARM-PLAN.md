# Tips → Arm: wiring review and enrichment plan

*Complete (all boxes ticked). The follow-up gap-closure work found by the
2026-08-29 full-sweep audit lives in `ARM-GAPS-PLAN.md` (clusters A–F).*

*2026-08-29. Full code review of the tip→arm path (plan.py, runner.py,
express.py, arming.py/SessionListener, proposals.py, lifecycle.py, analyst.py,
technique/plans.py, walkforward tracker). Five phases, checkboxes to tick off
during implementation. Charter context: ANALYST.md; intake context:
INTAKE-PLAN.md.*

## 0. The wiring at review time (the PRE-implementation snapshot)

*This §0 is the 2026-08-29 review that motivated the plan. All five phases have
since landed (see the ticked checkboxes and the implementation notes at the
end); F1–F10 are closed. Kept as the findings log — read it as history, not as
the current state.*

Two lanes leave a verified tip, and they are not coordinated:

| lane | trigger | vehicle | exits | who decides |
|---|---|---|---|---|
| **Buy now** (proposal) | none — immediate | analyst's contract (never chases above its limit) | analyst's exit plan via `lifecycle.adopt_when_filled` | analyst verdict `take` (+ human/auto approve) |
| **Wait for level** (arm) | shared `TriggerTracker`: bounce/reject (touch), breakout/breakdown (close-through) | stated contract verbatim, shares fallback | **fixed 50/50 ladder** (`runner._handoff`) | the human clicks `arm` (alert mode); the morning loop arms the shadow book |

What the arm machinery already does well (inherited from EM's execution
stack): both directions with shorts-as-puts, budget sizing, pre-open re-plan,
quote stop-watch + premium stop + failed-exit watchdog, restart recovery,
per-plan loss halts, alert/proposal/auto modes with live-money acks, full
journaling + outcome scoring via the same `simulate_plan`.

### Findings (2026-08-29 review)

- **F1 — lane conflict**: `create_from_signal` never checks `policy.entry`, so
  a `level_touch` source gets a tip-time proposal while `arm_signal` *refuses*
  anything but level_touch. The two lanes can act on the same tip differently.
- **F2 — the analyst cannot arm**: its only expression is buy-now. "Wait for
  the 22 retest" has no analyst-driven path to an armed plan.
- **F3 — two exit authorities**: proposal fills run the analyst's plan; armed
  fills run the hardcoded `TIP_LADDER` 50/50 (duplicated in plan.py comment +
  `_handoff`). ANALYST.md gap A6.
- **F4 — UI arms alert-mode only** (`ArmButton` hardcodes `mode: "alert"`);
  no instrument/mode choice, no "arm instead of propose" affordance.
- **F5 — schema headroom**: `SessionPlan.triggers` is a LIST (scale-ins are an
  extension); `Condition.kind` already has a vocabulary (touch, close_through,
  window, volume, decisive, followthrough) — conditional entries extend it.
- **F6 — adopt-on-fill not restart-safe** (proposal lane): the waiter is an
  in-process task; an approved-but-unfilled order at shutdown is never adopted.
- **F7 — risk-cap clash**: `budget_per_tip` ($1,000) exceeds
  `risk.max_option_premium_pct` (5% of $10k) and `risk.max_position_notional`
  ($1,000 exactly) — full-budget takes get risk-rejected with no warning at
  proposal/arm time.
- **F8 — fragile fatal check**: a transient quote miss fails `ticker_resolves`
  fatally (the AMZN case, 2026-08-29) — an explicit call dies on a feed hiccup.
- **F9 — proposal TTL vs the clock**: a take created after hours expires
  (30 min) long before the next open.
- **F10 — scorer parity risk**: outcomes replay through `simulate_plan` with
  the 50/50 book arithmetic; changing live exits (Phase 2) without teaching the
  scorer breaks the walk-forward identity the platform guarantees.

## Phase 1 — the analyst chooses: buy now vs arm at the level

*Closes F1/F2/F7/F8/F9. The analyst's verdict gains an entry mode; "take"
stops meaning "market now" by default.*

- [x] `AnalystOpinion` += `entry_mode` ("now" | "at_level"), `entry_level`
      (underlying price to wait for), `entry_note` — prompted-JSON stays flat.
- [x] Prompt: teach the choice ("the tip says wait / the level is below price /
      chasing here breaks your rules → at_level") with examples.
- [x] Pipeline: verdict `take` + `at_level` → `TipRunner.arm_signal` (mode from
      the source policy, instrument from the vehicle rule, analyst level
      override into `build_tip_plan(tip_entry=)`) instead of `create_from_signal`.
- [x] Lane coherence: suppress tip-time proposals for `level_touch` sources
      unless the analyst explicitly said `now` (and journal which lane won).
- [x] Arm context carries `analystRunId` + the exit plan (prep for Phase 2);
      the armed run links back to the appraisal in the UI.
- [x] Parked tips ("price already past entry") become armable by the analyst —
      parked is precisely "waiting for the level".
- [x] Preflight coherence check: at proposal/arm creation, compare the tip
      budget against `risk.max_option_premium_pct` / `max_position_notional`
      and surface the clash on the card (journaled) instead of a silent
      risk-rejection at fill time.
- [x] Quote-resolution failure PARKS an explicit call instead of killing it
      (retry on the next quote; the AMZN fix). *(Was already fixed on main —
      `ticker_resolves` is in PARKING_CHECKS since 2026-08-28.)*
- [x] Off-hours takes: proposal `expires_at` = next session open + TTL, not
      created-at + 30 min.
- [x] Tests: at_level take arms (no proposal); level_touch source mints no
      tip-time proposal; parked tip armed by analyst; preflight warning on
      budget/cap clash.

## Phase 2 — one exit authority: the analyst's plan everywhere

*Closes F3/F6/F10 (ANALYST.md A6). Deterministic code stays the executor;
the analyst becomes the single author of exit campaigns.*

- [x] `runner._handoff` builds its policy from the signal's analyst
      `exitPlan` via `lifecycle.policy_from_exit_plan` (fallback: today's
      default ladder), replacing the inline dict.
- [x] De-duplicate `TIP_LADDER`: one source of truth in `lifecycle.py`; plan
      target math keeps using the plan's own targets.
- [x] Decision + docs: the ARMED **shadow book** stays on the standard 50/50
      ladder so the scorecard's counterfactual stays comparable across
      sources; only REAL-money arms adopt the analyst plan. (Record in
      TRADING-RULES.md.)
- [x] Scorer parity: the run's `config` snapshots the exit plan; the outcome
      scorer replays with IT (`simulate_position`/`simulate_plan` path) — live
      and replay change together, parity-tested.
- [x] Restart-safe adoption: persist pending adoptions (approved-not-yet-
      filled tip proposals) and re-arm the waiters in `attach_tip_runner`,
      like armed-plan restore.
- [x] Invalid analyst plan → fallback is journaled AND shown on the analyst
      run's outcome line ("plan rejected: …, default ladder used").
- [x] Verify + test `update_exit_plan` against armed-handoff positions
      (technique == tip regardless of lane).
- [x] UI: managed-position card shows the exit campaign's author
      (analyst #run / default) with a link to the run.
- [x] Tests: armed fill runs the analyst ladder; restart mid-wait still
      adopts; parity test live-vs-simulate with a custom plan.

## Phase 3 — entry zones and scale-ins (multi-trigger plans)

*Uses F5's headroom: `triggers` is already a list; sizing becomes per-trigger.*

- [x] Extraction v2: `entry_zone_low/high` and `scale_in` (list of
      price+fraction) fields, flat schema + validators.
- [x] `build_tip_plan`: a zone becomes a touch band (entry = zone mid,
      tolerance widened to the zone edges) with the stop beyond the far edge.
- [x] Multi-trigger plans: one trigger per scale-in level, each with a
      `size_fraction`; plan-level invariant: fractions sum ≤ 1.
- [x] `PlanArmer`: per-trigger sizing (budget × fraction), fills accumulate
      into ONE managed position (append legs / re-average entry), single exit
      campaign over the combined size.
- [x] Tracker: reuse existing touch/breakout mechanics per trigger — no new
      state machine; triggers arm/void independently.
- [x] Outcome scorer: multi-fill simulation (weighted entry) — parity with the
      armer's accumulation.
- [x] Analyst schema: `entry_levels` + `entry_fractions` mirror the exit
      ladder, so the analyst can author "half at 22.60, half at 22.10".
- [x] UI: the armed-plan card renders the entry ladder like the exit ladder.
- [x] Tests: zone fill inside the band; 2-trigger scale-in → one position with
      averaged entry; partial (only first trigger fills) expiry behavior.

## Phase 4 — conditional and timed entries

*Extends the existing `Condition` vocabulary; everything price-relative stays
in `marketstructure`, parameterised by `MarketRules`.*

- [x] Condition kinds: `ema_reclaim` (close back above the N-EMA on the
      trigger tf), `holds_above` / `holds_below` (level held for N bars),
      `guard_symbol` (cross-symbol: "while SPY > 640"), `time_at` (ET time).
- [x] `marketstructure`: EMA primitive on the trigger tf (pure, picklable —
      the walk-forward process pool constraint).
- [x] Cross-symbol guards evaluated on bar close from the quotes/bars cache;
      guard failure = trigger stays dormant, journaled once per session.
- [x] Timed trigger: fires at its ET time via the armer's bar loop (respects
      the calendar; never during a halt).
- [x] Extraction: condition phrases ("if it reclaims the 8EMA", "as long as
      SPY holds 640", "at tomorrow's open") → structured conditions.
- [x] The analyst can author conditions in its arm request (same schema).
- [x] `simulate_plan` evaluates the same conditions (parity) — change both or
      neither.
- [x] Graceful degrade: an unsupported condition arms WATCH-ONLY with the
      reason on the card, never silently ignored.
- [x] Tests: one per condition kind, live-vs-simulate parity, dormant-guard
      journaling.

## Phase 5 — defined-risk multi-leg (spreads)

*The deepest lift; build when a source actually trades spreads at us. The
never-list holds: no naked short options — short legs exist only inside a
defined-risk group.*

- [x] Research first: SnapTrade multi-leg order support on Webull CA (probe
      like `snaptrade_options_check`; single-leg sequencing is the fallback).
- [x] Extraction grammar: "340/360 call spread", "put credit spread", debit vs
      credit orientation.
- [x] `express`: leg-pair picking — existence + liquidity on BOTH legs, net
      debit/credit computation, width sanity.
- [x] RiskGate: a defined-risk order GROUP exception to `no_naked_short_option`
      (short leg valid only when covered by a long leg in the same group; max
      loss = width − credit, capped by the tip budget).
- [x] Order placement: grouped legs with rollback (mirror
      `PositionManager.open`'s half-open rollback).
- [x] `PositionManager`: entry wiring for net-credit positions (the policy
      engine already speaks `profit_target_pct_of_credit`).
- [x] Analyst opinion: `legs[]` expression + spread-aware exit plans (close at
      % of max profit / width stops).
- [x] Shadow books: spread counterfactuals priced leg-by-leg (marks exist via
      the chain snapshots).
- [x] Tests: paper spread entry + credit-target exit; naked short leg alone is
      risk-rejected; rollback on second-leg rejection.

## Sequencing note

1 → 2 are routing over existing machinery and should land together (the arm
lane must carry the exit plan before it becomes the analyst's default lane).
3 and 4 are independent of each other; both depend on 2 (one exit authority)
to avoid teaching the scorer twice. 5 stands alone and waits for demand.


## Implementation notes (2026-08-29, all five phases landed)

- **P1**: lane suppression applies when an analyst opinion exists — a take
  chooses `now` (proposal) or `at_level` (arm, `TipRunner.arm_from_analyst`);
  watch/skip keeps today's proposal behavior so the human can overrule an
  advisory verdict. Journal kind `TipLaneDecided`; the opinion gains
  `armedRunId`. Found & fixed on the way: weekend arming planned for the
  weekend day itself (plan_for now rolls to the next session) and the tip
  runner tests were weekday-sensitive.
- **P2**: real-money armed fills run the analyst campaign
  (`policy_from_exit_plan`); shadow-book fills keep `DEFAULT_TIP_FRACTIONS`
  (50/50) for scorecard comparability. Position-level parity is the chaos
  suite's live-vs-`simulate_position` guarantee (policies are data evaluated
  by one engine); plan-level `technique_outcomes` deliberately stay on the
  standard ladder as the comparable counterfactual. Pending adoptions resume
  on boot (`lifecycle.resume_pending_adoptions`); exit authors are tagged
  (`exit:analyst:<run8>` / `exit:default`).
- **P3**: zones become 2-rung ladders; triggers carry `sizeFraction`
  (serialized only when != 1 — EM wire dicts unchanged); fills accumulate via
  `PositionManager.append_leg` (journal `ManagedPositionScaledIn`), one stop
  beyond the deepest rung, one campaign. Caveat: two rungs of IDENTICAL size
  firing within the 10s duplicate window would collide — distinct rung sizes
  or minutes-apart fills avoid it (documented, seen only in synthetic tests).
- **P4**: `marketstructure/guards.py` (ema_reclaim / holds_above / holds_below
  / guard_symbol / time_at); bars reach a tracker only while its guards pass;
  guard-fired plans (conditions with no level) enter at the first passing
  bar's close (trigger kind `timed`); `simulate_plan` evaluates the same
  documents. `guard_symbol` is live-only by nature — in replay it degrades to
  watch-only (never fills), the documented parity exception.
- **P5**: spreads propose as one `secType="SPREAD"` unit; approval runs
  `lifecycle.open_spread` — the LONG leg must FILL before the short leg goes
  out (tagged `spread:<gid>`; the risk gate accepts a short option leg only
  when the covering long is already held — a lone short leg stays naked and
  rejected). Net-credit pairs run `profit_target_pct_of_credit`; max loss is
  declared as the position's no-stop guard. The shadow book expresses stated
  spreads the same way. Venue research (RUN LIVE 2026-08-29, `snaptrade_options_check --probe income`):
  **Webull Canada ACCEPTS a native 2-leg defined-risk spread in one impact
  call** (both MARGIN and CASH; short opens accepted too); Wealthsimple stays
  1156-unsupported. The app ships leg-sequencing today; a native-mleg executor
  is a clean future upgrade at Webull. Found & fixed on the way: the duplicate-order key
  ignored the portfolio, so a shadow-book leg blocked the real one.

## Post-landing follow-ups (found in live use)

- [x] **Armed-hub visibility** (2026-08-29 evening, user report — the "phantom armed
  item"): plans armed by the tip runner (`arm_from_analyst`, the shadow armed
  book) were invisible to `GET /api/technique/armed` and every hub endpoint
  (summary, detail, exit, mode, pause/resume, stop-all, the `/api/health`
  restart-guard count) because the hub only consulted EM's armer — while the
  shared `PlanRunner._publish` WS deltas DID carry them, so the Armed badge
  said 1 and the page said 0, flickering on every 30s poll. Fixed with the
  `engine.plan_runners` registry that every hub endpoint aggregates
  (per-plan actions route by `runner_for(run_id)`); `attach_tip_runner`
  registers the runner (and `engine.techniques["tip"]` — a runner is its own
  `.armer`, so `/api/techniques/tip/*` resolves too). Regression test walks a
  tip-armed plan through the whole hub; invariant recorded in
  `PLATFORM-RULES.md` §2 and `BUILDING-A-TECHNIQUE.md` §2. Verified live:
  the SPY jon-and-kian armed-book plan shows steadily on the Armed page,
  badge and page agree, restart guard reports "armed plans restored: 1".
