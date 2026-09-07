# Options Cartel — method decisions and open questions

2026-09-06: research started. No calibrated thresholds, enabled trading, or
performance claims. Findings must cite SOURCES.md or an identified replay/run.

## Decisions

- D1: Own method namespace `options_cartel`; code target
  `backend/zargar/techniques/options_cartel/`; docs stay in this folder.
- D2: Treat the method as multi-day momentum swing trading. Do not clone Team2's
  intraday session rules or adopt another desk's knowledge/prompts.
- D3: Preserve source-version differences explicitly. Engineering defaults must
  be labeled as implementation choices, not attributed to Sean without evidence.
- D4: Source S06 establishes bearish puts and share selection when IV/ADR makes
  options unattractive. The method is not restricted to bullish calls or 0DTE.
- D5: Public ledger return percentages are not weighted realized returns; no
  scorecard, graduation gate or performance claim may treat them as such (S07 row 4).
- D7 (2026-09-06, engineering interpretation, not calibrated): the session-extreme
  initial stop freezes the regular-session low/high observed by confirmation time.
  It never uses the final daily candle's later extreme. Breakout-bar and preplanned
  stops remain explicit alternatives. Entry defaults to 15m closed-bar confirmation;
  5m/30m variants are explicit. Relative volume 1.5, directional close location 0.7,
  retest tolerance 0.25%, and never-chase 0.5 planned R are visible, snapshotted
  engineering values pending example/video research. No live activation is implied.
- D8: A retest requires a preceding volume-confirmed break, then a separate candle
  holding the level with confirmation volume/close quality. The initial kernel
  resets this observation each session and across missing-data buckets. Cross-day
  retest geometry must be explicitly supplied as a reviewed new plan until a
  source-validated persistent scenario rule is implemented.
- D8 clarification (S12 found 2026-09-06): an explicit `allow_gap_retest` policy
  allows an observed opening gap to provide context for a later completed retest
  candle. The gap itself is not an entry; volume, touch and chase checks remain.
  Legacy snapshots default false. Source gap path has two directional/causality
  tests. D8's ordinary intraday-break rule remains for plans without this option.

## Resolve before execution acceptance

D16 (2026-09-06, engineering selection policy): automatic routine selection
requires reviewed minimum/maximum/target DTE, target absolute delta, max ask and
max spread. These preferences are not claimed as Sean's universal numbers.
Search up to six expiries nearest target DTE and refresh up to the configured
candidate cap (12 by default). Rank eligible refreshed contracts by DTE distance,
delta distance, spread, then symbol. Report incomplete search coverage explicitly.
Manual lower-delta exceptions remain in preflight; automatic routine selection
keeps the >=0.25 floor. Selection is not submission permission and must be checked
again at the trigger after all slow operations.

D15 (2026-09-06, S15): routine option preflight uses absolute delta >=0.25 and
requires the correct call/put sign. A lower threshold requires an explicit
exception reason and is recorded in the preflight report; it does not bypass
quote, expiry, risk, account or Greeks-age checks. Delta observation must be
within 120 seconds (engineering limit). Field observation time is when the
provider returned that value, not an independently verified model-computation
timestamp. Merely refreshing bid/ask or another Greek never refreshes delta.

D14 (2026-09-06): expose the June scanner screenshot as `june_2026_image`
(ADR >2%, average volume over ten completed sessions >500K). Keep `june_2026`
as the earlier text-based prototype (ADR >3%, last-session liquidity-volume
interpretation). Do not silently rewrite saved plans or retrospectively choose
whichever variant performs better. September remains unchanged pending further
author clarification. Scanner-image selection does not invent a new exit schedule.

D12 (2026-09-06, execution sizing): Options preflight reserves the full premium
debit against the risk budget; no unsupported delta/stop-loss conversion is used.
Shares use planned trigger-to-invalidation distance for the risk estimate. Budget
and equity are in the portfolio's base currency; quote costs convert using a
current FX rate. Missing FX fails the preflight, never a 1:1 fallback. All numbers
must be recomputed after the final slow step at actual submission. This is an
explicit conservative implementation choice, not Sean's published sizing formula.

Preflight is not proof of a trigger, a connected execution venue, or a fill. It
must not serve as a reusable permission token. Manual/proposal live permission
is distinct from auto: both need Live workspace and acknowledgement; auto also
requires `techniques.options_cartel.allow_live_auto`. The latter defaults off.

D11 (2026-09-06, explicit exit execution interpretation): May and June profiles
preserve their stated quarter-position schedules. September requires five
reviewed fractions (first target, extension, daily 8/21/50 EMA); the first must
be 25%, all must sum to 100%, and the later fractions are labeled as the
reviewer's choice, not Sean's numbers. No hidden September allocation default.

Whole-lot allocation uses cumulative floor and gives the last EMA runner the
remainder. Zero-size trims do not generate an order or pretend a breakeven trim
filled. A one-contract position uses its final daily EMA exit or protective
stop. The first allocated target trim must fully fill before stop-to-entry.
This rounding convention is engineering, not a documented Sean small-lot rule.

Target/ATR exits use the caller's fresh observed underlying price; EMA exits
require the completed daily candle at its actual session-close boundary. Stops
and the platform expiry floor take precedence; pending exits suppress additional
requests, while protection asks the manager to cancel/replace rather than stack
orders. All fill accounting is incremental and idempotent. Final EMA liquidation
includes untriggered earlier allocations. These pure rules require an execution
adapter using the existing manager's reduce-only and pending-order accounting;
signals must never be passed off as filled sales.

- Q1: Entry confirmation 5m/15m (June) versus 15m/30m (September).
- Q2: Intraday breakout-bar stop (2024) versus daily breakout-candle low (June),
  including causal availability of that low at entry.
- Q3: 25% partial exits with 8/21 EMA tail (June), versus 3xATR extension and
  8/21/50 EMA portions (September); fractions, sequence, gaps and small lots.
- Q4: ADR/ATR lookbacks, tightness, base duration, volume comparison and leader ranking.
- Q5: Options DTE/strike/liquidity, earnings, gap exposure, sizing and risk reduction.
- Q6: Which statements apply to Sean's method versus another Cartel educator.

Research answers and deliberate engineering choices go here with dates and
evidence. Numerical variant sweeps must not overwrite source rules silently.

## Missed-close execution adaptation — 2026-09-07

This is platform recovery policy, not an additional Sean rule. A recovered daily
breach can become a current exit only when the checkpoint proves the supplied
campaign state predates the missed closes. Requirements do not simulate intervening
fills or a hypothetical first-trim breakeven move. Repeated same-rung decisions
are cumulative requirements; a protective breach supersedes profit requirements.

Persist batch identity and absolute remaining holdings before routing. Confirmed
fills advance the campaign through the existing manager; accepted/cancel-requested
orders do not. Fresh executable quotes are required at initial catch-up routing
and again after cancellation waits, within the regular session. Shares use the
shared market-exit convention; options retain its bid-limit/protective-market
convention. Historical closes are decision evidence, never execution prices.
The selected 15-second quote freshness threshold is an engineering gate.

## Ascending-triangle measurement — 2026-09-07

S18 names the setup; the numeric geometry below is an explicit engineering
interpretation. On the configured daily base window (default ten sessions), the
regression slope of highs must be approximately flat (absolute slope no more
than 0.10% of latest close per bar), lows must rise faster than that threshold,
and the latter half's range must be narrower. At least three highs must touch
within the existing 0.5% ceiling tolerance, with touches in both the first and
last thirds of the window. The ceiling is the maximum base high.

The candidate is bullish-only, retains all existing context/freshness/volume
gates, and requires reviewed targets. Its trigger/invalidation are the base
high/low; actual initial stop still follows the selected entry policy. It does
not silently replace generic base candidates or change already-saved plans.
Synthetic geometry/composition tests establish mechanics, not author calibration.
