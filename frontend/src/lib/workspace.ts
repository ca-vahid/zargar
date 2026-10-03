// The one place that decides what belongs to which workspace.
//
// Practice = the in-app simulator (sim + shadow books). Fake money, no venue.
// Live     = real venues: live brokerage accounts AND broker-hosted paper
//            accounts (IBKR paper trades on IBKR's systems with their numbers,
//            so it lives here, clearly badged — greyed until IBKR activates).
//
// W6.5 (2026-10-03): the workspace is a VIEW - it only changes what you see (kept per browser). Real-order
// routing is a separate server switch, `trading.mode` (useLiveRouting): with it on, Practice and the live books
// both keep trading in the background whichever workspace is on screen.
import { useMemo } from "react";
import { useStore } from "../store";
import type { Portfolio } from "../types";

export type Workspace = "live" | "practice";
export const LIVE_KINDS = new Set(["live", "paper"]);
export const PRACTICE_KINDS = new Set(["sim", "shadow"]);
// Money vs evidence. Shadow books are practice-SIDE (so the workspace filter
// rightly keeps them) but they are NOT money: they are the per-source track
// record. Anything that adds up to a balance must use this instead — the
// Dashboard's holdings once listed 54 research positions under a total that
// counted 3 of them (2026-09-07).
export const REAL_KINDS = new Set(["sim", "live", "paper"]);
export function isRealBook(kind: string | undefined | null): boolean {
  return REAL_KINDS.has(kind ?? "");
}

export function workspaceOf(kind: string | undefined | null): Workspace {
  return LIVE_KINDS.has(kind ?? "") ? "live" : "practice";
}

export function useWorkspace(): Workspace {
  return useStore((s) => s.viewWorkspace
    ?? ((s.settings["trading.mode"] ?? "practice") === "live" ? "live" : "practice"));
}

/** Real orders route to live/paper accounts (server `trading.mode` = live). Independent of the view. */
export function useLiveRouting(): boolean {
  return useStore((s) => (s.settings["trading.mode"] ?? "practice") === "live");
}

/** Portfolios visible in the active workspace. */
export function useWorkspacePortfolios(): Portfolio[] {
  const ws = useWorkspace();
  const portfolios = useStore((s) => s.portfolios);
  return useMemo(() => portfolios.filter((p) => workspaceOf(p.kind) === ws), [portfolios, ws]);
}

/** kind -> belongs to the active workspace. */
export function useWorkspaceFilter(): (kind: string | undefined | null) => boolean {
  const ws = useWorkspace();
  return useMemo(() => (kind: string | undefined | null) => workspaceOf(kind) === ws, [ws]);
}

/** kind -> in this workspace AND real money (research books excluded). */
export function useRealBookFilter(): (kind: string | undefined | null) => boolean {
  const ws = useWorkspace();
  return useMemo(
    () => (kind: string | undefined | null) => workspaceOf(kind) === ws && isRealBook(kind),
    [ws]);
}
