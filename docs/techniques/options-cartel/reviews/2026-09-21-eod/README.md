# September 21 EOD — capital was not the binding entry gate

Review cutoff 16:00 ET, retrieved after the close. Read-only review: no trading
settings, orders or runtime changes. Book e7b246c9e30d4dde93f4d91844cbc982,
Options Cartel Practice - Capital Experiment, runtime v0.8.28.

## Actual result

Zero orders, zero fills, zero fees, zero realized P&L and zero open instruments.
The session-review API was independently checked against orders/executions for
the book. Raising capital resolved the preparation affordability problem but did
not create a valid executable entry today. Profitability remains unproven.

| Armed symbol | Trigger | Session high | Observed entry outcome |
|---|---:|---:|---|
| BBY | 95.85 | 94.34 | Did not reach trigger |
| CNH | 14.46 | 13.745 | Did not reach trigger |
| NVT | 163.75 | 161.57 | Did not reach trigger |
| NOW | 139.94 | 140.16 | Brief 09:31 wick; minute closed 139.335, no recorded qualifying 15m crossing |
| NTNX | 70.48 | 70.59 | 10:30 confirmation volume 0.929x; 15:45 volume 1.162x; required 1.5x |
| ULTA | 547.58 | 561.47 | 10:00 close550.39: volume0.420x and first-target0.064R versus required0.25R |

These are stock prices, not option returns. Final regular-session coverage has
zero unresolved minutes after validated interval recovery. Historical data
refusals still occurred while observations arrived; repaired final coverage does
not prove timely delivery. No budget refusal or execution preflight was reached.

## Real-time 5m comparison and a concrete contract-selection flaw

The lab recorded NTNX breakout_5m_v1 at10:30 ET, observed10:30:35.885:
volume2.511x, close70.575, stop69.555, target71.0. It was research only.
Signal e4b98ed9df1663ee63a459832e27d9a2.

Three quote attempts searched November20 and October16 chains (47 structural
candidates), but refreshed only six November contracts. Eligibility failures
included low open interest, stale/missing Greeks and some wide spreads.
The result explicitly recorded searchComplete=false. Code in contracts.py sorts
by expiry distance before taking refresh_limit=6, then checks eligibility after
refresh. One expiry can consume the entire refresh allocation.

At10:30:36, the already-armed October contract NTNX261016C00060000 had a retained
fresh OPRA quote: bid9.80/ask11.30, sizes401/74, source10:30:33.372,
available10:30:33.834, not delayed. The spread is14.22%. This proves there was
another priced expression to examine, not that all its contemporaneous Greek/OI
and risk checks passed. Fix contract search before treating this shadow result
as evidence that a valid option was unavailable.

The same contract's closing bid was9.80. An illustrative ask-to-closing-bid
comparison is -$150 per contract before fees. This is neither an executed trade
nor a full campaign replay. More 5m entries alone would not prove profitability.

## ULTA: real underlying opportunity, costly selected option

ULTA's 5m09:55 close548.76 passed target-room/close-quality but volume0.962x
failed the1.5x rule. The15m10:00 confirmation then left only$0.38 to the first
resistance550.77. It failed both volume and target room. End-of-session stock
close was557.99. This makes confirmation cadence and level selection worth
investigating; it does not establish an eligible missed option profit.

Recorded ULTA261016C00560000 quote at09:55:27: bid10.00/ask14.80, roughly38.71%
spread, above the20% cap. Closing quote bid13.30/ask18.50. Paying the early ask
and liquidating at the closing bid illustrates -$150/contract before fees even
though the stock rose. It does not model intraday trims/stops or claim a fill.
Unlimited virtual cash does not solve an uneconomic option spread. Stocks versus
a genuinely liquid option deserves explicit execution-expression comparison.

## Source/access review

Direct X profile retrieval failed. Public mirrors and ThreadReader were readable,
but current-looking mirror text, relative ages and clicked status pages were
inconsistent. No independently dated September21 trade recap, fill record or
verified P&L for Sean was obtained. Do not call an indexed 'today' post today's
result or compare our book with unverified promotional returns.

Retrieved public sources:
- https://threadreaderapp.com/thread/2070969718882623784.html — archived method:
  leaders, strong themes, contracting bases and5m/15m entries; not an audited result.
- https://mobile.twstalker.com/SRxTrades — mirrored leader/theme/setup commentary;
  original dates not reliably verified in this retrieval.
- https://mobile.twstalker.com/SRxTrades/status/2097097587828707793 — archived
  weekly watchlist; historical comparison only, not a September21 signal.

Saved pre-open analyses explain divergence from the names in public material:
HPE failed a10-day base range of20.70% against15% and volume ratio1.104 against0.8.
NTAP passed the other context checks but volume ratio0.916 failed the0.8 limit:
volume declined about8.4%, while the code requires at least20%. Many cited leaders
were excluded by the same fixed dry-up/tightness rules. These engineering cutoffs
are stricter numerical interpretations of qualitative source guidance. A named
stock on a watchlist still is not proof of a trade or a missed winner today.

## Prioritized actionable changes

1. **Contract selection:** assess the already-reviewed contract first; diversify
   quote refresh across expiries; use known static liquidity failures to avoid
   spending all refresh slots on ineligible contracts. Preserve quote freshness,
   Greek, spread and size checks. Retain explicit incomplete-search status.
2. **Execution economics:** rank affordable options by executable spread/cost and
   usable liquidity, not DTE/delta proximity alone. A valid stock entry can still
   have no sensible option expression; compare bounded long shares where valid.
   Do not remove liquidity gates just to manufacture trades.
3. **Entry/setup fidelity:** evaluate5m against15m with their own baselines and
   realistic option costs. Review the hard1.5x volume requirement and fixed10-day
   dry-up/base rules by setup family. NTAP shows a concrete borderline dry-up
   exclusion. Keep source thresholds separate from engineering assumptions.
4. **Correct attribution:** NTNX/ULTA are labeled data_limited by the report
   because any earlier data refusal dominates the category. Their known critical
   confirmation refusals must be shown first, with data gaps as independent
   qualifiers. Otherwise the UI suggests fixing data alone would have entered.

No trading policy was changed during this review. The first recommended
implementation is bounded contract-search correction, followed by same-input
execution-economics and entry-cadence comparisons. Do not simultaneously relax
all filters, change exits and increase size; that would hide the cause of results.
The prior user authorization permits pursuing improvements; this review does not
claim that any proposed variant is profitable.

## Remaining operating issues

SAIC/ASC still lacked entry-window historical baselines; FISV lacked a2025-11-12
daily bar. These were not the causes of the six armed names failing to trade.
Health at review: zero failed handlers/bus drops and current lag about7ms;
21 historical loop stalls were recorded, last before this session. No causal
link from those old stalls to today's missed entries was established.
