# Zargar — where the plan lives

*Rewritten 2026-09-01 (the v0.1/v0.2 walkthrough this file used to hold is in
git history). This is the INDEX: each area's plan-and-findings doc is the
source of truth; this page just says which one and where things stand.*

## Current state, one paragraph

Three techniques run on one engine (registry-driven): **EM Options** (armed
session plans, options-first, R6 windows), **Tips** (Discord intake → analyst
appraisal → per-source shadow books → earned auto), **Flow** (context-only
nightly UOA scan). Practice money soaks daily with auto-approve gated per
source; live venues (SnapTrade: Wealthsimple + Webull CA) are connected but the
live-auto switches stay off until the Phase-6 gates pass. The desk surface is
the 08:25 ET morning report + Dashboard card.

## The active queue

| Plan | What it holds |
|---|---|
| `POST-SOAK-PLAN.md` + `POST-SOAK-BUILD-PLAN.md` | THE active queue (2026-08-31): phases 1–5 built; Phase 6 = the real-money calendar gates with run-books |
| `PRE-LIVE-PROFILE.md` | the settings re-tighten that must precede real money |
| `TECHNIQUE-CANDIDATES.md` | next-technique shortlist (T3 PEAD / T4 momentum / T5 credit spreads — trim decisions open) |
| `techniques/enhanced-market/EVOLUTION-PLAN.md` | EM evolution — **owned by the other team** |

## Per-area source of truth

- **Shared engine judgement:** `PLATFORM-RULES.md` (invariants, findings, knob
  change log — read before touching the runtime).
- **Building a technique:** `BUILDING-A-TECHNIQUE.md` (capabilities + testing bar).
- **Platform architecture:** `ARCHITECTURE.md`; the platform build record is
  `TECHNIQUE-PLATFORM-PLAN.md`.
- **Tips:** `techniques/tip/` — PLAN, BUILD-PLAN, INTAKE-PLAN, ARM-PLAN,
  ARM-GAPS-PLAN, KNOWLEDGE-PLAN(+BUILD), ANALYST.md (charter),
  TRADING-RULES.md (the tips desk's own judgement log).
- **EM (other team):** `techniques/enhanced-market/` — METHOD, TRADING-RULES,
  WALKFORWARD-PLAN, EVOLUTION-PLAN.
- **Flow:** `techniques/flow/` — PLAN, UI-PLAN, calibration notes.
- **Options plumbing:** `OPTIONS-PLAN.md`. **Mobile:** `MOBILE-PLAN.md` +
  `MOBILE-ACCESS.md`. **Sign-in:** `AUTH.md`. **Ops:** `OPERATIONS.md`.
  **IBKR (pending activation):** `IBKR_SETUP.md`.

## Standing decisions that shape everything

- Every order through `RiskGate.evaluate()`; journal every decision; money
  paths write-ahead (CLAUDE.md "Hard rules" is the canonical list).
- Trust is EARNED: sources graduate to auto on their closed record; failure
  paths fail CLOSED (a missing gatekeeper is not permission — 2026-08-31).
- Practice risk values are the AMBITIOUS posture, never the live baseline.
- Team split (2026-08-31): this desk = tips + technique-agnostic platform;
  EM evolution + other-technique enhancement = the other team.
