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
  "dashboard", "trade", "inbox", "technique", "portfolios", "journal", "settings",
];
export const TQ_TABS = ["analyse", "chat", "history", "backtest"] as const;
export type TqTab = (typeof TQ_TABS)[number];

export interface RouteState {
  page: Page;
  techniqueTab?: TqTab;
  runId?: string | null;
  threadId?: string | null;
}

export function parseLocation(pathname = window.location.pathname): RouteState {
  const parts = pathname.split("/").filter(Boolean);
  const page = (PAGES as string[]).includes(parts[0]) ? (parts[0] as Page) : "dashboard";
  if (page !== "technique") return { page };

  const second = parts[1];
  if (second === "run" && parts[2]) return { page, techniqueTab: "analyse", runId: parts[2] };
  if (second === "chat") return { page, techniqueTab: "chat", threadId: parts[2] ?? null };
  if ((TQ_TABS as readonly string[]).includes(second)) return { page, techniqueTab: second as TqTab };
  return { page, techniqueTab: "analyse" };
}

export function buildPath(s: RouteState): string {
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
