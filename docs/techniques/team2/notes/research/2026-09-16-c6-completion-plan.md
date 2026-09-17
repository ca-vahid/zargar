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
- Regular-hours coverage manifest (per ET date, per symbol, RTH rows by provenance; re-measured 2026-09-16 22:20 ET):
  **21 dates 2026-08-18 → 2026-09-16, each of SPY/QQQ/IWM at exactly 390 `exchange` rows, no other provenance inside RTH.**
  The earlier "63 symbol-days for 08-20 → 09-16" was miscounted: 63 = 21 dates × 3 from 08-18; the review's 19 trading dates
  from 08-20 are **57 cells**; the development window 08-20 → 09-11 is 16 dates = **48 cells** (the paired-comparison count),
  and the sealed validation window to date (09-14 → 09-16) is 3 dates = 9 cells. Manifest:

  | dates | SPY | QQQ | IWM |
  |---|---|---|---|
  | 08-18, 08-19, 08-20, 08-21, 08-24, 08-25, 08-26, 08-27, 08-28, 08-31, 09-01, 09-02, 09-03, 09-04, 09-08, 09-09, 09-10, 09-11, 09-14, 09-15, 09-16 | 390 exchange each | 390 exchange each | 390 exchange each |

- **Coverage does not identify the provider (review team, 2026-09-16).** Three writers stamp `exchange`: Alpaca's bar stream
  (`brokers/alpaca.py`), the aggregator's exchange ingest (`marketdata.py`), and the boot seed (`engine.py`), which re-reads
  "today's exchange minutes" through `marketstructure.history.fetch_window` and stamps the result `exchange` WHATEVER provider
  served it. The precedence upsert (`SOURCE_RANK`: exchange 3 > sampled 2 > unknown 1 > sim 0) treats two `exchange` rows as
  peers and merges them, so a later Yahoo-served write can overwrite an Alpaca minute without a trace. A hash over
  `source=exchange` rows therefore proves completeness, not an Alpaca-canonical tape.
- Rows with provenance `unknown` (Yahoo, pre-F75) and `sampled` still exist for the same symbols; none of them are RTH minutes
  inside the window (the precedence upsert replaced them where an exchange bar exists).
- `zargar.tools.team2_c2_report` refuses to report unless every sweep consumed one `datasetVersion`; the validation window is
  sealed inside it.

## 3. What remains — steps, owner, evidence

| # | Step | Owner | Closes when |
|---|---|---|---|
| 1 | **Freeze the dataset identity**: `marketdata.dataset_version` for SPY/QQQ/IWM 1m, 2026-08-20 → the session before activation, computed on `source=exchange` rows only; confirm replay/sweep readers take NO `sampled`/`unknown` fallback inside RTH | platform owners | the hash is recorded (this note + `c6-evidence.json`) and a re-run reproduces it |
| 1b | **Provider provenance**: which adapter wrote each `exchange` minute (Alpaca stream / Alpaca backfill / boot seed via `fetch_window` → which provider). Either a `provider` column (or a provenance manifest keyed by symbol-minute) or an audit that reconciles every RTH minute in the window to an Alpaca fetch; the boot seed stops stamping non-Alpaca bars `exchange` | platform owners | a per-date/symbol table of provider counts with zero non-Alpaca RTH minutes, or the rows named |
| 1c | **Precedence / merge policy**: state what happens when two `exchange` writers disagree on one minute (today: peers, merged) and prove a Yahoo-served write cannot overwrite an Alpaca minute after the dataset is frozen (a guard, or a frozen snapshot table the readers use) | platform owners | the policy in PLATFORM-RULES + a test that a later non-Alpaca write leaves the frozen minute unchanged |
| 1d | **Same decision-time inputs, live and replay**: the live read's warm-up (F99: prior sessions, extended-hours bars, provenance) and the replay's warm-up are the same rows — the ATR difference in step 2 is the symptom; the proof is a side-by-side of the warm-up row sets (hashes) for one session, not a smaller ATR gap alone | Team2 desk + platform owners | equal warm-up hashes live vs replay for 2026-09-17, or the differing rows named and a ruling |
| 1e | **Pre-market and warm-up inputs reconciled** (2026-09-17 finding: the private tape accepted exchange CORRECTIONS the bank never kept — SPY PML 660.65 vs 757.53, IWM 283.92 vs 285.35, QQQ PMH 716.76 vs 716.78; `notes/research/2026-09-17-premarket-input-reconciliation.md`). Each plan's `pmExtrema.inputs.hash` (v0.8.12) equals the hash of the bank's pre-market rows for its date, or the differing minutes are named and ruled on; the same for `plan.warmup.hash`; the platform owners state why corrections reach one tape and not the other and whether a corrupt correction is quarantined at intake | Team2 desk (audit: `python -m zargar.tools.team2_pm_audit --date`) + platform owners | equal hashes for the sessions in the evidence window, or the named differences with a ruling |
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
- The shadow diagnostics (v0.8.01) run on the live tape regardless of C6; their outcomes are after-cost quote observations,
  not research-tape numbers, so they are interpretable before C6 — with tiny counts.
- The receipt is the only door to activation; a receipt that says PREPARED is not a receipt that says READY.
- No `satisfied: true` record is written from coverage and a generic `exchange` hash alone (review team, 2026-09-16): steps 1b–1d
  are part of C6, not follow-ups. Nothing in this plan inspects or retunes the sealed C2 validation outcomes.
