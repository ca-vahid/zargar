import type { Page } from "../store";

/**
 * Minimal URL <-> state sync. The app has no router; this keeps the address bar
 * meaningful so a run can be linked, bookmarked and quoted:
 *
 *   /technique                     analyse tab
 *   /technique/history             a tab
 *   /technique/run/<runId>         one run, deep-linkable
 *   /technique/chat/<threadId>     one chat thread
 *   /trade, /journal, ...          the other pages
 *
 * Real paths (not hashes) because the server already falls through to
 * index.html for unknown paths.
 */

export const PAGES: Page[] = [
  "dashboard", "trade", "options", "inbox", "technique", "armed", "watchlists",
  "portfolios", "journal", "settings",
];
const OCC_RE = /^[A-Z]{1,6}\d{6}[CP]\d{8}$/;
export const TQ_TABS = ["analyse", "chat", "history", "backtest", "validation", "armed"] as const;
export type TqTab = (typeof TQ_TABS)[number];

export interface RouteState {
  page: Page;
  techniqueTab?: TqTab;
  runId?: string | null;
  /** armed page: /armed/<runId> opens that plan (phone sheet / desktop selection) */
  armedRunId?: string | null;
  threadId?: string | null;
  /** options page: /options/SPY, /options/SPY/2026-08-28, /options/c/<OCC> */
  optionsUnderlying?: string;
  optionsExpiry?: string | null;
  optionsContract?: string | null;
}

export function parseLocation(pathname = window.location.pathname): RouteState {
  const parts = pathname.split("/").filter(Boolean);
  const page = (PAGES as string[]).includes(parts[0]) ? (parts[0] as Page) : "dashboard";
  if (page === "options") {
    const a = (parts[1] ?? "").toUpperCase();
    if (a === "C" && parts[2]) {
      const occ = parts[2].toUpperCase();
      if (OCC_RE.test(occ)) {
        return { page, optionsContract: occ, optionsUnderlying: occ.match(/^[A-Z]{1,6}/)![0],
          optionsExpiry: `20${occ.slice(-15, -13)}-${occ.slice(-13, -11)}-${occ.slice(-11, -9)}` };
      }
    }
    if (a && a !== "C") {
      const exp = parts[2] && /^\d{4}-\d{2}-\d{2}$/.test(parts[2]) ? parts[2] : undefined;
      return { page, optionsUnderlying: a, ...(exp ? { optionsExpiry: exp } : {}) };
    }
    return { page };
  }
  if (page === "armed") return parts[1] ? { page, armedRunId: parts[1] } : { page };
  if (page !== "technique") return { page };

  const second = parts[1];
  // Armed moved to its own page — old /technique/armed links land there
  if (second === "armed") return { page: "armed" };
  if (second === "run" && parts[2]) return { page, techniqueTab: "analyse", runId: parts[2] };
  if (second === "chat") return { page, techniqueTab: "chat", threadId: parts[2] ?? null };
  if ((TQ_TABS as readonly string[]).includes(second)) return { page, techniqueTab: second as TqTab };
  return { page, techniqueTab: "analyse" };
}

export function buildPath(s: RouteState): string {
  if (s.page === "options") {
    if (s.optionsContract) return `/options/c/${s.optionsContract}`;
    if (s.optionsUnderlying) {
      return `/options/${s.optionsUnderlying}${s.optionsExpiry ? `/${s.optionsExpiry}` : ""}`;
    }
    return "/options";
  }
  if (s.page === "armed") return s.armedRunId ? `/armed/${s.armedRunId}` : "/armed";
  if (s.page !== "technique") return `/${s.page}`;
  if (s.techniqueTab === "analyse" && s.runId) return `/technique/run/${s.runId}`;
  if (s.techniqueTab === "chat") return s.threadId ? `/technique/chat/${s.threadId}` : "/technique/chat";
  if (s.techniqueTab && s.techniqueTab !== "analyse") return `/technique/${s.techniqueTab}`;
  return "/technique";
}

/** Absolute link for sharing/copying. */
export function absoluteUrl(s: RouteState): string {
  return `${window.location.origin}${buildPath(s)}`;
}

/** Write the path without reloading. `push` adds a history entry (user
 *  navigation); otherwise the current entry is replaced (derived changes). */
export function syncUrl(s: RouteState, push = false): void {
  const next = buildPath(s);
  if (next === window.location.pathname) return;
  if (push) window.history.pushState({}, "", next);
  else window.history.replaceState({}, "", next);
}

export function onRouteChange(fn: (s: RouteState) => void): () => void {
  const handler = () => fn(parseLocation());
  window.addEventListener("popstate", handler);
  return () => window.removeEventListener("popstate", handler);
}

/** Copy text, falling back for non-secure contexts. Returns success. */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to the legacy path */
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
