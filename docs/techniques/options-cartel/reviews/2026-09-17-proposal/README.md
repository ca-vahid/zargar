# 2026-09-17 proposal package — Lane A (long base breakout), revision 5

Implementation desk handback for review. Read in this order: BOTTLENECKS.md (what happened, from
records, with the boundary-enforced D1 probe and the tape-revision finding), FUNNEL.md (every gate
and its outcome class), RULE-MATRIX.md (where each requirement comes from), PROPOSAL.md (the lane,
the coexistence contract, acceptance, plan).

## Review status

- Revision 1 (d7c226b): proceed with evidence and diagnostics; revise strategy before activation.
- Revision 2 (517ad48): attribution, calendars, provisional feasibility, structural-R labelling and
  legacy controls accepted; two P1 evidence defects blocked approval of the data repair.
- Revision 3 (a0d78a6): fixes the two P1 defects and the coexistence contract, reruns the D1
  probe with boundary enforcement and artifacts, and records the tape-revision finding. Cleared
  scope only: evidence-tool corrections, corrected D1 probe, D3/D4/D5 diagnostics (separate
  commit), pure order-free Lane A evaluation (separate commit). No production baseline, live
  bucket eligibility, stop coverage or active ranking changed. No setting, arm, order or runtime
  process changed. Merge, deployment and Practice activation remain off.

- Revision 4 (dd2f22e): verdicts on revision 3 were evidence fixes accepted, D3/D4/D5 and the
  Lane A evaluator "changes requested". This revision corrects them: complete Lane A population and
  preparation lineage with explicit book/workspace selection; old-planner outcome reported apart;
  hypothetical point-in-time feasibility from saved limits and the effective cap with every
  failure set preserved; the dropped-bar registry keyed by plan and session, eligibility-aware,
  pruned, bounded, duplicate-aware and failure-isolated; the collector's studies on one bounded
  worker (documented as a concurrency bound, not full cancellation). Frozen reports regenerated.
  Still no production baseline, live bucket eligibility, stop coverage or active ranking change;
  merge, deployment and Practice activation remain off.

- Revision 5 (this commit): offline evaluator findings closed for the stated scope; the three
  remaining D4 registry defects fixed with regressions (captured-snapshot persistence, forward-only
  rollover, throttled failed attempts) plus pruning against the active set so every retirement path
  is covered; replay artifacts compacted (~27 MB of formatted JSON replaced by readable summaries,
  compact evidence and reproducibility manifests); the conclusion made precise. D3 immutable capture
  and offline provider reconstruction are the next commits, not merge blockers. Lane A, the 1.5R
  filter and any altered volume eligibility stay inactive. Merge pending review of the diagnostic
  fixes; deployment and activation remain off.

## Branch, commit, revisions examined

- Worktree `C:\Cursor\zargar\.claude\worktrees\session-2026-09-17`, branch
  `claude/cartel-lane-a-proposal` on origin/main `731edbd` (v0.8.11). The revision-5 commit is the
  branch head; its SHA is in the handback message.
- Source reviewed at `731edbd`; runtime database `zargar` on 127.0.0.1:5433 read with read-only
  transactions; Alpaca SIP bars and trades read for three symbol-sessions with the main checkout's
  credentials (`--env-file`); artifacts in `evidence/` carry no credentials (checked).

## Revision 3: review item → change → where to verify

| Item | Change | Verify |
|---|---|---|
| P1 probe boundaries | trades filtered locally to `start <= t < end` (provider `end` is inclusive), nanosecond stamps handled; per-interval `verifiedAt` after each request; incomplete **bar** pagination or any error → `incomplete_evidence`; unprobed absent minutes → `unknown`; classification by the reported odd-lot condition with size statistics separate; compact credential-free artifact with request bounds, counts, conditions, sha256 of every response body | `tests/test_cartel_evidence_tool.py` (boundary test includes the exact-at-end and nanosecond cases); `evidence/alpaca-minutes-*.json`; BOTTLENECKS §8b |
| P1 "decision-time tape" | renamed `finalArmTapeReplay` and documented as a consistency check; `journaled` section (decisionHistory/signalHistory) is the authority; per-decision comparison table (reproduced or not, live vs replay measurements); per-minute value comparison between the arm's saved minutes and the stored rows | `replay e2e12438…`: QS final-arm-tape replay returns only `entry_window_closed`; stored-tape signal 3.08×/0.99 vs live 3.06×/0.88; 379/390 minutes differ in price or volume |
| README claim "both tapes reproduce … 0 provenance differences" | withdrawn; replaced by the measured comparison and the finding in BOTTLENECKS §8c (stored bars revised after decisions) | BOTTLENECKS §3, §6, §8c |
| P2 coexistence and capacity | `lane_a_focus` defaults 0 and bypasses selection, ranking and chain fetch entirely; fallback to the general plan when Lane A has no capacity or is not executable; pending items never held/managed and never reserve slots; feasibility states extended with `filtered_other` (first-failing-filter counts) and `no_chain` | PROPOSAL §3 |
| D1 answers | execution unchanged; separate versioned volume calculation `volume_eligibility_v1` evaluated offline first, no double counting; buckets with `trades_without_bar` stay non-executable; session-extreme coverage not touched (a protection); missing historical chain quotes = `unknown`, kept in the denominator, conclusions stop at the last supported stage | PROPOSAL §5 D1, §4 |

## Revision 5: review item -> change -> where to verify

| Item | Change | Verify |
|---|---|---|
| P2 drop lost during persistence | `flush` captures the entry's `version` before the await and marks only that version persisted; later drops (and duplicate-only changes) stay dirty and flush after the interval | `test_flush_marks_only_the_captured_snapshot_and_keeps_later_drops_dirty` |
| P2 backward rollover | `note` rejects a bar from an older session than the live entry (`olderSessionBars` counter) and rolls forward only | `test_registry_counts_distinct_minutes_and_duplicates_and_rolls_forward_only` |
| P2 failure throttle | every attempt records `lastAttemptAt`; a failed attempt is retried only after the interval | `test_flush_throttles_failed_attempts_and_never_raises` (two attempts 1 ms apart -> one call) |
| Retirement coverage | `flush` prunes entries whose plan is not in the caller's active set (`armed`/`paused`/`closing`), so the runtime's overridden disarm/expiry/closing paths are covered without per-path calls; explicit `retire` kept where the base observer pops rows | `test_flush_prunes_plans_outside_the_active_set_and_stays_bounded`; `CartelObserver._flush_drop_diagnostics` |
| Artifact size | compact JSON keeps per-session counts, non-bulk rows and bulk-stage symbol lists; a manifest records arguments, original run ids, populations and sha256 of both files | `lane-a/frozen-replay-*.json`, `lane-a/frozen-replay-*.manifest.json` (sizes below) |
| Conclusion wording | "zero strict qualifiers among the available frozen analyses"; 09-08 had 58 analyses with 3,032 industry-prefiltered listings unavailable | PROPOSAL 4b |

## Revision 4: review item -> change -> where to verify

| Item | Change | Verify |
|---|---|---|
| P1 evaluator population | population = every frozen analysis parented by the session's **original** run plus the analyses its rows cite (resumed runs reuse earlier analyses: 2,554 on 09-11, 2,013 on 09-15); one per symbol; Lane A's own gates (direction -> screen -> context -> base -> ceiling tests -> confirmed target -> distance floor) applied to all; old-planner outcome reported apart (`screen_or_context_rejected`, `old_planner_rejected`, `old_planner_blocked`, `old_planner_candidate:<status>`, `unavailable_evidence`, `prefiltered`, `missing_analysis`) | `cartel_lane_a_eval.py` (`population`, `classify_analysis`, `old_planner_outcome`); tests in `test_cartel_lane_a.py`; per-session "Old planner outcome" table in the reports |
| P1 lineage / book selection | `--portfolio` and `--workspace` are explicit (default the Options Cartel Practice book); `choose_original` = earliest run with a known market read that evaluated the universe; all runs listed as lineage; later shortlist statuses reported as **later recovery** per symbol, never merged | `choose_original` test; "Lineage" section of the reports (e.g. 09-09: original 03:37Z read `mixed`, the 04:42Z rerun read Moderate `long`) |
| P1 feasibility point-in-time / saved limits | snapshot must be dated the previous exchange session (nightly research job ~16:30 ET) else `unknown_stale`; limits from the preparation's saved `contract_policy`, budget and risk %; effective cap via `effective_cap` with the book equity last persisted before the run; labelled **hypothetical under stated assumptions** in code and reports | `effective_cap` test; report headers name the basis |
| P1 first-failure classification | every inspected contract keeps its full failure set; `over_budget` / `spread_blocked` require a contract whose only failure is premium / spread; otherwise `filtered_other` with `failureSets` counts | `test_feasibility_keeps_every_failure_and_reserves_single_cause_states_for_single_failures` (the reviewer's spread+OI+premium case) |
| Artifact vs handback (1/9 vs 2/8) | the earlier handback mis-summed two sessions; after the population fix the Moderate variant has 6 qualified: 1 `affordable` (CVNA), 5 `unknown_stale` - stated from the artifact | `lane-a/frozen-replay-moderate.md` |
| P2 registry rollover | entries keyed by `(run_id, session)`; a new session starts a fresh entry (journaled count 0) and drops the old one | `test_registry_counts_distinct_minutes_and_duplicates_per_plan_session_and_resets_on_rollover` |
| P2 registry growth | one live session per plan; `retire(run_id)` on disarm/expiry/removal; `max_entries` eviction of the least recently observed | `test_registry_prunes_retired_plans_and_stays_bounded` |
| P2 eligibility | a drop counts only for plans that were `armed`/`waiting` with the minute inside `opensAt..expiresAt` and the plan's sessions | `test_eligibility_requires_an_armed_waiting_plan_and_a_minute_inside_its_horizon` (old-session arrival included) |
| P2 duplicates | distinct dropped minutes vs duplicate deliveries counted separately | same rollover test |
| P2 persistence failures | `DropRegistry.flush` catches persistence errors per plan, counts them on the entry and never raises; the observer wraps it again | `test_flush_isolates_persistence_failures_and_only_marks_successes` |
| P2 restart | in-memory registry starts empty; the last persisted summary stays on the arm row (`state.barDrops`) and is shown when no live entry exists | same flush test (fresh registry); `observer.detail` |
| P2 study workers | a dedicated one-worker `ThreadPoolExecutor` bounds concurrent research studies; documented that a timed-out awaiting task does not cancel a running study | `profitability_research._study`; module comment |

## Cleared implementation delivered after revision 3 (separate commits)

| Commit | Scope | What it changes | Evidence |
|---|---|---|---|
| "Cartel D3/D4/D5 diagnostics" (e162858) + revision-4 corrections | diagnostics only | D3: `read_entry` records `known` on data refusals and `bucketInputHash` on watch_only/triggered - decisions unchanged. D4: `DropRegistry` as above; the profitability collector yields between candidates and runs its studies on the bounded worker. D5: preflight `expression.spread` = cents, percent of mid, dollars per unit and for the sized quantity | `tests/test_cartel_diagnostics.py` (8); `test_options_cartel_observer.py`, `_runtime.py`, `_profitability_research.py`, `_execution.py`, `_pending_integrity.py`, `_entry.py` green on `zargar_test_cartel` |
| "Cartel Lane A pure evaluation" (7ffd689) + revision-4 corrections | order-free, unwired | `lane_a.py` (pure reviewer, inactive 1.5R experiment, feasibility classifier with full failure sets, `effective_cap`) and `tools/cartel_lane_a_eval.py` (complete-population frozen replay, lineage, later recovery, hypothetical feasibility) | `tests/test_cartel_lane_a.py` (9); `lane-a/frozen-replay-strict.md`, `lane-a/frozen-replay-moderate.md` + JSON; result in PROPOSAL 4b |

Frozen replay headline (corrected population, 2026-09-08 -> 09-17, Options Cartel Practice book):
strict basis **0** Lane A qualifiers (only 09-08 read strict-bullish; SPCX and ZIM had the ceiling
tested once). Moderate-read variant **6** qualifiers (09-10: ABUS, BGC, CVNA, FUTU, GROY; 09-14:
OII), all with structural R below 1.5 (five below 0.5), 1 `affordable` (CVNA), 5 `unknown_stale`.
Populations 3,056-3,081 analyses per session (58 on 09-08 under the then-strict industry gate,
3,032 `prefiltered`). The old planner rejected 2-13 context-passing names per session; they are in
the population now.

## Reproduction

From `backend/` with the main checkout's interpreter. A worktree has no `.env`; pass the database
URL (or `--env-file`) explicitly. Database commands force `default_transaction_read_only = on`;
`alpaca-minutes` makes read-only market-data requests only.

```
set U=postgresql+asyncpg://zargar:zargar@127.0.0.1:5433/zargar
python -m zargar.tools.cartel_evidence --database-url %U% plan e30a2db9c9aa72602410dfbce37a0d16     # APA
python -m zargar.tools.cartel_evidence --database-url %U% plan e2e12438418bc82ff34c3b2c5a7f365b     # QS
python -m zargar.tools.cartel_evidence --database-url %U% plan 341d97737adc3ca0d85ecfc2b576e02f     # TTWO
python -m zargar.tools.cartel_evidence --database-url %U% plan 9be071fc7c2f039534d6a74d666ed863     # PWR 09-17
python -m zargar.tools.cartel_evidence --database-url %U% plan d4ba82cd110834013b45510c2a86a3b5     # APTV 09-16
python -m zargar.tools.cartel_evidence --database-url %U% plan 8ba793383b07796921c7c1bf11574559     # APTV 09-17
python -m zargar.tools.cartel_evidence --database-url %U% replay e2e12438418bc82ff34c3b2c5a7f365b   # QS: journaled vs replays
python -m zargar.tools.cartel_evidence --database-url %U% replay d4ba82cd110834013b45510c2a86a3b5   # APTV 09-16: partial evidence
python -m zargar.tools.cartel_evidence --database-url %U% replay e30a2db9c9aa72602410dfbce37a0d16   # APA
python -m zargar.tools.cartel_evidence --database-url %U% replay 341d97737adc3ca0d85ecfc2b576e02f   # TTWO: never armed
python -m zargar.tools.cartel_evidence --database-url %U% preparation ed6d9da2da1d4f06981ad43b6d0edfe5
python -m zargar.tools.cartel_evidence --database-url %U% preparation cee03dd791ce404ab322378626339849
python -m zargar.tools.cartel_evidence --database-url %U% preparation bc78bc51f42a46568b255568ff052428
python -m zargar.tools.cartel_evidence --database-url %U% buckets APTV 2026-09-16 --plan d4ba82cd110834013b45510c2a86a3b5
python -m zargar.tools.cartel_evidence --database-url %U% coverage PLAB
python -m zargar.tools.cartel_evidence --database-url %U% quotes e2e12438418bc82ff34c3b2c5a7f365b
python -m zargar.tools.cartel_evidence --database-url %U% latency --since 2026-09-08
python -m zargar.tools.cartel_evidence --env-file <main>\backend\.env alpaca-minutes PLAB 2026-09-16 --limit 44 --artifact-dir <pkg>\evidence
python -m zargar.tools.cartel_evidence --env-file <main>\backend\.env alpaca-minutes LZB 2026-09-16 --limit 55 --artifact-dir <pkg>\evidence
python -m zargar.tools.cartel_evidence --env-file <main>\backend\.env alpaca-minutes PWR 2026-09-17 --limit 17 --artifact-dir <pkg>\evidence
python -m zargar.tools.cartel_lane_a_eval --database-url %U% --portfolio 0b48ed48de2f4030b49942b52858356d --start 2026-09-08 --end 2026-09-17 --market-basis strict --out-dir <pkg>\lane-a
python -m zargar.tools.cartel_lane_a_eval --database-url %U% --portfolio 0b48ed48de2f4030b49942b52858356d --start 2026-09-08 --end 2026-09-17 --market-basis moderate --out-dir <pkg>\lane-a
python -m pytest tests/test_cartel_evidence_tool.py tests/test_cartel_diagnostics.py tests/test_cartel_lane_a.py -q
set ZARGAR_TEST_DATABASE_URL=postgresql+asyncpg://zargar:zargar@127.0.0.1:5433/zargar_test_<yours>
python -m pytest tests/test_options_cartel_entry.py tests/test_options_cartel_observer.py tests/test_options_cartel_execution.py tests/test_options_cartel_runtime.py tests/test_options_cartel_profitability_research.py tests/test_options_cartel_pending_integrity.py -q
```

Values the commands must reproduce (details in BOTTLENECKS.md):

- APA: triggered 09-14 13:45:00Z at 1.97× / 0.92, stop 45.56, filled 3.30, stop exit 2.7095, net
  −61.13; 39 events by id; both replays reproduce the trigger; the arm tape holds 15 minutes.
- QS: three preflights failing only `entry_contract_spread` at 1.86/2.39 = $0.53 = $106 for qty 2
  (24.9%); journaled watch_only 18:15 (3.06×/0.61), triggered 19:00 (signal 3.06×/0.88);
  final-arm-tape replay → `entry_window_closed` only; stored-tape replay → signal 3.08×/0.99;
  379/390 minutes differ in price or volume, 0 in source label.
- APTV 09-16: journaled untrusted buckets 12:15/13:30/14:00 ET with partial lows 43.92/43.81/43.76
  above the 43.55 trigger; watch_only 15:00 ET at 1.32×; 386/390 minutes differ in value.
- TTWO: stored-tape replay `watch_only` 1.01× at 09:45 ET then `target_passed`; no arm tape.
- PWR: lowest otherwise-eligible ask 24.4 at 01:39:51Z; readiness reasons from 15:45:04Z /
  15:46:05Z.
- Latency: 84 decisions since 09-08, p50 1.4 s, max 60.1 s, none over 120 s.
- `alpaca-minutes` (2026-09-18 01:35–01:36Z): PLAB 44/44, LZB 55/55, PWR 17/17 absent minutes
  `trades_without_bar`, 0 `verified_no_trades`, 0 `unknown`, 0 trades dropped at the boundary;
  odd-lot condition on every trade in 32/44, 51/55, 15/17 minutes. Artifacts in `evidence/`.

Results on this desk: all commands ran on 2026-09-18 between 01:30Z and 01:45Z with the values
above; seven pure tests pass. No production code changed in this commit, so no other suite ran.

## Confirmed defects

1. **Planning admits setups with negligible room** — the only planning-time room check is a 0.5%
   distance; structural R is never gated (`automatic_plans.py:155`). Response: inactive
   experimental filter, measured first.
2. **Data refusals record no measurements** (`entry.py:75-87`). Response: D3 diagnostic (next
   commit); the evidence tool reconstructs known partial values meanwhile.
3. **Contract feasibility after ranking, top 25 only** (`preparation.py:478-482, 557-558`):
   candidates with no contract passing the saved limits consume the checking budget and watcher
   work. Capacity unaffected. Response: D2 provisional feasibility (proposal only).
4. **Provider minute semantics vs the baseline sample rule and live provenance rule.** Absent SIP
   1Min bars are minutes whose only trades were ineligible for aggregation (probe: odd lots).
   Response: D1 classification recorded, offline `volume_eligibility_v1` comparison before any
   production change.
5. **Decision inputs are not persisted at decision time** — the arm's minutes are overwritten as
   the tape grows and `observeAfter` moves; the stored bars are revised afterwards. Exact
   reconstruction of a past decision is therefore impossible from records (BOTTLENECKS §8c).
   Response: D3 extends to recording the bucket's input values with each decision.
6. Cosmetic: registry tabs vs page; `techniques.options_cartel.min_one_contract` unused by Cartel.

## Hypotheses (supported by records, not established)

1. Streaming exchange bars judged live carry lower volume than the later-refreshed stored bars
   (QS 09:30 ET 116,007 vs 172,764), so the live 1.5× rule and the provider-built baseline are
   not on one volume basis. Quantify in the offline comparison before drawing a conclusion.
2. The minute/daily volume ratio being similar for liquid and thin names suggests a systematic
   provider-pair basis difference rather than truncation — pending matched analysis.
3. The first-bucket session-extreme stop is inside one day's normal range for an ADR > 3% screen
   (APA 1.46%). One case; the labelled stop observations measure it.
4. Single-contract fills cannot follow the exit policy; Lane A reports the share.

## Unresolved questions for the reviewer

1. For the D3 decision bundle, the proposal now specifies inputs plus hash, previous crossing state,
   `observeAfter`, plan/policy/baseline versions, cutoff and observation times, and the session
   context as an immutable reference. Should the bundle be journaled (an events row per decision)
   or stored in its own table keyed by `(run_id, bucket_end)` with the events row carrying only the
   hash? The events table is append-only and large; a table keeps it reconstructible without
   bloating the journal.
2. The Moderate-read variant is where the current planner's long arms come from. Is it acceptable
   to keep reporting it beside the strict definition as an information-only column, or should the
   evaluator report strict only to avoid any appearance of endorsing the Moderate read for Lane A?
3. For `volume_eligibility_v1`, do you want the field-specific matrix validated first by
   reconstructing the provider's own minute-bar volume from the trade tape within tolerance for the
   three probed sessions (PLAB, LZB, PWR), before any Zargar-side calculation is compared?
