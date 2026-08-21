# Technique Pipeline — implementation plan

Companion to [`TECHNIQUE-ENHANCEDMARKET.md`](TECHNIQUE-ENHANCEDMARKET.md), which
is the rule specification. This document is the **build plan**: what gets
written, in what order, and why.

Goal: the app learns the EnhancedMarket method, produces accurate setups
(entry / stop / targets) from a chart or a period of price history, and lets you
interrogate every run conversationally. Execution stays practice-only for now.

---

## 1. Design principle: hybrid, not pure vision

A vision model reading prices off pixels will not give accurate numbers, and
accuracy is the whole point. So the pipeline splits the work:

| Layer | Does | Why |
|---|---|---|
| **Deterministic** (Python over OHLCV bars) | Swing pivots, level clustering, touch counts, time-of-day volume baselines, candle geometry, trend structure, R:R arithmetic | Exact numbers, cheap, testable, reproducible |
| **Vision + reasoning** (Claude Opus 5) | Which levels *matter*, is this a wedge, is this a fakeout, does the setup hold, what's the narrative | The judgement the book is actually about — irreducibly perceptual |
| **Grounding** (Python) | Re-verifies every number the model emitted against the bars | Hallucinated levels die here |

This mirrors the discipline already in `signals/extraction.py::ground_signal`:
**the LLM proposes, deterministic code disposes.**

---

## 2. Backend package: `backend/zargar/technique/`

| Module | Responsibility |
|---|---|
| `rulebook.py` | Rule IDs → text, thresholds (Q1–Q10) read from settings. Single source of truth cited by prompts, code, and journal events |
| `levels.py` | Swing pivot detection, level clustering within tolerance, touch counting, prior-day HOD/LOD, round numbers (T1) |
| `volume.py` | Time-of-day baseline, relative volume, spike/dry-up, divergence (T2) |
| `candles.py` | Body/wick ratios, decisive-candle test, hammer/doji/engulfing (T3.4) |
| `structure.py` | Higher-highs/lower-lows, trend direction, wedge trendline fitting (T3.1, T3.5) |
| `render.py` | OHLCV window → PNG (price + volume subplot, level overlays) for the vision pass |
| `schemas.py` | Pydantic `TechniqueAnalysis` (the §9 contract) + the rulebook system prompt |
| `vision.py` | Multi-pass Claude analysis loop |
| `grounding.py` | Verify model claims against bars; fail closed |
| `options.py` | Tradier chain fetch + contract selection per T5 |
| `service.py` | Orchestration, journaling, setup emission, scheduled scans |
| `backtest.py` | Replay historical windows, score outcomes |

New tables: `technique_runs`, `technique_setups`, `chat_threads`,
`chat_messages`. All append-only or versioned — nothing is overwritten.

---

## 3. The multi-pass analysis loop

```
bars + (optional uploaded chart image)
  │
  ├─ deterministic pre-pass ──▶ candidate levels, volume stats, candle metrics
  │
  ├─ PASS 1  wide context   (1h/15m render + facts) ──▶ market structure, major levels
  ├─ PASS 2  pattern zoom   (5m)                    ──▶ wedge/flag/consolidation ID
  ├─ PASS 3  entry zoom     (1m at the level)       ──▶ precise entry, stop, candle read
  ├─ PASS 4  adversarial    ("kill this setup")     ──▶ fakeout test, rule violations
  │
  ├─ grounding ── fail ─▶ re-render adjusted window, retry (bounded, max 5 passes)
  │
  └─ emit TechniqueAnalysis + journal every rule fired
```

Pass 4 is deliberately adversarial: the book spends more pages on *not* taking
bad breakouts than on taking good ones, so the critic pass earns its cost.

---

## 4. Options (CBOE, was Tradier)

**Changed 2026-08-21: Tradier's developer signup requires a US address — not
available to the user (Canada).** Replaced by CBOE's free delayed-quotes JSON
(`cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json`): the whole
chain in one request **with greeks** (delta/gamma/theta/vega), IV, bid/ask +
sizes, OI, volume, and the underlying spot — no account, no token, ~15 min
delayed. Verified live from this machine. `TradierClient` is kept behind
`technique.options.provider = "tradier"` for anyone with a token, and IBKR
native chains slot into the same provider interface once the account activates.

Original Tradier notes: `/v1/markets/options/chains?greeks=true` returns bid/ask,
volume, open interest, delta/gamma/theta/vega, and bid/mid/ask IV (ORATS).

Selection per T5: nearest strike **just OTM** in the setup's direction; expiry =
**current-week Friday**, or **0DTE** when available (with the reduced size T5.2
requires); reject on high IV (T5.3) or wide spread / poor greeks (T5.4, R3.3).

Config: `ZARGAR_TRADIER_TOKEN`, `technique.options.enabled`.
**Blocked until the user supplies a token** — everything else proceeds without it.

---

## 5. Conversational review surface

Not a side panel — a first-class page. Every pipeline run is a **thread** you can
open, inspect, and continue talking to.

**Requirements**
- Full run transcript: each pass, the tools called, inputs and outputs, thinking.
- Continue the conversation after the run — ask follow-ups, give new instructions.
- The model has **tools** so it can answer with real artifacts, not prose:
  `get_bars`, `render_chart`, `compute_levels`, `get_option_chain`,
  `run_analysis`, `backtest_window`. Asking "show me the 5-minute with the levels
  drawn" produces an actual chart.
- **Paste or drop an image** — analyse any chart screenshot from any period,
  which also sidesteps the Yahoo 1m history limit.
- **Streaming** output with visible **thinking**.
- Everything persisted and searchable. Nothing is lost.

**Implementation**
- `claude-opus-5`, `client.messages.stream(...)`, `thinking={"type":"adaptive",
  "display":"summarized"}` — `display` must be set explicitly because Opus 5
  defaults to `omitted`, which would render as a long silent pause.
- Manual agentic loop (not the tool runner) so every tool call can be journaled
  and streamed to the UI as its own event.
- Server → browser over the existing WS hub as a new `chat` topic; new
  `POST /api/technique/chat` starts/continues a thread.
- Images as `{"type":"image","source":{"type":"base64",...}}` content blocks.
- Prompt caching on the rulebook system prompt (stable prefix, ~4k tokens).
- Persistence: `chat_threads` + `chat_messages` (role, blocks JSONB, usage,
  tool calls, thinking). Full history replayable; runs linked to threads.

---

## 6. Frontend

New sidebar page **Technique** (`src/pages/TechniquePage.tsx`):
- **Analyse** — symbol, timeframe, date/period picker, or drop a chart image → Run.
- **Result** — chart with levels / wedge lines / entry / stop / target bands drawn,
  the numbers, R:R, rules fired (each citing its ID), no-trade reasons, confidence.
- **Chat** — streaming thread with thinking, tool calls rendered as cards,
  inline charts, image paste.
- **History** — every past run, searchable, re-openable.
- **Backtest** — run a date range, score the setups, show the distribution.

Reuses existing Highcharts wiring (`StockChart.tsx`) per the CLAUDE.md rules
(imperative updates via ref, `highcharts/esm/...`).

---

## 7. Risk & safety posture

- No auto-execution. Setups become **proposals**, nothing routes to a live venue.
- Shadow portfolio `Shadow: Technique` trades every emitted setup so the method
  builds a track record before any automation is discussed.
- Technique-specific sizing caps (R1: 5% ceiling, 0.5–1% default) sit *inside*
  the existing `RiskGate` — no code path bypasses it.
- Every run journaled via `Journal.append()`; `events` stays append-only.

---

## 8. Build order

| Phase | Scope | Status (2026-08-21) |
|---|---|---|
| **1** | `technique/` deterministic core (levels, volume, candles, structure, setups) + tests | ✅ built, 59 tests |
| **2** | Chart rendering for vision (`render.py`, ET axis, level/wedge/setup overlays) | ✅ built |
| **3** | Vision pipeline (4 passes + grounding retries), journaling, `TechniqueAnalysis` | ✅ built, verified live on SPY/AAPL |
| **4** | Chat surface: streaming thinking, tools (8), images, persistence, search | ✅ built, verified live |
| **5** | UI page: Analyse · Chat · History · Backtest + right rail; Settings section | ✅ built, Playwright-verified |
| **6** | Options integration (`options.py`, T5 contract pick) | ✅ **live via CBOE — free, no credentials**; Tradier optional |
| **7** | Backtest harness + scoring (`backtest.py`, deterministic) | ✅ built |
| **8** | Scheduled scans (`technique.scan.*` settings, RTH-only, daily cap) | ✅ built, default off |

Everything is wired and live; no credentials outstanding.

### What was learned building it (keep in mind)

- **Structured-output schemas must be flat.** Nested Pydantic models + many `Literal`
  enums produced *"compiled grammar is too large"* (400). `TechniqueAnalysis` is flat
  with sentinel values; the nested §9 shape is rebuilt by `to_contract()`.
- **Opus 5 defaults thinking display to `omitted`.** `llm.thinking_display` defaults
  to `summarized` so the stream is visible; raw chain-of-thought is never returned.
- **Prompt caching works**: the rulebook system prompt (~2.6k tokens) caches on
  pass 1 and is read on passes 2–4 (`cacheRead` visible per pass in the UI).
- **Per run**: ~100 s, ~13k in / ~6k out tokens ≈ **$0.20–0.25** at effort `high`.
- **The forming bar** from a live feed has volume 0; `assess_volume` walks back to
  the last traded bar and reports `measurable=false` when no baseline exists.
- **Yahoo 404 on unknown symbols** becomes a note, not a crash; the run fails cleanly.
- **Image uploads are sniffed** (`sniff_media_type`) — the API rejects a mislabelled
  media type (the book's "png" extracts were JPEGs).
- **Mid-run reconnects**: `TechniqueService._live` keeps pass progress per running
  run and `GET /api/technique/runs/{id}` returns it as `live` so a reloaded client
  seeds its view.

---

## 9. Open items

- **Tradier developer token** — needed for phase 6. Free signup at
  developer.tradier.com; goes in `backend/.env` as `ZARGAR_TRADIER_TOKEN`.
- **Per-run cost** — a 4-pass vision run on Opus 5 is roughly $0.15–0.40
  depending on image sizes. Scheduled scans multiply this by symbols × frequency;
  a budget cap setting (`technique.max_runs_per_day`) is included in phase 8.
- **Symbol universe** — the book's examples are US large caps (SPY, TSLA, NVDA).
  Which symbols the scheduled scan should sweep is still to be set.
