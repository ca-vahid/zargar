import type { OrderIntentBody } from "../store";

let authToken = localStorage.getItem("zargar_token") || "";

export function setAuthToken(token: string) {
  authToken = token;
  localStorage.setItem("zargar_token", token);
}

export function getAuthToken() {
  return authToken;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
  const resp = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
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
  ingestManual: (text: string, source_name: string, subject: string) =>
    request<any>("POST", "/api/ingest/manual", { text, source_name, subject }),
  getBrokerages: () => request<import("../types").Brokerages>("GET", "/api/brokerages"),
  orderImpact: (body: { portfolio_id: string; symbol: string; side: string; qty: number;
    order_type?: string; limit_price?: number | null }) =>
    request<{ estimatedCommission?: number; forexFees?: number;
      remainingCash?: number | null; remainingCashCurrency?: string | null;
      error?: string }>(
      "POST", "/api/brokerages/impact", body),
  refreshBrokerages: () =>
    request<import("../types").Brokerages>("POST", "/api/brokerages/refresh"),
  searchSymbols: (q: string) =>
    request<{ results: { symbol: string; name: string; exchange: string; type: string }[] }>(
      "GET", `/api/symbols/search?q=${encodeURIComponent(q)}`),
  watchSymbol: (symbol: string) => request<any>("POST", "/api/watch", { symbol }),
  updateWatchlist: (id: string, name: string, symbols: string[]) =>
    request<import("../types").Watchlist>("PUT", `/api/watchlists/${id}`, { name, symbols }),
  // --- technique ---
  techniqueStatus: () => request<import("../types").TechniqueStatus>("GET", "/api/technique/status"),
  techniqueAnalyze: (body: { symbol: string; tf?: string; asOf?: number | null; note?: string;
    imageDataUrl?: string | null }) =>
    request<import("../types").TechniqueRun>("POST", "/api/technique/analyze", body),
  techniqueRuns: (limit = 100, symbol?: string) =>
    request<import("../types").TechniqueRun[]>("GET",
      `/api/technique/runs?limit=${limit}${symbol ? `&symbol=${encodeURIComponent(symbol)}` : ""}`),
  techniqueRun: (id: string) => request<import("../types").TechniqueRun>("GET", `/api/technique/runs/${id}`),
  techniqueCancel: (id: string) => request<any>("POST", `/api/technique/runs/${id}/cancel`),
  techniqueSetups: (limit = 100) =>
    request<import("../types").TechniqueSetup[]>("GET", `/api/technique/setups?limit=${limit}`),
  techniqueBacktest: (body: { symbol: string; tf: string; days: number; horizonBars?: number; stepBars?: number }) =>
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
