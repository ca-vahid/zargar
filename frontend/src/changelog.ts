// The app's version + curated changelog. ONE source of truth for the UI:
// the TopBar chip, the What's-New dialog and the More sheet all read this.
// Keep entries CONCISE and user-facing (what changed for the trader, not the
// commit log); every release bumps APP_VERSION here AND in package.json,
// backend/zargar/__init__.py and backend/pyproject.toml.

export const APP_VERSION = "0.7.0";

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
    version: "0.7.0",
    date: "2026-09-04",
    title: "The Team2 desk opens",
    items: [
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
