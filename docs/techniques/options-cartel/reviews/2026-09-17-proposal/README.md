# 2026-09-17 proposal package — Lane A (long base breakout), revision 3

Implementation desk handback for review. Read in this order: BOTTLENECKS.md (what happened, from
records, with the boundary-enforced D1 probe and the tape-revision finding), FUNNEL.md (every gate
and its outcome class), RULE-MATRIX.md (where each requirement comes from), PROPOSAL.md (the lane,
the coexistence contract, acceptance, plan).

## Review status

- Revision 1 (d7c226b): proceed with evidence and diagnostics; revise strategy before activation.
- Revision 2 (517ad48): attribution, calendars, provisional feasibility, structural-R labelling and
  legacy controls accepted; two P1 evidence defects blocked approval of the data repair.
- Revision 3 (this commit): fixes the two P1 defects and the coexistence contract, reruns the D1
  probe with boundary enforcement and artifacts, and records the tape-revision finding. Cleared
  scope only: evidence-tool corrections, corrected D1 probe, D3/D4/D5 diagnostics (separate
  commit), pure order-free Lane A evaluation (separate commit). No production baseline, live
  bucket eligibility, stop coverage or active ranking changed. No setting, arm, order or runtime
  process changed. Merge, deployment and Practice activation remain off.

## Branch, commit, revisions examined

- Worktree `C:\Cursor\zargar\.claude\worktrees\session-2026-09-17`, branch
  `claude/cartel-lane-a-proposal` on origin/main `731edbd` (v0.8.11). The revision-3 commit is the
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
python -m pytest tests/test_cartel_evidence_tool.py -q
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

1. For `volume_eligibility_v1`, which of the provider's documented condition exclusions should be
   applied identically to historical bars and live buckets? The probe shows `I` dominates, with
   `4`, `F`, `W`, `B` present; I propose taking the provider's published exclusion list verbatim
   and versioning it, rather than choosing per condition.
2. Defect 5: should D3 persist the full bucket inputs (15 minutes × OHLCV × source) with every
   journaled decision, or a content hash plus the measurements? Full inputs make reconstruction
   possible; the hash only proves difference. I lean to full inputs for `watch_only`, `triggered`
   and the two data refusals, bounded to the bucket.
3. Whether the arm tape's 15-minute truncation after a fill (APA) is intended; it limits any
   post-fill audit of the entry bucket to the stored, revised tape.
