# 11. Selection study `s1-r4` — monitoring log

Monitoring owner: the Team2 desk. Scope, per the acceptance: **counts, coverage and collector health
only**, until the frozen endpoint (the close of the 60th counted session, or of 2026-12-18).
Operational problems are recorded here and kept separate from method performance, which is not
judged before the endpoint. Nothing in this file changes the collector, the registration or the
analysis; it is the record of what the study was collected under.

---

## Which build collected which session

The registration hash covers the study's definition, not the runtime it collects on, so the build
moves underneath the study whenever any desk deploys. That does not affect registration integrity,
but a reader of the frozen analysis should be able to tell the sessions apart, so the builds are
recorded here as they change.

| from session | build | version | note |
|---|---|---|---|
| activation, 2026-09-19 | `fea5bb49` | 0.8.26 | the build the activation record was journaled against |
| session 1, 2026-09-21 | `7ee5ad2a` | 0.8.28 | another desk deployed on 2026-09-20; the whole of session 1 ran on this |

---

## Session 1 — 2026-09-21 (first counted session)

**Collector health:** nominal. State `collecting`, all health counters zero at activation.

**Coverage defect: the `room` feature is blind under a skewed host clock.**

All four of this session's observations recorded `room = unknown`, with
`actionableWhy = "no fresh price evidence (stale or untimed last and quote)"`. The cause is the host
clock, not the feed and not the collector.

The host clock is running about nine seconds **behind** real time and the Windows Time service is
stopped. Equity quotes from `HybridQuoteFeed` carry genuine venue timestamps, so those stamps arrive
looking **future-dated** relative to the host. The actionable-price helper
(`runner.py` `_actionable_underlying`, and the study's own copy) tests freshness as
`t > 0 and 0 <= now - t <= max_age`; the stamps are present, so it is the `0 <= now - t` arm that
rejects them.

Measured on 2026-09-21, from durable records rather than from the API:

| measurement | value |
|---|---|
| host clock vs true time, 5 NTP servers (4 stratum 1), agreeing within 38 ms | **−10.517 s** |
| host clock − database clock (superseded, see below) | −8.978 s |
| equity `evidence.lastTs` − the record's own host `ts`, 9 of 9 `TechniqueFirstSale` rows | +5,078 to +9,974 ms |
| equity `quoteTs` − the record's own host `ts`, same rows | +4,030 to +10,073 ms |

**Correction (same day, from the EM desk).** The host-to-database comparison above UNDERSTATES the
skew by about 1.4 s, because the database runs in WSL and is itself behind true time. Comparing two
drifting clocks measures their difference, not the error. The authoritative figure is the NTP one:
the host is **10.517 s behind true time**, round-trip uncertainty at most 62 ms. Windows `w32time`
is Stopped with start type Manual, so the drift returns after every reboot — a one-off correction
without changing the service start type would not hold. The direction and the conclusion are
unchanged; only the magnitude was wrong, and the larger figure makes the venue stamps look further
into the future, not less.

The same fault refused every EM first-sale entry this session with
`underlying.validated.problems = ["venue_time_in_future"]` (9 of 9). One cause, two desks.

**Effect on the study.** One of six features (`room`) has zero coverage for this session. The
analysis treats that as zero coverage rather than failing — it is counted in `unknownFeature` and in
the per-feature `coverage` map — so the remaining five features are unaffected and the session still
counts. Option quotes are unaffected: they carry `source: "opra"` with a real `source_ts`.

**Not repaired here, deliberately.** Loosening the freshness guard to tolerate a future-dated stamp
would paper over a real clock fault on a gate that sits next to money, and would leave the study
quietly measuring against a skewed clock for the rest of the window. The repair is to resync the host
clock, which is a system settings change and the user's decision. Nothing was changed.

**Boundary marking.** If and when the clock is resynced, the EM desk will supply the measured time it
takes effect (host against database and against a venue stamp). The session in which that lands is
recorded here as the boundary, so sessions collected under the skew can be told apart from sessions
collected after it when the frozen analysis is read.

### Watch-out for a reader of this log

`GET /api/quotes` is **not** evidence about the quote object the runner sees. Its serializer exposes
only `source` and `sourceTs`, which are the option NBBO fields, so it reports an empty source and a
zero timestamp for every equity regardless of what the object holds. An earlier reading of this
defect drew the wrong conclusion from exactly that, and was corrected against the durable records.
