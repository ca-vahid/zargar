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

## 2. Findings (settled, with evidence)

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

## 3. Open questions the shared runtime is collecting data on

- **Reviewer net value** (EM 1.4 today): the runner's counters (kills, cooldown re-fires, failures)
  are per technique; a cross-technique tally is the capture-rate telemetry item.
- **Quote-stop breach parameters** (`quote_exit_excess_r` 0.25, `quote_exit_polls` 2): tuned on
  EM's 1m plans; a slower-timeframe technique may want wider.
- **Overnight holding** (plan §2.4): the default policy is `venue_stop_required`; whether
  app-managed holding is ever acceptable is undecided.

## 4. Change log of shared knobs (date · change · why · evidence)

- 2026-08-25 · Alpaca full-SIP stream + Alpaca-first history; feed-down alerting · Yahoo 429 incident.
- 2026-08-26 · `feed.exchange_bar_hold_seconds`=5 (A7) · exchange bars never reached the armer.
- 2026-08-26 · `technique.arm.critic_timeout_seconds`=25, `critic_fail_budget`=3 (A8) · fail-open
  with a budget replaces a silent stall.
- 2026-08-26 · `technique.arm.daily_loss_fallback`=100 (A2) · silent no-halt.
- 2026-08-26 · `technique.arm.contracts`=0 (risk-sized), `max_contracts`=10, `friday_size_mult`=0.5,
  `avoid_0dte_after`=10:30 (D2) · user decision; re-tighten before real money.
- 2026-08-26 · `technique.stop_on_close`=true (D3) · the runtime judges stops on the closed bar,
  the quote breach stays the brake.
- 2026-08-27 · Platform phases 0–2: `marketstructure` library, technique registry + `technique`
  identity column, `OrderIntent.technique_id`, `execution/planrunner.py` (generic runner) with EM as
  `PlanArmer(PlanRunner)` hooks · `docs/TECHNIQUE-PLATFORM-PLAN.md`; parity suites green.
