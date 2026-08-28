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

## Phase T1 — the expression module + the immediate book `[x]` *(built 2026-08-27)*

- [x] `techniques/tip/express.py` — pure-ish picker: `tip_is_option(sig)` (the vehicle
      rule) and `pick_tip_contract(engine, sig, policy, *, spot)` →
      stated strike+expiry → exact OCC (existence-checked against the chain; graceful
      "contract not listed" error), else DTE-window just-OTM via the shared chain client
      (`pick_for_setup` with an expiry window, not EM's weekly/0DTE policy); short tips →
      puts with the `min_strike` mirror (no strike below the downside target). Returns the
      contract dict shape the runner already consumes (symbol, bid/ask/mid, dte,
      spreadPct, warnings).
- [x] `signals/service._shadow_execute` v2: option tips buy the CONTRACT in the immediate
      book — `OrderIntent(sec_type="OPT", symbol=<unpadded OCC>, qty=size_by_budget(
      policy.budget_per_tip, ask, multiplier=100))`, `engine.ensure_symbol(occ)` +
      `options.track` so sim quotes flow; **no bracket** (tip targets are underlying
      prices — meaningless as premium brackets): the immediate book is buy-and-hold to
      thesis end, marked to market, settled by `OptionsService.settle_expired` (shadow is
      a practice-kind portfolio). Shares tips keep today's behavior (bracket included).
      Pick failure (no chain, not listed) falls back to shares with a journal note —
      the book must never silently skip a tip.
- [x] Tests (`test_tip_express.py` + rig): vehicle rule truth table; stated-contract pick
      vs DTE-window pick vs short-put mirror (fixture chain via `use_client` mock);
      immediate-book option order carries OPT/OCC/tags + budget sizing (4 contracts on a
      $500 budget at $1.15 ask); fallback-to-shares on a dead chain with the reason
      recorded on the signal. *(Bonus find: the fixture's first draft had an 18% spread
      and the runner's wide-spread gate correctly forced the shares fallback — the gates
      compose with tips unchanged.)*

## Phase T2 — the armed book goes options `[x]` *(built 2026-08-27)*

- [x] `TipRunner.arm_signal`: per-tip instrument — the vehicle rule decides
      `ArmConfig.instrument` (explicit config still overrides). `techniques.tip.instrument`
      stays `shares` as the FALLBACK for non-option tips (no `auto` value needed — the
      rule lives in `arm_signal`, the only tip arming path).
- [x] `TipRunner.pick_contract` hook: delegates to `express.pick_tip_contract`; the
      runner's gates apply unchanged; `entry_fallback="shares"` is the tip default.
- [x] **Budget cap on contracts** — built as a small platform extension instead of hook
      state: `ArmConfig.premium_budget` ($, 0=off), applied inside `_size_contracts`
      (floors at 1 with a warning when one premium exceeds the budget; the RiskGate
      premium caps still backstop; fixed `contracts` still wins). Logged in
      PLATFORM-RULES §4.
- [x] Handoff v2 (options): OPT leg (multiplier 100, avgFill=premium), app_managed +
      auto-ack (a live arm already carried the per-arm allowLive acknowledgement),
      `premium_stop_pct` + `dte_close` in the policy, entry/risk in underlying terms.
- [x] Short tips end-to-end rig test (`test_short_tip_puts_end_to_end`): put arm →
      reject-touch fire → put fill → handoff with the mirrored stop above entry —
      the armed book's short-side measurement gap is CLOSED (PLAN.md §4 caveat lifted).
- [x] Tests (tip rig): armed option tip fires → stated-strike pick → premium-budget
      clamp → sim fill via `quotes.on_quote` → OPT ManagedPosition with premium_stop +
      dte_close + app_managed ack; dead-chain fallback to shares.
- [x] **Both-books gate:** T1 and T2 built and land in one merge.

## Phase T3 — R-based outcomes + scorecard depth `[x]` *(built 2026-08-28)*

- [x] Tip runs enter the outcomes loop: `score_pending` already selects every
      `mode="plan"` run regardless of technique — the real gap was PARITY: the scorer
      replays with `run.config.thresholds`, so a tip run without a snapshot would replay
      under EM's rules (volume floor, prime-only windows) and contradict its own live
      tracker. Fixed at the source: `arm_signal` snapshots the TIP MarketRules into
      `config.thresholds` (`test_tip_run_snapshots_its_rules`).
- [x] Scorecard v2: `books.armed.outcomes` per source — scored / fired /
      never-triggered / win rate / avg R / **expectancyR** (an unfilled tip counts as
      0R: it measures the strategy per tip taken). Surfaced as an `E[R] +x.xx · n scored`
      line under the Level-touch column.
- [x] `barCleared` flips to expectancy-in-R once ≥ `scorecard_min_n` outcomes are
      scored (`barBasis: "expectancyR"`); until then the $-P&L rule stands
      (`barBasis: "pnl"`). **Decision:** `tipTimeEarned` stays a $-vs-$ book comparison —
      the immediate book is market orders with no runs, so it has no R to compare.
- [x] Tests: seeded runs/outcomes → expectancy math; the bar flips on R (winning and
      losing sources both covered).

## Phase T4 — Tips page v2 `[~]` *(redesign built 2026-08-28; editor + T3 line pending)*

- [x] **Full page redesign** (user: "exactly the crude page we had on day 1 — redesign"):
      tabs replace the container pile (**New tip | Tips | Sources | Inbox**), pending
      proposals ride above the tabs as an attention strip (they expire in minutes), and
      the **composer is the hero** — a centered card with clipboard screenshot paste,
      drag-and-drop, a full-width source box that defaults to **Auto-detect** (datalist
      of known sources from `GET /api/signals/source-names`), and an inline result card
      after extraction (status/park explanation, prices, vehicle chip from
      `shadowExpression`, flow/calendar context, arm button, duplicate notice). Quiet
      text empty states replace the illustration. Sidebar deduped: the top-level
      "Signals" entry is gone (Techniques ▸ Tips is the one home; the proposals badge
      moved onto it); the phone TabBar is untouched. Verified visually on a dedicated
      server (own DB, port 8421, screenshots).
- [x] **Source auto-detection** (user): `ExtractionResult.source_hint` — the extractor
      reads attribution out of the content itself (channel name, poster's handle,
      newsletter masthead; screenshots included via the transcript) and
      `_resolve_source` matches it punctuation/case-insensitively against the registry +
      every source ever seen ('#alpha-alerts' → 'Alpha Alerts'); a new hint becomes a
      new source; an explicit name is never overridden; no hint → 'unknown'. Recorded on
      the content row (`sourceDetected`/`sourceHint`/`sourceMatchedExisting`) and
      returned to the composer ("source: X (detected from the content)").
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
