# Team2 technique — research folder

*Started 2026-09-03. Candidate technique #4 for the multi-technique platform
(`docs/TECHNIQUE-PLATFORM-PLAN.md`; build guide `docs/BUILDING-A-TECHNIQUE.md`).
Working id: `team2` (display "Team2"); rename before registering if the user prefers.*

**Desk decision (user, 2026-09-03): this session/group IS the Team2 desk.** Team2 is built completely
separately from EM — its own docs, plan builder, runner, review loop and evolution loop, with the goal of
arming its own plans every night. Shared engine code and generic tools are reused; nothing inside EM's
package is touched for Team2.

## What this is

Casey (@Team2Trading) day-trades SPY / QQQ / IWM options off four daily levels (previous-day
high/low as 15m zones, pre-market high/low as lines), a 13/48/200 EMA regime read on the
2-minute chart, a 15-minute-close confirmation of level breaks, and 2-minute pullback entries
with a one-candle stop. He says the whole method is public on his X feed; the Discord adds
live alerts. This folder holds **everything we captured, verbatim, so it never has to be
fetched again**, plus our codification of it.

## Doc map

| File | What |
|---|---|
| `README.md` | this — status, capture method, next steps |
| `METHOD.md` | the codified rules (L/B/E/C/T/S/X/Z numbering), version drift, open questions, engine-fit notes |
| `SOURCES.md` | index of every captured post: date, id, kind, one-line summary, note file |
| `notes/x/*.md` | one file per X post/thread, text verbatim with frontmatter (url, date, capture method, what images were NOT captured) |
| `notes/x/PARTIAL-…md` | ids seen but not (yet) captured |
| `notes/video/*.md` | auto transcripts of the author's videos (`tools/transcribe_video.py`; audio in `notes/video/media/`, gitignored) |
| `PLAN.md` | the desk plan: charter, decisions D1–D14, engine work list §3b, completeness review §3c, build phases P0–P6, testing bar |
| `TRADING-RULES.md` | the desk's judgement log: rules under observation, findings, theories, change log |
| `tools/` | `extract_threads.py`, `build_sources_index.py`, `transcribe_video.py`, `fetch_tweet_media.py` |
| `notes/x/images/` | 145 tweet images (jpg, local only) + JSON metadata + `INDEX.md` describing the ones read |
| `AUTHOR-STUDY.md` | Codex's independent source study of the author (2026-09-08): explicit / demonstrated / interpretation / unresolved labels per rule |
| `CODEX-REVIEW-SCRATCHPAD.md` | Codex's review charter and baseline notes for its independent Team2 review task |
| `notes/market-watch.md` | the 30-minute market-hours watch log (scheduled task `team2-market-watch`; one section per run, findings mirror into TRADING-RULES) |
| `notes/research/` | dated research notes: author-study evidence, review feedback, the week-37 review + change plan (2026-09-12) with its addendum |
| `notes/research/week37-author-charts/` | the author's annotated charts for the week-37 review (jpg, local only) |

Code: `backend/zargar/techniques/team2/` (see ARCHITECTURE.md); shared primitives live in `marketstructure/`,
`options/pick.py`, `research/` per `BUILDING-A-TECHNIQUE.md`. Run the technique's tests with
`pytest tests/test_team2_*.py tests/test_codex_*.py tests/test_marketstructure_extended.py` (own DB `zargar_test_team2` on :5433;
the `test_codex_*` files are reviewers' regressions adopted verbatim); sweep with `python -m zargar.tools.team2_sweep`
(`--set key=value` overlays = the only way a variant is measured).

## Status (2026-09-13)

**Where the desk stands.** Team2 trades its own Practice book (`Team2 Practice`, $10,000, sim fills on live NBBO) in
`auto` mode since 2026-09-08 (auto on the shared Practice book from 2026-09-04). Plans for SPY/QQQ/IWM are minted at
17:00 ET and armed automatically, completed at 09:25 and finalized on the 09:30 open. Risk limits: $2,000 premium per
trade, 6 % risk, 10 % technique day-loss pause, 15 % book breaker, two losses desk-wide per day, flatten 15:45.
Deploys go only through the scheduler's `ZargarRestart` task after `/api/ops/restart-check` says clear
(PLATFORM-RULES invariant 18). A scheduled watch job reads the desk every 30 minutes in market hours.

**Evaluation cohorts.** Cohort v1 = sessions 1–12 (2026-08-26..09-10): read evidence only — the synthetic strike grid,
the delayed-chain veto, the model veto, stale gap-day targets and the F75 history defects meant the book rarely reached
an order (one filled day, 09-08 QQQ, −$66). **Cohort v2 started 2026-09-11 on v0.7.45+**: listed strikes are the ladder,
live quotes are the only contract authority, one warm-up rule, and the full candidate → quotes → verdict → order →
fill → exit trail is journaled (`TechniquePlanContract`, `TechniquePlanRead`, trail gaps recorded). Twenty sessions of
cohort v2 trigger a REVIEW, never a promotion (PLAN §3d).

**Rules under observation / research (see TRADING-RULES "Rules under observation" and the week-37 plan):**
F81b `target_replan=structure` (gap days) ON since 09-09; C1 no-trade zone = B5 conjunction, C1 room rule and C3
minimum target room are BUILT BEHIND KNOBS AND OFF (v0.7.53) pending C6 (one tape, platform) and a separately approved
Practice experiment; C2 multi-day key levels, C4 add on retest, C5 breakeven after trim are research items without a
frozen definition yet. Near-ITM contract eligibility is an open user decision.

**Built (milestones):**
- 2026-09-03 v0.1: shared primitives (ext-hours bars, aggregation, EMA, zones, market calendar, VIX proxy), the pure
  read `session.py` used live and in replay, runner, service, RiskGate 0DTE policy, premium-targeted picker, API, page,
  sweep CLI. 2026-09-04: second image review (T7/T8/E5/X5/X6/V12), posture pass (adds, HOD target, live-premium
  trims), auto mode, halt scopes, F13–F46 from the first live days.
- 2026-09-08 v0.7.13: engine hosting moved out of the assistant's process tree (watchdog + restart tasks), read
  integrity (fingerprints, session sigma from the chain, open finalized on the 09:30 bar, target breach hook).
- 2026-09-09 v0.7.28–0.7.32: the F75 shared-history repair (bar provenance, calendar gate, sim isolation, quarantine
  + Alpaca backfill, content-hashed datasets, session validation in every consumer, restart readiness door); Codex's
  ten review findings fixed with their regressions adopted verbatim.
- 2026-09-10 v0.7.34–0.7.49: F81 gap-day target re-derivation (+ F81b entry-time fallback), the picker rebuilt on
  listed strikes and fresh quotes (F104/F105/F108), one warm-up rule (F99), EM scorer boundary (F107), the journaled
  trail and trail gaps, the watch job's F88/F91/F100/F101/F106/F110/F111 fixes.
- 2026-09-13 v0.7.53: C1/C3 research knobs (off), ordered no-trade-zone truth table, chronological + book-level
  assessment tooling (scratch), C6 request to the platform owners.

**Open (by choice or pending):** C6 one tape (F119, platform); C1 activation experiment (after C6); C2/C4/C5
definitions; near-ITM policy (user); 5m flag detector (A5) and intraday zones (A11) never built; `/team2-review`
skill not built (the watch job and dated research notes do that work); the sweep still walks a synthetic strike grid
for history (no as-of listings) and scores the model's premium path, not fills.

## How the data was captured (so it can be repeated)

- **Logged out** (in-app browser or curl): single `x.com/Team2Trading/status/<id>` pages render the post text; the
  unauthenticated profile shows only the ~5 newest posts; `cdn.syndication.twimg.com/tweet-result?id=<id>&token=a`
  returns the full text + media URLs as JSON for any id (no login, occasionally rate-limited);
  `pbs.twimg.com/media/<id>.jpg?name=large` serves the image. WebFetch gets 402/403 from X; Thread Reader
  (`threadreaderapp.com/thread/<id>.html`) unrolls threads someone once unrolled and its "More from" cards expose
  earlier ids via `div[data-link-href]`.
- **Logged in** (the user's Chrome through the Claude in Chrome extension; pick the browser with `switch_browser`,
  the user names it, e.g. "i7 Home Laptop"): `x.com/search?q=from%3ATeam2Trading%20since%3AYYYY-MM-DD%20until%3AYYYY-MM-DD&f=live`
  lists every post and reply for a day (dates are UTC-ish, use a two-day window); `read_page filter=interactive`
  exposes the status ids, then fetch each by id as above. Never type credentials; the browser must already be signed in.
- Truncated tweets in a thread expand by clicking every "Show more" via `javascript_tool`. Search engines index only
  a fraction (`site:x.com Team2Trading <phrase>` found ~12 ids). Bulk pages: `extract_threads.py`.
- Images stay local (`*.jpg` gitignored, 2026-09-03 user decision); the JSON metadata and INDEX.md are committed.

## Not captured yet (ids known)

See `notes/x/PARTIAL-threads-seen-not-yet-captured.md` and the tail of `SOURCES.md`. The
chain keeps going back through 2024; the 2025–2026 material already states every rule
several times, so older threads are low value except for the bull/bear flags thread. Week-37 posts
(2026-09-09..09-12) are indexed in `SOURCES.md` with their ids; their text lives in the week-37 review note.
