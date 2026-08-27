# Technique run review — plan and status

> **Status (2026-08-21): built.** Phases A–G below are implemented; the table at
> the end says where each piece lives. Tests: `backend/tests/test_technique_review.py`.

Goal: every analysis run (one `technique_runs` id) is a complete, self-contained
record of *what the process saw, why it did each step, what it concluded, and
what actually happened afterwards*, so a Claude Code skill (`/technique-review`)
can replay the reasoning, compare it to the outcome and to what the user
expected, find the stage that went wrong, and plan a code/prompt/threshold fix.

## 1. What is already recorded per run id (no change needed)

| Where | What |
|---|---|
| `technique_runs` | symbol, as_of, tf, mode, trigger, status, verdict, setup_type, confidence, grounded, `facts` (detector output, last 60 bars/tf), `result` (analysis contract, grounding checks, per-pass parsed output + usage + seconds, options, mode, error), `images` (asset ids), `usage`, `llm` (model/effort/display) |
| `technique_setups` | the emitted plan (entry/stop/targets/R:R/rules/no-trade reasons/options), `valid` flag, proposal link |
| chat thread (`kind=run`, `run_id`) | per pass: the exact user prompt (images as refs) and the full assistant response blocks — summarized thinking, text, structured JSON; the run summary message |
| chat thread (`trigger=chat` runs) | `tool_use` blocks (tool name + args), `tool_result` blocks, and the assistant text/thinking that *preceded* the call — i.e. the model's stated reason for calling it |
| `events` journal (`aggregate_id = run_id`) | RunStarted, RunCompleted (rules fired, no-trade reasons, usage, seconds), GroundingFailed (failed checks), SetupEmitted; `ChatToolCalled` (name, args, meta) |
| `chat_assets` | per-tf chart PNGs the model saw, the annotated final chart, the user's image |

## 2. Gaps

1. **No outcome.** Nothing records what price did after `as_of` — whether the
   entry filled, stop/targets hit, R achieved, or (for `no_setup`) whether the
   rejected candidate would have worked. `backtest._simulate` has the logic but
   is never applied to live runs.
2. **No expectation / review record.** Nowhere to store "what I expected",
   "verdict was right/wrong", "root cause stage", "planned fix".
3. **Decision trace is implicit.** Why the critic ran (or not), why a retry
   happened, which corrections were sent, how the critic changed confidence or
   flipped the verdict, why the loop stopped (budget vs passed) — all
   reconstructable from pass names + grounding attempts, but not stated.
4. **No provenance snapshot.** Thresholds / `technique.*` + `llm.*` settings,
   the system-prompt version, the rulebook version and the code commit are not
   stored on the run — so two runs can't be compared fairly and a reviewed run
   can't be tied to the process version that produced it.
5. **Bars are not fully snapshotted.** `facts.bars` keeps 60 bars/tf; charts
   used 150–400; Yahoo 1m history is ~20 days. Older runs can't be replayed or
   re-scored.
6. **No single bundle / CLI.** Reviewing needs joins across 4 tables + asset
   fetches over HTTP; a skill needs one command that drops the whole run on disk.
7. **No replay.** `analyze(as_of_ms=…)` exists but can't pin thresholds/prompt
   or use saved bars, and doesn't link the replay to the parent run.
8. **No skill.** `.claude/skills/` doesn't exist in the repo.

## 3. Code changes

### Phase A — provenance + decision trace (backend, small)
- `TechniqueRun.config` (new JSON column, additive `ALTER TABLE … ADD COLUMN IF
  NOT EXISTS` helper in `db.py` next to `create_all`): `{thresholds, settings:
  {technique.*, llm.*}, promptVersion: sha256(SYSTEM_PROMPT)[:12],
  rulebookVersion: sha256(json(RULES))[:12], codeVersion: git sha (env
  `ZARGAR_GIT_SHA` or `git rev-parse` at startup), timeframes, maxPasses}`.
- `PipelineResult.trace: list[dict]` filled by `VisionPipeline`: one record per
  decision — `{"step", "reason", "detail", "call"}` — e.g. `entry_retry1:
  grounding failed [corrections…]`, `critic: skipped (verdict=no_setup)`,
  `critic: kill → verdict no_setup, conf 0.72→0.35`, `loop: stopped, call
  budget 6 reached`, `data: 1m 390 bars (yahoo, 1.2s); 15m 120 bars`. Persisted
  in `result.trace`; rendered by the bundle as a timeline.
- Bars snapshot: full per-tf windows used for charts/facts stored as one
  `chat_assets` row (`application/json`, gzip), id in `run.images["bars"]`.
- `TechniqueService.analyze` gains `parent_run_id` (for replays) stored in
  `config.parentRunId`.

### Phase B — outcomes ("facts of the matter")
- New module `technique/outcome.py`; new table `technique_outcomes`:
  `run_id, setup_id|null, plan_source (analysis|rejected_candidate), horizon_bars,
  status (pending|scored|unscorable), outcome (not_filled|stopped|tp1|tp2|tp3|
  horizon), r_multiple, mfe_r, mae_r, bars_held, path {+5,+15,+30,+60 bars:
  high/low/close}, bars_after_asset_id, scored_at, note`.
- Refactor `backtest._simulate` → shared `simulate_plan(bars, start_idx, plan)`
  used by both backtest and outcome scoring.
- Score both the emitted plan and, for `no_setup`, `facts.candidateSetups[0]`
  (the rejected candidate) so missed trades are measurable too.
- Trigger: `TechniqueService._outcome_loop` (hourly; scores runs whose
  `as_of + horizon` has elapsed, within Yahoo's history window), plus
  `POST /api/technique/runs/{id}/score` and the CLI. Journal
  `TechniqueOutcomeScored`.

### Phase C — review annotations
- New table `technique_reviews` (append-only, many per run): `id, run_id,
  created_at, reviewer (user|claude), expected_verdict, expected_setup_type,
  expected_entry/stop/targets (nullable), expectation_note, review_verdict
  (correct|wrong_verdict|wrong_levels|wrong_plan|late|data_issue|unclear),
  root_cause_stage (data|detectors|facts_prompt|pass_context|pass_pattern|
  pass_entry|critic|grounding|options|thresholds|other), notes, actions
  [{desc, file, status}], process_version (copied from run.config)`.
- `POST/GET /api/technique/runs/{id}/reviews`; `GET /api/technique/runs`
  gains `reviewed=`, `outcome=` filters and returns outcome/review summaries.
  Journal `TechniqueReviewAdded`.

### Phase D — bundle export + CLI (what the skill drives)
- `python -m zargar.tools.technique_review` (direct DB, no server needed):
  - `list [--unreviewed] [--wrong] [--symbol] [--limit]` — table of runs with
    verdict, outcome, R, review status.
  - `dump <run_id> [--out DIR]` → `DIR/<run_id>/`: `run.json` (row + config +
    setups + outcomes + reviews), `facts.json`, `bars/<tf>.json`,
    `transcript.md` (pass prompt → thinking → text → parsed JSON; tool calls with
    args/reason/result for chat runs), `transcript.json`, `trace.md`,
    `grounding.json`, `journal.json`, `images/*.png`.
  - `replay-facts <run_id>` — recompute `compute_facts` from the bars snapshot
    with current code/thresholds and diff vs stored facts (detector regression).
  - `review <run_id> --expected-verdict … --review-verdict … --root-cause …
    --note … [--action …]` — writes a `technique_reviews` row.
  - `score <run_id> [--horizon N]` — force outcome scoring.
- Same bundle via `GET /api/technique/runs/{id}/bundle` (zip) for the UI.

### Phase E — replay (after a fix)
- `POST /api/technique/runs/{id}/replay {thresholds?, promptOverride?}` →
  `analyze(symbol, as_of=run.as_of, parent_run_id=id, bars=snapshot)`;
  `gather_bars` accepts preloaded bars. The review then compares parent vs
  child side by side (`technique_review diff <a> <b>`).

### Phase F — UI (can follow the skill)
- Runs list: outcome / R / reviewed columns + filters.
- Run detail: Trace timeline, Outcome card (after-bars chart with the plan
  overlaid), Review panel (expected vs actual form → POST review).

### Phase G — the skill `.claude/skills/technique-review/`
- `SKILL.md` — triggers on "review run …", "why did the pipeline say …",
  "improve the technique". Workflow: pick run (id or `list --unreviewed/--wrong`)
  → `dump` → read `trace.md`, `transcript.md`, `facts.json`, outcome, images
  (Read renders PNG) → stage-by-stage table (saw / decided / evidence / rule) →
  compare to outcome and to the user's expectation (ask if not given) → classify
  root cause → `review` to persist → fix plan (file:function, threshold/prompt,
  test to add, lesson for `PIPELINE-PLAN.md`) → optionally implement
  in a worktree, `replay`, `diff`.
- `references/pipeline-map.md` (stage → file:function, settings keys, events),
  `references/rulebook-index.md` (rule ids ↔ PDF sections),
  `references/failure-taxonomy.md`, `references/review-template.md`.

### Tests
- outcome scoring on synthetic bars (fill / stop / tp ladder / not filled /
  horizon); trace + config present on a canned run; bundle export writes every
  file; review CRUD + journal; additive migration idempotent; replay-facts diff.

### Docs
- CLAUDE.md: CLI line + skill mention; `PIPELINE-PLAN.md` §9 → link.

## 4. Order
A → D (skill usable immediately on new runs) → B → C → G polish → E → F.

## 5. Where it lives (as built)

| piece | location |
|---|---|
| additive migration | `backend/zargar/db.py::create_all` (`_ensure_columns_sync`) |
| provenance snapshot | `technique/provenance.py`; stored in `TechniqueRun.config` (+ `parent_run_id`) |
| decision trace | `technique/vision.py::VisionPipeline.note`, `PipelineResult.trace`; service adds data/options/setup/proposal/run steps; persisted in `result.trace`; failed runs keep the partial trace |
| bars snapshot | gzip JSON chat asset (`kind=bars_snapshot`), id in `config.barsAssetId`; `TechniqueService.load_bars_snapshot` |
| outcomes | `technique/outcome.py` (`simulate_plan` shared with `backtest.py`, `fetch_after`, `path_summary`); `TechniqueService.score_run` / `score_pending` / `_outcome_loop`; table `technique_outcomes`; settings `technique.outcome.*`; journal `TechniqueOutcomeScored`; backdated runs are scored on completion |
| reviews | `technique/review.py` (taxonomy, validation, `diff_runs`); `TechniqueService.add_review` / `list_reviews`; table `technique_reviews`; journal `TechniqueReviewAdded`; the review is also appended to the run's chat thread |
| replay / diff | `TechniqueService.replay_run` (`analyze(parent_run_id, thresholds_override, bars_override)`), `TechniqueService.diff`; journal `TechniqueRunReplayed` |
| bundle | `technique/bundle.py` (`build_bundle`, `bundle_files`, `write_bundle`, `zip_bundle`, `trace.md` / `transcript.md` / `README.md` renderers) |
| API | `api/routes_technique.py`: `GET /runs?reviewed&outcome&reviewVerdict&processVersion&trigger`, `GET /runs/{id}` (+outcomes/reviews/replays/config), `POST /runs/{id}/score`, `POST /outcomes/score`, `GET/POST /runs/{id}/reviews`, `GET /reviews`, `GET /review/taxonomy`, `POST /runs/{id}/replay`, `GET /runs/{id}/diff/{other}`, `GET /runs/{id}/bundle[?format=json]` |
| CLI | `backend/zargar/tools/technique_review.py` (`list`, `show`, `dump`, `score`, `replay-facts`, `review`, `reviews`, `diff`, `replay`, `taxonomy`) |
| UI | `frontend/src/components/technique/RunResult.tsx` (provenance, trace panel, outcome cards, review form/list, replay + diff, bundle download); `TechniquePage.tsx` history lenses + outcome/review columns; store `techniqueRunBumps` refetch on WS `outcome`/`review` |
| skill | `.claude/skills/technique-review/SKILL.md` + `references/{pipeline-map,failure-taxonomy,review-template,rulebook-index}.md` |
