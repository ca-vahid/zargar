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
}

export interface Position {
  portfolioId: string;
  symbol: string;
  secType: string;
  qty: number;
  avgCost: number;
  realizedPnl: number;
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
  broker: { feed: string; feedConnected: boolean; ibkrConnected: boolean; mode: string };
}
