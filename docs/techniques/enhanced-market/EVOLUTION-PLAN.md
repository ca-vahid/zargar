# EM Evolution Plan — the بستر for a method that keeps learning

*2026-08-29. Context: week 1 live showed the funnel is R2-shaped (66% of
candidates die on a gate written for a different archetype), the author's
modern practice has drifted from his book (continuation breakouts, gap-fill
targets, fast exits, indices, swing lane), and we now have a working pipeline
for ingesting his current teaching (video → transcript → analysis). This plan
turns one-off learning into a standing loop.*

## Principles

1. **Evidence over authority.** Nothing from a video, post, or book changes a
   live parameter directly. Everything becomes a *hypothesis* with a testable
   spec and a decision threshold, exactly as TRADING-RULES already does it.
2. **The method is data.** Archetypes, gates, exits, and prompts are versioned
   values (rulebook/thresholds/policies), not scattered code — the platform
   refactor (marketstructure parameterized by rules) made this possible;
   evolution finishes the job.
3. **Shadow before money, practice before live.** New behavior earns its way
   up a ladder: backtest variant → shadow instance → practice-money instance →
   (eventually) live. Each promotion is a journaled human decision.
4. **The platform stays generic.** Everything here lives in EM's hooks,
   configs, prompts, and docs — or in the shared research/marketstructure
   libraries as parameterized tools. No EM knowledge leaks into the runner.
5. **TRADING-RULES is the constitution.** Hypotheses enter §3, experiments
   live in §1 with thresholds, settled results move to §2, every change is
   §5-logged. The evolution loop automates the *evidence gathering*, never
   the *judgement*.

## The loop

```
ingest (videos/posts/own reviews)
   → hypothesize (structured claim + testable spec → TRADING-RULES §3)
      → backtest variant (deterministic sweep vs baseline, free)
         → shadow instance (registered technique, sim fires, full trace)
            → practice-money instance (small risk, Practice account)
               → promote into EM proper / kill  (§5 change log)
```

Each stage has a kill gate; most hypotheses should die cheaply at the sweep.

## Phase 1 — Variant harness (the enabler; build first)

The single piece that unblocks everything: run the walk-forward **with a
modified rules value** side-by-side with baseline and diff the outcomes.

- `Thresholds`/rulebook overlay as data: a *variant* = named JSON overlay
  (e.g. `{"rr_gate": 2.0, "kinds": +["continuation"], "exit": "tp1_heavy"}`)
  stored with the sweep row provenance.
- Sweep compare: one command / Validation-tab action → baseline vs variant(s)
  over N days: fires, sumR, avgR, win rate, per-gate kill diffs, per-kind
  breakdown, spread-cost estimate. Output lands in the sweep store like any
  sweep (journaled, citable ids for TRADING-RULES).
- New trigger *kinds* become tracker-rules parameterizations in
  `marketstructure` (shared, rules-driven — per platform rules), so a variant
  can introduce an archetype without forking the tracker.
- **Pilot experiments** (already specced as theories):
  T-6 continuation-breakout (break prior-day high → next zone/gap edge,
  rr ≥ 1.5, TP1-heavy or time-boxed exit), T-7 gap-fill target anchors,
  T-8 index-ETF lane (SPY/QQQ/IWM), §1.8 rr-band 2.0–3.0.

## Phase 2 — Ingestion (recent videos & posts)

**Decision history:** 2026-08-29 the user scoped ingestion to Claude sessions
only; **2026-09-01 the user reversed this** after a week of daily manual
ingestion proved the value — the app now gets a dedicated, EM-only pipeline
watching the author's Discord server (morning video auto-capture, watch-list
posts, method-corpus channels). Full design: **`INGESTION-PLAN.md`** in this
folder. Governance is unchanged: the pipeline produces notes and candidate
theories; nothing auto-changes live parameters.

The manual session recipe below remains valid for ad-hoc material (links from
other sources, one-off videos):

The proven session recipe (first run 2026-08-28, ~10 min end to end):
1. scratch venv: `pip install yt-dlp faster-whisper` (ffmpeg already on PATH,
   winget Gyan.FFmpeg build);
2. `yt-dlp -x --audio-format mp3 -o <scratchpad>/clip.%(ext)s <tweet url>`;
3. faster-whisper `small` model, `vad_filter=True`, **Windows paths** (the
   /c/… Git-Bash form breaks PyAV);
4. frames when needed: Browser pane → enlarge the `<video>` element via JS →
   seek `video.currentTime` → screenshot;
5. transcript + analysis land in `notes/YYYY-MM-DD-<source>.md`, hypotheses
   go to TRADING-RULES §3, and each called setup gets a *ground-truth check*
   against our own bars (calibrates how much weight his calls deserve).

## Phase 3 — LLM tool belt (analyst & critic get hands)

Today the analyst/critic see one chart image + FACTS text. Give them tools
(a bounded tool-use loop in the vision pipeline, budgeted per pass):

- `get_bars(symbol, tf, window)` — look at another timeframe on demand.
- `get_level_history(symbol, price)` — touches/respects of a level over weeks.
- `get_gap_map(symbol)` — unfilled gaps above/below (T-7 fuel).
- `get_market_context()` — SPY/QQQ state, session stats (indices lead his calls).
- `get_outcome_stats(kind, rule, symbol?)` — **our own outcomes DB**: "what has
  this trigger kind / this gate historically done" — the critic judging from
  evidence instead of vibes.
- `find_similar_setups(embedding/params)` — past runs that looked like this
  one, with their outcomes.
- `get_option_context(symbol)` — spread/IV/DTE reality for the contract.
- Distilled **lessons memory**: reviews (we persist them) get distilled into
  short lessons retrieved by symbol/kind into the prompt — the method
  remembers its own mistakes without prompt bloat.

Cost control: tool budget per pass, `technique.arm.critic_effort` unchanged,
tools are read-only, every call lands in the run trace.

## Phase 4 — Shadow instances (evolution runs as siblings)

A variant that survives its sweep gets registered as its **own technique id**
(e.g. `em_cont_shadow`) via the platform registry — same shared libraries,
own rulebook overlay/prompts, sim workspace, alert-or-proposal mode, full
trace/outcomes/scorecards. It trades nothing real; it produces the same
review-loop data live EM does, on the same tape, at ~zero marginal cost
(deterministic fires; LLM only if the variant needs it).

- Promotion criteria (written per-variant in TRADING-RULES): e.g. ≥ 60 shadow
  fires, positive expectancy net of spread estimate, no unexplained
  divergences from its sweep profile.
- Demotion/kill likewise. Needs from engine team: per-technique pause,
  registry support for instance-with-config-overlay (mostly exists), settings
  live re-read.

## Phase 5 — Practice-money graduation + capture-rate telemetry

- Graduated shadow → Practice-account instance with small risk
  (`techniques.<id>.risk_pct` override), auto mode with all safety rails
  (loss halt, critic, kill switch) — the same ladder live EM climbed.
- **Capture-rate weekly report** (backlog #1 → automated): identified R
  (scorecards/sweeps) vs captured R (fills), with the friction reason for
  every gap; per-gate kill/save tallies; §1.x experiment tallies auto-updated
  as machine-generated sections. The human reads one page a week and makes
  the §5 calls.

## Phase 6 — Multi-day / swing lane

The author's flagship public setups (2h wedges held across days) need the
platform §2.4 runtime: policies-as-data exits, GTC venue stops, restart-proof
multi-day state, chaos suite. Sequence *after* phases 1–5 prove the loop on
intraday variants; the swing lane then enters as one more shadow instance
(`em_swing_shadow`) rather than a rewrite.

## Runbook — how to run one experiment (phase 1, operational)

Everything below is deterministic and free (no LLM calls). First run:
2026-08-29 pilot, sweeps `26f752fa5a` / `5a916ced73` / `9edf5248fa`.

1. **State the hypothesis** in TRADING-RULES §3 (or take an existing T-n):
   what changes, why, and the decision threshold that would promote or kill it.
2. **Express it as a threshold overlay.** Prefer expressing new behavior with
   existing knobs (T-6 needed zero code: rr gate + volume/decisive/follow-through
   knobs). Only add code when no knob combination can express the idea — and
   then add a *knob*, parameterized in the shared library, never a fork.
3. **Run baseline + variant over the same window** (Yahoo 1m depth bounds the
   window to ~3 trailing weeks; longer once archived bars accumulate):

   ```
   python -m zargar.tools.technique_review sweep --start A --end B --label "evo-baseline"
   python -m zargar.tools.technique_review sweep --start A --end B --label "evo-<name>" \
       --set key=value [--set key=value ...]
   ```

   Overrides are validated against `Thresholds` (typos fail loudly), recorded
   in `params.overrides`, and change `sweepVersion` — the variant is fully
   citable.
4. **Compare:** `technique_review sweep-compare <baseline> <variant>` — read
   the MARGINAL value of the extra (or removed) fires, per kind and per
   window, not the headline totals. Estimate spread cost (~0.1–0.2R/fire on
   single-name options; less on index 0DTE) before believing a thin mean.
5. **Log the verdict** in TRADING-RULES: evidence under the §1.x experiment or
   the §3 theory, citing sweep ids. A promoted change gets a §5 entry; a live
   parameter changes ONLY at that step, by hand, journaled via Settings.
6. Bigger deltas (new exit ladders, new archetypes with code) graduate through
   a **shadow instance** (phase 4), not straight to live.

### Where the LLM fits (and where it does not)

- **Sweeps are LLM-free.** The whole experiment loop above never calls a
  model — that is what makes it cheap enough to run weekly.
- **Ingestion extraction is the session's job** (this Claude, in-chat), not an
  app prompt: transcript → hypotheses → §3 entries.
- **The analyst/critic prompts stay method prompts.** They change only when
  the METHOD changes (e.g. the 2026-08-28 short-mirror fix), each change
  hashed into promptVersion.
- **A graduated variant that needs different judgement gets its prompt overlay
  at the shadow-instance stage** — the instance's own prompts/policies are part
  of its technique registration (platform supports per-technique prompts), so
  "EM-continuation" judging with different emphasis never edits live EM's
  prompt. No specialized evolution-prompt is needed before phase 4.

## Governance — what never auto-changes

- RiskGate, kill switch, loss halts, reduce-only exits: untouchable by any
  experiment. Variants inherit them all.
- Live EM's parameters change only via §5 entries made by a human decision.
- Shadow/practice instances are visibly labeled in the UI (registry chip).
- Every ingested claim keeps its source link; every promoted change cites its
  sweep/scorecard ids. If we can't cite it, we don't ship it.

## Sequencing

| # | What | Depends on | Size |
|---|---|---|---|
| 1 | Variant harness + T-6/§1.8 pilot sweeps | **built 2026-08-29** (`sweep --set`, `sweep-compare`; pilot + weekly audits running) | — |
| 2 | Ingestion pipeline (INGESTION-PLAN.md) | **built + live 2026-09-01** | — |
| 3 | LLM tool belt (start: get_outcome_stats, get_gap_map, get_bars) | — | days |
| 4 | Shadow instance registration | 1; engine-team pause/registry items | days |
| 5 | Capture-rate weekly report | 1 | ~1 day |
| 6 | Swing lane | platform §2.4 + chaos suite | later |

First concrete step: **Phase-1 variant harness with the T-6 continuation
sweep as the pilot** — it exercises rules-as-data, the compare report, and
directly answers week 1's "are we too strict" with numbers.

## Experiment log

- 2026-09-04 · **T-11 window-extremes level seed** (`seed_window_extremes`, TRADING-RULES §3):
  baseline sweep `evo-T11-baseline` 2026-08-24..09-03 (1,053 sessions, 26 fires, +0.79R);
  first variant run was invalid (the 2-touch floor still dropped single-touch extremes);
  v2 re-run after the fix: 26 fires / -0.12R vs baseline +0.79R -> NOT adopted (TRADING-RULES §3 T-11).
  Next variants: `lookback_sessions=5`; gap-through continuation.
