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

## The Team2 exchange, and a correction I owe

Their selection study recorded `room = unknown` on all four day-one observations. They first attributed it to underlying
quotes carrying no venue time at all, from a live IWM read returning `source: ""` and `sourceTs: 0`. I answered that this
was a field-selection error, because equity venue time lives on `quote_ts` and `last_ts` while `source_ts` is the option
NBBO field, and the quotes API serializer exposes only the option fields so every equity reads as untimed through it.

Half of that was right and half was wrong, and the wrong half is mine. The serializer trap is real and they withdrew
their conclusion from it. But their helper was never reading the wrong field: `techniques/team2/runner.py` takes
`last_ts` first and falls back to `quote_ts or source_ts`, so the selection was already correct. My claim that their bug
was field choice does not survive reading their code, and this paragraph replaces it.

The true answer is one cause, not two. Their freshness guard is `t > 0 and 0 <= now - t <= max_age`; the stamps are
present, so it passes the first arm and fails the second on a future-dated venue time - the same rejection EM's gate
makes, written differently. Measured across all nine of today's records, on the same feed their IWM quote uses:

| | min | max |
|---|---:|---:|
| `lastTs` minus the record's host time | +5,078 ms | +9,974 ms |
| `quoteTs` minus the record's host time | +4,030 ms | +10,073 ms |

Every one is future by more than the 1,000 ms tolerance, so all nine fail on any reading. A resync therefore repairs both
desks' symptoms, and neither desk is loosening a freshness guard to tolerate a skewed clock next to money.

If the resync happens, the Team2 desk has asked for the landing time, so their study's monitoring notes can record which
of its sixty counted sessions were collected under the skew.
