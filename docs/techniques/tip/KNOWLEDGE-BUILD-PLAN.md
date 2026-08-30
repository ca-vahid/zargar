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

## Phase 4 — digests (cluster C3, then C2)

- [ ] Analyst run kind `digest`: input = one context channel's mirrored messages for
      one date; output = ONE note, scope `daily:YYYY-MM-DD` (14d TTL), body =
      tickers discussed + sentiment + recurring themes + anything actionable-adjacent;
      durable nuggets promoted into `ticker:`/`source:` notes with provenance
      (`runId`). Streams like any analyst run.
- [ ] "Digest now" button on context-channel rows (Sources tab) → run + open it.
- [ ] Knowledge tab: "Today" section — `daily:*` notes grouped at the top, newest
      first (they already age out via TTL).
- [ ] After the prompt is tuned on manual runs: nightly scheduler job digests every
      context channel (`techniques.tip.digest_enabled`, default off until then).
- [ ] Tests: digest note scope/TTL; promotion provenance; scheduler gating.

## Phase 5 — run the experiment (cluster D)

- [ ] Batch 1: `--sample 20 --seed 7 --since 2026-06-01 --batch b1`. Review with the
      rubric below (batch review run + human pass in the UI). Log findings in a
      findings section appended to THIS file; date every claim, cite run ids.
- [ ] Fix the top findings (each fix = its own commit; method findings go to the tip
      docs, engine findings to PLATFORM-RULES).
- [ ] Batch 2: new seed after fixes; compare failure classes against batch 1 —
      recurring classes get escalated, resolved ones ticked.
- [ ] Decide: enable nightly digests (C2)? monthly experiment cadence? Update
      KNOWLEDGE-PLAN accordingly.

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
