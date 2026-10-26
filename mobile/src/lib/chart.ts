// Chart geometry. Pure functions so the maths is tested without a renderer.

export type Point = [number, number]; // [time ms, value]

/** Thin a series to about `max` points, keeping every bucket's low AND high.
 *  Taking every Nth sample makes the same window report a different high
 *  depending on where the buckets fall (the web app's rule, PLATFORM-RULES 23). */
export function decimate(points: Point[], max: number): Point[] {
  if (points.length <= max || max < 4) return points;
  const buckets = Math.floor(max / 2);
  const size = points.length / buckets;
  const out: Point[] = [];
  for (let b = 0; b < buckets; b++) {
    const start = Math.floor(b * size);
    const end = Math.min(points.length, Math.floor((b + 1) * size));
    if (end <= start) continue;
    let lo = start;
    let hi = start;
    for (let i = start + 1; i < end; i++) {
      if (points[i][1] < points[lo][1]) lo = i;
      if (points[i][1] > points[hi][1]) hi = i;
    }
    if (lo === hi) out.push(points[lo]);
    else if (lo < hi) out.push(points[lo], points[hi]);
    else out.push(points[hi], points[lo]);
  }
  const last = points[points.length - 1];
  if (out[out.length - 1] !== last) out.push(last);
  if (out[0] !== points[0]) out.unshift(points[0]);
  return out;
}

export interface Extent { min: number; max: number }

/** Value range with breathing room; a flat series still gets a visible band. */
export function extent(values: number[], extra: number[] = [], padFrac = 0.08): Extent {
  let min = Infinity;
  let max = -Infinity;
  for (const v of values) if (Number.isFinite(v)) { if (v < min) min = v; if (v > max) max = v; }
  for (const v of extra) if (Number.isFinite(v)) { if (v < min) min = v; if (v > max) max = v; }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { min: 0, max: 1 };
  if (max - min < 1e-9) {
    const band = Math.abs(max) * 0.01 || 1;
    return { min: min - band, max: max + band };
  }
  const padBy = (max - min) * padFrac;
  return { min: min - padBy, max: max + padBy };
}

export interface Frame { width: number; height: number; left: number; right: number; top: number; bottom: number }

/** Evenly spaced x: nights and weekends take no room, as on a broker's chart. */
export function xAt(i: number, n: number, f: Frame): number {
  const w = f.width - f.left - f.right;
  return n <= 1 ? f.left + w / 2 : f.left + (i / (n - 1)) * w;
}

export function yAt(v: number, e: Extent, f: Frame): number {
  const h = f.height - f.top - f.bottom;
  return f.top + (1 - (v - e.min) / (e.max - e.min)) * h;
}

/** The sample under a finger at horizontal position `x`. */
export function indexAt(x: number, n: number, f: Frame): number {
  if (n <= 1) return 0;
  const w = f.width - f.left - f.right;
  const i = Math.round(((x - f.left) / w) * (n - 1));
  return Math.max(0, Math.min(n - 1, i));
}

export function linePath(values: number[], e: Extent, f: Frame): string {
  let d = '';
  for (let i = 0; i < values.length; i++) {
    d += `${i === 0 ? 'M' : 'L'}${xAt(i, values.length, f).toFixed(1)},${yAt(values[i], e, f).toFixed(1)}`;
  }
  return d;
}

export function areaPath(values: number[], e: Extent, f: Frame): string {
  if (!values.length) return '';
  const base = (f.height - f.bottom).toFixed(1);
  return `${linePath(values, e, f)}L${xAt(values.length - 1, values.length, f).toFixed(1)},${base}L${xAt(0, values.length, f).toFixed(1)},${base}Z`;
}

/** Three or four round numbers across a range, for the right-hand scale. */
export function ticks(e: Extent, count = 4): number[] {
  const span = e.max - e.min;
  if (!(span > 0)) return [e.min];
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 5 ? 5 : norm >= 2 ? 2 : 1) * mag;
  const out: number[] = [];
  for (let v = Math.ceil(e.min / step) * step; v <= e.max + 1e-9; v += step) out.push(Number(v.toFixed(10)));
  return out;
}

export function tickLabel(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e4) return `${(v / 1e3).toFixed(1)}k`;
  if (a >= 100) return v.toFixed(0);
  if (a >= 1) return v.toFixed(2);
  return v.toFixed(3);
}
