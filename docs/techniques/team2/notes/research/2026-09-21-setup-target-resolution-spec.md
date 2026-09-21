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

### 3a. Amendment, 2026-09-21: "closer or equal" stated precisely

An earlier draft of this section claimed the policy "can only make a target closer or equal, never
farther". That is loose, and in the one case that matters it is meaningless: when the inherited
target is the setup's own source level, it is not a valid destination at all, so "closer than it"
compares against nothing. The claim is replaced by two separate cases, because they are separate
behaviours and are tested separately.

**Case A — the inherited target is valid.** It is distinct from the source, beyond it, and still
ahead of the actionable price. Then it is **preserved**, unless a valid structural level lies
*between* the source and it, in which case that nearer obstacle becomes the destination (§2.6: a
nearer level is an obstacle, and skipping it would manufacture room the structure does not offer).
The policy never moves a valid target farther out. This is the case that guarantees the policy is
not target shopping.

**Case B — the inherited target is invalid.** It is the source itself, behind the source, or behind
the price. Then it is rejected with its reason, and the destination is the nearest valid candidate
from the ladder. This is **not** "moving the target closer": there was no valid target to move.
It is resolving one where the day's global value supplied none.

Both cases fall out of the same mechanic — the inherited target is simply one candidate in the
ladder, and the nearest valid candidate wins — but they must be reported and tested as two cases,
because only Case A speaks to the target-shopping concern and only Case B changes which trades
become possible.

It runs before any entry exists, so no blocked trade can influence the result in either case.

---

## 4. Deliberate non-goals

- **Casey's 769.70 is not hardcoded** and the resolver is not tuned to make Monday's trade win. His
  chart is evidence that source and destination are distinct roles. It is not authority for our
  selection rule.
- **No other factor moves with it.** The no-trade zone, premium band, entry timing, stops, sizing
  and loss limits are untouched in this package.
- **Success is not more trades.** A policy that only raises trade count without improving
  after-cost outcomes has not succeeded. The comparison reports both.
- **A source-to-target distance is not a profitability claim.** Room must be measured from the
  ACTUAL entry price, which is a pullback to the EMA13 and is not the breakout level, and then
  carried through the option's quote, spread and fees at that time. A distance quoted from the
  source says nothing about whether a trade clears costs. Where option evidence is missing it stays
  unknown and is reported as unknown.
- **An excluded constant is not a defence against overfitting.** Checking that a particular number
  does not appear in the source proves nothing about the policy's behaviour. The tests that carry
  weight are the behavioural ones: causal inputs only, nearest-obstacle selection, long/short
  symmetry, independence from future data, valid targets preserved, and byte-identical behaviour
  when the policy is disabled.

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
