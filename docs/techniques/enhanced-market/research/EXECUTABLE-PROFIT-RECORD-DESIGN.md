# ED-04 - executable-profit record: design (2026-09-17 late; build follows, recorder OFF by default)

Owner: the EM desk session (record, capture, offline reducer). The Tips desk owns the shared quote-cache / portfolio-mark
layer this reads and reviews the shared-code diff. Reviewer acceptance contract (2026-09-17 EOD review, package A; ED-04)
is retained verbatim in `reviews/2026-09-17-EOD-RESPONSE.md` and restated here as the record's fields.

## The question the record answers

For one EM Practice position at one instant, three different numbers are currently conflated:

| Number | What it is | Where it comes from today |
|---|---|---|
| **Realized net** | cash already booked from fills, net of actual commissions | executions (`orders`, `executions`), exact |
| **Displayed open profit** | the book's mark of the remaining quantity (option mid when an ask exists, share last) minus cost | `portfolio.py::_mark`, the 30 s equity push - the number the UI and the day-change show |
| **Executable profit after fees** | what the remaining quantity could have been sold for at that instant against the covered side of a fresh quote (bid for longs, ask for shorts), size-limited, minus the modeled exit fee | does NOT exist - the 09-17 "giveback" of $161.63 was measured on marks |

The record makes the third number first-class and keeps the uncovered / stale / unknown part explicit, so a marked
high-water mark can never masquerade as liquidatable profit.

## Record: `TechniqueBookSnapshot` (journal event, one per position instant)

```
type: TechniqueBookSnapshot            version: "book-snapshot-v1"
runId, symbol, trigger, tradeInstance (= entry order id)   -- identity, all REQUIRED
at (ms)                               -- when the snapshot was taken (engine clock)
reason: "pre_decision" | "post_decision" | "bar_close" | "quote_watch" | "flatten" | "restore"
decision: {kind: tp1|tp2|tp3|stop|scratch|flatten|none, qty}   -- the production decision the snapshot brackets (if any)
quantities: {original, remaining, pendingExit, reserved}        -- remaining = held; pendingExit = committed to a working exit;
                                                                -- reserved = remaining - pendingExit (the only quantity that can be sold now)
realized: {net, gross, fees, fills: n}                          -- from executions, exact
mark: {basis: "mid" | "last" | "none", price, valueOpen, unrealizedAtMark}   -- the displayed number, reproduced from the same rule as the book
executable: {
   side: "bid" | "ask",                                         -- bid for a long, ask for a short (a short option = BUY to close at the ask)
   quote: {price, size, source, sourceTs, receivedTs, ageS, delayed, transform}   -- identity + freshness of the quote used
   coveredQty, uncoveredQty,                                    -- min(reserved, displayed size) and the rest
   grossCovered, feeModeled, netCovered,                        -- (price - avgFill) x coveredQty x m ; fee_side x coveredQty ; difference
   status: "covered" | "partial" | "unknown",                    -- unknown when the quote is stale (> 10 s source age), delayed, transformed,
                                                                --   crossed, or the size is unknown / zero
   why (when not covered)
}
total: {realizedNet, executableNetCovered, executableUnknownQty, displayedUnrealized}   -- the three numbers side by side
```

Rules (frozen with the record):
- A snapshot is never taken by a protective decision path synchronously: capture is a pure function producing a dict, the
  dict is enqueued to the existing bounded shadow recorder (`_shadow_enqueue`), the exit proceeds immediately (the P-06 /
  shadow-exit pattern). A full queue drops visibly (counted + logged), never blocks.
- `executable` uses ONLY a quote whose `source` is a venue (`opra` / `ibkr` for options; the feed for shares), whose source
  age is <= 10 s, that is not `delayed` and not `derived:*` (E17-01 transform), with a finite uncrossed book and a KNOWN
  displayed size. Anything else -> `status: unknown` with the reason. Unknown is a value, never a zero.
- Spread is never subtracted twice: the executable number uses the covered side directly; the mark keeps its own basis.
  The difference `executableNetCovered - displayedUnrealized` is the spread-and-depth haircut, reported, not modeled.
- Fees: realized uses actual commissions; executable uses the modeled per-unit exit fee (the fee schedule's median observed
  side, as the profitability tool does today) and says so.
- Reconciliation: at the terminal event the last `pre_decision` snapshot's covered quantity must equal the quantity the
  production exit then sold (else `reconcile: mismatch` is journaled by the reducer, never silently corrected).
- Restore: after a restart the first snapshot is `reason: restore` so the series has an explicit gap marker.

## Reducer (offline, `tools/em_profitability.py`, per session)

Per position: the series of snapshots -> (a) realized net (exact), (b) displayed high-water mark (mark basis), (c) executable
high-water mark = max over snapshots of `realizedNet + executableNetCovered` with `executableUnknownQty == 0` (a snapshot with any
uncovered quantity cannot make a high-water mark), (d) giveback = executable HWM - final realized net, (e) coverage ratio =
snapshots with `status: covered` / all. Book level: the same over the sum of positions at each instant (synchronized by `at`
bucketed to the second; instants where any position is `unknown` are excluded from the book HWM and counted). Output beside
P-01..P-06 in the per-session report; nothing here is a rule.

## Acceptance (from the review; each becomes a test before the knob can be turned on)

1. A stale / delayed / transformed / unknown-depth quote cannot make a liquidatable high-water mark (`status: unknown`, excluded).
2. Partial and pending quantities cannot be sold twice (`reserved` is the only sellable quantity; `pendingExit` excluded).
3. An option-mid spike is visibly distinct from realizable net (mark vs executable side by side, haircut reported).
4. Snapshots bracket target / stop / protection decisions (`pre_decision` / `post_decision`) and never delay them (pure
   capture + enqueue; the exit path has no await on the recorder).
5. Reconciles to fills at the terminal event; spread never subtracted twice.
6. ORCL 09-17 evidence unchanged, still flagged as simulated / questionable.

## Build plan (next dev session; nothing tonight)

1. `execution/booksnapshot.py`: pure `capture_book_snapshot(tr, q, oq, now_ms, fee_side, mark_rule)` + tests for rules 1-3, 5.
2. `PlanRunner`: knob `techniques.enhanced_market.book_snapshot_observe` (DEFAULT False) -> enqueue at `bar_close` and around
   every `_exit` decision (`pre_decision` / `post_decision`), and on the quote watch at most once per 30 s per position.
3. Reducer + report section; then the observation-only deployment with the knob OFF; turning it on is a user decision,
   disclosed like the P-06 observer.

Kept: no trading rule, threshold or exit policy changes from this work; P-02 / P-06 collection untouched.
