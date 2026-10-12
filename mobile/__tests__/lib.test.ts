import { dayMove, dayMovePct, groupOf, visibleBooks } from '@/lib/books';
import { areaPath, decimate, extent, indexAt, linePath, type Point, tickLabel, ticks, xAt, yAt } from '@/lib/chart';
import { ago, money, pct, price, qty, signedMoney, sourceLabel, titleCase, tone, until } from '@/lib/format';
import { routeForWebPath } from '@/lib/links';

describe('format', () => {
  it('writes money with grouping, sign and currency', () => {
    expect(money(6923.16)).toBe('$6,923.16');
    expect(money(-12.5)).toBe('−$12.50');
    expect(money(1234567.891, 'CAD')).toBe('C$1,234,567.89');
    expect(money(null)).toBe('—');
    expect(money(NaN)).toBe('—');
  });
  it('always signs a gain or loss', () => {
    expect(signedMoney(5.17)).toBe('+$5.17');
    expect(signedMoney(-28.24)).toBe('−$28.24');
    expect(signedMoney(0)).toBe('$0.00');
    expect(pct(0.79)).toBe('+0.79%');
    expect(pct(-8.49)).toBe('−8.49%');
    expect(pct(undefined)).toBe('—');
  });
  it('shows sub-dollar prices with four decimals', () => {
    expect(price(101.4199)).toBe('101.42');
    expect(price(0.3825)).toBe('0.3825');
    expect(price(1234.5)).toBe('1,234.50');
    expect(price(null)).toBe('—');
  });
  it('keeps whole share counts whole', () => {
    expect(qty(103)).toBe('103');
    expect(qty(1500)).toBe('1,500');
    expect(qty(0.5)).toBe('0.50');
  });
  it('picks the colour from the sign, treating dust as flat', () => {
    expect(tone(3)).toBe(1);
    expect(tone(-3)).toBe(-1);
    expect(tone(0.001)).toBe(0);
    expect(tone(null)).toBe(0);
  });
  it('reads epoch seconds, epoch milliseconds and ISO strings alike', () => {
    const now = Date.parse('2026-10-12T15:00:00Z');
    expect(ago(now - 30_000, now)).toBe('just now');
    expect(ago((now - 5 * 60_000) / 1000, now)).toBe('5 min ago');
    expect(ago('2026-10-12T12:00:00Z', now)).toBe('3 h ago');
    expect(ago('2026-10-10T15:00:00Z', now)).toBe('2 d ago');
    expect(ago(null, now)).toBe('');
  });
  it('counts down an approval card and says when it has expired', () => {
    const now = Date.parse('2026-10-12T15:00:00Z');
    expect(until('2026-10-12T15:42:00Z', now)).toBe('42 min left');
    expect(until('2026-10-12T17:05:00Z', now)).toBe('2 h 5 min left');
    expect(until('2026-10-12T14:59:00Z', now)).toBe('expired');
  });
  it('cleans labels', () => {
    expect(sourceLabel('🌟｜jon-and-kian')).toBe('jon-and-kian');
    expect(sourceLabel('plain')).toBe('plain');
    expect(titleCase('verification_failed')).toBe('Verification failed');
  });
});

describe('chart geometry', () => {
  const frame = { width: 300, height: 100, left: 10, right: 40, top: 10, bottom: 10 };
  it('keeps the true high and low when thinning', () => {
    const pts: Point[] = Array.from({ length: 5000 }, (_, i) => [i, Math.sin(i / 50) * 10]);
    pts[1234] = [1234, 999];
    pts[4321] = [4321, -999];
    const out = decimate(pts, 300);
    expect(out.length).toBeLessThanOrEqual(302);
    expect(Math.max(...out.map((p) => p[1]))).toBe(999);
    expect(Math.min(...out.map((p) => p[1]))).toBe(-999);
    expect(out[0]).toBe(pts[0]);
    expect(out[out.length - 1]).toBe(pts[pts.length - 1]);
    // time never runs backwards
    for (let i = 1; i < out.length; i++) expect(out[i][0]).toBeGreaterThanOrEqual(out[i - 1][0]);
  });
  it('leaves a short series alone', () => {
    const pts: Point[] = [[1, 1], [2, 2], [3, 3]];
    expect(decimate(pts, 300)).toBe(pts);
  });
  it('gives a flat series a visible band and includes reference levels', () => {
    const flat = extent([100, 100, 100]);
    expect(flat.max).toBeGreaterThan(100);
    expect(flat.min).toBeLessThan(100);
    const withStop = extent([100, 110], [90]);
    expect(withStop.min).toBeLessThan(90);
    expect(extent([])).toEqual({ min: 0, max: 1 });
  });
  it('maps values and positions into the frame and back', () => {
    const e = { min: 0, max: 100 };
    expect(yAt(100, e, frame)).toBe(10);
    expect(yAt(0, e, frame)).toBe(90);
    expect(xAt(0, 11, frame)).toBe(10);
    expect(xAt(10, 11, frame)).toBe(260);
    expect(indexAt(135, 11, frame)).toBe(5);
    expect(indexAt(-50, 11, frame)).toBe(0);
    expect(indexAt(999, 11, frame)).toBe(10);
  });
  it('builds a line and a closed area', () => {
    const e = { min: 0, max: 100 };
    expect(linePath([0, 100], e, frame)).toBe('M10.0,90.0L260.0,10.0');
    expect(areaPath([0, 100], e, frame).endsWith('Z')).toBe(true);
    expect(areaPath([], e, frame)).toBe('');
  });
  it('chooses round scale numbers inside the range', () => {
    const t = ticks({ min: 6890, max: 6960 }, 3);
    expect(t.length).toBeGreaterThanOrEqual(2);
    for (const v of t) {
      expect(v).toBeGreaterThanOrEqual(6890);
      expect(v).toBeLessThanOrEqual(6960);
      expect(v % 10).toBe(0);
    }
    expect(tickLabel(6900)).toBe('6900');
    expect(tickLabel(39695)).toBe('39.7k');
    expect(tickLabel(6.43)).toBe('6.43');
  });
});

describe('books', () => {
  const mk = (id: string, kind: any, extra: any = {}) => ({ id, name: id, kind, cash: 100, equity: 100, startingCash: 0, ...extra });
  it('never mixes real money, paper, practice and research', () => {
    expect(groupOf(mk('a', 'live'))).toBe('real');
    expect(groupOf(mk('a', 'paper'))).toBe('paper');
    expect(groupOf(mk('a', 'sim'))).toBe('practice');
    expect(groupOf(mk('a', 'shadow'))).toBe('research');
  });
  it('hides archived, empty and research books, real money first', () => {
    const all = [mk('zsim', 'sim'), mk('old', 'sim', { archived: true }), mk('shadow', 'shadow'), mk('paper', 'paper'), mk('real', 'live'),
      mk('unfunded', 'live', { cash: 0, equity: 0 })];
    expect(visibleBooks(all).map((b) => b.id)).toEqual(['real', 'paper', 'zsim']);
    expect(visibleBooks(all, true).map((b) => b.id)).toEqual(['real', 'paper', 'zsim', 'shadow']);
  });
  it("measures today from the server's day-start anchor only", () => {
    expect(dayMove({ equity: 6908.71, dayStart: 6923.16 })).toBeCloseTo(-14.45, 2);
    expect(dayMovePct({ equity: 6908.71, dayStart: 6923.16 })).toBeCloseTo(-0.2087, 3);
    expect(dayMove({ equity: 100, dayStart: null })).toBeNull();
    expect(dayMovePct({ equity: 100, dayStart: 0 })).toBeNull();
  });
});

describe('notification links', () => {
  it('opens the screen that shows what the web path showed', () => {
    expect(routeForWebPath('/armed/abc123')).toBe('/armed');
    expect(routeForWebPath('/inbox')).toBe('/tips');
    expect(routeForWebPath('/inbox/analyst/9')).toBe('/tips');
    expect(routeForWebPath('/dashboard')).toBe('/portfolio');
    expect(routeForWebPath('/techniques/scout/dossier')).toBe('/research');
    expect(routeForWebPath('/')).toBe('/');
    expect(routeForWebPath(null)).toBe('/');
    expect(routeForWebPath('/something-new')).toBe('/');
  });
});
