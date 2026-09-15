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

## Approval-card readiness + KF83-01..04 (2026-09-15, branch `claude/tips-approval-readiness`, release 0.7.85)

### Approval cards (the separate Tips work item)

`backend/zargar/approvals/readiness.py` (pure) + `proposals.py::assess / revalidate / _refuse_human`,
`POST /api/proposals/{id}/revalidate`, `approve` body `{half, expected, override}`, `InboxPage.tsx`
`ProposalCard` + `OverrideDialog`. Readiness is scoped to Tips cards (`techniqueId == "tip"`); a
card another technique creates keeps the old approval path unchanged
(`test_non_tip_proposals_keep_the_old_approval_path`; Cartel runtime + pipeline proposal tests
green). The ONE shared change in `approve()` is a tightening for every desk: the status flip is
row-locked and re-checks pending/expiry, so duplicate clicks or a click racing the TTL cannot
create a second order (PLATFORM-RULES entry).

| Requirement | Delivered |
|---|---|
| 1. actual blocking reason | typed blockers with a code, label, evidence detail, overridable flag and scope: `source_not_qualified` (auto-only, informational), `risk_budget_exceeded`, `quote_missing` / `quote_stale` / `quote_delayed`, `contract_metadata`, `risk_evidence_unavailable`, `plan_review`, `integrity_incident` / `integrity_unavailable`, `unsupported_instrument`, `no_enforced_plan`, `expired`. The risk plan now carries typed `evidence` problems; a refused automated attempt stamps the same typed state. |
| 2. opinion vs readiness | two pills: `analyst: take/watch/skip` (tooltip says it is an opinion) and `execution: ready / blocked / needs refresh / unverified / expired`; "Take" never implies the checks passed. |
| 3. final risk calculation | risk grid: purchase allocation limit (the $2,000 `sizing.budget`), approved planned-risk budget + source, est. risk per unit + basis, final qty x risk = planned risk (within / exceeds budget; "analyst asked N"), final stop (analyst's original), quote source/age/delayed, adjustments, estimate note with the theoretical maximum; the analyst's narrative is a separate labelled section. |
| 4. refresh and revalidate | `revalidate()`: `ensure_symbol` + `options.refresh_now`, limit re-priced DOWN only, geometry + sizing recomputed (`count_failures=False` - a refresh never feeds the incident counter), `integrity.admission`, source qualification; persisted (`context.readiness`, risk plan, a stale `reviewRequired`/`autoGate` cleared, the improved limit), journaled `ProposalRevalidated{orders:0}`; an expired card is marked expired. |
| 5. explicit, safe approval | `approve(via=app/telegram)` on a Tips card revalidates first; refused (no raise, `refused` + readiness) when blocked, when `expected` (the readiness fingerprint = final stop + admissible size + blocker set) differs, or when an incident opened between the validation and the order (approval reverted); override = `{checks:[codes], reason>=20 chars}` naming EVERY failed check, overridable ones only (`integrity_incident`, `risk_budget_exceeded`, `plan_review`, `unsupported_instrument`; never a missing/stale quote, missing evidence or expiry), journaled `ProposalOverridden` with the exposure; Telegram taps get the refusal text. |

Acceptance (`tests/test_proposal_readiness.py`, 7): AFRM-shape card shows the budget failure with
its per-unit risk, plain Approve and half size refused with zero orders; override named, reasoned,
journaled, submits the shown exposure (order qty = exposure qty); MRNA-shape card blocked by an
open incident, the label clears on revalidation after the incident is resolved, the approved order
carries the displayed size and stop with a limit never above the displayed one; a stale
fingerprint or a new incident between refresh and submission is refused; expired cards and two
concurrent clicks produce exactly one order; non-tip cards unchanged. Updated to the labeled
override path: `test_tip_geometry_wiring.py`, `test_tip_integrity.py` (case 4),
`test_tip_activation.py`.

### KF83-01..04 (review verdict `2026-09-15-kfin-followup-verdict.md`)

The reviewer's five-test file is adopted verbatim as `tests/test_kfin_followup_boundaries_review.py`
(5 passed; the four failing assertions unchanged). The older `test_kfin_final_review.py` was NOT
adopted: its first assertion requires the resolution-notification failure to raise, which the
newer control (`test_notification_failure_still_finishes_and_replays`) contradicts.

| Tag | Correction | Proof |
|---|---|---|
| KF83-01 | a release whose note is also expired/merged by a batch of the same payload is DEFERRED into that batch: `apply_knowledge_batch(releases={id: marker})` releases the dispute (snapshot with the marker), then expires, in ONE transaction; the row stays `needs_human` (non-operative) until the expiry commits; the batch receipt records `applied.released` | `test_failed_expiry_never_activates_rejected_proposal`, `test_rejection_keeps_the_rule_non_operative_until_the_expiry_commits` (failure injected at the expiry -> row disputed at the reviewed revision; retry completes one rejection; wrapper receipt deleted -> recovered from the batch receipt, no second mutation) |
| KF83-02 | ownership proof: a standalone release writes revision reason `resolve:c:<manifest16>`; recovery requires reviewed+1 AND that marker (deferred releases: the payload's own batch receipt with the marker); the reviewed revision is re-checked under the row lock before releasing | `test_unrelated_resolution_is_not_manifest_ownership`, `test_release_without_saved_progress_is_recognised_on_retry` (genuine retry recovered; a `flag_tip_notes` resolution at the same arithmetic refused, nothing expired) |
| KF83-03 | due time, observation time, lateness and eligibility are separate fields on the sample; `techniques.tip.entry_cohort_delay_tolerance_seconds` (60) declares the tolerance; later observations are `late` diagnostics excluded from the delay variant; the row is claimed under a row lock (timer vs recovery); catch-up bounded (200) with each observation on its own clock | `test_twelve_minute_recovery_is_not_three_minute_evidence`, `test_delayed_sample_timing_and_provenance_eligibility` |
| KF83-04 | `qualify_quote`: venue identity (`opra`/`ibkr`) for options, no `delayed`, no `chain`, a genuine source time (shares may use a labelled receipt-time basis; options may not), no future time, valid uncrossed bid/ask, the option venue session (mirroring the Practice venue policy `sim_option_sessions`); `evidence_ok` re-judges STORED records from their own fields in every variant | `test_delayed_chain_quote_is_not_eligible_execution_evidence`, the provenance cases in the follow-ups file; the KFIN-09 cap fixture now carries provenance |

Precision on the completion claims, as the reviewer asked: MK is in `observe` (classification and
grading instrumentation, `route=pipeline`), NOT a declared funded shadow cohort; the first verbatim
frozen paired comparison is still pending new captured evidence (a reconstructed bundle and a
dry-run replay do not close it). Knowledge consolidation applies and entry-study conclusions stay
on hold until this release is reviewed.

### Deployment status (02:05 ET 2026-09-15)

PR #131 merged (`995738e`). The running checkout is converged at `8be1d24` (main + the EM desk's
`c5dde09`, version 0.7.85, frontend built, check-release green). The `ZargarRestart` task at
01:59 ET passed the gate (restart-check safe, `techniqueRunning` 0) but could not stop the running
server: `Stop-Process python (156864): Access is denied` - the process was started at 21:28 PT by
the EM desk's elevated `deploy.ps1`; the Cartel desk's 22:39 PT attempt failed identically
(receipt `phase: failed`, "Administrator terminal required ... automatic retries paused"). **Live
stays v0.7.83 build `b7d8a57` until the process owner restarts** (the elevated terminal's
`scripts\stop.ps1`, or the EM desk's deploy path). No order was placed by any attempt. Practice
scope, risk budgets and live gates unchanged. The two pending cards (AFRM, MRNA; expire 11:30 ET)
will be revalidated through the new endpoint once 0.7.85 is live.

## AP85-01..03 (review verdict `2026-09-15-v085-approval-verdict.md`; release 0.7.86)

Reviewer file `test_v085_approval_boundaries_review.py` adopted verbatim (7 passed). Changes:
AP85-01 - blockers carry an `identity` (incident id parsed from the admission refusal); the
override records the identities it acknowledged; the final admission runs BEFORE any dispatch
(spreads included) and admits only when the check names exactly an acknowledged incident; an
unavailable integrity store (`integrity_unavailable`) always blocks. AP85-02 - the fingerprint
binds the complete displayed plan (final stop, admissible size, unit loss, planned risk, budget,
the approved maximum limit, symbol/secType/book, exit-plan hash, bracket, vehicle, each blocker's
code + identity/detail); `expected` is REQUIRED on every manual approval (app and Telegram:
the first Telegram tap only revalidates and shows the plan with confirm buttons carrying the
fingerprint); the approval's revalidation runs at the confirmed maximum limit and may only
improve the submitted limit; the pending->approved claim re-checks, under the row lock, that the
row's readiness fingerprint, bracket stop and limit still match the confirmed snapshot and the
order is built from that snapshot; `assess` never rewrites a claimed row. AP85-03 - half =
floor(displayed quantity / 2), minimum one, validated against the same displayed fingerprint;
the recorded exposure is the half exposure. Research follow-through: lateness is judged at the
actual sample time (after any awaited refresh), an in-process pre-fetch claim stops timer +
recovery double fetches, legacy records are re-judged at `sampledAt` (option session at capture,
missing age = never adequate). Tests written by the reviewer only, per the user's instruction
to ship fast; the existing suites were updated to pass the fingerprint.

## A86-01/02 (review verdict `2026-09-15-v086-final-verdict.md`; release 0.7.87, code only - no restart)

Reviewer file `test_v086_final_boundaries_review.py` adopted verbatim (3 passed) alongside the seven
AP85 checks. A86-01: `integrity.applicable_incidents` returns the COMPLETE applicable open set as
identity records (id, revision, evidence hash); the card's `integrity_incident` blocker carries that
set as its identity (bound by the fingerprint); an override must pass `acknowledged` identities
equal to what the card showed (a bare code acknowledges nothing); the final admission rebuilds the
set and requires exact equality; an unavailable store always refuses. A86-02: the claim recomputes
the canonical plan from the row's CURRENT exit policy (full hash), bracket, vehicle and risk plan
under the row lock and compares it with the confirmed fingerprint; the claimed payload is frozen as
`context.approvedPlan` (exit plan, vehicle, bracket, risk plan, quantity) and both the dispatch and
`adopt_when_filled` read it. Research: the sampling claim is held through finalization; the two
fixtures now carry the capture-time fields the capture path writes (positive assertions preserved).
Slice on this commit: reviewer A86 + AP85, readiness, KF83 follow-ups, KFIN-09, integrity,
activation - 46 passed. The manual approval hold stays until the review team confirms; live is
0.7.86 and no restart is requested for this change.

### v0.7.87 verdict follow-through (2026-09-15)

`_incident_set` no longer builds a partial identity when the structured read fails: the result is
`integrity_unavailable` (non-overridable) in both the card and the final admission. Adoption
(`adopt_when_filled`) consumes `approvedPlan.vehicle` and `approvedPlan.riskPlan` alongside the
frozen exit plan. Reviewer file `test_v087_confirmation_review.py` adopted verbatim.

## RKT exposure exception (profitability sweep 2026-09-15, reconciled 11:54 ET)

Sequence: BUY 148 @13.46 (Sep 11), trim SELL 59 @13.7373 (Sep 14), venue GTC stop SELL 148
@12.9374 (Sep 15 11:17 ET) - the resting stop was never resized after the trim, and after the
morning restarts the manager had forgotten the stop's order id, so the fill did not reach the
position (it stayed open at 89 while the ledger read -59). Reconciled: reduce-only BUY 59 in the
Tips Practice book (order `4bfd05bd`, filled 13.0926; the excess short cost -$9.16, RKT realized
-$39.31 in total, of which -$30.15 is the legitimate long episode), then the managed position
closed through the venue-clamped exit path with no order ("venue already flat"). Root-cause fix
merged (PLATFORM-RULES 2026-09-15 venue-stop entry), rides the next deploy.

## PROF-01 / PROF-02 (profitability sweep 2026-09-15; built the same day, code only)

**PROF-01 - risk budget before the verdict.** `techniques/tip/feasibility.py` (pure):
`unit_risk` (shares = |entry - stop|; options = the geometry gate's delta-linear estimator, premium
stop / full premium without an underlying stop), `feasibility` (units that fit the approved
planned-risk budget AND the purchase allocation; qty 0 = an honest no-trade), `share_alternative`
and `chain_alternatives` (RESEARCH comparisons at equal dollar risk - labelled, never a
substitution, never for a bearish thesis as shares). The analyst's system prompt now puts the
risk budget first and requires a `check_feasibility` call before a take; the header states the
approved planned-risk budget and labels the per-tip budget as the PURCHASE allocation; two tools
(`check_feasibility`, `preview_payoff`) serve the same numbers the gate sizes with; every TAKE is
assessed server-side after the answer (`expression` + `thesisVerdict` on the opinion, journaled on
the run). `techniques.tip.analyst_feasibility_gate`: `annotate` (default - verdict kept) |
`downgrade` (an unfittable take becomes watch; flipping it is a reviewed method decision).
Acceptance: `python -m zargar.tools.tip_feasibility replay --since 2026-09-14` re-judges the
recent TAKE cards at their stored contemporaneous unit loss / budget and prints feasible quantity
or the honest no-trade plus the shares alternative at equal risk (chain alternatives at the time
were not stored - reported as unavailable, not invented).

**PROF-02 - the whole exit path.** `techniques/tip/payoff.py` (pure): `integer_ladder` (units per
rung, runner, executable / collapsed), `unit_gains`, `payoff_preview` (every target / first target
then the stop / the stop alone, in $ and R, fees per unit; the coherent one-lot policy when the
ladder cannot be followed), `realized_from_fills` (round-trip reconciliation, excess exits kept
apart). The risk plan carries `payoff` and the card's risk grid shows it; the analyst has a one-lot
rule and the `preview_payoff` tool. `python -m zargar.tools.tip_payoff_report --since 2026-09-08`
lists closed Tips positions with ladder executability, the plan's arithmetic and the realized
round trip from fills. Tests: `tests/test_tip_payoff_feasibility.py` (integer arithmetic for
1/2/3 contracts and odd shares, the reviewer's five cases, RKT long-only = -$30.15 with the 59
excess apart, alternatives, the gate modes) and `tests/test_tip_expression_gate.py` (the real
analyst path with a scripted client). No risk limit changed; no source policy changed.

**Replay results (contemporaneous stored evidence, 2026-09-15 12:1x ET).** `tip_feasibility replay --since 2026-09-14`:
nine TAKE cards - feasible 4 (SLV 65C qty 1, MRNA 11 shares, AAL 14C 2, HIMS 30C 1), honest no-trade 5
(PLTR 195C $130.00 vs $89.62, AFRM 80C $200.08 vs $89.11, AMZN 300C $191.53 vs $89.60, TSLA 340P
$100.11 vs $89.43, MSFT 505C $96.00 vs $88.93 - the reviewer's five, reproduced exactly); labelled
shares alternatives at equal risk where the tip carried a stop (AFRM 14 @ $86.00, AMZN 7 @ $75.96,
MSFT 3 @ $55.32); chain alternatives reported unavailable (the chain at the time was not stored).
`tip_payoff_report --since 2026-09-08`: 30 closed Tips positions; RKT reconciles from the book's
executions to **-$30.15** on the long episode (entry 148 @13.46, trim 59 @13.7373 = +16.36, stop 89
of the 148 @12.9374 = -46.51) with the **59 excess units reported apart**, declared ladder 59/51/37
+1 executable, plan arithmetic: all targets +$91 (1.2R), TP1-then-stop -$26, stop -$31; the one-lot
option positions (GS 1 contract on a 40/35/25 ladder: units 0/0/0 - NOT executable as declared) show
the PROF-02 defect the preview now surfaces before admission.

## PROF-03 / PROF-05 built (2026-09-15, research only; code rides the next deploy)

**PROF-03 overnight-hold comparison.** `techniques/tip/holdstudy.py` + table `tip_hold_snapshots`
+ scheduler jobs `tip_hold_snapshot` (15:50 ET) and `tip_hold_next_open` (09:36 ET), gated by
`techniques.tip.hold_study_enabled` (True; observation only - no order, no policy change). The
snapshot records, per open Tips position (arm `carry`) and per position that exited intraday that
session (arm `intraday_exit`): the exact leg, quantity, entry, declared horizon (hold cap,
sessions held, DTE), the active exits (stop, ladder, premium stop), planned risk, costs, the source
and the QUALIFIED pre-close quote (`cohort.qualify_quote`: venue provenance, delayed flag, genuine
source time, session). The next session's first qualified quote is sampled separately.
`tools/tip_hold_study.py report` pairs carry-to-next-open (the next session's FIRST qualified bid,
never a later peak) against the predeclared intraday close (the pre-close bid; the actual exit price
for the intraday arm) net of the same costs, in $ and R, by setup (shares / option DTE buckets);
unqualified or missing samples are counted as insufficient; sacrificed next-day winners are
flagged; no blanket rule is derived. Tests: `tests/test_tip_hold_study.py` (missing quote =
insufficient; only the two contemporaneous bids; sacrificed winner; aggregation counts; on the
engine: a snapshot + next-open sample leave the position's stop and the order book untouched).

**PROF-05 frozen full-versus-compact.** `frozen.variant_knowledge` gains `compact`: the CORE rules,
the notes relevant to the tip (ticker / source scopes plus core notes) and the newest
`COMPACT_HISTORY_LINES` (12) history lines - on the identical frozen evidence, today line, tool
outputs and system prompt as `current`; replay reports now carry `cacheRead`, `cacheCreation`,
`effectiveInput` tokens and `headerChars`, and `compare` lists contracts, stops and quantities
beside verdicts, latency and tokens. Tests: `tests/test_tip_frozen_compact.py` (same evidence and
time in both variants, selection counts, no mutation path). The first paired report is recorded
below once run on a bundle captured after `frozen_capture_context` was on.

**First paired frozen report (PROF-05, 2026-09-15 13:2x ET, one bundle, one paid replay per variant).**
Bundle `fb-16d3146639a86744` (NVDA, eva, run `60d279a3` appraised at 13:21 ET with the manifest
captured EXACT - the first bundle taken after `frozen_capture_context` was on; one gap: the
view_image output is not capturable). Baseline verdict skip. **Corrected 2026-09-15 evening from the
persisted `report.tokens` (the first write of this paragraph printed None for fields the report did
carry - a reporting mistake, PR #141/#142 review):**

| metric | current | compact |
|---|---:|---:|
| verdict | skip | skip |
| input tokens | 68,917 | 37,235 |
| output tokens | 844 | 1,128 |
| calls | 2 | 3 |
| latency | 14.4 s | 17.0 s |
| header characters | 63,899 | 10,167 |
| tool calls served / missing | 1 / 1 | 1 / 3 |
| cache read / creation | 0 / 0 | 0 / 0 |

**This pair is COVERAGE-LIMITED:** the full run lacked `get_positions`, the compact run lacked
`get_quote`, `get_flow` and `get_positions` (it asked for evidence the original run never fetched),
and the image output was not capturable - so a verbatim header does not mean every requested tool
input was served, and two identical skip verdicts are NOT decision equivalence. The reading stays
mixed: about 46 % fewer input tokens, but more output tokens, one more call and about 17 % slower;
not an invoice-level cost comparison, not a validated optimization. `frozen.compare` now flags
`coverageLimited` / `coverageNote` on every pair (missing tool calls or an image gap). ONE case - no
conclusion, compact is not adopted; complete-evidence pairs are kept apart from missing-evidence
stress cases and gaps are never filled with today's data.

## 15:15 ET tick: a second over-sell class (MRNA) and the shadow books' phantom shorts

**MRNA, Tips Practice (fixed, PR pending merge).** The 09:34 ET fill (7 shares @ 141.96) carried the
proposal's bracket: GTC target 7 @ 149.70 + GTC stop 7 @ 134.3674, spawned by the OrderManager on
the fill. Adoption three seconds later added the manager's venue stop 7 @ 134.37 and the analyst's
35/35/30 ladder without cancelling the children: at 134.37 both stops would have sold 14 against 7
held (RKT again, a different cause); at 149.70 the bracket would have sold all 7 and the ladder
trimmed on top. The two bracket children were cancelled by hand at 15:22 ET (MRNA 141.97 at the
time, 5.4 % above the stop) so the manager is the only exit authority on the lot; the code fix makes
adoption/scale-in/restore do that and refuses a late bracket under a managed entry
(`tests/test_position_bracket_release.py`; PLATFORM-RULES change log). RKT (09-11) predates the
bracket-on-share-proposals rule; SLV/T carry none.

**Shadow books hold unintended SHORT share positions** (research books, no money; the trust bar is
judged on the ARMED book, so these pollute it): eva (armed) TSLA -5, MU -13, AAPL -15, MSTR -36,
SNOW -6, GOOGL -28, AMZN -57; ab (armed) APLD -40,600, RDDT -64, GOOGL -2, AMZN -3; common-stock
(armed) LULU -49; muggzone-options (armed) MSFT -2. Cause: the same over-sell classes (a venue stop
kept at pre-trim size, a manager stop firing on a record the venue no longer held) accumulated since
09-04 - the resize/clamp fix (PR #138) is not in the running 0.7.86 build. Stale resting stops still
sit against them: eva TSLA SELL 14 @ 353.17 (held -5), muggzone INTU SELL 6 (held 0), RKLB SELL 31
(held 0). Nothing was placed or cancelled on the shadow books (sim orders are the user's call):
the recommendation is a one-shot reconciliation after the deploy - cancel resting stops whose size
exceeds the held quantity and flatten the shorts with reduce-only buys, journaled as a research
reset, then re-seed the armed scorecards from that date. The TSLA record 8fd43463 that the sweep
saw "closed on a stale record" at 15:15 ET is that class: its 13-share stop filled on 09-04 against
8 held after trims, and the record stayed `closing` for 11 days until today's clamp closed it.

## 2026-09-15 end of session: 0.7.87 LIVE, manual-approval hold lifted

**Deployment verified 16:37 ET.** Build `5b7542d` (EM desk's combined merge = Tips `c06fb0b` + EM
`a1a408a`) is live; `git merge-base` confirms `6dcc06b` (v087 follow-through), `c06fb0b` and
`d5034a2` (PR #145 one-exit-authority) are ancestors. Restoration: 7/7 armed plans, 3/3 managed
positions (Tips Practice MRNA shares with venue stop `a948b077` re-registered, SLV and T calls
`app_managed` + acknowledged), 22/22 resting orders, sim book restored; no
`ManagedPositionBracketReleased` at boot (MRNA's children were already cancelled at 15:22 ET).
Gates unchanged (`geometry_gate=enforce`, `entry_pause_mode=integrity`, `allow_live_auto=False`,
Practice). No pending cards, so nothing to revalidate. **The Tips manual-approval hold that stood
since the AP85/A86 review rounds is LIFTED** - the review-cleared code is the running code; cards
decide themselves under the unattended-practice rule again (take approves, skip/watch declines,
review-required cards wait for a person).

**The day in numbers (Tips desk).** 20 cards: 2 executed (MRNA 7 shares @ 141.96; SLV Nov 65 call
x1 @ 10:05), 4 expired ("no quote"/"no live reference" review-required cards the analyst had marked
take), 14 declined by the analyst (skip). 32 `TipGeometryRepaired` records: 15 review-required
"no quantity satisfies the $89-90 risk budget" (one-lot option risk above the budget - the PROF-01
feasibility annotation now says so on the analyst record; the knob stays `annotate`), 6 stop
re-placements at submission/revalidation (MRNA, AFRM, AMZN, GS, MSFT, GOOGL, HIMS), 2 wrong-side
target drops (AMZN). No incident opened today (the four `repeated_pre_entry_failure` incidents were
2026-09-14 evening and resolved at the session boundary); one `TipAutoPaused` at 09:34 = the AFRM
review-required card. Closed on Tips Practice: HIMS call (premium bled 40 %, -$25), RKT (the
reconciled short, manual close). Desk ledger realized today -$267.21 including EM's ORCL call
(-$79.08); ledger balanced (unexplained 0).

**Carried overnight (Tips Practice):** MRNA 7 shares, stop 134.37 (venue GTC, single authority);
SLV Nov 65 call x1 and T Jan-27 29 call x4, `app_managed` + acknowledged. Armed multi-day plans
rolling: 7 (restored). Tonight: `tip_retro` on HIMS/RKT (retro_enabled), `tip_knowledge_maintenance`
PROPOSE-ONLY (`knowledge_apply_enabled=False`), digests on; the hold study's first snapshot is
tomorrow 15:50 ET (the job shipped after today's close); cohort + frozen capture + MK observe on.
`TipIntakeStalled` fired 19 times today under 0.7.86 (briefly pending envelopes) - the pending-streak
rule (PR #137) is now live and should silence it.

**Defects found today and their state:** RKT venue-stop resize + restore re-registration (PR #138,
live); MRNA double exit authority (PR #145, live); shadow-book phantom shorts (13 positions across
eva/ab/common-stock/muggzone armed books, APLD -40,600) - NOT touched; needs the user's go for a
journaled research reset (cancel oversize stops eva TSLA 14/-5, muggzone INTU 6/0, RKLB 31/0; reduce-only
buys; re-seed the armed scorecards). EM desk note: `test_grade_lanes_writes_verdict` failed once in
a full-file run on the combined tree and passes alone - order-sensitive, watch it.

## HOLD142-01..03 corrections (2026-09-15 evening, research only; `holdstudy-v2`)

Reviewer verdict `2026-09-15-pr141-142-verdict.md` (PR #141 arithmetic accepted). The four supplied
regressions are adopted verbatim as `tests/test_prof142_research_boundaries_review.py`; all four
failed on `b9fbc6c` and pass now. Nothing here touches risk limits, permissions, stops or entry/exit
policy; feasibility stays `annotate`; ordinary trading was never stopped.

**HOLD142-01 sampling windows.** Every observation now carries its protocol window and the actual
observation time (`observed_at`, `window{start,end,verdict,observedAt,sourceTs,toleranceS}`). A
pre-close observation must fall inside the last `hold_preclose_window_minutes` (15) before the
exchange close of a trading day - early closes included (`market_calendar.session_close_minutes`);
too early records nothing (the timely run will), after the close or on a non-trading day (an
after-close boot's scheduler catch-up) the observation is recorded as `outside_window` WITHOUT a
quote - a miss, never back-labeled pre-close. The next-open observation is bound to the EXPECTED
next trading session (`expected_next_session` = `market_calendar.next_trading_day`, weekends and
holidays skipped) and to the opening window 09:30 + `hold_next_open_window_minutes` (15): it is the
FIRST qualified quote inside that window (the 09:36 job retries in-window, 20 s apart, up to
`hold_next_open_attempts`; with none qualifying the row is settled terminally with the attempt count);
before the expected session or before 09:30 nothing happens; a pending row whose expected session
has passed is `missed` - a later day never replaces it. **Tonight's after-close boot (16:42 ET)
had already produced the reproduction: three v1 rows labeled pre-close, MRNA `fresh`.** The one-shot
`python -m zargar.tools.tip_hold_study requalify` (adds the v2 columns/index additively, then
re-labels any v1 observation captured outside its window `outside_window`, fills the identity key
and expected session) was run against the live DB the same evening - see the record below.

**HOLD142-02 identity.** `observation_key` = study version | session | position (holding episode) |
leg | arm, enforced by a UNIQUE index (`ix_tip_hold_observation_key`; `db.create_all` now also
creates declared indexes an existing table lacks - PLATFORM-RULES change log). Capture checks the
key first and swallows the concurrent-writer IntegrityError; the original observation is never
replaced. The next-open settle runs under a row lock and only on `pending` rows. Every OPT/STK leg
is observed (spreads no longer sample only the first leg). Summaries count position-session
observations and list distinct positions separately (`distinctPositions`, `unit`).

**HOLD142-03 costs and meaning.** `compare_row` nets the allocated ENTRY fee and the EXIT cost:
options a per-contract fee (+ `sim.reg_fee_per_contract`, carried on the row as
`fees.regPerContract`) on each side; shares a per-order commission on each side with the entry
commission allocated pro rata to the sampled remainder (`entry_qty` persisted) - unknown inputs stay
visible in `costs.notes` (sell-side SEC/FINRA charges are not modelled). The reviewer's case (2
contracts at 1.50, bids 1.40 / 1.80, $1 per contract per side) reads -24 / +56; the paired
difference +80 is unchanged. The R denominator is rebased to the sampled size
(`planned_risk_qty` persisted; `riskForSample`, `riskBasis`). The carry arm is reported as what it
is: `carryToNextOpen` = OVERNIGHT QUOTE DRIFT (the next-open bid on the sampled size), and
separately `managedCarry` = the strategy's own result when its stop/exit closed the position before
the next-open sample (`carry_outcome` read from the durable managed record at settle time: closed
before the sample, exits between the two endpoints, price, reason) - `known: false` while the
position is still open. No fill is ever inferred from an endpoint quote. The study is therefore a
labelled quote-drift comparison plus the managed outcome where known - not yet a policy-faithful
"retain the stop" experiment; that stays a separate, explicitly defined protocol.

Tests: `tests/test_prof142_research_boundaries_review.py` (4, reviewer), `tests/test_tip_hold_study.py`
(fee both sides, sampled-size R, managed-vs-drift, exchange-calendar windows incl. early close /
holiday / weekend, on the engine: timely capture is idempotent, too-early next-open does nothing,
in-window first qualified quote with attempts + managed outcome, orders and stop untouched),
`tests/test_tip_frozen_compact.py`, `tests/test_profitability_preview_review.py`,
`tests/test_tip_payoff_feasibility.py`: **20 passed** (the reviewer's 4 + the existing 16).

**Live repair record (2026-09-15 ~18:20 ET):** `tip_hold_study requalify` against the runtime DB added
the v2 columns and `ix_tip_hold_observation_key` additively and re-labeled the three 16:42 ET rows
(MRNA, SLV, T; session 2026-09-15, expected next session 2026-09-16) `outside_window` with the
re-qualification gap - none of them is pre-close evidence; their next-open sample will read
insufficient. The running build (5b7542d) still carries `holdstudy-v1`; tomorrow's 15:50 ET capture
is protocol-correct only once this commit is deployed (merged, not deployed at the time of writing).

## R147-01/02 corrections (2026-09-15 late evening, research only)

Reviewer verdict `2026-09-15-pr147-verdict.md` on merged `9082bfa`: the HOLD142 corrections pass and
the live cleanup / unique index are verified; two narrow items remained. The reviewer's checks
`tests/test_pr147_observation_review.py` are adopted verbatim (three failed on `9082bfa`, the index
migration check already passed; all four pass now).

**R147-01 the ACTUAL sample time governs admission.** Both collectors judged the window on the
job's start clock and persisted it as the observation time, so a job starting at 15:59:59 could
store a quote sampled at 16:00:02 as `fresh`. Now: the clock is re-read per row and per attempt
(`_clock`: the real clock, or the pinned instant a caller supplied), the window is judged BEFORE
sampling a row and AGAIN on the quote's own `sampledAt` (stamped by the quote store when the sample
was read; `sourceTs` stays the venue print, `jobStartedAt` the job's clock - all three persisted,
`observed_at` / `next_open_sampled_at` = the actual sample time). A qualified quote sampled outside
its window is stored with status `late` (quote kept, never protocol-qualified, `compare_row`
insufficient); a row the window ended before is `late` / `missed` without a quote. The managed-outcome
attribution uses the actual sample time. Tests: the reviewer's two clock-crossing cases, a slow
two-row capture (15:59:40 fresh, 16:00:10 late) and the engine case's persisted times.
**Calendar-relative wiring:** `Scheduler.register` accepts a per-day resolver (`at_et(date) ->
"HH:MM"`, `resolve_at`, shown in `status()` as `calendarRelative`), and the runner registers the
pre-close job at `session_close - hold_snapshot_before_close_minutes` (10: 15:50 on a normal day,
12:50 on a 13:00 early close - `holdstudy.preclose_job_time`) and the next-open job AT the opening
window's start, 09:30 (`next_open_job_time`), searching the first qualified quote inside 09:30-09:45
with in-window retries (`hold_next_open_attempts` 40 x 20 s). The old fixed `hold_snapshot_at` /
`hold_next_open_at` knobs are empty by default and override only when set. Tests:
`test_job_times_follow_the_exchange_calendar` (Black Friday 12:50, a 5-minute offset on Christmas
Eve, the scheduler resolving the callable per day).

**R147-02 the emitted gap fields.** `frozen.replay` emits `bundleGaps` (capture-time gaps such as
"view_image output is not capturable") and `manifestGaps` (header/system reconstruction gaps);
`compare` read legacy `gaps` / `headerGaps` only, so an image-only gap with zero missing tool calls
read complete. `compare` now unions `bundleGaps` + `manifestGaps` (legacy names kept) and reports
`coverage = {missingToolCalls, imageGap, bundleGaps, manifestGaps}` beside `coverageLimited` - the
reasons stay independently visible and none masks another. Tests: the reviewer's image case plus
complete-evidence, manifest-only, both-reasons and legacy-field controls. The NVDA pair's reading is
unchanged (coverage-limited, mixed; compact not adopted).

Runs on the final commit: `tests/test_pr147_observation_review.py` + `test_prof142_research_boundaries_review.py`
+ `test_tip_hold_study.py` + `test_tip_frozen_compact.py` + `test_profitability_preview_review.py` +
`test_tip_payoff_feasibility.py` = **27 passed**; scheduler-touching slice `test_platform_phase3.py` +
`test_flow_api.py` + `test_tip_knowledge_review_20260913.py` = 29 passed, 1 failed
(`test_flow_api.py::test_repair_rescans_degraded_day` - fails identically on the unmodified checkout,
Flow desk, not touched here); `test_tip_activation.py` (attaches the runner with the calendar-relative
registration) 4 passed. Merged, not deployed (live 5b7542d); the affected samples are not to be used
for any holding or model-context decision until the corrections are live and verified.
