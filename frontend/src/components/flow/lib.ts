// Flow UI helpers — OCC display, short money, lean/score colors.
import type { FlowFlag, FlowReadItem } from "../../types";

/** Unpadded OCC ("COIN260912C00300000") -> "09/12 300C". */
export function fmtOcc(contract: string): string {
  const m = /^([A-Z.]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/.exec(contract || "");
  if (!m) return contract || "—";
  const [, , , mm, dd, cp, strike8] = m;
  const strike = parseInt(strike8, 10) / 1000;
  const k = Number.isInteger(strike) ? String(strike) : String(strike);
  return `${mm}/${dd} ${k}${cp}`;
}

/** $4,200,000 -> "$4.2M"; 820000 -> "$820k". */
export function fmtPrem(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (a >= 1_000) return `$${Math.round(v / 1_000)}k`;
  return `$${Math.round(v)}`;
}

export function leanPill(lean: string): string {
  return lean === "bull" ? "ok" : lean === "bear" ? "bad" : lean === "mixed" ? "wait" : "dim";
}

export function leanColor(lean: string): string {
  return lean === "bull" ? "var(--up)" : lean === "bear" ? "var(--down)"
    : lean === "mixed" ? "var(--warn)" : "var(--text-3)";
}

export function topFlag(r: FlowReadItem): FlowFlag | null {
  return (r.flags && r.flags.length) ? r.flags[0] : null;
}

export function maxRepeat(r: FlowReadItem): number {
  const vals = Object.values(r.repeatHits || {});
  return vals.length ? Math.max(...vals) : 0;
}
