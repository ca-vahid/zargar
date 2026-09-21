# 2026-09-21 - the experiment's zero fills: proved from the durable records, not inferred

Read-only investigation. Nothing changed. Written after the Team2 desk asked, correctly, whether EM's refusals were
"in-future" or "untimed" - the two have the same symptom and different fixes, and only one of them is cured by a clock
resync.

## The answer: every refusal is `venue_time_in_future`

All nine `TechniqueFirstSale` records of the session carry `underlying.validated.problems = ["venue_time_in_future"]`.
Nine of nine. No `venue_time_unknown`, no `source_unknown`, no `stale_underlier`, anywhere in today's payloads.

The first record (IREN, 09:31:02 ET) shows the mechanism exactly:

| Field | Value | Meaning |
|---|---:|---|
| `receivedTs` | 1789997462010 | when the HOST thinks the quote arrived |
| `quoteTs` | 1789997471583 | venue time of the bid/ask, **+9,573 ms** |
| `lastTs` | 1789997472041 | venue time of the print, **+10,031 ms** |
| `source` | `feed:HybridQuoteFeed` | identified, not derived, not delayed |

The quote is complete: two-sided, sourced, and carrying real venue times. `validate_underlier` rejects it because
`max(quoteTs, lastTs) - now_ms > 1000`, and with the host clock roughly 9.6 s behind, every equity quote in the session
looks future-dated. The gate is doing precisely what it was built to do; the evidence it is judging is stamped against a
wrong clock.

Corroboration, two independent clocks against one: the Postgres instance in Docker/WSL reads +8.3 to +9.6 s ahead of the
host all session, and the venue stamps agree with it. The Windows Time service is not started. The host is the outlier.

## Why this matters for the close report

The experimental book's zero fills today are an **environmental fault**, not a verdict on the method. The rules produced
12 fires; nine reached the admission gate and were deferred on evidence that was itself correct. The remaining three were
ordinary rule skips. Nothing was refused for a reason belonging to the bundle under test, so today supports no comparison
of admission policy between the books.

## What would and would not fix it

| Option | Effect | Cost |
|---|---|---|
| Start / resync the Windows Time service | The venue stamps stop looking future-dated; the gate passes | No code, no bundle change, no app restart |
| Leave it, decide after the close | Today stands as an environmental no-fill; the question of whether the gate should tolerate a documented skew moves to the review | None today, but a second lost session if unaddressed |

Both remain the user's decision. Nothing has been changed.

## A finding handed to the Team2 desk

Their selection study recorded `room = unknown` on all four day-one observations, and they attributed it to underlying
quotes carrying no venue time at all (`sourceTs: 0` on a live IWM read). That is a field-selection issue, not missing
data, and it is worth recording here because it is the same trap EM avoided by accident:

- `source_ts` is the **option** NBBO venue time. For an **equity** the venue time is on `quote_ts`, with `last_ts` for the
  print. `technique/research_recorder.py` chooses between them by instrument, which is why EM's equity evidence above has
  a populated `quoteTs` from the same feed.
- The quotes API serializer exposes only `source` and `sourceTs`, so `GET /api/quotes?symbols=<equity>` reports an empty
  source and a zero venue time for every equity regardless of what the `Quote` object holds. Reproduced today on IWM.
- EM additionally synthesizes the source from the feed name when an equity quote has no source string but does have a
  `quote_ts` (`sourceBasis: engine_feed`), rather than discarding the quote.

A clock resync would not have changed any of their four observations. Different fault, same symptom - which was their
point, and it was a good one.
