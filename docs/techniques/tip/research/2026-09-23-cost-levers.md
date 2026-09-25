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
| 2 | Trim knowledge notes, keep rules | `techniques.tip.review_context=notes` (`compact_review_header(notes_only=True)`: rulebook + pending proposals verbatim; notes scoped to the message's tickers/source + 3 general, each trimmed) | decided by the A/B below: **rejected** |
| 3 | Record extraction cost per call | new table `tip_llm_calls` (one row per extraction/transcription attempt, `ref` = raw content id) via `techniques/tip/llm_ledger.py`; `tip_llm_cost` prices it | on (no switch — bookkeeping) |
| 4 | Cheaper model for intake extraction (and a review-model check) | `techniques.tip.extraction_model` / `extraction_effort` (Extractor reads them per call); A/B tools `tip_review_ab`, `tip_extraction_ab` | decided by the A/B below: **rejected** |
| 5 | Batching (not fewer tool turns — user) | `techniques/tip/batching.py`: one-request Message Batches (50% list) for the nightly digests and the knowledge-audit judge; `techniques.tip.batch_jobs`, `batch_timeout_s` (3600 s; a batch that does not end is cancelled and fails as a timeout); cost report prices `(batch)` groups at half | switched on at deploy |
| 6 | Opus 5.5 for the analyst | `techniques.tip.analyst_model=claude-opus-5-5`; `techniques.tip.analyst_effort=high` pins the depth (Opus 5 default high, Opus 5.5 default medium); repairs replay the reply AS RECEIVED (Opus 5.5 rejects dropped/edited thinking blocks) — analyst appraise repair, digest repair, extraction JSON repair | switched at deploy |

Official prices (platform pricing page, read 2026-09-23 and entered in `llm.rates`): Opus 5.5 $4 in / $20 out, cache
read $0.20 (0.05×), 5-minute cache write $5; Sonnet 5 $2 / $10, cache read $0.20; batch = 50% of list.

Opus 5.5 request rules checked in the Tips code: no `thinking` field is sent (adaptive always on — fine), no forced
`tool_choice` (only `none`, which is allowed), no sampling parameters, no prefill; replies are read by block type.

## Measurements

**Extraction A/B (`tip_extraction_ab`, 40 recent messages, $4.39 spent of an $8 estimate-based guard, run to
completion 2026-09-23 evening).** Reference = the production extraction model (Opus 5).

| arm | exact | missed actionable | changed actionable | invalid | cost |
|---|---:|---:|---:|---:|---:|
| Opus 5 (reference) | 34/40 | 0 | 0 | 0 | $1.92 |
| Opus 5.5 | 30/40 | 0 | 1 (GOOGL call: expiry dropped) | 0 | $1.60 |
| Sonnet 5 | 27/40 | 0 | 3 (ab AMAT call and common-stock FSLY shares flipped to NON-actionable; FSLY instrument lost) | 0 | $0.86 |

**Verdict: both fail the pre-registered rule; extraction stays on Opus 5** (`extraction_model` = ""). Sonnet 5's
failure mode is the dangerous one: a real call read as non-actionable is exactly what the new review skip would drop.
The saving on offer was about $1 per 40 messages.

**Review A/B (`tip_review_ab`, stopped by host low memory after 8 of 15 cases, $4.75; per-case rows were saved).**
6 of the 8 carried a production management instruction. Missed-or-changed management vs production: Opus 5.5
reference 2, **notes-only trim 4**, **Sonnet 5 5**; Sonnet 5 was inconclusive on all 8 (it asked for evidence the
cases do not hold). **Verdict: both fail; `review_context` stays `full` and reviews stay on the analyst model.** The
reference's 2 of 6 is the replay noise floor (Opus 5 replayed against itself missed 2 of 8 in the ADV-04 run).

A first attempt at the same evaluation (22 review cases, about $15) was also stopped by low memory and saved nothing
detailed - the tools now write every finished case immediately (`--rows`).


## Rollback

Every lever is a journaled setting: `analyst_model` back to `""` (Opus 5), `review_skip_nonactionable=false`,
`review_context=full`, `extraction_model=""`, `batch_jobs=false`, `prompt_cache=false`. `tip_llm_calls` is
append-only bookkeeping and needs no rollback.

## Addendum - Opus 5.5 re-tested properly (2026-09-23 late evening, user: "opus 5.5 should supersede 5 … try harder")

**What was wrong with the first test.** It scored each model by agreement with what Opus 5 had extracted in
production, which rewards Opus 5 for reproducing its own output (Opus 5 re-run matched itself on only 32-34 of 40).
The re-test judged every disagreement against the MESSAGE itself.

**Finding.** Opus 5.5 was not worse at random: it systematically skipped POSITION UPDATES ("Stopped break even on MU
spreads", "3rd TP hit … QQQ puts", "cutting googl friday calls") - it read the prompt's "most content contains NO
actionable signal … return an empty signals list" literally. Anthropic's Opus 5.5 prompting guide: start at `medium`
effort (Opus 5.5 at medium matches or exceeds Opus 5 at high; it thinks MORE per turn at the same level), reserve
xhigh/max for measured gains, size `max_tokens` for thinking, and name the specific behaviour wanted.

**Runs (same 40 messages, estimate-based guards):**

| arm | changed actionable | position updates caught | cost / 40 |
|---|---:|---|---:|
| Opus 5 @ high (production) | 0 | yes (noisy re-run) | $1.89-1.92 |
| Opus 5.5 @ xhigh, old prompt | 3 | no (AMAT trim, MU stop-out, QQQ trims missed) | $1.95 |
| Opus 5.5 @ medium, old prompt | 3 | no (same misses) | $1.51 |
| Opus 5.5 @ high + updates rule | 1 (FSLY instrument) | yes; also fixed DLTR (production had DLR) | $1.66 |
| **Opus 5.5 @ medium + updates rule** | **0** | **yes** (one slip: ACHR "leaps" instrument - now covered) | **$1.56** |
| Sonnet 5 @ max | 2 invalid replies in 4 messages (thinking ate the output budget); stopped | - | - |
| Sonnet 5 @ high + updates rule | 0 | partly (missed CIFR, QQQ close) | $0.86 |

**Decision (shipped in this release):** the POSITION UPDATES rule (+ LEAPS, shares-source instrument) is in the
production extraction prompt; extraction runs `claude-opus-5-5` at `medium`; the analyst runs `claude-opus-5-5` at
`medium` with `analyst_max_output_tokens` 8000 (was 3000, sized for Opus 5). Sonnet 5 stays off: with the rule it
stops making actionable errors but still misses updates the desk manages from.

