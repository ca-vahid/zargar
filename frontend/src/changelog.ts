// The app's version + curated changelog. ONE source of truth for the UI:
// the TopBar chip, the What's-New dialog and the More sheet all read this.
// Keep entries CONCISE and user-facing (what changed for the trader, not the
// commit log); every release bumps APP_VERSION here AND in package.json,
// backend/zargar/__init__.py and backend/pyproject.toml.

export const APP_VERSION = "0.5.0";

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
