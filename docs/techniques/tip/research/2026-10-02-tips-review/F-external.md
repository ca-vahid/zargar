# External evidence (deep-research workflow, 105 agents, 3-vote adversarial verification)

The verified evidence does not support copying unscreened tip sources. On StockTwits, 56% of finfluencers have negative skill (-2.3% a month) and only 28% are skilled (+2.6% a month). The negative-skill accounts draw more followers, so popularity is a poor way to pick a source. Micro-cap message spikes driven by promoters reverse by about 5% within five days. Buying short-dated options is the most cost-exposed way to act on a tip. Retail option buyers lose in aggregate at every horizon studied, mostly to spreads: weeklies quote about 12.6% wide and fill about 6.6% wide. Buying before earnings loses about 5-9%, or 10-14% when expected volatility is high, because implied volatility collapses after the release. An earnings calendar is therefore clearly justified as a filter. A macro calendar is justified for risk on announcement days, not as a source of edge: the pre-FOMC drift faded after 2015, and CPI and jobs releases show no pre-announcement drift. The verified claims did not cover entry-latency decay, exit design, small-account sizing and PDT rules, LLM decision quality or paper-to-live promotion criteria. Those parts of the plan rest on the desk's own data and judgement, not on this evidence.

## F1. Following an unscreened tip source has no edge on average, and most sources have a negative one. Sources must be scored on their own track record: popularity, follower count and activity are poor guides and may point the wrong way.

- confidence: medium | vote: 3-0
- sources: https://jhfinance.web.unc.edu/wp-content/uploads/sites/12369/2023/11/Finfluencers.pdf

Kakhbod, Kazempour, Livdan and Schuerhoff studied more than 29,000 StockTwits finfluencers from 2013 to 2017. 28% were skilled (+2.6% a month abnormal return), 16% unskilled (about 0) and 56% antiskilled (-2.3% a month), which averages about -0.56% a month across all sources. Antiskilled finfluencers have more followers and more influence on retail order flow. A contrarian strategy against them earned positive out-of-sample returns, so the signal carries information, but following it does not pay. Votes were 3-0 on both claims. It is one working paper, the returns are before costs, and the platform is StockTwits rather than Discord. That supports desk policy: earned trust per source, judged on graded outcomes.

## F2. Buying after a social-media hype spike loses money when the spike is promoter-driven. Non-promoter spikes do not reverse, so who is posting matters more than how loud the post is.

- confidence: medium | vote: 3-0
- sources: https://www.thomas-renault.com/wp/market-manipulation-suspicious.pdf

Renault (2018) studied 635 Twitter message-spike events in 315 OTC/small-cap stocks. Abnormal returns were +4.10% on the day before and +6.88% on the day of the spike, then -3.11% over the next five days. In the 407 events involving a promoter or pump-tracker, returns fell 5.34%. In the 228 events without one, returns rose 0.87%, significant only at the 10% level. An earlier study, Sabherwal et al. (2011), found -5.4% after message-board spikes. This is a single working paper using roughly 2015 data on micro-caps, so it is pump-and-dump evidence that applies only indirectly to liquid-name Discord rooms. Its practical use is to argue against entering late, after a tip has already moved the price.

## F3. Retail buyers of short-dated options lose money in aggregate at every horizon studied, and most of the loss is trading cost. Half of retail option trades are in contracts with under a week to expiry. Those quote about 12.6% wide and fill about 6.6% wide, which is a large round-trip hurdle for any tip expressed in options.

- confidence: high | vote: 3-0 (buyer/seller split 2-1)
- sources: https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13285, https://cepr.org/publications/dp17688, https://cdn.cboe.com/resources/education/research_publications/Retail_Profitability.pdf

Bryzgalova, Pavlova and Sikorskaya (Journal of Finance 2023) cover Nov 2019 to Jun 2021. Retail trades lost money at every horizon: about $2.1B in total at a 10-day horizon (-$5.03M a day) and -$1.63M a day if held to expiration. Indirect costs (trade price versus midquote) came to $6.4B, against about $900M in commissions. About 50% of trades were in options with under a week to expiry, at a 12.6% quoted and 6.6% effective spread. Buyers of short-term options lost money even before costs, consistent with theta decay, while retail sellers earned significant profits after costs. That last split was voted 2-1. Votes on the other claims were 3-0.

## F4. How large retail option losses are is disputed. Trader-level and exchange data show smaller losses or breakeven, and point to execution (limit orders, not crossing the spread) as the main lever. Execution quality is the variable this desk controls.

- confidence: medium | vote: 3-0
- sources: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4682388, https://cdn.cboe.com/resources/education/research_publications/Retail_Profitability.pdf

Bogousslavsky and Muravyev studied verified broker-linked data: 5,182 traders and 0.9M option trades over 2020-2022. The average option trade returned -0.9%, ranging from -5% to +1% across subsamples. Stock trades roughly broke even, with purchases at -0.17%. The authors say aggregate proxies (3-9% losses per trade) count only market orders that cross the spread, and that retail traders likely use limit orders to avoid paying it. The Cboe-funded study by Amaya et al. (2025), using true trade direction and expiration values, found +$0.34M a day for Cboe customer SLIM trades, with t=0.29. That is no evidence of losses and no evidence of an edge either. Both sources are working papers. The Cboe study has a possible conflict of interest, and both samples are more sophisticated than a $3k account copying tips.

## F5. An earnings calendar is clearly worth having. Buying options into earnings is where retail losses are largest, because event implied volatility is overpriced on average and collapses after the release. Comparing a stock's past earnings-day moves with the implied move is a usable filter.

- confidence: high | vote: 3-0
- sources: https://www.timdesilva.me/files/papers/losing_optional.pdf, https://www.stern.nyu.edu/sites/default/files/assets/documents/NYU%20conference%20Johannes%20final.pdf, https://www.mdpi.com/1911-8074/16/5/270

de Silva, So and Smith (Review of Finance 2025) find retail investors buy options in a concentrated way before earnings, especially when expected volatility is high. Losses average 5-9%, and 10-14% for high expected-volatility announcements. Dubinsky, Johannes et al. (RFS 2019) show implied volatility rises into earnings, falls discontinuously after, and that event volatility priced in options exceeds the move that actually happens. Their straddles held over the announcement day lost about 8% per event before spreads, which was significant. Milian (JRFM 2023) finds weekly straddle returns are higher when past earnings moves are large relative to the implied move, and lower when they are small. That is one author in a mid-tier journal, with no cost adjustment.

## F6. A macro calendar is a risk tool, not a source of edge. FOMC should be treated differently from CPI and jobs releases, and any calendar-based effect must be re-validated, because the best-known one (the pre-FOMC drift) has largely faded.

- confidence: medium | vote: 3-0
- sources: https://onlinelibrary.wiley.com/doi/10.1111/jofi.12196, https://pmc.ncbi.nlm.nih.gov/articles/PMC7525326/

Lucca and Moench (Journal of Finance 2015) found CPI, jobs and other major releases give no pre-announcement excess equity returns. Kurov, Wolfe and Gilbert (2020) found the pre-FOMC return on press-conference meetings fell from about 44 bp (2011-2015) to about 9 bp (2016-2019). Post-2016 announcement days are not distinguishable from other days. The claim that roughly 80% of returns are earned before FOMC was refuted (1-2), as was the 49 bp figure (0-3). A verifier also noted Savor and Wilson (2013): CPI, jobs and FOMC days all carry higher volatility on the day itself. So for short-dated options all three still deserve risk treatment, such as size cuts or entry blackouts around the release time.

## F7. US equity and option trades settle T+1 (since 28 May 2024). In a cash account, sale proceeds are unsettled until the next business day, which caps how often a small account can recycle its capital.

- confidence: high | vote: 3-0
- sources: https://international.schwab.com/story/understanding-stock-settlement-dates-violations

SEC Rule 15c6-1 was amended and took effect 28 May 2024, moving settlement from T+2 (2017) to T+1. Settlement counts business days, which follow bank holidays. Canada also moved to T+1 on 27 May 2024. A precise statement of the good-faith-violation mechanics was refuted (0-3), so the exact IBKR cash-account rule needs to be confirmed with IBKR before any same-day round trip.

## caveats

```
"Coverage gaps: no claims survived verification on (a) how a tip's edge decays with entry latency, (b) exit design (mirroring the source, trailing or time stops, scaling out, volatility at the open), (c) fixed-fractional sizing, PDT applicability to cash accounts and Canadian IBKR clients, or exact good-faith-violation rules, (d) LLM agent decision quality, abstention or autonomy, and (e) shadow-trading promotion criteria. Recommendations in those areas must rest on the desk's own data (shadow books, TipEntryStudy, scorecards) or on later research.\n\nSource limits: the evidence on tip sources comes from StockTwits, Twitter and micro-caps between 2013 and 2017, not Discord rooms on liquid names. The Finfluencers and Renault papers are working papers. The scale of retail option losses is actively disputed: Bryzgalova, Pavlova and Sikorskaya (BPS) against the Cboe-funded rebuttal, which has a possible conflict of interest. Most samples cover the 2019-2021 retail boom. Several results are abnormal returns before costs, so after costs a buyer would do worse. Time-sensitivity: the pre-FOMC drift decayed after 2015, and the share of 0DTE trading has grown since the BPS sample."
```

## openQuestions

```
[
 "How fast does a Discord tip's edge decay with minutes of entry latency, net of the actual fill-versus-quote cost? This can only be answered from the desk's own immediate-versus-armed shadow books and the TipEntryStudy/TipFillVsQuote data.",
 "For a $3k IBKR cash account held by a Canadian resident, which rules actually bind: Reg T good-faith and freeriding, whether PDT applies, and settlement of option premium and same-day round trips? This must be confirmed with IBKR's own documentation.",
 "Does giving the LLM analyst more autonomy or tool depth improve graded tip outcomes, or does it mainly reduce useful abstention? The verified evidence does not answer this; it needs a preregistered A/B on graded tips.",
 "When a tip is expressed in shares instead of short-dated options, how much of the per-trade edge is kept after the ~6-13% option spread? And should options be limited to longer-dated, tighter-spread contracts filled with limit orders at the mid?"
]
```

## refuted

```
[
 {
  "claim": "US equities earn large average excess returns in the window before scheduled FOMC announcements, accounting for a sizable fraction of annual realized stock returns (published figure: about 49 bp in the 24 hours before the announcement since 1994, though the fetched abstract gives no number).",
  "vote": "0-3",
  "source": "https://onlinelibrary.wiley.com/doi/10.1111/jofi.12196"
 },
 {
  "claim": "From 1994 to 2011, roughly 80% of US equity excess returns were earned in the 24 hours before scheduled FOMC announcements (the pre-FOMC drift), which makes FOMC dates a material calendar event for short-term equity trading.",
  "vote": "1-2",
  "source": "https://www.bis.org/publ/work1079.pdf"
 },
 {
  "claim": "A good faith violation happens when you buy with unsettled sale proceeds and then sell that new position before the original sale settles. An intraday round trip in a cash account leaves only the untouched settled cash free to trade until the next day.",
  "vote": "0-3",
  "source": "https://international.schwab.com/story/understanding-stock-settlement-dates-violations"
 }
]
```

## unverified

```
[]
```

## sources

```
[
 {
  "url": "https://jhfinance.web.unc.edu/wp-content/uploads/sites/12369/2023/11/Finfluencers.pdf",
  "quality": "primary",
  "angle": "Social-signal edge and latency decay (academic)",
  "claimCount": 5
 },
 {
  "url": "https://www.sciencedirect.com/science/article/abs/pii/S0165176525003489",
  "quality": "unreliable",
  "angle": "Social-signal edge and latency decay (academic)",
  "claimCount": 0
 },
 {
  "url": "https://www.thomas-renault.com/wp/market-manipulation-suspicious.pdf",
  "quality": "primary",
  "angle": "Social-signal edge and latency decay (academic)",
  "claimCount": 5
 },
 {
  "url": "https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13285",
  "quality": "primary",
  "angle": "Retail option buyers vs shares",
  "claimCount": 5
 },
 {
  "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4682388",
  "quality": "primary",
  "angle": "Retail option buyers vs shares",
  "claimCount": 5
 },
 {
  "url": "https://www.timdesilva.me/files/papers/losing_optional.pdf",
  "quality": "primary",
  "angle": "Retail option buyers vs shares",
  "claimCount": 5
 },
 {
  "url": "https://cdn.cboe.com/resources/education/research_publications/Retail_Profitability.pdf",
  "quality": "primary",
  "angle": "Retail option buyers vs shares",
  "claimCount": 5
 },
 {
  "url": "https://www.researchgate.net/publication/401400759_Retail_option_traders_and_the_implied_volatility_surface",
  "quality": "unreliable",
  "angle": "Retail option buyers vs shares",
  "claimCount": 0
 },
 {
  "url": "https://cepr.org/publications/dp17688",
  "quality": "primary",
  "angle": "Retail option buyers vs shares",
  "claimCount": 5
 },
 {
  "url": "https://onlinelibrary.wiley.com/doi/10.1111/jofi.12196",
  "quality": "primary",
  "angle": "Event calendar and earnings risk",
  "claimCount": 4
 },
 {
  "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC7525326/",
  "quality": "primary",
  "angle": "Event calendar and earnings risk",
  "claimCount": 4
 },
 {
  "url": "https://www.sciencedirect.com/science/article/abs/pii/S0304405X14000890",
  "quality": "unreliable",
  "angle": "Event calendar and earnings risk",
  "claimCount": 0
 },
 {
  "url": "https://www.stern.nyu.edu/sites/default/files/assets/documents/NYU%20conference%20Johannes%20final.pdf",
  "quality": "primary",
  "angle": "Event calendar and earnings risk",
  "claimCount": 5
 },
 {
  "url": "https://www.bis.org/publ/work1079.pdf",
  "quality": "primary",
  "angle": "Event calendar and earnings risk",
  "claimCount": 4
 },
 {
  "url": "https://www.mdpi.com/1911-8074/16/5/270",
  "quality": "primary",
  "angle": "Event calendar and earnings risk",
  "claimCount": 4
 },
 {
  "url": "https://www.wilmerhale.com/en/insights/client-alerts/20260423-sec-approves-amendments-to-finra-rule-4210-replacing-day-trading-margin-requirements-with-a-modernized-intraday-margin-standard",
  "quality": "secondary",
  "angle": "Small cash-account rules and sizing",
  "claimCount": 5
 },
 {
  "url": "https://international.schwab.com/story/understanding-stock-settlement-dates-violations",
  "quality": "primary",
  "angle": "Small cash-account rules and sizing",
  "claimCount": 5
 },
 {
  "url": "https://us.etrade.com/knowledge/library/stocks/understanding-cash-account-violations",
  "quality": "primary",
  "angle": "Small cash-account rules and sizing",
  "claimCount": 5
 },
 {
  "url": "https://www.finra.org/investors/insights/frequent-intraday-trading",
  "quality": "primary",
  "angle": "Small cash-account rules and sizing",
  "claimCount": 5
 },
 {
  "url": "https://arxiv.org/abs/2510.11695",
  "quality": "primary",
  "angle": "LLM trading agents and paper-to-live promotion",
  "claimCount": 5
 },
 {
  "url": "https://www.arxiv.org/pdf/2511.03628",
  "quality": "primary",
  "angle": "LLM trading agents and paper-to-live promotion",
  "claimCount": 5
 },
 {
  "url": "https://arxiv.org/abs/2512.10971",
  "quality": "primary",
  "angle": "LLM trading agents and paper-to-live promotion",
  "claimCount": 4
 },
 {
  "url": "https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf",
  "quality": "primary",
  "angle": "LLM trading agents and paper-to-live promotion",
  "claimCount": 5
 }
]
```

## stats

```
{
 "angles": 5,
 "sourcesFetched": 23,
 "claimsExtracted": 95,
 "claimsVerified": 25,
 "confirmed": 22,
 "killed": 3,
 "unverified": 0,
 "afterSynthesis": 7,
 "urlDupes": 0,
 "budgetDropped": 7,
 "agentCalls": 105
}
```

