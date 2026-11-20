import type { AlertItem } from '../api/endpoints';

export interface AlertGroup { item: AlertItem; count: number; firstTs: string }

const KIND_LABEL: Record<string, string> = {
  TechniquePlanError: 'Plan alert', BrokerDisconnected: 'Broker link', BrokerConnected: 'Broker link',
  StandingOrder: 'Standing order', TradingHalted: 'Kill switch', TradingResumed: 'Kill switch',
};

/** What kind of alert this is, in a word or two (the journal's own type names are code). */
export function alertLabel(a: Pick<AlertItem, 'kind' | 'level'>): string {
  if (a.kind === 'alert') return a.level === 'error' ? 'Problem' : a.level === 'warning' ? 'Warning' : 'Note';
  return KIND_LABEL[a.kind] ?? a.kind.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/^\w/, (c) => c.toUpperCase()).replace(/ (\w)/g, (m) => m.toLowerCase());
}

/** The same alert repeated back to back (a broker link that drops every night) becomes
 *  one row with a count, newest first, so one noisy source cannot bury the rest. */
export function foldAlerts(items: AlertItem[]): AlertGroup[] {
  const out: AlertGroup[] = [];
  for (const a of items) {
    const prev = out[out.length - 1];
    if (prev && prev.item.kind === a.kind && prev.item.title === a.title && prev.item.body === a.body) {
      prev.count += 1;
      prev.firstTs = a.ts;
    } else {
      out.push({ item: a, count: 1, firstTs: a.ts });
    }
  }
  return out;
}
