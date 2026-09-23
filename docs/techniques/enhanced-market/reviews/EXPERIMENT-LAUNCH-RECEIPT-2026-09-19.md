# EM Experimental - launch receipt (2026-09-19)

Answers the user's direction `2026-09-19-ACTIVE-EXPERIMENTAL-PRACTICE-ROLLOUT.md`: a dedicated sim-only Practice book runs the integrated EM bundle
ACTIVELY from the next eligible session, beside the unchanged EM Practice baseline. Simulated money only. No live account, no baseline configuration
and no other desk was changed. Frozen definitions: `research/EXPERIMENT-DEFINITIONS-2026-09-19.md`.

| Item | Value |
|---|---|
| Experimental book | **EM Experimental**, id **`07ef1e867cad4150bc81e072a8fd600a`**, kind `sim` (Practice). No matching book existed; one was created, none was reset |
| Baseline book | EM Practice, id `045d8c35b3f149628ea001ae90a58edb`, unchanged, flat at launch |
| Starting equity | **9,849.6032** = the baseline's recorded equity (its last persisted equity point and cash; it held no position). Both comparison series start at **2026-09-19T18:18:02Z** |
| Deployed build | **v0.8.26**, build `8645a61286f96303df7fda563aa66a698579e69a`; deployment receipt `phase: verified`, `restoration: ok`, 2026-09-19T18:17:24Z |
| First session | Monday **2026-09-21** |
| Operating owner | EM desk (this EM Dev session): attends pre-open, the open and the close; runs the daily comparison; rollback = pause the experimental book |

## 1. Active policies (book-scoped overrides of `techniques.enhanced_market.experiment`, version `em-experiment-v1`)

| Switch in the experimental book | Value | Policy version | Trades or observes |
|---|---|---|---|
| `preparation_policy` | `deterministic` | `em-prep-policy-v1` | ACTIVE: selects and arms the plans |
| `conditional_review_fix` / `prep_grade_floor` | `apply` / `B` | `conditional-review-v1` | ACTIVE |
| `first_sale_rr_gate` | `enforce` | `first-sale-v2` | ACTIVE: refuses or defers entries, rechecked at final dispatch |
| `book_snapshot_observe` | `true` | `book-snapshot-v3` | measurement (its own recorder and ledger); never trades |
| `source_candidates_execute` | `true` | `source-continuation-v1`, `requalification-v1`, promotion `em-experiment-v1` | ACTIVE: live candidates of the day are promoted once into real simulated plans |
| `runner_protection` | `execute` | `tp1-reclaim-runner-exit-v1` (P-06) | ACTIVE: a reduce-only exit of the whole remainder after a confirmed TP1 fill; production stops and targets go first |
| P-02 `small-position-exit-v1` | paired observation, both books | - | observation only. No blanket early-TP1 exit is on |

Technique-wide EM settings are untouched and still at their defaults: `first_sale_rr_gate` off, `preparation_policy` baseline, `book_snapshot_observe` /
`source_scenarios_observe` / `source_candidates_observe` off. `shadow_exit_observe` and `shadow_p02_candidate` stay on. Exactly ONE setting was written during
the launch: the experiment key (one journaled `SettingChanged`). Risk limits are the same for both books: the experimental arm configuration differs from the
baseline's only in the book id and in the per-plan daily loss limit, which the same rule derives from each book's equity (393.98 vs 405.96).

Two order-free, technique-wide side effects of an enabled experiment, stated plainly: the ingestion board check now also builds and stores the source
scenarios artifact (and runs its supersession query), and the one-minute candidate evaluation pass runs. Neither arms or orders anything; the baseline arm
decision reads neither.

## 2. Preparation counts for 2026-09-21 (journaled `TechniqueExperimentPrepared`, 18:23:18Z)

| Sheet rows | Eligible under the rules | Refused by the rules | Plan runs minted | Armed in EM Experimental | Already armed | Model calls | Errors |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 144 | **79** | 65 | 79 | **79** (mode auto) | 0 | **0** | 0 |

Sheet `8e47c46d` (the same sheet the baseline uses). A second preparation on the live system minted 0 and armed 0 (79 reused, 79 already armed):
idempotent and restart-safe. From now on the experiment's own loop prepares each next session once its sheet exists, single flight, and finds a prepared
session in the database after a restart. Ingestion-built board plans and pre-open re-plans are copied or kept in the experimental book under the same
owner. Source and requalified candidates are promoted during the session only; nothing historical or expired is replayed into orders.

The baseline's plans for Monday are NOT armed yet: its model-reviewed evening preparation runs on its usual schedule (Sunday evening), in its own book.

## 3. Routing verification on the live system

| Check | Result |
|---|---|
| EM plans armed for 2026-09-21 | 79, ALL in `07ef1e86...` (sim), status armed, mode auto; 0 in any other book |
| Experimental arms whose run is not tagged `experiment:em-experiment-v1` + `xbook:<id>` | 0 |
| Tagged runs armed in any other book | 0 |
| Model passes on experimental runs | 0 |
| Orders / executions in the experimental book | 0 / 0 (market closed) |
| Other desks after the deploy | 25 of 25 plans restored equal by id (Tips, Team2, Cartel), 28 resting orders and 6 managed positions equal, nothing open or in flight |
| Shared capacity | cash, positions, exposure caps, daily-loss halts, the duplicate window and `max_open_trades` are per book. Shared by design: the kill switch, `techniques.enhanced_market.paused`, and ONE global order-rate window (30 per minute, all desks). EM's busiest minute since 09-08 was 2 BUY orders and the busiest all-desk minute 12, so two EM books stay far below it; I did not touch that knob |
| Engine | healthy, readiness safe. One 3.3 s event-loop stall was recorded DURING the 79-symbol preparation (market closed). The daily preparation runs after the close; I will watch it on the first weekday run |

## 4. Acceptance tests (final candidate; reviewer files unchanged)

`tests/test_em_experiment.py`, 9 cases on the real engine, sim broker, API and Postgres: policy resolved per book and an invalid setting enables nothing; the
boundary is two-way and sim-only; nothing is fabricated and history is never replayed; routing is book-scoped with the baseline unchanged (two first-sale
policies at once, separate positions and cash, order tags, the book-scoped pause); P-06 executes only in the experimental book with conserved confirmed-fill
quantities; a stop goes first and no TP1 fill means no protection; **a promoted source candidate really fills a simulated order in the experimental book while
the same research object is refused by every ordinary arm path**, promoted once under concurrency, restored after a restart even with the experiment off; one
requalified child is promoted once with its frozen geometry and disarmed at its horizon; preparation is deterministic, duplicate-safe, automatic,
restart-safe and independent of the baseline's arm of the same candidate.

| Run | Result |
|---|---|
| EM + reviewer EM + worker suites, ingestion, platform separation (on `b1bd0f3d`, the same EM code) | 354 passed, 5 pre-existing skips |
| Technique / platform / options batch (on `32e4935c`) | 216 passed, 1 failed: the Team2 event contract, their open PR #224 |
| Arming suite alone (on `dc54d424`) | 31 passed |
| Final candidate `81cd7313` (= deployed code; later commits are documents): experiment, integrated API, ingestion, separation | 27 passed |
| Reviewer-database files incl. all dispatch cases (final candidate) | 26 passed |
| Build, release check 0.8.26, import | green |

One arming case failed once in a run that shared the machine with another desk's suite (a timing race, about 2 GB free memory); it passed alone and in the
full rerun. Owner reviews of the shared runner hooks: Tips / platform desk and Team2 desk, both NO OBJECTION (reviews, not deploy approvals); Team2 ran 367 of
their cases green on the hooks.

## 5. Genuinely not available, and honest limits

1. Attribution per component does not exist: the book runs ONE bundle.
2. Promotion runs once a minute, so a promoted plan starts watching up to about a minute after its candidate is born, and it runs without the opening-gap rule (marked `gap_unchecked`), like any late start.
3. A source-continuation candidate whose exact trigger is already traded by the prepared plan is recorded as covered, not armed twice.
4. Executable-profit capture scores only quotes with a venue identity (`opra` / `ibkr`, a venue quote time, displayed size). If the Practice feed cannot supply them for a position, coverage will be low and will say so.
5. First-sale enforcement DEFERS an entry when the validated underlying evidence is missing. If that turns out to be frequent, the experimental book will trade less than the baseline for that reason alone; the daily report shows refusals by stage.
6. The daily comparison tool is new and has only been smoke-run on a past session: `python -m zargar.tools.em_experiment_report report --date <D>`.

## 6. Rollback

`POST /api/portfolios/07ef1e867cad4150bc81e072a8fd600a/pause`: new experimental entries stop, open experimental positions stay managed to their exits, all
evidence stays. No live account, no baseline setting and no other desk is touched. Setting `enabled: false` stops preparation and promotion as well; armed
experimental plans still restore after a restart.
