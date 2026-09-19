# 7. Prospective selection study S1: frozen specification (order-free, default off)

Status: registration `s1-r2` (2026-09-19, after the review team's four amendments). The collector is BUILT, DEFAULT OFF and not
collecting (`08-collector-package.md`). Nothing is enabled. Turning it on needs a reviewed deployment and one setting change, neither
of which is part of this package. Any later change to a definition below is a new registration and restarts collection.
Amendments in r2: a book-independent opportunity identity; an explicit positive-improvement condition and a frozen rule for several
passing features; exact timing for the entry quote and the thirty-minute clock; records journaled when observation BEGINS.

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

- Identity (book-independent): `(session date, symbol, setup id, close time of the 2m contact bar)`, journaled as
  `opportunityId = date|SYMBOL|setupId|signalTs`. All four parts are market facts: the setup id is the setup's kind and the 15m bar
  that confirmed it, the contact bar is the bar the read fired on. **No per-book counter is used.** A book's contact number depends
  on what that book refused earlier: on 2026-09-18 C1's touch #1 was the 10:14 bar and Control's touch #1 was the 10:22 bar, which C1
  called contact #3. Under this identity 10:14 and 10:22 are two opportunities, and the 10:22 bar is ONE opportunity in every book
  that examined it (`test_identity_ignores_per_book_contact_numbers`).
- One observation per identity. Each book that examines an opportunity journals its own record; `collapse()` keeps ONE: Control's,
  else Sizing 0.5's, else C1's, and lists which books examined it. An opportunity that only C1 examined is flagged `c1Only` and is
  analysed only in a stated sensitivity, never in the primary test, because the conjunction zone admits a different population.
- A contact counts whether the book took it, refused it after pricing, or shadow-quoted it after an allocation refusal, as long as
  the read reached the contract step. Contacts the read never priced are outside the study and are counted from the decision ledger.
- A later revision of the same opportunity in the same book never opens a second record: the FIRST record stands.

## Features (all computed at the decision time T from bars that had CLOSED by T; never revised afterwards)

ATR = the read's 14-period ATR on 2m bars at T. "Trade direction" = the setup's direction. A feature whose inputs are missing is
`unknown`; unknowns are reported per feature and excluded from that feature's test only.

| id | Name | Exact definition | Favoured bucket (fixed now) | Unknown when |
|---|---|---|---|---|
| F-a | Flag into the line | Let B1..B4 be the four closed 2m bars immediately before the contact bar. `flag` = (max high - min low of B1..B4) <= 1.25 x ATR AND the six closed 2m bars before B1 moved at least 1.5 x ATR in the trade direction (close of the last minus open of the first, signed) | `flag` | fewer than 10 closed regular-session 2m bars before the contact bar, or ATR missing |
| F-b | Level origin | Origin of the setup's anchor level: `pm` (today's pre-market high/low), `prior` (previous session's zone). A level two or more sessions old can only exist with C2 key levels, which stay OFF: that bucket is NOT OBSERVABLE in this study and is not claimed | `prior` | anchor origin not recorded |
| F-c | Wait since confirmation | Minutes from the 15m close that confirmed the setup to T: `short` < 15, `medium` 15 to 60, `long` > 60 | `long` versus the other two together | no confirmation time |
| F-d | First fifteen minutes | T in [09:45, 10:00) ET versus later | `first15` | never |
| F-e | Scenario 4 | setup kind is `scenario_4` versus any other kind | `scenario_4` | never |
| F-f | Room to the target | abs(target - actionable underlying price at T) / ATR: `near` < 1.5, `mid` 1.5 to 3, `far` >= 3. Actionable price = the runner's fresh underlying price (last by its own print time, else midpoint by quote time) | `mid` versus the other two together | no target, no fresh underlying price, or ATR missing |

F-a, F-b and F-c come from the author's words (flag, level, waiting). F-d, F-e and F-f are cells that looked positive in the
historical tables AFTER looking; the favoured bucket is fixed here so the prospective test is fair. None of the six was tuned on data.

## Outcomes

Timing, exactly (implemented in `selection_study.py`, pinned by `test_the_entry_quote_delay_...` and `test_an_observation_counts_only_...`):

| Symbol | Definition |
|---|---|
| `T_signal` | close time of the 2m contact bar (`entryLocation.signalTs`) |
| `t_q0` | the SOURCE timestamp of the chosen contract's entry quote (the provider's time for that bid and ask), bound together with the price when the contract was examined. Never a receipt time, never a collection time |
| entry-quote delay | `t_q0 - T_signal`. The entry quote is valid evidence only when `0 <= delay <= 90 s` AND it passed `quote_check` when bound (live OPRA, bid and ask positive and not crossed, source time within 30 s of collection). Otherwise the opportunity has no outcome and the reason is recorded (`predates the signal`, `after the signal`, `not valid evidence`, `no contract chosen`) |
| horizon clocks | start at `t_q0`: `due_10 = t_q0 + 10 min`, `due_30 = t_q0 + 30 min`. Not at `T_signal`, so a slow quote does not shorten the holding period |
| observation validity | a NEW quote (the option service's forced refresh at the due time), valid only when it passes `quote_check` and `due <= its SOURCE time <= due + 90 s`. A quote older than its due time, a late one, a non-live one or a zero bid is `unknown` with its reason |
| `late` | `due_30` after 15:45 ET: no primary outcome, reported |

- PRIMARY: `R30 = (bid_30 - ask_0 - 2 x fee) / (ask_0 + fee)`, prices per share, `fee` = $1.04 / 100 per share per side, winsorised
  at +200% (frozen). `ask_0` is the entry quote's ask, `bid_30` the thirty-minute observation's bid.
- SECONDARY, descriptive only, no tests, no claims: `R10`; the same `R30` at one tick worse on each side; the underlying's signed
  move at thirty minutes in ATR (from bars, computed at analysis time). The first draft's "return at the read's own exit" is dropped:
  it exists only for entries a book took, which is a different population per book.
- Never a print, a delayed chain value, a midpoint, or an earlier quote carried forward.

## Implementation of the thirty-minute observation (built, shadow-only, default off)

Built in this package; details and acceptance tests in `08-collector-package.md`. Frozen behaviour:

1. **The record is journaled when observation BEGINS** (`TechniquePlanDiagnostic`, kind `selection_study_open`): identity, book,
   features with their inputs, the entry quote with its validity and delay, and the schedule. A second row
   (`selection_study_close`) is journaled when the last observation resolves. An opportunity whose follow-ups never finish
   (crash, disarm, plan removed, engine stopped) therefore still exists in the journal as an OPEN record with no close, and the
   analysis counts it as `incomplete` in the coverage denominator. Nothing can disappear by never being written.
2. Observations use the option service's forced refresh for the ONE chosen contract at the due time; no standing subscription is
   added. At most 12 opportunities are followed at once across the desk; beyond that the observations are recorded `capacity`.
3. Pending observations are persisted with the plan (`state_extras.selectionStudy`). After a restart an observation more than 90 s
   past due is recorded `late: not taken within the window (restart or stall)` and is NOT quoted; nothing is back-filled.
4. The event contract for `TechniquePlanDiagnostic` is PR #224 (open). The collector adds two `kind` values, no new event type.

## Analysis (frozen)

- Population: collapsed opportunities (one per identity), `c1Only` excluded, sessions excluded only by the rules below.
- Test per feature: `d = mean(R30 | favoured bucket) - mean(R30 | rest)`, with a date-clustered bootstrap (10,000 resamples of whole
  sessions). Two-sided p from the bootstrap.
- Multiple comparisons: Holm's step-down procedure across the six primary tests at a family level of 0.05. Secondary outcomes are
  never tested.
- A feature PASSES only if ALL of these hold:
  (i) its Holm-adjusted p < 0.05;
  (ii) **the improvement is positive: `d > 0`, and the lower end of its date-clustered 95% interval is above zero.** A favoured
  bucket that is significantly WORSE than the rest cannot pass, whatever its own mean;
  (iii) the favoured bucket's own mean R30 is above zero after costs;
  (iv) `d` keeps its sign with the three sessions most favourable to it removed.
- **Several passing features: exactly one goes forward**, chosen by this frozen order: the smallest Holm-adjusted p; ties broken by
  the larger lower bound of `d`'s interval; remaining ties by the feature order F-a, F-b, F-c, F-d, F-e, F-f. No combination of
  features is formed and no second feature is carried to a trading experiment from this study.
- Minimum sample for a feature to be judged at all: at least 60 collapsed opportunities with a valid R30 on EACH side of its
  comparison, from at least 20 distinct sessions on each side, AND valid-outcome coverage of at least 80% on each side. 150
  observations in total is NOT sufficient by itself. A feature that misses any of these is `insufficient evidence`.
- Coverage is reported per feature bucket with EVERYTHING in the denominator: opportunities opened, valid, `late`, `capacity`,
  `incomplete`, and each unknown reason (`coverage()`). A feature whose two sides differ in coverage by more than 15 points is
  `insufficient evidence` (the missing outcomes could carry the effect).
- What the study can and cannot detect: the thirty-minute return has a standard deviation near 75% before winsorising, and
  clustering widens it. With 60 against 140 opportunities the standard error of a difference is about 11 points or more, so only
  differences of roughly 35 to 40 points can pass after the Holm correction. A real but modest effect (10 to 15 points) will most
  likely end as `insufficient evidence`. That is a property of 0DTE returns, not something to tune away.

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
