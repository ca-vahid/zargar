// The app's version + curated changelog. ONE source of truth for the UI:
// the TopBar chip, the What's-New dialog and the More sheet all read this.
// Keep entries CONCISE and user-facing (what changed for the trader, not the
// commit log); every release bumps APP_VERSION here AND in package.json,
// backend/zargar/__init__.py and backend/pyproject.toml.

export const APP_VERSION = "0.8.48";

export type ChangeTag = "major" | "new" | "improved" | "fixed" | "security";

export interface ChangeItem { tag: ChangeTag; text: string }
export interface Release {
  version: string;
  date: string;        // YYYY-MM-DD
  title: string;
  items: ChangeItem[];
}

export const CHANGELOG: Release[] = [
  {version:"0.8.48",date:"2026-09-24",title:"Tips: stops never fire after hours; notes filed where they belong; lighter intake",items:[
    {tag:"fixed",text:"A position quote-stop no longer fires on an after-hours print; the venue stop remains the protection outside the session. On 09-24 an after-hours print sold JELD for the next open and released its stop."},
    {tag:"fixed",text:"A knowledge note the analyst files under a named source or ticker is kept there instead of landing in general notes."},
    {tag:"improved",text:"Discord images are downloaded through one shared connection and written off the main loop, and the extraction instructions are cached between reads."},
  ]},
  {version:"0.8.47",date:"2026-09-24",title:"Option picks survive the opening-minute rush",items:[
    {tag:"fixed",text:"At the open the free options-chain provider rate-limits bursts, and on September 24 four EM short entries were dropped after about two seconds of retries. Two books firing the same symbol now share one request, a live entry retries for about four seconds, and background chain requests pause from 9:29 to 9:34 ET (a setting) so entries get the provider first. Held positions and your own reads are never held back."},
    {tag:"fixed",text:"A share entry is sized against the same price the risk check uses (the higher of the limit and the live mid), so an order is no longer refused for landing a fraction over the position cap after a fast bar."},
  ]},
  {version:"0.8.46",date:"2026-09-24",title:"Tips: a short-dated option is handled as a lotto even when the tip gave no expiry",items:[
    {tag:"fixed",text:"When the analyst picks a contract that expires within the lotto window, the position is held into expiry day and flattened at the lotto time. Before, a tip without a stated expiry was treated as an ordinary option, and the day-before-expiry rule sold a 1-day call nine minutes after it filled (fees larger than the gain)."},
  ]},
  {version:"0.8.44",date:"2026-09-24",title:"Tips: option contracts are always valid option symbols",items:[
    {tag:"fixed",text:"An option contract written in a short form (for example INTC260925C130) is converted to the standard option symbol before a card is priced; a string that is not a contract is never used. The first such card waited for a human with no risk estimate."},
  ]},
  {version:"0.8.43",date:"2026-09-23",title:"Tips: intake reads tips with Claude Opus 5.5 and catches position updates",items:[
    {tag:"improved",text:"Intake extraction now names position updates explicitly (trims, stop-outs, closes, 'TP hit') and resolves 'friday calls' and LEAPS, so follow-ups on positions the desk mirrors are no longer dropped. Measured on 40 real messages before the switch: Claude Opus 5.5 at medium effort with this rule changed no actionable signal and costs about 18% less than Opus 5."},
    {tag:"improved",text:"The Tips analyst runs Claude Opus 5.5 at medium effort (Anthropic's recommended starting point) with room for its thinking in every reply."},
  ]},
  {version:"0.8.42",date:"2026-09-23",title:"Tips: cards that need you now alert you, and restarts keep overnight orders",items:[
    {tag:"new",text:"A Tips card that is still waiting for a human 20 seconds after it appears sends one push and Telegram line: what, from whom, why it waits, the share alternative and when it expires."},
    {tag:"improved",text:"When a source says they are out of a trade the desk mirrors, the review now closes our copy instead of only tightening the stop. In Practice, a take whose option cannot be sized within the risk budget can become the equal-risk share position at the same stop (a switch)."},
    {tag:"fixed",text:"A market order placed after hours is no longer cancelled as lost by an overnight restart: it waits for the open like it was meant to, and every restart cancellation now records its reason. The deploy restore check waits for a large restore to finish before calling it a mismatch."},
    {tag:"improved",text:"Reviews can share one cached copy of the desk's rulebook (a switch), so consecutive reviews read it instead of each paying to write it again."},
  ]},
  {version:"0.8.41",date:"2026-09-23",title:"Tips: two fixes found in today's review",items:[
    {tag:"fixed",text:"A tip parked on a cold quote is no longer turned into an approval card while its analyst appraisal is still running; the card now always carries the analyst's opinion and the tip's own contract."},
    {tag:"fixed",text:"When the analyst changes only part of an open position's exit plan (for example the stop), the rest of the plan (profit targets, premium stop) is kept instead of being cleared."},
  ]},
  {version:"0.8.40",date:"2026-09-23",title:"EM: plan outcomes are scored again",items:[
    {tag:"fixed",text:"EM stopped scoring what price did after each plan from September 21: the nightly plans for the next session filled the scorer's queue before they could be scored, so finished sessions never got their turn. Finished sessions are now scored oldest first and future ones wait, so Validation outcomes and the review loop are complete again."},
    {tag:"improved",text:"EM scorecard: a new preregistered test compares breakout trades with level bounces and rejects (30 breakout trades decide it); the rules-vs-model comparison is closed now that EM prepares by rules only."},
  ]},
  {version:"0.8.39",date:"2026-09-23",title:"Tips: lower model cost (caching, Opus 5.5, fewer needless reviews, batch jobs)",items:[
    {tag:"improved",text:"Tips reviews reuse their cached conversation (about half the cost of a multi-turn review) and can run on Claude Opus 5.5 at the same thinking depth. Replies are replayed exactly as received when a reply has to be repaired."},
    {tag:"new",text:"A message that touches nothing the desk holds, waits on or proposes, and that extraction marked non-actionable, can skip the analyst review (a switch, recorded on every decision). Messages about positions, plans or possible entries are always reviewed."},
    {tag:"new",text:"The cost of every intake extraction and image transcription is now recorded per call, so the Tips cost report covers intake too. Nightly digests and knowledge audits can go through the batch API at half price."},
    {tag:"new",text:"Separate model and depth settings for intake extraction, and a notes-only review trim that keeps every rule in full; both are chosen from a side-by-side test on real messages. No trading policy, risk limit, stop or approval control changed."},
  ]},
  {version:"0.8.38",date:"2026-09-23",title:"Hourly and daily history come from the paid Alpaca feed",items:[
    {tag:"fixed",text:"Hourly and daily price history for US stocks now comes from Alpaca instead of Yahoo, whose daily history silently skipped the September 22 session. Hours still start at the open (9:30, 10:30 ...), as every technique reads them, and daily bars carry the official open, close and volume; compared with Yahoo they match to within a few hundredths of a percent. Yahoo remains the fallback and the source for non-US listings."},
  ]},
  {version:"0.8.37",date:"2026-09-23",title:"EM runs without a model: the baseline book prepares by rules",items:[
    {tag:"major",text:"EM can now prepare its main Practice book from the graded sheet by rules alone, with no model calls, exactly as the experimental book already does. It switches on with the EM preparation policy set to deterministic; the paid nightly model review (about $1,100 of EM's $1,109 model spend since August) then stands down. Entry decisions were already rule-based; chat and manual Analyse runs still use the model only when you start them."},
  ]},
  {version:"0.8.36",date:"2026-09-22",title:"EM: the analyst-check panel tells the truth about a scheduled batch",items:[
    {tag:"fixed",text:"The EM Validation analyst-check panel counted only the reads a scheduled evening batch had already started, so a 113-row batch read 19/20 with about 4 minutes left for hours and never closed. It now counts the whole sheet, shows how many rows are not yet started with an honest time estimate, and closes on its own when the batch finishes or stops (saying how many rows were never read). Dismissing it never stops the batch."},
  ]},
  {version:"0.8.35",date:"2026-09-23",title:"EM: a stop rule for the method, a daily scorecard, and BRK.B on the live stream",items:[
    {tag:"new",text:"EM now has a stop rule, agreed before the answer is known: after 20 evaluable sessions from 2026-09-22, if the baseline book's cumulative R is at or below zero and the optimistic end of its average trade is under +0.1R, the paid nightly model review stops and EM stays watch-only. The close check writes a daily scorecard (track record per book, the stop rule, and five preregistered tests with fixed sample sizes) and raises a notice when a decision is due. It never changes a setting itself."},
    {tag:"new",text:"EM records the quote each exit was decided on, tied to its exit order, so the exit side of the spread is measured instead of estimated. Observation only; an exit never waits for it."},
    {tag:"fixed",text:"BRK.B (and other US share classes such as BF.B) now stream live from Alpaca. Before, the dot in the ticker kept them on the slower Yahoo poll, and on 2026-09-22 BRK.B's plans saw a new bar only every three to five minutes. Foreign listings (.TO, .V) are unchanged."},
    {tag:"improved",text:"EM's evening preparation runs as a recurring, resumable weekday task (one paid read at a time, one batch at a time) with a switch to turn the paid review off; the after-arming check follows Friday's batch to Monday. The Sept-21 fixes ride along: clock health check, admission alarm, and share observations with the same evidence policy as options."},
  ]},
  {version:"0.8.34",date:"2026-09-23",title:"Tips: correct target evidence, cleaner controls, and measured cost levers",items:[
    {tag:"fixed",text:"Scorecard: an option's target-to-fill is judged on the underlying at the fill minute (it had compared a premium with a stock target). Shadow research books are counted from their first execution, and the books with sells they never bought are quarantined as evidence."},
    {tag:"new",text:"Approval cards can show the equal-risk share size when an option cannot be sized within the budget (shown, never substituted), and an optional friction flag. Optional book and single-name exposure caps and per-source review budgets ship off."},
    {tag:"improved",text:"Prompt caching can cover the whole review conversation (measured about 50% cheaper on replayed reviews; off until chosen). A compact review context was measured and rejected because it lost management actions."},
    {tag:"new",text:"Reports: source return net of model cost, overnight carry by expiry, a knowledge ledger (what each rule costs on every call) and a one-page weekly review. No trading policy, risk limit, stop or approval control changed."},
  ]},
  {version:"0.8.33",date:"2026-09-22",title:"Cartel: better contracts and more ways into a trade (Practice switches, off until chosen)",items:[
    {tag:"fixed",text:"Contract ranking executable_cost_v2 compares crossing cost only among contracts near the target delta (0.35-0.65), so it no longer drifts to deep in-the-money contracts as v1 did."},
    {tag:"new",text:"Gap opens: an optional retest_v1 entry lets a stock that opens above its trigger enter on a completed candle that retests the trigger, with every other confirmation rule unchanged."},
    {tag:"new",text:"Screening: an optional non_increasing_v1 volume dry-up rule (base volume not above the prior base) beside the 0.8x rule; the review shows which rule each check used."},
    {tag:"new",text:"Arming: an optional minimum first-target R keeps plans whose first target sits almost on the trigger from taking an arm."},
    {tag:"improved",text:"Research panels keep scoring candidates on the 15-minute basis when a 5-minute entry pilot runs; the lab judges stock quote freshness by receipt time, so venue timestamps ahead of the host clock no longer blank its observations."},
  ]},
  {version:"0.8.32",date:"2026-09-22",title:"Tips: checkpoint verdicts are structured, replay claims are locked",items:[
    {tag:"fixed",text:"The five-session checkpoint reads the observation report's structured verdict: an INCOMPLETE report, an empty report or a missing verdict can no longer be published as READY, and every exported report uses the same cutoff."},
    {tag:"fixed",text:"A manual intake replay takes an atomic, durable per-message claim, so two concurrent requests can never process the same failed message twice."},
    {tag:"improved",text:"Quote records say whether an age comes from the vendor's stamp, this host's poll or receipt; a poll age is never presented as a verified source-event age. No trading policy, risk limit, stop or approval control changed."},
  ]},
  {version:"0.8.31",date:"2026-09-22",title:"Team2: a price estimate can no longer sell your position",items:[
    {tag:"fixed",text:"A Team2 premium stop is now taken only when the contract you actually hold has bled past the configured limit on a valid live quote, measured against what you paid. The read's own price estimate can no longer sell the position on its own. Structural stops, targets, the flatten and the live protective exits are unchanged."},
    {tag:"improved",text:"Every Team2 exit now records who decided it, the fill it was measured against, the quote and its timestamp, the resulting return and the limit in force."},
  ]},
  {version:"0.8.30",date:"2026-09-22",title:"Tips: correct decision arithmetic, complete observation evidence, exit and cost diagnostics",items:[
    {tag:"fixed",text:"Approval cards price options with the same complete fee basis as execution and show the contract's break-even and expiry, decoded from the contract itself when the vehicle omits them. The card states that payoff scenarios assume an exit at the target price."},
    {tag:"fixed",text:"The relevance-filter observation report joins every decision to its review's final status, marks the checkpoint INCOMPLETE when any decision is unresolved, and exports every human-review candidate. The five-session checkpoint task checks each report's exit code and counts only completed observe sessions."},
    {tag:"fixed",text:"A context-channel digest that is cut off or unparseable gets one bounded same-transcript repair before failing; both attempts stay on the usage record and nothing is written twice."},
    {tag:"new",text:"Scorecard v4: target exits show first touch, decision, order and fill times with the target-to-fill shortfall; open positions show all-in friction (fees plus quoted spread), hold cap and same-underlying exposure. Fill records label decision-, submission- and fill-time quotes apart and say which clock each age came from. Raw-message coverage report and a bounded manual replay for messages whose extraction failed. No trading policy, risk limit, stop or approval control changed."},
  ]},
  {version:"0.8.29",date:"2026-09-21",title:"Cartel: contract search, executable cost, causal review and a 5-minute Practice cadence",items:[
    {tag:"new",text:"Contract selection version diverse_liquidity_v1 (Practice, off until chosen): the reviewed contract is refreshed first, refresh requests are spread across expiries, contracts already below the open-interest minimum are recorded instead of refreshed, and the search reports exactly what it did and did not cover."},
    {tag:"new",text:"Contract ranking version executable_cost_v1 (Practice, off until chosen): eligible contracts are ordered by displayed-size coverage and crossing spread plus fees over the debit; every estimate names its assumptions and the legacy choice."},
    {tag:"improved",text:"Daily review names the first known blocker, other independent blockers, incomplete windows (kept unknown), contract-search coverage and actual versus modeled results per plan. NOW's wick and BBY/CNH/NVT's no-touch sessions are explained as such."},
    {tag:"new",text:"Practice entry cadence breakout_5m_v1 (off until chosen): new plans confirm on 5-minute candles with their own baseline while a non-ordering 15-minute matched control is recorded on the same tape for the daily review."},
    {tag:"improved",text:"Preflight and selection reports show spread in units, dollars and percent of premium, fees, debit and full-debit exposure beside the stock target/stop geometry."},
    {tag:"fixed",text:"Review round 1: the matched 15-minute control keeps observing after the executing plan acts (own tape, watermark and session lifetime); saved unlabelled 5-minute settings stay legacy and valid in Live; the 5-minute pilot is long-only; discovery and chain requests obey the signal deadline; a partial candle is reported as unknown, not as a close; partial fills are classified from order and execution rows; later refusals are no longer claimed independent."},
  ]},
  {version:"0.8.28",date:"2026-09-20",title:"Cartel keeps analysis checkpoints across repeated restarts",items:[
    {tag:"fixed",text:"Resuming an interrupted retry now reuses analyses from its compatible earlier checkpoints, including work saved before a crash. Existing plans remain preserved."},
    {tag:"fixed",text:"Automatic recovery waits for its runtime controller to attach before attempting a restart resume."},
  ]},
  {version:"0.8.27",date:"2026-09-20",title:"Cartel preparation resumes after restart",items:[
    {tag:"fixed",text:"Interrupted Cartel preparation now keeps its recovery checkpoint and resumes under the existing retry settings. Existing armed plans are preserved."},
    {tag:"improved",text:"The preparation panel explains saved work and how to resume, instead of showing stale discovery progress and a generic red restart error."},
  ]},
  {version:"0.8.26",date:"2026-09-19",title:"EM Experimental: a second Practice book runs the integrated method",items:[
    {tag:"new",text:"EM can run a dedicated experimental Practice book beside the unchanged EM Practice baseline. The experimental book prepares with rules only, enforces reward to risk at the real first sale, records executable profit, trades eligible source ideas and fresh setups, and protects a runner that closes back through its first target."},
    {tag:"improved",text:"Every experimental policy is resolved for that one simulated book. The baseline book, other desks, live accounts and all risk limits are unchanged. Pausing the experimental book stops its new entries while open positions stay managed."},
  ]},
  {version:"0.8.25",date:"2026-09-19",title:"Tips: opportunity tracking and a faster cold-ticker path",items:[
    {tag:"fixed",text:"A tip parked only because its symbol had no quote yet is re-checked on the first real quote (up to 60 s) instead of waiting for the 15-minute sweep. The same verification, plan and risk checks apply."},
    {tag:"new",text:"Reports: every actionable idea gets one disposition (filled, declined, risk-infeasible, late, analysis failed, approval expired, order unfilled) with avoidable misses apart; the scorecard shows how closed positions ended, winners and losers together; review cost is split by message type and what the review did."},
    {tag:"improved",text:"A reviewed rule consolidation can be applied as a pending proposal: duplicates are retired reversibly and the merged rule stays non-operative until approved. A cheaper-model evaluation of intake reviews is prepared with a $35 ceiling; no paid run and no model change."},
  ]},
  {version:"0.8.23",date:"2026-09-18",title:"EM: source fidelity, one preparation owner and executable profit",items:[
    {tag:"new",text:"EM Validation has a read-only review panel: what each author actually said against every trigger we planned and the gate that decided, order-free source candidates, first-sale R at the final quantity, and realized, displayed and executable profit side by side."},
    {tag:"fixed",text:"EM can measure reward to risk where a position really exits, at the quantity bought and the live underlying price. The check is built and switched off; observing it and enforcing it are separate settings."},
    {tag:"new",text:"Source ideas keep their author, direction, conditions and timing. A ticker the transcript does not support stays unresolved, a call strike is never a price target, and a correction never rewrites what the app knew on the day."},
    {tag:"new",text:"A rules-based preparation policy, a fresh-setup requalification study and the executable-profit recorder are built and switched off. Baseline Practice preparation and trading are unchanged."},
    {tag:"fixed",text:"EM research: a thin first quote no longer closes the runner-protection search."},
    {tag:"fixed",text:"EM review panel: each trade keeps its own result even when two entries share one contract, late fills are shown as revisions, partial results say what is unknown, and model cost is shown as an estimate beside results."},
  ]},
  {version:"0.8.22",date:"2026-09-18",title:"Cartel trial readiness",items:[
    {tag:"fixed",text:"A frozen trial now says awaiting sessions before its first market open, instead of reporting future observations as missing evidence."},
  ]},
  {version:"0.8.21",date:"2026-09-18",title:"Cartel method lab and accurate SIP liquidity",items:[
    {tag:"new",text:"Practice Method lab compares breakout, reclaim and 30-minute pivot entries using frozen cohorts, recorded quotes and modeled option/share costs. Research does not place orders or change trading permissions."},
    {tag:"improved",text:"Trial reviews retain missing evidence, show modeled fills and costs, and record daily reviews with Friday checkpoints. No automatic strategy promotion."},
    {tag:"fixed",text:"Modern Alpaca SIP stock quote sizes are now treated as shares, removing obsolete 100x liquidity scaling. Option quote units are unchanged."},
  ]},
  {version:"0.8.20",date:"2026-09-18",title:"Cartel: clearer opportunity reviews and timely recovery",items:[
    {tag:"fixed",text:"Daily review separates a stock not reaching its entry level from incomplete data and historical refusals. Current Armed coverage no longer repeats a resolved warning as a current hold."},
    {tag:"improved",text:"Verified Practice repairs retry every minute and preserve the next fresh candle confirmation without replaying closed signals. Trading limits and selection rules are unchanged."},
  ]},
  {version:"0.8.19",date:"2026-09-18",title:"Cartel: verify provider-omitted intervals",items:[
    {tag:"fixed",text:"Practice can distinguish provider-omitted price intervals from lost data using complete trade-feed evidence. No candles are invented, unresolved gaps still block, and repaired history cannot trigger a late entry."},
    {tag:"new",text:"Cartel Settings exposes the Practice-only verification switch; Armed shows verified interval counts. Exact proof evidence is saved with decisions."},
  ]},
  {version:"0.8.18",date:"2026-09-18",title:"Cartel: reject malformed minute updates",items:[
    {tag:"fixed",text:"Cartel rejects misaligned or wrong-symbol minute updates before they reach entry evaluation. Valid updates continue normally; incomplete and unverified candles still block entries."},
  ]},
  {version:"0.8.17",date:"2026-09-18",title:"Team2: retain experiment review state",items:[
    {tag:"fixed",text:"Practice experiment starting equity and sampled high-water marks can be saved and restored through the settings service. Trading rules are unchanged."},
  ]},
  {version:"0.8.16",date:"2026-09-18",title:"Team2: consistent inputs for Practice comparisons",items:[
    {tag:"fixed",text:"Bars retain their data provider, and Yahoo updates cannot replace Alpaca bars. Team2 can use Alpaca-only history and preserve each plan's indicator warm-up through restarts and replay."},
    {tag:"new",text:"Practice experiment books get scheduled half-hour equity reviews with persistent book pauses at their agreed review thresholds. Activation still requires verified data and a readiness receipt."},
  ]},
  {version:"0.8.15",date:"2026-09-18",title:"Cartel: faster preparation and clearer progress",items:[
    {tag:"improved",text:"Cartel checks and arms its shortlist before optional research finishes. Plans shows stage timings and separates shortlist readiness from research completion."},
    {tag:"new",text:"History request spacing offers a Fast option with automatic slowdown on provider throttling. Scan coverage, data source and trading checks stay unchanged."},
  ]},
  {version:"0.8.14",date:"2026-09-18",title:"Options Cartel: explain missed entries",items:[
    {tag:"improved",text:"Cartel records partial candle evidence, delayed-bar counts and the dollar cost of option spreads to explain missed entries. Trading thresholds and account protections are unchanged."},
    {tag:"new",text:"Offline Cartel method comparisons now distinguish original preparation, later recovery and unavailable evidence. Experimental setup and volume rules remain inactive."},
  ]},
  {version:"0.8.13",date:"2026-09-18",title:"EM research: the runner-protection observation seeks a real quote",items:[
    {tag:"improved",text:"EM research observer (behind the already-on shadow knob, order-free): after a confirmed TP1 trim, the bar that closes back through the saved first target now records the signal once and keeps looking for the first fresh, adequately covered contract quote on later quotes - a stale or thin first sample is raw evidence and no longer ends the search. The offline reducer walks fills and completed bars in time order, validates every observation strictly (trade, contract, signal, chronology, coverage, lifetime, cutoff) and reports proxy-only until an observation passes. No exit is placed from any of this; nothing else changes."},
  ]},
  {version:"0.8.12",date:"2026-09-17",title:"Team2: a breakout never targets the level it broke",items:[
    {tag:"fixed",text:"Team2 target resolution (September 17 QQQ finding): a setup's destination must be distinct from, and beyond, the structural level it broke or held, and ahead of the current actionable price (the fresh underlying print aged by its own trade time, else the bid/ask midpoint aged by the quote's own time, judged at the fire and again at the order boundary after the awaited work) - the same way for the EMA entry and the level entry of one setup. A target that is the setup's own source level is refused with a clear reason (skip_target_collision) instead of being re-planned to a farther level or silently dropped; no distance threshold is used. Switch: techniques.team2.target_identity_guard (default on; off = the earlier behaviour)."},
    {tag:"new",text:"Team2 pre-market inputs carry provenance: every frozen PMH/PML names the bar it came from and the hash of all pre-market bars (journaled at 09:25 and at the 09:30 finalization), and python -m zargar.tools.team2_pm_audit --date reconciles a plan's frozen extremes against the bank and the plan's own bar-revision history without rewriting the decision."},
    {tag:"improved",text:"Team2 chain listings (which contracts exist for an expiry) are cached per provider, symbol and expiry, concurrent requests share one fetch, a rate-limited or transient failure is retried twice with short back-offs and may serve a labelled stale listing within a bound; every candidate is still re-priced on the live NBBO and the timing gates are unchanged."},
    {tag:"improved",text:"Team2 shadow diagnostics: target and stop room from the actual underlying quote at the order boundary, whether the target is the setup's own level, Greeks with their provenance, a labelled payoff estimate after commissions and spread (insufficient evidence when an input is missing), coverage reported separately for attempts, Greeks and follow-up quotes, and gross versus net outcomes side by side (the risk counter's basis is unchanged)."},
  ]},
  {version:"0.8.12",date:"2026-09-18",title:"EM: the pre-open re-plan stops drawing charts nobody reads; profit-protection and prep-ablation research",items:[
    {tag:"improved",text:"EM pre-open re-plan runs (09:25 ET, deterministic, no model pass) no longer render four charts each on the single render thread - 45 of them did at the open on 09-17. Every run a model or a person reads keeps its charts and annotated map."},
    {tag:"new",text:"Practice simulator: an OPTION quote implausibly wide for its mid can be barred from pricing an OPENING order (config sim_max_option_spread_pct, OFF by default; stops, flattens and reducing exits are never capped - a proposal after the ORCL 148C fill at 1.12 on a 0.76/1.12 snapshot the contract never traded at). Share orders keep their own 5% rule."},
    {tag:"improved",text:"EM profitability report: a frozen runner-protection candidate (exit the runner only if a completed bar closes back through the saved TP1 after a CONFIRMED trim; a research-only reclaim observation records the contract quote at the signal), a descriptive table of closed positions without a TP1 trim, and the first-order premium edge at TP1 after friction per intent. Offline research; nothing trades from it."},
    {tag:"new",text:"EM preparation ablation tool (research, zero paid calls): replays every saved read of a prepared sheet through the live pre-open rules and the walk-forward tracker to compare model-selected, deterministic and exception-filtered plan sets; classifies the model's vetoes."},
  ]},
  {version:"0.8.11",date:"2026-09-17",title:"A quote that was changed locally can no longer pass as a venue quote",items:[
    {tag:"fixed",text:"Options: a real-time OPRA bid/ask is never bent toward a slower feed's last print any more (a 15-minute-old 0.70 print had turned a fresh 1.90/2.00 MRNA 165C band into 0.65/0.75 still labelled OPRA, and Practice 'bought' at 0.75). A delayed-chain estimate that IS recentred is now labelled derived, keeps the raw venue prices beside it, and can never price a simulated fill; fill receipts show the raw values and the transform."},
    {tag:"improved",text:"Tips payoff preview uses the same fee basis as the execution-cost diagnostic (commission plus the regulatory fee per contract per side)."},
    {tag:"fixed",text:"Tips analyst: every appraisal and intake review now keeps time for its final answer - inside the last ~20 s of the 120 s budget tools are switched off and the model is asked to answer; a run that still runs out records WHY (timeout / deadline / validation / error, the stage, elapsed and remaining seconds) instead of an empty error, its usage is marked partial when a call was cut, and a repair never re-runs a tool. The intake parser takes the first complete JSON object so trailing text no longer fails a valid extraction."},
    {tag:"new",text:"Tips operating cost, apart from trading P&L: every intake record now names its extraction model, and `python -m zargar.tools.tip_llm_cost --since <date>` rolls up model usage by day, run kind and model - priced only for models named in the new `llm.rates` setting, otherwise reported UNPRICED, with cut or cancelled calls flagged as a lower bound. Prompt caching of the stable prefix (system prompt, schema, tool definitions) is available behind `techniques.tip.prompt_cache` (off by default) so cache hits, cost and latency can be measured before anything is claimed."},
    {tag:"fixed",text:"Review follow-up: the analyst's final-answer reserve is now re-checked after every provider reply and before every tool and retry, so a late reply or a slow first tool can no longer run optional work inside the reserve; a reply that contains two competing valid JSON objects is refused as ambiguous (one clarification, tools off) instead of taking the first; the cost report prices tokens under the model that actually consumed them, keeping the intake extractor's identity apart, and reads legacy usage records without assuming their shape."},
    {tag:"fixed",text:"Review round 2: when a tool-capable analyst call is cut at the reserve boundary the run now spends the reserve on the final answer (tools off, same deadline) instead of failing with time in hand - only a cut final call is terminal; and every JSON parser inspects the whole reply past a closing code fence, so a competing 'correction' after the fence is refused as ambiguous rather than silently dropped."},
    {tag:"fixed",text:"Review round 3: a model reply that still has unexamined JSON after the parser's scan budget is refused as ambiguous instead of being certified unique; digest and rule-audit usage records name their model on every attempt; the frozen replay harness gains an explicit cache on/off switch and an enforced dollar ceiling with per-attempt accounting (production prompt caching stays off)."},
  ]},
  {version:"0.8.10",date:"2026-09-17",title:"Practice share stops trigger only in the regular session, on a real quote",items:[
    {tag:"fixed",text:"Practice (sim) share orders now rest outside 09:30-16:00 ET unless placed for extended hours, and a stop never triggers on a placeholder quote: a quarantined shadow book's AFRM stop had 'filled' 27 sh at 44.99 at 03:59 ET on a 45/75 pre-market book while the stock traded 72-74. A share quote wider than 5% of mid cannot price a simulated fill; the order waits and says why (both knobs, sim.stock_sessions / sim.max_spread_pct)."},
  ]},
  {version:"0.8.09",date:"2026-09-17",title:"EM Analyse tab stays up beside other techniques' runs",items:[
    {tag:"fixed",text:"EM > Analyse crashed (\"Cannot read properties of undefined (reading 'map')\") a few seconds after opening: the page read the newest run of ANY technique, and tonight that was an Options Cartel research run whose analysis has no EM levels. The EM page now lists only EM runs, and the result view tolerates an analysis without levels, targets or reasons."},
    {tag:"fixed",text:"EM profitability report (offline research tool): the paired confirmation comparison now tells the report's cutoff apart from the session's actual 16:00 ET close - a 10:02 ET report with one observed bar after the touch stays PENDING instead of reading as no confirmation; only the session's last bar closes an incomplete horizon. Preparation and trading unchanged."},
  ]},
  {version:"0.8.08",date:"2026-09-16",title:"The EM check panel finishes when the server has finished",items:[
    {tag:"fixed",text:"EM > Validation: the analyst-check panel no longer sits at \"73/114 · 0 working · 0 queued · ~2.1 h left\" for hours on a batch the server had finished. Its run list was crowded out of the window by another technique's research runs, so every 3 s it fetched up to 40 full runs and restarted itself before recording any of them - a real load on the engine while the page stayed open. Now the list is filtered to the batch, a finished run is never fetched again, a run the server cannot return is counted as not loaded after a few looks, one poll runs at a time, and the batch closes when nothing is open."},
    {tag:"improved",text:"The check panel lives on the Validation tab (phones keep it on every tab), the time-left estimate shows only while something is actually running, and a dismissed batch stays dismissed instead of coming back on the next reload."},
  ]},
  {version:"0.8.07",date:"2026-09-16",title:"Knowledge tab: the true total, the loaded count and honest category counts",items:[
    {tag:"fixed",text:"Tips > Knowledge: the category buttons (Rules, Tickers, Sources, General, Needs you) now filter on the server BEFORE paging, so an older rule or a flagged note beyond the first 200 rows is reachable through its button instead of vanishing; their counts are the whole store's, not the loaded page's."},
    {tag:"improved",text:"The coverage line shows two separate numbers - how many notes MATCH the current view/search and how many are LOADED - with a load-more that names how many come next; it lives on its own wrapping row so it stays visible at phone widths and browser zoom instead of being pushed out of the panel header."},
  ]},
  {version:"0.8.06",date:"2026-09-17",title:"The watchdog never mistakes a quiet engine for a dead one",items:[
    {tag:"fixed",text:"Watchdog: a live engine process whose log is quiet is LIVE, not absent; a process-discovery failure is UNCERTAIN; both refuse ordinary recovery (with or without -Force) because readiness is unavailable, and only the explicit override replaces a living engine. A healthy first probe clears the stall marker and alert state; -ProbeOnly creates nothing and writes nothing. The caller decision is a pure function with mocked acceptance (20 cases)."},
    {tag:"improved",text:"EM profitability report: the paired confirmation comparison judges the entry minute itself, keeps incomplete horizons pending, states that the touch bar never confirms, and labels itself a geometry-only underlying proxy naming the gates it does not evaluate. Research labels only; no trading change."},
  ]},
  {version:"0.8.05",date:"2026-09-16",title:"Team2 candidate quotes are bound at examination",items:[
    {tag:"fixed",text:"Team2 shadow diagnostics: each contract the picker examines is recorded as ONE observation - its bid/ask, provenance, source-confirmation time, receipt time and capture time are captured together at that moment, and the report validates and shows exactly that record. A later quote-cache state is a separate observation and is never attached to an earlier price; a quote that moves during capture is marked unknown with the reason."},
  ]},
  {version:"0.8.04",date:"2026-09-17",title:"EM entries survive a rate-limited chain; the engine can name a stall",items:[
    {tag:"fixed",text:"EM option pick: a CBOE HTTP 429 (rate limit) is retried briefly (0.6 s, then 1.2 s; Retry-After honoured up to 2 s) before the entry gives up; expired chain data is never served for a live pick; the no-contract alert names the cause and says a short has no shares fallback by rule. Background chain fetches (enrichment, research) stand down for options.cboe_cooldown_seconds after a 429 instead of feeding the burst."},
    {tag:"fixed",text:"Two event-loop stall causes the new stall watch named on its first evening are fixed: root logging goes through a queue (the rotating file handler wrote on the loop - one 51 s stall came from inside it), and provider chain/snapshot JSON is parsed off the loop (a multi-megabyte CBOE chain took 4 s on it); chain normalisation and the enrichment index run on a worker thread too, and the enrichment pass yields between underlyings (a 4.8 s stall was OCC formatting over thousands of rows)."},
    {tag:"improved",text:"Chart rendering for the vision passes runs off the event loop on one worker thread, and an event-loop stall watch (ops.loop_stall_seconds) logs the blocking call site and reports loopStalls / lastStall / eventLoopLagMs on /api/health - the 2026-09-16 restart storm could not say what stalled."},
    {tag:"improved",text:"EM profitability report: P-04 entry strata (descriptive) plus a paired, order-free confirmation comparison (confirmed close, then next-bar open, unchanged gates, distinct refusals, option dollars unknown), and P-05 session-window / event-phase cohorts from the shared session clock with unknown calendar coverage stated. Research labels only; no trading rule changes."},
    {tag:"fixed",text:"/api/health answers build=unknown instead of a 500 when the launch-bound build helper is missing from the checkout."},
  ]},
  {version:"0.8.03",date:"2026-09-16",title:"Team2 quote freshness reads the source, not the receipt",items:[
    {tag:"fixed",text:"Team2 shadow diagnostics: a price's freshness is judged on the provider's confirmation time for that bid/ask (the quote's source timestamp), never on when the app last received it - a recently received old price is unknown at the entry and at every follow-up, a price with no source evidence stays unknown, and a freshly confirmed unchanged price still counts. Receipt and collection times are recorded beside the source time."},
  ]},
  {version:"0.8.02",date:"2026-09-16",title:"Team2 shadow measurements: unknown stays unknown",items:[
    {tag:"fixed",text:"Team2 diagnostics (review of v0.8.01): a follow-up quote counts only when it is live, sane and carries its own source timestamp within 30 s of collection - a cached entry quote re-served two minutes later is unknown, with the reason; every candidate keeps its source and collection timestamps; the shadow follow-up refreshes through the options service's forced path and follows at most six contracts per attempt. A candidate whose entry price is unknown produces no hypothetical return and enters no denominator or comparison. The shadow summary is isolated from the close: a fault in it is recorded as diagnostic-incomplete while P&L, the funnel and the disarm complete. Exit prices are weighted by confirmed filled quantity, whatever the cached order status says; a requested quantity is never a fill."},
    {tag:"improved",text:"The diagnostics report labels the two kinds of number apart: actual book fills (realized, after commissions) versus HYPOTHETICAL quoted ask-to-bid returns after two commissions."},
  ]},
  {version:"0.8.01",date:"2026-09-16",title:"Team2 measures its entries and contracts in the shadow",items:[
    {tag:"fixed",text:"Team2 close report: refusals and skips are counted as UNIQUE decisions from a durable ledger (event, setup, source minute) that rides the persisted state and is rebuilt from the journal - the 400-row display buffer no longer decides the day's funnel, a re-quoted price on the same candidate is a revision, and raw row counts are reported apart. The scorecard now carries an immutable decision-time view of every fire (signal and confirmation times, tape and rules identity, release and build) beside the corrected-history comparison."},
    {tag:"new",text:"Team2 profitability diagnostics (shadow measurements, techniques.team2.diagnostics, no order decision changes): every entry records its confirmation close, pullback candle, setup level, entry line, the underlying at the order boundary and the distances in ATR (same-close confirmation and moved-away labels); every attempt records first vs subsequent entry into the setup, whether the previous attempt lost and what fresh evidence existed; the picker keeps the selected contract and the alternatives it examined with their live quotes and Greeks, follows them 2, 5 and 10 minutes later and at the actual exit, and compares after-cost outcomes (ask-to-bid after two commissions; missing quotes stay unknown). A candidate refused by an allocation cap is quoted in the shadow too."},
    {tag:"new",text:"python -m zargar.tools.team2_diag_report --date YYYY-MM-DD: the session's entry situations and contract choices ranked on after-cost outcomes, with observation counts and missing-data coverage."},
  ]},
  {version:"0.7.99",date:"2026-09-16",title:"Cartel: better contract choices and preparation evidence",items:[
    {tag:"new",text:"Automatic Practice plans can make one bounded alternative-contract search when spread is the only failed entry check. Saved limits stay intact and every entry check runs again; control it in Cartel Settings."},
    {tag:"improved",text:"Research baselines warm for the next session overnight. Validation compares saved entry rules with non-executing gap/retest and 1x-volume diagnostics on the same data."},
    {tag:"fixed",text:"Daily review now shows the actual execution refusal and its dated quote evidence instead of leaving a rejected entry labeled only as signalled."},
  ]},
  {version:"0.7.98",date:"2026-09-16",title:"Current Cartel guidance and integrated release identity",items:[
    {tag:"improved",text:"Cartel's Method documentation now explains research readiness, fair baseline retries, short-pool counts, data warnings and actual versus modeled results. Stale operational snapshots are replaced with dated references."},
    {tag:"fixed",text:"The shared build-identity helper is retained on main, and health remains available if build identification fails. Deployment still requires verified source, artifact and restored state."},
  ]},
  {version:"0.7.97",date:"2026-09-16",title:"Cartel research gives every candidate a turn",items:[
    {tag:"fixed",text:"Research now loads never-attempted volume baselines before retrying failed names. Retries rotate by persisted attempt count and oldest due time, so early failures cannot starve the rest of the pool after a restart. Trading rules and candidate rankings are unchanged."},
  ]},
  {version:"0.7.96",date:"2026-09-16",title:"Tips see the day's event and the real cost of a trade",items:[
      { tag: "new", text: "Tips: verified event context (TMR-01). The analyst header, every card, the cohort and hold-study records and adopted positions now carry the day's verified macro-event label - FOMC statement 2026-09-16 14:00 ET and press conference 14:30 ET from the official Federal Reserve calendar, with the verification time and time-to-event; a date the calendar has not been checked for reads UNKNOWN, never 'no event'. Awareness only: no automatic no-trade rule, no order placed or blocked." },
      { tag: "improved", text: "Tips analyst reasoning (INTRA-01/02): the payoff preview now prints the EXPIRATION break-even beside the before-expiry scenarios with the declared holding horizon, and a one-contract plan is judged on the single exit it can execute (first target or a premium exit) instead of being called unmanageable for not copying a source's partial scale-outs; the prompt carries both rules and keeps every independent reason to skip." },
      { tag: "new", text: "Tips intake (INTRA-03): a cheap deterministic read of a multi-signal message (map / recap / management / new / mixed) is journaled before the paid appraisal; routing confirmed recaps to a compact analyst context is built but OFF (techniques.tip.recap_route) until evaluated on frozen examples." },
      { tag: "new", text: "Tips research: an experiment register (TMR-05) gives every study one identity - hypothesis, variants, unit of observation, costs, regime, evaluation window - and every research report now carries it; a time/volatility scenario prototype (TMR-03, research only, wired to nothing) shows how elapsed time and an IV change would move a long option's value, with a worked example on frozen evidence." },
      { tag: "new", text: "Tips: execution-cost diagnostic (TMR-02). Beside feasibility and payoff, the analyst tools, the risk plan and the card show the instantaneous round trip on the qualified quote - spread once plus both sides' fees at the venue basis, quoted size, cost as a share of the purchase - and each realised fill is journaled against the quote the decision saw. Unknown on stale, crossed or missing quotes; changes no quantity, contract, limit or gate." },
  ]},
  {version:"0.7.95",date:"2026-09-15",title:"EM entries are decided by the app's own rules, not a model",items:[
    {tag:"major",text:"EM live entry authority is deterministic (techniques.enhanced_market.fire_decision_mode=deterministic): when a trigger fires, the app's encoded rules judge the saved geometry, the tracker's own window, volume and the confirmation branch that actually fired - in milliseconds, with no model call, no chart render and no timeout on the entry path. Every attempt is journaled as a TechniqueEntryDecision with its frozen snapshot, policy and the last 240 bars up to the signal close; refusals are recorded as no-setup with reason codes. The pre-market LLM plan builder is unchanged; legacy critic mode remains selectable."},
    {tag:"new",text:"Optional after-close LLM evidence (fire_evidence_mode=after_close, OFF): one bounded, evidence-only pass over the frozen decisions of a closed session - it verifies the record's declared identity (input hash, frozen-bar hash and count, cutoff) against the captured material before rendering or buying an opinion, and can never touch an order, an arm or a setting."},
    {tag:"improved",text:"EM profitability report attributes fills and refusals to the attempt that produced them (policy version, decision id), builds the attempt census from every run's immutable fire events and counts refusals once per attempt."},
    {tag:"improved",text:"Armed cards and the arm dialog show the effective live-entry policy (deterministic / legacy critic / policy error); Settings gains an EM live entry authority group."},
  ]},
  {version:"0.7.94",date:"2026-09-15",title:"Experiment books are validated, frozen and transition-safe",items:[
    {tag:"fixed",text:"Team2 experiments (still OFF): the map is validated as a whole - a control book, one role per experiment book (sizing -> size_full, c1 -> no_trade_zone), required labels, distinct unarchived Practice books, no combination of C1 and the sizing cap; an invalid map applies nothing and reports why. A plan's override is frozen on the plan at mint time, so disabling or editing the map can no longer turn an armed sizing book back into full size, and a restart restores the same book and rules. Switching the default book inventories plans on other books (retired without exposure, paused with it), a forced re-plan never removes the manager of an open trade, and an experiment plan can only be armed on the Practice book it was minted for. A transition step that fails or cannot be confirmed blocks the experiment minting and leaves the old plan managing its book. Every plan now carries the release and build that minted it, the readiness receipt checks that provenance and plan cardinality per book and symbol, and its settings load is fully read-only."},
  ]},
  {version:"0.7.93",date:"2026-09-15",title:"Team2 can run parallel Practice experiments, one book each",items:[
    {tag:"new",text:"Team2 experiments (techniques.team2.experiments, OFF by default): each listed Practice book gets its own plan per symbol, minted and run under the shared baseline plus that book's overrides - and only size_full or no_trade_zone may differ; anything else is refused. Loss counters and the concurrency cap are now per book, plans carry their book's rules and label, and an experiment book must be a Practice (sim) book - never real money. The shared Team2 settings stay the baseline every other book runs on. Built for the review team's parallel sizing-cap and C1 experiments; nothing is enabled or activated by this release."},
  ]},
  {version:"0.7.92",date:"2026-09-15",title:"Cartel: tomorrow's plans wait for tomorrow",items:[
    {tag:"fixed",text:"Plans armed for a future session no longer show 390 overdue minutes from the preparation day. Their status names the upcoming session, while genuine gaps during an active session still trigger attention and repair."},
  ]},

  {
    version: "0.7.91",
    date: "2026-09-15",
    title: "The Dashboard's colour, its picker, and real money in one currency",
    items: [
      { tag: "fixed", text: "The equity chart is coloured by the same number its header prints. It used to colour itself against the first sample in the window (04:00 ET pre-market), while the header measures from the previous close - so a green '+US$220 today' sat over a red line whenever the window opened above the close." },
      { tag: "improved", text: "Picking a book drives the whole board: the headline shows that book's total and its move, its account chip lights up, and the curve follows. Chips are the picker - click one for that book, again for all." },
      { tag: "fixed", text: "LIVE reads in one currency. The real accounts are a CAD book holding US listings and a USD book; the day move, the headline's live marking and the summed curve added those together raw, and the board said -24% on a day the money moved -2%. Every book is now converted at today's USD/CAD before it is summed, the footer says so, and an account that cannot be priced is named instead of silently skipped." },
      { tag: "fixed", text: "The day anchor for a real account no longer drifts. A broker sync shifted it by 'equity after minus equity before', which also carried a currency correction or a mark replacing a fallback - 95 syncs manufactured +1,560 of anchor on a C$4,000 Wealthsimple book and read as -28% today. It shifts only for cash that moved and holdings that appeared or vanished, at the book's own mark, and every shift is journaled (DayAnchorShifted) so a restart replays it instead of forgetting a transfer." },
      { tag: "improved", text: "Empty accounts fold into one '+N empty' chip instead of four C$0.00 tiles." },
    ],
  },
  {version:"0.7.90",date:"2026-09-15",title:"A book can be paused until someone releases it",items:[
    {tag:"new",text:"Per-book pause (POST /api/portfolios/{id}/pause with a reason and label, /unpause to release): every new entry and add on that book is refused - by the runners and by the risk gate - while protective exits keep working and every other book trades on. Unlike the daily-loss halt it has no day: it survives restarts and the day roll and ends only when released. Releasing it never clears the kill switch or a daily-loss halt, and those never clear it. The record snapshots the book's sizing settings; the pause changes no setting. Built as the loss-stop action of the Team2 sizing experiment; nothing is paused by this release."},
  ]},
  {version:"0.7.89",date:"2026-09-15",title:"Cartel: compare opportunities before changing the strategy",items:[
    {tag:"new",text:"Practice profitability research follows a wider candidate pool, compares selection rankings and adds a separate bearish study. Find dated observations in Options Cartel > Validation."},
    {tag:"new",text:"Compare campaign targets and predefined failed-break, time and early-trim exits. Whole units, source gaps and missing option costs stay visible; research cannot place orders or change your trading permissions."},
    {tag:"improved",text:"The Method library now explains how to collect and review the experiments. Actual fills and account profit remain in Daily review."},
  ]},
  {version:"0.7.88",date:"2026-09-15",title:"A cheap 0DTE contract is sized to the cap, not refused",items:[
    {tag:"fixed",text:"Team2 F127: the contract sizer now clamps to the technique's 0DTE policy cap (40 contracts) for a contract that expires today, instead of asking for 50 and being refused by the risk gate - IWM's 284 put at $0.33 was refused that way at 11:14 ET on 09-15. Scoped to the selected contract's actual expiry: a longer-dated contract keeps its existing cap. The risk gate itself is unchanged."},
  ]},
  {
    version: "0.7.87",
    date: "2026-09-15",
    title: "Tips: an override acknowledges the whole incident state; the claimed plan is immutable",
    items: [
      { tag: "fixed", text: "A86-01: a card shows EVERY applicable open incident (id, revision, evidence); an override must acknowledge exactly that set - appended evidence, another incident or a changed revision refuses with zero orders; an unavailable integrity store always blocks." },
      { tag: "fixed", text: "A86-02: the approval claim recomputes the card's full plan (exit policy, bracket, vehicle, risk plan) under the row lock instead of trusting the cached fingerprint; the claimed plan is frozen on the card and both the order and the later position adoption use it - a concurrent edit of the exit policy cannot be claimed." },
      { tag: "improved", text: "Entry-variant study: the sampling claim is held through finalization (timer and recovery never double-fetch); research fixtures carry capture-time verdict fields." },
      { tag: "fixed", text: "A failed structured read of the incident store is 'integrity state unavailable' (never overridable) rather than a partial identity from prose; position adoption uses the claimed vehicle and risk plan as well as the claimed exit plan." },
      { tag: "fixed", text: "Tips intake liveness no longer flaps Stalled/Recovered during a busy session: envelopes briefly in flight are a warning; only envelopes pending through three consecutive checks (about six minutes) are a stall." },
      { tag: "new", text: "Tips analyst considers the risk budget before recommending (PROF-01): the header states the approved planned-risk budget, a check_feasibility tool answers how many units of a named expression fit at the declared stop (with labelled research alternatives at equal risk - shares, or another strike of the same expiry - never a substitution), and every TAKE is assessed server-side: the expression check rides beside the opinion (thesis verdict kept apart); techniques.tip.analyst_feasibility_gate = annotate (default) or downgrade (an unfittable take becomes watch). Replay tool: python -m zargar.tools.tip_feasibility replay." },
      { tag: "new", text: "Whole-exit-path payoff preview (PROF-02): the risk plan and the card carry the ladder in INTEGER units (is it executable at this size?), the net result if every target fills, if the first target is followed by the stop, and the stop alone (in $ and R, fees included) and the coherent one-lot policy; the analyst gets a preview_payoff tool and a one-lot rule. Report tool: python -m zargar.tools.tip_payoff_report (RKT long-only round trip reconciles to -$30.15). Estimates, never a forecast." },
      { tag: "improved", text: "Overnight-hold study protocol v2 (research only): every observation carries its sampling window and identity - a pre-close sample must fall in the last 15 minutes before the exchange close (early closes included; an after-close boot records a miss, never back-labeled), the next-open sample is the first qualified quote inside 09:30-09:45 ET of the exchange calendar's next trading session (a later day never stands in), every sample is admitted on its ACTUAL sample time (a quote taken after the window is late, never qualified), the jobs run relative to the exchange close (12:50 on an early close) and from the opening bell, repeated capture is one observation, nets include the allocated entry fee and the exit cost, R follows the sampled size, and the carry arm is reported as overnight quote drift beside the strategy's own outcome when its exit closed the position first. Frozen comparisons flag coverage-limited pairs." },
      { tag: "new", text: "Overnight-hold study (PROF-03, research only): a 15:50 ET snapshot of every open Tips position (and every one that exited intraday) with the leg's qualified pre-close quote, horizon, exits and costs, plus the next session's first qualified quote at 09:36 ET; python -m zargar.tools.tip_hold_study report pairs carry-to-next-open against a predeclared intraday close by setup, counts unqualified samples as insufficient, never uses a hindsight peak and derives no rule. Knob techniques.tip.hold_study_enabled (observation only)." },
      { tag: "new", text: "Frozen analyst comparison (PROF-05): a compact context variant (core rules, notes relevant to the tip's ticker/source, the newest history lines) replays the same frozen evidence as the full context; reports now carry cache usage, effective input tokens, header size, contract, stop and quantity differences beside decision, latency and tokens. Research only - method behaviour unchanged." },
      { tag: "fixed", text: "Positions: ONE exit authority. When the manager adopts a filled share proposal it now cancels the entry order's resting bracket children (the proposal's GTC take-profit and stop-loss) - left beside the manager's own stop and ladder they doubled every exit (Tips Practice held 7 MRNA with 14 resting to sell at the stop on 2026-09-15; released by hand at 15:22 ET). Restore releases records adopted before the rule, and a bracket never spawns under an entry the manager already owns (partial fills)." },
      { tag: "fixed", text: "Positions: the resting venue GTC stop is resized after every trim (it used to keep the original size - RKT sold 148 shares against 89 held on 2026-09-15, a 59-share unintended short, reconciled the same day) and is re-registered after a restart so its fill reaches the position instead of leaving a phantom open lot." },
    ],
  },
  {
    version: "0.7.86",
    date: "2026-09-15",
    title: "Tips: an approval is bound to the whole plan you saw",
    items: [
      { tag: "fixed", text: "AP85-01: an incident override acknowledges one specific incident; a different incident or an unavailable integrity store at the final check always blocks, for single orders and spreads alike." },
      { tag: "fixed", text: "AP85-02: the confirmation now binds the complete displayed plan (stop, size, risk per unit, planned risk, budget, approved maximum limit, book/instrument, exit plan, bracket, each blocker's identity); every manual approval must carry it (Telegram first shows the revalidated plan, then confirms); the claim re-checks the row's plan atomically and the order is built from the confirmed snapshot - a concurrent refresh or edit refuses with zero orders." },
      { tag: "fixed", text: "AP85-03: half size = half of the displayed quantity (never below one), validated as that explicit action; the exposure recorded matches." },
      { tag: "improved", text: "Entry-variant study: a delayed sample is timed at the actual sample moment, one fetch per row even when the timer and the recovery pass coincide, and legacy records are re-judged at their capture time (after-hours or age-less observations never count)." },
    ],
  },
  {
    version: "0.7.85",
    date: "2026-09-15",
    title: "Tips: approval cards say whether a trade is ready, not just whether the analyst likes it",
    items: [
      { tag: "new", text: "Approval cards show two independent statuses - the analyst's opinion (take / watch / skip) and execution readiness (ready / blocked / needs refresh / unverified) - and list the ACTUAL blocking reasons by name: source not qualified for automatic trading, planned risk over the approved budget, missing / stale / delayed quote, an open execution-integrity incident, an unsupported instrument. 'AUTO: NOT YET EARNED' is gone." },
      { tag: "new", text: "The final risk calculation is on the card: purchase allocation limit, approved planned-risk budget, estimated risk per share/contract, final quantity x risk, final stop (and the analyst's original), quote source and age, every adjustment made after the analyst's answer. Planned stop risk is labelled an estimate, not a guaranteed maximum loss; the analyst's sizing narrative stays separate." },
      { tag: "new", text: "'Refresh & revalidate' re-fetches the quotes the plan needs, recomputes geometry and sizing, re-checks incidents and gates and saves the result - zero orders, the entry limit never raised. A resolved incident no longer leaves a permanent stale label." },
      { tag: "improved", text: "Approve submits exactly the displayed, freshly validated plan: a blocked card is refused with the reason, a plan that changed since it was displayed (stop, size, a new failed check, a new incident) asks you to look again, a limit is never above what you saw, expired cards and duplicate clicks cannot create orders. An override is a separate action that names each check it accepts, shows the resulting exposure, needs a reason and is journaled; the platform protections (risk gate, kill switch, loss halts) still apply." },
      { tag: "fixed", text: "Knowledge consolidation (KF83-01/02): a reviewed rejection now releases the dispute and expires the rule in ONE transaction - a failed expiry leaves the rule disputed and non-operative - and a retry recovers only a release this manifest wrote (the revision snapshot carries the manifest's marker; the batch receipt is the proof); another person's resolution refuses the stale review." },
      { tag: "fixed", text: "Entry-variant study (KF83-03/04): a delayed sample counts as three-minute evidence only inside a declared tolerance (default 60 s) - later observations are kept as late diagnostics; a quote is executable comparison evidence only with venue provenance, no delayed flag, a genuine source time, a valid two-sided quote and an open option session - a freshly stamped chain snapshot never qualifies; stored records are re-judged." },
    ],
  },
  {version:"0.7.84",date:"2026-09-15",title:"Intraday market research without automatic unlocking",items:[
    {tag:"new",text:"Cartel Practice can observe blocked-market shortlists during the session, comparing completed 15-minute index candles with saved daily EMA levels and recording hypothetical stock confirmations. It cannot arm plans or place orders."},
    {tag:"improved",text:"The accepted research-only decision and its distinction from Sean's guidance are documented. Missing evidence stays unavailable, and existing execution permissions and risk settings remain unchanged."},
  ]},
  {
    version: "0.7.83",
    date: "2026-09-15",
    title: "Tips: retry-safe knowledge batches, recovered samples, visible attachment coverage",
    items: [
      { tag: "fixed", text: "Knowledge consolidation: a dispute release now commits together with the batch's progress record, and the journal notification comes after - a failed notification can no longer leave a released rule that an identical retry refuses. A release that committed without its progress is recognised on retry (reviewed revision + 1 with a resolve snapshot)." },
      { tag: "fixed", text: "Entry-variant cohort: pending delayed samples are recovered after a restart (startup and every minute while the cohort is enabled); a sample far past its due time is marked missed, never back-labelled." },
      { tag: "new", text: "Tips card shows attachment coverage (per image: processed / failed / unreadable / skipped) and which block the extracted evidence came from (caption or attachment n)." },
    ],
  },
  {version:"0.7.82",date:"2026-09-14",title:"A cancel that reports more contracts than were booked books them",items:[
    {tag:"fixed",text:"Orders F: a terminal order report now books its cumulative fill for any entry, including one an earlier partial fill had already opened - a cancel reporting two contracts after one was booked adds the second and manages both. Duplicate reports, a smaller total and a confirmed zero fill still change nothing they should not."},
  ]},
  {version:"0.7.81",date:"2026-09-14",title:"A cancel that says one contract filled is a position",items:[
    {tag:"fixed",text:"Orders F: a terminal order report (cancelled, expired, rejected) is now classified by the cumulative filled quantity it carries, not by what the app happened to see earlier - if the partial-fill callback was missed, a cancel reporting one contract filled books that contract and manages it instead of being treated as a zero fill. Live and after a restart (the persisted order row). Confirmed zero-fill outcomes still clear the way for Team2's proxy exemption."},
  ]},
  {version:"0.7.80",date:"2026-09-14",title:"An unanswered order is resolved when the venue answers",items:[
    {tag:"fixed",text:"Orders F: an entry whose venue hand-off got no answer now stops being uncertain the moment the venue's own report arrives - a confirmed rejection or cancel with nothing filled becomes an ordinary failed/cancelled entry (and Team2 may exempt it from the read's proxy), a fill or partial fill stays managed and is never exempted, and a cancel after a partial keeps the fill. After a restart an unresolved entry is judged against the persisted order row; an in-flight or missing row keeps the uncertainty. Nothing clears it on a local timeout or a cancel request."},
  ]},
  {version:"0.7.79",date:"2026-09-14",title:"Tips intake reads every image, and says which one it read",items:[
    {tag:"new",text:"Multi-image tips (KFIN-07): a message's whole attachment set is processed, not just the first image - each attachment keeps its Discord id and order, gets its own transcript, and every extracted quote is attributed to the caption or to ONE attachment (attachment n of N). A ticker or price that lives only in the second screenshot now grounds. Bounded by techniques.tip.intake_max_images (4), intake_max_image_bytes (8 MiB) and intake_vision_calls_per_message (4)."},
    {tag:"improved",text:"Attachment coverage is on the record: the content's manifest and a TipAttachmentsProcessed journal entry list every image as processed, absent, unreadable, failed (with the reason) or skipped-over-budget - an image the desk did not read is never evidence, and a fetch failure at the gateway no longer disappears."},
    {tag:"fixed",text:"Two screenshots that disagree (a different strike, price or expiry for the same trade) are no longer blended into one tip: both readings are kept, flagged as a conflict (TipAttachmentConflict), fail verification into the analyst's review and never dedupe onto an older tip. Duplicate deliveries still cost no extraction or transcription; an edited message is still a revision, never re-extracted."},
  ]},
  {version:"0.7.78",date:"2026-09-14",title:"A retry is a new order, an unanswered order is not a zero, a held position keeps its stop",items:[
    {tag:"fixed",text:"Team2 E: a transport retry of an entry is judged on the wall clock again before it is sent, and the technique's time rule now runs inside the order manager after its last await, immediately before the venue hand-off - an entry admitted at 15:29:59 that retried at 15:30:01 used to go out. A refusal there is recorded as a skipped opportunity with its decision time, never as a strategy refusal. Exits and cancels are untouched."},
    {tag:"fixed",text:"Orders F: when the venue hand-off happens but the answer never arrives, the outcome is UNKNOWN (SubmitUncertain, carrying the order id) - the entry stays submitting with its exposure reserved and its order identity registered, it is never retried as a fresh order, an alert is raised, and it is never treated as a zero fill. Team2's proxy exemption withdraws itself when fill evidence later arrives; only a confirmed rejection or cancel with zero fill clears occupancy."},
    {tag:"fixed",text:"Team2 G: a book position the model no longer holds (its exit surfaced by a corrected minute was recorded, not replayed) still receives the method's present-time one-candle stop: on every 2m decision the current close is judged against the EMA13 / EMA48 / 200 EMA (or the level) and a stop is issued NOW with the current timestamp (orphan_stop). No new threshold."},
  ]},
  {
    version: "0.7.77",
    date: "2026-09-14",
    title: "Tips EOD review: liveness, governance, isolation",
    items: [
      { tag: "new", text: "Meet Kevin own-book workflow (KFIN-08, shadow-first, OFF by default): a source enrolled in techniques.tip.mk_ownbook_sources has its 'I bought / added / sold half' text classified (own trade, exit, recap, hypothetical, someone else's screenshot) and, in mode=shadow, booked only in a dedicated own-book shadow book - never a proposal, an armed plan or a Practice order. A disclosure without a grounded price/contract or a qualified quote stays unresolved on the record; recaps and exits never open. GET /api/tip/ownbook/{source} reports the ledger graded on the quote at the decision inside the declared cohort against the mk_ownbook_* promotion criteria - a human verdict, nothing automatic." },
      { tag: "improved", text: "Delivery telemetry + deployment ownership (KFIN-03/04): one bounded telemetry writer flushes every bar consumer's snapshot even while the journal is slow, handler start/end/failure/cancellation are recorded for every consumer (in-flight age and bus drops on /api/ops/delivery-health), engine shutdown never waits on a stuck sink; a restart handoff verifies clean reviewed source plus a manifest of the whole built UI, deployment receipts always end in verified/failed/deferred, and a long-running Tips analyst job stays visible to restart readiness by ownership and heartbeat, not by age." },
      { tag: "new", text: "Intake liveness (EOD-01): the Discord gateway now proves delivery, not just health - a status file every 30 s (last frame, last message per channel, ledger backlog, reconnects), an idle watchdog that forces a reconnect when no frame arrives for 3 minutes, and a file log. The app exposes GET /api/tip/intake/liveness (gateway clock + mirror watermarks per watched channel) and journals TipIntakeStalled / TipIntakeRecovered during 04:00-20:00 ET. Today 26 market-hours messages first arrived after the close." },
      { tag: "fixed", text: "Integrity incidents (EOD-02): the geometry plan carries a typed review class (evidence | budget | plan); only unavailable-evidence failures count toward a repeated-failure incident, the real producer texts ('missing delta', '301s old') are recognised, and one book's failures never trip another's counter. The four false-positive incidents were released on the day's bound validations." },
      { tag: "fixed", text: "Rulebook governance (EOD-03): a rule the analyst writes under propose-only maintenance is a PROPOSAL - born pending review, never superseding a live rule, rendered as 'PENDING REVIEW, not policy' in every run. Three retro-promoted hypotheses from today were quarantined for review." },
      { tag: "improved", text: "Delivery and protection isolation (EOD-04): simulator fill handling runs on its own bounded queue off the quote-to-bars path, and the position watchdog runs each position as its own step so one blocked position never stalls another's protective retry." },
      { tag: "fixed", text: "Practice execution realism (EOD-05): an option order in the simulator rests until an eligible session (09:30-16:00 ET on a trading day) instead of filling at 04:01 ET on an underlying quote; test suites keep the old behaviour explicitly." },
      { tag: "fixed", text: "Evidence identities (EOD-06): a share plan records the quote source, age and delayed flag its incident classifier requires; an execution on one of the incident's own orders is bound by that relationship, not by comparing an option contract with its underlying symbol." },
      { tag: "fixed", text: "Scheduler: each job runs as its own task and shutdown is bounded (10 s) - a stuck nightly job no longer blocks other jobs' ticks or holds a restart hostage (the after-hours test teardowns were hanging on exactly that)." },
      { tag: "improved", text: "Restart readiness (EOD-07) counts running Tips work (appraisals, intake reviews, retros, digests, rule audits) alongside EM's; stale rows are reported separately. Research quarantine (EOD-09): a corrupted shadow book can be flagged (POST /api/portfolios/{id}/quarantine) and is excluded from source trust and lane grading until reconciled; the rule audit records finished_at (EOD-08)." },
      { tag: "new", text: "Tips experiments (KFIN-09): a FROZEN knowledge comparison (an immutable case bundle - message, the tool outputs the run saw, rules/notes with ids + revisions, model + settings, the exact context manifest - replayed under current / core-only / no-knowledge variants with every write isolated: tool calls are served from the bundle or refused, notes the model wants to save are captured, never written) and an ENTRY-VARIANT COHORT that records EVERY eligible open/add idea at its decision (proposals, blocked cards, declines, arms, skips, shadows, parks, failures) with separate post/receipt/decision times, exact instruments, the source premium and the decision-time quote; immediate / delayed / 1.05x-cap entries are simulated into separate result books under identical budget, fees and fill assumptions. Reports separate adequate from insufficient evidence and never claim a P&L. All knobs are off by default (techniques.tip.frozen_capture_context, techniques.tip.entry_cohort_enabled); CLIs: zargar.tools.tip_frozen, zargar.tools.tip_entry_cohort." },
    ],
  },
  {version:"0.7.76",date:"2026-09-14",title:"A refusal survives a restart, an add obeys the cutoff, a correction never backdates an order",items:[
    {tag:"fixed",text:"Team2 R1: the list of fires the book never held (refused, deferred, stale, rejected, cancelled unfilled, sizing) now rides every ordinary save of the armed plan, is restored before the first read after a restart, and is rebuilt from the journaled contract verdicts. Before this a restart could bring the modelled position of a refused contract back. Orders with an unknown acknowledgement and partial fills are never exempted."},
    {tag:"fixed",text:"Team2 R2: one entry gate at the order boundary for every money path - initial entries, trim-and-add orders riding a cached contract, and the collar re-price retry - judged on the wall clock after quoting, review and sizing. A synthetic 15:28 add delivered at 15:32 used to reach the order boundary; adds are also judged at their origin like fires."},
    {tag:"fixed",text:"Team2 R3: a decision watermark per plan - a fire, add, trim or exit whose close is at or before the last decision was surfaced by a corrected or late minute and is recorded (backdated_signal_skip, with the time it was judged and the time it surfaced), never sent as a backdated order; a setup the current close creates still acts. Corrections and recovered minutes are now journaled durably (bar_revised / bar_recovered)."},
    {tag:"improved",text:"Team2 R5: the close funnel builds its attempts from the durable contract verdicts and joins the trade projection to them, so a verdict journaled before the projection was saved is reported as journal-only evidence with its own row instead of vanishing; opportunities and retries are counted separately (verdicts / journalOnly)."},
  ]},
  {
    version: "0.7.75",
    date: "2026-09-14",
    title: "The Ledger and the Dashboard agree on today",
    items: [
      { tag: "fixed", text: "The Ledger's TODAY tile is now the same number as the Dashboard: how the book moved today against the previous session's close. What CLOSED today is its sub-line, with the remainder labelled 'open & carried' - the Ledger's day rows book a trade's whole gain on the day it closes, so a position that lost $210 over four days and closed today reads -210 there and only today's slice on the Dashboard. The two screens read +429.97 and +145.07 for the same day; both were right, and neither said which question it was answering." },
      { tag: "fixed", text: "The Ledger values an open position exactly as the book does. It marked at the last print while the book (since 0.7.70) marks an option at the mid of its market, and the gap - (mid minus last) times the contracts, across three open lots - surfaced as a '+4.00 unexplained' pill. Same mark, no gap." },
    ],
  },
  {version:"0.7.74",date:"2026-09-14",title:"Recover preparation and reconcile daily results",items:[
    {tag:"fixed",text:"Partial Cartel preparation retries unresolved history with bounded recovery, preserving successful analyses, existing arms and immutable plan revisions."},
    {tag:"fixed",text:"Simulated fills require fresh eligible quotes and retain exact source evidence. Protective orders keep waiting for usable quotes rather than claiming stale fills."},
    {tag:"improved",text:"Cartel daily review separates trades, fills, fees and remaining holdings, with candidate attempts and durable quote coverage. Archived account history remains available."},
    {tag:"improved",text:"Deployment ownership is serialized across teams; bar delivery measurements distinguish queue delays from missing history."},
  ]},
  {version:"0.7.73",date:"2026-09-14",title:"A refused contract is not a loss, a late signal is not an order",items:[
    {tag:"fixed",text:"Team2 R1: the Practice book's two-loss allowance now counts only filled, closed losers. A contract the live picker refused or deferred is no longer a modelled loss against the desk, and the read no longer keeps a proxy position for a fire the book never held - the next pullback is a new candidate. Today IWM's single refused attempt had charged one of the two allowances."},
    {tag:"fixed",text:"Team2 R2: a fire is judged on the wall clock before any order chain starts and again after the quotes come back - outside its session, past the 15:30 cutoff, or older than three minutes it is recorded as a stale signal with source and decision times and never sent. A synthetic 15:28 signal delivered at 15:32 used to reach the order boundary."},
    {tag:"fixed",text:"Team2 R3: a corrected or late-recovered minute is now merged into the desk's private tape by timestamp and recorded (bar_revised / bar_recovered) instead of being dropped because a later minute had already been seen; the next read runs on the corrected history without re-acting on anything already acted on."},
    {tag:"fixed",text:"Restart scripts R4: a deploy takes an exclusive lease (logs/deploy.lock, owner-named, stale after ten minutes), the entry pause must be acknowledged by the engine AND read back from its state before anything is stopped, and the watchdog will not start a second engine while a deploy holds the lease. A pause that is not confirmed refuses the ordinary restart; -Force / -Override remain the journaled exceptions."},
    {tag:"improved",text:"Team2 R5: the close scorecard keeps every attempt, filled or not, with its decisive contract verdict (policy refusal, transient deferral, order rejected) and the live price examined, and adds a durable funnel (attempts / filled / refused / deferred / book losses) rebuilt from the journal after a restart. Today's refused IWM 290 call read 'not taken - see skips' with no reason."},
  ]},
  {version:"0.7.72",date:"2026-09-14",title:"Team2 close record",items:[
    {tag:"fixed",text:"Team2: the end-of-day scorecard now names its session (planFor), so the close no longer logs an event-contract warning per plan and scored rows can be joined to their day without the plan row."},
  ]},
  {version:"0.7.71",date:"2026-09-14",title:"Clear, focused plan review",items:[
    {tag:"fixed",text:"EM review second follow-up (FA-01..05): a synchronous final guard runs right before the broker submit on every entry attempt, so a daily-loss budget that moves while the order is being persisted refuses the order; the FIX-01 repair writes state and receipts in one transaction, grounds values in the execution ledger and refuses ownership mismatches; a promotion reuses a prior read only under the same saved definition; /api/health.build is bound at launch."},
    {tag:"fixed",text:"EM review follow-up (DA-01..08): option entries pass one final admission on the price and quantity actually sent (fresh spread, premium caps, remaining daily loss budget); a pending or cancelled exit can no longer consume a target; quote-stop confirmation is forward-only; the FIX-01 repair tool journals its receipt before it commits and applies a plan's corrections as one transition; per-desk sizing-floor setting registered; /api/health reports the build SHA."},
    {tag:"fixed",text:"EM review Delivery A: a shares fallback no longer keeps the option's x100 (HPQ booked -$719 on a -$7 trade and false-halted; repair tool with a dry-run manifest); a two-contract exit takes TP2 in the bar it prints with TP1; contracts are sized on the live ask, and a contract that does not fit the risk budget sizes to zero instead of one; the 09:25 pre-open judges shorts with the same direction-aware rule as the open (twelve shorts were wrongly replaced on 09-14); the critic's opinion, advisory flag and errors survive a restart and every fire journals its final disposition; short setups score as shorts; a cached option quote cannot confirm a premium stop twice."},
    {tag:"improved",text:"The top-bar review indicator opens only flagged plans, with every stock, technique and account named. Blocked entries are distinguished from position or execution problems, with clear next steps."},
    {tag:"fixed",text:"Setup messages show entry descriptions and prices instead of bare IDs. Fixed the visible Unicode escape and replaced the pulsing red attention banner with a quieter, accessible control."},
    {tag:"improved",text:"Team2: a pre-market break setup pointing against the day's bias now says so on the Armed page (\"inert while the bias is puts: needs a bias flip\") instead of reading like a live entry candidate."},
  ]},
  {
    version: "0.7.70",
    date: "2026-09-14",
    title: "The board tells the truth about today, and keeps telling it",
    items: [
      { tag: "fixed", text: "Today's move on the Dashboard is read from the day's real opening equity - the previous session's close, the same basis every broker quotes a day change on - instead of being derived from the chart's own points, which are session-filtered, thinned and flat-collapsed. The baseline was whichever sample survived thinning, so it changed on every reload: a board opened during a dip read RED all morning on a green day and went green on a refresh. The headline and the chart now read the same two numbers." },
      { tag: "improved", text: "The Dashboard follows the live equity push instead of freezing at page load. Equity is sent for every book every 30 seconds; nothing was keeping those samples, so the balance updated over the websocket while the move and the curve beside it stayed pinned to whatever was fetched on mount - which is why the numbers only changed when you reloaded. The curve now extends itself, and says 'live' when it is doing so." },
      { tag: "improved", text: "The equity chart carries its numbers on its face: six labelled gridlines instead of two, the previous close drawn as a reference line, the current value labelled on the line itself, and a PREV CLOSE / HIGH / LOW / NOW strip underneath. The readings are there without hovering." },
      { tag: "fixed", text: "Downsampling a long equity window no longer throws away its highs and lows. Keeping every Nth sample meant the same 1D window reported a 40,120 high on one load and 38,898 on the next, depending on where the buckets fell; buckets now keep their extremes, so the shape and the range survive at any budget." },
      { tag: "fixed", text: "An option position is valued at the middle of its two-sided market rather than a lone print. Two INTC 0DTE calls bought at $1.00 were marked near $7 by a single print this morning: equity jumped $1,406 (+14%) for one sample, that spike was written into the book's history permanently, and it set the whole vertical range of the day's chart. The same figure feeds the daily-loss halt, where a bad print the other way would halt a book that had not lost anything." },
      { tag: "fixed", text: "The day's opening equity survives a restart. It was held only in memory and seeded with 'equity the first time we looked today', so an engine restarted mid-session re-based the day at the restart price - a book already down 4% came back reading flat and the daily-loss halt forgot how far down it was." },
    ],
  },
  {
    version: "0.7.69",
    date: "2026-09-14",
    title: "An integrity incident needs a failing path, not a card that does not fit",
    items: [
      { tag: "fixed", text: "Tips integrity pause: only SYSTEMIC pre-entry failures (bars, quote, greeks or provider evidence unavailable) count toward a repeated-failure incident; a card that is review-gated on its own merits (the risk budget fits no unit, the plan has no stop, an unsupported vehicle) never pauses the book. The first enforce session opened two incidents at 09:22/09:36 ET from three analyst-skipped option cards whose whole debit exceeded the $88 budget - a false positive that paused Practice proposals." },
      { tag: "fixed", text: "One repeated-failure incident per entry path, book and session: further failures extend it (evidence + revision) instead of opening a duplicate." },
    ],
  },
  {
    version: "0.7.68",
    date: "2026-09-14",
    title: "A scaled-in position closes flat, once",
    items: [
      { tag: "fixed", text: "Managed positions: an exit fill is now applied across every leg of the same symbol toward flat and never past zero. Before, a scaled-in position (two legs of one ticker) had the second leg's stop fill applied to the first, already-flat leg, flipping it back open - the stop re-fired on every tick (APLD in a research shadow book, pre-market 2026-09-14: 3,282 exits, 37,625 shares short before the pre-open check caught it). No real or Practice money was involved." },
      { tag: "fixed", text: "A reduce-only exit never sells what the venue does not hold: when the book already shows the symbol flat or on the other side, the stale leg is marked flat and the record closes on attention instead of looping; an unknown venue line never blocks a protective exit." },
    ],
  },
  {
    version: "0.7.67",
    date: "2026-09-14",
    title: "Tips: geometry before entry, and an integrity pause instead of a clock",
    items: [
      { tag: "major", text: "Pre-entry geometry (Practice books only, knob techniques.tip.geometry_gate): a tip's stop is finalized BEFORE the order and the size is derived from that stop against the approved risk budget (risk_pct of equity, or a fixed per-tip budget). Shares are sized at the executable limit; options need a fresh delta, a fresh non-delayed underlying reference and explicit contract metadata - anything missing is review-gated (a person decides), never guessed. The same plan is recomputed at submission; a card that fails there is returned to pending, no order." },
      { tag: "major", text: "Execution-integrity pause (knob techniques.tip.entry_pause_mode): automated tip entries are paused by evidence of a broken execution path - a filled trade outside its plan, an exit on unconfirmed or delayed evidence, duplicate or unreconciled fills, a repeatedly failing entry path - not by a fast loss on a clean trade. Incidents are rows (they survive restarts), pause every automated path including already-armed plans and retries, never touch exits, and release only on evidence bound to the incident (or an explicit, labeled override). A valid fast loss is a diagnostic; the daily loss limits are unchanged." },
      { tag: "improved", text: "Post-fill stop changes may only tighten immediately; a widen is a trim-first sequence with the tight stop armed until the trim is confirmed and the residual re-checked, durable before it is exposed, and it resumes safely after a restart." },
      { tag: "fixed", text: "A confirmed premium stop now records the two observations that confirmed it on the exit; risk accounting distinguishes the executed plan from a hypothetical shadow plan; note scopes gain evidence:<family> for case records that are searchable but never injected into a run." },
    ],
  },
  {
    version: "0.7.66",
    date: "2026-09-13",
    title: "A new rule is classified in the same commit it is inserted",
    items: [
      { tag: "fixed", text: "Saving a rule that conflicts with a disputed rule of the same family now classifies it (staged as disputed) in the same database transaction that inserts it. Before, the insert committed first and the classification ran after the notification - a failed notification could leave a conflicting rule active and unflagged. The returned note reflects its final committed state." },
    ],
  },
  {
    version: "0.7.65",
    date: "2026-09-13",
    title: "Disputes hold against every writer, audits finish their cycle",
    items: [
      { tag: "fixed", text: "A disputed rule can no longer be replaced by an ordinary analyst or retro note through rule-family matching: the original stays active and disputed, and the conflicting newcomer is staged as disputed too - nothing contradictory enters the rulebook as uncontested advice until you decide." },
      { tag: "fixed", text: "Deleting an already-replaced note keeps its replacement link and mints a revision like every other change, so history read at an earlier moment still shows the real replacement, not 'deleted'." },
      { tag: "fixed", text: "The knowledge audit now runs as a persisted cycle: it audits only what is still pending, a group that fails is retried with backoff (three attempts, then set aside visibly) instead of holding every other group out, and the cycle completes once everything was covered - so propose-only maintenance no longer pays for the same rulebook and groups every day." },
      { tag: "fixed", text: "A failed audit reply keeps its paid-call usage on the run record (tokens, stop reason, latency per call), and a reply cut off at its output cap gets its one bounded retry even when it had started an object." },
      { tag: "new", text: "Truncation restoration prepared, not applied: a tool builds the exact manifest for the 19 notes whose full text survives in their run traces (full ids, current revisions, evidence hashes, the added text for review); applying it later is a revision transition gated on that manifest's hash." },
    ],
  },
  {version:"0.7.64",date:"2026-09-13",title:"Cartel entry integrity and Practice evidence",items:[
    {tag:"fixed",text:"Cartel: saved contract limits are checked again immediately before entry. Pending plans retain invalidation during slow lookups, and nearer confirmed targets cannot disappear behind optimistic fallback targets."},
    {tag:"improved",text:"Cartel: explicitly review older unused Practice arms, choose reachable first trims for new 2–3-contract campaigns, and replay the actual position size. Existing campaigns keep their saved exit policy."},
    {tag:"improved",text:"Cartel research: deduplicated option quotes and gap records support long campaign valuation; dated leadership context and policy cohorts support prospective comparisons. History cache reuse now respects provider changes."},
  ]},
  {
    version: "0.7.63",
    date: "2026-09-13",
    title: "Knowledge maintenance goes propose-only",
    items: [
      { tag: "fixed", text: "Knowledge maintenance is PROPOSE-ONLY by default: the audit's merges and expiries are recorded as proposals (Knowledge tab, 'Audit proposals') and touch no live note until apply is switched on. Contradiction flags still land - they only protect. The automatic audit had already applied one merge after the last release; the applied path is now off." },
      { tag: "fixed", text: "An audit can no longer act on a note that changed after it was read: every batch carries the revision numbers it judged and aborts whole on any mismatch; a batch whose receipt committed but whose journal write failed replays as already-applied instead of superseding twice; a note flagged as disputed stays untouched by every later audit until you resolve it." },
      { tag: "fixed", text: "Historical (as-of) reads no longer present an unversioned legacy note's current text as old knowledge - such notes are excluded and counted as unavailable; legacy notes get an observation-time baseline at boot; deleting a note leaves a tombstone so history stays readable." },
      { tag: "fixed", text: "The knowledge audit visits groups least-recently-audited first (ticker groups had been starving behind source groups), a run with failed groups is recorded as partial, an all-skipped maintenance tick is 'skipped' rather than 'done', and every audit reply is measured per call with one larger retry when the reply hit its output cap before any JSON (the first live rule audit came back empty)." },
      { tag: "new", text: "Notes carry a dispute button (journaled) and show supplied vs relied-on counts on the card itself; the analyst records 'supplied' before its first model call and 'relied on' separately after the verdict, for intake reviews too." },
      { tag: "fixed", text: "Outcome census: every buy fill in scope is inventory even when its order predates the report window - an unknown-owner lot consumes FIFO and is reported as such instead of shifting a sale onto a newer idea." },
    ],
  },
  {
    version: "0.7.62",
    date: "2026-09-13",
    title: "Knowledge that keeps its history, audits that can't merge a contradiction",
    items: [
      { tag: "fixed", text: "The weekly knowledge audit finally has its own schedule (daily job, weekends included) - it had been chained inside a weekday-only job, so its Saturday default never ran. Every tick now records skipped / done / partial / failed, with catch-up when a week is missed." },
      { tag: "fixed", text: "Audit consolidation is validated before anything is written: two notes the audit calls contradictory can no longer be merged or expired in the same breath; the batch applies in one transaction, exactly once, and a concurrent edit aborts it cleanly." },
      { tag: "new", text: "Every knowledge note keeps immutable revisions: a historical (as-of) read shows what was actually known then, and a later edit, pin, renewal or supersession can no longer rewrite the past. Pre-existing history that cannot be recovered is labeled unavailable, never backdated." },
      { tag: "fixed", text: "Note scopes are validated on every write path (an empty 'ticker:' can no longer be stored as an unreachable orphan) and note text is never silently truncated." },
      { tag: "improved", text: "Knowledge tab searches the whole store server-side with a real total and 'load more'; the analyst's rulebook selection is deterministic (pinned rules are core and always supplied, with the selection recorded on every run); hover shows supplied vs relied-on counts honestly." },
      { tag: "fixed", text: "Outcome census: fees are reported as paid / allocated-to-realized / open-lot separately, every in-scope sale is examined (a sale without a recognized lot is a visible exception, never a vanished one), and the report states its portfolio scope." },
    ],
  },
  {version:"0.7.61",date:"2026-09-13",title:"Entry selection restored for zone and pre-market setups",items:[
    {tag:"fixed",text:"Team2: v0.7.60's nearest-anchor tie-break was applied to every setup, so on a day where a zone break and a pre-market break confirmed on the same 15-minute bar the desk could pick a different setup than before - the reviewers' before/after test showed two fires where the previous build had none, with the research knob off. The tie-break now applies only among key-level setups (the research feature, still off); zone and pre-market selection is the previous rule byte-for-byte. The regression is in the suite verbatim."},
    {tag:"improved",text:"Team2 research: every sweep row says whether the inputs for key levels existed, and a paired-comparison helper drops such symbol-sessions from every variant at once, so a missing-data cell is never counted as an evaluated no-effect observation."},
  ]},
  {version:"0.7.60",date:"2026-09-13",title:"Key-level research fixes from review, still off",items:[
    {tag:"fixed",text:"Team2 research (C2, knob still OFF): two key levels breaking on the same 15-minute bar are now two setups (the setup id carries the level), the entry precedence among same-bar setups is the nearest confirmed anchor, a level cluster has a hard maximum width instead of a running-median test that could chain across several ATRs, and a plan without the specified 2-minute ATR input reports insufficient data instead of using a scaled fallback. The reviewers' two reproduction tests are in the suite verbatim. No change to the live path."},
  ]},
  {
    version: "0.7.59",
    date: "2026-09-13",
    title: "Every sale counted once, every lot keeps its basis",
    items: [
      { tag: "fixed", text: "The outcome census is a real FIFO lot engine now: a shared exit is allocated exactly once across the ideas that own the shares, and a re-entry can never rewrite an earlier episode's realized basis. Oversold or pre-lot sales are reported as unallocated, never invented. Still reconciles to the ledger to the penny." },
    ],
  },
  {version:"0.7.58",date:"2026-09-13",title:"Key-level definitions built, switched off",items:[
    {tag:"improved",text:"Team2 research (C2): the three multi-day key-level definitions from the frozen spec exist in code behind the knob key_levels (off | D1 | D2 | D3), with the causal flip/expiry state machine, the 17:00 zone mask and the 09:25/09:30 pre-market mask, the key-level break as a scenario confirmation, the retest entry only after a confirmed flip, key levels as extra target rungs, and a per-plan funnel in the sweep. The knob is OFF and stays off: a test proves the live read is byte-identical. Sweeps wait for the canonical tape (C6)."},
  ]},
  {
    version: "0.7.57",
    date: "2026-09-13",
    title: "A healthy print clears the alarm, and the books balance",
    items: [
      { tag: "fixed", text: "A healthy fresh quote seen by the bar path now clears a pending premium-stop sighting from the tick path - two isolated bad prints separated by a healthy one can no longer pair into an exit." },
      { tag: "fixed", text: "The outcome census attributes sales by book and holding episode (another portfolio's sale can no longer mark an open position as closed-profitable), includes partial realizations with proportionally allocated entry fees, and reconciles to the ledger to the penny." },
    ],
  },
  {version:"0.7.56",date:"2026-09-13",title:"Cartel documentation brought current",items:[
    {tag:"improved",text:"The Method library now explains current preparation, recovery, data quality, ignition research and the optional Practice pilot. Superseded milestones are archived, and implemented features are separated from remaining validation work."},
  ]},
  {
    version: "0.7.55",
    date: "2026-09-13",
    title: "Confirmation means new evidence, on every path",
    items: [
      { tag: "fixed", text: "A bar-close evaluation can no longer exit on the very option flash quote the tick path is holding for confirmation: premium stops share ONE evidence state across both paths, keyed by the full per-leg observation set." },
      { tag: "fixed", text: "An out-of-order quote (an older packet arriving late) never confirms a premium stop - confirmation requires strictly forward-ordered fresh evidence; a leg-set change restarts the sighting; the state dies with the position." },
      { tag: "new", text: "First idea-level outcome census (tools/tip_outcomes.py): source x DTE-bucket table with net results, fees, no-fills and missed executions kept separate - the ground truth for deciding where an edge actually exists." },
    ],
  },
  {
    version: "0.7.54",
    date: "2026-09-13",
    title: "One flash print is not a reason to sell",
    items: [
      { tag: "fixed", text: "A tick-path premium stop (bleed stop or ratchet floor) now needs two DISTINCT fresh quotes inside a 45-second window before it market-exits - re-reading the same cached quote never counts, recovery resets the count, and a real fast decline still confirms within seconds. DAL was dumped on a single anomalous print that vanished one second later." },
      { tag: "improved", text: "Analyst runs record each turn's input-token contribution, so context-size decisions rest on the per-turn shape rather than a summed total." },
    ],
  },
  {version:"0.7.53",date:"2026-09-13",title:"Research knobs for the no-trade zone, all off",items:[
    {tag:"improved",text:"Team2 research (other team's review of the week-37 plan): three knobs exist and are OFF - no_trade_zone (pm_range today | conjunction: risk off only inside both the pre-market and prior-day ranges), pm_room_atr (refuse an in-range entry with too little room to the pre-market edge) and min_target_atr (refuse a target too near to pay for the trade). Nothing in the live read changes until the user flips one; the sweep can now run the variants with the same code the desk runs. The read journals skip_pm_room and skip_target_near when they are on."},
  ]},
  {version:"0.7.52",date:"2026-09-12",title:"Keep developing ignition setups in focus",items:[
    {tag:"fixed",text:"Ignition research now hides retired theses by default, prioritizes ready setups, and explains developing, invalidated and expired states accurately. The watchlist is collapsed below preparation progress and displays 25 rows at a time."},
  ]},
  {version:"0.7.51",date:"2026-09-12",title:"Cartel ignition research and reliable preparation",items:[
    {tag:"new",text:"A persistent ignition watchlist follows strong volume events into quiet consolidation. A separately selectable Practice pilot evaluates post-ignition setups using fresh closed-bar execution plans."},
    {tag:"fixed",text:"New plans can require verified exchange bars. Recovery preserves source information, upgrades sampled context and never replays missed entries. Daily history is cached durably with native batch collection where configured."},
    {tag:"improved",text:"Preparation can recover interrupted work automatically. Settings expose coverage policy, data quality and the pilot; plans show rejected contracts and whole-contract exit allocations. Existing positions remain managed."},
  ]},
  {
    version: "0.7.50",
    date: "2026-09-12",
    title: "Captions count as evidence, and truncated answers get room to finish",
    items: [
    {tag:"new",text:"EM method change plan C1-C5 (2026-09-12): a nightly option-liquidity screen decides which names EM may trade in options (the rest fall back to shares in Practice - C2 makes shares the EM Practice default); a wide spread on the just-OTM strike now tries the next strike and the next expiry; a pre-open re-plan keeps the evening triggers alongside the new ones (IBIT +4.8R was lost to a re-plan on 09-11); gap-day policy, targeted scratch and consolidation-break entries ship as knobs, off until their sweeps pass."},
      { tag: "fixed", text: "A tip whose message has both a caption and a screenshot no longer loses the caption from the evidence: grounding now checks quotes against BOTH, clearly sectioned, with an honest note when only the first of several images was read. Meet Kevin's first tips died on exactly this." },
      { tag: "fixed", text: "When the analyst's answer is cut off at the output-token limit, the retry now gets double the room instead of being cut off at the same place - and a still-truncated failure says 'truncated', not just 'no JSON'. The RKLB no-verdict case was this." },
      { tag: "improved", text: "Ingest records how many attachments a message carried so partially-read messages are visible instead of silently incomplete." },
    ],
  },
  {version:"0.7.49",date:"2026-09-11",title:"The morning's target change is on the record",items:[
    {tag:"fixed",text:"Team2: when the morning re-derives a plan target the gap has already run through, and when the day type is finalized on the real 09:30 open, both are now written to the plan's append-only audit. Until now they existed only in the plan's in-memory event list, so a mid-session restart erased the evidence that the target had moved before any entry was judged."},
    {tag:"fixed",text:"Team2: plan-level audit rows (chain listing, warm-up identity, open finalize, target re-derive) now state that they belong to no single trigger instead of omitting the field, which was logging a contract warning on every one."},
  ]},
  {version:"0.7.48",date:"2026-09-10",title:"A hole in the audit record is itself recorded",items:[
    {tag:"fixed",text:"Team2: when an audit-trail write fails, the plan now logs a trail gap, raises one warning per plan and shows the gaps on its snapshot, so an incomplete record can never pass for a quiet session. The trade itself is not blocked by the record. The contract picker's early exits (options service missing, no expiry listed, an unexpected error) now write a deferred verdict instead of returning silently."},
  ]},
  {
    version: "0.7.47",
    date: "2026-09-10",
    title: "A retry that actually looks again",
    items: [
      { tag: "fixed", text: "The stale-quote entry retry now requests a genuinely fresh observation for the exact contract (the cached reprice path could resubmit against the very quote that was rejected), and it fires only for automatic Practice entries - a human's click is a human's decision." },
      { tag: "fixed", text: "The tick-path premium stop now judges the quote's SOURCE age, like the bar path - an hour-old bid re-received a second ago can no longer force a market exit - and tick exits carry their mark evidence too." },
      { tag: "fixed", text: "The Ledger no longer borrows an exit explanation from another book: reasons attach only within the same portfolio, and a cross-book match says 'reason unmatched' instead of guessing." },
      { tag: "improved", text: "The entry-quality study labels its data honestly: the source's stated premium and the proposal limit are separate fields, samples are decision-time (not alert-time), and each study writes durable created/delayed records." },
    ],
  },
  {version:"0.7.46",date:"2026-09-10",title:"Every step from candidate to fill is on the record",items:[
    {tag:"improved",text:"Team2 cohort v2: the chain listing, the warm-up identity, a model-out-of-band read and every contract verdict (picked, deferred, refused) with the full list of contracts quoted are now written to the plan's append-only audit, joining the order, fill and exit records already there. Before this they lived only in the plan's in-memory event list, which is capped and lost on a crash."},
    {tag:"improved",text:"User decisions recorded: fresh quotes stay mandatory for a contract, near-ITM eligibility stays unchanged, the twenty-session review counts cohort v2 sessions only."},
  ]},
  {version:"0.7.45",date:"2026-09-10",title:"Live quotes are the only authority on a contract",items:[
    {tag:"fixed",text:"Team2 F108: on the live path the premium model no longer vetoes a contract. When nothing models inside the band the read still fires, carries the nearest listed out-of-the-money strike as its proxy and says 'model out of band'; the live picker then decides on fresh executable quotes. Sweeps and history keep the model as their gate and say so."},
    {tag:"fixed",text:"Team2 F108: the picker reads no delayed price at all. It walks the listed out-of-the-money contracts nearest the underlying, quotes each one live, and stops early only when a live ask is already under the floor. A contract with no live quote is never eligible: the entry is deferred, not priced off the delayed chain (opt-out knob require_fresh_quote). When the quote bound is reached with contracts unexamined the entry is deferred, never declared 'no contract'."},
    {tag:"fixed",text:"Team2 F99: the warm-up identity is now stamped after the fallback history fetch, so it describes the bars the read actually consumed."},
  ]},
  {
    version: "0.7.44",
    date: "2026-09-10",
    title: "Exits on real evidence, entries with one honest retry",
    items: [
      { tag: "fixed", text: "A premium stop can no longer fire on a stale or delayed option mark: SPCX was closed for a phantom 54% bleed while the exit itself filled 4% under entry. Premium exits now require a fresh real-time quote and name their evidence." },
      { tag: "new", text: "A Tips entry rejected only for quote staleness gets exactly one recovery: refresh the contract's quote, never raise the limit, re-run every risk gate. The 10:53 AAPL take died on a 10.5-second-old quote with no second look." },
      { tag: "fixed", text: "A filled-but-venue-rounded exit (2.5 contracts filled as 2) no longer strands a phantom remainder that blocks the position from ever getting flat." },
      { tag: "fixed", text: "The nightly 'unfilled tips' retro no longer teaches lessons from trades that actually filled and lost - an expired signal with a real fill in any book now goes to the closed-position retro instead." },
      { tag: "new", text: "Entry-quality study: every option proposal records the contract's real quotes at alert time and three minutes later (journal only) - the dataset for deciding source-premium caps and delayed entries on evidence, not anecdotes." },
    ],
  },
  {version:"0.7.43",date:"2026-09-10",title:"The desk prices the contracts that are listed, on the quotes that fill",items:[
    {tag:"fixed",text:"Team2 F104: the premium gate now walks the venue's LISTED strikes. At the first bar of the session the desk reads today's chain listing and stamps it on the plan; the read prices those contracts instead of a synthetic $1 grid, and every fire or refusal says which ladder it walked. On 2026-09-10 the grid tested IWM's 287 put at $0.11 and never the listed 287.5 put at $0.21, refusing ten in-band pullbacks. History still walks the grid and says so - there is no as-of listing for past sessions."},
    {tag:"fixed",text:"Team2 F105: a delayed chain ask never refuses a contract on its own. The nearest listed contracts are re-priced on the live NBBO before the premium band is judged, the band is judged on what would fill, and a refusal names every contract it examined with both prices and which series spoke. Same minute, same contract, CBOE said $0.19 and OPRA said $0.20 at a $0.20 floor."},
    {tag:"fixed",text:"Team2 F99: live, replay and the sweep now seed their EMAs from the same warm-up - the last twelve valid sessions - and the plan carries that slice's content hash, so a replay states whether it matched the desk's warm-up instead of silently running on a different depth (live took ~6 sessions, replay 12, sweep 12 dates)."},
    {tag:"fixed",text:"F107: the EM outcome scorer scores EM's own runs only; it had been adopting every Team2 and Tip plan run into EM's scorecard."},
  ]},
  {version:"0.7.43",date:"2026-09-10",title:"The desk prices the contracts that are listed, on the quotes that fill",items:[
    {tag:"fixed",text:"Team2 F104: the premium gate now walks the venue's LISTED strikes. At the first bar of the session the desk reads today's chain listing and stamps it on the plan; the read prices those contracts instead of a synthetic $1 grid, and every fire or refusal says which ladder it walked. On 2026-09-10 the grid tested IWM's 287 put at $0.11 and never the listed 287.5 put at $0.21, refusing ten in-band pullbacks. History still walks the grid and says so - there is no as-of listing for past sessions."},
    {tag:"fixed",text:"Team2 F105: a delayed chain ask never refuses a contract on its own. The nearest listed contracts are re-priced on the live NBBO before the premium band is judged, the band is judged on what would fill, and a refusal names every contract it examined with both prices and which series spoke. Same minute, same contract, CBOE said $0.19 and OPRA said $0.20 at a $0.20 floor."},
    {tag:"fixed",text:"Team2 F99: live, replay and the sweep now seed their EMAs from the same warm-up - the last twelve valid sessions - and the plan carries that slice's content hash, so a replay states whether it matched the desk's warm-up instead of silently running on a different depth (live took ~6 sessions, replay 12, sweep 12 dates)."},
    {tag:"fixed",text:"F107: the EM outcome scorer scores EM's own runs only; it had been adopting every Team2 and Tip plan run into EM's scorecard."},
  ]},
  {version:"0.7.42",date:"2026-09-10",title:"Safer Cartel preparation and executable reserves",items:[
    {tag:"new",text:"EM scratch rule (T-14, off until its sweep passes): once a trade is scratch_r R in favour, half is sold and the stop moves to breakeven, in the simulator and in the live exits alike (technique.scratch_r / scratch_trim). HOOD today: +2.5R in four minutes, then stopped for a full loss."},
    {tag:"fixed",text:"Refreshing preparation preserves existing arms and positions, including when research fails. Pending contracts no longer consume the final armed shortlist; additional ranked candidates are checked within a bounded reserve."},
    {tag:"fixed",text:"Stale benchmark history is retried once and reports its actual completed session. Fresh preparation is required when benchmark data remains stale; trading checks are unchanged."},
  ]},
  {version:"0.7.41",date:"2026-09-10",title:"The 15:45 flatten says it ran",items:[
    {tag:"improved",text:"Team2 F106: the 15:45 flatten now writes one line when the clock reaches it, saying what it found - how many open trades it is closing, how many working entries it is cancelling, or that the book is already flat. Before this it logged only per trade, so on a day the desk ended flat, a flatten that ran correctly and a flatten that never ran left exactly the same record: nothing. Today all three symbols finished flat and the 15:45 pass was invisible."},
  ]},
  {version:"0.7.40",date:"2026-09-10",title:"A refused strike names the strike it tried",items:[
    {tag:"improved",text:"Team2 F101: when no contract prices inside the $0.20-$0.90 band, the refusal now names the nearest out-of-the-money strike it modelled and that strike's price. The band is checked against a synthetic $1 strike ladder, not the venue's listed strikes, so the reason a refusal happened is now readable without pulling the chain. Today IWM refused nine entries between 13:40 and 14:02 ET on a ladder that tested the 287 put at $0.11 and never the listed 287.5 put, which was bid $0.20 / ask $0.21 with 33,000 contracts traded."},
  ]},
  {version:"0.7.39",date:"2026-09-10",title:"A refused pullback says what it really costs",items:[
    {tag:"fixed",text:"Team2 F100: a pullback refused for its location - inside the pre-market no-trade zone, or on a range day that has not cleared its level - used to say “not counted as a pullback” while the read's own pullbacks counter had already counted it. It now says what is true: the refusal does not spend the two-pullback allowance. Today QQQ reached 11 pullbacks with 0 tradeable ones, and the two numbers looked like a contradiction."},
  ]},
  {version:"0.7.38",date:"2026-09-10",title:"The desk enters the trade its read fired",items:[
    {tag:"fixed",text:"Team2 F91: when the read drops a target because no structure is left ahead of the entry, the live runner now enters that trade instead of refusing it against the old target the setup still carries. The trims, the candle stop, the premium stop and the 15:45 flatten manage it, exactly as the read simulated. Today SPY fired a 756 put at 10:06 ET and the runner refused it on a 757.90 the read had already replanned away, so the experimental gap-day target rule could never actually trade."},
  ]},
  {version:"0.7.37",date:"2026-09-10",title:"A re-derived target can come back",items:[
    {tag:"fixed",text:"Team2 F88: the gap-day target re-derivation now always measures against what the 17:00 plan said, never against its own earlier output. On plans built before the feature shipped it recovers the original target from the record the first pass left behind, so a side the 09:25 pre-market estimate wiped is restored by the 09:30 open when the real open leaves a level ahead of it. This morning IWM opened 288.48 with the 287.83 pre-market low ahead and was left with no down-target at all."},
  ]},
  {version:"0.7.36",date:"2026-09-09",title:"Cartel volume-supported entry windows",items:[
    {tag:"fixed",text:"New Practice preparation can watch only confirmation periods with valid historical volume baselines instead of requiring all 26 periods. Each usable period still needs five complete samples; missing bars are never fabricated."},
    {tag:"improved",text:"Plans show baseline coverage and supported entry windows. Unsupported periods and closing-bell confirmations cannot trigger entries. Legacy plans and Live defaults retain full-session readiness."},
  ]},
  {version:"0.7.35",date:"2026-09-09",title:"Cartel target quality and observation health",items:[
    {tag:"improved",text:"New Cartel plans apply configurable minimum target distance and entry reward/risk checks. Shortlists can rank by target room and relative strength instead of volume alone; original nearby resistance is preserved."},
    {tag:"fixed",text:"Cartel repairs overdue minute gaps with bounded history reads while preserving live decisions and suppressing missed historical entries. Records show session coverage and recovery events."},
    {tag:"new",text:"Preparation includes advisory SPY/RSP and QQQ/QQQE breadth context. Missing NYMO evidence is explicitly unavailable and never substituted or used to increase risk."},
  ]},
  {
    version: "0.7.34",
    date: "2026-09-10",
    title: "A gap day re-derives its targets at the open",
    items: [
      { tag: "new", text: "Team2 F81: when the morning's price has already run through a target the plan fixed the night before, the pre-open (09:25) and the 09:30 open re-derive it from the morning's structure - the pre-market low/high if still ahead, else the next level of the ladder, else no target - and the plan keeps what 17:00 said next to what the morning decided (journaled as targets_rederived). Yesterday every IWM and SPY pullback was refused against a stale target while the author took the pre-market-low break for +141%." },
      { tag: "improved", text: "An experimental entry-time fallback (target_replan=structure, gap days only) reproduces the author's IWM day (+114.5% modelled) but loses on the other gap days of the 14-date sample (+220 vs +248 summed); it stays off until the twenty-session review." },
    ],
  },
  {
    version: "0.7.33",
    date: "2026-09-09",
    title: "A watch-only pullback says which contact it is",
    items: [
      { tag: "fixed", text: "Past its first two pullbacks Team2 keeps watching but stops counting, so every later contact reported the same “touch #3” — one late contact read exactly like seven (IWM logged seven today). Each now states its own running number (F84)." },
    ],
  },
  {
    version: "0.7.32",
    date: "2026-09-09",
    title: "Review fixes: restart evidence, one merge policy",
    items: [
      { tag: "improved", text: "EM: the fire-time critic is advisory on at-level bounces and rejects (new knob execution.critic_mode = veto | momentum_only | advisory; EM uses momentum_only). Its verdict is still recorded on every fire; breakouts and breakdowns are still vetoed. Ten sessions with zero fills and a 25-kill tally at +0.5R made the veto not worth its cost." },
      { tag: "fixed", text: "Restart readiness now blocks on what it cannot see: an order-book failure, a fire chain still choosing its contract or awaiting review, and a missing readiness answer all refuse the restart unless overridden. The scripts suspend new entries (self-expiring) before they capture the state they compare afterwards, and the restoration check reconciles managed positions by id (a position that closed is explained, one that vanished fails)." },
      { tag: "fixed", text: "One merge policy for two venue observations of the same minute, applied identically in memory, in a flush and in the database: the newer OHLC wins, a zero volume is an incomplete observation and the known volume stands, any other newer volume (lower included) is a correction. A recovered minute that falls between existing bars is inserted, not dropped; seeding history never turns a session total into one minute's volume." },
      { tag: "fixed", text: "The bars repair names its provider and only zeroes a day's print-less minutes when Alpaca covered that day; a Yahoo fallback or a partial answer writes what it got and zeroes nothing. Quarantine locks, archives the CURRENT rows column-for-column and deletes in one transaction, so a correction that lands after selection is archived, never lost." },
      { tag: "fixed", text: "Team2 sweeps validate their warm-up sessions the way plans do and stamp the hash of the bars they actually consumed (plans do the same); a symbol with no usable history yields no plan instead of an error." },
    ],
  },
  {
    version: "0.7.31",
    date: "2026-09-09",
    title: "A refused pullback states the premium band it really used",
    items: [
      { tag: "fixed", text: "When Team2 turned a pullback away for want of a contract it said no strike priced “between $0.20 and $0.60”, but both the modelled and the live picker accept up to 1.5× the target — $0.90. The refusal now quotes the band it actually applied, and names the target beside it (F82)." },
    ],
  },
  {
    version: "0.7.30",
    date: "2026-09-09",
    title: "A setup's note states its own target",
    items: [
      { tag: "fixed", text: "Team2's pre-market break note always read “→ puts down to the PDL zone” whichever level the setup's target actually resolved to, so on a gap day it advertised room the setup does not have. It now states that setup's own number and says plainly when the break has already run through it (F76)." },
    ],
  },
  {
    version: "0.7.29",
    date: "2026-09-09",
    title: "Provisional minutes are not corrections",
    items: [
      { tag: "fixed", text: "Yahoo's poll re-sends its last 30 minutes with volume still empty for the freshest ones; with source precedence those overwrote Alpaca's true bars with volume 0 (F79). A minute without volume is provisional and is no longer handed on as an exchange bar; an exchange re-fetch never lowers a bar's volume; legacy rows with no provenance rank below live sampled bars." },
      { tag: "fixed", text: "On the Alpaca+Yahoo feed a restart seeds today's completed minutes from the venue's history at boot, so the minute that was forming when the old process died is no longer a silent hole in the 2-minute tape (F80)." },
      { tag: "fixed", text: "History requests to Alpaca are no longer clamped to Yahoo's 20-day depth (a backfill of mid-August silently started on August 20); the bars audit no longer calls an opening or closing auction print a volume spike." },
    ],
  },
  {
    version: "0.7.28",
    date: "2026-09-09",
    title: "Market data with provenance",
    items: [
      { tag: "fixed", text: "Every stored bar now says where it came from (exchange, quote-sampled, sim, or legacy unknown), and an exchange correction overwrites a sampled bar in storage instead of being ignored — the sampled bar used to survive on disk after memory had already been corrected. A sampled bar can never undo an exchange bar." },
      { tag: "fixed", text: "Bars form and persist only in market minutes on trading days: the one-price weekend and Labor Day \"sessions\" (the app ran on closed days) cannot be written again, and synthetic sim-feed bars are refused by the shared table unless a test allows them." },
      { tag: "fixed", text: "Bar volume for Alpaca-streamed symbols is a sum of print sizes; the session-to-date counter it used to difference was re-seeded from Yahoo and painted a 43-million-share minute on September 8. A counter that goes down (session roll / re-seed) is never a spike." },
      { tag: "new", text: "A bars repair tool: audit every symbol-session (closed day, one-price, outlier range, thin, volume spike), quarantine by explicit reason with the original rows preserved and verified before deletion, backfill exchange bars from Alpaca by provenance, and stamp a CONTENT-hash dataset version. Team2 plans and sweeps cite the dataset they ran on." },
      { tag: "fixed", text: "Team2 reads only valid sessions (no closed days, one-price or outlier sessions in the lookback or the EMA warm-up), counts its ten-session lookback in valid sessions, and records the sessions used and excluded on the plan." },
      { tag: "improved", text: "Restarts are coordinated app-wide: start.ps1 asks the engine what a restart would interrupt across every technique (open trades, working entries and exits, venue orders, analyst reads) and refuses unless overridden; after a detached restart it compares armed plans, open trades and orders by id with the state before (restoration check). The scheduler tasks ZargarRestart (refuses) and ZargarRestartOverride (emergency) go through the same door." },
    ],
  },
  {
    version: "0.7.27",
    date: "2026-09-09",
    title: "Ledger acknowledgments keep their exact identity",
    items: [
      { tag: "fixed", text: "An acknowledged Discord edit no longer comes back after a restart (the intake ledger's completion record now names the exact revision it completed)." },
      { tag: "fixed", text: "A repeated delivery of a message that already failed keeps its real retry count and its already-confirmed EM delivery - it can no longer reset retries or send EM a second copy." },
    ],
  },
  {
    version: "0.7.26",
    date: "2026-09-09",
    title: "Tips intake that survives crashes, and honest evidence",
    items: [
      { tag: "major", text: "Discord intake is now crash-proof end to end: every message is written to a durable ledger BEFORE processing and leaves it only after the app confirms it — a hard kill, restart, queue overflow or app outage no longer loses a tip. Edits, EM forwards and retries each confirm separately, in order." },
      { tag: "fixed", text: "A repeated delivery can never pay for a second extraction (atomic claim), and a message abandoned mid-processing by a crash is resumed instead of silently dropped." },
      { tag: "improved", text: "The analyst's evidence got honest: an exact contract's real-time quote carries its age and is labeled stale when old; bar timestamps carry the year; historical experiment runs are locked to what existed at the tip's moment (no future rules, no current-book management, closed bars only)." },
      { tag: "new", text: "Per-stage LLM cost/latency measurement (extraction, appraisals, reviews, retros, digests, audits) rolls up nightly — with retries, malformed outputs and failures counted for what they actually were." },
      { tag: "fixed", text: "Source trust ages holdings by when they actually FILLED, not when the order was placed." },
    ],
  },
  {
    version: "0.7.25",
    date: "2026-09-09",
    title: "No room means no trade, at both gates",
    items: [
      { tag: "fixed", text: "A Team2 entry whose profit target had no room left is now refused by the live runner too, not quietly entered without any target at all. An invalid target and no target are different things, and only the second one was ever allowed." },
      { tag: "new", text: "Team2 can optionally re-plan a stale target instead of refusing the trade: it picks the next structural level beyond current price and re-checks it at the entry itself. Off by default - it is there to be measured against the refusal, not adopted yet." },
    ],
  },
  {
    version: "0.7.25",
    date: "2026-09-09",
    title: "Saying \"already through\" out loud",
    items: [
      { tag: "fixed", text: "The Team2 plan line that was supposed to say a level is already broken never actually said it: the wording was keyed to a label the desk does not use, so every break setup fell back to a bare percentage. Break rows now read \"price is already through, waiting on the 15m close\"." },
    ],
  },
  {
    version: "0.7.24",
    date: "2026-09-09",
    title: "A target you have already passed is not a target",
    items: [
      { tag: "fixed", text: "Team2 no longer takes an entry whose profit target sits at or behind the entry price. A gap that opens straight through the zone leaves the planned level behind price, and because both target checks are touched checks, that trade would have closed on its first bar or its first live quote - booking a loss under a target reached label. The setup now says so instead of trading." },
    ],
  },
  {
    version: "0.7.23",
    date: "2026-09-09",
    title: "Through the level, not away from it",
    items: [
      { tag: "fixed", text: "A Team2 plan whose price had already broken through its PDH/PDL zone still read as a percentage \"away\" from it - and with the sign inverted, so a level already broken looked further off than one not reached yet. It now says the price is already through and the desk is waiting on the 15m close." },
    ],
  },
  {
    version: "0.7.22",
    date: "2026-09-09",
    title: "One finalization, not two",
    items: [
      { tag: "fixed", text: "A failed intake review finalized twice - the second write erased the run's recorded token usage and side-effect receipts. It finalizes once now, metadata intact." },
    ],
  },
  {
    version: "0.7.21",
    date: "2026-09-09",
    title: "Failure records complete",
    items: [
      { tag: "fixed", text: "Failed analyst runs and intake reviews now record the tokens they consumed and any side effects they performed - failure no longer erases the bill or the actions." },
      { tag: "fixed", text: "An intake review cancelled by a restart is marked failed immediately, and startup now reconciles every leftover running run regardless of how recently it died." },
      { tag: "fixed", text: "A disarm (or any management action) that reports it did NOT act no longer counts as a side effect on the run's record." },
    ],
  },
  {
    version: "0.7.20",
    date: "2026-09-09",
    title: "Honest failures",
    items: [
      { tag: "fixed", text: "When the analyst's answer fails to parse, the retry now continues the same conversation with all its tool evidence instead of starting over blind - the failure mode behind several no-verdict cards. A run that runs out of tool budget is told to answer, not left returning nothing." },
      { tag: "fixed", text: "Runs interrupted by a restart no longer sit labeled running forever - they are reconciled to failed at startup, and cancellation mid-run records itself." },
      { tag: "new", text: "Side-effect receipts: if a run saved a note, changed an exit, closed a position or disarmed a plan before failing, the run says exactly that - never \"nothing was asked or ordered\". Every run also records its token usage and stop reasons." },
    ],
  },
  {
    version: "0.7.19",
    date: "2026-09-08",
    title: "Audit boundary cases closed",
    items: [
      { tag: "fixed", text: "Premium-priced targets can no longer fail a tip on the stock-price ordering check (they were correctly skipped in one check but still compared in another), and the units guard works even when the quote feed is cold." },
      { tag: "fixed", text: "The nightly review census no longer skips positions that share a timestamp, and a capped scan says so instead of calling itself the full backlog." },
      { tag: "fixed", text: "The AI cannot label its own extraction as a refusal or failure - those statuses come only from the provider and the parser. Undeclared option units resolve only when the numbers fit exactly one interpretation; ambiguous stays skipped, on the record." },
      { tag: "improved", text: "The independent auditor's five boundary tests now run in the main suite (tests/test_tip_audit_acceptance.py), all green." },
    ],
  },
  {version:"0.7.18", date:"2026-09-08", title:"Moderate market alignment for Practice",
    items:[
      {tag:"new", text:"Cartel Practice Settings offer an explicit Moderate market experiment: one index above its 8/21/50 EMAs and both above their 50 EMA. Strict remains the default and Live requires strict plans."},
      {tag:"improved", text:"Preparation records the selected alignment mode. Changing the policy requires fresh preparation; a recent scan under different settings no longer suppresses the scheduled run."},
    ]},
  {
    version: "0.7.17",
    date: "2026-09-08",
    title: "The audit's first three fixes",
    items: [
      { tag: "fixed", text: "Option tips whose targets are the contract's own price (\"1.40 → 1.75\") are no longer judged against the stock's price — the units are labeled at extraction, ambiguous ones skip the check on the record instead of guessing, and premium numbers never become stock levels in an armed plan. (Codex audit finding 1.)" },
      { tag: "fixed", text: "A garbled AI extraction no longer masquerades as \"no signal here\": it is recorded as an error and retried once; a safety refusal is recorded distinctly. Silent tip loss closed. (Finding 3.)" },
      { tag: "fixed", text: "Nightly position reviews can no longer starve: eligibility is checked before the batch cap, and the response reports the true backlog and the oldest unreviewed age. (Finding 5.)" },
    ],
  },
  {
    version: "0.7.16",
    date: "2026-09-08",
    title: "Cartel scans fetch histories in parallel",
    items: [
      { tag: "improved", text: "Cartel preparation prefetches a bounded window of 25 histories with up to six concurrent fetches by default. Batch size and concurrency are adjustable in Practice and Live Settings; provider pacing and throttling protections remain." },
      { tag: "improved", text: "Progress shows active history fetches and completed prefetches. Evaluation and shortlist selection retain discovery order, and cancellation awaits pending work before saving the final state." },
    ],
  },
  {
    version: "0.7.15",
    date: "2026-09-08",
    title: "Skips never arm",
    items: [
      { tag: "fixed", text: "A tip the analyst said skip/watch to can no longer sit armed waiting for its level - it never arms, and a verdict that arrives after arming vetoes the fire and disarms the plan. The analyst hand-cleaned eight of these in one day, one minutes from firing a skipped short." },
      { tag: "fixed", text: "Scoring a tip-triggered plan no longer fails on a too-narrow database column (plan_source widened; the error appeared at every startup while it retried)." },
      { tag: "new", text: "scripts/restart.ps1: the one deploy script for every desk - stop, start, and WAIT for the app to answer before exiting, reporting anything an unelevated shell could not stop. Three market-hours outages came from deploys that walked away early." },
    ],
  },
  {
    version: "0.7.14",
    date: "2026-09-08",
    title: "Cartel research continues through mixed markets",
    items: [
      { tag: "improved", text: "Cartel now evaluates stocks and saves research candidates when market alignment blocks trading. Research-only candidates cannot auto-arm; fresh aligned preparation is required." },
      { tag: "improved", text: "Plans show SPY/QQQ closes, EMA levels and alignment, with market restrictions separated from data-coverage failures. Settings select bullish or bearish research when the market is blocked." },
    ],
  },
  {
    version: "0.7.13",
    date: "2026-09-08",
    title: "Team2: the read cannot rewrite itself",
    items: [
      { tag: "fixed", text: "The ZargarRestart deploy task works again: restart.ps1 is ASCII-only (Windows PowerShell read its em dash as a broken string and ran nothing), and it holds the 3-minute watchdog off so a restart can no longer spawn a second engine." },
      { tag: "fixed", text: "EM's daily LLM run cap counts only EM's own runs: another technique's nightly scan (5,557 rows on 2026-09-08) had used it up and the evening review was refused." },
      { tag: "fixed", text: "The engine now runs under the Windows Task Scheduler (ZargarWatchdog every 3 minutes, ZargarRestart on demand) instead of inside the assistant's process tree: the 14:24 outage on 2026-09-08 was the Claude desktop package update stopping its VM service, which took the engine with it. The app log keeps days instead of 50 minutes and says hello/goodbye with its pid." },
      { tag: "fixed", text: "Team2 recognises the read's events by fingerprint, so an input that moves under the recomputed read (IV, a corrected bar, a level) can never repeat a fire it already took or skip one; a rewritten history is reported once as 'read_rewritten'." },
      { tag: "fixed", text: "Team2 locks the read's IV per session from today's 0DTE at-the-money chain (falls back to the VIX proxy), stamps it on the plan and the run, and replays with the same number: the read's history is a point-in-time record, not a function of the latest quote." },
      { tag: "fixed", text: "Team2 finalizes the day type, open and sizing on the real 09:30 bar; the 09:25 pre-market estimate is kept as a snapshot and the change is journaled." },
      { tag: "fixed", text: "Team2 sells the rest at the plan target on the first FRESH underlying print through it (reduce-only limit at the contract's bid) instead of waiting for the 2-minute close; the model labels its own target exits as an intrabar assumption." },
      { tag: "fixed", text: "A Team2 pullback is an episode (price must close half an ATR off the EMA13 before the next one counts), and only a PRICED pullback spends the two-pullback allowance: a no-contract refusal no longer burns it. The read shows pullbacks / opportunities / spent / attempts." },
      { tag: "improved", text: "The F47 target-floor and both F56 no-trade-zone variants stay EXPERIMENTAL (sweep-only); twenty banked Practice sessions trigger a review, never an automatic promotion." },
    ],
  },
  {
    version: "0.7.12",
    date: "2026-09-08",
    title: "Cartel coverage and entry explanations",
    items: [
      { tag: "improved", text: "Cartel preparation can evaluate leaders across industries with ranks as context, retains a strict-rank option, and includes explicitly reviewed ETFs such as DRAM. A sourced comparison watchlist shows why names were included or excluded." },
      { tag: "fixed", text: "New automatic plans require complete confirmation-volume baselines. Pending contracts need complete opening history and an unreached target before arming; recovered history never turns a missed crossing into a live entry." },
      { tag: "improved", text: "Entry rejections retain timestamps and measured thresholds through recovery. Practice and Live settings expose the entry timeframe, breakout/retest approach, volume and close-quality choices." },
      { tag: "new", text: "Research replay comparisons support 5m and 15m breakout/retest variants with separately rebuilt historical volume baselines. Comparisons place no orders and never change the active strategy automatically." },
    ],
  },
  {
    version: "0.7.11",
    date: "2026-09-08",
    title: "Promoted takes flow",
    items: [
      { tag: "fixed", text: "A tip the recovery sweep revives with an analyst TAKE now approves itself in unattended practice (FRVO sat waiting on a quote-data artifact); skip/watch still declines itself, a tip with NO analyst verdict still waits fail-closed, and live books always keep the human." },
      { tag: "improved", text: "Team2's History tab now says how each past session went: trades taken, what the book actually kept after commissions, and the read's own model % beside it (they can disagree in sign). The refused count is setups the method turned down; once-a-day state notes (past the 15:30 cutoff, event day, loss cap) are named separately in the tooltip instead of padding it. A closed Team2 day used to leave no readable record." },
      { tag: "fixed", text: "The session brake (pause autos after a sub-5-minute stop-out) could never fire - the close reason it looked for was never saved. It is saved now, and research-book deaths no longer count against the real book." },
    ],
  },
  {
    version: "0.7.10",
    date: "2026-09-08",
    title: "The gate covers both doors",
    items: [
      { tag: "fixed", text: "The exit-plan geometry gate now also covers fills from armed plans, not just approved cards. This morning AVGO filled at 370.39 into a ladder drawn at 359/361 (both below the buy) and sold itself at a loss six minutes later, and GME armed a hair-width stop that died in the same minute - plans are now re-checked against the actual fill price, targets on the wrong side are dropped, too-tight stops move to real structure, and every repair is journaled and shown on the run." },
    ],
  },
  {
    version: "0.7.9",
    date: "2026-09-07",
    title: "Adjustable Cartel preparation risk",
    items: [
      { tag: "improved", text: "Cartel preparation supports up to 10% equity risk per setup in both Practice and Live settings. New Practice configurations default to 10%; new Live configurations stay at 1%, and saved values are preserved." },
      { tag: "improved", text: "Settings explain that the separate premium budget still limits spending. Changing risk does not enable Live trading or bypass cash, exposure and order checks." },
    ],
  },
  {
    version: "0.7.8",
    date: "2026-09-07",
    title: "Room for the next idea",
    items: [
      { tag: "new", text: "Glide sizing for tips: each new tip is budgeted at min(full budget, free cash ÷ 3), so the first positions get full size, later ones glide down, and a late great tip still gets a minimum position instead of bouncing off an empty book. The card says when the reserve trimmed it; a truly full book declines on the record." },
      { tag: "fixed", text: "The per-source limits (max open tips, open budget cap) existed in Settings but were enforced nowhere — they're real now: a source's open dollars shrink its next budget, and its open-count cap declines the tip with the reason journaled." },
    ],
  },
  {
    version: "0.7.7",
    date: "2026-09-07",
    title: "Cartel uses its own Practice book",
    items: [
      { tag: "fixed", text: "Cartel preparation honors its dedicated Practice account even when an older shared-book selection was saved. Archived or unavailable assigned books never fall back to another technique's account." },
      { tag: "improved", text: "Cartel account selectors and new-entry checks honor book ownership and archive flags. Risk percentages use the selected book's equity, not the combined Practice total." },
    ],
  },
  {
    version: "0.7.6",
    date: "2026-09-07",
    title: "Clearer Cartel plan details",
    items: [
      { tag: "fixed", text: "The Dashboard understands the per-technique Practice books: the headline totals all four ($40,000) and the equity chart now plots all four combined, with a picker for any single desk's book — it used to total four books in the headline while charting one arbitrary book underneath. The day's move and the sparkline follow the same set." },
      { tag: "improved", text: "Holdings name the book that holds them, so you can see which desk is carrying a position at a glance. The archived Practice book never appears — not in the total, the chart, the accounts row or the holdings." },
      { tag: "major", text: "Practice reset: one $10,000 Practice book per technique (EM, Tips, Team2, Options Cartel - $40,000 in all). The old shared book is archived: its holdings and history stay readable, but it is out of every list and total and trades nothing." },
      { tag: "improved", text: "Manual tickets ask which book a trade goes in instead of guessing; Flow sits last in the technique list (context only, no book)." },
      { tag: "fixed", text: "Opening or refreshing a Cartel record no longer duplicates its chart." },
      { tag: "improved", text: "Each Cartel record has a dedicated, bookmarkable page with Back navigation. Record links can also open in a new browser tab." },
      { tag: "improved", text: "Plan details lead with status, entry conditions and the actual exit schedule. Evidence and manual execution controls are separate, and the chart starts with the latest 30 saved sessions." },
    ],
  },
  {
    version: "0.7.5",
    date: "2026-09-07",
    title: "Preparation with visible coverage",
    items: [
      { tag: "improved", text: "Cartel checks the full eligible universe by default. An optional resource cap is separate from shortlist size; definite industry failures avoid unnecessary history downloads." },
      { tag: "new", text: "Preparation shows discovery and evaluation progress, current work, elapsed time, heartbeat, coverage gaps and history reuse. Interrupted scans can resume their saved snapshot." },
      { tag: "fixed", text: "Saved plans refresh as preparation publishes results, and filtered stocks show their later-stage rejection reasons. Data errors are counted separately." },
      { tag: "improved", text: "Option selection searches beyond the nearest three expiry dates when needed and explains rejection counts and the effective per-contract premium limit." },
    ],
  },
  {
    version: "0.7.4",
    date: "2026-09-07",
    title: "Cartel follows your workspace",
    items: [
      { tag: "improved", text: "Every trading technique now has its own day-loss pause (Team2, EM and Tips at 10% of the book on practice) with the book breaker at 15% above them as the catastrophe stop — the ladder is one table in PLATFORM-RULES; EM and Tips settings panels show their number." },
      { tag: "fixed", text: "Cartel preparation now shows accounts, settings and saved automatic plans for the selected Practice or Live workspace." },
      { tag: "new", text: "Live preparation has its own disabled-by-default setup, explicit execution and overnight acknowledgements, and the existing Cartel live-auto permission." },
      { tag: "improved", text: "Existing Practice settings remain intact. Switching workspace prevents preparation from arming in the previous mode while held-position protection continues." },
    ],
  },
  {
    version: "0.7.3",
    date: "2026-09-07",
    title: "A unified Cartel desk",
    items: [
      { tag: "new", text: "Options Cartel can discover the market, prepare a daily shortlist and arm qualifying options plans for automatic Practice execution." },
      { tag: "improved", text: "Cartel now follows the other trading desks: Plans, Armed, History and Validation, with compact tables and separate Method and Settings tabs." },
      { tag: "improved", text: "Preparation puts the shortlist first. Account, risk and schedule settings have their own home, and saved plans open directly into their details." },
      { tag: "improved", text: "Shared buttons, status labels, loading and empty states follow the app's theme, density and phone layouts." },
    ],
  },
  {
    version: "0.7.2",
    date: "2026-09-07",
    title: "Options Cartel desk",
    items: [
      { tag: "fixed", text: "Research (shadow) books no longer pad the Dashboard. \"My holdings\" showed 61 positions worth $327k under a balance that counted 3 of them — the per-source scorecard books are practice-SIDE but they are not money. Real positions now stand alone, with a \"+ research (51)\" toggle that reveals them dimmed and badged; Recent orders and Fills work the same way, and shadow rows there are labelled research instead of \"practice\"." },
      { tag: "new", text: "Options Cartel has its own research desk, source library, dated screen profiles, saved plans and history." },
      { tag: "new", text: "Capture capitalization and industry evidence, scan a focus list, and review completed results or retry individual data failures." },
      { tag: "new", text: "Review share or option expressions, arm alerts, proposals or automatic execution, and manage positions through the shared risk controls." },
      { tag: "new", text: "Replay saved campaigns, compare entry variants, and value modeled fills with recorded option quotes and fees. Missing data and simulation limits remain visible." },
      { tag: "new", text: "Optional Cartel quote recording and scheduled research/recovery have separate controls and start disabled." },
      { tag: "fixed", text: "Background technique work is fully awaited during shutdown, and option Greek freshness is tracked by field." },
    ],
  },
  {
    version: "0.7.1",
    date: "2026-09-04",
    title: "The plan gate",
    items: [
      { tag: "improved", text: "The Dashboard on a phone actually shows something now: the balance carries today's move (amount and %) and a sparkline of the day right under it, the plans card became one scrollable line of chips instead of a wall, and holdings fit eight to a screen with value over P&L. Panels also stopped sizing to their content — they were 300-347px wide on a 374px board." },
      { tag: "new", text: "Adoption geometry gate: a filled tip is checked against its actual entry before any exit order exists — targets on the wrong side or inside the noise are dropped, a stop that would fire instantly is re-placed at real structure, and every repair is journaled and shown on the analyst run. Eight adoptions died in seconds this week to exactly these defects." },
      { tag: "new", text: "Session brake: if one adopted tip stops out within five minutes of arming, tip auto-approvals pause for the rest of the day and the cards wait for a person (or the morning triage)." },
      { tag: "new", text: "Per-tip premium cap ($750, adjustable in Settings): one oversized option entry can no longer be the whole day's result." },
      { tag: "improved", text: "Sources can now earn auto-trading on their record at tip time (the immediate shadow book's aged positions), not only on the wait-for-the-level lane that momentum tips never fill." },
      { tag: "improved", text: "Knowledge cleanup: nine near-identical versions of one analyst rule were consolidated to one; a new rule now automatically retires the version it replaces. Nightly digests of the conversation channels are ON." },
      { tag: "fixed", text: "A tip promoted by the recovery sweep with an analyst skip/watch verdict now declines itself in unattended practice instead of waiting for a click that never comes (RDDT sat pending 18 minutes)." },
    ],
  },
  {
    version: "0.7.0",
    date: "2026-09-04",
    title: "The Team2 desk opens",
    items: [
      { tag: "new", text: "EM: the morning board check now arms the author's names itself when they pass our own gates (valid trigger, R:R, grade B or better, critic, loss halt) - his video ends at 06:15 Vancouver time and nobody could click. One setting turns it off." },
      { tag: "fixed", text: "Practice buys must fit the cash on hand, as any real venue insists - the shared Practice book had gone to -$5,000 cash." },
      { tag: "improved", text: "A restart re-attaching armed plans no longer journals them as new arms (1,600 phantom \"armed\" events in one day)." },
      { tag: "improved", text: "Sidebar: the techniques sit in the desk's order — Tips, Team2, EM, Flow — and the nav answers a click: a ripple from the pointer, an accent bar that slides to the active item, icons that lift on hover, a dot that pops on the active technique. All of it is off under reduced-motion." },
      { tag: "improved", text: "The Team2 page now looks like the Tips page: underline tabs with Plan now parked on the right, one panel per tab with a header line, the same table style with symbol icons, status pills and copyable run ids, one row per symbol for the coming session with earlier (replaced or disarmed) plans folded away, and the Armed tab shows mode, budget, loss halt, account, P&L and freshness." },
      { tag: "fixed", text: "The EM page no longer blanks the whole app when a plan is missing a list (confluences, notes, level sources, cautions, symbols) — every such spot is guarded, and a page that still crashes shows an error panel with try-again / reload / clear-saved-state instead of a white screen." },
      { tag: "improved", text: "Technique URLs name the technique: /techniques/em/validation, /techniques/tips, /techniques/team2/armed, /techniques/flow/brief. The old /technique, /inbox, /team2 and /flow links still open the same pages." },
      { tag: "fixed", text: "After the first live day, a post-close audit: Team2 re-prices a stuck exit and flattens the book on the clock at 15:45 whatever the read holds; sizes on the live ask; the premium stop ignores stale option quotes; the day-loss halt keeps counting a plan that already halted; replays use that day's IV; the phone timeline shows the events that stop the desk and the loss-limit tile shows the technique's brake; Settings gained a Risk & clock group for Team2." },
      { tag: "fixed", text: "A plan that halts mid-session now books its own flatten (the record no longer says 'open' after the book is flat), Team2 writes a real day scorecard (the read vs the book, skips, net of fees), expired contracts drop off the live quote batch, and the nightly option-chain sweep paces itself instead of losing half the universe to rate limits." },
      { tag: "fixed", text: "Team2 after its first real trades: the read and the book now pick the same contract (closest to the premium target), the premium stop measures the mid with a 3-tick floor so a one-cent spread cannot stop a cheap contract, both loss halts count commissions and refuse an entry that cannot fit the remaining day budget, the loss cap counts the whole desk, and read events carry one clock (the bar close)." },
      { tag: "improved", text: "The daily-loss breaker now halts only the book that lost (Practice, a live account…), not every book — the big red HALT is still global. Each technique can also pause itself on a book after its own bad day (Team2: 10%). The Armed page's kill-switch tile shows a halted book and lets you release it." },
      { tag: "improved", text: "Dashboard rebuilt around the number that matters: equity leads the page at full size, the accounts fold in underneath instead of repeating in a second card, and the always-green plumbing chips (snaptrade / ibkr / quotes) only appear when something is actually wrong." },
      { tag: "improved", text: "The equity chart skips dead time — nights, weekends and any stretch where the book did not move are collapsed, so a day reads as a day instead of a flat line from 6 PM. Pre- and post-market moves still show, and 1D / 3D / 1W / 1M / All are one click." },
      { tag: "fixed", text: "\"My holdings\" follows the workspace: in Practice it shows the practice book, not the real accounts you cannot trade there. It replaces the watchlist on the board, carries value and P&L per position, and links to the Trade page." },
      { tag: "improved", text: "The armed card says what it is — \"Plans watching the market · 63 armed · 57 still waiting\" — and ranks the ones closest to firing with how far away they are. The top bar's balance is a labelled readout instead of a small grey chip." },
      { tag: "fixed", text: "Armed page: a Team2 plan no longer wears EM's clothes — its Now line is the method's own read, the chart bands say 'entries all session · no new entries 15:30 · flat 15:45' instead of prime/mid-day windows, and its read events have icons. The Team2 page's Armed tab shows the read per symbol." },
      { tag: "fixed", text: "Quote day high, day low and volume are the session's, not 'since the app started': seeded from the exchange session values, widened by regular-session prints only, reset each session (they used to shrink to nothing after every restart)." },
      { tag: "improved", text: "Team2 trades the way his recaps do: trim heavily on the first push, then re-up the same contract on the next 13 EMA hold; a re-entry sells at the running high/low of day; and in money modes the +50/+100% trims are judged on the contract's live bid, not the model — the Armed row shows 'contract +X% live'." },
      { tag: "major", text: "Unattended practice: nobody has to watch the Approvals queue. An analyst skip/watch declines the card immediately with the reasoning attached (history, not a to-do); a take trades; anything still pending at the open gets a fresh analyst re-appraisal at 9:33 ET against live prices and is decided then. Live money always keeps the human." },
      { tag: "improved", text: "Approval cards now say when they were suggested (and that it was after the close, held for the open), how far the market has moved since, and that approving always re-prices at the live ask — plus 'time box 15 sessions', not '15s'." },
      { tag: "major", text: "A fourth technique, Team2 — Casey/@Team2Trading's SPY·QQQ·IWM day-trading method, codified from 49 public posts, two videos and his own trade screenshots: prior-day high/low zones and the pre-market range, a 13/48/200 EMA regime on the 2-minute chart, a 15-minute-close confirmation, EMA13 pullback entries with a one-candle stop, 0DTE contracts picked by premium (~$0.50), +50/+100% trims and a 15:45 flatten. Nightly plans per symbol, 09:25 completion, alert mode first. Its own page: Plans · Armed · History · Validation." },
      { tag: "new", text: "Extended-hours bars are banked nightly (04:00–20:00 ET, 1-minute) with the VIX indices — the walk-forward for any intraday technique can finally run on more than Yahoo's 20 days." },
      { tag: "new", text: "A market calendar: NYSE holidays and 13:00 early closes. Every clock-driven session close now honours them." },
      { tag: "new", text: "Per-technique 0DTE policy in the risk gate — a technique that IS a 0DTE method (Team2) opens the never-list for itself with its own last-entry time, flatten time and caps; every other technique stays hard-rejected." },
      { tag: "new", text: "A premium-path scorer for 0DTE: the sweep re-prices the actual $0.50 contract along the day (Black–Scholes on the VIX proxy, fees and slippage included) instead of scoring the underlying in R — calibrated against the author's documented SPY 711c trade." },
      { tag: "new", text: "Macro event calendar placeholder (FOMC/CPI/NFP) as a manual list in settings; techniques can flag or skip those days once a source is wired." },
    ],
  },
  {
    version: "0.6.2",
    date: "2026-09-04",
    title: "Winners get banked",
    items: [
      { tag: "fixed", text: "Validation batch: the Arm button says exactly why nothing qualifies instead of a cheerful \"All 0 armed\", and every bulk arm is verified against the server before it reports success." },
      { tag: "improved", text: "The Armed list reads in plain English. A row now says what will actually happen — \"Buy at 323.71 · eva · off support\", \"needs to fall 1.37%\" — instead of EM-only jargon that every tip row was wearing by accident. Anything identical on every row (market window, \"watching 1\", empty grades, zero P&L) is said once above the list or not at all, and rows sort closest-to-firing first." },
      { tag: "major", text: "Monetize campaign for swing options (researched against practitioner + academic literature): at +100% on the contract, half is sold — the trade has paid for itself and can no longer lose; ratchet floors lock in +15%/+50%/+120% as the premium climbs, tightening near expiry and when the gain is IV-driven. Judged every ~2 seconds. The analyst's stock-level ladder still runs; whichever prints first." },
      { tag: "major", text: "Deep-in-the-money winners roll up: when a call is mostly intrinsic (delta ≥ 0.75), the desk sells it and buys the ~0.35-delta strike — only when the cash banked exceeds what the trade originally cost. Upside stays on, the trade becomes unlosable. Max 2 rolls, both legs must quote tight and real-time." },
      { tag: "improved", text: "Every option position now records its best premium mark (MFE) — the raw material for tuning the exit thresholds on our own fills once enough history exists." },
      { tag: "improved", text: "Extraction understands entry slang: 'ape now', 'got starter', 'loading up', 'back in' are fresh entries, not commentary (neal's GME call was missed for this)." },
      { tag: "fixed", text: "The Ledger always shows a row for today — a quiet day reads 0.00 instead of repeating yesterday's number." },
    ],
  },
  {
    version: "0.6.1",
    date: "2026-09-02",
    title: "Nothing stranded, nothing lost to a bug",
    items: [
      { tag: "improved", text: "Ledger, three ways — a view switch between Timeline (the week as a story, today at the head), Sheet (every trade with filters by source, book, win/loss, options/shares, hold time, plus sortable columns and a running balance) and Chart (a real waterfall from your starting cash to now). Day totals no longer look like a trade's P&L, the headline is a balance instead of an equation, and the decorative day bars are gone." },
      { tag: "fixed", text: "Today is always on the Ledger now, even when nothing closed — a quiet day used to be indistinguishable from a broken page, and the positions you were carrying showed no date at all." },
      { tag: "fixed", text: "A restart no longer strands a working entry: the entry window now times out by the clock, the contract is watched again after a restart, and an order the sim book lost is cancelled instead of sitting 'accepted' forever." },
      { tag: "new", text: "Counterfactual ledger (Armed > History): when a bug costs a trade, the fired order is replayed through the desk's own exit rules on the real bars after the fix - fill, exits, gain, R - and kept beside the real results. Practice stays what actually happened." },
      { tag: "improved", text: "The EM ingestion window says what it captured today on start instead of sitting blank." },
      { tag: "fixed", text: "A restart no longer empties the practice/shadow order book: resting stops, limits and bracket exits come back; a market order that never filled is cancelled rather than filled late." },
      { tag: "major", text: "Real-time option quotes: contracts we track are priced from Alpaca's OPRA feed (the subscription already covered it) instead of CBOE's 15-minute-delayed chain. Practice fills, sizing, entry limits, premium stops and the risk gate's caps all run on the live NBBO; a contract without a live quote is badged 'delayed' on every money screen, and with the live source configured the risk gate refuses to open a position on a delayed quote." },
      { tag: "new", text: "Lotto profit-taking on the contract itself: a 0-3 DTE tip sells half at +100%, the next quarter at +200%, and the rest can never go below what was paid - judged every quote tick, not on 15-minute bars (the underlying ladder never sees a 0DTE triple)." },
      { tag: "fixed", text: "Practice fills on options use what is actually trading: when the live tape has printed past the 15-minute-delayed chain quote, the bid/ask re-centres on the print (a GOOGL 0DTE was 'bought' at 0.13 while the market was 0.50)." },
      { tag: "fixed", text: "A managed position's stop is watched again after a restart (RKLB went unwatched for an hour); thin contracts the live feed never prints can still fill in practice from the chain quote." },
    ],
  },
  {
    version: "0.6.0",
    date: "2026-09-01",
    title: "The Ledger, and the method reads itself in",
    items: [
      { tag: "major", text: "Ledger: the money in plain terms — day by day, what was bought, what was sold and the gain each time, after real fees. The headline is an identity (start + banked + riding = total), so the page can never quietly fail to add up; tap any trip for the full breakdown. Real books in LIVE, sim books in Practice, like the Dashboard." },
      { tag: "major", text: "EM method ingestion: the author's Discord channels are watched, his morning video is transcribed on its own, and one read turns it into a summary, his board, his method claims and his vetoes — then OUR pipeline plans every symbol he named and tells you which are already armed, which produce a valid fresh plan (with an Arm button), and which our gates rejected and why. Arming stays your click." },
      { tag: "new", text: "Author's board card on the EM page: today's material with supplementary notes, live-broadcast deferral (a stream still running is re-probed instead of half-captured), same-day media dedupe, and a speech-to-text ticker hint so \"SpaceX\" stops becoming the wrong symbol." },
      { tag: "new", text: "Lotto lane for 0–3 DTE tips: two of the desk's most active sources trade almost nothing else, and the old policy killed every one before the analyst judged it. Short-dated tips now get their own budget, the stated contract verbatim, tip-time entry — and a mandatory flatten on expiry day (never hold through the close)." },
      { tag: "improved", text: "A message that carries many calls (a daily level map) is appraised ONCE and the siblings inherit the verdict — one story, one judgement, instead of eleven analyst runs." },
      { tag: "improved", text: "Practice fills now mirror Webull Canada's real fee schedule (per-contract commission plus regulatory fees), so the practice book and the Ledger tell the same story as real money." },
      { tag: "fixed", text: "Approving an aged proposal re-prices the limit at the live ask before it goes out — a two-hour-old limit against a moved market tripped the price collar and failed your own click. The never-chase rule still applies: the limit may only improve." },
      { tag: "fixed", text: "Research (shadow) books no longer hit %-of-equity risk caps — a beaten-down fake book was blocking record entries, which is a gap in the evidence, not protection. Absolute caps still apply." },
      { tag: "fixed", text: "The scan panel marks plans built for a session that is already over as expired and leaves them out of \"Arm N confirmed\", so a stale batch can't be armed after the close." },
      { tag: "fixed", text: "A ledger correction can be retired by a later one instead of both being counted." },
    ],
  },
  {
    version: "0.5.0",
    date: "2026-08-30",
    title: "Three techniques on one engine — and honest position marks",
    items: [
      { tag: "major", text: "Multi-technique platform: EM Options, Tips and Flow run side by side on the shared engine (registry-driven nav, per-technique settings, one risk gate)." },
      { tag: "major", text: "Tips desk: paste or auto-ingest Discord tips, an independent Analyst appraises each one live (play-by-play you can watch), every source earns trust through two shadow books before real money." },
      { tag: "new", text: "Flow desk: nightly unusual-options-activity scan with overnight open-interest confirmation, symbol stories, a morning brief — context for the other techniques, never orders." },
      { tag: "new", text: "Discord intake: pick exactly which DMs/channels feed the pipeline, test any source, \"▶ tip\" a message on demand; multi-day stay-armed plans roll across sessions." },
      { tag: "new", text: "Knowledge notes with lifetimes, nightly channel digests, weekly rule audits, and a historical tip-experiment harness that never touches real books." },
      { tag: "fixed", text: "Positions with no live quote (weekend, halted, never traded since start) showed a dead-flat P&L at average cost — TQQQ sat at −0.00% all weekend. Quotes now fall back per symbol to the slow feed, and every sync also carries the broker's own mark." },
      { tag: "new", text: "This dialog: version chip in the top bar, filterable changelog." },
      { tag: "new", text: "The morning report: at 08:25 ET a push + Dashboard card answers \"what needs me\" — waiting proposals (with why), flagged plans, overnight tips, today's armed plans and rolls." },
      { tag: "new", text: "Auto-approve is earned per source: a tipper's takes self-approve only after enough of their tips have closed well; until then every take waits for you with a graduation note." },
      { tag: "improved", text: "Research (shadow) books read as research: hidden or dimmed in the Blotter and Journal, never toast, one row per source pairing the immediate and armed lanes with the hit record instead of fake cash." },
      { tag: "fixed", text: "On phones the version chip pushed HALT onto a second row, where it covered the page — the phone top bar is now a single row that shrinks (logo, version, workspace, alerts, search, HALT all fit on a 320px screen); tablet portrait tightens instead of overlapping." },
      { tag: "fixed", text: "First live-soak hardening: a slow fill can no longer double-exit a position past flat; a crashed analyst leaves the proposal for you instead of approving it; cold quotes park a tip instead of killing it; API overloads retry; a lotto-priced option can't be sized into hundreds of contracts." },
      { tag: "new", text: "Lotto lane: 0–3 DTE tips are no longer killed — they trade the stated contract at tip time from their own smaller budget and are flattened on expiry day before the close." },
      { tag: "improved", text: "The analyst appraises a multi-branch message (a daily level map) once; branches inherit the verdict. Knowledge notes are capped at two per run and chatter cataloguing is refused." },
      { tag: "new", text: "Ledger page: your money in plain terms — every buy and sell as a round trip with its gain, day by day, plus what's still riding. Real books only; the research books never appear." },
      { tag: "improved", text: "Approving an older proposal re-prices it at the live ask (the price can only improve, never chase), and a source posting a trim/close cancels only that source's pending cards." },
    ],
  },
  {
    version: "0.4.0",
    date: "2026-08-26",
    title: "Phone-first: mobile UI, sign-in, a public address",
    items: [
      { tag: "major", text: "Full mobile layer: bottom tab bar (Now · Trade · Tips · Portfolio · More), sheets instead of dialogs, the armed \"Now\" screen as the phone home, installable app with push notifications." },
      { tag: "security", text: "Sign in with Google (allow-listed accounts only), 30-day sessions that survive restarts, rate-limited sign-in, phones exit-only on real accounts by default." },
      { tag: "new", text: "Public HTTPS address via Tailscale Funnel — the app works from any browser, anywhere, with sign-in in front." },
      { tag: "improved", text: "Charts on phones: one finger pans, two pinch-zoom, tap reads a bar, double-tap snaps back to the live edge; last price tagged on the axis." },
      { tag: "improved", text: "Trading-day range presets (2D · 3D · TW · LW · 2W) and a broker-style floating price readout on desktop charts." },
    ],
  },
  {
    version: "0.3.0",
    date: "2026-08-25",
    title: "The EM technique trades: armed plans, options, review loop",
    items: [
      { tag: "major", text: "EnhancedMarket pipeline end-to-end: structure analysis, session plans, walk-forward validation, and armed plans that watch 1m bars and fire in the book's two windows." },
      { tag: "major", text: "Armed plans trade options by default (just-OTM calls/puts, risk-based sizing, critic pre-check) with managed exits: targets, stops on bar close, premium stop, quote crash-brake, loss halts." },
      { tag: "new", text: "Review loop: every run carries its full decision trace, outcomes are scored by replaying the same simulator, reviews and sweeps are first-class records." },
      { tag: "new", text: "Both directions planned — bounces/breakouts with calls, rejects/breakdowns with puts; shorts never touch shares." },
      { tag: "improved", text: "Durable positions: exits are policies-as-data, state survives restarts, overnight share holds get a venue-side stop." },
    ],
  },
  {
    version: "0.2.0",
    date: "2026-08-20",
    title: "Real money: SnapTrade trading, dashboard, per-provider views",
    items: [
      { tag: "major", text: "Live trading through SnapTrade (Wealthsimple + Webull Canada): risk-gated orders, write-ahead money paths, fill polling with reconciliation — never a blind resubmit." },
      { tag: "new", text: "Dashboard home with per-currency net worth, provider cards, equity curve; Portfolios grouped by brokerage with authoritative balance syncs." },
      { tag: "new", text: "Real-money confirm dialog pre-flights every order as a dry run before you commit." },
      { tag: "improved", text: "Live quotes: Alpaca stream + Yahoo context/fallback hybrid; day change measured against the prior close, like every broker." },
      { tag: "fixed", text: "Multi-currency accounts sum every wallet (a USD balance inside a CAD account no longer vanishes)." },
    ],
  },
  {
    version: "0.1.0",
    date: "2026-08-17",
    title: "First light",
    items: [
      { tag: "major", text: "Engine + API + UI skeleton: portfolios, watchlists, simulated trading, journal of every decision, kill switch." },
    ],
  },
];
