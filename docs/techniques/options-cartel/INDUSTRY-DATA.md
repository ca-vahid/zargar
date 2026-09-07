# Industry evidence for Cartel

September 7 automation update: [Daily preparation](DAILY-PREPARATION.md) now
captures the complete publisher table directly and joins the stock screener's
publisher industry labels. It uses an explicit, at-most-24-hour observation-age
policy for this current publication, leaving constituent data time unknown.
The older manual/provider-time workflow below retains its stricter timestamp
requirement; its collection gaps describe the earlier implementation.

Sean's September thread requires an industry in the top ten on both weekly and
monthly performance. The linked [TradingView industry page](https://www.tradingview.com/markets/stocks-usa/sectorandindustry-industry/)
provides a Performance tab with independently sortable 1W and 1M columns.
Overview ordering is not performance rank. Browser inspection: 2026-09-07.

For manual evidence, select Performance, sort 1W descending, record the stock's
industry and its rank, then repeat for 1M. Verify the sorting direction from the
values. Preserve the source URL and observation time with the submitted facts.
Cartel requires both ranks to qualify; strength in one period does not imply
strength in the other. Bearish rank inputs describe downside leadership and
must be recorded separately from the bullish descending list.

Do not assign a stock an industry from its narrative theme alone. Record the
source of the symbol-to-industry mapping. Do not substitute sector rank for
industry rank. Missing ranks stay unknown under the existing screen gate.

Automated collection still needs a verified complete universe, explicit missing
values and tie handling, raw performance values, sort direction, provider time,
collection time and symbol membership. A 2026-09-07 read-only DOM check confirmed
129 displayed industry rows, matching the header, with explicit 1W/1M percentage
values in every row. The earlier 115-row finding was a parser error: 14 labels
with colons were quoted differently in the accessibility snapshot. Future
captures still need their own count check. Displayed rounding can hide ties, so a locally inferred
rank must not claim exact provider parity without a documented tie rule.

Historical scans require snapshots available at the historical decision time.
Today's table cannot establish earlier leadership or membership. A source-dated
snapshot import/store is now available through
`POST /api/options-cartel/industry-snapshots`. Daily preparation now adds automated
collection and stock-facts integration; today's capture still cannot establish
historical leadership before its observation time.

## Combining evidence without look-ahead

Legacy `ListingFacts` inputs bundle capitalization, industry mapping and ranks
under one `observed_at`. They remain supported as coherent snapshots. Imported
ranks now retain separate observation/data timestamps and source, while stock
capitalization and mapping retain their original evidence timestamp. Do not
refresh that stock timestamp while silently keeping an older component.

Collection time and market-data time are different. Record a provider's published
data timestamp when available, but do not claim that a table fetched today was
available at an earlier trading decision just because its last session was
Friday. Historical eligibility requires evidence available at that decision time.
Likewise, use the provider's actual 1W/1M definitions; do not substitute calendar
week/month returns or a different industry weighting without labeling the change.

Before the scan gate can consume an imported rank, require a verified symbol-to-
industry mapping, complete captured industry universe, explicit period values,
direction and a documented tie rule. A tie spanning the top-ten boundary must
remain ambiguous unless the provider's ordering is verified. These are the next
data-integration acceptance checks; the import foundation below covers only part of them.

## Snapshot import foundation

The import accepts source/observation/data timestamps, explicit 1W/1M definitions,
expected universe count and unique named rows with percentage values or explicit
missing values. It rejects count mismatches, duplicates and future observations.
It stores the original input and SHA-256 digest as an owned research record.

The pure reader computes best/worst ranks: tied observations share a range, and
missing values in other industries widen that range. A rank range crossing the
top-ten boundary stays unknown. Bullish and bearish rankings use opposite ordering
and require both periods. Data age and observation availability are checked
separately. Imported source accuracy is not independently verified, and importing
does not arm or place orders.

Analyze, collect and focus-list scan requests can now select `industrySnapshotId`.
The service loads only an owned industry record and resolves the explicitly
provided stock industry against it. Rank intervals are retained in saved facts;
ambiguous top-ten ties, unavailable snapshots and stale data cannot qualify.
Fresh ranks do not refresh stale stock evidence. Future rank values are omitted
from the historical screen display while original inputs remain preserved.
The desk now offers a tab-separated import form and a recent-snapshot selector.
Imported captures open for review and are applied only when explicitly selected.
Unknown source-data timestamps can be stored, but their freshness remains unknown
and they cannot qualify stock screening. Manual rank inputs are disabled while
a saved snapshot is selected. Automated capture remains unfinished; browser and
mobile acceptance of the new import workflow is still pending.

## Existing provider assessment — 2026-09-07

The app already uses Yahoo quoteSummary through `EventCalendar` and an anonymous
cookie/crumb session. A read-only probe for MU requesting `price,assetProfile`
returned HTTP 200 with matching symbol, USD currency, capitalization, quote time
and industry classification. Sanitized evidence is saved in
`.cache/options-cartel/fundamentals-probe.json`; no session tokens were stored in
that artifact. This is evidence of one working current-data request, not a
historical fundamentals feed or a guarantee for every symbol.

The existing `technique/universe.py` most-active helper also exposes capitalization,
but its Yahoo universe is prefiltered more strictly (volume above 5M and cap above
2B) than Cartel's source scan. It must not silently substitute for the complete
Cartel universe.

The candidate form now captures and persists quoteSummary evidence and passes the
selected capture into collection and analysis. Capitalization has separate
observation and provider-price timestamps; future observations, stale provider
times and unsupported currencies cannot qualify the capitalization gate. This
does not refresh stock-to-industry evidence. Yahoo's industry label
is a provider classification suggestion; it is not by itself proof of membership
in a TradingView industry aggregate. That mapping remains an explicit verification
step before joining a stock to the captured rank table.

Captures selected during the current page visit are retained per symbol and used
by matching symbols in focus-list scans. The scan persists the capture ID map;
retries retain it and the original cutoff. Invalid or missing captures produce a
per-symbol data error while other symbols complete. Changing the candidate symbol
clears manual facts to prevent accidentally transferring another stock's evidence.
Captures remain in saved history. The candidate form lists matching symbols from
the 200 most recent captures, requiring explicit selection after reopening the
page. Automated universe collection remains unfinished.

The focus-list form can capture capitalization for all 1–20 listed symbols before
scanning. Each response is saved separately with its actual observation time.
Failures remain visible per symbol and clear that symbol's selected capture;
successful siblings remain usable. Capture does not automatically start a scan.
The subsequent scan cutoff therefore follows the selected evidence observations.
This is user-requested batch collection, not scheduled market-wide discovery.

## Verified current stock membership

The read-only membership collector requests an explicitly selected NASDAQ, NYSE
or AMEX stock page, verifies its canonical identity, reads its unique US-industry
link, then requires that industry page's member table to contain the exact
exchange and symbol. Redirects, ambiguous classifications and absent member rows
are rejected. For example, [MU's company page](https://www.tradingview.com/symbols/NASDAQ-MU/)
links to [Semiconductors](https://www.tradingview.com/markets/stocks-usa/sectorandindustry-industry/semiconductors/),
whose table includes NASDAQ:MU (verified 2026-09-07). No Yahoo-to-TradingView label
translation is inferred.

`POST /api/options-cartel/membership/{exchange}/{symbol}` saves an owned membership
record with source URLs, extracted identity, observation time and both response
hashes. The desk's Verify industry membership control selects the result for that
symbol. Candidate analysis uses `membershipSnapshotId`; scans persist a per-symbol
`membershipSnapshotIds` map, retained on retries. Capture time establishes when
this current classification was observed, not a historical effective date. Its
age is checked independently of capitalization and performance-rank evidence.

This automates positive membership verification for supported pages. It does not
claim complete market coverage: a missing row may reflect pagination, and still
fails verification. Saved membership selection after reopening the page is now
available, with explicit per-symbol selection from the 200 most recent captures.
Automatic exchange discovery and complete industry-performance collection remain unfinished.

## Provider definitions and complete-table loading

TradingView's [classification documentation](https://www.tradingview.com/support/solutions/43000724300-sector-industry/)
identifies FactSet's industry/sector model and groups companies by their principal
revenue-generating business. Theme labels and Yahoo classification strings are
therefore not sufficient substitutes for verified membership.

The [Screener performance definition](https://www.tradingview.com/support/solutions/43000636536-how-is-performance-calculated-in-the-screener/)
compares the latest close with an earlier bar's open, expressed as a percentage
of that open's absolute value. Its example implementation uses seven calendar
days for 1W and thirty for 1M, locating the corresponding historical daily bar.
This differs from weekly/monthly Change and from close-to-close returns. The
example depends on current time and explicitly distinguishes realtime from
historical results. It documents the symbol screener calculation; it does not
by itself establish the weighting or update timestamps of aggregate industries.
Those aggregate details remain unverified.

A fresh browser check selected Performance and clicked Load More. That yielded
129 actual rendered industry rows. The displayed header count alone is insufficient:
the initial page contains only 100 rows. Rendered performance columns identify
`Performance|Interval1W` and `Performance|Interval1M`; changing the tab does not
change the page URL. No `time` elements were exposed in the resulting document.
That absence is not proof that no timestamp exists anywhere, but this check did
not establish a usable provider data timestamp. Do not invent one from the
collection clock or the preceding exchange close.
