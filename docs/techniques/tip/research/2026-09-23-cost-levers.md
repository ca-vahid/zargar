# Tips model cost levers — decisions, build and measurements (2026-09-23, 0.8.39)

**User decision (2026-09-23, in session):** "yes switch on caching and the go from items 1 to 4; for 5 i dont like fewer
tool turns per run but i like batching … let's update our opus usage to use 5.5 … let's go with all of these."

Starting point (list price, `tip_llm_cost`): 2026-09-22 priced $100.45 — intake reviews $73.59, appraisals $23.85,
retros $2.64, digests $0.38; 97% of the bill is input tokens and none of it was read from cache. Intake extraction was
not in the report at all (in-memory rollup only; EM's estimate $50–130 over the month).

## What changed

| # | Lever | Built as | State after this release |
|---|---|---|---|
| 0 | Conversation prompt caching | `techniques.tip.prompt_cache=true`, `prompt_cache_scope=conversation` (0.8.34 code) | **ON since 2026-09-23 13:46 ET** (journaled `SettingChanged`) |
| 1 | Skip the analyst on non-actionable, desk-irrelevant messages | `techniques.tip.review_skip_nonactionable` — skip ONLY when the relevance gate found nothing held/armed/proposed, the desk read was complete, the discard was not entry-shaped AND extraction marked every signal non-actionable; journaled `TipReviewGate appliedBy=nonactionable` | switched on at deploy (user decision). The gate itself stays `observe` for everything else |
| 2 | Trim knowledge notes, keep rules | `techniques.tip.review_context=notes` (`compact_review_header(notes_only=True)`: rulebook + pending proposals verbatim; notes scoped to the message's tickers/source + 3 general, each trimmed) | decided by the A/B below |
| 3 | Record extraction cost per call | new table `tip_llm_calls` (one row per extraction/transcription attempt, `ref` = raw content id) via `techniques/tip/llm_ledger.py`; `tip_llm_cost` prices it | on (no switch — bookkeeping) |
| 4 | Cheaper model for intake extraction (and a review-model check) | `techniques.tip.extraction_model` / `extraction_effort` (Extractor reads them per call); A/B tools `tip_review_ab`, `tip_extraction_ab` | decided by the A/B below |
| 5 | Batching (not fewer tool turns — user) | `techniques/tip/batching.py`: one-request Message Batches (50% list) for the nightly digests and the knowledge-audit judge; `techniques.tip.batch_jobs`, `batch_timeout_s` (3600 s; a batch that does not end is cancelled and fails as a timeout); cost report prices `(batch)` groups at half | switched on at deploy |
| 6 | Opus 5.5 for the analyst | `techniques.tip.analyst_model=claude-opus-5-5`; `techniques.tip.analyst_effort=high` pins the depth (Opus 5 default high, Opus 5.5 default medium); repairs replay the reply AS RECEIVED (Opus 5.5 rejects dropped/edited thinking blocks) — analyst appraise repair, digest repair, extraction JSON repair | switched at deploy |

Official prices (platform pricing page, read 2026-09-23 and entered in `llm.rates`): Opus 5.5 $4 in / $20 out, cache
read $0.20 (0.05×), 5-minute cache write $5; Sonnet 5 $2 / $10, cache read $0.20; batch = 50% of list.

Opus 5.5 request rules checked in the Tips code: no `thinking` field is sent (adaptive always on — fine), no forced
`tool_choice` (only `none`, which is allowed), no sampling parameters, no prefill; replies are read by block type.

## Measurements

*Filled in from the paid A/B runs of 2026-09-23 (estimate-based guards: reviews $20, extraction $8).*

RESULTS_PLACEHOLDER

## Rollback

Every lever is a journaled setting: `analyst_model` back to `""` (Opus 5), `review_skip_nonactionable=false`,
`review_context=full`, `extraction_model=""`, `batch_jobs=false`, `prompt_cache=false`. `tip_llm_calls` is
append-only bookkeeping and needs no rollback.
