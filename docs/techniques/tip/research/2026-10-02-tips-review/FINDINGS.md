# Tips desk - full review before real money (findings, 2026-10-02)

**Scope.** The whole Tips record: the Practice book opened 2026-09-08 ($10,000), the fresh-start book from 2026-09-28,
the per-source shadow books, every analyst run, every alert's timing, the event data, the architecture for running
Practice and live together, and an external evidence review. Read-only throughout - nothing was changed while
reviewing. Six detailed reports sit beside this file (appendices A-F); every number below is net of
`executions.commission` and traceable there.

**This is findings, not the plan.** The plan is written next, from section 9.

## 1. Bottom line

1. **Tips has no demonstrated edge yet - but the desk's execution is worth something.** Buying every tip at tip time
   (shadow books) lost about **-25%** of cost. The desk, trading the same signals with shares-first sizing and stops,
   lost far less (-7% vs -30% on the 29 signals both traded) and the fresh-start book is slightly positive
   (+$102 realized on 9 trades). The value is in *how* we trade, not in *which* tips we pick.
2. **Options were the loss.** Shares made **+$259 on 22 trades**; options lost **-$1,244 on 24** (-14.6% of notional) and
   paid all the fees. External evidence agrees: retail short-dated option buyers lose at every horizon, mostly to
   spreads (weeklies fill about 6.6% wide). Shares-first was the right call.
3. **The worst damage was early and is fixed.** 12 trades before per-trade risk sizing (09-08..09-16) lost **-$1,152**;
   since sizing, the old book recovered +$376.
4. **The analyst does not "give up too easily" in the sense of quitting early** - it rarely hits its tool budget and
   most skips (~86%) are rule-driven and avoided losses. It does give up on *good ideas that don't fit one contract*:
   it never looks for a cheaper strike, later expiry, spread or shares when the first contract is too big.
5. **Several real defects** would cost money live (section 6). None is exotic; all are fixable before go-live.
6. **Model cost was the biggest single drag** ($873 over the window); since 09-28 it runs about $6-11 a day.

## 2. Scoreboard

| | trades | realized net | win rate | payoff | per trade |
|---|---:|---:|---:|---:|---:|
| Old Practice book (09-08..) | 37 | **-$1,086.82** | 35% | 0.92 | -$29.37 |
| New Practice book (09-28..) | 9 | **+$101.66** | 56% | 1.41 | +$11.30 |
| Shares (both books) | 22 | +$258.78 | | | |
| Options (both books) | 24 | -$1,243.95 | | | |
| Model cost (list price) | | -$872.64 | | | ~$37.6 since 09-28 |

By exit class: trailed stop **+$657** (7), target **+$402** (4), initial stop -$762 (13), premium stop/bleed **-$1,212**
(11, zero wins), opening minutes 09:30-09:35 -$962 (11), mirrored source exit -$115 (7).

By source (desk): **neal +$185.50 on 4** is the only source positive in every view; **ab -$368.79 on 16** is the most
traded and the worst; florida-man -$505 and eva -$172 are single trades. Shadow "buy every tip": ab -24.9%,
eva -29.0%, muggzone -33.8%, neal **+9.5%**.

## 3. What we did right

- **Shares-first (09-25).** The cleanest result in the record; matches external evidence on option costs.
- **Risk-based sizing (from 09-16).** Stops fill at -0.97R..-1.03R - the plan is honoured; the bleeding stopped.
- **Letting winners trail.** Trailed stops and targets are the only positive exit classes (+$1,059 together).
- **Instrument-matched mirroring (Q2).** Copying a source's trim only on the leg we hold avoided false trims.
- **Quote-watch targets, stale exit, 7-slot cap, lotto off** - small samples, all behaved as designed.
- **Cost discipline.** Model spend fell from ~$116/day to ~$6-11/day with caching, the gate and Opus 5.5 medium.
- **Speed.** Post-to-fill median **47 s** since 09-23 (66.7 s overall); the underlying barely moves in that time
  (median +0.04%, 1 of 51 fills worse than 0.25R).

## 4. What went wrong (and risks taken too hastily)

- **Started with options and no per-trade risk sizing** - the -$1,152 first week.
- **Opening-minutes option stops** - 6 premium stops in 09:30-09:35 lost -$830 (P3 grace now covers this).
- **Premium stop / bleed exits never won** (0 of 11). The rule cut options that were bleeding on spread and theta,
  not on the thesis.
- **Human-review cards never got a human.** 119 cards waited for a person; **0 approved**, 20 expired - 12 of them
  after the source had already exited. A 2-hour card life is far longer than these trades last.
- **Too many ideas are pre-market maps split into branches.** 234 signals in 09:15-09:29 (mostly eva) became 72
  proposals and **0 fills**.
- **Sizing lands below budget.** New-book planned risk is a median **$57 against a $100 budget**; several positions
  risk $10-25. Capital deployed in market hours averaged 27% (old) / 48% (new).
- **Hasty changes, knowingly:** P3 opening grace shipped without its replay; the review gate went to enforce on one
  session of evidence; the fresh-start reset reset counters mid-measurement. Each was a user decision; each leaves the
  measurement thinner.
- **Events handled by hand.** The verified-events list is edited manually, never held CPI, and each edit overwrote the
  last (history lost). Nothing blocks entries before events; the only enforcement is "flatten shares the day before
  earnings" - and entries were still made inside that window (ORCL shadow: bought, force-sold 9-13 min later).
- **The host machine.** Memory under 1 GB twice froze the app (09-28, 09-29), dropped the Alpaca feed and once killed
  the API socket. Real money cannot ride on that.

## 5. Missed opportunities

- **Budget skips of genuine trades:** 18 declined ideas failed the risk budget as one contract (5 after 09-28), with
  no cheaper or share alternative offered. The clear misses: **neal TQQQ** (+16% underlying, shadow +108%), **ab SPY
  9/25 760C** (shadow +299%), **ab LITE** (+15%), HOOD, MU, QCOM, AAOI, MRNA. Realistic value at desk size with trims:
  roughly **$1-3k** over the window - not the $40k the shadow books show (they hold to expiry at ~2x size).
- **Gate/analyst size mismatch:** 15 "take" cards expired because the geometry gate refused the size - **9 of them had
  passed the analyst's own feasibility check** (two different risk calculations).
- **"Watch" is a dead end:** 23 watch verdicts produced zero armed levels.
- **Options rejected by a units bug** (premium target compared with the stock price): at least 11 real option buys,
  most recently MSFT 505C on 09-28.
- **No measurable selection edge either way:** declined ideas moved +1.19% in 5 days vs +0.04% for takes (n=170 / 52) -
  the analyst is not yet *adding* value by picking; it mainly avoids non-opens and chases.

## 6. Defects found (must fix before live)

| # | Defect | Impact | Appendix |
|---|---|---|---|
| D1 | Units check compares an option's premium target with the stock price when the instrument is "unspecified" | real option buys dismissed (>= 11) | C |
| D2 | Analyst feasibility check and the geometry gate use different risk arithmetic | 9 approved takes expired | B |
| D3 | Simulated option fills far below their limit (MRNA 0.75 vs a 2.01 ask; AAOI, DAL) | Practice results overstated | C |
| D4 | Gateway holds a per-channel lock through the whole appraisal; 2 workers | 22% of messages waited > 10 s | C |
| D5 | Host clock drifts ~1 s/day (10.5 s by 09-21) vs a 10 s quote-age limit | an order refused as "stale" | C |
| D6 | Verified-events list overwritten on each edit; no tiers; CPI missing; bill auctions count as events (221/236 "event-day") | event data unusable | D |
| D7 | Entries allowed inside the earnings flatten window; armed plans fire through FOMC | buy-then-force-sell; event fills | D |
| D8 | "Contract multiplier unknown" data defect (INTC) | takes lost | B |
| D9 | Two non-quarantined shadow books ("Shadow: tt", "Shadow: ab (armed)") have sells with no matching buy | source comparisons wrong | A |
| D10 | Recovery-sweep auto-approve skips the earned-trust gate; integrity incidents scoped only to `default_portfolio` | wrong book paused in a fan-out | E |
| D11 | The analyst's chosen quantity overrides budget sizing | would copy Practice quantities to a live book | E |
| D12 | Rule-audit judge calls fail with an empty error (09-29: 2 of 22 returned) | maintenance only | EOD 09-30 |

## 7. Answers to the specific questions

**Do we need a calendar? Yes - earnings: enforce; macro: as a risk tool.** External evidence: buying options into
earnings is where retail loses most (implied volatility collapses after the release); the pre-FOMC drift faded after
2015 and CPI/jobs show no drift, so macro events matter for *risk* (wider ranges - SPY's FOMC-day range was 1.59% vs a
0.71% median), not as a signal. Desk evidence: the 11 trades held across a major release made +$245 vs -$1,017 for the
other 36, but that is survivorship and tiny samples. Proposal (D): one append-only event store fed from official
sources (Fed, BLS, BEA, Treasury) plus two-source-confirmed earnings dates; enforce "no entries inside the earnings
window" now; run "no new entries around tier-1 releases / half size across one / no short options through one" in
observe first and promote on >= 25 affected trades over >= 6 events.

**Does the LLM give up too easily? Not by quitting early - by not looking for another way.** Tool depth is not the
problem (1 run hit the cap). Make it search for an alternative before a budget skip (cheaper strike, later expiry,
debit spread, shares); make "watch" with a level become an armed level; align its feasibility with the gate. More tool
turns alone would change nothing measurable; a second-opinion pass on *judgement* skips (~9% of skips) is worth a test.

**Alert timing.** Speed is fine for shares; for options each second costs about 0.1% of premium (8 of 22 option fills
> 1% worse than the post). Cheap wins: fix D4/D5, preload quotes/chains (saves 8-15 s), buy-at-ask limits capped near
the source's price (never market). A "fast lane" for clean priced buys saves ~30 s - test in shadow first because most
appraisals are skips. Cards that wait for a human should live ~15 min (0DTE) or be decided automatically on Practice.

**Options at all?** Only for sources that earn them on graded outcomes, longer-dated and tight-spread, filled with
limits near the mid. On the live book: shares only (already enforced in 0.8.58).

**Sources.** Score each source on its own graded record (external evidence: 56% of social-media tipsters have negative
skill and the popular ones are worse). Today only neal is positive everywhere; ab is the most traded and the worst.

**Exits.** Keep trailing and targets; re-examine the premium stop/bleed rule (0 wins in 11) and the initial-stop class;
mirrored exits are roughly flat (-$115 on 7) and worth keeping mainly as risk control.

**Sizing for a $3k cash account.** Fixed-fractional risk works (stops honoured); raise realised risk toward the budget
(median $57 vs $100); cap open positions to what settled cash allows (US T+1 since 2024-05-28; the exact IBKR
good-faith rules for a Canadian cash account must be confirmed with IBKR before same-day round trips).

## 8. Practice and live running together (requested architecture)

Today one setting (`techniques.tip.default_portfolio`) picks one book; `trading.mode` is both the screen view and the
live-order gate; nearly every budget is a global value. Proposed (appendix E):
- `techniques.tip.books`: a list of linked books - each with role (practice | live), budget, max positions, dollar
  cap, enabled, live-auto acknowledgement, primary flag. Empty list = today's behaviour.
- **The analyst appraises once per signal**; each linked book then gets its own proposal, sizing (rescaled to that
  book - fixes D11), gates and auto-approve decision; exits and mirrors run per book.
- **The mode toggle becomes a view filter** (browser-side); live routing becomes its own server switch plus each
  book's enabled flag. Options Cartel also reads `trading.mode` and needs a coordinated change.
- Guard against double counting: earned trust, nightly retros (paid), the entry study and card alerts must count each
  idea once; the orders-per-minute limit and the per-technique day notional are shared across books.
- Rollout: empty list -> Practice only -> Practice + IBKR paper -> Practice + live.

## 9. Improvement options (input to the plan, ranked by evidence)

**Before any real money (defects and safety):** fix D1-D11; move the app to a machine (or settings) with enough memory
and NTP clock sync; quarantine the two bad shadow books; confirm the IBKR cash-account settlement rules.

**Profit levers with evidence:** keep shares-first; let the analyst find a fitting alternative instead of a budget skip;
make watches arm; align feasibility with the gate; buy-at-ask limits capped near the source's price; re-tune or drop
the premium bleed rule; raise realised risk toward budget; earnings entry block.

**To test before adopting (shadow/observe first):** macro-event rules; a fast lane for clean priced buys; a second
opinion on judgement skips; a reduced-size starter lane; per-source option permission earned on graded outcomes.

**Architecture:** the multi-book method binding (section 8), with Practice and live running side by side.

## 10. What the evidence cannot tell us yet

9 closed trades on the new book; 49 fills in the analyst window; ~18 sessions. Nothing here passes a significance test.
Two MRNA runners flip the shadow skip result from -22% to +10%. Every proposal above is framed so that it either fixes
a defect or is measured before it is trusted.

## Appendices

- [A - outcomes, exits, sizing, shadow books](A-outcomes.md)
- [B - analyst behaviour](B-analyst.md)
- [C - alert timing and latency](C-timing.md)
- [D - events and calendar](D-events.md)
- [E - Practice + live architecture](E-architecture.md)
- [F - external evidence (deep research, 105 agents, 3-vote verification)](F-external.md)
