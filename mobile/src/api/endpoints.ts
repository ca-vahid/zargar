import { request } from './client';
import type {
  ArmedPlan,
  ArmedSummary,
  Execution,
  JournalEvent,
  Ledger,
  ManagedPosition,
  Order,
  Portfolio,
  Position,
  Proposal,
  ScoutCandidate,
  ScoutDossier,
  ScoutLane,
  Signal,
  Snapshot,
} from './types';

export interface AuthUser { email: string; name?: string | null; picture?: string | null; provider?: string }
export interface AuthConfig { required: boolean; googleClientId: string | null; sessionDays: number }
export interface Health {
  ok: boolean; started: boolean; version: string; build?: string;
  local?: { armed?: number; clockSkewMs?: number;
    delivery?: { eventLoopLagMs?: number; hostFreeGb?: number; loopStalls?: number } };
}
export interface IntakeLiveness {
  ok: boolean; state: string; reasons: string[]; warnings?: string[];
  gateway?: { state?: string; lastMessageAt?: string | null; watched?: number };
}
/** GET /api/alerts — recent alert-like journal items (backend PR "mobile-backend"). */
export interface AlertItem {
  id: string; ts: string; kind: string; level: 'info' | 'warning' | 'error';
  title: string; body: string; symbol?: string | null; url?: string | null;
}
export type ChartBar = [number, number, number, number, number, number];
export interface ChartData { symbol: string; tf: string; range: string | null; source: string; bars: ChartBar[] }
export type PortfolioWithPositions = Portfolio & { positions?: Position[] };

const q = (params: Record<string, string | number | boolean | undefined | null>) => {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join('&')}` : '';
};

export const api = {
  // --- sign-in
  authConfig: () => request<AuthConfig>('GET', '/api/auth/config'),
  authMe: () => request<{ required: boolean; user: AuthUser | null }>('GET', '/api/auth/me'),
  /** `client: "phone"` is signed into the session by the server (ignored by older servers). */
  authGoogle: (credential: string) =>
    request<{ user: AuthUser; token: string }>('POST', '/api/auth/google', { credential, client: 'phone' }),

  // --- system
  health: () => request<Health>('GET', '/api/health'),
  state: () => request<Snapshot>('GET', '/api/state'),
  intakeLiveness: () => request<IntakeLiveness>('GET', '/api/tip/intake/liveness'),
  alerts: (limit = 60) => request<AlertItem[]>('GET', `/api/alerts${q({ limit })}`),
  events: (type: string, limit = 50) => request<JournalEvent[]>('GET', `/api/events${q({ type, limit })}`),

  // --- money
  portfolios: () => request<PortfolioWithPositions[]>('GET', '/api/portfolios'),
  equity: (pid: string, opts: { since?: number; points?: number } = {}) =>
    request<[number, number][]>('GET', `/api/portfolios/${pid}/equity${q({ since: opts.since, points: opts.points ?? 300 })}`),
  managedPositions: (status = 'open') => request<ManagedPosition[]>('GET', `/api/positions/managed${q({ status })}`),
  orders: (portfolio: string, limit = 30) => request<Order[]>('GET', `/api/orders${q({ portfolio, limit })}`),
  executions: (portfolio: string, limit = 30) => request<Execution[]>('GET', `/api/executions${q({ portfolio, limit })}`),
  ledger: (workspace: 'practice' | 'live', scope?: string, days = 30) =>
    request<Ledger>('GET', `/api/desk/ledger${q({ days, workspace, scope })}`),
  /** `range` asks for real exchange history; without it the server answers from its own short store */
  chart: (symbol: string, tf: string, range?: string, limit = 200) =>
    request<ChartData>('GET', `/api/chart/${encodeURIComponent(symbol)}${q({ tf, range, limit })}`),
  searchSymbols: (text: string) =>
    request<{ results: { symbol: string; name: string; exchange: string; type: string }[] }>(
      'GET', `/api/symbols/search${q({ q: text })}`),

  // --- actions (each one is confirmed on the phone before it is sent)
  halt: (reason: string) => request<unknown>('POST', '/api/halt', { reason }),
  resume: () => request<unknown>('POST', '/api/resume'),
  pauseBook: (pid: string, reason: string) =>
    request<unknown>('POST', `/api/portfolios/${pid}/pause`, { reason, label: 'phone' }),
  unpauseBook: (pid: string) => request<unknown>('POST', `/api/portfolios/${pid}/unpause`),
  closePosition: (id: string, fraction = 1.0) =>
    request<unknown>('POST', `/api/positions/managed/${id}/close${q({ fraction })}`),
  cancelOrder: (id: string) => request<unknown>('POST', `/api/orders/${id}/cancel`),

  // --- tips
  proposals: (all = false, limit = 60) => request<Proposal[]>('GET', `/api/proposals${q({ limit, all: all || undefined })}`),
  /** refresh quotes and re-run every execution check — never an order */
  revalidateProposal: (id: string) => request<Proposal>('POST', `/api/proposals/${id}/revalidate`),
  approveProposal: (id: string, expected: string | null, half = false) =>
    request<Proposal>('POST', `/api/proposals/${id}/approve`, { half, expected, override: null }),
  rejectProposal: (id: string) => request<Proposal>('POST', `/api/proposals/${id}/reject`),
  signals: (limit = 50) => request<Signal[]>('GET', `/api/signals${q({ limit })}`),

  // --- armed plans
  armedSummary: () => request<ArmedSummary>('GET', '/api/technique/armed/summary'),
  armed: () => request<ArmedPlan[]>('GET', '/api/technique/armed?slim=1'),
  armedExit: (runId: string, trigger?: string | null) =>
    request<ArmedPlan>('POST', `/api/technique/armed/${runId}/exit`, { trigger: trigger ?? null }),
  armedPause: (runId: string) => request<ArmedPlan>('POST', `/api/technique/armed/${runId}/pause`),
  armedResume: (runId: string) => request<ArmedPlan>('POST', `/api/technique/armed/${runId}/resume`),

  // --- scout (research only)
  scoutCandidates: (days = 14) => request<ScoutCandidate[]>('GET', `/api/scout/candidates${q({ days })}`),
  scoutLanes: () => request<ScoutLane[]>('GET', '/api/scout/lanes'),
  scoutDossiers: (limit = 30) => request<ScoutDossier[]>('GET', `/api/scout/dossiers${q({ limit })}`),
  scoutDossier: (id: string) => request<ScoutDossier>('GET', `/api/scout/dossiers/${id}`),
  scoutDossierRequest: (ticker: string, refresh = false) =>
    request<ScoutDossier>('POST', '/api/scout/dossiers', { ticker, refresh }),

  // --- push (Expo token; backend PR "mobile-backend")
  pushRegister: (token: string, label: string) =>
    request<{ ok: boolean; subscriptions: number }>('POST', '/api/push/expo', { token, label }),
  pushUnregister: (token: string) =>
    request<{ ok: boolean }>('DELETE', `/api/push/expo${q({ token })}`),
  pushTest: () => request<{ sent: number }>('POST', '/api/push/test'),
};
