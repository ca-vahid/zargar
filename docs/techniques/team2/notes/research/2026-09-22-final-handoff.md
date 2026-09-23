# Team2 — final handoff, 2026-09-22

Closes the four items: F129 deployed, the target-resolver package decided, operational checks done
or honestly labelled unverified, and this record.

---

## 1. Exact deployed build

| | |
|---|---|
| build | `3ac3dac7d66579fa87253c73842a7aac8d1acabf` |
| version | **0.8.31** |
| deployed | 2026-09-21 22:17 PT, market closed, restart-check safe with nothing in flight |
| route | PR #242 merged to main (`136fac04`), main merged into the running checkout, gates, `ZargarRestart` task |
| PR | #242, title "Team2 F129 + setup-target-v1 + opportunity audit" |

Version note: 0.8.29 and 0.8.30 were taken by the Cartel and Tips desks while this work was open. I
renumbered to 0.8.31 by taking main's changelog whole and re-inserting only my own block, so both
released blocks are intact. One `APP_VERSION`, `check-release` green.

## 2. Restoration

The restart script's own verdict:

```
Restore check OK: armed 147/147, openTrades 0/0, workingEntries 0/0, pendingExits 0/0,
                  restingOrders 29/29, inflightOrders 0/0, managedPositions 10/10, managedOpen 10/10
```

Independently captured before and after by snapshot, with capture times stamped:

| | before 05:11:11Z | after 05:17:27Z |
|---|---|---|
| armed plans | 147 | 147 equal |
| resting orders | 29 | 29 equal |
| managed positions | 10 | 10 equal |
| open technique trades | 0 | 0 equal |
| paused books | 0 | 0 equal |
| Team2 plans | 9 | 9 equal |

**All nine Team2 plans restored**, three symbols across three books, every one `armed` / `auto`:

| symbol | run | book |
|---|---|---|
| IWM | `25f77d57`, `78fa47e4`, `97ab9c5e` | Sizing, Control, C1 |
| QQQ | `0ad37a81`, `92969eec`, `e15e88cc` | Sizing, Control, C1 |
| SPY | `309e3027`, `5fe500da`, `d8bc3338` | Control, Sizing, C1 |

The engine log contains 105 `restore check MISMATCH` warnings during startup. They are transient:
the check runs while plans are still being restored, and the final verdict above is OK. Worth
knowing before someone greps the log and alarms.

## 3. Effective settings

The **only** settings change is the new knob, shipped at its default:

| key | value | meaning |
|---|---|---|
| `techniques.team2.setup_target` | `inherit` | resolver OFF; the read follows exactly the path it followed before |

Every other Team2 setting is byte-identical across the restart (78 before, 79 after, the one
addition being the key above). Premium-stop threshold 25%, basis `mid`, 3-tick floor, fee
convention, quote-validity policy: all unchanged. Sizing, risk, product pricing, C2 and the three
experiment books: untouched.

## 4. F129 verified in the deployed build

Checked against the running process's own modules, not a test rig. All pass:

- The incident's own numbers no longer produce a stop: fill 0.33, live mid 0.295, **−10.6% against a
  25% limit**, recorded as a model-only observation with the model's −32% kept as a diagnostic.
- A genuine bleed still confirms: live 0.205, −37.9%, decided by the held contract.
- Quote-validity unchanged: stale, delayed and missing quotes all refuse; a fresh real-time quote
  with no bid is still a total bleed.
- The configured line is what decides: floor for a 0.33 fill is 0.2475, and the shared predicate is
  still the one used.
- Structural protection intact: quote watch, present-time structural guard, clock flatten,
  failed-exit retry, and every exit carries an authority record.

## 5. Study and cohort status

| | |
|---|---|
| state | `collecting`, 1 of 60 counted sessions, deadline 2026-12-18 |
| counted by cohort | `A-skewed-clock`: 1 |
| collector health | all six counters zero |
| collector | on (`collect`) |

Monday 2026-09-21 is **`counted` and stays counted**. Clock skew is not one of the frozen
registration's three exclusion rules, and adding one after the fact to drop a session would be
changing the measurement to fit the result. Instead two cohorts are recorded as append-only journal
evidence (events 200068–200069), naming what each session was collected under. Counting, stopping
and population rules are untouched; the study population is unchanged at 5 rows.

Reporting stays **coverage-only** until the endpoint. No outcome value is shown or computed.

## 6. The target-resolver decision: collect more evidence

Full reasoning in `2026-09-21-target-policy-comparison-and-decision.md`. In short: the day held 22
pre-refusal candidates, one newly admitted by the variant (SPY), one still refused (QQQ, nothing
above the break in the structure), and at least one displaced — a SPY entry would have taken C1's
single slot and prevented the 10:36 IWM round trip, which actually lost $213.15 net.

The newly admitted candidate has **no option evidence of any kind**: refusal preceded contract
selection, so no contract was chosen and no quote stored. Its after-cost outcome is unknown and
unrecoverable. The variant therefore trades an unknown-outcome position instead of a known loss,
which is not evidence of improvement in either direction.

Not rejected (the defect is real and the fix sound). Not approved for a Practice test (that needs a
new book or schema extension and explicit approval, on the strength of one session, one candidate
and no option evidence). **The resolver stays off.**

## 7. Operational checks — what is verified and what is not

| check | status |
|---|---|
| external clock, before the open | **VERIFIED** 05:16Z: 88–111 ms behind true time across four independent NTP operators (spread 24 ms), `w32time` Running / Automatic. Improved from 137–167 ms earlier, consistent with a running service disciplining the clock. |
| host-vs-database agreement | **NOT verification.** The database derives its clock from the host, so agreement proves consistency only. Recorded as a sanity check. |
| the +0.3 ms figure reported after the repair | **NOT reproduced.** Independent measurement puts the host ~100 ms behind, not sub-millisecond. Immaterial to a 180 s freshness window; the discrepancy is recorded rather than smoothed over. |
| alarm raises and clears | **NOT VERIFIED — not in this build.** The admission alarm belongs to the EM desk and is on their branch, which has not merged to main. It cannot be exercised here. Their desk demonstrated raise-then-clear live after fixing a defect where a pipeline-writing logger made the clear path impossible. |
| reboot verification | **NOT PERFORMED — no reboot has occurred.** The service is set to Automatic start, which is what should make the fix survive, but that is an expectation, not a measurement. Record the result when a reboot actually happens. |
| trading tolerances | **UNCHANGED.** No threshold was widened to accommodate any of the above. |

## 8. Rollback

- **The whole deploy:** `git revert 136fac04` on main, merge into the running checkout, gates,
  `ZargarRestart`. Previous build `11fb05f75df989b9daaf21ac20079688d36f5108` (v0.8.30).
- **The target resolver alone:** it is already off. Nothing to roll back. If it is ever switched on,
  `PATCH /api/settings` `techniques.team2.setup_target` back to `inherit`.
- **The premium-stop fix alone:** there is no knob, by design — it is a correctness fix, not an
  experiment. Rolling it back means reverting the deploy.
- **The study:** `PATCH /api/settings` `techniques.team2.selection_study` to `off`. Records stay,
  later sessions count as disabled, trading is unaffected.
- The cohort journal rows are append-only evidence and are not rolled back.

## 9. Monitoring owner and cadence

The Team2 desk. After each close:

- `python -m zargar.tools.team2_selection_study status` — counts, coverage and collector health
  only, until the frozen endpoint.
- `python -m zargar.tools.team2_opportunity_audit <date>` — order-free, read-only, to accumulate the
  pre-refusal evidence the resolver decision is waiting on.

Report operational problems separately from method performance. No method verdict before the
endpoint.

## 10. Remaining limitations

- One session of study data, collected under a ~10.5 s clock skew, with one of six features blind.
- The resolver's single newly-admitted candidate has no option evidence, so no after-cost number
  exists for it.
- Entry-relative room was not measurable for that candidate: the entry never happened, so there is
  no entry price to measure from. The 0.63 source-to-target distance is not a profitability claim.
- The displacement chain past the first IWM trade is undetermined.
- A ledger gap is parked with this desk: a loss-budget block rescued by the shares fallback writes
  no journal row, so budget blocks are under-counted. Not in this package; scheduled after it.
- One intermittent test failure was seen once in a full-suite run and did not reproduce in three
  isolated runs or a second full run. Reported as intermittent, not fixed.
