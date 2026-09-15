# Tips desk — state of play, what changed, known gaps

*Start here. Dated; the newest entry wins over any older doc in this folder. Update this
file whenever a rollout, an activation or a review changes what is true. Last full refresh:
2026-09-14 01:45 ET (after the v0.7.67 rollout).*

## Doc map

| File | What it is | Currency |
|---|---|---|
| `README.md` | this file — state, changes, gaps | current |
| `PLAN.md` | design record + decision log for intake → books (2026-08-27/28) | as-built history; its "Status" section is 2026-08-29 |
| `BUILD-PLAN.md` | Phase B (options expression) task list | as-built history |
| `INTAKE-PLAN.md` | Discord auto-intake boundary, gateway, mirror | current (gateway ledger detail in `GATEWAY-PLAN.md`) |
| `ANALYST.md` | the Tips Analyst charter | current |
| `ARM-PLAN.md`, `ARM-GAPS-PLAN.md` | tip → arm enrichment, gap clusters A–F | as-built 2026-08-29; §0 wiring map still accurate |
| `GEOMETRY-RISK-PLAN.md` | pre-entry geometry + risk sizing | ACTIVE 2026-09-14 |
| `KNOWLEDGE-PLAN.md`, `KNOWLEDGE-BUILD-PLAN.md` | shared notes, TTLs, audits, safeguards, maintenance cycle | current through round 3 + the 2026-09-14 consolidation |
| `TRADING-RULES.md` | the METHOD judgement log (findings, change log) | current — every rule change is dated there |
| `reviews/` | external review rounds, responses, deploy records, manifests | dated records; `2026-09-13-pr91-pr93-response.md` holds the v0.7.67 rollout record |

## State of play (2026-09-14)

- **Version:** v0.7.77 (deployed 21:35 ET 2026-09-14: EOD review fixes EOD-01..09, `reviews/2026-09-14-eod-response.md`; on top of the day's rollout PR #95, exit guard PR #98, counter fix PR #100). Practice only: `trading.mode=practice`,
  `techniques.tip.allow_live_auto=false`. The Tips Practice book (`techniques.tip.default_portfolio`)
  is the only book that trades tips; shadow books (immediate / armed) are research.
- **Entry controls, both ACTIVE by journaled settings (2026-09-14 05:15Z):**
  `techniques.tip.geometry_gate=enforce` and `techniques.tip.entry_pause_mode=integrity`.
  Code defaults remain `shadow` / `clock`. Rollback is one journaled PATCH back; it never clears
  an incident row and never touches a position's stop.
- **Geometry (enforce):** stop finalized and size derived from it against `risk_pct` 1% of
  equity (`risk_budget_per_tip` 0 = percent budget) before the order; recomputed at submission;
  evidence missing → review-gated card, never auto. Shares sized at the executable limit; options
  need delta ≤ 900 s old, a fresh non-delayed underlying reference and an explicit contract
  multiplier. Post-fill: tighten immediately, widen only trim-first with a durable attempt
  (`geometry_trim:<id>` on the order), unknown outcomes hold and reconcile at restart.
- **Integrity pause:** a persisted `TipExecutionIncident` pauses every automated tip entry
  (auto-approval, the `approve(via=auto)` head and final submission, the stale-quote retry, every
  armed submission and retry), never exits. Causes: filled outside its risk plan, exit on
  unconfirmed/delayed evidence, duplicate/unreconciled fills, repeated pre-entry failure. Release
  needs evidence bound to the incident (repaired path + fresh observation for invalid evidence) or
  an explicit labeled override. A valid fast loss is a `TipFastStopDiagnostic`; the loss limits
  are independent. The 2026-09-04 clock brake (`TipAutoPaused` after a <5-min stop-out) is retired.
- **Knowledge:** propose-only maintenance (`knowledge_apply_enabled=false`). The reviewed
  batches were applied 2026-09-14: 19 truncation restorations, the adoption-geometry family
  consolidated into one canonical rule, the kill-switch rule replaced by the incident policy,
  14 `evidence:adoption-geometry` records (never injected). Live rulebook: 32 rules.
- **Monitoring:** the desk's Claude session runs a pre-open tick (08:23 ET), 30-minute session
  ticks (:03/:33, 09:03–15:33 ET) and a 16:06 ET wrap-up. These are session-only crons — a
  session restart drops them and they must be re-armed.
- **Meet Kevin own-book workflow (KFIN-08, built, NOT enrolled):** `techniques.tip.mk_ownbook_mode`
  is `off` and `mk_ownbook_sources` is empty, so nothing changed at runtime. When enrolled
  (`observe` first, then `shadow`), MK's "I bought / added / sold half" text is classified
  (`techniques/tip/ownbook.py`) and booked ONLY in a dedicated `book=ownbook` shadow book —
  never the Practice book, a proposal or an armed plan; ungrounded/stale disclosures stay
  `ownbook_unresolved`; recaps, hypotheticals and other people's screenshots are
  `ownbook_context`. Ledger + grading against the `mk_ownbook_min_*` criteria:
  `GET /api/tip/ownbook/MK-alpha-trades` (a report — promotion stays a human verdict).
  PLATFORM-RULES invariant 19; TRADING-RULES 2026-09-14.

## What changed on 2026-09-13/14 (why older docs read differently)

| Older statement | Now |
|---|---|
| "one <5-min stop-out pauses tip autos for the session" (`adoption_killswitch`, `TipAutoPaused`) | retired; `entry_pause_mode=integrity` pauses on incidents, not on a clock |
| "geometry gate default shadow, not active" / "KB-06 is a design" | both ACTIVE in Practice by settings; code defaults unchanged |
| "bulk knowledge cleanup HELD until the consolidation packet's policy decisions" | applied through `tools/tip_consolidation.py` with receipts; routine maintenance still propose-only |
| "the 22 possible truncations" | 19 restored from run traces; 3 experiment-scope rows unproven and untouched |
| "the two kill-switch rules are disputed" | released and superseded by the incident-based rule |
| "PR #91 / #93 open for review" | merged via PR #95 |

## Known gaps, risks and what could be wrong (read before trusting a number)

0. **The MK own-book classifier is text rules + two extraction fields, unexercised on live
   MK posts.** Known blind spots (TRADING-RULES 2026-09-14): "we bought" reads as the author's
   fund; "sold puts" (a premium-selling OPEN) reads as an exit; a third-party screenshot with
   no textual cue depends on the extractor's `actor`; entry aging counts weekdays, not the
   exchange calendar. Run `observe` mode on MK for a week and read the `TipOwnBookClassified`
   journal before switching to `shadow`; nothing about it is a Practice path either way.
1. **No live-market session under enforce/integrity yet.** Everything is proven on the sim
   broker and the reviewer's rigs. Acceptance = the first `TipGeometryRepaired` with
   `phase: pre-entry, enforced: true`, the first review-gated card, and (if one happens) the
   first incident showing every automated path refusing while exits ran. Watch 2026-09-14.
2. **Option evidence comes from CBOE's delayed chain.** Delta per-field age ≤ 900 s is a
   staleness bound, not a liveness guarantee; in a fast tape the unit-loss estimate
   (`delta-linear-v1`) can be wrong in either direction. Premium-at-risk (`stressRisk`) is the
   honest bound. A tip that arrives when the chain snapshot is old will be review-gated, i.e.
   it waits for a person — under unattended Practice that means MISSED, not traded.
3. **Review-gated cards do not auto-decide.** Under unattended practice a card that fails
   evidence sits pending until it expires. Expect fewer automated fills than before; that is
   the design, but the counterfactual (armed shadow book) keeps trading full size, so the
   scorecard comparison will drift. Judge the source trust bar with that in mind.
4. **An incident with no repair evidence stays open.** If the repaired-path record never
   appears (for example the defect was in a feed that simply recovered), the pause persists
   until a labeled human override. The tick reports open incidents; the override is the
   user's call, not the loop's.
5. **The armed-lane geometry wiring has no end-to-end degenerate-fill test** (debt recorded
   2026-09-08); the pure gate and the proposal path are covered, the armed submission asks
   both gates, but forcing a fill past the planned ladder through the arm machinery is
   untested end to end.
6. **Geometry is Practice-only by construction.** A live book gets no risk plan in either
   mode. Before any real-money tip, the scope decision must be made explicitly and
   `docs/PRE-LIVE-PROFILE.md` re-tightened — the practice limits are ambitious on purpose.
7. **The consolidated family rule carries numeric HYPOTHESES** (stop-width floors, TP1 ≥
   max(0.5×ATR, ~1R), 0.5 consumed-risk). They are labeled non-operative; the analyst may
   still quote them. The code gate's own floors (0.75%, 1× ATR) are the enforced ones.
8. **Knowledge maintenance is propose-only** — the weekly cycle records merges/expiries as
   proposals; only contradiction flags land. The rulebook therefore drifts only through
   analyst retros (family dedupe supersedes within a `RULE (<family>` prefix) and reviewed
   batches. Nobody is reading the proposals unless the user opens the Knowledge tab.
9. **Three truncated `experiment:*` notes are unproven** (no trace evidence) and stay
   truncated. KB-08's frozen-evidence comparison for the rulebook audit is not built.
10. **Own-book mirroring for Meet Kevin is OFF**; Telegram intake is deprioritized. Multi-image
    evidence is processed since KFIN-07 (2026-09-14): every supported attachment up to
    `techniques.tip.intake_max_images` (4) / `intake_max_image_bytes` (8 MiB) /
    `intake_vision_calls_per_message` (4) is transcribed and grounded per attachment id; images
    beyond those budgets are explicit `skipped-over-budget` in the coverage manifest, and a
    contradiction between documents fails verification into review instead of picking a side.
11. **Tools that mint a session need `backend/.env`** — `tip_note_restore` and
    `tip_consolidation` must run from `C:/Cursor/zargar/backend`; from a worktree the apply
    step fails after printing the plan (learned 2026-09-14; nothing was written).
12. **Same-symbol legs were a blind spot until 2026-09-14 (v0.7.68).** A scaled-in position
    looped its stop 3,282 times in a shadow book because exit fills were attributed to the
    first leg by symbol. Fixed (fills reduce toward flat; a reduce-only exit never crosses the
    venue's zero), but the two research books that ran away (`ab` short 40,600 APLD, `eva`
    short 5 TSLA) still carry those positions until the user resets them, and their armed-lane
    scorecards are not trustworthy for those names.
13. **Under a 1% budget, option tips are a review product (day 1 evidence, 2026-09-14).**
    Eleven of sixteen enforced cards were gated on "no quantity satisfies the ~$89 budget"
    because a contract with no stop risks its whole debit. Two analyst takes expired
    unapproved. Either the analyst supplies a stop on every take, or `risk_pct` /
    `risk_budget_per_tip` changes — a user decision recorded in TRADING-RULES.
14. **Intake delivery stalled for 4 h 38 m on 2026-09-14 (12:35–17:13 ET)** with the app
    healthy; 26 market-hours messages were first seen after the close. Root cause unproven
    (console-only gateway logging); v0.7.73 adds the status file, idle watchdog, file log,
    `/api/tip/intake/liveness` and the stall journal. The four stale incidents of the day
    were released on bound evidence at 18:22 ET; three retro-promoted rules are quarantined
    pending your review.
15. **Bar delivery stalled three times on 2026-09-14** (~4 min each, bars intact, quotes
    fresh). Exits are quote-based so positions were safe, but an armed ENTRY on a stale
    bar stream is blind; the aggregator's delivery latency is not instrumented yet.
16. **Restarts are the platform's biggest operational risk.** Other desks deploy during the
    session; the app has been dark mid-session before. Every deploy must go through
    `/api/ops/restart-check` and the `ZargarRestart` task, never inside 09:30–10:30 /
    14:45–16:00 ET unless the app is dead.

## Experiments (KFIN-09, built 2026-09-14 - inert by default)

Two evidence tools, both isolated by construction (`tests/test_tip_kfin09_experiments.py`
proves write isolation, denominator correctness, missing-data handling and reproducibility):

- **Frozen knowledge comparison** (`techniques/tip/frozen.py`, CLI `zargar.tools.tip_frozen`).
  `capture --signal <id>` (or `--run <id>`) builds an immutable case bundle from what the DB
  already holds - the message, the tool outputs the run saw (its trace), the rule snapshot
  (ids, revisions, core flags, hash), the notes it was handed, model + settings and the exact
  context manifest (verbatim only when `techniques.tip.frozen_capture_context` was ON at run
  time; otherwise reconstructed and labeled so, source history missing). `replay --bundle
  fb-... --variants current,core_only,no_knowledge` runs the analyst prompt against the bundle
  only: a tool call is served from the bundle or refused ("missing" - never fetched today),
  `save_note` is captured as a proposed note and never written; the only rows added are
  `tip_frozen_bundles` / `tip_frozen_replays`. `report --bundle fb-... --json out.json` prints
  decision changes vs the baseline, grounding (used notes, rules/notes supplied), protections,
  no-verdict rate, latency and tokens per variant - counts only, no "better".
- **Entry-variant cohort** (`techniques/tip/cohort.py`, CLI `zargar.tools.tip_entry_cohort`).
  With `techniques.tip.entry_cohort_enabled` ON, every eligible open/add idea is a
  `tip_entry_cohort` row at its intake decision (and a `redecision` row when the recovery sweep
  re-decides a park): source post / receipt / decision times kept apart, the exact source
  instrument (OCC only when fully stated) and the proposed one, the source-stated premium, the
  decision-time quote with age + provenance (`fresh|stale|missing`), gaps, and the configured
  later sample (`techniques.tip.entry_cohort_delay_minutes`, labeled `delayed`; "unknown at
  alert" stays unknown; a sample far past due is `missed`). `report` simulates the declared
  variants - immediate, delay, `entry_cohort_premium_cap` x stated premium - into separate
  result books (`tip_entry_variant_results`, book `variant:<name>`) under identical budget
  (min of `budget_per_tip` / `max_premium_per_tip`), fees and fill-at-ask assumptions, and
  separates "evidence adequate" from "insufficient" per row and variant. No P&L, no
  equivalence claim; promotion of any variant is a separate reviewed verdict.

## Rollback and where the receipts are

- Settings: `PATCH /api/settings {"techniques.tip.geometry_gate": "shadow",
  "techniques.tip.entry_pause_mode": "clock"}` (journaled; previous values recorded in
  `reviews/2026-09-13-pr91-pr93-response.md`).
- Knowledge: `reviews/2026-09-14-consolidation/manifest.md` (rollback mapping) and
  `reviews/2026-09-14-truncation-restoration/` (per-id revisions); receipts in
  `tip_knowledge_batches`.
