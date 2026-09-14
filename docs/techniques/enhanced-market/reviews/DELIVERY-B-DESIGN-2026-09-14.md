# EM review — Delivery B design: source revisions and scenario records (2026-09-14)

Design only; nothing here is built. Answers FIX-07 (durable source revisions), FIX-08 (grounded scenario
extraction) and FIX-09 (alignment + source-informed candidate) from the reviewer packet, for review before
implementation. Module names below are proposals inside the EM namespace (`backend/zargar/technique/`).

## 1. Source revisions (FIX-07)

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
