import type { AlertItem } from '../src/api/endpoints';
import type { BrokerState, Portfolio } from '../src/api/types';
import { brokerCash, withBrokerCash } from '../src/hooks/useBooks';
import { alertLabel, foldAlerts } from '../src/lib/alerts';
import { liftEmptyCurve, visibleBooks } from '../src/lib/books';
import { routeForWebPath } from '../src/lib/links';

const book = (over: Partial<Portfolio>): Portfolio =>
  ({ id: 'ib', name: 'Live (IBKR)', kind: 'live', cash: 0, equity: 0, startingCash: 0, baseCurrency: 'USD', venue: 'ibkr', ...over });
const broker = (cash: Record<string, number>, portfolioId = 'ib'): BrokerState =>
  ({ feed: 'x', feedConnected: true, mode: 'live', ibkr: { portfolioId, account: 'U1', syncedAt: '', bookCurrency: 'USD', cashByCurrency: cash, spendable: 0 } });

describe('an IBKR account whose book has no cash on record yet', () => {
  it('takes the cash the broker reports, converted into the book currency', () => {
    expect(brokerCash(book({}), broker({ CAD: 3000 }), 1.5)).toBeCloseTo(2000);
    expect(brokerCash(book({}), broker({ CAD: 3000, USD: 100 }), 1.5)).toBeCloseTo(2100);
  });
  it('adds nothing without a rate, for another book, or once the book has its own cash', () => {
    expect(brokerCash(book({}), broker({ CAD: 3000 }), null)).toBeNull();
    expect(brokerCash(book({ id: 'other' }), broker({ CAD: 3000 }), 1.5)).toBeNull();
    expect(brokerCash(book({ cash: 250 }), broker({ CAD: 3000 }), 1.5)).toBeNull();
    expect(brokerCash(book({}), broker({}), 1.5)).toBeNull();
    expect(brokerCash(book({}), null, 1.5)).toBeNull();
  });
  it('keeps the account in the Live lists instead of dropping it as empty', () => {
    const all = [book({})];
    expect(visibleBooks(all, 'live')).toHaveLength(0);
    const seen = visibleBooks(withBrokerCash(all, broker({ CAD: 3000 }), 1.5), 'live');
    expect(seen).toHaveLength(1);
    expect(seen[0].equity).toBeCloseTo(2000);
    expect(seen[0].dayStart).toBeCloseTo(2000); // cash: no move today
  });
  it('holds an all-zero curve at what the book is worth', () => {
    expect(liftEmptyCurve([[1, 0], [2, 0]], 2000)).toEqual([[1, 2000], [2, 2000]]);
    expect(liftEmptyCurve([[1, 0], [2, 1990], [3, 0]], 2000)).toEqual([[2, 1990], [3, 0]]);
    expect(liftEmptyCurve([[1, 0]], 0)).toEqual([[1, 0]]);
  });
});

const alert = (over: Partial<AlertItem>): AlertItem =>
  ({ id: String(Math.random()), ts: '2026-11-15T07:45:00Z', kind: 'BrokerDisconnected', level: 'error', title: 'Broker disconnected: ibkr', body: '', ...over });

describe('alerts', () => {
  it('folds a run of the same alert into one row with a count', () => {
    const g = foldAlerts([
      alert({ ts: '3' }), alert({ ts: '2' }), alert({ ts: '1' }),
      alert({ kind: 'TechniquePlanError', title: 'INTC: armed plan alert', body: 'stale bars', ts: '0' }),
      alert({ ts: '-1' }),
    ]);
    expect(g.map((x) => x.count)).toEqual([3, 1, 1]);
    expect(g[0].item.ts).toBe('3');
    expect(g[0].firstTs).toBe('1');
  });
  it('names a kind in plain words', () => {
    expect(alertLabel({ kind: 'TechniquePlanError', level: 'warning' })).toBe('Plan alert');
    expect(alertLabel({ kind: 'BrokerDisconnected', level: 'error' })).toBe('Broker link');
    expect(alertLabel({ kind: 'alert', level: 'error' })).toBe('Problem');
    expect(alertLabel({ kind: 'TipIntakeStalled', level: 'error' })).toBe('Tip intake stalled');
  });
  it('opens the standing orders screen from its notification', () => {
    expect(routeForWebPath('/standing')).toBe('/orders?tab=standing');
  });
});
