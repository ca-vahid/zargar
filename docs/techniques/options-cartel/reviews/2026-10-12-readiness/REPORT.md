# Cartel is not ready for real money

**Options Cartel is not ready to trade real money next month, and it cannot trade options on Wealthsimple at all through this app.** The belief that "the plan is working well" rests on one trade: a single purchase of DHT call options that is up about $1,060 on paper, with nothing else behind it. The 20-session Practice experiment has produced **1 entry and 0 fully closed trades** against the 8 it needs, and it has been silently switched off since the week of 5 October. The bookkeeping adds up to the cent, but the headline profit is flattered by an optimistic entry fill and an optimistic valuation, and the experiment's pass/fail number has no agreed definition. The real-money route (SnapTrade, the service that connects the app to Wealthsimple and Webull) has **never carried a single order of any kind from this app**. Its only options venue is Webull Canada, and three design problems are likely to bite on first contact. A held option also has no stop-loss resting at the broker, so the app being up is the only protection. The earliest sound real-money step is a supervised one-contract plumbing test on Webull in three to five weeks, after specific fixes. Automated Cartel trading with real money is not supportable before a restarted, completed and positive Practice sample, which puts it in 2027 at the earliest.

Throughout, "verified" means a researcher read it directly from the database, the code or a published page on 2026-10-12. "Inference" means reasoning that no record states outright. File and line references are in the evidence section at the end.

## One open trade is carrying the whole result

### What the experiment actually did

The Practice book ("Options Cartel Practice 10k", a simulated $10,000 account) has had exactly two orders in its life (verified). On 29 September it bought 5 DHT November $22 calls at $1.80. On 1 October it sold 1 of them at $2.20 when the stock hit its first target. Four contracts are still open. ([practice note §1](../research_notes/Cartel%20real%20money%20readiness/practice_results_and_reliability.md))

| Measure (as of the 10-12 close) | Value |
|---|---|
| Book value | $11,093.76 (+10.94%) |
| Profit actually banked, before fees | +$40.00 |
| Fees paid | $6.24 |
| Paper profit on the 4 open contracts, at the mid-price | +$1,060.00 |
| Share of the result that is unbanked paper profit | 96.9% |
| Fully closed trades in the experiment | **0 of the 8 required** |
| Result if DHT is excluded | $0.00 on zero trades |

About $460 of the gain arrived in the last session alone, so the headline depends heavily on the day it is read.

The experiment's own written rule says that fewer than 8 closed trades after 20 sessions (28 September to 23 October) means "stop development". It also says that even 8 or more trades with a profit means "the next step is a longer sample, never live money on this evidence alone". Eleven sessions have passed and nine remain. The observed pace was one entry in roughly six sessions. **Reaching 8 closed trades by 23 October is not realistic (inference), so the experiment's own rule points to "stop development", not "go live".**

The plan document warned in advance that this strategy's test results were dominated by one outlier trade: 8 replayed trades made +5.52R, of which one trade made +7.33R and the other seven lost 1.81R. ("R" is one unit of planned risk.) Practice has reproduced that shape with a sample of one. "The plan is working well" is therefore not supported as a statement about the method. What is supported is narrower: one trade worked, and the first profit-taking exit fired at the right price and time.

### Why so few trades

While it ran, the funnel was narrow for identifiable reasons (verified). A thin-trading screen removed 50–62% of qualifying stocks each night. Of 18 occasions when a stock touched its trigger and was refused, 17 failed the rule that breakout volume must be 1.5 times normal. Five of those had volume between 1.13 and 1.40 times normal with an otherwise good bar, and the DHT winner passed at 1.54. Data quality refused more decision bars (66) than the method did (18). One valid signal (NTAP, 2 October) was lost because the chosen contract cost $14.20 against a $10 cap and a $1,000 budget. Up to nine expensive stocks a night never got a contract at all for the same structural reason. ([practice note §3–4](../research_notes/Cartel%20real%20money%20readiness/practice_results_and_reliability.md))

### The experiment has been dark for a week, and nobody was told

On Saturday 3 October the Tips desk turned on the app's server-wide "real orders" switch (`trading.mode = live`) for its paper account at Interactive Brokers (IBKR). Cartel uses that same switch to decide whether to read its Practice settings or its Live settings. Its Live settings are empty, so every scheduled nightly and morning preparation since 5 October has returned "disabled" in zero seconds: **11 runs, verified**. The scheduler logged each as a normal run, so no alarm fired, and no Cartel document records the stoppage.

**The notes disagree on the date, and here is the better-supported reading.** The cross-desk note says the experiment has been "dark since 10-03" with "effectively 5 live sessions". The practice note says six sessions were active (through 5 October) and five were dark (6, 7, 8, 9 and 12 October). Both are describing the same facts from different angles:

- The switch flipped on 3 October (both notes, verified).
- The last real preparation ran Friday 2 October and armed five plans for Monday 5 October. Those plans were watched all day on the 5th (verified rows).
- The cross-desk note argues from the code that any entry on the 5th would have been refused. That is an inference: no signal fired that day to test it.

The best statement is that **Cartel could really trade on 5 sessions, watched without being able to act on a sixth, and has done nothing at all on the last five.** The practice note's version of the scheduler evidence is the stronger one, because the cross-desk note says it did not check the job records.

**The notes also disagree on trade counts.** The SnapTrade note says Practice "has produced two round trips" and "two closed option trades". That is loose. The better-supported figure, from the accounting and cross-desk notes and the project's own scoreboard, is:

- **Lifetime:** 2 entries. One is closed (APA in mid-September, −$61.13, on an older archived book outside the experiment). One is open (DHT).
- **Inside the experiment:** 1 entry, 1 partial exit, 0 closed trades.

### The one held position ran half-blind

DHT's daily exit rules sell portions of the position when the stock closes below its moving averages. Those rules could not be evaluated for its first five closes because of a history-recovery bug, fixed on 5 October in version 0.9.05. A sixth close (9 October) was missed after the fix. Six missed closes are still flagged for review, and the automatic catch-up cannot complete that review (verified). A researcher's recomputation says no exit was actually due on any of those days, so it cost nothing this time, but for half the holding period the app could not have known that.

The cause is fragile by design. The day's bar is only built if all 390 one-minute bars arrive live within two minutes, so one dropped minute or one short restart blinds that day's exit. ([practice note §5–6](../research_notes/Cartel%20real%20money%20readiness/practice_results_and_reliability.md))

## The books balance, but the headline flatters

### What is right

Cash, position, fees and the latest book value reconcile to **$0.00 difference** when rebuilt by hand from the two fills (verified). Commissions are included in Practice: $1.04 per contract per fill ($0.99 plus $0.05 regulatory), on both buys and sells, taken out of cash and therefore out of the book value. No double counting was found. Cartel's own daily session review reports profit net of fees correctly. ([accounting note §1–2, §4](../research_notes/Cartel%20real%20money%20readiness/accounting_accuracy.md))

### What is inaccurate or optimistic

**The "Realized" figure on the shared screens is before fees.** The Blotter and Armed pages show +$40.00. After both sides' fees on that contract the figure is +$37.92. The gap is $2.08 per contract round trip and will grow with every trade.

**The entry fill was more generous than a real market would give.** The simulator filled all 5 contracts at the $1.80 asking price when only 1 contract was on offer there. The app's own pre-trade check recorded that only 20% of the order was covered. A real order would probably have filled one contract at $1.80 and the rest higher or not at all (inference), so the cost basis of 4 of the 5 contracts is optimistic.

On a related point the notes disagree. The Tips desk reply and the cross-desk note say Cartel option fills before 3 October "may be optimistic" because of an older simulator timing flaw. The accounting note checked the fill evidence by query and found neither fill on this book was affected. The query is the stronger evidence. The displayed-size problem is separate and real.

**Open options are valued at the midpoint between the buy and sell quotes, with no check on quote age or quality.** Selling the 4 contracts at the actual bid and paying exit fees would give $10,989.60, which is **$104.16 less** than the reported $11,093.76 (+9.90% rather than +10.94%). Worse, junk quotes at the opening bell reach the valuation. On 9 October a placeholder quote of $0.00 / $4.70 wrote a **phantom $520 drop (−4.83%)** into the book's history. Quotes of $0.05 / $19.40 and $0.05 / $17.80 on two other mornings would have added a phantom $2,000-plus, and only by luck fell between the 30-second samples.

That is a display issue on Practice. On a real account it becomes a safety defect, because the same number feeds the daily-loss halt and position sizing. At the app's default 3% halt, the 9 October glitch would have halted a book that had lost nothing. ([accounting note §3](../research_notes/Cartel%20real%20money%20readiness/accounting_accuracy.md))

**The experiment's pass/fail number has no single definition and no tool computes it.** "Net P&L after fees" on this book today is anywhere from $0 (closed trades only) through +$37.92 (banked, net) to +$989.60 (sold at the bid) or +$1,093.76 (reported). The rule does not say which, and does not define "closed trade". ([accounting note §7](../research_notes/Cartel%20real%20money%20readiness/accounting_accuracy.md))

### What would be wrong on a real account

- **Commissions disappear.** Fills that come back through SnapTrade are recorded with zero commission, so every "net" Cartel figure on Webull would actually be before fees.
- **Currency is not converted on fills.** US-dollar cost is subtracted from a Canadian-dollar book unconverted until the next broker sync, and the broker's conversion markup is never booked as a cost. Both Webull books are Canadian-dollar based.
- **Expiry has no accounting path.** A call that expires in the money and converts to shares would land in a "needs a person" state, and the simulator has no expiry logic at all.
- **Cartel's own loss limit is off and could not work if turned on.** It needs daily price history for the option that the database does not have.
- **The app disagrees with the brokers about account size.** Its computed value differs from the broker's own total by 18–32% on the linked real accounts (verified, unexplained), and Cartel sizes trades from the app's figure.

## The real-money path has never carried an order

### Wealthsimple is out for options; Webull is untested

The app's last live probe (22 August) got SnapTrade error 1156 from Wealthsimple: "Option Trade impact is not supported for this brokerage". The app hard-blocks option orders there. Wealthsimple itself offers options to customers; the limit is the SnapTrade connection ([Wealthsimple options](https://www.wealthsimple.com/en-ca/invest/options)). The probe is seven weeks old and was not re-run.

The only real-money options venue the code can reach is **Webull Canada via SnapTrade**. The IBKR connection that the Tips desk hardened refuses anything that is not shares (verified in code). ([SnapTrade note §1](../research_notes/Cartel%20real%20money%20readiness/snaptrade_live_order_path.md))

The database shows **zero orders and zero executions on all five SnapTrade-linked accounts, ever**, and no option order on any real or paper venue (verified). Automated tests cover the SnapTrade pieces against a stand-in, and Cartel's logic against the simulator, but **no test joins the two**. The stand-in also encodes the project's assumptions about SnapTrade's replies, so passing tests do not show those assumptions hold. There is no paper account on SnapTrade, and the "Alpaca paper overnight pass" that the project's own pre-live checklist requires cannot be run, because no Alpaca order connection exists in the code. ([SnapTrade note §5–6](../research_notes/Cartel%20real%20money%20readiness/snaptrade_live_order_path.md))

### Three things likely to break on first contact

These come from reading code against SnapTrade's published documentation. They are untested interactions, not observed faults.

**1. The app asks too often.** While an order is working, the app asks SnapTrade for order status every 2 seconds, about 30 times a minute. SnapTrade's documented limit for personal keys is **10 requests per minute per account**, with guidance to poll no faster than every 15 seconds ([SnapTrade rate limiting](https://docs.snaptrade.com/docs/ratelimiting.md)). A refused poll marks the broker "not connected", and the app then rejects every new order on that account, **including protective exits**. Cartel's exit logic gives up after five attempts, about two and a half minutes.

**2. A lost reply can strand a real position.** If the app sends an option order and never hears back, it looks for its own reference number in SnapTrade's order list. Option orders do not carry that number, and SnapTrade's list does not return it ([recentOrders](https://docs.snaptrade.com/reference/Account%20Information/AccountInformation_getUserAccountRecentOrders.md)). The fallback is a guess by symbol and quantity. If the guess misses, the app records "rejected" after 60 seconds while the order may be live or filled at Webull, with no stop or target attached.

**3. The 15-minute account sync can hide a fresh position.** The sync overwrites the app's holdings with the broker's. If the broker's list lags a new fill, the app can believe it holds nothing and skip an exit. Nobody has measured how fresh that list is.

### No stop-loss at the broker

Cartel's stop exists only inside the running app. It watches the stock, not the option, and sends a market sell when the stop is crossed. Nothing rests at Webull. If the app is frozen, restarting or down, a held option is unprotected, and overnight and weekend gaps are unprotected by design.

This host has a record of freezes of 12 to 181 seconds, one of 395 seconds, a 540-second stall that needed a manual override, and one incident of two engines running at once. Other desks are now authorised to restart the app during market hours. The Tips desk calls this "Cartel's biggest structural risk on real money". ([Tips desk reply §2](../research_notes/Cartel%20real%20money%20readiness/tips_desk_reply.md), [cross-desk note §6](../research_notes/Cartel%20real%20money%20readiness/cross_desk_lessons.md))

A broker-side stop may be possible, but the sources conflict. Webull Canada's help page lists stop orders for options and says "Only Day orders are available for options trading" ([Webull Canada order types](https://www.webull.ca/help/faq/556-Three-Things-You-Need-to-Know-About-Options-Trading-and-Order-Types-on-Webull)). The app's own August preview recorded good-till-cancelled as accepted, and its one attempt at an option stop got a server error. Webull's published page is the better source until a real order proves otherwise. A day-only stop would have to be re-placed every morning.

### The safety switches are looser than they look

The server-wide "real orders" switch is already on, for the Tips paper account, so it protects nothing for Cartel. What stands between today and a real Cartel option order is two Cartel settings: a saved Live preparation policy and `allow_live_auto`.

The global risk limits in force are the deliberately loosened Practice values:

| Limit | In force today | Project's pre-live profile |
|---|---|---|
| Daily-loss halt | 15% | 2% |
| Option contracts per order | 50 | 5 |
| Option premium per position | $10,000 or 50% of the account | $1,000 or 10% |

Per-account overrides exist, but the three option-specific caps ignore them (verified in code). A new live Cartel account would inherit the loose values. The check that stops a paper-type account routing to a real one exists only for IBKR, not SnapTrade. ([SnapTrade note §4](../research_notes/Cartel%20real%20money%20readiness/snaptrade_live_order_path.md))

## What the Tips paper run teaches

The Tips desk's first-hand reply opens with the caveat that matters most: everything it learned was on IBKR with **shares only**, and "no desk has yet sent a real option order or used SnapTrade as a technique executor".

**Review does not find everything.** Two code reviews before the first paper order found 13 money-path defects. The first real session then found a different set that no review predicted: prices rejected for being off the broker's price increment, a connection that claimed to be up while orders sat unsent, positions left with no stop, and multi-second freezes. The app went through about 30 versions in 11 days on the simplest possible case (long shares with a stop resting at the broker). Six sessions after "paper passed", it still found a bug that left a position stuck closing for 30 minutes. **Inference: Cartel should assume a comparable undiscovered list exists for its own venue and vehicle.** Almost none of the Tips fixes transfer, because they live in the IBKR connection or in shared exit code that Cartel's own exit logic bypasses.

**Fees dominate small trades.** IBKR charged about $1 per order even for 2 shares: $4.02 of commission on a day that lost $3. Webull's schedule is US$0.99 per contract, refunded for the first three months for accounts activated from August 2026 ([Webull Canada pricing](https://www.webull.ca/pricing)). The Webull cash account holds about C$1,400 in cash, so real Cartel trades would be one or two contracts. At that size the exit ladder cannot work as tested, because it sells in 20–25% steps.

**Options were the loss.** On the same Tips signals, shares made +$259 on 22 trades and options lost $1,244 on 24, paying all the fees. Team2's replay profit turned into −3.7% per trade when re-priced on real option trades. Every Cartel research number so far is measured on the stock, not on option prices, and no tool on any desk scores a Cartel trade on historical option prices.

**Other lessons that apply directly:**

- The app never converts currency, so the right currency must be funded first.
- Broker cash lags fills, and Tips had to correct for it. SnapTrade will have the same lag.
- Test outages on purpose: pull the link during an entry, a cancel and a close.
- Reconcile the app against the broker at every close.
- Decide the overnight-option question before anything else.

**Where Cartel is already strong.** Its entry path writes the intent down before sending, never resubmits blindly, checks every halt three times and handles partial fills. The cross-desk note judges it stricter than Tips was before its reviews.

## Gap fixes, in priority order

| # | Fix | Why it matters |
|---|---|---|
| **Now, before any more Practice evidence is trusted** | | |
| 1 | Stop Cartel choosing Practice or Live from the shared `trading.mode` switch; give it its own setting. Do not flip the shared switch back, because that would stop the Tips paper account. | Restarts the experiment; removes a hazard where another desk's switch starts or stops Cartel live trading |
| 2 | Treat a "disabled" preparation on a trading day as a failure that alerts | A week of silence went unnoticed |
| 3 | Write down the stop-rule metric (what counts as a closed trade; whether open positions count, valued at the bid) and build one scorecard tool that computes it | Today the answer ranges from $0 to $1,094 |
| 4 | Clear DHT's six missed-close flags with the app's own review tool, and fix the catch-up so it can complete | An unresolved "needs review" on the only position |
| 5 | Build the daily bar from recovered data when live minutes are missing, instead of all-390-or-nothing | Exits were blind on 6 of 10 closes |
| **Accuracy** | | |
| 6 | Value options only from fresh, two-sided, sane quotes (reuse the check fills already use); value at the bid for risk decisions | Phantom −$520; false halts and wrong sizing on a real account |
| 7 | Show profit after fees on the Blotter and Armed screens | Before-fees figure reads as the result |
| 8 | Make simulated limit orders respect displayed size; turn on the simulator's spread cap | The DHT entry would not have filled in full |
| 9 | Record real commissions on SnapTrade fills (from the broker's data or the known schedule), and convert currency on fills | Otherwise before-fees is reported as after-fees |
| 10 | Explain the 18–32% gap between the app's and the brokers' account totals | Sizing reads the app's figure |
| **Order path** | | |
| 11 | Slow status polling to fit 10 requests a minute (or obtain a higher limit or webhooks from SnapTrade); a refused poll must never block an exit | Likely first-contact failure |
| 12 | Make lost-reply recovery for option orders reliable; never record "rejected" on a guess | A real position with no stop |
| 13 | Protect a just-filled position from the 15-minute sync overwrite | A skipped exit |
| 14 | Make per-account overrides reach the option caps; create a tight Cartel live profile; add an account-type check for SnapTrade | Loosened limits would apply to real money |
| 15 | Round option prices to the exchange's allowed increments; re-price stale profit-target orders | Rejections and missed targets |
| 16 | Decide and build overnight protection: a day-only broker stop re-placed each morning (if Webull accepts it), or no overnight holds at first | The biggest structural risk |
| 17 | Add expiry and exercise handling, and the missing late-fill path the code itself flags as required "before live entry activation" | Unbooked outcomes |
| **Reliability** | | |
| 18 | Merge and verify the two stalled draft changes (#293 and #301: reserved database connections, restart safety with Cartel work running, a second option-chain source, settings snapshot, 95% fewer stored records) | Open since 28 September |
| 19 | Finish the machine move first; keep 3 GB of memory free; no heavy tests in market hours | Freezes are the stop-loss failing |
| 20 | Alert when live option quotes or stock bars are down while a real option is held | Single-supplier dependence on Alpaca |
| **Validation** | | |
| 21 | Tests that run a Cartel entry, each exit type, a partial fill, a refused poll and a restart through the SnapTrade stand-in | No such test exists |
| 22 | A replay that prices Cartel trades on real historical option trades (the pieces exist from the EM and Team2 work) | Stock-based results have flipped sign before |
| 23 | Re-run the chaos test suite on the current code (two option tests were reported failing on 12 October, unchecked) | It is the stated gate for overnight holds |
| 24 | Add earnings-date awareness to Cartel entries and holds | Cartel reads none today |

## A staged path with go/no-go gates

**On venue:** real-money Cartel options means Webull Canada, not Wealthsimple. Two alternatives deserve a decision. Building options support for IBKR would give a real paper account to practise on and a more capable broker, but it is unbuilt. Running Cartel as shares on IBKR would inherit the Tips desk's hardened path and a broker-side stop, but Cartel's automatic preparation does not build share plans today.

**On timeline:** "a couple of weeks" is not achievable for anything. November is achievable only for a supervised plumbing test.

| Stage | What happens | Go criteria | Earliest (inference) |
|---|---|---|---|
| 0. Restore and define | Fixes 1–5. Decide whether the dark sessions count. Recommended: declare the sample interrupted and restart a fresh 20 sessions with the metric defined first. | Preparation runs nightly for a week with an alert on failure; scorecard tool exists; DHT flags cleared | 1–2 weeks |
| 1. Make it truthful and safe | Fixes 6–16, 18, 21, 23. Re-run the Wealthsimple and Webull probes. | All new tests green; chaos suite green; tight live profile reads back correctly; no phantom valuation moves for 5 sessions | 3–5 weeks |
| 2. Supervised plumbing test | The owner's explicit decision. One cheap, liquid contract on Webull Cash, a manually approved buy and then sell the same day, with the owner watching Webull's own app. Not automated, not overnight. Then three to five repeats, including deliberate outages. | Fill quantities and commission match the broker; cash and position match at the close; no stuck order; status polling never throttled; kill switch blocks an entry; link-pull during entry, cancel and close all recover cleanly | Mid to late November |
| 3. Overnight test | One contract held overnight and over a weekend with the chosen protection in place | Morning reconcile clean three nights running; protection present each morning; a restart with the position held recovers it | December |
| 4. Evidence gate | The restarted Practice sample completes; real-option-price replay built | At least 8 closed trades and net profit after fees on the written metric, not dependent on one trade; then the "longer sample" the plan itself requires; replay on real option prices not negative | Sample ends about late November; longer sample into Q1 2027 |
| 5. Capped automated live | The owner's explicit go. Smallest size, tight limits, a daily reconcile, and review after the first position before the second. | Any unexplained fill, stuck order or attention flag stops new entries until explained | Not before 2027 |

**No-go conditions at any stage:**

- The restarted sample again ends under 8 closed trades.
- Net result is at or below zero after fees.
- Profit comes from a single trade.
- Webull rejects market or stop orders on options in a way that leaves no workable exit.
- The host is still freezing for more than a few seconds in market hours.

The project's own cross-desk rule also stands: live money stays off until a technique shows a positive, capped Practice record over its preregistered sample. No desk has met that rule, and the owner's 2 October decision named Cartel as staying on Practice. Going earlier would be a deliberate override, as it was for Tips, and Tips' own go-live is currently delayed.

## Conclusion

Two different questions have been running together. One is whether the machinery can safely place and manage a real option trade. That is answerable in weeks, by fixing a known list and then spending a hundred dollars or so of risk on supervised single-contract tests. The other is whether the method makes money. One open trade cannot answer that, and the experiment designed to answer it stopped collecting data on 5 October without anyone noticing. The second question, not the first, sets the timeline.

The stoppage is the most useful finding here. A setting changed for another desk silently disabled this one, and every monitor reported normal. On Practice that cost a week of data. With a real option held and no stop at the broker, the same class of silent failure costs money. Readiness for Cartel is less about the strategy's cleverness than about the app proving that it notices when it has stopped working.

## Evidence and references

**Research notes** (all dated 2026-10-12, code read at `origin/main` commit `0756a52d`, database queries read-only):
[practice results and reliability](../research_notes/Cartel%20real%20money%20readiness/practice_results_and_reliability.md) ·
[accounting accuracy](../research_notes/Cartel%20real%20money%20readiness/accounting_accuracy.md) ·
[SnapTrade live order path](../research_notes/Cartel%20real%20money%20readiness/snaptrade_live_order_path.md) ·
[cross-desk lessons](../research_notes/Cartel%20real%20money%20readiness/cross_desk_lessons.md) ·
[Tips desk reply](../research_notes/Cartel%20real%20money%20readiness/tips_desk_reply.md)

**Key code and document locations behind the main claims**

| Claim | Where |
|---|---|
| Stop rule and "never live money on this evidence alone" | `docs/techniques/options-cartel/reviews/2026-09-24-sharp-pencil/PLAN.md:174-197` |
| Cross-desk rule that live money stays off | `docs/PLAN-2026-09-24-SHARP-PENCIL.md:81, 110` |
| Cartel picks Practice or Live from `trading.mode` | `backend/zargar/techniques/options_cartel/preparation_scope.py:14-21` |
| Empty policy returns "disabled" without an error | `.../options_cartel/preparation.py:797-810` |
| Simulator fee, $1.04 per contract | `backend/zargar/brokers/sim.py:420-431`; `settings_service.py:610-612` |
| Simulated limit fills ignore displayed size | `brokers/sim.py:401-408` |
| Realized profit stored before fees | `portfolio.py:395-398`; `execution/positions.py:1574-1576` |
| Option valuation rule, no age or quality check | `portfolio.py:204-226`; `marketdata.py:143-144` |
| Net-of-fees session review | `.../options_cartel/review_ledger.py:27-54` |
| SnapTrade fills carry no commission | `brokers/snaptrade.py:718-730`; `brokers/base.py:46` |
| No currency conversion on fills | `portfolio.py:408-411` |
| IBKR connection is shares-only | `brokers/ibkr.py:279-283` |
| Option order has no client reference; 60 s lost-reply search | `brokers/snaptrade.py:755-769, 496-544` |
| 2-second status poll; failed poll marks broker disconnected | `brokers/snaptrade.py:650-694, 673-676`; `orders.py:394-398` |
| Options held "app managed", no broker stop | `.../options_cartel/adoption.py:118-135`; `exit_router.py:118-120` |
| Exit retries stop after five attempts | `.../options_cartel/exit_router.py:177-228` |
| Daily bar needs all 390 live minutes | `.../options_cartel/position_adapter.py:270-291` |
| Catch-up review cannot complete | `.../options_cartel/catchup.py:16-18`; `position_adapter.py:250-254` |
| Option caps ignore per-account overrides | `risk.py:147-167, 543, 573` |
| Live gates and loosened limits | `.../options_cartel/controller.py:136-144`; `docs/PRE-LIVE-PROFILE.md:25-43` |
| Pre-live checklist and Tips paper criteria | `docs/PRE-LIVE-PROFILE.md:11-21, 48-55`; `docs/techniques/tip/LIVE-IBKR-RUNBOOK.md:63-65` |
| Wealthsimple probe result (code 1156) | `docs/OPTIONS-PLAN.md:22-27`; `BrokerCapabilityChecked` events, 2026-08-22 |

**External sources:**
[SnapTrade rate limiting](https://docs.snaptrade.com/docs/ratelimiting.md) ·
[SnapTrade recentOrders](https://docs.snaptrade.com/reference/Account%20Information/AccountInformation_getUserAccountRecentOrders.md) ·
[SnapTrade option order endpoint](https://docs.snaptrade.com/reference/Trading/Trading_placeMlegOrder.md) ·
[SnapTrade Wealthsimple integration](https://snaptrade.com/brokerage-integrations/wealthsimple-api) ·
[Webull Canada option order types](https://www.webull.ca/help/faq/556-Three-Things-You-Need-to-Know-About-Options-Trading-and-Order-Types-on-Webull) ·
[Webull Canada pricing](https://www.webull.ca/pricing) ·
[Wealthsimple options](https://www.wealthsimple.com/en-ca/invest/options) ·
[Wealthsimple trade fees](https://www.wealthsimple.com/en-ca/legal/fees/trade)

**What was not checked.** No tests were run and no broker was contacted. The Wealthsimple and Webull probes were not repeated. The app's own session-review and catch-up tools were not executed, so the +$37.92 net figure and the "no exit was due" conclusion are hand computations. Webull's real reject behaviour, SnapTrade's actual enforcement of its rate limit, and how fresh its holdings data is are unknown until a real order is placed.
