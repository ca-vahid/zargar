# Building a technique on the Zargar engine

*For the techniques team. Written 2026-08-27, after platform phases 0–3. The engine provides
capabilities; a technique provides judgement. Companion: `ARCHITECTURE.md` (the engine),
`TECHNIQUE-PLATFORM-PLAN.md` (what exists vs what's coming), `PLATFORM-RULES.md` (the invariants
you inherit — read §1 before writing any live code).*

## 1. What the engine gives you

| Capability | Where | What you get |
|---|---|---|
| Market structure | `zargar.marketstructure` | `detect_levels`, `nearest_level`, `count_touches` (in-band), `distance_pct`, `atr`, `relative_volume`/`assess_volume` (time-of-day baseline), candle classification, trendlines/wedges, the ET session clock, **`TriggerTracker`** (touch → observed → fired / gap_void / invalidated / exhausted), `simulate_plan`. Everything is parameterised by a `MarketRules` value **you** build — the library never reads your rulebook or settings. |
| Execution | `zargar.execution.planrunner.PlanRunner` | The whole money path: arm/restore/persist, the off-loop fire chain, entry with retry, risk-based sizing + premium caps, ladder/stop/flatten management on closed bars, loss halt, quote-stop + premium-stop watch, failed-exit watchdog, alert escalation (log + journal + toast + Telegram), audit, phone summary, pre-open orchestration, clock-driven session close (16:05 ET even if the closing bar never arrives), per-hook latency stats. You subclass it and fill in hooks (§2). |
| Data | bars table (1m…1h + `1d` daily layer), `option_chain_snapshots` (nightly per-contract OI/IV/volume/mid — history that cannot be backfilled), Yahoo/Alpaca history, CBOE/Tradier chains via `engine.options.provider()` (a platform setting, `options.provider` — never hardcode a provider) | |
| Calendar | `engine.calendar` (`EventCalendar`) | `await get(sym)` → earnings dates + BMO/AMC timing + ex-dividend; `days_to_earnings`, `days_to_ex_dividend`. Source v1 is Yahoo (advisory: `confirmed=False`) — treat as scan input and risk-reduction signal, not a firing trigger. |
| Scheduler | `engine.scheduler` | `register("my_scan", "20:00", fn)` — once per ET day, journaled (`ScheduledJobRan/Failed`), failure-alerted. This is how nightly/pre-open scans run; do not spawn your own timing loops. |
| Research | `technique_runs/outcomes/reviews/sweeps` (all with a `technique` column), free-form `tags` on runs (`analyze(tags=["source:xyz"])`, filter `GET .../runs?tag=`), replay/diff/bundles, walk-forward sweeps, the review CLI | |
| Signals front door | `signals/*` pipeline | Paste/email/Telegram/screenshot → extraction → grounding → verification → proposals + per-source shadow portfolios. A tip-style technique **starts here**; it does not build ingestion. |
| API | `GET /api/techniques` (registry), `GET/POST /api/techniques/{id}` + `/pause` + `/resume` + `/runs` + `/armed` | Pause stops new arms and fires for ONE technique; exits and open-position management keep running (reduce-only exempt, like the kill switch). |

## 2. What you implement

Register a `TechniqueInfo` in `zargar/techniques/` and subclass `PlanRunner`:

```python
class MyTechnique(PlanRunner):
    TECHNIQUE_ID = "my_technique"                 # registry id; stamps plans, orders, journal

    def rules(self) -> MarketRules: ...           # tolerance, volume floor, gap policy, windows,
                                                  # max false breaks, stop_on — YOUR numbers
    async def load_plan(self, run_id): ...        # the run record with result.plan (levels+triggers as data)
    async def load_baseline_bars(self, run_id, tf): ...
    def entry_windows_enforced(self) -> bool: ... # schedule rule (pre/after-market entry suppression
                                                  # is runner-core — you cannot opt into it)
    async def analyze_fire(...) -> FireJudgement  # deterministic read of a fire; no I/O
    def reviewer_available(self) -> bool          # optional model reviewer
    async def review_fire(...) -> (verdict, confidence, critic)
                                                  # you own prompt + verdict; the RUNNER owns timeout,
                                                  # fail-open budget, veto cooldown, kill cap, re-arming
    async def record_fire(...); emit_proposal(...); after_fire(...)
    async def pick_contract(...)                  # expression policy (which option, which DTE window)
    def size_multiplier(contract) -> (mult, why)  # policy multipliers on risk-based size
    def preopen_due(now) / preopen_check(ap, premarket) -> {rows, reference, gapPct, replan}
    async def build_replacement_plan(ap, *, reference_price)
```

**Hooks judge; the runner journals.** No hook may call `journal.append` — the runner journals hook
results so the event shapes stay uniform (they are contracts, §5). Two context flags always flow
into your reviewer: `gap_unchecked` and the mid-day experiment marker.

## 3. Settings

Resolution for every runtime key: `techniques.<your_id>.<key>` → `execution.<key>` (platform
default). Read them via `self.rt("premium_stop_pct", 50.0)` — never `settings.get` with a raw
prefix. Your method's own knobs (thresholds, DTE windows, regime gates, scan schedule, per-source
budgets) live under `technique.<your_id>.*`-style keys you add to `settings_service.DEFAULTS` so
they're UI-editable and journaled. The old `technique.arm.*` names are deprecated aliases; do not
introduce new ones. `technique.arm.midday_trading` is EM-only forever (settled 2026-08-27).

## 4. Risk — what you cannot do

`RiskGate` is the one gate and parts of it are deliberately not settings:
- **Share shorting: never.** Shorts are long puts. Hard reject, `risk.allow_short` is ignored.
- **0DTE: EM's gated path only.** Any other `technique_id` is hard-rejected at the gate.
- **Naked short options: blocked** at the gate today. The income family (verified 2026-08-27:
  Webull CA accepts SELL_TO_OPEN and native 2-leg spreads at impact level) requires a
  structure-aware gate change — an engine work item, not a technique toggle.
- Set `technique_id` (the runner does) and `tags` on every intent: `risk.max_day_notional_per_technique`
  and `risk.max_day_notional_per_tag` cap what one technique or one tip source can take per day
  (v1 is day-notional; position-attributed open exposure arrives with the durable manager).
- Exits are reduce-only and can never be blocked. Anything held overnight follows plan §2.4
  (venue-side GTC stop where the venue truly supports it; otherwise app-managed **with explicit
  acknowledgement** and the loud Armed-page flag — Webull CA accepts GTC on option orders, a
  venue-side option STOP is unproven; Alpaca options are day-TIF).

## 5. Journal and event contracts

Every `Technique*` journal kind has a versioned schema in
`zargar/research/events_contract.py`; the contract test fails the build if a journaled kind is
unregistered, and runtime validation warns on shape drift. If you need a new event kind: add it to
`events.py`, register the contract, note it in `PLATFORM-RULES.md` §4. Consumers must ignore
unknown fields; you must never remove/rename a required field without a version bump.

## 6. Testing bar (what "done" means)

- **Parity**: your tracker path must produce identical results live and in replay (see
  `tests/test_technique_walkforward.py` for the pattern EM uses; the sim rig in
  `tests/test_technique_arming.py` drives the real runner on the sim broker).
- **Include-invalid audit**: every gate you add must be replayable with the gate off
  (`replay_plan(include_invalid=True)`, sweep `--include-invalid`) so the gate's value is
  measurable. Replay rows carry plan-side `valid` — do not restamp it.
- **No live money overnight** until the chaos suite (plan §2.5 + §A9) passes for your hold style.
- Run `tests/test_platform_phase0.py` / `_phase3.py` untouched — they are the platform's guarantees.

## 7. Keep your own judgement log

`docs/techniques/<your-id>/TRADING-RULES.md` — findings, open questions with decision thresholds,
and a change log for every method change, dated with the run/scorecard that motivated it.
Engine-level lessons go to `PLATFORM-RULES.md` instead. Read both before your first live session.
