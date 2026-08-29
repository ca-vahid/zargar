# Flow technique — build plan

*Planned 2026-08-27 from `docs/TECHNIQUE-CANDIDATES.md` (T2) after the wave-one trim.
Evidence base: options order flow is informative at **daily-to-weekly** horizons
(Pan-Poteshman 2006; Johnson-So 2012; Hilliard et al. 2025); real-time sweep chasing and
alert-room following are on the never list. ⚙ = engine-team dependency (2026-08-27 memo).
Status: **Phase A built 2026-08-27** — pure scan math (`techniques/flow/scan.py`),
`FlowService` (registered on `engine.scheduler` at `techniques.flow.scan_at` = 16:45 ET,
after the `chain_snapshots` research feed; reads `option_chain_snapshots` — single writer
is the research feed — with a scoring-only live fallback; verdicts in `flow_reads`),
routes (`/api/flow/reads|context|scan|status`), registry entry, settings keys, context
line consumed by Tip verification; tests in `tests/test_flow_scan.py`. **UI + the
remaining Phase A items BUILT same day** per `UI-PLAN.md` (Desk main view + evidence
badges/strip, Symbol Story drill-down with journaled `FlowContextServed` deliveries,
Morning Brief tab, universe flow layer, EM context injection, Tips flow chip; visual pass
against a live-CBOE scan — calibration findings in UI-PLAN §3a). Phase B (sweep → maybe
swing variant) unchanged.*

## 0. What it is — and what it is not

A **daily scanner** over the options chains we already fetch (CBOE delayed; Alpaca OPRA
if the sub is restored) that flags unusual activity per contract and per symbol, tracks
it across days, and surfaces it as **context**: a flow score on the universe, a badge in
the UI, and context lines for the Tip technique's verification/critic and EM's reads.

**v1 places no orders.** A tradeable swing variant (enter next open on multi-day repeat
accumulation) exists only if a walk-forward sweep over accumulated snapshots proves edge
— the research expects the public version of this anomaly to be heavily decayed, so a
null result is the base case and the context value stands on its own.

## 1. Identity

id `flow`, label "Flow"; registry entry; settings `techniques.flow.*`. Runs of the scan
are journaled (`technique="flow"`) so scans are replayable like every other decision.

## 2. The signals (all computable from data in hand)

Per **contract** (from a daily chain snapshot):
- `vol_oi = volume / max(open_interest, 1)` — opening-activity proxy (Barchart's public
  recipe uses ≥ 1.25; we sweep the threshold).
- `premium_proxy = mid × volume × 100` — money-weighted size.
- OTM% and DTE bucket — the informative footprint is **near-dated, somewhat OTM**
  (Hilliard: money flowing into probably-worthless contracts is the signal).
- **Overnight OI confirmation**: next day's OI delta ≈ yesterday's flagged volume ⇒ the
  volume really was opening positions. This is the disambiguator retail flow services
  can't give us and it only needs *daily* data.
- **Repeat hits**: same contract (or same strike-zone/expiry) flagged ≥ N days in a
  rolling window — the strongest practitioner filter, matches the academic accumulation
  picture.

Per **symbol** (aggregates):
- O/S ratio (options volume ÷ stock volume — Johnson-So; mostly a *bearish* flag when
  high), put/call volume skew, net premium direction, IV vs its own recent history.

Output: `FlowRead` per symbol per day — score, direction lean, top contracts, reasons —
persisted like a run result, queryable by date.

## 3. Phase A — scanner + context (build now)

1. **Snapshot dependency** (⚙ memo B5): the nightly chain-snapshot job is the engine
   ask. Until it lands, the technique keeps its own minimal persistence so we lose no
   data: one row per (day, symbol, contract): volume, OI, mid, IV. Universe: the shared
   universe layers + any symbol with an open/armed position.
2. **Scan pass** (nightly after the close; ⚙ B4 scheduler when it lands, else the
   service's own loop): compute §2, write `FlowRead`s, journal a summary event.
3. **Surfacing**:
   - Universe: a `flow` auto-layer (like most-actives) feeding `service.universe()`.
   - UI: flow badge/column on the universe and Armed pages; a small Flow tab listing
     today's reads with reasons (plain language, as everywhere).
   - **Tip integration**: tip verification/critic context gets the symbol's FlowRead
     ("flow agrees: 3-day call accumulation, OI-confirmed" / "flow disagrees: heavy put
     skew") — recorded in the run config so reviews can judge whether flow context
     actually helped.
   - EM: FlowRead available to the analyze context the same way (a note, not a gate).
4. **Pure functions** in the shared spirit: scan math lives as parameterised functions
   (`techniques/flow/scan.py`) with fixture-chain tests; thresholds in settings:
   `techniques.flow.{vol_oi_min, premium_min, dte_max, otm_range, repeat_days,
   repeat_window, os_ratio_flag}`.

## 4. Phase B — the sweep, then maybe the swing variant (⚙ + data-gated)

- Accumulate ≥ 60 trading days of snapshots (or backfill trades/quotes/bars from Alpaca
  historical options data, Feb 2024+, if the sub is restored — OI history still accrues
  only forward).
- Walk-forward sweep (the existing sweep harness, keyed `technique="flow"`): signal =
  repeat-accumulation + OI confirmation; entry next open; exits = ladder + time stop
  (5–10 sessions) + premium stop; earnings veto. Score with `simulate_plan` /
  `simulate_position` (⚙ Phase 2b for option holds).
- **Gate**: only if the sweep shows positive expectancy after realistic spread costs does
  a tradeable variant get built — shadow-first like every source, real money behind the
  same scorecard bar as Tip sources. A null result leaves Flow as a context technique,
  which is already worth its cost.

## 5. Tests

Fixture chains (real CBOE JSON shapes, incl. string numbers) → scan math; repeat-hit
tracking across synthetic days; OI-confirmation logic; O/S aggregation; universe layer;
context injection into a canned tip verification.

## 6. Open questions

- Scan universe breadth vs API cost on CBOE (117-name core + extras is ~120 chain
  fetches/night — fine; full most-actives sweep needs a cap).
- Whether the flow score should ever *veto* (not just inform) a Tip — proposal: never in
  v1; revisit with scorecard evidence.
- Snapshot retention (raw rows are small; keep everything until proven otherwise).

## 7. Judgement log

- **2026-08-29 · First calibration (PRELIMINARY, one day-pair)** — see
  `notes/2026-08-29-calibration.md` + the `flow_calibrate` CLI. Headline: 0-2
  DTE flags were ANTI-signal (confirmation below the 28.1% baseline); a DTE
  floor doubles confirmation. Applied live: `dte_min=3` (new), `premium_min`
  100k→250k, `vol_oi_min` 1.25→2.0; the score is now PREMIUM-WEIGHTED
  (`premium_unit` $1M/point) so a whale outranks five minnows.
  `techniques.flow.calibrated` stays **false** — the FL4 conviction upgrade
  (explicit_call on confirmed high scores) is built but gated until the
  re-run over ≥ 5 day-pairs (~Sept 5) confirms the separation holds.
