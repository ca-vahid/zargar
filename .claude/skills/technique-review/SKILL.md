---
name: technique-review
description: Review one technique (EnhancedMarket) analysis run end-to-end — replay what the pipeline saw, why it took each step, what it concluded, what price actually did afterwards and what the user expected — then classify the root cause and plan the code/prompt/threshold fix. Use when the user says "review run <id>", "why did the pipeline say setup/no setup on X", "this run was wrong", "what went wrong with the technique", "improve the technique", "compare run A and B", or "find the worst recent runs".
---

# Technique run review

The technique pipeline (`backend/zargar/technique/`, spec `docs/TECHNIQUE-ENHANCEDMARKET.md`,
book `docs/Day Trading 101 - From Beginer to Expert.pdf`) records everything per run id:
the bars it saw, the deterministic FACTS, every model pass (prompt, thinking, text,
structured output), a **decision trace** (each step + why), the provenance of the process
(prompt / rulebook / code / thresholds / settings versions), the **outcome** (what price did
afterwards, per plan) and any **reviews**. This skill turns that record into a diagnosis
and a fix plan, and persists the review so the next run can be compared against it.

Read `references/pipeline-map.md` once per session — it maps every stage to the code that
owns it. `references/failure-taxonomy.md` is the vocabulary for the verdict and root cause.

## The CLI

Everything goes through `zargar.tools.technique_review` (reads Postgres directly; the app
does **not** need to be running, except for `replay`). From the repo root:

```bash
cd backend && .venv/Scripts/python.exe -m zargar.tools.technique_review --help   # Windows
cd backend && .venv/bin/python -m zargar.tools.technique_review --help           # Linux / dev container
```

| command | use |
|---|---|
| `list [--unreviewed] [--wrong] [--outcome loss\|win\|stopped\|tp1..3\|not_filled\|pending] [--symbol S] [--verdict setup\|no_setup] [--json]` | pick what to review; `--wrong` = non-correct review or a losing outcome |
| `show <run_id>` | one-screen README + the trace |
| `dump <run_id> [--out DIR]` | write the full bundle to `DIR/<run_id>/` (default `./technique-reviews/`) |
| `score <run_id>` / `score --pending` | (re)score what price did after the run |
| `replay-facts <run_id> [--set key=value ...]` | recompute the detectors on the saved bars with the current code (and optional threshold overrides) and diff vs what the run recorded |
| `review <run_id> --verdict V --root-cause S [--expected setup\|no_setup] [--expected-type T] [--expected-entry P --expected-stop P --expected-targets a,b,c] [--expectation "..."] [--note "..."] [--action "..."]... [--reviewer user\|claude]` | persist the review |
| `reviews [<run_id>]` | list reviews |
| `diff <run_a> <run_b>` | compare analysis / thresholds / versions of two runs (e.g. parent vs replay) |
| `replay <run_id> [--set key=value ...] [--no-snapshot] [--note "..."]` | re-run the same moment through the live API (app must be running; costs a few model calls) |
| `taxonomy` | print the review-verdict and root-cause vocabularies |

Add `--json` before the subcommand for machine-readable output.

## Workflow

### 1. Pick the run
- If the user gave a run id (full or the 8–10 char prefix shown in the UI), use it.
- Otherwise run `list --unreviewed` and, when the user is hunting for problems,
  `list --wrong`. Show the table and ask which one (or take the newest losing one).
- If the outcome column says `pending`/`partial`, run `score <id>` first — a review
  without the outcome is only half a review.

### 2. Dump and read the bundle
`dump <id>` then read, in this order:
1. `README.md` — verdict, plan, process version, outcome, prior reviews.
2. `trace.md` — **the step-by-step story with reasons.** Note: what the detectors found
   (`data/facts`), what the drafts said (`entry/draft`), whether the critic killed or
   warned, how grounding went, why the loop stopped, whether the setup was valid and why.
3. `facts.json` — levels (price, kind, touches, position), volume, trend, wedge,
   `candidateSetups` (the deterministic plan the detectors built, with its
   `noTradeReasons` and `valid` flag).
4. `transcript.md` — the model's reasoning per pass. Look for where the narrative
   diverges from FACTS or from the book's rule.
5. `outcome.json` — per plan: filled?, outcome, R, MFE/MAE, `path` (+5/+15/+30/+60 bars).
6. `images/` — `Read` the PNGs (`1h.png`, `5m.png`, `1m.png`, `annotated.png`,
   `user.*`). Look at the chart yourself and form your own read *before* judging the
   model's; the picture is the ground truth for "was there a setup".
7. `journal.json` only if timing / ordering matters.

### 3. Get the expectation
If the user has not said what they expected, ask — one question, concrete:
"What did you expect here: setup or no setup? If setup — type, roughly where the entry and
stop should have been?" Record it verbatim for `--expectation`.
If the user is asking you to judge, form the expectation yourself from the chart + the
book's rules and say that you did.

### 4. Stage-by-stage audit
Build this table (it is the core deliverable — keep it tight, one line per stage):

| stage | what it saw | what it decided | evidence for/against | rule(s) |
|---|---|---|---|---|
| data | bars per tf, as_of, notes | — | missing tf? stale as_of? | — |
| detectors | key levels, volume, trend, candidates | candidate X valid/invalid because… | does the chart agree? | T1.2, T2.9, R2… |
| facts→prompt | what FACTS told the model | — | anything important missing/misleading? | — |
| pass 1 context | higher-tf structure, levels kept | trend, concerns | matches the 1h chart? | T3.5 |
| pass 2 pattern | pattern / breakout read | hypothesis | real pattern? | T3.1–T3.3 |
| pass 3 entry | draft verdict + plan | setup/no_setup, entry/stop/targets | at the level? chased? R:R≥3? | T4.1, T4.2, R2 |
| critic | kill / warn / survive | confidence change | was the kill/keep justified? | T3.3d–g, R3 |
| grounding | checks passed/failed | accepted / retried | false accept / false reject? | — |
| options / setup / proposal | contract, validity, proposal | — | — | T5, R1 |
| outcome | what price did | filled / stop / targets, R, MFE/MAE | — | — |

Then answer, in prose: **where did the first wrong turn happen?** Everything downstream of
the first bad step is usually a consequence, not a cause. Compare against:
- the **outcome** (did the plan work? did the declined candidate work? → `wrong_verdict`,
  `wrong_plan`, `late`…),
- the **expectation**,
- the **book** (cite rule ids; if you need the exact text, `get_rule`-style lookup is
  `references/rulebook-index.md`, and the PDF can be read with the `pdf` skill / `Read`
  with `pages=`).

Cross-check the detectors with `replay-facts <id>`: if the current code produces
different levels/candidates than the run recorded, the detectors have changed since —
say so (it means the fix may already be in, or a regression slipped in).

### 5. Classify and persist
Pick one `review_verdict` and one `root_cause_stage` from `references/failure-taxonomy.md`
(exactly those strings — they are validated). Write the review:

```bash
cd backend && .venv/Scripts/python.exe -m zargar.tools.technique_review review <id> \
  --verdict wrong_verdict --root-cause pass_entry \
  --expected setup --expected-type support_bounce --expected-entry 101.20 --expected-stop 100.80 \
  --expectation "bounce at prior-day LOD with rising volume" \
  --note "Detectors had the level (101.20 ×3) and a valid candidate; pass 3 chose no_setup citing R3.1 but volume was 1.3× baseline (FACTS volume.relative=1.3). Prompt over-weights the critic's chop warning." \
  --action "schemas.SYSTEM_PROMPT: state that R3.1 applies only when FACTS volume.belowFloor is true" \
  --action "grounding: add check no_trade_reason R3.1 requires volume.belowFloor" \
  --reviewer claude
```
Use `--reviewer user` when you are recording the user's judgement verbatim, `claude`
when it is yours. Discuss with the user before writing if the call is contestable.

### 6. Plan the fix
For each action, name the file:function, the exact change, the test that pins it, and
how you will prove it: usually `replay <id> [--set threshold=value]` then `diff <id> <child>`
(same bars, new process version → the change in verdict is attributable). Offer to
implement in a worktree. After a fix lands, re-run the replay, `diff`, and add a second
review (`--verdict correct`, `--note "fixed in <sha>"`) so the run's history shows the
before/after.

Append any durable lesson to `docs/TECHNIQUE-PIPELINE-PLAN.md` → "What was learned".

## Guardrails
- Never edit `technique_runs` / `events` rows; reviews are new rows, runs are replayed
  not rewritten.
- Don't trust the model's rationale as fact — check every number against `facts.json`
  and the chart.
- Outcomes are scored with the same rules as the backtester (`outcome.simulate_plan`):
  bounce fills only if price trades down to the entry within the entry window; stop
  wins when a bar straddles both; 30/40/15 trims; runner to horizon. Say so when an
  outcome looks harsh or generous.
- A `partial` outcome can still change; a `not_filled` candidate is not a loss.
- One review = one run. For a pattern across runs, review 2–3 individually, then
  summarise the common root cause.
