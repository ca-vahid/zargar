# EM closure - delivery review ED-01..ED-04 (2026-09-17 evening)

Review answered: `C:/Cursor/zargar-codex/docs/techniques/enhanced-market/reviews/2026-09-17-EOD-DELIVERY-REVIEW.md` (reviewed
code `d5e0c97`). One consolidated follow-up; the optional spread cap stays OFF; baseline preparation and trading unchanged;
no readiness bypass; no other desk's work interrupted.

## Tested SHA and defaults

**Tested SHA: `ad8796f79c9dde6616f0d50e710c6a51a9e2adfc`** on `claude/technique-review-trade-plan-fbb9ba` (contains main 0.8.11 /
runtime `8d89547`), release block 0.8.12. This closure record is committed on top of it.

| Default / scope | Value | Status |
|---|---|---|
| `sim_max_option_spread_pct` (config) / `SimExecutor(max_option_spread_pct=)` | `0.0` = OFF | unchanged, not activated; when on: OPENING option orders only |
| `sim_max_spread_pct` (Tips F-HOLD-01, shares) | `0.05` | untouched |
| `techniques.enhanced_market.shadow_exit_observe` / `shadow_p02_candidate` | `True` / `True` (user decision 2026-09-15) | unchanged; the `tp1-reclaim` observation rides the same knob |
| `techniques.enhanced_market.fire_decision_mode` / `fire_evidence_mode` | `deterministic` / `off` | unchanged |
| Preparation flow, thresholds, arming, risk | unchanged | no batch rerun; tonight's normal preparation is a separate receipt below |
| Activation scope of anything in this delivery | none | research + evidence validation only |

### Results on `ad8796f` (private test databases, foreground, one job at a time)

| Check | Result |
|---|---|
| `tests/test_em_sim_option_spread.py` (ED-01: default off, entry rests then fills, stop / flatten / reducing trim / short cover fill on the aberrant book with the cap on, unknown intent never capped + delayed-chain refusal intact, cross-desk opening order capped, shares untouched) | 6 passed |
| `tests/test_sim_share_session_and_spread.py` (Tips F-HOLD-01 regression) | 4 passed |
| `tests/test_em_runner_protection.py` (ED-02: confirmed trim -> proxy with actual production fills; cancelled / unfilled trim; partial + intermediate trims with a refire ignored; stop-first; missing minute; covered observation -> dollars, early / thin observation -> proxy; runner open at cutoff; pure reclaim signal) | 8 passed |
| `tests/test_em_prep_ablation.py`, `test_em_profitability_p04_p05.py`, `test_em_confirmation_pair_rereview.py`, shadow-observer suites (`test_em_forward_measurement`, `test_em_shares_position_cap`, `test_codex_em_capture_followup`, `test_codex_em_measurement_boundaries`, `test_codex_team2_diag_observations`) | 57 passed in total with the two files above |
| `tests/test_technique_arming.py` solo (planrunner changed) | 30 passed, 1 failed = the known baseline `test_auto_options_one_contract_lifecycle` |
| `test_technique_walkforward.py` lazy-render + eager-render plan tests | 2 passed (earlier tonight on the same code paths) |
| Import smoke (`zargar.api.app`, planrunner, tools) | ok |
| Frontend `npm run build` + check-release | "Release 0.8.12 ... agree", built |

## Per finding

| ID | Change on `ad8796f` | Acceptance evidence | Status |
|---|---|---|---|
| ED-01 optional cap blocked protective exits | `brokers/sim.py::quote_rejection`: the cap applies only when `order.sec_type == "OPT"` AND `order.option_action` ends with `_TO_OPEN`. `option_action` is derived by the order manager from the book's position (`BUY_TO_CLOSE` when short, `SELL_TO_CLOSE` when long; `orders.py`), never from the side alone; closing / reducing orders and unknown intent (`None`, e.g. a restored order) are never capped and keep the finite-uncrossed-book, freshness, delayed-chain and unknown-source checks. The first predicate is withdrawn. Executor-wide knob = platform knob (PLATFORM-RULES updated). | The reviewer's reproduction (SELL/MKT option flatten on 0.76/1.12 with a 10% cap) now fills; so do a triggered STP stop, a reducing LMT trim and a BUY_TO_CLOSE cover; an opening order rests and later fills at its limit; a non-EM opening order is capped the same way; default off = 09-17 behaviour. | BUILT, OFF, not activated |
| ED-02 P-06 fill linkage and execution accounting | `tools/em_profitability.py::runner_protection` takes the trade instance's own exit records and the executions of those orders: eligible only after a confirmed TP1 fill; remainder = original fill minus every execution at or before the signal; signal = first bar completed after the TP1 fill whose close is back through TP1, consecutive minutes only, visible only when completed before production's next fill; candidate = covered executable bid from a runtime `tp1-reclaim` observation (options, actual entry fee + modeled exit fee) else next open as an underlying proxy for shares AND options (no dollars); production = actual fills after the signal, VWAP + allocated fees, to the terminal event (`partial` if still open); options compare underlying to underlying. Runtime: `PlanRunner._reclaim_capture` + pure `exits.tp1_reclaim_signal`, behind `shadow_exit_observe`, same evidence rules as shadow-exit-v1, enqueued and never awaited ahead of protection. The SCHW dollar comparison is withdrawn; both 09-17 rows are `underlying_proxy_only` (SCHW -0.23 R, BMNR +1.69 R on the underlying, premium unknown). Cohorts doc updated. | 8 cases listed above; report regenerated (`research/profitability/2026-09-17.md`). | BUILT (research); observer order-free |
| ED-03 ablation conclusions | `tools/em_prep_ablation.py` v3 and the report: "underlying independent-replay cohort difference +0.77 R under these assumptions", never measured model value or a token-dollar return; shared-book competition stated unmodeled / unscorable; pre-market evidence source split per cohort; baseline funnel reconciliation from the immutable journal for cohort A (live fired 12 / refused before order 5 / orders 15 / opened 6 vs replay fired 11 / filled 11, per-symbol table with the live refusal text; CRM and SNDK fired only in the replay, SKHY and SOXS only live - not full trigger parity, stated); "36 of 50 (72%)"; feature matches reproduce stated reasons, not the whole-plan eligibility decision; features learned on this session are exploratory on this session. | Report `research/prep-ablation/2026-09-17.md`; EOD response corrected. | DONE |
| ED-04 executable-profit measurement owner | OWNER: the EM desk (this session) for the EM-book record, capture and offline reducer; the Tips desk for the shared quote-cache / portfolio-mark layer it reads and the shared-code review. Acceptance contract retained verbatim: realized net, midpoint mark, executable covered liquidation net (bid for longs / ask for shorts, size-limited), contemporaneous source identity / timestamps / sizes, pending and remaining quantities, exit fees, explicit unknowns; asynchronous capture (queue + bounded recorder) so no protective exit waits; before and after target / stop / protection decisions; reconciled to fills without double-counting spread; a stale or unknown-depth quote never makes a liquidatable high-water mark. Delivery: record shape + design 2026-09-18 evening, recorder behind a knob OFF next, offline reducer in the profitability report after; no further giveback / trailing policy proposed ahead of it. Until then the 09-17 marked giveback ($161.63) is not recoverable dollars. | Recorded in the EOD response (Package A) and TRADING-RULES. | ASSIGNED, not built |
| Reporting corrections | $222.65 net after $16.64 commissions ($239.29 gross before commissions); ORCL 2.29 sensitivity = $133.92 on the trade / $105.65 on the day, arithmetic only; the one-minute bar is "inconsistent with that minute's prints", not proof of impossibility; ORCL labelled simulated / questionable evidence, ledger unchanged; E17-01 recorded as the likely producer transform (Tips desk), causality not claimed proven. Unfinished A / C / D components stated as not built. | EOD response edited in place. | DONE |

## Preparation receipt (separate)

Tonight's normal next-session preparation (sheet `ed48a80aa9854e3d8ecb3da887aacfaa` for 2026-09-18, 102 setup rows, one
review-and-arm batch, 4 reads in flight) was running while this closure was written and is reported in its own receipt
below when it completes. Nothing in ED-01..04 touches it.

- [ ] Preparation receipt: _pending_ (reviewed / setup / no-setup / armed / failed counts, log `evening_batch_0918.log`)

## Deployment receipt (separate)

0.8.12 (this tree, carrying main 0.8.10 / 0.8.11) is deployed only through `scripts/deploy.ps1` under the lease after
`/api/ops/restart-check` is safe, never over open EM trades and never by interrupting another desk's run; the elevated
shell hands the restart to the `ZargarRestart` task; restoration is verified by hand against the before-inventory.

- [ ] Deployment receipt: _pending_ (target SHA, receipt phase, restoration before / after by id)

## Kept

Rules, thresholds, observation knobs, the preparation flow and live gates unchanged; the 8% friction marker a marker; no
activation of any research candidate; the optional cap OFF.
