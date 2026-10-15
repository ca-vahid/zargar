import type { Point } from '@/lib/chart';
import { marketClock, span as spanText } from '@/lib/market';
import { clip, monthGrid, rangeStats, rangeWords, spanChip, spanFor, spanLabel, spanOfDays, startOfDay, sumSeries } from '@/lib/range';

const DAY = 24 * 3600e3;
const now = new Date(2026, 9, 13, 11, 0).getTime(); // Tue Oct 13 2026, local

describe('chart ranges', () => {
  it('opens each preset window the right distance back', () => {
    expect(spanFor('1W', now)).toEqual({ from: now - 7 * DAY, to: null });
    expect(spanFor('YTD', now).from).toBe(new Date(2026, 0, 1).getTime());
    expect(spanFor('All', now)).toEqual({ from: null, to: null });
    expect(spanFor('Custom', now, { from: 5, to: 9 })).toEqual({ from: 5, to: 9 });
  });
  it('turns two picked days into whole days, in either order, open-ended when it ends today', () => {
    const a = new Date(2026, 9, 1, 15).getTime();
    const b = new Date(2026, 9, 10, 9).getTime();
    const past = spanOfDays(b, a, now);
    expect(past.from).toBe(new Date(2026, 9, 1).getTime());
    expect(past.to).toBe(new Date(2026, 9, 10, 23, 59, 59, 999).getTime());
    expect(spanOfDays(a, now, now).to).toBeNull();
    expect(spanLabel(past, now)).toBe('Oct 1 – Oct 10');
    expect(spanLabel(spanOfDays(a, now, now), now)).toBe('Oct 1 – now');
    expect(spanChip(past, now)).toBe('Oct 1–10');
    expect(spanChip(spanOfDays(new Date(2026, 8, 28).getTime(), b, now), now)).toBe('Sep 28–Oct 10');
    expect(spanChip(spanOfDays(a, now, now), now)).toBe('Oct 1–now');
  });
  it('names the period after the change figure', () => {
    expect(rangeWords('1D', spanFor('1D', now), now)).toBe('today');
    expect(rangeWords('3M', spanFor('3M', now), now)).toBe('past 3 months');
    expect(rangeWords('All', spanFor('All', now), now, new Date(2025, 7, 20).getTime())).toBe('since Aug 20, 2025');
  });
  it('measures a window from its first record, or from the anchor it is given', () => {
    const pts: Point[] = [[1, 100], [2, 90], [3, 130], [4, 120]];
    expect(rangeStats(pts)).toMatchObject({ start: 100, end: 120, change: 20, pct: 20, high: 130, low: 90 });
    expect(rangeStats(pts, 80)).toMatchObject({ start: 80, change: 40, pct: 50 });
    expect(rangeStats([])).toBeNull();
  });
  it('cuts a curve to a span that ends in the past', () => {
    const pts: Point[] = [[1, 1], [5, 2], [9, 3], [12, 4]];
    expect(clip(pts, { from: 5, to: 9 })).toEqual([[5, 2], [9, 3]]);
    expect(clip(pts, { from: null, to: null })).toBe(pts);
  });
  it('adds curves sampled at different times, each holding its last value', () => {
    const a: Point[] = [[10, 100], [30, 110]];
    const b: Point[] = [[20, 50], [40, 40]];
    expect(sumSeries([a, b])).toEqual([[10, 150], [20, 150], [30, 160], [40, 150]]);
    expect(sumSeries([a, []])).toBe(a);
    expect(sumSeries([])).toEqual([]);
  });
  it('lays a month out in weeks starting on Sunday', () => {
    const oct = monthGrid(2026, 9); // Oct 1 2026 is a Thursday
    expect(oct[0]).toEqual([null, null, null, null, 1, 2, 3]);
    expect(oct.flat().filter((d) => d != null)).toHaveLength(31);
    expect(oct.every((w) => w.length === 7)).toBe(true);
    expect(startOfDay(now)).toBe(new Date(2026, 9, 13).getTime());
  });
});

describe('market clock', () => {
  const at = (weekday: number, h: number, m = 0) => ({ weekday, minutes: h * 60 + m });
  it('counts down to the close and to the open', () => {
    expect(marketClock(at(2, 13, 46))).toEqual({ state: 'open', title: 'Market open', detail: 'closes in 2 h 14 min' });
    expect(marketClock(at(2, 9, 0))).toMatchObject({ state: 'pre', detail: 'opens in 30 min' });
    expect(marketClock(at(2, 3, 30))).toMatchObject({ state: 'closed', detail: 'opens in 6 h' });
  });
  it('says when the next session is after the close and at the weekend', () => {
    expect(marketClock(at(2, 17))).toMatchObject({ state: 'post', detail: 'opens tomorrow 9:30 ET' });
    expect(marketClock(at(5, 21))).toMatchObject({ state: 'closed', detail: 'opens Monday 9:30 ET' });
    expect(marketClock(at(6, 12))).toMatchObject({ state: 'closed', detail: 'opens Monday 9:30 ET' });
    expect(marketClock(at(0, 12))).toMatchObject({ state: 'closed', detail: 'opens Monday 9:30 ET' });
  });
  it('believes the price feed on a holiday, and admits when it cannot tell the time', () => {
    expect(marketClock(at(4, 11), 'closed')).toMatchObject({ state: 'closed', title: 'Market closed' });
    expect(marketClock(null).state).toBe('closed');
    expect(spanText(59)).toBe('59 min');
    expect(spanText(120)).toBe('2 h');
  });
});
