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

Code: `backend/zargar/techniques/team2/` (see ARCHITECTURE.md); shared primitives live in `marketstructure/`,
`options/pick.py`, `research/` per `BUILDING-A-TECHNIQUE.md`. Run the technique's tests with
`pytest tests/test_team2_*.py tests/test_marketstructure_extended.py`; sweep with `python -m zargar.tools.team2_sweep`.

## Status

- [x] Research: 30+ posts/threads captured (Nov 2022 → Sep 2026), method codified (v0.1).
- [x] Contract selection, sizing guide, trim ladder — answered from the recap IMAGES (METHOD §7b, Q1–Q3).
- [x] Video transcripts in `notes/video/` (2022 strategy overview, 2023 Trading Camp podcast) — mined
      into METHOD §7b/§7c (hard −20% premium stop, no time gate, first-pullback rule, daily risk).
- [x] Images: 145 fetched via the X syndication endpoint (`tools/fetch_tweet_media.py`), 16 read and
      described in `notes/x/images/INDEX.md` — they answered Q1 (0DTE, ≈$0.50 strike), Q2 (size buckets)
      and Q3 (trims +50/+100%, sell at target). 96 MB — keep local, do not commit without asking.
- [x] PLAN.md drafted (decisions D1–D14, phases P0–P6, engine list §3b, completeness review §3c); TRADING-RULES.md opened.
- [x] D3 decided: 0DTE technique with its own gated RiskGate policy; engine ENRICHED not forked.
- [x] **Second review (2026-09-04):** 8 more images read (INDEX), METHOD T7/T8/X5/X6/V12 added, F9–F11 logged; the read gained break & base, EMA48 and 200-EMA-flush entries, the new-extreme trim cue, the stalled-pullback rule and the cross-plan concurrency cap.
- [x] **Posture pass (2026-09-04):** trim-and-add (X5), the running high/low of day as a re-entry's target (X3b),
      live-premium trims + small-position rule in the runner, adds as real orders on the same contract; 4 new tests.
- [x] **Build v0.1 (2026-09-03):** shared primitives (ext-hours bars, aggregation, EMA, zones, market calendar, VIX + macro placeholder), `zargar/techniques/team2/` (rules → regime → scenario → plan → premium → `session.py` → runner → service), RiskGate 0DTE policy, premium-targeted picker, `/api/team2/*`, `Team2Page`, `tools/team2_sweep.py`; 49 tests green. Alert mode only.
- [ ] Bank bars for ≥ 20 sessions (nightly job runs from the first night on this build), then the first walk-forward sweep → settle D4–D14 in TRADING-RULES.
- [ ] Proposal/auto modes (earned ladder), morning-report line, mobile-audit of the page, `/team2-review` skill, calibration of the other 8 documented trades.
- [ ] Walk-forward sweep on SPY/QQQ/IWM before proposal/auto arming (alert-mode arming is live).

## How the data was captured (so it can be repeated)

- X profile pages and single `x.com/Team2Trading/status/<id>` pages render **without login** in
  the Claude in-app browser (`get_page_text`); WebFetch gets HTTP 402 from X and 403 from
  Thread Reader. The unauthenticated profile timeline shows only the ~5 newest posts.
- Truncated tweets in a thread expand by clicking every "Show more" via `javascript_tool`.
- **Thread Reader App** (`threadreaderapp.com/thread/<id>.html`) serves full unrolls of every
  thread someone once unrolled. Its "More from @Team2Trading" cards carry the ids in
  `div[data-link-href="/thread/<id>.html"]` (not in `<a href>`), so a JS extraction on each
  thread page walks the chain backwards in time. The `/user/…` page itself needs login.
- Search engines index only a fraction; `site:x.com Team2Trading <phrase>` found ~12 ids.
- Scratch extractor used for the bulk pages: `extract_threads.py` (splits a persisted
  `browser_batch` result into note files; header regex accepts @Team2Trading and @cs_tradess).

## Not captured yet (ids known)

See `notes/x/PARTIAL-threads-seen-not-yet-captured.md` and the tail of `SOURCES.md`. The
chain keeps going back through 2024; the 2025–2026 material already states every rule
several times, so older threads are low value except for the bull/bear flags thread.
