# Exit policies and net payoff by setup - 2026-09-17 (research, no rule derived)

Scope: the five Tips Practice entries of 2026-09-17 and the MRNA share campaign opened 2026-09-15. Read from
`proposals.context.riskPlan.payoff` (delta-linear previews, `payoff-v1`), `riskPlan.execCost` (`execcost-v1`),
`ManagedPositionPolicyChanged` / `ManagedPositionExit` journals and `executions`. Register identity:
`feasibility-annotate` + `entry-timing-cohort` context (`experiments-v1`). One session, five positions, one flash-fill
anomaly: nothing here is an expectancy, and no threshold, minimum-R gate or stop rule is proposed from it.

## Quote-quality and depth caveats (read first)

- **MRNA Sep-18 165C** (+$112.92): the buy price 0.75 was a LOCALLY RECENTRED estimate, not a venue quote
  (E17-01 audit `reviews/2026-09-17-mrna-quote-audit.md`). Every number on that row is evidence-quality-limited;
  it is shown apart and excluded from the "clean" subtotal. Its execution-cost diagnostic (round trip $13.08,
  6.5% of purchase value) was computed on the decision quote and is unaffected by the fill.
- **Depth:** the entry-side top-of-book size was 1 contract on MRNA 165C, ORCL 160C and SMCI 41C (against 1 lot),
  and 1 on ACHR against 3 contracts; the immediate-liquidation cost is therefore indicative of the touch, not of
  available depth. SBLK's share sizes (50k/40k) are the shares feed's placeholder sizes, not venue depth.
- **Fee basis:** cash fees are $1.04 per option contract per side and $0 per share order; the payoff previews before
  this evening's fix used the commission alone ($0.99) and understate modelled round trips by $0.10 per contract
  (fixed in 0.8.11 - previews now use execcost's basis).
- Payoff previews are delta-linear arithmetic on the DECLARED plan ("no statement that any target is reached").

## Per position: declared plan, what management did, actual net

| Setup | Position | Declared plan at entry (payoff preview, best target) | Policy changes (source-driven vs original) | Actual exits and net (cash fees) |
|---|---|---|---|---|
| shares (campaign from 09-15) | MRNA 7 sh @141.96 | original stop 134.37, ladder 155/162 x 0.5 | 9 changes today, all analyst follow-ups of the SOURCE (KianTrades trims): stop 134.37 -> 145.5 (09:29) -> 148 (09:39) -> 152 (09:55) -> 155.5 (10:00) -> 156.8 (10:07) -> 157.2 (10:09); ladder 155/162 -> 162 only | 2 @152.97 (source follow-up), 2 @154.37 (TP1), 1 @156.45, 1 @159.59 (follow-ups), 1 @157.11 (venue stop) = **+$94.10** whole campaign, $0 fees; realised in 5 tranches on the day the source trimmed |
| option, short-dated (1 DTE) | MRNA 165C x1 @0.75 (FLASH) | oneLot R 1.0, net +$87.41 at the declared target; round trip est. $13.08 | none | sold 1.90 four seconds later (premium TP1 +100%) = **+$112.92** - evidence-limited (recentred quote) |
| option, 8 DTE | ORCL 160C x1 @1.64 | oneLot R 1.53, net +$112.96 at target 155.5 (underlying); planned stop risk $73.80 (45% premium stop) | 10:25:28 policy updated from the source's own 1.45 stop: premium stop 45% -> **12%** (guard tightened) | 12% premium stop hit 11:04 on a second distinct observation @1.44 = **-$22.11** (vs -$73.80 had the original 45% stop been the exit) |
| option, 8 DTE | SMCI 41C x1 @1.59 | oneLot R 1.02, net +$73.24 at target 41.3; 45% premium stop | 10:49:27 policy re-declared (target 41.3, premium guard unchanged) | open; marked -$26.00 at the close; round trip est. $6.08 (3.8%) |
| option, 120 DTE | ACHR 7C x3 @0.48 | 3 rungs 5.95 / 6.6 / 7.4 (1/1/1 contracts), fixed underlying stop 4.75; best-target R ~1.98; TP1-then-stop about -$30 | none | open; marked $0.00; round trip est. $9.24 (6.4%) with bid size 1 against 3 contracts |
| shares | SBLK 62 sh @31.91 | ladder 32.85 / 33.90 x 31/31, stop 30.58 (geometry moved 30.95 -> 30.58); best-target R ~1.10; TP1-then-stop about -$12 | post-fill decision: keep the tighter stop | open; marked -$6.82; venue GTC stop 30.58 resting; round trip est. $1.24 (0.06%) |

## By setup (this session only; counts are position-sessions, not independent ideas)

| Setup | Entries | Closed | Net realised (cash fees) | Clean subtotal (flash excluded) | Open marked | Modelled best-target R (declared plans) | Round-trip friction at entry |
|---|---:|---:|---:|---:|---:|---|---|
| shares | 2 (MRNA campaign, SBLK) | 1 | +$94.10 | +$94.10 | -$6.82 | 1.10 (SBLK); MRNA campaign pre-dates the preview | 0.06% (SBLK) |
| options <= 14 DTE | 3 | 2 | +$90.81 (+112.92 flash, -22.11 ORCL) | **-$22.11** | -$26.00 (SMCI) | 1.0 / 1.53 / 1.02 | 6.5% / 1.9% / 3.8% |
| options > 14 DTE | 1 (ACHR) | 0 | - | - | $0.00 | ~1.98 (collapsed 3-rung ladder) | 6.4% |

## Readings (hypotheses only)

- **Source-managed exits did the work on MRNA shares.** All nine policy changes were analyst follow-ups of the source's
  own trims; the campaign realised +$94.10 in five tranches with quantity protection intact. The overnight-hold pair
  measured a +$46.27 quote-drift advantage for carrying to the open - one observation, not an overnight edge.
- **The tightened ORCL guard changed the loss, not the decision.** The source-driven 12% premium stop turned a planned
  -$73.80 stop risk into -$22.11; whether the tighter stop "helped" cannot be read from one loss - it needs the
  initial-policy and source-driven-policy regimes studied apart across many positions (register: exit policy regime
  as a grouping key from now on).
- **Cheap short-dated options carry 2-7% immediate friction and single-lot depth**; modelled best-target outcomes near
  1.0R leave little room. This is measurement, not a minimum-R gate.
- **Entry throughput is not the bottleneck** (all five TAKEs filled); the open question is exit quality and fill
  authenticity, which E17-01 and the fill diagnostics now make measurable.

## Next collection (prospective)

Group every closed Tips position by setup x exit-policy regime (original vs source-driven vs premium-guard) with net
after cash fees, the entry-time round-trip estimate and the touch depth; carry the E17-01 evidence-quality label on
any fill whose evidence shows `transform` or a one-lot flash. Report weekly, no promotion from concentrated single-name
gains.
