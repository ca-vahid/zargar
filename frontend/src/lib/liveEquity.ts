import { useMemo } from "react";

import { useStore } from "../store";
import type { AppState } from "../store";
import type { Position, Quote } from "../types";

/** Options are quoted per share, held per contract. */
const MULT = (secType: string) => (secType === "OPT" ? 100 : 1);

/** What one unit of a position is worth right now, from the live quote.
 *
 *  Mirrors the server's `PositionKeeper._mark` (PLATFORM-RULES invariant 22):
 *  an option is valued on its BOOK, at the mid, including a 0 bid — half the
 *  ask is the honest read on a contract going worthless. A lone print is used
 *  only when there is no ask at all: one stale print marked two INTC 0DTE
 *  calls near $7 on 2026-09-14 and put +$1,406 into a book's equity history.
 *  Change this and change `PositionKeeper._mark` with it.
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
 *  not any number changed (the re-render trap CLAUDE.md warns about). A
 *  selector returning a STRING re-renders only when the cents actually move:
 *  the loop still runs on each store change, which is a handful of positions,
 *  but the component tree does not.
 */
function signature(s: AppState, ids: string[]): string {
  const held: Record<string, number> = {};
  let priceable = true;
  for (const p of Object.values(s.positions)) {
    if (!ids.includes(p.portfolioId) || Math.abs(p.qty) < 1e-9) continue;
    const q = s.quotes[p.symbol];
    // no live quote AND no server mark: this book cannot be priced honestly
    if (!q && p.last == null) { priceable = false; break; }
    held[p.portfolioId] = (held[p.portfolioId] ?? 0) + p.qty * markOf(p, q) * MULT(p.secType);
  }
  return ids.map((id) => {
    const b = s.portfolios.find((p) => p.id === id);
    if (!b) return `${id}:`;
    const v = priceable ? b.cash + (held[id] ?? 0) : (b.equity ?? b.cash);
    return `${id}:${v.toFixed(2)}`;
  }).join("|");
}

/** Equity per book id, marked to the live tape.
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

/** Total live equity across a set of books, in their shared base currency. */
export function useLiveTotal(bookIds: string[]): number {
  const live = useLiveEquity(bookIds);
  return bookIds.reduce((t, id) => t + (live[id] ?? 0), 0);
}
