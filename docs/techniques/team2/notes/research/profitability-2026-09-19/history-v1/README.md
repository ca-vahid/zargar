# Team2 profitability study: consolidated review package (2026-09-19)

One package for review. No runtime setting, order path, experiment book or deployment was touched. Control, Sizing 0.5 and
C1 ran unchanged. C2 (`key_levels`) was not run on any date on or after 2026-09-14.

## The decision

**The automated Team2 method, as implemented, shows no after-cost edge, and none of nine preregistered single-factor changes
gives it one. Recommendation per arm: REJECT all nine. Recommendation for the method as automated: INSUFFICIENT EVIDENCE of
profitability, with the measured expectation slightly negative after fees.** What is missing is not another threshold. It is the
author's selection judgment and his losing trades, neither of which is documented (section "What is still missing").

| Question | Answer | Evidence |
|---|---|---|
| Does the baseline have a repeatable after-cost edge? | No. 333 replayed trades on 93 sessions, priced on real option prints: mean -3.8% per trade after fees, 95% interval -7.6% to +0.1%, win rate 31.5%. Gross of fees it is about zero. With one tick of slippage per leg it is -7.0% | `04-loss-attribution.md`, `results/` |
| Does it read the market like the author? | Direction and scenario: yes, six of six of his documented trades in the window. Capture of his winners: zero of six | `03-opportunity-ledger.md` |
| Where is the money lost? | Not in one place. The entries have no option edge at any holding time from 4 to 120 minutes. Fees take 3.9% of cost per round trip on a $0.56 contract. 51% of trades stop out within four minutes at -11.7% | `04-loss-attribution.md` |
| Did any bounded improvement pass? | No. Two-candle stop, target-room floor, new-extreme trim cue, conjunction no-trade zone, dearer contract, collision re-plan, no outright target exit, and two resting-limit brackets all failed criterion 1 on the training window | `05-hypotheses-and-results.md` |
| What goes to a prospective Practice experiment? | No trading arm earned it. The specification is for an order-free selection study plus the evidence to collect from the author | `06-prospective-experiment-spec.md` |

## Deliverables

1. `01-reconciled-baseline.md`: actual fills, fees, equity, drawdown and exposure for Control, Sizing 0.5, C1 and the retired Practice book, kept apart from replay.
2. `02-method-fidelity-matrix.md`: every behaviour mapped author vs code, labelled explicitly supported, inferred or unresolved; all dated author instances with evidence class.
3. `03-opportunity-ledger.md`: what was observable at each decision; taken, refused and late setups; the author's six documented trades against ours.
4. `04-loss-attribution.md`: direction vs timing vs contract vs cost vs exit; by setup, market condition, time of day, first entry vs re-entry; displaced opportunities.
5. `05-hypotheses-and-results.md`: ranked hypotheses, the frozen criteria, results, dependence on dates and symbols, fill sensitivity.
6. `06-prospective-experiment-spec.md`: the next experiment.
7. `../2026-09-19-profitability-preregistration.md`: the three registrations, each committed and pushed before its arms were run (commits 5bc329e3, 038ab13f, 2db47a49).
8. `harness/` and `results/`: every script and every summary number in this package.

## Two defects in our own measurement found on the way (both matter more than any arm)

1. **The replay's option pricing formula turns a loss into a large gain.** On the same 280 trades the formula says +21.8% per
   trade; real prints say -1.0% to -3.2%. Two causes. It books target exits at the target price inside the bar, and it prices
   0DTE contracts with a flat volatility (previous day's VIX1D) that makes a winner worth +77% where the real contract made +19%.
   It also believes the chosen contract costs $0.49 when the real one at that strike cost $1.35, so it picks strikes the live
   picker never would. Every earlier Team2 sweep, including the ones behind the sizing and C1 sheets, was scored with this formula.
   Those results should be treated as unscored until re-run on real prints.
2. **The harness silently imported the running checkout instead of the patched worktree** (a script's own folder, not the working
   directory, heads Python's path). Caught because the first arm came back byte-identical to the baseline. Fixed with an explicit
   path, and the default-parity proof was re-done against the correct code.

## Code in this change (research knobs, both default to the behaviour that is live)

- `session.py`, `rules.py`: `stop_candles` (was declared "informational", now real; default 1) and `target_collision`
  (`refuse` default | `replan`). Both were measured and rejected. They stay so the measurement can be reproduced. Neither is in
  `SETTINGS_MAP`, so neither can be switched on from the settings UI.
- A duplicate declaration of `target_identity_guard` in `rules.py` (a merge artefact on main, harmless) was replaced by the new field.
- Proof of no behaviour change at the defaults: the September replay (27 symbol-days, 15 trades, every event) hashes to
  `cf62d34425106c39` with the running checkout's code and with the patched code.
- Tests: `tests/test_team2_research_knobs.py` (3). Team2 and reviewer files: 384 passed.

## Limitations

- Prints, not quotes. Alpaca keeps no historical option quotes, so the true bid and ask at our decision instant are unknown. The
  minute-open proxy was validated on our 16 actual fills (median error $0.00, range -$0.105 to +$0.04). Queue position and partial
  fills are not modelled.
- Strikes walk the $1 grid. IWM half strikes are not tested.
- The book simulation drops a trade that collides with an open position or the loss cap, and does not re-simulate the symbol's
  later sequence. The size-after-a-win rule is not applied.
- 93 sessions in one volatility regime. The interval on the baseline mean still touches zero: the honest statement is "no evidence of
  an edge and a negative point estimate", not "proven unprofitable".
- The author's record is selected: 17 documented executions, all winners; five losing trades mentioned, none with a price, a size
  or a hold time. It cannot give a win rate. Images were read through the capture index, not viewed.
- Actual fills are five distinct round trips (nine book round trips). They agree with the replay but prove nothing alone.

## Blockers and decisions that are not mine

- Whether Control, Sizing 0.5 and C1 keep trading while the expectation is negative. Holding them stable was the instruction and I
  changed nothing. The book simulation at the current 6% risk shows drawdowns of $6,800 to $10,700 on $10,000 and an outcome that
  rests on three days. Pausing or cutting size tightens protection; it is the owner's call.
- Re-scoring the sizing and C1 sheets on real prints needs the review team's agreement, since they accepted those sheets.
- Collecting the author's losing alerts needs a source we do not have.

## Acceptance checks for the reviewer

1. `git log` shows each registration commit before the results it governs; `results/results.jsonl` holds no arm outside the three registrations.
2. `harness/validate_proxy.py` reproduces the fill-vs-print table from `harness/actual.json`.
3. `harness/run_arms.sh train 2026-05-07 2026-08-14 0 base H1 H2 H3 H4 H5 E1 E2` reproduces `results/results_table.txt` (needs the Alpaca keys already in `backend/.env`; read-only data calls, about two minutes per arm).
4. The default-parity hash is reproducible with and without the patch.
5. `01-reconciled-baseline.md` cash arithmetic matches `portfolios.cash` to the cent for all four books.
6. No file under `backend/` other than `session.py`, `rules.py` and the new test changed; no setting, migration or frontend file changed; no version bump (nothing user-visible ships).
