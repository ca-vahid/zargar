# EM review — Delivery B design: source revisions and scenario records (2026-09-14)

Design only; nothing here is built. Answers FIX-07 (durable source revisions), FIX-08 (grounded scenario
extraction) and FIX-09 (alignment + source-informed candidate) from the reviewer packet, for review before
implementation. Module names below are proposals inside the EM namespace (`backend/zargar/technique/`).

## 1. Source revisions (FIX-07) - SUPERSEDED by the revision at the end of this file (2026-09-14 verdict)

> The schema and backfill wording in this section is kept as the original proposal only. Do NOT implement
> `first_usable_at` from `updated_at`, and do not put transcript/usability fields on the immutable revision -
> see "Revision after the reviewers' answers" below (three tables; availability is a fact of the artifact
> that produced it, else `unknown`).


Today `technique_method_notes` holds one row per Discord message id with `text`, `transcript`,
`extraction`, `board_check`, `status`; edits overwrite in place, the author is a display name, and a
crash between stages leaves the stage implicit in which columns are filled.

Proposed schema (additive; the existing table stays and becomes the "latest" view):

```
technique_source_revisions
  id (pk)             uuid
  note_id             fk technique_method_notes.id      -- the message identity (channel + message id)
  revision            int                               -- 1 = first receipt; +1 per edit/re-delivery/deletion
  author_id           str   (Discord user id; the API already receives authorId, store_message drops it)
  author_name         str
  channel_id / channel_name
  published_at        ts    (Discord message timestamp)
  received_at         ts    (gateway receipt)
  first_usable_at     ts    (when transcript/extraction completed - what "available at the open" means)
  kind                video | post | chart | edit | deletion
  text                str   (verbatim)
  attachments         json  [{id, url, sha256, mime, local_path}]
  transcript          str | null
  content_hash        sha256(text + attachment hashes)
  supersedes          fk technique_source_revisions.id | null

technique_source_jobs
  revision_id         fk
  stage               received | transcribed | extracted | board_checked | scenarios_built | done | failed
  attempts            int
  lease_owner / lease_until                              -- one worker at a time, recoverable on expiry
  next_due_at         ts
  error               str | null
```

Rules: a revision is immutable; an edit or re-delivery with a different `content_hash` creates revision n+1
with `supersedes`; identical re-delivery is a no-op (idempotent by hash). Scenarios reference a revision id,
so an edit marks dependent scenarios `stale_source` for review instead of mutating them. Startup and every
gateway delivery call `resume_unfinished()`: any job whose lease expired is picked up at its recorded stage,
never from the beginning (a half-done board keeps the rows it produced).

Migration: backfill one revision per existing note (`revision=1`, `content_hash` from stored text,
`first_usable_at` = the note's `updated_at` when extraction exists, else null), then switch the writers.
Uniqueness moves from `message_id` to `(note_id, revision)`. Backfill is a dry-run tool with a manifest,
same shape as the FIX-01 reconciliation.

## 2. Scenario records (FIX-08)

```
technique_source_scenarios
  id, revision_id
  symbol              str | null        confidence  float      (unresolved symbols stay null, with the raw token)
  purpose             new_entry | management | recap | context | refusal | illustration
  direction           long | short | two_sided | unknown          -- unknown authorizes neither side
  branches            json [{direction, condition, level, target, invalidation}]   -- explicit two-sided
  setup_family        break | reclaim | retest | continuation | bounce | reject | wedge | range | other
  sequence            json [ordered required events, e.g. "hold 265", "reclaim 266", "break 267"]
  entry_condition / level_or_zone / targets / invalidation
                      each {value, origin: source_stated | chart_observed | algorithm_derived | unknown, span}
  timeframe           str | null (source-stated chart tf, e.g. 1h, 2h)
  session / horizon   intraday | swing | unknown; earliest_usable_at; expires_at
  priority / caveats  json
  evidence            json [{kind: transcript | caption | chart, ref: revision_id + span/time, text}]
  normalization_confidence float
```

Extraction (`technique/scenarios.py`): one prompted-JSON pass over transcript + caption + chart attachments
together (the current extraction is transcript-only and drops short posts). Every field carries its origin;
the model is instructed that a stop it did not hear is `unknown`, and a direction it cannot ground is
`unknown`. Chart images are passed with their timestamp; a chart posted later than the transcript cannot
resolve the transcript's ambiguity (evidence time > scenario time is rejected by the validator in
`technique/source_evidence.py`).

Acceptance corpus (the packet's): Sep 2 AMZN two-sided -> `two_sided` with both branches; Sep 9 SPY retest ->
`purpose=new_entry, setup_family=retest, condition` kept; Sep 9 MSFT -> `direction=unknown`; Sep 10 MSFT puts
-> `purpose=management`; Sep 11 unnamed 376/369 -> `symbol=null`, geometry recorded, `not executable`; Sep 14
MRNA -> `timeframe=2h, horizon=swing|unknown`, stop origin `unknown`.

## 3. Alignment and the source-informed candidate (FIX-09)

`technique/scenario_alignment.py::align(scenario, plan) -> {status, reasons}` compares symbol, direction,
setup family, sequence, entry region (level within tolerance), targets, timeframe, session, horizon and
instrument feasibility. Statuses: `aligned`, `partial`, `different_scenario`, `source_ambiguous`,
`expired_or_completed`, `not_represented`. The board card shows the status and the reasons per row; "covered"
disappears as a label. A plan that is already armed / paused / replaced is reported as that state, not as a
new arm.

Source-informed candidate: `technique/plans.py::build_from_scenario(scenario, bars, thresholds)` produces a
plan with `origin = "scenario:<id>"`, keeps the source-stated level/targets where present, uses the existing
level detector only to supply what the source left `unknown` (stop, secondary targets) and labels those
`algorithm_derived`. It passes through the existing gates (R2, stop cap, windows) and records the reasons
when it fails them. It is a research/shadow origin: it mints runs and outcomes, never orders, until activation
is decided separately (a setting that does not exist yet and will not default on).

## 4. Measurement hook (toward FIX-10)

Every scenario gets a terminal disposition per session: `not_executable` (why), `candidate_failed_gates`
(which), `armed` (plan id), `fired`, `filled`, `no_touch`, `expired`. The daily funnel is a query over
scenarios, not over triggers, so ideas that never became triggers are counted.

## 5. Questions for the reviewers

1. Is a revision per Discord edit sufficient, or should the transcript re-run on every edit (cost)?
2. Should the source-informed candidate share the EM Practice book when activated, or get its own book like
   the other techniques (PLATFORM-RULES invariant 15 suggests its own)?
3. The two-sided scenario: one scenario row with branches, or two rows sharing a `pair_id`? The alignment
   logic is simpler with two rows; the source fidelity is better with one.


---

# Revision after the reviewers' answers (same day)

**Answers adopted.** (1) A revision per distinct accepted source state, including deletion/restoration and
`A -> B -> A` as a genuine third state; identical transport redelivery is a receipt/retry event, never a
revision; transcription is reused when the media hash and transcription configuration are unchanged;
extraction has its own processing version. (2) No new Practice book in Delivery B; candidates are order-free
research records; any later EM activation uses EM Practice with immutable origin attribution, common risk
limits and one position owner. (3) One parent opportunity with child branch rows (stable branch ids, own
conditions/lifecycle); the parent is reserved atomically before any future submission; unknown direction
creates no executable branch.

**Schema separation (edit 1 + the mutability point).** Three tables, not one:
- `technique_source_revisions` - IMMUTABLE observations only: identity, author id/name, `published_at`,
  `received_at`, kind, text, attachment hashes, `content_hash`, `supersedes`. No transcript, no usability.
- `technique_source_artifacts` - APPEND-ONLY derived artifacts: `revision_id`, `kind` (transcript | extraction |
  scenarios), `version`, `config_hash` (model/prompt/transcription config), `input_hash` (media or transcript
  hash), `completed_at`, payload. `first_usable_at` for a scenario is the `completed_at` of the artifact that
  produced it - a fact, never backfilled from `updated_at`; historical rows get `availability = unknown`.
- `technique_source_jobs` - MUTABLE progress: stage, attempts, `lease_owner`, `lease_until`, `fence_token`
  (edit 2: a worker commits only if its fence token still matches; an expired worker's writes are refused),
  per-item checkpoints (`board_progress` as a list of completed item keys), `outcome` (retryable | permanent |
  in_progress | done).

**Later evidence (edit 3).** A later chart or post never rewrites an earlier as-of artifact; it produces a new
scenario version with `first_usable_at` = its own availability, and the current-validity check runs before it
is used. The earlier "evidence-time ban" is replaced by this versioning.

**Order-free boundary (edit 4).** Scenario candidates carry `origin = scenario:*` and the runner refuses to
arm any run whose origin starts with `scenario:` (a hard check in `arm_plan`, `arm_today`, the ingest auto-arm,
restore and any retry path), independent of settings. The refusal is journaled. This stays until an
activation decision adds an explicit allow-list.

**Supersession fencing (edit 5).** For future activation only: final admission checks the scenario's
revision is still current; a superseded/deleted source cancels working entries and leaves managed positions
to the existing exit owner. In Delivery B it only marks records `stale_source`.

**Typed evidence and lifecycle (edit 6).** Evidence rows keep raw numeric fragments and spans, chart marker
roles and conflicts; `source_timeframe`, `confirmation_timeframe`, `exit_timeframe` and `holding_horizon`
are separate fields (2h alone does not imply swing). Scenario lifecycle: `received -> understood ->
candidate | not_executable -> armed -> fired -> filled -> exited`, plus `no_touch` only when observation
coverage of the session is complete, `expired`, `superseded`.

First implementation PR (proposed): the three tables + backfill dry-run tool + `resume_unfinished()` with
fencing, no extraction changes yet.

**Two implementation contracts for the first PR (2026-09-14 verdict):**
1. Source edit/event ordering is recorded (Discord edit timestamp + gateway sequence) and partial updates
   merge safely: an older or partial delivery never replaces a newer complete source state.
2. Source/job creation and output/checkpoint transitions are atomic where the database allows (one
   transaction for "artifact row + job checkpoint") and otherwise idempotent by output key: a crash between
   creating an output and checkpointing it is recovered by re-deriving the same key, never by duplicating.

---

# First PR - BUILT (2026-09-14, closure review GO; schema/diagnostic only)

Code: `backend/zargar/technique/source_revisions.py` (the ledger), models `TechniqueSourceRevision` /
`TechniqueSourceArtifact` / `TechniqueSourceJob` (additive tables; `db.create_all` adds them on the next boot),
`tools/em_source_backfill.py` (dry-run manifest + one-transaction `--apply`, idempotent, hash-checked),
`execution/origins.py::scenario_origin` + the refusal in `PlanRunner.arm` (order-free boundary), the ingest
service (`store_message` writes revision 1 WITH the note in one commit; new `store_revision` for edits/deletes;
`resume_unfinished` on every gateway delivery and worker poll), the API body (`kind`, `editedAt`, `gatewaySeq`,
`images: None` = absent; `GET /api/technique/ingest/revisions/{noteId}`), and the gateway forwards EM-channel
EDITS to EM's inbox as `kind=update` (the tips mirror path is untouched). Tests: `tests/test_em_source_revisions.py`
(10 cases, real Postgres, no engine/LLM/gateway).

The two implementation contracts, as built:
1. **Ordering + partial merge** (`record_delivery`): the source's `editedAt` orders deliveries, the gateway
   sequence breaks ties; an older delivery is recorded as `stale` and changes nothing; absent `text`/`images`
   (None) keep the accepted values. Identical redelivery = receipt. `A -> B -> A` = three revisions; delete and
   restore are revisions (`deleted` flag in the content hash).
2. **Atomic output + checkpoint** (`checkpoint`): artifact row + job checkpoint staged in ONE session, one
   commit; the artifact id IS the output key `(revision, kind, input_hash, config_hash)`, so recovery after a
   crash between output and checkpoint reuses the existing row. Leases carry a fence token; `resume_unfinished`
   re-leases expired jobs at their recorded stage under a new token and a stale worker's checkpoint raises
   `FenceMismatch` with nothing written.

Not in this PR (by the verdict): extraction changes, scenario records/alignment, any Practice book, candidate
orders, activation. `technique_method_notes` keeps showing the LATEST accepted text (a convenience view);
artifacts are never rewritten by a later revision. Backfill: `python -m zargar.tools.em_source_backfill`
(dry run) then `--apply <manifest>` - a human step, like FIX-01; historical artifacts get `availability:
unknown` (`completed_at` NULL), never a value derived from `updated_at`.

Limitations, stated: the gateway forwards edits but not deletions yet (Discord delete events are not
enqueued for EM; `kind=delete` is accepted by the API and the ledger); attachment identity is the URL set,
hashes arrive when bytes are fetched; the transcription/extraction workers do not yet write artifacts
through `checkpoint` (they still write the note columns) - wiring them is the next PR, with the scenario
extraction.
