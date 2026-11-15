import {
  groupPlans, guardText, minutesToTrigger, orderLine, planStatus, preflightText, sizeText, standingCounts, type StandingOrder, waitText,
} from '../src/lib/standing';

const order = (over: Partial<StandingOrder>): StandingOrder => ({
  id: 'a', planId: 'p1', planName: 'Monday test', planArmConfirm: 'ARM p1', portfolioId: 'book', symbol: 'AAPL', side: 'BUY',
  qty: 1, budget: null, trigger: 'at', notBefore: '10:00', expiresOn: '2026-11-16', maxPrice: 367, minPrice: null,
  slippagePct: 0.5, takeProfitPct: null, stopLossPct: null, status: 'draft', note: null, lastError: null, filledQty: 0,
  avgFillPrice: null, attempts: [], armConfirm: 'ARM a', positionId: null, ...over,
});

describe('standing orders', () => {
  it('names a plan by its most urgent order', () => {
    expect(planStatus([{ status: 'done' }, { status: 'working' }])).toBe('working');
    expect(planStatus([{ status: 'draft' }, { status: 'armed' }])).toBe('armed');
    expect(planStatus([{ status: 'done' }, { status: 'failed' }])).toBe('failed');
    expect(planStatus([{ status: 'done' }, { status: 'done' }])).toBe('done');
    expect(planStatus([{ status: 'cancelled' }])).toBe('cancelled');
  });

  it('groups orders into plans in firing order and sets finished plans apart', () => {
    const g = groupPlans([
      order({ id: 'buy', notBefore: '10:00' }), order({ id: 'sell', side: 'SELL', notBefore: '09:45' }),
      order({ id: 'old', planId: 'p0', status: 'cancelled' }), order({ id: 'lone', planId: null, status: 'armed' }),
    ]);
    expect(g.open.map((p) => p.key)).toEqual(['p1', 'single:lone']);
    expect(g.open[0].rows.map((r) => r.id)).toEqual(['sell', 'buy']);
    expect(g.closed.map((p) => p.key)).toEqual(['p0']);
  });

  it('says the size, the guard and the order in plain words', () => {
    expect(sizeText({ qty: 1, budget: null })).toBe('1 share');
    expect(sizeText({ qty: null, budget: 14000 })).toBe('up to $14,000');
    expect(guardText({ side: 'BUY', maxPrice: 367, minPrice: null, symbol: 'AAPL' })).toBe('Pay at most $367.00');
    expect(guardText({ side: 'BUY', maxPrice: 56.19, minPrice: null, symbol: 'XIU.TO' })).toBe('Pay at most C$56.19');
    expect(guardText({ side: 'SELL', maxPrice: null, minPrice: 132.15, symbol: 'SPCX' })).toBe('Sell at $132.15 or better');
    expect(guardText({ side: 'BUY', maxPrice: null, minPrice: null, symbol: 'ANT' })).toBe('No price cap');
    expect(orderLine(order({ side: 'SELL', symbol: 'SPCX', qty: 2 }))).toBe('Sell 2 shares of SPCX');
  });

  it('counts the minutes to the next trigger in New York time, skipping the weekend', () => {
    const at10 = { trigger: 'at', notBefore: '10:00' };
    expect(minutesToTrigger(at10, { weekday: 1, minutes: 9 * 60 })).toBe(60);            // Monday 09:00
    expect(minutesToTrigger(at10, { weekday: 1, minutes: 11 * 60 })).toBe(0);            // window already open
    expect(minutesToTrigger(at10, { weekday: 1, minutes: 17 * 60 })).toBe(17 * 60);      // after the close: tomorrow
    expect(minutesToTrigger(at10, { weekday: 5, minutes: 17 * 60 })).toBe(3 * 1440 - 7 * 60); // Friday evening: Monday
    expect(minutesToTrigger(at10, { weekday: 0, minutes: 16 * 60 + 37 })).toBe(1440 - 6 * 60 - 37); // Sunday
    expect(minutesToTrigger({ trigger: 'now', notBefore: null }, { weekday: 6, minutes: 0 })).toBe(2 * 1440 + 570);
    expect(minutesToTrigger({ trigger: 'at', notBefore: '08:00' }, { weekday: 2, minutes: 7 * 60 })).toBe(150); // never before the open
    expect(minutesToTrigger({ trigger: 'listing', notBefore: null }, { weekday: 1, minutes: 600 })).toBeNull();
    expect(minutesToTrigger(at10, null)).toBeNull();
  });

  it('words a wait', () => {
    expect(waitText(0)).toBe('window open now');
    expect(waitText(42)).toBe('in 42 min');
    expect(waitText(120)).toBe('in 2 h');
    expect(waitText(1043)).toBe('in 17 h 23 min');
    expect(waitText(2 * 1440 + 90)).toBe('in 2 d 1 h');
  });

  it('counts what is open and what failed', () => {
    const c = standingCounts([order({ status: 'draft' }), order({ status: 'armed' }), order({ status: 'working' }),
      order({ status: 'failed' }), order({ status: 'done' })]);
    expect(c).toEqual({ draft: 1, armed: 1, working: 1, failed: 1, open: 3 });
  });

  it('reads a dry-run result', () => {
    expect(preflightText({ ok: true, qty: 1, limit: 55.1, notional: 55.1 })).toBe('Would send 1 at 55.1 (55.1 in all)');
    expect(preflightText({ ok: false, why: 'market closed' })).toBe('market closed');
    expect(preflightText({ ok: false, failedChecks: [{ name: 'max_position_pct', detail: 'over 50% of the book' }] })).toBe('over 50% of the book');
  });
});
