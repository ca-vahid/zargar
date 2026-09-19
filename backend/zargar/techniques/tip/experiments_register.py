"""TMR-05 (2026-09-16): the Tips desk's EXPERIMENT REGISTER - one durable identity per
research experiment, carried by every report the experiment produces.

Why a register: a report that shows numbers without saying WHICH hypothesis, WHICH
variant definition, WHICH eligible setup, WHAT the unit of observation is, WHICH policy
and build regime produced the data and WHEN the prospective evaluation window closes,
cannot support a decision - and a small sample dressed as proof is worse than none.
Every entry here is documentation; nothing allocates, promotes or trades on it. The
human-readable mirror is `docs/techniques/tip/research/EXPERIMENT-REGISTER.md` (a test
keeps the two lists of ids equal).
"""
from __future__ import annotations

REGISTER_VERSION = "experiments-v1"

EXPERIMENTS: dict[str, dict] = {
    "entry-timing-cohort": {
        "hypothesis": "Entering a tip at the alert-time qualified quote versus the same idea a fixed delay later "
                      "(or only when the ask stays within a cap of the source-stated premium) changes net outcomes by setup.",
        "variants": ["immediate (decision-time qualified quote)", "delayed (techniques.tip.entry_cohort_delay_minutes, 3.0 min)",
                     "capped (ask <= techniques.tip.entry_cohort_premium_cap 1.05 x source premium)"],
        "eligibleSetup": "every eligible open/add idea on watched sources (skips, declines, blocked cards, shadows, parks, failures included)",
        "unit": "one idea at one decision (a repeated alert/quote for the same idea is NOT a new observation)",
        "episodeIdentity": "tip_entry_cohort.id (signal id + content id + decision kind)",
        "primaryMetric": "net $ and R per variant book on qualified quotes; insufficient counted, never filled",
        "costs": "options fee per contract per side (+ regulatory), shares commission per order; fills at the ask, exits at the bid",
        "regime": {"module": "techniques/tip/cohort.py", "knobs": ["techniques.tip.entry_cohort_enabled", "entry_cohort_delay_minutes",
                                                                    "entry_cohort_premium_cap", "entry_cohort_quote_max_age_seconds",
                                                                    "entry_cohort_delay_tolerance_seconds"],
                   "policyVersions": ["qualify_quote KF83-04", "evidence_ok (legacy re-judged at sampledAt)"]},
        "alternativesTried": ["none promoted; a delayed-NBBO diagnostic (TipEntryStudy) preceded it"],
        "evaluationWindow": {"opened": "2026-09-15", "closes": "after >= 30 adequate pairs per setup or 2026-10-15, whichever first",
                             "decisionRule": "no rule change without a cost-aware validated cohort; reviewer decides"},
        "status": "collecting",
    },
    "overnight-hold": {
        "hypothesis": "Carrying a Tips position overnight versus a predeclared pre-close liquidation of the sampled size "
                      "differs in net outcome by setup (shares / option DTE bucket).",
        "variants": ["carry (quote drift to the next session's first qualified bid inside 09:30-09:45 ET; managed outcome shown apart)",
                     "intraday_exit (sell the sampled size at the pre-close qualified bid in the last 15 min before the exchange close)"],
        "eligibleSetup": "open Tips positions at the pre-close window + positions that exited intraday that session",
        "unit": "one position-session observation (a position held several nights is counted once per session)",
        "episodeIdentity": "tip_hold_snapshots.observation_key = study version | session | position | leg | arm",
        "primaryMetric": "paired net $ and R (risk rebased to the sampled size) PER BOOK KIND x setup (never pooled as performance; "
                         "HOLD-SCOPE-01), managedCarry separate from carryToNextOpen; quarantined / attention / unknown-scope "
                         "inventory is diagnostic only, never adequate (HOLD-SCOPE-02)",
        "costs": "allocated entry fee + exit cost (options per contract per side + regulatory; shares per order per side)",
        "regime": {"module": "techniques/tip/holdstudy.py", "studyVersion": "holdstudy-v2",
                   "knobs": ["techniques.tip.hold_study_enabled", "hold_snapshot_before_close_minutes", "hold_preclose_window_minutes",
                             "hold_next_open_window_minutes", "hold_next_open_attempts"]},
        "alternativesTried": ["v1 (2026-09-15) rejected: no windows, job-start clock, one fee side, first leg only - its rows stay outside_window"],
        "evaluationWindow": {"opened": "2026-09-16 (first protocol-correct capture 15:50 ET)",
                             "closes": "after >= 20 adequate pairs per setup or 2026-10-16, whichever first",
                             "decisionRule": "no holding-policy change from this study alone; reviewer decides"},
        "status": "collecting",
    },
    "frozen-context": {
        "hypothesis": "A compact analyst context (core rules + relevant notes + newest history lines) reaches the same decisions "
                      "as the full context on identical frozen evidence at lower cost.",
        "variants": ["current (the CAPTURED request verbatim - the full-route CONTROL only when the run was on the full route; "
                     "on a compact-route capture it is the compact treatment, flagged isFullControl=False)",
                     "core_only", "no_knowledge", "compact (generic PROF-05 trim - not the production candidate)",
                     "recap_candidate (the production recap route: recap.CANDIDATE recap-candidate-v1, same builder as production; "
                     "exact parity by request hash on a compact capture, treatment-only on a full capture)"],
        "eligibleSetup": "analyst runs captured with frozen_capture_context on (exact manifest) AND, for the recap question, a captured "
                         "classifier read (recapRead) - bundles without it are non-parity / coverage-limited; replays on the identical bundle",
        "unit": "one bundle x one variant replay (a pair is complete only when every requested tool input was served AND the two "
                "treatments were assembled from the same frozen inputs - frozen.assemble_treatments proves it offline first)",
        "episodeIdentity": "bundle id + variant + report hash",
        "primaryMetric": "verdict / contract / protections equality; input, output and cached tokens; calls; latency; coverageLimited",
        "costs": "paid model calls per replay (recorded in the report usage)",
        "regime": {"module": "techniques/tip/frozen.py", "bundleVersion": 1, "knobs": ["techniques.tip.frozen_capture_context", "frozen_variants"]},
        "alternativesTried": ["one NVDA pair (fb-16d3146639a86744): coverage-limited, mixed reading - not adopted",
                              "2026-09-16 SPX-map / APLD-digest bundles: HELD - unpaid assembly shows no captured classifier read, "
                              "so the recap_candidate inputs are unavailable (non-parity); no paid pair run"],
        "evaluationWindow": {"opened": "2026-09-15", "closes": "after >= 10 complete-evidence pairs",
                             "decisionRule": "compact is not adopted from coverage-limited pairs; reviewer decides on complete pairs"},
        "status": "collecting",
    },
    "mk-ownbook-observe": {
        "hypothesis": "Mirroring a source's own-book trades (MK-alpha-trades) would add a positive net edge; first, observe only.",
        "variants": ["observe (record, no book)", "shadow (not enabled)", "mirror (not enabled)"],
        "eligibleSetup": "own-book narration from techniques.tip.mk_ownbook_sources",
        "unit": "one narrated trade",
        "episodeIdentity": "signal id",
        "primaryMetric": "n/a until shadow: observation counts and narration quality only",
        "costs": "n/a (no fills)",
        "regime": {"module": "techniques/tip/mk_ownbook (KFIN-08)", "knobs": ["techniques.tip.mk_ownbook_mode", "mk_ownbook_sources"]},
        "alternativesTried": [],
        "evaluationWindow": {"opened": "2026-09-15", "closes": "user decision; predefined promotion criteria required before shadow",
                             "decisionRule": "narration is research, never permission (PLATFORM-RULES 19)"},
        "status": "observing",
    },
    "prompt-cache": {
        "hypothesis": "Caching the identical stable prefix (system prompt + schema + tool definitions) reduces repeated-input cost "
                      "and latency without changing any judgment; the dynamic header (quotes, positions, evidence) stays uncached.",
        "variants": ["off (live)", "on (techniques.tip.prompt_cache True) - not enabled"],
        "eligibleSetup": "every analyst-family loop call",
        "unit": "one provider call",
        "episodeIdentity": "run id + call index",
        "primaryMetric": "usage.cacheRead / cacheWrite per call, priced cost from llm.rates incl. the warm-up write, latency; judgments unchanged",
        "costs": "the calls themselves; a cache write is billed above the input rate - measured, never assumed",
        "regime": {"module": "techniques/tip/analyst.py cacheable_request + tools/tip_llm_cost.py",
                   "knobs": ["techniques.tip.prompt_cache", "llm.rates"]},
        "alternativesTried": [],
        "evaluationWindow": {"opened": "2026-09-17 (plan research/2026-09-17-prompt-cache-pilot-plan.md; pilot awaiting approval)",
                             "closes": "step 1: the bounded side-effect-free pilot (8 frozen-replay calls, cap $8); step 2 (a measured session) only if favourable and approved",
                             "decisionRule": "user decides on measured hits, priced cost incl. warm-up and latency; recap routing stays OFF (separate experiment)"},
        "status": "built, off",
    },
    "review-gate": {
        "hypothesis": "An intake review can only manage an item the desk holds, arms or proposes; skipping reviews of messages "
                      "that reach none (and are not entry-shaped) removes ~1/3 of review spend without losing a management action.",
        "variants": ["observe (live: decision journaled, review still runs)", "enforce (skip) - not enabled"],
        "eligibleSetup": "every intake message that reaches the review path (a discarded signal, or a no-ticker follow-up)",
        "unit": "one intake message",
        "episodeIdentity": "intake run id",
        "primaryMetric": "false negatives = skip-decisions whose review called update_exit_plan / close_position / disarm_plan "
                         "(must be 0); secondary: skipped share and priced review cost (llm.rates, estimate)",
        "costs": "none in observe (the review still runs); enforce removes the skipped reviews' cost",
        "regime": {"module": "techniques/tip/review_gate.py + signals/service._review_gate + tools/tip_review_gate_eval.py",
                   "knobs": ["techniques.tip.review_gate"]},
        "alternativesTried": ["source-level open-items check (existing D1 gate): shadow signals never expire, so nearly every "
                              "active source always passed it - no reduction"],
        "evaluationWindow": {"opened": "2026-09-19 (retrospective 2026-09-09..18: 186/556 reviews skipped, $121.83, 0 false negatives)",
                             "closes": "5 observe sessions (2026-09-21..25) - tip_review_gate_eval --prospective",
                             "decisionRule": "a REVIEW checkpoint, never an automatic switch: 0 management false negatives "
                                             "(prospective AND retrospective) are necessary, and a human reads the skipped "
                                             "corrections / new entries / mixed messages / deferred actions; sessions are counted "
                                             "after the actual deployment; the user approves any switch (ECON-03 fixed 2026-09-19: "
                                             "absent or unrestored desk components always review)"},
        "status": "built, observe",
    },
    "feasibility-annotate": {
        "hypothesis": "Annotating every TAKE with the expression's feasibility and payoff (without downgrading) reduces "
                      "unfittable option purchases over time; downgrade mode is NOT enabled.",
        "variants": ["annotate (live)", "downgrade (not enabled)"],
        "eligibleSetup": "every analyst TAKE on a live (non-experiment) run",
        "unit": "one analyst run",
        "episodeIdentity": "analyst run id",
        "primaryMetric": "share of takes that fit >= 1 unit; unit risk vs budget; later: realised outcomes by feasibility verdict",
        "costs": "as booked (execcost diagnostic on the record from 2026-09-16)",
        "regime": {"module": "techniques/tip/feasibility.py + payoff.py + execcost.py",
                   "versions": ["feasibility-v1", "payoff-v1", "execcost-v1"], "knobs": ["techniques.tip.analyst_feasibility_gate"]},
        "alternativesTried": [],
        "evaluationWindow": {"opened": "2026-09-15", "closes": "reviewer decision", "decisionRule": "downgrade only on reviewer verdict"},
        "status": "collecting",
    },
}


def identity(experiment_id: str, *, build: str | None = None, extra: dict | None = None) -> dict:
    """The identity block a report carries: which experiment, which regime, which
    evaluation window - and the build that produced the report when known."""
    e = EXPERIMENTS.get(experiment_id)
    if e is None:
        return {"registerVersion": REGISTER_VERSION, "experimentId": experiment_id, "registered": False}
    return {"registerVersion": REGISTER_VERSION, "experimentId": experiment_id, "registered": True,
            "hypothesis": e["hypothesis"], "variants": list(e["variants"]), "unit": e["unit"],
            "episodeIdentity": e["episodeIdentity"], "primaryMetric": e["primaryMetric"], "costs": e["costs"],
            "regime": {**e["regime"], **({"build": build} if build else {})},
            "evaluationWindow": dict(e["evaluationWindow"]), "status": e["status"],
            "caveat": "repeated alerts/quotes are not independent observations; partial realisations and fees count once; "
                      "event sessions and incomplete evidence stay visible; no sample count is called proof",
            **(extra or {})}
