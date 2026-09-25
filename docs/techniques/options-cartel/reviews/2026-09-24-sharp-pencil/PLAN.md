# Options Cartel: sharp-pencil review and plan, 2026-09-24

Prepared 2026-09-24 evening by the Cartel desk at the user's request: review the plan, the current approach,
how the app uses LLMs and its knowledge base and intake, remove what does not earn its keep, and plan for
maximum opportunity and profit. Evidence is read-only (runtime DB, native Alpaca SIP minutes, code) unless
a line says otherwise. Money here is simulated Practice money; no live book has traded.

The cross-desk plan is `docs/PLAN-2026-09-24-SHARP-PENCIL.md` (EM desk; profit map, LLM/knowledge review,
ops audit). This document is Cartel's part of it, plus review findings from the Cartel desk's own three
read-only studies (Cartel pipeline audit, LLM usage review, knowledge/intake review) that the cross-desk plan
does not already carry.

## 1. Where Cartel stands

| | |
|---|---|
| Executed trades since 09-14 | 1 (APA, -$61.13) |
| Orders 09-21..09-24 | 0 |
| Plan-days observed 09-14..09-22 | 24; 11 touched the trigger; 0 confirmations reached an order |
| 09-24 ($10k book, first day) | 9 arms; NTAP refused at 09:45 (volume 1.26x < 1.5x, first target 0.14R < 0.25R), ran to 203.91 then closed below its trigger; others never touched or were invalidated; 4 names hit an 11:30 feed gap |
| 09-25 | 9 armed at 20:27 ET 09-24 (AI, BBY, CNH, FROG, NOW, NTAP, NTNX, TSLA, VRNS); NVT waits for a contract |

**Diagnosis.** Cartel is not losing money; it is not trading. Every entry gate in the live path is engineering
(1.5x volume, 0.70 close location, 0.5R chase, 0.25R first-target room, 15-minute candle, 120 s signal age);
only the session-extreme stop and the 0.25 minimum delta are sourced from the author. So the question the
desk must answer with evidence is: **which of those engineering gates are costing money, and which are
saving it?** Section 3 is that test.

## 2. Removed tonight: work that never fed an order

Pipeline audit (read-only, origin/main 75bfe357): 13 research modules (3,217 lines) plus ~924 more write 16
research-only run modes; nothing on the arm or order path reads them.

| Item | Cost measured | Action (2026-09-24, journaled) |
|---|---|---|
| Profitability research | 99 s of a 383 s preparation; a 60 s collector 24 h a day; 5 s quote sampler; a context rewrite per candidate update | runtime OFF (settings PATCH 19:54 PT); default OFF in 0.8.50 |
| Intraday research | 60 s task; superseded by the above | runtime OFF; default OFF in 0.8.50 |
| Method lab | 30 s collector, 5 s quotes, a quote row per change for up to 100 selections; its `warm()` built an SSL context per call (engine stall stacks) | runtime OFF (was on; code default already off); records preserved |
| Ignition research | ~3,000 DB transactions per preparation; live `post_ignition` setups never read the table | Practice config `ignitionResearch=false`; default OFF in 0.8.50 |
| Benchmark wait retries | a full discovery + new preparation row every 5 min (127 rows / 43 MB on 09-23) | 0.8.50: spaced 20 min |
| Morning re-preparation | 08:45 redid a complete 20:20 run (12 h window was 25 min too short): ~3,000 listings evaluated twice a day | 0.8.50: 14 h window |
| Per-call HTTP client in session recovery | SSL context per call on every gap repair | 0.8.50: one pooled client per engine |

**Kept:** catch-up (`catchup_runtime` drives real exits), observation health (moves `observeAfter` and entry
verification), sweeps / premium replay (manual tools), the matched cadence control (dormant until 5m).

**Measured incident (lesson):** my first grid replay (1.2 GB, loading every saved analysis) coincided with a
395 s engine stall at 19:45-19:52 PT with 0.6-0.9 GB free; the stall ended seconds after I stopped it. Research
tools now load only screen-passing analyses, and heavy tools stay off the host during market hours.

## 3. Entry-rule replay grid (the "is the entry the problem?" test)

Tool: `backend/zargar/tools/cartel_entry_grid.py` (read-only; no orders, no writes). Declared before running:

- Pools: the latest completed pre-open preparation per session for each Practice book (`0b48ed48` 09-08..09-18,
  `e7b246c9` 09-21..09-23, `297d8b39` 09-24); long candidates that passed the automatic review; frozen at the
  preparation's finish time, cap 100.
- Minutes: native Alpaca SIP 1m (raw), baselines only from sessions before the candidate's cutoff.
- Grid (16): breakout 15m and 5m x volume 1.0 / 1.2 / 1.5 x gap policy none / retest_v1; pivot_30m (Sean's
  30-minute pivot pullback) and undercut_reclaim at 5m and 15m confirmation.
- Outcome: entry at the confirmation close; exit at the first of stop or first target (the open if it gapped
  through) within 5 sessions, else the last close; R of the signal's own risk, net of 2 bp per side.
- Limits: underlying R only (no historical option quotes); retrospective minutes, not receipt-time evidence;
  an exploratory grid on a small sample, not a held-out test; signals within one session are correlated.

RESULTS_PLACEHOLDER

## 4. Cartel plan, ordered by expected effect on profitable trades

| # | Action | Evidence / reason | When |
|---|---|---|---|
| C1 | Apply the grid's verdict only if a variant beats the current rule on BOTH signal count and net R with at least 10 scored trades; otherwise keep the rule and let the prospective record grow | Section 3 | after review of section 3 |
| C2 | `minArmTargetR=0.5` in Practice | NTAP 09-24 refused at 0.14R; 8/24 plan-days under 0.25R: the arm slot is wasted on geometry that can never pass the entry rule | next preparation after C1 is settled |
| C3 | Persist full analyses only for screen passes; store screen-outs as the compact row already in the preparation result | ~3,090 analysis runs (140-310 MB) per preparation; the table is 4.7 GB and append-only (EM P0.5) | reviewed PR |
| C4 | Check benchmark freshness BEFORE discovery | a late benchmark still pays for discovery on every retry | same PR |
| C5 | Refresh the comparison watchlist from Sean's latest dated focus list (Chrome read) instead of the frozen 09-07 code default; keep it comparison-only | the list is a code constant | weekly, docs + setting |
| C6 | Delete the research-only modules after two weeks off (profitability, intraday, method lab and their panels), keeping `candidate_from_analysis` / `make_plan` / `freeze_candidates` that the replay tools reuse | ~4,100 backend lines and 5 panels, none on the order path | 2026-10-08 if nobody asks for them back |
| C7 | Remove the dead `techniques.options_cartel.min_one_contract` setting (read only by `PlanRunner.rt`, which Cartel does not use) | misleading knob | with C3 |
| C8 | P4 (untrusted minutes in a bucket's last 3 minutes) stays a design decision: a declared fixed decision delay vs accepting the loss | non-retroactivity rule | user decision |

**Not recommended:** lowering the volume multiple, spread limit or target-room rule from one day's evidence;
widening stops to raise R; bigger size to make results look better; live money before a positive capped
Practice record (cross-desk P1.5).

## 5. LLM use (all desks) — findings not already in the cross-desk plan

1. **Code defaults drift from the deployed settings.** `settings_service.DEFAULTS` still ships the older costlier
   values (`techniques.tip.prompt_cache` False, `analyst_effort` high, `batch_jobs` False,
   `review_skip_nonactionable` False, EM `preparation_policy` baseline + `paid_review` True, engine
   `extraction_model` claude-opus-5). A settings reset or fresh install restores the $100+/day setup and the
   nightly EM paid review. Owner Tips + EM: move the decided values into DEFAULTS.
2. **No global daily LLM dollar cap.** `review_source_budgets` defaults to `{}` and only skips reviews the gate
   already judged irrelevant; `llm.rates` is `{}`, so usage can show unpriced. Owner platform.
3. **The intake review can close a LIVE position.** `analyst.close_position` -> `position_manager.close`;
   `_manage_guard` checks technique/open/not-shadow/`analyst_manage_enabled` but not the book kind, and the
   module docstring says it "never places orders itself". Owner Tips: exclude live books (or require the live
   acknowledgement) before any live money.
4. **No wall-clock timeout on Tips extraction/transcription** calls, and the SDK's own retries run under the
   app's 3-attempt loops (up to 6 model calls per message). Owner Tips.
5. **EM chat bypasses the EM daily run cap** (`trigger != "chat"`). Owner EM.
6. Cartel makes **no** model calls; its entry, exits and preparation are deterministic.

## 6. Knowledge base and intake — findings not already in the cross-desk plan

1. **Copying the source's own exit is the only measured intake edge** (+$417 over 8 trades, 6 winners) while
   opening-quote stop exits lost -$830; edits that change a level or exit are mirrored but never re-extracted,
   so a corrected exit is lost. Owner Tips: deterministic follow-the-author exit + edit re-extraction.
2. **Cartel's sources are read by hand** (X blocks automated readers; the Chrome extension works while the user
   is logged in). Recommendation: a dated weekly note of Sean's focus list and any stated levels, read through
   the logged-in browser, feeding C5 only; no automated X scraping, no order path.
3. **EM author ingestion receives transcripts, not the charts the levels are drawn on** (6 of 21 source rows on
   09-21 held for exactly that). Owner EM: keyframes or research-only.
4. **Housekeeping:** `tools/discord_watch.py` is superseded by the gateway (no launcher starts it); CLAUDE.md
   says "never user-token Discord automation" while the gateway is a user-token client the user opted into —
   reconcile the text. Owner Tips / user.

## 7. Operating rules for the desk (from tonight)

- Heavy replay/research tools run after the close, only with > 2 GB free, and load the minimum rows.
- Every Cartel switch change goes through the journaled endpoints and is recorded in section 8.
- A day with zero trades is reported as zero trades, with the funnel stage that stopped each plan.

## 8. Activation record

| When | Change | Why |
|---|---|---|
| 2026-09-24 19:54 PT | settings `techniques.options_cartel.{intraday_research,profitability_research,method_lab}` -> false; Practice `ignitionResearch` -> false | order-free load on a memory-starved engine (section 2) |
| 2026-09-24 | PR #283 merged (0.8.50): defaults off, spaced benchmark retries, 14 h prepared window, pooled recovery client, grid tool | section 2 |
