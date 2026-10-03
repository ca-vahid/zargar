# B. Does the Tips analyst give up too easily?

Window: 2026-09-08 to 2026-10-02 (UTC). "Pre" means before 2026-09-28 and "post" means from 2026-09-28 on. Read-only analysis of
`tip_analyst_runs` (kind=appraise), `signals`, `proposals`, `orders`, `managed_positions` and `events`. The scripts and
extracts are in `scratchpad/review/` (`a1..a5.py`, `data/`).

**Short answer: mostly no, but there is one real exception.** The analyst seldom stops early because it runs out of
tools or time. Most of its skips apply rules it has learned, and buy-and-hold outcomes show those rules avoided losses.
The money it left behind comes from three places:
- one gate, the 1% risk budget (about $90 per tip), which turns down about a third of genuine BTOs and still blocked 15 takes after the analyst had approved them;
- a handful of judgement skips (geometry or reach, contract identity) that turned into large runners;
- no fallback path: a "watch" never becomes an armed level, and a too-large contract is never cut down to a cheaper or defined-risk expression. The analyst skips instead.

Picking which tips to take adds only a little edge. Exit management is where the value is: on the same 36 signals, the
desk made +0.3% and buy-and-hold lost 29%.

## 1. Verdicts and what happened to the takes

There were 369 appraisal runs on 364 signals. The tables below use the latest run for each signal.

| | take | skip | watch | none (failed) | total |
|---|---|---|---|---|---|
| Pre (09-08..09-27) | 62 (24%) | 177 (68%) | 14 | 6 | 259 |
| Post (09-28..10-02) | 28 (27%) | 67 (64%) | 9 | 1 | 105 |
| **All** | **90 (25%)** | **244 (67%)** | **23 (6%)** | **7** | **364** |

**By verification state when the appraisal ran.** This is the key cut: most skips land on content that intake had already
flagged.

| verification | take | skip | watch | none |
|---|---|---|---|---|
| passed (a genuine priced BTO) | 79 | 83 | 15 | 5 |
| parked (price-position failure) | 10 | 58 | 3 | 2 |
| shadow-only (non-actionable, implied) | 1 | 103 | 5 | 0 |

**By source:**

| source | take | skip | watch | none |
|---|---|---|---|---|
| muggzone-options | 29 | 81 | 0 | 4 |
| eva | 5 | 84 | 3 | 0 |
| ab | 25 | 27 | 7 | 2 |
| tt | 6 | 20 | 3 | 1 |
| neal | 5 | 14 | 7 | 0 |
| jon-and-kian | 11 | 3 | 3 | 0 |
| common-stock | 8 | 4 | 0 | 0 |
| giul-heatseeker | 0 | 7 | 0 | 0 |
| MK-alpha-trades | 0 | 3 | 0 | 0 |
| florida-man | 1 | 1 | 0 | 0 |

**By instrument:**

| instrument | take | skip | watch | none |
|---|---|---|---|---|
| call | 74 | 157 | 15 | 7 |
| put | 3 | 26 | 2 | 0 |
| shares | 10 | 6 | 3 | 0 |
| unspecified | 3 | 55 | 3 | 0 |

By action: open = 82 take / 227 skip, add = 8 take / 17 skip.

**What happened to the 90 takes:**

| fate | pre | post | total |
|---|---|---|---|
| Filled (Tips Practice books) | 36 | 13 | **49** |
| Proposal expired waiting for a human: geometry gate said "no quantity satisfies the $89–92 risk budget" | 14 | 0 | 14 |
| Proposal expired: "contract multiplier unknown" (INTC ×2, a data defect) | 2 | 0 | 2 |
| Proposal expired: "no risk estimate: no stop" (META, tt) | 0 | 1 | 1 |
| Proposal expired: no gate reason (AVGO) | 1 | 0 | 1 |
| No proposal: the source runs in **shadow** mode (muggzone since 09-25; eva and giul since 09-28) | 0 | 13 | 13 |
| Armed at a level, never touched (GOOGL ×2, HOOD, FSLY, CRML, CAVA) | 5 | 1 | 6 |
| Order rejected by RiskGate (limit 0.25 from mid; quote age 10.5 s) or cancelled | 3 | 0 | 3 |
| Bogus ticker (NAVIDAD), parked | 1 | 0 | 1 |

Only 49 of the 90 takes (54%) became trades. **Of the 18 expired takes, 15 were refused by the risk budget, and 9 of
those 15 came after the analyst had itself called `check_feasibility` and said "take".** The analyst's feasibility check
and the geometry gate's final stop disagree. That is a platform inconsistency, not the LLM giving up.

## 2. Why it skips (267 skip/watch verdicts, keyword-clustered)

I read 55 rationales in full, stratified up to 8 per source, and then classified all 267 by regex. Each verdict gets the
first matching category, in priority order. Treat the counts as about ±10%, because many rationales cite two or three
reasons.

| primary reason | all | of which passed-verification BTOs | type | shadow P&L if bought and held (passed only) |
|---|---|---|---|---|
| Not an open: watchlist, flow-screenshot narration, recap or victory lap, status mark, digest, conditional wish | 129 | 14 | rule (verification + R1) | −45% (14) |
| Risk budget infeasible (one lot risks $100–$375 against a $88–$100 budget) | 44 | 33 | rule / arithmetic | −30% (32), 7 winners |
| Hedge leg, not to be mirrored standalone | 24 | 9 | rule | −60% (9), 0 winners |
| Chase, fill band, or price already ran | 15 | 8 | judgement backed by a rule | −85% (8), 0 winners |
| Already held, or a duplicate | 11 | 5 | rule | −76% (3) |
| Average-down, add, or escalation | 11 | 9 | learned rule | −43% (8) |
| Contract identity unresolvable (no expiry, strike or premium) | 10 | 6 | rule-ish | **+62% (5)**: LITE, QCOM |
| Geometry, reach, or counter-trend tape | 8 | 8 | **judgement** | **+54% (8)**: one winner, HOOD +882% |
| 0DTE floor or DTE window | 3 | 2 | rule | −100% (1) |
| Short premium (a sold put read as long) | 2 | 2 | rule | +32% (1) |
| Low conviction | 1 | 1 | judgement | −100% |
| Other: SPX not priceable on the venue, bad ticker | 9 | 1 | rule / platform | n/a |

**Rule-driven:** about 230 of 267 (86%) are rules, arithmetic or verification, mostly "not an open" on content intake had
already parked or shadowed.

**Pure judgement:** about 25 of 267 (9%): geometry or reach, chase, low conviction, and some identity calls.

## 3. Tool-use depth (all 369 runs)

The limits are `analyst_max_tools` = 8 and a 120 s timeout. The model was Opus 5 until about 09-23, then Opus 5.5 at
medium effort.

| verdict | runs | mean tool calls | median | 0 tools | 1–3 | 4–7 | 8+ | median duration |
|---|---|---|---|---|---|---|---|---|
| take | 95 | 5.9 | 6 | 0 | 3 | 82 | 10 | 48 s |
| skip | 244 | 2.8 | 3 | 13 | 167 | 62 | 2 | 21 s |
| skip, post 09-28 | 67 | **2.0** | 2 | 8 | 52 | 7 | 0 | 15 s |
| watch | 23 | 4.3 | 4 | 0 | 7 | 15 | 1 | 34 s |

- **Budget and timeouts:** 1 run hit the tool budget and 4 hit the final-answer time reserve (3 of those were takes).
  **The analyst is not being cut off.**
- **Skip depth by verification state:** skips on passed BTOs average 4.0 tools. Skips on parked or shadow content
  average 2.1–2.2.
- **Failed runs (7):** 5 "no JSON object in analyst reply" (Opus 5, pre), 1 interrupted by a restart, 1 timeout
  (Opus 5.5, post, 252 s).

Share of runs that used each tool:

| tool | take | skip | watch |
|---|---|---|---|
| get_quote | 92% | 67% | 78% |
| get_chain | 84% | 26% | 61% |
| get_bars | 86% | 22% | 30% |
| get_positions | 66% | 50% | 70% |
| view_image | 20% | 36% | 52% |
| check_feasibility | 68% | **5%** | 57% |
| preview_payoff | 48% | **0%** | 0% |
| get_earnings | 17% | 1% | 0% |
| search_messages | 4% | 2% | 0% |
| get_source_stats | 28% | 2% | 13% |

- **Market checks on skips:** 75 of 244 skips (31%) were decided without any quote or chain. Almost all of those are
  verification-failed non-opens, which is reasonable.
- **News:** there is no news tool. Event context is in the header, but `research.macro_events` is empty, as already
  documented.
- **Risk-infeasible skips:** of the 44, only 23 called `check_feasibility`, only 1 called `preview_payoff`, 16 mention a
  spread and 10 mention a shares alternative. When a contract does not fit, the analyst says so and stops. It does not
  look for a cheaper strike, a later expiry, a debit spread or the shares alternative.

## 4. "Gave up too easily?": outcomes

**How the proxy works.** Each source's immediate shadow book buys the tip's own contract at tip time, about $2k per tip.
It holds to expiry, a bracket, or settlement. Positions still open are marked at the 10-02 chain mid, at intrinsic value
if expired, or at the last 1m close for shares. 11 episodes with no mark are excluded.

**Caveats.** This is buy-and-hold at shadow size, not what the desk would have done: the desk buys about 1 contract,
averages about $970 deployed per fill, and trims at +50% and +100%. Sample sizes are small and the results are dominated
by a few runners.

| group | n with shadow data | shadow P&L | pooled | median | winners | ≥ +50% | ≤ −90% |
|---|---|---|---|---|---|---|---|
| Takes | 72 | −$31.9k | −21.5% | −26% | 21 | 7 | 24 |
| Skips on passed BTOs (genuine trades declined) | 91 | −$55.4k | **−31.3%** | — | 15 | 10 | 48 |
| Skips/watch on non-passed content | 98 | +$19.8k | +9.9% | — | 36 | 12 | 23 |
| ...excluding eva's two MRNA flow-tile runners (+$48.5k) | 96 | about −$28.6k | about −15% | — | — | — | — |
| All skip/watch excluding eva MRNA | 186 | −$82.2k | −22.2% | — | — | — | — |

Underlying move in the tip's direction, 5 sessions later (daily bars):

| group | n | mean | median |
|---|---|---|---|
| Takes | 43 | +2.6% | +0.3% |
| Passed-BTO skips | 74 | +2.2% | +1.0% |

There is no meaningful difference.

**What the takes actually made, with the analyst's exits:** 49 fills, −$1,160 on $47.5k deployed (−2.4%), 21 of 49 won.

| | pre | post |
|---|---|---|
| Fills | 36 | 13 |
| P&L | −$1,201 (−4.7%) | +$42 (+0.2%) |

On the **36 matched signals**, the desk made **+$120 (+0.3%)** and the shadow buy-and-hold lost **−$21,040 (−29%)**.

Worst real takes:

| ticker (source) | P&L | return |
|---|---|---|
| CCXI (florida-man) | −$480 | −67% |
| AAOI (ab) | −$210 | −36% |
| APLD (ab) | −$204 | −30% |
| GS (eva) | −$170 | −36% |

Wins are small (best: GOOGL +$250, ON +$159). Take confidence sits at 0.45–0.62 and does not predict P&L.

**Forgone runners.** 22 of 189 skip/watch verdicts gained ≥ +50% in shadow. The 10 that were genuine BTOs:

| date | source | ticker | gain | skip reason |
|---|---|---|---|---|
| 09-17 | muggzone | HOOD 110C | +882% (+$13.2k shadow) | judgement: "setup passes my filters" yet skipped on reach/geometry |
| 09-25 | ab | LITE | +212% (+$9.3k) | no expiry; analyst inferred 0DTE |
| 09-16 | ab | SPY 760C | +300% (+$6.0k) | risk budget |
| 09-17 | tt | MU ×2 | +118%, +124% | risk budget / average-down |
| 09-11 | muggzone | QCOM | +141% | identity |
| 09-16 | neal | TQQQ | +116% | budget |
| 09-24 | ab | AAOI | +85% | budget |
| 09-22 | muggzone | MRNA | +59% | budget |

At desk size (1 contract, trimmed at +50% and +100%), the realistic forgone amount is perhaps $1–3k in total, not the
$40k+ the shadow shows.

**Losses avoided.** These categories lost heavily in shadow:

| category | shadow return | winners | shadow loss |
|---|---|---|---|
| Hedge-leg skips | −60% | 0 | — |
| Chase skips | −85% | 0 | — |
| Average-down skips | −43% | — | — |
| Budget skips | −30% | 7 of 32 | −$20.7k |

## Findings

1. **The analyst is not starved of tools or time.** 1 of 369 runs hit the 8-tool cap and 4 hit the time reserve. Median
   skip time is 21 s. Raising `analyst_max_tools` alone would change almost nothing.
2. **Most skips are correct by rule.** 161 of 244 skips land on content intake had already marked shadow-only (103) or
   parked (58), and about 14 more are non-opens that passed verification. The analyst mostly confirms what verification
   said.
3. **On genuine BTOs it takes about half:** 79 take versus 98 skip or watch. The declined BTOs did *worse* in shadow
   (−31%) than the taken ones (−21.5%). Selection has a weak positive edge of about 10 points. It is not too timid.
4. **The 1% risk budget (about $90) is the biggest single blocker.** It is the reason for 33 of 98 BTO declines, 15 of 90
   takes expiring, and 13 of 23 watches. Each time, one lot of a normal $2–3 option at a structure stop risks
   $100–$375.
5. **The analyst and the gate disagree.** 9 takes passed the analyst's own `check_feasibility` and were then refused by
   the geometry gate ("no quantity satisfies… one unit risks $98–$292"). Separately, two INTC takes died on "contract
   multiplier unknown", which is a data defect.
6. **When something does not fit, the analyst does not look for another expression.** Among budget-infeasible skips,
   `preview_payoff` ran in 1 of 44, there is no search for a cheaper strike or expiry, no debit spread is proposed, and
   the shares alternative is mentioned in only 10. This is the most plausible sense in which it "gives up".
7. **"Watch" is a dead end.** 23 watches, 0 armed plans and 0 re-appraisals. Only 3 of those tickers were later taken,
   from new tips. Recovery treats watch as decline, so a "watch at 144–151" goes nowhere.
8. **Judgement skips are the expensive ones, but there are few.** Geometry/reach (8) and identity (6) skips gained
   +54% and +62% in shadow, entirely from HOOD, LITE and QCOM. The sample is too small to call this a pattern. HOOD's
   rationale says the setup passed its filters and it skipped anyway, which is a candidate for a second-opinion rule.
9. **Exits are where the edge is.** On the same 36 signals the desk made +0.3% and buy-and-hold lost 29%. The analyst's
   stops and trims cut the −90% tail. Any loosening of entry selection should keep that exit authority.
10. **Post-09-28 skips are shallower** (2.0 tools, 8 with zero tools), because muggzone, eva and giul are now shadow
    sources and most of what reaches the analyst is non-actionable. 13 post-period takes went nowhere purely because
    of source policy.
11. **The real book has no edge yet.** 49 fills, −2.4% pooled, small wins. Taking more trades at the same quality
    would add variance, not expected value. Shadow results for takes are −21.5% buy-and-hold.
12. **The data is fragile.** Two eva MRNA flow-tile runners (+$48.5k shadow) flip the entire skip cohort from −22% to
    +10%. Any "forgone P&L" headline here is dominated by one or two trades, so use date-clustered intervals before
    acting.
13. **Failures are rare and old.** 5 "no JSON" failures, all on Opus 5 before about 09-23, and 1 timeout on Opus 5.5.

## Improvement options

| # | option | expected impact | risk / cost |
|---|---|---|---|
| A | **Fit-or-reshape before skipping.** When `check_feasibility` returns qty 0, require one pass over cheaper strikes or later expiries, a debit spread (native mleg exists), and the shares alternative, using `preview_payoff`. Skip only if none fits. | Converts some of the 33 budget-declined BTOs and some of the 15 budget-expired takes. Biggest lever. | Spreads cap the runners that made the forgone list. More tool calls (budget is fine). Spread fills on SnapTrade are Webull-only. |
| B | **One feasibility authority.** Make the gate's final-stop arithmetic the analyst's `check_feasibility` output, or have the gate return the fitting stop or qty to the analyst for one revision instead of expiring the card. Also fix "contract multiplier unknown". | Recovers most of the 9 "take → refused" cases and the 2 INTC cases. | Low. It is a correctness fix. |
| C | **Revisit the risk budget for Practice.** For example, 1.5–2% or a $150 floor in Practice only, logged in PLATFORM-RULES, and re-tightened before real money per PRE-LIVE-PROFILE. | Unblocks most one-lot $1–3 options. | More variance on a book with −2.4% realized. Needs a preregistered cohort. Do not treat it as a fix for edge. |
| D | **"Watch" becomes an armed level** when the analyst names a level and stop (ARM-PLAN `at_level`). Expire it at the tip horizon. | Turns 23 dead verdicts into conditional entries; a few would fill. | Level-touch fills inherit the armed-book record, which is unproven. The trust bar is judged on the armed book anyway. |
| E | **Second-opinion pass on judgement skips of a verified BTO** (geometry, reach, chase, identity) where the tip "passes filters". A cheap, short re-check with the opposite framing; flip only on a concrete reason. | Targets the HOOD/LITE/QCOM pattern. | Extra paid call on about 10–15% of appraisals. A small sample suggests the effect is small. A/B it in frozen replay first (`tip_frozen_*`). |
| F | **Explicit pre-skip checklist in the prompt** for verified BTOs: quote, chain, bars, feasibility, alternative expression and earnings, all called before a skip. | Raises depth on the 83 BTO skips from about 4 to 6 tools. More consistent rationales. | Mostly cosmetic for rule skips. Adds about 15 s per run. |
| G | **Smaller-size or "starter" lane.** Allow 1 lot with a premium stop sized to the budget, flagged as a lower-conviction tier, instead of a skip, when the only problem is stop width. | Some participation in runners. | The analyst already rejects "decorative" stops as noise-triggered, so expect more stop-outs. |
| H | **Do not raise `analyst_max_tools`** for its own sake. | None measurable. | Cost only. |

**Recommended order:** B (a correctness fix), then A, then D. Treat C, E and G as preregistered Practice experiments
measured on real fills with date-clustered intervals, not on the shadow buy-and-hold proxy. The proxy overstates both the
upside (no trims) and the downside (no stops).

**Sample-size honesty:**
- 49 real fills;
- 91 passed-BTO skips with shadow data;
- one window of about 18 sessions;
- shadow P&L at about 2× desk size, buy-and-hold;
- regex reason clustering is approximate.

None of the outcome differences above would pass a significance test without the top two or three trades.
