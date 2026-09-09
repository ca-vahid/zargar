# Tips system audit — discussion packet for the Tips team

**Review date:** September 8, 2026 (Vancouver); inspection continued into September 9 UTC.
**Recommendation:** address correctness, intake continuity and evaluation quality before
changing trading thresholds. The system is receiving tips and producing useful decisions,
but several failure paths can hide missing work or teach the analyst the wrong lesson.

This is an independent system audit requested before the team's daily review, not a
review of a supplied team report. No method settings, rules, orders or runtime processes
were changed. Recommendations below are proposals for discussion.

## Evidence and version boundary

- Source checkout: `C:/Cursor/zargar-codex`, `codex/zargar-development`.
- Fetched origin and merged `origin/main` (`91e115e`, v0.7.14) into this branch as
  `0fbda1f`. A direct fast-forward was impossible because the branch had local commits.
  Existing Team2 edits and the Tips scratchpad were preserved. The newly published
  change was Cartel-related; no newer Tips commit was found in the fetched update.
- Running app: `/api/health` and the signed-in browser both showed **v0.7.13**.
  These source findings must be checked against the team's actual deployed commit
  before attributing every historical incident to this checkout.
- Read-only browser inspection: Tips list, Analyst history, selected run details,
  Knowledge and Sources in the **Practice** workspace. No action buttons, settings
  saves, manual processing, trades or new LLM runs were triggered.
- Eight offline probes exercised existing functions with fake I/O. No database,
  market API, Discord API or paid model calls were made by the probes. See
  [reproduction script](2026-09-08-probes.py).
- Evidence labels below distinguish **observed runtime**, **reproduced**, and
  **code inspection**. There is no full-session database export or provider usage
  export, so this report does not assert an overall capture rate, token cost,
  model accuracy, or profitability improvement.

## What is working and worth retaining

The pipeline has a substantial foundation: allowlisted Discord channels, a searchable
message mirror with local image support, text/image extraction, quote grounding,
separate handling for entry versus trim/close messages, an analyst with tool traces,
now/at-level choices, deterministic position-management policies, shadow comparisons,
retrospectives and scoped knowledge. Tips knowledge remains separate from EM knowledge.

The live UI showed **11 monitored channels**. The latest run list includes successful
appraisals and eight automatic retros dated September 8. RIVN covered-call commentary
was classified as skip, and many watchlist/performance messages did not become takes.
Those observations establish useful processing, not independently verified judgment
accuracy. Preserve the existing risk gate, exit protections and experimental isolation.

## What the runtime sample actually shows

The Analyst UI fetches the latest **200** runs and hides experiments by default
(`frontend/src/pages/InboxPage.tsx:2156`). At inspection, **172 displayed rows** were
dated September 8 in the browser's local time. This is a bounded UI sample.

| Kind | September 8 rows in sample | Observation |
| --- | ---: | --- |
| Intake | 133 | Four still labeled running; many similar pairs need message-ID reconciliation |
| Appraisal | 30 | 4 take, 23 skip, 2 failed, 1 running |
| Retro | 8 | Automatic reviews had already run; distinct from the team's human review |
| Digest | 1 | Failed |

Appraisal completion in this sample is 27/30 (90%). That is neither a success rate
for trade selection nor a provider-call success rate. Intake rows may contain multiple
LLM calls, and related rows may represent one message. No watch verdict appeared among
these 30 appraisals; this alone is not evidence the model is overly restrictive.

Selected runtime evidence (times as displayed in the Vancouver browser):

| Record | Observed behavior |
| --- | --- |
| ORCL `dd912e72`, parent intake `4860d51f` | 09:40:38–09:41:30, about 52 seconds. Four tools returned; JSON repair attempted; ended with `no JSON object in analyst reply`. Model displayed: `claude-opus-5`; 12 notes and 31 rules supplied. |
| CRWV `e70322e5`, parent `29121cdf` | 07:59:03–07:59:53, about 50 seconds. Four tools returned; recorded answer ends partway through a JSON string, repair fails. 12 notes and 29 rules supplied. |
| Digest `e568d1b0` | 14:16:46–14:17:16, about 30 seconds. 590 trading-floor messages selected; failed with empty-input JSON validation error. Actual provider stop reason is not exposed. |
| APLD appraisal and intake at 08:05; intake at 08:33; two intakes at 11:23 | Still labeled running during evening inspection. The UI also showed a September 7 intake still running. These labels do not establish that requests remain active. |

## Findings, in priority order

### 1. P1 — Option premium and underlying prices can be compared as the same unit

**Observed runtime + reproduced.** The September 8 CRWV tip (`d07ee4fe`) displayed
premium entry 1.40, target 1.75 and stop 0.90 for the 105C. Its failed analyst trace
explicitly used the verifier's `not_past_target` failure to conclude the premium had
already passed the first target. But `verify_signal` reads the **underlying** quote
and compares it directly with `target_price`/`target_prices`.

The probe reproduces `not_past_target` failing on **98.87 versus 1.75** without
consulting the option quote. The schema distinguishes premium from underlying entry,
but target/stop fields do not carry a price domain. This is not evidence that buying
CRWV would have been correct; it is evidence that the stated rejection reason can be
invalid and then contaminate LLM reasoning and future lessons.

**Discuss:** explicit underlying versus premium fields (or mandatory units), preserve
those units from extraction to verification, planning, exits and replay. Ambiguous
prices should stay unresolved. Acceptance cases: premium target/stop, stock target/stop,
mixed units, calls and puts, missing option quote. No policy tuning should compensate
for this defect.

**Code:** `signals/schemas.py:55-100`; `signals/verification.py:90-136`;
`techniques/tip/analyst.py` appraisal header and tool results.

### 2. P1 — Discord receiving waits on downstream processing, with incomplete gap recovery

**Code inspection + two reproduced boundary failures.** `_session` awaits each
`_on_frame`, which awaits `_on_message`, mirror delivery and ultimately a manual-ingest
HTTP request with a **200-second** timeout. That work shares the receive path with
heartbeat ACK handling. A slow message can delay later alerts and ACK processing;
the independent heartbeat task can then conclude the connection is unacknowledged.

Reconnect identifies afresh; there is no session-resume implementation. The watch
fingerprint is retained across reconnects, and onboarding backfills old history rather
than a durable forward gap. Mirror POST failures are suppressed and non-success HTTP
statuses are not checked. A log of matching messages is useful evidence, but no
automated durable delivery retry from that log was found.

In addition, the live intake body carries text/source/subject/first image, **not the
Discord message ID or authoritative posting time**. Semantic signal dedupe happens
after extraction and does not prevent repeated extraction costs. Similar paired runs
were visible, but whether each pair is duplicate delivery, two ingestion paths, or
deliberate reprocessing remains unverified.

`MESSAGE_UPDATE` is ignored, and the mirror skips existing IDs rather than revising
them. Corrected strikes, stops or entry text can therefore remain stale even if an
edited record reaches the store.

**Discuss:** a durable message envelope keyed by Discord identity/revision; immediate
persist-and-enqueue; bounded workers; per-channel ordering for lifecycle updates;
forward cursors and reconnect gap checks; acknowledgments and retry state; idempotent
downstream actions. Handle edits as revisions with an explicit re-review policy.
Validate with slow-processing, disconnect, duplicate, edit and app-unavailable cases.
Do not blindly replay old entries into execution.

**Code:** `tools/discord_gateway.py::_session`, `_heartbeat`, `_on_frame`, `_mirror`,
`_backfill_watched`, `_watch_loop`, `_ingest_message`; `signals/service.py:569-606`.

### 3. P1 — Extraction failures can masquerade as successful “no signal” reads

**Reproduced.** After two malformed responses, `Extractor.extract()` returns
`ExtractionResult(signals=[], source_type="other")`. Refusal also becomes an empty
result. `process_content` cannot distinguish those from a genuinely non-trading
message and can mark the content extracted. The recovery sweep retries content with
status `error`, so the malformed-output path evades that recovery.

**Discuss:** typed outcomes for no-signal, refused, invalid-output, timeout and provider
error; persist failure metadata and retry eligibility. Separate those rates from
correctly ignored commentary. Prove malformed extraction remains visible and does not
vanish into the non-tradable denominator.

**Code:** `signals/extraction.py:139-157`; `signals/service.py::process_content`,
`recovery_sweep`.

### 4. P1 — LLM repair loses its evidence; stalled runs and side effects need reconciliation

**Observed runtime + reproduced repair-loop behavior.** ORCL and CRWV both failed
after tool use and a repair attempt. The current repair starts a new conversation
from the original header, leaving out the first attempt's tool results and partial
answer, while reusing its `tools_used` list with `max_tools=2`. If four tools were
already used and the model requests another, the loop returns text without servicing
the request. An empty text block produces another parse failure. The reproduction
establishes this failure path; it does not establish the unseen content of those
particular runtime repair responses.

Calls request 2,000 output tokens, and the loop does not record provider usage or
stop reason. CRWV's visible partial JSON is consistent with truncation, but its exact
cause cannot be proven from the trace. Raising the limit blindly would not fix repair
context loss. Review, digest and audit paths do not share one consistent repair policy.

Several old runs remain labeled running. `CancelledError` is not caught by the usual
`except Exception` handlers, and no Tips-run startup reconciliation was found. Also,
tools can save notes, update exits, close positions or disarm plans **before** final
JSON validation. A failed run is not necessarily free of side effects, despite the UI
text “nothing was asked or ordered.” This is an architectural concern, not a claim that
the sampled failed runs placed an order.

**Discuss:** repair the same transcript, force a final structured response at the tool
budget, retain tool evidence, record stop reasons and per-attempt usage. Reconcile
interrupted runs to an explicit terminal state using persisted action receipts; never
blindly rerun management actions. Render aftermath from actual receipts. Add tests for
max-token termination, empty final text, exhausted tools, cancellation and post-tool
failure.

**Code:** `techniques/tip/analyst.py:810-877, 1007-1035, 1117-1240`;
`frontend/src/pages/InboxPage.tsx:1643`.

### 5. P1 — Nightly retros can stop reaching newer closed positions

**Reproduced; runtime backlog size unknown.** `run_tip_retros` selects the oldest
50 closed positions and only then removes `retro-done` records in Python. When those
50 have all been reviewed, position 51 is never selected. The response can still say
`pending: 0`. Unfilled retros similarly limit to 100 before excluding reviewed rows,
although that path has a rolling 14-day window.

**Discuss:** filter eligibility before limiting, use a stable cursor, count the full
eligible backlog and expose oldest-unreviewed age. Acceptance: 50 reviewed positions
plus one new position must review the new position; failures must retry without
starving later records. Separate Practice/live/shadow/archived cohorts explicitly.

**Code:** `techniques/tip/retro.py:158-189, 302-334`.

### 6. P2 — The analyst cannot inspect every named contract or reconstruct price structure

**Reproduced chain limitation + code inspection.** `get_chain` returns nine strikes
nearest spot. `_compact_chain` has a `want` argument, but the tool calls it without
that argument and the tool schema offers no strike selection. A far-out-of-the-money
contract explicitly named in a tip may be absent from the evidence the analyst sees.
That absence must not be treated as proof of illiquidity or no contract.

`get_bars` compresses history to the last 24 closes plus overall high/low/count. It
omits per-bar times, OHLC and volume, while the analyst is asked to reason about
structure, ATR/noise, stops and catalyst timing. The quote result omits source timestamp
and source label even though the platform tracks quote provenance.

**Discuss:** exact-contract lookup/repricing; labeled quote age/source; compact but
timestamped OHLCV or deterministic structure/ATR facts; data-completeness flags. Test
the named-contract path and ensure no inference of current executable price from
delayed chain spot. Keep payload budgets explicit.

**Code:** `techniques/tip/analyst.py::_compact_bars`, `_compact_chain`, `TOOLS`,
`_run_tool` branches `get_quote`, `get_bars`, `get_chain`.

### 7. P2 — Knowledge currently rewards recency and repeated exposure more than evidence quality

**Observed runtime + code inspection.** The Knowledge page showed a capped 300-note
result: 210 source notes, 64 ticker notes, 21 rules and one general note, plus other
scopes. These are displayed-subset counts, not the complete database inventory.
Morning appraisals recorded 29–31 injected rules. The page cannot be assumed to show
all rules because it filters categories after fetching a shared 300-row limit.

Default context is the newest 12 matching general/source/ticker/signal notes, with no
per-scope allocation or relevance ranking. Every supplied note is counted as “cited”
and has its TTL refreshed when the appraisal completes, regardless of whether the
model used it. This can keep frequently injected advice alive without validating it.
Rules are capped at 50 and injected as text without a full versioned rule snapshot
in the run trace (the start step records the count).

Rule notes become active immediately, including from ordinary intake/appraisal tool
calls. Family supersession depends on prose formatting; prefixes like “extends” and
“refines” intentionally evade matching. Live notes still included long variations of
the adoption-geometry lesson. One September 8 GOOGL lesson also advocated full lane
size after passing checks, based on narrow evidence. That is a tuning candidate,
not a demonstrated sizing improvement. Human-review flags do not exclude a rule from
`tip_notes`, and the prompt does not label flagged conflicts when injecting them.

**Discuss:** separate observations, hypotheses and active rules; structured family ID,
evidence IDs, applicable conditions, version and promotion state; concise active policy
with supporting cases stored separately. Distinguish supplied/used/helpful metrics;
reserve context space for source profile, ticker thesis and open-position context.
Make disputed rules explicit and snapshot exactly what each run received. Preserve
the analyst's independent judgment while making evidence-based promotion reviewable.

**Code:** `signals/service.py:176-193, 224-288, 314-333, 358-371`;
`techniques/tip/analyst.py:725-736, 931-945, 1061-1067`;
`techniques/tip/rule_audit.py::run_rule_audit`;
`frontend/src/pages/InboxPage.tsx:1949`.

### 8. P2 — Context digests have coverage, delivery and recovery gaps

**Observed runtime + reproduced retrieval gap + code inspection.** Today's 590-message
digest failed. `_prepare` selects the first 600 messages; `_run` truncates the transcript
at 60,000 characters without a coverage manifest. Later messages and image-only
content can be excluded. The live gateway supplies only the first image to extraction;
other images can be found via the mirror, but are not guaranteed to be considered.

Daily summaries live under `daily:<date>`, but `notes_for_tip` never retrieves that
scope. Only promoted ticker/source nuggets enter the normal knowledge context; the
summary does not automatically become a market-context briefing. This may be intentional,
but the distinction needs to be visible. Nightly digest orchestration catches a JSON
validation failure as `ValueError`, the same branch labeled a quiet-channel skip;
failed runs are persisted, but there is no digest retry queue in this path.

**Discuss:** chunked chronological summaries with counts and covered intervals; explicit
image coverage; idempotent channel/day/revision results; visible failure and retry state.
Choose intentionally whether a small recent context digest belongs in appraisals.
Keep chat commentary from becoming trade permission.

**Code:** `techniques/tip/digest.py:63-80, 95-139, 193-210`;
`signals/service.py::notes_for_tip`; `tools/discord_gateway.py::_ingest_message`.

### 9. P2 — Historical experiments still have hindsight channels

**Code inspection; no new experiment run.** Historical appraisals still load current
notes and rules. Search fetches the newest limited messages and only then filters by
the historical timestamp; newer messages can consume the limit and hide older valid
evidence. Some tools still return current market/position information, with a prompt
warning rather than complete event-time isolation. Experimental note writes are
quarantined, which is valuable, but output isolation does not make evaluation
historically unbiased.

**Discuss:** distinguish retrospective educational review from a valid historical
decision test. For the latter, use as-of filtering in the query before LIMIT, frozen
knowledge/configuration, event-time market data and an explicit tool-availability
matrix. Do not use contaminated experiments to justify next-day thresholds.

**Code:** `techniques/tip/analyst.py:464-482, 889-891, 931-960`;
`_run_tool` experiment handling and `save_note` quarantine.

### 10. P2 — Source scorecards are not yet a clean measure of the method's edge

**Observed runtime + code inspection.** The Sources page showed nine named Tips sources
explicitly set to auto, with a label that this bypasses the earned-auto bar. Preserve
that configured user choice; do not describe these accounts as having earned trust
solely from their scorecards. The separate scorecard “cleared/shadow” and tip-time
labels can communicate a different criterion from the operative auto override.

The display mixes monetary shadow-book P&L with replay-based R outcomes: for example,
ab showed positive armed-book dollars but negative E[R], and eva showed the reverse.
Those are not necessarily calculation errors, but reviewers need the cohort, vehicle,
exposure, pricing and horizon behind each statistic. They are not interchangeable.
Large immediate-book marks do not establish realizable missed profits.

`source_trust` combines closed positions with aged open shadow marks; the latter uses
earliest BUY order creation time for a symbol rather than the current holding episode's
actual first execution. Re-entry after an old holding can qualify as aged immediately.
The queried closed-position cohort is not explicitly filtered by portfolio kind in
that function. Audit which books and archived history contribute before interpreting it.

**Discuss:** report executed results, marked research books and replay results separately;
deduplicate idea/holding episodes; use actual fill timestamps and quote freshness;
version the policy and reset/cohort boundary. Compare now versus at-level with matching
opportunities, sizes and costs. This is measurement work, not a recommendation to
change a source's mode or increase allocation.

**Code:** `signals/service.py::source_trust`, `source_scorecards`;
`frontend/src/pages/InboxPage.tsx` source-policy and scorecard UI.

## Suggested team sequence and acceptance evidence

| Order | Discussion/work item | Evidence needed before calling it resolved |
| --- | --- | --- |
| 1 | Price units and exact-contract evidence | CRWV-shaped and mirrored put cases verify the correct asset's prices; analyst sees the named contract |
| 2 | Durable Discord intake and explicit extraction failures | A controlled message set survives disconnects, edits, duplicate delivery and invalid JSON with one explainable disposition per revision |
| 3 | LLM repair and run reconciliation | Saved transcripts demonstrate successful repair with retained evidence; interrupted runs terminate honestly; action receipts prevent repeated effects |
| 4 | Review backlog and digest reliability | Backlog count/age is correct; position 51 is processed; long channel-days disclose complete or partial coverage |
| 5 | Knowledge governance and clean evaluation | Rule versions/evidence and exact injected context are recoverable; historical tests have a documented event-time boundary |
| 6 | Trading-method experiments | Baseline-versus-variant comparison on independent sessions, matched exposure/costs, explicit downside and rollback conditions |

Before choosing a cheaper or stronger model, collect per-stage request counts,
input/output/cache tokens, latency percentiles, stop reasons, retries, invalid-output
rates and tool failures. Join these to message IDs, decision age and final disposition.
The current traces let us inspect individual failures but do not establish total cost
or whether model choice is the bottleneck. Consider routing/rule-based filtering only
after a labeled sample distinguishes entry calls, lifecycle updates, watchlists,
recaps, images and chatter; measure missed actionable updates as well as saved calls.

## Handoff

- [x] Updated local branch with published main, preserving existing work.
- [x] Inspected intake, extraction, verification, analyst tools/retries, knowledge,
  digests, retros, source scoring and relevant UI behavior.
- [x] Read current signed-in runtime evidence; counted the bounded visible sample.
- [x] Reproduced eight shortcomings offline with existing functions and fake I/O.
- [x] Prepared this discussion packet; no fixes or tuning applied.
- [ ] Team confirms deployed commit and reconciles raw message IDs with repeated runs.
- [ ] Full session/provider metrics establish capture rate, latency distribution and cost.
- [ ] Team selects changes and validation criteria; implementation is separate work.

Reproduce locally from the repository root:

```powershell
& backend/.venv/Scripts/python.exe docs/techniques/tip/reviews/2026-09-08-probes.py
```

The probes assert the current shortcomings to make the review reproducible; after a
fix, replace them with proper acceptance tests expecting the corrected behavior. No
claim is made that the full application test suite passed during this documentation audit.
