# Knowledge & historical-experiment BUILD plan

Executes the decided options from `KNOWLEDGE-PLAN.md` (§4: backfill 90d, batch 20,
TTLs 14/90/∞, digest-on-demand first, experiment out-of-band). Phases in build order;
tick each box when done; every phase ends with its tests green
(`ZARGAR_TEST_DATABASE_URL` on :5433, own DB when parallel sessions may run).
Rules of the house apply: RiskGate on every order path (the experiment places NO
orders — enforce it, don't assume it), journal every decision, camelCase wire format,
new knobs in `settings_service.DEFAULTS`.

## Phase 0 — separation guards + experiment tagging (cluster E)

- [ ] `docs/PLATFORM-RULES.md` invariant: *technique knowledge stores are
      per-technique — `tip_notes` belongs to the tips desk only; EM's rulebook to EM
      only; no cross-injection, ever.*
- [ ] Guard test (`tests/test_platform_separation.py`): static scan — no module under
      `zargar/technique/` imports/queries `TipNote`/`tip_notes`; no module under
      `zargar/techniques/tip/` reads EM's rulebook/prompt assets. Fails the suite on a
      cross-read.
- [ ] `experiment:<batch>` tag convention: experiment signals carry it in
      `extraction.experiment`, their TipAnalystRuns in `opinion.experiment`; helper
      `is_experiment(...)` in one place.
- [ ] Exclusion filters: source scorecards, shadow-book stats, nightly retros,
      unfilled retros, lane grading and the weekly rule audit all skip
      experiment-tagged rows (with an explicit `include_experiments=True` escape
      hatch for the batch review itself). Tests for each exclusion.

## Phase 1 — context channels + 90-day backfill (cluster C1 + config)

- [ ] Watch entry gains `mode: "tips" | "context"` (default `tips`). Gateway: a
      `context` channel is mirrored (live + backfill) but NEVER matched into tip
      intake/extraction. Tips-mode behavior unchanged.
- [ ] Sources UI (Discord picker): mode toggle per channel — label context mode
      "mirror + digest only (never auto-tips)".
- [ ] Raise the `onboardDays` backfill cap 17 → 90 (constant + validation; per-channel
      value still set on the watch entry).
- [ ] Mirror capacity check: estimate 90d × 10 channels vs
      `techniques.tip.mirror_max_messages` (20k); raise the default if the estimate
      crowds it (keep pruning oldest-first).
- [ ] Operator steps (doc + do): set `onboardDays: 90` on the 9 tip channels; add
      `trading-floor` as a `context` channel (baseline backfill). Verify mirror
      counts/date ranges per channel afterwards and record them here.
- [ ] Tests: context-mode messages never reach extraction; backfill honors 90;
      tips-mode unchanged.

## Phase 2 — historical experiment harness (cluster A1)

- [ ] Process-mirrored-message path: build a RawContent from a `DiscordMessage`
      (text + local image transcription path), with `stated_at`/posted-at taken from
      the mirror row — NOT "now" — so the stale-tip gate routes it to replay
      naturally. No proposals, no book entries, no scheduler arms for experiment
      signals (assert, don't assume).
- [ ] `tools/tip_experiment.py` CLI:
      `--sample 20 --seed 7 --since 2026-06-01 --channels ... --batch <name>` —
      random sample of mirrored messages from tips-mode channels, skipping
      already-processed message ids; runs each through the real intake
      (extraction → verification → replay) + analyst appraisal; writes a batch
      manifest (message ids → signal ids → run ids) to the journal
      (`TipExperimentBatch` event) and prints a review URL list.
- [ ] Analyst historical mode: appraise context carries
      `historical: {statedAt, note}` — "this tip is from <date>; live quotes/chains
      are NOT its market — appraise the decision as of tip time; the replay block
      holds the outcome evidence." Verdicts still recorded, never traded.
- [ ] Batch review: `tip_experiment review --batch <name>` runs ONE analyst run
      (kind `retro`, experiment-tagged) over the batch's runs with the §5 rubric,
      producing a findings summary note (scope `general`, experiment-tagged) and a
      printed report.
- [ ] Tests: seeded sampler determinism; mirror→RawContent conversion (incl. image
      path); stale routing with old posted_at; zero-order/zero-proposal guarantee;
      batch manifest journaling; exclusion filters still hold end-to-end.

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
