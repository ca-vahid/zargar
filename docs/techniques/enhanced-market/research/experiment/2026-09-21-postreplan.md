# EM books - pre-open verification, 2026-09-21

Generated 2026-09-21T13:32:02+00:00 (read-only).
Experiment `em-experiment-v1` enabled: **True**; owner: EM desk (EM Dev session) - attends pre-open, open, close; rollback = pause this book

| Item | baseline (EM Practice) | experiment (EM Experimental) |
|---|---|---|
| Book id | 045d8c35b3f149628ea001ae90a58edb | 07ef1e867cad4150bc81e072a8fd600a |
| Kind | sim | sim |
| Cash | 4934.783199999987 | 9849.6032 |
| Last equity point | 9860.443199999987 | 9849.6032 |
| Armed for the session | 53 {'armed': 38, 'disarmed': 15} {'auto': 53} | 107 {'armed': 79, 'disarmed': 28} {'auto': 107} |
| Plan origins | {'preopen_replan': 15, 'promote': 38} | {'preopen_replan': 28, 'experiment': 79} |
| Promoted candidates | none | none |
| Experiment-tagged arms | 0 | 107 |
| Open positions / working orders | 2 / 0 | 0 / 0 |
| Limit: mode | auto | auto |
| Limit: instrument | options | options |
| Limit: riskPct | 2.0 | 2.0 |
| Limit: maxQty | 100.0 | 100.0 |
| Limit: contracts | None | None |
| Limit: maxContracts | 10 | 10 |
| Limit: singleContractExit | tp2 | tp2 |
| Limit: maxOpenTrades | 1 | 1 |
| Limit: entryFallback | shares | shares |
| Limit: skipWideSpread | True | True |
| Limit: skipElevatedIv | False | False |
| Limit: slippagePct | 0.1 | 0.1 |
| Limit: flattenMinutesBeforeClose | 5 | 5 |
| Limit: allowLive | False | False |
| Daily loss limit per plan | [393.98] | [393.98] |
| Matches 2 x riskPct x equity | False | True |

Technique-wide EM settings (must be unchanged by the experiment): {"first_sale_rr_gate": null, "preparation_policy": null, "book_snapshot_observe": null, "source_candidates_observe": null, "source_scenarios_observe": null, "shadow_exit_observe": true, "shadow_p02_candidate": true, "paused": null}

Shared, not per book: {"maxOrdersPerMinute": 30, "dayNotionalPerTechnique": null, "emLossHaltPct": 10.0, "bookLossHaltPct": 15.0}

Routing: {"taggedRunsArmedOutsideTheExperimentalBook": 0, "untaggedArmsInsideTheExperimentalBook": 0, "bothBooksAreSim": true}

## Desk verification, 09:36 ET - ONE DEFECT FOUND (read-only; nothing changed)

Routing and preparation survived the 09:25 re-plan cleanly:

| Check | Result |
|---|---|
| Books after the re-plan | baseline 38 armed (15 re-planned), experiment 79 armed (28 re-planned); the counts moved, the BOOKS did not |
| Experimental tags | all 107 experimental rows (79 live + 28 replaced parents) tagged `experiment:em-experiment-v1` + `xbook:07ef1e86...`; tagged runs armed elsewhere: 0; untagged arms inside the experimental book: 0 |
| Re-planned experimental runs | 0 missing the tags, 0 model passes - the replacement path kept both the book and the deterministic policy |
| Per-plan loss allowance | 393.98 in both books, unchanged from the pre-open file |
| Books | both `sim`, neither paused nor halted; no `TechniqueArmRefused` and no `preopen_replan_ineligible` since 09:00 ET |
| Frozen bundle and technique-wide switches | unchanged |

The checker's "Matches 2 x riskPct x equity: **False**" for the baseline is NOT drift: the baseline has traded, so its equity
moved to 9,860.44 while its plans still carry the 393.98 derived at arm time. The check compares against CURRENT equity; that is
a reporting nuance, not a policy change.

### DEFECT: the host clock is ~10 s behind, and first-sale enforcement refuses every experimental entry

- The experimental book fired **8** triggers by 09:32 and entered **0**. Seven reached the first-sale gate and all seven were
  `deferred_missing_evidence`, reason `underlier_invalid`, problem **`venue_time_in_future`**. Their R was fine (7.11, 4.92,
  4.19 ... all above the 3.0 minimum) - only the evidence check blocked them.
- Cause: every equity quote carries a venue timestamp about **10 seconds AHEAD** of this host's clock
  (`quoteTs - receivedTs` = +4.8 s to +10.2 s across all eight records). Postgres, which runs in the Docker/WSL VM, is
  **+9.57 s** ahead of the Windows host. The Windows Time service is **not running** (`w32tm /query /status` ->
  "The service has not been started"), so the host clock has drifted behind real time. The feed and the database are right;
  the host is slow.
- Blast radius: EM Experimental only. `first-sale-v2` allows a venue time at most 1 s in the future, so it fails closed - which
  is the policy behaving exactly as designed on evidence it cannot trust. The baseline book is unaffected (its gate is `off`)
  and has three positions. Other desks are unaffected: the production RiskGate measures age as `now - ts`, which is simply
  negative here and passes.
- This is an ENVIRONMENT fault, not an EM code fault, but its effect is that the experiment cannot trade while it persists, so
  today's comparison would be "38 baseline entries vs 0 experimental" for a reason that has nothing to do with the method.
- Not fixed on the fly: starting the Windows time service or stepping the host clock is a system change, and deploying a
  tolerance change to `first-sale-v2` during regular trading hours is barred by the protocol and would unfreeze the bundle.
  Escalated to the user with two options: (a) start/resync the Windows time service now, which removes the defect without any
  code or bundle change; (b) leave it, accept that the experiment does not trade today, and decide after the close whether the
  gate should tolerate a documented clock skew.
