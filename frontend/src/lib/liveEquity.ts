import { useMemo } from "react";

import { useStore } from "../store";
import type { AppState } from "../store";
import type { Position, Quote } from "../types";

/** Options are quoted per share, held per contract. */
const MULT = (secType: string) => (secType === "OPT" ? 100 : 1);

/** USD/CAD is the only pair this desk holds. The server's `FxService` reads
 *  the same `USDCAD=X` quote; a missing rate is null, never a silent 1:1 — a
 *  Webull book holds SPCX in USD and that mistake read as a −24% day. */
export function makeRate(usdCad: number | undefined | null) {
  return (from: string, to: string): number | null => {
    const f = (from || "USD").toUpperCase(), t = (to || "USD").toUpperCase();
    if (f === t) return 1;
    if (!usdCad || usdCad <= 0) return null;
    if (f === "USD" && t === "CAD") return usdCad;
    if (f === "CAD" && t === "USD") return 1 / usdCad;
    return null;
  };
}

/** What one unit of a position is worth right now, from the live quote.
 *
 *  Mirrors the server's `PositionKeeper._mark` (PLATFORM-RULES invariant 22):
 *  an option is valued on its BOOK, at the mid, including a 0 bid — half the
 *  ask is the honest read on a contract going worthless. A lone print is used
 *  only when there is no ask at all. Change this and change `_mark` with it.
 */
function markOf(pos: Position, q: Quote | undefined): number {
  if (pos.secType === "OPT" && q && q.ask > 0 && q.ask >= q.bid) {
    return (Math.max(q.bid, 0) + q.ask) / 2;
  }
  if (q && q.last > 0) return q.last;
  return pos.last ?? pos.avgCost;
}

/** Live equity per book, as a compact signature string.
 *
 *  Quotes land ~10 Hz and `applyQuotes` replaces the whole map, so a hook that
 *  subscribed to it would re-render its consumer ten times a second whether or
 *  not any number changed. A selector returning a STRING re-renders only when
 *  the cents actually move.
 *
 *  Every position is converted into its BOOK's currency (a CAD book holding a
 *  US listing) with the same rate the server uses; a book that cannot be
 *  converted keeps the server's own equity rather than a wrong number — per
 *  book, so one unpriceable holding does not freeze every other book.
 */
function signature(s: AppState, ids: string[]): string {
  const rate = makeRate(s.quotes["USDCAD=X"]?.last);
  const base: Record<string, string> = {};
  for (const id of ids) base[id] = (s.portfolios.find((p) => p.id === id)?.baseCurrency || "USD").toUpperCase();
  const held: Record<string, number> = {};
  const broken = new Set<string>();
  for (const p of Object.values(s.positions)) {
    if (!ids.includes(p.portfolioId) || Math.abs(p.qty) < 1e-9) continue;
    const q = s.quotes[p.symbol];
    const r = rate(p.currency || "USD", base[p.portfolioId]);
    // no live quote AND no server mark, or no way to convert: keep the server's number
    if ((!q && p.last == null) || r == null) { broken.add(p.portfolioId); continue; }
    held[p.portfolioId] = (held[p.portfolioId] ?? 0) + p.qty * markOf(p, q) * MULT(p.secType) * r;
  }
  return ids.map((id) => {
    const b = s.portfolios.find((p) => p.id === id);
    if (!b) return `${id}:`;
    const v = broken.has(id) ? (b.equity ?? b.cash) : b.cash + (held[id] ?? 0);
    return `${id}:${v.toFixed(2)}`;
  }).join("|");
}

/** Equity per book id, in each book's own currency, marked to the live tape.
 *
 *  The server pushes equity every 30 s, which is the anchor — but between those
 *  pushes the headline sat perfectly still while quotes arrived behind it (user
 *  2026-09-14: "make it update in real time"). Cash comes from the server; the
 *  positions are marked here against the same quotes the board already draws.
 */
export function useLiveEquity(bookIds: string[]): Record<string, number> {
  const key = bookIds.join(",");
  const sig = useStore((s) => signature(s, key ? key.split(",") : []));
  return useMemo(() => {
    const out: Record<string, number> = {};
    for (const part of sig.split("|")) {
      const i = part.lastIndexOf(":");
      if (i < 0) continue;
      const v = Number(part.slice(i + 1));
      if (Number.isFinite(v)) out[part.slice(0, i)] = v;
    }
    return out;
  }, [sig]);
}

/** Total live equity across a set of books that share one currency. */
export function useLiveTotal(bookIds: string[]): number {
  const live = useLiveEquity(bookIds);
  return bookIds.reduce((t, id) => t + (live[id] ?? 0), 0);
}
