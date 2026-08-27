# Technique platform — one engine, many techniques

*Written 2026-08-27 after the first live day of the EnhancedMarket (EM) technique. Status:
**phases 0, 1 and 2 are built, parity-tested and live (same day)**; 2b (durable positions), 3
(research/API/settings), 4 (UI shell) and 5 (the second technique) remain. §1–§2 keep the original
analysis as the record of the starting point, with as-built notes. Owner: the technique layer.
Companion docs: `ARCHITECTURE.md` (the app — its "Technique platform" section is the as-built
reference), `PLATFORM-RULES.md` (the shared judgement log),
`techniques/enhanced-market/PIPELINE-PLAN.md` / `techniques/enhanced-market/WALKFORWARD-PLAN.md` (how EM was built),
`techniques/enhanced-market/TRADING-RULES.md` (the method judgement log).*

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

## 1. The starting point (as of `77f5a97`, the morning of the build — kept as the record)

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

### 1.4 Entangled — where the real work was *(resolved by phases 0–2 the same day; the table is the before-picture)*
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

As built (2026-08-27) — ✔ = exists, → = still to come:

```
backend/zargar/
  marketstructure/        ✔ SHARED LIBRARY — pure functions over bars, no I/O, no settings reads
    levels.py volume.py candles.py structure.py history.py     ✔ moved verbatim (old paths are shims)
    sessions.py           ✔ the ET session clock (cut out of EM's rulebook)
    rules.py              ✔ MarketRules (duck-compatible with EM's Thresholds) + windows + DEFAULT_LADDER
    tracker.py            ✔ TriggerTracker / level_respect / score_trigger (cut out of walkforward)
    outcome.py            ✔ simulate_plan · __init__ exports distance_pct / count_touches
    (facts stays in EM's analysis.py until phase 2's tail — it imports setups)
  execution/              ✔ SHARED RUNTIME
    listener.py exits.py book.py                               ✔ (pre-existing)
    planrunner.py         ✔ PlanRunner(SessionListener): arm/restore/persist, off-loop fire chain,
                            entry+retry, sizing + premium caps, ladder/stop/flatten management, loss
                            halt, quote/premium stop watch, failed-exit watchdog, alerts, audit,
                            phone summary, pre-open orchestration, clock-driven close, hookStats
    positions.py policies.py simulate.py                       → phase 2b (durable multi-day manager)
  research/               → phase 3 (today: the generic halves of technique/service.py)
  techniques/
    base.py               ✔ TechniqueInfo + registry (GET /api/techniques)
    enhanced_market/      → phase 3/4 rename; TODAY EM still lives at zargar/technique/ —
                            arming.py = PlanArmer(PlanRunner), 319 lines of hooks; rulebook, setups,
                            plans, schemas, vision, chat, analysis stay there
    tip/                  → phase 5
```

### 2.1 The technique protocol
A technique produces **data** — a `SessionPlan` with `Trigger`s — and a handful of policies.
The shared runner does everything risky.

As built, the protocol is the **hook set of `PlanRunner`** (every default is the "no opinion"
path; hooks judge, the runner journals — none of them may journal):

```python
class PlanRunner(SessionListener):
    TECHNIQUE_ID: str                                     # registry id on plans + order intents
    def rules(self) -> MarketRules                        # what the trackers/exits read
    async def load_plan(self, run_id) -> dict             # the run record with result.plan
    async def load_baseline_bars(self, run_id, tf)        # prior-session bars (volume baseline)
    def entry_windows_enforced(self) -> bool              # EM: R6 unless the mid-day experiment
    async def analyze_fire(self, ap, tid, tr, trade) -> FireJudgement     # deterministic, no I/O
    def reviewer_available(self) -> bool
    async def review_fire(self, ap, tid, tr, trade, j) -> (verdict, confidence, critic)
                                                          # EM: prompt assembly + verdict; the RUNNER
                                                          # owns timeout, fail-open budget, veto
                                                          # cooldown, kill cap, re-arming
    async def record_fire(...); async def emit_proposal(...); async def after_fire(...)
    async def pick_contract(self, ap, trade) -> dict | None   # expression (T5 pick for EM)
    def size_multiplier(self, contract) -> (mult, why)        # EM: Friday x0.5, 0DTE x0.5
    def preopen_due(self, now) -> bool
    async def preopen_check(self, ap, premarket) -> {rows, reference, gapPct, replan}
    async def build_replacement_plan(self, ap, *, reference_price) -> run | None
    async def arm_today(self, symbol, ...)                # build + arm today's plan on demand
```

The wider `Technique` protocol (plan construction, `score()`, `ui`) arrives with phases 3–4 when
the research layer and the UI shell go generic; `TechniqueInfo.tabs` is its first slice.

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

### 2.3 Identity everywhere *(built in phase 0; settings scoping is the phase-3 piece — spec in §8.4)*
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
| **0 · identity** ✅ *built 2026-08-27* | `technique` column on the five tables; `techniques/base.py` + registry with one entry; run/armed/sweep/setup dicts carry `technique`; Sidebar/TabBar read `GET /api/techniques` (fallback: EM); `OrderIntent.technique_id` on every intent the armer raises | none | small |
| **1 · library** ✅ *built 2026-08-27* | `zargar/marketstructure/` = levels, volume, candles, structure, history, outcome, **tracker** (TriggerTracker / level_respect / score_trigger cut out of walkforward), **sessions** (the ET clock, cut out of rulebook), **rules** (`MarketRules`, duck-compatible with EM's `Thresholds`, with `windows`); old `technique.*` paths are shims; `distance_pct` / `count_touches` public; `tests/test_platform_phase0.py` asserts the library imports without the technique package. Still in EM: `analysis.py` (imports `setups`) — moves with phase 2 | none (full suite) | medium |
| **2 · runner** ✅ *built 2026-08-27* | `execution/planrunner.py` = `PlanRunner(SessionListener)`: everything that moves money, moved verbatim from `arming.py` (2,334 → 375 lines of EM). Hooks (the EM dev team's list, safest first): `size_multiplier` (Friday/0DTE), `pick_contract` (T5 vehicle; the shares fallback stays runner-side), `entry_windows_enforced` + `rules().windows` (R6; R6.5 extended-hours suppression stays runner-core), `preopen_due`/`preopen` (09:25 judgement + re-plan), `analyze_fire` + `reviewer_available`/`review_fire` (EM owns prompt assembly + verdict; the **runner** owns timeout, fail-open budget, pause-on-exhaust, veto cooldown, kill cap, re-arming and their persistence), `record_fire`/`emit_proposal`/`after_fire`, `load_plan`/`load_baseline_bars`, `arm_today`. **Hooks never journal** — the runner journals hook results, so the event schema stays uniform. `gap_unchecked` and `middayExperiment` still flow into the review context. Exit policy (ladder / single-contract exit / flatten minutes) stays `ArmConfig` data for now. The pre-open judgement is now runner-orchestrated too (`_run_preopen` journals; EM's `preopen_check` returns keep\|replan data and `build_replacement_plan` builds the fresh run) — **no hook journals anywhere** | none (arming + walk-forward + review suites; include-invalid replay) | large — done as one verbatim move with the seams as hooks, deployed after the close |
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
method change logged in `techniques/enhanced-market/TRADING-RULES.md` under the technique's own heading.

## 7. Decisions
Settled (dated in `PLATFORM-RULES.md` §4 and EM's TRADING-RULES):
- 2026-08-27 · Technique ids/labels: `enhanced_market` / "EM Options"; `/api/technique/*` stays the EM alias through phase 4.
- 2026-08-27 · Phase 2 timing: done same-day with user authorization (practice money), one verbatim move with hook seams, parity suites + the include-invalid audit after each step.
- 2026-08-27 · `technique.arm.midday_trading` is **EM-only, never a platform key** (user + EM team).
- 2026-08-27 · Veto/critic budgets: **platform defaults with per-technique override** — resolution `techniques.<id>.<key>` → `execution.<key>`, spec in §8.4 (user + EM team).

- 2026-08-27 · **Tip IS the second technique** (and Flow the third, context-only); entry is a
  **per-source policy** — level-touch by default, tip-time earned by a positive scorecard (user).
  Plans: `docs/techniques/tip/PLAN.md`, `docs/techniques/flow/PLAN.md`; candidates research in
  `docs/TECHNIQUE-CANDIDATES.md`.

Still open:
1. Overnight policy default `venue_stop_required` — assumed yes, confirm before phase 2b starts.
2. Phase 2b timing (the second money path; ships with the chaos suite or not at all).

## 8. Engine backlog — the EM team's operating list (2026-08-27)

Ranked; ✅ = built the same day, the rest are scheduled into the phases.

| # | Idea | Status / phase |
|---|---|---|
| 1 | **Clock-driven session close** — expiry + scorecard fire at 16:05 ET by the clock, not on the 15:59 bar (08-26: the bar never came, nothing scored) | ✅ `PlanRunner._end_session` shared by the bar path and a heartbeat clock check |
| 2 | **Daily pre-open feed self-test** — 09:00 ET REST bar fetch + WS auth handshake, loud alert on failure (the 08-26 subscription lapse degraded silently) | ✅ `engine._feed_monitor`: `FeedSelfTestPassed/Failed` journal + critical toast + Telegram |
| 3 | **Event-schema contracts** — versioned schema per `TECHNIQUE_PLAN_*` kind + a contract test; N techniques journaling through shared machinery makes payload shapes an API | phase 3 (research split) — the contract test lands with the event registry |
| 4 | **Per-technique settings scoping + live re-read** — spec settled with the EM team 2026-08-27 (user decisions: mid-day toggle EM-scoped; veto budgets inherit-with-override): **resolution for every key `planrunner.py` reads directly is `techniques.<id>.<key>` (per-technique override) → else `execution.<key>` (platform default)** — the veto/critic family (`critic_kills_per_day`, `refire_cooldown_minutes`, `critic_fail_budget`, `critic_timeout_seconds`) explicitly included, plus quote-exit, stale-seconds, premium-stop and the live-auto gate. Old `technique.*` names stay as deprecated aliases for a migration window with `SettingChanged` journal continuity. **`technique.arm.midday_trading` is explicitly excluded: EM-only, never a platform key** (read in exactly one place — EM's `entry_windows_enforced()`). Plus: `max_concurrent_runs` re-read without a restart | phase 3 — spec ready |
| 5 | **Bars table hygiene** — unique index on (symbol, tf, ts), bucket alignment enforced at write, stub-row cleanup | phase 3, cheap-now item; do before technique #2 writes bars |
| 6 | **Hook observability** — per-hook latency / exception / veto-rate ("which hook, how often, how slow" = a query) | ✅ counters: `PlanRunner._hook()` wraps analyze/review/pick/record/proposal/preopen; `hookStats` on the armed summary. Journal roll-up still open (with #3's event registry) |
| 7 | **Per-technique pause** — HALT stays global; "stop EM, keep X" is a first-class control whose exits stay reduce-only-exempt like the kill switch | phase 4/5 (needs a second technique to mean anything; API shape reserved: `POST /api/techniques/{id}/pause`) |
| 8 | **Replay outputs carry plan-side validity** — includeInvalid sweeps stamped every trigger `valid: true` (two wrong tallies in the 08-27 gate audit) | ✅ `replay_plan` joins `valid` from the plan trigger |
| 9 | **Version-stamp marketstructure into sweepVersion** — a parity diff must be attributable to a library version | ✅ `technique_source_version()` hashes `marketstructure/` too (extends the existing `sweepVersion`) |
