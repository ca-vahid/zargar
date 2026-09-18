# 2026-09-17 proposal package — Lane A (long base breakout), revision 2

Implementation desk handback for review. Read in this order: BOTTLENECKS.md (what happened,
from records, with the D1 probe), FUNNEL.md (every gate and its outcome class), RULE-MATRIX.md
(where each requirement comes from), PROPOSAL.md (the lane, coexistence, acceptance, plan).

## Review status

- Revision 1 (commit d7c226b) verdict: proceed with evidence and diagnostic corrections; revise
  the strategy proposal before activation. Permission granted for evidence-tool corrections,
  read-only D1 investigation and bounded refusal/latency diagnostics only.
- Revision 2 (this commit) delivers exactly that scope. No strategy-changing coverage repair, no
  contract exclusion, no Lane A activation. No production behaviour, setting, arm, order or
  runtime process changed.

## Branch, commit, revisions examined

- Worktree `C:\Cursor\zargar\.claude\worktrees\session-2026-09-17`, branch
  `claude/cartel-lane-a-proposal` on origin/main `731edbd` (v0.8.11). The revision-2 commit is
  the branch head; its SHA is in the handback message.
- Running app when revision 1 was written: v0.8.09, build `dd525de` (2026-09-16 22:00 PT), which
  already contained every Cartel commit through `c99501b` (PR #189, merged 2026-09-17 01:18Z).
- Source reviewed at `731edbd`: `backend/zargar/techniques/options_cartel/`,
  `api/routes_options_cartel.py`, the Cartel documents, `docs/PLATFORM-RULES.md`.
- Runtime database read: `zargar` on 127.0.0.1:5433 (read-only transactions). Market data read:
  Alpaca SIP bars and trades for three symbol-sessions (§ D1 below), using the main checkout's
  credentials via `--env-file`; nothing was written anywhere.

## What changed in revision 2 (review item → change → evidence)

| Review item | Change | Where to verify |
|---|---|---|
| Orders/positions matched by symbol prefix | attribution by identity only: order tag `cartel_run:<id>` or the arm's recorded order id; positions from the adoption record; exit orders from the position; events by those aggregate ids | `plan e30a2db9…` shows 39 events, both APA orders and the position, all linked by id |
| Bucket crossing carried state through partial/untrusted buckets | display buckets mark `partial` (missing and untrusted minutes named), judge no crossing, reset state as production does; `replay` runs the engine's `read_entry` over the decision-time tape and the stored tape and lists provenance differences | `buckets APTV 2026-09-16 --plan d4ba82cd…`; `replay d4ba82cd…` |
| Coverage joins by month/day; older cache rows overwrote newer | full ISO date keys; daily volume from the newest 1d cache row only; absent minutes against the exchange-calendar session length | `coverage PLAB` |
| Fixed EDT and 390 minutes | `marketstructure.sessions.session_bounds` + America/New_York everywhere; early closes handled (test covers 2026-11-27) | `tests/test_cartel_evidence_tool.py` |
| Missing-data refusals without known measurements | `replay` attaches `partialEvidence` (minutes present/missing/untrusted, partial high/low/last close/volume, slot baseline) and names the fields not computed | `replay d4ba82cd…` |
| "$210/$620 stock cannot have an affordable put" | replaced with: no contract in the inspected snapshots passed all configured limits; TTWO's cheaper contract failed spread; delta floor 0.25 | BOTTLENECKS §4, §5; FUNNEL D3 |
| Unaffordable candidates "consume focus slots" | corrected: they consume the 25-candidate checking budget and watcher work; capacity counts occupied arms and positions | BOTTLENECKS §1, FUNNEL closing note, PROPOSAL §2 |
| Spread diagnostics | absolute spread, dollars per contract and dollars for the preflight quantity beside the percent (QS: $0.53, $106 for 2) | `plan e2e12438…` PREFLIGHT lines; `quotes e2e12438…` |
| D1 classification | probe implemented and run: `verified_no_trades` / `trades_without_bar` / `incomplete_evidence`, same SIP feed, complete pagination, [start,end) boundaries, conditions recorded, verification time | `alpaca-minutes PLAB 2026-09-16`; results in BOTTLENECKS §8b |
| (1−p)^15 and volume-ratio conclusions | labelled illustrative / hypothesis pending matched-provider, matched-session analysis | BOTTLENECKS §8 |
| Causal snapshot | per-input source time, availability time and decision cutoff specified; run `created_at` explicitly not an availability time; missing point-in-time evidence named `unknown` | PROPOSAL §4; `preparation` output shows logical start vs market-inputs-as-of vs attemptedAt |
| Legacy controls vs Lane A examples | separated: APA = legacy execution control; QS/TTWO/PWR/APTV = diagnostics only; Lane A acceptance = dated long `base` cases from app history (CPRT, DRAM 09-09; CVNA 09-10; NOV 09-14) and source-dated examples, qualification an outcome not a requirement | PROPOSAL §4 |
| Coexistence and capacity | Lane A supplements the existing planner in the same run; one plan per symbol; `lane_a_focus` slots ranked first (proposed 2 of 5), rollback = 0; lane identity snapshotted on run, plan, arm, order tags, position extras | PROPOSAL §3 |
| Paired stop study causality | two labelled observations: `hindsight_daily_low` (hindsight-only, protected nothing) and `close_switch` (session extreme until the close, then the daily low); compared only from the close onward | PROPOSAL §2 |
| 1.5R basis and status | trigger-to-reviewed-invalidation; inactive experimental filter (`lane_a_min_planning_r` null); structural R, executable R and option dollar risk as three fields | PROPOSAL §2, RULE-MATRIX |
| Blanket suite claim | replaced by focused tests named per acceptance criterion, on this desk's database `zargar_test_cartel` | PROPOSAL §4 |

## Reproduction

From `backend/` with the main checkout's interpreter. A worktree has no `.env`; pass the database
URL (or `--env-file`) explicitly. Database commands force `default_transaction_read_only = on`;
`alpaca-minutes` makes read-only market-data requests only.

```
set U=postgresql+asyncpg://zargar:zargar@127.0.0.1:5433/zargar
python -m zargar.tools.cartel_evidence --database-url %U% plan e30a2db9c9aa72602410dfbce37a0d16     # APA (attribution by id, spread cost)
python -m zargar.tools.cartel_evidence --database-url %U% plan e2e12438418bc82ff34c3b2c5a7f365b     # QS
python -m zargar.tools.cartel_evidence --database-url %U% plan 341d97737adc3ca0d85ecfc2b576e02f     # TTWO
python -m zargar.tools.cartel_evidence --database-url %U% plan 9be071fc7c2f039534d6a74d666ed863     # PWR 09-17
python -m zargar.tools.cartel_evidence --database-url %U% plan d4ba82cd110834013b45510c2a86a3b5     # APTV 09-16
python -m zargar.tools.cartel_evidence --database-url %U% plan 8ba793383b07796921c7c1bf11574559     # APTV 09-17
python -m zargar.tools.cartel_evidence --database-url %U% replay e2e12438418bc82ff34c3b2c5a7f365b   # QS: both tapes
python -m zargar.tools.cartel_evidence --database-url %U% replay d4ba82cd110834013b45510c2a86a3b5   # APTV 09-16: partial evidence
python -m zargar.tools.cartel_evidence --database-url %U% replay 341d97737adc3ca0d85ecfc2b576e02f   # TTWO: stored tape only (never armed)
python -m zargar.tools.cartel_evidence --database-url %U% preparation ed6d9da2da1d4f06981ad43b6d0edfe5   # 09-16
python -m zargar.tools.cartel_evidence --database-url %U% preparation cee03dd791ce404ab322378626339849   # 09-17 nightly
python -m zargar.tools.cartel_evidence --database-url %U% preparation bc78bc51f42a46568b255568ff052428   # 09-17 last resume
python -m zargar.tools.cartel_evidence --database-url %U% buckets APTV 2026-09-16 --plan d4ba82cd110834013b45510c2a86a3b5
python -m zargar.tools.cartel_evidence --database-url %U% coverage PLAB
python -m zargar.tools.cartel_evidence --database-url %U% quotes e2e12438418bc82ff34c3b2c5a7f365b
python -m zargar.tools.cartel_evidence --database-url %U% latency --since 2026-09-08
python -m zargar.tools.cartel_evidence --env-file <main checkout>\backend\.env alpaca-minutes PLAB 2026-09-16 --limit 40
python -m zargar.tools.cartel_evidence --env-file <main checkout>\backend\.env alpaca-minutes LZB 2026-09-16 --limit 30
python -m zargar.tools.cartel_evidence --env-file <main checkout>\backend\.env alpaca-minutes PWR 2026-09-17 --limit 30
python -m pytest tests/test_cartel_evidence_tool.py -q
```

Values the commands must reproduce (details in BOTTLENECKS.md): APA triggered 09-14 13:45:00Z
at 1.97× / 0.92, stop 45.56, filled 3.30, stop exit 2.7095, net −61.13, 39 events by id; QS three
preflights failing only `entry_contract_spread` at 1.86/2.39 = $0.53 = $106 for qty 2 (24.9%),
`replay` reproduces watch_only 18:15 / triggered 19:00 on both tapes with 0 provenance
differences; APTV 09-16 replay shows the three untrusted buckets with partial lows 43.92 / 43.81 /
43.76 above the 43.55 trigger and the 15:00 ET watch_only at 1.32×; TTWO stored-tape replay
`watch_only` 1.01× at 09:45 ET then `target_passed`; PWR lowest otherwise-eligible ask 24.4 at
01:39:51Z, readiness reasons from 15:45:04Z / 15:46:05Z; latency 84 decisions, p50 1.4 s, max
60.1 s, none over 120 s; `alpaca-minutes`: PLAB 40/40, LZB 30/30, PWR 17/17 absent minutes
classified `trades_without_bar`, none `verified_no_trades`.

Results on this desk: every command above ran on 2026-09-18 between 00:00Z and 00:30Z with the
values stated; the pure tests pass (3). The Alpaca probe results are dated 2026-09-18 00:15Z and
reflect the provider's tape at that time.

## Confirmed defects

1. **Planning admits setups with negligible room.** The only planning-time room check is a 0.5%
   first-target distance; structural R is computed and never gated (PWR 0.075, TTWO 0.28;
   `automatic_plans.py:155`). Proposed response is an inactive experimental filter, not a rule.
2. **Data refusals record no measurements** (`entry.py:75-87`): `untrusted_confirmation` and
   `missing_bucket` carry nothing; the evidence tool now reconstructs known partial values from
   the tape, and D3 proposes recording them at decision time.
3. **Contract feasibility is checked after ranking and only for the top 25**, so names with no
   contract passing the saved limits consume the checking budget and watcher work all day
   (`preparation.py:478-482, 557-558`). Capacity (focus slots) is unaffected.
4. **Provider minute semantics vs the baseline sample rule.** Alpaca SIP 1Min bars are absent for
   minutes whose only trades were ineligible for aggregation (probe: odd lots). The baseline
   rule treats such minutes as missing data and discards the sample; the live provenance rule
   treats the quote-sampled stand-in as untrusted. Both are consistent with their design; the
   design did not anticipate this provider behaviour. Any change waits for D1's class-by-class
   definition (PROPOSAL §5).
5. Cosmetic: registry tabs differ from the page; `techniques.options_cartel.min_one_contract` is
   never read by Cartel's sizing.

## Hypotheses (supported by records, not established)

1. The minute-volume/daily-volume ratio being similar for liquid and thin names suggests the
   provider pair's volume bases differ systematically rather than absent minutes truncating
   volume — pending matched-provider, matched-session analysis.
2. The session-extreme stop at the first bucket is inside one day's normal range for an
   ADR > 3% screen (APA 1.46%). One case; the labelled stop observations measure it.
3. Single-contract fills cannot follow the exit policy; with a $500 budget most fills will be
   single contracts. Lane A reports the share.
4. Bearish sessions dominated 09-15 → 09-17; the long method has not been exercised since APA.

## Unresolved questions for the reviewer

1. Odd-lot trades: for the 1.5× same-slot rule, should odd-lot shares count in both the baseline
   and the live bucket (consistent with consolidated volume) or be excluded in both (consistent
   with the provider's bar aggregation)? Either is defensible; mixing them is not. D1 needs this
   decision before it changes a single sample.
2. `trades_without_bar` minutes have prices only from ineligible trades. Should a bucket
   containing such a minute be judged on the bars of its other 14 minutes (with the minute's
   shares added to volume), or stay unjudged as today? The proposal defaults to the former for
   volume only and the latter for OHLC/crossing, and asks for your view.
3. For the frozen replay of 09-08 → 09-17 (O1), planning-time chain quotes were not recorded
   before 2026-09-16; feasibility states for earlier sessions will be `unknown`. Is that
   acceptable for the before/after, with the denominator unchanged?
