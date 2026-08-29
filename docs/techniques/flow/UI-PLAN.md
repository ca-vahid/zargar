# Flow UI — build plan

*Written 2026-08-27 after the user picked from five mockups
(claude.ai/code/artifact/9185e731-0987-417c-ac07-3bbf283cee09). Companion:
`PLAN.md` (the technique), `docs/TECHNIQUE-PLATFORM-PLAN.md` §2.3/phase 4 (UI shell —
this page is technique-owned until the shell goes generic). Status: **BUILT 2026-08-27**
(all phases; §3a below is the as-built record + what the first real scan taught).*

## 0. The decision (user, 2026-08-27)

- **Main view = Option A "The Desk"** — the Armed-page pattern: ranked reads table left,
  pinned symbol detail right — **enriched with Option C's evidence, without the crowding**:
  - the left table's Evidence column carries C's verdict badges (`OI ✓ +n` / `churn` /
    `Rpt n/5` / `Strong`), not just flags;
  - C's right-rail day summary becomes a **slim strip above the table**: call-vs-put premium
    bar, flagged count, confirmed/churn counts, repeat streaks — one line, not a panel;
  - C's contract-level rows do NOT move into the table (that is the crowding) — they live in
    the detail pane (already in A) and in the drill-down.
- **Drill-down = Option D "Symbol Story"** — clicking "how was this built?" on the detail
  pane opens the day-by-day story: snapshot → flag → overnight OI verdict → repeat streak →
  score, plus "where this read went" (Tip verifications, EM context, universe layer).
- **Third tab = Option E "Morning Brief"** — the zero-click daily report (confirmed
  overnight / accumulation watch / new today / dying flags / verbatim context lines).
- Page structure: `Flow` page with tabs **Reads | Brief** (Story is a drill-in from Reads,
  not a tab). Day picker on Reads (trailing week).

## 1. What exists vs what's missing

Backend today: `flow_reads` rows (score, lean, flags, confirmed, repeatHits, aggregates,
reasons — per symbol per day), `option_chain_snapshots` (the raw chain history),
`GET /api/flow/reads?day`, `GET /api/flow/context/{symbol}`, `POST /api/flow/scan`,
`GET /api/flow/status`. Frontend today: the Sidebar **already lists Flow** (registry
sub-item, page key `flow`) but `App.tsx` has **no route** — clicking it renders nothing.
Data gaps for the chosen design: no day-summary aggregates, no per-symbol multi-day story
endpoint, no brief composition, and **no record of where a read went** (context lines are
served but not journaled, so D's "where it went" panel has nothing to read). EM does not
receive flow context yet (only Tip does).

## 2. Phases

### Phase F1 — backend: the read APIs `[x]` *(built 2026-08-27)*

- [x] **Journal context deliveries.** `FlowService.context_for()` currently serves a line and
      forgets it. Add a `consumer` kwarg (`"tip"`, `"em"`, `"api"`) and journal
      `FlowContextServed` {symbol, day, score, consumer, refId (signal/run id)} — register the
      kind in `events.py` + note in PLATFORM-RULES §4. This is what makes D's "where it went"
      panel real. Callers updated: tip verification (`signals/service.py`).
- [x] **EM context note (opt-in).** Inject `context_for(symbol, consumer="em")` into EM's
      analyze context as an informational note (mirror of the Tip injection; never a gate).
      Journaled by the same event. Confirm with the EM team it lands in their prompt context
      the way `gap_unchecked` does — a note, not a rule.
- [x] **`GET /api/flow/days?limit=10`** — trailing scan days with per-day summary computed
      from `flow_reads`: {day, scanned, flagged, callPremium, putPremium, confirmed, churn,
      repeatStreaks: [{symbol, contract, days}]}. Powers the day picker + the slim strip.
- [x] **`GET /api/flow/symbol/{sym}?days=6`** — the story: that symbol's reads oldest→newest
      (score, flags, confirmed, repeats per day) + `deliveries` (from the journal: consumer,
      refId, ts, the line) + `universe` (is the symbol currently held by the flow layer).
- [x] **`GET /api/flow/brief?day=`** — server-composed sections so the UI stays thin:
      `confirmedOvernight` (today's `confirmed` + yesterday's flags whose OI stayed flat =
      churn), `accumulation` (repeatHits ≥ 2 with day-dot vectors), `newToday` (first flag in
      the window), `dying` (flagged contracts with DTE ≤ 1, and streaks that broke),
      `contextLines` (today's verbatim lines for symbols score ≥ threshold).
- [x] Tests (`tests/test_flow_api.py`): seed `flow_reads` fixtures across 3 synthetic days →
      days summary math, story ordering + deliveries join, brief sections (confirmed vs churn
      split, dying by DTE), context delivery journaling from a tip verification.
- [x] Gate: full backend suite green.

### Phase F2 — frontend: page shell + the Reads desk `[x]` *(built 2026-08-27)*

- [x] Route the page: `App.tsx` `page === "flow"` → `<FlowPage />` (lazy like TechniquePage);
      phone TabBar: Flow lives under **More** (no new bottom tab).
- [x] `api.ts` + `types.ts`: `flowDays`, `flowReads`, `flowSymbol`, `flowBrief`, `flowScan`
      + `FlowRead`/`FlowDay`/`FlowStory`/`FlowBrief` types (camelCase wire).
- [x] `pages/FlowPage.tsx`: header (title, day picker from `/days`, scan status line,
      "Scan now" button → `POST /api/flow/scan` with toast), tabs **Reads | Brief**.
- [x] `components/flow/DayStrip.tsx` — the C-derived slim strip: premium bar (calls vs puts),
      flagged/confirmed/churn counts, repeat streaks as `COIN 4 · MU 3` chips.
- [x] `components/flow/ReadsTable.tsx` — ranked table: Sym, Last, Score (mini bar), Lean
      pill, Top contract (mono), Premium, Vol/OI, Evidence badges (`OI ✓ +n` / `churn` /
      `Rpt n/5` / `Strong`). Row order frozen between sorts; selection never auto-moves
      (the Armed-page anti-jump rules). Footer: "N symbols quiet · show all".
- [x] `components/flow/ReadDetail.tsx` — pinned right pane: header (sym, last, lean, score),
      "Why this score" reasons, flagged-contracts table, repeat tracker (day dots), score
      sparkline (last 6 reads, plain SVG — no Highcharts for a 6-point line), the verbatim
      context-line box, actions (Analyze in EM · Open chain · Chart · **How was this
      built? →** opens the Story).
- [x] Keyboard: ←/→ moves selection (as ArmedPage).
- [x] Gate: `npm run build`.

### Phase F3 — the Symbol Story drill-down `[x]` *(built 2026-08-27)*

- [x] `components/flow/SymbolStory.tsx` — replaces the detail pane (with "← back to read")
      or full-width on narrow screens: the day-column pipeline (snapshot count → flags →
      OI verdict → repeat streak → day score), the score/premium buildup chart (SVG bars +
      line, per the mockup), and the "Where this read went" cards driven by `deliveries`
      (Tip verification with source + link to the signal, EM run link, universe chip).
- [x] Deep links: from a Tip's `flowContext` line on the Tips page → this story; from the
      story's delivery card → the signal/run.
- [x] Gate: `npm run build`.

### Phase F4 — the Brief tab `[x]` *(built 2026-08-27)*

- [x] `components/flow/BriefTab.tsx` — the E layout: Confirmed overnight (with churn rows),
      Accumulation watch (day-dot strips + DTE pills), New today / Dying flags side by side,
      "What Tips & EM receive today" (mono verbatim lines), footer (next scan time, Scan now).
      All from `GET /api/flow/brief` — no client-side composition.
- [x] "Previous briefs": the day picker drives the same endpoint.
- [x] Gate: `npm run build`.

### Phase F5 — mobile, polish, wiring the loose ends `[x]` *(built 2026-08-27)*

- [x] Phone layout: Reads as `bl-cards` (score + lean + top contract + badges per card),
      detail + Story in a `Sheet` (the Brief renders as the tab full-width — a sheet adds
      nothing to a report layout; deliberate deviation); ALL phone rules in `mobile.css` only.
- [x] Device screenshots pass: desktop 1440×900 + iPhone 390×844 via Playwright against a
      dedicated server (port 8799, own DB) — seven states reviewed, three defects found and
      fixed (see §3a). The official `npm run mobile-audit` targets the RUNNING app, which is
      still the pre-Flow build — run it once after the next restart deploys this.
- [x] **Universe flow layer** (PLAN.md open item): symbols with score ≥
      `techniques.flow.universe_score_min` (new setting, default 5) for ≥ 2 of the last 3
      sessions join the working universe as provenance `flow`; drop when quiet 3 sessions.
      Surfaced in the story's universe chip and the universe endpoint's provenance.
- [x] Flow badge on the Tips page: a small score chip next to a signal's ticker when a
      fresh read exists (links to the story).
- [x] Docs: PLAN.md status updated; PLATFORM-RULES §4 entry for `FlowContextServed`;
      screenshots refreshed in the mockup artifact if the built page drifts from Option A+C.

## 3a. As-built notes + what the first real scan taught (2026-08-27)

The visual pass ran against a dedicated server whose boot scheduler ran a **real scan on
live CBOE chains** (56 symbols, 42 flagged, $600M flagged premium) — an accidental but
valuable full-integration test. Verified working end to end: the reads desk with real
badges, day picker, multi-day Symbol Story (day columns, next-morning OI verdicts
attributed to the right day, score/premium chart), the Brief with churn rows, the Tips
`flow N` chip → story hand-off, phone cards + sheets. Defects found by inspection and
fixed: the Brief's "yesterday had no flags" copy showed even when churn rows followed;
the phone day strip clipped; the detail's contracts table clipped OTM/DTE on phones (now
scrolls); the Last column was empty for unwatched symbols (reads now persist the scan-time
`spot` as the fallback).

**Calibration observation for TRADING-RULES-style follow-up (not a UI matter):** with the
default thresholds, a real day flags 42 of 56 symbols, almost all score 4, dominated by
1-DTE contracts (whole GLD/META expiry boards land in "dying flags"). The premium floor
($100k) barely filters a modern chain. Candidate tunings to evaluate against accumulating
snapshots before trusting scores: `dte_min` (exclude ≤1 DTE from flags — their OI verdict
never arrives), a higher `premium_min`, and/or per-symbol flag caps. The scoring machinery
is fine; the thresholds are book-naive.

**Live-usability round 2 (2026-08-27, evening, after the user drove the deployed page):**
the day-one experience was rebuilt around three complaints — "how do I drill down",
"what am I looking at", "how do I arm". (1) Drill-down is now always visible: a
"story ›" link on every table row plus "The story →" in the detail header. (2) The
detail and the story both open with a plain-language **What now** verdict (four derived
states: first-sighting / OI-confirmed / repeat+confirmed / expiry-noise) and the table
legend decodes the badges. (3) **Send to Tips** (detail + story header): `FlowService.
to_tip()` turns the latest read into a grounded tip under source `flow-scan` through the
normal pipeline — both shadow books, dedupe→seen_count, armable; refuses MIXED leans and
≤1-DTE noise. The Symbol Story got its chart-style hero, **Price & the bets**: 3 months
of real daily closes (`/api/chart?tf=1d&range=3mo`) with each flagged strike drawn as a
dashed level — calls green above, puts red below, line weight ∝ premium, staggered
labels — so a single-day story is no longer an empty box (the buildup chart now renders
only with ≥2 sessions, and takes the lean's color). Puts vs calls are color-coded
everywhere a contract appears (`Occ` in `components/flow/lib.tsx`: green call / red put,
desk, detail, story, brief, phone cards). Note: the price panel needs a Yahoo/Hybrid
feed — on a sim-feed dev server `/api/chart` falls back to local bars and the map
degrades gracefully.

**Nightly reliability (2026-08-29, after the 08-28 wipe):** the 16:45 scan ran fine at
20:25 ET (52 flagged, real leans) but three later boot re-runs — each `scripts\start.ps1`
redeploy re-fired the scheduler job — scored with a cold quote cache: spot 0 → every
contract "failed" the 0–12% OTM window → zero flags, and the idempotent re-scan
overwrote the good day with OI-confirm-only junk (the all-NONE score-4 board). Four
fixes, all tested: scheduler jobs hydrate their last-run day from the journal (a redeploy
never re-runs the night's job; a genuinely missed one still runs late); `_spot_for` falls
back to **put-call parity on the snapshot chain** before any network call; a spot-less
scan **never overwrites** an existing read (`noSpot`/`keptExisting` journaled); weekend
"Scan now" rolls the day back to Friday. Plus boot self-healing: `_repair_last_scan`
re-scans the latest day (its own symbols only) when it shows the degraded signature —
so 08-28 rebuilds itself on the next restart.

## 3. Decisions taken / open

- Taken: Reads default day = latest scan day; sparkline = plain SVG (Highcharts is for the
  Trade chart, not a 6-point line); Story is a drill-in, not a tab; the tape's contract-level
  day-by-day view is NOT built (its evidence reached the badges + detail + story instead) —
  revisit only if the story proves insufficient.
- Open: does "Analyze in EM" pre-fill the EM analyze form or fire it immediately (proposal:
  pre-fill only); should the Brief also go out via Telegram at 09:00 with the feed self-test
  (cheap once `/brief` exists — separate decision, default no).
