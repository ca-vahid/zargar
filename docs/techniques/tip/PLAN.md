# Tip technique — design + as-built record

*Planned and built 2026-08-27/28 (research: `docs/TECHNIQUE-CANDIDATES.md` §3; task-level
status lives in `BUILD-PLAN.md` — this file is the design record and the decision log).
Runs on the technique platform (`docs/TECHNIQUE-PLATFORM-PLAN.md`); read
`docs/BUILDING-A-TECHNIQUE.md` before touching the runner side.*

## Doc map

- **`PLAN.md`** (this file) — design record + decision log for the intake→books core.
- **`BUILD-PLAN.md`** — Phase B (options expression) task list, as-built.
- **`INTAKE-PLAN.md`** — Discord auto-intake: the ToS boundary, the gateway, the
  source allowlist, the message MIRROR + onboarding, analyst run history + live view.
- **`ANALYST.md`** — the Tips Analyst CHARTER: it is an independent options trader with
  its own self-maintained rulebook, exit campaigns, memory (shared notes) and retros.
  EM's method book never applies to it. Read this before touching the analyst.
- **`ARM-PLAN.md`** — the tip→arm enrichment (5 phases, all built 2026-08-29):
  analyst-chosen now-vs-at-level, one exit authority, scale-ins, conditional/timed
  entries, defined-risk spreads. Its §0 is the current wiring map + findings log.
- **`ARM-GAPS-PLAN.md`** — the gap-closure clusters A–F (built 2026-08-29): MULTI-DAY
  STAY-ARMED plans (roll at each close until the horizon), partial-fill adoption,
  verified spread rollback, never-chase, action-aware follow-ups (a "close" expires
  pending proposals + flags waiting plans; the analyst can `disarm_plan`), re-arm
  replaces, lane grading + unfilled retros, tip-scoped knobs + the Settings/Sources
  editors, and the UI wiring (day-N badges, armed chips, honest window copy).
- **`TRADING-RULES.md`** — the METHOD judgement log (findings, decisions, change log).

## Status (as of 2026-08-29)

**Built and on main:** extraction v2 (option-aware flat schema, Discord-shorthand
grounding, screenshot→transcript intake, **source auto-detection**; + entry zones,
scale-in ladders, conditional entries and 2-leg spread grammar — ARM-PLAN P3–P5),
dedupe with seen-again, verification parking, per-source policies (`signals/sources.py`),
dual shadow books (`Portfolio.book`: immediate vs armed, never blended), the tip plan
builder (`techniques/tip/plan.py`: level-touch, breakout, multi-trigger scale-ins,
guarded/timed entries), `TipRunner` (`techniques/tip/runner.py`: level-touch arming,
analyst-driven arming, expiry-bounded waiting via `horizon.py`, the `tip_shadow_arm`
morning loop, the `tip_retro` nightly loop, the handoff to `PositionManager`), **options
expression in both books** under the per-tip vehicle rule (`express.py`, `pick_spread`),
R-based outcome scoring with per-source expectancy, and the Tips page (Tips · New tip ·
Analyst · Inbox + a set-apart ⚙ Sources config tab).

**The Tips Analyst (charter: `ANALYST.md`)** is an independent trader: per tip it
appraises with market tools (quote/bars/chains/flow/scorecard/earnings/our-positions/
open-tips/**view_image**/**search_messages**), reads its own rulebook + the source's
shared notes + the source's last ~3 days of mirrored messages, then chooses take/watch/
skip AND how to express and exit it. A `take` chooses `now` (a proposal trading the tip's
own vehicle) or `at_level` (an armed plan waiting for its price); the exit CAMPAIGN it
authors (scale-out ladder, stop or premium-stop guard, hold cap) is what real-money
positions run. It can steer OPEN tip positions (`update_exit_plan`/`close_position`,
exit-only) and open defined-risk spreads. Every run persists a **TipAnalystRun** (kinds
appraise/intake/retro, streamed live on `tip_analyst`, parent↔child linked) reviewable at
Tips > Analyst. Closed positions get a nightly **retro** that grades the trade and
updates the rulebook. Knobs: `techniques.tip.analyst_*`, `retro_*`, `allow_live_auto`,
`analyst_manage_enabled`.

**Discord auto-intake (`INTAKE-PLAN.md`):** the gateway allowlist + the message MIRROR
(`discord_messages`, image bytes downloaded locally, onboarding backfill up to 17 days),
searchable by the analyst and browsable in the Mirror panel.

Every extract & verify and every analyst run surfaces a **click-to-copy id** and a
`GET /api/content/{id}` / `GET /api/tip/analyst/runs/{id}` record behind it. Tests:
`test_signals_tip.py`, `test_tip_express.py`, `test_tip_runner.py`,
`test_api_and_pipeline.py`, `test_discord_gateway.py`.

**Not yet built** — planned with checkboxes in **`docs/NEXT-GAPS-PLAN.md`**: the A8
rule quality loop, the native multi-leg executor, flow calibration, the real-money
gate path, the real-device mobile pass, HMAC webhook auth. Telegram intake is
DEPRIORITIZED (user, 2026-08-29) — don't build it unasked. *(The per-source policy
editor and the repeat-mention decision shipped with ARM-GAPS E6/D6; the practice
runtime runs the ambitious active-dev limits, NEXT-GAPS-PLAN §0.)*

## 0. What it is

A tip — from a Discord room (screenshot or paste), a newsletter email, or the user's own
head — says "this symbol is going up/down, roughly this hard, roughly this soon." The
technique turns that into a monitored plan with a budget, expresses it as the tip's own
option (or shares when no option is named), manages it out with a profit ladder +
trailing + time stop, and — before any source touches real money — builds that source a
shadow track record it must earn its way out of.

Hard boundaries (from the research; refined 2026-08-28 — full table in `INTAKE-PLAN.md`):
- Tips arrive via a **human, a service's own bot/API, or the OS notifications Discord
  already delivered to the user** (`tools/discord_watch.py`). Never user-token
  automation/self-bots (ToS), never autonomous execution of room alerts.
  Screenshot-of-your-own-client → vision is fine.
- **Shadow-first per source**: real money only for sources whose scorecard clears the bar.
- Sizing is budget- and risk-capped per tip AND per source; the never-list (0DTE, naked
  calls, share shorts) is RiskGate's job.

## 1. Identity

- id `tip`, label "Tips"; runs/outcomes/armed rows carry `technique="tip"` and
  `tags=["source:<name>"]`; settings under `techniques.tip.*` (resolver falls through to
  `execution.*` for runner keys).
- Docs: this file + `BUILD-PLAN.md` (tasks) + `docs/techniques/tip/TRADING-RULES.md`
  (create with the first live decision; every method change logged there).

## 2. The pipeline (as built)

**Intake** (`signals/`): paste / screenshot (transcribed, grounded against the
transcript) / email webhook. `source_name="auto"` → the extractor's `source_hint`
(channel name, poster's handle, masthead) is matched punctuation/case-insensitively
against the registry + every source ever seen; an explicit name is never overridden.
Duplicates (same source + ticker + direction + strike + expiry inside
`dedupe_window_hours`) bump `seen_count` on the original instead of re-trading.

**Verification**: the deterministic checks split three ways — fatal (ungrounded,
unknown ticker, halted, penny, spread, incoherent prices), **parking** (price moved
away from the stated entry / already past target — the tip waits for its level), and
**shadow-gating** (`actionable`: an implied directional lean with no explicit call
trades in both shadow books, status `shadow`, but never becomes a proposal —
2026-08-28, the PeloSwing CRM case). **Freshness** is checked first: the extractor
reads the content's own visible post date into `stated_at`; older than
`techniques.tip.max_tip_age_hours` (72) → status `replayed` — the tip is run through
`techniques/tip/replay.py` (real plan builder + walk-forward on 1h history, both
books' counterfactuals on `extraction.replay`) and never traded. Advisory context
rides along: the Flow read (`flowContext`) and earnings-in-horizon
(`calendarContext`). Both are information, never checks.

**Two books per tip** (the vehicle rule: an option-shaped tip — instrument call/put or a
stated strike/expiry/DTE hint — is an OPTION in both books; else shares in both):
- *Immediate book*: buys at verification. Options are budget-sized contracts with no
  bracket (buy-and-hold counterfactual; expiry settlement closes them); shares are
  sized by the SAME `budget_per_tip` (2026-08-28 — was 5% of equity, which made the
  vehicles incomparable) and keep the tip's bracket; a bracket-less share buy books a
  `closeAfter` time exit that the morning sweep enforces (before this they were held
  forever). A failed pick falls back to shares (longs) or is recorded "not
  expressed" (shorts) — never silently skipped (`extraction.shadowExpression`).
- *Armed book*: the `tip_shadow_arm` morning loop (scheduler, 09:12 ET) arms every open
  level-touch tip with today's plan — entry at the tip's level (or nearest structural
  level), tracker with TIP rules (no volume requirement, no gap-magnitude void, all RTH
  windows), budget-clamped sizing (`ArmConfig.premium_budget`). Waiting is bounded by
  `expiry − entry_cutoff_dte`; past it the signal expires (`SignalExpiredUnfilled`) —
  itself a scorecard datum.

**On fill** the trade hands off to the durable `PositionManager` (`runner._handoff`).
The exit policy has ONE authority (ARM-PLAN P2): a REAL-money armed fill runs the
**analyst's** exit campaign when the appraisal wrote one (`lifecycle.policy_from_exit_plan`
— its ladder, stop-or-premium-guard, hold cap); the **shadow** books and any
plan without an analyst campaign run the standard default (fixed stop, 50/50 on the first
two targets — `lifecycle.DEFAULT_TIP_FRACTIONS`), so the per-source scorecard stays
comparable across sources. Both add the structure trail after +1R, the thesis-expiry time
stop, the earnings flatten (unless the catalyst IS earnings), `premium_stop` + `dte_close`
for options (app-managed overnight with the acknowledgement) and the venue GTC stop for
shares. The exit author is tagged on the position (`exit:analyst:<run8>` / `exit:default`).
The session runner forgets the trade — end-of-day flatten never touches it. A scale-in
plan's later rungs JOIN the same position (`PositionManager.append_leg`), one campaign over
the combined size. Approved buy-now proposals adopt the same way (`lifecycle.adopt_when_filled`,
restart-safe via `resume_pending_adoptions`); defined-risk spreads open leg-sequenced
(`lifecycle.open_spread`).

**Scoring**: tip runs snapshot their own rules into `config.thresholds` so the outcome
scorer replays them faithfully; per-source armed-book stats (scored / fired /
never-triggered / win rate / avg R / expectancy where an unfilled tip = 0R) feed the
scorecard; `barCleared` judges expectancy-in-R once `scorecard_min_n` outcomes exist
(`barBasis` says which rule applied), $-P&L before that. `tipTimeEarned` compares the two
books in $ (the immediate book has no runs to measure in R — a decision, not a gap).

## 3. Real-money gates (unchanged)

A tip source trades real money only after ALL of: 20+ scored tips with positive
armed-book expectancy; the engine team's Alpaca-paper chaos gate + practice soak;
`trading.mode=live` + `allow_live_auto` + the per-arm `allowLive` acknowledgement; and
the per-source/per-tag RiskGate caps stay on. Shadow books auto-acknowledge app-managed
overnight options; real money never does.

## 4. Decisions taken / still open

- ✅ Entry: per-source policy, default level_touch, tip_time earned (user, 2026-08-27).
- ✅ **Dual shadow books** (user, 2026-08-27): immediate vs armed per source, never
  blended; `barCleared` judges the ARMED book; `tipTimeEarned` = immediate demonstrably
  beats armed (their tips run away).
- ✅ **Options tips die at expiry** (user, 2026-08-27): wait window capped at
  `expiry − entry_cutoff_dte` (default 2d); the hold cap follows the thesis expiry too.
- ✅ **Phase 2b handoff** (2026-08-27): fills become durable managed positions; an entry
  unfilled after 10 minutes stays session-scoped (flatten applies — safe).
- ✅ **Per-tip vehicle rule** (Phase B, 2026-08-27): one rule, both books — see
  `BUILD-PLAN.md` §0. Shorts are puts end-to-end; the short measurement gap is closed.
- ✅ Default source mode is **proposal**, not shadow — a human approval is itself a gate
  and the paste-by-hand user is the common case; "shadow until the bar clears" governs
  AUTO mode specifically.
- ✅ Trust bar: expectancy-in-R once `scorecard_min_n` (20) outcomes are scored; $-P&L
  before that. `tipTimeEarned` stays $-vs-$ (decision, 2026-08-28).
- ✅ Source auto-detection (user, 2026-08-28): `source_hint` from the content itself;
  explicit names always win; unmatched hints become new sources.
- ✅ **Shadow-implied lane** (user, 2026-08-28): a non-actionable but directional tip
  gets status `shadow` — books + scorecard yes, proposal never. Found via the
  PeloSwing CRM replay: the old fatal gate blinded the books to the commonest tip shape.
- ✅ **Freshness + replay lane** (user, 2026-08-28): `stated_at` from the content,
  72h max age, stale tips replayed on history instead of traded.
- ✅ **Generous defaults** (user, 2026-08-28): budget 1000/tip, 5000 open, horizon 15
  sessions, 5 open tips. Logged in `TRADING-RULES.md`.
- ✅ Extraction is **prompted JSON + local validation** (2026-08-28): the schema blew
  the structured-output grammar budget on the first real screenshot ("Schema is too
  complex"); the wire schema lives in the prompt, pydantic validators enforce the vocab.
- ✅ **Breakout tips are breakouts** (2026-08-28, PeloSwing BOIL): a stated level on
  the far side of price mints a breakout/breakdown trigger at the tip's level with the
  tracker's close-through discipline — never a substitute dip-buy.
- Open: email webhook auth (HMAC upgrade, T5); repeat-mention conviction — auto-bump vs
  display-only (default display-only until decided); Telegram as an *intake* (today it
  is outbound + approvals only); the per-source policy editor UI (T4's last piece);
  a tip-specific critic on the fire path (deferred — the source policy is the judge
  in v1, revisit with scorecard evidence).
