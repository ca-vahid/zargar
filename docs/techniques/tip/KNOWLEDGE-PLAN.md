# Tips knowledge & historical-experiment plan (research, 2026-08-30)

Goal (user): start processing **historical tips** through the Tips Analyst at random,
review the outcomes to find shortcomings/gaps, and upgrade the **knowledge system**
(organization, tool use, update/removal of outdated knowledge, general-channel intake
like `trading-floor`) so the process runs seamlessly — while keeping the Tips Analyst
**fully separate** from the EM analyst.

This file = the research findings + design options + recommended experiment protocol.
Nothing here is built yet; each cluster ends with a decision the user makes before /goal.

---

## §0 Separation audit — DONE, already clean (verified 2026-08-30)

The user's hard requirement holds today:

| | Tips Analyst | EM "analyst" |
|---|---|---|
| What it is | trader persona, tool loop (`techniques/tip/analyst.py`) | 4-pass model chart read (`technique/service.py` + `vision.py`) |
| Knowledge store | `tip_notes` DB table (scopes rule/general/ticker:/source:/signal:) | prompts + settings + `docs/techniques/enhanced-market/TRADING-RULES.md` |
| Rulebook | `tip_notes` scope `rule` (retros + weekly audit maintain it) | EM METHOD book/rulebook versions in run config |
| Cross-reads | **none** — no file in `zargar/technique/` touches `tip_notes` | **none** — prompt says "NOT bound by any other technique's method" |

Shared surfaces are infrastructure only (LLM client, market data, flow context notes —
flow is context-only by design). **Guardrails to add** (cheap, cluster E):
- an invariant line in `docs/PLATFORM-RULES.md`;
- a test asserting `zargar/technique/` has no `tip_notes` import and vice versa.

## §1 What exists today (internal audit)

**Data** (runtime DB, 2026-08-30):
- `discord_messages` mirror: **227 messages**, 9 tip channels (OWLS Capital 🌟 rooms),
  ~25 each (the default `--backfill 25` baseline), oldest 2026-07-23. **No general
  channels** (`trading-floor` is not watched, not in the mirror).
- `signals`: ~26 total (test-era volume). `tip_notes`: 19 (3 rules, ticker/source scopes).
- `raw_content`: 21 manual + 3 flow.

**Capabilities already built:**
- Gateway history **backfill**: `_backfill_channel(days)` paginates a channel back N days
  (per-watch `onboardDays`, capped **17 days**; default baseline 25 recent messages).
- **Stale-tip replay** (`techniques/tip/replay.py`): a tip older than
  `techniques.tip.max_tip_age_hours` never trades — both books' counterfactuals run on
  1h bars (~2 years back). This is the outcome engine for historical tips.
- Analyst runs persist full play-by-plays (`TipAnalystRun`), retros + weekly rule audit
  already curate the rulebook; the Knowledge tab (2026-08-30) has edit/delete/supersede/
  needs-your-call UI.
- `search_messages` analyst tool reads the mirror (source history cross-referencing).

**Gaps for the experiment:**
1. Only "process the channel's **last** message" exists — no "process mirrored message X",
   no batch/random sampler.
2. The analyst's tools (quotes, chains, positions) serve **live** data — appraising an old
   tip mixes tip-time thesis with today's market.
3. The 17-day `onboardDays` cap bounds how far history can be mirrored.
4. No "context-only" channel role — adding `trading-floor` to the watch today would push
   every chat message through tip extraction (noise, cost, garbage signals).
5. Notes have supersede/delete but **no expiry/validity window** — a "today's chatter"
   note would sit in every future run forever.

## §2 External research (deep-research run, 22 sources, 14 claims verified 3-0/2-1)

The patterns that matter for us, with sources:

1. **Supersede by temporal invalidation, never delete** — Zep/Graphiti stamps every fact
   with validity windows (`t_valid`/`t_invalid` + created/expired) and an LLM compares
   new facts against related existing ones, closing the old fact's validity instead of
   overwriting ([Zep paper](https://arxiv.org/pdf/2501.13956), 3-0). Our `superseded_by`
   is the right instinct; what's missing is the **validity window** and serving facts
   *with* their dates so the model sees temporal validity explicitly (also 3-0).
2. **Layered retention by knowledge type** — FinMem gives an LLM trading agent 3 memory
   layers with decay constants ~14d (daily news) / ~90d (quarterly insights) / ~365d
   (durable reflections), and retrieval scores recency·relevance·importance
   ([FinMem](https://arxiv.org/abs/2311.13743), 3-0). Maps exactly onto: daily digests
   (short TTL) < ticker/source notes (medium) < rules (long, audit-gated).
3. **Cutting off future data at test time** is the core replay hygiene (FinMem regime
   switch, 3-0). Additionally (unverified — verifier agents hit a usage cap, treat as
   caution not fact): "parametric look-ahead" — the model's own weights know how 2024-25
   stocks moved — inflates historical LLM backtests, and small window extensions flipped
   FinMem's results. **Consequence:** grade the *process*, not the P&L, and prefer
   history from after the model's knowledge cutoff (≥ Feb 2026) when P&L-ish replay
   numbers are quoted at all.
4. **Financial agents specifically need recency-weighted memory** and the field's lineage
   (FinMem → TradingGPT → FinCon) all keep **per-role scoped memories** with selective,
   not broadcast, knowledge updates ([survey](https://arxiv.org/pdf/2602.05665), 3-0).
   Shared-state contamination numbers (57-71% cross-task misuse; 36.9% of multi-agent
   failures from inconsistent shared state — unverified) all point the same way: the
   user's separation requirement is the published best practice.
5. Practitioner Discord summarizers (SimplySummary, discord-summarizer) do scheduled
   digests with ticker extraction — our "daily digest into knowledge" idea is a known,
   workable pattern.

## §3 Design options

### Cluster A — historical-tip experiment harness (the test itself)

- **A1 (recommended): mirror-driven batch runner.** Raise/waive the `onboardDays` cap
  (per-channel opt-in, e.g. 60-120 days), backfill the 9 tip channels, then a new CLI
  `tools/tip_experiment.py`:
  `--sample 20 --seed 7 --channels ... --since 2026-02-01` → picks random mirrored
  messages, runs each through the REAL intake (extraction → verification), passing the
  mirror's `posted_at` as `stated_at` so the **stale path fires naturally**: books
  untouched, `replay.py` computes both books' counterfactuals, the analyst appraises
  with a `historical: true` flag in its context ("this tip is from <date>; today's
  quotes are NOT its market — reason from the tip's time"). Every run tagged
  `experiment:<batch-id>` for review.
- **A2: as-of tool shim.** Replace the analyst's live tools with as-of versions
  (bars-only quotes, no live chain) during historical runs. Cleanest science, most work,
  and chains can't be reconstructed historically anyway (no stored chain history except
  flow snapshots) — defer; A1's explicit flag + process-grading covers the experiment's
  actual goal (finding pipeline/knowledge gaps, not measuring alpha).
- **A3: review loop.** After each batch: one **batch review run** (analyst `retro` kind
  over the batch) + a human pass in the UI. Grading rubric per run: extraction fidelity /
  verification correctness / knowledge retrieved (was the right note injected?) /
  tool use sanity / verdict reasonableness at tip time / what knowledge SHOULD have
  existed. Findings land in `docs/techniques/tip/TRADING-RULES.md`-style log +
  concrete fixes.

### Cluster B — knowledge organization & lifecycle

- **B1 (recommended, small): validity windows on notes.** Add `valid_until` (nullable)
  + per-scope default TTLs (FinMem-style): `daily:*` 14d, `ticker:*`/`source:*` 90d
  (refreshable on touch), `rule`/`general` no expiry (audit-gated instead). Expired
  notes stop being injected (kept as history like superseded ones); a nightly sweep
  expires them; the Knowledge tab shows "expires in Xd" and lets the user pin
  (clear `valid_until`).
- **B2: serve dates with facts.** When injecting notes into a run, prefix each with its
  date + scope (Zep's confirmed trick) so the model can discount old context itself.
  Trivial, do with B1.
- **B3 (defer): temporal knowledge graph** (entities/edges à la Graphiti). Overkill at
  19-notes scale; revisit if the store passes ~500 notes and retrieval (not curation)
  becomes the bottleneck.
- **B4: extend the weekly audit** beyond `rule` scope: stale-note candidates (old,
  never-injected-into-a-take, contradicted) get flagged needs-your-call the same way.

### Cluster C — general/context channels (`trading-floor`)

- **C1 (recommended): watch-entry `mode: "context"`.** New field on watch entries:
  `tips` (today's behavior) vs `context` (mirror only — searchable by the analyst,
  NEVER auto-extraction). Sources UI gets the toggle. `trading-floor` becomes the first
  context channel.
- **C2: nightly digest run.** A scheduled analyst run (`kind: "digest"`) reads the day's
  mirrored context-channel messages and writes ONE note per channel-day, scope
  `daily:YYYY-MM-DD` (TTL 14d per B1): tickers discussed, sentiment, recurring themes,
  and — critically — **promotes durable nuggets** into `ticker:`/`source:` scopes with
  provenance. The Knowledge tab's General view grows a "Today" section (daily notes,
  newest first).
- **C3 (cheaper start): digest-on-demand.** A "digest now" button per context channel
  before committing to the scheduler. Good phase-1 stepping stone; C2 follows once the
  digest prompt is tuned.

### Cluster D — experiment protocol (the actual test, once A+C1 exist)

1. Backfill: 9 tip channels × 60-90 days (`onboardDays` opt-in), + `trading-floor` as
   context (baseline backfill only).
2. Batch 1: `tip_experiment --sample 20 --seed 7 --since 2026-02-01` (post-cutoff months
   preferred per §2.3). Review with the rubric; log findings; fix the top issues.
3. Batch 2 (n=20, new seed) after fixes — measure whether the same failure classes recur.
4. Then decide: turn on C2 nightly digests, tune knowledge injection, repeat monthly.

### Cluster E — separation hardening (cheap, do with A)

- PLATFORM-RULES invariant: *"technique knowledge stores are per-technique; `tip_notes`
  is the tips desk's only; EM's rulebook is EM's only; no cross-injection, ever."*
- Test: import/reference check both directions (fails the suite on a cross-read).
- The experiment tag (`experiment:<batch>`) keeps experimental runs/notes out of the
  real retro/audit inputs unless explicitly included.

## §4 Decisions for the user

1. **Backfill depth** for tip channels: 60 days? 90? (deeper = more sample, more replay
   on coarser evidence; 1h bars reach ~2 years so outcomes stay computable).
2. **Sample size** per batch (suggest 20 — reviewable in one sitting).
3. **`trading-floor`**: context-mode mirror from day 1 (C1), digest on demand (C3) first
   or straight to nightly (C2)?
4. **TTL defaults** (B1): 14/90/∞ as proposed, or different numbers?
5. Anything from the batches that should feed the SOURCE scorecards, or keep the
   experiment fully out-of-band (recommended: out-of-band, `experiment:` tagged)?

## Sources (external)

- Zep/Graphiti temporal KG: https://arxiv.org/pdf/2501.13956 (bi-temporal invalidation,
  3-tier episodic/semantic graph, retrieval + dates-in-prompt; LongMemEval +15-18%)
- FinMem layered memory/decay: https://arxiv.org/abs/2311.13743
- Agent-memory survey (finance section, decay/contradiction patterns):
  https://arxiv.org/pdf/2602.05665
- Cautions (unverified — verifier capacity, not refuted): parametric look-ahead in LLM
  backtests https://arxiv.org/html/2605.24564v1; FinMem/FinAgent alpha fragility
  https://arxiv.org/html/2505.07078v3; shared-state contamination
  https://arxiv.org/pdf/2508.08997, https://www.oreilly.com/radar/why-multi-agent-systems-need-memory-engineering/
- Discord digest practitioners: https://github.com/KenDingel/SimplySummary,
  https://github.com/M3-org/discord-summarizer
