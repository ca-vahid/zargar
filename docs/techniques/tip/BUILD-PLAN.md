# Tips technique — Phase B build plan

*Written 2026-08-27 on the Tips fork (`claude/adoring-thompson-c258ab`), while the Flow
team builds `flow/UI-PLAN.md` in parallel. Companion: `PLAN.md` (Phase A as-built + the
decisions), `docs/BUILDING-A-TECHNIQUE.md` (the platform contract). Status: **plan → in
progress**; tick tasks as they land.*

**Coordination boundary with the Flow team:** they own `techniques/flow/*`,
`api/routes_flow.py`, and one call-site change in `signals/service.py` (their F1 adds a
`consumer=` argument where tip verification fetches flow context). Tips work must not
touch `techniques/flow/*`; expect one small merge in `signals/service.py` and rebase on
main often.

## 0. The headline: options expression (Phase B proper)

Tips are mostly options calls ("NVDA 180c 9/19") and today both books express them in
**shares** — the scorecard measures the idea's timing but not its leverage, and short
tips can't be expressed at all. Phase B makes the vehicle real, under one rule that
protects the dual-book comparison:

> **Per-tip vehicle rule:** a tip is expressed as an OPTION when it names one
> (instrument call/put, or a strike/expiry/DTE hint); otherwise shares. BOTH books apply
> the same rule to the same tip — the immediate-vs-armed comparison stays
> apples-to-apples per tip, whatever the vehicle.

Contract choice honors the tip first: a stated strike+expiry is used verbatim
(`occ.make`); a bare "calls"/"puts" gets the just-OTM pick inside the source policy's
DTE window (10–30d default, never 0DTE — RiskGate hard-rejects it for non-EM anyway).

## Phase T1 — the expression module + the immediate book `[ ]`

- [ ] `techniques/tip/express.py` — pure-ish picker: `tip_is_option(sig)` (the vehicle
      rule) and `pick_tip_contract(engine, sig, policy, *, spot)` →
      stated strike+expiry → exact OCC (existence-checked against the chain; graceful
      "contract not listed" error), else DTE-window just-OTM via the shared chain client
      (`pick_for_setup` with an expiry window, not EM's weekly/0DTE policy); short tips →
      puts with the `min_strike` mirror (no strike below the downside target). Returns the
      contract dict shape the runner already consumes (symbol, bid/ask/mid, dte,
      spreadPct, warnings).
- [ ] `signals/service._shadow_execute` v2: option tips buy the CONTRACT in the immediate
      book — `OrderIntent(sec_type="OPT", symbol=<unpadded OCC>, qty=size_by_budget(
      policy.budget_per_tip, ask, multiplier=100))`, `engine.ensure_symbol(occ)` +
      `options.track` so sim quotes flow; **no bracket** (tip targets are underlying
      prices — meaningless as premium brackets): the immediate book is buy-and-hold to
      thesis end, marked to market, settled by `OptionsService.settle_expired` (shadow is
      a practice-kind portfolio). Shares tips keep today's behavior (bracket included).
      Pick failure (no chain, not listed) falls back to shares with a journal note —
      the book must never silently skip a tip.
- [ ] Tests (`test_signals_tip.py` + rig): vehicle rule truth table; stated-contract pick
      vs DTE-window pick vs short-put mirror (fixture chain via `use_client` mock);
      immediate-book option order carries OPT/OCC/tags; fallback-to-shares on a `.TO`
      symbol (no CBOE chain).

## Phase T2 — the armed book goes options `[ ]`

- [ ] `TipRunner.arm_signal`: per-tip instrument — the vehicle rule decides
      `ArmConfig.instrument` (explicit config still overrides); `techniques.tip.instrument`
      default flips `shares` → `auto`.
- [ ] `TipRunner.pick_contract` hook (fires at fire time, before sizing): delegate to
      `express.pick_tip_contract`; the runner's existing gates then apply (skip-wide-spread,
      elevated IV, `entry_fallback="shares"` set as the tip default so a blocked contract
      expresses in shares rather than skipping — SNOW lesson).
- [ ] **Budget cap on contracts**: the runner sizes options by risk%; a tip must also
      respect `budget_per_tip` — clamp in the hook: `contracts ≤ size_by_budget(budget,
      ask, multiplier=100)` (hook stores the clamp on the trade; never journals).
- [ ] Handoff v2 (options): legs `secType="OPT"` (qty = +contracts, multiplier 100,
      avgFill = premium), `overnight="app_managed"` + `overnightAck=True` **for shadow
      books only** (a real-money arm still requires the per-arm acknowledgement — the
      runner's existing live gates stand); policy adds `premium_stop_pct` (resolved
      `techniques.tip.*` → `execution.*`) and `dte_close` (platform floor
      `execution.min_dte`); `time_stop_sessions` still capped by the thesis expiry;
      entry/risk stay in underlying terms (the manager's `net_mark` handles premium).
- [ ] Short tips end-to-end: direction=short + puts through arm → fire → handoff (closes
      the armed book's measurement gap; the scorecard caveat in PLAN.md §4 comes out).
- [ ] Tests (tip rig): armed option tip fires → contract picked (stated strike) → budget
      clamp respected → sim fill (option quote via `engine.quotes.on_quote`, published
      twice past the 120ms latency) → handoff produces an OPT ManagedPosition with
      premium_stop + dte_close + app_managed ack; short-put mirror; wide-spread fallback
      to shares.
- [ ] **Both-books gate:** T1 and T2 merge to main TOGETHER (a release where one book is
      options and the other shares would poison the comparison from that day on).

## Phase T3 — R-based outcomes + scorecard depth `[ ]`

- [ ] Tip runs enter the outcomes loop: `technique="tip"` plan runs scored by
      `simulate_plan` like EM's (underlying terms; note `premiumPathSimulated: false`
      analog for option tips). Verify the research outcomes loop picks up non-EM runs;
      if it is EM-keyed, fix it there (research layer, not a fork).
- [ ] Scorecard v2: per source per book — n scored, win rate, avg R, expectancy,
      never-triggered and expired-unfilled rates — alongside the portfolio P&L; the
      `barCleared` / `tipTimeEarned` rules re-read from expectancy (R) instead of raw
      P&L once ≥ `scorecard_min_n` outcomes exist.
- [ ] Tests: seeded runs/outcomes → expectancy math; the bar flips on R, not $.

## Phase T4 — Tips page v2 `[ ]`

- [ ] Source policy editor (a Sheet from the scorecard row): entry mode, mode, budgets,
      DTE window, conviction bar — writes `techniques.tip.sources` (journaled settings).
- [ ] Tip lifecycle row: received → parked/verified → armed today (chip → Armed page) →
      filled (chip → managed position) → scored (R); expired-unfilled shown honestly.
- [ ] Book comparison per source: the two P&L columns gain the T3 expectancy line; the
      `tip-time?` badge explains itself (tooltip with the two books' numbers).
- [ ] Gate: `npm run build`; phone rules in `mobile.css` only.

## Phase T5 — intake + ops `[ ]`

- [ ] Telegram intake: a message to the bot (`/tip <text>` or a bare forward) lands in
      `ingest_manual` with source = the configured per-chat source name.
- [ ] Email webhook auth: replace the single shared header key with an HMAC signature
      (keep the old key as a deprecated fallback for one release).
- [ ] Repeat-mention conviction: decide display-only vs auto-bump (default: display-only;
      log the decision in PLAN.md §4).
- [ ] `npm run mobile-audit` pass over the Tips page.
- [ ] Practice-soak checklist before any tip source leaves shadow for real money:
      20+ scored tips, positive armed-book expectancy, the engine team's Alpaca-paper
      chaos gate green, and the per-arm live acknowledgement flow tested once end-to-end.

## Decisions taken here

- Per-tip vehicle rule (above) — one rule, both books, no blending.
- Immediate book holds options WITHOUT a premium bracket (buy-and-hold counterfactual;
  expiry settlement closes it); the armed book is where managed exits live.
- Shadow arms auto-acknowledge `app_managed` overnight options; real money never does.
- `entry_fallback="shares"` is the tip default (a blocked contract still expresses the
  idea; the fallback is journaled and visible on the trade).
