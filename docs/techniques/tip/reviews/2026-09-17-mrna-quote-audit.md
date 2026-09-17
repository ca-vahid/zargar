# MRNA Sep-18 165C, 2026-09-17 10:04 ET - quote-sequence audit (E17-01)

Read-only audit of the Practice fill that booked +$112.92 in 3.6 seconds. The booked ledger is NOT rewritten; this
record attaches an evidence-quality finding to it. Sources: `events` (TipEntryStudy, OrderFill evidence,
TipFillVsQuote, ManagedPosition*), `bars` (1m, source exchange, OCC symbol), the QuoteCache code path as deployed
(0.8.09 `dd525de`; no diff to reviewed main in `marketdata.py`). The raw provider messages themselves are not
journaled (quotes are never journaled - a standing rule), so the chain of custody below is reconstructed from the
receipts that exist plus an offline reproduction of the transformation. It is a mechanistic explanation, not a
provider-message proof.

## Sequence (all ET)

| Time | Record | Bid / ask / last | Source, sourceAt | Meaning |
|---|---|---|---|---|
| 10:04:50.954 | TipEntryStudy `atDecision` | 1.90 / 2.01 / 2.00 | opra, 10:04:50.954 | the market the analyst decided on |
| 10:04:51.204 | OrderIntentCreated | limit 1.95 | | BUY 1 LMT 1.95 (analyst take, proposal 6a6a6ecd) |
| 10:04:53.554 | (OPRA pass, inferred from the fill's `sourceAt`) | 1.90 / 2.00 (raw, from the 10:04:58 receipt) | opra | the real-time band still ~1.90/2.00 |
| ~10:04:54.79 | incoming Quote with `last` = 0.70 (chart feed; bid/ask 0) | | feed "" | a STALE print: the contract printed 0.70 at 09:43 and 09:49 ET (`bars`), never in the 10:03-10:05 minutes (10:04 bar low 1.90) |
| 10:04:54.793 | OrderFill evidence | **0.65 / 0.75** / -, askSize 1, bidSize 7 | **opra, 10:04:53.554** | `QuoteCache._apply_overlay` recentred the OPRA band (width 0.10) on the 0.70 print and KEPT `source=opra` and the fresh source time; the sim priced the marketable limit at the synthetic ask 0.75 |
| 10:04:57.317 | TipFillVsQuote | fill 0.75 vs quote mid 1.955 | | vsMid -1.205 (-$120.50 "improvement") - the diagnostic flagged the anomaly |
| 10:04:57.576 | ManagedPositionExit (quote watch) | mark bid 1.90 | opra | "+153% (premium TP1 +100%)" on the next real OPRA band |
| 10:04:58.428 | OrderFill evidence | 1.90 / 2.00, bidSize 17 | opra, 10:04:58.425 | SELL 1 @ 1.90 |

## Offline reproduction (reviewer's `test_sep17_quote_provenance_review.py`, adopted verbatim)

OPRA overlay bid 1.90 / ask 2.00, fresh `source_ts`, `anchor_last` 1.95; deliver `Quote(last=0.70, bid=0, ask=0)` -> the
cache held bid 0.65 / ask 0.75 with `source="opra"`, and `SimExecutor.quote_rejection` accepted it. An unchanged raw
OPRA quote (positive control) is accepted, as it must be. On main before the fix: 2 failed, 1 passed. After the fix
(this PR): 3 passed.

## Why the print was stale

The chart feed publishes the contract's `last` from Yahoo's 1-minute chart for the unpadded OCC symbol
(`options/service.py` module docstring), which lags real time by minutes. The 0.70 value matches the contract's
09:43 and 09:49 ET prints exactly; MRNA shares were ~154-156 then and ~159.7 at 10:04, when the same call traded
1.90-2.00. The recentring rule was written for the DELAYED CHAIN case (2026-09-02 GOOGL 0DTE: the live tape had moved
past a 15-minute-old chain band) and was never meant to move a real-time venue band toward a slower feed.

## Fix (PR, this branch)

- `QuoteCache._apply_overlay`: an overlay whose `source` is a venue identity (`opra`, `ibkr`) is never recentred; the
  print is kept as a print. A delayed-chain overlay may still be recentred (the GOOGL lesson), but the result is a
  DERIVED estimate: raw bid/ask/source/source_ts ride on the quote (`raw_*`), `source` becomes `derived:<raw source>`,
  `transform` = `recenter-v1`. Both paths are covered: a new incoming quote and an update to an existing cached quote.
- `Quote.delayed` is true for derived quotes; `SimExecutor.quote_rejection` refuses any transformed quote with an
  explicit reason (before the delayed/identity checks), and `quote_evidence` records `transform`, `rawBid`, `rawAsk`,
  `rawSource`, `rawSourceAt` (None when untouched).
- Positive control retained: an unchanged, fresh OPRA quote still prices fills.
- Not done on purpose: no blanket "quote jump" rejection, no change to protective exits, no share-path change beyond
  the transform refusal (PR #199's share-session / spread guards are a separate matter).

## Effect on the ledger and on method grading

The +$112.92 stays in the booked ledger. In method grading it is shown SEPARATELY as an evidence-quality-limited
result (the buy price was a locally transformed value that could not have been executed at the venue); the other
closed Tips results on 2026-09-17 total +$71.99, a sensitivity subtotal, not a replacement. The overnight-hold
research row for the position carries the same label. Whether such fills should be reversed in the Practice book is
the user's call; nothing was reversed.

## Residual limitations

- Raw provider messages are not retained; the reconstruction rests on the fill receipt's `sourceAt`, the TipEntryStudy
  samples, the bars, and the reproduction. A future raw-quote ring buffer for symbols with open orders would make this
  a proof instead of an explanation (not built here - it is a platform decision with memory cost on a host that is
  already paging).
- The GOOGL 355C shadow fill at 09:30:01 on a 3.60/6.35 1x1 quote is a different pattern (wide one-lot book, not a
  recentring) and stays under the F-FILL-02 finding.
