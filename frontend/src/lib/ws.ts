import { useStore } from "../store";
import { getAuthToken } from "./api";
import { clientKind, viewportNow } from "./viewport";

let socket: WebSocket | null = null;
let retryDelay = 1000;
let barListeners: ((msg: { symbol: string; tf: string; bar: number[] }) => void)[] = [];
// every symbol asked for since boot — re-sent on every (re)connect so a phone
// coming back from a network switch never watches a frozen quote
const watched = new Set<string>();
let hiddenSince = 0;
let hiddenTimer: ReturnType<typeof setTimeout> | null = null;
let closedByVisibility = false;

export function onBar(listener: (msg: { symbol: string; tf: string; bar: number[] }) => void) {
  barListeners.push(listener);
  return () => {
    barListeners = barListeners.filter((l) => l !== listener);
  };
}

export function watchSymbol(symbol: string) {
  const sym = symbol.toUpperCase();
  watched.add(sym);
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ t: "watch", symbol: sym }));
  }
}

// ---- quote conflation: phones coalesce frames to ≤ 4 Hz, desktop applies at once
let pendingQuotes: Map<string, any> | null = null;
let flushTimer: ReturnType<typeof setTimeout> | null = null;

function queueQuotes(list: any[]) {
  const interval = viewportNow().isPhone ? 250 : 0;
  if (interval === 0) { useStore.getState().applyQuotes(list); return; }
  if (!pendingQuotes) pendingQuotes = new Map();
  for (const q of list) pendingQuotes.set(q.symbol, q);
  if (flushTimer === null) {
    flushTimer = setTimeout(() => {
      flushTimer = null;
      const batch = pendingQuotes ? [...pendingQuotes.values()] : [];
      pendingQuotes = null;
      if (batch.length) useStore.getState().applyQuotes(batch);
    }, interval);
  }
}

function url(): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const token = getAuthToken();
  const params = new URLSearchParams();
  if (token) params.set("token", token);
  params.set("client", clientKind());
  return `${proto}://${location.host}/ws?${params.toString()}`;
}

/** Drop the current socket and open a fresh one (after sign-in / sign-out). */
export function reconnectWS() {
  const old = socket;
  socket = null;                 // the old socket's onclose sees it is stale and stays quiet
  try { old?.close(); } catch { /* ignore */ }
  retryDelay = 1000;
  connectWS();
}

export function connectWS() {
  const store = useStore.getState();
  const ws = new WebSocket(url());
  socket = ws;

  ws.onopen = () => {
    if (socket !== ws) return;   // superseded by a reconnect
    retryDelay = 1000;
    closedByVisibility = false;
    store.setConnected(true);
    // resubscribe everything the UI is showing
    for (const sym of watched) ws.send(JSON.stringify({ t: "watch", symbol: sym }));
  };

  ws.onclose = (ev) => {
    if (socket !== ws) return;   // stale socket closing after a reconnect — ignore
    useStore.getState().setConnected(false);
    if (closedByVisibility) return; // reconnect happens on visibilitychange
    if (ev.code === 4401) {
      // not signed in: the login screen takes over; no retry storm
      useStore.getState().setAuth({ checked: true, required: true, user: null });
      return;
    }
    setTimeout(connectWS, retryDelay);
    retryDelay = Math.min(retryDelay * 2, 15000);
  };

  ws.onmessage = (msg) => {
    if (socket !== ws) return;
    let data: any;
    try {
      data = JSON.parse(msg.data);
    } catch {
      return;
    }
    const s = useStore.getState();
    switch (data.t) {
      case "snapshot":
        s.applySnapshot(data.d);
        break;
      case "quotes":
        queueQuotes(data.d);
        break;
      case "order":
        s.applyOrder(data.d);
        break;
      case "execution":
        s.applyExecution(data.d);
        break;
      case "position":
        s.applyPosition(data.d);
        break;
      case "portfolio":
        s.applyPortfolio(data.d);
        break;
      case "proposal":
        s.applyProposal(data.d);
        break;
      case "signal":
        s.applySignal(data.d);
        break;
      case "system":
        s.applySystem(data.d);
        break;
      case "event":
        s.applyEvent(data.d);
        break;
      case "bar":
        for (const l of barListeners) l(data.d);
        break;
      case "technique":
        s.applyTechnique(data.d);
        break;
      case "chat":
        s.applyChat(data.d);
        break;
    }
  };
}

// ---- battery: a hidden tab (screen lock, app switch) drops the socket after
// 30s; coming back reconnects immediately and the snapshot re-syncs state
if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      hiddenSince = Date.now();
      if (hiddenTimer) clearTimeout(hiddenTimer);
      hiddenTimer = setTimeout(() => {
        hiddenTimer = null;
        if (document.visibilityState === "hidden" && socket && socket.readyState === WebSocket.OPEN) {
          closedByVisibility = true;
          socket.close();
        }
      }, 30_000);
    } else {
      if (hiddenTimer) { clearTimeout(hiddenTimer); hiddenTimer = null; }
      const dead = !socket || socket.readyState === WebSocket.CLOSED || socket.readyState === WebSocket.CLOSING;
      if (closedByVisibility || dead) {
        closedByVisibility = false;
        retryDelay = 1000;
        connectWS();
      }
      hiddenSince = 0;
    }
  });
}

export function hiddenForMs(): number { return hiddenSince ? Date.now() - hiddenSince : 0; }
