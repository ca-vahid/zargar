# Zargar v0.3 — "Improve by 200%" plan

Born from first real-world morning with live accounts (2026-08-20). Decisions
made with the user: daily-loss halt applies **only to zargar-traded
portfolios** (passive drift warns, never halts); trading modes collapse to
**Practice | Live**; **light theme becomes the default** (dark stays);
UI is **real-money-first** with practice clearly compartmentalized.

Mark subtasks `[x]` as they're completed. Each phase ends with the gates
green (`pytest` 88+, `npm run build`) and a commit.

---

## Phase 1 — Kill-switch trust & safety [x]

The auto-halt fired on a normal red day because Webull CASH drifted −3%
intraday with zero zargar orders. Fix the semantics, then make every halt
explain itself.

- [x] Daily-loss monitor only evaluates portfolios with zargar-originated
      orders placed **today (ET)** — `Engine.check_daily_loss` +
      `_traded_today()` (DRY_RUN orders don't count); shadow still excluded.
- [x] Passive drift ≥ threshold → `DailyDriftWarning` journal event (once
      per portfolio per ET day) + system bus `{"kind":"drift"}` → amber
      dismissible banner linking to Portfolios. Never halts.
- [x] Day-start equity anchor waits for live quotes on every open position
      (`PositionKeeper._quotes_ready`); no more avgCost-baseline anchors.
- [x] Halt banner: reason + "view in journal" link (pre-filters the risk
      group via `openJournal`); RESUME opens a confirm dialog showing the
      halt reason and what resuming does.
- [x] Banner layout: `.app` grid now `48px auto 1fr` with a `.banners` row;
      halt + drift banners are fixed 30px — zero layout shift across pages.
- [x] Journal noise: `BrokerSync` journals only when cash or positions
      actually changed; quiet cycles stay off the audit trail.
- [x] Portfolio cards show a "±x.xx% today" chip (`todayPct` on portfolio
      payloads + 30s equity snapshots).
- [x] Tests (4 new in `test_daily_loss.py` + sync-noise assertion): passive
      drift warns once & never halts; traded portfolio halts; DRY_RUN
      doesn't arm the halt; anchor waits for quotes; quiet sync not
      journaled. Suite: 92 passed.

## Phase 2 — Money accuracy: currencies & FX [x]

Verified bug (2026-08-20): USD positions inside CAD accounts are summed at
face value with no FX — Webull CASH shows C$15,286 while SnapTrade's own
FX-converted total says C$20,025 (SPCX is USD: 60 × $131.98 counted as CAD,
~C$2,900 missing; TQQQ same story in Wealthsimple, ~C$1,100 missing).

- [x] Positions carry currency end-to-end: broker-reported currency in the
      in-memory dicts + wire shape; derived from the symbol suffix
      (`fx.currency_for_symbol`) everywhere else — zero schema changes.
- [x] FX rates ride the quote feed: engine watches `USDCAD=X` on the Yahoo
      feed; `FxService.rate/convert` with a 6h age guard, inverse-pair
      fallback, and a conservative 1:1 fallback (undercounts, so risk caps
      bind sooner, never later). FX symbols skip bar aggregation.
- [x] `equity()` / `gross_exposure()` convert every position into the
      portfolio's base currency — risk caps now operate in account currency.
- [x] Blotter market values shown in the position's native currency
      (`C$`/`US$`); account totals in account currency.
- [x] Sync cross-check: computed equity vs SnapTrade's FX-converted
      `balance.total`; >2% deviation journals `BrokerSyncMismatch` (once per
      account per day) and shows a Δ pill on Dashboard + Portfolios.
- [x] Dashboard adds an "≈ C$… all currencies, live FX" blended headline,
      marked approximate, only when a live rate exists.
- [x] Tests (5 new): symbol currencies, direct/inverse/stale rates, the
      SPCX-in-CAD equity bug reproduced + fixed, gross exposure conversion,
      mismatch warning journaled once. Suite: 96 passed.

## Phase 3 — Trading modes: Practice | Live [ ]

Four confusing modes (Dry run / Simulation / Paper (IBKR) / LIVE (IBKR))
become two, venue-agnostic.

- [ ] `trading.mode` accepts `practice | live` only. Routing: practice →
      sim/shadow portfolios; live → all kinds (sim/shadow still fill on the
      SimExecutor; live/paper route to their venue — SnapTrade or IBKR).
- [ ] Migration on settings load: `dry_run`→`practice` (+ note), `sim`→
      `practice`, `paper`/`live`→`live`; journaled `SettingChanged`.
- [ ] Dry-run survives **only** as the per-order "validate only" checkbox
      (and the confirm dialog's pre-flight) — the mode rung disappears.
- [ ] IBKR paper folds into Live routing when the account arrives (kind
      `paper` routes to IBKR under live mode; no separate mode rung).
- [ ] TopBar: two-option select — Practice (default) and LIVE (styled
      dangerous, keeps the confirm dialog). Settings page options updated.
- [ ] RiskGate `market_hours` + routing-gate tests updated; engine tests
      migrated off `trading.mode=sim` strings.

## Phase 4 — Real vs Practice compartmentalization [ ]

Real money is the headline; the simulator is a clearly-labeled sandbox.
No mixed totals anywhere.

- [ ] TopBar equity chip → real net worth per currency (from the brokerage
      sync, e.g. "C$16.9k · US$0"), click → Dashboard. Separate small
      "practice" chip when a sim portfolio exists.
- [ ] Blotter: Real | Practice | All filter (defaults to Real when live
      accounts exist); portfolio names carry venue badges.
- [ ] Portfolios page: Real section first (brokerage panels), Practice below
      under an explicit "Practice environment" header with badge; equity
      chart splits into Real / Practice series groups.
- [ ] Dashboard: practice card visually distinct (badge + muted); recent
      activity rows badge real vs practice.
- [ ] Order ticket account selector grouped: "Real accounts" (with venue +
      currency) vs "Practice"; default follows trading mode (practice mode →
      practice account, live mode → last-used real account).
- [ ] Sim portfolio rename to "Practice" everywhere user-facing.

## Phase 5 — Broker identity: icons & naming [ ]

- [ ] Sync captures brokerage logo URLs from SnapTrade `authorizations`
      (`brokerage.aws_s3_square_logo_url` / `logo_url`) into
      `BrokerageAccount.meta` + the providers payload (`logoUrl`).
- [ ] `BrokerIcon` component: rounded `<img>` with graceful lettermark
      fallback (initials on brand-ish tint) — used in provider cards,
      Portfolios sections, ticket account selector, confirm dialog, TopBar.
- [ ] Account naming: "Webull (Cash)", "Webull (Margin)", "Wealthsimple
      (Personal · CAD)", "Wealthsimple (Corporate)" — account_type moves into
      brackets, no institution duplication, currency only when disambiguating.
- [ ] Rename-on-sync updates existing portfolio rows to the new pattern.

## Phase 6 — Light theme by default + polish [ ]

- [ ] Default `ui.theme` → `light` (respect an explicitly saved choice —
      only unset/default users flip).
- [ ] Light polish pass: surface/border/shadow tuning, chart readability
      (Highcharts pulls tokens — verify axis/tooltip/candle contrast),
      status pills, flash colors, halt/drift banners, watchlist rows,
      confirm dialog.
- [ ] Dark retested side-by-side; both pass the browser walk.

## Phase 7 — Navigation & discoverability [ ]

"Links that take me to places where I can see what's happening."

- [ ] Lightweight page context in the store (`setPage(page, ctx)`): Journal
      accepts a pre-filter (group/type/portfolio), Portfolios accepts a
      scroll-to provider.
- [ ] Halt/drift banners → Journal (risk filter). Provider cards → their
      Portfolios section. Position rows → Trade with symbol (keep) and
      portfolio context in the ticket. Journal aggregate ids → filtered view.
- [ ] Dashboard sync timestamp → refresh action; every EmptyState links to
      the exact page/setting that fixes it.
- [ ] Settings: group headers get one-line explainers; risk knobs get
      hover tooltips with concrete examples ("collar 5% = reject a limit
      more than 5% from last").

## Phase 8 — Verification & ship [ ]

- [ ] Backend suite green (existing + new Phase 1/2 tests).
- [ ] `npm run build` + grep gates (no emoji, no window.confirm, no bare
      useStore(), tokens only).
- [ ] Browser walk of all pages in light and dark; halt-drift scenario
      exercised end-to-end (simulate drift, see warning not halt).
- [ ] Screenshot review with the user; commit + push per phase.

---

### Known context for whoever implements

- The 2026-08-20 halt: `DailyLossHalt {lossPct: -3.001, portfolioId: Webull
  CASH}` at 08:20 ET — SPCX fell ~5% overnight; no zargar orders existed.
- The FX undercount: computed Webull CASH equity C$15,286 vs SnapTrade's
  FX-converted `balance.total` C$20,025 — the delta is SPCX's USD market
  value counted 1:1 as CAD. Use `balance.total` as the audit reference.
- The user's screenshots that triggered this plan were from a **cached old
  bundle** (pre-Dashboard); hard refresh shows the current UI. Cache-busting
  is handled by Vite hashes; the stale HTML came from the browser.
- Broker logos: SnapTrade serves brokerage logo URLs from S3; the app runs
  locally so hotlinking is fine, but cache the URL in meta and always render
  the lettermark fallback when the image errors.
