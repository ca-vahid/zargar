# Setup-target policy: comparison against unchanged C1, and the decision

Date: 2026-09-21 · Desk: Team2 · Resolver state: **off** (`techniques.team2.setup_target=inherit`)

Reference: C1 unchanged. Variant: C1 plus setup-target-v1 only — identical sizing, execution
assumptions, contract rules, protections, no-trade zone, premium band, entry timing, stops and loss
limits. No book was altered to run this, and no new book or experiment-schema entry was created.

---

## 1. What the day actually contained

From the order-free pre-refusal audit (`zargar.tools.team2_opportunity_audit 2026-09-21`), counting
**physical candidates** deduplicated across books, revisions and repeated bars:

| | count |
|---|---|
| candidates seen before contract selection | 22 |
| admitted in at least one book | 1 |
| refused in every book | 16 |
| **never priced — no contract ever selected** | **21** |

First refusal by reason: entry gate 9, last-entry 3, **source-target collision 2**, engulfing 1,
loss cap 1.

For contrast, the selection study recorded **zero primary opportunities** for the same session. The
study begins at contract selection, so all 21 unpriced candidates are invisible to it. That gap is
the reason this audit exists.

## 2. The three categories

### Newly admitted by the variant: 1

**SPY `pm_break_up@09:45`.** Refused in C1 at 10:08 ET for the source-target collision; Control and
Sizing refused it earlier for the no-trade zone, which the variant does not change. With the
destination resolved to 767.89 (nearest valid ladder level above the 767.26 break) C1 would have
admitted it.

**Its after-cost outcome is UNKNOWN, and cannot be recovered.** The refusal happened *before*
contract selection, so no contract was ever chosen, no quote was ever fetched and none was stored.
The journal holds zero `TechniquePlanContract` rows for SPY on the day, and no SPY option expiring
2026-09-21 has a single stored bar. Inferring a 0DTE option return from the underlying chart alone
is exactly what this package is forbidden to do, so the outcome stays unknown rather than being
estimated.

What can be said without option evidence: the source-to-target distance was **0.63** (767.26 to
767.89). Room from the *actual* entry would be smaller still, because the entry is a pullback to the
EMA13 below the break level, and that entry price was never established either. 0.63 on the
underlying is a thin destination for a 0DTE contract that must also clear a spread and $1.04 per
contract per side. That is a reason for caution, not a measurement.

### Still refused by the variant: 1

**QQQ `pm_break_up@09:30`.** Its prior-day high zone (721.285–721.71) sits below the break, and its
level ladder holds **nothing** above 729.14. The variant refuses it explicitly — recorded as no
destination existing in the available structural data. Correcting the defect does not manufacture
this trade, and no level was added and no target dropped to recover it.

### Displaced by the variant: at least 1

Team2 holds **one position at a time** (`max_concurrent_positions = 1`). The desk's only two fires
on the day were IWM at 10:36 and 11:30 ET. A SPY entry admitted at ~10:08 would have occupied C1's
single slot, so **the 10:36 IWM round trip would not have happened**.

That round trip actually lost **−$140.35 gross, −$213.15 net**. The 11:30 IWM fire may or may not
have survived, depending on when the SPY position exited — which is unknown for the same reason.

## 3. The honest net effect

| | reference (C1 as it ran) | variant |
|---|---|---|
| trades taken | 2 (IWM ×2) | 1 known-displaced, 1 unknown (SPY), 1 uncertain (IWM #2) |
| known result | −$213.15 and −$178.15 net | **not computable** |

The variant trades an **unknown-outcome** SPY position *instead of* a **known −$213.15** loss. That
is not evidence of improvement. It is also not evidence against: both directions are unavailable.
On this single session the comparison cannot distinguish the policies on after-cost outcome at all.

Adverse cases considered: the newly admitted trade displaced a real (losing) trade rather than
adding to it, so a favourable-looking day could arise purely from displacing losers, which is not
the same as the policy being profitable. The thin 0.63 destination is an adverse indicator. One
session with one newly-admitted candidate and no option evidence is far below anything that could
support a verdict.

Allowance consumption is unchanged in this package, as required. Structural refusals do not spend
the two-pullback allowance, so the SPY collision refusals did not consume one; that behaviour is
identical in both arms and is documented, not altered.

---

## 4. Decision: **collect more evidence**

Not approve a separate Practice test, and not reject.

**Why not reject.** The defect is real, traced end to end through the runtime's own records, and the
correction is sound: a setup's destination must be distinct from its own source. Leaving it would
keep a known role-confusion bug in the read.

**Why not approve a Practice test yet.** A Practice test needs a new book or an experiment-schema
extension, which requires explicit activation approval, and nothing here justifies asking for it. We
have one session, one newly-admitted candidate, zero option evidence for it, and a displacement
effect that could make a bad policy look good by removing losers. Approving on that would be
approving on a story, not a measurement.

**What collecting more evidence means, concretely.** The order-free audit now exists and costs
nothing: it sends no orders, changes no setting and touches no book. Run it after each close to
accumulate pre-refusal candidates, how often the collision actually suppresses a candidate, what
destination the resolver would have chosen, and — critically — how often such a candidate is
displaced by occupancy rather than added. Revisit when there are enough newly-admitted candidates
to say something about after-cost outcomes, rather than one with no evidence attached.

The resolver stays **off** until that decision. This package changes no trading behaviour.

## 5. Limitations of this comparison, stated plainly

- One session. Monday 2026-09-21 only.
- The single newly-admitted candidate has **no option evidence of any kind**, so no after-cost
  number exists for the variant arm.
- Entry-relative room was not measurable: the entry price was never established, because the entry
  never happened.
- The displacement chain past the first IWM trade is undetermined.
- Session 1 was collected under a ~10.5 s clock skew (cohort `A-skewed-clock`), which blinded the
  `room` feature. It does not affect the structural refusals analysed here, which are computed from
  bars and levels rather than from quote ages.
