# Tips pre-live build plan (2026-10-02)

Built from [FINDINGS.md](FINDINGS.md) and appendices A-F. Every finding maps to one item below (traceability table at
the end). User direction 2026-10-02: build all of it, including the analyst looking for another way to take a trade
when the first contract is too expensive; **don't cut corners and don't add restrictions or blockers that the evidence
does not call for.**

**Design principles**
1. **Fix, don't fence.** A defect gets fixed and enforced. A rule that would *block* trades on thin evidence starts in
   `observe` (it journals what it would have done) and is promoted by a predefined criterion - never by mood.
2. **More ways to say yes.** Where the desk said "no" because of an arithmetic or plumbing limit (budget, contract
   size, a watch with nowhere to go), the fix is a fitting alternative, not a looser risk limit.
3. **One method, every book.** The same analyst decision feeds Practice and live; each book applies its own budget and
   caps. The mode toggle is a view.
4. **Exits keep authority.** Nothing here weakens stops, trims or the reduce-only exit path.
5. **Measured on real fills**, date-clustered, never on the shadow buy-and-hold proxy alone.

Status legend: `[ ]` open, `[x]` built + tested, `(observe)` ships journaling only.

---

## W1 - Correctness defects (enforce; no study needed)

- [ ] **W1.1 Units check (D1).** `not_past_target` / price-position checks compare a premium target with the stock price
  when `instrument=unspecified`. Rule: if the tip carries a strike or contract and the stated prices are premium-scale
  (below a fraction of the underlying), treat them as premium. Test with the MSFT 505 0DTE message (09-28).
- [ ] **W1.2 One feasibility authority (D2).** `check_feasibility` (analyst tool) and the geometry gate compute the same
  thing through ONE pure function (stop finalisation + per-unit risk + qty). The analyst sees the exact qty the gate
  will allow. If the gate still refuses at submission (quote moved), it returns the fitting qty/stop for one automatic
  re-size instead of expiring the card.
- [x] **W1.3 Contract multiplier unknown (D8).** (PR #313) Default 100 for standard US equity options when the chain omits it;
  refuse only on a known non-standard deliverable.
- [ ] **W1.4 Sim option fill realism (D3).** A simulated option BUY never fills below the decision bid/ask band that the
  live NBBO would allow (fill at the ask-side quote seen after latency, never below the limit by more than the live
  spread allows). Re-mark the three affected fills in the review notes (not in the books - books are append-only).
- [x] **W1.5 Gateway head-of-line blocking (D4).** Per-channel lock held through extraction only; the appraisal runs
  async after the signal is recorded (ordering stays per channel at extraction). Workers 2 → 6.
  *Built 2026-10-02 (branch claude/tips-w1-gateway):* the gateway sends `asyncAppraisal` and runs `--workers 6`;
  `/api/ingest/manual` answers once extraction + verification + the signal rows are recorded (content `extracted`
  = the ACK point) and the post-record stage (shadow books, appraisal, lane, auto-approve, cohort, review/finish)
  runs as one tracked task per message (`TipAppraisalDeferred` / `...Done`). Durable marker
  `extraction.deferredStage`; the recovery sweep resumes an orphan (< 30 min, never a second card) or abandons it
  (`TipDeferredStageRecovered`). A close/trim/update_stop recorded while the appraisal ran refuses the card
  (`TipLaneDecided lane=refused`). Rollback: `techniques.tip.intake_async_appraisal=false` or `--sync-appraisal`.
- [x] **W1.6 Clock (D5).** Startup + 08:00 ET skew check against an NTP/HTTP Date reference, journaled `ClockSkew`;
  desk alert above 2 s; runbook step to enable Windows time sync (user, one command).
  *Built 2026-10-02:* `zargar/clockskew.py` (NTP quorum via `tools/clock_health`, HTTP `Date` HEAD fallback),
  `ops.clock_skew_*` settings, `/api/health` `local.clockSkewMs`, escalation via `zargar/desk_alert.py`; runbook in
  docs/OPERATIONS.md "Host clock" (the w32time step is still the user's).
- [x] **W1.7 Earnings entry consistency (D7 / E0).** (tip-time, armed-fire and armed auto entries) No new tip entry when the exit policy would flatten it before the
  next session (`days_to_earnings <= flatten_before.days`); journaled `TipLaneDecided lane=refused reason=earnings_window`.
- [x] **W1.8 Shadow book quarantine (D9).** (cause fixed in PR #313; quarantine at deploy) Quarantine "Shadow: tt" and "Shadow: ab (armed)"; fix the cause (sells
  without a matching lot) so FIFO never goes short in a shadow book.
- [x] **W1.9 Recovery-sweep gates (D10).** The recovery sweep and the main intake share one `_decide_auto` helper (trust,
  geometry, integrity). Integrity incidents scoped to the order's own book.
- [ ] **W1.10 Rule-audit judge failures (D12).** Surface the real error (empty message today), retry with backoff.

## W2 - Analyst: find another way to take the trade

- [ ] **W2.1 Fit-or-reshape before a budget skip.** When the stated contract does not fit the risk budget, the
  application (deterministically, no extra model turns) builds the alternatives and hands them to the analyst in one
  tool result `find_alternatives`:
  1. same expiry, cheaper strikes (one-two strikes further OTM, liquid, spread within the fill band);
  2. later expiry, same strike (when the thesis horizon allows);
  3. a debit vertical of the stated contract (where the venue supports multi-leg);
  4. **shares** of the underlying sized to the risk budget at the structure stop.
  Each with qty that fits, max loss, break-even, spread %, and `preview_payoff` numbers. The analyst picks one or skips
  with a concrete reason against each. Live books receive the shares alternative (shares-only policy). Journaled
  `TipAlternativesOffered` / chosen alternative on the opinion (`opinion.reshapedFrom`).
- [ ] **W2.2 Prompt contract.** A verified, priced BTO may be skipped for budget only after `find_alternatives`; the
  verdict JSON carries `alternativesConsidered`. Missing → one automatic re-ask (no human).
- [x] **W2.3 Watch becomes an armed level.** A `watch` with a named level + stop is armed at-level (ARM-PLAN `at_level`)
  until the tip horizon; a watch without a level stays a note. Re-appraisal on touch is the normal fire path.
- [ ] **W2.4 Prefetch + seeded context.** Quote, chain slice, bars summary, positions and earnings for the extracted
  ticker are fetched in parallel with extraction and seeded into the prompt (saves 1-2 turns, ~8-15 s; earnings checked
  on 100% of appraisals instead of 5%).
- [x] **W2.5 Second opinion on judgement skips (observe: candidates journaled; the frozen-replay A/B is the next step).** For a verified BTO skipped on geometry/reach/chase/identity
  while "passing filters", a short opposite-framing re-check runs in frozen replay first (A/B on the frozen capture);
  promotion = flips with positive graded outcome on >= 15 cases.
- [x] **W2.6 Starter lane (observe).** Where only stop width fails, journal the 1-lot "starter" alternative as a shadow
  decision; graded before it can trade.
- [x] **W2.7 Do not raise `analyst_max_tools`** (evidence: 1 of 369 runs hit it).

## W3 - Timing and entries

- [x] **W3.1 Entry limit referenced to the source.** (option band 1.10x; no cancel-reprice - 49 of 51 fills came within 3.5 s) Option BUY limit = min(decision ask, source price × 1.10 (options)
  / 1.02 (shares), decision ask + 1 tick); cancel-and-reprice once after 20 s; never market. Removes the >5% overpays.
- [x] **W3.2 Card TTL by lane.** 0DTE/weekly cards live 15 min, swings 2 h; push at creation with a one-tap approve link;
  expire on the source's own trim/close (exists). Practice unattended keeps auto-deciding.
- [x] **W3.3 Pre-market level maps.** (posts with >= 3 branch signals decline on the record without a card per branch) A multi-branch map post becomes ONE watch-map record (no per-branch proposal rows);
  its levels arm after 09:30 through W2.3 when the analyst names them.
- [x] **W3.4 Intake liveness paging.** Gateway idle > 3 min in RTH → push + Telegram + desk alert (escalation, not just
  a journal line).
  *Built 2026-10-02:* `intake_liveness.page_loop` (30 s; `StallPager` = one page per stall + a recovery message),
  `techniques.tip.intake_page_idle_minutes` (3), journaled `TipIntakePaged`. (The old monitor's `eng.alert` call
  never existed on the engine - that is why 59 `TipIntakeStalled` rows reached nobody.)
- [x] **W3.5 Fast lane (observe).** Deterministic pre-check for clean priced BTOs from earned-auto sources, booked as a
  shadow decision beside the analyst's; promotion criteria preregistered (fill-vs-quote gain net of extra takes).

## W4 - Event calendar v2 (shared platform store)

- [x] **W4.1 Append-only `market_events` store** with revisions, tiers, per-source coverage windows (`unknown` outside
  coverage, never "no event"), `as_of` reads. Backfill the three journaled verified-event versions + 09-11 CPI + 09-16
  FOMC.
- [x] **W4.2 Fetchers** (BLS ships as the official 2026 schedule: bls.gov blocks scripted downloads) (nightly + 08:00 ET): Fed FOMC calendar, BLS iCal (CPI/NFP/PPI/JOLTS), BEA (GDP/PCE), Treasury
  (tier 3 label only), earnings from two sources (`confirmed` when they agree within a day, BMO/AMC kept). Journaled
  `MarketEventsFetched`.
- [x] **W4.3 Horizon-aware exposure** (`event_ack` in the opinion schema still open) `TipEventExposure` on every proposal/arm/adoption: tier-1/2 events and earnings
  inside the position's planned life. Analyst header shows tier 1-2 + the ticker's earnings only (fixes the 221/236
  label noise). Opinion field `event_ack`.
- [x] **W4.4 Timing-aware earnings flatten (E4, enforce).** BMO → flatten 15:45 prior session; AMC → 15:45 same day.
  This *removes* today's premature full-day-early exits.
- [x] **W4.5 Event policies E1-E3 (observe; E5 open).** Tier-1 entry window, size-down across tier-1, short-dated options
  across tier-1, arms carry their event (re-appraise before the window). Journal `TipEventPolicyShadow`; promote per the
  D-appendix rule (>= 25 affected trades and >= 6 tier-1 events).

## W5 - Exits, sizing, sources

- [ ] **W5.1 Premium bleed exit review.** 0 wins in 11. Replace the fixed bleed with a thesis-anchored rule: the
  underlying's stop governs; the premium stop becomes a catastrophic floor (e.g. -60%) plus theta/time cap. Ship the
  current rule beside the new one in observe for 10 sessions, then switch (Practice); live is shares-only anyway.
- [x] **W5.2 Size toward budget - investigated 2026-10-03: capital-bound, not arithmetic.** The reserve glide (free cash / 3 slots) and the $2,000/tip cap bind before the $100 risk budget (MSTR: risk allowed 24 sh, cash 10); a $1,000+ share is an integer floor. Sizing up is a capital decision for the user (e.g. size to risk with notional capped by max_position_pct). Find why median planned risk is 57% of budget (integer floors, notional/name caps,
  analyst qty hints) and fix the arithmetic; report utilisation per trade on the desk report.
- [ ] **W5.3 Per-source option permission earned on graded outcomes** (options allowed for a source only after its
  graded record clears the bar; default shares). Practice keeps measuring every source in shadow.
- [ ] **W5.4 Source scorecard on the desk** (graded per source, date-clustered) feeding earned-auto; ab under watch.

## W6 - One method, many books (Practice + live together)

Design in appendix E §5. Items:
- [x] **W6.1 `techniques.tip.books` bindings** + validator + `resolve_books`/`knob` (empty = today).
- [x] **W6.2 Fan-out**: appraise once; `create_from_signal` per binding with per-book budget, qty rescale, geometry,
  caps, vehicle policy; `TipBookFanOut` journaled; `_decide_auto` per proposal.
- [x] **W6.3 Armed plans keyed `(signal, book)`**; live arms carry the binding's acknowledgement.
- [x] **W6.4 Dedupe once-per-idea work**: trust, retros, entry study, card alerts, cohort rows count the primary book.
- [x] **W6.5 Routing split** (`trading.mode` stays the routing key; the UI switch became a per-browser view): `trading.live_routing` (server switch) + per-binding `enabled`; the toggle becomes a client
  view; reduce-only exemption on the multi-leg gate too. `trading.mode` kept in sync for Options Cartel (their code
  untouched).
- [x] **W6.6 Per-book risk keys**: order-rate and technique day-notional keyed per book.
- [x] **W6.7 UI**: Tips cards show a book chip + sibling outcome; Settings "Tips books" editor; routing indicator by HALT.

## W7 - Live readiness

- [x] **W7.1 Cash-account settlement guard** (sync = settled cash; sale proceeds since the last sync are excluded; IBKR Canada rules still to confirm with IBKR): spendable = settled cash (T+1); no buy funded by unsettled proceeds that
  would be sold before settlement (good-faith rule) - enforced on the live book; confirm IBKR Canada specifics (user).
- [x] **W7.2 Host** (alert below 1.5 GB; moving the runtime is the user's call): memory guard + alert below 1.5 GB free; checklist to move the runtime off the crowded machine.
- [ ] **W7.3 Paper session** (runbook): Practice + IBKR paper bound together, both auto, pass criteria in the runbook.
- [ ] **W7.4 Go-live**: live binding, $3k cap, shares only, user's explicit go for routing + live auto.

---

## Order of work

1. **Weekend before the 10-05 paper session:** W6 (both books must run together Monday), W1 (all), W3.1, W3.2, W4.4 +
   W1.7, W7.1.
2. **Next:** W2.1-W2.4 (fit-or-reshape, one feasibility authority already in W1.2, watch→arm, prefetch), W3.3, W3.4.
3. **Then:** W4.1-W4.3 store + fetchers + exposure, W5.1-W5.4.
4. **Observe lanes running in parallel:** W2.5, W2.6, W3.5, W4.5.

## Traceability

| Finding | Item |
|---|---|
| Options lost, shares made money | W5.3, live shares-only (exists) |
| Premium stop/bleed 0 of 11 | W5.1 |
| Human cards never approved | W3.2 |
| Pre-market maps 0 fills | W3.3 |
| Planned risk 57% of budget | W5.2 |
| Budget skips of genuine trades | W2.1, W2.2 |
| Gate vs analyst mismatch | W1.2 |
| Watch dead end | W2.3 |
| Units bug | W1.1 |
| Sim fills below limit | W1.4 |
| Gateway queueing | W1.5 |
| Clock drift | W1.6 |
| Event data hand-kept / noisy / lost history | W4.1-W4.3 |
| Entries inside earnings window; arms through FOMC | W1.7, W4.5 (E5) |
| INTC multiplier | W1.3 |
| Bad shadow books | W1.8 |
| Recovery sweep skips trust; incidents scoped to one book | W1.9 |
| Analyst qty copied to every book | W6.2 |
| Rule audit failures | W1.10 |
| Host memory | W7.2 |
| Option seconds cost money | W3.1, W2.4, W1.5, W3.5 |
| Judgement skips (HOOD/LITE/QCOM) | W2.5 |
| Tipster skill mostly negative | W5.4 |
| T+1 / good-faith on a cash account | W7.1 |
| Practice + live together | W6 |
