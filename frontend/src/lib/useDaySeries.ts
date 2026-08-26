import { useEffect, useReducer } from "react";
import { api } from "./api";
import { onBar } from "./ws";
import { viewportNow } from "./viewport";

export interface DayData {
  closes: number[]; // today's regular-session 1m closes, 09:30 ET -> now
  open: number | null; // today's first regular-session bar open (fallback basis
                       // when the feed carries no previous close)
}

const SESSION_START_MS = 9.5 * 3600_000; // 09:30 ET
const SESSION_END_MS = 16 * 3600_000;    // 16:00 ET

function inRegularSession(ts: number, dayStart: number): boolean {
  return ts >= dayStart + SESSION_START_MS && ts < dayStart + SESSION_END_MS;
}

interface Entry {
  data: DayData;
  fetched: boolean;
  listeners: Set<() => void>;
}

const cache = new Map<string, Entry>();
let barSubscribed = false;

/** Epoch ms of midnight in America/New_York (the trading day boundary). */
function etDayStartMs(): number {
  const now = new Date();
  const etNow = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" }));
  const offset = now.getTime() - etNow.getTime();
  const etMidnight = new Date(etNow);
  etMidnight.setHours(0, 0, 0, 0);
  return etMidnight.getTime() + offset;
}

function ensureBarSubscription() {
  if (barSubscribed) return;
  barSubscribed = true;
  onBar((msg) => {
    if (msg.tf !== "1m") return;
    const entry = cache.get(msg.symbol);
    if (!entry || !entry.fetched) return;
    if (!inRegularSession(msg.bar[0], etDayStartMs())) return; // pre/post bars stay out
    const close = msg.bar[4];
    entry.data.closes.push(close);
    if (entry.data.open === null) entry.data.open = msg.bar[1];
    entry.listeners.forEach((l) => l());
  });
}

/** Today's 1m close series for a symbol (shared cache, live bar appends). */
export function useDaySeries(symbol: string): DayData {
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    ensureBarSubscription();
    let entry = cache.get(symbol);
    if (!entry) {
      entry = { data: { closes: [], open: null }, fetched: false, listeners: new Set() };
      cache.set(symbol, entry);
      const dayStart = etDayStartMs();
      const phone = viewportNow().isPhone;
      api.get<{ bars: number[][] }>(phone
        ? `/api/chart/${symbol}?tf=5m&limit=120`   // data diet: an 84px sparkline needs ~80 points
        : `/api/chart/${symbol}?tf=1m&limit=600`)
        .then((d) => {
          const bars = (d.bars ?? []).filter((b) => inRegularSession(b[0], dayStart));
          entry!.data = {
            closes: bars.map((b) => b[4]),
            open: bars.length ? bars[0][1] : null,
          };
          entry!.fetched = true;
          entry!.listeners.forEach((l) => l());
        })
        // sparkline simply stays absent when history is unavailable
        .catch(() => { entry!.fetched = true; });
    }
    const listener = () => force();
    entry.listeners.add(listener);
    return () => { entry!.listeners.delete(listener); };
  }, [symbol]);
  return cache.get(symbol)?.data ?? { closes: [], open: null };
}
