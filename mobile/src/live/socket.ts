import { AppState, type AppStateStatus } from 'react-native';

import { getToken, socketUrl } from '../api/client';
import type { Quote } from '../api/types';
import { useStore } from '../store';

// One socket for the whole app. The server sends a full snapshot on connect and then
// every topic to every client, so a reconnect always re-syncs state by itself.

let socket: WebSocket | null = null;
let retryMs = 1000;
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let pingTimer: ReturnType<typeof setInterval> | null = null;
let wanted = false;
let backgroundTimer: ReturnType<typeof setTimeout> | null = null;
let closedForBackground = false;
const watched = new Set<string>();

type BarListener = (m: { symbol: string; tf: string; bar: number[] }) => void;
let barListeners: BarListener[] = [];
export function onBar(l: BarListener) {
  barListeners.push(l);
  return () => { barListeners = barListeners.filter((x) => x !== l); };
}

/** Next reconnect delay: doubles from 1 s, capped at 15 s. */
export const nextBackoff = (ms: number) => Math.min(ms * 2, 15000);

// quotes arrive ~10 Hz for every symbol the desk follows; a phone repaints once a second
let pending: Map<string, Quote> | null = null;
let flushTimer: ReturnType<typeof setTimeout> | null = null;
function queueQuotes(list: Quote[]) {
  if (!pending) pending = new Map();
  for (const quote of list) pending.set(quote.symbol, quote);
  if (flushTimer) return;
  flushTimer = setTimeout(() => {
    flushTimer = null;
    const batch = pending ? [...pending.values()] : [];
    pending = null;
    if (batch.length) useStore.getState().applyQuotes(batch);
  }, 1000);
}

export function watchSymbol(symbol: string) {
  const sym = symbol.toUpperCase();
  watched.add(sym);
  if (socket && socket.readyState === 1) socket.send(JSON.stringify({ t: 'watch', symbol: sym }));
}

function clearTimers() {
  if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
  if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
}

function open() {
  if (!wanted || !getToken()) return;
  clearTimers();
  const store = useStore.getState();
  store.set({ conn: 'connecting' });
  let ws: WebSocket;
  try {
    ws = new WebSocket(socketUrl());
  } catch {
    schedule();
    return;
  }
  socket = ws;
  ws.onopen = () => {
    if (socket !== ws) return;
    retryMs = 1000;
    closedForBackground = false;
    useStore.getState().set({ conn: 'live' });
    for (const sym of watched) ws.send(JSON.stringify({ t: 'watch', symbol: sym }));
    pingTimer = setInterval(() => {
      if (ws.readyState === 1) ws.send(JSON.stringify({ t: 'ping' }));
    }, 25000);
  };
  ws.onmessage = (ev) => {
    if (socket !== ws) return;
    let msg: any;
    try { msg = JSON.parse(String(ev.data)); } catch { return; }
    if (msg.t === 'quotes') queueQuotes(msg.d);
    else if (msg.t === 'bar') for (const l of barListeners) l(msg.d);
    else if (msg.t !== 'pong') useStore.getState().applyMessage(msg.t, msg.d);
  };
  ws.onclose = (ev) => {
    if (socket !== ws) return; // an older socket closing after a reconnect
    socket = null;
    clearTimers();
    useStore.getState().set({ conn: 'down' });
    if (closedForBackground || !wanted) return;
    if ((ev as any)?.code === 4401) {
      // the session ended: the sign-in screen takes over, no retry storm
      useStore.getState().set({ user: null, token: null });
      return;
    }
    schedule();
  };
  ws.onerror = () => { /* onclose follows and handles the retry */ };
}

function schedule() {
  if (!wanted) return;
  retryTimer = setTimeout(open, retryMs);
  retryMs = nextBackoff(retryMs);
}

export function connectSocket() {
  wanted = true;
  if (socket && (socket.readyState === 0 || socket.readyState === 1)) return;
  retryMs = 1000;
  open();
}

export function disconnectSocket() {
  wanted = false;
  clearTimers();
  const old = socket;
  socket = null;
  try { old?.close(); } catch { /* ignore */ }
  useStore.getState().set({ conn: 'idle' });
}

// battery: thirty seconds in the background drops the socket; coming back reconnects
// at once and the snapshot brings everything up to date
function onAppState(next: AppStateStatus) {
  if (next === 'active') {
    if (backgroundTimer) { clearTimeout(backgroundTimer); backgroundTimer = null; }
    if (wanted && (!socket || socket.readyState > 1)) {
      closedForBackground = false;
      retryMs = 1000;
      open();
    }
  } else if (!backgroundTimer) {
    backgroundTimer = setTimeout(() => {
      backgroundTimer = null;
      if (socket && socket.readyState === 1) {
        closedForBackground = true;
        socket.close();
      }
    }, 30000);
  }
}

let appStateBound = false;
export function bindAppState() {
  if (appStateBound) return;
  appStateBound = true;
  AppState.addEventListener('change', onAppState);
}
