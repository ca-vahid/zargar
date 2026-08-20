import { create } from "zustand";
import type {
  Brokerages,
  BrokerState,
  Execution,
  HaltState,
  JournalEvent,
  Order,
  Portfolio,
  Position,
  Proposal,
  Quote,
  Settings,
  Signal,
  Snapshot,
  Watchlist,
} from "./types";

export type Page = "dashboard" | "trade" | "inbox" | "portfolios" | "journal" | "settings";

export interface OrderIntentBody {
  portfolio_id: string;
  symbol: string;
  sec_type?: string;
  side: string;
  qty: number;
  order_type: string;
  limit_price?: number | null;
  stop_price?: number | null;
  tif?: string;
  bracket?: {
    take_profit?: number | null;
    stop_loss?: number | null;
    take_profit_pct?: number | null;
    stop_loss_pct?: number | null;
  } | null;
  dry_run?: boolean;
}

interface AppState {
  connected: boolean;
  page: Page;
  activeSymbol: string;
  settings: Settings;
  portfolios: Portfolio[];
  positions: Record<string, Position>; // key portfolioId:symbol:secType
  openOrders: Record<string, Order>;
  recentOrders: Order[];
  executions: Execution[];
  quotes: Record<string, Quote>;
  prevQuotes: Record<string, number>; // last price before latest update, for flash direction
  watchlists: Watchlist[];
  proposals: Proposal[];
  signals: Signal[];
  halt: HaltState;
  broker: BrokerState | null;
  brokerages: Brokerages | null;
  events: JournalEvent[];
  toasts: { id: number; kind: "info" | "error" | "success"; text: string }[];

  setPage: (p: Page) => void;
  setActiveSymbol: (s: string) => void;
  applySnapshot: (s: Snapshot) => void;
  applyBrokerages: (b: Brokerages) => void;
  applyQuotes: (quotes: Quote[]) => void;
  applyOrder: (o: Order) => void;
  applyExecution: (e: Execution) => void;
  applyPosition: (p: Position) => void;
  applyPortfolio: (msg: any) => void;
  applyProposal: (p: Proposal) => void;
  applySignal: (s: Signal) => void;
  applySystem: (msg: any) => void;
  applyEvent: (e: JournalEvent) => void;
  setConnected: (v: boolean) => void;
  setSettings: (s: Settings) => void;
  setWatchlists: (w: Watchlist[]) => void;
  toast: (kind: "info" | "error" | "success", text: string) => void;
  dismissToast: (id: number) => void;
}

const posKey = (p: Position) => `${p.portfolioId}:${p.symbol}:${p.secType}`;
let toastSeq = 1;

export const useStore = create<AppState>((set, get) => ({
  connected: false,
  page: "dashboard",
  activeSymbol: "AAPL",
  settings: {},
  portfolios: [],
  positions: {},
  openOrders: {},
  recentOrders: [],
  executions: [],
  quotes: {},
  prevQuotes: {},
  watchlists: [],
  proposals: [],
  signals: [],
  halt: { engaged: false, reason: "", ts: 0 },
  broker: null,
  brokerages: null,
  events: [],
  toasts: [],

  setPage: (page) => set({ page }),
  setActiveSymbol: (activeSymbol) => set({ activeSymbol }),

  applySnapshot: (s) =>
    set({
      settings: s.settings,
      portfolios: s.portfolios,
      positions: Object.fromEntries(s.positions.map((p) => [posKey(p), p])),
      openOrders: Object.fromEntries(s.openOrders.map((o) => [o.id, o])),
      quotes: s.quotes,
      watchlists: s.watchlists,
      proposals: s.proposals,
      halt: s.halt,
      broker: s.broker,
      brokerages: s.brokerages ?? get().brokerages,
      activeSymbol: get().activeSymbol || s.settings["ui.default_symbol"] || "AAPL",
    }),

  applyBrokerages: (brokerages) => set({ brokerages }),

  applyQuotes: (quotes) =>
    set((st) => {
      const next = { ...st.quotes };
      const prev = { ...st.prevQuotes };
      for (const q of quotes) {
        const old = next[q.symbol];
        if (old) prev[q.symbol] = old.last;
        next[q.symbol] = q;
      }
      return { quotes: next, prevQuotes: prev };
    }),

  applyOrder: (o) =>
    set((st) => {
      const open = { ...st.openOrders };
      const isOpen = ["SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED", "NEW"].includes(o.status);
      if (isOpen) open[o.id] = o;
      else delete open[o.id];
      const recent = [o, ...st.recentOrders.filter((r) => r.id !== o.id)].slice(0, 100);
      return { openOrders: open, recentOrders: recent };
    }),

  applyExecution: (e) =>
    set((st) => ({ executions: [e, ...st.executions].slice(0, 200) })),

  applyPosition: (p) =>
    set((st) => ({ positions: { ...st.positions, [posKey(p)]: p } })),

  applyPortfolio: (msg) =>
    set((st) => ({
      portfolios: st.portfolios.map((p) =>
        p.id === msg.portfolioId
          ? { ...p, cash: msg.cash ?? p.cash, equity: msg.equity ?? p.equity }
          : p,
      ),
    })),

  applyProposal: (p) =>
    set((st) => {
      const rest = st.proposals.filter((x) => x.id !== p.id);
      return { proposals: p.status === "pending" ? [p, ...rest] : rest };
    }),

  applySignal: (sig) =>
    set((st) => ({ signals: [sig, ...st.signals.filter((x) => x.id !== sig.id)].slice(0, 200) })),

  applySystem: (msg) => {
    if (msg.kind === "halt") {
      set({ halt: { engaged: msg.engaged, reason: msg.reason, ts: msg.ts } });
      get().toast(msg.engaged ? "error" : "success",
        msg.engaged ? `Kill switch engaged: ${msg.reason}` : "Kill switch released");
    } else if (msg.kind === "setting") {
      set((st) => ({ settings: { ...st.settings, [msg.key]: msg.value } }));
    } else if (msg.kind === "brokerage") {
      const { kind: _kind, ...brokerages } = msg;
      get().applyBrokerages(brokerages as Brokerages);
    }
  },

  applyEvent: (e) => set((st) => ({ events: [e, ...st.events].slice(0, 500) })),
  setConnected: (connected) => set({ connected }),
  setSettings: (settings) => set({ settings }),
  setWatchlists: (watchlists) => set({ watchlists }),

  toast: (kind, text) => {
    const id = toastSeq++;
    set((st) => ({ toasts: [...st.toasts, { id, kind, text }] }));
    setTimeout(() => get().dismissToast(id), 6000);
  },
  dismissToast: (id) => set((st) => ({ toasts: st.toasts.filter((t) => t.id !== id) })),
}));

// --- selectors -------------------------------------------------------------
export const useQuote = (symbol: string) => useStore((s) => s.quotes[symbol]);
export const usePrevLast = (symbol: string) => useStore((s) => s.prevQuotes[symbol]);

export function positionsFor(state: AppState, portfolioId?: string): Position[] {
  return Object.values(state.positions).filter(
    (p) => (!portfolioId || p.portfolioId === portfolioId) && Math.abs(p.qty) > 1e-9,
  );
}

/** Positions grouped by portfolio id (pure helper — use with useMemo). */
export function groupPositions(positions: Record<string, Position>): Record<string, Position[]> {
  const out: Record<string, Position[]> = {};
  for (const p of Object.values(positions)) {
    if (Math.abs(p.qty) < 1e-9) continue;
    (out[p.portfolioId] ??= []).push(p);
  }
  return out;
}

/**
 * Per-currency net worth across live brokerage accounts + local portfolios.
 * No FX conversion — one total per currency, brokerage accounts counted from
 * their server-side equity (portfolios array carries the same ids, so live
 * portfolios are skipped there to avoid double counting).
 */
export function netWorthByCurrency(
  portfolios: Portfolio[],
  brokerages: Brokerages | null,
): { currency: string; total: number; brokerage: number; local: number }[] {
  const acc: Record<string, { brokerage: number; local: number }> = {};
  const brokeragePids = new Set<string>();
  for (const provider of brokerages?.providers ?? []) {
    for (const account of provider.accounts) {
      brokeragePids.add(account.portfolioId);
      const ccy = (account.currency || "USD").toUpperCase();
      (acc[ccy] ??= { brokerage: 0, local: 0 }).brokerage += account.equity;
    }
  }
  for (const p of portfolios) {
    if (p.kind === "shadow" || brokeragePids.has(p.id)) continue;
    const ccy = (p.baseCurrency || "USD").toUpperCase();
    (acc[ccy] ??= { brokerage: 0, local: 0 }).local += p.equity ?? p.cash;
  }
  return Object.entries(acc)
    .map(([currency, v]) => ({ currency, ...v, total: v.brokerage + v.local }))
    .sort((a, b) => b.total - a.total);
}
