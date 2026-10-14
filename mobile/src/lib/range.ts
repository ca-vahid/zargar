// Time windows for the equity chart, and what a curve says over one. Pure functions.
import type { Point } from './chart';

export type RangeKey = '1D' | '1W' | '1M' | '3M' | 'YTD' | '1Y' | 'All' | 'Custom';
export const RANGE_KEYS: RangeKey[] = ['1D', '1W', '1M', '3M', 'YTD', '1Y', 'All', 'Custom'];

/** `from` null = from the first record; `to` null = up to now (the live value). */
export interface Span { from: number | null; to: number | null }

const DAY = 24 * 3600e3;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export const startOfDay = (ms: number) => { const d = new Date(ms); d.setHours(0, 0, 0, 0); return d.getTime(); };
export const endOfDay = (ms: number) => { const d = new Date(ms); d.setHours(23, 59, 59, 999); return d.getTime(); };

export function spanFor(key: RangeKey, now: number, custom?: Span | null): Span {
  switch (key) {
    case '1D': return { from: now - DAY, to: null };
    case '1W': return { from: now - 7 * DAY, to: null };
    case '1M': return { from: now - 31 * DAY, to: null };
    case '3M': return { from: now - 92 * DAY, to: null };
    case 'YTD': return { from: new Date(new Date(now).getFullYear(), 0, 1).getTime(), to: null };
    case '1Y': return { from: now - 365 * DAY, to: null };
    case 'Custom': return custom ?? { from: now - 7 * DAY, to: null };
    default: return { from: null, to: null };
  }
}

/** A custom span from two picked days; an end of today (or later) means "up to now". */
export function spanOfDays(a: number, b: number, now: number): Span {
  const lo = Math.min(a, b);
  const hi = Math.max(a, b);
  return { from: startOfDay(lo), to: startOfDay(hi) >= startOfDay(now) ? null : endOfDay(hi) };
}

function day(ms: number, now: number): string {
  const d = new Date(ms);
  const sameYear = d.getFullYear() === new Date(now).getFullYear();
  return `${MONTHS[d.getMonth()]} ${d.getDate()}${sameYear ? '' : `, ${d.getFullYear()}`}`;
}

/** "Oct 1 – Oct 10" for a custom span. */
export function spanLabel(span: Span, now: number): string {
  if (span.from == null) return 'all time';
  return `${day(span.from, now)} – ${span.to == null ? 'now' : day(span.to, now)}`;
}

/** The same span as a chip label: "Oct 1–8", "Sep 28–Oct 8", "Oct 1–now". */
export function spanChip(span: Span, now: number): string {
  if (span.from == null) return 'All';
  const a = new Date(span.from);
  if (span.to == null) return `${MONTHS[a.getMonth()]} ${a.getDate()}–now`;
  const b = new Date(span.to);
  return a.getMonth() === b.getMonth() && a.getFullYear() === b.getFullYear()
    ? `${MONTHS[a.getMonth()]} ${a.getDate()}–${b.getDate()}`
    : `${day(span.from, now)}–${day(span.to, now)}`;
}

/** The words after the change figure: "+$12.40 +0.3% past week". */
export function rangeWords(key: RangeKey, span: Span, now: number, firstTs?: number | null): string {
  switch (key) {
    case '1D': return 'today';
    case '1W': return 'past week';
    case '1M': return 'past month';
    case '3M': return 'past 3 months';
    case 'YTD': return 'this year';
    case '1Y': return 'past year';
    case 'Custom': return spanLabel(span, now);
    default: return firstTs ? `since ${day(firstTs, now)}` : 'all time';
  }
}

/** Keep the points inside a span (the server only cuts the start). */
export function clip(points: Point[], span: Span): Point[] {
  if (span.from == null && span.to == null) return points;
  return points.filter(([ts]) => (span.from == null || ts >= span.from) && (span.to == null || ts <= span.to));
}

export interface RangeStats { start: number; end: number; change: number; pct: number | null; high: number; low: number; firstTs: number; lastTs: number }

/** What a curve did over its window. `base` overrides the starting value: the day view
 *  measures from the server's day-start anchor, never from the first sample drawn. */
export function rangeStats(points: Point[], base?: number | null): RangeStats | null {
  if (!points.length) return null;
  const start = base ?? points[0][1];
  const end = points[points.length - 1][1];
  let high = -Infinity;
  let low = Infinity;
  for (const [, v] of points) { if (v > high) high = v; if (v < low) low = v; }
  const change = end - start;
  return { start, end, change, pct: start ? (change / Math.abs(start)) * 100 : null, high, low,
    firstTs: points[0][0], lastTs: points[points.length - 1][0] };
}

/** Add several curves sampled at different times into one: each curve holds its last
 *  value between its own samples (and its first value before it starts). */
export function sumSeries(list: Point[][]): Point[] {
  const curves = list.filter((c) => c.length > 0);
  if (curves.length === 0) return [];
  if (curves.length === 1) return curves[0];
  const stamps = [...new Set(curves.flatMap((c) => c.map((p) => p[0])))].sort((a, b) => a - b);
  const at = curves.map(() => 0);
  return stamps.map((ts) => {
    let total = 0;
    curves.forEach((c, i) => {
      while (at[i] + 1 < c.length && c[at[i] + 1][0] <= ts) at[i]++;
      total += c[at[i]][1];
    });
    return [ts, total] as Point;
  });
}

/** A month as weeks of day numbers, Sunday first; null pads the first and last week. */
export function monthGrid(year: number, month: number): (number | null)[][] {
  const first = new Date(year, month, 1).getDay();
  const count = new Date(year, month + 1, 0).getDate();
  const cells: (number | null)[] = [...Array(first).fill(null), ...Array.from({ length: count }, (_, i) => i + 1)];
  while (cells.length % 7) cells.push(null);
  const weeks: (number | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

export const monthName = (month: number) => MONTHS[month];
