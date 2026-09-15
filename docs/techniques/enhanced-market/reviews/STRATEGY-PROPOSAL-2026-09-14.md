# EM strategy proposal: source setups and exits (2026-09-14 evidence; revised 2026-09-15 for SP-01..03)

Research only. Nothing here changes trading behaviour; candidates stay order-free, risk limits stay as they
are, the baseline EM Practice book keeps trading and being prepared exactly as before. Evidence: the EM
Practice ledger (`executions` joined to `orders`, book `045d8c35…`), the armed-plan states, the saved plan
levels, exchange-tagged 1-minute underlying bars, and the stored 1-minute option bars. **Option bars are
prints, never executable bids**; every option figure that is not a recorded fill is illustrative. Underlying
R figures are diagnostics of a scenario, not option P&L. **The September 14 tables are a retrospective case
study**: the definitions below are frozen for NEW sessions; they were not frozen before this session's
outcomes were inspected, so nothing in them is an as-of result for September 14.

Baseline for both comparisons: the five completed positions, net of recorded commissions.

| position | entry | exit(s) | net | recorded mechanism |
|---|---|---|---:|---|
| Sep 10 HOOD 2× Sep 11 $114 put | 09:47 @1.73 | 10:01 @1.399 | −70.36 | underlying quote stop; no target reached |
| Sep 14 HPQ 100 sh | 09:31 @34.77 | 09:37 30 @34.803; 09:51 70 @34.6531 | −7.19 | TP1 trim submitted after the bar closed, then quote stop |
| Sep 14 HOOD 1× Sep 18 $115 put | 09:35 @3.45 | 09:38 @3.90 | +42.92 | full exit at TP2 |
| Sep 14 INTC 2× Sep 14 $96 call | 09:33 @1.00 | 11:42 @2.15 | +225.84 | full exit at TP2 |
| Sep 14 MSFT 1× Sep 18 $507.5 put | 12:50 @5.45 | 15:56 @6.50 | +102.92 | session flatten (15:55 trigger); no target reached |

## 1. Source setups versus our plans (Sep 14: MSFT, META, AAPL, MRNA)

| name | author (before the open) | our linked plan | what the tape did (RTH, 1m exchange bars) | verdict |
|---|---|---|---|---|
| MSFT | long over **498.97** toward **505+** (caption 09:20:51); no stop, no confirmation, no contract | short rejection at 509.56 (stop 514.751), built Sep 13 | 09:30 high 499.10 but close 498.03; first completed close above 498.97 at **09:48** (499.99); post-break minimum 498.39 with 12 minutes at/under the level before 505; first 505 touch **11:36**; session high 509.93 | **representation mismatch** (long idea covered by a short plan); an underlying trigger-to-target sequence exists |
| META | long reclaim/break of the double top after a liquidity grab, hold required; no number | short rejection 663.7467, gap-voided | open 657.83, high 668.60, low 649.22 | direction mismatch; **unscorable** without a numeric level |
| AAPL | long over **336.22** (caption) | long breakout at 336.22, armed 09:15 (our stop 330.5688, our targets) | high **335.50** | correct no-trigger; the plan matched the source level |
| MRNA | long over **149.73**, swing horizon possible | breakout 148.5613 rejected (0.26R) | high **147.34** | correct no-trigger; different geometry did not matter today |

Two of four were no-trigger controls; one had no geometry; one (MSFT) is the case to define.

### The source-candidate definition (one, frozen for new sessions; version `source-continuation-v1`)

Author-supplied fields are marked **A**; everything else is **ours** because the author omitted it.

| field | value | who |
|---|---|---|
| direction, level, target | long over the stated level toward the stated target (Sep 14: 498.97 → 505.00); full exit at the target for one or two contracts | A (direction/level/target) / ours (full-exit rule) |
| earliest eligible observation | the first completed 1-minute bar **after the opening range is complete** (09:35 close known at 09:36): crosses before that are recorded as `early_cross` and neither enter nor invalidate anything | ours |
| entry confirmation | the first completed 1-minute close above the level at or after the earliest eligible observation; the order is placed at the next minute's open, marked `next-open-proxy` (a genuine immediate entry needs an executable quote at the confirming close and is a separate row) | ours |
| no-chase | at the **executable entry price**, not the confirming close: refuse when the next-minute open (or the ask, live) is above level × 1.005; the candidate then enters `retest` state: the first completed close back above the level after a low within level + 0.10 re-arms it once; the row expires at 15:55 (the baseline flatten clock, `flattenMinutesBeforeClose=5`) or at 11:30 ET if never confirmed (R6 prime windows) | ours |
| stop | the **opening-range low** (low of the first five completed minutes, 09:30–09:34), invalidation on a 1-minute close below; recorded and never moved | ours |
| expiry | same session; the baseline flatten clock (15:55 trigger; a 15:45 cut would be a separate candidate change, not the baseline) | ours |
| contract | just-OTM call, ≤ 10% spread on the live NBBO, current-week or next-week expiry, quantity by the existing risk budget; unscorable when no live NBBO exists | ours (existing EM policy) |
| gates that still apply | R2 (3R to the target with this stop), the option liquidity screen, the daily loss budget, the final-dispatch guard — all unchanged; a candidate that fails a gate is recorded as `gated`, never traded | ours (existing) |
| risk limits | unchanged; the row is order-free and consumes no cash, budget or plan slot | — |

Retrospective Sep 14 walk of that definition (for illustration, not as-of):

| entry definition | entry (next-open proxy) | stop rule A: opening-range low 495.34 (known 09:36) | stop rule B: the level itself (close below) |
|---|---|---|---|
| (1) first touch before the opening range is complete (09:31) | 498.13 | **stop unavailable at 09:31** — not an eligible entry under this definition (`early_cross`); no R claimed | invalid: the proxy entry is below the level |
| **(2) first completed close above, at/after 09:36** (09:48 → 09:49 open) | 499.96 | target 11:36, +1.09R; **fails the 3R gate** → recorded `gated` | stopped 10:26 @498.79, −1.18R |
| (3) break + retest (retest 09:50 low 498.87 → 09:52 open) | 499.53 | target 11:36, +1.31R; fails the 3R gate | stopped 10:26, −1.32R |

Reading: the chosen candidate (2) reaches the author's target but earns 1.1R against our stop and fails EM's
own 3R gate, so it is a measurement row, not a trade the current rulebook would take. Rows (1) and (3) are
alternatives, not results: (1) has no as-of stop; nothing here generalises to "never use the level" — the
level-stop rows are one session's paths. What the case does justify: representing the source direction and
level as their own **order-free** row so the daily ledger can count how often the author's continuation
triggers, confirms, is gated, reaches its target or is stopped under the frozen definition, across new
sessions, with unknowns kept as unknown (no bars, no NBBO, no numeric level → `unknown`, never zero).

Option leg on Sep 14: no just-OTM 500 call bars are stored; the nearest stored contract (Sep 21 $505 call)
has only sampled prints. **Unscorable as an option trade.**

## 2. Exits with entries, contracts and quantities held fixed

### 2a. Faster execution at unchanged targets (the HPQ question)

Two different mechanisms, kept apart:

- **Resting share limit at the target** (an arithmetic illustration only): with 30 HPQ shares assumed
  filled at exactly 35.1462 on the 09:36 touch (bar high 35.19) and the 70-share remainder unchanged, the
  net would be −$7.19 + 30 × (35.1462 − 34.803) = **+$3.10 under that assumed fill**. The minute high does
  not establish a bid, posted size, queue position or a fill at a valid price increment. This is not a
  demonstrated outcome and not the proposed mechanism.
- **Fresh-observation target detection** (the proposed shadow variant): the same targets evaluated on the
  first qualifying fresh underlying observation after entry (the ~2 s quote watch), with the same-contract
  NBBO recorded at that observation. A 2 s watcher can miss a brief touch or see it after the bid moved, so
  the benefit is **unmeasured** — HPQ is one clear completed-bar delay case (touch 09:36 intrabar, trim
  submitted 09:37:00, filled 34.803); the alternative execution result is unverified.

| position | target event | actual action | fresh-observation result |
|---|---|---|---|
| HPQ | TP1 35.1462 touched intrabar 09:36 (close 34.87) | trim submitted 09:37:00, filled 34.803 | **unknown** (no contemporaneous bid/size stored; the delay is the observed fact) |
| HOOD Sep 14 | TP2 113.0225 touched intrabar 09:37 | exit filled 09:38 @3.90 | **unknown, sign included** (exchange prints 09:37 4.42–4.57 are not bids) |
| INTC | TP2 98.1708 touched intrabar 11:41 | exit filled 11:42 @2.15 | **unknown, sign included** (print 11:41 2.30 is not a bid) |
| HOOD Sep 10 | no target reached (TP1 6.46R away) | quote stop | not applicable (no target event) |
| MSFT | no target reached (low 504.70 vs TP1 502.81) | flatten | not applicable (no target event) |

### The shadow exit-observation definition (frozen; version `shadow-exit-v1`)

Order-free, alongside unchanged baseline execution: no second order owner, no duplicate exits, no cash or
budget consumed, no plan amended.

| item | rule |
|---|---|
| scope | every actual EM Practice admission (any vehicle) from the first session after activation of the observer; shares and options summarised separately |
| identity | copied from the live trade at fill: instrument, entry fill and time, quantity, direction, plan revision, targets, stop, flatten policy; experiment version `shadow-exit-v1` |
| control | the production policy and its recorded fills are the accounting baseline; the control's own first eligible observation of each rung (the completed-bar evaluation) is recorded when it occurs |
| variant trigger | the first fresh underlying observation (`Quote.last`, else mid; sources: the feed's real-time stream, never a chain row; max age 10 s by the source timestamp; one observation per source timestamp — a repeated print is not a new observation) at or beyond the **next production rung for the actual remaining quantity** (quantity-aware: for fewer than three contracts the full-exit rung, else the next ladder rung); one shadow record per trade per rung |
| precedence | the stop is evaluated first on the same observation; if the quote-stop breach fires on that observation the record says so and the shadow is `stop_first`; a target observation while an exit is already pending is recorded as `pending_exit` |
| observation record | source and received timestamps and the observation id of the underlying quote; underlying decision price; same-contract NBBO bid/ask/sizes, source, source timestamp and age; remaining quantity and pending exits; policy version; reason. Recorded at the observation, never back-dated; missing or stale contract quotes are recorded as `unscorable` and the next eligible observation is recorded separately (never credited at the earlier target price) |
| modeled proceeds | for a sell-to-close, the contemporaneous **bid** is a modeled liquidation opportunity, not a fill: covered quantity = min(remaining, displayed bid size), the rest `unresolved`; a fixed latency convention of 2 s and one tick of slippage; the contract multiplier and the recorded commission schedule apply; shares use the bid likewise |
| terminal | each shadow row is followed to its own terminal event (target observation, stop, flatten) or the session cap even if the live position closed earlier |
| output | one timeline per admission plus paired detection delay (control vs variant observation time), quote coverage, modeled net difference where scorable, worst loss, bid-based favourable movement and giveback, holding time, coverage exclusions; counts and missing data beside every aggregate; a first diagnostic read after ten sessions, which is not permission to activate anything |

### 2b. A predefined earlier-profit / structural exit (the HOOD Sep 10 question) — deferred, defined

Policy P as first written was inconsistent (it replaced TP1 with a level that could be farther away and then
kept TP1 when it was closer). The consistent definition, recorded for a later comparison and **not evaluated
here**: **earlier-only** — the first opposing saved plan level at least 1R from entry in the profit direction
replaces the next production rung only when it is nearer than that rung; otherwise the baseline rung stands.
Quantities: one contract exits fully at the replacement; two contracts trim one at the replacement and keep
the baseline full-exit rung for the second; three or more follow the ladder with the replacement as rung one.
Stop and time cap unchanged. Levels come from the saved plan only (no contemporaneous critic levels unless a
provenance rule admits them first).

What the five positions say about P, with unknowns kept:

| position | nearest saved level ≥ 1R (earlier-only) | effect |
|---|---|---|
| HOOD Sep 10 | none between 115.09 and 105.79 (the plan saved no intermediate level) | **untestable** for this saved-level rule; this is a limitation of the candidate, not evidence that structural exits cannot help (the critic's 114.51/114.02 would need their own provenance rule before inclusion) |
| HPQ | 35.4983 is farther than TP1 → baseline rung stands | no change |
| HOOD Sep 14 | 114.9121 (2.5R), touched in the **entry minute** (fill 09:35:21) | **unscorable**: minute OHLC cannot order the touch against the fill, and the next-minute print is not a bid |
| INTC | 99.34 is farther than TP1 → baseline rung stands | no change |
| MSFT | 501.61 (1.5R), never reached | no change |

### Target distance: a diagnostic, not a gate

Record, for every fire and every fill, the distance in R to the quantity-dependent full-exit rung: the
denominator (entry − stop), the entry basis (intended vs final fill), the rung, the vehicle, the final
quantity, the session, the source availability and the policy/sweep version. It changes nothing: no arm is
rejected, no target or size is altered, the minimum-R gate is untouched. A threshold (N) may be proposed later
only with frozen calibration dates, an untouched chronological validation window, a stated selection metric,
every eligible setup including non-fills and rejections, and the trades removed, losses avoided and gains
sacrificed — and frequency reported as an outcome, since a distance gate could further reduce already scarce
entries. Underlying-only sweeps measure geometry, not option profitability.

### Missing data (both comparisons)

- No historical option **bid/ask** path for any contract; only prints. Every option "would have" figure is
  illustrative and every hypothetical exit result is **unknown, including its sign**.
- No stored just-OTM MSFT call bars for the continuation candidate.
- The Sep 10 HOOD plan has no saved intermediate levels; policy P is untestable there.
- Five positions are a case study. Neither comparison is a promotion; both define what the forward cohort
  records.

## What proceeds now (order-free, baseline unchanged)

1. **Source-candidate rows** under `source-continuation-v1`: the desk records each morning's numeric author
   ideas (symbol, direction, level, target, source note, availability bound) and the evaluator scores the
   frozen definition on the day's bars with `unknown` retained; Sep 14 MSFT is the retrospective first row.
2. **Shadow exit observations** under `shadow-exit-v1`: journaled `TechniqueExitShadow` records from the
   existing quote watch, one per trade per rung, no orders.
3. **Target-distance diagnostic**: journaled `TechniqueTargetDistance` at fire and at fill; no gate.
4. Baseline EM Practice review-and-arm continues unchanged; no candidate from 1–3 is armed or traded.

## Measurement implementation notes (FM-01..05, 2026-09-15)

- **Protection first (FM-01).** The quote watch performs a pure CAPTURE of the observation and hands it to a
  bounded background recorder; no research I/O is awaited ahead of the premium stop or the quote stop. A
  saturated or failing recorder drops records visibly (counted, logged) and never delays protection. The
  observer is OFF for every desk (`execution.shadow_exit_observe=false`) and OFF for EM
  (`techniques.enhanced_market.shadow_exit_observe=false`) until the reviewers activate it; when on, it applies
  to the technique's default (Practice) book only.
- **Production quantities and policy (FM-02).** The next rung is decided as `plan_exit` decides it: the small-
  position rule on the ORIGINAL filled quantity, the ladder from `trims_done`; the proposed exit quantity is the
  production trim (ladder share × original filled, capped by the uncommitted remainder; the whole remainder for a
  small position or the last rung). Original, remaining, pending and proposed quantities are recorded separately.
  The target-distance diagnostic reports the intended underlying geometry, the option premium of the fill, the
  next rung and the full-exit rung separately; an observed underlying entry is never inferred.
- **Evidence (FM-03).** Coverage requires provenance, a source timestamp within 10 s, a finite uncrossed
  two-sided book and a KNOWN displayed size; unknown depth is unresolved, never covered. Stop precedence includes
  the premium-stop predicate on the same observation; stop-first and pending-exit rows are not scored.
- **Scope (FM-04).** This release is **raw observation capture only**: one durable record per trade instance
  (entry order) per rung, marked seen only after the write succeeded, retried with the original timing, dropped
  visibly after three failures. There is no shadow remainder or terminal tracker yet; P&L comparison is deferred
  to a separately defined reducer, and the latency/slippage constants are metadata for that reducer, not a fill
  simulation. Terminal-event evidence is unknown until that reducer exists.
- **Source timing (FM-05).** The evaluator is eligible only after both the opening range is complete and the
  source was available (timezone-aware; missing availability = unknown); bars must belong to the New York
  session date, be unique and ordered; the opening range needs all five minutes; the next-open proxy needs the
  immediately following minute; a missing minute inside the path is an unresolved interval = unknown. Per-gate
  fields report only R2 as evaluated; option liquidity, budget, contract selection and final dispatch are
  `not_evaluated` - a `target` path is not an admitted option trade.

