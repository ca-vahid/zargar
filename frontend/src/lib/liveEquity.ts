import { useMemo } from "react";

import { useStore } from "../store";
import type { Portfolio, Position, Quote } from "../types";

/** Options are quoted per share, held per contract. */
const MULT = (secType: string) => (secType === "OPT" ? 100 : 1);

/** What one unit of a position is worth right now, from the live quote.
 *
 *  Mirrors the server's `PositionKeeper._mark` (PLATFORM-RULES invariant 22):
 *  an option marks at the MID of a two-sided market, because a thin contract's
 *  last print is not a valuation — one print marked two INTC 0DTE calls near
 *  $7 on 2026-09-14. Anything without a live quote keeps the server's own mark.
 */
function markOf(pos: Position, q: Quote | undefined): number {
  if (pos.secType === "OPT" && q && q.ask > 0 && q.ask >= q.bid) return (Math.max(q.bid, 0) + q.ask) / 2;
  if (q && q.last > 0) return q.last;
  return pos.last ?? pos.avgCost;
}

/** Equity per book, marked to the live tape.
 *
 *  The server pushes equity every 30 seconds, which is the anchor — but between
 *  those pushes the headline sat perfectly still while quotes arrived at ~10 Hz
 *  behind it (user 2026-09-14: "make it update in real time"). Cash comes from
 *  the server; the positions are marked here against the same quotes the rest
 *  of the board is already drawing.
 *
 *  Falls back to the server's `equity` for any book we cannot price ourselves,
 *  so a missing option quote can never make a book read as just its cash.
 */
export function useLiveEquity(books: Portfolio[]): Record<string, number> {
  const positions = useStore((s) => s.positions);
  const quotes = useStore((s) => s.quotes);
  const ids = books.map((b) => b.id).join(",");
  return useMemo(() => {
    const out: Record<string, number> = {};
    for (const b of books) out[b.id] = b.equity ?? b.cash;
    const priceable = new Set(books.map((b) => b.id));
    const held: Record<string, number> = {};
    let ok = true;
    for (const p of Object.values(positions)) {
      if (!priceable.has(p.portfolioId) || Math.abs(p.qty) < 1e-9) continue;
      const q = quotes[p.symbol];
      // no quote AND no server mark: we cannot price this book honestly
      if (!q && p.last == null) { ok = false; continue; }
      held[p.portfolioId] = (held[p.portfolioId] ?? 0) + p.qty * markOf(p, q) * MULT(p.secType);
    }
    if (!ok) return out;
    for (const b of books) out[b.id] = b.cash + (held[b.id] ?? 0);
    return out;
  }, [ids, books, positions, quotes]);
}

/** Total live equity across a set of books, in their shared base currency. */
export function useLiveTotal(books: Portfolio[]): number {
  const live = useLiveEquity(books);
  return books.reduce((t, b) => t + (live[b.id] ?? b.equity ?? b.cash), 0);
}
