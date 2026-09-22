# EM books - pre-open verification, 2026-09-22

Generated 2026-09-22T13:32:01+00:00 (read-only).
Experiment `em-experiment-v1` enabled: **True**; owner: EM desk (EM Dev session) - attends pre-open, open, close; rollback = pause this book

| Item | baseline (EM Practice) | experiment (EM Experimental) |
|---|---|---|
| Book id | 045d8c35b3f149628ea001ae90a58edb | 07ef1e867cad4150bc81e072a8fd600a |
| Kind | sim | sim |
| Cash | 10051.301699999987 | 9849.6032 |
| Last equity point | 10051.301699999987 | 9849.6032 |
| Armed for the session | 42 {'disarmed': 9, 'armed': 33} {'auto': 42} | 118 {'armed': 91, 'disarmed': 27} {'auto': 118} |
| Plan origins | {'promote': 33, 'preopen_replan': 9} | {'preopen_replan': 27, 'experiment': 91} |
| Promoted candidates | none | none |
| Experiment-tagged arms | 0 | 118 |
| Open positions / working orders | 0 / 0 | 0 / 0 |
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
| Daily loss limit per plan | [402.05] | [393.98] |
| Matches 2 x riskPct x equity | True | True |

Technique-wide EM settings (must be unchanged by the experiment): {"first_sale_rr_gate": null, "preparation_policy": null, "book_snapshot_observe": null, "source_candidates_observe": null, "source_scenarios_observe": null, "shadow_exit_observe": true, "shadow_p02_candidate": true, "paused": null}

Shared, not per book: {"maxOrdersPerMinute": 30, "dayNotionalPerTechnique": null, "emLossHaltPct": 10.0, "bookLossHaltPct": 15.0}

Routing: {"taggedRunsArmedOutsideTheExperimentalBook": 0, "untaggedArmsInsideTheExperimentalBook": 0, "bothBooksAreSim": true}

