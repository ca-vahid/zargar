# Next gaps — the remaining build items (active-dev posture)

*2026-08-29. Everything in `docs/techniques/tip/ARM-PLAN.md` and
`ARM-GAPS-PLAN.md` is built and live. This plan collects what remains, minus
Telegram intake (explicitly deprioritized by the user — do not build it until
asked). Posture: ACTIVE DEV on practice money — limits are deliberately
ambitious (see §0), every source is fully open to the intake, and the goal is
to generate maximum learning signal per week, not to be careful.*

## 0. The practice posture (set live 2026-08-29, journaled)

Strict caps were moved to ambitious practice values so real activity flows
instead of being risk-rejected. The kill switch, the never-list (no share
shorting, no naked writing, reduce-only exits), write-ahead ordering and the
RiskGate path itself are UNCHANGED — this loosens sizes, not safety identity.

| key | was | now |
|---|---|---|
| risk.max_position_notional | 5,000 | **25,000** |
| risk.max_position_pct | 10 | **50** |
| risk.max_gross_exposure_pct | 100 | **300** |
| risk.max_option_premium_pct | 25 | **50** |
| risk.max_option_premium_notional | 2,500 | **10,000** |
| risk.max_option_contracts | 10 | **50** |
| risk.max_orders_per_minute | 10 | **30** |
| risk.daily_loss_halt_pct | 3 | **8** |
| risk.max_option_spread_pct | 10 | **20** |
| techniques.tip.budget_per_tip | 1,000 | **2,500** |
| techniques.tip.budget_open_max | 5,000 | **15,000** |
| techniques.tip.max_open_tips | 5 | **10** |
| technique.max_risk_pct / techniques.tip.max_risk_pct | 5 | **10** |
| execution.daily_loss_fallback | 100 | **500** |

Discord intake: **every monitored source runs `botsOnly=false`** (2026-08-29)
— human posters count everywhere; the per-entry flag stays available on
Tips → Sources. Code DEFAULTS stay conservative on purpose (a fresh install
should be careful; the arm preflight warns about any clash either way).

**Before real money, these come back down** — that decision belongs with the
real-money gate (§4), not to a settings drift.

## 1. A8 — the analyst's rule quality loop

*Rules only accrete (`tip_notes` scope `rule`); nothing merges, expires or
audits them. ANALYST.md §6/§8 — the one open charter item.*

- [x] **A8.1** — a `rule_audit` run kind (weekly, scheduler; knob
  `techniques.tip.rule_audit_enabled` + `rule_audit_day`): reads ALL rules +
  the last N retros/lane grades, and returns a consolidation: merges
  (duplicates → one refined rule), expiries (no longer supported by
  evidence), contradictions (kept, surfaced to the human — never
  self-resolved).
- [x] **A8.2** — rule lifecycle on `tip_notes`: an audit SUPERSEDES a rule by
  writing the refined one and marking the old (`supersededBy`), never
  deleting — the journal stays the history; the "YOUR TRADING RULES" injection
  serves only live rules.
- [x] **A8.3** — contradictions surface on Tips → Analyst → Knowledge with a
  "needs your call" badge; resolving is a human click (keep A / keep B / keep
  both), journaled.
- [x] **A8.4** — every rule must cite evidence (position/run/lane-grade id);
  the audit flags evidence-free rules for expiry first.
- [x] **A8.5** — tests: audit run consolidates a seeded duplicate pair,
  expires an evidence-free rule, keeps + surfaces a contradiction; the run
  injection excludes superseded rules.

## 2. Native multi-leg spread executor (Webull CA)

*Leg-sequencing ships today (long fills first; rollback verified — ARM-GAPS
B3). Webull CA ACCEPTS a native 2-leg order in one impact call (probed live
2026-08-29 via `snaptrade_options_check --probe income`); Wealthsimple stays
1156-unsupported.*

- [x] **M1** — `SnapTradeExecutor.place_mleg()`: one `POST
  …/trading/options` with both legs (padded OCC, string prices, net limit);
  preview via `…/impact` first; venue capability gate per account
  (`options_capability` grows a `mleg` flag).
- [x] **M2** — `lifecycle.open_spread` prefers native mleg when the venue
  supports it, falls back to leg-sequencing otherwise (same adopt shape,
  `spread:<gid>` tags either way); the sim executor gets a native-mleg fill
  path so tests cover both.
- [x] **M3** — RiskGate: evaluate the SPREAD as one unit (net debit/credit vs
  the premium caps; max loss = width−credit for credits) instead of two leg
  checks; the covered-short exception stays for the sequencing fallback.
- [x] **M4** — tests: native fill on sim, fallback on a non-mleg venue,
  risk-gate net-unit sizing, chaos: venue rejects the mleg → sequencing
  fallback engages.

## 3. Flow calibration

*Default flags are UNCALIBRATED on real chains (42/56 symbols flagged, mostly
1-DTE noise — flow UI-PLAN §3a). Now urgent-adjacent: flow-scan tips feed the
analyst (the HOOD at-level arm came from flow).*

- [x] **FL1** — a calibration sweep over the accumulated
  `option_chain_snapshots` (2+ weeks of history by early September): for each
  candidate threshold set, how many symbols flag per day and how do flagged
  contracts do over the next 1–3 sessions (OI confirmation rate, premium
  follow-through)?
- [x] **FL2** — kill the 1-DTE noise: a `min_dte` floor on flag eligibility
  and a premium-weighted (not count-weighted) score.
- [x] **FL3** — pick thresholds where ≤ ~10 symbols/day flag and the
  overnight-OI confirmation rate visibly separates flagged from unflagged;
  write the chosen values + evidence into `docs/techniques/flow/PLAN.md`'s
  judgement log and the settings.
- [x] **FL4** — only then: let flow-scan tips carry a conviction above
  `implied` (today they park/appraise; a calibrated flag could propose).

## 4. The real-money gate (tips + multi-day machinery)

*docs/BUILDING-A-TECHNIQUE.md §2b: real money holds overnight only after an
Alpaca-paper pass + practice soak. The multi-day roll/adopt/partial paths are
new — they soak first. The BUILD half (tooling + the written profile) is done;
the soak itself is a CALENDAR gate that no session can fast-forward.*

- [x] **R1 (build)** — the automated soak report:
  `python -m zargar.tools.soak_report` scores the checklist from the journal
  (≥14d span, ≥10 clean multi-day rolls — a roll past its own horizon flags as
  a BUG, ≥5 adopt-on-fill handoffs incl. ≥1 partial, 0 unexplained critical
  alerts, retros + lane grades accumulating) and says READY / still soaking.
- [x] **R3 (build)** — `docs/PRE-LIVE-PROFILE.md`: the exact discipline
  settings that come back before the first live tip, with the OBJECTIVE
  triggers (soak_report READY + Alpaca-paper pass + a source with
  `barCleared` on expectancyR) and the first-live rules.

**Operational gates — user + calendar owned, deliberately NOT checkboxes a
session can tick:**

- **R2** — the Alpaca-paper overnight pass (needs the Alpaca subscription
  restored; one options position held overnight app-managed, exits fire next
  session per policy).
- **R4** — the first live tip (smallest size, `allow_live_auto` OFF, one
  source, retro-reviewed before the second). Placing real-money trades is the
  user's act, never an agent's.

## 5. Real-device mobile pass

*The Playwright audit is green (0 failing combos, 2026-08-29 — including the
thumb-size link-chip fix it caught).*

- [x] **MB2** — fix what the audit finds; re-run `npm run mobile-audit`
  (done: the tip-row link chips were 33px targets → 44px in mobile.css;
  audit re-run clean).

**Operational gate — needs the user's physical phone:**

- **MB1** — the MOBILE-ACCESS.md real-device checklist over Tailscale (login,
  Now view with day-N chips, tip rows + armed chips, HALT, sell-now, push
  tap-through).

## 6. Webhook intake auth (HMAC)

*Small. The email/webhook ingest endpoints predate the auth layer.*

- [x] **W1** — HMAC signature on `POST /api/ingest/email` (shared secret in
  settings, `X-Zargar-Signature`), reject unsigned when the secret is set;
  the in-app paths keep using the session auth.

## Sequencing

FL (flow calibration) first — it feeds the analyst TODAY and its data ages
well. Then A8 (the rulebook is growing now). M (native mleg) whenever a spread
tip actually appears in practice. R runs on the calendar (soak time), MB is an
evening with the phone, W1 is an hour whenever.

## Implementation notes — A8 / FL / W1 / M (landed 2026-08-29)

- **A8**: `techniques/tip/rule_audit.py` — weekly `rule_audit` run (LLM judges,
  code applies): merges SUPERSEDE (`tip_notes.superseded_by`, never delete),
  evidence-free rules expire first, contradictions FLAG (`needs_human` →
  "needs your call" badge + ✓ resolve on Knowledge; POST /api/tip/notes/{id}/
  resolve). Rides the nightly review on `rule_audit_day` (Sat). Journal
  `TipRuleAudited`. The live injection (`_rules_text`/`tip_notes`) serves only
  live rules.
- **FL**: `tools/flow_calibrate.py` (offline grid sweep over the snapshot
  history, parity spots, baseline OI-confirm comparison) — first run
  2026-08-29 (`flow/notes/2026-08-29-calibration.md`): 0-2 DTE flags were
  ANTI-signal; applied dte_min=3, premium_min 250k, vol_oi_min 2.0,
  premium-WEIGHTED score (`premium_unit`). FL4's conviction upgrade is built
  behind `techniques.flow.calibrated` (false until ≥5 day-pairs re-confirm).
- **W1**: `X-Zargar-Signature` = HMAC-SHA256(secret, raw body) on
  /api/ingest/email when `ZARGAR_INGEST_HMAC_SECRET` is set (env — pre-auth
  boundary); unsigned/mis-signed → 401; the static ingest key stays the
  fallback mode.
- **M**: native multi-leg spreads. `Executor.submit_mleg` (sim: accepts and
  fills per-leg; SnapTrade: ONE /trading/options order with the `legs` array
  the Webull probe verified). `OrderManager.place_spread` — write-ahead both
  rows (oca_group=gid, tag `mleg`), ONE `RiskGate.evaluate_spread` verdict on
  the structure's MAX LOSS (debit, or width−credit), one venue submit; not a
  side-door (same guarantees as `place`, unit-shaped). `open_spread` prefers
  native when `_mleg_supported` (sim/shadow always; SnapTrade accounts listed
  in `options.mleg_accounts` — empty by default, fill it after probing) and
  FALLS BACK to the verified leg-sequencing on any native failure; a
  failed/partial native fill unwinds reduce-only. Tests: native fill e2e,
  one-unit risk rejection, forced venue failure → sequencing fallback.
  LIVE mleg still requires adding the Webull account id to
  `options.mleg_accounts` — deliberate, per-account opt-in.
