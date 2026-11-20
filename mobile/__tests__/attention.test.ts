import type { DeskQuestion } from '../src/api/endpoints';
import { newYorkDate } from '../src/lib/market';
import {
  armedByText, dayLabel, minutesToTrigger, orderLine, sizeText, standingCounts, type StandingOrder, whenText, withStale,
} from '../src/lib/standing';
import { attentionKeys, attentionOf } from '../src/live/attention';
import { attentionCount } from '../src/store';

const order = (over: Partial<StandingOrder>): StandingOrder => ({
  id: 'a', planId: 'p1', planName: 'Plan', planArmConfirm: 'ARM p1', portfolioId: 'real', symbol: 'ANT', side: 'BUY',
  qty: null, budget: null, trigger: 'listing', notBefore: null, expiresOn: '2026-11-19', maxPrice: null, minPrice: null,
  slippagePct: 1, takeProfitPct: 10, stopLossPct: 10, status: 'draft', note: null, lastError: null, filledQty: 0,
  avgFillPrice: null, attempts: [], armConfirm: 'ARM a', positionId: null, ...over,
});
const question = (over: Partial<DeskQuestion>): DeskQuestion => ({
  id: 'q1', text: 'Convert or skip?', detail: null, options: ['Convert', 'Skip'], status: 'open', askedBy: 'claude', url: null,
  answer: null, answeredVia: null, answeredAt: null, expiresAt: null, createdAt: '2026-11-18T15:00:00Z', ...over,
});
const kindOf = (pid: string) => (pid === 'real' ? 'live' : 'sim');

describe('what needs the person', () => {
  it('counts open questions, drafts and failures per workspace', () => {
    const a = attentionOf(
      [question({}), question({ id: 'q2', status: 'answered' })],
      [order({}), order({ id: 'b', status: 'failed' }), order({ id: 'c', portfolioId: 'sim1' }), order({ id: 'd', status: 'armed' })],
      kindOf, '2026-11-18');
    expect(a.questions.map((q) => q.id)).toEqual(['q1']);
    expect(a.drafts).toEqual({ live: 1, practice: 1 });
    expect(a.failed).toEqual({ live: 1, practice: 0 });
    expect(attentionCount(a)).toBe(4);
  });
  it('lets a draft or a failure go once its last day has passed', () => {
    const old = [order({ expiresOn: '2026-11-16' }), order({ id: 'b', status: 'failed', expiresOn: '2026-11-16' })];
    expect(attentionCount(attentionOf([], old, kindOf, '2026-11-18'))).toBe(0);
    expect(withStale(old, '2026-11-18').map((o) => o.status)).toEqual(['expired', 'failed-old']);
    expect(standingCounts(withStale(old, '2026-11-18'))).toEqual({ draft: 0, armed: 0, working: 0, failed: 0, open: 0 });
    expect(withStale(old, null).map((o) => o.status)).toEqual(['draft', 'failed']); // unknown date: nothing is hidden
  });
  it('keys one alert per question, per plan to arm and per failed order', () => {
    const keys = attentionKeys([question({})], [order({}), order({ id: 'b' }), order({ id: 'c', status: 'failed' })], '2026-11-18');
    expect(keys.sort()).toEqual(['draft:p1', 'failed:c', 'q:q1']);
  });
});

describe('the newer order fields', () => {
  it('words a spend-all buy and a start date', () => {
    expect(sizeText({ qty: null, budget: null, spendAll: true })).toBe('all the cash in the account');
    expect(orderLine(order({ spendAll: true }))).toBe('Buy ANT with all the cash in the account');
    expect(dayLabel('2026-11-19')).toBe('Thu Nov 19');
    expect(whenText({ trigger: 'listing', notBefore: null, startsOn: '2026-11-19' })).toBe('Thu Nov 19 · when it starts trading');
    expect(whenText({ trigger: 'at', notBefore: '09:30', startsOn: null })).toBe('From 09:30 ET');
    expect(whenText({ trigger: 'now', notBefore: null })).toBe('At the next open');
  });
  it('waits for the start date', () => {
    const sell = { trigger: 'now', notBefore: null, startsOn: '2026-11-19' };
    expect(minutesToTrigger(sell, { weekday: 3, minutes: 10 * 60 }, '2026-11-18')).toBe(1440 - 30); // Wed 10:00 -> Thu 09:30
    expect(minutesToTrigger(sell, { weekday: 4, minutes: 9 * 60 }, '2026-11-19')).toBe(30);
  });
  it('says who armed it when it was not the person', () => {
    expect(armedByText({ armedBy: 'user' })).toBeNull();
    expect(armedByText({})).toBeNull();
    expect(armedByText({ armedBy: 'claude:delegation:abc' })).toMatch(/delegation/);
    expect(armedByText({ armedBy: 'claude:repair:abc' })).toMatch(/original go-ahead/);
  });
  it('reads the New York date', () => {
    expect(newYorkDate(Date.UTC(2026, 10, 19, 3, 0))).toBe('2026-11-18'); // 22:00 ET the evening before
    expect(newYorkDate(Date.UTC(2026, 10, 19, 15, 0))).toBe('2026-11-19');
  });
});
