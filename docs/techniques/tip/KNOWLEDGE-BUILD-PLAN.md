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

## Phase 3 — knowledge lifecycle (cluster B1/B2/B4/B5)

- [ ] `TipNote.valid_until` (nullable) + `last_cited_at`/`cited_count` columns
      (additive migration via `db.create_all`).
- [ ] TTL defaults on create, by scope kind: `daily:*` 14d · `ticker:*`/`source:*`
      90d · `rule`/`general`/`signal:*` none. Knobs:
      `techniques.tip.note_ttl_daily_days`, `note_ttl_scoped_days` in DEFAULTS.
- [ ] Injection: expired notes are NOT injected (kept as history, like superseded);
      every injected note is rendered WITH its date + scope (B2) so the model sees
      temporal validity.
- [ ] Nightly sweep expires due notes (journaled `TipNoteExpired`; folded into the
      existing nightly tip review job).
- [ ] Knowledge tab: "expires in Xd" chip; pin action (clears `valid_until`,
      journaled); expired notes under the history toggle.
- [ ] B4: weekly audit widened beyond `rule` — stale candidates (past TTL grace,
      never cited, or contradicted) flagged `needs_human` with the same one-click
      resolve.
- [ ] B5 outcome refresh: when a retro/appraisal cites a note (`save_note` refers or
      the run's injected-note ids are credited), bump `cited_count`, set
      `last_cited_at`, and extend `valid_until` by its scope's TTL. Injection order:
      rules first (age order), then cited-recently, then newest.
- [ ] Tests: TTL assignment per scope; injection filter + date rendering; sweep;
      pin; refresh-on-cite; audit widening.

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
