# 7. Prospective selection study S1: frozen specification (order-free, default off)

Status: SPECIFICATION ONLY. Nothing here is built, enabled or collecting. It replaces `06-prospective-experiment-spec.md` (kept
for history). It becomes a registration when it is accepted and committed BEFORE the collection switch is turned on; any later
change to a definition below is a new registration and restarts collection.

## Question

Does any one of six entry properties, known at the decision and codeable, separate Team2 entries whose contract is worth more
after costs thirty minutes later from the rest? "The author's edge is selection" is the HYPOTHESIS this study probes. It is not an
established explanation: his published record contains no priced losing trade (see `06-author-comparison.md`).

## What runs, and what does not

- Order-free. No portfolio, no order, no proposal, no change to any entry, exit, sizing or refusal decision in any book.
- Default off: one new knob `techniques.team2.selection_study` = `off` | `collect` (default `off`), read by the shadow diagnostics only.
- It extends the existing shadow diagnostics (`TechniquePlanDiagnostic`). The present follow-ups are 2, 5 and 10 minutes and the
  exit; this study ADDS a 30-minute observation and a feature block. Both are new code (section "Implementation"), reviewed as one
  shadow-only package before any collection.

## The unit: one independent opportunity

- Identity: `(session date, symbol, setup id, contact number)`, where the contact number is the read's own count of pullback
  contacts for that setup (the `#N` of the trigger id). It is the same in every book, every plan revision and every restart.
- One observation per identity. Source order: Control's record; if Control did not examine the contact, Sizing 0.5's; else C1's
  (the conjunction zone admits contacts the others do not: those are kept and FLAGGED `c1Only`, and are analysed only in a
  stated sensitivity, never in the primary test, because they are a different population).
- A contact counts whether the book took it, refused it (occupancy, loss cap, no-trade zone, target rules) or shadowed it, as long
  as the read reached the contract-selection step and a contract was chosen. Contacts the read never priced are counted and reported,
  not analysed.
- Revisions of one decision record (the ledger already versions them) collapse to the FIRST version that carries a valid entry quote.

## Features (all computed at the decision time T from bars that had CLOSED by T; never revised afterwards)

ATR = the read's 14-period ATR on 2m bars at T. "Trade direction" = the setup's direction. A feature whose inputs are missing is
`unknown`; unknowns are reported per feature and excluded from that feature's test only.

| id | Name | Exact definition | Favoured bucket (fixed now) | Unknown when |
|---|---|---|---|---|
| F-a | Flag into the line | Let B1..B4 be the four closed 2m bars immediately before the contact bar. `flag` = (max high - min low of B1..B4) <= 1.25 x ATR AND the six closed 2m bars before B1 moved at least 1.5 x ATR in the trade direction (close of the last minus open of the first, signed) | `flag` | fewer than 11 closed 2m bars in the session, or ATR missing |
| F-b | Level origin | Origin of the setup's anchor level: `pm` (today's pre-market high/low), `prior` (previous session's zone). A level two or more sessions old can only exist with C2 key levels, which stay OFF: that bucket is NOT OBSERVABLE in this study and is not claimed | `prior` | anchor origin not recorded |
| F-c | Wait since confirmation | Minutes from the 15m close that confirmed the setup to T: `short` < 15, `medium` 15 to 60, `long` > 60 | `long` versus the other two together | no confirmation time |
| F-d | First fifteen minutes | T in [09:45, 10:00) ET versus later | `first15` | never |
| F-e | Scenario 4 | setup kind is `scenario_4` versus any other kind | `scenario_4` | never |
| F-f | Room to the target | abs(target - actionable underlying price at T) / ATR: `near` < 1.5, `mid` 1.5 to 3, `far` >= 3. Actionable price = the runner's fresh underlying price (last by its own print time, else midpoint by quote time) | `mid` versus the other two together | no target, no fresh underlying price, or ATR missing |

F-a, F-b and F-c come from the author's words (flag, level, waiting). F-d, F-e and F-f are cells that looked positive in the
historical tables AFTER looking; the favoured bucket is fixed here so the prospective test is fair. None of the six was tuned on data.

## Outcomes

- PRIMARY: after-cost quoted return of the chosen contract over thirty minutes,
  `R30 = (bid_30 - ask_0 - 2 x fee) / (ask_0 + fee)`, prices per share, `fee` = $1.04 / 100 per share per side.
  `ask_0` = the ask of the contract the live picker chose, from the entry quote bound at examination. `bid_30` = the bid observed at T + 30 min.
  Winsorised at +200% (frozen) to limit the weight of single contracts. If T + 30 min is after 15:45 ET the opportunity has no
  primary outcome (`late`) and is reported, not analysed.
- SECONDARY, descriptive only, no tests, no claims: R at 10 minutes; R at the read's own exit where the read opened a model
  position; the underlying's signed move at 30 minutes in ATR; the same R30 at one tick worse on each side.
- Quote validity (both ends): live OPRA source, bid and ask positive and not crossed, the quote's OWN source timestamp within 30 s of
  the observation and not in the future (the existing `quote_check`). A failed check is `unknown` with its reason. Never a print,
  a delayed chain value, a midpoint or a carried earlier quote.

## Implementation of the thirty-minute observation (to be built, shadow-only)

1. When an opportunity is recorded with a valid entry quote, schedule observations at T + 10 min and T + 30 min for the CHOSEN
   contract only (the present diagnostics follow up to six candidates for 10 minutes; the 30-minute leg follows one).
2. The contract stays subscribed on the quote feed until its last due observation. Hard cap: 12 contracts followed at once across
   the desk; an opportunity that would exceed it is recorded `unknown: capacity`. No subscription is added for any other purpose.
3. The observation is taken by the existing two-second quote watch when `now >= due`. It is valid only if taken within 90 s of due
   (the present `MAX_LATE_MS`) and the quote passes `quote_check`; otherwise `unknown: late` or the check's reason.
4. Pending observations live in the plan's persisted `state_extras`. After a restart an observation more than 90 s overdue is
   `unknown: restart`; nothing is back-filled.
5. One journal row per opportunity (`TechniquePlanDiagnostic`, kind `selection_study`), written when the last observation resolves:
   identity, features with their inputs, entry quote, each observation with due time, taken time, quote, source time and validity.
   The event contract entry is added in the same change.
6. Tests required before collection: feature purity (no bar after T is read), identity across books and revisions, the capacity cap,
   late and restart handling, the contract entry, and a proof that every book's decisions and orders are byte-identical with the
   knob on and off on a recorded session.

## Analysis (frozen)

- Test per feature: difference in mean winsorised R30 between the favoured bucket and the rest, with a date-clustered bootstrap
  (10,000 resamples of whole sessions; all opportunities of a resampled session enter together). Two-sided p from the bootstrap.
- Multiple comparisons: Holm's step-down procedure across the six primary tests at a family level of 0.05. Secondary outcomes are
  never tested.
- A feature PASSES only if (i) its Holm-adjusted p < 0.05, (ii) the favoured bucket's own mean R30 is above zero, and (iii) the
  result keeps its sign with the three most favourable sessions for that bucket removed.
- Minimum sample for a feature to be judged at all: at least 60 opportunities with a valid R30 in EACH side of its comparison,
  from at least 20 distinct sessions on each side, AND valid-outcome coverage of at least 80% on each side. 150 observations in
  total is NOT sufficient by itself: a feature that misses any of these is reported `insufficient evidence`.
- Coverage is reported per feature bucket: opportunities, `late`, `unknown` by reason, valid. A feature whose two sides differ in
  coverage by more than 15 points is `insufficient evidence` (the missing outcomes could carry the effect).
- What the study can and cannot detect (from the historical replay the 30-minute return has a standard deviation near 75% before
  winsorising): with 60 against 140 opportunities the standard error of a difference is about 11 points, so only differences of
  roughly 35 to 40 points can pass after the Holm correction. A real but modest effect (10 to 15 points) will most likely end as
  `insufficient evidence`. That is an honest property of 0DTE returns, not a defect to be tuned away.

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
- The present experiment schema CANNOT express it. `EXPERIMENT_ROLES` whitelists exactly two overrides: `sizing -> size_full` and
  `c1 -> no_trade_zone`. A selection filter needs a separately specified and reviewed extension: a third role (for example
  `selection -> entry_filter`), a pure read-side filter evaluated before the fire, its validation rule, the frozen-at-mint
  snapshot, per-book counters and transition checks equal to the existing roles. That is trading-path code and is NOT part of this
  study or this package.

## Not in scope

No change to Control, Sizing 0.5 or C1. No use of C2 key levels. No product pricing change. No deployment. No new variant family.
