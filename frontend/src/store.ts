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
  ChatLive,
  ChatMessage,
  ChatThread,
  TechniqueRun,
  TechniqueSetup,
  ArmedPlan,
} from "./types";

export type Page = "dashboard" | "trade" | "options" | "inbox" | "portfolios" | "journal" | "settings" | "technique" | "armed" | "watchlists";

export interface OptionsPrefill { side?: "BUY" | "SELL"; qty?: number; portfolioId?: string }

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
  driftWarnings: { portfolioId: string; name: string; lossPct: number; ts: string }[];
  chgDollar: boolean; // day-change display: false = %, true = $ (global, persisted)
  journalGroup: string | null; // pre-filter applied when the Journal page opens
  portfoliosFocus: string | null; // provider connectionId to scroll to on Portfolios
  ticketPortfolioId: string | null; // one-shot account preselect for the order ticket
  // --- options page ---
  optionsUnderlying: string;
  optionsExpiry: string | null;
  optionsContract: string | null;   // canonical OCC symbol loaded in the option ticket
  optionsPrefill: OptionsPrefill | null; // one-shot ticket prefill (close from blotter, technique pick)
  events: JournalEvent[];
  toasts: { id: number; kind: "info" | "error" | "success"; text: string }[];
  alerts: { ts: number; level: string; text: string; runId?: string | null }[]; // persisted plan alerts (Now screen)
  // --- technique / chat ---
  techniqueRuns: TechniqueRun[];            // most recent first
  techniqueSetups: TechniqueSetup[];
  techniqueTab: "analyse" | "chat" | "history" | "backtest" | "validation" | "armed";
  techniqueFocusRunId: string | null;
  // bumped when an outcome / review lands for a run so open views refetch it
  techniqueRunBumps: Record<string, number>;
  techniqueArmed: ArmedPlan[];
  techniqueSweepBump: number;
  chatThreads: ChatThread[];
  chatActiveThreadId: string | null;
  chatMessages: Record<string, ChatMessage[]>;   // threadId -> messages (loaded threads)
  chatLive: Record<string, ChatLive>;            // threadId -> streaming state

  setPage: (p: Page) => void;
  setActiveSymbol: (s: string) => void;
  openJournal: (group: string) => void;
  clearJournalGroup: () => void;
  openPortfolios: (focus?: string) => void;
  clearPortfoliosFocus: () => void;
  openTrade: (symbol: string, portfolioId?: string) => void;
  clearTicketPortfolio: () => void;
  openOptions: (args: { underlying?: string; expiry?: string | null; contract?: string | null } & OptionsPrefill) => void;
  setOptionsView: (v: { underlying?: string; expiry?: string | null; contract?: string | null }) => void;
  clearOptionsPrefill: () => void;
  toggleChgMode: () => void;
  dismissDrift: (portfolioId: string) => void;
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
  // --- technique / chat ---
  applyTechnique: (msg: any) => void;
  applyChat: (msg: { threadId: string; runId?: string | null; event: any }) => void;
  setTechniqueRuns: (runs: TechniqueRun[]) => void;
  setTechniqueSetups: (s: TechniqueSetup[]) => void;
  setTechniqueTab: (t: "analyse" | "chat" | "history" | "backtest" | "validation" | "armed") => void;
  setTechniqueArmed: (a: ArmedPlan[]) => void;
  openTechniqueRun: (runId: string) => void;
  armedFocusRunId: string | null;
  openArmedPlan: (runId: string) => void;
  clearArmedFocus: () => void;
  setTechniqueFocusRun: (runId: string | null) => void;
  setChatThreads: (t: ChatThread[]) => void;
  setChatThread: (t: ChatThread) => void;
  setChatActive: (id: string | null) => void;
  openTechniqueChat: (threadId: string) => void;
  seedChatLive: (threadId: string, live: { passes?: any[]; grounding?: any; facts?: any }) => void;
  applyRoute: (r: { page: Page; techniqueTab?: string; runId?: string | null; threadId?: string | null; armedRunId?: string | null;
    optionsUnderlying?: string; optionsExpiry?: string | null; optionsContract?: string | null }) => void;
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
  driftWarnings: [],
  chgDollar: localStorage.getItem("zargar_chg_dollar") === "1",
  journalGroup: null,
  portfoliosFocus: null,
  ticketPortfolioId: null,
  optionsUnderlying: localStorage.getItem("zargar_options_underlying") || "SPY",
  optionsExpiry: null,
  optionsContract: null,
  optionsPrefill: null,
  events: [],
  toasts: [],
  alerts: [],
  techniqueRuns: [],
  techniqueSetups: [],
  techniqueTab: "validation",
  techniqueFocusRunId: null,
  armedFocusRunId: null,
  techniqueRunBumps: {},
  techniqueArmed: [],
  techniqueSweepBump: 0,
  chatThreads: [],
  chatActiveThreadId: null,
  chatMessages: {},
  chatLive: {},

  setPage: (page) => set({ page }),
  setActiveSymbol: (activeSymbol) => set({ activeSymbol }),
  openJournal: (group) => set({ page: "journal", journalGroup: group }),
  clearJournalGroup: () => set({ journalGroup: null }),
  openPortfolios: (focus) => set({ page: "portfolios", portfoliosFocus: focus ?? null }),
  clearPortfoliosFocus: () => set({ portfoliosFocus: null }),
  openTrade: (symbol, portfolioId) =>
    set({ page: "trade", activeSymbol: symbol, ticketPortfolioId: portfolioId ?? null }),
  clearTicketPortfolio: () => set({ ticketPortfolioId: null }),
  openOptions: ({ underlying, expiry, contract, side, qty, portfolioId }) =>
    set((st) => {
      const und = (underlying ?? (contract ? contract.replace(/\s+/g, "").match(/^[A-Z]{1,6}/)?.[0] : null)
        ?? st.optionsUnderlying).toUpperCase();
      localStorage.setItem("zargar_options_underlying", und);
      const changed = und !== st.optionsUnderlying;
      return {
        page: "options",
        optionsUnderlying: und,
        optionsExpiry: expiry !== undefined ? expiry : changed ? null : st.optionsExpiry,
        optionsContract: contract !== undefined ? contract : changed ? null : st.optionsContract,
        optionsPrefill: side || qty || portfolioId ? { side, qty, portfolioId } : null,
      };
    }),
  setOptionsView: (v) =>
    set((st) => {
      const und = (v.underlying ?? st.optionsUnderlying).toUpperCase();
      if (v.underlying) localStorage.setItem("zargar_options_underlying", und);
      return {
        optionsUnderlying: und,
        optionsExpiry: v.expiry !== undefined ? v.expiry : st.optionsExpiry,
        optionsContract: v.contract !== undefined ? v.contract : st.optionsContract,
      };
    }),
  clearOptionsPrefill: () => set({ optionsPrefill: null }),
  toggleChgMode: () =>
    set((st) => {
      const next = !st.chgDollar;
      localStorage.setItem("zargar_chg_dollar", next ? "1" : "0");
      return { chgDollar: next };
    }),
  dismissDrift: (portfolioId) =>
    set((st) => ({ driftWarnings: st.driftWarnings.filter((d) => d.portfolioId !== portfolioId) })),

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
          ? {
              ...p,
              cash: msg.cash ?? p.cash,
              equity: msg.equity ?? p.equity,
              todayPct: msg.todayPct !== undefined ? msg.todayPct : p.todayPct,
            }
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
    } else if (msg.kind === "broker") {
      set({ broker: msg.broker });
    } else if (msg.kind === "drift") {
      set((st) => ({
        driftWarnings: [
          { portfolioId: msg.portfolioId, name: msg.name, lossPct: msg.lossPct, ts: msg.ts },
          ...st.driftWarnings.filter((d) => d.portfolioId !== msg.portfolioId),
        ],
      }));
    }
  },

  applyEvent: (e) => set((st) => ({ events: [e, ...st.events].slice(0, 500) })),
  setConnected: (connected) => set({ connected }),
  setSettings: (settings) => set({ settings }),
  setWatchlists: (watchlists) => set({ watchlists }),

  // --- technique / chat -----------------------------------------------------
  setTechniqueRuns: (techniqueRuns) => set({ techniqueRuns }),
  setTechniqueSetups: (techniqueSetups) => set({ techniqueSetups }),
  setTechniqueTab: (techniqueTab) => set({ techniqueTab }),
  setTechniqueArmed: (techniqueArmed) => set({ techniqueArmed }),
  applyRoute: (r) =>
    set((st) => ({
      page: r.page,
      armedFocusRunId: r.armedRunId ?? st.armedFocusRunId,
      techniqueTab: (r.techniqueTab as any) ?? st.techniqueTab,
      techniqueFocusRunId: r.runId ?? (r.page === "technique" ? null : st.techniqueFocusRunId),
      chatActiveThreadId: r.threadId ?? st.chatActiveThreadId,
      optionsUnderlying: r.optionsUnderlying ?? st.optionsUnderlying,
      optionsExpiry: r.page === "options" ? (r.optionsExpiry ?? (r.optionsUnderlying && r.optionsUnderlying !== st.optionsUnderlying ? null : st.optionsExpiry)) : st.optionsExpiry,
      optionsContract: r.page === "options" ? (r.optionsContract ?? (r.optionsUnderlying && r.optionsUnderlying !== st.optionsUnderlying ? null : st.optionsContract)) : st.optionsContract,
    })),
  openTechniqueRun: (runId) => set({ page: "technique", techniqueTab: "analyse", techniqueFocusRunId: runId }),
  openArmedPlan: (runId) => set({ page: "armed", armedFocusRunId: runId }),
  clearArmedFocus: () => set({ armedFocusRunId: null }),
  setTechniqueFocusRun: (techniqueFocusRunId) => set({ techniqueFocusRunId }),
  setChatThreads: (chatThreads) => set({ chatThreads }),
  setChatThread: (t) =>
    set((st) => ({
      chatThreads: [t, ...st.chatThreads.filter((x) => x.id !== t.id)],
      chatMessages: t.messages ? { ...st.chatMessages, [t.id]: t.messages } : st.chatMessages,
    })),
  setChatActive: (chatActiveThreadId) => set({ chatActiveThreadId }),
  openTechniqueChat: (threadId) =>
    set({ page: "technique", techniqueTab: "chat", chatActiveThreadId: threadId }),
  seedChatLive: (threadId, live) =>
    set((st) => {
      const prev = st.chatLive[threadId];
      if (prev && prev.passes.length > 0) return {};
      const base: ChatLive = prev ?? {
        active: true, thinking: "", text: "", round: 0, tools: [], passes: [], pass: null,
        grounding: null, facts: null, error: null,
      };
      const passes = (live.passes ?? []).map((p: any) => ({
        name: p.name, status: p.status, thinking: p.thinking ?? "", text: p.text ?? "",
        usage: p.usage, seconds: p.seconds, call: p.call,
      }));
      const running = passes.find((p: any) => p.status === "running");
      return { chatLive: { ...st.chatLive, [threadId]: {
        ...base, active: true, passes, pass: running?.name ?? null,
        grounding: live.grounding ?? base.grounding, facts: live.facts ?? base.facts } } };
    }),

  applyTechnique: (msg) => {
    if (msg.kind === "run" || msg.kind === "run_done") {
      const run = msg.run as TechniqueRun;
      set((st) => ({
        techniqueRuns: [run, ...st.techniqueRuns.filter((r) => r.id !== run.id)].slice(0, 300),
      }));
      if (msg.kind === "run_done") {
        const r = msg.run as TechniqueRun;
        if (r.status === "failed") {
          const raw = String(msg.error ?? r.error ?? "");
          const friendly = raw.includes("Invalid JSON") || raw.includes("validation error")
            ? "the model's reply came back malformed — run it again from History"
            : raw.slice(0, 140);
          get().toast("error", `${r.symbol}: analysis failed — ${friendly}`);
        }
        else if (r.verdict === "setup") get().toast("success", `${r.symbol}: ${r.setupType} setup (conf ${(r.confidence ?? 0).toFixed(2)})`);
      }
    } else if (msg.kind === "setup") {
      set((st) => ({ techniqueSetups: [msg.setup, ...st.techniqueSetups].slice(0, 300) }));
    } else if (msg.kind === "outcome") {
      set((st) => ({
        techniqueRuns: st.techniqueRuns.map((r) => r.id === msg.runId ? { ...r, outcomes: msg.outcomes } : r),
        techniqueRunBumps: { ...st.techniqueRunBumps, [msg.runId]: (st.techniqueRunBumps[msg.runId] ?? 0) + 1 },
      }));
    } else if (msg.kind === "review") {
      const rv = msg.review;
      set((st) => ({
        techniqueRuns: st.techniqueRuns.map((r) => r.id === msg.runId ? {
          ...r, reviewCount: (r.reviewCount ?? 0) + 1,
          lastReview: { reviewVerdict: rv.reviewVerdict, rootCauseStage: rv.rootCauseStage, createdAt: rv.createdAt, reviewer: rv.reviewer },
        } : r),
        techniqueRunBumps: { ...st.techniqueRunBumps, [msg.runId]: (st.techniqueRunBumps[msg.runId] ?? 0) + 1 },
      }));
    } else if (msg.kind === "armed") {
      const ap = msg.armed as ArmedPlan;
      set((st) => ({
        techniqueArmed: ap.status === "disarmed" || ap.status === "expired"
          ? st.techniqueArmed.filter((a) => a.runId !== ap.runId)
          : [ap, ...st.techniqueArmed.filter((a) => a.runId !== ap.runId)].sort((a, b) => a.symbol.localeCompare(b.symbol)),
      }));
      if (msg.event === "fired") get().toast("success", `${ap.symbol}: planned trigger fired (${ap.config.mode})`);
      else if (msg.event === "armed") get().toast("info", `${ap.symbol} plan armed for ${ap.planFor} — ${ap.config.mode} on ${ap.portfolio.name ?? ap.portfolio.id}`);
      else if (msg.event === "position_open") get().toast("success", `${ap.symbol}: position open`);
      else if (msg.event === "exit_fill" || msg.event === "exit_submit") { /* quiet */ }
      else if (msg.event === "entry_rejected" || msg.event === "entry_error" || msg.event === "exit_failed") get().toast("error", `${ap.symbol}: ${msg.event.replace(/_/g, " ")} — see Armed tab`);
    } else if (msg.kind === "alert") {
      get().toast(msg.level === "warning" ? "info" : "error", `\u26a0 ${msg.text}`);
      set((st) => ({ alerts: [{ ts: Date.now(), level: String(msg.level ?? "critical"), text: String(msg.text ?? ""), runId: msg.runId ?? null }, ...st.alerts].slice(0, 50) }));
    } else if (msg.kind === "disarmed") {
      set((st) => ({ techniqueArmed: st.techniqueArmed.filter((a) => a.runId !== msg.runId) }));
    } else if (msg.kind === "sweep" || msg.kind === "sweep_progress") {
      set((st) => ({ techniqueSweepBump: st.techniqueSweepBump + 1 }));
      if (msg.kind === "sweep" && msg.sweep?.status === "done") get().toast("success", `Walk-forward sweep finished (${msg.sweep.summary?.sessions ?? 0} sessions)`);
    } else if (msg.kind === "scan") {
      get().toast("info", `Scan started ${msg.started?.length ?? 0} run(s)`);
    }
  },

  applyChat: ({ threadId, event }) => {
    const e = event;
    const t = e.type as string;
    if (t === "thread") {
      get().setChatThread(e.thread);
      return;
    }
    if (t === "message") {
      const m = e.message as ChatMessage;
      set((st) => {
        const cur = st.chatMessages[threadId] ?? [];
        if (cur.some((x) => x.id === m.id)) return {};
        const live = st.chatLive[threadId];
        // a persisted assistant message supersedes the streamed buffer for that turn
        const nextLive = live && m.role === "assistant"
          ? { ...live, thinking: "", text: "" } : live;
        return {
          chatMessages: { ...st.chatMessages, [threadId]: [...cur, m].sort((a, b) => a.seq - b.seq) },
          chatLive: nextLive ? { ...st.chatLive, [threadId]: nextLive } : st.chatLive,
          chatThreads: st.chatThreads.map((th) => th.id === threadId
            ? { ...th, messageCount: (th.messageCount ?? 0) + 1, updatedAt: m.createdAt } : th),
        };
      });
      return;
    }
    set((st) => {
      const prev: ChatLive = st.chatLive[threadId] ?? {
        active: false, thinking: "", text: "", round: 0, tools: [], passes: [], pass: null,
        grounding: null, facts: null, error: null,
      };
      let live: ChatLive = prev;
      switch (t) {
        case "turn_start":
          live = { ...prev, active: true, thinking: "", text: "", tools: [], error: null }; break;
        case "turn_done":
          live = { ...prev, active: false, error: e.error ?? null, pass: null }; break;
        case "pass_start": {
          const passes = [...prev.passes.filter((p) => p.name !== e.pass),
            { name: e.pass, status: "running" as const, thinking: "", text: "", call: e.call }];
          live = { ...prev, active: true, pass: e.pass, passes, thinking: "", text: "" }; break;
        }
        case "pass_done": {
          const passes = prev.passes.map((p) => p.name === e.pass
            ? { ...p, status: "done" as const, usage: e.usage, seconds: e.seconds } : p);
          live = { ...prev, passes, pass: null }; break;
        }
        case "grounding":
          live = { ...prev, grounding: { passed: e.passed, checks: e.checks, attempt: e.attempt } }; break;
        case "facts":
          live = { ...prev, facts: { keyLevels: e.keyLevels, volume: e.volume, trend: e.trend } }; break;
        case "run_done":
          live = { ...prev, active: false, pass: null }; break;
        case "thinking_delta": {
          const passes = prev.pass
            ? prev.passes.map((p) => p.name === prev.pass ? { ...p, thinking: p.thinking + e.text } : p)
            : prev.passes;
          live = { ...prev, active: true, thinking: prev.thinking + e.text, passes }; break;
        }
        case "text_delta": {
          const passes = prev.pass
            ? prev.passes.map((p) => p.name === prev.pass ? { ...p, text: p.text + e.text } : p)
            : prev.passes;
          live = { ...prev, active: true, text: prev.text + e.text, passes }; break;
        }
        case "tool_running":
          live = { ...prev, thinking: "", text: "",
            tools: [...prev.tools.filter((x) => x.id !== e.id),
              { id: e.id, name: e.name, input: e.input, status: "running" as const }] }; break;
        case "tool_done":
          live = { ...prev, tools: prev.tools.map((x) => x.id === e.id
            ? { ...x, status: "done" as const, meta: e.meta, preview: e.preview } : x) }; break;
        case "message_done":
          live = { ...prev, round: (e.round ?? prev.round) }; break;
        default:
          return {};
      }
      return { chatLive: { ...st.chatLive, [threadId]: live } };
    });
  },

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
