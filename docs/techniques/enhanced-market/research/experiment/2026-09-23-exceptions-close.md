# EM books - pre-open verification, 2026-09-23

Generated 2026-09-23T20:37:04+00:00 (read-only).
Experiment `em-experiment-v1` enabled: **True**; owner: EM desk (EM Dev session) - attends pre-open, open, close; rollback = pause this book

| Item | baseline (EM Practice) | experiment (EM Experimental) |
|---|---|---|
| Book id | 045d8c35b3f149628ea001ae90a58edb | 07ef1e867cad4150bc81e072a8fd600a |
| Kind | sim | sim |
| Cash | 9756.577399999982 | 9474.7775 |
| Last equity point | 9756.577399999982 | 9474.7775 |
| Armed for the session | 49 {'disarmed': 49} {'auto': 49} | 127 {'disarmed': 127} {'auto': 127} |
| Plan origins | {'promote': 41, 'preopen_replan': 8} | {'experiment': 103, 'preopen_replan': 24} |
| Promoted candidates | none | {'requalification': 2} |
| Experiment-tagged arms | 0 | 127 |
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
| Daily loss limit per plan | [395.07] | [383.11, 383.22, 383.57] |
| Matches 2 x riskPct x equity | False | False |

Technique-wide EM settings (must be unchanged by the experiment): {"first_sale_rr_gate": null, "preparation_policy": "deterministic", "book_snapshot_observe": null, "source_candidates_observe": null, "source_scenarios_observe": null, "shadow_exit_observe": true, "shadow_p02_candidate": true, "paused": null}

Shared, not per book: {"maxOrdersPerMinute": 30, "dayNotionalPerTechnique": null, "emLossHaltPct": 10.0, "bookLossHaltPct": 15.0}

Routing: {"taggedRunsArmedOutsideTheExperimentalBook": 0, "untaggedArmsInsideTheExperimentalBook": 0, "bothBooksAreSim": true}


## Operational exceptions

Anything to report: **True**. By class: {'fault': 38, 'protective': 2}. By type: {'TechniquePlanError': 103, 'OpsQuiesce (other book)': 3, 'TechniquePlanRestored (other book)': 7}.
Expected protective actions: 2 | FAULTS: 38 | plan restores in the window: 7
Shared order-rate window: 0 rejections (0 in an EM book); busiest minute 2026-09-23 13:19:00+00:00 with 6 orders, cap 30.
Recorder: {'07ef1e867cad4150bc81e072a8fd600a': {'snapshots': 789, 'instances': 1, 'drops': 0}}; unscorable reasons: {'07ef1e867cad4150bc81e072a8fd600a': {'LITE': 2, 'HOOD260925P00126000': 114, 'quote_time_skew_21780ms': 1, 'quote_time_skew_19825ms': 1, 'quote_time_skew_16424ms': 1, 'quote_time_skew_12894ms': 1, 'quote_time_skew_12094ms': 1, 'quote_time_skew_9341ms': 1, 'quote_time_skew_6566ms': 1, 'quote_time_skew_23883ms': 1, 'quote_time_skew_19160ms': 1, 'quote_time_skew_11734ms': 1, 'INTC260923C00121000': 14, 'quote_time_skew_19926ms': 1, 'quote_time_skew_13906ms': 1, 'quote_time_skew_8644ms': 1, 'KORU': 1, 'GOOGL260925C00342500': 46, 'quote_time_skew_15577ms': 1, 'quote_time_skew_11988ms': 1, 'quote_time_skew_8028ms': 1, 'quote_time_skew_27869ms': 1, 'quote_time_skew_8204ms': 1, 'quote_time_skew_20692ms': 1, 'quote_time_skew_13546ms': 1, 'quote_time_skew_7072ms': 1, 'quote_time_skew_8916ms': 1, 'quote_time_skew_22404ms': 1, 'quote_time_skew_18391ms': 1, 'quote_time_skew_14438ms': 1, 'quote_time_skew_12274ms': 1, 'quote_time_skew_23115ms': 1, 'quote_time_skew_17469ms': 1, 'quote_time_skew_14721ms': 1, 'quote_time_skew_10807ms': 1, 'quote_time_skew_22995ms': 1, 'quote_time_skew_17820ms': 1, 'quote_time_skew_13594ms': 1, 'quote_time_skew_8336ms': 1, 'quote_time_skew_22544ms': 1, 'quote_time_skew_15564ms': 1, 'quote_time_skew_9396ms': 1, 'quote_time_skew_20836ms': 1, 'quote_time_skew_17653ms': 1, 'quote_time_skew_11838ms': 1, 'quote_time_skew_5072ms': 1, 'quote_time_skew_9113ms': 1, 'quote_time_skew_22241ms': 1, 'quote_time_skew_17384ms': 1, 'quote_time_skew_11174ms': 1, 'quote_time_skew_8301ms': 1, 'quote_time_skew_20754ms': 1, 'quote_time_skew_17454ms': 1, 'quote_time_skew_12606ms': 1, 'SNDK': 1, 'quote_time_skew_6574ms': 1, 'quote_time_skew_22949ms': 1, 'quote_time_skew_17951ms': 1, 'quote_time_skew_14255ms': 1, 'quote_time_skew_9979ms': 1, 'quote_time_skew_5651ms': 1, 'quote_time_skew_20949ms': 1, 'quote_time_skew_15922ms': 1, 'quote_time_skew_12945ms': 1, 'quote_time_skew_6377ms': 1, 'quote_time_skew_19171ms': 1, 'quote_time_skew_15512ms': 1, 'quote_time_skew_11335ms': 1, 'quote_time_skew_23504ms': 1, 'quote_time_skew_15150ms': 1, 'quote_time_skew_26736ms': 1, 'quote_time_skew_20110ms': 1, 'quote_time_skew_13719ms': 1, 'quote_time_skew_8505ms': 1, 'quote_time_skew_21266ms': 1, 'quote_time_skew_14130ms': 1, 'quote_time_skew_8614ms': 1, 'quote_time_skew_5798ms': 1, 'quote_time_skew_23711ms': 1, 'quote_time_skew_18887ms': 1, 'quote_time_skew_24515ms': 1, 'quote_time_skew_18221ms': 1, 'quote_time_skew_11050ms': 1, 'quote_time_skew_5518ms': 1, 'quote_time_skew_17576ms': 1, 'quote_time_skew_15852ms': 1, 'quote_time_skew_5202ms': 1, 'quote_time_skew_26100ms': 1, 'quote_time_skew_17436ms': 1, 'quote_time_skew_9161ms': 1, 'quote_time_skew_22001ms': 1, 'quote_time_skew_15471ms': 1, 'quote_time_skew_6856ms': 1, 'quote_time_skew_20812ms': 1, 'quote_time_skew_15043ms': 1, 'quote_time_skew_8231ms': 1, 'quote_time_skew_19012ms': 1, 'quote_time_skew_9194ms': 1, 'quote_time_skew_6660ms': 1, 'quote_time_skew_29207ms': 1, 'quote_time_skew_18219ms': 1, 'quote_time_skew_27855ms': 1, 'quote_time_skew_13729ms': 1, 'quote_time_skew_9378ms': 1, 'quote_time_skew_37270ms': 1, 'quote_time_skew_20126ms': 1, 'quote_time_skew_13880ms': 1, 'quote_time_skew_8441ms': 1, 'quote_time_skew_24656ms': 1, 'quote_time_skew_12426ms': 1, 'quote_time_skew_6267ms': 1, 'quote_time_skew_22599ms': 1, 'quote_time_skew_31166ms': 1, 'quote_time_skew_6347ms': 1, 'quote_time_skew_18967ms': 1, 'quote_time_skew_19751ms': 1, 'quote_time_skew_12136ms': 1, 'quote_time_skew_5014ms': 1, 'quote_time_skew_12488ms': 1, 'quote_time_skew_45634ms': 1, 'quote_time_skew_26578ms': 1, 'quote_time_skew_9936ms': 1, 'quote_time_skew_23268ms': 1, 'quote_time_skew_14812ms': 1, 'quote_time_skew_8401ms': 1, 'quote_time_skew_21469ms': 1, 'quote_time_skew_14319ms': 1, 'quote_time_skew_7741ms': 1, 'quote_time_skew_20643ms': 1, 'quote_time_skew_16551ms': 1, 'quote_time_skew_8362ms': 1, 'quote_time_skew_20060ms': 1, 'quote_time_skew_13855ms': 1, 'quote_time_skew_43856ms': 1, 'XLK': 5, 'quote_time_skew_19359ms': 1, 'quote_time_skew_13527ms': 1, 'quote_time_skew_6550ms': 1, 'quote_time_skew_29699ms': 1, 'quote_time_skew_14099ms': 1, 'quote_time_skew_18022ms': 1, 'quote_time_skew_24177ms': 1, 'quote_time_skew_20369ms': 1, 'quote_time_skew_14928ms': 1, 'quote_time_skew_23074ms': 1, 'quote_time_skew_17970ms': 1, 'quote_time_skew_10261ms': 1, 'quote_time_skew_21161ms': 1, 'quote_time_skew_16067ms': 1, 'quote_time_skew_18805ms': 1, 'quote_time_skew_9556ms': 1, 'quote_time_skew_16246ms': 1, 'quote_time_skew_9141ms': 1}}.
Entries the admission gate could not decide: 0 (none).
- 2026-09-23T13:30:22.451769+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T14:43:17.789707+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True b2: premium stop: bid 0.31 is 51% below the 0.63 paid (limit 50%) ΓÇö theta/IV bleed the underlying stop cannot see ΓÇö selling at market
- 2026-09-23T16:49:46.112083+00:00 TechniquePlanError book=045d8c35b3f149628ea001ae90a58edb ours=True b2: premium stop: bid 0.22 is 51% below the 0.45 paid (limit 50%) ΓÇö theta/IV bleed the underlying stop cannot see ΓÇö selling at market
- 2026-09-23T19:14:46.307089+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:14:48.508225+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:14:50.557420+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:14:51.668648+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:14:52.773279+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:14:53.540481+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:14:54.334012+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:14:55.774497+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:14:56.924072+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:14:58.226797+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:14:58.526702+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:14:58.978311+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:14:59.775632+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:00.192805+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:00.715916+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:01.433475+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:01.597148+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:02.669560+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:02.852695+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:03.001880+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:03.044813+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:03.081527+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:03.142858+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:03.176879+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:03.218829+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:03.334593+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:03.361271+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:03.400376+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:03.620964+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:04.025725+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:04.044789+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:04.060743+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:04.099467+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:04.143051+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:04.178450+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:05.593487+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
- 2026-09-23T19:15:06.258820+00:00 TechniquePlanError book=07ef1e867cad4150bc81e072a8fd600a ours=True stale bars
