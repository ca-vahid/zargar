import type { OrderIntentBody } from "../store";
import { clientKind } from "./viewport";

let authToken = localStorage.getItem("zargar_token") || "";
// phone sign-in handoff: open https://host/#token=... once, the token is kept in
// this browser and scrubbed from the address bar (never lands in history/logs)
try {
  const m = /[#&]token=([^&]+)/.exec(window.location.hash);
  if (m) {
    authToken = decodeURIComponent(m[1]);
    localStorage.setItem("zargar_token", authToken);
    window.history.replaceState({}, "", window.location.pathname + window.location.search);
  }
} catch { /* ignore */ }

export function setAuthToken(token: string) {
  authToken = token;
  localStorage.setItem("zargar_token", token);
}

export function getAuthToken() {
  return authToken;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  headers["X-Zargar-Client"] = clientKind(); // phone => exit-only safety policy server-side
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
  const resp = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (resp.status === 401 && !path.startsWith("/api/auth/")) {
    // the session ended (or never existed): show the sign-in screen
    const { useStore } = await import("../store");
    useStore.getState().setAuth({ checked: true, required: true, user: null });
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const data = await resp.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),

  placeOrder: (intent: OrderIntentBody) => request<any>("POST", "/api/orders", intent),
  cancelOrder: (id: string) => request<any>("POST", `/api/orders/${id}/cancel`),
  halt: (reason: string) => request<any>("POST", "/api/halt", { reason }),
  resume: () => request<any>("POST", "/api/resume"),
  patchSettings: (values: Record<string, unknown>) =>
    request<Record<string, unknown>>("PATCH", "/api/settings", values),
  approveProposal: (id: string, half = false) =>
    request<any>("POST", `/api/proposals/${id}/approve`, { half }),
  rejectProposal: (id: string) => request<any>("POST", `/api/proposals/${id}/reject`),
  ingestManual: (text: string, source_name: string, subject: string, imageDataUrl?: string) =>
    request<any>("POST", "/api/ingest/manual",
      imageDataUrl ? { text, source_name, subject, imageDataUrl } : { text, source_name, subject }),
  sourceScorecards: () =>
    request<import("../types").SourceScorecard[]>("GET", "/api/signals/sources"),
  sourceNames: () => request<string[]>("GET", "/api/signals/source-names"),
  armTipSignal: (sid: string, body?: { portfolioId?: string; mode?: string }) =>
    request<any>("POST", `/api/signals/${sid}/arm`, body ?? {}),
  getBrokerages: () => request<import("../types").Brokerages>("GET", "/api/brokerages"),
  orderImpact: (body: { portfolio_id: string; symbol: string; side: string; qty: number;
    order_type?: string; limit_price?: number | null }) =>
    request<{ estimatedCommission?: number; forexFees?: number;
      remainingCash?: number | null; remainingCashCurrency?: string | null;
      error?: string }>(
      "POST", "/api/brokerages/impact", body),
  refreshBrokerages: () =>
    request<import("../types").Brokerages>("POST", "/api/brokerages/refresh"),
  // --- sign-in ---
  authConfig: () => request<{ required: boolean; googleClientId: string | null; sessionDays: number;
    providers: { id: string; label: string; enabled: boolean; note?: string | null }[] }>("GET", "/api/auth/config"),
  authMe: () => request<{ required: boolean; user: import("../store").AuthUser | null }>("GET", "/api/auth/me"),
  authGoogle: (credential: string) =>
    request<{ user: import("../store").AuthUser; token: string }>("POST", "/api/auth/google", { credential }),
  authLogout: () => request<{ ok: boolean }>("POST", "/api/auth/logout"),
  pushVapid: () => request<{ available: boolean; publicKey: string | null; subscriptions: number }>("GET", "/api/push/vapid"),
  pushSubscribe: (body: { endpoint: string; keys: Record<string, string>; label?: string }) =>
    request<{ ok: boolean; subscriptions: number }>("POST", "/api/push/subscribe", body),
  pushUnsubscribe: (endpoint: string) =>
    request<{ ok: boolean; subscriptions: number }>("DELETE", `/api/push/subscribe?endpoint=${encodeURIComponent(endpoint)}`),
  pushTest: () => request<{ sent: number }>("POST", "/api/push/test"),
  searchSymbols: (q: string) =>
    request<{ results: { symbol: string; name: string; exchange: string; type: string }[] }>(
      "GET", `/api/symbols/search?q=${encodeURIComponent(q)}`),
  watchSymbol: (symbol: string) => request<any>("POST", "/api/watch", { symbol }),
  updateWatchlist: (id: string, name: string, symbols: string[]) =>
    request<import("../types").Watchlist>("PUT", `/api/watchlists/${id}`, { name, symbols }),
  // --- options ---
  optionsExpiries: (underlying: string) =>
    request<import("../types").OptionExpiries>("GET", `/api/options/${encodeURIComponent(underlying)}/expiries`),
  optionsChain: (underlying: string, expiry: string) =>
    request<import("../types").OptionChain>("GET",
      `/api/options/${encodeURIComponent(underlying)}/chain?expiry=${encodeURIComponent(expiry)}`),
  optionsQuote: (occ: string) =>
    request<import("../types").OptionContract>("GET", `/api/options/quote/${encodeURIComponent(occ)}`),
  optionsImpact: (body: { portfolio_id: string; symbol: string; side: string; qty: number;
    order_type?: string; limit_price?: number | null }) =>
    request<import("../types").OptionImpact>("POST", "/api/options/impact", body),
  optionsCapabilities: () =>
    request<{ accounts: import("../types").OptionCapability[] }>("GET", "/api/options/capabilities"),
  optionsExpiring: (days = 2) =>
    request<any[]>("GET", `/api/options/expiring?days=${days}`),
  // --- technique ---
  techniques: () => request<import("../types").TechniqueInfo[]>("GET", "/api/techniques"),
  techniqueStatus: () => request<import("../types").TechniqueStatus>("GET", "/api/technique/status"),
  techniqueUniverse: () => request<{ date: string | null; symbols: string[]; provenance: Record<string, string>; counts: { core: number; extra: number; auto: number }; autoSource?: string | null }>("GET", "/api/technique/universe"),
  techniqueUniverseRefresh: () => request<{ date: string | null; symbols: string[]; provenance: Record<string, string>; counts: { core: number; extra: number; auto: number }; autoSource?: string | null }>("POST", "/api/technique/universe/refresh"),
  techniquePlan: (body: { symbol: string; asOf?: number | null; tf?: string; withVision?: boolean | null; wait?: boolean }) =>
    request<import("../types").TechniqueRun>("POST", "/api/technique/plan", body),
  techniqueSweeps: () => request<import("../types").TechniqueSweep[]>("GET", "/api/technique/walkforward"),
  techniqueArmedExit: (runId: string, trigger?: string | null) =>
    request<import("../types").ArmedPlan>("POST", `/api/technique/armed/${runId}/exit`, { trigger: trigger ?? null }),
  techniqueStartSheet: (body: { symbols: string[]; label?: string }) => request<import("../types").TechniqueSweep>("POST", "/api/technique/walkforward/next", body),
  techniqueScoreSheet: (id: string) => request<import("../types").TechniqueSweep>("POST", `/api/technique/walkforward/${id}/score`),
  techniqueRenameSweep: (id: string, label: string) => request<import("../types").TechniqueSweep>("PATCH", `/api/technique/walkforward/${id}`, { label }),
  techniqueSweep: (id: string, rows = true) => request<import("../types").TechniqueSweep>("GET", `/api/technique/walkforward/${id}?rows=${rows}`),
  techniqueStartSweep: (body: { symbols: string[]; start: string; end: string; structureTfs?: string[]; triggerTf?: string; includeInvalid?: boolean; label?: string }) =>
    request<import("../types").TechniqueSweep>("POST", "/api/technique/walkforward", body),
  techniquePromote: (id: string, body: { symbol: string; session: string; withVision?: boolean; wait?: boolean }) =>
    request<import("../types").TechniqueRun>("POST", `/api/technique/walkforward/${id}/promote`, body),
  techniqueArmed: (slim = false) => request<import("../types").ArmedPlan[]>("GET", `/api/technique/armed${slim ? "?slim=1" : ""}`),
  techniqueArmedSummary: () => request<import("../types").ArmedSummary>("GET", "/api/technique/armed/summary"),
  techniqueArmedDetail: (runId: string) => request<import("../types").ArmedPlan>("GET", `/api/technique/armed/${runId}`),
  techniqueArmedAudit: (runId: string) => request<any[]>("GET", `/api/technique/armed/${runId}/audit`),
  techniqueArmedHistory: () => request<any[]>("GET", "/api/technique/armed/history"),
  techniqueArmOptions: () => request<import("../types").ArmOptions>("GET", "/api/technique/armed/options"),
  techniqueArmPreflight: (runId: string, body?: import("../types").ArmRequest) =>
    request<import("../types").ArmPreflight>("POST", `/api/technique/runs/${runId}/arm/preflight`, body),
  techniqueArm: (runId: string, body?: import("../types").ArmRequest) =>
    request<import("../types").ArmedPlan>("POST", `/api/technique/runs/${runId}/arm`, body ?? {}),
  techniqueDisarm: (runId: string, flatten = false) =>
    request<{ disarmed: boolean }>("DELETE", `/api/technique/runs/${runId}/arm${flatten ? "?flatten=true" : ""}`),
  techniqueSetMode: (runId: string, opts: { mode?: string; allowLive?: boolean; entryFallback?: string }) => request<import("../types").ArmedPlan>("POST", `/api/technique/armed/${runId}/mode`, opts),
  techniquePause: (runId: string) => request<import("../types").ArmedPlan>("POST", `/api/technique/armed/${runId}/pause`),
  techniqueResume: (runId: string) => request<import("../types").ArmedPlan>("POST", `/api/technique/armed/${runId}/resume`),
  techniqueStopAll: (flatten = false) => request<{ disarmed: number }>("POST", `/api/technique/armed/stop-all${flatten ? "?flatten=true" : ""}`),
  techniqueArmToday: (symbol: string, body?: import("../types").ArmRequest) =>
    request<import("../types").ArmedPlan>("POST", "/api/technique/arm-today", { symbol, ...(body ?? {}) }),
  techniqueAnalyze: (body: { symbol: string; tf?: string; asOf?: number | null; note?: string; plan?: boolean | null; withVision?: boolean | null;
    imageDataUrl?: string | null }) =>
    request<import("../types").TechniqueRun>("POST", "/api/technique/analyze", body),
  techniqueRuns: (limit = 100, symbol?: string, extra?: Record<string, string>) =>
    request<import("../types").TechniqueRun[]>("GET",
      `/api/technique/runs?limit=${limit}${symbol ? `&symbol=${encodeURIComponent(symbol)}` : ""}`
      + Object.entries(extra ?? {}).map(([k, v]) => `&${k}=${encodeURIComponent(v)}`).join("")),
  techniqueRun: (id: string) => request<import("../types").TechniqueRun>("GET", `/api/technique/runs/${id}`),
  techniqueScore: (id: string) => request<import("../types").TechniqueOutcome[]>("POST", `/api/technique/runs/${id}/score`),
  techniqueScorePending: () => request<any>("POST", "/api/technique/outcomes/score"),
  techniqueReviews: (id: string) => request<import("../types").TechniqueReview[]>("GET", `/api/technique/runs/${id}/reviews`),
  techniqueAddReview: (id: string, body: any) =>
    request<import("../types").TechniqueReview>("POST", `/api/technique/runs/${id}/reviews`, body),
  techniqueTaxonomy: () => request<import("../types").TechniqueTaxonomy>("GET", "/api/technique/review/taxonomy"),
  techniqueReplay: (id: string, body: { thresholds?: Record<string, any> | null; useSnapshot?: boolean; note?: string; wait?: boolean }) =>
    request<import("../types").TechniqueRun>("POST", `/api/technique/runs/${id}/replay`, body),
  techniqueDiff: (a: string, b: string) => request<any>("GET", `/api/technique/runs/${a}/diff/${b}`),
  techniqueBundleUrl: (id: string) =>
    `/api/technique/runs/${id}/bundle${getAuthToken() ? `?token=${encodeURIComponent(getAuthToken())}` : ""}`,
  techniqueCancel: (id: string) => request<any>("POST", `/api/technique/runs/${id}/cancel`),
  techniqueSetups: (limit = 100) =>
    request<import("../types").TechniqueSetup[]>("GET", `/api/technique/setups?limit=${limit}`),
  techniqueBacktest: (body: { symbol: string; tf: string; days: number; horizonBars?: number; stepBars?: number; primeWindowsOnly?: boolean }) =>
    request<any>("POST", "/api/technique/backtest", body),
  techniqueScan: () => request<any>("POST", "/api/technique/scan"),
  techniqueOptions: (symbol: string, direction = "long") =>
    request<any>("GET", `/api/technique/options/${encodeURIComponent(symbol)}?direction=${direction}`),
  // --- chat ---
  chatThreads: (kind?: string) =>
    request<import("../types").ChatThread[]>("GET", `/api/chat/threads${kind ? `?kind=${kind}` : ""}`),
  chatCreate: (body: { title?: string; symbol?: string | null }) =>
    request<import("../types").ChatThread>("POST", "/api/chat/threads", body),
  chatThread: (id: string) => request<import("../types").ChatThread>("GET", `/api/chat/threads/${id}`),
  chatPatch: (id: string, body: { title?: string; archived?: boolean }) =>
    request<import("../types").ChatThread>("PATCH", `/api/chat/threads/${id}`, body),
  chatSend: (id: string, body: { text: string; images?: string[] }) =>
    request<import("../types").ChatMessage>("POST", `/api/chat/threads/${id}/messages`, body),
  chatCancel: (id: string) => request<any>("POST", `/api/chat/threads/${id}/cancel`),
  chatSearch: (q: string) => request<any[]>("GET", `/api/chat/search?q=${encodeURIComponent(q)}`),
  assetUrl: (id: string) => `/api/chat/assets/${id}${getAuthToken() ? `?token=${encodeURIComponent(getAuthToken())}` : ""}`,
};
