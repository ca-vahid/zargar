# Tips → Arm: gap-closure plan (clusters A–F)

*2026-08-29. Source: the full-sweep audit run after ARM-PLAN landed (three parallel
code reviews over the armed lifecycle, the management/follow-up paths, and
expression/risk/settings — every finding below carries the file:line evidence the
sweep verified, so implementation sessions don't need to re-audit). Companion to
`ARM-PLAN.md` (the five build phases, complete); this plan closes what live use
and the audit exposed.*

## Decisions (user, 2026-08-29)

- **All six clusters are in scope.**
- **Multi-day armed plans STAY ARMED** across sessions (user's preference,
  confirmed here as the design): one run id, one audit trail, the plan rolls
  internally at each session close instead of disarming and re-arming each
  morning. The alternative (a morning re-arm job mirroring `tip_shadow_arm`)
  was considered and rejected — it proliferates `technique_armed` rows, splits
  the audit across runs, and adds a scheduled job that can be missed.
- EM plans remain strictly single-session — every multi-day behaviour below is
  gated on the plan's own horizon (`context.horizonSessions > 1` /
  `ArmConfig.horizon_sessions`), never on the technique id, so a future
  multi-day technique inherits it for free.
- `gapped_past` on a level-touch tip (market opens through our buy level): the
  trigger no longer dies silently — the plan **rolls and keeps watching** (the
  level often gets retested) and the event alerts. Chasing the open remains
  forbidden.

---

## Cluster A — the armed tip survives until its horizon

*The flagship at_level lane currently works for exactly one session
(`planrunner.py:1657-1680` expires at the close; only the shadow book re-arms),
restore hard-expires `plan_for < today` (`planrunner.py:536-542`), and a
proposal-mode fire produces nothing (`planrunner.py:1838-1848` + the base
`emit_proposal` no-op at `:2371-2374`).*

- [ ] **A1 — horizon on the ArmConfig/plan.** Compute the plan's last valid
  session at arm time (`effective_wait_sessions` → `expiresSession`, bounded by
  contract expiry − `entry_cutoff_dte`); carry `horizonSessions`,
  `sessionsUsed`, `expiresSession` on the armed snapshot. Wire format
  camelCase; persisted in `technique_armed.state`.
- [ ] **A2 — roll at the close instead of expiring.** `_end_session` for a
  multi-day plan: run the session housekeeping (score the day's trades, cancel
  resting entry orders), keep `status="armed"`, advance `plan_for` to the next
  trading session (calendar-aware), rebuild the trigger trackers fresh for the
  new session (same path as a morning arm: `_complete_opening_bars` gives the
  09:30 gap judgement), increment `sessionsUsed`, journal a
  `TechniquePlanRolled` event (register the contract; note in
  PLATFORM-RULES §4). The nightly `_expire_by_clock` (16:05 path,
  `planrunner.py:2269-2279`) rolls the same way.
- [ ] **A3 — expire properly at the horizon.** When `sessionsUsed` reaches the
  horizon, or the contract's DTE falls below `entry_cutoff_dte` at roll time:
  expire through the full `_end_session` path (scored + journaled + scorecard —
  the restore shortcut at `planrunner.py:538-541` currently skips scoring),
  emit `SIGNAL_EXPIRED_UNFILLED` on the signal exactly as the shadow loop does
  (`runner.py:433-448`).
- [ ] **A4 — restore rolls instead of expiring.** On boot, a row with
  `plan_for < today` whose horizon still has sessions left re-arms rolled
  forward to today (re-checking `entry_cutoff_dte`); sessions missed while the
  app was down count against `sessionsUsed` and are journaled. A row past its
  horizon expires through the scored path (A3), never the silent write.
- [ ] **A5 — `TipRunner.emit_proposal`.** A proposal-mode tip fire creates a
  real proposal at the touch: vehicle = the analyst's contract when the arm
  came from an appraisal, else the tip's stated contract, else the book's
  expression (same preference order as `create_from_signal`); limit from C1's
  never-chase cap; TTL from `_ttl_expiry`; context carries
  `vehicle`/`explain`/`analystRunId`/`armedRunId`. Telegram + push get the
  approval card (`topics.PROPOSALS` already wires both). A proposal-creation
  failure escalates via `_alert` and sets `needsAttention` — never the current
  silent `proposal_failed` log line.
- [ ] **A6 — `gapped_past` rolls, loudly.** For a plan with horizon > 1, a
  trigger terminal-ed by `gapped_past`/`gapped_through` is revived at the next
  session's roll (fresh tracker, next open re-judged); the event journals and
  alerts ("SPY opened through your 768.8 level — not chasing; watching for the
  retest"). Same-session behaviour unchanged (no chasing).
- [ ] **A7 — UI: the card says where in the horizon it is.** "day 2 of 5 ·
  expires Thu 09/04" on the Armed card and the Now view; History groups a
  multi-day plan as one row with per-session sub-lines, not N ghost rows.
- [ ] **A8 — tests.** Multi-day plan fires on day 3 (roll × 2 then touch);
  restart mid-horizon restores rolled; horizon exhaustion expires scored; DTE
  cutoff expires at roll; proposal-mode fire mints a proposal with the right
  vehicle; `gapped_past` day-1 → fires on day-2 retest; EM single-session
  behaviour unchanged (regression: existing arming suite green).

## Cluster B — no orphaned money

*Partial fills are never adopted (`lifecycle.py:337-349` breaks only on
`FILLED`), the spread rollback is fire-and-forget (`lifecycle.py:174-192`), the
shares fallback ignores the tip budget (`planrunner.py:1869-1876`), and the
fill→handoff→flatten sequence has no interlock (`runner.py:462-474` vs
`exits.py:50-53`).*

- [ ] **B1 — adopt partial fills.** `adopt_when_filled` (and
  `resume_pending_adoptions`) treats `PARTIALLY_FILLED` as adoptable: when the
  order goes terminal (or the 4h timeout fires) with `filled_qty > 0`, adopt
  the filled portion with the analyst's policy and **cancel the resting
  remainder**; journal `TIP_POSITION_ADOPTED {partial: true, filled, ordered}`.
  The timeout branch cancels the resting order instead of abandoning it.
- [ ] **B2 — armed partial fills hand off too.** `_handoff_when_filled` accepts
  a partial: at session end, hand off the filled quantity (multi-day thesis
  keeps living) and cancel the remainder — instead of today's flatten of the
  whole position (`runner.py:469-478`).
- [ ] **B3 — spread rollback is verified and loud.** `open_spread`'s rollback
  sell: await the fill, retry (market, ×N with backoff), and on final failure
  journal a dedicated event, fire the runner-style alert (journal + WS toast +
  Telegram), and adopt the naked long as an `attention` managed position with
  an emergency exit policy — a naked leg must never exist outside the
  PositionManager's view. The shadow-book fallback path journals its downgrade
  instead of swallowing it (`service.py:1216-1220`).
- [ ] **B4 — the shares fallback keeps the budget.** When an option tip falls
  back to shares, qty is additionally capped so notional ≤ the plan's
  `premiumBudget` (journaled when the cap binds). No tip expression may exceed
  the tip's budget by construction.
- [ ] **B5 — fill→handoff→flatten interlock.** On entry fill, mark the trade
  `handoff_pending` before `adopt` starts; `_manage`/`plan_exit` skip
  handoff-pending trades; `_handoff` re-checks the trade wasn't already exited
  before adopting. Kills the 15:57 double-sell/phantom-position race.
- [ ] **B6 — tests.** Partial adopt + remainder cancel (proposal and armed
  lanes); rollback retry then alert + attention-position on forced failure;
  budget-capped fallback qty; the flatten race with a fill landing on the bar
  boundary (chaos-suite style).

## Cluster C — the fire honors the thesis

*The armed fire pays whatever the ask is (`planrunner.py:1995` — the proposal
path's never-chase guard from the $16k-quote incident never made it here), uses
the tip's contract even when the analyst reasoned about a different one
(`runner.py:118-123` vs `proposals.py:173-179`), never re-checks DTE on a
stated expiry (`express.py:61-67`), and substitutes contracts silently
(`express.py:68, 213`).*

- [ ] **C1 — never-chase cap on the armed fire.** Entry limit =
  min(live ask, reference premium × (1 + `techniques.tip.max_chase_pct`, new
  knob, default ~10%)) where the reference is the analyst's `limit_price`, else
  the tip's stated premium, else absent (no cap — but then C4's substitution
  marker shows). Above the cap: skip the fire with a journaled, alerting
  `premium_chase_blocked` (the level can roll to the next session under A6's
  logic; the thesis isn't dead just because one print was bad).
- [ ] **C2 — the analyst's contract wins on the armed path.** `arm_from_analyst`
  stores the opinion's contract on the plan; `pick_contract` prefers it
  (existence/liquidity re-checked live at the touch as today), then the tip's
  stated contract, then the book's just-OTM pick — the same preference order the
  proposal path already has.
- [ ] **C3 — fire-time DTE floor.** A stated/analyst expiry is accepted at the
  touch only if its DTE ≥ `entry_cutoff_dte`; otherwise pick the nearest valid
  expiry in the policy window and mark the substitution (C4). Kills the
  "dte_min=10 but bought 1-DTE on the last allowed day" hole.
- [ ] **C4 — substitutions are visible.** The contract payload carries
  `statedContract` + `substituted: true` + the reason whenever the bought
  contract differs from what the tip/analyst named; the Armed card and the
  proposal card render "tip said F 250C 09/05 — bought 252.5C 09/12: stated
  strike not listed". No more silent swaps.
- [ ] **C5 — tests.** Chase-blocked fire (bad quote), analyst-contract
  preference on an armed fire, DTE-floor substitution, substitution marker on
  the wire + card (UI build).

## Cluster D — follow-ups close the loop

*A source exit can't touch a waiting plan or pending proposal (no disarm tool —
`analyst.py:101-199`; `armedRunId` write-only; verification ignores
`action:"close"` so an exit message can open NEW exposure), re-arming double-arms
(`runner.py:209`; `_armed_today` unused outside the shadow loop), re-posts only
bump a counter (`service.py:836-857`), the lane choice is never graded
(`TIP_LANE_DECIDED` has zero consumers), and the analyst can close shadow-book
positions (`analyst.py:328-344`).*

- [ ] **D1 — verification is action-aware.** `action in ("close","trim","exit")`
  never verifies as an open: it routes to the review lane referencing the
  source's open items (position, waiting plan, pending proposal) instead of the
  proposal/shadow lanes. A no-ticker exit message ("I'm out") reaches the
  review run too — keyed off the source having open items, with the mirror
  context identifying what "it" is.
- [ ] **D2 — signal → armed-run index + a `disarm_plan` tool.** Maintain the
  live index at arm time (today `extraction.analyst.armedRunId` is written and
  never read; `runs_for_signal` exists unexposed). Give review/appraise runs a
  `disarm_plan` tool (tip-technique plans only, waiting-only — a plan with an
  open trade goes through `close_position`/`update_exit_plan` as today);
  journaled with the analyst's reason, surfaced on the run's play-by-play.
- [ ] **D3 — the analyst can SEE waiting plans.** `get_open_tips` (and the run
  preamble for the tip's source) includes each open tip's armed state: run id,
  waiting levels, day X of N, pending proposal if any. "Our book" =
  positions + waiting commitments.
- [ ] **D4 — proposals are follow-up-aware.** Index pending proposals by
  `signal_id`; a verified source exit/reversal expires the pending proposal
  with a reason ("source exited before approval") — journaled, card shows why.
  `auto` mode must check this at approval time (no self-approve of a reversed
  idea).
- [ ] **D5 — re-arm replaces, never doubles.** `arm_signal`/`arm_from_analyst`
  check the signal's live armed run first: default is refuse with the existing
  run id (API 409-style), explicit `replace: true` disarms the old plan then
  arms the new one atomically. `_armed_today` becomes the shared check.
- [ ] **D6 — seen-again refreshes.** A re-post of an open tip annotates the
  armed plan (journal on the run: "source repeated the call, seen_count=3"),
  and knobs decide the rest: `techniques.tip.seen_again_extends` (roll the
  horizon window forward, default off) and `seen_again_reappraise` (queue a
  review run, default on when the analyst is enabled).
- [ ] **D7 — grade the lane choice.** A nightly consumer of `TIP_LANE_DECIDED`:
  when a tip resolves (filled+closed or expired), compare the chosen lane
  against the counterfactual the shadow books already hold (immediate vs armed
  row for that signal) and write the delta to the source scorecard +
  a `lane` note the analyst reads. "The analyst chose at_level 9 times; now
  would have paid better 6 of 9" becomes visible.
- [ ] **D8 — learning from non-fills.** The retro sweep grows a second query:
  expired-unfilled plans and expired proposals get a lightweight batch retro
  (one run per source per day max) whose lessons go to notes/rules — the
  misses teach too.
- [ ] **D9 — shadow-book quarantine.** `_manage_guard` and the `managed` list
  handed to the analyst exclude shadow-book portfolios; the analyst can never
  see or close a counterfactual position (scorecard integrity).
- [ ] **D10 — tests.** Exit message disarms via analyst; exit message can no
  longer open exposure; no-ticker exit reaches review; re-arm refuses/replaces;
  pending proposal expires on source exit incl. auto-mode block; seen-again
  annotates + optional reappraise; lane grader writes the scorecard delta;
  analyst payloads contain no shadow positions.

## Cluster E — config & knobs coherence

*EM-prefixed knobs silently govern tip plans (`technique.enforce_session_windows`,
`technique.options.enabled`, `technique.max_risk_pct` read raw at
`planrunner.py:723-793`; `PRIME_WINDOWS` hardcoded into `windowOpenNow`), the
settings UI has zero `techniques.tip.*` controls, the arm preflight is
analyst-only and its warning is dropped from the snapshot (`runner.py:292`), a
config-less API arm bypasses the vehicle rules (`runner.py:192-207`), and the
DEFAULTS still encode the premium/notional clash the runtime has already fixed.*

- [ ] **E1 — every shared-path read goes through `rt()`.** Migrate the raw
  `technique.*` reads in `planrunner.py` to the resolver so
  `techniques.tip.enforce_session_windows` / `.options_enabled` /
  `.max_risk_pct` exist and win; `windowOpenNow` derives from the plan's own
  `rules().windows`, not the hardcoded EM prime windows (fixes the phone Now
  payload lying about when a tip can fire).
- [ ] **E2 — a Tips settings section.** Surface `techniques.tip.*` (mode,
  budgets, dte window, entry_cutoff_dte, retro knobs, the new chase/seen-again
  knobs) in the Settings UI under Tips; the shared `execution.*` panel stops
  being labeled as EM's "Auto-trading" (rename to "Execution (all
  techniques)"). No knob a tip obeys should be editable only under EM's name.
- [ ] **E3 — preflight everywhere, warning visible.** The cap preflight runs on
  every arm path (analyst, API/UI button, config-less); `riskWarning` rides the
  armed snapshot and renders on the Armed card exactly like the proposal card
  does today.
- [ ] **E4 — config-less arms get the vehicle defaults.** `arm_signal(config=None)`
  applies the same shape-derived defaults the UI path gets (instrument from the
  tip's shape, `entryFallback: "shares"`, `premiumBudget` from the source
  budget) — the raw-API footgun closes.
- [ ] **E5 — defaults + stale docs.** Reconcile `settings_service.DEFAULTS` with
  the values the runtime already runs (`risk.max_option_premium_pct` 25,
  `risk.max_position_notional` 5000 — or pick deliberate fresh-install values
  and document them); fix ANALYST.md §8, which still describes the clash as
  open.
- [ ] **E6 — per-source policy editor.** The Sources tab gets the deferred
  editor: per-source mode (alert/proposal/auto), budget, entry policy
  (level_touch/tip_time), min conviction, horizon — reading/writing the same
  policy objects `create_from_signal` consumes. The trust-bar graduation
  ("earned tip-time") gets its button here.
- [ ] **E7 — botsOnly is visible and validated.** The Sources UI shows each
  watch entry's botsOnly flag with a warning when mirrored traffic shows the
  tips come from humans (🌟｜muggzone-options today: botsOnly=true but MuggZone
  posts as a human — that source can never auto-intake); fix that entry.
- [ ] **E8 — tests + audit.** Settings-resolution tests for every migrated key
  (tip override wins, EM value ignored); preflight-on-all-paths test;
  config-less arm shape test; `npm run mobile-audit` after the Settings/Sources
  UI work.

## Cluster F — observability & UI wiring

*A tip plan and an EM plan are indistinguishable on the Armed page (technique
never rendered — `ArmedTab.tsx:113-133`), EM's mid-day copy shows on plans that
CAN fire mid-day, `useCritic: true` renders on plans nothing critiques, the Tips
list shows no armed state, the analyst run says "see the Armed page" without a
link, fire-time failures don't raise `needsAttention`, and a tip fill notifies
by push only.*

- [ ] **F1 — the Armed card knows what it is.** Render the technique chip and
  the `source:<name>` tag; window copy comes from the plan's own rules (a tip
  shows "fires any time in RTH", not EM's "mid-day watching only"); hide/grey
  `useCritic` when the runner has no reviewer.
- [ ] **F2 — Tips list shows the armed state.** Each tip row: "armed — waiting
  at 768.8 · day 2/5" (or "proposal pending", "position open — managed") with a
  click-through to `/armed/<runId>`; expose `runs_for_signal` as
  `GET /api/signals/{sid}/runs`.
- [ ] **F3 — the analyst run links its plan.** The at_level outcome line and the
  handoff step render `armedRunId` as a chip navigating to the Armed page
  (`store.armedFocusRunId` already exists for the hand-off).
- [ ] **F4 — fire-time failures raise attention.** "no proposal could be
  created", "no option contract available — nothing sent" and
  `premium_chase_blocked` all route through `_alert` + `needsAttention`, not
  bare journal lines (extends `_attention_reasons`).
- [ ] **F5 — Telegram on fills.** `techniques.tip.telegram_fills` (default on):
  an auto-mode tip entry fill / handoff sends the Telegram message with the
  deep link, matching what proposals already get.
- [ ] **F6 — phone pass.** The Now view shows tip plans with technique + day-N
  context; `npm run mobile-audit` green.
- [ ] **F7 — visual inspection.** Live end-to-end: arm a multi-day tip, roll it
  across a (simulated) close, fire a proposal at the touch, inspect
  Armed/Tips/Analyst/phone views for artifacts — same bar as ARM-PLAN's
  acceptance.

---

## Sequencing

A → B are the pre-conditions for trusting the arm lane with real money and land
first (A2/A3/A4 are one coherent change to `_end_session`/`restore`; A5 next;
B1/B2 together; B3 standalone). C rides on A5/C2's shared preference order.
D1/D2/D5 unblock the follow-up story before D6-D8's learning loops. E1 before
E2 (the knobs must exist before the UI edits them). F last, except F4 which
lands with A5/C1 (their alerts are its content).

Cross-cutting rules: every new knob in `settings_service.DEFAULTS`; every new
event registered + noted in PLATFORM-RULES §4; `technique_armed`/`events` rows
never edited; each cluster's tests green before its box ticks; suites
(`test_tip_runner`, `test_signals_tip`, `test_position_*`, `test_technique_arming`)
green at every merge.
