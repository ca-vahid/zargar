export interface Quote {
  symbol: string;
  bid: number;
  ask: number;
  last: number;
  bidSize: number;
  askSize: number;
  volume: number;
  halted: boolean;
  ts: number;
  // session context from real feeds (0 / "" when unknown, e.g. the sim feed)
  prevClose?: number; // prior session close — the day-change basis
  regPrice?: number;  // regular-session price (differs from last pre/post)
  dayHigh?: number;
  dayLow?: number;
  session?: "pre" | "regular" | "post" | "closed" | "";
}

export interface Portfolio {
  id: string;
  name: string;
  kind: "live" | "paper" | "sim" | "shadow";
  cash: number;
  equity?: number;
  startingCash: number;
  sourceName?: string | null;
  isDefault?: boolean;
  baseCurrency?: string;
  venue?: string; // "ibkr" | "snaptrade" for live/paper portfolios
  todayPct?: number | null; // % equity change vs today's first quote-backed observation
}

export interface BrokeragePosition {
  symbol: string;
  qty: number;
  avgCost: number;
  price?: number | null;
  marketValue?: number | null;
  currency?: string | null;
  universalId?: string | null; // SnapTrade universal symbol id (impact checks)
}

export interface BrokerageAccount {
  id: string;
  portfolioId: string;
  institution: string;
  name: string;
  number: string;
  currency: string;
  accountType?: string;
  cash: number;
  cashBalances?: { currency: string; cash: number }[]; // native per-currency cash
  equity: number;
  brokerTotal?: number | null; // broker's own FX-converted account total
  brokerSyncedAt?: string | null; // vintage of brokerTotal (their overnight sync)
  mismatch?: { computedEquity: number; brokerTotal: number; pct: number } | null;
  syncedAt: string | null;
  positions: BrokeragePosition[];
}

export interface BrokerageProvider {
  connectionId: string;
  broker: string;
  logoUrl?: string | null;
  type: "trade" | "read" | string;
  disabled: boolean;
  accounts: BrokerageAccount[];
}

export interface Brokerages {
  enabled: boolean;
  lastSyncAt: string | null;
  providers: BrokerageProvider[];
}

export interface BrokerState {
  feed: string | null;
  feedConnected: boolean;
  ibkrConnected?: boolean;
  snaptradeConnected?: boolean;
  quoteSource?: "yahoo" | "sim" | "ibkr" | string;
  mode: string;
}

export interface OptionInfo {
  symbol: string; underlying: string; expiry: string; strike: number; right: "C" | "P";
  optionType: "call" | "put"; dte: number; display: string; short: string; multiplier: number;
}

export interface Position {
  portfolioId: string;
  symbol: string;
  secType: string;
  option?: OptionInfo | null; // present for OPT positions
  qty: number;
  avgCost: number;
  realizedPnl: number;
  currency?: string; // native currency of the instrument (values are native)
  last?: number;
  marketValue?: number;
  unrealizedPnl?: number;
  unrealizedPnlPct?: number;
}

export interface Order {
  id: string;
  portfolioId: string;
  symbol: string;
  secType: string;
  side: "BUY" | "SELL";
  qty: number;
  orderType: string;
  limitPrice: number | null;
  stopPrice: number | null;
  tif: string;
  status: string;
  filledQty: number;
  avgFillPrice: number | null;
  source: string;
  parentId: string | null;
  rejectReason: string | null;
  option?: OptionInfo | null; // present for OPT orders
  optionAction?: string | null; // BUY_TO_OPEN … (API response only)
  createdAt: string;
}

export interface Execution {
  id: string;
  orderId: string;
  portfolioId: string;
  symbol: string;
  side: string;
  qty: number;
  price: number;
  commission: number;
  ts: string | number;
}

export interface Watchlist {
  id: string;
  name: string;
  sort: number;
  symbols: string[];
}

export interface Proposal {
  id: string;
  signalId: string | null;
  portfolioId: string;
  symbol: string;
  secType: string;
  side: string;
  qty: number;
  orderType: string;
  limitPrice: number | null;
  bracket: { take_profit?: number | null; stop_loss?: number | null } | null;
  rationale: string | null;
  context: any;
  status: string;
  expiresAt: string | null;
  decidedVia?: string | null;
  orderId?: string | null;
  createdAt: string;
}

export interface Signal {
  id: string;
  rawContentId: string | null;
  sourceName: string | null;
  ticker: string;
  direction: string;
  action: string;
  instrument?: string;            // shares | call | put | either | unspecified
  strike?: number | null;
  expiry?: string | null;         // YYYY-MM-DD
  dteHintDays?: number | null;
  horizonSessions?: number | null;
  catalyst?: string | null;
  seenCount?: number;
  lastSeenAt?: string | null;
  entryPrice: number | null;
  targetPrice: number | null;
  stopPrice: number | null;
  timeframe: string;
  thesisSummary: string | null;
  confidence: string;
  isActionable: boolean;
  verification: { passed: boolean; park?: boolean; flowContext?: string; calendarContext?: string;
    checks: { name: string; passed: boolean; detail: string; fatal?: boolean }[] } | null;
  extraction?: any;               // full LLM output + grounding + shadowExpression (vehicle record)
  status: string;
  createdAt: string;
}

export interface ShadowBook {
  portfolioId?: string;
  equity?: number | null;
  pnl?: number | null;
  pnlPct?: number | null;
  positions?: number;      // armed book: managed positions opened
  closed?: number;
  realizedPnl?: number;
  outcomes?: {             // armed book: R-based, from scored tip-run outcomes
    scored: number; fired: number; neverTriggered: number;
    winRate: number | null; avgR: number | null; expectancyR: number | null;
  };
}

export interface DiscordCatalogChannel { channelId: string; name: string; category?: string; }
export interface DiscordCatalogGuild { guildId: string; guildName: string; channels: DiscordCatalogChannel[]; }
export interface DiscordCatalogDM { channelId: string; name: string; isBot?: boolean; }
export interface DiscordCatalog {
  user?: { id?: string; username?: string } | null;
  at?: string | null;
  dms: DiscordCatalogDM[];
  guilds: DiscordCatalogGuild[];
}
export interface DiscordWatch {
  channelId: string;
  kind: "dm" | "channel";
  sourceName: string;
  label?: string;
  guildName?: string;
  botsOnly?: boolean;
  enabled?: boolean;
  /** onboarding: backfill this many days of channel history into the mirror (<= 17) */
  onboardDays?: number;
}
/** One mirrored Discord message (the analyst-searchable source history). */
export interface DiscordMirrorMessage {
  id: string; channelId: string; source?: string | null; guild?: string | null;
  author: string; isBot?: boolean; text: string; images: string[];
  postedAt?: string | null;
}

export interface AnalystStep {
  seq: number; kind: string; text: string; at?: string;
  tool?: string; args?: any; result?: any; opinion?: any; tip?: any; verification?: any;
  runId?: string; ticker?: string; status?: string;   // intake hand-off extras
}
export interface AnalystRunSummary {
  id: string; ticker: string; source?: string | null; status: string;
  kind?: string;                                      // "appraise" | "intake"
  verdict?: string | null; model?: string | null; signalId?: string | null;
  traceSteps: number; createdAt?: string | null; finishedAt?: string | null;
}
export interface AnalystRun extends AnalystRunSummary {
  tools: string[]; trace: AnalystStep[]; opinion: any; tip: any; error?: string | null;
}
/** Shared tips knowledge: a durable note the analyst (or the user) saved.
    Scope: "general" | "source:<name>" | "ticker:<SYM>" | "signal:<id>". */
export interface TipNote {
  id: string; scope: string; text: string; author: string;
  signalId?: string | null; runId?: string | null; createdAt?: string | null;
}

export interface SourceScorecard {
  source: string;
  signals: number;
  verified: number;
  parked: number;
  failed: number;
  expiredUnfilled?: number;   // level never came before the tip's contract died
  seenAgain: number;
  lastSignalAt: string | null;
  books?: { immediate: ShadowBook; armed: ShadowBook };
  shadowPortfolioId?: string;      // back-compat: the immediate book
  shadowEquity?: number | null;
  shadowPnl?: number | null;
  shadowPnlPct?: number | null;
  barCleared?: boolean;            // judged on the ARMED book
  tipTimeEarned?: boolean;         // immediate demonstrably beats armed
  policy?: { entry: string; mode: string; risk_pct: number; budget_per_tip: number;
    dte_min: number; dte_max: number; horizon_sessions: number };
}

// --- Flow technique (docs/techniques/flow/UI-PLAN.md) ---
export interface FlowFlag {
  contract: string;            // unpadded OCC
  expiry: string | null;
  optionType: string;          // call | put
  strike: number;
  volume: number;
  openInterest: number;
  volOi: number;
  mid: number | null;
  premium: number;
  otmPct: number;
  dte: number;
  strong: boolean;
  iv?: number | null;
  oiDelta?: number;            // on confirmed entries
  oiConfirmed?: boolean;
}

export interface FlowReadItem {
  id: string;
  day: string;
  symbol: string;
  score: number;
  lean: string;                // bull | bear | mixed | none
  spot?: number | null;        // underlying at scan time (fallback when no live quote)
  flags: FlowFlag[];
  confirmed: FlowFlag[];
  repeatHits: Record<string, number>;
  reasons: string[];
  aggregates: { callVolume?: number; putVolume?: number; totalVolume?: number;
    pcVolumeRatio?: number | null; callPremium?: number; putPremium?: number;
    osRatio?: number | null };
  createdAt: string | null;
}

export interface FlowDaySummary {
  day: string;
  scanned: number;
  flagged: number;
  callPremium: number;
  putPremium: number;
  confirmed: number;
  churn: number;
  repeatStreaks: { symbol: string; contract: string; days: number }[];
}

export interface FlowDelivery {
  consumer: string;            // tip | em
  refId: string | null;
  day: string;
  score: number;
  line: string;
  ts: string | null;
}

export interface FlowStory {
  symbol: string;
  reads: FlowReadItem[];       // oldest -> newest
  deliveries: FlowDelivery[];
  universe: { inUniverse: boolean; provenance: string | null };
}

export interface FlowBrief {
  day: string;
  prevDay: string | null;
  empty: boolean;
  summary?: FlowDaySummary;
  sections: {
    confirmedOvernight: { symbol: string; contract: string; oiDelta: number; volume: number; score: number }[];
    churn: { symbol: string; contract: string; premium: number }[];
    accumulation: { symbol: string; contract: string; days: number; dte: number | null; premium: number | null }[];
    newToday: { symbol: string; contract: string; premium: number; volOi: number; lean: string; strong: boolean }[];
    dying: { symbol: string | null; contract: string; dte: number | null; reason: string }[];
    contextLines: { symbol: string; line: string }[];
  };
}

export interface RawContentItem {
  id: string;
  sourceType: string;
  sourceName: string | null;
  sender: string | null;
  subject: string | null;
  status: string;
  receivedAt: string;
  preview: string;
}

export interface JournalEvent {
  id: number;
  ts: string;
  type: string;
  aggregateType: string | null;
  aggregateId: string | null;
  portfolioId: string | null;
  payload: Record<string, any>;
}

export interface HaltState {
  engaged: boolean;
  reason: string;
  ts: number;
}

export type Settings = Record<string, any>;

export interface Snapshot {
  settings: Settings;
  portfolios: Portfolio[];
  positions: Position[];
  openOrders: Order[];
  quotes: Record<string, Quote>;
  halt: HaltState;
  watchlists: Watchlist[];
  proposals: Proposal[];
  brokerages?: Brokerages | null;
  broker: BrokerState;
}


// --- options -------------------------------------------------------------------
export interface OptionExpiry { date: string; dte: number; is0dte: boolean; weekday: string }
export interface OptionExpiries {
  underlying: string; spot: number | null; prevClose: number | null; iv30: number | null;
  expiries: OptionExpiry[]; provider: string; delayed: boolean;
}
export interface OptionCell {
  symbol: string; bid: number; ask: number; mid: number; last: number | null; spreadPct: number | null;
  volume: number; openInterest: number; iv: number | null; delta: number | null; gamma: number | null;
  theta: number | null; vega: number | null; inTheMoney: boolean;
}
export interface OptionChainRow { strike: number; call: OptionCell | null; put: OptionCell | null }
export interface OptionChain {
  underlying: string; expiry: string; dte: number | null; spot: number | null; rows: OptionChainRow[];
  asOf: number; provider: string; delayed: boolean;
}
export interface OptionContract extends OptionInfo, Partial<Omit<OptionCell, "symbol">> {
  underlyingSpot: number | null; available: boolean; asOf?: number; quote: Quote | null;
  provider: string; delayed: boolean;
}
export interface OptionCapability {
  accountId: string; portfolioId: string | null; broker: string; allowlisted: boolean;
  supported: boolean | null; probed: boolean; checkedAt: string | null; detail: string | null;
}
export interface OptionImpact {
  estimatedCashChange?: number | null; direction?: string | null; estimatedFees?: number | null;
  supported?: boolean | null; error?: string; code?: string | null;
}

// --- technique pipeline + chat ------------------------------------------------
export interface TechniqueLevel {
  price: number; kind: string; touches: number; note?: string;
  strong?: boolean; sources?: string[]; position?: string; effectiveKind?: string; timeframes?: string[];
}
export interface TechniqueTarget { price: number; trimPct: number; basis: string }
export interface TechniqueContract {
  symbol: string; verdict: "setup" | "no_setup"; setupType: string; direction: string; trend: string;
  levels: TechniqueLevel[];
  pattern: { kind: string; present: boolean; widestHeight?: number | null; volumeDeclining: boolean; notes: string };
  breakout: { observed: boolean; levelPrice?: number | null; verdict: string; volumeConfirmed: boolean;
    decisiveCandle: boolean; followThrough: boolean; holdsLevel: boolean; higherTfAgrees: boolean };
  entry: { price: number; basis: string; requiresConfirmation: boolean } | null;
  stop: { price: number; kind: string; reference: string } | null;
  targets: TechniqueTarget[]; runnerPct: number; riskReward: number; volumeVerdict: string;
  confidence: number; rulesFired: string[]; noTradeReasons: string[];
  optionsExpression: { strikeGuidance: string; expiryGuidance: string; warnings: string[] } | null;
  rationale: string;
}
export interface GroundingCheck { name: string; passed: boolean; detail: string }
export interface TraceStep {
  seq: number; t: number | null; stage: string; step: string; reason: string; call?: number | null; detail?: any;
}
export interface TechniqueOutcome {
  id: string; runId: string; setupId: string | null; planSource: string; status: string; horizonBars: number;
  plan: any; outcome: string | null; rMultiple: number | null; mfeR: number | null; maeR: number | null;
  barsHeld: number | null; barsAfter: number; path: Record<string, any>; barsAssetId: string | null;
  note: string | null; scoredAt: string | null; createdAt: string | null;
}
export interface TechniqueReview {
  id: string; runId: string; reviewer: string; expectedVerdict: string | null; expectedSetupType: string | null;
  expectedPlan: any; expectationNote: string; reviewVerdict: string; rootCauseStage: string | null; notes: string;
  actions: { desc: string; file?: string | null; status?: string }[]; processVersion: Record<string, any>;
  createdAt: string | null;
}
export interface TechniqueRunConfig {
  promptVersion?: string; rulebookVersion?: string; codeVersion?: string; processVersion?: string;
  thresholds?: Record<string, any>; settings?: Record<string, any>; model?: string; effort?: string;
  thinkingDisplay?: string; maxPasses?: number; timeframes?: string[]; parentRunId?: string | null;
  overrides?: Record<string, any>; barsAssetId?: string;
}
export interface TechniqueRun {
  technique?: string;   // registry id (platform plan phase 0); absent from older servers
  id: string; threadId: string | null; symbol: string; asOf: number | null; primaryTf: string;
  mode: string; trigger: string; status: "running" | "done" | "failed";
  verdict: string | null; setupType: string | null; confidence: number | null; grounded: boolean | null;
  analysis?: TechniqueContract | null; groundingPassed?: boolean | null;
  images: Record<string, string>; usage: Record<string, number>; error: string | null;
  llm: Record<string, string>; createdAt: string | null; finishedAt: string | null;
  options?: any; seconds?: number;
  facts?: any; result?: { analysis: TechniqueContract | null; grounding: { passed: boolean; checks: GroundingCheck[] };
    passes: { name: string; parsed: any; usage: any; seconds: number }[]; mode: string; error: string | null;
    usage: any; options?: any; seconds?: number; trace?: TraceStep[]; plan?: SessionPlan; sessionWindow?: string | null };
  setups?: TechniqueSetup[];
  plan?: { planFor: string; builtFromSession: string; levels: number; triggers: number; validTriggers: number; kinds: string[] } | null;
  sessionWindow?: string | null;
  // review loop
  config?: TechniqueRunConfig; parentRunId?: string | null; processVersion?: string | null; traceSteps?: number;
  outcomes?: TechniqueOutcome[]; reviews?: TechniqueReview[];
  replays?: { id: string; createdAt: string | null; verdict: string | null; setupType: string | null; confidence: number | null; status: string }[];
  reviewCount?: number;
  lastReview?: { reviewVerdict: string; rootCauseStage: string | null; createdAt: string | null; reviewer: string } | null;
}
export interface TechniqueTaxonomy { reviewVerdicts: Record<string, string>; rootCauseStages: Record<string, string> }
export interface PlanCondition { rule: string; text: string; kind: string }
export interface TriggerAssessment { grade: "A" | "B" | "C" | null; score: number; strengths: string[]; cautions: string[] }
export interface PlanTrigger {
  id: string; kind: "bounce" | "breakout" | "wedge_break" | "reject" | "breakdown" | string; direction: string; levelPrice: number; level: any;
  entry: { price: number; basis: string }; stop: { price: number; reference: string };
  targets: { price: number; trimPct: number; basis: string }[]; riskReward: number; risk: number;
  conditions: PlanCondition[]; voidIf: string[]; confluences: string[]; confidence: number; rules: string[];
  valid: boolean; noTradeReasons: string[]; notes: string; setupType: string;
  assessment?: TriggerAssessment;
}
export interface PlanLevel {
  price: number; kind: string; effectiveKind: string; touches: number; sources: string[]; timeframes: string[];
  position?: string; distancePct: number | null; ageSessions: number | null; priorDayExtreme: boolean; carried?: boolean;
}
export interface SessionPlan {
  symbol: string; planFor: string; builtFromMs: number; builtFromSession: string; structureTfs: string[]; triggerTf: string;
  lastClose: number; levels: PlanLevel[]; context: any; triggers: PlanTrigger[]; invalidations: { rule: string; text: string; kind: string }[];
  gapPolicy: any; notes: string[]; validTriggers: number; bottomLine?: string;
}
export interface TechniqueSweep {
  technique?: string;   // registry id (platform plan phase 0); absent from older servers
  id: string; label: string; symbols: string[]; start: string; end: string; params: any; status: string; progress: any;
  summary: any; error: string | null; createdAt: string | null; finishedAt: string | null; rows?: WalkforwardRow[];
}
export interface WalkforwardRow {
  id: string; sweepId: string; symbol: string; session: string; planFor: string | null; plan: any; result: any; summary: any;
  promotedRunId: string | null; createdAt: string | null;
}
export interface ArmConfig {
  portfolioId: string; mode: "alert" | "proposal" | "auto" | string; instrument: "options" | "shares" | string;
  contracts: number | null; maxContracts: number; singleContractExit: string;
  riskPct: number; maxQty: number; qty: number | null;
  useCritic: boolean; allowLive: boolean; flattenMinutesBeforeClose: number; slippagePct: number; maxRetries: number;
  maxOpenTrades?: number; dailyLossLimit?: number; skipWideSpread?: boolean; skipElevatedIv?: boolean;
  entryFallback?: string;
}
export interface ArmPreflight {
  ok: boolean; blocked?: string; note?: string; instrument?: string; trigger?: string;
  account?: { name?: string; kind?: string };
  size?: { shares?: number; entry?: number; notional?: number; contracts?: number; estPremium?: number; estNotional?: number };
  checks: { name: string; passed: boolean; detail: string }[];
}
export interface ArmScorecard {
  planFor: string; symbol: string; theoreticalFires: number; actualFires: number; matched: number;
  theoreticalSumR: number; realizedPnl: number;
  rows: { trigger: string; kind: string; match: boolean; entrySlippage: number | null; notes: string[];
    theoretical: { status?: string; firedTs?: number | null; fill?: number | null; outcome?: string; rMultiple?: number | null; mfeR?: number | null; maeR?: number | null };
    actual: { status?: string; firedTs?: number | null; instrument?: string; avgFill?: number | null; premiumPaid?: number | null; realizedPnl?: number; exits?: string[]; reason?: string } | null }[];
}
export interface ArmRequest {
  portfolioId?: string; mode?: "alert" | "proposal" | "auto"; instrument?: "options" | "shares";
  contracts?: number; maxContracts?: number; singleContractExit?: string;
  riskPct?: number; maxQty?: number; qty?: number;
  useCritic?: boolean; allowLive?: boolean; flattenMinutesBeforeClose?: number; slippagePct?: number;
  maxOpenTrades?: number; dailyLossLimit?: number; skipWideSpread?: boolean; skipElevatedIv?: boolean;
  entryFallback?: string;
}
export interface ArmOptions {
  portfolios: { id: string; name: string; kind: string; venue?: string; baseCurrency?: string; cash?: number; isDefault?: boolean;
    sourceName?: string | null; optionsOk: boolean; optionsNote: string }[];
  defaults: { portfolioId: string; mode: string; instrument: string; contracts: number; maxContracts: number; singleContractExit: string;
    riskPct: number; maxRiskPct: number; maxQty: number; useCritic: boolean; flattenMinutesBeforeClose: number; slippagePct: number;
    maxOpenTrades?: number; dailyLossLimit?: number; skipWideSpread?: boolean; skipElevatedIv?: boolean; entryFallback?: string };
  haltAllowsExits?: boolean;
  optionsEnabled: boolean; optionsProvider: string;
  tradingMode: string; allowLiveAuto: boolean; enabled: boolean; llmAvailable: boolean; halt: any; emitProposals: boolean;
}
export interface ArmedTrade {
  triggerId: string; kind: string; firedTs: number; window: string; entry: number; stop: number; targets: number[]; status: string;
  instrument?: string; contract?: { symbol: string; display?: string; strike?: number; expiry?: string; bid?: number; ask?: number; delta?: number; iv?: number; is0dte?: boolean; warnings?: string[] } | null;
  orderSymbol?: string | null; multiplier?: number; premiumPaid?: number | null;
  reason: string; setupId: string | null; proposalId: string | null; entryOrderId: string | null; limitPrice: number | null;
  qty: number; filledQty: number; avgFill: number | null; remaining: number; trimsDone: number;
  exits: { kind: string; qty: number; orderId: string | null; status: string | null; filledQty: number; price: number | null; error?: string }[];
  realizedPnl: number; unrealizedPnl: number; realizedR: number | null; lastPrice: number | null; errors: string[]; retries: number;
  openedTs: number | null; closedTs: number | null; critic: { kill?: boolean; summary?: string; violations?: string[] } | null;
}
export interface ArmedPlan {
  technique?: string;   // registry id (platform plan phase 0); absent from older servers
  needsAttention?: boolean; attentionReasons?: string[];
  runId: string; symbol: string; planFor: string; status: "armed" | "paused" | "expired" | "disarmed" | string;
  grade?: string | null;
  stopReason?: string; scorecard?: ArmScorecard | null;
  config: ArmConfig; portfolio: { id: string; name?: string; kind?: string; venue?: string; baseCurrency?: string };
  armedAt: string; barsSeen: number; lastBarTs: number | null; barAgeSeconds: number | null; stale: boolean;
  sessionWindowNow: string; lastPrice: number | null; quoteAgeSeconds: number | null;
  triggers: { id: string; kind: string; status: string; entry: number; stop: number; targets: number[]; riskReward: number | null;
    firedTs: number | null; firedWindow: string | null; observedMidday: number; skipped: any[]; conditions: any[]; setupId?: string | null;
    grade?: string | null; gradeScore?: number | null;
    distancePct?: number; distance?: number; windowOpenNow?: boolean;
    direction?: string; levelTouches?: number | null; levelAge?: number | null }[];
  trades: ArmedTrade[]; openPositions: number; realizedPnl: number; fired: any[]; events: { ts: number; event: string; text: string; [k: string]: any }[];
  summary: string;
}
/** GET /api/technique/armed/summary — the phone's "Now" payload. */
export interface ArmedSummaryBase {
  runId: string; symbol: string; status: string; grade?: string | null; mode: string; instrument: string;
  workspace?: string | null; account?: string | null; stale: boolean; lastPrice: number | null;
}
export interface ArmedSummary {
  asOf: number; window: string; windowOpenNow: boolean; haltEngaged: boolean; workspace: string;
  counts: { armed: number; paused: number; inTrade: number; attention: number; watching: number; stoppedToday?: number };
  attention: (ArmedSummaryBase & { reasons: string[]; hasPosition: boolean })[];
  inTrade: (ArmedSummaryBase & {
    triggerId: string; kind: string; direction: string; remaining: number; filledQty: number; entry: number;
    stop: number; nextTarget: number | null; targets: number[]; trimsDone: number; unrealizedPnl: number;
    unrealizedR: number | null; firedTs: number | null; window: string | null; orderSymbol: string | null;
    contract: { symbol?: string; strike?: number; expiry?: string; right?: string; bid?: number; ask?: number } | null;
    tradeStatus: string; realizedPnl: number; multiplier?: number;
  })[];
  timeline: { ts: number; runId: string; symbol: string; kind: string; text: string; pnl?: number | null }[];
  watching: (ArmedSummaryBase & {
    triggers: number;
    nearest: { id: string; kind: string; entry: number; stop: number; distancePct: number | null;
               direction?: string; targets?: number[] };
    size?: { contracts?: number | null; riskPct?: number | null; qty?: number | null };
    window: string; windowOpenNow: boolean; summary: string;
  })[];
  stoppedToday: { runId: string; symbol: string; status?: string; mode?: string; reason: string; realizedPnl?: number | null; at: string | null }[];
  pnl: { realized: number; unrealized: number; lossLimit: number; lossLimitUsedPct: number | null };
}
export interface TechniqueSetup {
  technique?: string;   // registry id (platform plan phase 0); absent from older servers
  id: string; runId: string; symbol: string; setupType: string; direction: string; entry: number; stop: number;
  targets: TechniqueTarget[]; riskReward: number; confidence: number; valid: boolean; rules: string[];
  noTradeReasons: string[]; options: any; proposalId: string | null; status: string; createdAt: string | null;
}
/** GET /api/techniques — the technique registry (platform plan phase 0). */
export interface TechniqueInfo {
  id: string; label: string; version: string; page: string; settingsPrefix?: string; tabs: string[]; description?: string;
}

export interface TechniqueStatus {
  llmAvailable: boolean; model: string; effort: string; thinkingDisplay: string; optionsAvailable: boolean;
  optionsProvider?: string;
  runsToday: number; maxRunsPerDay: number; scanEnabled: boolean; scanSymbols: string[]; running: string[];
  activeRuns?: Record<string, { symbol?: string; stage?: string }>;
  rules: Record<string, string>;
  sessionWindow?: string; enforceSessionWindows?: boolean; structureTfs?: string[]; triggerTf?: string;
  armed?: ArmedPlan[]; sweepsRunning?: string[]; sweepVersion?: string; techniqueSource?: string;
}
export interface ChatBlock { type: string; [k: string]: any }
export interface ChatMessage {
  id: string; threadId: string; seq: number; role: "user" | "assistant"; blocks: ChatBlock[];
  meta: Record<string, any>; createdAt: string | null;
}
export interface ChatThread {
  id: string; title: string; kind: "chat" | "run"; symbol: string | null; runId: string | null;
  archived: boolean; meta: Record<string, any>; createdAt: string | null; updatedAt: string | null;
  messageCount?: number | null; messages?: ChatMessage[]; busy?: boolean;
}
/** Live (in-flight) streaming state for one thread; cleared when the turn ends. */
export interface ChatLive {
  active: boolean; thinking: string; text: string; round: number;
  tools: { id: string; name: string; input: any; status: "running" | "done"; meta?: any; preview?: string }[];
  pass?: string | null;
  passes: { name: string; status: "running" | "done"; thinking: string; text: string; usage?: any; seconds?: number; call?: number }[];
  grounding?: { passed: boolean; checks: GroundingCheck[]; attempt: number } | null;
  facts?: any; error?: string | null;
}
