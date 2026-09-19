# 7. Prospective selection study S1: frozen specification (order-free, default off)

Status: registration `s1-r3` (2026-09-19). r2 added the review team's four amendments; r3 is the correction pass after their review
of the first collector (quote evidence, lifecycle and capacity, point-in-time features, operational isolation) and freezes the
analysis implementation. The collector is BUILT, DEFAULT OFF and NOT collecting (`08-collector-package.md`). Any later change to a
definition below, or to the hash-pinned analysis file, is a new registration and restarts collection.

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
`ad4b02111a79494ffdc1b71c5ff04e68e88f6c20c611851269814bb79adcb772`, pinned by `tests/test_team2_selection_analysis.py`. While
collection runs, the only permitted view is `python -m zargar.tools.team2_selection_study` (counts and coverage, never an outcome);
`--final` is refused before the stop rule.

- Population: collapsed opportunities (one per identity), `c1Only` and excluded sessions set apart and counted; rows of an earlier
  registration are counted and never analysed.
- Test per feature: `d = mean(R30 | favoured bucket) - mean(R30 | rest)`, date-clustered bootstrap (10,000 resamples of whole
  sessions, fixed seed), two-sided p from the bootstrap.
- Multiple comparisons: Holm's step-down procedure across the judged features at a family level of 0.05. Secondary outcomes are never tested.
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

## Collection, stopping and exclusions (frozen)

- Start: the first full session after the package is accepted, the code is reviewed and the knob is set to `collect`. Sessions before
  that, and every historical session, are excluded.
- No interim look at outcomes by feature. Operational monitoring may look ONLY at counts and coverage.
- Stop: at the close of the 60th collected session, or on 2026-12-18, whichever comes first. No early stop for a favourable result.
  Early stop only if overall valid-outcome coverage is under 60% after 15 sessions (the instrument is broken: fix, re-register, restart).
- Excluded sessions, decided without looking at outcomes: a session with an engine restart between 09:30 and 15:45 ET, a feed
  outage recorded by `BarDeliveryHealth`, or an exchange early close. Excluded sessions are listed.
- Outcomes of the study: for each feature `pass`, `fail` or `insufficient evidence`; for the study `at least one pass` or `none`.
  `None` is a valid, reportable result and does not license a second round of features on the same data.

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
