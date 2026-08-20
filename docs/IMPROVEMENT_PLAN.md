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

## Phase 3 — Trading modes: Practice | Live [x]

Four confusing modes (Dry run / Simulation / Paper (IBKR) / LIVE (IBKR))
become two, venue-agnostic.

- [x] `trading.mode` accepts `practice | live` only (set() validates);
      routing: practice → sim/shadow; live → everything (sim/shadow still on
      the simulator; live/paper route to their venue).
- [x] One-time migration on settings load (`MODE_ALIASES`): dry_run/sim →
      practice, paper → live; persisted + journaled `SettingChanged` with a
      migration note. set() also accepts the old aliases forever.
- [x] Dry-run is only the per-order checkbox + confirm pre-flight; the mode
      rung is gone (`intent.dry_run` short-circuit only).
- [x] IBKR paper folds into Live routing (kind `paper` under live mode).
- [x] TopBar: Practice | LIVE select (LIVE keeps the danger confirm);
      Settings options + hint updated; ticket header shows a mode pill.
- [x] Tests migrated: mode-alias coverage, order-level dry run, practice
      blocks live portfolios ("trading.mode=practice blocks"). 96 passed.

## Phase 4 — Real vs Practice compartmentalization [x]

Real money is the headline; the simulator is a clearly-labeled sandbox.
No mixed totals anywhere.

- [x] TopBar: real brokerage net worth per currency (click → Dashboard) +
      separate "practice …" chip (click → Portfolios); no more "Simulation:
      $…" masquerading as the headline.
- [x] Blotter: real | practice | all scope chips on every tab (defaults to
      real when brokerages are connected).
- [x] Portfolios page: "Real accounts" section (brokerage panels + IBKR
      placeholder card) then "Practice environment" section with badges;
      equity chart gains all/real/practice series-group chips.
- [x] Dashboard: PracticeCard is dashed/muted with a "simulated — not real
      money" badge; recent orders/fills rows carry real/practice pills.
- [x] Order ticket: Account selector grouped (Real accounts w/ currency vs
      Practice); default follows the mode — practice → practice portfolio,
      live → last-used real account (localStorage).
- [x] Sim portfolio renamed "Practice" (DB migration in seed + UI labels).

## Phase 5 — Broker identity: icons & naming [x]

- [x] Sync captures brokerage logo URLs from `authorizations`
      (`aws_s3_square_logo_url` → providers payload `logoUrl`).
- [x] `BrokerIcon` component: rounded logo `<img>` with deterministic
      lettermark fallback — used in Dashboard provider cards, Portfolios
      broker sections, and the real-money confirm dialog. (Native `<select>`
      can't render images, so the ticket keeps text + optgroups.)
- [x] Account naming via `_display_name`: "Webull (Cash)", "Webull
      (Margin)", "Wealthsimple Trade (Personal)" — type words move into
      brackets (broker-reported or inferred from trailing CASH/MARGIN/
      PERSONAL/… words), broker never duplicated; currency stays on the
      ccy chips.
- [x] Rename-on-sync migrates the existing portfolio rows automatically.

## Phase 6 — Light theme by default + polish [x]

- [x] Default `ui.theme` → `light` (DEFAULTS + frontend fallbacks; an
      explicitly saved choice in the settings table still wins).
- [x] Light polish: warmer bg (#f4f4f0), stronger borders/grid, darker ink
      scale for contrast; banners/pills/shadows already token-driven from
      Phase 1-5 work; charts pull tokens at build time.
- [x] Dark retested in the Phase 8 browser walk (both themes).

## Phase 7 — Navigation & discoverability [x]

"Links that take me to places where I can see what's happening."

- [x] Page context in the store: `openJournal(group)`, `openPortfolios
      (focusProviderId)` (smooth-scrolls to the provider section),
      `openTrade(symbol, portfolioId)` (one-shot ticket preselect).
- [x] Halt banner → risk-filtered Journal; drift banner → Portfolios;
      Dashboard provider cards → their Portfolios section; blotter position
      rows → Trade with the account preselected; Journal aggregate ids are
      clickable filters (filter matches aggregate ids too).
- [x] Dashboard sync timestamp lives inside the refresh button; EmptyStates
      (no brokerages / no real accounts / empty watchlist) link straight to
      Settings.
- [x] Settings: every panel head has a one-line explainer; risk knobs
      gained concrete hints (currency-of-caps, stale-quote behavior,
      gross-exposure definition).

## Phase 8 — Verification & ship [x]

- [x] Backend suite green: **96 passed** (was 64 at v0.1).
- [x] `npm run build` green + grep gates pass (0 window.confirm/prompt,
      0 bare useStore(), 0 emoji, 2 documented fire-and-forget catches).
- [x] Live browser walk on real data: Dashboard (real chips C$22,326 +
      practice chip, blended ≈C$36,105, Δ mismatch pills, broker sections),
      Trade (mode pill, grouped account selector, real-scope blotter with
      native-currency values), Portfolios (Real/Practice sections, 7-line
      equity chart with scope chips), Journal (halt banner deep-links to the
      risk filter), Settings. Light theme default verified (#f4f4f0), dark
      toggles live over WS, banner row fixed at 30px/banner with zero layout
      shift (grid 48px auto 1fr measured).
- [x] Drift scenario exercised END-TO-END against real accounts: threshold
      temporarily dropped to 0.005% → both real accounts journaled
      `DailyDriftWarning`, amber banners rendered with details/dismiss,
      **halt stayed disengaged**; threshold restored, banners dismissed.
      Yesterday's stale false-positive halt released through the new RESUME
      confirm dialog.
- [x] Committed + pushed per phase (97c0aa9 → this commit).

---

## Follow-ups shipped after the 8 phases (2026-08-20 PM) [x]

- [x] **Mismatch root-caused and fixed**: accounts hold multi-currency cash
      (Webull CASH had US$914.17 + C$67.31; only the CAD row was counted).
      `_fetch_cash` now sums every `/balances` entry FX-converted; the UI
      shows the per-currency breakdown ("cash US$914.17 + C$67.31"). The
      residual ~2% vs `balance.total` is SnapTrade's overnight sync vintage —
      threshold moved to 5%, tooltip explains, both Δ pills cleared.
- [x] **Live updates fixed**: Yahoo's v7 quote endpoint turned out to serve
      hourly-frozen snapshots to unauthenticated sessions; the feed now polls
      v8 chart 1m bars per symbol (verified seconds-fresh; NVDA/TSLA/SPCX/
      TQQQ/USDCAD all ticking), with concurrency cap + 429 cooldown.
- [x] **Alive & personalized UI**: quote cells pulse green/red on every tick
      (key-remount animation, reduced-motion aware), provider position
      tables are live-priced with P&L% (no longer static sync prices),
      "My holdings" section (your real positions) tops the sidebar with a
      breathing live dot, bolder tabular numerals, hover lift on cards,
      accent-tinted real-money chip, unified transitions.
- [x] Verified in-browser: 10 price changes + flash mutations in 8s;
      97 backend tests; build green.

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
