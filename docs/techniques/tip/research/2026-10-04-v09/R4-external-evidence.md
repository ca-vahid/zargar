# R4 - External evidence (deep research, 2026-10-04)

**Question:** Evidence-based best practices for an automated system that trades Discord stock/option tips with a small real-money account (~US$7,000, IBKR cash account, Canadian resident; shares first, long only, options only with defined risk), maximizing after-cost profit and avoiding avoidable losses: (1) choosing the holding horizon at entry (intraday / 2-5 days / one week / multi-week / months) from the setup type, and the exit rules that fit each (time stops, trailing stops, scale-outs, target ladders); (2) stop-loss design that cuts losses in time without noise stop-outs (ATR vs structure vs percent, close vs intrabar, gaps, breakeven and trailing moves; Kaminski-Lo and stop-loss momentum evidence); (3) smart profit taking (partials, R-multiples, trailing, disposition-effect costs); (4) sizing a small account (fixed-fractional risk, volatility targeting, fractional Kelly, max positions, capital utilisation, concentration); (5) decision-time information that improves short-term outcomes (relative volume, relative strength, trend and regime filters, VIX, earnings/macro calendar, liquidity, short interest); (6) execution costs for a small IBKR account (limit vs marketable, open volatility, commissions, T+1/good-faith rules, CAD/USD conversion); (7) copy-trading evidence (edge decay with delay, which tipster traits predict success, grading sources). Output quantified rules and parameter ranges to encode in software.

## Summary

The verified evidence covers four of the seven sub-questions well: stops, sizing, source grading and cash-account settlement. It says little about holding horizon by setup, profit-taking ladders, or execution costs and FX. On stops, Kaminski-Lo shows that a stop lowers expected return unless returns persist (momentum or regime switching). Stops checked over windows shorter than a month had negative premiums across wide parameter ranges, and trailing stops mainly reduce risk rather than add return. After costs, only wider stops stay useful. So the software should use wide stops built for risk control (structure or multi-ATR, not tight percent stops) and should not expect stops to create edge. On sizing, use fractional Kelly at 1/4 to 1/2 of an estimate deliberately shrunk for error in the edge, and never above full Kelly. With an unproven tip edge, that means small fixed-fractional risk per trade until each source has a graded record. On sources, about 56% of 29,000+ StockTwits finfluencers had negative skill and the average source loses money. Popularity and posting frequency point the wrong way, so the system must grade each source on its own realised after-cost record and ignore follower counts. Three decision-time filters have support: a relative-volume shock is mildly positive for holds of about one month; avoid high days-to-cover names; and treat a negative trailing 2-year market return plus high volatility as a hostile regime for momentum-style entries. In an IBKR cash account, buy only with settled cash and never close a position bought with unsettled proceeds before they settle (T+1), or the account faces a 90-day Cash Up Front restriction.

## Findings

### Stop-loss value depends on return persistence. Under IID (random-walk) returns every stop lowers expected return. Under ...

Stop-loss value depends on return persistence. Under IID (random-walk) returns every stop lowers expected return. Under momentum or regime switching the stopping premium can be positive and is proportional to persistence; in the regime model this requires the low regime's mean to be below the safe asset's yield. Empirically (US futures, 1993-2011, stocks switching to bonds), stops checked daily or weekly had negative premiums across wide parameter ranges, while monthly-or-longer rules could be positive. Encoding implication (inference): a stop is a regime or risk exit, not an edge source. Prefer exits judged on a daily or weekly close, or on structure, over hair-trigger intrabar stops for multi-day holds, and keep a separate intrabar crash brake for catastrophic moves only.

- confidence: high · vote 3-0 (x3)
- evidence: Three claims merged, all voted 3-0, from one peer-reviewed primary paper (Kaminski & Lo, Journal of Financial Markets 2014). Quotes: 'If the portfolio follows a random walk... the stopping premium is always negative'; 'stopping premium can be positive and is directly proportional to the magnitude of return persistence'; 'Longer term stop-loss at frequencies above one month perform better'. The evidence is about index allocation, not single-stock swing trades.
- sources: https://dspace.mit.edu/bitstream/handle/1721.1/114876/Lo_When%20Do%20Stop-Loss.pdf

### Trailing stops reduce total and downside risk, most of all in falling markets, but earn lower mean returns than a mean-v...

Trailing stops reduce total and downside risk, most of all in falling markets, but earn lower mean returns than a mean-variance optimal benchmark. Transaction costs remove the benefit of tight trailing thresholds, while wider thresholds stay useful after costs. Encoding implication (inference): no tight trailing stops on a small account with real costs. Activate a trailing stop only after the trade has moved in favour (for example after +1R to +2R), trail by a wide multiple (several daily ATRs, or below the last higher-low structure), and treat it as downside protection.

- confidence: medium · vote 3-0 (x3)
- evidence: Three claims merged, all voted 3-0, from Dai, Marshall, Nguyen & Visaltanachoti, International Review of Finance 2021 (peer-reviewed). Only the abstract was read; the threshold values and cost levels were not checked. Rated medium because it is a single paper and the full text was not read.
- sources: https://onlinelibrary.wiley.com/doi/abs/10.1111/irfi.12328

### For long-horizon trend following, very wide ATR trailing stops work and the multiple barely matters. Buying all-time-hig...

For long-horizon trend following, very wide ATR trailing stops work and the multiple barely matters. Buying all-time-high closes with a 10-ATR trailing stop (exit at the next open after a breach) on 24,000+ US stocks from 1983-2004, including delisted names, with a $15 price floor and a dollar-volume floor, produced 18,000+ trades. Winners were 49.3%, average win/loss was 2.56, and expectancy was about +15.2% per trade net of 0.5% round-turn costs. The average hold was 305 days. Stop multiples from 8 to 12 ATR made no material difference: looser stops raised the win rate slightly and lowered the win/loss ratio slightly. Encoding implication: a 'months' horizon class for breakout or trend tips can use an 8-12x ATR trail with exits judged on the close. This says nothing about intraday or 2-5 day stops.

- confidence: low · vote 3-0 (x2)
- evidence: Two claims merged, both voted 3-0. The source is a single practitioner white paper (Blackstar, 2005), not peer-reviewed. It covers a bull-market sample, and its per-trade expectancy comes from heavily overlapping positions.
- sources: https://www.cis.upenn.edu/~mkearns/finread/trend.pdf

### Size with fractional Kelly, never above full Kelly, and shrink the fraction when the edge estimate is uncertain. In a 70...

Size with fractional Kelly, never above full Kelly, and shrink the fraction when the edge estimate is uncertain. In a 700-bet simulation with a 14% edge, the share of runs ending below starting wealth was 12.4% at full Kelly, 7.25% at 3/4, 3.5% at 1/2, 2.15% at 1/4 and 1.1% at 1/8. The worst final wealth from $1000 was $4, $56, $111, $513 and $587 respectively. Above full Kelly, growth falls while risk rises. Errors in the mean (the edge) cost about 10-20x more than variance errors, and about 100x more than covariance errors under log utility. The authors endorse half Kelly as a practical compromise. Encoding implication (inference): use at most 1/4 Kelly computed on a shrunk, source-specific edge estimate. Before a source has a graded record, use fixed-fractional risk of about 0.5-1% of equity per trade (roughly $35-70 at risk on $7k), with a cap on total open risk.

- confidence: high · vote 3-0 (x3)
- evidence: Three claims merged, all voted 3-0. The source is MacLean, Thorp, Zhao & Ziemba (2011), which cites Chopra & Ziemba (1993) for the error ratios. It is textbook mathematics plus a stylised simulation with a known edge; a tip edge is uncertain or may be absent. The 0.5-1% range is a synthesis inference, not from the source.
- sources: http://hari.seshadri.com/docs/kelly-betting/kelly1.pdf

### Most finfluencers have no skill or negative skill, so copying the average source loses money and each source must be gra...

Most finfluencers have no skill or negative skill, so copying the average source loses money and each source must be graded. Among 29,477 StockTwits finfluencers, 28% were skilled (+2.6%/month abnormal return), 16% unskilled and 56% antiskilled (-2.3%/month). Weighted by share, the average source is about -0.56%/month before costs and delay. Antiskilled sources have more followers and more influence. A tenfold increase in posts goes with a 3.7% lower probability of skill and 0.08%/month lower alpha. A higher share of bearish posts goes with slightly more skill. Encoding implication: give follower or engagement counts zero or negative weight. Penalise high-frequency posters. Admit a source to live sizing only after a statistically meaningful, after-cost, delay-adjusted graded record, and keep the remaining sources in shadow books.

- confidence: high · vote 3-0, 3-0, 2-1
- evidence: Three claims merged (votes 3-0, 3-0, 2-1), all from Kakhbod, Kazempour, Livdan & Schuerhoff, Finfluencers (SSRN/CEPR working paper). The data is StockTwits, not Discord, and the returns are measured before costs and before any copying delay. The frequency effect is a small, split-vote association. Rated high for the core skill split; the frequency detail is medium.
- sources: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4428232

### Written crowd opinions carry some signal. Views in Seeking Alpha articles and commentaries predicted future returns and ...

Written crowd opinions carry some signal. Views in Seeking Alpha articles and commentaries predicted future returns and earnings surprises over about a three-month horizon. Copy-trading platforms treat even delayed public trade information as copyable value (followers free-ride on trades once they are made public), but no study measured how fast the edge decays with delay. Encoding implication (inference): tips can carry information, but the system must measure each source's decay with delay itself, for example by comparing entry at the tip versus delayed entry in shadow books.

- confidence: medium · vote 3-0, 2-1
- evidence: Two claims merged. Chen et al. is peer-reviewed (Review of Financial Studies 2014), voted 3-0. Yang, Zheng & Mookerjee (Management Science 2022) voted 2-1 and is only a design premise with no decay numbers; its PDF returned 403. The related claim that the best delay differs by trader was refuted 0-3.
- sources: https://hub.hku.hk/handle/10722/267581, https://carlsonschool.umn.edu/sites/carlsonschool.umn.edu/files/inline-files/Social_Trading_0.pdf

### Relative-volume shock is a mildly positive conditioning variable. Stocks with unusually high volume over a day or a week...

Relative-volume shock is a mildly positive conditioning variable. Stocks with unusually high volume over a day or a week, measured against their own recent volume, tended to rise over the following month, and unusually low-volume stocks tended to fall. The effect replicates across 41 countries but is weaker for large caps. It is a volume shock net of the price move, not support for chasing a news spike. Encoding implication: a modest positive score weight for an RVOL spike (for example 1-day or 1-week volume at or above about 2x its own trailing average) on 2-week to 1-month holds. Do not use it as an intraday entry trigger.

- confidence: medium · vote 3-0
- evidence: Voted 3-0. Gervais, Kaniel & Mingelgrin, Journal of Finance 2001, replicated by Kaniel, Ozoguz & Starks (Journal of Financial Economics 2012). The 2x threshold is an illustrative inference, not from the paper.
- sources: https://onlinelibrary.wiley.com/doi/10.1111/0022-1082.00349

### Momentum regime filter: momentum crashes are partly forecastable. They come in 'panic' states after market declines and ...

Momentum regime filter: momentum crashes are partly forecastable. They come in 'panic' states after market declines and when volatility is high, and they coincide with sharp rebounds. From 1927 to 2013, 14 of the 15 worst monthly momentum returns came when the lagged 2-year market return was negative, and all 15 came in months when the market rose. Encoding implication (inference, untested for long-only single-stock tips): flag a hostile regime when the trailing 24-month market return is below 0 and trailing 126-day volatility is high. In that regime, cut size or the number of momentum or breakout entries.

- confidence: medium · vote 3-0 (x2)
- evidence: Two claims merged, both voted 3-0. Daniel & Moskowitz, Journal of Financial Economics 2016 (primary). Most of the crash comes from the short (loser) leg of a long-short decile portfolio, so applying it to long-only tips is an extrapolation.
- sources: https://www.nber.org/system/files/working_papers/w20439/w20439.pdf

### Days-to-cover (short ratio divided by average daily turnover) is a stronger warning flag than plain short interest. From...

Days-to-cover (short ratio divided by average daily turnover) is a stronger warning flag than plain short interest. From 1988 to 2012, a portfolio long the lowest-DTC decile and short the highest-DTC decile earned 1.19%/month (t=6.67), against 0.71%/month (t=2.57) for the plain short ratio. Encoding implication: penalise or avoid long entries in the top DTC decile (high DTC predicts low returns). Do not treat high short interest as a squeeze bonus.

- confidence: medium · vote 3-0
- evidence: Voted 3-0. Hong, Li, Ni, Scheinkman & Yan, NBER WP 21166. The short ratio there is over shares outstanding, not float. Equal-weighted results lean on small caps (value-weighted is about half). The data ends in 2012, and the evidence is monthly sorts rather than short-horizon trades.
- sources: https://www.nber.org/system/files/working_papers/w21166/w21166.pdf

### IBKR cash-account settlement rules: a purchase must be paid for before the security is sold. Selling without full paymen...

IBKR cash-account settlement rules: a purchase must be paid for before the security is sold. Selling without full payment by settlement date is free riding. IBKR's end-of-day surveillance treats closing a position before settlement as a violation and automatically imposes a 90-day 'Cash Up Front' restriction, during which only settled funds can be used. IBKR has applied this to options since January 2023. Encoding implication: track settled cash per currency. Fund every buy only from settled cash. Block any sell of a lot bought with unsettled proceeds until those proceeds settle (T+1 for US stocks and options). This makes intraday round trips possible only with already-settled cash, and the capital stays locked until settlement.

- confidence: high · vote 3-0 (x2)
- evidence: Two claims merged, both voted 3-0. Primary broker documentation, consistent with Reg T 12 CFR 220.8. An IBKR Canada account under CIRO rules may differ and should be confirmed.
- sources: https://www.ibkrguides.com/kb/en-us/free-riding-rule.htm

## caveats

```
Coverage is uneven. No surviving claim addresses: picking the holding horizon from the setup type; how to design scale-outs or target ladders; R-multiple profit-taking or the cost of the disposition effect; volatility targeting (the volatility-managed-portfolio claim was refuted 0-3); VIX, earnings or macro-calendar filters; relative strength or liquidity thresholds; or execution costs (limit vs marketable orders, opening volatility, IBKR commission tiers, CAD/USD conversion). Every parameter range for those areas would be a practitioner judgement and is not given here as evidence. The stop evidence comes from index allocation (Kaminski-Lo), portfolio-level trailing rules (Dai et al., abstract only) and a 2005 practitioner white paper on multi-month trends, so none of it directly calibrates intraday or 2-5 day stops on single stocks. The finfluencer evidence is StockTwits data through about 2021, measured before costs and before copying delay; Discord tip sources may differ. Several factor results (high-volume premium, DTC, momentum crashes) are monthly cross-sectional sorts that may have decayed since publication and were not tested as long-only short-horizon filters. The refuted claims were: delay that depends on the trader; volatility-managed sizing; and the 70/30 stop-out regime statistic. None of these should be encoded. The ranges labelled as inference (0.5-1% risk per trade, 1/4 Kelly cap, RVOL at or above 2x, the trail-activation threshold) are synthesis judgements and should be validated in the system's own shadow books.
```

## openQuestions

```
[
 "How fast does a Discord tip's edge decay with entry delay (seconds, minutes, hours), and does it differ by source and setup type? This needs measuring from the desk's own immediate versus armed shadow books, because no verified study quantifies it.",
 "For 1-5 day single-stock holds, which stop beats the others after costs and noise stop-outs: a structure stop, a 1-3x daily ATR stop, or a percent stop, and judged on the close or intrabar? The verified evidence covers only index-level and multi-month settings.",
 "What are the actual all-in round-trip costs for a ~US$7k IBKR account, including spread, IBKR Pro tiered versus fixed commissions, opening-auction slippage for marketable versus limit orders, and CAD/USD conversion spread? Could they make short-horizon tip trading net-negative even for a skilled source?",
 "Do earnings dates, macro event days or VIX level change short-horizon tip outcomes enough to justify hard blocks rather than size reductions?"
]
```

## refuted

```
[
 {
  "claim": "The best delay before a trader's trades are released publicly depends on that trader's performance profile. A variable (trader-specific) delay policy beat a fixed-delay policy when tested on data from a foreign-exchange social trading platform. This points to edge decay with delay differing by tipster, not being one constant.",
  "vote": "0-3",
  "source": "https://carlsonschool.umn.edu/sites/carlsonschool.umn.edu/files/inline-files/Social_Trading_0.pdf"
 },
 {
  "claim": "Scaling exposure down when recent volatility is high, and up when it is low, produces positive alpha and higher Sharpe ratios than holding the same factor at constant exposure. This supports volatility-targeted position sizing over fixed notional sizing. Caveat: the evidence comes from monthly-rebalanced factor portfolios, not from short-horizon single-stock trades. (Wiley page returned 403; quote taken from the NBER working-paper abstract.)",
  "vote": "0-3",
  "source": "https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12513"
 },
 {
  "claim": "Kaminski and Lo (2008) looked at a 10% stop-loss rule that switches from stocks to bonds, using US data from 1950 to 2004. While the rule held stocks, stocks beat bonds 70% of the time. In the periods after it stopped out into bonds, stocks beat bonds only 30% of the time, so the stop-outs tended to happen when stocks were about to lag. This supports stop-losses as a regime or momentum filter.",
  "vote": "1-2",
  "source": "https://www.quant-investing.com/blog/truths-about-stop-losses-that-nobody-wants-to-believe"
 }
]
```
