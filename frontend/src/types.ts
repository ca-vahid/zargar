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
  entryPrice: number | null;
  targetPrice: number | null;
  stopPrice: number | null;
  timeframe: string;
  thesisSummary: string | null;
  confidence: string;
  isActionable: boolean;
  verification: { passed: boolean; checks: { name: string; passed: boolean; detail: string }[] } | null;
  status: string;
  createdAt: string;
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
export interface TechniqueRun {
  id: string; threadId: string | null; symbol: string; asOf: number | null; primaryTf: string;
  mode: string; trigger: string; status: "running" | "done" | "failed";
  verdict: string | null; setupType: string | null; confidence: number | null; grounded: boolean | null;
  analysis?: TechniqueContract | null; groundingPassed?: boolean | null;
  images: Record<string, string>; usage: Record<string, number>; error: string | null;
  llm: Record<string, string>; createdAt: string | null; finishedAt: string | null;
  options?: any; seconds?: number;
  facts?: any; result?: { analysis: TechniqueContract | null; grounding: { passed: boolean; checks: GroundingCheck[] };
    passes: { name: string; parsed: any; usage: any; seconds: number }[]; mode: string; error: string | null;
    usage: any; options?: any; seconds?: number };
  setups?: TechniqueSetup[];
}
export interface TechniqueSetup {
  id: string; runId: string; symbol: string; setupType: string; direction: string; entry: number; stop: number;
  targets: TechniqueTarget[]; riskReward: number; confidence: number; valid: boolean; rules: string[];
  noTradeReasons: string[]; options: any; proposalId: string | null; status: string; createdAt: string | null;
}
export interface TechniqueStatus {
  llmAvailable: boolean; model: string; effort: string; thinkingDisplay: string; optionsAvailable: boolean;
  optionsProvider?: string;
  runsToday: number; maxRunsPerDay: number; scanEnabled: boolean; scanSymbols: string[]; running: string[];
  rules: Record<string, string>;
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
