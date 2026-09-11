
---

# Team follow-up 2 — v0.7.44 verdict items (same day)

All three failing checks and both reporting corrections implemented; your
`test_v0744_review.py` adopted verbatim and green.

- **1A-P1**: `OptionsService.refresh_now()` forces a real observation
  (track + `_refresh_live`) — the retry no longer re-reads the cache; the
  refreshed quote's source timestamp is recorded on the `freshRetry` stamp.
- **1A-P2**: retry scope is `via == "auto"` AND portfolio kind `sim` only;
  the once-only stamp is now written under a row lock (`with_for_update`).
- **1B tick**: `_watch_once` premium decisions use the same source-age-aware
  `_fresh_net_mark` as the bar path (receipt age is gone) and the evidence
  string lands on the tick exit record too.
- **Entry study**: fields renamed honestly — `signalStatedPremium` (from the
  signal) vs `proposalLimit`, sample is `atDecision` (proposal time, not alert
  time); two durable journal rows (phase created/delayed) so a restart loses
  only the delayed sample, visibly. Coverage caveat (proposal-path only)
  documented in the docstring; this remains diagnostics, not the variant study.
- **Ledger attribution**: exit reasons join by portfolio identity; a same-time
  decision that exists only in another book renders as "reason unmatched
  (cross-book decision excluded)", never borrowed. Regression tests in
  `tests/test_ledger_attribution.py` (cross-book never borrowed; same-book
  attaches).

**Geometry decision (user, 2026-09-10):** validate geometry and sizing BEFORE
entry, with explicit, bounded, journaled post-fill exceptions only for
already-existing positions. Design work queued as its own reviewed change —
not bundled into this fix release.
