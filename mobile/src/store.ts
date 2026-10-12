import { create } from 'zustand';

import type { AlertItem, AuthUser } from './api/endpoints';
import type { BrokerState, HaltState, Order, Portfolio, Position, Proposal, Quote, Snapshot } from './api/types';

export type Conn = 'idle' | 'connecting' | 'live' | 'down';

/** The server's halt payload also carries explicit per-book pauses. */
export type Halt = HaltState & { pauses?: Record<string, { reason: string; label?: string; ts: number; source?: string }> };

export interface ConfirmRequest {
  title: string;
  body?: string;
  lines?: [string, string][];
  confirmLabel: string;
  danger?: boolean;
  /** ask for fingerprint / device PIN after the tap (every money action does) */
  secure?: boolean;
  resolve: (ok: boolean) => void;
}

export interface Toast { id: number; kind: 'ok' | 'error' | 'info'; text: string }

const OPEN_ORDER = ['NEW', 'SUBMITTED', 'ACCEPTED', 'PARTIALLY_FILLED', 'WORKING'];
export const posKey = (p: Pick<Position, 'portfolioId' | 'symbol'>) => `${p.portfolioId}:${p.symbol}`;

export interface AppState {
  // --- session
  booted: boolean;
  apiUrl: string;
  token: string | null;
  user: AuthUser | null;
  locked: boolean;
  lockEnabled: boolean;
  // --- live
  conn: Conn;
  synced: boolean;
  settings: Record<string, any>;
  portfolios: Portfolio[];
  positions: Record<string, Position>;
  openOrders: Record<string, Order>;
  quotes: Record<string, Quote>;
  halt: Halt;
  proposals: Proposal[];
  broker: BrokerState | null;
  liveAlerts: AlertItem[];
  /** bumps when something the armed summary shows has changed (plan event, halt) */
  armedBump: number;
  // --- ui
  selectedBook: string | null;
  confirm: ConfirmRequest | null;
  toasts: Toast[];

  set: (patch: Partial<AppState>) => void;
  applySnapshot: (s: Snapshot) => void;
  applyMessage: (t: string, d: any) => void;
  applyQuotes: (list: Quote[]) => void;
  toast: (kind: Toast['kind'], text: string) => void;
  dropToast: (id: number) => void;
  reset: () => void;
}

const emptyHalt: Halt = { engaged: false, reason: '', ts: 0, books: {}, pauses: {} };
let toastSeq = 1;

const live = {
  conn: 'idle' as Conn,
  synced: false,
  settings: {},
  portfolios: [] as Portfolio[],
  positions: {} as Record<string, Position>,
  openOrders: {} as Record<string, Order>,
  quotes: {} as Record<string, Quote>,
  halt: emptyHalt,
  proposals: [] as Proposal[],
  broker: null as BrokerState | null,
  liveAlerts: [] as AlertItem[],
  armedBump: 0,
};

export const useStore = create<AppState>((set, get) => ({
  booted: false,
  apiUrl: '',
  token: null,
  user: null,
  locked: false,
  lockEnabled: false,
  ...live,
  selectedBook: null,
  confirm: null,
  toasts: [],

  set: (patch) => set(patch),

  applySnapshot: (s) =>
    set({
      synced: true,
      settings: s.settings ?? {},
      portfolios: s.portfolios ?? [],
      positions: Object.fromEntries((s.positions ?? []).map((p) => [posKey(p), p])),
      openOrders: Object.fromEntries((s.openOrders ?? []).map((o) => [o.id, o])),
      quotes: s.quotes ?? {},
      halt: { ...emptyHalt, ...(s.halt as Halt) },
      proposals: (s.proposals ?? []).filter((p) => p.status === 'pending'),
      broker: s.broker ?? null,
    }),

  applyQuotes: (list) =>
    set((st) => {
      const next = { ...st.quotes };
      for (const quote of list) next[quote.symbol] = quote;
      return { quotes: next };
    }),

  // every delta carries the whole updated object: an upsert, never a diff
  applyMessage: (t, d) => {
    switch (t) {
      case 'snapshot':
        get().applySnapshot(d);
        break;
      case 'order':
        set((st) => {
          const open = { ...st.openOrders };
          if (OPEN_ORDER.includes(d.status)) open[d.id] = d;
          else delete open[d.id];
          return { openOrders: open };
        });
        break;
      case 'position':
        set((st) => ({ positions: { ...st.positions, [posKey(d)]: d } }));
        break;
      case 'portfolio':
        set((st) => ({
          portfolios: st.portfolios.map((p) =>
            p.id === d.portfolioId
              ? {
                  ...p,
                  cash: d.cash ?? p.cash,
                  equity: d.equity ?? p.equity,
                  dayStart: d.dayStart !== undefined ? d.dayStart : p.dayStart,
                  todayPct: d.todayPct !== undefined ? d.todayPct : p.todayPct,
                }
              : p,
          ),
        }));
        break;
      case 'proposal':
        set((st) => {
          const rest = st.proposals.filter((x) => x.id !== d.id);
          return { proposals: d.status === 'pending' ? [d, ...rest] : rest };
        });
        break;
      case 'system':
        if (d.kind === 'halt') {
          set((st) => ({
            halt: { engaged: !!d.engaged, reason: d.reason ?? '', ts: d.ts ?? 0, books: d.books ?? {},
              pauses: d.pauses ?? st.halt.pauses ?? {} },
            armedBump: st.armedBump + 1,
          }));
        } else if (d.kind === 'setting') {
          set((st) => ({ settings: { ...st.settings, [d.key]: d.value } }));
        } else if (d.kind === 'broker') {
          set({ broker: d.broker });
        }
        break;
      case 'technique':
        if (d.kind === 'alert') {
          const item: AlertItem = {
            id: `live-${Date.now()}-${Math.round(Math.random() * 1e6)}`,
            ts: new Date().toISOString(),
            kind: 'alert',
            level: d.level === 'error' || d.level === 'critical' ? 'error' : d.level === 'warning' ? 'warning' : 'info',
            title: d.symbol ? `${d.symbol}` : 'Alert',
            body: String(d.text ?? d.message ?? d.error ?? ''),
            symbol: d.symbol ?? null,
            url: d.runId ? `/armed/${d.runId}` : null,
          };
          set((st) => ({ liveAlerts: [item, ...st.liveAlerts].slice(0, 100), armedBump: st.armedBump + 1 }));
        } else if (d.kind === 'armed') {
          set((st) => ({ armedBump: st.armedBump + 1 }));
        }
        break;
      default:
        break; // execution, signal, event, bar, chat, tipAnalyst: screens fetch what they show
    }
  },

  toast: (kind, text) => {
    const id = toastSeq++;
    set((st) => ({ toasts: [...st.toasts, { id, kind, text }].slice(-3) }));
    setTimeout(() => get().dropToast(id), kind === 'error' ? 6000 : 3500);
  },
  dropToast: (id) => set((st) => ({ toasts: st.toasts.filter((x) => x.id !== id) })),

  reset: () => set({ ...live, selectedBook: null, confirm: null }),
}));

/** Ask the person to confirm an action; resolves false when they back out. */
export function confirmAction(req: Omit<ConfirmRequest, 'resolve'>): Promise<boolean> {
  return new Promise((resolve) => useStore.getState().set({ confirm: { ...req, resolve } }));
}
