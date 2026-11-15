import { useMemo } from 'react';

import type { BrokerState, Portfolio } from '../api/types';
import { visibleBooks, type Workspace } from '../lib/books';
import { rateFor } from '../lib/fx';
import { useStore } from '../store';

/** The IBKR account's cash as the broker last reported it, in the book's own currency.
 *  The server's book for a freshly connected IBKR account can read zero while the broker
 *  holds cash in another currency (CAD in a USD book); without this the account is
 *  dropped from every list as "empty". Null when there is nothing to add or no rate. */
export function brokerCash(book: Portfolio, broker: BrokerState | null, usdCad: number | null): number | null {
  const ib = broker?.ibkr;
  if (!ib || ib.portfolioId !== book.id || Math.abs(book.cash ?? 0) >= 0.005) return null;
  let total = 0;
  for (const [cur, amount] of Object.entries(ib.cashByCurrency ?? {})) {
    const rate = rateFor(usdCad, cur, book.baseCurrency ?? 'USD');
    if (rate == null) return null;
    total += amount * rate;
  }
  return Math.abs(total) < 0.005 ? null : total;
}

/** Every book, with the broker's own cash read filled in where the server's book has none yet. */
export function withBrokerCash(portfolios: Portfolio[], broker: BrokerState | null, usdCad: number | null): Portfolio[] {
  return portfolios.map((p) => {
    const cash = brokerCash(p, broker, usdCad);
    if (cash == null) return p;
    const equity = (p.equity ?? 0) + cash;
    // cash does not move with the market: the day starts where it stands
    return { ...p, cash, equity, dayStart: p.dayStart ?? equity };
  });
}

/** The books of one workspace a person follows day to day. */
export function useBooks(workspace: Workspace, includeResearch = false): Portfolio[] {
  const portfolios = useStore((s) => s.portfolios);
  const broker = useStore((s) => s.broker);
  const usdCad = useStore((s) => s.quotes['USDCAD=X']?.last ?? null);
  return useMemo(
    () => visibleBooks(withBrokerCash(portfolios, broker, usdCad), workspace, includeResearch),
    [portfolios, broker, usdCad, workspace, includeResearch]);
}
