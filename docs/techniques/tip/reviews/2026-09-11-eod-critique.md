
---

# Team response (2026-09-12)

All GO items executed; NO-GOs respected (no grounding bypass, no MK mirroring
enabled, no risk/timing change, no validation claims).

**Scoreboard reconciled from executions+fees (Tips Practice 4611946d):**
DAL: BUY 4 @ 1.56 / SELL 4 @ 1.5274 → gross −$13.04, net −$21.36 (both prior
figures were real on different bases — prose error, not ledger error). Your
−$296 concern resolves: the fill was 1.5274, NOT 0.82. GOOGL: 8.45 → 10.95 ×1
→ +$250 gross / +$247.92 net. T: 4 of 14 @ 0.52 → 0.61 → +$36 gross /
+$27.68 net. Day net = +$254.24 (the sweep was correct). Cumulative Tips
Practice closed net since the 09-08 reset ≈ −$950.55 — one green day inside a
drawdown; "continue evaluating" is the only claim made. Sep 11 was Friday —
date error acknowledged.

**NEW FINDING from the reconciliation:** DAL's exit decision cited
`[mark: opra 1s old bid=0.82]` but the market exit filled at 1.5274 one second
later — a FRESH but ANOMALOUS single print (flash) triggered the premium stop.
Freshness is fixed; single-print SANITY is not: the tick premium path has no
debounce (the underlying quote-stop requires N consecutive polls). Proposed
follow-up for review: require the premium breach to persist 2 consecutive
evaluations (or cross-check vs recent fills/mid) before a market exit. Cost
here was ~$3 gross; the mechanism could cost real exits.

**Alpaca window (official 12:56–13:25 ET):** portfolio-level evidence — 1
order app-wide in the window (FILLED), 0 rejects, 0 plan errors; ledger 0
pending after. The incident's entire cost was declined-evidence inaction.
"Nothing lost" is hereby narrowed to that order/ledger evidence.

**Caption/grounding (your reproduced bug) — FIXED (v0.7.49):** the transcript
no longer replaces the caption; grounding runs against the sectioned union
(caption + image transcript) with a coverage manifest line ("attachment 1 of
N processed"; gateway now sends imageCount). Your regression adopted verbatim
(tests/test_tip_caption_grounding_review.py) + manifest test. Multi-image
processing and per-source quote attribution remain queued follow-ups, per
your design note.

**RKLB root cause — FOUND and FIXED (v0.7.49):** run abd015d4: usage
in=136,737 / out=4,331, stops [tool_use, max_tokens, max_tokens] — the JSON
never finished printing at the 2,000-token output cap and the repair was
starved at the SAME cap. Fix: per-turn cap is now a knob
(techniques.tip.analyst_max_output_tokens, 3000) and a max_tokens stop DOUBLES
the next turn's room (ceiling 8192); a still-truncated failure reports
"truncated at max_tokens", not bare "no JSON". No-verdict stays fail-closed.
The 136k-token input (50 rules + notes) supports your P4 consolidation item.
Whether RKLB would have won remains unknown and unclaimed.

**MK shadow-first build:** deferred until this grounding release is reviewed;
will start with labeled fixtures (fresh execution vs recap vs holding snapshot
vs hypothetical vs trim) and PREDEFINED promotion criteria per your conditions.
Entry study: collection continues; rationale corrected (proposal-time,
proposal-path-only diagnostics; no lotto cohort yet; a week is a checkpoint,
not a promotion deadline).
