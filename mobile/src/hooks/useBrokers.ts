import { useCallback } from 'react';

import { api } from '../api/endpoints';
import { useStore } from '../store';
import { usePoll } from './usePoll';

export interface BookBroker { name: string; broker: string; logoUrl: string | null; kind?: string; currency?: string }

/** Which broker holds a book, with its logo: SnapTrade connections by account, IBKR by venue. */
export function useBrokers(): (portfolioId: string) => BookBroker {
  const portfolios = useStore((s) => s.portfolios);
  const list = usePoll(() => api.brokerages(), 600000, [], 'brokerages');
  const providers = list.data?.providers;
  return useCallback((portfolioId: string) => {
    const book = portfolios.find((p) => p.id === portfolioId);
    const base = { name: book?.name ?? portfolioId.slice(0, 8), kind: book?.kind, currency: book?.baseCurrency };
    for (const pr of providers ?? []) {
      if (pr.accounts.some((a) => a.portfolioId === portfolioId)) return { ...base, broker: pr.broker, logoUrl: pr.logoUrl ?? null };
    }
    const ibkr = book?.venue === 'ibkr' || (book?.name ?? '').includes('IBKR');
    return { ...base, broker: ibkr ? 'Interactive Brokers' : book?.name ?? 'Account', logoUrl: null };
  }, [portfolios, providers]);
}
