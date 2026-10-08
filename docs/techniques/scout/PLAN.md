# Scout - research-only idea finder (plan, 2026-10-07)

**Status:** PLAN for the user's review. Nothing built yet. User decision 2026-10-07: the IBKR real-money go-live is
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

### 2.3 The LLM analyst (filter + explainer)

- Input: the facts for one candidate - the Form 4 rows or the earnings release text, recent price/volume numbers,
  sector, upcoming events - with company name and ticker **masked** where the judgement allows [F6].
- Output (flat schema, prompted JSON): `keep | drop`, a 1-5 conviction, the reasons, and **a quote with its source
  id for every factual claim**; a claim without a citation is discarded (grounding).
- It may veto (drop), never add a candidate. Budget: <= 20 deep reads/night, capped by a setting (~US$5/day).
- Its "drop" decisions are tracked as a counterfactual lane, so its value is measured, not assumed.

### 2.4 Trading rules (simulated, identical for every lane)

Position US$600 (*judgement*, matches the live book's slot size); stop 2x daily ATR; exits: time stop 20 sessions
(S1) / 10 sessions (S2), or the stop; no trims. Costs charged: $1 per order + half the quoted spread each side.
Research books only (one per lane): `Scout S1 screen`, `Scout S1 +LLM keep`, `Scout S1 LLM drop`, same for S2,
plus the random baseline.

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
| P3 | days 4-5 | LLM analyst (masked inputs, cited verdicts, budget cap) + research books per lane + daily report | First daily report |
| P4 | days 5-10 | Prospective run, no tuning; Tips paper keeps running | 2-week checkpoint review |

Constraints: Scout never routes to IBKR; it lives in `zargar/techniques/scout/` with its own settings
(`techniques.scout.*`); it uses the shared marketstructure/execution libraries, never Tips' or other desks' code.

## 5. Decisions for the user

1. Approve S1 (insider clusters) as the core and S2 (earnings reaction) as secondary - or pick only one.
2. Approve the gates in 2.2 (price >= $5, ADV >= $5M, spread <= 0.5%, cap >= $300M) or set your own.
3. LLM budget cap (suggested US$5/day).
4. Whether Scout may later share the IBKR account with Tips (a separate slot) once a lane passes - decided only after
   the 6-10 week evidence, not now.
