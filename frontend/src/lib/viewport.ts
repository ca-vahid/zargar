import { useSyncExternalStore } from "react";

/** Viewport / input classes, derived (never persisted).
 * phone < 640px · tablet 640–1023px · desktop ≥ 1024px; `coarse` = touch pointer. */
export interface Viewport {
  isPhone: boolean;
  isTablet: boolean;
  isDesktop: boolean;
  coarse: boolean;
  landscape: boolean;
}

const QUERIES = {
  // portrait phones by width; landscape phones by height (a 390px-tall viewport is a phone)
  phone: "(max-width: 639px), ((max-height: 500px) and (max-width: 1023px))",
  tablet: "(min-width: 640px) and (max-width: 1023px)",
  coarse: "(pointer: coarse)",
  landscape: "(orientation: landscape)",
};

let current: Viewport = compute();
const listeners = new Set<() => void>();

function mq(q: string): MediaQueryList | null {
  return typeof window !== "undefined" && window.matchMedia ? window.matchMedia(q) : null;
}

function compute(): Viewport {
  const phone = !!mq(QUERIES.phone)?.matches;
  const tablet = !!mq(QUERIES.tablet)?.matches;
  return {
    isPhone: phone,
    isTablet: tablet,
    isDesktop: !phone && !tablet,
    coarse: !!mq(QUERIES.coarse)?.matches,
    landscape: !!mq(QUERIES.landscape)?.matches,
  };
}

function refresh() {
  const next = compute();
  if (next.isPhone !== current.isPhone || next.isTablet !== current.isTablet
    || next.coarse !== current.coarse || next.landscape !== current.landscape) {
    current = next;
    document.documentElement.dataset.vp = next.isPhone ? "phone" : next.isTablet ? "tablet" : "desktop";
    listeners.forEach((l) => l());
  }
}

if (typeof window !== "undefined") {
  for (const q of Object.values(QUERIES)) mq(q)?.addEventListener("change", refresh);
  document.documentElement.dataset.vp = current.isPhone ? "phone" : current.isTablet ? "tablet" : "desktop";
}

export function useViewport(): Viewport {
  return useSyncExternalStore(
    (cb) => { listeners.add(cb); return () => { listeners.delete(cb); }; },
    () => current,
    () => current,
  );
}

/** For non-React code (ws, api): the current viewport class. */
export function viewportNow(): Viewport { return current; }

/** Client kind sent to the backend (`X-Zargar-Client`) — drives the
 * exit-only safety policy for phones and slimmer payloads. */
export function clientKind(): "phone" | "tablet" | "desktop" {
  return current.isPhone ? "phone" : current.isTablet ? "tablet" : "desktop";
}
