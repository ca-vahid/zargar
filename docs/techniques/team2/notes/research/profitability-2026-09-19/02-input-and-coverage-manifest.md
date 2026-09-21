# 2. Versioned input and coverage manifest

Machine-readable: `results/manifest_all_base_s0_proxy.json` (every symbol-day: bars, warm-up hash, scenario, entry attempts by
outcome, unknown marks, refusals, class) and the `meta` block at the top of every replay file. Status: developer-reported,
reproducible from the cached inputs with `harness/manifest.py`.

## Code and rules

| Item | Value |
|---|---|
| Code measured | branch `claude/trading-technique-research-56296a`, commit `806f20345bc7b4d5f9a5da48de5339b44d5fe826` (recorded in every replay file's `meta.codeCommit`; the harness imports the worktree named by `PYTHONPATH`, and `meta.zargarPath` records which) |
| Relation to the running build | the running build on 2026-09-18 was v0.8.20 (`f4ce6ad8`). The measured commit differs from it in `session.py`/`rules.py` only by two default-off research knobs; default parity was proven by hashing a September replay's trades and events with both codes (`cf62d34425106c39`, v1 harness) |
| Read functions | `build_skeleton`, `complete_plan`, `simulate_session`, `Team2Service.warmup_slice`: the same pure functions the desk runs |
| Effective baseline rules | `settings_service.DEFAULTS` overlaid with the runtime's stored Team2 settings read on 2026-09-18: `budget_per_trade` 2000, `risk_pct` 6, `max_risk_pct` 6, `target_replan` structure, `daily_loss_halt_pct` 10. The complete resolved rule set is stored in every replay file under `rules` |
| Rules that stay off | `key_levels` off (C2 sealed window preserved), `pm_room_atr` 0, `min_target_atr` 0, `stop_candles` 1, `target_collision` refuse |
| Contract authority in the replay | `model` branch of the read with the real-print model substituted for the formula: the read's own premium band decides eligibility on observed prints. The live desk uses `quotes` authority on the NBBO; that difference is a limitation, not reproduced |

## Data

| Input | Identity |
|---|---|
| Provider | Alpaca market data. Underlying: `/v2/stocks/bars`, `feed=sip`, `adjustment=raw`, `1Min`, extended hours included. Options: `/v1beta1/options/bars`, `1Min` (OPRA TRADE prints aggregated per minute; there are no historical option quotes) |
| Time range fetched | 2026-04-20 to 2026-09-18 (the first twelve sessions seed the warm-up; replay 2026-05-07 to 2026-09-18) |
| `SPY_1m.json` | 11,560,383 bytes, sha256 `f4b42a5e94d649ac…` (full value in the manifest) |
| `QQQ_1m.json` | 12,070,201 bytes, sha256 `b3172e5ff7e1d487…` |
| `IWM_1m.json` | 9,879,813 bytes, sha256 `13b1c2aacb25b8dc…` |
| Option cache | 3,385 contract-day files; set hash `7e5e475cf8980483f09daf48eaae79f053ff4ca61b38187736b197a8f30ef614` (sha256 over sorted file names and file hashes) |
| Calendar | `zargar.marketstructure.market_calendar.trading_days`; session dates by `session_date` (America/New_York) |
| Warm-up | twelve valid prior sessions through `warmup_slice` (live rule F99); the slice hash is recorded per symbol-day |
| Relation to the C6 canonical tape | same provider and feed as the desk's canonical Alpaca tape, fetched independently into a local cache; it is NOT the frozen C6 snapshot. Bars were compared with the runtime bank on spot checks only (2026-09-16 10:00 and 10:08 QQQ: identical) |
| Cached-input requirement | the cache is not in the repository (about 80 MB). `harness/v1/fetch_bars.py` re-fetches the underlying; option contracts are fetched on demand by the replay and cached. A re-fetch reproduces the hashes only if Alpaca serves identical history; the hashes above are what these results were computed on |

## Coverage and exclusions (baseline run)

| Level | Count |
|---|---|
| Sessions x symbols requested | 93 x 3 = 279 |
| Missing underlying data (`no_bars`, `no_prev_session`) | 0 |
| Sessions with a short regular session (< 385 one-minute bars) | 0 |
| Symbol-days with at least one trade | 176 |
| Symbol-days with a priced refusal only (a fire reached the contract step and was refused on prices) | 1 |
| Symbol-days with a genuine no-trade decision (the read never reached a contract) | 102 |
| Entry attempts that reached the contract step | 347 = 332 filled + 13 `no_observed_contract_in_band` + 2 `no_execution_print` |
| Filled entries executed in the decision minute / later | 332 / 0 |
| Management marks unknown (no print inside the 2m bar) | 1 |
| Trades censored (an exit without a print within five minutes) | 0 |
| Contract-day files with no print all day | 99 of 3,385 (far strikes on the ladder). A contract without prints may be unlisted or listed and untraded: prints cannot tell these apart, so "absent listing" is NOT separately identified |

Three different things are kept apart: **missing data** (none at the symbol-day level), **price unavailability** (15 refused
entries, 1 unknown mark, reported by reason), and **no-trade decisions** (102 symbol-days plus every `skip_*` refusal, which are the
read's own choices and are listed by reason on page 4).

## Common eligible sample for variant comparisons

All arms run on the same 69 training sessions x 3 symbols with the same inputs. Arms differ in WHICH entries they take, so page 5
reports, for every arm: entries common to the arm and the baseline (with both means), entries only in the arm, entries only in
the baseline, and censored counts on each side. Eligibility changes are therefore visible, not folded into one mean.
