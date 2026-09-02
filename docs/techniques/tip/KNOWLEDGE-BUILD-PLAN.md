# Knowledge & historical-experiment BUILD plan

Executes the decided options from `KNOWLEDGE-PLAN.md` (§4: backfill 90d, batch 20,
TTLs 14/90/∞, digest-on-demand first, experiment out-of-band). Phases in build order;
tick each box when done; every phase ends with its tests green
(`ZARGAR_TEST_DATABASE_URL` on :5433, own DB when parallel sessions may run).
Rules of the house apply: RiskGate on every order path (the experiment places NO
orders — enforce it, don't assume it), journal every decision, camelCase wire format,
new knobs in `settings_service.DEFAULTS`.

## Phase 0 — separation guards + experiment tagging (cluster E) — DONE 2026-08-30

- [x] `docs/PLATFORM-RULES.md` invariants 12+13: per-technique knowledge stores;
      out-of-band experiments never touch money or scores.
- [x] Guard test (`tests/test_platform_separation.py`): static source scan both
      directions (EM never touches `tip_notes`; tips never read EM's
      rulebook/vision/analysis/review/setups/chat/… knowledge modules) + the
      charter disclaimer line is asserted present in the analyst prompt.
- [x] Tag convention: `handle_extraction(..., experiment="<batch>")` stamps
      `extraction.experiment`; helper `signals.service.experiment_tag()`.
      *(Stronger than planned: an experiment signal is FORCED onto the replayed
      path even when fresh — no books/proposals/arming possible by construction.)*
- [x] Exclusions: dedupe skipped in BOTH directions (experiment rows invisible to
      `_find_duplicate`, experiment runs never dedupe), source scorecards skip
      tagged rows. Retros/lane-grading/arming need no filter — `replayed` status
      is outside all of them by existing design (verified). Rule-audit exclusion
      of `experiment:*` note scopes lands with B4 (Phase 3).
      Tests: `tests/test_tip_experiment.py` (3) — zero orders/proposals proven.

## Phase 1 — context channels + 90-day backfill (cluster C1 + config) — DONE 2026-08-30

- [x] Watch entry `mode: "tips" | "context"`: gateway mirrors context channels but
      never ingests them (`_on_message` guard); `discord_set_watch` sanitizer keeps
      the field (found: it silently stripped unknown fields + clamped onboardDays).
- [x] Sources UI: "context only" toggle per channel; onboard field max 17 → 90.
- [x] Backfill cap 17 → 90 (gateway `_backfill_watched` + sanitizer clamp).
- [x] Mirror cap default 20k → 50k (`techniques.tip.mirror_max_messages`).
- [x] Operator run (2026-08-30): 9 tip channels `onboardDays: 90`; OWLS
      `💬｜trading-floor` + PeloSwing `trading-floor🪙` added as `context`.
      Result: **5,853 mirrored messages** — muggzone 2125 (back to 05-29), ab 927,
      tt/eva 625, giul/jon-and-kian 525, neal 425 (all ≥ ~90d deep);
      florida-man/common-stock stayed at baseline 25 (low-traffic channels);
      trading-floor mirroring live (26 in first minutes). Ample pool for batch 1.
- [x] Tests: `tests/test_discord_gateway_modes.py` (3) — context never ingests,
      tips unchanged, unwatched ignored.

## Phase 2 — historical experiment harness (cluster A1) — DONE 2026-08-30

- [x] `SignalService.ingest_experiment(msg, batch)`: mirror row → RawContent
      (`source_type=experiment`, meta carries batch + discordMessageId + postedAt) →
      `process_content(experiment=, stated_at=)` — the mirror's posted_at OVERRIDES
      any model-inferred date, so the stale gate + replay run on the true tip time.
      *(v1 is text-only: image-only messages are excluded by the sampler and counted
      — an explicit finding candidate, not a silent drop.)*
- [x] `techniques/tip/experiment.py`: seeded sampler (tips-mode channels only,
      text-bearing, never-processed), sequential `run_batch` with journaled manifest
      (`TipExperimentBatch` started/finished), restart-surviving `batch_status`.
      API: `POST /api/tip/experiment/run`, `GET /api/tip/experiment/{batch}`,
      `POST /api/tip/experiment/{batch}/review`. CLI `tools/tip_experiment.py`
      (run --watch / status / review) drives the RUNNING app.
- [x] Analyst historical mode: `analyze_tip(experiment=, historical_note=)` — the
      prompt leads with the HISTORICAL block (tools show today, appraise as of tip
      time, save_note only timeless lessons, date-bound → scope experiment:<batch>);
      run + opinion tagged. Replayed experiment signals ARE appraised (live replayed
      tips still are not — unchanged).
- [x] Batch review: one `kind=retro` run applying the rubric to every item's full
      record (tip, checks, replay, appraisal, tool calls); summary saved as a note
      under scope `experiment:<batch>` (never injected into live runs).
- [x] Tests (`test_tip_experiment.py`, 4 + gateway 3 + separation 3): forced
      out-of-band (zero orders/proposals asserted), two-way dedupe isolation,
      scorecard exclusion, age wording, seeded sampler determinism + exclusions +
      processed-marking.

## Phase 3 — knowledge lifecycle (cluster B1/B2/B4/B5) — DONE 2026-08-30

- [x] `TipNote.valid_until` + `last_cited_at` + `cited_count` (additive, via
      `db.create_all`).
- [x] TTL on create by scope: `daily:*` 14d · `ticker:*`/`source:*` 90d ·
      `rule`/`general`/`signal:*`/`experiment:*` none. Knobs
      `techniques.tip.note_ttl_daily_days` / `note_ttl_scoped_days`.
- [x] Injection: expired notes filtered at QUERY TIME (deterministic, restart-
      proof, append-only — **no mutation sweep needed**, so the planned journaled
      nightly sweep was dropped deliberately; expiry is visible in the UI chip and
      the history toggle instead). Dates were ALREADY rendered with every injected
      note (`(created, author)` in notes_txt) — B2 verified, not rebuilt.
- [x] Knowledge tab: "expires in Xd" chip (amber ≤ 7d) with the TTL story in its
      tooltip, 📌 pin (clears expiry, journaled TipNoteEdited), history toggle now
      "superseded + expired" (API `superseded=true` returns both).
- [x] B4: `run_knowledge_audit` — the weekly judge→apply pass widened to every
      `ticker:*`/`source:*`/`general` group with ≥3 active notes (merge dupes,
      expire unsupported, flag contradictions needs-your-call); `daily:*` expire on
      TTL; `experiment:*`/`signal:*` never audited. Runs beside the rule audit in
      the nightly job on audit day.
- [x] B5 refresh: notes injected into a COMPLETED live appraisal get
      `cited_count`++/`last_cited_at` and their TTL extended (experiment runs
      deliberately never refresh). Injection order kept simple (newest-first) —
      revisit if volume ever makes ordering matter.
- [x] Tests (`tests/test_tip_knowledge.py`, 5): TTL per scope, query-time expiry +
      history, citation refresh, pin, scoped-audit flagging (+ experiment scopes
      never served to the judge).

## Phase 4 — digests (cluster C3, then C2) — DONE 2026-08-30

- [x] `techniques/tip/digest.py`: run kind `digest` per channel-ET-day — ONE
      `daily:YYYY-MM-DD` note (14d TTL, `[channel]`-prefixed) + ≤5 durable nuggets
      promoted to `ticker:`/`source:` scopes ONLY (a promotion aimed at `rule` is
      refused), provenance = `(from <channel> <date>)` + author `digest:<run8>` +
      run link. Streams via _Recorder like every run.
- [x] "📝 digest now" button on context-channel rows (`POST /api/tip/digest`
      validates + creates the run, finishes in background, UI opens the streaming
      run immediately).
- [x] Knowledge tab: "📅 Today & recent digests" section at the top of All view,
      newest day first.
- [x] Nightly: `digest_all_context_channels` inside the nightly tip review, gated
      by `techniques.tip.digest_enabled` (default OFF until the prompt is tuned via
      digest-now).
- [x] Tests: daily-note scope + TTL, promotion provenance + scope guard, run row
      done (`test_tip_knowledge.py::test_digest_channel_writes_daily_note_and_promotes`);
      gating is a one-line settings read exercised by the nightly suite.

## Phase 5 — run the experiment (cluster D)

- [x] **Batch 1 RUN 2026-08-30**: `run --batch b1 --sample 20 --seed 7 --since
      2026-06-01` → 20 messages → **22 signals, all `replayed`, 0 orders,
      0 proposals** (verified in the live DB during and after the batch).
      19 appraised (all skip — defensible as-of-tip-time), 3 silently dropped
      (F1), replay outcomes on most items (tp1/tp2/stopped/not_filled/horizon).
      Review run **`64f40988`** applied the rubric; findings below. Harness bugs
      found *by running it* and fixed same day: an oversized record set produced
      a done-but-empty review (retry + 10k budget + compact records), and
      digest/review verdict cards rendered "?" in the UI.
- [ ] Fix the top findings (each fix = its own commit; method findings go to the tip
      docs, engine findings to PLATFORM-RULES). → see F1-F12 below.
- [ ] Batch 2: new seed after fixes; compare failure classes against batch 1 —
      recurring classes get escalated, resolved ones ticked.
- [ ] Decide: enable nightly digests (C2)? monthly experiment cadence? Update
      KNOWLEDGE-PLAN accordingly.

### Batch 1 findings (review run 64f40988, 2026-08-30 — grades the PROCESS)

**What worked:** extraction fidelity (strike fan-out, evidence quotes, premium/
expiry survived); the judgment layer — "position commentary is never an entry",
one-message-many-strikes appraised once, positions checked before concluding
nothing to manage. The review's words: *"that is real process."* And the
out-of-band guarantee held live: zero orders, zero proposals, zero book entries.

**Fix list for batch 2** (signal ids in the review run):

- [ ] **F1 · Silent drops (14%)** — 3/22 signals ended with no verdict, no tools,
      no reason (`f603e968` NVDA — the cleanest signal in the batch —, `4ffb7309`,
      `6872a89f`); probably variant-suppression firing without a record. *No
      signal may terminate without a status string.*
- [ ] **F2 · `fresh` fails 22/22 by design** — a constant, not a discriminator;
      every rationale gets a free hard kill. Experiment mode should pin the clock
      to `statedAt` and make freshness an annotation, not a fatal check.
- [ ] **F3 · `ticker_resolves` flaky + conflated** — failed non-deterministically
      on liquid names (GLW/META/NFLX/MU/COIN/INTC) while the replay held full
      OHLC for the same symbols; rationales said "no quote" then priced the
      ticker. Split resolution / entitlement (SPX!) / staleness; soft in
      experiment mode.
- [ ] **F4 · Premium-vs-underlying confusion** — `af8d5a2c` (MU 850P) loaded the
      premium ladder as UNDERLYING targets → fabricated `+99.63%` immediate
      print; same class `2f5fa44e`, `2d22ac22`. Add a `price_basis` notion;
      replay must refuse mixed-basis plans.
- [ ] **F5 · Post-tip leakage** — three rationales cited the source's LATER
      commentary (mirror history/tools reach past tip time). As-of isolation must
      be harness-enforced (time-capped search/history in experiment mode).
- [ ] **F6 · Replay invents plans** — "no structural level — ATR pullback" arms a
      trade the tip never proposed, and its ±R is then read as tip evidence;
      `resolved: false` rows are indistinguishable. Label constructed plans.
- [ ] **F7 · Fan-out inflates counts** — one eva message → up to 11 signals from
      mutually exclusive alternates; no `sourceMessageId` on records; a stale
      scorecard line quoted as fact. Group alternates; stamp the message id.
- [ ] **F8 · Staleness leaked into `is_actionable`** — `25ab69fb` (INTC explicit
      open) marked not-actionable because the expiry had passed *by processing
      time*. Staleness is verification's job, not extraction's.
- [ ] **F9 · Action taxonomy lacks status/hold** — "STILL IN META calls" and a
      P/L brag both became `update_stop`; a half-size disclosure became `open`.
- [ ] **F10 · Inferred fields asserted as fact** — a 0DTE ban invoked on a null
      `dte_hint_days`. Mark inferred values as inferred.
- [ ] **F11 · Live `get_quote` on historical tips** — the prompt warning alone
      does not prevent tool-time confusion; stub or time-pin quotes in
      experiment mode.
- [x] **F12 · Knowledge pollution — FIXED 2026-08-30** (user hit it in the UI:
      "a lot of general items… not sure if they're useful"). Historical runs had
      saved 11 per-item recaps into `general` and 5 rules into `rule` despite
      the prompt — confirming F5's thesis that isolation must be harness-
      enforced. Fix: `save_note` during an experiment run now HARD-QUARANTINES
      every save under `experiment:<batch>` with `[wanted scope: X]` recorded
      (test: `test_experiment_save_note_is_quarantined`); the 16 leaked live
      notes were moved to `experiment:b1` in the runtime DB; ONE rule (the
      consolidated "position commentary is never an entry" — explicitly endorsed
      by the batch review) was deliberately promoted back by the reviewer.
      Knowledge tab hides `experiment:*` behind the history toggle
      ("🧪 Experiment artifacts" section). Promotion is now always a human/
      review act, never a side effect of running history.

### Batch 2 (2026-09-01, POST-SOAK 5.3) — 40 msgs · seed 11 · since 06-01

Run AFTER the F1/F2/F4/F5/F6/F11 harness fixes. **41 signals, all replayed;
isolation perfect (0 proposals, 0 orders, 0 book entries, 0 failed runs,
0 silent drops — F1's guarantee held with nothing to catch).** Review run
`38c4130201`; full report note `experiment:b2` (`1d7d118a…`) + two promoted
source-habit notes (quarantined, per F12's rule).

**Measured against batch 1:** silent drops 14% → **0%** (F1 ✓); the fatal
`fresh` free-kill gone (F2 ✓ — annotation now); no post-tip leakage cited
(F5 ✓); live-quote confusion gone by construction (F11 ✓ — quotes withheld);
`constructed`/`premiumBasis` flags wired but untriggered in this sample
(F4/F6 present, unexercised); fan-out 40→41 signals vs b1's 20→22 (sample-
dependent — the F7 grouping fix is still open).

**New findings (b2):**

- [ ] **F13 · Isolation over-corrected: 41/41 verdicts = skip.** With quotes
      withheld and history capped, the appraiser has almost nothing to judge
      with — skip-everything is rational but grades nothing. The historical
      header needs the tip's OWN evidence attached: pre-tip bars summary + the
      replay block. (Review fixes #1/#2 point the same way: point-in-time
      `get_source_stats`/`get_positions`, and cite only what was retrieved.)
- [ ] **F14 · Replay arms plans that ignore the tip's stated entry condition**
      (review #9): "above 422" armed at 416.49; "under 940" armed at 1000.
      The armed leg snaps to nearest structure instead of honouring
      `entry_conditions` — its −1.25R prints are harness artifacts, not tip
      evidence. Replay must respect the stated trigger side or mark the plan
      `constructed`.
- [x] **F15 · Fan-in at the message level** — DONE 2026-09-01 (daily review:
      eva's map → 11 appraisals → 11 notes). A message with ≥
      `techniques.tip.fan_in_min` (3) signals is appraised ONCE with every
      branch in the header; siblings inherit the verdict (a take never fans
      out — siblings become watch, `fanIn: true`). Verification/dedupe/shadow
      books still run per branch. Test `test_multi_branch_message_is_appraised_once`.
- [x] **Note hygiene (daily review 2026-09-01)** — 100 notes in a day, 18
      numbering "message families". Harness-enforced in `save_note`: ≤2 saves
      per run, blank `ticker:` scope refused, chatter-taxonomy text refused
      (`_TAXONOMY_RE`); prompt says formats live in ONE profile note.
- [ ] **F16 · "Trim/TP without a matching open" flag** (review #11): three
      position-management messages had no captured opening message — an
      ingestion-coverage alarm worth emitting on the live path too.
- [ ] **F17 · Source-profile notes must record FORMATS** (review #12): eva has
      two formats (maps AND clean BTO/STC fills) — the working MuggZone
      tier-note is the template; SPX→SPY venue mapping should be a table, not
      three hand-derivations (review #14).
- [ ] **F18 · An `ok:false` replay must say "no replay evidence"** in the
      record instead of being graded as if informative (review #14).

### Review rubric (per experiment run)

1. Extraction fidelity — did the tip's ticker/direction/prices/expiry survive intact?
2. Verification correctness — right status (parked/shadow/replayed/failed) for the
   tip's actual content and age?
3. Knowledge injection — were the RIGHT notes in context? What note SHOULD have
   existed and didn't?
4. Tool use — sensible calls, no live-data confusion, no wasted loops?
5. Verdict quality — reasonable *as of tip time* given the replay outcome?
6. Gaps — anything the pipeline dropped, mislabeled, or should have flagged.

## Constraints (unchanged)

Never user-token automation beyond reading; never alert-room auto-execution; the
experiment places no orders and touches no books; kill switch / never-list / RiskGate
invariants untouched; Telegram intake stays deprioritized.
