// The app's version + curated changelog. ONE source of truth for the UI:
// the TopBar chip, the What's-New dialog and the More sheet all read this.
// Keep entries CONCISE and user-facing (what changed for the trader, not the
// commit log); every release bumps APP_VERSION here AND in package.json,
// backend/zargar/__init__.py and backend/pyproject.toml.

export const APP_VERSION = "0.7.47";

export type ChangeTag = "major" | "new" | "improved" | "fixed" | "security";

export interface ChangeItem { tag: ChangeTag; text: string }
export interface Release {
  version: string;
  date: string;        // YYYY-MM-DD
  title: string;
  items: ChangeItem[];
}

export const CHANGELOG: Release[] = [
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
