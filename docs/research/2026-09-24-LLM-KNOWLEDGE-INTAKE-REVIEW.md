# LLM use, knowledge base and intake: read-only review (2026-09-24)

**Scope and method.** This is a read-only review. The runtime Postgres was opened with `default_transaction_read_only = on`.
No settings, code or data were changed, and no model was called. Dollar figures are **list-price estimates** taken from
`llm.rates` (Opus 5: $5 in / $25 out / $0.50 cache read / $6.25 cache write. Opus 5.5: $4 / $20 / $0.20 / $5. Batches at
50%). They are not the invoice. Days are ET calendar days. Sources: `tip_analyst_runs.opinion.usage` (every
appraise/intake-review/retro/digest run), `tip_llm_calls` (extraction and transcription, recorded only from
2026-09-23), nightly `TechniqueHookStats.llm` rollups, `settings`, `SettingChanged`, `TipReviewGate`, `tip_notes`,
`raw_content`, `signals`, `proposals`, and `managed_positions` on the Tips Practice book `4611946d…`.

This builds on `docs/techniques/tip/research/2026-09-23-cost-levers.md` and `2026-09-24-sharp-pencil-review-and-plan.md`.
Where a finding is already in those plans (P1-P12), it is cross-referenced and not re-proposed.

**Caveat.** The new cost regime (caching, Opus 5.5 at medium effort, the non-actionable skip) has **one full day** of
data (09-24). Every "per day now" figure below is n=1 and should be re-read after the 09-25 session.

---

## 1. Current LLM configuration and measured cost

### 1.1 What is set now (runtime `settings`, as of 2026-09-24 22:37 ET)

| Stage | Model | Effort | Caching / routing | Changed |
|---|---|---|---|---|
| Intake extraction and attachment transcription (`signals/extraction.py`) | `claude-opus-5-5` (`techniques.tip.extraction_model`) | `medium` | **none**: the static system prompt and schema are sent uncached on every call | 09-23 22:52 |
| Intake review (analyst on non-tradable messages) | `claude-opus-5-5` (`techniques.tip.analyst_model`) | `medium` (`analyst_effort`) | `prompt_cache=true`, `prompt_cache_scope=conversation`, `prompt_cache_stable_first=true` (rulebook first, own 5-minute marker) | 09-23 13:46 / 21:54 / 22:28 |
| Appraisal (tradable tip) | same analyst model and effort | `medium` | same caching | same |
| Retro (nightly, closed positions) | same | `medium` | same | same |
| Digest and knowledge-audit judge | same | `medium` | `batch_jobs=true` (Message Batches, 50%) | 09-23 16:41 |
| Output cap | `analyst_max_output_tokens=8000` (was 3000) | | | 09-23 22:28 |
| Review filters | `review_skip_nonactionable=true`; `review_gate` **not set = `observe`**; `review_context` not set = `full`; `review_source_budgets` = `{}` (off) | | | 09-23 16:41 |
| Research capture | `review_capture_context=true`, `frozen_capture_context=true` (about 78 KB stored per review) | | | 09-19 / 09-15 |
| Engine default | `llm.model` default `claude-opus-5`, `llm.effort` `high` (EM; EM makes no scheduled model calls since `paid_review=false`) | | | |
| Knowledge | `analyst_notes_max` 12, `analyst_max_rules` 50, `analyst_max_pending_rules` 6, `knowledge_apply_enabled` false (propose-only), `digest_enabled` true, `rule_audit_enabled` true | | | |

### 1.2 Measured spend, last 7 days (09-18 → 09-24, list price)

| Day | Intake reviews | Appraisals | Retros | Digest | Extraction + transcribe | **Total** |
|---|---:|---:|---:|---:|---:|---:|
| 09-18 Thu | $69.85 (90 runs) | $8.93 (11) | $3.39 | $0.19 | not recorded¹ | **$82.36** |
| 09-19 Fri (weekend-ish flow) | $2.74 | – | – | – | ¹ | $2.74 |
| 09-20 Sun | $10.36 | – | – | – | ¹ | $10.36 |
| 09-21 Mon | $92.68 (134) | $20.32 (25) | $2.47 | $0.18 | ¹ (rollup: 921k in / 89k out ≈ $6.83) | **$115.65** |
| 09-22 Tue | $73.59 (109) | $23.85 (27) | $2.64 | $0.38 | ¹ | **$100.46** |
| 09-23 Wed (switch day) | $52.05 (100) | $7.76 (12) | $1.23 | $0.08 | $0.03 | **$61.15** |
| **09-24 Thu (new regime)** | **$10.30 (72)** | **$5.98 (26)** | **$0.70** | **$0.06** | **$4.41 (114 calls)** | **$21.45** |
| **7-day total** | **$311.57** | **$66.84** | **$10.43** | $0.89 | $4.44 + unrecorded | **≈ $394 (+ roughly $15-25 of unrecorded extraction)** |

¹ Before 09-23, extraction was measured only by the in-memory rollup, which is lost on restart. The 09-17 and 09-21
rollups price it at $4.2 and $6.8 a day on Opus 5. Rule-audit runs carry no usage, so they are unpriced.

**Per-review cost fell from about $0.68 (09-22) to $0.14 (09-24), and per appraisal from $0.88 to $0.23.** A weekday
now costs about $21, down from $100-115 (-80%).

### 1.3 Token mix

- **Before caching (09-22):** 97% of dollars were uncached input. Nothing was read from cache.
- **Since caching was enabled (09-23 13:46 ET → now, 145 analyst-family runs):** input-side tokens = 11.94M cache
  read + 3.75M cache write + 0.05M uncached. **Cache-read share is 75.9%** (72.5% if the uncached extraction input
  since 09-23 is counted).
- **Where 09-24's $21.45 went:**

| Component | $ | Share |
|---|---:|---:|
| Cache **writes** (analyst: 2.43M tokens × $5) | $12.17 | **57%** |
| Output (analyst 149k + extraction 73k tokens) | ≈ $4.50 | 21% |
| Uncached input (extraction 723k tokens; this path has no caching) | $2.92 | 14% |
| Cache reads (9.08M tokens × $0.20) | $1.82 | 8% |

The input/output split is now 79/21 (it was 97/3). The rulebook is effectively free once cached: about 11k tokens
per read is $0.002. **The bill is now cache writes of per-message content, plus uncached extraction.**

- An intake review's first call writes about 17k tokens on average; appraisals write about 32k. 59 of 72 reviews and
  16 of 26 appraisals read the shared rulebook from cache on their first call. The misses (gaps between runs longer
  than 5 minutes) re-write about 36k tokens each.

---

## 2. Knowledge base health

### 2.1 Inventory (`tip_notes`, now)

| Scope | Rows | Live | Disputed / pending | Superseded | Live chars | Live, never supplied to a run | Live, never cited |
|---|---:|---:|---:|---:|---:|---:|---:|
| `source:*` | 1,080 | 1,068 | 11 | 1 | **1.56M** | 360 | 603 |
| `ticker:*` | 356 | 347 | 9 | 0 | 398k | 210 | 200 |
| `general` | 244 | 244 | 0 | 0 | 349k | 27 | 171 |
| `rule` | 113 | **37 operative** | **29 pending** | 47 | 41.7k (operative) | 0 | **37 (all: reliance is not recorded)** |
| `experiment:*` | 52 | 52 | 0 | 0 | 40k | 52 | 52 |
| `daily:*` (digests) | 28 | 25 | 0 | 0 | 23k | **25 (all)** | 25 |
| `evidence:*` | 17 | 17 | 0 | 0 | 33k | 17 (by design) | 17 |
| `signal:*` | 14 | 14 | 0 | 0 | 12k | 13 | 13 |

No note is pinned or core. Nothing has expired yet: the oldest scoped notes are about 27 days old against a 90-day
TTL. Deleted rows: 0.

**Growth: about 100-150 notes (≈150k chars) per weekday.** 09-24 alone added 42 general, 19 source, 16 ticker, 3 rule
and 3 daily notes. 1,709 of the live notes were written by the analyst. Most come from intake reviews (648
`save_note` calls in the 7-day window).

### 2.2 What is injected into every run

Measured on the 433 intake reviews whose exact request was captured (`reviewManifest`, `review_capture_context=true`).
The header median is **76.5k chars (about 19k tokens)**:

| Header part | Median chars | Share |
|---|---:|---:|
| Operative rulebook (37 rules, all supplied every run) | 42,379 | **55%** |
| Pending rule proposals (6 of 29 shown, "not operative") | 10,953 | 14% |
| Shared notes (up to 12: 4 general, 4 source, 3 ticker) | 20,306 | 26% |
| Recent messages from the source | 2,032 | 3% |
| **The message itself** (plus per-signal outcomes) | **about 100-1,600** | **< 2%** |
| (System prompt, apart) | 2,347 | |

**About 96% of every review's context is knowledge; the message is under 2%.** With stable-first caching the 55%
rulebook is now cheap, but the other roughly 40% (pending proposals, notes, history) is written fresh on every review.
That write is where most of today's bill comes from.

### 2.3 Defects and hygiene findings

**K1. Bug: fully-qualified note scopes are silently rewritten to `general`.** In `techniques/tip/analyst.py`
(`save_note` handler, around line 979), the model's `scope` argument is lower-cased and looked up in
`{"ticker","source","tip","rule"}`. Any other value falls back to `"general"`. When the model passes the full scope
string, e.g. `"source:🌟｜eva"` or `"ticker:NVDA"`, the note is stored as `general`, and the tool even returns
`"scope": "general"` (run `356b0b82…`, note `0d0536c2…`). In the 7-day traces, **135 of 701 `save_note` calls
(19%) passed a full scope and were misrouted.** Of the 183 general notes written in 8 days, 120 start with a source
tag like `[eva, …` or `[MuggZone, …`. There are two consequences:
- **Quality (every run):** `notes_for_tip` reserves the first 4 of 12 slots for the *newest* general notes. Right now
  those 4 slots, in every appraisal and review of every source, hold MuggZone's SPX GEX-map chatter and an eva NVDA
  flow note (newest general notes, 09-24 15:06-15:43). An `ab` appraisal of AFRM is handed another room's 0DTE SPX
  commentary.
- **Knowledge lost:** the source's own scope never gets these notes. A future eva run does not see its own eva
  lesson.

**K2. Retrieval is recency-only, so most knowledge is never read.** Each scope returns its *newest* N notes
(`signals/service.py::notes_for_tip`, general 4 / source 4 / ticker 3 / signal 3). muggzone has 477 live source notes
(732k chars), but a run sees only the 4 newest, so a durable lesson written a week ago is buried by today's chatter.
The analyst then re-derives it and saves it again. This write-many, read-newest-4 loop is what grows the KB by about
100 notes a day. 360 source notes and 210 ticker notes have never been supplied to a single run. (Already partly in
plan P8, weekly compaction.)

**K3. The rulebook is unmeasured.** All 37 operative rules are supplied to every run (supplied_count 543-544 each).
`cited_count` is 0 for every rule because rule reliance is not recorded (plan P7). The average rule is 1,128 chars,
mostly dated "Evidence:" narrative. A cheaper rendering (headlines) was measured and rejected as UNSAFE on 09-23, so
this is a quality and measurement issue now, not a cost issue.

**K4. The human review queue is the knowledge bottleneck.** There are 29 pending rule proposals, the oldest from 09-15
(9 days). **11 of them are refinements of the one "adoption geometry" family**, and 5 more are
"exit execution integrity / fill-reconciliation" clauses. Every run is shown 6 of them (≈11k chars, ≈2.7k tokens,
written to cache fresh each time), with an explicit label that they are not policy.

**K5. Rule tensions to adjudicate.** These were read from headlines; they are not proven contradictions.
- *Operative* 08-31 "an AVERAGE-DOWN add IS a real open … mirror if the underlying is still on the right side" vs
  *operative* 09-02 "ESCALATION: a fresh BTO on the SAME losing thesis at a further-OTM strike → auto-skip". The only
  line between the two is the strike, and there is no tie-breaker.
- *Pending* 09-24 "exit stacking: the source's trims REPLACE our ladder rungs" vs *pending* 09-21 "post-TP1 ratchet"
  and 09-22 "unarmed trail / post-trim breakeven". These are three exit proposals that can prescribe different actions
  after the same source trim, and plan P2 (deterministic source-exit mirroring) would supersede all three.
- *Pending* 09-17 and 09-24 "premium-stop width must exceed 2× the option's noise" vs *pending* 09-21 "on 0-5 DTE the
  premium stop IS the invalidation". These give opposite guidance on how tight a short-dated stop should be.

**K6. Digest daily notes are written but never read.** `daily:*` is not a scope `notes_for_tip` supplies, and all 25
live daily notes have supplied_count 0. Only the ≤5 "promoted nuggets" per digest reach runs. The cost is small
(digests ≈ $0.06/day under batching).

**K7. Near-duplicates are template-shaped, not semantic.** A 4-gram Jaccard ≥ 0.35 within the same scope finds only
24 of 1,659 notes (mostly "LANE GRADE: X — the desk chose 'arm'; … made $+0" boilerplate from the lane grader). The
real redundancy is semantic: the same source habit is restated daily in different words, a consequence of K2.
**Stale:** 31 live ticker notes (26k chars) are about tickers with no signal in 21 days. 52 `experiment:*` notes are
quarantined by design and never supplied.

**K8. Storage.** `tip_analyst_runs` holds 73 MB, of which 70 MB is traces from the last 7 days. Most of that is the
research capture (about 78 KB of `reviewManifest` per review). That capture's purpose, a cheaper-model review A/B,
was concluded on 09-23 (Sonnet rejected).

---

## 3. Intake funnel (2026-09-17 → 09-24: six sessions plus a weekend)

Mirrored Discord traffic: 17,342 trading-floor messages (context-only: digest, never intake) plus 1,147 messages in
the tip channels. Intake processed **730 messages**.

| Stage | Count | Note |
|---|---:|---|
| Messages taken in (`raw_content`) | 730 | all extracted (1 error) |
| Signals extracted | 400 | |
| Marked actionable by extraction | 201 | |
| Verified → proposal made | 74 | 246 failed verification, 44 shadow-only, 20 parked, 16 expired |
| Proposals | 88 | 55 declined by the analyst, 13 expired, **20 executed** |
| Practice positions opened | 20 | 14 closed, 6 open |
| Closed profitable | **7 of 14** | **realized +$242.75** |
| Model spend in the same window (recorded) | **$466.40** | intake reviews $367.86 (79%), appraisals $79.84, retros $13.20, digest $1.07, extraction $4.44 (+ unrecorded) |

**Unit costs at the old prices (window):** $0.64 per message, **$2.32 per actionable signal**, $5.30 per proposal,
**$23.32 per filled trade**, $33.31 per closed trade.
**On 09-24 (new regime):** 110 messages, 23 actionable, 15 proposals, 3 fills, $21.45. That is **$0.93 per actionable
signal and $7.15 per fill**.

### 3.1 By source (same window)

| Source | Msgs | Signals | Actionable | Proposed | Executed | Closed (wins) | Realized | Review $ | Appraisal $ | **Model $ total** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| muggzone-options | 335 | 114 | 48 | 25 | 5 | 5 (2) | +$77.95 | $172.86 | $25.37 | **$198.23 (43%)** |
| ab | 121 | 88 | 57 | 16 | 7 | 4 (3) | -$0.28 | $60.42 | $15.39 | $75.81 |
| tt | 82 | 45 | 25 | 9 | 0 | 0 | $0 | $47.46 | $9.24 | $56.70 |
| eva | 55 | 89 | 39 | 25 | 0 | 0 | $0 | $22.55 | $12.50 | $35.05 |
| common-stock | 44 | 19 | 14 | 3 | 3 | 2 (1) | **+$211.11** | $23.52 | $3.96 | $27.48 |
| neal | 42 | 26 | 10 | 5 | 4 | 2 (1) | -$7.02 | $15.65 | $7.74 | $23.39 |
| giul-heatseeker | 23 | 3 | 0 | 0 | 0 | 0 | $0 | $11.08 | $1.34 | $12.42 |
| jon-and-kian | 17 | 11 | 7 | 4 | 1 | 1 (0) | -$39.01 | $9.55 | $4.07 | $13.62 |
| MK-alpha-trades | 11 | 5 | 1 | 1 | 0 | 0 | $0 | $4.78 | $0.23 | $5.01 |
| **Total** | **730** | **400** | **201** | **88** | **20** | **14 (7)** | **+$242.75** | $367.86 | $79.84 | $447.70 |

(Realized P&L is for positions opened in the window and already closed. 6 are still open. All-time Tips Practice
closed: 29 positions, -$714.57.)

### 3.2 Where spend is wasted

1. **Intake reviews that change nothing but a note: about 70% of all spend.** Of the 601 paid reviews, **521 (87%)
   only saved notes**, 12 did nothing, **49 (8%) managed a position** (update_exit_plan 32, disarm 22, close 12 calls),
   and 19 (3%) flagged a possible missed tip. At the old price that is about $319 for notes that, per K1 and K2, are
   mostly misfiled or never read again. At today's $0.14 per review it is about $8-9 a day.
2. **Reviews the relevance gate would skip.** In `observe` mode the gate judged 78 reviews since 09-19 as unable to
   reach any held, armed or proposed item, and they ran anyway. **In those 78: 0 management actions**, and 2
   "missed_tip" flags, both of which point at items already on the desk (the AAPL 345C 11:23 fill; the HOOD 140C
   proposal pending with TAKE). **No false negatives in this sample.** That is about 13 reviews a day, ≈ $1.8/day now
   (≈ $9/day at old prices).
3. **Source concentration.** muggzone produced 46% of messages and 43% of model spend, for 5 fills and +$78 in this
   window. The sharp-pencil review found it -$226 realized over the whole record, with $334 of spend and 0 realized
   winners on options. `giul-heatseeker` (23 messages, 0 actionable, $12) and `tt` (25 actionable, 0 fills, $57) cost
   money and produced no trades in the window.
4. **Appraisals of ideas that are then declined.** 55 of 88 proposals were declined by the analyst, and 29% of takes
   could not be sized (sharp-pencil F5). A tip that fails a cheap deterministic feasibility check (premium × 100 × 1
   contract > risk budget) still pays for a full appraisal (≈ $0.23 now).
5. **Uncached extraction.** Every extraction call re-sends the same about 5-6k-token system prompt and JSON schema
   uncached (median input 6.6k tokens a call, 110 calls on 09-24 = $2.89 of uncached input a day, 14% of the bill).

**Profitability context.** In this window, trading realized +$243 over six sessions, about $40 a session. At the new
regime's $21 a weekday, the desk would have been roughly **+$19/session after model cost**. At the old prices it was
-$224. The profit levers are now trading ones: P1 shares-first, P2 mirror source exits, P3 no opening-quote stops.
Model cost is no longer the dominant term.

---

## 4. Recommendations, ranked by (money saved or made) / effort

Savings are per weekday at the 09-24 regime unless stated. **TD** = a Tips-desk decision (method, policy, knowledge or
setting). **Fix** = a code defect any reviewer would accept.

| # | Change | File / setting | Est. value | Effort | Risk | Owner |
|---|---|---|---|---|---|---|
| **R1** | **Fix the scope bug (K1).** In the `save_note` handler, accept an already-qualified scope (`ticker:X`, `source:Y`, `signal:Z`) by passing it through `SignalsService.normalize_scope`, and map bare words only when there is no colon. Reject a `source:` that does not match `ctx.source` (use ctx) so a run cannot write into another room. | `backend/zargar/techniques/tip/analyst.py` (`save_note`, ~l.979); test in `tests/test_tip_*` | **Quality, every run:** stops injecting other rooms' chatter into the 4 general slots of every appraisal and review, and routes about 19% of saved notes to the right scope. | XS (≈10 lines + test) | Very low | Fix, plus **TD** for the one-off repair below |
| **R1b** | **Re-scope the ≈135 misrouted general notes** (text starts `[<source>, …`, author `analyst:*`, 09-17 →) through the audited batch path (manifest + `--confirm`, revision snapshots). | `tools/tip_consolidation.py`-style manifest → `POST /api/tip/knowledge/consolidate` | Restores those notes to their sources; clears the general slots | S | Low (reversible, revisioned) | **TD** (knowledge mutation; propose-only policy) |
| **R2** | **Cache the extraction system prompt.** Put `cache_control: {"type":"ephemeral","ttl":"1h"}` on the static system block (prompt + schema). The per-message content stays after it. Intake is bursty and averages about one message every 4-5 minutes, so the 1-hour TTL (2× write, about $0.05/hour) beats the 5-minute one. | `backend/zargar/signals/extraction.py` (`system=` in `extract`, ~l.378-389; same for `transcribe`) | **≈ $2/day (≈ $10/week, about 10% of the current bill)**. Output is unchanged (exact-prefix cache). | XS | Very low. Verify `cache_read_input_tokens > 0` in `tip_llm_calls` the next day. | Fix (cost) |
| **R3** | **Enforce the relevance gate** (plan P5). 0 management false negatives in 78 observed skips. The 2 missed-tip flags were re-mentions of items already on the desk. | `techniques.tip.review_gate = enforce` (PATCH /api/settings, journaled) | ≈ $1.8/day now (-15-18% of reviews); scales with volume | Setting | Low; the gate keeps entry-shaped discards and anything held/armed/proposed | **TD** (after the 09-25 five-session report) |
| **R4** | **Take pending proposals out of the per-message write.** Either (a) render the pending channel inside the cached rulebook block (it only changes when a proposal is added or decided), or (b) show it only to appraisals and retros, since intake reviews wrote 3 rules in a week. | `techniques/tip/review_context.py::stable_first_blocks` (end the cached block at NOTES, not PENDING) or `analyst.py::review` (`_rules_text(..., pending=False)`) | ≈ 2.7k tokens less cache write per review, **≈ $1/day**, and less noise | XS-S | Low; a pending proposal stays labelled non-operative | Fix (a) / **TD** (b) |
| **R5** | **Adjudicate the 29 pending rules in one sitting** (K4, K5). Fold the 11 geometry refinements into the canonical geometry rule or reject them (much of it is code-enforced by `geometry_gate`). Decide the 5 exit-integrity clauses together with P2. Add tie-breakers for the average-down vs escalation boundary and for the short-DTE stop-width conflict. | Knowledge tab "Audit proposals" / consolidate endpoint | Quality: removes contradictory guidance from every run; pending channel ≈ 11k → ~0 chars | S (human, about 1 hour) | Low | **TD** |
| **R6** | **Source budgets** (plan P4, built as ADV-05 and off): muggzone's irrelevant-review spend capped, e.g. `{"🌟｜muggzone-options": 3, "*": 5}` $/day. It never skips a message about a held, armed or proposed item. Also consider `observe`-only for `giul-heatseeker` (0 actionable in the window). | `techniques.tip.review_source_budgets` | ≈ $2-4/day now (muggzone ≈ 43% of spend) | Setting | Low with the relevance exemption | **TD** |
| **R7** | **Relevance-first note retrieval (K2).** In `notes_for_tip`, serve pinned notes first, then notes mentioning the tip's ticker, then newest. Pin one canonical profile note per source (P8 compaction produces it). | `backend/zargar/signals/service.py::notes_for_tip` (~l.995) | Quality: the durable lesson reaches the run instead of today's chatter. Fewer re-saved notes (KB growth down). | S | Low; keep the `limit`, change only the order | Fix (ordering) + **TD** (which note is canonical) |
| **R8** | **A note budget per source per day** instead of up to 2 per run: e.g. `save_note` on a source scope updates the day's single source note (append or supersede) rather than adding a new row. | `analyst.py` `save_note` + `SignalsService.add_tip_note` | KB growth -70-80% (from about 100-150 notes a day); smaller notes block, so less cache write | S | Low (supersede path is revisioned) | **TD** |
| **R9** | **Skip the appraisal when the vehicle is infeasible before any model call.** If 1 contract × premium × 100 exceeds the per-tip risk budget and no share alternative is allowed, record the refusal deterministically (`check_feasibility` already exists; today it runs *inside* the appraisal). | `techniques/tip/lifecycle.py` / `feasibility.py` call site before `analyst.appraise` | ≈ 25-30% of takes are infeasible (sharp-pencil F5), so ≈ $1/day, plus faster cards | S | Medium: a take that the analyst would re-express (spread, shares) is lost unless P1 shares-first handles it; ship after P1 | **TD** |
| **R10** | **Turn off the research capture** (`review_capture_context`, `frozen_capture_context`). The cheaper-model A/B it served is closed. | settings | ≈ 10 MB/day of DB growth (70 MB/week), trace reads faster; $0 model | Setting | None unless a new frozen study is planned | **TD** |
| **R11** | **1-hour TTL on the stable rulebook block** (and on system+tools, which must precede it). This targets the 13/72 reviews and 10/26 appraisals whose first call missed and re-wrote about 36k tokens. | `analyst.py` cache helpers (l.83-128) + `review_context.stable_first_blocks` | ≈ $1/day | S (TTL ordering rules: 1h markers must precede 5m ones) | Low | Fix (cost) |
| **R12** | **Stop writing `daily:*` digest notes nobody reads (K6)** or add `daily:<yesterday>` to the general allocation for morning runs. Keep the promoted nuggets. | `techniques/tip/digest.py` or `notes_for_tip` | ≈ $0.3/week, or quality if wired in | XS | None | **TD** |
| **R13** | **Price rule-audit and knowledge-cycle calls.** They persist no usage today, so the cost report is a lower bound. | `techniques/tip/rule_audit.py` → stamp `usage` like `run_agent_loop` | Measurement only | XS | None | Fix |

**Suggested order.** R1 and R2 first (defect and free saving, both XS). Then R3 and R6 after the 09-25 five-session
report. R5 as a one-hour human session this weekend. R4, R7 and R8 together with plan P7/P8 (rule ids and compaction).
R9 after P1 shares-first.

**Expected combined effect on cost:** R2+R3+R4+R6+R11 take about $6-8/day off $21, to **about $13-15 per weekday
(≈ $70/week)**. This lowers the trading break-even the sharp-pencil review set at about $105/week. The larger
money is still the trading levers P1-P3. R1, R5 and R7 are the **quality** items: today every run's knowledge
block is about 40% other rooms' newest chatter and unadjudicated proposals.

---

## 5. Reproduction notes

All figures come from read-only SQL over the runtime DB:
- cost = Σ over `tip_analyst_runs.opinion.usage` {in, out, cacheRead, cacheWrite} × `llm.rates[usage.model]` (batch ×0.5),
  plus `tip_llm_calls`. This matches `python -m zargar.tools.tip_llm_cost --since 2026-09-18 --until 2026-09-24`.
- header composition = the `reviewManifest.header` split at the markers `YOUR TRADING RULES`, the pending header,
  `SHARED NOTES` and `RECENT MESSAGES FROM THIS SOURCE`.
- review outcome = the tool calls in each intake run's trace (mutating: update_exit_plan / close_position /
  disarm_plan) plus `opinion.missedTip`.
- gate false negatives = `TipReviewGate` (decision=skip, not applied) joined to the run via `payload.intakeRunId`.
- misrouted scopes = `save_note` tool_call `args.scope` values containing `:`.
