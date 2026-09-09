# Flow-confirmed entries (T-12) - build plan

Written 2026-09-08 evening by the EM desk, from the day-9 review and the author's X feed
(`notes/2026-09-08-author-x-feed.md`). Status of every phase is a checkbox; findings go to
TRADING-RULES (method) and PLATFORM-RULES (engine). The evolution loop applies: nothing
here changes a live threshold until a variant sweep, then a shadow instance, then Practice
money has earned it (EVOLUTION-PLAN.md).

**STATUS 2026-09-09 00:30 ET: phases 0-1 done, the theory is REJECTED on our history in both
forms (confirm gate and sweeps-as-trigger); T-6 exit tempo also negative. Sections 2-3 are kept
as the original design record; D4-D7 did not survive phase 1. Nothing here runs live. The only
open item is phase 2 in log mode (live NBBO-classified sweeps), optional, revisited after ten
sessions of live data if it is ever built.**

## 1. The finding, in one paragraph

Nine days of EM: one fill (GLD, +$175), zero on eight of nine days, and the review says our
gates were right 14 times in 20 when they said no. The author trades the same levels we plan
but his TRIGGER is order flow: a sweep on the ask, many times the open interest, in a
near-the-money contract expiring today or this week, minutes after the open; he exits the same
day on premium percent. We plan the WHERE as well as he does (his own names are on our board
every morning); we have no WHEN. Our Flow lane reads chain snapshots once a night. His screen
reads prints live.

Feasibility check, 2026-09-08 21:40 ET: our Alpaca subscription already serves historical
option TRADES. The contract he named (TSLA $360C expiring 2026-08-31) returns 10,000+ prints
for 09:30-10:10 ET that day, 37,874 contracts, 23 prints of 100+ contracts. The signal is
available to us, historically and (via the same feed's websocket) live.

## 2. What we set out to build (design record; items 2, 3 and 5 were never built - phase 1 killed them)

1. **A sweep detector** (platform, `zargar/marketstructure/flowprints.py` +
   `zargar/research/optiontrades.py`): option prints from Alpaca (REST for history, websocket
   for live) classified against the NBBO at print time (at/above ask = buyer-initiated),
   aggregated per contract per minute, scored against that morning's open interest.
   Output: a `flow_sweeps` table (symbol, contract, minute, contracts, notional, side,
   vol_oi, prints, largest) and a `FlowSweep` bus event for consumers.
2. **A method gate, as data** (EM, `technique/rulebook.py` + `execution/planrunner.py` hook):
   `flow_confirm` = {off | log | require}. In `require` a fire waits up to N minutes for a
   qualifying sweep in the contract we would buy (or its neighbour strike) before the entry
   is sent; in `log` the fire proceeds as today and the sweep state is journaled on the
   trade so the review can score it. Default `log` in EM Practice from day one - it costs
   nothing and starts the evidence.
3. **A variant on history**: the walk-forward gets the same gate (`--set
   flow_confirm=require`) against RECORDED sweeps, so the theory is tested on the weeks we
   already have plans for, not on future days only. Alpaca history reaches back well past
   our 20-day bar window, so every replayable session can be scored.
4. **Exit tempo in premium** (T-6, already queued): a second variant that exits on premium
   percent with one exit, so his numbers and ours are compared on the same scale.
5. **A shadow instance** (`em_flow_shadow`, EVOLUTION phase 4) running `require` + fast exits
   live in alert mode beside EM, on the same tape, before any Practice money.

## 3. Decisions taken before phase 1 (as proposed; outcome: D1-D3 calibrated in phase 0, D4 withdrawn in 1a, D5-D7 moot after 1b)

| decision | proposal | why |
|---|---|---|
| D1 sweep definition | prints at or above the ask, >= 3x the contract's morning open interest within a rolling 5-minute window, and >= 250 contracts | his TSLA (122k vs 6.7k) and GPRO (32.7k vs 2.7k) are far above; 3x/250 catches the mega-caps without drowning in noise; tune by sweep |
| D2 which contract | the contract our pick would buy, plus one strike either side, same expiry | his sweeps sit on the strike just OTM of the level; a neighbour strike is the same statement |
| D3 wait window N | 10 minutes after the level touch | inside our entry window (12 bars); his 9:49 entry was 19 minutes after the open |
| D4 what a sweep may do | confirm a fire (gate), never create one | keeps the level as the WHERE; a sweep alone is GPRO territory and outside the method |
| D5 first mode | `log` in EM Practice immediately; `require` only in the shadow instance | evidence first, no behaviour change on the live book |
| D6 exits for the shadow | one exit at +100% premium or the plan's TP2 touch, whichever first; premium stop 50%; flat 15:45 | his tempo; the stop mirrors our premium stop |
| D7 adopt bar | +0.3R per fire over the baseline on the same sessions, and no more than 2x the fire count | the standing bar for every theory |

## 4. Phases

### Phase 0 - measurement plumbing (BUILT 2026-09-08 evening)
- [x] `flow_sweeps` table + model; `FlowSweep` event contract.
- [x] `research/optiontrades.py` (fetch, classify, detect) + `tools/optiontrades_backfill.py`
      (`--occ` / `--underlying --near N`, `--oi`, `--dry --verbose`). Historical option QUOTES
      are not on our Alpaca plan (404), so history classifies buys with the TICK TEST (uptick =
      buy, repeat = half); the live detector (phase 2) classifies on the real NBBO and rows
      carry `method` so the two are never mixed in a sweep.
- [x] Open interest from `option_chain_snapshots` (latest snapshot at or before the day);
      unknown OI is judged against an assumed 2,000, never against 1.
- [x] Calibrated on the author's named trades (dry runs, 2026-09-08 22:30 ET):

| contract | day | prints / contracts | OI | sweeps found | the author |
|---|---|---|---|---|---|
| TSLA $360C 0DTE | 08-31 | 31,807 / 108,445 (16x OI) | 6,742 | **09:40** (5,009 buys in the window, cumulative 3.0x OI) | entered 09:49, +240% |
| GPRO $1C 9/18 | 08-31 | 1,657 / 32,651 (12x) | 2,733 | **14:22** and 15:48 | "32,702 contracts, all on the ask", closed at $0.24 |
| NVDA $230P 0DTE | 09-04 | 54,952 / 499,435 (65x) | 7,716 | **09:42** and 10:55 | (he traded the calls, +115%; the puts were the flow) |
| NVDA $230C 0DTE | 09-04 | 37,602 / 291,995 (4.2x) | 70,246 | none | liquid contract: no burst against its own pace |

      D1 as calibrated (`SweepRules`): 5-minute window; window buys >= max(250, 0.25 x OI);
      session cumulative >= max(1,000, 3 x OI); the window must be >= 3x the contract's own
      prior 30-minute pace once 15 minutes have been seen; 10-minute cooldown; at most 3 sweeps
      per contract per day. The first version fired every 10 minutes on NVDA's puts (33 "sweeps")
      until the pace rule went in - a liquid contract is busy, not swept.

### Phase 1a - the confirm-gate on history (DONE 2026-09-08 late, REJECTED)
- [x] `tools/flow_variant.py`: rebuild each replay fire's contract (+/-1 strike), backfill its
      sweeps, mark the fire confirmed inside [-15, +10] min. Result on 30 valid fires / 19 with a
      chain: **1 confirmed (a -1.03R loser), 18 unconfirmed (+2.61R)**. His sweeps do not sit on
      our levels; decision D4 (confirm, never create) is withdrawn for the test that follows.

### Phase 1b - sweeps as the trigger (DONE 2026-09-09 00:30 ET, REJECTED)
- [x] `tools/flow_sweep_universe.py --backfill`: 9 snapshot days x 117 names x near-the-money
      contracts = 2,978 contract-days fetched, **923 sweeps** written to `flow_sweeps`.
- [x] `--score`: 847 sweeps (before 15:30) as trades on his tempo: **30% win, mean -13.0%, median
      -55% of premium**; exit grid and first-90-minutes / first-per-name cuts all negative (best
      cell -2.4%). Only AAPL positive (+2.3% on 50). Verdict in TRADING-RULES T-12.
- [x] `tools/flow_variant.py --tempo` (T-6): our own 19 fires on his premium tempo: best cell
      -14.8%; the plan ladder on the underlying beats it. T-6 not adopted.

Both theories fail on our data. What the evening established: the signal he names is
observable to us (the detector finds his trades), but as a mechanical trigger from public
prints it has no edge, and our own fires do not improve on his exit tempo. The remaining
unknowns are his ask-side classification (we used the tick test on history) and his
selection - the only honest way to test those is live NBBO-classified sweeps, collected in
log mode at no cost, revisited after 10 sessions. Phases 2-4 below are re-scoped to that.

### Phase 1c - the walk-forward variant (only if 1b is positive)
- [ ] Backfill sweeps for the EM universe over the sessions we can replay (last 20 trading days).
- [ ] `flow_confirm` in `MarketRules`/`Thresholds` (off | log | require), read by `TriggerTracker`
      via a `sweeps_for(symbol, minute)` lookup injected by the walk-forward.
- [ ] Variant sweep: baseline vs `--set flow_confirm=require`; report per kind and window;
      record in TRADING-RULES T-12 with the verdict against D7.
- [ ] Second variant: `require` + premium-percent exits (T-6 knobs) - the "his tempo" run.

### Phase 2 - live detector, LOG mode only (one day; the only phase still worth building)
- [ ] Websocket consumer for option trades on the contracts EM is watching (the picks of
      armed plans + neighbours), same connection family as the OPRA quotes.
- [ ] Sweep aggregation live, `FlowSweep` on the bus, journaled; Flow page gets an "Intraday
      sweeps" tab (context, same as its nightly reads).
- [ ] EM runner in `log` mode: every fire records `flowConfirm: {sweep|none, contracts, volOi,
      minutesAfterTouch}` on the trade; the daily review tallies fired-with-sweep vs without.

### Phase 3 - shadow instance (ONLY if 10 sessions of live NBBO sweeps score positive)
- [ ] Register `em_flow_shadow` (EVOLUTION phase 4): EM's plans, `require` gate, D6 exits,
      alert mode, its own scorecards. Runs beside EM on the same tape.
- [ ] Five sessions minimum before judging; the weekly capture-rate page compares the three
      lanes (EM, shadow, author's posted trades).

### Phase 4 - graduation
- [ ] If the shadow beats EM by D7 over ten sessions: `em_flow_shadow` gets the Practice book
      at reduced risk (EVOLUTION phase 5), then the gate is proposed for EM itself in
      TRADING-RULES 5 with the evidence.

## 5. What this does NOT change

- R2, the critic, the gap rules and the windows stay. The critic's tally is +9.0R in its favour
  and the day-9 replay had 100% coverage; the missing piece is timing, not filtering.
- The nightly LLM plan review stays while it is measured (2026-09-08: accepted plans +0.52R per
  valid fire, rejected -0.65R, ten fires over three sessions - promising, not proven; decision
  at ten sessions, TRADING-RULES 2).
- Arming stays as it is (batch + auto-arm from the board). Sweeps neither confirm fires nor
  build plans in the live runner - they are rows in `flow_sweeps` for research.

## 6. Risks and honest caveats

- His posts are his selection of his wins. We have no verified record of his losses; the plan
  tests the MECHANISM on our own data, not his claimed results.
- Sweep detection on thin names (GPRO) produces many false positives; D1's 250-contract
  floor and the pace rule are the guard (D4 no longer applies).
- Alpaca option trades are one feed; OPRA consolidated prints may differ in size attribution.
  The backfill check against his three named trades is the calibration.
- Latency: a live sweep arrives seconds after the print; the fire-to-order chain already costs
  about a minute (critic). In `require` mode the wait is bounded by N.
