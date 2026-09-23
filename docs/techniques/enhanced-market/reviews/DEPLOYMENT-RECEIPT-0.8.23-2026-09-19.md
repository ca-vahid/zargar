# EM 0.8.23 - deployment receipt (2026-09-19, default-off)

Deployment of the accepted EM integrated package (`FINAL-COMPLETION-RESPONSE-2026-09-19.md`) on the user's instruction. Deployment only:
no preparation was re-run, no strategy or switch was activated, no setting was changed, no order was placed by this work.

| Item | Value |
|---|---|
| Deployed commit | **`b3cfb9612f370d87899df0af55fe5f8c6e6a81e5`**, version **0.8.23**. It is the reviewed and tested `2d7f51bb` plus documents only (`git diff 2d7f51bb..b3cfb961 --stat` = `docs/`, including the rollback correction below) |
| Replaced | v0.8.22 build `4801aa3061e95583dfcbc37b6a01c88f37188275` |
| Live now | `/api/health`: ok, started, version 0.8.23, build `b3cfb961...` (launch-bound) |
| Script receipt | `C:/Cursor/zargar/logs/deployment-receipt.json`: phase **verified**, target and health build `b3cfb961`, healthy version 0.8.23, completed 2026-09-19T16:47:22Z |
| When | Saturday 2026-09-19, about 09:43 to 09:47 PT. Market closed |

## 1. Fresh checks before the deploy

| Check | Result |
|---|---|
| Ancestry, re-read at deploy time | origin/main `f621d49f` and the runtime head `4801aa30`: the target was 0 commits behind both. The runtime checkout fast-forwarded (`git merge --ff-only`); nothing was reset or downgraded. No version collision (main and the runtime were 0.8.22) |
| Runtime checkout | clean before and after; head `b3cfb961` after |
| Readiness `GET /api/ops/restart-check` | **safe**, no reasons. Market closed; open trades 0; working entries 0; pending exits 0; in-flight orders 0; runs in flight 0; no inventory error; not quiesced; no paused book |
| Before-inventory | 22 armed plans (Tips 10, Team2 9, Options Cartel 3), 28 resting orders, 6 managed positions. Saved: `C:/ProgramData/Zargar/reviews/em-deploy-0.8.23-before-readiness.json`, `...-before-state.json`, and the script's `logs/restart-inventory-20260919-094318.json` |
| Processes | one engine, one Discord gateway, one EM ingestion helper (each a launcher + child pair) |
| Other desks | Tips, Team2 and the Cartel session were told before the deploy; all three replied that nothing of theirs was in flight and held their own restarts. Open pull requests (#223, #224) were not merged |
| Build and import on the target | `npm run build` + `check-release` 0.8.23 green; `import zargar.api.app` ok |

## 2. What happened, including the part that went wrong

1. `scripts/deploy.ps1 -TargetCommit b3cfb961... -Expect 0.8.23` ran from `C:/Cursor/zargar` under the deployment lease. It re-checked readiness, quiesced entries, fast-forwarded the checkout, built the frontend, saved its inventory and called the guarded restart.
2. **The restart step stopped the engine and then refused to start the new one**, because my assistant shell is ELEVATED (`start.ps1` exit 8: an engine started from an elevated shell could not be stopped by the `ZargarRestart` task or the watchdog). The script recorded phase `failed`. The app was DOWN.
3. I confirmed no engine process was running and started the prescribed door for an elevated shell, the `ZargarRestart` scheduled task (non-elevated, the same `restart.ps1`). It started the target, waited for health and recorded phase `verified` at 16:47:22Z.
4. **Downtime: about 4 minutes** (engine stopped about 16:43:18Z, healthy by 16:47:22Z), on a closed Saturday with no open trade, no working entry and no in-flight order. No order, fill or exit could be affected. Venue-side GTC stops of the six managed positions stayed at the venue throughout.
5. The task's own receipt says `restoration: skipped-no-baseline` (its baseline was consumed by the failed first attempt). Restoration was therefore verified by hand against my own before-inventory (section 3).

Lesson, recorded for every assistant session: from an elevated shell `deploy.ps1` must not be the restarting party. The safe sequence is the fast-forward and build, then the `ZargarRestart` task. I should have checked the shell's elevation before calling the script; the repo notes say assistants restart through the task.

## 3. Verification after the deploy

| Check | Result |
|---|---|
| Armed plans | **equal by id**, 22 of 22 (Tips 10, Team2 9, Cartel 3) |
| Resting orders | equal, 28 of 28 |
| Managed positions | equal, 6 of 6. Tips desk confirmed its positions and the SBLK venue stop (STP 30.58 x62, ACCEPTED) |
| Open trades / working entries / pending exits / in-flight orders | none; no inventory error; not quiesced; no paused book |
| Helpers | exactly one Discord gateway and one EM ingestion helper, restarted with the engine. Tips desk confirmed intake live and the gateway connected |
| New tables | `technique_book_snapshots`, `technique_prep_decisions`, `technique_source_candidates` exist and hold **0 rows**; 0 `scenarios` artifacts; 0 `TechniqueFirstSale` events |
| Defaults (`GET /api/technique/em/manifest`, saved as `em-deploy-0.8.23-manifest.json`) | every new switch effective = default: `first_sale_rr_gate=off`, `book_snapshot_observe=False`, `source_scenarios_observe=False`, `source_candidates_observe=False`, `source_candidates_chain_fetch=False`, `preparation_policy=baseline`, `conditional_review_fix=report`, `prep_audit_quota_pct=0.0`, `pick_retry_after_429_s=0.0`. Recorder counters all zero |
| Established settings | unchanged: `shadow_exit_observe=True`, `shadow_p02_candidate=True` (P-02 / P-06 collection continues), `fire_decision_mode=deterministic`, `fire_evidence_mode=off`. No settings event was journaled during the deploy window; no EM setting row changed |
| Other desks | Tips verified its side on the new build (review gate at its default, plans, positions, intake). Team2 and the Cartel session were given the receipt for their own read-only checks |

Still to observe at Monday's first EM entry and exit (cannot be seen on a closed market): no `TechniqueFirstSale` event beside the entry; the exit's `TechniquePlanOrderResult` carries `entryOrderId`; P-02 shadow-exit events continue.

## 4. Rollback (corrected checklist)

Settings rollback touches ONLY the switches this delivery added, each back to its shipped default, and only those that were changed:
`book_snapshot_observe=False`, `first_sale_rr_gate=off`, `source_scenarios_observe=False`, `source_candidates_observe=False`,
`source_candidates_chain_fetch=False`, `preparation_policy=baseline`, `conditional_review_fix=report`, `prep_audit_quota_pct=0`,
`pick_retry_after_429_s=0`. Today none of them has been changed, so there is nothing to roll back by settings.
**Never part of a rollback:** `shadow_exit_observe`, `shadow_p02_candidate` (the established P-02 / P-06 collection), `fire_decision_mode`,
`fire_evidence_mode`, `ingest.auto_arm`, every risk limit and every other desk's setting. Code rollback = deploy `4801aa30` (0.8.22) through the
same protocol, restarting through the `ZargarRestart` task; the additive tables can stay.

## 5. Activation order (none done here; each is a separate decision)

1. `book_snapshot_observe = true` - executable-profit capture. Read the first session's coverage, unscorable reasons, drops and revisions first.
2. `first_sale_rr_gate = observe` - after a clean recorder day.
3. `source_scenarios_observe`, then `source_candidates_observe` (keep `source_candidates_chain_fetch` off).

`first_sale_rr_gate = enforce` and `preparation_policy = deterministic` remain OFF.
