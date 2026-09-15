# EM review — Delivery A response (2026-09-14)

Reviewer packet: `DEV-TEAM-HANDOFF-2026-09-14.md` (audited baseline `fa1f797`, runtime 0.7.71). This
response covers FIX-01..06 plus the FIX-11 quote-confirmation policy decision the packet asked to be made
explicit. Implemented on branch `claude/technique-review-trade-plan-fbb9ba` (EM desk), merged with
`origin/main` at the time of writing; the exact commit is in the git log under this file's date.

## Baseline reproduction on our HEAD before the changes

The three reviewer files were adopted unchanged into `backend/tests/` as `test_em_review_execution.py`,
`test_em_review_evidence.py`, `test_em_review_preopen.py` (originals kept under
`docs/techniques/enhanced-market/reviews/2026-09-14-regressions/` in the reviewer checkout; the ZIP
manifest carries their hashes). Result on our HEAD (which is `fa1f797` + 79 commits): **16 failed, 4 passed** -
the packet's recorded result.

## After

```
tests/test_em_review_execution.py tests/test_em_review_evidence.py tests/test_em_review_preopen.py
tests/test_execution_exits.py tests/test_scratch_rule.py tests/test_method_change_c1_c5.py
44 passed
```
Database: `zargar_test_em` on 127.0.0.1:5433 (this desk's private DB, never the shared one). Broader suites
run on the same change: `test_technique_arming.py`, `test_tip_runner.py`, `test_platform_phase3.py`,
`test_technique_lifecycle.py`, `test_technique_review.py`, `test_restart_entry_recovery.py`: **115 passed** (on
`zargar_test_em2`, 11 minutes). Two of these had failed on `origin/main` before this change
(`test_native_mleg_failure_falls_back_to_sequencing`, `test_every_journaled_kind_has_a_contract`); both pass now.

## What changed, per FIX

| FIX | files | change | tests |
|---|---|---|---|
| 01 | `execution/planrunner.py::_enter` | the final instrument decision sets `trade.instrument` and `trade.multiplier` together: shares fallback -> 1.0, options -> 100.0; nothing downstream infers the multiplier from the arm's requested instrument | both `test_shares_fallback_*` |
| 01 repair | `tools/em_reconcile_fallback.py` (new), `research/events_contract.py::TechniqueTradeCorrected` | dry-run manifest (run/trigger, expected state hash, entry/exit order ids, old/new multiplier and realized P&L, fills, halt old/new, reason); `--apply MANIFEST` is idempotent (skips already-corrected rows, refuses rows whose state changed since the dry run), appends a correction event per trade, never edits original events, never resumes paused plans | manual dry run, manifest attached below |
| 02 | `execution/exits.py::plan_exit` | for the one/two-contract full-exit policy the rung walk advances through rungs that need no order in the same bar and exits in full when the selected target is reached in that observation; a single advance is still handed to the caller; only a confirmed fill closes the position (unchanged) | both same-bar TP2 cases, existing `test_single_contract_option_exits_in_full_at_tp2` unchanged |
| 03 | `planrunner.py::_size_contracts`, `_enter` | re-price on the live NBBO BEFORE sizing and re-judge the spread on that quote; the risk budget is a bound - a contract whose premium stop exceeds it sizes to 0 and the fire is skipped with reason `size_zero` (journaled); the old floor is now the explicit knob `execution.min_one_contract` (default off); the tip technique's premium-budget floor and fixed `contracts` are untouched | `test_contract_risk_sizing_can_refuse_one_unaffordable_contract`, `test_final_reprice_resizes_before_submission` |
| 04 | `technique/arming.py::preopen_check` | the pre-open verdict uses the tracker's own direction-aware predicates (bounce/reject: through the stop, past the entry, by direction; break kinds: past the entry by direction); replan only when every eligible trigger is dead | all six parity cases |
| 05 | `planrunner.py::Trade`, `_restore_trades`, `_fire_rest`, TriggerFired payload | `critic`, `critic_advisory`, `errors`, `retries` round-trip through restore; new `critic_disposition` (`allowed` / `advisory` / `vetoed` / `timeout-allowed` / `error-allowed` / `not-run`) persisted and journaled next to the model's opinion and the effective `criticMode` | four restore-field cases |
| 06 | `marketstructure/outcome.py` | `plan_from_contract` / `plan_from_candidate` carry `direction`; `same_plan` compares direction, entry, stop and the full target list | both short-path cases, target-identity case |
| 11 policy | `planrunner.py::on_quote_watch` | **decision:** `quote_exit_polls` counts distinct quote observations (by the quote's source timestamp); polling the same cached print twice is one observation. Emergency exits are not delayed: a fresh print every poll still confirms in `quote_exit_polls` polls | `test_premium_stop_does_not_confirm_the_same_cached_quote_twice` |

## Design decisions recorded (as the packet asked)

- **Minimum-one sizing:** the risk budget is a bound. Zero contracts is a valid, journaled answer (`size_zero`).
  The former floor is preserved as an opt-in knob (`execution.min_one_contract`) for whoever wants learning-mode
  sizing back; EM does not set it.
- **Quantity-dependent R:R:** not changed in this delivery. R2 remains the plan-level reward:risk to the gate
  target. The packet's request to report the reward at the actual quantity/exit policy alongside it belongs to
  FIX-10's measurement work; recorded as open.
- **Quote confirmation:** distinct-observation policy, above.
- **Chase cap:** unchanged (`entry_limit_cap`, the never-chase cap); repricing now happens before sizing, so a
  cheaper ask reduces nothing and a dearer ask reduces quantity rather than raising the risk.

## Reconciliation manifest (FIX-01, dry run)

Affected records on the live database (EM Practice `045d8c35...`): five `technique_armed` trade projections
carry `instrument: shares` with `multiplier: 100`. Four never filled (USO b1/b2, SWKS b1/b2: realized 0,
no orders - the multiplier field is corrected, nothing else changes). One is the HPQ case:

| run | trigger | old realized | new realized | daily limit | halt old | halt new |
|---|---|---|---|---|---|---|
| `4d46f318` HPQ b1 | buy 100 @ 34.77; tp1 30 @ 34.803; stop 70 @ 34.6531 | -719.30 | **-7.193** | 397.19 | true | false |

The plan was disarmed at 09:52 ET with reason "loss halt" on the false figure. The manifest lists it under
`falseHalts`; applying the manifest corrects the projection and journals `TechniqueTradeCorrected`; it does
NOT re-arm the plan (the session is over). The EM Practice book's cash was never wrong - the sim book fills at
share prices; only the trade projection and the halt judgement carried the x100.

Apply command (run by a human after review, from the backend directory with the runtime DB URL):
`python -m zargar.tools.em_reconcile_fallback --apply <manifest.json>`. Not applied in this delivery.

## FIX-04 replacement audit (2026-09-14 journal)

Twelve pre-open rows on 09-14 marked a short `gapped_past` with the pre-market print between entry and stop
and requested a replacement: SPY, IBIT, NKE, UNH, DIA, XLF, XLU, TLT, IWM, CVNA (the packet's ten,
breakdowns, gapR 0.01-0.48) plus USO r3 and BSX r2 (rejects; gapR 5.67 and 5.22, so `gap_void` would have
voided them anyway - the verdict label was wrong, the outcome was not). Under the corrected predicate the ten
breakdowns would have stayed pending. Whether any of them would have fired or paid is unmeasured and not
claimed.

## FIX-06 affected history

No historical full-analysis outcome was scored from a short contract without direction: the outcomes table
holds 12 `candidate`-source rows, none short, and no `analysis`/`contract`-source rows. Nothing to recalculate.

## Scope

Correctness fixes only. No risk limit, critic policy, auto-arm rule or trading threshold changed. New knob
`execution.min_one_contract` defaults off (EM), which is the policy change the packet asked to be explicit.
No production data was modified (dry run only).

## Known limitations / next evidence

- FIX-02 covers the decision function; the "restart while an exit is pending" and "failed/ambiguous ACK" cases
  rely on the existing fill-confirmation path (`on_order_update`) and were not given new integration tests here.
- FIX-03's original repricing reproduction checks a constructed intent with submission mocked, as the packet
  notes; no broker-fill integration test was added.
- FIX-05 journals the disposition from this deploy forward; older TriggerFired rows keep only `critic` and
  `verdictAfterCritic`, and their disposition is reconstructed as `unknown` (not relabelled).


---

# Follow-up after the re-review (`2026-09-14-delivery-a-rereview.md`), same day

Deployment of the combined change was HELD as asked (the deploy watcher was stopped at 11:59 PT before it
fired; the engine was not restarted; the manifest was not applied). The 11 new boundary cases were adopted
unchanged as `tests/test_em_review_da_execution.py` and `tests/test_em_review_da_reconcile.py`: **11 failed** on
the previous head, **11 pass** now; the full reviewer group is 55 passing.
Broader suites on the follow-up (arming, tip runner, platform phase 3, lifecycle, review, restart recovery,
technique API, walk-forward): **170 passed** on `zargar_test_em2` (11m40s). Commit `6aa489c` (follow-up), merged
head `f7c6d3a`; `/api/health` will report `build: 6aa489c`-or-later once deployed.

| DA | correction | where |
|---|---|---|
| 01 | one admission function (`_admit_option_entry`: T5.3/T5.4 warning skips, premium caps, REMAINING daily-loss budget) runs on the pick and again on the final price and quantity immediately before dispatch; method-specific quality lives behind a new hook `rejudge_contract` (generic runner: spread only, `execution.spread_warn_pct`; EM overrides with T5.4 + T5.3 IV) - the direct EM import is gone | `planrunner.py`, `technique/arming.py` |
| 02 | `_manage` never advances a rung while `pending_exit_qty > 0`; a cancelled exit leaves the target unexecuted, and the next touch sends the full TP2 | `planrunner.py::_manage` |
| 03 | the repair builds an independent deep copy and assigns it (ORM history sees the change); the `TechniqueTradeCorrected` receipt is journaled BEFORE the row commits, so an audit failure commits nothing | `tools/em_reconcile_fallback.py` |
| 04 | items are grouped by plan and applied as one conditional row transition; list and dict projections; exact replay reports `already_applied`; the corrected value is recomputed from the fill records and must match the manifest; plan aggregate `realizedPnl` recomputed; portfolio/technique checked when present; commissions read from the exit records; live (armed/paused) rows are skipped unless `--include-live` after quiescing | same |
| 05 | confirmation is forward-only: an observation counts only when its source timestamp is strictly newer than the last counted one; a breach that clears resets the sequence; the underlying quote-stop and emergency paths are unchanged | `planrunner.py::on_quote_watch` |
| 06 | `execution.min_one_contract` registered (False) with explicit per-desk values: EM False; Tips, Team2, Options Cartel True (their behaviour unchanged - their call to flip); `execution.spread_warn_pct` registered | `settings_service.py` |
| 07 | `same_plan` includes `entry.basis`; `promote` reuses a prior read only under the same variant overlay (`config.overrides.thresholds`) and builds a fresh read with `thresholds_override=variant` | `outcome.py`, `technique/service.py` |
| 08 | an exhausted critic failure budget sets and journals `critic_disposition = failure-budget-paused` before the fire stops | `planrunner.py::_fire_rest` |

Build identity: `/api/health` now reports `build` = the checkout's short commit SHA (`ZARGAR_BUILD` overrides),
so the corrected release is distinguishable from the audited 0.7.71 without a version bump.

Corrections to the earlier response: ten shorts were consequentially replaced on 09-14 (pending-break error);
the two reject rows were mislabelled but the magnitude rule invalidated them regardless. The USO/SWKS rows are
unfilled, not "no orders" - they carry order ids - and they were still armed at the review snapshot; the revised
tool skips live rows by default. Fresh manifest: `FIX-01-manifest-dryrun-v2-2026-09-14.json` (5 records; false
halt: HPQ only; live rows: USO, SWKS plans).

Still open, stated as open: quantity-dependent R:R reporting (FIX-10); FIX-02's partial-fill / uncertain-ACK /
restart integration cases beyond the decision function; DA-01's integration evidence is still constructed
intents, not broker acceptance; the reconciliation tests use isolated session fakes (the tool's real-DB
round trip on the test database is the next evidence to produce).


---

# Second follow-up (`2026-09-14-delivery-a-followup-verdict.md`), same day

Deployment still HELD; manifest still unapplied. The three new reviewer files were adopted unchanged as
`tests/test_codex_em_final_dispatch_budget.py`, `tests/test_reconcile_postgres_atomicity.py` and
`tests/test_promote_resolved_definition.py` (the last with a package-relative import of its sibling's DB
guard, nothing else). Run sequentially against `zargar_test_codex` on loopback:5433 with the wrapper's
environment: **8 failed / 4 passed** before, **12 passed** now (14 s). The earlier 55 reviewer-group cases
still pass; broader suites in the section below.

| FA | correction | where |
|---|---|---|
| 01 | `_entry_guard` is a synchronous predicate over the runner's own state (remaining daily-loss budget from `_net_realized`/`_unrealized`, cached T5.4 evidence) passed as `before_submit` to `OrderManager.place` on the entry and on the collar retry; carried through `_place_with_retry` on every attempt; never resizes; reduce-only exits untouched. The third timing case now ends in `REJECTED_RISK` with `beforeSubmitRejected` and no executor call | `planrunner.py` |
| 02 | the repair writes the plan state and every `TechniqueTradeCorrected` receipt row in ONE session and ONE commit (`Event` rows staged in the caller's transaction, the row locked with `FOR UPDATE`, the hash re-checked inside the lock); bus publication only after commit; replay is recognised by a committed receipt for (plan, trigger, manifest generation) plus corrected state | `tools/em_reconcile_fallback.py` |
| 03 | ownership (portfolio AND technique from the manifest) is validated before any read of the state; a mismatch refuses the whole plan and writes nothing | same |
| 04 | corrected values come from the Order/Execution ledger joined on the trade's recorded order ids and the row's portfolio: weighted BUY entry, SELL exits, commissions over all executions (entry + exits); a projection that disagrees is flagged `evidenceConflict` and the ledger wins; no ledger rows = `evidence: missing`, refused at apply; `haltOld/haltNew` labelled a per-trade gross diagnostic (`haltNote`); `--include-live` documented as a bypass that verifies nothing | same |
| 05 | promotion compares the complete selected definition - the sweep's saved resolved thresholds (`params.thresholds`, field-named) merged with its overlay - against the prior run's own resolved thresholds and process version; a fresh read is built with `thresholds_override = saved resolved values + overlay`, never today's defaults | `technique/service.py::promote` |
| build | `BUILD` is bound once at import (full SHA, `-dirty` suffix when the tree had uncommitted changes, `unknown` without git; `ZARGAR_BUILD` overrides); `/api/health.build` reports it | `zargar/__init__.py` |

Disclosure: `apply()` keeps both reviewer harnesses green with a capability check on the session it is given -
a production `AsyncSession` (has `execute`/`add`) takes the ledger + staged-receipt path; the earlier direct-function
cases drive it with minimal fakes (get/commit only) and fall back to projection arithmetic and `journal.append`
before the commit. The real-Postgres path is the one deployed code exercises; the fallback exists only so the
earlier 5 reconciliation cases stay unweakened. If the reviewers prefer, those 5 can be retired in favour of the
Postgres cases.

Fresh manifest: `FIX-01-manifest-dryrun-v3-2026-09-14.json` - every item now carries `evidence`
(ledger | unfilled | missing), `evidenceConflict`, the ledger figures and the commissions summed over all
executions. HPQ's ledger figure is the same -7.193 as before.

Delivery B: the first PR will carry the two implementation contracts named in the verdict (source edit/event
ordering with safe partial-update merging; atomic or idempotently-recoverable source/job creation and
output/checkpoint transitions with idempotent output keys). The design's original section 1 schema and
backfill wording is marked superseded in the design file.

Still open, stated as open: quantity-dependent R:R reporting (FIX-10); the wider FIX-02 exit integration
cases; `--include-live` has no quiescence verification (a live repair needs the owner/quiescence/restoration
protocol before it is ever used).

## Broader-suite regression from the FA-01 guard, and its scoping (same day, commit 1afc713)

Two wider suites failed after the guard landed and both were fixed before this hand-off:

- `tests/test_tip_runner.py` - `TipRunner._place_with_retry` (the Tip desk's override) did not accept the new
  `before_submit` keyword. It now accepts and forwards it to `super()` / `OrderManager.place`, so the Tip retry
  path carries the same predicate and no desk bypasses the final boundary. No Tip behaviour changed.
- `tests/test_technique_arming.py::test_daily_loss_halt_flattens_and_stops_the_plan` - the first guard also
  budget-gated SHARE entries, which is not what F33 enforces: F33's per-entry day-budget predicate is defined
  for option entries; a share entry that would exhaust the day budget is caught by the plan-level loss halt
  after the fill (flatten + stop the plan), which that test pins. The guard now runs the remaining-budget
  predicate for option entries only; the cached T5.4 evidence check applies to every option entry as before.
  Reviewer case 3 (the $160 / $150 / -$40 scenario) is an option entry and still ends in `REJECTED_RISK`.

Results after the scoping: reviewer group 55/55, Postgres group 12/12, `test_tip_runner` +
`test_technique_arming` 82/82; platform phase 3 + lifecycle + review + restart recovery + technique API +
walk-forward + engine flow 98/98 (13.5 min). Nothing new on origin/main or the other desk branch to merge.

---

# Closure review (`2026-09-14-fa-closure-review.md`), same day

Deployment still HELD (FC-01 was the one remaining blocker; fixed below, awaiting the reviewers' re-read).
The FIX-01 manifest is NOT applied by this desk: the reviewers gave a scoped GO for the five v3 records on
the default non-live path, and `--apply` stays a human step (the user runs it; receipts and the readback
are returned afterwards, never a deployment claim).

**FC-01 (P1, fixed).** `_entry_guard` no longer reads the captured contract's warning list as its evidence.
It reads the CURRENT cached quote for the order symbol (`engine.quotes.get`, synchronous) and asks the
technique's new pure hook `judge_entry_quote(ap, trade, contract, quote)` for a verdict, inside
`before_submit`, after OrderManager's last await. The predicate (`execution/entry_quality.py`, no I/O, no
mutation): a two-sided uncrossed book; an observation fresher than `execution.premium_mark_max_age_seconds`
by its source timestamp; the current spread within the technique's limit when the arm skips wide spreads
(EM: T5.4's own `MAX_SPREAD_PCT` 10%, the number the pick and `rejudge_spread` use; generic runner:
`execution.spread_warn_pct`). With no current observation, or only the delayed chain row, the captured T5.4
verdict is the only evidence and is applied as before. The budget check and the retry/collar forwarding are
unchanged. The reviewer's case (`tests/test_codex_em_final_dispatch_quote.py`, adopted unchanged: bid 2.95/ask
3.00 admitted, then 2.50/3.00 = 18.2% replaces the cache during the SUBMITTED transition) now ends in
`REJECTED_RISK` with `beforeSubmitRejected`, no executor call. Pure-function cases: `tests/test_entry_quality.py`
(narrow allow, widened refuse, one-sided/crossed, stale, no-quote/chain fallback, shares untouched).

**Test-harness cleanup (done).** `tools/em_reconcile_fallback.py` has ONE code path: the capability shim
(`_can`), the projection arithmetic (`_recompute_projection`), the journal-before-commit branch and the
`with_for_update` fallback are removed. The five direct-function cases in `tests/test_em_review_da_reconcile.py`
are kept verbatim as historical reproductions and marked skipped with the reason; their real-session
equivalents are `tests/test_em_reconcile_real_session.py` (repository `fresh_db`, any test database) with the
coverage map in its docstring: persisted corrected state + plan aggregate, two corrections as one row
transition, receipt failure rolls the state back (then the exact retry applies once), exact replay =
`already_applied` with no second receipt. The reviewer's Postgres cases stay the failure-mode authority.

**v4 dry run.** `FIX-01-manifest-dryrun-v4-2026-09-14.json`, produced by the cleaned tool against the runtime
database (read-only): the same five records, the same three state hashes as v3 (USO `9d03592cf2f6e804`, SWKS
`6d45be2ad1d79b75`, HPQ `ef17f95f1725c722`), the same corrected values, `liveRows` none, `unresolved` none.

**Upstream.** `origin/main` (5188956, Tips day-1 findings + geometry wiring fixture) is merged; the
`docs/PLATFORM-RULES.md` conflict was resolved by keeping both desks' 2026-09-14 sections in full.

**Delivery B first PR** is next on this branch (three tables, backfill dry-run tool, `resume_unfinished()` with
fencing, order-free boundary, the two implementation contracts).

Results: reviewer group on zargar_test_codex (budget 3 + quote 1 + Postgres 6 + promotion 3) 13/13;
`test_entry_quality` 7/7; real-session reconcile 4/4 (+ 2 kept, 5 historical skipped); arming + tip runner +
Team2 runner + reviewer execution/evidence/preopen/exits 121/121; ingest + gateway + separation 28 passed,
3 failed in `test_discord_gateway_modes.py` that call a method (`_on_message`) the Tips desk's envelope
refactor removed - they fail identically on origin/main and are not touched by this branch.

---

# First-PR review (`2026-09-14-delivery-b-first-pr-review.md`), same day

Deployment HELD; Delivery B source backfill HELD (not applied); the FIX-01 v4 five-record money repair keeps
its scoped GO on the non-live path (a human runs it; receipts and readback returned afterwards). The four
reviewer files were adopted unchanged: `tests/test_codex_fc01_source_loss.py`, `tests/test_codex_em_source_ordering.py`
(the standalone ordering/API/jobs file), `tests/test_codex_em_source_backfill.py`, `tests/test_codex_em_edit_gateway.py`.
All fifteen boundary cases failed before and pass now; the earlier 13 reviewer cases still pass (28 in the
codex group after this round).

| finding | closure | where |
|---|---|---|
| FC-02 (P1) missing / delayed current quote admitted | An option entry needs CURRENT executable evidence at dispatch: no quote = refusal; with a real-time source configured (`RiskGate.live_option_quotes_expected`) a delayed chain row = refusal and the age is the SOURCE age; without one the chain row is judged by receipt age and spread, as RiskGate does. The freshness limit is the ENTRY policy `risk.stale_quote_seconds` (10 s), no longer the exit-mark age. A quote without a timestamp is not evidence. The captured warning list no longer admits anything. The pure test that blessed the fallback was rewritten to this contract | `execution/entry_quality.py`, `PlanRunner.judge_entry_quote` + `_entry_quote_max_age` / `_live_option_quotes_expected`, EM override in `technique/arming.py`, `tests/test_entry_quality.py` |
| B-01 (P1) real update envelope never selected EM; worker-time sequence | `_enqueue` marks `em` for create AND update on EM channels and persists the RECEIPT sequence in the envelope (`seq`, spooled with it); `_em_forward(kind=, seq=)` sends that key, never the worker's `_seq`; an EM-only channel's edit returns after EM delivery and never reaches the tips mirror/intake; independent `emDone` acknowledgement kept | `tools/discord_gateway.py` |
| B-02 (P1) DTO defaults broke partial updates | `text: str \| None = None` on the request model; for updates omitted/null = unchanged and explicit `""` = cleared; create defaults are normalised only on the create path | `api/routes_technique.py` |
| B-03 (P1) ordering metadata could move backward | ONE comparison key (event time, gateway sequence) kept on the note as the accepted WATERMARK (`meta.sourceWatermark`), independent of the immutable revisions: equal event times fall to the sequence; a delivery without an event time orders by sequence alone and never lowers the time watermark (a tombstone keeps its authority); a newer identical state advances the watermark without a new revision; a content change with neither key is `unordered` and refused, never ordered by worker time | `technique/source_revisions.py::record_delivery`, `_compare_order`, `_advance_watermark` |
| B-04 (P1/P2) starvation; expired worker could checkpoint | eligibility (free/expired lease, not backing off) is in the query BEFORE the limit, with `skip_locked`; `checkpoint` requires a claimed, in-progress, UNEXPIRED lease plus the current fence - a matching integer alone is refused | `technique/source_revisions.py::resume_unfinished`, `checkpoint` |
| B-05 (P1) backfill copied unreviewed evidence | the manifest digest (`planHash` over EVERY evidence field: identity, content hash, media reference, transcript hash, extraction hash, artifact keys, stage, outcome) is verified first; the preflight refuses early; then each note is rebuilt from the LOCKED row inside the one transaction and compared field by field - any difference refuses the whole apply with nothing written; `apply` returns 0 on refusal and the CLI exits 2 | `tools/em_source_backfill.py` |

Pre-existing: the three `test_discord_gateway_modes.py` failures (`_on_message`) belong to the Tips desk's
envelope refactor and are recorded for that desk to port; untouched here.

Deferred to the next PR, as disclosed: gateway DELETE forwarding (the API/ledger accept `kind=delete` now);
wiring the transcription/extraction workers through artifacts + `checkpoint`.

Results this round: reviewer codex group 28/28 (source-loss 2, ordering/API/jobs 8, backfill 3, gateway 2,
budget 3, quote 1, Postgres 6, promotion 3); `test_entry_quality` 10/10; own Delivery B + real-session
reconcile + ingest + gateway envelope/ack + separation 67 passed, 5 historical skipped; arming + tip runner +
Team2 runner + reviewer execution/evidence/preopen/exits 121/121.

---

# a55bced review (`2026-09-14-a55bced-review.md`) - release integration, same day

**Team2 F126 preserved.** The running checkout's local branch (b1da621, never pushed) carried 260fbc0
(`planFor` on Team2's close scorecard + its regression, v0.7.72 metadata) and the Team2 watch runs 93-95.
It is merged into the EM branch; `backend/zargar/__init__.py` keeps `__version__ = "0.7.72"` AND EM's
launch-bound `BUILD`; `npm run check-release` agrees on 0.7.72 across the four files. `test_team2_close.py`
runs green on the combined tree.

**Exclusive test window.** `zargar_test_codex` had the Cartel branch's two stray tables
(`execution_evidence`, `cartel_preparation_attempts`) which break this revision's `fresh_db` teardown; with
ZERO other clients on the database (checked in `pg_stat_activity` before and after) they were dropped and the
combined group run once, sequentially: budget 3 + quote 1 + source-loss 2 + Postgres 6 + promotion 3 +
ordering/API/jobs 8 + backfill 3 + gateway 2 + watermark pair 2 + `test_team2_close` 4 = **34 passed**, no
other client before or after. (A shared reservation for that database is still the right fix; this desk only
checked and ran.)

**P2 watermark pair - fixed now rather than carried.** `_advance_watermark` stores ONE accepted observation's
(event time, sequence) pair: a newer event time replaces the pair (its own sequence, even if lower - the
gateway sequence-reset case), the same event time keeps the larger sequence, an event without a time
advances the sequence only. The reviewer's pure regression is adopted as `tests/test_codex_source_watermark_pair.py`
(1 failed -> 2 pass); the tombstone and same-content cases stay green. Sequence-reset semantics, stated: the
source's own edit time is authoritative across gateway connections; the sequence only orders deliveries that
share an event time or have none.

**Fresh Delivery B backfill dry run** (read-only, the cleaned tool against the runtime database; the revision
table does not exist there until the new build boots, which the dry run tolerates and `apply` does not):
`DELIVERY-B-backfill-dryrun-2026-09-14.json` - 19 notes, 0 already revisioned, digest `f3931513580afb0c`,
24 artifacts (8 transcripts, 16 extractions, all `availability: unknown`), stages board_checked 16 /
received 3, outcomes done 16 / retryable 3. NOT applied; a fresh dry run is re-generated after deployment
and reviewed before `--apply`.

FIX-01 v4 money repair: unchanged scoped GO, still a human step. Deployment: after the reviewers read this,
through the ZargarRestart task with the readiness check; the build SHA on `/api/health`, effective settings
and restoration evidence are returned afterwards.

Results this round: codex exclusive window 34/34 (+ backfill/ordering/own Delivery B 21/21 after the dry-run patch); own Delivery B + reconcile + ingest + gateway envelope/ack 57/57; Team2 runner + close, arming, reviewer execution groups 50/50 (8.7 min).

**Second integration, same round:** origin/main moved again while the suites ran (Cartel v0.7.74, Team2
R1-R5, the deploy lease). Merged: version 0.7.74 in all four files with EM's launch-bound `BUILD` kept;
Team2's close scorecard keeps `planFor` (F126) beside the R5 funnel; the changelog keeps the 0.7.72 block
under 0.7.74/0.7.73; `npm run check-release` agrees. The stray Cartel tables were gone from
`zargar_test_codex` by then. One combined run had ONE other client present at its start and showed two
failures that pass alone and in the clean rerun - reported as a collision, not counted. Clean exclusive
window on the final tree (0 other clients before and after): reviewer groups + watermark pair +
`test_team2_close` + entry quality **42/42**; own Delivery B + reconcile + ingest + gateway + separation
60/60; Team2 runner + reviewer execution 16/16; arming 29/30; tip runner 48/52. The FIVE failures are all option-fill
timeouts/rejections (`test_technique_arming::test_auto_options_one_contract_lifecycle`, `test_tip_runner::
test_option_tip_both_books_end_to_end`, `test_short_tip_puts_end_to_end`, `test_native_mleg_spread_fills_on_sim`,
`test_native_mleg_failure_falls_back_to_sequencing`) and every one of them FAILS IDENTICALLY on unmodified
origin/main (checked in a throwaway worktree of main): the Cartel merge's sim executor now refuses an option
fill unless the quote carries a real-time source identity (`SimExecutor.quote_rejection`, `synthetic_quotes`
off), and those tests publish contract quotes with an empty source. Pre-existing on main, owned by the Cartel
desk, not touched here; recorded for that desk. (Runs were done one file at a time in the foreground: the
machine had ~1 GB free and background runs were killed for memory.)

**Third integration (origin/main 7b1dee2: Cartel handoff receipt, deployment lock, Team2 F123/F126 on main):**
clean merge, no conflicts; version 0.7.74 agrees; `planFor` present once. Exclusive window on the final tree
(0 other clients before/after): reviewer groups + watermark + `test_team2_close` + entry quality 42/42; own
Delivery B + reconcile + ingest + gateway + separation + Team2 runner + reviewer execution 72/72.

---

# Release verdict at 3f1d665 (`2026-09-14-3f1d665-release-verdict.md`) - deployed, same evening

**Build-helper integration defect, repaired twice in parallel.** The Ledger merge (49f91da, v0.7.75) dropped
`_read_build` / `BUILD` / `build_sha` from `backend/zargar/__init__.py` while the health route still imports
`build_sha`. The EM desk restored it on the branch as 309280b (with `test_health_and_state` now REQUIRING the
`build` field - a version-only check cannot see a dropped helper); the runtime checkout's session restored it
as 0014640 (same helper + a PLATFORM-RULES note). Both are merged (c266361 on the remote branch contains
0014640). Before the repair booted, the runtime restarted on 2a02844 at 17:37:16 with the file rewritten at
17:37:26: the process ran without the helper, health answered 500, and the watchdog looped. Lesson recorded:
a file written after the process starts is not in the process.

**Deployment (by the deployment protocol, receipt `logs/deployment-receipt.json`):** target
`0014640bf530e4751dc37e70eec53a89213c7b16`, expected 0.7.75, phase `verified`, completed 2026-09-15T00:44:03Z,
restart log `restart-20260914-174252.log` "Healthy: v0.7.75 | armed 11 | runs in flight 0". Health afterwards:
`{"ok":true,"version":"0.7.75","build":"0014640bf530e4751dc37e70eec53a89213c7b16","local":{"armed":11}}`.
Restoration: 11 armed plans (3 Team2 + 8 Tips, the same inventory as the readiness snapshot before the
restart), 3 managed positions open + 2 closed, 23 resting orders, no open trades / in-flight orders, not
quiesced. Market closed at the time. The EM desk did not run the restart: its own lease attempt found the
watchdog holding the runtime, and the release owner's deployment then completed.

**Delivery B source backfill - APPLIED under the scoped GO.** Post-deploy dry run
(`DELIVERY-B-backfill-dryrun-postdeploy-2026-09-14.json`) was identical to the reviewed one: 19 notes, 0
already revisioned, 24 artifacts (8 transcripts, 16 extractions, all `availability: unknown`), digest
`f3931513580afb0c`; the three tables existed after the boot. Applied through the locked evidence checks in
one transaction: readback 19 revisions (all revision 1, kind create), 24 artifacts (16 extraction, 8
transcript, all `completed_at` NULL), 19 jobs (16 done / board_checked, 3 retryable / received), 19 of 19
EM notes revisioned, original notes untouched. A second apply wrote nothing (19 skipped as already
revisioned).

**FIX-01 v4 money repair:** unchanged scoped GO; still a human step, not run by this desk.

**Next PR (proceeding):** gateway deletion forwarding; the transcription/extraction workers through immutable
artifacts + fenced checkpoints; the sequence-reset ordering through the real gateway/API path; tombstones that
keep history and leave managed positions under their exit owner. Candidates stay order-free.
