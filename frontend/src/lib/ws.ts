import { useStore } from "../store";
import { getAuthToken } from "./api";

let socket: WebSocket | null = null;
let retryDelay = 1000;
let barListeners: ((msg: { symbol: string; tf: string; bar: number[] }) => void)[] = [];

export function onBar(listener: (msg: { symbol: string; tf: string; bar: number[] }) => void) {
  barListeners.push(listener);
  return () => {
    barListeners = barListeners.filter((l) => l !== listener);
  };
}

export function watchSymbol(symbol: string) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ t: "watch", symbol }));
  }
}

export function connectWS() {
  const store = useStore.getState();
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const token = getAuthToken();
  const url = `${proto}://${location.host}/ws${token ? `?token=${encodeURIComponent(token)}` : ""}`;
  socket = new WebSocket(url);

  socket.onopen = () => {
    retryDelay = 1000;
    store.setConnected(true);
  };

  socket.onclose = () => {
    useStore.getState().setConnected(false);
    setTimeout(connectWS, retryDelay);
    retryDelay = Math.min(retryDelay * 2, 15000);
  };

  socket.onmessage = (msg) => {
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
        s.applyQuotes(data.d);
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
