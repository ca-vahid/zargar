# EM deployment and source-backfill verification

**Deployment identity and the Delivery B source-backfill readback are verified. The team can proceed with deletion forwarding and real worker artifact/checkpoint wiring, keeping candidates order-free. FIX-01's money-projection repair has not been applied and retains its separate scoped approval.**

This review used read-only runtime endpoints, read-only PostgreSQL queries, Git ancestry and local receipt/log reads. No restart, lease change, data application, settings change or trading action was performed.

## Deployed build and artifact

The live `/api/health` response independently returned:

```json
{"ok":true,"started":true,"version":"0.7.75","build":"0014640bf530e4751dc37e70eec53a89213c7b16"}
```

The runtime checkout was clean at that same full SHA. `logs/deployment-receipt.json` records target `0014640bf530e4751dc37e70eec53a89213c7b16`, expected version 0.7.75, phase `verified`, and completion at `2026-09-15T00:44:03.7332999+00:00`.

The receipt's frontend artifact hash independently matches the current `frontend/dist/index.html`:

`7C2443BFA91D87453EF31BD8FF9E77A7A9605F7047EF9B6DB78EA90690AB2543`

`restart-20260914-174252.log` ends with `Healthy: v0.7.75 | armed 11 | runs in flight 0`. The deployed commit includes the accepted EM tree `3f1d665`; remote review head `39299ff` includes the deployed commit and the separately restored helper/test work. A later documentation/test merge does not change which build is actually running.

## Current inventory and restoration evidence

At the current `/api/ops/state` snapshot:

| Item | Readback |
|---|---:|
| Armed plans | 11: 3 Team2, 8 Tips |
| Open technique-runner trades | 0 |
| Working entries / firing / pending exits / in-flight orders | 0 |
| Resting orders | 23 |
| In-memory managed positions | 3 open, 2 closed |
| Runs in flight | 0 |
| Inventory error | null |
| Quiesced | false |
| Market open | false |

The persisted `OpsRestartCheck` at `2026-09-15T00:42:48.206256+00:00`, caller `load-health-repair`, records safe=true, 11 arms, 3 managed open positions, 23 resting orders, zero open trades/in-flight orders and no inventory error. Those counts match the current readback.

**Scope:** the current identities and counts were inspected, and the counts match the retained readiness event. The journal event retains counts, not the complete before-state ID lists. The successful restart transcript contains no `Restore check OK` line. A complete independent before/after-by-ID comparison therefore is not claimed from the supplied persisted evidence. If the release owner retained the pre-restart state response, attach its ID comparison to the receipt; do not infer ID preservation from counts alone.

The database's full historical `managed_positions` table contains older closed/archived/attention rows beyond the runtime manager's loaded inventory. Those historical totals are not a contradiction of the reported 3-open/2-closed runtime snapshot.

## Delivery B source backfill

The pre-deployment and post-deployment manifests have identical reviewed items. Their digest is independently reproducible as **`f3931513580afb0c`**.

Live PostgreSQL readback:

| Object | Verified result |
|---|---|
| Source revisions | 19; all revision 1, kind `create` |
| Artifacts | 24: 8 transcripts, 16 extractions |
| Availability | All 24 have `completed_at=NULL` and `availability=unknown` |
| Jobs | 19: 16 `done` / `board_checked`; 3 `retryable` / `received` |
| Revision text/images versus current original notes | Zero mismatches |
| Artifact transcript/extraction payloads versus original notes | Zero mismatches |

The complete current source-evidence items were rebuilt read-only using the reviewed `item_for` definition. All **19/19** match the post-deployment manifest, and their recomputed digest is also **`f3931513580afb0c`**. This verifies the source evidence against the approved snapshot rather than accepting counts alone.

The team's second-apply/no-op result was reported; this review did not call apply again. The already-tested idempotent path and unchanged 19/24/19 readback are consistent with that report. There is no need to repeat a data operation merely to obtain another verification count.

The source backfill is closed within this scope. Three unfinished jobs do not imply that real transcription/extraction recovery is finished; those workers are explicitly the next wiring task.

## FIX-01 money repair remains separate

There are **zero `TechniqueTradeCorrected` events** in the runtime database at this review's check. The monetary projection correction is not claimed as applied.

Its earlier approval remains limited to the explicit v4 five-record set, using current row hashes, ownership and authoritative ledger checks on non-live rows. No `--include-live`, automatic rearming, cash adjustment or rewriting execution history is authorized by the source-backfill completion. Return correction receipts and readback if that separate operation is performed.

## Restart incident: operational follow-up

The watchdog log confirms a new process start at 17:37:16 local time and unsuccessful health polling through 17:39; later ticks deferred while a start was recent. The repaired build became healthy by the verified deployment completion around 17:44. The earlier build-helper defect and the fact that rewriting a source file does not repair an already-imported module are consistent with the observed incident.

There is an important control gap to address in the shared deployment tooling:

```powershell
try { Invoke-RestMethod /api/health; $engineUp = $true }
catch { $engineUp = $false }
```

In the current restart script, that result controls whether the script requests entry pause, captures pre-restart inventory and performs readiness/restoration checks. An HTTP 500 from an existing process is therefore treated like a stopped engine. The successful recovery transcript's missing restore-check line is consistent with that path.

**Requested follow-up for the release owner, without another unnecessary restart now:**

1. Distinguish connection refusal/no process from a reachable but unhealthy process. On HTTP 500, obtain the independent ops inventory/readiness when available and preserve normal entry-pause and in-flight safeguards.
2. If inventory/readiness is unavailable, record that uncertainty explicitly and use the documented incident-recovery authority; do not silently classify the process as absent.
3. Validate the target import and health contract before stopping the existing process. Keep source/artifact selection, writes and restart under the deployment ownership protocol so a post-start file rewrite cannot masquerade as a loaded fix.
4. Persist the before/after IDs or their comparison evidence. A receipt should distinguish health/artifact verification from restoration status, including `unknown/skipped-no-baseline` when appropriate.
5. Bound or stop repeated retries of an unchanged deterministic import/health failure, with an actionable incident record. Preserve independent protective order/position management during recovery.

Acceptance cases should include HTTP 500 with a still-live engine and active work, unavailable ops inventory, a target missing the health import contract, and recovery where before-state evidence is unavailable. These are shared deployment safeguards prompted by the actual incident, not new EM strategy changes. The currently healthy engine does not need to be restarted to work on them.

## Next PR and handoff

Proceed with gateway deletion forwarding and the actual transcription/extraction workers using immutable artifacts, fenced leases and transactional checkpoints. Demonstrate the real gateway → API → worker path, including duplicate delivery, changed source, worker crash, expired lease and retry. Preserve unknown versus known availability and keep candidates order-free.

Retain existing managed positions and protective exits under their current owner; a source deletion or supersession must not remove protection. Later scenario alignment, quantity-dependent R:R, wider exit integration and strategy activation remain separate work.

Primary documentation folder/branch: `C:/Cursor/zargar-codex` / `codex/zargar-development`. Deployment and backfill were performed by the release team; this task only verified and documented them. No production changes or test runs were needed for these read-only closure checks.
