# Scout - research-only idea finder (plan, 2026-10-07)

**Status:** PLAN APPROVED 2026-10-07 (decisions in section 6). Build starting. User decision 2026-10-07: the IBKR real-money go-live is
DELAYED; the IBKR Paper book keeps rehearsing the C$3k account while Scout is planned, built and judged on simulated
money for ~2 weeks. Scout places **no orders** at IBKR - research books only (PLATFORM-RULES invariants 12-13 style).

Source: deep-research run 2026-10-07 (5 angles, 22 sources, 25 claims verified 3-vote, 22 confirmed, 3 refuted).
Verified findings are cited `[F#]`; anything marked *judgement* is design choice, not evidence.

## 1. What the evidence says (and what it does not)

| # | Finding | Confidence | Consequence for Scout |
|---|---|---|---|
| F1 | Published anomalies earn ~58% less after publication (97 predictors; McLean & Pontiff, JF 2016) | high | Assume any paper's edge is half or less, before costs |
| F2 | Post-earnings drift (PEAD) decile hedge fell from ~5-6%/qtr to ~0 after 2017 (Kettell, McInnis & Zhao 2022) | medium | PEAD is a *secondary* signal, never the core |
| F3 | Remaining PEAD sits in high-cost small/illiquid names; costs eat most of it (Ng, Rusticus & Verdi 2008) | high | Strict liquidity gate; count only after-cost, long-only results |
| F4 | **Opportunistic** insider buys (Cohen-Malloy-Pomorski filter: drop "routine" insiders who traded the same month 3 years running) earned 82 bp/month VW, 180 bp EW, gross, 1986-2007; routine trades carry ~no signal | high (gross, old) | **Core signal v1** - but apply F1 decay; needs 3 years of Form 4 history |
| F5 | LLM backtests inside the model's training window are contaminated by memorization (look-ahead collapses to ~0 only after the cutoff) | high | **No historical backtest of the LLM layer.** The LLM is judged only prospectively |
| F6 | Masking company names improved LLM news signals (prior knowledge distracts) | medium | Show the model masked text where the task allows |
| F7 | No reliable evidence LLMs pick stocks: the best-known "GPT beats analysts" paper was withdrawn (2025-02); a masked benchmark of 10 frontier agents found returns = market + style tilts, selection alpha ~0 to deeply negative | medium | **The LLM filters and explains; it does not generate ideas** |
| F8 | Trading costs are first-order (>50 bp round trip typical; 2-3x for small caps) | medium | Model >= 0.5-1% round trip for small caps; prefer week-scale holds; measure real fills |
| F9 | A backtest is meaningless without the number of variants tried | high | Preregister screens + thresholds, log every variant, no tuning during the paper run |
| F10 | EDGAR fair access: <= 10 req/s with a declared User-Agent; Alpaca has a real-time news WebSocket (beta) | high | Data plumbing is free; respect limits |

**Not covered by verified evidence** (design judgement only): momentum / 52-week-high, short-term reversal, analyst
revisions, volume breakouts, short interest, free-tier limits of Finnhub/FMP/Polygon, LLM cost per analysis,
pump-and-dump detection, biotech/FDA handling, gap risk, and concrete spread / price / dollar-volume thresholds.

**Honest expectation:** two weeks of paper trading yields tens of trades - enough to prove the plumbing, measure costs
and slippage, and see a *direction* for "screen vs screen+LLM"; **not** enough to prove an edge (needs ~6-10 weeks
and >= 40-60 closed trades per lane).

## 2. Design

### 2.1 Signals (deterministic, preregistered - the candidates come from rules, never from the LLM)

- **S1 - Opportunistic insider cluster (core).** Form 4 open-market purchases (transaction code `P`) by officers or
  directors, CMP-filtered to opportunistic insiders (routine = traded in the same calendar month in each of the
  prior 3 years, classified once a year from past trades only). Cluster = >= 2 distinct opportunistic insiders
  buying within 10 calendar days, total >= US$100k (*judgement*). Signal time = the Form 4 **filing** time, entry
  the next regular session.
- **S2 - Earnings reaction drift (secondary).** Earnings-day abnormal return (day 0 to day +1 vs SPY) in the top
  ~10% with volume >= 2x its 20-day average, entry day +2 (*judgement*, EAR-based like our T3 candidate).
- **Baseline lanes** for every signal: *screen-all* (every candidate that passes the gates) and *random-matched*
  (same count, same gates, random dates) - the bar Scout must beat.

### 2.2 Gates (*judgement* - preregistered, not tuned during the run)

Price >= $5; 20-day average dollar volume >= $5M; quoted spread <= 0.5% at entry; market cap >= $300M; no
earnings inside the hold (S1); no pending binary event flagged in filings (biotech FDA/PDUFA, trial readouts);
no reverse split or ticker change in 6 months; not mentioned by a Discord tip source in the prior 5 days (keeps
Scout independent of Tips).

**Entry-spread rule (preregistered, user-approved via the desk 2026-10-07; `techniques/scout/entry.py`).** A
candidate's entry is attempted at **10:00 ET** on its entry session; the spread gate (<= 0.5% of mid) is judged on
the **live quote at that moment**. Wider (or no usable two-sided quote): re-check **every 15 minutes until 11:30
ET**; still wider at the 11:30 attempt -> **skipped, reason `spread`** (`no_quote` when no usable quote was ever
seen). An attempt that only runs after 11:30 + one step (the app was down) is `window_missed` - never a late fill.
The verdict calls run before 10:00 (09:00 ET), so "passed the gates" for the analyst lanes means every gate except
the entry spread passed. (P1's 09:35-09:40 median is replaced by this rule; the historical re-check of an
un-attempted candidate now measures 10:00-10:01 ET.)

### 2.3 The LLM analyst (filter + explainer)

- Input: the facts for one candidate - the Form 4 rows or the earnings release text, recent price/volume numbers,
  sector, upcoming events - with company name and ticker **masked** where the judgement allows [F6].
- Output (flat schema, prompted JSON): `keep | drop`, a 1-5 conviction, the reasons, and **a quote with its source
  id for every factual claim**; a claim without a citation is discarded (grounding).
- It may veto (drop), never add a candidate. Budget: <= 20 deep reads/night, capped by a setting (~US$5/day).
- Its "drop" decisions are tracked as a counterfactual lane, so its value is measured, not assumed.
- **As built (P3, 2026-10-07; `techniques/scout/analyst.py`, `desk.py`):** prompted JSON `{verdict keep|drop,
  conviction 1-5, claims [{text, quote, source_id}], reasons [{text, claims [indexes]}]}`. A claim whose quote is not
  found verbatim (whitespace-collapsed, case-insensitive) in the CITED packet source is discarded (kept on the record
  as dropped); a reason survives only if it cites a surviving claim; no surviving reason -> `drop`, reason
  `ungrounded`. Packet sources: `S1` cluster summary + `F4-n` purchase rows (insiders renamed Insider A, B, ...) or
  `S2` reaction + `8K` (EX-99 release text, capped at `packet_max_chars`), `PX` daily price/volume numbers, `SEC`
  sector (SIC), `EV` entry/exit/earnings calendar. Company names (submissions JSON incl. former names, 8-K header)
  and the ticker are masked. The packet is stored per candidate (`scout_state` `packet:<id>`) and hashed on every
  verdict. Two lanes on the SAME packet: Claude `claude-opus-5-5` effort `medium` (`output_config.effort`,
  `cache_control` on the system prompt, no `thinking` parameter - Opus 5.5 thinks adaptively) and OpenAI
  `gpt-6.1-sol` (Responses API, `reasoning.effort` medium; key from env `OPENAI_API_KEY`, absent = every candidate
  records `skipped: no OPENAI_API_KEY`). **Budget** `llm_budget_usd_day` (US$15) is SHARED: before each call
  `spent today + worst case (input ~chars/3.5 tokens + the full max_tokens output) > budget` stops that lane for the
  day (`ScoutBudgetStop`, journaled once per lane per day); cost = usage x `llm_rates` (Opus 5.5 $4/$20 per M,
  cache read $0.20 / write $5.00; GPT-6.1 Sol $2/$10 marked "third-party pricing, verify"). Every verdict (incl.
  skipped / budget / error) is a `scout_verdicts` row + `ScoutVerdict` event (tokens, cost, latency, packet hash).

### 2.4 Trading rules (simulated, identical for every lane)

Position US$600 (*judgement*, matches the live book's slot size); stop 2x daily ATR; exits: time stop 20 sessions
(S1) / 10 sessions (S2), or the stop; no trims. Costs charged: $1 per order + half the quoted spread each side.
Research books only (one per lane): `Scout S1 screen`, `Scout S1 claude keep`, `Scout S1 claude drop`,
`Scout S1 gpt keep`, `Scout S1 gpt drop`, the same five for S2, plus `Scout random` (11 books).

**As built (P3, 2026-10-07; `books.py`, `desk.py`):** books are SHADOW portfolios (`kind shadow`, `book scout`,
`source_name scout:<lane>`): the engine routes them to the sim executor only, money totals / ledger / daily-loss
monitor skip them, Tips' scorecards never read them. Entry = BUY limit at the observed ask (+ at most the gate's
half spread, so it is marketable) via `OrderManager.place()` (RiskGate), US$600 / ask shares, cancelled as `unfilled`
if not filled within `entry_fill_wait_s`; the fill is adopted by the shared position manager with policy
`{timeframe 1d, stop fixed at fill - 2 x 14-day daily ATR, time_stop_sessions hold-1, gap_exit}` (the stop is judged
on the daily close, a resting GTC stop sits at the same price on the sim executor; the time stop exits at the close
of the P1 `exitDate` session = 20 sessions incl. the entry day for S1, 10 for S2). Accounting: $1 per FILLED order
(entry + each exit) is charged in Scout's ledger; the half spread is embodied in the ask/bid fills and reported apart
(`half_spread_cost`), never charged twice. Kill switch / book halts are honoured (skip reason `halted`).
s1_unclassified candidates are tracked, not traded (`trade_unclassified` off). **Random matched baseline:** for every
gate-passing S1/S2 candidate one twin, seeded by the candidate key: a ticker drawn from Scout's own gate-passing
tickers of the last 365 days (minus the last 30 days' names; topped up with a fixed liquid list below 20 names),
entry = the matched entry + U{0..4} sessions, same hold/rules; it must pass price/ADV/corporate-action/Tips gates
(market cap not required - no CIK), up to 5 redraws (`books.py` docstring).

### 2.5 Data (free first)

- SEC EDGAR: Form 4 + 8-K via the daily index / RSS, <= 10 req/s, User-Agent with contact [F10]; 3-year Form 4
  backfill for the CMP filter. Record the filing **acceptance** time (the refuted timing claim means this must be
  verified first-hand before any replay).
- Earnings: dates + day-0/+1 reaction from our existing daily bars (Alpaca/Yahoo); an earnings calendar source is
  still to be chosen (open item).
- News: Alpaca news stream for context only (beta; verify fields and timestamps first-hand - that claim was refuted).

## 3. Validation (preregistered)

1. **History, screens only** (no LLM - F5): replay S1/S2 with the gates and costs on 2018-2026 data that our
   sources can supply point-in-time; report after-cost mean return per trade, hit rate and drawdown by year, with the
   number of variants tried (F9). Expect roughly half the papers' numbers (F1). This tells us whether a lane is worth
   watching at all.
2. **Prospective paper run** (the held-out test): all lanes in parallel from day 1, no threshold changes during the
   run, one daily report (candidates, verdicts with citations, fills, costs, open P&L per lane).
3. **What the 2-week checkpoint can decide:** plumbing works end to end; costs and slippage match the model; LLM
   cost per day; whether the LLM keep lane is not *worse* than screen-all. **It cannot approve real money.**
4. **What a real-money decision would need later** (~6-10 weeks): >= 40-60 closed trades in the lane, after-cost mean
   per trade > 0 with a confidence interval that excludes zero after the multiple-testing correction, beating both the
   screen-all and random lanes.

## 4. Build plan (this week and next)

| Phase | When | What | Done when |
|---|---|---|---|
| P0 | day 1 | Verify data first-hand: EDGAR Form 4/8-K fields and acceptance times; Alpaca news fields and timestamps; an earnings calendar source | A short note with real samples |
| P1 | days 1-3 | EDGAR ingester (daily index + 3-year Form 4 backfill), CMP classifier, gates, S1/S2 screens -> candidate table | Yesterday's candidates listed with their evidence |
| P2 | days 3-4 | Historical replay of the screens (no LLM), after costs | Report per year + variants log |
| P3 | days 4-5 | LLM analyst (masked inputs, cited verdicts, budget cap) + research books per lane + daily report | First daily report - **BUILT 2026-10-07 (branch claude/scout-p3; not deployed)** |
| P4 | days 5-10 | Prospective run, no tuning; Tips paper keeps running | 2-week checkpoint review |

Constraints: Scout never routes to IBKR; it lives in `zargar/techniques/scout/` with its own settings
(`techniques.scout.*`); it uses the shared marketstructure/execution libraries, never Tips' or other desks' code.

## 5. Decisions for the user

1. Approve S1 (insider clusters) as the core and S2 (earnings reaction) as secondary - or pick only one.
2. Approve the gates in 2.2 (price >= $5, ADV >= $5M, spread <= 0.5%, cap >= $300M) or set your own.
3. LLM budget cap (suggested US$5/day).
4. Whether Scout may later share the IBKR account with Tips (a separate slot) once a lane passes - decided only after
   the 6-10 week evidence, not now.

## 7. First review and screen v2 (2026-10-11, user: "ship the fixes, start the replay, make the adjustments you feel necessary")

Reviewed after two entry sessions (2026-10-08/09): 15 candidates, 8 verdicts (US$0.26 of LLM), 3 distinct trade
ideas, no exits yet. Nothing here is evidence about edge. What the review found, and what changed (`SCREEN_VERSION
scout-p1-v2`, analyst packet `scout-analyst-v2`; every change is plumbing or a NEW preregistered variant with its own
book - no existing threshold was tuned):

| # | Finding | Change |
|---|---|---|
| 1 | PENG filed two 8-Ks with item 2.02 for one release: two candidates, two verdict pairs, a double position in the screen book, two random twins, and two of the day's two top-decile ranks | **One S2 event per company and day 0** (`screens.dedupe_reactions`, earliest accepted filing; a company already recorded for that day 0 is never recorded again) |
| 2 | The second PENG packet carried a CFO-appointment press release, not the results | `analyst.release_text` scores every EX-99 exhibit on results vocabulary and takes the best; the SGML document header (file name) is never in the text |
| 3 | 3 of 4 packets named the company ("Penguin" as a defined short name, `pengq4-26...htm`, `investors@lambweston.com`) | Masking also covers the release's own defined short names, a distinctive first word, names broken across lines, squashed names, e-mail addresses and URLs |
| 4 | APOG (both models: keep) was lost to a RiskGate stale-quote refusal | Already fixed in 0.9.19 (the entry returns to pending and retries at the next 15-minute step) |
| 5 | The random twins were megacaps (COST, DE, PEP, T) against small/mid-cap earnings movers | **Peer-matched baseline** (`service.peer_pool`, `books.RANDOM_METHOD`): the twin is another company with the same kind of event in the same days, bound by the market-cap gate too. Pending twins of the old method are skipped as `superseded` |
| 6 | S1 (the core signal) cannot be judged: ~6 opportunistic clusters a month in 2026 BEFORE gates, against ~80 that need unclassified insiders; all 5 clusters of the week were unclassified, tracked but not traded | **The unclassified variant trades in its own five books** (`s1u_*`, `trade_unclassified` on) - a separate preregistered lane, never blended into S1 |
| 7 | TSM "cluster": ~30 executives each buying $2k-$11k on one day; purchase rows of $1bn+ (filer typos) exist | `s1_min_insider_value_usd` $10k (an insider counts only with at least that much bought in the window) and `s1_max_row_value_usd` $500M (a larger single row is dropped) |
| 8 | The 16:30 report marked open positions at a thin after-hours bid (PENG 75.65 vs a 76.28 close) | Outside the regular session the mark is the regular-session price |
| 9 | Validation step 1 (history, screens only) had been skipped | `tools/scout_replay.py` (P2): S1 2018-2026 and S2 2023-2026, after costs, by year, with SPY-relative and month-clustered statistics and a variants log (`replay/VARIANTS.jsonl`) |

Consequences for the run: the two-week checkpoint clock restarts at 2026-10-12 for the lanes whose inputs changed
(S2 packets, the random book, the new `s1u` books). The PENG duplicate (candidate `4d3feb38`, the 16:34 ET filing)
stays on the record as entered; lane comparisons must count that event once.

**Replay result (2026-10-11, `replay/README.md`, 5 runs logged):** neither screen shows an after-cost edge on
history. S1 strict: 268 trades 2018-2026, +0.79% net per trade, -0.45% against SPY (month-clustered t -0.39).
S1U: 3,291 trades, -0.03% net, -1.04% against SPY. S2 selected: 1,898 trades 2023-2026, -0.50% net - no better
than the 25,069 other gate-passing reporters of the same days (-0.40%), on a universe that excludes delisted
companies. Removing the stop does not change the sign. The screens are a roughly zero-edge candidate source; what
the prospective run can still answer is whether an analyst KEEP book beats its screen book and the random book.

Still open: an earnings-in-hold source that is not a projection; S2's "top decile" is ranked inside ONE day's
releases (1-2 names in a quiet week, dozens in peak season); costs at this size (US$1 per order on US$600 is 0.33%
round trip before the spread).

## 6. User decisions (2026-10-07)

0. **Entry-spread rule** (desk, 2026-10-07): 10:00 ET live-quote judgement, re-check every 15 min to 11:30 ET,
   then skip `spread` - recorded in 2.2.

1. **Both screens**, each behind its own toggle so either can be switched off later without code:
   `techniques.scout.s1_insider_enabled`, `techniques.scout.s2_earnings_enabled` (both default on). **Full
   visibility:** a Scout page (candidates with their evidence, every LLM verdict with its citations, each lane's
   book and P&L) plus the daily report.
2. **Gates as recommended** (price >= $5, ADV >= $5M, spread <= 0.5%, cap >= $300M), each a `techniques.scout.*`
   setting. Paper money first - "be aspirational".
3. **LLM budget US$15/day** (`techniques.scout.llm_budget_usd_day`). **Two analyst lanes on the same candidates:**
   Claude Opus 5.5 (the Tips analyst's model, effort medium) and OpenAI GPT-6.1 Sol (`gpt-6.1-sol`, ~$2/$10 per
   million tokens per third-party pricing pages - verify on the official page before relying on it). Each has its
   keep/drop lanes; the comparison is part of the experiment. The OpenAI client lives inside Scout only; the user
   adds `OPENAI_API_KEY` to backend/.env (until then the GPT lane is skipped and says so).

## 8. Research note ("dossier"), built 2026-10-11 (0.9.26)

User request 2026-10-11: let Scout act as a financial analyst on a company, without making it complicated enough
to make mistakes. Decision: the note is a RESEARCH AID for the user, not a signal. It feeds no book, is never
masked (a person reads it), and is not part of the keep/drop experiment in sections 2 to 7.

How it is kept honest (`techniques/scout/dossier.py`, `fundamentals.py`):

- Code computes every number: SEC XBRL `companyfacts` (revenue, margins, cash flow, balance sheet, share count),
  daily bars (returns against SPY, range, averages, volatility), valuation ratios, Form 4 open-market trades on
  file, recent 8-Ks and the next results date. Each is a numbered fact. What cannot be established is left out and
  the sheet says so (stale tags, financial companies' cash flow and debt, foreign-currency reporters' ratios).
- One Claude call (Opus 5.5, effort high) writes the note from the fact sheet and the latest results press release.
  Every point cites fact ids or a verbatim quote from the release; code removes anything else and keeps it on the
  record as dropped. The model gives a lean (constructive / neutral / cautious), never a price target or an order.
- No tools are handed to the model and it sees no chart images: models read tables more reliably than pictures, and
  a single call with a fixed input is reproducible. The page draws the charts for the reader.
- Own daily cap `techniques.scout.dossier_budget_usd_day` (US$5; a note costs about US$0.10), apart from the lanes'.

Known limits: XBRL lags a results release until the 10-Q or 10-K is filed, so the newest quarter can be missing for
days (the note says so when it sees the release); "long-term debt" is the tagged figure and can omit leases and
short-term borrowings; the company background is the model's own knowledge and is labelled unchecked; funds and
companies that file no US statements get an error or a price-only sheet.

API: `POST /api/scout/dossiers {ticker}`, `GET /api/scout/dossiers`, `GET /api/scout/dossiers/{id}`. UI: Scout >
Research, and "Research note on <ticker>" in a candidate's detail. Tests: `tests/test_scout_dossier.py`.
Long-hold replay (same evening): `replay/README.md` - no edge at 20 to 120 sessions either.
## 9. The Scout agent - autonomous research and proposals (user decision 2026-10-14, built 0.9.35)

User, 2026-10-14: "the idea is that the scout gets automatically used with an smart llm system and suggest investments
not that a human uses it"; plan approved the same evening with every default ("go with all recommendations and p1 up to
p5"). This is a SEPARATE experiment from sections 2-7 (the screen + keep/drop filter): there the model may only veto a
rule's candidate; here the model finds and proposes trades itself, and is judged prospectively against fair controls.

**Honest frame.** No published evidence shows a language model picks stocks with an edge, and backtests of model picks
are contaminated by what the model has seen (section 1, [F6]). So the agent is judged ONLY live, from
`techniques.scout.agent_sample_start` (2026-10-15), on simulated research books, against a random twin of every pick.

### 9.1 How a day runs (`techniques/scout/agent.py`)
- 07:30 ET `scout_agent`: code chart-reads Scout's own universe (`AGENT_UNIVERSE`, ~150 liquid US names, plus
  `agent_universe_extra`) and ranks it (`agent_tools.screen`: 60d and 20d return vs SPY, 5-day volume ratio; above the
  50-day average, price >= $5, 20-day dollar volume >= $5M). Each model lane then runs a tool loop.
- Tools (all numbers computed by code, quotable lines, `agent_tools.py`): `chart` (trend, 20/50/200-day averages, ATR,
  returns vs SPY, RSI, 20/55/52-week ranges, swing support/resistance with touches, volume ratios, gap, last 10
  sessions), `fundamentals` (the research note's SEC fact sheet + results release excerpt, `DossierDesk.gather`),
  `options_view` (30-day IV, implied 1/10-session move, at-the-money straddle), `events` (next earnings), `book`,
  `past_cases` (closed picks + active lessons). The screen and the book are given up front as results T1/T2. No chart
  images: the model reads numbers.
- The model ends with `submit_proposals` (0-3). Code checks each (`agent_plan.check`): every evidence item must quote a
  tool result of THIS run verbatim (min 2 grounded); the ticker was charted; long shares only; stop 0.5-4 ATR below
  the entry; first target >= 1.5R; horizon 3-20 sessions, cut to end before a known earnings date (< 3 left = refused);
  limit entries at or below the last close; not held or proposed twice. Refusals stay on the record.
- Accepted -> a `ScoutCandidate` (kind `agent_pick`) + a pending `ScoutEntry` in the lane's book. The existing entry rule
  fills it 10:00-11:30 ET (spread gate; a limit plan also waits for ask <= limit, else `level_not_reached`).
- Sizing at the fill (code): qty = 1% of book equity / (fill - stop), capped at 20% of equity and by cash.
- Exits (position manager, policies-as-data): the plan's stop on the daily close, targets as a half/half ladder with
  the stop to entry on the first trim, time exit at the horizon, gap exit.

### 9.2 Lanes (shadow books, $10k each, sim executor only)
| Book | What it trades |
|---|---|
| `agent_claude` | Opus 5.5 (effort high) picks |
| `agent_gpt` | GPT-6.1 Sol on the same tools and prompt |
| `agent_random` | for every Claude pick, a seeded random name from the same universe (excluding names the agent charted), with the pick's geometry in ATR units (stop distance, limit offset, targets in R, horizon) |
| `agent_screen` | the screen's top 3 names on a fixed plan (now, stop 2 ATR, targets 2R/3R, 10 sessions) |

The agent's candidates are kept out of the section 2-7 baseline pools and candidate lists (they have their own tab).

### 9.3 Learning loop
16:30 report: closed agent trades become cases (`enrich_cases`: result in R, best/worst excursion in R from daily
bars, SPY over the hold, excess return). Week's last session 16:45 ET `scout_agent_review`: one Claude call over the
closed cases writes lessons; each must cite >= 2 case ids (else discarded); max 8 active; a lesson is supplied to runs
only from the NEXT week's first session (`effective_from`), never mid-week; the review may retire a lesson. The active
lesson set's hash (`lessons_version`) is stamped on every run so results can be split by lesson set.

### 9.4 Scorecard and graduation gate (`agent_score.py`, preregistered)
Per lane: closed trades, mean R (net after $1/order fees over planned risk), hit rate, mean excess vs SPY, net P&L.
Comparisons with a DATE-CLUSTERED bootstrap (sessions resampled, 2000 draws): Claude - random (the gate), Claude -
screen, GPT - random. Gate (all must hold): >= 40 closed Claude-lane trades; >= 8 weeks since the sample start; Claude
net P&L > 0; the 95% lower bound of (Claude mean R - random mean R) > 0. Otherwise "no proven edge yet".

### 9.5 What passing the gate does - and does not do
Nothing by itself. Scout never routes to IBKR (standing constraint). The next step - the agent's picks as approval
cards on the IBKR Paper book, at small size - is the user's decision when the gate passes, and real money keeps the
per-card OK. That wiring is deliberately NOT built.

### 9.6 Budget and knobs
`techniques.scout.agent_*` (settings_service): own daily cap `agent_budget_usd_day` $10 (both lanes + the review; a call
whose worst case would exceed it is not made - the run is recorded `budget`), 16 turns / 24 tool calls / 12k tokens per
call, one moving prompt-cache breakpoint. Expected cost ~$1-2 per Claude run. Do not tune thresholds mid-sample; a
change is a new prompt/plan version.

### 9.7 API, UI, tests
`GET /api/scout/agent` (runs, scorecard + gate, lessons, lane books), `GET /api/scout/agent/runs/{id}` (with the
transcript), `POST /api/scout/agent/run` (run today now; idempotent per day and lane). UI: Scout > **Agent** (default
tab). Tests: `tests/test_scout_agent.py` (fake providers only - no model call).

### 9.8 Limit entries worked for three sessions (2026-10-21, 0.9.39; user: "improve and use scout more")
Finding: in the first 7 sessions the Claude and GPT lanes proposed 18 trades and 3 filled. 17 of the 18 were limit
buys 1-6% under the last close, and a limit was tried only at the 15-minute slots from 10:00 to 11:30 ET on the entry
session. The lanes were judged on almost nothing. The tips desk's measured record (2026-10-21: 272 option tips, negative
under every exit rule) also made Scout the desk's own idea source to build on, not a side study.

Change (entry rule only; screen, checks, sizing and exits unchanged):
- A LIMIT plan (agent picks and their random twins alike, so the comparison stays fair) is worked 10:00 to
  `techniques.scout.agent_limit_end` (15:30 ET) for `techniques.scout.agent_limit_sessions` (3) sessions, the entry
  session included (`entry.limit_window`). The last slot of a non-final session carries the limit to the next session.
  The last slot of the final session skips it (`level_not_reached`). A "now" plan keeps the 10:00-11:30 rule.
- A limit filled on a later session keeps the plan's END date: the horizon is reduced by the sessions waited (the
  horizon was already cut before a known earnings date at proposal time).
- Prompt `scout-agent-v2` tells the agent how a limit is worked. `agent_max_proposals` 3 -> 5 (more cases per week).
- Runs are labelled by prompt version. The gate's sample start (2026-10-15) is unchanged: the v1 sample is only 3
  fills. A scorecard split by prompt version is not built yet.
