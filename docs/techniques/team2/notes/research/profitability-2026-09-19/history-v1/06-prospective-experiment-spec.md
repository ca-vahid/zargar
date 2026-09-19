# 6. Prospective experiment specification

## What did NOT earn a prospective trading arm

Nothing. Nine registered arms failed on the training window. Launching a fourth Practice trading book now would be activity, not
evidence. This page specifies the experiment the evidence does support: an order-free SELECTION study, run on fresh sessions,
that can tell us whether any observable, codeable property separates the entries that work from the ones that do not, and whether
that property is what the author is using. It ends in the same three-way decision.

## Experiment S1: "A+ selection", order-free, one factor at a time

| Item | Specification |
|---|---|
| Label | `team2-selection-study-2026-09` (research register; no portfolio, no orders, no proposals) |
| What runs | The existing shadow diagnostics (`TechniquePlanDiagnostic`, live since v0.8.05) already record every examined entry with its real quote, follow-ups at 2, 5 and 10 minutes and at the exit. S1 adds FEATURES to that record, computed at the decision from bars that have closed, and changes no decision |
| Features (frozen list) | F-a flag: the three 2m bars before the touch are inside bars or a narrowing range (5m confirmation, the unwired `flag_tf_min`). F-b level age: the anchor level is from the previous session vs two or more sessions old. F-c wait: minutes since the 15m confirmation (under 15, 15 to 60, over 60). F-d first fifteen minutes (09:45 to 10:00) vs later. F-e scenario 4 vs the rest. F-f room to the target in ATR (under 1.5, 1.5 to 3, over 3) |
| Outcome | Real quoted return of the contract the picker chose (ask in, bid out, two commissions), at 10 and 30 minutes and at the read's own exit. Quotes, not prints: this removes the largest limitation of the historical study |
| Why these six | F-a, F-b and F-c are the author's own words (flag, multi-day level, "waited almost five hours"). F-d, F-e and F-f are the three cells that looked positive in the historical tables and must be treated as found by looking: S1 is where they get a fair test |
| Sample | Fresh sessions only, from the first session after acceptance. Minimum 150 examined entries (25 to 40 sessions: the replay produced 3.6 entries per session across three symbols, the desk-wide caps roughly halve that). No look before 150 |
| Analysis (frozen) | For each feature, mean quoted return at the read's exit in the favoured bucket minus the rest, with a bootstrap 95% interval. One feature "passes" if its interval excludes zero AND the favoured bucket's own mean is above zero after fees. Six features, so at least one false pass is expected in about one study in seven; a single pass earns a trading arm, not an adoption |
| Then | The passing feature, alone, becomes ONE separately labelled Practice book against Control on fresh sessions (the existing experiment schema supports it), with the sizing of the Sizing 0.5 book, the -$800 sampled review level and twenty sessions. Adopt only if that book's actual after-fee result beats Control's actual result with an interval that excludes zero |
| Stop early | Never for good results. Stop if diagnostics coverage (entries with a valid quote at both ends) falls under 80% |
| Cost | No orders, no model calls. One small code change: the feature block in `diagnostics.py` plus tests, shadow-only, reviewed as one package |

## Evidence to collect from the author (no code)

1. His LOSING alerts with entry, exit, premium and minutes held: at least ten. Today there are five mentions and no numbers. Without
   them his stop tolerance, his real win rate and his loss size are unknown, and "a candle or 2" cannot be resolved.
2. The 2026-09-17 red-day post (exists, not captured).
3. For each new alert: the clock time of the alert, the contract and the price. With 20 timed alerts we can measure how often our
   read had fired by then, was refused (and by which rule) or had seen nothing. That is the prospective version of the six-row
   ledger on page 3 and it is the only fair way to rank our refusal rules.
4. Whether he trades a fixed size. It decides whether the 6% risk sizing is ours alone.

## Decisions for the owner and the review team, in order

1. **Sizing now.** The historical book at 6% risk draws down by the size of the account and rests on three days. Pausing the
   three books until S1 reads out, or halving the risk for all three alike, tightens protection and keeps every between-book
   difference intact. I changed nothing; this needs an explicit yes.
2. **Re-score the accepted sheets.** The sizing sheet and the C1 comparison were scored with the pricing formula this study shows
   to be wrong by sign. Re-running them on real prints is a day of work with the harness in this package.
3. **Replace the formula in the product replay and sweep** with real prints where they exist, and mark formula-priced results as
   such in the UI. This is infrastructure that corrupts evidence, which the goal puts in scope; it is a separate package.
4. **Accept or amend S1.**

## Final recommendation on the goal's question

- Nine bounded improvements: **reject**.
- The automated Team2 method as it stands: **insufficient evidence of profitability**, with a measured after-fee expectation of
  about -4% per trade (interval -7.6% to +0.1%), no directional information at the actionable price, and book results that
  depend on three days. It should not be promoted, and it should not be given more size.
- The author's method: **not tested**. What we automate is the mechanical skeleton of it. The part that may carry his edge is
  selection, and his published record cannot tell us, because it contains no losers.
