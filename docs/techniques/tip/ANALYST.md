# The Tips Analyst — charter and build plan

*2026-08-28. Decision (user): the Tips analyst is a COMPLETELY INDEPENDENT
trader. It does not follow the EnhancedMarket book — EM's rulebook, gap rules,
session windows and R-arithmetic apply to the EM technique only. The analyst
trades the tip technique with its OWN set of rules, which it maintains and
improves itself over time.*

## 1. What "the book" means here (a disambiguation that caused real confusion)

When the analyst's tools and prompts say "our book" they mean **the desk's own
open positions** (the trading sense of "book": what we hold across live /
practice / sim portfolios, plus the managed multi-day positions) — served by
the `get_positions` tool. It has nothing to do with the EM technique's method
book (`docs/techniques/enhanced-market/METHOD.md`), which the analyst never
sees and must never be given. The two shadow "books" per source (immediate /
armed) are a third meaning: counterfactual scorecard portfolios.

## 2. The charter

The analyst is a stock-and-options trader persona with real market tools and
a persistent, self-maintained memory. Its job, per tip and over time:

1. **Appraise** — free-form analysis with tools (quote, bars, chains, flow,
   source track record, earnings, our positions, open tips) plus the desk's
   shared notes and its own rules. No fixed checklist: it decides what to look
   at.
2. **Express** — suggest the trade (mostly options): the contract, a limit
   premium, size within the source's budget — or watch/skip. Its "take"
   becomes the proposal the human approves; on an `auto`-mode source the
   proposal self-approves (same RiskGate path).
3. **Manage** — every filled tip position is handed to the durable position
   manager with an **exit plan the analyst itself wrote**: scale-out targets
   on the underlying with fractions ("sell in bits and pieces"), a stop (or a
   declared premium-stop guard), a premium bleed stop, and a hold cap. The
   shared policy engine executes it on closed bars (ladder / trailing /
   premium stop / DTE / time — `execution/policies.py`), so exits are
   deterministic, journaled and backtestable even though the PLAN was authored
   by an LLM. Management covers the desk's WAITING commitments too (ARM-GAPS
   D2/D3): `get_open_tips` shows each tip's live armed plan (run id, waiting
   levels, day N of M) and pending proposal, and the **`disarm_plan` tool**
   kills a waiting plan when the source exited before our level filled (a plan
   holding a position refuses — `close_position` is that path). Shadow-book
   positions are quarantined from all manage tools (D9).
4. **Learn** — when a tip position closes, a **retro run** reviews what
   happened (fills, trims, exit reasons, P&L) against the entry-time opinion
   and writes lessons to the shared knowledge base — and updates its OWN
   TRADING RULES when the evidence warrants. The nightly sweep
   (`nightly_tip_review`, 17:10 ET) also runs **unfilled-tip batch retros**
   (one per source over recently expired never-filled tips — "were these
   levels ever realistic?", ARM-GAPS D8) and the deterministic **lane
   grader** (`grade_lanes`, D7): once a tip resolves, the analyst's
   now-vs-at_level choice is scored against the shadow books' own orders and
   a LANE GRADE note lands in the knowledge the next runs read.

## 3. The safety floor (platform-enforced, not the analyst's to change)

These are not "rules" the analyst maintains — they are the cage the platform
enforces regardless of what any LLM outputs:

- Every order goes through `RiskGate.evaluate()`; the kill switch is honored.
- Never 0DTE, never naked option writing, never shorting shares (bearish =
  long puts). Enforced in `create_from_signal` and the express layer.
- Size within the source's per-tip budget (`techniques.tip.budget_per_tip`).
- Auto mode self-approves only on an analyst "take" (or analyst off); a LIVE
  portfolio additionally needs `techniques.tip.allow_live_auto` (default off).
- Exits are reduce-only; the policy document is validated
  (`validate_policy`) before a position is adopted — an invalid analyst exit
  plan falls back to the technique's default policy, journaled.

Everything above the floor is the analyst's own judgement.

## 4. The rules system (self-improving)

- Rules live in the shared knowledge base (`tip_notes`) under scope **`rule`**
  — durable, journaled (`TipNoteAdded`), user-editable in Tips > Analyst >
  Knowledge, and versionable by reading the journal.
- **Every analyst run is handed all current rules** as a "YOUR TRADING RULES"
  section, separate from ticker/source notes. The prompt tells it these are
  its own rules, written by earlier runs and retros, and to follow them.
- The analyst updates rules via `save_note(scope="rule", ...)` — typically
  from a **retro**, when a closed position teaches something ("stop sizing
  hedge tips at full budget", "don't chase premium above the alert's stated
  price by more than ~7%"). A rule should state the WHY and cite the position
  or run that taught it.
- When no rules exist yet, the prompt seeds a small starter set (in the
  prompt only — the DB starts empty so the first retro writes the first real
  rule). The starter set:
  1. Prefer the tip's own contract when it is liquid; say why when deviating.
  2. Judge liquidity before price: spread ≤ ~10% of mid, OI ≥ ~100 unless the
     tip names the exact contract.
  3. Scale out — never plan a single all-or-nothing exit for a multi-contract
     position; first trim near a level that pays the risk.
  4. Respect the stated framing: a hedge is sized and exited like insurance,
     not like a conviction trade.
  5. Time is a position: if the move hasn't started by ~half the runway,
     re-evaluate instead of hoping.

## 5. Lifecycle wiring (what runs where)

```
Discord/manual tip → extraction → verification
        → analyze_tip (kind=appraise; tools + notes + rules → opinion + EXIT PLAN)
        → proposal (the opinion's contract/limit/qty; context.exitPlan)
        → approve (human, or auto on "take")
        → order fills → lifecycle.adopt_when_filled
        → PositionManager (policy from the analyst's exit plan:
             ladder targets/fractions · stop or premium-stop guard ·
             premium_stop_pct · time_stop_sessions · dte_close · earnings flatten)
        → trims/exits on closed bars, journaled under the position
        → position closes → tip_retro (kind=retro; lessons → notes, rules)
```

The armed path (level-touch plans via `TipRunner`) keeps its own handoff
(`runner._handoff`) and default policy; the analyst's exit plan governs the
**proposal** path. Unifying the two is a later phase.

## 6. Build phases

- [x] **A1 — persona + rules store** (2026-08-28): prompt rewritten as the
  independent-trader charter; rules scope (`rule`) injected into every run;
  `save_note` accepts scope `rule`; starter rules in-prompt when none saved.
- [x] **A2 — analyst-authored exit plans** (2026-08-28): `AnalystOpinion` +=
  `exit_targets`, `exit_fractions`, `underlying_stop`, `premium_stop_pct`,
  `max_hold_sessions`, `exit_rationale`; proposals carry `context.exitPlan`
  (analyst plan, falling back to the tip's own stop/targets and settings).
- [x] **A3 — adopt-on-fill** (2026-08-28): `techniques/tip/lifecycle.py` —
  an approved tip proposal's fill becomes a managed position with the
  analyst's policy (`policy_from_exit_plan`; invalid plans fall back to the
  default tip policy, journaled). Managed `runId` = the analyst run, so the
  position links back to the reasoning that opened it.
- [x] **A4 — retro loop** (2026-08-28): scheduler job `tip_retro` (17:10 ET)
  finds closed tip positions without a retro, runs a `kind=retro` analyst run
  (position log + entry opinion + rules in; lessons out via save_note; rule
  updates via scope `rule`), tags the position `retro-done`. Off-switch
  `techniques.tip.retro_enabled`.
- [x] **A5 — follow-up-driven management** (2026-08-28): appraise and review
  runs hold `update_exit_plan` (exit-only rewrite of an open tip position's
  campaign; stops may only tighten — `set_policy` enforces it) and
  `close_position` (reduce-only, fraction). The review run acts on source
  follow-ups ("sold 40%") against what the desk holds; entries never come from
  these tools. Knob: `techniques.tip.analyst_manage_enabled`. Journaled
  `TipExitPlanUpdated`; every action is in the run's play-by-play.
- [x] **A5b — the source's history** (2026-08-28, user): `discord_messages`
  mirror — every message the gateway sees in a watched channel (full text,
  image URLs, author, time), plus per-source **onboarding** (watch entry
  `onboardDays`, <= 17: paginated REST backfill driven by
  `/api/tip/discord/mirror-stats`, never re-downloading). Every appraise and
  review run is handed the source's last ~3 days automatically (the tip's
  backstory) and can `search_messages` deeper. UI: the **Mirror** panel on
  Tips > Sources (Discord-style, search + load older).
- [x] **A6 — armed-path unification** (2026-08-29, ARM-PLAN P2): real-money
  armed fills run the analyst's exit plan via `lifecycle.policy_from_exit_plan`;
  shadow books keep the standard 50/50 ladder for scorecard comparability.
- [x] **A7-partial — analyst-chosen arming, scale-ins, conditions, spreads**
  (2026-08-29, ARM-PLAN P1/P3/P4/P5): the analyst chooses now-vs-at-level,
  authors entry ladders and guard conditions, and expresses defined-risk
  spreads. See `ARM-PLAN.md`.
- [x] **A8 — rule quality loop** (2026-08-29, NEXT-GAPS A8): the weekly
  `rule_audit` run (`techniques/tip/rule_audit.py`, rides the nightly review on
  `techniques.tip.rule_audit_day`, default Sat) reads ALL live rules + recent
  retros + lane grades and consolidates: merges → one refined rule (old ones
  SUPERSEDED, never deleted — `tip_notes.superseded_by`), evidence-free/stale
  rules expired, contradictions FLAGGED for the human (`needs_human` → the
  "needs your call" badge + ✓ resolve on Tips > Analyst > Knowledge; the audit
  never resolves a disagreement itself). The LLM only judges; the apply step is
  deterministic. Journal `TipRuleAudited`.

## 7. Knobs

| key | default | meaning |
|---|---|---|
| `techniques.tip.analyst_enabled` | true | the appraise run |
| `techniques.tip.analyst_model` | "" (extraction model) | model for all analyst runs |
| `techniques.tip.analyst_max_tools` | 8 | tool budget per run |
| `techniques.tip.analyst_notes_max` | 12 | notes handed to a run (rules are always all) |
| `techniques.tip.review_enabled` | true | non-tradable-update reviews |
| `techniques.tip.retro_enabled` | true | the retro loop |
| `techniques.tip.retro_at` | "17:10" | ET time of the nightly self-review (retros + unfilled batches + lane grading) |
| `techniques.tip.allow_live_auto` | false | auto mode may self-approve into LIVE |
| `techniques.tip.max_chase_pct` | 10.0 | never-chase: an armed fire pays at most the stated premium × (1 + this %) |
| `techniques.tip.seen_again_reappraise` | true | a re-posted tip with a live waiting plan gets a fresh appraisal |
| `techniques.tip.seen_again_extends` | false | a re-post pushes the waiting plan's horizon window forward |

All the analyst/tip knobs are editable in **Settings → Tips technique**
(ARM-GAPS E2); per-source policy (mode, entry doctrine, budget, horizon,
conviction floor) is edited on **Tips → Sources → Per-source policy** (E6).

## 8. Known gaps (found in the 2026-08-28 review pass)

- ~~Adopt-on-fill does not survive a restart~~ **FIXED 2026-08-29**
  (`lifecycle.resume_pending_adoptions`, called from `attach_tip_runner`).
- ~~A6 (armed-path unification)~~ **CLOSED 2026-08-29** (ARM-PLAN P2): real
  armed fills run the analyst's exit plan; shadow books keep the standard
  ladder for scorecard comparability.
- ~~Mirror stores CDN image URLs, not bytes~~ **FIXED 2026-08-29**: images are
  downloaded at mirror time (while the links are still signed) into
  `backend/discord_media/` (gitignored), recorded on the row
  (`local_images`), served by `GET /api/tip/discord/media/{messageId}/{i}`
  (the viewer shows real thumbnails), and the analyst has a **view_image**
  tool that returns the picture as an actual image block — chart-only alerts
  can be LOOKED at during appraisals, reviews and retros. Source-history
  lines carry `[images: <messageId> — view_image to look]` markers.
- ~~Risk-config clash~~ **RESOLVED 2026-08-29**: the practice runtime now runs
  the AMBITIOUS active-dev posture (`docs/NEXT-GAPS-PLAN.md` §0: premium 50% /
  $10k, notional $25k, budget_per_tip $2,500, max_open_tips 10 …), and the arm
  preflight (ARM-GAPS E3) warns on EVERY arm path — journaled, persisted on
  the plan (`riskWarning`) and rendered on the Armed card. Stock DEFAULTS stay
  conservative deliberately; the pre-live tightening is gap R3 in
  NEXT-GAPS-PLAN.
- ~~Rule consolidation (A8)~~ **BUILT 2026-08-29** — the weekly rule audit
  (see §6 A8). The charter has no open items.

## 9. Knowledge lifecycle + historical mode (KNOWLEDGE plan, 2026-08-30)

The analyst's memory now has a LIFECYCLE (docs/techniques/tip/KNOWLEDGE-PLAN.md;
built per KNOWLEDGE-BUILD-PLAN.md):

- **Per-scope TTLs** (FinMem-style layering): `daily:*` digest notes expire in
  14 days, `ticker:*`/`source:*` in 90; `rule`/`general` never expire
  mechanically — the weekly audit gates them. Expiry is **query-time** (an
  expired note simply stops being injected; kept as history). Being cited in a
  completed LIVE appraisal refreshes a note's TTL (`cited_count`,
  `last_cited_at`); the user can 📌 pin a note (clears expiry). Knobs:
  `techniques.tip.note_ttl_daily_days` / `note_ttl_scoped_days`.
- **Widened weekly audit**: `run_knowledge_audit` applies the same judge→apply
  pass (merge / expire / flag contradictions needs-your-call) to every
  `ticker:`/`source:`/`general` group with ≥3 active notes. `experiment:*` and
  `signal:*` scopes are never audited; `daily:*` just expire.
- **Context channels + digests**: watch entries with `mode: "context"`
  (trading-floor) are mirrored but NEVER auto-intake; `digest.py` distills one
  channel-day into a `daily:<date>` note + ≤5 durable nuggets promoted to
  `ticker:`/`source:` scopes with provenance (digest-now button; nightly pass
  gated by `techniques.tip.digest_enabled`).
- **Historical mode**: an experiment batch (`tools/tip_experiment.py`) replays
  old mirrored messages through the real pipeline. The appraisal prompt leads
  with the HISTORICAL block (live tools show TODAY's market; appraise as of tip
  time), and — after batch b1 proved prompt-only discipline leaks (F12) —
  **every `save_note` from an experiment run is hard-quarantined** under
  `experiment:<batch>` with the wanted scope recorded; promotion into live
  scopes (rules included) is always a human/review act. Experiment runs never
  refresh note TTLs, never touch books/orders/proposals/dedupe/scorecards
  (PLATFORM-RULES invariants 12–13), and get graded by a rubric batch-review
  run.
