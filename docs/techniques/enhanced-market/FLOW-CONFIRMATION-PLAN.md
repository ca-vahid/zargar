# Flow-confirmed entries (T-12) - build plan

Written 2026-09-08 evening by the EM desk, from the day-9 review and the author's X feed
(`notes/2026-09-08-author-x-feed.md`). Status of every phase is a checkbox; findings go to
TRADING-RULES (method) and PLATFORM-RULES (engine). The evolution loop applies: nothing
here changes a live threshold until a variant sweep, then a shadow instance, then Practice
money has earned it (EVOLUTION-PLAN.md).

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

## 2. What we are building

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

## 3. Decisions to take before phase 1 (defaults proposed; the user decides)

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

### Phase 0 - measurement plumbing (half a day)
- [ ] `flow_sweeps` table + model; `FlowSweep` event contract.
- [ ] `tools/optiontrades_backfill.py`: pull Alpaca option trades for a symbol list and a date
      range, classify against the NBBO quotes from the same API, write sweeps. Verify on
      the author's three named trades (TSLA 08-31, GPRO 08-31, NVDA 09-04) - the detector
      must find them or D1 is wrong.
- [ ] Open-interest source: the morning CBOE chain snapshot we already store (`option_chain_snapshots`).

### Phase 1 - history and the variant (one to two days)
- [ ] Backfill sweeps for the EM universe over the sessions we can replay (last 20 trading days).
- [ ] `flow_confirm` in `MarketRules`/`Thresholds` (off | log | require), read by `TriggerTracker`
      via a `sweeps_for(symbol, minute)` lookup injected by the walk-forward.
- [ ] Variant sweep: baseline vs `--set flow_confirm=require`; report per kind and window;
      record in TRADING-RULES T-12 with the verdict against D7.
- [ ] Second variant: `require` + premium-percent exits (T-6 knobs) - the "his tempo" run.

### Phase 2 - live detector (one day)
- [ ] Websocket consumer for option trades on the contracts EM is watching (the picks of
      armed plans + neighbours), same connection family as the OPRA quotes.
- [ ] Sweep aggregation live, `FlowSweep` on the bus, journaled; Flow page gets an "Intraday
      sweeps" tab (context, same as its nightly reads).
- [ ] EM runner in `log` mode: every fire records `flowConfirm: {sweep|none, contracts, volOi,
      minutesAfterTouch}` on the trade; the daily review tallies fired-with-sweep vs without.

### Phase 3 - shadow instance (one day, after phase 1 passes D7)
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
- Arming stays as it is (batch + auto-arm from the board). Sweeps confirm fires; they do not
  build plans.

## 6. Risks and honest caveats

- His posts are his selection of his wins. We have no verified record of his losses; the plan
  tests the MECHANISM on our own data, not his claimed results.
- Sweep detection on thin names (GPRO) will produce many false positives; D1's 250-contract
  floor and the "confirm, never create" rule (D4) are the guard.
- Alpaca option trades are one feed; OPRA consolidated prints may differ in size attribution.
  The backfill check against his three named trades is the calibration.
- Latency: a live sweep arrives seconds after the print; the fire-to-order chain already costs
  about a minute (critic). In `require` mode the wait is bounded by N.
