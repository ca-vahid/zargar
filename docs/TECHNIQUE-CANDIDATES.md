# Technique candidates — research for the multi-technique platform

*Researched 2026-08-27 (four parallel web-research passes + a codebase audit of the old signals
path). Status: **research, for trimming** — nothing here is decided. Companion docs:
`TECHNIQUE-PLATFORM-PLAN.md` (the platform this all runs on), `PLATFORM-RULES.md`.
Every claim below is sourced in the per-family notes (§6); apply the McLean & Pontiff haircut
everywhere: published anomaly returns run ~26% lower out-of-sample and ~58% lower
post-publication.*

## 0. How candidates were judged

Five criteria, in order of weight:

1. **Evidence** — peer-reviewed > independent replication > practitioner backtest > blog/vendor.
   Post-publication decay checked explicitly (several famous edges are documentedly dead).
2. **Self-manageability** — can the app run it mostly hands-off on our stack: Yahoo 1m/daily
   bars, CBOE delayed chains (~15 min, US listings only), SnapTrade polled fills ~1 order/sec,
   **no share shorting** (shorts = long puts), low-five-figures capital, RiskGate + loss halts.
3. **Marginal data cost** — free/already-fetched data strongly preferred.
4. **Platform fit** — does it map onto the `Technique` protocol (plan / trigger_rules / express /
   exit_policy / critic) and the shared runner, and which missing capability does it force
   (mostly: the Phase 2b durable position manager).
5. **Risk shape** — defined risk, venue-side GTC stops for overnight, no negative-skew
   strategies without a regime gate.

Two structural facts sorted the whole menu:

- **15-minute delayed chains + polled fills** are fine for 30–45 DTE and multi-day holds, and
  disqualifying for anything sub-hour in options (0DTE, real-time sweep chasing).
- **Capital**: one SPY cash-secured put ties up ~$64k — index premium is reachable only via
  defined-risk spreads; the wheel only via sub-$100 single names.

## 1. The shortlist (recommendation: build these, in roughly this order)

| # | Candidate | Family | Hold | Evidence | Expected (honest) | Platform gap it forces |
|---|---|---|---|---|---|---|
| T1 | **Tip** — human-relayed tips (Discord/newsletter/manual), option expression, budgeted, monitored | signal-following | days–weeks | n/a (source-dependent; the app *measures* each source) | whatever the source is worth — the point is the harness + track record | Phase 2b durable positions; signals rebuild (§3) |
| T2 | **Flow** — daily UOA/O-S scanner over CBOE delayed chains; repeat-accumulation swing variant later | options flow | context / 1–3 wk | peer-reviewed at daily horizon (Pan-Poteshman, Johnson-So, Hilliard 2025) | as context: universe/veto value; as trades: modest, prove via sweep first | chain-snapshot persistence; scanner scheduler |
| T3 | **Drift** — PEAD long side, EAR-ranked (announcement-window return), enter day +2, hold 4–12 wk | event swing | 4–12 wk | 50 yrs peer-reviewed; long side still alive, accelerates days 20–75 | ~5–8% CAGR standalone, Sharpe ~0.7, low touch | earnings calendar feed; daily-bar scan; Phase 2b |
| T4 | **Intraday momentum** — Zarattini/Barbon "Beat the Market" noise-band on SPY/QQQ, half-hour cadence, flat at close | intraday index | intraday | 17-yr net-of-cost backtest Sharpe 1.33, independent directional replications | Sharpe ~0.6–1.0 after decay/costs; puts for the short side | none material — closest to EM's shape |
| T5 | **Premium** — 30–45 DTE put credit spreads on SPY/QQQ behind a VIX-term-structure + IV-percentile gate, exit 50–75% profit or 21 DTE | options income | 2–6 wk | CBOE index studies + multiple independent backtests; **the regime gate is the strategy** (unfiltered CNDR ≈ 0%/yr since 2010) | 8–15%/yr on committed capital, 60–75% win rate, worst-year ≈ −15–20% ungated | **venue check first** (§4.1: SELL_TO_OPEN + multi-leg on Webull CA); Phase 2b |

Sequencing logic: T1 is already the platform plan's Phase 5 and forces the Phase 2b work
everything else reuses. T2's scanner is nearly free (data already fetched) and feeds
T1/T3/EM as context. T3 is the best evidence-to-effort ratio of the pure-systematic
candidates. T4 is the only intraday one and slots into today's session-scoped runner
almost unchanged. T5 opens the income family but is gated on a venue capability check.

## 2. Tier 2 — good candidates, after the shortlist proves the platform

| Candidate | Why it waits |
|---|---|
| **Connors RSI-2 / cum-RSI basket** (daily mean reversion on liquid large-caps + SPY/QQQ, long-only, 2–7 d holds, 65–75% win rate) | Decayed-but-alive; buys weakness so it needs *sizing + portfolio halt* instead of per-trade stops (a stop guts the edge — Connors' own finding). Cheap to add once daily-bar scanning exists (T3). |
| **Insider cluster buys** (EDGAR Form 4: opportunistic/cluster open-market buys; JF 2012 ~10%/yr abnormal; 1–6 mo holds) | Strongest free-data event edge, but month-scale holds and small-cap skew; needs the EDGAR poller + comfort with long holds. Natural third event technique after T3. |
| **Stocks-in-play ORB, long-only** (Zarattini 2024: top-20 relative-volume gappers, first-5-min break, 10%-ATR stop) | Best published numbers (Sharpe 2.81) but the short half (≈half the edge) is unavailable to us, event-stock slippage is real, and OOS tests collapse in some regimes. The **relative-volume scanner** inside it is worth building regardless (feeds EM + universe; needs pre-market bars). |
| **Covered-call overlay** (≤30Δ, 30–45 DTE, only on holdings explicitly flagged "OK to cap", ex-dividend guard) | Trivially automatable and delay-insensitive, but only worth it on positions you'd sell at the strike; melt-up drag is ~12 pt/yr on growth names. Opt-in per holding. |
| **Wheel on 2–4 liquid $20–80 names** | Mature automation precedent (ThetaGang), assignment detectable via the positions poller — but honest framing is "paid to scale into names you want to own", not alpha; spintwig: no wheel variant beat buy-and-hold, >94% of return was the long leg. |
| **52-week-high / cross-sectional momentum, monthly long-only rotation** | Peer-reviewed and trivial to code, but it's a monthly *portfolio sleeve*, not a technique that needs the engine; 30%+ drawdowns. Maybe later as a passive sleeve. |

## 3. The Tip technique — rethink of the old signals path

The old path (`signals/*`, `approvals/*`, InboxPage) is a **one-shot** flow: text in → one LLM
extraction → verbatim-quote grounding → 8 checks against the *current* quote → a 30-min-TTL
share proposal sized at 5% notional → static GTC bracket → nothing. Audit findings (what
"crude" means concretely):

- **No monitoring**: everything is decided in the ~2 s after ingest; a tip 4% from its entry
  fails verification once and is dead forever — never re-armed when price comes back.
- **No trigger concept**, no touch/volume/invalidation waiting; no position management after
  the bracket (no ladder, trail, time stop, premium stop, watchdog — all of which now exist
  in `zargar/execution/`).
- **Shares only** (`sec_type` never set) — the "buy the option" goal is unimplementable there.
- **Notional sizing**, not risk-based; extraction schema can't carry strike/expiry/DTE.
- **No dedupe** (same tip twice = two proposals, two shadow fills); grounding is brittle for
  Discord shorthand ("NVDA 180c 9/19 🚀").
- **Shadow portfolios exist but are never scored** — per-source track record is collected and
  then ignored.

The rebuild (platform plan §4 already sketches it) keeps intake/extraction/verification as the
front door and replaces everything after with platform machinery:

```
tip (paste / email / Telegram / screenshot→vision) → extract (schema + strike/expiry/DTE/thesis-horizon)
  → ground → verify → dedupe → tip.plan(): ONE Trigger, kind="tip"
      entry: tip-time market  OR  limit at nearest shared level (user decision, plan §7.3)
      rules: TriggerRules(volume_floor=None, gap_policy="ignore", windows=ALL_DAY)
  → PlanRunner arms it (alert/proposal/auto, RiskGate, journal)     ← exists
  → express(): option pick, 2–4 wk DTE policy (NOT 0DTE)            ← policy over existing chain code
  → exit_policy(): ladder 50/50 + trail after +1R + time stop N sessions + dte_close + premium stop
  → ManagedPosition (Phase 2b): survives restarts/weekends, venue-side GTC stop, reconciliation
  → outcome scoring + per-source scorecard (shadow portfolios finally measured)
```

**Source policy (from the flow research, firm):** tips enter via a *human or a service that
offers a bot/API*. No Discord self-bot scraping (ToS violation, feed dies mid-position) and
**no autonomous execution of room alerts** — alert rooms have an SEC/DOJ/FTC fraud record
(Atlas Trading $114M pump-and-dump; Raging Bull $2.4M FTC settlement; zero audited evidence any
paid room beats the market). The app's leverage is the harness: per-source shadow track record
first, small real budgets only for sources that survive their own scorecard. Screenshot intake
(your own client → vision extraction) is ToS-clean and the vision plumbing already exists in
the technique layer.

## 4. Shared capabilities the shortlist forces (build-once list)

| Capability | Needed by | Notes |
|---|---|---|
| **Phase 2b durable positions** (`managed_positions`, policies-as-data, venue GTC, reconciliation, chaos suite) | T1, T2-swing, T3, T5, all Tier 2 swing | Already specced (platform plan §2.4–2.5). This is the critical path; ships with the chaos suite or not at all. |
| **Venue capability check: short options + multi-leg on Webull CA via SnapTrade** | T5, covered calls, wheel | ✅ **Probed 2026-08-27** (read-only impact previews): Webull CA accepts SELL_TO_OPEN, native 2-leg spreads, and GTC on options; venue-side option STOP unproven (503); Wealthsimple rejects (1156). The income family is venue-viable — remaining gate is the structure-aware RiskGate change (naked-call block must understand spreads), an engine work item. |
| **Daily-bar layer + overnight scan scheduler** | T2, T3, Tier 2 (Connors, insider, 52wk) | The app is 1m-centric today; these run on daily closes + a nightly/pre-open scan pass. |
| **Earnings calendar feed** (confirmed dates + BMO/AMC) | T3 (core), T1/T2/T5 (as a veto: `flatten_before("earnings")` is already a §2.4 policy input) | Yahoo's dates are unreliable for automation; cross-check via a second free source. |
| **Chain snapshot persistence** (daily per-symbol CBOE chain rows: volume, OI, IV) | T2 (core — repeat-hits + overnight OI confirmation need history), T5 (IV percentile) | Cheap: we already fetch the JSON; start persisting now so the sweep has data by build time. |
| **VIX / VIX3M fetch** | T5 regime gate | Trivial — Yahoo v8 chart, symbols `^VIX`, `^VIX3M`. |
| **Pre-market bars** (`includePrePost`) | RVOL scanner (Tier 2 ORB, EM context) | Feed currently filters to RTH. |
| **Settings resolver** `techniques.<id>.<key>` → `execution.<key>` | everything | Specced (platform plan §8 item 4), unbuilt. |
| **Never-list enforcement in RiskGate** | all | 0DTE for non-EM techniques, naked calls, share shorts — as gate rules, not settings. |

## 5. The never list (researched and rejected — don't revisit without new evidence)

| Rejected | Why |
|---|---|
| Real-time sweep chasing | Needs $150–375/mo real-time flow API to even compete; on delayed data you are the exit liquidity; retail loses 8–12% round-trip to spreads on exactly these contracts. |
| Discord auto-execution (scraping rooms) | ToS violation + documented pump-and-dump ecosystem + zero audited evidence. Human-in-the-loop tips (T1) are the acceptable form. |
| 0DTE, selling or debit | Delayed chains + polled fills are disqualifying; academic record: retail lost ~$350k/day, mostly to transaction costs. Enforce in RiskGate. |
| IV-crush selling through earnings | Negative skew, needs naked short options — excluded by mandate. |
| Gap fade / buy-on-gap | Textbook arbitraged-away edge: Sharpe 3.58 (2005-08) → ≈0 (2018+). |
| Night effect (overnight drift harvesting) | Real anomaly, failed live product (NightShares shut 2023); costs kill it. |
| Last-half-hour momentum (Gao et al.) | Post-publication OOS Sharpe negative (2015–2020). At most a conditional overlay on high-vol days. |
| VWAP standalone, gap-and-go, VCP/CANSLIM as-published | No credible complete-system evidence; VWAP stays an exit anchor, RVOL stays a filter, breakout patterns would need us to generate the evidence ourselves. |
| GEM / dual momentum, leveraged-ETF rotation | GEM lagged 60/40 out-of-sample 2014–2026; leveraged rotations are period-fit backtests. |
| Analyst-upgrade drift | Real academically, but the move happens in the first hours and needs a paid real-time ratings feed. |

## 6. Research provenance

Four research passes (2026-08-27), each with full sources archived in the session:
**flow/social** (Pan & Poteshman RFS 2006; Johnson & So JFE 2012; Chakravarty et al. "Clean
Sweep" JFQA 2012; Augustin et al. Mgmt Sci 2019; Hilliard et al. RQFA 2025; Bryzgalova et al.
JoF 2023; MIT "Losing is Optional"; Bradley et al. RFS 2024; SEC v. Atlas Trading; FTC v.
Raging Bull; Unusual Whales/Barchart/FlowAlgo pricing), **intraday** (Zarattini & Aziz SSRN
4416622 + replication; Zarattini/Barbon/Aziz SSRN 4729284 + QuantConnect OOS; Gao et al. JFE
2018 + decay replication; "Beat the Market" SSRN 4824172 + Quantitativo ES/NQ replication;
NY Fed overnight-drift; NightShares closure), **swing/event** (McLean & Pontiff JoF 2016;
Connors replications; Daniel & Moskowitz JFE 2016; Quantpedia PEAD; Frazzini & Lamont;
Cohen/Malloy/Pomorski JoF 2012; Cohen/Polk/Silli; George & Hwang JoF 2004; Womack/Loh-Stulz),
**options income** (CBOE PUT/BXM/BXMD/CNDR index studies; Bondarenko 2019; Wilshire 2019;
spintwig SPY wheel + short-put matrix; Option Alpha SPY PCS 8-variant + 25k-trade 0DTE data;
Beckmeyer et al. 0DTE; Quantpedia VRP + VIX term structure; ThetaGang/Alpaca automation
precedents). The codebase audit of `signals/*`/`approvals/*` and the platform-reuse inventory
is in §3 and the platform plan.

## 7. The trim (decided 2026-08-27 with the user)

1. **Wave one = T1 Tip + T2 Flow** — build plans: `docs/techniques/tip/PLAN.md`,
   `docs/techniques/flow/PLAN.md`. T4 (intraday momentum) and T3 (Drift) stay warm in this
   doc, not planned. T5 (Premium) waits on the venue short-options probe.
2. **Tip entry policy: per-source** — default level-touch for unproven sources; tip-time
   entry must be earned by a positive scorecard (user decision).
3. **Tip budgets**: per-tip budget + risk %, per-source cap, shadow-only until the scorecard
   bar clears (proposed default: 20 scored tips, positive expectancy) — defaults in the Tip
   plan, tunable.
4. Venue short-options probe + daily chain snapshots: handed to the engine team in the
   2026-08-27 Phase 2b/3 requirements memo (with the Alpaca addendum: data/paper only —
   Canada is ineligible for live Alpaca brokerage).
5. Engine-side prerequisites (durable positions, calendars, RiskGate tag caps, settings
   resolver) are the engine team's scope per that memo; the wave-one plans mark every ⚙
   dependency and sequence Phase A work to need none of them.
