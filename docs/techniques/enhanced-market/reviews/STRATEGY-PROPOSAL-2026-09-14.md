# EM strategy proposal: source setups and exits (2026-09-14 evidence)

Research only. Nothing here changes trading behaviour; candidates stay order-free, risk limits stay as they are.
Evidence: the EM Practice ledger (`executions` joined to `orders`, book `045d8c35…`), the armed-plan states, the
saved plan levels, exchange-tagged 1-minute underlying bars, and the stored 1-minute option bars. **Option bars are
prints, never executable bids**; every option figure below that is not a recorded fill is labelled illustrative.
Underlying R figures are diagnostics of the scenario, not option P&L.

Baseline for both comparisons: the five completed positions, net of recorded commissions.

| position | entry | exit(s) | net | recorded mechanism |
|---|---|---|---:|---|
| Sep 10 HOOD 2× Sep 11 $114 put | 09:47 @1.73 | 10:01 @1.399 | −70.36 | underlying quote stop; no target reached |
| Sep 14 HPQ 100 sh | 09:31 @34.77 | 09:37 30 @34.803; 09:51 70 @34.6531 | −7.19 | TP1 trim after the bar closed, then quote stop |
| Sep 14 HOOD 1× Sep 18 $115 put | 09:35 @3.45 | 09:38 @3.90 | +42.92 | full exit at TP2 |
| Sep 14 INTC 2× Sep 14 $96 call | 09:33 @1.00 | 11:42 @2.15 | +225.84 | full exit at TP2 |
| Sep 14 MSFT 1× Sep 18 $507.5 put | 12:50 @5.45 | 15:56 @6.50 | +102.92 | session flatten; no target reached |

## 1. Source setups versus our plans (Sep 14: MSFT, META, AAPL, MRNA)

| name | author (before the open) | our linked plan | what the tape did (RTH, 1m exchange bars) | verdict |
|---|---|---|---|---|
| MSFT | long over **498.97** toward **505+** (caption 09:20:51); no stop, no confirmation, no contract | short rejection at 509.56 (stop 514.751), built Sep 13 | 09:30 high 499.10 but close 498.03; first completed close above 498.97 at **09:48** (499.99); post-break minimum 498.39 with 12 minutes at/under the level before 505; first 505 touch **11:36**; session high 509.93 | **representation mismatch** (long idea covered by a short plan); an underlying trigger-to-target sequence exists |
| META | long reclaim/break of the double top after a liquidity grab, hold required; no number | short rejection 663.7467, gap-voided | open 657.83, high 668.60, low 649.22 | direction mismatch; **unscorable** without a numeric level |
| AAPL | long over **336.22** (caption) | long breakout at 336.22, armed 09:15 (our stop 330.5688, our targets) | high **335.50** | correct no-trigger; the plan matched the source level |
| MRNA | long over **149.73**, swing horizon possible | breakout 148.5613 rejected (0.26R) | high **147.34** | correct no-trigger; different geometry did not matter today |

Two of four were no-trigger controls; one had no geometry; one (MSFT) is the case to define.

### The continuation candidate (one definition, frozen before any new cohort)

Author-supplied fields are marked **A**; everything else is **ours** because the author omitted it.

| field | value | who |
|---|---|---|
| direction, level | long over 498.97 | A |
| target | 505.00 (the caption's lower bound); full exit for one or two contracts | A (level) / ours (full-exit rule) |
| entry confirmation | first **completed 1-minute close above the level**, order at the next minute's open (intraminute order is not recoverable from OHLC; a first-touch entry enters below the level on this day) | ours |
| stop | **opening-range low of the first five completed minutes** (495.34 on Sep 14), invalidation on a 1-minute close below; never the level itself (the tape re-crossed 498.97 twelve times before the target) | ours |
| expiry | same session; flatten at 15:45 like every EM plan; no re-fire after a stop | ours |
| no-chase | do not enter above level + 0.5% (501.46); if the confirming close is above that, wait for a retest close | ours |
| contract | just-OTM call, ≤ 10% spread on the live NBBO, current-week or next-week expiry, quantity by the existing risk budget | ours (existing EM policy) |
| R:R gate | R2 measured to the author target with our stop: at the 09:49 open the trade is 1.09R (499.96 entry, 4.62 risk) — below EM's 3R gate | ours (existing) |

Sep 14 walk-forward of that definition and its two rejected alternatives, underlying only:

| entry definition | entry | stop rule A (opening-range low) | stop rule B (the level, close below) |
|---|---|---|---|
| (1) first touch, next open | 498.13 @ 09:31 | target 11:36, **+2.46R** | invalid: entry is below the level |
| **(2) completed close, next open** | 499.96 @ 09:49 | target 11:36, **+1.09R** | stopped 10:26 @498.79, −1.18R |
| (3) break + retest (retest 09:50 low 498.87), next open | 499.53 @ 09:52 | target 11:36, +1.31R | stopped 10:26, −1.32R |

Reading: with a structural stop every entry definition reaches the author's target, but the confirmed entry
earns only 1.1R against our stop and fails EM's own 3R gate; a stop at the level is stopped out in every
confirmed variant. The candidate is therefore **not** a trade the current rulebook would take, and the day's
outcome does not by itself justify relaxing the gate. What it does justify: representing the source direction
and level as their own candidate row (order-free) so the daily ledger can count how often the author's
continuation triggers, confirms, and reaches its target under a frozen stop, across a fresh cohort.

Option leg: no just-OTM 500 call bars are stored; the nearest stored contract (Sep 21 $505 call) has only
sampled prints at 09:48–09:53 (3.85 / 4.50) and 11:35–11:40 (4.00 / 6.55). **Unscorable as an option trade.**

## 2. Exits with entries, contracts and quantities held fixed

### 2a. Faster execution at unchanged targets (the HPQ question)

| position | target event | actual action | with a fresh-observation execution at the same target | change |
|---|---|---|---|---|
| HPQ | TP1 35.1462 touched intrabar **09:36** (high 35.19, close 34.87) | trim submitted 09:37:00 after the bar closed, filled 34.803 (+$0.99) | a resting limit for the 30 shares at 35.1462 fills on the touch: +$11.29; the 70-share remainder unchanged | net −7.19 → **about +3.10** (shares have real liquidity at the touch; this is an assumption, stated) |
| HOOD Sep 14 | TP2 113.0225 touched intrabar 09:37 | exit filled 09:38 @3.90 | exchange prints 09:37 4.42–4.57; a bid path is not stored | direction unchanged; size of the gain unknown (illustrative only) |
| INTC | TP2 98.1708 touched intrabar 11:41 | exit filled 11:42 @2.15 | exchange print 11:41 2.30 | direction unchanged; illustrative only |
| HOOD Sep 10 | no target reached (TP1 6.46R away) | quote stop | no change | none |
| MSFT | no target reached (low 504.70 vs TP1 502.81) | flatten | no change | none |

Proposed behaviour: judge profit targets on fresh underlying observations (the ~2 s quote watch already used
for stops) and submit the exit against the immediately available option bid and size, instead of waiting for
the completed 1-minute bar. Targets, sizes and stops unchanged. This is an execution-cadence change with one
observed beneficiary (HPQ), no observed loser, and unknown magnitude on options because bids are not stored.

### 2b. A predefined earlier-profit / structural exit (the HOOD Sep 10 question)

Frozen policy P for the comparison: first opposing **saved plan level at least 1R** from the entry in the
profit direction replaces TP1 for the trim (single contract: full exit there); stop and time cap unchanged.
Evaluated on the saved levels of each plan, not on levels chosen after seeing the path:

| position | nearest saved level ≥ 1R | reached before the actual exit? | effect versus baseline |
|---|---|---|---|
| HOOD Sep 10 | 105.794 (16.2R) — the plan saved **no** level between 115.09 and 105.79 | no | **no help**: the levels the critic cited (114.51 / 114.02) are not in the saved plan, so a "structural" exit had nothing to act on; the 2.76R favourable move (113.50) is only reachable by a fixed-R rule, which this comparison does not test |
| HPQ | 35.4983 (3.4R) | no | none (TP1 at 1.3R was closer) |
| HOOD Sep 14 | 114.9121 (2.5R) | yes, at 09:35 (entry minute); option print 3.95 in the next minute vs 3.90 actual | roughly neutral (illustrative) |
| INTC | 99.34 (9.9R) | no | none; the winner is kept intact |
| MSFT | 501.61 (1.5R) | no (low 504.70) | none |

Reading: policy P changes nothing on four positions and is neutral on the fifth. The HOOD Sep 10 giveback
is a **distant-target** problem (TP1 at 6.5R for a two-contract position that exits fully at TP2, 12R) that
a structural rule cannot fix because the plan recorded no intermediate level; the only rules that would have
taken money there are fixed-R or premium-percentage rules, which the reviewers asked us not to grid-fit on
five trades. Proposal: keep policy P out; instead add a **target-distance sanity gate** at arm time — a
one/two-contract plan whose full-exit target is more than N R away is flagged, with N to be chosen on the
walk-forward sweeps (TRADING-RULES §5), not on these five trades.

### Missing data (both comparisons)

- No historical option **bid/ask** path for any contract; only prints (exchange and sampled). Every option
  "would have" figure is illustrative. Storing the NBBO at each exit observation is the prerequisite for 2a.
- No stored just-OTM MSFT call bars for the continuation candidate.
- The Sep 10 HOOD plan has no saved intermediate levels; policy P is untestable there.
- Five positions are a case study. Neither comparison is a promotion; both define what the forward cohort
  must record: source scenario, first eligible observation, target observation time, exit submission and fill,
  and the bid at the exit observation.

## Recommendation (reviewable, no behaviour change yet)

1. **Adopt for measurement, not trading:** the continuation candidate above as an order-free scenario row
   (direction/level from the author, our frozen confirmation, stop, expiry, no-chase), counted daily.
2. **Run 2a as the first forward experiment** on the same admissions: fresh-observation target execution
   with bids recorded; targets and sizes unchanged. HPQ is the motivating case; INTC/HOOD Sep 14 are the
   controls that must not lose.
3. **Do not adopt 2b's structural policy**; replace the question with the target-distance gate, calibrated on
   the sweeps.
4. Keep the advisory-critic delay measurement separate (about 17 s per fire; no fill was blocked by it).
