# Tip technique — design + as-built record

*Planned and built 2026-08-27/28 (research: `docs/TECHNIQUE-CANDIDATES.md` §3; task-level
status lives in `BUILD-PLAN.md` — this file is the design record and the decision log).
Runs on the technique platform (`docs/TECHNIQUE-PLATFORM-PLAN.md`); read
`docs/BUILDING-A-TECHNIQUE.md` before touching the runner side.*

## Status (as of 2026-08-28)

**Built and on main:** extraction v2 (option-aware flat schema, Discord-shorthand
grounding, screenshot→transcript intake, **source auto-detection** from the content
itself), dedupe with seen-again, verification parking, per-source policies
(`signals/sources.py`), dual shadow books (`Portfolio.book`: immediate vs armed, never
blended), the tip plan builder (`techniques/tip/plan.py`), `TipRunner`
(`techniques/tip/runner.py`: level-touch arming, expiry-bounded waiting via `horizon.py`,
the `tip_shadow_arm` morning loop, the Phase 2b handoff to `PositionManager`), **options
expression in both books** under the per-tip vehicle rule (`express.py`), R-based outcome
scoring with per-source expectancy on the scorecard, and the redesigned Tips page
(tabs, hero composer, auto-detect source). Every extract & verify surfaces a
**click-to-copy id** (extraction = content id, tip = signal id — same `CopyChip` as EM
runs) and `GET /api/content/{id}` dumps the full record behind it, so a run can be
quoted by number when fine-tuning the process. Tests: `test_signals_tip.py`,
`test_tip_express.py`, `test_tip_runner.py`.

**Not yet built:** the per-source policy editor UI, Telegram intake, HMAC webhook auth,
the repeat-mention conviction decision, the official `mobile-audit` pass (needs the next
prod restart), and the real-money gates (below).

## 0. What it is

A tip — from a Discord room (screenshot or paste), a newsletter email, or the user's own
head — says "this symbol is going up/down, roughly this hard, roughly this soon." The
technique turns that into a monitored plan with a budget, expresses it as the tip's own
option (or shares when no option is named), manages it out with a profit ladder +
trailing + time stop, and — before any source touches real money — builds that source a
shadow track record it must earn its way out of.

Hard boundaries (from the research, non-negotiable):
- Tips arrive via a **human or a service's own bot/API**. No Discord scraping, no
  autonomous execution of room alerts. Screenshot-of-your-own-client → vision is fine.
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

**On fill** the trade hands off to the durable `PositionManager`: fixed stop, ladder
50/50 on the first two targets, structure trail after +1R, time stop at the thesis
expiry, earnings flatten (unless the catalyst IS earnings), `premium_stop` + `dte_close`
for options (app-managed overnight with the acknowledgement), venue GTC stop for shares.
The session runner forgets the trade — end-of-day flatten never touches it.

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
- Open: email webhook auth (HMAC upgrade, T5); repeat-mention conviction — auto-bump vs
  display-only (default display-only until decided); Telegram as an *intake* (today it
  is outbound + approvals only); the per-source policy editor UI (T4's last piece);
  a tip-specific critic on the fire path (deferred — the source policy is the judge
  in v1, revisit with scorecard evidence).
