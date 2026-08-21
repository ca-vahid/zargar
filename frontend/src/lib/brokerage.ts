import type { BrokerageAccount } from "../types";
import { fmtCcy } from "./format";

/** Native per-currency cash line: "US$914.17 + C$67.31" (or the plain total). */
export function cashText(a: Pick<BrokerageAccount, "cash" | "currency" | "cashBalances">): string {
  const parts = (a.cashBalances ?? []).filter((b) => Math.abs(b.cash) > 0.004);
  if (parts.length > 1) return parts.map((b) => fmtCcy(b.cash, b.currency)).join(" + ");
  return fmtCcy(a.cash, a.currency);
}

/** Provider-level total across accounts; blends to CAD when currencies mix. */
export function providerTotal(
  accounts: BrokerageAccount[],
  usdCad: number | undefined,
): string {
  const by: Record<string, number> = {};
  for (const a of accounts) by[a.currency] = (by[a.currency] ?? 0) + a.equity;
  const entries = Object.entries(by).filter(([, v]) => Math.abs(v) > 0.005);
  if (entries.length === 0) return fmtCcy(0, accounts[0]?.currency ?? "CAD");
  if (entries.length === 1) return fmtCcy(entries[0][1], entries[0][0]);
  if (usdCad && usdCad > 0 && entries.every(([c]) => c === "CAD" || c === "USD")) {
    const cad = entries.reduce((sum, [c, v]) => sum + (c === "CAD" ? v : v * usdCad), 0);
    return `≈ ${fmtCcy(cad, "CAD")}`;
  }
  return entries.map(([c, v]) => fmtCcy(v, c)).join(" · ");
}
