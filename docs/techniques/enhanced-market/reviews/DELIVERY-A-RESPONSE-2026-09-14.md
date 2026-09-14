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
