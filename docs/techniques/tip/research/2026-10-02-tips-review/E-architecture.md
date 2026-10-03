# E. Tips: one method, two books (Practice + live IBKR) — architecture survey

Survey of `C:/Cursor/zargar` at `027ea341` (0.8.58). Read-only: nothing was edited or run.
Paths are relative to `backend/zargar/` unless they start with `frontend/` or `docs/`.

**What the owner asked for:** Tips runs all the time, feeding the Practice (sim) book and a live IBKR book together.
Each book has its own budget and caps. The top-bar mode toggle only changes what is displayed.

**What the code does today:** Tips feeds exactly ONE book. `trading.mode` is both the view and the order-routing gate.
`docs/techniques/tip/LIVE-IBKR-RUNBOOK.md` (Go-live step 3) says it outright: "The Practice book stops receiving Tips
ideas."

---

## 1. How Tips picks the book today

### 1.1 Tip-time proposals: `ProposalService.create_from_signal`

- `approvals/proposals.py:518`
  `pid = techniques.tip.default_portfolio or trading.default_portfolio`. If that book is missing it falls back to the
  first `sim` book (`:519-524`). This is ONE scalar. A signal produces at most one proposal, in one book.
- The book is used for:
  - budget: `_tip_budget(policy, pid, …)` at `:527`;
  - vehicle policy: `policy_kind(settings, pf)` at `:627` (shares-first) and `:804` (share substitution);
  - the spread live refusal at `:575` and the single-leg live refusal at `:861`;
  - geometry: `_pre_entry_geometry(pid=…)` at `:792`;
  - preflight caps: `:839-859`;
  - superseding older pending cards for the same contract **in that pid**: `:870-888`.
- It sets `signal.status = "proposed"` on the signal row (`:929`). The function returns ONE `pdict`. It also starts
  the entry study (`:936`) and the card alert (`:937`), both per proposal.
- Callers:
  - main intake: `signals/service.py:2882`;
  - parked-recovery sweep: `signals/service.py:3683`.

  Both take a single proposal and then run the auto-approve block on it.

### 1.2 Armed (at-level) plans: `techniques/tip/runner.py`

- `arm_from_analyst` (`runner.py:441`) uses the same scalar resolution as 1.1 (falls back to the first sim book) and
  builds ONE `ArmConfig` with `portfolioId: pid` (`:456`).
- **One-plan-per-tip index:** `live_run_for_signal(signal_id)` (`runner.py:589-596`) is keyed by **signalId only**.
  - `arm_signal` refuses a second arm, or replaces the first when `replace=True` (`:322-329`).
  - `arm_from_analyst` always passes `replace: True` (`:466`).
  - `_armed_today` (`:656`) and `_expire_signal_if_dead` (`:181-193`) use the same index.
- **Pre-existing collision:**
  - The morning shadow arm (`arm_shadow`, `:479-501`, into the per-source "armed" shadow book) shares this
    signal-keyed index with the real analyst arm.
  - An analyst arm therefore *disarms* the shadow-book plan for the same signal.
  - A live analyst plan makes the morning loop skip the shadow arm.
  - Fan-out across books would hit the same collision.
- Fire-time proposals: `emit_proposal` → `create_from_armed_fire(portfolio_id=ap.config.portfolio_id)`
  (`runner.py:195-219`, `proposals.py:394`). This path is already per book, because the plan carries its own pid.
- **Arming on a live book is blocked in practice:**
  - `validate_config` (`execution/planrunner.py:1279-1286`) needs `rt("allow_live_auto")`, a per-arm
    `cfg.allow_live` acknowledgement and `trading.mode == "live"`.
  - `arm_from_analyst` never sets `allowLive`, so an at-level take on a live book raises.
  - The intake catches that and falls back to the proposal lane (`signals/service.py:2856-2861`). The runbook's
    statement "At-level plans do NOT arm on live" is accurate, but the mechanism is the missing ack, not only the
    shared `technique.arm.allow_live_auto` key.

### 1.3 Adoption: `techniques/tip/lifecycle.py:726 adopt_when_filled`

- Works per proposal and per order. The position lands in `proposal.portfolioId`.
- Nothing in adoption assumes a single book, so fan-out adoption works as it is.

### 1.4 Shadow books

- `models.py:54-68`: `Portfolio.kind` is `live|paper|sim|shadow`. `book` is `immediate|armed|ownbook` for shadow
  rows.
- `SignalsService.shadow_portfolio(source, book)` (`signals/service.py:3059-3081`) creates one book per source per
  lane.
- The immediate book trades every verified/shadow signal (`_shadow_execute`, `signals/service.py:2720-2726`). The
  armed book is the morning loop (`runner.py:503-542`).
- RiskGate exempts shadow books from:
  - the duplicate check (`risk.py:482`);
  - the daily-loss halt (`risk.py:492`);
  - `_tip_budget` gating (`proposals.py:269`).

### 1.5 Can one signal already create proposals in several books?

- **Not as real proposals.** It already lands in up to three books: the immediate shadow book (always), the armed
  shadow book (morning loop), and ONE proposal/arm in the default book.
- So "one signal → several books" already exists, but only for research books. They are hard-wired, not
  configurable, and they are not proposals.

---

## 2. What `trading.mode` does today

### 2.1 Backend

| Where | What it does |
|---|---|
| `settings_service.py:23,47,699-792` | Two values: `practice` and `live`. Aliases fold `paper` into `live` and `dry_run`/`sim` into `practice`. |
| `orders.py:312-343` (single orders) | **Routing gate.** `practice` routes only to `{sim, shadow}`; `live` routes to `{sim, shadow, paper, live}`. Reduce-only exits are exempt (`:336-340`). **Live mode does not stop sim books**: Practice keeps filling in live mode. Practice mode blocks live entries. |
| `orders.py:440-447` (native multi-leg) | The same gate, **without** the reduce-only exemption. |
| `execution/planrunner.py:1269-1272` | In practice mode, a *defaulted* live/paper account is silently swapped for the first sim book. |
| `execution/planrunner.py:1285-1286` | An auto arm on live/paper raises unless mode is `live`. |
| `execution/planrunner.py:1227` | `"workspace"` is stamped into the armed summary (read by `NowView`). |
| `desk.py:221-222` | `ledger()` follows the mode: live = `live/paper` books, practice = `sim`. |
| `technique/service.py:2025` | `tradingMode` is exposed to the ArmDialog. |
| `approvals/telegram.py:220` | The mode is shown in the Telegram status. |
| Options Cartel (another team's code) | Mode is used as an arming gate: `controller.py:139`, `execution.py:133`, `runtime.py:130`. It also picks the preparation scope: `preparation_scope.py:15`. |
| Tips | Tips itself never reads `trading.mode`. It depends on the mode only through the order gate and `validate_config`. |

### 2.2 Frontend

- **The mode is the workspace.** `frontend/src/lib/workspace.ts:8-9,31-33`: `useWorkspace()` reads
  `settings["trading.mode"]`. `workspaceOf(kind)` maps `live`/`paper` to live and everything else to practice.
- **Toggle:**
  - `components/TopBar.tsx:69-81` writes `trading.mode` with `PATCH /api/settings` (there is a confirm dialog for
    `live`).
  - The phone tab bar does the same: `components/TabBar.tsx:83-93`.
  - The header comment (`TopBar.tsx:21-22`) says the switch "scopes every account-shaped view AND gates order
    routing".
- **What the workspace filters:**
  - `AccountSelect.tsx:65`, `Blotter.tsx:66`;
  - `ArmedPage.tsx:47,519`, `ArmDialog.tsx:89,106,299`;
  - `DashboardPage`, `TechniquePage`, `ArmedTab`;
  - the cartel pages;
  - `TopBar.tsx:62-64` counts "armed in the other workspace";
  - `OrderTicket.tsx:39` and `OptionTicket.tsx:31` read the mode directly.
- **The Tips pages do not use the workspace at all.** `pages/InboxPage.tsx` has no `useWorkspace` call, so tips,
  proposals and analyst runs are book-agnostic. The only Tips live control in Settings is `SettingsPage.tsx:604`
  (`techniques.tip.allow_live_auto`).

---

## 3. Budgets and caps: which are global and which are per book

The table shows the **knob** (a global setting) and the **scope it is judged on**.

| Knob | Where it is read | Judged per |
|---|---|---|
| `techniques.tip.budget_per_tip` (+ per-source `sources.<n>.budget_per_tip`) | `signals/sources.py:26,65`; `proposals.py:267` | source (global value) |
| `techniques.tip.reserve_slots` / `min_budget` (glide = min(budget, free cash / slots)) | `proposals.py:273-283` | **book** cash, global knob |
| `techniques.tip.max_book_exposure_pct` / `max_name_exposure_pct` | `proposals.py:285-294` | book, global % |
| `techniques.tip.live_capital_cap` | `proposals.py:295-306` (only when `kind in (live,paper)`) | each live/paper book, ONE global $ |
| `techniques.tip.max_open_positions` | `proposals.py:307-313` | book, global count |
| per-source `max_open_tips` / `budget_open_max` | `proposals.py:314-328` (`_source_open(pid, …)`) | source **within the book** |
| `techniques.tip.max_premium_per_tip`, `max_contracts_per_tip` | `proposals.py:211-217,383-391` | tip |
| `techniques.tip.lotto_budget`, `lotto_max_per_source_day` | `proposals.py:535-545,940-957` | source per book per day |
| geometry risk budget (`risk_budget_per_tip` or `risk_pct` × book equity) | `geometry.py:95-100`; `_pre_entry_geometry` | **book** equity |
| `risk.daily_loss_halt_pct` (3%) | `engine.py:786-809`; `risk.py:494` | **each book**, one global % (`risk.daily_loss_halt_scope=portfolio`) |
| `techniques.tip.daily_loss_halt_pct` (10%) | `planrunner.py:2050-2072` | technique × book (armed plans only) |
| per-book PAUSE | `engine.py:578-615`; `risk.py:280,526` | **book** (truly per book, survives restarts) |
| `risk.max_position_notional` / `max_position_pct` / `max_gross_exposure_pct` / option premium caps | `risk.py:213-226,393,444-459` | global value; the % ones scale with book equity |
| `risk.max_orders_per_minute` | `risk.py:468-469` | **GLOBAL across all books** (a fan-out doubles the count) |
| `risk.max_day_notional_per_technique` / `_per_tag` | `risk.py:428-429`, `_exposure_keys` `:182-189` | **technique-wide, not per book** (Practice would eat live's day notional) |
| duplicate window | `risk.py:474-486` | book (keyed by portfolio since 2026-08-29) |

**Conclusion:** every money knob is a single global value. Some are judged against the book's own cash or equity, but
nothing can say "Practice $1,000 per tip, live $500 per tip, live at most 3 open".

---

## 4. Live gates and how a live book differs from Practice today

### 4.1 Pure gates in `approvals/proposals.py`

- **`policy_kind`** (`:19-31`): with `techniques.tip.live_parity` on, an IBKR live/paper book is treated as `"sim"`
  for *policy*. That means shares-first (`:57-61`), substitution (`:64-74`), the geometry gate (`_geometry_scope`,
  `:1085-1096`) and the source-exit mirror (`signals/service.py:2177-2180`). SnapTrade books are never treated this
  way.
- **`live_vehicle_refusal`** (`:34-47`): `techniques.tip.live_shares_only` (default True) refuses an OPT or SPREAD
  vehicle on a live/paper book, journaled `TipLaneDecided lane=refused` (`:575-578,861-864`).
- **`live_capital_cap`** (`:295-306`): see §3.

### 4.2 Auto-approve in `signals/service.py:2905-2999`

- `live_ok = kind != "live" or techniques.tip.allow_live_auto` (`:2908-2909`). **A `paper` book self-approves without
  `allow_live_auto`.** The runbook intends this ("the same on PAPER"), but the check tests `kind` rather than an
  explicit per-book flag.
- `unattended = techniques.tip.unattended and kind != "live"` (`:2915-2916`). On live, skip/watch cards *wait* for a
  person and are not declined.
- The gates run in this order:
  1. earned-auto trust (`source_trust`, `:2953-2961`);
  2. geometry review (`:2962-2964`);
  3. the integrity pause (`:2970-2980`).
- The recovery sweep repeats a smaller copy of this logic (`:3691-3702`). **That copy has no trust, geometry or
  integrity gate before `approve(via="auto")`.** The integrity and geometry checks are re-run inside `approve()`
  (`proposals.py:1838-1847,1918-1921`), but earned trust is not.

### 4.3 Other gates

- Approval (`proposals.py:1832+`): KB-06 `integrity.admission(portfolio_id=…)` for automated approvals. Human clicks
  get readiness plus a fingerprint check.
- Integrity scope (`techniques/tip/integrity.py:61-65`): `default_scope` = `techniques.tip.default_portfolio` only.
  With two books, incidents are scoped to whichever book is the "default". A live-book defect could end up scoped to
  Practice, or the other way round.
- Arm gates: `planrunner.py:1279-1286` (see §1.2).

### 4.4 Summary: live book vs Practice today (with parity on)

Same analyst, same policy, same geometry, same mirror. The live book differs in:

- shares only;
- the $ cap;
- the venue GTC stop;
- skip/watch cards wait instead of being declined;
- no at-level arms;
- it needs `trading.mode=live` to route at all.

---

## 5. Design: binding a method to accounts

### 5.1 The setting

A new key in `settings_service.DEFAULTS`, so it is journaled and editable in the UI:

```jsonc
"techniques.tip.books": [
  { "portfolioId": "<Tips Practice 09-28>", "role": "practice", "enabled": true,  "primary": true,
    "mode": "auto", "budgetPerTip": 1000, "maxOpenPositions": 7, "capitalCap": 0,
    "reserveSlots": 3, "minBudget": 500, "armAtLevel": true },
  { "portfolioId": "<Tips IBKR Live>",     "role": "live",     "enabled": false, "primary": false,
    "mode": "auto", "budgetPerTip": 500,  "maxOpenPositions": 3, "capitalCap": 3000,
    "reserveSlots": 3, "minBudget": 300, "allowLiveAuto": false, "armAtLevel": false,
    "sharesOnly": true }
]
```

- **Empty list = today's behaviour.** The code synthesises one binding from `techniques.tip.default_portfolio`, so the
  change is backward compatible and rollback is a single PATCH.
- **Validator** (in `settings_service.set`, next to the `trading.mode` check at `:789`):
  - the portfolio exists and is not archived;
  - `role=live` requires `kind in (live, paper)`;
  - `role=practice` requires `kind == sim`;
  - shadow books are never allowed;
  - exactly one `primary`;
  - no duplicate pids.
- **Resolution order for every per-book knob:** binding field → `techniques.tip.<key>` → `execution.<key>`. This is a
  pure helper `techniques/tip/books.py::resolve_books(settings, positions) -> list[Binding]` plus
  `knob(binding, key)`. It mirrors `PlanRunner.rt()`.
- **`primary`** is the book used for the analyst's sizing context, scorecards, trust and retros (see the risks in
  §5.4). It defaults to the practice role.

### 5.2 Flow: appraise once, fan out the rest

1. Intake, verification, shadow books and the **analyst appraisal run ONCE per signal** (`signals/service.py:2721-2812`,
   unchanged). The opinion is written to `extraction.analyst`, as now.
2. Lane decision, once:
   - **take + at_level**: `arm_from_analyst` loops over the bindings where `armAtLevel` is true. A live binding also
     needs `allowLiveAuto`, `allowLive=true` on the config, and the routing gate (§5.3).
   - **otherwise**: `create_from_signal` loops over the enabled bindings.
3. **Per book:**
   - vehicle policy (`policy_kind`, `live_vehicle_refusal`);
   - budget (`_tip_budget` with binding overrides);
   - **the qty rescaled to that book** (see the risk in §5.4);
   - geometry against that book's equity;
   - preflight;
   - supersede;
   - Proposal row with `context.book = {role, primary, bindingRev}` and `context.fanOutGroup = signal.id`.
4. **Per proposal:** the auto-approve decision is evaluated independently, with that book's gates. One book's refusal
   or exception never blocks the other book.
5. Adoption, the manager, venue stops and exits run per position, as now.

### 5.3 The mode toggle becomes a view

- **Split the two meanings of `trading.mode`:**
  - **routing:** a new server key `trading.live_routing` (bool, default False, journaled, confirmed in the UI), or
    derive it from "some enabled binding has role=live". Recommendation: an explicit master switch **and** a per-book
    `enabled` flag. A live or paper book routes an entry only if the master switch is on AND the book is bound and
    enabled (Tips) or explicitly armed (other desks).
  - **view:** a client-side `ui.workspace`, held in the store and persisted to `localStorage`, with try/catch. It is
    never a server gate.
- **Keep `trading.mode` readable for the other desks** (Options Cartel uses it as an arming gate). Migration: on
  load, `trading.live_routing := (trading.mode == "live")`. Then move each *gate* reader to `live_routing`, and give
  each *view* reader a `?workspace=` query parameter. Cartel's own reads should be changed by their team, or left on
  `trading.mode` and kept in sync. Keep the shared-engine diff small and log it in `docs/PLATFORM-RULES.md`.

### 5.4 Risks

| Risk | Where | Mitigation |
|---|---|---|
| **The analyst's quantity is copied to every book.** `qty_hint` (the analyst's `quantity`) wins over budget sizing. | `proposals.py:682-684` (`int(qty_hint) or floor(budget/…)`) and the share path `:713` | Per book: `qty = min(scale(qty_hint, book_budget / analyst_budget), budget-derived qty)`, then geometry. The analyst sized against the PRIMARY book (`analyst.py:768`). |
| Analyst context is single-book | `analyst.py:763-781` (`_expression_context` uses `default_portfolio` equity) | Use the primary binding. Optionally add one line listing the other books' budgets and caps (no extra cost). The appraisal stays once. |
| **Earned-auto trust counts each idea twice** | `signals/service.py:3754-3769` counts every closed non-shadow tip position | Count the primary role only, or dedupe by `fanOutGroup`. |
| **Retros run twice** (paid, and they write duplicate notes and rules) | `retro.py:241-276` retros every closed tip position | Retro only the primary book's position. Attach the sibling's outcome to the same retro as evidence. Tag the sibling `retro-done` with `retroOf`. |
| Unfilled retros / lane grading | `retro.py:402+` | Judge per idea, not per proposal. |
| Scorecards and outcome tools read one book | `tools/tip_scorecard.py:684-691`, `tools/tip_outcomes.py:67,520` | Use the `--book` default = primary binding. Add a `--role` flag. |
| Entry cohort / frozen capture | `cohort.py:522` (global budget); `signals/service.py:3003-3007,3705-3708` (`proposal=` single) | Pass the primary proposal plus a `books` list. One cohort row per idea. |
| Entry study runs twice | `proposals.py:936,1003-1072` | Run only for the primary book (or only for OPT, which live never has). |
| Card alerts double-page | `proposals.py:937,959-1001` | One alert per `fanOutGroup`. Prefer the live card, which is the one that waits for a person. |
| **Mirrored source exits** | `signals/service.py:2172-2203` iterates every open tip position | Already per book. This is desired: both books mirror. The live book is included only via `live_parity`; make that per binding (`mirror: true`). |
| **Analyst manage tools and follow-ups touch one book** | `analyst.py:721-744` (`_manage_guard` allows any non-shadow tip position) | Apply a management action to the whole `fanOutGroup` (trim / stop-tighten on both). Live may never be looser than Practice. Journal it per position. |
| One-plan-per-tip index | `runner.py:589-596,656,322-329`; `_signal_played` `:662-678` | Key by `(signalId, portfolioId)`. "Signal dead" = no live plan in ANY book. `disarm_plan` and `followup_close_disarms` act on every book. This also fixes the existing shadow-vs-analyst collision. |
| Integrity incidents scoped to the default book | `integrity.py:61-65` | Scope each incident to the pid of the order that produced it. `admission(portfolio_id)` already filters by scope (`:68-78`). |
| **Global order-rate cap** | `risk.py:468-472` (10/min across all books) | Fan-out plus shadow books plus exits can trip it in a burst. Exempt sim/shadow books from it, or key it per book (a shared-engine change: PLATFORM-RULES). |
| Technique day-notional shared across books | `risk.py:182-189,428-441` | Add `book:<pid>` to the keys, or key `tech:tip` per pid. |
| Recovery-sweep auto-approve skips the trust and geometry gates | `signals/service.py:3691-3702` vs `:2950-2980` | Refactor both into one `_decide_auto(proposal, row, binding)` helper before fanning out. |
| Paper book auto-approves without the live flag | `signals/service.py:2908`, `:3694-3695` | Use an explicit `binding.allowLiveAuto` for every live-role book, paper included. Global `techniques.tip.allow_live_auto` stays as the master switch. |
| Signal status / supersede | `proposals.py:870-888,925-930` | Supersede is already per pid. The status flips to `proposed` once (idempotent). |
| Hold study | `holdstudy.py:269,368-385` | Already grouped by book kind. Note that a parity live book reports `bookKind=live/paper`. |
| Mode toggle back to Practice traps nothing, but blocks live entries | `orders.py:340`; multi-leg gate `:443` has no reduce-only exemption | After the split, the view toggle cannot block anything. Add the reduce-only exemption to `:443` as well. |
| Divergent fills (live rests, Practice fills) | — | Expected. Report per book and never "reconcile" one to the other. |

### 5.5 Every code change needed

**Backend**

1. `settings_service.py`:
   - DEFAULTS: add `techniques.tip.books: []` and `trading.live_routing: False`;
   - a validator in `set()`;
   - a migration from `trading.mode` on load (near `:752-765`).
2. New `techniques/tip/books.py`: `resolve_books`, `knob`, `primary_book`. Pure, plus unit tests.
3. `approvals/proposals.py`:
   - split `create_from_signal` (`:506-938`) into `_create_for_book(…, binding)` plus a fan-out wrapper that returns
     `list[pdict]` (keep a `create_from_signal_primary` shim for old callers);
   - `_tip_budget` (`:254`) takes the binding (budgetPerTip, reserveSlots, minBudget, maxOpenPositions, capitalCap for
     any role);
   - rescale `qty_hint`;
   - `context.book` / `fanOutGroup`;
   - entry study and card alert only once per group;
   - `create_from_armed_fire` (`:394`) reads the binding from `ap.config.portfolio_id`.
4. `signals/service.py`:
   - `:2877-2999` and `:3679-3702` loop over the proposals through one shared `_decide_auto` helper with per-binding
     live gates;
   - `source_trust` (`:3740`): primary role only;
   - `_mirror_source_exit` (`:2177-2180`): per-binding `mirror` instead of `policy_kind`;
   - the cohort call passes the group.
5. `techniques/tip/runner.py`:
   - `arm_from_analyst` (`:438-467`) loops over the bindings (live: `allowLive` from the binding);
   - `live_run_for_signal` / `_armed_today` / `_signal_played` / `_expire_signal_if_dead` / `arm_signal` replace
     logic are keyed `(signal, pid)`;
   - `emit_proposal` unchanged.
6. `techniques/tip/analyst.py:768`: use the primary binding. `_manage_guard` / manage tools act on the group.
7. `techniques/tip/integrity.py:61-65`: per-pid scope.
8. `techniques/tip/retro.py:219-276,402+`: primary only; sibling evidence.
9. `orders.py:312-343,440-447`: replace the mode gate with `live_routing` plus a per-book enablement predicate
   (`engine.book_routable(pid)`). Keep the reduce-only exemption in both.
10. `execution/planrunner.py:1269-1286`: same predicate instead of `trading.mode`. `:1227` workspace becomes a request
    parameter.
11. `desk.py:221`: `ledger(workspace=…)` from the query string. `technique/service.py:2025`: expose `liveRouting`.
12. `risk.py:182-189,468`: per-book keys for day-notional and order rate (a PLATFORM-RULES entry).
13. Tools: `tip_scorecard.py`, `tip_outcomes.py` default to the primary binding.
14. API:
    - `GET /api/tip/books` (resolved bindings with live cash, open count, cap room, gates);
    - journal `TipBookFanOut {signalId, books:[{pid, role, outcome: proposed|refused|skipped, reason}]}` for each
      signal, so the record shows why a book got nothing.
15. Docs: `docs/techniques/tip/README.md`, `LIVE-IBKR-RUNBOOK.md` (go-live step 3 changes: "Practice keeps running"),
    `docs/PLATFORM-RULES.md` (routing-gate split, risk key change).

**Frontend**

1. `lib/workspace.ts`: `useWorkspace()` reads the client view state (`ui.workspace` in the store, persisted). Update
   the header comment. Add `useLiveRouting()` for the routing state.
2. `components/TopBar.tsx:69-81`, `components/TabBar.tsx:83-93`: the toggle sets the view only (no PATCH, no
   real-money confirm). Add a separate, confirmed "Live routing ON/OFF" indicator next to HALT.
3. `OrderTicket.tsx:39`, `OptionTicket.tsx:31`, `ArmDialog.tsx:106,299`, `ArmedPage.tsx:102,161`, `App.tsx:97`:
   - gate checks use `liveRouting`;
   - labels and filters use the view;
   - `NowView` / `DashboardPage` / ledger pass `?workspace=`.
4. Tips page (`pages/InboxPage.tsx`):
   - proposals and positions filtered by the view (today unfiltered);
   - each card carries a book chip ("Practice" / "LIVE");
   - a sibling link ("also in LIVE: filled 12 sh / refused: cap").
5. `SettingsPage.tsx:604` area: a **Tips books** editor (account picker limited to the role's kinds, budget, max
   open, $ cap, enabled, live-auto acknowledgement with a confirm). It writes `techniques.tip.books` through
   `PATCH /api/settings`.
6. `types.ts`: `TipBookBinding`, `context.book`.
7. `changelog.ts` plus the four-way version bump. Run `npm run build`, `check-release` and `mobile-audit`.

### 5.6 Test points

**Pure / unit**

- `resolve_books`: empty list falls back to `default_portfolio`; the validator rejects role/kind mismatch, shadow
  books, two primaries and archived books.
- Knob resolution order.
- Qty rescale: an analyst qty of 20 at a $1,000 primary budget gives the live book at $500 a qty ≤ 10 and within
  `capitalCap`.
- `live_vehicle_refusal` per binding; the `sharesOnly` override.

**Integration (sim engine + paper fake)**

- One verified signal with two bindings → exactly one analyst run (`TipAnalystRun` count = 1) and two proposals with
  distinct pids and a shared `fanOutGroup`.
- A live binding that is disabled or has `allowLiveAuto=false` → the Practice proposal auto-approves and the live
  proposal is pending (or not created), with `TipBookFanOut` recording why.
- The live cap is reached → the live book is refused on the record and Practice still proposes.
- A per-book pause / daily-loss halt on live → Practice unaffected, and the reverse.
- The view toggle to Practice → a live entry still routes (`live_routing` on). `live_routing` off → the live entry is
  REJECTED_RISK and live exits still pass (both the single-order and the mleg path).
- At-level take → two plans `(signal, pid)`. Disarming one leaves the other. The morning shadow arm is no longer
  disarmed by the analyst arm. Horizon expiry expires the signal only when both are dead.
- Source "close" follow-up → mirrored on both positions. An analyst manage action applies to the group.
- Retro sweep → one retro per group. `source_trust` counts one per idea.
- Integrity incident on a live fill pauses live only.
- Order-rate / day-notional: a burst of fan-out plus shadow orders does not starve the live entry.
- Recovery sweep (`_recover`) fans out the same way and applies the trust and geometry gates.

**Chaos / existing suites stay green**

- `tests/test_position_chaos.py`;
- `tests/test_platform_separation.py` (experiments never fan out);
- `tests/test_ibkr_adapter.py`;
- `tests/test_em_review_*.py`, `tests/test_codex_*.py`.

**UI**

- `mobile-audit` with a minted session: the toggle changes the lists and no PATCH is sent.
- The routing indicator is visible on phones next to HALT.

### 5.7 Rollout

1. Ship with `techniques.tip.books=[]` (no behaviour change). Then add the Practice binding (identical behaviour).
2. Add the paper IBKR binding with `enabled=true`, `live_routing=true` and a paper session with both books running.
3. Swap paper → live binding, with `allowLiveAuto=true` as the user's explicit go.

Rollback at any step = disable the binding, or `trading.live_routing=false`. Exits keep running.
