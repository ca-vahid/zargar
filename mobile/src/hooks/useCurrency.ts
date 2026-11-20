import { useCallback } from 'react';

import { savePref } from '../auth/storage';
import { rateFor } from '../lib/fx';
import { useStore } from '../store';

export type Currency = 'USD' | 'CAD';

/** The currency money TOTALS are shown in. Per-share prices always stay in the
 *  stock's own currency, as on a broker's screen. */
export function useCurrency(): Currency {
  return useStore((s) => s.currency);
}

export function setCurrency(currency: Currency) {
  useStore.getState().set({ currency });
  void savePref('currency', currency);
}

/** Convert an amount into the display currency with the live rate. When no rate is
 *  known the amount comes back untouched in its own currency, so the label stays true. */
export function useConvert(): (amount: number | null | undefined, from: string | null | undefined) => { value: number | null; cur: string } {
  const to = useCurrency();
  const usdCad = useStore((s) => s.quotes['USDCAD=X']?.last ?? null);
  return useCallback((amount, from) => {
    const own = (from || 'USD').toUpperCase();
    if (amount == null) return { value: null, cur: rateFor(usdCad, own, to) == null ? own : to };
    const rate = rateFor(usdCad, own, to);
    return rate == null ? { value: amount, cur: own } : { value: amount * rate, cur: to };
  }, [to, usdCad]);
}
