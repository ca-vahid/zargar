# Technique platform — one engine, many techniques

*Written 2026-08-27 after the first live day of the EnhancedMarket (EM) technique. Status: **plan,
not built**. Owner: the technique layer. Companion docs: `ARCHITECTURE.md` (the app),
`TECHNIQUE-PIPELINE-PLAN.md` / `TECHNIQUE-WALKFORWARD-PLAN.md` (how EM was built),
`TRADING-RULES.md` (the method judgement log).*

## 0. The idea

Zargar was built to run **many techniques** on one engine. EM is the first; the next may be
nothing like it — a *tip* technique that takes a "this stock is going up" signal, buys the
option, and manages it out with its own profit-taking. What those techniques share is not the
idea but the machinery around it: how we know price is *touching* a level, how far it is in
percent, whether volume is adequate, when a level is dead, how a fill becomes a managed
position with stops and a ladder, how a run is journaled, replayed, scored and reviewed.

Today that machinery exists but most of it lives inside `zargar/technique/`, which is named,
configured and wired as if EM were the only technique. This plan turns it into three shared
libraries plus a thin per-technique package, without a big-bang rewrite: every phase keeps EM
running and its parity tests green.

## 1. What we have (as of `77f5a97`)

### 1.1 Already shared and technique-agnostic
| Where | What |
|---|---|
| `engine.py`, `bus.py`, `events.py` (Journal), `risk.py` (RiskGate), `orders.py` (OrderManager), `portfolio.py`, `brokers/*`, `options/*`, `marketdata.py`, `settings_service.py` | The trading engine. No technique knowledge. Every order path already goes through RiskGate. |
| `zargar/execution/` (`SessionListener`, `exits`, `book.ManagedTrade`) | The shared live loop (1m bars + orders + heartbeat + quote watch), pure exit decisions, reduce-only intents, the position lifecycle record. Written for reuse; EM's `PlanArmer` is its only subclass so far. |
| `signals/*`, `approvals/*` | Extraction → grounding → verification → proposal → shadow portfolios. **This is the tip path**; a tip technique starts here, it does not re-invent it. |
| Armed page + `/api/technique/armed/*` | Designed cross-technique (the fleet is "every armed plan from every technique"); the only EM hard-code was the `Tech` column, replaced 2026-08-26 by the Setup column. |

### 1.2 Should be shared, currently filed under EM (the "market-structure library")
These are pure functions over bars. They are exactly the library the next technique will ask for
("is it touching the line? what's the percentage?"):

| Module (`technique/`) | Reusable content |
|---|---|
| `levels.py` | `find_pivots`, `_tolerance`, `_count_touches` (in-band semantics, fixed 08-27), `_cluster`, `detect_levels`, `nearest_level`, `atr`, round-number candidates |
| `volume.py` | `build_profile`, `relative_volume`, `volume_trend`, `price_trend`, `assess_volume` |
| `candles.py` | `metrics`, `is_decisive`, `classify` (hammer / engulfing …) |
| `structure.py` | `fit_line`, `read_trend`, `detect_wedge` |
| `analysis.py` | bars → FACTS (swing highs/lows, breaks with volume at the break bar) |
| `walkforward.py` | `level_respect`, **`TriggerTracker`** — the touch / break / gap / volume / false-break / invalidation state machine shared by live, plan and sweep; `replay_plan`, `score_trigger`, `plan_window`, session helpers |
| `outcome.py` | `simulate_plan(plan, bars, stop_on, breach_r)` — direction-aware forward walk, the same code the backtester and the outcome scorer use |
| `history.py`, `render.py`, `llm.py`, `grounding.py`, `provenance.py`, `review.py`, `bundle.py`, `universe.py` | Bars fetch (Yahoo v8, clipped to now), chart PNGs for vision, Claude plumbing (flat schemas, thinking display, media sniffing), number grounding, run provenance, review taxonomy, run bundles, the universe layers |

### 1.3 EM-specific (stays in the technique)
`rulebook.py` (R/T rule ids, `Thresholds`, the R6 windows), `setups.py` (bounce/breakout
arithmetic, TP ladder geometry, stop anchors), `plans.py` (`build_session_plan` — the book's
pre-session routine, trigger grading), `schemas.py` / `vision.py` / `tools.py` / `chat.py`
(prompts, the 4-pass read, chat tools), `options.py` (just-OTM weekly/0DTE pick — an EM
*policy* over the shared chain providers), `backtest.py`, the docs and TRADING-RULES entries.

### 1.4 Entangled — where the real work is
| Piece | Size | Generic part | EM part |
|---|---|---|---|
| `technique/arming.py` (`PlanArmer`) | 2,334 lines | arm/restore/persist, `_spawn_fire`, entry with retry, contract pick + sizing, `_manage`/`_exit`, loss halt, quote stop watch, premium stop, failed-exit watchdog, `_alert`, audit, `summary()` for the phone | R6 session windows, gap rule on the 09:30 bar, pre-open re-plan, the critic prompt, 0DTE cutoff, Friday multiplier, TP2 single-contract exit, `max_false_breaks` |
| `technique/service.py` (`TechniqueService`) | 2,329 lines | run persistence, cancel, outcomes loop, reviews, replay, diff, bundles, sweeps/sheets/process pool, orphan marking, universe refresh, armed proxies | `analyze()`/`_execute()` (the EM vision pipeline), `_emit_proposal`, scan loop, sheet loop timing |
| `api/routes_technique.py` | 53 routes under `/api/technique/…` | runs, reviews, replay, sweeps, armed, universe | analyze, chat, rules, backtest |
| `settings_service.DEFAULTS` | 91 `technique.*` keys (38 `technique.arm.*`) | risk %, contracts, caps, flatten time, critic budget, quote exit, premium stop, universe | volume floor, gap void R, touch tolerance, windows, 0DTE cutoff, rr gate |
| `models.py` | `technique_runs/outcomes/reviews/sweeps/walkforward/armed/setups` | all of it | **no `technique` column anywhere**; `orders.source` is `String(12)` = `"technique"` |
| `events.py` | 28 `TECHNIQUE_*` kinds | all of it | payloads assume EM trigger kinds |
| Frontend | `TechniquePage.tsx` ≈1,150 lines, `store` slice `technique*`, `Sidebar`/`TabBar` "EM Options", `SettingsPage` "EnhancedMarket pipeline" | tabs shell, runs list, sweeps, armed dashboard, plan cards | analyse form, chat, rules panel, EM labels |

## 2. Target shape

```
backend/zargar/
  marketstructure/        SHARED LIBRARY — pure functions over bars, no I/O, no settings reads
    levels.py  volume.py  candles.py  structure.py  facts.py  distance.py
    tracker.py            TriggerTracker + TriggerRules (parameters, not rulebook lookups)
    outcome.py            simulate_plan
  execution/              SHARED RUNTIME — turning a plan into managed money (exists; grows)
    listener.py  exits.py  book.py
    planrunner.py         generic PlanRunner(SessionListener): arm/restore/fire/enter/manage/exit/alert
    sizing.py             risk-based sizing, caps, day-of-week / DTE multipliers as parameters
    expression.py         "how to express a level idea": shares vs option pick (shared chain access)
  research/               SHARED RESEARCH — runs, provenance, outcomes, reviews, replay, bundles, sweeps/sheets, LLM plumbing
  techniques/
    base.py               the Technique protocol + registry
    enhanced_market/      today's technique/ minus what moved out: rulebook, setups, plans, schemas, vision, chat, live hooks
    tip/                  (future) signal-driven technique
```

### 2.1 The technique protocol
A technique produces **data** — a `SessionPlan` with `Trigger`s — and a handful of policies.
The shared runner does everything risky.

```python
class Technique(Protocol):
    id: str                      # "enhanced_market", "tip"  (settings prefix technique.<id>.*)
    label: str                   # "EM Options"
    version: str                 # goes into run provenance

    def universe(self, ctx) -> list[str]                       # default: shared universe layers
    async def plan(self, ctx, symbol: str, as_of: int, *, reference_price=None) -> SessionPlan
    def trigger_rules(self, ctx) -> TriggerRules               # tolerance, volume floor, gap policy,
                                                               # windows, max false breaks, stop_on, cooldown
    def express(self, ctx, trigger) -> Expression              # shares | option pick policy (strike/expiry/DTE rules)
    def exit_policy(self, ctx, trade) -> ExitPolicy            # ladder, single-contract exit, flatten time, trail/time stops
    async def critic(self, ctx, fire) -> Verdict | None        # optional second opinion; None = no critic
    def score(self, plan, bars) -> Outcome                     # default: marketstructure.simulate_plan
    ui: TechniqueUI                                            # tabs to show, settings sections, labels
```

Shared data types (most already exist in `plans.py` / `walkforward.py` / `book.py` and move to
`marketstructure` / `execution`): `Level`, `Trigger`, `Condition`, `SessionPlan`,
`TriggerRules`, `TriggerState`, `ManagedTrade`, `Expression`, `ExitPolicy`, `Outcome`.

**The one rule that makes this work:** rules become *parameters*. Today `TriggerTracker`
reads `rulebook.Thresholds`; tomorrow it takes a `TriggerRules` value the technique built.
Same state machine, same parity tests, different numbers — and a tip technique can pass
`volume_floor=None, gap_policy="ignore", windows=ALL_DAY` and reuse the entry/stop/invalidation
logic unchanged.

### 2.2 The shared library, as the next technique will call it
```python
from zargar.marketstructure import (
    detect_levels, nearest_level, count_touches, distance_pct, level_respect, atr,
    relative_volume, assess_volume, classify_candle, is_decisive, read_trend, detect_wedge,
    facts, TriggerTracker, TriggerRules, simulate_plan,
)
levels  = detect_levels(bars_by_tf, rules.level)                 # [Level(price, kind, touches, age, tfs)]
lv      = nearest_level(levels, price)                           # the one the tip should respect
pct     = distance_pct(price, lv.price)                          # "+1.41% above"
touched = count_touches(bars_1m, lv.price, rules.tolerance)      # in-band touches only
ok_vol  = relative_volume(bars_1m, profile) >= rules.volume_floor
tr      = TriggerTracker(trigger, rules); state = tr.on_bar(bar)  # waiting → observed → fired | gap_void | invalidated | exhausted
out     = simulate_plan(plan, bars, stop_on=rules.stop_on)        # what would have happened
```

### 2.3 Identity everywhere
- DB: a `technique` column (String(32), default `"enhanced_market"`) on `technique_runs`,
  `technique_sweeps`, `technique_armed`, `technique_setups`, `technique_outcomes`
  (`db.create_all` adds columns additively — no manual migration).
- Orders: keep `orders.source = "technique"` (12 chars) and put `technique_id` in the order
  intent meta / journal payload, so nothing about the risk path changes.
- Journal: keep the `TECHNIQUE_*` kinds; every payload carries `technique`.
- Settings: `technique.<id>.*` per technique; the shared runtime reads `execution.*` (risk %,
  caps, flatten time, critic budget, quote exit, premium stop). Migration maps today's
  `technique.arm.*` → `execution.*` and the EM-only knobs → `technique.enhanced_market.*` with the
  UI-editable defaults preserved (settings are journaled, so the rename is auditable).
- API: `/api/techniques` (registry) and `/api/techniques/{id}/…`; `/api/technique/*` stays as an
  alias for `enhanced_market` until the UI is moved.
- UI: Sidebar/TabBar list the registry (`Techniques ▸ EM Options ▸ Tip …`); the technique page
  becomes a shell whose tabs come from `TechniqueUI`; the Armed page shows a technique chip.

### 2.4 The durable position manager — holding for days or weeks
*(added 2026-08-27 after the user's requirement: the library must monitor a stock for days or
weeks and take profits automatically, and it must be iron-clad.)*

EM's runner is **session-scoped**: a plan is armed for one date, expires at the close,
`flatten_minutes_before_close=5` closes everything, `restore()` re-arms only `plan_for >= today`,
exits are judged on 1m bars during the session, and outcomes are scored from Yahoo 1m depth
(~20 days). None of that is wrong for EM — but a tip technique that buys a 3-week call and wants
to scale out over ten sessions cannot be built on it. So the shared runtime gets a second
object next to the session plan:

```
execution/
  planrunner.py     session plans: watch triggers for ONE session (EM today)
  positions.py      ManagedPosition: a position that lives until its policy closes it —
                    days, weeks, across restarts, weekends, holidays and feed outages
  policies.py       exit policies as DATA, evaluated by shared code:
                    ladder(targets, fractions) · trailing(atr_mult | pct | structure="last swing low")
                    · breakeven_after(+R) · time_stop(sessions) · dte_close(min_dte)
                    · premium_stop(pct) · strength_exit(extension) · flatten_before(event)
  simulate.py       simulate_position(policy, bars_by_tf) — the same evaluation over history,
                    so a policy is backtested by the code that will run it live
```

How it must behave (these are requirements, not suggestions):
- **Position-scoped state, write-ahead.** `managed_positions` table: policy, legs, fills, the
  bar-timeframe it is judged on, last decision, provenance (technique, plan, trigger). Persisted
  before every order; restored on boot regardless of date. The plan that opened it is history.
- **Venue-side protection whenever the venue can do it.** For anything held overnight the manager
  places a resting GTC stop (and optionally the first target) at the broker — `OrderManager`
  already builds GTC bracket children (`orders.py`), SnapTrade maps `GTC`, IBKR supports it —
  so the app being down does not leave a naked position. Where the venue cannot (a venue with
  no GTC stops on options), the policy must say `overnight="venue_stop_required"` and the manager
  refuses to hold, or `overnight="app_managed"` with an explicit acknowledgement and a loud
  "app-managed only" flag on the Armed page.
- **Judged on closed bars of the policy's timeframe** (5m / 15m / 1d), with the quote watch as
  the crash brake (as today: decisive breach × N polls), **only while the venue can fill** — RTH
  for options, and never a decision on a stale quote (staleness → exits allowed on last known,
  no new entries).
- **Reconciliation, not trust.** On boot and every N minutes: our positions vs broker positions
  (`/positions/all`, IBKR portfolio). Drift → adopt (`adopt_order` exists) or alert; a position
  the broker no longer has is closed in our book with a journaled reason; one we don't know about
  is surfaced, never silently managed.
- **Idempotent money.** Client order ids on every intent; unknown submit outcomes reconcile
  against the venue (SnapTrade `_reconcile_unknown` today) and never resubmit blindly.
- **Options expiry is a policy, not an accident.** `dte_close(min_dte)` closes before expiry; an
  ITM contract must never be left to auto-exercise/assignment. (Today expiry settlement exists
  only for practice portfolios — `OptionsService.settle_expired`.)
- **Exits are reduce-only and unblockable** (halt, caps, rate window never stop a stop); the
  failed-exit watchdog (retry ×5 then alert) and the `_alert` escalation (log + journal + toast +
  Telegram) are the shared path for every failure mode.
- **Event awareness.** Earnings/ex-dividend calendar gate (the B-list item) becomes a policy
  input: `flatten_before("earnings")` or `reduce_before(...)`.
- **Fleet-wide caps** (open positions, gross exposure, per-symbol) live in RiskGate, not in a
  technique.

### 2.5 What "iron clad" means as tests
A position manager is only as reliable as the failures it has been run through. Before any
technique holds real money overnight the shared layer needs a **chaos suite** on the sim rig:
restart mid-position (state restored, venue stop still there), feed outage during RTH (no false
exits, alert raised), partial fills and rejected exits (watchdog retries, reduce-only), venue
disconnect on an exit (reconcile, never duplicate), expiry day (dte_close fires), a weekend and
a holiday (no decisions, no drift), a halt while holding (exits still allowed), and the same
policy replayed by `simulate_position` over the fixture bars producing the same decisions the
live path made (parity, as with the tracker). These are the acceptance tests for Phase 2b below.

## 3. Migration — five phases, EM green throughout

Parity harness that gates every phase: `tests/test_technique_walkforward.py` (sweep rows equal
promoted runs; live tracker == replay), `tests/test_technique_arming.py` (25 tests on the sim
rig), `tests/test_technique_review.py` (replay/outcome), plus a frozen fixture: the 2026-08-25
and 08-26 sweeps re-run must produce byte-identical rows.

| Phase | Work | Behaviour change | Size |
|---|---|---|---|
| **0 · identity** | `technique` column on the five tables; `techniques/base.py` + registry with one entry; run/armed dicts carry `technique`; Sidebar/TabBar read the registry (still one item); order intent meta gets `techniqueId` | none | small |
| **1 · library** | Create `marketstructure/`; *move* levels/volume/candles/structure/analysis/outcome/tracker there (old paths re-export, so nothing breaks); introduce `TriggerRules`, built by `rulebook.rules_from_settings()`, consumed by tracker / outcome / exits instead of `Thresholds` directly; `distance_pct`/`count_touches` become public | none (parity fixture) | medium |
| **2 · runner** | Split `arming.py`: `execution/planrunner.py` (generic lifecycle) + `techniques/enhanced_market/live.py` (windows, gap on the 09:30 bar, pre-open re-plan, critic prompt, 0DTE cutoff, Friday multiplier, TP2 single exit) as hook implementations; `execution/sizing.py`, `execution/expression.py`; `ArmedPlan.technique` | none (arming tests) | large — the money path; do it in a quiet week, one hook at a time |
| **2b · durable positions** | `execution/positions.py` + `policies.py` + `simulate.py`; `managed_positions` table; venue-side GTC protection; reconciliation loop; the chaos suite (§2.5). Independent of EM — EM keeps its session plans | new capability | large — the second money path; ships with the chaos suite or not at all |
| **3 · research + API + settings** | `research/` for runs/outcomes/reviews/replay/bundles/sweeps/sheets keyed by technique; `/api/techniques/{id}`; settings namespaces with a one-time key migration | key renames only | medium |
| **4 · UI shell** | `TechniquePage` → generic shell + per-technique panels (EM keeps Validation/Analyse/Chat/History/Backtest); Settings gets a per-technique section; Armed chip | cosmetic | medium |
| **5 · second technique** | Build **Tip** (below) on the platform. Every gap it finds becomes a protocol hook, never a fork of the runner | new feature | medium |

Phases 0–1 are cheap and give the library immediately; 2 is the risky one and should not start
while a live-money gate is open; 3–4 can interleave with method work.

## 4. Worked example — the Tip technique on the platform

```
signal (email / paste / Telegram) ─▶ signals.extract → ground → verify        (shared, exists)
  ─▶ tip.plan(): SessionPlan with ONE trigger, kind="tip":
        entry = next-bar open or a limit at the nearest shared level below price (marketstructure)
        stop  = ATR-based or the level below (marketstructure.atr / nearest_level)
        targets = the tip's target(s) or R multiples; direction from the tip
        rules = TriggerRules(volume_floor=None, gap_policy="ignore", windows=ALL_DAY, stop_on="close")
  ─▶ PlanRunner arms it like any plan (alert / proposal / auto; RiskGate; journal)
  ─▶ express(): shared option pick with the technique's DTE policy (e.g. 2–4 weeks, not 0DTE)
  ─▶ exit_policy(): trail after +1R, time stop at N sessions, ladder 50/50 — its own numbers, shared code
  ─▶ outcomes: simulate_plan scores it the same way; TRADING-RULES gets a `## Tip` section
```
Nothing above is new machinery; it is the same runner with different data and policies. The
shadow portfolio per source (already there) becomes the tip technique's track record.

## 5. What we deliberately do not share
Prompts, schemas and rule ids (each technique owns its vocabulary); plan construction (that
*is* the technique); grading; chat tools; the book's thresholds; the technique's docs and its
TRADING-RULES section. Sharing these would couple techniques through the wrong layer.

## 6. Invariants that survive the redesign (from CLAUDE.md, restated per technique)
Every order through `RiskGate.evaluate()` via `OrderManager.place()`; journal every decision;
write-ahead money paths; reduce-only exits that halts cannot trap; **one tracker shared by
live / plan / sweep with parity tests** (now per `TriggerRules`, still one class); the
live-persisted record beats replay on restore; restarts only mid-day or after the close; every
method change logged in `TRADING-RULES.md` under the technique's own heading.

## 7. Decisions needed
1. Technique ids and labels (`enhanced_market` / "EM Options" assumed).
2. Keep `/api/technique/*` as the EM alias during phases 0–4 (assumed yes).
3. Is **Tip** the second technique, and does it enter on tip-time or wait for a level touch?
4. Phase 2 timing — which quiet week; it must not overlap a live-money gate.
5. Overnight policy default: `venue_stop_required` (refuse to hold without a resting venue stop) — assumed yes.
