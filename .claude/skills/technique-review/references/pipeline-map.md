# Pipeline map — stage → code → settings → trace steps

All paths under `backend/zargar/technique/` unless noted. Trace records carry `stage` /
`step`; this table says which code produced each and what knob changes it.

| stage | step(s) in trace | code | tunables (settings key → `Thresholds` field) | what can go wrong |
|---|---|---|---|---|
| run | `start`, `done`, `failed` | `service.TechniqueService.analyze` / `_execute` | `technique.enabled`, `technique.max_runs_per_day`, `llm.*` | cap reached, no key |
| data | `fetch`, `snapshot`, `abort`, `snapshot_saved`, `charts` | `analysis.gather_bars` → `history.fetch_recent` / `fetch_window` (Yahoo v8 chart); `render.render_chart` | `SESSIONS_FOR_TF`, `WINDOW_FOR_TF` in `analysis.py`; Yahoo depth: 1m ≈ 20 d, 5m/15m 60 d, 1h 2 y | missing timeframe (too far back), 404 symbol, 429, forming bar with volume 0, as_of off-session |
| data | `facts` | `analysis.compute_facts` → `levels.detect_levels`, `volume.build_profile`/`assess_volume`, `structure.read_trend`/`detect_wedge`, `candles.metrics`, `setups.build_bounce_setup`/`build_breakout_setup`/`classify_breakout`, `analysis._recent_break` | `technique.level_tolerance_pct`→`level_tolerance_pct`, `min_touches`, `pivot_window`, `lookback_sessions`, `volume_spike_mult`, `volume_dryup_mult`, `decisive_body_ratio`, `wedge_min_bars`, `min_risk_reward` (+ fixed: `strong_touches`, `volume_floor_mult`, `decisive_size_mult`, `max_breakout_wick_ratio`, `followthrough_*`, `long_wick_ratio`, `round_number_steps`) | level missed / merged / wrong kind; volume baseline absent (`measurable=false`); candidate invalid for the wrong reason; break not detected |
| facts→prompt | (inside `loop/plan`) | `analysis.facts_for_prompt` (max_bars=60) | — | important level outside the listed set; bars window too short to show the pattern |
| loop | `plan`, `stop`, `final`, `abort` | `vision.VisionPipeline.run` | `llm.max_passes` (call budget), `llm.effort`, `llm.model` | budget exhausted before grounding passes |
| context | `pass_1`, `result` | `VisionPipeline.run` PASS 1, schema `schemas.PassNotes`, prompt in `vision.py` + `schemas.SYSTEM_PROMPT` | — | wrong trend read on the 1h; keeps a level not in FACTS |
| pattern | `pass_2`, `result` | PASS 2 (same schema) | — | hallucinated wedge/flag; missed break test |
| entry | `pass_3`, `pass_3_retry{n}`, `draft`, `unparsed` | PASS 3, schema `schemas.TechniqueAnalysis` (flat), `to_contract()`; `clamp()` | prompt text in `vision.py`; `SYSTEM_PROMPT` | chased entry, wrong basis (bounce vs break), R:R < 3, no_setup with weak reasons, invented level |
| critic | `pass_4`, `kill`, `survive`, `skipped`, `unparsed` | PASS 4, schema `schemas.CriticVerdict`; applied in `VisionPipeline.run` | — | kill on a non-reason; survive with obvious fakeout tells; confidence adjustment out of range |
| grounding | `check` | `grounding.ground_analysis` | uses `level_tolerance_pct` / `level_tolerance_atr`; `min_risk_reward` | false accept (level within tolerance of the wrong anchor), false reject (entry on a bar price that is not in the 60-bar window), correction text unclear |
| options | `pick`, `result`, `skipped` | `service.option_pick` → `options.CboeClient` / `TradierClient`, `pick_for_setup` | `technique.options.enabled`, `technique.options.provider`, env `ZARGAR_TRADIER_TOKEN` | CBOE is US-only (`.TO`/`.V` → no chain); delayed quotes |
| setup | `persist` | `service._persist_setup` → `technique_setups` row | — | `valid` requires setup verdict + entry/stop + grounded + no blocking reason (CRITIC-WARN does not block) |
| proposal | `emit`, `skipped`, `error` | `service._emit_proposal` (practice proposal; approval → RiskGate) | `technique.emit_proposals`, `technique.default_risk_pct`, `technique.max_risk_pct`, `signals.default_ttl_minutes`, `trading.default_portfolio` | no sim portfolio |
| outcome | (separate: `technique_outcomes` rows, journal `TechniqueOutcomeScored`) | `service.score_run` / `score_pending` / `_outcome_loop` → `outcome.simulate_plan`, `fetch_after`, `path_summary` | `technique.outcome.enabled`, `technique.outcome.horizon_bars`, `technique.outcome.entry_window_bars`, `technique.outcome.interval_minutes` | pending (no bars yet / after-hours), unscorable (Yahoo depth passed, image-only) |
| review | `technique_reviews` rows, journal `TechniqueReviewAdded` | `service.add_review`, `review.py` taxonomy | — | — |
| window | `ok` / `note` / `watch_only` | `rulebook.session_window`; `service._execute` adds the R6 reason | `technique.enforce_session_windows`, `technique.scan.windows` | setup at mid-day marked valid=False; scans outside prime windows |
| plan | `mode`, `levels`, `trigger_<id>`, `no_triggers`, `invalidations` | `plans.build_session_plan` (from FACTS with structure tfs as context) ; `service._execute` plan branch; `_score_plan_run` → outcome rows `trigger:<id>` + `levels` | `technique.structure_tfs`, `technique.trigger_tf`, `technique.plan.*`, `technique.bounce_stop_pct` | level missed; trigger invalid for the wrong reason; gap rule (ours) voided a good plan; wrong planFor date (holiday) |
| walk-forward | `technique_sweeps` / `technique_walkforward` rows, journal `TechniqueSweep*` | `walkforward.run_symbol` / `replay_plan` / `TriggerTracker` / `level_respect` / `aggregate` ; `service.start_sweep` / `promote` | same as plan | claims `insufficient` until ≥ sample; counterfactual vs base tells whether R6/gap rules earn their place |
| arming | journal `TechniquePlanArmed/Disarmed/TriggerFired/TriggerSkipped`, chat note `plan_trigger` | `arming.PlanArmer` (bus `BARS` 1m), `VisionPipeline.run_critic`, `_persist_setup` | `technique.arm.*` | trigger fired mid-day (should be observed only); critic killed a good fire; no bars flowing (ensure_symbol) |
| replay | runs with `parent_run_id`, journal `TechniqueRunReplayed` | `service.replay_run` (bars from the parent's snapshot, `thresholds_override`) ; `service.diff` → `review.diff_runs` | — | image-only runs can't replay |

## Where things are persisted (per run id)

| table / place | content |
|---|---|
| `technique_runs` | row: symbol, as_of, tf, mode, trigger, status, verdict, setup_type, confidence, grounded, `facts` (slim, 60 bars/tf), `result` (analysis contract, grounding, passes, **trace**, options, usage, seconds), `images` (asset ids), `usage`, `llm`, **`config`** (provenance: promptVersion, rulebookVersion, codeVersion, processVersion, thresholds, settings, model/effort, maxPasses, timeframes, parentRunId, overrides, **barsAssetId**), `parent_run_id` |
| `chat_threads` / `chat_messages` (thread `kind=run`) | every pass: user prompt (images as refs) + assistant blocks (thinking, text) with `meta.parsed`; `run_summary`; reviews (`meta.kind=review`); for chat-driven runs: `tool_use` / `tool_result` blocks |
| `chat_assets` | per-tf PNGs (`kind=pass_chart`), `annotated`, `user_image`, **`bars_snapshot`** (gzip JSON, full windows), **`bars_after`** (JSON, outcome bars) |
| `technique_setups` | the emitted plan, `valid`, reasons, options, proposal link |
| `technique_outcomes` | per (run, plan_source ∈ analysis/candidate/market): status, outcome, R, MFE/MAE, bars_held, path, bars_asset_id |
| `technique_reviews` | expectation, verdict, root cause, notes, actions, process_version |
| `events` (aggregate_id = run id) | `TechniqueRunStarted/Completed/Failed`, `TechniqueGroundingFailed`, `TechniqueOutcomeScored`, `TechniqueReviewAdded`, `TechniqueRunReplayed`; setups under their own aggregate; `ChatToolCalled` under the thread |

## API (for the UI / scripts)

`GET /api/technique/runs?reviewed=&outcome=&reviewVerdict=&processVersion=&trigger=`,
`GET /api/technique/runs/{id}` (includes `outcomes`, `reviews`, `replays`, `config`),
`POST /runs/{id}/score`, `POST /api/technique/outcomes/score`,
`GET|POST /runs/{id}/reviews`, `GET /api/technique/reviews`, `GET /api/technique/review/taxonomy`,
`POST /runs/{id}/replay {thresholds?, useSnapshot, note, wait}`, `GET /runs/{id}/diff/{other}`,
`GET /runs/{id}/bundle[?format=json]` (zip).

## Tests that pin behaviour

`backend/tests/test_technique_review.py` (fake LLM client + synthetic bars: trace, provenance,
snapshot, outcome, reviews, bundle, replay, diff, migration, CLI),
`test_technique_api.py` (grounding, API shape), `test_technique_setups.py` /
`test_technique_detection.py` (detectors). Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_technique_*.py`.
