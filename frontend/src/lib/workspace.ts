// The one place that decides what belongs to which workspace.
//
// Practice = the in-app simulator (sim + shadow books). Fake money, no venue.
// Live     = real venues: live brokerage accounts AND broker-hosted paper
//            accounts (IBKR paper trades on IBKR's systems with their numbers,
//            so it lives here, clearly badged — greyed until IBKR activates).
//
// The workspace IS trading.mode: switching it both changes what you see and
// flips the order-routing gate (practice mode rejects orders to real accounts).
import { useMemo } from "react";
import { useStore } from "../store";
import type { Portfolio } from "../types";

export type Workspace = "live" | "practice";
export const LIVE_KINDS = new Set(["live", "paper"]);
export const PRACTICE_KINDS = new Set(["sim", "shadow"]);

export function workspaceOf(kind: string | undefined | null): Workspace {
  return LIVE_KINDS.has(kind ?? "") ? "live" : "practice";
}

export function useWorkspace(): Workspace {
  return useStore((s) => ((s.settings["trading.mode"] ?? "practice") === "live" ? "live" : "practice"));
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
