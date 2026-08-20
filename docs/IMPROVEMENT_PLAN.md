# Zargar v0.3 — "Improve by 200%" plan

Born from first real-world morning with live accounts (2026-08-20). Decisions
made with the user: daily-loss halt applies **only to zargar-traded
portfolios** (passive drift warns, never halts); trading modes collapse to
**Practice | Live**; **light theme becomes the default** (dark stays);
UI is **real-money-first** with practice clearly compartmentalized.

Mark subtasks `[x]` as they're completed. Each phase ends with the gates
green (`pytest` 88+, `npm run build`) and a commit.

---

## Phase 1 — Kill-switch trust & safety [ ]

The auto-halt fired on a normal red day because Webull CASH drifted −3%
intraday with zero zargar orders. Fix the semantics, then make every halt
explain itself.

- [ ] Daily-loss monitor only evaluates portfolios with zargar-originated
      orders placed **today (ET)** — query `orders` per portfolio per cycle
      (cache per day); shadow stays excluded as today.
- [ ] Passive drift ≥ threshold on other portfolios → new journal event
      `DailyDriftWarning` (once per portfolio per day) + `system` bus message
      → amber dismissible banner in the UI ("Webull CASH −3.1% today — market
      drift, trading not halted") linking to Portfolios. Never halts.
- [ ] Day-start equity anchor correctness: don't memoize a portfolio's
      day-start equity until live quotes exist for its position symbols
      (avgCost-fallback baselines cause false positives); re-anchor when the
      quote feed first connects.
- [ ] Halt banner UX: show reason + "view in journal" link (Journal
      pre-filtered to the risk group); RESUME opens a confirm dialog stating
      what resume does and what caused the halt.
- [ ] Halt banner layout bug: `.app` grid is `48px 1fr`, so the banner (a
      third grid child) absorbs the `1fr` leftover and balloons on short
      pages, shoving the sidebar around per page. Fix rows to
      `48px auto 1fr` + give the banner one fixed height everywhere — no
      layout shift when switching pages.
- [ ] Journal noise: `BrokerSync` currently journals every 15-min cycle even
      when nothing changed. Journal only when the diff is non-empty (cash
      delta or positionsChanged); quiet cycles publish to the bus only.
- [ ] Portfolio cards get a "today" P&L% chip so daily state is visible
      before any threshold is near.
- [ ] Tests: monitor skips passive portfolios; drift warning journaled once;
      traded portfolio still halts; anchor waits for quotes; no-change sync
      does not journal.

## Phase 2 — Money accuracy: currencies & FX [ ]

Verified bug (2026-08-20): USD positions inside CAD accounts are summed at
face value with no FX — Webull CASH shows C$15,286 while SnapTrade's own
FX-converted total says C$20,025 (SPCX is USD: 60 × $131.98 counted as CAD,
~C$2,900 missing; TQQQ same story in Wealthsimple, ~C$1,100 missing).

- [ ] Positions carry their own currency end-to-end: sync already parses it;
      store it on the Position row + PositionKeeper in-memory dicts + wire
      shape (camelCase `currency`).
- [ ] FX rate source: Yahoo pairs (`USDCAD=X`, `CADUSD=X`) polled alongside
      quotes (they ride the existing feed as watched symbols); a tiny
      `fx.convert(amount, from, to)` helper with rate age guard.
- [ ] `PositionKeeper.equity()` / `gross_exposure()` / market values convert
      each position into the **portfolio's base currency** before summing;
      risk caps therefore operate in account currency correctly.
- [ ] Blotter/portfolio/provider views label position market values in their
      native currency and account totals in account currency.
- [ ] Cross-check on every sync: computed equity vs SnapTrade's
      `balance.total` (their FX-converted number); deviation > ~2% raises a
      journaled `BrokerSyncMismatch` warning surfaced in the UI.
- [ ] Dashboard net worth: per-currency totals stay primary; add an optional
      FX-blended headline ("≈ C$32.1k total") using the live rate, clearly
      marked approximate.
- [ ] Tests: USD position in CAD account equity math, FX helper with stale
      rate, mismatch warning fires, blended total.

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
