# 7. Prospective selection study S1: frozen specification (order-free, default off)

Status: registration **`s1-r4`**, the FINAL pre-activation registration (2026-09-19). Registration hash `13b2bcc18bbbf5fa`,
analysis sha256 `4022fccf7e06d9102d0c3048e0951be35a7a34541fcb46574b04ff4ac9f1aa48`. The collector is BUILT, DEFAULT OFF and NOT collecting. Frozen at activation: from the activation row on, a
material change to any definition below, to the analysis file or to the lifecycle rules is a NEW registration; records of `s1-r4`
are kept and never mixed with another registration's (every row carries `study` and `registrationHash`; rows of any other
registration are counted and never analysed). History: r2 = the four review amendments; r3 = the collector corrections and the
first frozen analysis; r4 = this integration pass (below). The machine-readable record is `selection_study.REGISTRATION`
(`python -m zargar.tools.team2_selection_study registration`).

### What changed from r3 to r4 (decided before any observation exists)

- Holm family resolved: the family is ALL SIX primary tests, always. A feature that cannot be judged enters with p = 1, so dropping a
  feature never loosens the others (r3's text said "across the judged features"; r2's said "the six primary tests": r4 takes the
  stricter reading and freezes it).
- Secondary outcomes: `R10` and `R30` at one tick worse on each side, reported descriptively per bucket, never tested. The underlying's
  move at 30 minutes is dropped (it needed bars at analysis time and was never tested).
- Every record carries `registrationHash`; the opening hash includes it.
- Lifecycle, session accounting, endpoint, early stop and the frozen final sample are now specified exactly and implemented
  (`selection_study_lifecycle.py`), replacing r3's "Collection, stopping and exclusions" text.

## Question

Does any one of six entry properties, known at the decision and codeable, separate Team2 entries whose contract is worth more
after costs thirty minutes later from the rest? "The author's edge is selection" is the HYPOTHESIS this study probes. It is not an
established explanation: his published record contains no priced losing trade (see `06-author-comparison.md`).

## What runs, and what does not

- Order-free. No portfolio, no order, no proposal, no change to any entry, exit, sizing or refusal decision in any book.
- Default off: one new knob `techniques.team2.selection_study` = `off` | `collect` (default `off`), read by the shadow diagnostics only.
- It extends the existing shadow diagnostics (`TechniquePlanDiagnostic`). The present follow-ups are 2, 5 and 10 minutes and the
  exit; this study adds its own 10- and 30-minute observations of the ONE chosen contract and a feature block
  (`08-collector-package.md`), reviewed as one shadow-only package before any collection.

## The unit: one independent opportunity

- Identity (book-independent): `opportunityId = date|SYMBOL|setupId|signalTs`, where `signalTs` is the close time of the 2m contact
  bar. All four parts are market facts. **No per-book counter is used**: on 2026-09-18 C1's touch #1 was the 10:14 bar and Control's
  touch #1 was the 10:22 bar, which C1 called contact #3. Here 10:14 and 10:22 are two opportunities, and the 10:22 bar is ONE
  opportunity in every book that examined it.
- One observation per opportunity, and one capacity slot. The FIRST book to open an opportunity follows it. Any other book that
  examines the same opportunity journals an opening marked `duplicateOf` (the follower's run, book and `openHash`) with no schedule
  and no slot. The analysis takes the follower's record and lists every book that examined it. An opportunity only C1 examined is
  `c1Only`: set apart, counted, analysed only in a stated sensitivity.
- A contact counts whether the book took it, refused it after pricing, or shadow-quoted it after an allocation refusal, as long as
  the read reached the contract step. Contacts the read never priced are outside the study.
- A later revision of the same opportunity never opens a second record, whether the first is still open or already closed.
- Every record carries `openHash`, the hash of its immutable opening (identity, book, trigger, features, entry quote, recorded time,
  due times). A close counts only when it carries the follower's `openHash`; the first such close wins; later or foreign closes are
  counted as `ignoredCloses` and never merged. Features and the entry quote always come from the OPENING row.

## Features (captured SYNCHRONOUSLY when the signal is created, from bars that had closed by T; stored with the hash of the exact bar values; never recomputed)

ATR = the read's 14-period ATR on 2m bars at T. "Trade direction" = the setup's direction. A feature whose inputs are missing is
`unknown`; unknowns are reported per feature and excluded from that feature's test only. An opportunity whose features were not
captured at the signal has all six `unknown` ("not captured at the signal"): nothing is computed late, because a later correction
to an earlier bar would rewrite what was observable at T.

| id | Name | Exact definition | Favoured bucket (fixed now) | Unknown when |
|---|---|---|---|---|
| F-a | Flag into the line | Let B1..B4 be the four closed 2m bars immediately before the contact bar. `flag` = (max high - min low of B1..B4) <= 1.25 x ATR AND the six closed 2m bars before B1 moved at least 1.5 x ATR in the trade direction (close of the last minus open of the first, signed) | `flag` | fewer than 10 closed regular-session 2m bars before the contact bar, or ATR missing |
| F-b | Level origin | Origin of the setup's anchor level: `pm` (today's pre-market high/low), `prior` (previous session's zone). A level two or more sessions old can only exist with C2 key levels, which stay OFF: that bucket is NOT OBSERVABLE in this study and is not claimed | `prior` | anchor origin not recorded |
| F-c | Wait since confirmation | Minutes from the 15m close that confirmed the setup to T: `short` < 15, `medium` 15 to 60, `long` > 60 | `long` versus the other two together | no confirmation time |
| F-d | First fifteen minutes | T in [09:45, 10:00) ET versus later | `first15` | never |
| F-e | Scenario 4 | setup kind is `scenario_4` versus any other kind | `scenario_4` | never |
| F-f | Room to the target | abs(target - actionable underlying price) / ATR: `near` < 1.5, `mid` 1.5 to 3, `far` >= 3. Actionable price, read at the capture: the last print when its OWN `last_ts` is within `stale_seconds`, else the bid/ask midpoint when the quote is sane and its own `quote_ts`/`source_ts` is within the bound; zero and future times are no evidence. NEVER the picker's spot | `mid` versus the other two together | no target, no price with field-bound fresh evidence, or ATR missing |

F-a, F-b and F-c come from the author's words (flag, level, waiting). F-d, F-e and F-f are cells that looked positive in the
historical tables AFTER looking; the favoured bucket is fixed here so the prospective test is fair. None of the six was tuned on data.

## Outcomes

Timing, exactly (implemented in `selection_study.py`, pinned by `test_the_entry_quote_delay_...` and `test_an_observation_counts_only_...`):

| Symbol | Definition |
|---|---|
| `T_signal` | close time of the 2m contact bar (`entryLocation.signalTs`) |
| `t_q0` | the SOURCE timestamp of the chosen contract's entry quote (the provider's time for that bid and ask), bound together with the price when the contract was examined. Never a receipt time, never a collection time |
| entry-quote delay | `t_q0 - T_signal`. The entry quote is valid evidence only when `0 <= delay <= 90 s` AND it is quote evidence under the study's own rule below. Otherwise the opportunity has no outcome and the reason is recorded (`predates the signal`, `after the signal`, `not valid evidence`, `no contract chosen`) |
| horizon clocks | start at `t_q0`: `due_10 = t_q0 + 10 min`, `due_30 = t_q0 + 30 min`. Not at `T_signal`, so a slow quote does not shorten the holding period |
| observation validity | a PASSIVE read of the quote cache during `[due, due + 90 s]` (the option service refreshes every tracked contract about every five seconds; the collector requests nothing). The first read that is quote evidence with `due <= its SOURCE time <= due + 90 s` is the observation. If the window ends without one it is `unknown` with the last reason |
| `late` | `due_30` after 15:45 ET: no primary outcome, reported |

- PRIMARY: `R30 = (bid_30 - ask_0 - 2 x fee) / (ask_0 + fee)`, prices per share, `fee` = $1.04 / 100 per share per side, winsorised
  at +200% (frozen). `ask_0` is the entry quote's ask, `bid_30` the thirty-minute observation's bid.
- SECONDARY, descriptive only, no tests, no claims: `R10`; the same `R30` at one tick worse on each side; the underlying's signed
  move at thirty minutes in ATR (from bars, computed at analysis time). The first draft's "return at the read's own exit" is dropped:
  it exists only for entries a book took, which is a different population per book.
- Never a print, a delayed chain value, a midpoint, or an earlier quote carried forward.

Quote evidence, the study's OWN rule, applied identically to the entry quote and to every observation (`quote_evidence`):
bid > 0 and ask > 0, both finite, ask >= bid; the quote's own `source` is exactly `opra` (never inferred from another flag, never
synthesised); a positive source timestamp that is NOT after the moment the quote was collected, with no clock tolerance, and at most
30 s before it. The entry is re-validated from the bound fields of the chosen candidate row; the shared diagnostics' `priceKnown`
flag, which accepts ask-only rows and a five-second future tolerance, is not used.

## Implementation (built, default off; `08-collector-package.md`)

1. **Opened at the start.** `selection_study_open` is journaled when observation begins; `selection_study_close` once, when the
   record resolves. An opening with no accepted close is `incomplete` and stays in every coverage denominator.
2. **Passive.** No provider request, no forced refresh, no tracking change, no awaited call, no task. Observations are synchronous
   reads of the quote cache on the two-second quote watch.
3. **Capacity** = 12 UNIQUE opportunities across the desk; beyond it the observations are recorded `capacity`.
4. **Everything opened is closed**: resolved, `plan removed before the observation`, `collector switched off`, or `session ended`.
   Housekeeping runs while records remain even when the switch is off.
5. **Restart.** Pending records persist with the plan; after a restart they wait (at most 60 s) for a journal reconciliation that
   drops records whose close is already journaled. Overdue observations are recorded `unknown`, never quoted, never back-filled.
6. **Where it runs.** The capture runs at the signal; the opening runs inside `pick_contract`, before the later entry gates and the
   submission; both only read and return nothing. Isolation is shown by a real runner on/off comparison, not by a source search.
7. Depends on PR #224 for the `TechniquePlanDiagnostic` event contract; two `kind` values are added, no new event type.

## Analysis (frozen AND implemented before collection)

Implementation: `backend/zargar/techniques/team2/selection_study_analysis.py`, sha256
`4022fccf7e06d9102d0c3048e0951be35a7a34541fcb46574b04ff4ac9f1aa48`, part of the registration and pinned by `tests/test_team2_selection_analysis.py`. While
collection runs, the only permitted view is `python -m zargar.tools.team2_selection_study` (counts and coverage, never an outcome);
`final` is refused before the endpoint.

- Population: collapsed opportunities (one per identity), `c1Only` and excluded sessions set apart and counted; rows of an earlier
  registration are counted and never analysed.
- Test per feature: `d = mean(R30 | favoured bucket) - mean(R30 | rest)`, date-clustered bootstrap (10,000 resamples of whole
  sessions, fixed seed), two-sided p from the bootstrap.
- Multiple comparisons: Holm's step-down procedure across ALL SIX primary tests at a family level of 0.05; a feature that is not
  judgeable enters the family with p = 1. Secondary outcomes are never tested.
- A feature PASSES only if ALL hold: (i) Holm-adjusted p < 0.05; (ii) **the improvement is positive: `d > 0` and the lower end of its
  95% interval is above zero** (a favoured bucket that is significantly WORSE than the rest cannot pass, whatever its own mean);
  (iii) the favoured bucket's own mean R30 is above zero after costs; (iv) `d` stays positive with the three sessions most
  favourable to it removed.
- **Several passers: exactly one goes forward**: the smallest Holm-adjusted p; ties by the larger lower bound of `d`; remaining ties by
  the order F-a, F-b, F-c, F-d, F-e, F-f. No combination is formed.
- Judged at all only with: at least 60 valid outcomes on EACH side, from at least 20 sessions on each side, valid-outcome coverage of
  at least 80% on each side, and a coverage gap of at most 15 points between the sides. Otherwise `insufficient evidence`. 150
  observations in total is not sufficient by itself.
- Coverage per feature bucket keeps EVERYTHING in the denominator: valid, `late`, `capacity`, `incomplete`, and every unknown reason.
- Power, stated plainly: the thirty-minute return has a standard deviation near 75% before winsorising and clustering widens it.
  With 60 against 140 opportunities only differences of roughly 35 to 40 points can pass. A modest real effect will most likely end
  as `insufficient evidence`.

## Lifecycle, session accounting and the endpoint (frozen; `selection_study_lifecycle.py`)

The lifecycle is a PURE function of durable records, so it is the same before and after any restart and anyone can recompute it:
the activation row, `SettingChanged` rows for `techniques.team2.selection_study`, `TechniquePlanRestored` times of Team2 plans (an
engine restart restores every armed plan), SPY/QQQ/IWM regular-session 1m bars (provider alpaca), the NYSE calendar
(`market_calendar`, America/New_York), the study's own rows and `selection_study_final` rows.

States: `prepared` (no activation row of THIS registration) -> `collecting` -> `stopped_insufficient_coverage` or
`ready_for_final_analysis` -> `finalized` (a `selection_study_final` row of this registration exists).

Activation: `python -m zargar.tools.team2_selection_study activate --build <reviewed sha> --confirm <registrationHash>` journals ONE
activation row (study, registration hash, analysis hash, the full registration, build, activation time, first eligible session).
It does not switch anything on; the operator then sets the knob to `collect`.

Session status, decided without looking at any return (first rule that applies wins):

| Status | Rule | Advances the count | Its records in the sample |
|---|---|---|---|
| `disabled` | the collector was off for the whole regular session | no | no |
| `partial` | on for only part of the session, or the study was activated during it | no | no |
| `excluded` | on for the whole session, but a 13:00 early close; or an engine restart (a Team2 `TechniquePlanRestored`) between 09:30 and 15:45 ET; or a feed outage = three or more consecutive regular-session minutes without an alpaca 1m bar for SPY, QQQ or IWM | **no** | no |
| `counted` | everything else, INCLUDING a session with zero opportunities | yes | yes |
| `in_progress` / `not_started` | the session's close has not passed | not yet | not yet |
| `after_endpoint` | after the endpoint or the early stop | no | no |

(r3 named `BarDeliveryHealth` for outages; it has no objective outage field, so r4 defines the outage on the bars themselves.)

- First eligible session: the first trading day whose 09:30 ET is at or after the activation time.
- Endpoint: the CLOSE (16:00 ET) of the 60th counted session, or the close of the 2026-12-18 session, whichever comes first. A
  session counts only when its close has passed: an opening record on the 60th morning cannot unlock the analysis.
- Pending observations: every observation's window ends by 15:46:30 ET (the 30-minute clock cannot be due after 15:45), so at the
  16:00 endpoint everything is resolved or `unknown`; an opening that never got its close stays `incomplete`. An observation whose
  quote is after the endpoint is made invalid (`after endpoint`) in the final sample. Records with a signal at or after the endpoint,
  and records of non-counted sessions, are outside the sample and counted by reason.
- Early stop (coverage only): at the close of the 15th and every later counted session before the endpoint, if valid-outcome coverage
  of the primary population so far is under 60%, the state becomes `stopped_insufficient_coverage` and no final analysis runs (fix,
  re-register, restart). No early stop for any result. Stopping never touches a trading book, a rule or a setting: the operator
  switches the collector off.
- No interim look at outcomes by feature. The only view before the endpoint is `status`: lifecycle, session accounting, counts,
  coverage and collector health.

### The frozen final sample, journal-order precedence and the seal

Precedence is decided in JOURNAL ORDER (each row carries its `events.id` as `_eventId`), BEFORE anything is canonicalised for
hashing, and never by price or payload order:

- the OWNER of an opportunity is the first opening that is not a `duplicateOf`;
- its close is the FIRST close carrying the owner's `openHash`; an opportunity with no opening keeps its first close (a recovered
  opening, when the opening's journal write was lost);
- every opening stays in the sample (openings record which books examined the opportunity, hence `c1Only`); later or foreign closes
  are dropped and COUNTED in the diagnostics, so they can never change the sample or its hashes.

`final --out <dir>` is refused unless the state is `ready_for_final_analysis`. It builds the manifest from the selected evidence:
registration, analysis hash, activation, window `[activation, endpoint]` and its reason, the counted sessions, the FULL session
classification with the reason for every non-counted session (the eligibility decision, frozen here), the identity of every selected
record (`opportunityId`, `openHash`, opening and close event ids), the sha256 of the selected evidence, the registered fee and the
analysis parameters. The window, exclusions, costs and registration are NOT parameters. Counts about rows outside the window, closes
that were not selected, recovered openings and repeated openings are DIAGNOSTICS reported beside the manifest, never inside it, so
later arrivals cannot change its hash.

`final --record` journals ONE sealed row carrying the whole manifest and result with their hashes. **The first sealed row is
authoritative for ever**: afterwards `final` returns the sealed artifact (never a recomputation), `final --record` is refused, an
existing `final.json` with different content is never overwritten, and the sealed row's own integrity is checked (its embedded
manifest and result must hash to the recorded values). A recomputation from today's records is reported beside it as DRIFT
(`manifestWouldChange`, `resultWouldChange`, `sessionsReclassified`, records only in the seal or only in the recomputation), which is
how a later historical bar backfill, a late in-window duplicate or any other later arrival becomes visible without being applied.
`verify --out <dir>` HASHES the saved manifest and report and compares those computed hashes with the artifact's own declared
hashes, then with the seal, and separately with a recomputation. An edited or missing payload FAILS verification (exit 2), and so
does a payload that was edited and re-hashed to be self-consistent, because it is then no longer the sealed artifact. A file that is
absent or not JSON fails the same way. Later data drift on a VALID sealed artifact is not a failure: it is reported beside it and the
command still succeeds. Verification updates nothing.

Before the first seal, eligibility is recomputed from the current records on every call, so a bar backfill in that period can change
a session's classification. That is why the seal happens at the endpoint and freezes the classification with its reasons; after it,
no later data can redefine eligibility.

The lifecycle is a READ. When the study is stopped, ready or finalized while the collector is still on, `status` says so and the
OPERATOR switches `techniques.team2.selection_study` to `off`; the tool never changes a setting, and no trading book is ever paused.

## What a pass earns, and what it needs first

- A pass earns ONE subsequent Practice experiment, never an adoption: a new labelled sim book that takes only the favoured bucket
  of the passing feature, against a CONTROL WITH IDENTICAL SIZING AND PROTECTIONS (same `size_full`, premium budget, contract cap,
  loss caps, day-loss pause, breaker), changing only that filter. Judged on actual after-fee fills over a pre-set number of
  sessions with date-clustered uncertainty, in its own registration.
- The present experiment schema CANNOT express it, and this package does not extend it. `EXPERIMENT_ROLES` whitelists exactly two overrides: `sizing -> size_full` and
  `c1 -> no_trade_zone`. A selection filter needs a separately specified and reviewed extension: a third role (for example
  `selection -> entry_filter`), a pure read-side filter evaluated before the fire, its validation rule, the frozen-at-mint
  snapshot, per-book counters and transition checks equal to the existing roles. That is trading-path code and is NOT part of this
  study or this package.

## Not in scope

No change to Control, Sizing 0.5 or C1. No use of C2 key levels. No product pricing change. No deployment. No new variant family.
