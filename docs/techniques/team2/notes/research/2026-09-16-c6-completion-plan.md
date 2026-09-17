# C6 — one tape: completion plan (2026-09-16, Team2 desk)

*C6 is the prerequisite the other team set for every Team2 profitability experiment (2026-09-13) and the ONLY blocker on the
experiment readiness receipt. This note says what C6 is, what is already true, what remains, who does it, what evidence closes
each step, and how the receipt turns READY. The gate is not waived by anyone: the receipt refuses a missing evidence record.*

## 1. What C6 means

The live desk decides on Alpaca exchange 1m bars (provenance `exchange`, persisted through `persist_bars`, F75); every sweep,
replay and report that claims to measure the method must consume exactly that tape — the same rows, the same warm-up, the
same session validation — so a research number and a book result are two measurements of ONE experiment. F119 (2026-09-11)
established parity of the read event-for-event over a full session with two residues: bar-boundary splits of ±1 bucket
(accepted as noise) and an ATR that comes in LOWER in replay than live on every run (SPY 0.2246 vs 0.2018, QQQ 0.2949 vs
0.2525, IWM 0.1277 vs 0.1145 on 09-11) — systematic, unexplained, and the venue question the user was asked to rule on.

The sizing-cap and C1 experiments are read on Practice books, but their thresholds, the calibration (`calibrate_practice.py`)
and the C2 development sweeps were computed on the research tape; the other team's condition is that the research tape and
the live tape are one before an experiment result is compared to a research prior.

## 2. What is true today (measured 2026-09-16 evening, runtime DB, read-only)

- The `bars` table holds `source=exchange` 1m rows for SPY, QQQ and IWM from 2026-08-14 through 2026-09-16.
- Regular-hours coverage 2026-08-20 → 2026-09-16: **63 symbol-days, every one 390/390 minutes with provenance `exchange`**
  (query in the desk's session log: per (symbol, ET date) counts of RTH rows by source; no day under 385). The development
  window (08-20 → 09-11) and the sealed validation window to date (09-14 → 09-16) are fully banked.
- Rows with provenance `unknown` (Yahoo, pre-F75) and `sampled` still exist for the same symbols; none of them are RTH minutes
  inside the window (the precedence upsert replaced them where an exchange bar exists).
- `zargar.tools.team2_c2_report` refuses to report unless every sweep consumed one `datasetVersion`; the validation window is
  sealed inside it.

## 3. What remains — steps, owner, evidence

| # | Step | Owner | Closes when |
|---|---|---|---|
| 1 | **Freeze the dataset identity**: `marketdata.dataset_version` for SPY/QQQ/IWM 1m, 2026-08-20 → the session before activation, computed on `source=exchange` rows only; confirm replay/sweep readers take NO `sampled`/`unknown` fallback inside RTH | platform owners | the hash is recorded (this note + `c6-evidence.json`) and a re-run reproduces it |
| 2 | **Explain the ATR difference**: replay 2026-09-16 (three runs) against the banked tape with the live warm-up rule (F99) and compare `atr`, EMA13/48/200 at the open and every fire/skip event with the live records; identify whether the live warm-up read extended-hours or sampled minutes the replay does not (or the reverse) | Team2 desk (after the 09-17 close) | a dated parity note with the cause; either the code is aligned (one warm-up source) or the user rules that the live source is canonical and replay adopts it |
| 3 | **User ruling (F119)**: which venue's bars are the desk's tape when they disagree — the answer is already Alpaca exchange for the live desk; the ruling records it for research | user | one line in TRADING-RULES' change log |
| 4 | **Evidence record**: `notes/research/c6-evidence.json` = `{"satisfied": true, "reviewedBy": "<other team>", "date": "YYYY-MM-DD", "datasetVersion": "<hash from step 1>", "reference": "<this note + the parity note>"}` | other team writes/reviews; desk commits | the file exists on main with all five fields |
| 5 | **Receipt**: `python -m zargar.tools.team2_receipt --date <next session>` reads the record; then `techniques.team2.default_portfolio` = Control, `experiments.enabled` = true, forced plan-now; the receipt must say READY with zero blockers | Team2 desk | READY receipt text sent with the activation snapshot |
| 6 | **GO** | other team | their written GO; nothing is armed on the experiment books before it |

Step 2 is the desk's own work and starts tomorrow after the close (it needs a complete session on the new diagnostics build).
Steps 1 and 4 need the platform owners / the other team; the desk will send them the step-1 query and hash request with
tomorrow's review packet.

## 4. What C6 does NOT change

- No research knob, threshold or experiment setting moves. The sealed C2 validation window stays sealed.
- The shadow diagnostics (v0.7.100) run on the live tape regardless of C6; their outcomes are after-cost quote observations,
  not research-tape numbers, so they are interpretable before C6 — with tiny counts.
- The receipt is the only door to activation; a receipt that says PREPARED is not a receipt that says READY.
