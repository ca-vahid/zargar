# Setup-target resolution v1 — frozen specification

Date: 2026-09-21 · Desk: Team2 · Status: **specification frozen before implementation**.
Setting `techniques.team2.setup_target`, default `inherit` (today's behaviour, unchanged).

This document is written before the code and is not edited to match it afterwards. If the
implementation cannot meet a clause, the clause is amended here in a dated note saying why.

---

## 1. The defect, traced end to end

Every step below is from the runtime's own records for 2026-09-21.

**SPY**

| when | record | value |
|---|---|---|
| 17:00 prior evening | plan `targets.above` | 762.95 |
| 09:25 pre-open | `targets_rederived` | reference 766.20 had run through 762.95 → `above` re-derived to **767.26**, `source: "pmh"` |
| 09:30 open | `targets_rederived` | reference 766.29 → `above` = **767.26** again |
| 09:55 | `premarket_extrema` | PMH **767.26**, from the 07:55 bar |
| 10:00 | `pm_break` | 15m close above the pre-market high **767.26** → "calls up to 767.26 — already behind the break, so this setup has no destination" |
| 10:08 | `skip_target_collision` | target 767.26 is the setup's own source level 767.26 |

**QQQ** is the same shape: planned `above` 721.886, re-derived at 09:25 to the pre-market high
**729.14**, breakout confirmed at 09:46 with source 729.14 and target 729.14, then refused
repeatedly through the morning.

**Count these carefully.** The day produced 37 `skip_target_collision` records, but that is 37
*rows*, not 37 opportunities. It is **two** suppressed setups — SPY `pm_break_up@09:45` and QQQ
`pm_break_up@09:30` — each refused on many bars across three books. The unit that matters is the
physical candidate, not the refusal event. (The EM desk hit the same inflation from the other side:
one trigger produced 48 occupancy-refusal rows over 51 minutes while a single position was open.)
The opportunity audit in this package therefore counts deduplicated candidates, never skip rows,
and any figure quoted as an opportunity count in this work means candidates.

### What is actually wrong

Nothing in the refusal. The collision guard did exactly its job, and the `pm_break` note even
narrates the problem in plain words before the refusal happens.

The fault is one step earlier, and it is a **role confusion**. F81b re-derives the day's single
global destination to the pre-market extreme when the planned target has been overrun. That is a
sound destination for a setup whose source is a prior-day zone edge. It is not a destination for a
**pre-market breakout**, because for that setup the same price is the *source*. One global
`targets["above"]` is shared by setups whose sources differ, so a breakout inherits the level it
just broke as the place it is trying to reach.

This is a correctness defect in target assignment. The resolution policy below is nevertheless
treated as a **trading-policy experiment**, because fixing it changes which trades happen.

---

## 2. Policy

At setup creation or confirmation, for a setup `S` with source level `L`, direction `D` and
confirmation timestamp `T`:

**2.1 Source and role.** `S` retains `source = L` and `sourceRole`, one of `pm_extreme`
(`pm_break_up` / `pm_break_down`), `zone_edge` (`scenario_*`), `key_level` (`key_break_*`). The
role is what makes "this level is my source, not my destination" decidable.

**2.2 Candidate ladder.** Enumerate destinations known at `T`, each with its origin label and the
timestamp of the input it came from:

| origin | candidate |
|---|---|
| `pd_zone` | the prior-day zone edge ahead in `D` |
| `pm_extreme` | the pre-market extreme ahead in `D`, only when it is not `L` itself |
| `ladder` | each `levelLadder` entry ahead in `D` |
| `planned` | the evening's `targetsPlanned` value for that side, when still ahead |

Only inputs with timestamp ≤ `T` are eligible. Nothing observed after `T` may enter the ladder.

**2.3 Selection.** Sort valid candidates by distance ahead of `L`, ascending, and take the
**nearest**. Ties break on the origin order in the table above, then on price. One policy, no
alternatives, no configuration.

**2.4 Distinctness.** A candidate within `tick` of `L`, or not directionally beyond `L`, is
rejected with reason `not_distinct` or `wrong_side`. This is the rule the SPY and QQQ cases break.

**2.5 Ahead of the actionable price.** The destination must still be ahead of the actionable price
before entry. This is the existing check, unchanged, and it runs again after awaited work and
immediately before submission.

**2.6 Nearest obstacle respected.** Taking the nearest valid candidate is what enforces this. The
policy can never skip an intervening level to manufacture room, because a skipped level would by
definition have been nearer and therefore selected first.

**2.7 Explicit refusal.** If no candidate qualifies, the setup is refused with
`skip_no_destination` and its rejection reasons. The target is never dropped, widened or moved to
allow an otherwise-invalid order.

**2.8 Persistence.** `source`, `sourceRole`, the full candidate ladder with per-candidate
accept/reject reasons, the chosen destination and the input timestamps are persisted on the setup
and survive replay and restart. A later bar or level correction cannot alter an earlier decision;
re-deriving from corrected bars produces a new record, never an edit.

---

## 3. How this differs from the re-planning variants already rejected

This is the question that decides whether the policy is legitimate, so it is answered directly.

| | rejected: `target_replan="entry"`, `target_collision="replan"` | this policy |
|---|---|---|
| **when** | at entry, on each pullback | once, at setup confirmation |
| **trigger** | an entry was blocked | nothing; it is how a setup is built |
| **direction of effect** | substitutes a **farther** level so a blocked trade can proceed | takes the **nearest** valid level |
| **what motivates it** | the trade | the structure |
| **if nothing valid** | refuse (same) | refuse (same) |

The rejected variants are target shopping: a trade is blocked, so a more distant destination is
found to unblock it. They can only ever move a target farther away, which inflates apparent reward
and is exactly the failure mode that got them rejected.

This policy cannot do that. It selects the nearest valid destination, so relative to a free choice
it can only make a target **closer or equal, never farther**. It runs before any entry exists, so
no blocked trade can influence it. That asymmetry is testable and is an acceptance case.

---

## 4. Deliberate non-goals

- **Casey's 769.70 is not hardcoded** and the resolver is not tuned to make Monday's trade win. His
  chart is evidence that source and destination are distinct roles. It is not authority for our
  selection rule.
- **No other factor moves with it.** The no-trade zone, premium band, entry timing, stops, sizing
  and loss limits are untouched in this package.
- **Success is not more trades.** A policy that only raises trade count without improving
  after-cost outcomes has not succeeded. The comparison reports both.

---

## 5. Comparison design

- **Reference:** C1 unchanged.
- **Variant:** C1 plus this policy, nothing else.
- Identical sizing, execution assumptions, contract rules and protections.
- Evaluate every affected setup, including adverse cases and opportunities displaced by occupancy.
- Missing historical option evidence is reported as missing. No fill is invented, and no tradable
  option return is inferred from the underlying chart alone.
- Report gross P&L, commissions and net P&L separately, with spread and slippage assumptions,
  premium invested, contracts, exposure, drawdown, and newly admitted, displaced and downstream
  trades.
- The existing allowance-consumption policy is unchanged here. Its effects are documented; changing
  whether an unfilled fire spends an allowance would be a separate experiment.

No existing book is altered to run this comparison, and no new Practice book or experiment-schema
extension is created without explicit activation approval.
