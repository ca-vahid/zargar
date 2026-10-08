# Scout - data notes (P0, verified first-hand 2026-10-07)

Everything below was fetched from the live sources on 2026-10-07 (evening ET) with
`User-Agent: Zargar research vhaeri@bgcengineering.ca`, throttled well under the SEC's 10 req/s.
Saved real samples live in `backend/tests/fixtures/scout/` (the unit tests parse them; no network in tests).

## 1. SEC EDGAR - Form 4

### 1.1 Listing a day's Form 4s: the daily form index

`https://www.sec.gov/Archives/edgar/daily-index/{YYYY}/QTR{q}/form.{YYYYMMDD}.idx` (directory listing also as
`.../QTR4/index.json`). Fixed-width text, sorted by form type:

```
Form Type   Company Name                                                  CIK         Date Filed  File Name
---------------------------------------------------------------------------------------------------------------------------------------------
4                AFLAC INC                                                     4977        20261006    edgar/data/4977/0001104659-26-113911.txt
4                Japan Post Holdings Co., Ltd.                                 1783464     20261006    edgar/data/1783464/0001104659-26-113911.txt
4/A              Arbe Robotics Ltd.                                            1861841     20261006    edgar/data/1861841/0001213900-26-107326.txt
```

- **A Form 4 is listed once per party** (issuer AND each reporting owner): 2026-10-06 had 837 `4` lines but 412
  unique accessions. Dedupe on the accession number.
- Published once a day: `form.20261006.idx` was last-modified `10/06/2026 10:02:38 PM` (ET). No file for
  weekends/holidays (404). Volumes on 2026-10-06: 412 Form 4, 245 8-K.
- Intraday alternative (not used in P1): the Atom feed
  `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&owner=include&count=40&output=atom` - each
  `<entry>` has `<updated>2026-10-07T21:43:44-04:00</updated>` (= acceptance, with offset), title
  `4 - <name> (<cik>) (Reporting|Issuer)`, and `AccNo` in the summary. Useful for P3/P4 same-evening runs.

### 1.2 One filing: the full submission `.txt` (header + XML in one request)

`https://www.sec.gov/Archives/edgar/data/{cik}/{accession}.txt` (the path from the index). Top of the file:

```
<SEC-DOCUMENT>0001104659-26-113911.txt : 20261006
<SEC-HEADER>0001104659-26-113911.hdr.sgml : 20261006
<ACCEPTANCE-DATETIME>20261006090030
ACCESSION NUMBER:		0001104659-26-113911
CONFORMED SUBMISSION TYPE:	4
CONFORMED PERIOD OF REPORT:	20261002
FILED AS OF DATE:		20261006
```

then the `ownershipDocument` between `<XML>` and `</XML>`. Header-only (smaller, ~900 B):
`https://www.sec.gov/Archives/edgar/data/{cik}/{accession-no-dashes}/{accession}.hdr.sgml` with
`<ACCEPTANCE-DATETIME>`, `<TYPE>`, `<FILING-DATE>` and, for 8-Ks, one `<ITEMS>` line per item.

### 1.3 Fields Scout reads (ownershipDocument, schema X0609)

| What | XML path | Sample |
|---|---|---|
| Issuer CIK / ticker | `issuer/issuerCik`, `issuer/issuerTradingSymbol` | `0000004977`, `AFL` (free text: `AXIA3`, `NONE` happen) |
| Insider | `reportingOwner/reportingOwnerId/rptOwnerCik`, `rptOwnerName` | `0001783464`, `Japan Post Holdings Co., Ltd.` |
| Role flags | `reportingOwner/reportingOwnerRelationship/isDirector`, `isOfficer`, `isTenPercentOwner`, `isOther`, `officerTitle` | **`1`/`0` OR `true`/`false`** - both seen the same day |
| Rows | `nonDerivativeTable/nonDerivativeTransaction` (derivative table ignored) | |
| Date | `transactionDate/value` | `2026-10-02` |
| Code | `transactionCoding/transactionCode` | `P` purchase, `S` sale, `A` award, `M` exercise, `F` tax, `G` gift ... |
| Shares / price | `transactionAmounts/transactionShares/value`, `transactionPricePerShare/value` | `5671`, `110.93` (price can be a weighted average - footnote; absent for gifts) |
| Acquired/disposed | `transactionAmounts/transactionAcquiredDisposedCode/value` | `A` / `D` |
| Direct/indirect | `ownershipNature/directOrIndirectOwnership/value` | `D` / `I` |

Joint filings carry several `reportingOwner` blocks sharing one transaction table (fixture `form4_joint.txt`: a CEO
and his family trust). Scout stores one row per (transaction, owner) with `row_key = accession:index` and counts a
row's value once.

### 1.4 Acceptance time - semantics (the refuted research claim, settled)

- `<ACCEPTANCE-DATETIME>YYYYMMDDHHMMSS` is **US Eastern wall clock**: the Grab Form 4 header says `20261007214344`
  and the Atom feed says `2026-10-07T21:43:44-04:00` for the same accession.
- Form 3/4/5 accepted in the evening keep the SAME filing date (accepted 21:43 ET -> `FILED AS OF DATE 20261007`;
  `form4_purchase_1.txt` accepted 18:07:46 on 2026-10-06, filed 2026-10-06). So a filing date alone does not say
  whether the market could have traded on it that day.
- **Rule used by S1:** signal time = acceptance; entry = the first regular session whose 09:30 ET open is strictly
  after it (pre-open filing -> same day; after 09:30 -> next session). Data-set rows without an acceptance time are
  treated as known at 23:59 ET of the filing date (conservative - never earlier than the truth) and flagged
  `signalTimeApprox` until `scout_backfill` enriches them from the header.
- **Gotcha:** `data.sec.gov/submissions/CIK##########.json` `acceptanceDateTime` is NOT the UTC it claims.
  AAPL 8-K header `20260730163028` (16:30:28 EDT) -> JSON `2026-07-31T00:30:28.000Z`; AAPL `20260129163033` (EST) ->
  `2026-01-30T02:30:33.000Z`; B&G Foods `20261006080045` -> `2026-10-06T16:00:45.000Z`. The JSON is the true UTC
  instant plus the ET offset again. `form4.submissions_json_acceptance()` undoes it (tested on these three).

### 1.5 History: the quarterly Insider Transactions Data Sets (the backfill path)

`https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets` lists one ZIP per quarter,
2006q1 -> 2026q3. **Newer quarters moved folders:** 2026q2+ under
`/files/datastandardsinnovation/data/insider-transactions-data-sets/{yyyy}q{q}_form345.zip`, older under
`/files/structureddata/data/insider-transactions-data-sets/`. 2026q3: 8.7 MB zipped, 53 MB of TSVs, published
2026-10-03 (Last-Modified 2026-10-07). Tables used:

- `SUBMISSION.tsv`: `ACCESSION_NUMBER, FILING_DATE (31-JUL-2026), PERIOD_OF_REPORT, DOCUMENT_TYPE (4, 4/A, 3, 5),
  ISSUERCIK, ISSUERNAME, ISSUERTRADINGSYMBOL, AFF10B5ONE`
- `REPORTINGOWNER.tsv`: `RPTOWNERCIK, RPTOWNERNAME, RPTOWNER_RELATIONSHIP` (comma list: `Director,Officer`,
  `TenPercentOwner`, `Other`), `RPTOWNER_TITLE`
- `NONDERIV_TRANS.tsv`: `NONDERIV_TRANS_SK, TRANS_DATE, TRANS_CODE, TRANS_SHARES, TRANS_PRICEPERSHARE,
  TRANS_ACQUIRED_DISP_CD, DIRECT_INDIRECT_OWNERSHIP, ...`

**No acceptance time** in the data sets (filing DATE only). 2026q3 counts: 33,521 Form 4 + 627 4/A; transaction
codes S 25,441, A 9,817, M 7,433, F 6,802, **P 5,184**. One ZIP per quarter replaces ~35k per-filing requests, so the
3-year (and longer) backfill costs minutes, not days. Acceptance times for the rows S1 actually times
(officer/director purchases) are stamped afterwards from `.hdr.sgml`, newest first.

## 2. Earnings source for S2

- **Event time:** 8-K **item 2.02 "Results of Operations"**. The daily form index lists 8-Ks; the `.hdr.sgml` of each
  gives `<ITEMS>2.02` + acceptance (fixture `8k_202.hdr.sgml`: `20261006161531`, items 2.02/7.01/9.01). ~245 8-K
  headers/day = ~1 minute at 5 req/s. For history, the per-company submissions JSON (`filings.recent`: `form`,
  `items` "2.02,9.01", `acceptanceDateTime` (with the offset bug above), `filingDate`, up to 1000 filings) gives every
  past release in one request per issuer.
- **Decision:** S2 uses the 8-K 2.02 acceptance time as the announcement time (free, timestamped, point in time).
  Caveat: the 8-K can follow the press release by minutes to hours (AAPL files at the 16:30 release; others file
  later or the next morning) - day 0 is the first session that closes after acceptance, so a late 8-K can shift day 0
  by one session. Ticker = SEC `company_tickers.json` (CIK -> current ticker; not point in time).
- **Reaction:** day 0..+1 abnormal return = close(+1)/close(-1) of the stock minus the same for SPY, from the shared
  Alpaca-first daily bars (`marketstructure.history.fetch_window(sym, "1d", ...)`); volume ratio = day-0 volume over
  the 20 prior sessions.
- **Upcoming earnings (S1 "no earnings in the hold" gate):** the engine's Yahoo calendar (advisory,
  `confirmed=False`); an empty answer is treated as unknown and falls back to projecting the issuer's 8-K 2.02 cadence
  (last release + 84..98 days); no history = `unknown`.

## 3. Other gate data

- **Market cap:** SEC XBRL `https://data.sec.gov/api/xbrl/companyconcept/CIK##########/dei/EntityCommonStockSharesOutstanding.json`
  (`units.shares[]` with `end`, `val`, `accn`, `form`, `filed`) x last close. Point in time via `filed <= signal date`;
  multiple share classes on the same `end` are summed. Missing fact -> `unknown` (foreign filers, new listings).
- **Spread at entry:** Alpaca `GET /v2/stocks/{sym}/quotes?start&end&feed=sip` works historically (fields `ap, as,
  ax, bp, bs, bx, c, t, z`; e.g. AAPL 2026-10-06T13:35:00.001Z bp 332.92 / ap 333.06). Scout takes the median spread
  % of mid over 09:35-09:40 ET of the entry session; before that it is `unknown` (pending), re-checked by the daily job.
- **Reverse split / symbol change:** Alpaca `GET /v1/corporate-actions?symbols=&types=reverse_split,name_change` ->
  `corporate_actions.reverse_splits[] (ex_date, old_rate, new_rate, symbol)` and `name_changes[] (old_symbol,
  new_symbol, process_date)`. Best effort; unavailable -> `unknown`.
- **Tips mention:** the platform `signals` table (`ticker`, `source_name`, `created_at`), read-only.

## 4. Alpaca news (context only, left for P3)

`GET https://data.alpaca.markets/v1beta1/news?symbols=AAPL&start&end&limit` -> `{news: [...], next_page_token}`;
each item: `id, headline, author, source ("benzinga"), summary, content (often empty), images[], symbols[],
url, created_at, updated_at` (RFC 3339 UTC, e.g. `2026-07-31T20:00:27Z`). Many items tag 5-18 symbols (market
wraps), so a symbol match is not company news. `created_at` vs the true publication time was NOT verified - do not
use it for timing until P3 checks it against the source page. The WebSocket stream was not tested.

## 5. Volumes and cost of the backfill

| Phase | Requests | Notes |
|---|---|---|
| Data sets 2015q1-2026q3 | 47 ZIPs | ~1 min each to download + parse; 2015q1 alone = 65,957 Form 4/4-A filings, 39,562 P/S rows |
| Daily indexes (current quarter) | 1 + ~400 Form 4 + ~250 8-K per day | ~2-3 min/day at 5 req/s |
| Acceptance enrichment | 1 per officer/director purchase filing | the long tail; newest first, resumable |
