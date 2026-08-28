# Tip technique — build plan

*Planned 2026-08-27 from `docs/TECHNIQUE-CANDIDATES.md` §3 (research + audit of the old
signals path) after the wave-one trim (user decisions: T1+T2 greenlit; entry policy =
per-source, default level-touch, tip-time only for sources with a positive scorecard).
Runs on the technique platform (`docs/TECHNIQUE-PLATFORM-PLAN.md`); the engine team owns
Phase 2b/3 per the 2026-08-27 requirements memo — those dependencies are marked ⚙ below.
Status: **FULLY BUILT 2026-08-27** — Phase A (intake/extraction v2, dedupe, parking,
per-source policies, plan builder, scorecards), the `TipRunner` (level-touch arming through the
shared `PlanRunner`; tip-time sources propose immediately instead), the **dual shadow books**
with the morning `tip_shadow_arm` loop and expiry-bounded waiting (§4), the **Phase 2b handoff**
of filled entries to the durable position manager (§4), and **Phase B options expression in both
books** (`BUILD-PLAN.md` — the per-tip vehicle rule, `express.py`, premium budgets, shorts as
puts). The Tips page was redesigned 2026-08-28 (New tip · Tips · Sources · Inbox tabs, source
auto-detection via `source_hint`). Tests: `tests/test_signals_tip.py`, `tests/test_tip_runner.py`.
§2/§3 below are kept as the build record; §4 is the decision log. Building this surfaced and
fixed two platform bugs (order-pipeline bracket deadlock; unfiltered runner restore) —
PLATFORM-RULES §4. Standing decision: the platform default source mode is **proposal** (a human
approval is itself a gate); "shadow until the scorecard clears" governs AUTO mode specifically.*

## 0. What it is

A tip — from a Discord room (screenshot or paste), a newsletter email, Telegram, or the
user's own head — says "this symbol is going up/down, roughly this hard, roughly this soon."
The technique turns that into a monitored plan with a budget, expresses it as an option
(2–4 week DTE, never 0DTE), manages it out with a profit ladder + trailing + time stop, and
— before any source touches real money — builds that source a shadow track record it must
earn its way out of.

Hard boundaries (from the research, non-negotiable):
- Tips arrive via a **human or a service's own bot/API**. No Discord scraping, no
  autonomous execution of room alerts. Screenshot-of-your-own-client → vision is fine.
- **Shadow-first per source**: real money only for sources whose scorecard clears the bar.
- Sizing is budget- and risk-capped per tip AND per source; the never-list (0DTE, naked
  calls, share shorts) is RiskGate's job (⚙ memo B7).

## 1. Identity

- id `tip`, label "Tips", registry entry in `techniques/base.py`; runs/outcomes/armed rows
  carry `technique="tip"` (column exists since platform phase 0).
- Settings under `techniques.tip.*` resolving to `execution.*` (⚙ memo B1; until the
  resolver lands, keys live flat in `settings_service.DEFAULTS` with the target names).
- Per-source scorecards need runs/outcomes to carry `tags: ["source:<name>"]` (⚙ memo B2);
  until then the source name rides in run `config` and the scorecard query joins on it.
- Docs: this file + `docs/techniques/tip/TRADING-RULES.md` (created with the first live
  decision; every rule change logged there, per platform invariant §6).

## 2. Phase A — buildable now (no engine dependencies)

### A1. Extraction v2 (`signals/schemas.py`, `signals/extraction.py`)
The current `TradeSignal` cannot carry the trade (no strike/expiry/DTE, 5-value timeframe
enum nothing reads). New flat schema (flat — the LLM gotcha about nested schemas applies):

- symbol, direction (long|short), conviction, **instrument hint** (shares|call|put|either),
  strike?, expiry?, dte_hint? ("next week" → int range), entry_ref?, targets[] (prices or
  %), stop? , horizon_sessions? , catalyst?, evidence quotes, is_actionable.
- Grounding: keep verbatim-quote grounding for prose sources; add a **shorthand path** for
  Discord-style text ("NVDA 180c 9/19 🚀"): prices/strikes ground by normalized token match
  (strip $, commas, c/p suffixes) instead of literal substring — the current rule fails
  exactly the messages this technique exists for.
- **Screenshot intake**: `POST /api/ingest/manual` accepts `imageDataUrl`; reuse
  `technique/vision.py` + `sniff_media_type` + the `chat_assets` blob store (plumbing
  exists in the technique layer, wire it to `SignalService`). The vision pass extracts the
  text; extraction v2 runs on that text; the image is kept as evidence.
- **Dedupe**: content hash on RawContent + a semantic key (source, symbol, direction,
  strike, expiry) with a 24 h window — a duplicate attaches to the existing signal as a
  "seen again" event (which is itself signal: repeat mentions raise conviction) instead of
  minting a second proposal/shadow fill.

### A2. Source registry → source policy (`settings_service`, new `signals/sources.py`)
Today `sources.registry` only maps sender → name. It becomes a policy record per source:

```
techniques.tip.sources.<name>:
  entry: level_touch | tip_time      # default level_touch; tip_time must be EARNED (A4 bar)
  budget_per_tip / budget_open_max   # $ caps; also mirrored as a RiskGate tag cap (⚙ B3)
  risk_pct                           # per-tip risk sizing input
  dte_window: [10, 30]               # option expression window, days
  mode: shadow | alert | proposal | auto   # default shadow
  min_conviction, max_open_tips
```
The default for an unknown source is shadow-only with the platform defaults.

### A3. Plan construction (`techniques/tip/plan.py`)
Tip → `SessionPlan` with ONE `Trigger`, `kind="tip"`, direction from the tip:
- `entry=level_touch`: entry at `marketstructure.nearest_level(detect_levels(bars), price)`
  on the tip's side (below price for longs); stop = the level below / ATR-based
  (`marketstructure.atr`); a tip whose price never comes back expires unfilled after
  `horizon_sessions` — that is a *recorded outcome* ("never triggered"), not a failure.
- `entry=tip_time`: an immediate-condition trigger (fires on the next bar), stop ATR-based.
- Targets: the tip's stated targets if grounded, else R-multiples (defaults in settings).
- `TriggerRules(volume_floor=None, gap_policy="ignore", windows=ALL_DAY, stop_on="close")`
  — same tracker, tip numbers (platform plan §2.1).
- Verification v2 replaces the old one-shot kill: the 8 checks still run, but "price
  deviated from stated entry" now *parks* the plan (waiting for the level) instead of
  killing the signal. Kill reasons that remain: ungrounded, unresolvable ticker, halted,
  below min price, spread.

### A4. Shadow-first + the scorecard (closes the audit's "collected but never scored" gap)
- Every verified tip auto-arms **in shadow** regardless of source mode (this generalizes
  `_shadow_execute`, which becomes a real armed plan on the sim/shadow venue instead of a
  fire-and-forget market order).
- Outcomes scored by `simulate_plan` like every technique; a nightly pass aggregates
  per-source: n scored, win rate, avg R, expectancy, max drawdown of the shadow book.
- **The bar** (settings, defaults): a source may leave shadow when `n >= 20` scored tips
  AND expectancy > 0; `tip_time` entry additionally requires expectancy > 0 *measured on
  tip-time fills* in shadow. Falling back below the bar demotes the source (journaled).
- UI: per-source scorecard table (replaces the dead SignalsPanel), tip lifecycle view
  (received → grounded → parked/armed → fired → managed → scored), and the source policy
  editor. Interim home: rebuilt InboxPage ("Tips"); moves into the technique shell at
  platform phase 4.

### A5. Tests
Extraction fixtures for Discord shorthand / newsletter prose / screenshot-OCR text (canned,
no LLM — the `canned_extraction` convention); dedupe window; parked-plan re-arm when price
returns; plan construction both entry modes; shadow scorecard math; the tracker parity
suite picks up `kind="tip"` triggers automatically.

## 3. Phase B — the money path *(BUILT 2026-08-27 — the as-built record is `BUILD-PLAN.md`; this section is the original plan)*

Lands when Phase 2b ships; everything here is policy/data on shared machinery:
- `express()`: option pick via the shared chain access with the source's `dte_window`
  (default 10–30 d), just-OTM by default, respecting `min_strike` direction mirror;
  shares fallback where no chain exists (.TO names).
- `exit_policy()` (policies-as-data, ⚙ memo A1): ladder 50/50 at T1/T2 + `trail_after(+1R)`
  + `time_stop(horizon_sessions, default 10)` + `dte_close` + `premium_stop` +
  `flatten_before("earnings")` unless the tip's catalyst *is* earnings (then the source
  policy must say so explicitly).
- Overnight: `venue_stop_required` for shares; options expected `app_managed` + per-arm
  acknowledgement (⚙ A7 answer pending).
- Budgets: `budget_per_tip` caps the debit; RiskGate tag caps enforce the per-source
  ceiling (⚙ B3). Auto mode obeys all existing live gates (`allow_live_auto`,
  `trading.mode`, per-arm `allowLive`).
- Critic: reuse the fire-critic seam with a tip prompt (does live tape contradict the
  tip? spread sane? IV already pumped? — the "chasing IV" failure mode from the research).

## 4. Decisions taken / still open

- ✅ Entry: per-source policy, default level_touch, tip_time earned (user, 2026-08-27).
- ✅ **Dual shadow books** (user, 2026-08-27 — built same day): every source keeps TWO
  pretend accounts (`Portfolio.book`): **immediate** ("buy the moment the tip verified" —
  the source's raw quality; the old shadow market order) and **armed** ("wait for the
  level with managed exits" — what the app actually does; the morning loop
  `tip_shadow_arm` on the scheduler auto-arms every open level-touch tip there in auto
  mode, budget-sized). The scorecard shows both side by side; `barCleared` judges the
  ARMED book (real money would trade that way); `tipTimeEarned` flags a source whose
  immediate book demonstrably beats its armed book — the evidence that its tips run away
  and it has earned tip-time entry. One tip, two books, never blended.
- ✅ **Options tips die at expiry** (user, 2026-08-27 — built same day): the wait-for-the-
  level window is capped at `expiry − techniques.tip.entry_cutoff_dte` (default 2 days —
  entering later is buying theta), using the tip's stated expiry or its DTE hint
  (`techniques/tip/horizon.py`). Past the cutoff the signal becomes **expired** (journaled
  `SignalExpiredUnfilled`) — itself a scorecard datum ("the level never came"). The same
  expiry caps how long a FILLED position may be held (`time_stop_sessions` = sessions to
  the thesis expiry), even when expressed in shares.
- ✅ **Phase 2b handoff** (built same day, on the engine team's `PositionManager`): when an
  auto entry FILLS, the trade leaves the session runner and becomes a durable managed
  position — policy: fixed stop, ladder 50/50 on the tip's first two targets, structure
  trail after +1R (`techniques.tip.trailing_after_r`), time stop at the thesis expiry,
  earnings flatten unless the tip's catalyst IS earnings; shares rest a venue GTC stop.
  The runner's end-of-day flatten never touches a handed-off position. An entry unfilled
  after 10 minutes stays session-scoped (flatten applies — safe).
- ✅ Shadow bar: 20 scored tips + positive ARMED-book P&L (default — tune in
  TRADING-RULES once real sources exist).
- ~~Known measurement gap: short tips~~ **CLOSED 2026-08-27 by Phase B** (`BUILD-PLAN.md`
  T1/T2): both books express option-shaped tips as contracts (stated strike/expiry
  verbatim, else the policy DTE window) and shorts as puts end-to-end; a tip with no
  usable contract falls back to shares (longs) or is honestly recorded as not expressed
  (shorts), never silently skipped.
- Open: keep email ingest webhook auth as-is or move behind session auth; whether repeat
  mentions ("seen again") should bump conviction automatically or just display; Telegram
  as an *intake* (today it's outbound + approvals only); options expression for BOTH
  books at once (Phase B — instrument must match across books or the comparison breaks).
