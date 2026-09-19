# Decision sheet: Team2 profitability, correction and validation pass (2026-09-19)

Scope kept: research, harness, documents and tests only, in an isolated worktree. Control, Sizing 0.5 and C1 untouched. No book
paused, no sizing changed, no strategy activated, no product pricing replaced, nothing merged to the trading path, nothing deployed.
C2 key levels were not run on or after 2026-09-14. Test-database lanes agreed with the Cartel desk (mine: `zargar_test_team2`).

## Status after review (2026-09-19)

The review team accepted the revised conclusions, with their limitations, as EXPLORATORY research, and directed the order-free
study, not another trading variant. Their four amendments are incorporated in `07-selection-study-spec.md` (registration `s1-r2`)
and the default-off, order-free collector is delivered in `08-collector-package.md`. No variant search, no trading-book change and
no risk change was made.

## Decision supported by the evidence

**INSUFFICIENT EVIDENCE of an after-cost edge for the automated Team2 method. No established after-cost edge; negative estimate under
the books' actual fee and any adverse slippage. All nine registered variants failed their preregistered criterion under the
corrected harness. Recommended next action: accept or amend the order-free selection study (page 7); start no new trading arm.**

This is weaker than the first package's headline ("no after-cost edge", "direction is a coin flip", "exits are not the leak"). Those
sentences went beyond the measurement and are withdrawn; section "Corrections" lists each one.

## Accepted findings, with their evidence class

| # | Finding | Evidence class |
|---|---|---|
| 1 | All four books' cash reconciles to the cent; 22 book fills = 16 market legs = 8 round trips = 6 independent opportunities on 4 days; commissions are 39% of the realized loss | actual fills; independently verifiable |
| 2 | The baseline replay's mean is -3.7% per trade (date-clustered 95%: -7.9 to +0.8) at the books' fee with no extra slippage; about zero with no fee or with every target sold at the touch minute's high; -7.6% (-11.5 to -3.3) at one tick per leg | simulated execution on real prints; developer-reported, reproducible |
| 3 | The print proxy differs from our fills by about three cents per leg in absolute terms (five percent of the premium) and looks about two cents per round trip pessimistic, on 15 legs from 6 opportunities. That uncertainty is as large as finding 2's estimate | actual fills vs prints; small sample |
| 4 | The product replay's flat-volatility premium formula reports +21.8% per trade on trades that real prints put between about -4% and 0%. Earlier formula-scored Team2 sweeps, including the modelled columns of the accepted sizing and C1 sheets, are not reliable in level or sign | real prints vs formula, 280 trades |
| 5 | No directional edge was DETECTED at the actionable price (favourable 49 to 54% at 4 to 120 minutes; mean move 0.00%, +/-0.05% at thirty minutes). A small edge cannot be excluded; option-return intervals are +/-13 points at thirty minutes | descriptive, examined before registration |
| 6 | Nine registered single-factor variants failed their frozen criterion, before and after the harness correction; ranking unchanged; the holdout was never opened for an arm. H5 (a dearer contract) is the only one with an interval above zero, only at one tick, and for a cost-arithmetic reason | simulated; registrations committed before measurement |
| 7 | On 2026-09-18 C1 missed SPY because two conjunction-admitted SPY fires, refused for occupancy at 10:14 and 10:16, spent the setup's two-pullback allowance; it then took QQQ because it had one loss where Control had two. C1 changes one configuration factor; these are downstream effects of it, so the experiment measures the whole policy, not only the quality of the newly admitted entries | journal; independently verified by the review team |
| 8 | No applicable experiment review level was reached on 2026-09-18 (Sizing $549 vs $800; C1 $816 vs $1,000; Control has none). `equity_points` is a 30-second mid-marked series, the monitor a 30-minute bid-marked one; neither is continuous | runtime records |
| 9 | Against five documented author executions and one illustrated area, our read had the same scenario each time and held none of his trades; the visible causes are our target derivation, the pre-market no-trade zone, the engulfing filter, and exits plus the loss cap. Only ONE of his entries has a timestamp, NONE has a price, and his record has no priced loser | source images inspected directly (09-18 excepted) |

## Corrections to the first package

| First package said | Status |
|---|---|
| "No after-cost edge"; "nine arms rejected" | Reworded: no ESTABLISHED edge; arms FAILED THE PREREGISTERED CRITERION under this harness |
| "Direction is a coin flip; the entry carries no directional information" | Withdrawn as stated; see finding 5 |
| "Exits are not the leak" | Withdrawn; the failed exit variants do not prove exits are irrelevant |
| Proxy "median error $0.00" | Replaced by signed, absolute and tail errors by side (finding 3) |
| "Seven distinct round trips" | Eight |
| Control "$928 beyond the $800 review level" | Wrong: Control has no experiment review level (finding 8) |
| His 09-09 entry "preceded our 09:45 gate" | Not supported: 09:41 is a WATCH alert |
| "2026-07-14 SPY 624C" | Removed: the year was inferred wrongly |
| "His edge is selection" | A hypothesis, stated as one |
| Book drawdowns ($6,800 to $10,700) as a reason to cut size | Withdrawn as a forecast: the book simulation is simplified (page 4, section B). The sizing question stands on its own and is the owner's |
| S1 "150 entries" and "the existing experiment schema supports it" | Replaced by per-comparison minimums, a deadline and an insufficient-evidence outcome; the schema does NOT support a selection filter |
| Harness: future-price selection, zero-dollar marks, unbounded price age, single target fill | Fixed, with eight regressions; 12 of 332 trades changed, mean -3.76% to -3.71% |

## Limitations that remain

- Prints, not quotes; no historical option quotes exist. Proxy fidelity is supported only for liquid near-$0.60 contracts in September 2026.
- One volatility regime, 93 sessions; $1 strike grid; `model` contract authority instead of the live NBBO picker.
- The book simulation does not reproduce allowance consumption by refused fires, deferrals, partial fills or marked equity.
- The author's record is selected and has no priced losing trade.
- Subgroup cells were examined before registration and are not findings.

## Blockers and decisions that are not mine

1. Accept or amend the selection-study specification (page 7). It needs a shadow-only code package (30-minute observation, feature
   block) reviewed before collection; a passing feature would then need a separately specified extension of the experiment schema.
2. Whether to re-score the accepted sizing and C1 sheets on real prints (finding 4). Recommended; about a day with this harness.
3. Whether a fire refused for occupancy should spend the pullback allowance (finding 7). A method question; I changed nothing.
4. Sizing or pausing the three books remains the owner's call; this package no longer argues it from simulated drawdowns.
5. PR #224 (the missing event contract) is open and independent of this package.

## Reproduce

```
export PYTHONPATH=<worktree>/backend            # REQUIRED: otherwise the venv imports the running checkout
H=docs/techniques/team2/notes/research/profitability-2026-09-19/harness
python -m pytest $H/test_pricing_boundaries.py -q -p no:cacheprovider -c /dev/null        # 8 passed
python -m pytest backend/tests/test_team2_research_knobs.py -q                            # 3 passed (own database)
bash $H/run_all.sh <DATA> <RUNDIR> <worktree> all      # 26 replay files, about 70 s each; Alpaca keys from backend/.env, read-only calls
bash $H/assemble.sh <DATA> <RUNDIR> <package>/results  # statistics, pairs, simplified book, manifest, file identities
python $H/validate_proxy.py <DATA> $H/actual_fills.json out.json
python $H/author_trace.py <DATA> <RUNDIR>/all_base_s0_proxy.json
```

Cached inputs: `<DATA>` = `SPY_1m.json`, `QQQ_1m.json`, `IWM_1m.json`, `vix1d.csv`, `opt/` (3,385 contract-day files), about 80 MB, not in
the repository; identities on page 2 and in `results/manifest_all_base_s0_proxy.json`. Output identities:
`results/replay_file_identities.sha256`. **Independently verified by the review team (2026-09-19): the eight pricing-boundary tests pass, and the C1 journal trace (10:14 and 10:16 occupancy refusals, allowance exhausted at 10:22). NOT independently reproduced: the 93-session results.** Independently VERIFIABLE
without my harness: findings 1, 7 and 8 (runtime database and journal). Everything else is developer-reported.

## Acceptance checklist

1. Registrations 5bc329e3, 038ab13f, 2db47a49 precede their results; this pass changed no definition, value or criterion.
2. The eight boundary regressions pass; the first fails against `harness/v1/realmodel.py` (v1 picks the post-decision strike; v1 marks a missing print 0.0).
3. No replay file contains a price of zero for a held contract; censored and unknown counts are reported (0 censored, 1 unknown mark, 15 priced refusals).
4. Every interval on pages 4 and 5 is date-clustered; naive intervals appear only beside them, labelled.
5. Page 1 counts legs, round trips and opportunities separately and does not treat three books as three cases.
6. Page 6 cites the image behind every row and labels each entry's evidence class; no chart arrow is treated as a fill.
7. Page 7 fixes features, identity, primary outcome, quote validity, clustering, Holm correction, per-side minimums, deadline and the insufficient-evidence outcome, and states the schema limitation.
8. The collector package has its own checklist in `08-collector-package.md` (12 acceptance tests; default off; order-free).
9. `git diff main --stat` touches only: the package, `backend/zargar/techniques/team2/{session,rules}.py` (two default-off research knobs), the collector (`selection_study.py`, its wiring in `runner.py`, one default in `settings_service.py`), two test files, and documentation. No settings, migrations, frontend or version files.
