# EM: where the money actually is, and what to do about it (2026-09-22)

Written after the first session in which both EM books traded, at the user's request to review, remove any useless
books, and make the approach more profitable. It separates what the evidence supports from what it does not, because
the fastest way to lose money with a method that has no proven edge is to keep tuning it on the last few days.

## The bottom line

**1. EM has not made money.** Every closed EM trade across all three books, matched first-in-first-out from fills:

| | Value |
|---|---:|
| Closed trades | 38 over 8 sessions |
| Net after fees | **−$219.40** |
| Net if the disputed ORCL fill is priced at the ask | **about −$336** |
| Win rate | 29% |
| Average win / average loss | +$104.91 / −$50.87 |
| Profit factor | 0.84 |
| Trades ending at the stop | 27 of 38 (71%) |

The 95% range for the average trade runs from about −$31 to +$23, so the record cannot show an edge either way. It is
too short to say the method is broken, and far too short to say it works.

**2. All EM trading is simulated. The only real money EM spends is the model review.** Both EM books are `sim` with
live trading disallowed. The baseline's nightly preparation reviews every setup with a paid model: about **$50 to $62
per night**, or roughly **$1,100 to $1,300 a month** at the current price card. The experimental book prepares with
rules only and makes **zero** model calls. That is the most direct real-money lever EM has.

**3. The method's author has no verifiable track record.** His posts for today could not be read without logging in,
and every result he has published is a win, used to market a copy-trading product. No independent or broker-verified
record was found. EvaPanda, whose watchlist was the only morning note today, is a separate contributor. So the method's
worth has to be proven by our own records, not borrowed from his.

## Books: nothing to remove

There is **no useless EM book**. EM has exactly two, and both are needed:

| Book | Role | State |
|---|---|---|
| EM Practice | the baseline, and the experiment's control | active, traded today |
| EM Experimental | the integrated bundle under test | active, traded today |

The only candidate is the old shared book, **"Practice (archived 2026-09-07)"**. It is already archived, which is the
app's proper way to retire a book: it leaves every list and total while keeping its history. It is not really EM's
either: EM placed 5 of its 47 orders, and its three open positions (RKLB call, ZURA, SOFI) were opened by the Tips
signal path. Deleting it would destroy shared history and orphan another desk's positions, so it is left alone. One
cosmetic inconsistency is recorded for the platform owner: it is still flagged as the default book, although nothing
routes by that flag.

## Where the losses come from

These buckets overlap heavily - every short is a put, and most midday trades are shorts - so they are one cluster, not
three findings.

| Bucket | Trades | Net | Win % | Reading |
|---|---:|---:|---:|---|
| Short puts (reject) | 14 | −$316.66 | 29% | candidate problem |
| Midday entries | 9 | −$228.84 | 22% | candidate problem, 7 of 9 are shorts |
| Long shares (the fallback when no option is tradeable) | 14 | −$185.82 | 21% | candidate problem |
| Long options | 10 | +$283.08 | 40% | not a real strength: rests on three wins, one of them the disputed fill |
| Long, prime open | 20 | +$143.56 | 30% | tentative |

**It is an entry problem, not a stop problem.** Of the 27 trades that stopped out, 18 kept moving at least another 1R
against the position afterwards: the stop saved money and the entry was wrong. Only 6 later reached their first target.
Wider stops would have lost more.

**Friction is large against small option positions.** Fees were $93.60, and the entry-side spread cost about $167
across 24 option trades, with the exit side estimated at a similar size. All-in option friction of roughly $380 to $480
sits against an option gross of **+$60**. On one to four contracts with quoted spreads of 5 to 8%, the method needs a
large edge just to break even.

## What I changed tonight: one thing

**Midday trading is turned OFF** (`technique.arm.midday_trading`: true to false, journaled as `SettingChanged`).

This is not a claim that it will make EM profitable. It is ending an experiment that answered its question:

- The method's own rule R6 says midday is chop and watch-only, and the toggle's default has always been off.
- The experiment was built to find out whether allowing midday adds value. Its preregistered threshold of 30 scored
  midday fires is met (62 fires), and its filled trades lost: **−0.30R per trade**, total −2.40R, 22% winners.
- Honest caveat: the prime windows are negative too (−0.09R per trade), and midday is not statistically distinguishable
  from them (permutation p = 0.36). Midday is a worse slice of a losing method, not the one thing to cut. Returning to
  the book's documented rule is the conservative move; it is the absence of evidence *for* midday that decides it.

It applies to both books equally, so the comparison between them stays fair, and it takes effect at the next fire.
Rollback is the same key set back to true.

## What I deliberately did NOT change

Each of these points the same way as midday, and each is below the bar the desk set for itself. Changing them tonight
would be fitting the method to the last few days.

| Candidate | Evidence | Why it waits |
|---|---|---|
| Stop taking short puts | 14 trades, −$316.66 | half of them were midday; with midday off, the prime-window shorts are 7 trades |
| Stop the shares fallback | 14 trades, −$185.82 | preregistered threshold is 20 fallback events |
| Widen the flat 0.5% stop floor | 2 of 7 setups reversed after stopping | the other 5 were wrong entries; widening would have lost more |
| Tighten the option spread limit | friction exceeds option gross | exit-side spreads are not yet recorded, so the true cost is unknown |

## Recommendations that need your decision

1. **Adopt a stop rule for EM itself, now, before the answer is known.** After **20 evaluable sessions**, if EM's
   cumulative R is at or below zero and the upper bound of the average trade is below +0.1R, stop paying for the model
   review and keep EM in observation only: plans recorded and scored, no money spent. Deciding the rule in advance is
   what stops a losing method from being tuned indefinitely.
2. **Let the A/B decide the real-money question.** The two books differ mainly in how they prepare: paid model review
   versus free rules. If, over those sessions, the rules-only book does no worse, the model review is not earning its
   $1,100+ a month and should stop. Today the rules-only book took more trades and lost more, but that is one day.
3. **Deploy the September 21 package in a dedicated off-hours window**, not tonight. It carries the systemic admission
   alarm and the fix that makes share observations scorable. It now sits 44 commits behind the running build, so it is
   a real integration, and it restarts the engine for every desk.
4. **Fix BRK.B's live bars.** Its plan saw one bar in every three to five minutes all session while storage holds all
   390. A plan that misses its trigger bar cannot trade correctly, and the stored record hides the gap.

## Preregistered tests to run, not changes to make

Each one is decided by data that now accumulates on its own, with the threshold fixed before the answer is seen:

- **Shares fallback vs options**: R and dollars over at least 20 fallback events (existing threshold).
- **Short puts in the prime windows only**: now that midday is off, over at least 20 trades.
- **Stop size against volatility**: for each stopped trade, stop distance divided by the stock's recent one-minute
  range, and whether price later reached target. The early hint is that stops under two average ranges get whipsawed
  more often (4 of 11 reached target, against 2 of 16 wider ones).
- **One-touch carried levels**: whether rejects off a level touched only once lose disproportionately (CRWV today).
- **Rules-only vs model-reviewed selection**: the experiment itself.

## Known data defects that bias these numbers

- **ORCL, 2026-09-17**: a buy limit at $2.29 recorded a fill at $1.12, below any price offered. It is already on the
  disputed list and overstates the record by about $117.
- **Option exit spreads are not recorded**, so friction is part measured and part estimated.
- **The capture recorder flags quote-time skew** on option observations, most likely because OPRA `source_ts` is the
  poll time rather than the vendor time (found by the Team2 desk).

## Implemented 2026-09-22 (user decision: "implement this fully")

| Plan item | Where it lives now | State |
|---|---|---|
| 1. EM stop rule | `technique/em_scorecard.py` (`em-stop-rule-v1`), `tools/em_scorecard.py`, close check writes `research/experiment/<date>-scorecard.md` and raises keyed `stoprule` | adopted; collecting 1/20 |
| 2. A/B decides the paid review | preregistered test `rules_vs_model` (20 sessions); switch `techniques.enhanced_market.paid_review` (default on) honoured by `scripts/em-evening-batch.py` | collecting |
| 3. Sept-21 package deployed in an off-hours window | with this release, through `scripts/deploy.ps1` after the evening batch finishes | see the release receipt |
| 4. BRK.B live bars | `is_us_share_class` in `brokers/alpaca.py` - BRK.B streams from Alpaca (PLATFORM-RULES 2026-09-22) | fixed |
| Preregistered tests | `em_scorecard.TESTS`; TRADING-RULES §5 2026-09-22 (late) | collecting; a ready test raises keyed `decision` |
| Exit-side spreads | `TechniqueExitQuote` (`exit-quote-v1`) | recording from 2026-09-23 |
| Recurring preparation | weekday tasks `ZargarEmEveningBatch` 14:05 PT + `ZargarEmAfterArming` 14:07 PT | replaces the per-date one-offs |

Still a human step, by design: switching `paid_review` off when the stop rule trips, and every decision a ready test asks
for. No threshold, stop, vehicle or window was changed by this implementation beyond the midday switch above.
