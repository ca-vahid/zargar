# Known-work completion packet (KFIN-01..10) — development response

Packet: `C:/Cursor/zargar-codex/docs/techniques/tip/reviews/2026-09-14-known-work-completion-packet.md`
(baseline main `561a859`, live v0.7.77). Work split across branches; each merged only after its
own suites and the integrated checks; deployed under the existing gates. Practice scope, the
approved risk budgets (`risk_pct` 1%, `risk_budget_per_tip` 0) and propose-only maintenance are
unchanged.

## KFIN-05 — manifest / rollback safeguards (this desk, branch `claude/kfin-05-10`)

`techniques/tip/consolidation.py` rewritten around ONE canonical payload hash
(`payload_hash`) shared by the client tool (`tools/tip_consolidation.py`) and the server:
every release carries the reviewed revision, every batch (merge or expire) its id, scope,
sorted sources, expected revisions and the sha256 of its exact output text, every evidence
record its scope, source id + revision and content sha. The server recomputes the hash from
the payload it receives — a changed text under the same claimed hash is refused before any
write. All reviewed revisions (including the dispute releases) are validated before ANY
mutation; a durable wrapper receipt (`tip_knowledge_batches` id `consolidation:<hash>`) records
progress step by step and answers an identical replay idempotently even after the sources
were superseded; a different payload under an already-applied batch id is refused (the batch
receipt carries the wrapper identity; pre-KFIN receipts are matched on their recorded
sources + output text). Evidence identity = source id + revision + content hash in the note
marker. Rollback guards come from the ACTUAL receipt transitions (`rollback_plan`: revision at
supersede, new rule id, release from→to, evidence ids), never "+1 per source". The wrapper
also applies reviewed REJECTIONS (expire batches) — used for the three quarantined promotions
(`--reject-proposals`, manifest in `2026-09-14-policy-proposal-rejection/`).

Tests: `tests/test_tip_knowledge.py::test_consolidation_payload_integrity_kfin05` (changed text
under the same hash, stale revision during resolution, changed evidence revision, different
payload under an applied batch id → refused with nothing written; identical replay idempotent;
receipt + rollback plan; expire batch) and the updated
`test_reviewed_consolidation_applies_through_audited_paths`.

## KFIN-10 — historical research with an honest disposition (this desk)

`tools/tip_late_evidence.py` reproduces the reviewer's cohort (33 late messages → 9 candidate
messages → 10 option branches + 1 share branch) from the live DB and attempts retrieval through
the already-authorized provider (Alpaca market data, the keys `research/optiontrades.py` uses):

| Evidence | Result |
|---|---|
| Option trade prints (±5 / +60 min around the post) | retrieved for all 10 contracts: 10,768 prints with exchange and condition codes |
| Option 1-minute bars (13:30–20:00 UTC) | retrieved for all 10: 2,429 bars |
| Contemporaneous NBBO (bid/ask/sizes) | **UNAVAILABLE** — `/v1beta1/options/quotes` answers HTTP 404 under this entitlement; recorded per case |
| MRNA shares | descriptive underlying path from local exchange bars only (the stated "risk at the 8D" names no indicator/trigger/fill policy) |

Every retrieval is persisted in the runtime table `historical_evidence` (provider, kind, symbol,
signal/message id, window, status, reason, record count, first/last timestamp, HTTP status,
request URL without credentials, raw records) and summarised in
`2026-09-14-late-evidence/disposition.md` + `evidence.json`. Disposition per option case:
prints and bars exist with provenance; because no executable quote exists at the alert, no
fill, spread, slippage or missed-profit figure is derived. Prospective sampling of the full
eligible cohort (skips and blocked candidates included) is built under KFIN-09.

**Three unproven truncated notes** (`aac9ee3e…`, `b3d7a110…` in `experiment:b1`, `1d7d118a…` in
`experiment:b2`, all 2,000-char cuts by the batch-review writer): no run trace holds the full
text and no authoritative original exists in the mirror; disposition = retain the original
truncated text at revision 1 with the provenance recorded as unresolved (no restoration, no
tombstone). They are experiment-scope records and are never injected.

**Three quarantined promotions** (`e02fbae2…`, `e7a30cb4…`, `2c8ed73d…`): closed through an
explicit reviewed rejection, not by clearing `needs_human` — released at their reviewed revision,
expired in one batch with the stated reason, and preserved verbatim as
`evidence:policy-proposals` records with the reviewer's rationale. Applied after the deploy
through the hardened wrapper; manifest hash and receipt recorded below.

## Per-tag results (all merged into main; integrated checks below)

| Tag | Branch / PR | Merge commit | Own checks (agent report) |
|---|---|---|---|
| KFIN-01/02 | `claude/kfin-01-02` PR #116 (head `f2e8b37`) | `42f054c` | `test_tip_retro_digest_accounting.py` 15, `test_tip_audit_chunks.py` 7, reviewer's `test_first_audit_request_honors_output_ceiling` pass; kb/knowledge suites 17 + 15 + 20 + 2 green |
| KFIN-03/04 | `claude/kfin-03-04` PR #118 (head `180eb12` + merge `10b64fe`) | `5fc2852` | `test_delivery_health.py` 6, reviewer's two-consumer check pass, `test_ops_tip_run_liveness.py`+restart 3, `test_ops_restart.py` 3, `test_deployment_lock.py` 9 (PowerShell 5.1), packet group 28 |
| KFIN-05/10 | `claude/kfin-05-10` PR #114 (head `186c423`) | `ddf9637` | `test_tip_knowledge.py` consolidation + kfin05 integrity 2, `test_knowledge_governance.py` 7; late-evidence tool run: 10 contracts, 10,768 prints, 2,429 bars, NBBO 404 |
| KFIN-06 | `claude/kfin-06-suite-failures` PR #115 (head `b48c73d`) | `6a9d25c` | the 8 failures → 29 passed grouped (twice); flow_scan 20, gateway 13, cartel trio 26, sim/engine 20; production code untouched |
| KFIN-07 | `claude/kfin-07-multi-image` PR #119 (head `a2ddfc5`, release 0.7.79) | `e4290e7` | `test_tip_multi_image_intake.py` 15, grounding+signals 30, gateway envelope trio 23, intake union 59 |
| KFIN-08 | `claude/kfin-08-mk-shadow` PR #120 (head `d81d1fc`) | `a670457` | `test_tip_ownbook.py` 30 (18 labeled cases), ownbook+separation+signals 60; `mk_ownbook_mode=off` by default |
| KFIN-09 | `claude/kfin-09-experiments` PR #117 (head `447bc90`) | `e770ade` | `test_tip_kfin09_experiments.py` 6 (isolation, denominator, missing data, reproducibility), separation 3, knowledge 9, experiment 5, analyst loop 4; all knobs off |

Pre-existing host-load flakes reported by two agents and reproduced identically on a clean
main: `test_api_and_pipeline.py::test_take_fill_adopts_position_under_analyst_exits`,
`::test_spread_tip_proposes_and_opens_defined_risk`, `::test_aged_limit_improves_to_live_ask_on_approval`
(sim option-fill timing under load), `test_position_chaos.py::test_failed_exit_watchdog_retries_then_alerts`
(grouped-run only) and `test_technique_arming.py::test_auto_options_one_contract_lifecycle` (EM's).
None is a KFIN regression; they are listed here rather than hidden.

## Integrated checks on final main (this desk, one pytest at a time, own DB)

| Slice | Files | Result |
|---|---|---|
| 1 (on `e4290e7`) | the 6 EOD regression files, completion boundaries, delivery_health, deployment_lock, ops_tip_run_liveness, audit_chunks, retro_digest_accounting, kfin09_experiments | 60 passed |
| 2 (on `a670457`) | tip_ownbook, tip_multi_image_intake, signals_tip, platform_separation, tip_caption_grounding_review | 78 passed |
| 3 (on `a670457`) | tip_integrity, tip_geometry_wiring, tip_activation, tip_knowledge, knowledge_governance, completion boundaries, audit_chunks, retro_digest_accounting, kfin09, delivery_health, ops liveness, eod restart | 86 passed, 1 failed under host load (`test_retro_timeout_keeps_paid_calls_and_receipts`; 15/15 on rerun of its file) |

Effective settings after deploy: Practice only, `geometry_gate=enforce`, `entry_pause_mode=integrity`,
`risk_pct` 1.0, `risk_budget_per_tip` 0, `knowledge_apply_enabled` false, `mk_ownbook_mode` off,
`entry_cohort_enabled` false, `frozen_capture_context` false, `allow_live_auto` false.

## Deployed and applied

- **Live:** v0.7.80, build `3b31f31` — the Team2 desk's 23:35 ET restart carried every KFIN merge
  (the running checkout contains `a670457`); no additional restart. Verified on the live app:
  `/api/ops/delivery-health` and the `delivery` block in `/api/health`, `/api/tip/intake/liveness`
  live, `/api/tip/ownbook/MK-alpha-trades` (mode off, not enrolled), readiness `tipRuns` /
  `tipRunsStale` / `tipRunsReconciled` all empty, 0 open incidents, gates enforce/integrity,
  every new knob at its inert default.
- **Reviewed rejection applied** (23:42 ET) through the hardened wrapper on the live app: manifest
  `9e12f30ac31f4014bf7c556ecfa2acb1a9bd0d574cb97ef21454c99dfe0be766`, receipt
  `consolidation:9e12f30a…` status applied; `e02fbae2`, `e7a30cb4`, `2c8ed73d` released at their
  reviewed revision 2 (→3), expired in batch `rejection-policy-proposals-2026-09-14` at revision 3
  (now revision 4, `superseded_by expired:consolid…`), preserved verbatim with the reviewer's
  rationale as `evidence:policy-proposals` records `54216f58`, `2ea6747a`, `2bbed243`; rollback plan
  (9 steps) on the receipt. Live rulebook: 37 rules.
- Tool follow-up: PR #123 (module-level `subprocess` import on the `--reject-proposals --apply`
  path; the apply above was posted from the planned manifest file).

## Review follow-ups (2026-09-15, branch `claude/kfin-followups`, PR #127, release 0.7.83)

Commits: `45b0235` (the three fixes + `tests/test_kfin_followups.py`), `6e59f81` (merge of
`origin/main` after the other desk's 0.7.82 took the number), `f9b9180` (renumber to 0.7.83);
merge commit on main `c5bb01b`; running checkout `d95ab68`. Live since 00:21 ET (build
`d95ab683…`, restart through the `ZargarRestart` task after `restart-check safe=true`,
`techniqueRunning=0`; 0 open incidents, gates enforce/integrity, Practice, `allow_live_auto` off).

| # | Item | What changed | Proof |
|---|---|---|---|
| 1 | Consolidation retry safety | `consolidation.py`: the dispute release (revision snapshot + `needs_human=False`) and the wrapper's progress (`rec.applied`) commit in ONE transaction, row-locked; the `TipRuleAudited` notification comes after the commit and is best-effort (logged, never fatal). Validation accepts a row the same manifest already released (revision == reviewed + 1 and the latest snapshot reason is `resolve`) as `recovered`; any other move past the reviewed revision is still refused ("not disputed"). | `test_release_commits_with_progress_and_retries_after_a_failed_notification` (journal raises once → release committed, receipt applied, identical retry `replay: true`), `test_release_without_saved_progress_is_recognised_on_retry` (`recovered: true`; a row moved twice by someone else refused) |
| 2 | Delayed-sample recovery | `cohort.recovery_loop` (first pass 30 s after boot, then every 60 s while `entry_cohort_enabled`) calls `sample_due`; wired in `attach_signal_layer` as the engine task `tip-cohort-recovery`. A sample past its grace is `missed` with the gap recorded, never back-labelled. | `test_delayed_samples_are_recovered_after_a_restart` (2 pending rows → 1 sampled/1 missed; task present) |
| 3 | Attachment coverage in the UI | `_persist_attachments` stamps a coverage summary (id, n, status, chars, error — never the transcripts) on `extraction.attachments` of every signal of the content, and new signals are born with it; `InboxPage.tsx` `AttachmentsBlock` renders per-image chips (processed / failed / unreadable / skipped) and "Evidence from: caption, attachment n" from `grounding.quoteSources`. | `test_tip_multi_image_intake.py` 15 passed; frontend build green; block present in the deployed bundle |

### Item 4 — observation-only workflows started (00:26 ET, journaled `PATCH /api/settings`)

`techniques.tip.mk_ownbook_mode=observe`, `techniques.tip.mk_ownbook_sources=["MK-alpha-trades"]`
(`GET /api/tip/ownbook/MK-alpha-trades` → enrolled, mode observe, book null, all counts 0),
`techniques.tip.entry_cohort_enabled=true`, `techniques.tip.frozen_capture_context=true`.
Nothing else moved: Practice, `risk_pct` 1.0, `risk_budget_per_tip` 0, `knowledge_apply_enabled`
false, `allow_live_auto` false, geometry enforce, integrity pause. No order path is touched by any
of the four keys (observe = classify + grade only; cohort = record + sample; frozen = stamp the
manifest on the run's start step). Practice promotion stays a separate reviewed verdict.

Initial reports at enablement:

- Entry cohort (`tip_entry_cohort report`): 0 eligible ideas, all sample counters 0 — the cohort
  starts with the 2026-09-15 session (`cohort-baseline.json` kept in the session scratchpad).
- Frozen capture: `tip_frozen capture --run ca5c37db…` (ZS, eva, 21:45 UTC) built bundle
  `fb-d74a31d83dc9162c` — manifest RECONSTRUCTED (the flag was off when the run happened),
  `core_only` unavailable (the rule snapshot predates the core flag). A stub replay
  (`--dry-run`) exercised both variants end to end without a provider call. **No paid replay was
  spent on a reconstructed bundle**: the first real paired report comes from a run captured
  AFTER the flag (tomorrow's session), which is the only capture that is verbatim.

### Item 5 — clean integrated verification (fresh DB, one pytest at a time)

Main `c5bb01b`, database `zargar_test_hubfix` dropped and recreated first, the other desks'
pytest processes polled to zero before every slice (slice 4's first run overlapped one and was
repeated clean), every slice under 9 minutes, no wider 590-second run:

| Slice | Files | Result |
|---|---|---|
| 1 | kfin_followups, tip_knowledge, knowledge_governance, tip_multi_image_intake | 35 passed (85 s) |
| 2 | tip_ownbook, signals_tip, platform_separation, tip_caption_grounding_review, tip_integrity, tip_geometry_wiring, tip_activation | 94 passed (170 s) |
| 3 | tip_audit_chunks, tip_retro_digest_accounting, tip_kfin09_experiments, delivery_health, ops_tip_run_liveness, ops_restart, tip_runner | 87 passed, **4 failed** in `test_tip_runner.py` (482 s) — see below |
| 3b | `test_tip_runner.py` alone after the fix below | 52 passed (194 s) |
| 4 | the six `test_tip_eod_20260914_*` files, tip_completion_boundaries | 15 passed (17 s) |

None of the reviewer's ten missing-row / FK failures reproduced on the fresh database.

**The four `test_tip_runner.py` failures are not from PR #127** — they reproduce identically on
`98bfdc3` (main before the PR), on `a670457` (main after KFIN-08) and with the test clock pinned
to 11:00 ET. Cause: the Options Cartel desk's `12491f2` (2026-09-14, "reconcile execution
evidence") made the sim venue refuse an OPTION fill on any quote without a venue identity and a
fresh source time (`SimExecutor.quote_rejection`: "Delayed quotes cannot price simulated fills",
"Option fill source identity or timestamp is unknown"). The runner tests' contract quotes carried
no source, and the chain overlay installed at `track()` stamps every incoming quote
`chain`/delayed — so the entries that used to fill off the DELAYED chain quote (a fantasy fill,
the very thing the rule closes) now sit `ACCEPTED` and the tests time out. The live runtime is
unaffected: the OPRA research feed installs an `opra` overlay with a fresh `source_ts`
(`options/service.py`), and 37 Practice option orders filled in the 36 hours before this check.
Fix (tests only, no production change): `_opt_quote` now does exactly what the OPRA feed does —
`set_overlay(..., source="opra", source_ts=now)` + `on_quote` — and the two end-to-end tests
publish a post-fire quote that is executable at the entry limit (ask 1.15 = the chain ask the
limit came from; the old 1.15-mid quote had ask 1.20 and never crossed).
